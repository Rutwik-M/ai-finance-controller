import os
import sys
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

def load_data(data_dir):
    db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgrespassword@localhost:5432/settlement_reconciliation")
    print(f"Connecting to database: {db_url}")
    
    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        cur = conn.cursor()
    except Exception as e:
        print(f"Failed to connect to DB: {e}")
        sys.exit(1)

    # 1. Load Razorpay
    rp_path = os.path.join(data_dir, "razorpay.csv")
    if os.path.exists(rp_path):
        print("Loading Razorpay...")
        rp_df = pd.read_csv(rp_path)
        rp_records = []
        for _, row in rp_df.iterrows():
            rp_records.append((
                "razorpay", 
                str(row["settlement_id"]), 
                str(row["payment_id"]) if pd.notna(row["payment_id"]) else None,
                str(row["order_id"]) if pd.notna(row["order_id"]) else None,
                float(row["net_amount"]), 
                row["settled_at"], 
                str(row["utr"]) if pd.notna(row["utr"]) else None
            ))
        insert_records(cur, rp_records)
    
    # 2. Load Bank
    bk_path = os.path.join(data_dir, "bank.csv")
    if os.path.exists(bk_path):
        print("Loading Bank...")
        bk_df = pd.read_csv(bk_path)
        bk_records = []
        for _, row in bk_df.iterrows():
            bk_records.append((
                "bank", 
                str(row["txn_ref"]), 
                None, 
                None, 
                float(row["amount"]), 
                row["value_date"], 
                str(row["narration"]) if pd.notna(row["narration"]) else None
            ))
        insert_records(cur, bk_records)

    # 3. Load Ledger
    lg_path = os.path.join(data_dir, "ledger.csv")
    if os.path.exists(lg_path):
        print("Loading Ledger...")
        lg_df = pd.read_csv(lg_path)
        lg_records = []
        for _, row in lg_df.iterrows():
            lg_records.append((
                "ledger", 
                str(row["order_id"]), 
                str(row["payment_id"]) if pd.notna(row["payment_id"]) else None,
                str(row["order_id"]) if pd.notna(row["order_id"]) else None,
                float(row["expected_amount"]), 
                row["created_at"], 
                None
            ))
        insert_records(cur, lg_records)

    cur.close()
    conn.close()
    print("Ingestion complete.")

def insert_records(cur, records):
    if not records:
        return
    query = """
        INSERT INTO records (source, external_id, payment_id, order_id, amount, reference_date, raw_reference)
        VALUES %s
        ON CONFLICT (source, external_id) DO NOTHING
    """
    execute_values(cur, query, records)
    print(f"Inserted/Processed {len(records)} records.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m src.ingestion.load <data_dir>")
        sys.exit(1)
    
    data_dir = sys.argv[1]
    load_data(data_dir)
