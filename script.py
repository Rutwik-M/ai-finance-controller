#!/usr/bin/env python3
import subprocess
import argparse
import sys
import re
import os

def run_cmd(cmd):
    print(f"\n=> Running: {cmd}")
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        print(f"Command failed with exit code {result.returncode}")
        sys.exit(1)

def set_llm_model(model_name):
    print(f"\n=> Updating LLM model to: {model_name} in src/matching/llm.py")
    with open("src/matching/llm.py", "r") as f:
        content = f.read()
    
    # Replace the "model": "..." line
    new_content = re.sub(
        r'"model":\s*"[^"]+"',
        f'"model": "{model_name}"',
        content
    )
    
    with open("src/matching/llm.py", "w") as f:
        f.write(new_content)

def main():
    parser = argparse.ArgumentParser(description="Run the complete reconciliation pipeline")
    parser.add_argument("--records", type=int, default=200, help="Number of records to generate")
    parser.add_argument("--model", type=str, help="Groq model name to use (e.g., llama-3.1-8b-instant)")
    args = parser.parse_args()

    if args.model:
        set_llm_model(args.model)

    print("\n[1/5] Truncating database to ensure a clean slate...")
    run_cmd('docker compose exec -T db psql -U postgres -d settlement_reconciliation -c "TRUNCATE records, matches, exceptions, audit_log CASCADE;"')

    print(f"\n[2/5] Generating {args.records} synthetic records...")
    run_cmd(f'docker compose exec -T api python data/generator.py --records {args.records} --out temp_data')

    print("\n[3/5] Ingesting records into the database...")
    run_cmd('docker compose exec -T -e DATABASE_URL="postgresql://postgres:postgrespassword@db:5432/settlement_reconciliation" api python src/ingestion/load.py temp_data')

    print("\n[4/5] Running Matching Pipeline (Deterministic & LLM)...")
    
    # Create the env variable string for docker compose exec based on .env
    env_str = ""
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                if line.strip() and not line.startswith("#"):
                    key = line.split("=")[0].strip()
                    val = line.split("=", 1)[1].strip()
                    # only inject GROQ keys
                    if "GROQ" in key:
                        env_str += f'-e {key}="{val}" '
    
    run_cmd(f'docker compose exec -T {env_str}-e DATABASE_URL="postgresql://postgres:postgrespassword@db:5432/settlement_reconciliation" api python -m src.matching.run')

    print("\n[5/5] Pipeline complete! Check the dashboard at http://localhost:5173")

if __name__ == "__main__":
    main()
