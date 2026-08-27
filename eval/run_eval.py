import os
import json
import psycopg2

def run_evaluation():
    db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgrespassword@localhost:5432/settlement_reconciliation")
    
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
    except Exception as e:
        print(f"Failed to connect to DB: {e}")
        return

    # 1. Load Ground Truth
    gt_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'samples', 'ground_truth.json')
    if not os.path.exists(gt_path):
        print(f"Ground truth not found at {gt_path}")
        return
        
    with open(gt_path, 'r') as f:
        ground_truth_raw = json.load(f)
        
    total_logical_transactions = len(ground_truth_raw)
    
    # Set of sets (frozensets) for quick lookup of valid matches
    valid_matches = set()
    for gt in ground_truth_raw:
        if gt.get('should_match'):
            valid_matches.add(frozenset(str(uid) for uid in gt['record_ids']))
            
    # Fetch mapping of internal DB UUIDs to external IDs
    cur.execute("SELECT id, external_id FROM records")
    id_to_ext = {str(row[0]): str(row[1]) for row in cur.fetchall()}
    
    # 2. Fetch Matches
    cur.execute("SELECT record_ids, status, match_type FROM matches")
    db_matches = cur.fetchall()
    
    resolved_matches = 0
    auto_resolved_matches = 0
    wrong_matches = 0
    
    for row in db_matches:
        record_ids = row[0]
        status = row[1]
        
        # psycopg2 sometimes returns arrays of uuids as a string e.g. "{id1,id2}"
        if isinstance(record_ids, str):
            record_ids = record_ids.strip('{}').split(',')
            
        resolved_matches += 1
        if status == 'auto_resolved':
            auto_resolved_matches += 1
            
            # Check if this auto-resolved match is correct according to ground truth
            # We must map the internal UUIDs to external IDs first
            ext_ids = [id_to_ext.get(str(r).strip()) for r in record_ids]
            match_set = frozenset(ext_ids)
            if match_set not in valid_matches:
                wrong_matches += 1
                
    # 3. Fetch Exceptions
    cur.execute("SELECT reason, count(*) FROM exceptions GROUP BY reason")
    exceptions_by_reason = cur.fetchall()
    total_escalated = sum(count for _, count in exceptions_by_reason)
    
    cur.close()
    conn.close()
    
    # 4. Compute Metrics
    match_rate = resolved_matches / total_logical_transactions if total_logical_transactions else 0
    auto_resolution_rate = auto_resolved_matches / total_logical_transactions if total_logical_transactions else 0
    wrong_match_rate = wrong_matches / auto_resolved_matches if auto_resolved_matches else 0
    escalation_rate = total_escalated / total_logical_transactions if total_logical_transactions else 0
    
    # 5. Output Report
    report = f"""# Reconciliation Evaluation Report

## Base Metrics
- **Total Transactions (Ground Truth):** {total_logical_transactions}
- **Valid Matchable Transactions:** {len(valid_matches)}

## Performance Metrics
- **Match Rate:** {match_rate:.2%} ({resolved_matches} / {total_logical_transactions})
- **Auto-resolution Rate:** {auto_resolution_rate:.2%} ({auto_resolved_matches} / {total_logical_transactions})
- **Wrong-match Rate:** {wrong_match_rate:.2%} ({wrong_matches} / {auto_resolved_matches})
- **Escalation Rate:** {escalation_rate:.2%} ({total_escalated} / {total_logical_transactions})

## Escalation Breakdown
"""
    if exceptions_by_reason:
        for reason, count in exceptions_by_reason:
            report += f"- **{reason}:** {count}\n"
    else:
        report += "- No escalations found.\n"
        
    print(report)
    
    # Optionally, write the report to a markdown file
    out_path = os.path.join(os.path.dirname(__file__), '..', 'evaluation_report.md')
    with open(out_path, 'w') as f:
        f.write(report)
    print(f"\nReport saved to {out_path}")

if __name__ == "__main__":
    run_evaluation()
