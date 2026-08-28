import os
import psycopg2

DDL = """
create table if not exists records (
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

create index if not exists idx_records_payment_id on records(payment_id);
create index if not exists idx_records_amount_date on records(amount, reference_date);

create table if not exists matches (
    id                uuid primary key default gen_random_uuid(),
    record_ids        uuid[] not null,        -- 2 or 3 matched record ids
    match_type        text not null,          -- 'deterministic' | 'fuzzy' | 'llm'
    confidence         numeric(4,3) not null,
    status            text not null,          -- 'auto_resolved' | 'escalated'
    matched_at        timestamptz not null default now()
);

create table if not exists exceptions (
    id           uuid primary key default gen_random_uuid(),
    record_id    uuid references records(id),
    reason       text not null,               -- 'amount_mismatch' | 'no_counterpart' | 'duplicate' | 'date_drift'
    detail       jsonb,
    status       text not null default 'open', -- 'open' | 'reviewed' | 'resolved'
    created_at   timestamptz not null default now()
);

create table if not exists audit_log (
    id           uuid primary key default gen_random_uuid(),
    match_id     uuid references matches(id),
    decision     text not null,               -- what was decided
    rule_fired   text,                        -- for deterministic/fuzzy
    llm_reasoning text,                       -- for LLM-assisted, verbatim model output
    created_at   timestamptz not null default now()
);

alter table exceptions add column if not exists action_recommended jsonb;


create table if not exists ground_truth (
    id              uuid primary key default gen_random_uuid(),
    record_ids      uuid[] not null,
    should_match    boolean not null
);
"""

def migrate():
    db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgrespassword@localhost:5432/settlement_reconciliation")
    print(f"Connecting to database: {db_url}")
    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        cur = conn.cursor()
        
        print("Executing DDL...")
        cur.execute(DDL)
        print("Migration successful.")
        
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Migration failed: {e}")
        exit(1)

if __name__ == "__main__":
    migrate()
