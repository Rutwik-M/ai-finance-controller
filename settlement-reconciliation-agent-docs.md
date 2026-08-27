# Settlement Reconciliation Agent — Project Documentation

Track: Razorpay AI Buildathon 2026 — Track 04, AI Finance Controller
Deadline: September 5, 2026

---

## 1. Overview

A settlement reconciliation agent that matches records across three messy sources — a Razorpay settlement report, a bank statement, and a merchant's internal ledger — and produces an honest accuracy report instead of a demo that only shows the happy path.

The problem this solves: settlement reconciliation is still done by hand at most merchants. A payment gets settled, the bank credits an amount that rarely matches the gross payment exactly (fees, tax, rounding, split settlements, delayed batches), and someone has to manually tie the three records together every week. This system automates the matching, flags what it can't confidently resolve, and logs why every decision was made.

Track 4's stated bar: "Throughput plus measured accuracy plus an honest exception list. One cherry-picked match proves nothing." Every design decision below is built around satisfying that bar with real numbers, not a curated demo.

---

## 2. Goals and success criteria

**Functional goals**
- Ingest three heterogeneous sources and normalize them into one schema
- Match records across sources with high automation and low false-positive rate
- Surface everything it could not confidently resolve, with a reason
- Log every decision (auto-resolved or escalated) with enough detail to reconstruct why

**Non-functional goals**
- Scale to a batch of 500+ records without linear growth in LLM cost
- Every money-relevant decision must be explainable after the fact
- Idempotent: re-running the pipeline on the same batch never double-counts

**Submission success metrics** (report these numbers, not adjectives)
- Match rate: % of records resolved (auto or manually confirmed) against total
- Auto-resolution rate: % resolved without human/LLM ambiguity
- Wrong-match rate: % of auto-resolved matches that are wrong, measured against synthetic ground truth
- Escalation rate: % sent to the exception queue, with reason breakdown
- Throughput: records processed per second in the deterministic pass vs. the LLM pass

---

## 3. Scope

**In scope for the submission**
- Batch reconciliation of 3 synthetic sources (500–1,000 records)
- Deterministic + fuzzy + LLM-assisted matching pipeline
- Confidence-gated auto-resolve vs. escalate
- Audit log for every decision
- Evaluation harness against ground truth
- Minimal dashboard showing match rate, exceptions, and audit drill-down
- One deliberately injected failure case, handled gracefully, shown in the demo video

