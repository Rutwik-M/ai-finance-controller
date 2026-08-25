import os
import json
import csv
import io
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor

app = FastAPI(title="Reconciliation API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db_connection():
    db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgrespassword@localhost:5432/settlement_reconciliation")
    # Inside docker, db is "db", locally it's "localhost".
    # Since FastAPI will run in docker as 'api', it should use the ENV var correctly (which we'll inject via docker-compose)
    return psycopg2.connect(db_url)

@app.get("/api/metrics")
def get_metrics():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("SELECT match_type, count(*) FROM matches GROUP BY match_type")
        matches = [{"name": row[0], "value": row[1]} for row in cur.fetchall()]
        
        cur.execute("SELECT count(*) FROM records WHERE source = 'razorpay'")
        total_records = cur.fetchone()[0]
        
        cur.execute("SELECT count(*) FROM exceptions WHERE status = 'open'")
        total_exceptions = cur.fetchone()[0]
        
        cur.execute("SELECT reason, count(*) FROM exceptions WHERE status = 'open' GROUP BY reason")
        reasons = [{"reason": row[0], "count": row[1]} for row in cur.fetchall()]
        
        cur.execute("SELECT reference_date::date, count(*) FROM records WHERE source = 'razorpay' GROUP BY reference_date::date ORDER BY reference_date::date")
        daily = [{"date": str(row[0]), "transactions": row[1]} for row in cur.fetchall()]
        
        cur.close()
        conn.close()
        
        return {
            "matches_breakdown": matches,
            "total_records": total_records,
            "total_exceptions": total_exceptions,
            "exceptions_by_reason": reasons,
            "daily_transactions": daily
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/exceptions")
def get_exceptions():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT e.id, e.record_id, e.reason, e.detail, e.created_at, r.amount, r.reference_date, r.raw_reference
            FROM exceptions e
            JOIN records r ON e.record_id = r.id
            WHERE e.status = 'open'
            ORDER BY e.created_at DESC
        """)
        
        data = []
        for row in cur.fetchall():
            detail = row[3] if isinstance(row[3], dict) else {}
            if isinstance(row[3], str):
                try:
                    detail = json.loads(row[3])
                except:
                    pass
                
            data.append({
                "id": str(row[0]),
                "record_id": str(row[1]),
                "reason": row[2],
                "detail": detail,
                "created_at": str(row[4]),
                "amount": float(row[5]) if row[5] else None,
                "reference_date": str(row[6]),
                "raw_reference": row[7]
            })
            
        cur.close()
        conn.close()
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class ResolveRequest(BaseModel):
    candidate_id: str
    notes: str

@app.post("/api/exceptions/{exception_id}/resolve")
def resolve_exception(exception_id: str, payload: ResolveRequest):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Get record ID
        cur.execute("SELECT record_id FROM exceptions WHERE id = %s", (exception_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Exception not found")
        record_id = row[0]
        
        # Create a new match in the matches table
        # A human match has confidence 1.0
        # We need the record_ids: [razorpay_id, bank_id]
        cur.execute(
            "INSERT INTO matches (record_ids, match_type, confidence, status) VALUES (%s::uuid[], %s, %s, %s) RETURNING id;",
            ([str(record_id), payload.candidate_id], "human", 1.0, "resolved")
        )
        match_id = cur.fetchone()[0]
        
        cur.execute("UPDATE exceptions SET status = 'resolved' WHERE id = %s", (exception_id,))
        cur.execute(
            "INSERT INTO audit_log (match_id, decision, llm_reasoning) VALUES (%s, %s, %s)",
            (match_id, "human-resolved", f"Resolved to {payload.candidate_id}. Notes: {payload.notes}")
        )
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/export")
def export_csv():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Get all razorpay records and their resolution status
        cur.execute("""
            SELECT r.external_id, r.amount, r.reference_date, r.raw_reference, 
                   COALESCE(m.status, e.status, 'unmatched') as resolution_status,
                   m.match_type,
                   m.confidence,
                   b.external_id as matched_bank_id
            FROM records r
            LEFT JOIN matches m ON r.id = ANY(m.record_ids)
            LEFT JOIN exceptions e ON r.id = e.record_id
            LEFT JOIN records b ON b.id = ANY(m.record_ids) AND b.source = 'bank'
            WHERE r.source = 'razorpay'
            ORDER BY r.reference_date DESC
        """)
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Razorpay ID', 'Amount', 'Date', 'Reference', 'Status', 'Match Type', 'Confidence', 'Matched Bank ID'])
        
        for row in cur.fetchall():
            writer.writerow([row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7]])
            
        cur.close()
        conn.close()
        
        response = StreamingResponse(iter([output.getvalue()]), media_type="text/csv")
        response.headers["Content-Disposition"] = "attachment; filename=reconciled_ledger.csv"
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/audit")
def get_audit_log():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT a.id, a.match_id, a.decision, a.rule_fired, a.llm_reasoning, a.created_at,
                   m.status, m.match_type, m.confidence
            FROM audit_log a
            LEFT JOIN matches m ON a.match_id = m.id
            ORDER BY a.created_at DESC
            LIMIT 50
        """)
        
        data = []
        for row in cur.fetchall():
            data.append({
                "id": str(row[0]),
                "match_id": str(row[1]) if row[1] else None,
                "decision": row[2],
                "rule_fired": row[3],
                "llm_reasoning": row[4],
                "created_at": str(row[5]),
                "status": row[6],
                "match_type": row[7],
                "confidence": float(row[8]) if row[8] else None
            })
            
        cur.close()
        conn.close()
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/records/{source}")
def get_source_records(source: str):
    if source not in ['razorpay', 'bank', 'ledger']:
        raise HTTPException(status_code=400, detail="Invalid source")
    
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT id, amount, reference_date, raw_reference FROM records WHERE source = %s ORDER BY reference_date DESC LIMIT 100",
            (source,)
        )
        records = cur.fetchall()
        cur.close()
        conn.close()
        
        # Convert UUID and Date to string
        for record in records:
            record['id'] = str(record['id'])
            record['amount'] = float(record['amount'])
            record['reference_date'] = str(record['reference_date'])
            
        return records
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
