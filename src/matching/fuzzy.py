import os
import psycopg2
import pandas as pd
from rapidfuzz import fuzz
from psycopg2.extras import execute_values

def run_fuzzy_matching():
    db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgrespassword@localhost:5432/settlement_reconciliation")
    
    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        cur = conn.cursor()
    except Exception as e:
        print(f"Failed to connect to DB: {e}")
        return []

    # 1. Candidate Generation (SQL Join)
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
            l.id AS l_id, l.amount AS l_amount, l.reference_date AS l_date, l.raw_reference AS l_ref,
            b.id AS b_id, b.amount AS b_amount, b.reference_date AS b_date, b.raw_reference AS b_ref
        FROM r
        JOIN l ON r.order_id = l.order_id OR r.payment_id = l.payment_id
        JOIN b ON (
            (b.amount BETWEEN r.amount - 5 AND r.amount + 5)
            OR (b.reference_date BETWEEN r.reference_date - INTERVAL '3 days' AND r.reference_date + INTERVAL '3 days')
        )
    """
    
    cur.execute(query)
    columns = [desc[0] for desc in cur.description]
    rows = cur.fetchall()
    
    if not rows:
        print("No fuzzy candidate triplets found.")
        cur.close()
        conn.close()
        return []
        
    df = pd.DataFrame(rows, columns=columns)
    
    # 2. Rule Evaluation
    def calculate_score(row):
        # Amount score
        amt_diff = abs(row['r_amount'] - row['b_amount'])
        if amt_diff < 0.01:
            amt_score = 1.0
        elif amt_diff <= 2.0:
            amt_score = 0.8
        else:
            amt_score = 0.0
            
        # Date score
        date_diff = abs((row['r_date'] - row['b_date']).days)
        if date_diff == 0:
            date_score = 1.0
        elif date_diff <= 3:
            date_score = 0.7
        else:
            date_score = 0.0
            
        # Narration score
        narr_score = 0.0
        if pd.notna(row['r_ref']) and pd.notna(row['b_ref']):
            narr_score = fuzz.partial_ratio(str(row['r_ref']).lower(), str(row['b_ref']).lower()) / 100.0
            
        return (amt_score * 0.4) + (date_score * 0.3) + (narr_score * 0.3)

    df['rule_score'] = df.apply(calculate_score, axis=1)
    
    # Auto-resolve those >= 0.85
    auto_resolved = df[df['rule_score'] >= 0.85].copy()
    
    # Ensure no duplicate matches for the same record
    auto_resolved = auto_resolved.sort_values('rule_score', ascending=False)
    auto_resolved = auto_resolved.drop_duplicates(subset=['r_id'])
    auto_resolved = auto_resolved.drop_duplicates(subset=['b_id'])
    auto_resolved = auto_resolved.drop_duplicates(subset=['l_id'])
    
    if not auto_resolved.empty:
        print(f"Found {len(auto_resolved)} matches passing fuzzy threshold (>=0.85).")
        matches_data = []
        for _, row in auto_resolved.iterrows():
            matches_data.append((
                [str(row['r_id']), str(row['b_id']), str(row['l_id'])], 
                "fuzzy", 
                float(row['rule_score']), 
                "auto_resolved"
            ))
            
        args_str = ','.join(cur.mogrify("(%s::uuid[], %s, %s, %s)", x).decode("utf-8") for x in matches_data)
        cur.execute("INSERT INTO matches (record_ids, match_type, confidence, status) VALUES " + args_str + " RETURNING id;")
        match_ids = [row[0] for row in cur.fetchall()]
        
        audit_data = []
        for m_id, score in zip(match_ids, auto_resolved['rule_score']):
            audit_data.append((m_id, "auto-resolved", f"Fuzzy score {score:.2f} >= 0.85"))
            
        query_audit = """
            INSERT INTO audit_log (match_id, decision, rule_fired)
            VALUES %s
        """
        execute_values(cur, query_audit, audit_data)
        
    # Return the remaining ambiguous candidates (score >= 0.4 and < 0.85) to pass to LLM
    # We must exclude those that just got auto-resolved
    resolved_r_ids = set(auto_resolved['r_id'])
    ambiguous = df[(df['rule_score'] >= 0.4) & (df['rule_score'] < 0.85)].copy()
    ambiguous = ambiguous[~ambiguous['r_id'].isin(resolved_r_ids)]
    
    # Find Razorpay records that had no candidates or all candidates were < 0.4 score
    cur.execute("SELECT id FROM records WHERE source = 'razorpay' AND id NOT IN (SELECT unnest(record_ids) FROM matches)")
    all_unmatched_r_ids = {str(row[0]) for row in cur.fetchall()}
    
    # Records that are now resolved or ambiguous
    handled_r_ids = resolved_r_ids.union({str(r) for r in ambiguous['r_id'].unique()})
    
    # The difference is the true orphans
    orphaned_r_ids = all_unmatched_r_ids - handled_r_ids
    
    if orphaned_r_ids:
        import json
        orphan_data = [(r_id, 'no_candidates_found', json.dumps({"error": "No bank records found within fuzzy thresholds."})) for r_id in orphaned_r_ids]
        execute_values(cur, "INSERT INTO exceptions (record_id, reason, detail) VALUES %s", orphan_data)
    
    cur.close()
    conn.close()
    
    # Group by r_id so we have a list of candidate triplets for each unmatched razorpay record
    llm_candidates = []
    for r_id, group in ambiguous.groupby('r_id'):
        top_candidates = group.sort_values('rule_score', ascending=False).head(3)
        llm_candidates.append({
            'r_id': r_id,
            'r_amount': top_candidates.iloc[0]['r_amount'],
            'r_date': top_candidates.iloc[0]['r_date'],
            'r_ref': top_candidates.iloc[0]['r_ref'],
            'l_id': top_candidates.iloc[0]['l_id'],
            'candidates': top_candidates.to_dict('records')
        })
        
    return llm_candidates

if __name__ == "__main__":
    candidates = run_fuzzy_matching()
    print(f"Returned {len(candidates)} ambiguous records for LLM.")
