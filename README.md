# Settlement Reconciliation Agent

A prototype agent being built for the Razorpay AI Buildathon (Track 04). The goal is to match records across a Razorpay settlement report, a bank statement, and a merchant's internal ledger.

## Current Progress
- [x] Initial infrastructure setup (Docker, Postgres)
- [x] Synthetic data generation pipeline (50+ records)
- [ ] Core matching engine (WIP)
- [ ] Evaluation metrics (WIP)

## Initial Setup

```bash
cp .env.example .env
docker-compose up -d db
pip install -r requirements.txt

# Generate initial synthetic data for testing
python data/generator.py --records 750 --out data/samples/
