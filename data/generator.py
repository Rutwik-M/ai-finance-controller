import argparse
import random
import uuid
import pandas as pd
import json
import os
from datetime import datetime, timedelta

def random_date(start, end):
    return start + timedelta(
        seconds=random.randint(0, int((end - start).total_seconds())),
    )

def generate_base_data(num_records):
    base_data = []
    start_date = datetime.now() - timedelta(days=30)
    end_date = datetime.now() - timedelta(days=5)

    for i in range(num_records):
        order_id = f"order_{uuid.uuid4().hex[:8]}"
        payment_id = f"pay_{uuid.uuid4().hex[:8]}"
        settlement_id = f"setl_{uuid.uuid4().hex[:8]}"
        txn_ref = f"txn_{uuid.uuid4().hex[:8]}"
        utr = f"UTR{uuid.uuid4().hex[:10].upper()}"
        
        gross = round(random.uniform(100, 5000), 2)
        fee = round(gross * 0.02, 2)
        tax = round(fee * 0.18, 2)
        net = round(gross - fee - tax, 2)
        
        created_at = random_date(start_date, end_date)
        settled_at = created_at + timedelta(days=random.choice([1, 2]))
        
        base_data.append({
            "order_id": order_id,
            "payment_id": payment_id,
            "settlement_id": settlement_id,
            "txn_ref": txn_ref,
            "utr": utr,
            "gross": gross,
            "fee": fee,
            "tax": tax,
            "net": net,
            "created_at": created_at,
            "settled_at": settled_at,
            "is_clean": True, # Default to clean, we'll mutate later
            "noise_type": None
        })
    return base_data

def apply_noise(base_data):
    # Proportions:
    # 70% clean
    # 5% rounding differences
    # 5% delayed batches
    # 5% duplicate rows (bank)
    # 5% partial refunds
    # 10% pure noise (unmatchable)
    
    n = len(base_data)
    idx = 0
    
    # 5% rounding differences
    for i in range(idx, min(n, idx + int(n * 0.05))):
        base_data[i]["noise_type"] = "rounding_difference"
        base_data[i]["is_clean"] = False
    idx += int(n * 0.05)
    
    # 5% delayed batches
    for i in range(idx, min(n, idx + int(n * 0.05))):
        base_data[i]["noise_type"] = "delayed_batch"
        base_data[i]["is_clean"] = False
    idx += int(n * 0.05)
    
    # 5% duplicate rows (bank)
    for i in range(idx, min(n, idx + int(n * 0.05))):
        base_data[i]["noise_type"] = "duplicate_bank_row"
        base_data[i]["is_clean"] = False
    idx += int(n * 0.05)
    
    # 5% partial refunds
    for i in range(idx, min(n, idx + int(n * 0.05))):
        base_data[i]["noise_type"] = "partial_refund"
        base_data[i]["is_clean"] = False
    idx += int(n * 0.05)
    
    # 10% pure noise
    for i in range(idx, min(n, idx + int(n * 0.10))):
        base_data[i]["noise_type"] = "pure_noise"
        base_data[i]["is_clean"] = False
    idx += int(n * 0.10)
    
    return base_data

def generate(num_records, out_dir):
    base_data = generate_base_data(num_records)
    base_data = apply_noise(base_data)
    
    razorpay_records = []
    bank_records = []
    ledger_records = []
    ground_truth = []
    
    for row in base_data:
        # Base entries
        rp_row = {
            "settlement_id": row["settlement_id"],
            "payment_id": row["payment_id"],
            "order_id": row["order_id"],
            "gross_amount": row["gross"],
            "fees": row["fee"],
            "tax": row["tax"],
            "net_amount": row["net"],
            "utr": row["utr"],
            "settled_at": row["settled_at"].strftime("%Y-%m-%d %H:%M:%S")
        }
        
        bank_amount = row["net"]
        if row["noise_type"] == "rounding_difference":
            bank_amount = round(bank_amount + random.choice([-1.5, -0.5, 0.5, 1.5]), 2)
            
        bank_value_date = row["settled_at"]
        if row["noise_type"] == "delayed_batch":
            bank_value_date = bank_value_date + timedelta(days=random.randint(2, 5))
            
        bank_narration = f"NEFT-RZP-{row['utr']}-SETTLEMENT"
        # Intentionally corrupt UTR in the bank statement for some noisy records
        # This prevents the deterministic UTR rule from catching them, forcing them into Fuzzy/LLM stages.
        if row["noise_type"] in ["rounding_difference", "delayed_batch", "partial_refund"]:
            if random.random() < 0.7:  # 70% chance to corrupt the UTR text
                bank_narration = f"NEFT-TRANSFER-{random.randint(10000, 99999)}"
        
        bk_row = {
            "txn_ref": row["txn_ref"],
            "amount": bank_amount,
            "value_date": bank_value_date.strftime("%Y-%m-%d"),
            "narration": bank_narration
        }
        
        ledger_amount = row["gross"]
        if row["noise_type"] == "partial_refund":
            ledger_amount = round(row["gross"] * random.uniform(0.1, 0.9), 2)
            
        lg_row = {
            "order_id": row["order_id"],
            "payment_id": row["payment_id"],
            "expected_amount": ledger_amount,
            "order_status": "paid",
            "created_at": row["created_at"].strftime("%Y-%m-%d %H:%M:%S")
        }
        
        # pure noise logic
        if row["noise_type"] == "pure_noise":
            noise_target = random.choice(["razorpay", "bank", "ledger"])
            if noise_target == "razorpay":
                razorpay_records.append(rp_row)
                ground_truth.append({
                    "record_ids": [rp_row["settlement_id"]],
                    "should_match": False
                })
            elif noise_target == "bank":
                bank_records.append(bk_row)
                ground_truth.append({
                    "record_ids": [bk_row["txn_ref"]],
                    "should_match": False
                })
            else:
                ledger_records.append(lg_row)
                ground_truth.append({
                    "record_ids": [lg_row["order_id"]],
                    "should_match": False
                })
            continue # Don't add to all three

        razorpay_records.append(rp_row)
        bank_records.append(bk_row)
        ledger_records.append(lg_row)
        
        # duplicate bank row logic
        if row["noise_type"] == "duplicate_bank_row":
            dup_bk_row = bk_row.copy()
            dup_bk_row["txn_ref"] = f"txn_{uuid.uuid4().hex[:8]}"
            bank_records.append(dup_bk_row)
            # The duplicate is pure noise essentially for the ground truth of the true triplet
            ground_truth.append({
                "record_ids": [dup_bk_row["txn_ref"]],
                "should_match": False
            })

        ground_truth.append({
            "record_ids": [rp_row["settlement_id"], bk_row["txn_ref"], lg_row["order_id"]],
            "should_match": True
        })

    os.makedirs(out_dir, exist_ok=True)
    pd.DataFrame(razorpay_records).to_csv(os.path.join(out_dir, "razorpay.csv"), index=False)
    pd.DataFrame(bank_records).to_csv(os.path.join(out_dir, "bank.csv"), index=False)
    pd.DataFrame(ledger_records).to_csv(os.path.join(out_dir, "ledger.csv"), index=False)
    
    with open(os.path.join(out_dir, "ground_truth.json"), "w") as f:
        json.dump(ground_truth, f, indent=2)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=int, default=750, help="Number of records to generate")
    parser.add_argument("--out", type=str, required=True, help="Output directory")
    args = parser.parse_args()
    
    print(f"Generating {args.records} records into {args.out}...")
    generate(args.records, args.out)
    print("Done.")