**Explicitly out of scope** (say this out loud in the pitch — naming what you didn't build is a signal of judgment, not a weakness)
- Live Razorpay production API integration (test-mode/synthetic data only)
- Multi-currency handling
- Real-time streaming reconciliation (batch only)
- Auth/multi-tenant merchant support
- Automated write-back to accounting systems (ERP integration)

---

## 4. System architecture

```
Razorpay settlement CSV ─┐
Bank statement CSV ──────┼──▶ Ingestion & normalization
Merchant ledger CSV ─────┘              │
                                         ▼
                          Deterministic matcher (SQL joins)
                                         │
                              unmatched records only
                                         ▼
                          Fuzzy + LLM matcher (ambiguous cases)
                                         │
                                         ▼
                              Confidence gate (rule score + LLM score)
                                    │           │
                              auto-resolved   escalated
                                    │           │
                                    ▼           ▼
                              Audit trail & dashboard
```

Design principle that makes this scale: the deterministic pass handles the majority of records (exact key or exact amount+date matches) using indexed SQL joins. The LLM is only ever invoked on the minority of genuinely ambiguous records. This is the difference between a system that costs and takes the same time whether you feed it 500 or 50,000 records, and one that falls over at scale because every row hits an LLM call.

---

## 5. Data model

### 5.1 Source schemas (raw, as ingested)

**Razorpay settlement export**
```
settlement_id, payment_id, order_id, gross_amount, fees, tax, net_amount, utr, settled_at
```

**Bank statement**
```
txn_ref, amount, value_date, narration (free text, often truncated, sometimes includes UTR)
```

**Merchant internal ledger**
```
order_id, payment_id, expected_amount, order_status, created_at
```

### 5.2 Canonical schema (post-normalization)

```python
class NormalizedRecord(BaseModel):
    source: Literal["razorpay", "bank", "ledger"]
    external_id: str            # source's own primary key
    payment_id: str | None
    order_id: str | None
    amount: Decimal
    reference_date: date
    raw_reference: str | None   # UTR or narration, kept for fuzzy matching
    ingested_at: datetime
```

### 5.3 Database schema (PostgreSQL DDL)

```sql
create table records (
    id              uuid primary key default gen_random_uuid(),
    source          text not null,
    external_id     text not null,
    payment_id      text,
    order_id        text,
    amount          numeric(12,2) not null,
    reference_date  date not null,
    raw_reference   text,
    ingested_at     timestamptz not null default now(),
    unique (source, external_id)
);

create index idx_records_payment_id on records(payment_id);
create index idx_records_amount_date on records(amount, reference_date);

create table matches (
    id                uuid primary key default gen_random_uuid(),
    record_ids        uuid[] not null,        -- 2 or 3 matched record ids
    match_type        text not null,          -- 'deterministic' | 'fuzzy' | 'llm'
    confidence         numeric(4,3) not null,
    status            text not null,          -- 'auto_resolved' | 'escalated'
    matched_at        timestamptz not null default now()
);

create table exceptions (
    id           uuid primary key default gen_random_uuid(),
    record_id    uuid references records(id),
    reason       text not null,               -- 'amount_mismatch' | 'no_counterpart' | 'duplicate' | 'date_drift'
    detail       jsonb,
    status       text not null default 'open', -- 'open' | 'reviewed' | 'resolved'
    created_at   timestamptz not null default now()
);

create table audit_log (
    id           uuid primary key default gen_random_uuid(),
    match_id     uuid references matches(id),
    decision     text not null,               -- what was decided
    rule_fired   text,                        -- for deterministic/fuzzy
    llm_reasoning text,                       -- for LLM-assisted, verbatim model output
    created_at   timestamptz not null default now()
);
```

Ground truth (evaluation only, never touches the production tables):
```sql
create table ground_truth (
    id              uuid primary key default gen_random_uuid(),
    record_ids      uuid[] not null,
    should_match    boolean not null
);
```

---

## 6. Tech stack

| Layer | Technology | Why |
|---|---|---|
| Backend API | FastAPI | Async, Pydantic validation for structured LLM output, fast to iterate |
| Database | PostgreSQL (Supabase) | Relational integrity for financial records, indexed joins for the deterministic pass |
| Matching (bulk) | pandas + SQL | Vectorized deterministic pass, not row-by-row Python |
| Matching (fuzzy) | rapidfuzz | Fast string similarity for bank narration text |
| LLM calls | OpenRouter, structured JSON output | Multi-model routing, same pattern as NoteDeck; route cheap model for high volume, stronger model only if confidence stays low |
| Frontend | React + Tailwind + shadcn | Match-rate dashboard, exception drill-down, audit trail viewer |
| Containerization | Docker + docker-compose | One-command local spin-up for the demo video and for the panel to run themselves |
| Testing | pytest + hypothesis | Unit tests on matching rules, property-based tests to catch edge cases in amount/date tolerance logic |
| CI | GitHub Actions | Run the evaluation harness on every push, fail the build if wrong-match rate regresses |
| Logging | structlog | Structured, queryable logs — reuse the webhook-monitoring discipline from your homelab |
| Deployment (demo) | Render or a single Docker Compose stack on your homelab, exposed via Tailscale/Nginx if you want a live link | You already have this infra pattern built |

---

## 7. Matching engine design

### 7.1 Deterministic matcher (stage 1)

Run first, as a set of prioritized SQL joins, in this order:
1. Exact `payment_id` match across all three sources
2. Exact UTR / bank reference match (settlement UTR = bank narration substring)
3. Exact amount + same-day date match

Every record that matches here is marked `match_type = 'deterministic'`, `confidence = 1.0`, and auto-resolved. This should account for the large majority of a clean batch.

### 7.2 Fuzzy matcher (stage 2, only for what stage 1 missed)

For remaining unmatched records:
- Amount within a tolerance band (e.g. ±₹2 to catch rounding, or exact minus known fee)
- Date within a rolling window (e.g. settlement date within 3 days of payment date, to catch delayed batches)
- `rapidfuzz.fuzz.partial_ratio` on the bank narration against the UTR/payment reference

Combine into a rule-based score (0–1): weight exact-amount higher than fuzzy-amount, weight narration similarity moderately. Anything scoring above a high threshold (e.g. 0.85) can auto-resolve as `match_type = 'fuzzy'`; the rest goes to stage 3.

### 7.3 LLM-assisted matcher (stage 3, ambiguous minority only)

For each remaining unmatched record, retrieve the top 2–3 candidate counterparts (by rule score) and send them to the LLM in a single batched, structured-output call:

```json
{
  "record": { "...": "..." },
  "candidates": [ { "...": "..." }, { "...": "..." } ],
  "instruction": "Given the record and candidates, decide which candidate (if any) is the correct match. Return structured JSON only."
}
```

Expected structured response:
```json
{
  "match_candidate_id": "uuid or null",
  "confidence": 0.0,
  "reasoning": "short explanation, stored verbatim in audit_log"
}
```

Batch multiple ambiguous records into fewer API calls where candidate sets don't overlap, to control cost. Cache identical narration strings so the same bank text is never re-scored twice.

### 7.4 Confidence gate

```
final_confidence = (rule_score * 0.4) + (llm_confidence * 0.6)   # tune weights against eval data
if final_confidence >= 0.90: auto_resolve()
else: escalate(reason=classify_exception(record))
```

Log the threshold value in your README and be ready to defend why 0.90 and not 0.95 or 0.80 — this is the kind of number the panel will ask about.

---

## 8. Evaluation harness

### 8.1 Synthetic data generator

Write a script that generates the three source CSVs plus a `ground_truth.json`. Inject these noise types deliberately, and log how many of each you injected:
- Rounding differences (settlement net differs from bank credit by a few paise/rupees)
- Split settlements (one order settled across two payouts)
- Delayed batches (settlement date 2–5 days after payment)
- Duplicate rows (same transaction appearing twice in bank export)
- Partial refunds (ledger shows lower amount than gross settlement)
- Pure noise records with no valid counterpart anywhere (true unmatchable exceptions)

### 8.2 Metrics definitions

- **Match rate** = resolved records / total records
- **Auto-resolution rate** = auto-resolved / total records
- **Wrong-match rate** = auto-resolved matches that are incorrect per ground truth / auto-resolved matches
- **Escalation rate** = escalated / total records, broken down by exception reason
- **Precision / recall** on the matching decision itself, computed against `ground_truth`

### 8.3 Running the harness

Output a single report (markdown or JSON) after each run:
```
Total records: 750
Auto-resolved: 612 (81.6%)
  - deterministic: 540
  - fuzzy: 72
Escalated: 138 (18.4%)
  - amount_mismatch: 51
  - no_counterpart: 44
  - duplicate: 22
  - date_drift: 21
Wrong-match rate (auto-resolved): 0.8% (5 / 612)
```

This report is your single most important artifact for the submission. Put it directly in the README.

---

## 9. API design

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/ingest` | Upload/parse a source file, normalize into `records` |
| POST | `/reconcile/run` | Trigger a full matching run over unmatched records |
| GET | `/matches` | List matches, filterable by status and match_type |
| GET | `/exceptions` | List open exceptions, filterable by reason |
| GET | `/audit/{match_id}` | Full decision trail for one match |
| GET | `/metrics` | Current match rate, escalation rate, wrong-match rate (if ground truth loaded) |

---

## 10. Build roadmap: today (Aug 24) to submission (Sept 5)

| Days | Milestone |
|---|---|
| 1–2 (Aug 24–25) | Repo scaffold, DB schema, synthetic data generator + ground truth committed |
| 3–4 (Aug 26–27) | Ingestion layer + deterministic matcher (stage 1), first real numbers from a clean batch |
| 5–6 (Aug 28–29) | Fuzzy matcher (stage 2) + LLM-assisted matcher (stage 3) with structured output |
| 7 (Aug 30) | Confidence gate, exceptions table, audit log wired end to end |
| 8 (Aug 31) | Evaluation harness complete, first full report, tune thresholds against it |
| 9 (Sept 1) | Dashboard: match rate, exception list, audit drill-down |
| 10 (Sept 2) | Dockerize, write README + architecture doc, deploy a reachable demo instance |
| 11 (Sept 3) | Record the 5-minute pitch video, rehearse the failure-handling story |
| 12–13 (Sept 4–5) | Buffer: polish, fix whatever the video exposed, submit early rather than at the deadline |

Submit a day early if you can. It gives you room if a deploy breaks, and "submitted with time to spare" is itself a small signal.

---

## 11. Production considerations (beyond the submission)

- **Idempotency**: every ingestion is keyed on `(source, external_id)` with a unique constraint — replaying the same file never double-inserts
- **Horizontal scale**: the deterministic pass is stateless and can run as parallel workers over date-partitioned batches; the LLM pass should sit behind a queue (Celery/RQ) so a slow LLM call never blocks ingestion
- **Cost control**: cache LLM responses for identical narration+amount pairs; track $/1000 records processed as a metric you can quote
- **Security**: bank data is sensitive — least-privilege DB credentials, secrets in environment variables never committed, and if you extend this beyond synthetic data, treat it as PII/financial data under retention policy
- **Observability**: structured logs per pipeline stage, plus a webhook or alert if wrong-match rate on a rolling eval sample crosses a threshold — this is a direct extension of the disaster-recovery/monitoring pattern from your homelab

---

## 12. Demo and pitch plan (5-minute video)

1. 30s: the problem — reconciliation is manual, here's why it matters
2. 60s: architecture diagram walkthrough (use the diagram from this doc)
3. 90s: live run — ingest 3 messy sources, run the pipeline, show the report with real numbers
4. 60s: drill into one exception, show the audit trail explaining why it was escalated
5. 30s: the one deliberately injected failure — show it happening and the pipeline handling it gracefully (e.g. a malformed CSV row skipped with a logged reason, not a crash)
6. 30s: what you'd do next at 10x scale, and what you explicitly left out of scope

---

## 13. Repo structure

```
settlement-reconciliation-agent/
├── data/
│   ├── generator.py           # synthetic data + ground truth generator
│   └── samples/
├── src/
│   ├── ingestion/
│   ├── matching/
│   │   ├── deterministic.py
│   │   ├── fuzzy.py
│   │   └── llm.py
│   ├── confidence.py
│   ├── api/                   # FastAPI app
│   └── db/                    # models, migrations
├── eval/
│   └── run_eval.py            # produces the metrics report
├── dashboard/                 # React app
├── tests/
├── docker-compose.yml
├── .github/workflows/ci.yml
└── README.md
```

---

## 14. Getting started

```bash
git clone <your-repo>
cd settlement-reconciliation-agent
cp .env.example .env            # DB URL, OPENROUTER_API_KEY

docker-compose up -d db
python -m src.db.migrate

python data/generator.py --records 750 --out data/samples/

python -m src.ingestion.load data/samples/
python -m src.matching.run

python eval/run_eval.py         # prints the metrics report

cd dashboard && npm install && npm run dev
```
