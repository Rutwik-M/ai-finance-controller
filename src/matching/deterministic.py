import os
import psycopg2
import pandas as pd
from psycopg2.extras import execute_values

def run_deterministic_matching():
    db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgrespassword@localhost:5432/settlement_reconciliation")
    print(f"Connecting to database: {db_url}")
    
    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        cur = conn.cursor()
    except Exception as e:
        print(f"Failed to connect to DB: {e}")
        return

    # 1. Candidate Generation (SQL Join)
    # Join Razorpay and Ledger on order_id
    # Join with Bank loosely on amount or substring match
    query = """
        WITH unmatched AS (
            SELECT * FROM records 
            WHERE id NOT IN (SELECT unnest(record_ids) FROM matches)
        ),
        r AS (SELECT * FROM unmatched WHERE source = 'razorpay'),
        l AS (SELECT * FROM unmatched WHERE source = 'ledger'),
        b AS (SELECT * FROM unmatched WHERE source = 'bank')
        SELECT 
            r.id AS r_id, r.amount AS r_amount, r.reference_date AS r_date, r.raw_reference AS r_ref,
            l.id AS l_id, 
            b.id AS b_id, b.amount AS b_amount, b.reference_date AS b_date, b.raw_reference AS b_ref
        FROM r
        JOIN l ON r.order_id = l.order_id OR r.payment_id = l.payment_id
        JOIN b ON b.amount = r.amount OR (r.raw_reference IS NOT NULL AND b.raw_reference LIKE '%' || r.raw_reference || '%')
    """
    
    cur.execute(query)
    columns = [desc[0] for desc in cur.description]
    rows = cur.fetchall()
    
    if not rows:
        print("No candidate triplets found.")
        return
        
    df = pd.DataFrame(rows, columns=columns)
    
    # 2. Rule Evaluation (Pandas)
    def check_utr_match(row):
        return pd.notna(row['r_ref']) and pd.notna(row['b_ref']) and str(row['r_ref']) in str(row['b_ref'])
        
    df['rule1'] = df.apply(check_utr_match, axis=1)
    df['rule2'] = (df['r_amount'] == df['b_amount']) & (df['r_date'] == df['b_date'])
    
    df['matched_rule'] = None
    df.loc[df['rule1'], 'matched_rule'] = 'Exact order/payment ID and UTR match'
    df.loc[df['rule2'] & df['matched_rule'].isna(), 'matched_rule'] = 'Exact order/payment ID, amount, and date match'
    
    # Filter only matched records
    matched_df = df[df['matched_rule'].notna()].copy()
    
    # Ensure no record is matched multiple times in this pass
    matched_df = matched_df.drop_duplicates(subset=['r_id'])
    matched_df = matched_df.drop_duplicates(subset=['b_id'])
    matched_df = matched_df.drop_duplicates(subset=['l_id'])
    
    if matched_df.empty:
        print("No matches passed the deterministic rules.")
        return
        
    print(f"Found {len(matched_df)} matches passing deterministic rules.")
    
    # Insert matches
    matches_data = []
    for _, row in matched_df.iterrows():
        # Postgres expects an array literal or cast for uuid[]
        # We will use mogrify to handle the array properly with casting
        matches_data.append((
            [str(row['r_id']), str(row['b_id']), str(row['l_id'])], 
            "deterministic", 
            1.0, 
            "auto_resolved"
        ))
        
    # We cast the first element %s::uuid[]
    args_str = ','.join(cur.mogrify("(%s::uuid[], %s, %s, %s)", x).decode("utf-8") for x in matches_data)
    cur.execute("INSERT INTO matches (record_ids, match_type, confidence, status) VALUES " + args_str + " RETURNING id;")
    match_ids = [row[0] for row in cur.fetchall()]
    
    audit_data = []
    for m_id, rule in zip(match_ids, matched_df['matched_rule']):
        audit_data.append((m_id, "auto-resolved", rule))
        
    query_audit = """
        INSERT INTO audit_log (match_id, decision, rule_fired)
        VALUES %s
    """
    execute_values(cur, query_audit, audit_data)
    
    cur.execute("SELECT COUNT(*) FROM records")
    total_records = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM matches WHERE match_type = 'deterministic'")
    total_matches = cur.fetchone()[0]
    
    print(f"Total records processed: {total_records}")
    print(f"Total deterministic matches created: {total_matches}")
    
    cur.close()
    conn.close()

if __name__ == "__main__":
    run_deterministic_matching()
