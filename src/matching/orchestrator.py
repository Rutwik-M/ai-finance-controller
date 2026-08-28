import os
import json
import httpx
import psycopg2
import asyncio
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential, retry_if_exception_type

_current_key_idx = 0

async def _call_llm_async(client, api_keys, payload):
    global _current_key_idx
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(6),
        wait=wait_exponential(multiplier=2, min=5, max=60),
        retry=retry_if_exception_type(httpx.HTTPStatusError),
        reraise=True
    ):
        with attempt:
            key = api_keys[_current_key_idx % len(api_keys)]
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json"
            }
            
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30.0
            )
            
            if response.status_code == 429 and len(api_keys) > 1:
                _current_key_idx += 1
                
            response.raise_for_status()
            return response

async def process_exception(exc, api_keys, db_url, semaphore, client):
    async with semaphore:
        exc_id, record_id, reason, detail, amount, date, raw_ref = exc
        
        prompt = {
            "instruction": "You are a financial operations agent. An exception occurred during reconciliation. Determine the best recovery action to close the loop. Action type must be one of: 'slack_alert' (for manual trace), 'email_merchant' (if they need to provide proof), or 'ledger_adjustment' (for rounding/partial differences).",
            "exception": {
                "reason": reason,
                "detail": detail if isinstance(detail, dict) else json.loads(detail) if detail else {}
            },
            "target_record": {
                "amount": float(amount) if amount else None,
                "date": str(date) if date else None,
                "reference": raw_ref
            }
        }

        payload = {
            "model": "openai/gpt-oss-20b",
            "messages": [{"role": "user", "content": json.dumps(prompt)}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "action_recommendation",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "action_type": {"type": "string", "enum": ["slack_alert", "email_merchant", "ledger_adjustment"]},
                            "action_payload": {
                                "type": "object",
                                "properties": {
                                    "message": {"type": "string"},
                                    "adjustment_amount": {"type": ["number", "null"]},
                                    "recipient": {"type": ["string", "null"]}
                                },
                                "required": ["message", "adjustment_amount", "recipient"],
                                "additionalProperties": False
                            },
                            "reasoning": {"type": "string"}
                        },
                        "required": ["action_type", "action_payload", "reasoning"],
                        "additionalProperties": False
                    },
                    "strict": True
                }
            }
        }
        
        try:
            response = await _call_llm_async(client, api_keys, payload)
            result = response.json()
            content = result['choices'][0]['message'].get('content', '')
            if not content:
                raise ValueError("Empty response")
                
            content = content.strip()
            if content.startswith("```"):
                start = content.find("{")
                end = content.rfind("}")
                if start != -1 and end != -1:
                    content = content[start:end+1]
            
            action = json.loads(content)
            return {"exc_id": exc_id, "status": "success", "action": action}
        except Exception as e:
            print(f"Orchestrator failed for exception {exc_id}: {e}")
            return {"exc_id": exc_id, "status": "error", "error": str(e)}

async def _run_orchestrator_batch(exceptions, api_keys, db_url):
    # Keep concurrency low to avoid hitting Groq rate limits
    concurrency_limit = 2
    semaphore = asyncio.Semaphore(concurrency_limit)
    limits = httpx.Limits(max_keepalive_connections=concurrency_limit, max_connections=concurrency_limit)
    
    async with httpx.AsyncClient(limits=limits, timeout=90.0) as client:
        results = []
        # Process in small sequential batches to stay within rate limits
        batch_size = 2
        for i in range(0, len(exceptions), batch_size):
            batch = exceptions[i:i + batch_size]
            tasks = [process_exception(exc, api_keys, db_url, semaphore, client) for exc in batch]
            batch_results = await asyncio.gather(*tasks)
            results.extend(batch_results)
            # Stagger batches to respect Groq's RPM limits
            if i + batch_size < len(exceptions):
                await asyncio.sleep(3)
        return results

def run_orchestrator():
    api_keys = []
    key1 = os.getenv("GROQ_API_KEY")
    key2 = os.getenv("GROQ_API_KEY_2")
    if key1: api_keys.append(key1)
    if key2: api_keys.append(key2)
    
    if not api_keys:
        print("Warning: GROQ_API_KEY not found. Skipping Orchestrator.")
        return
        
    db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgrespassword@localhost:5432/settlement_reconciliation")
    
    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        cur = conn.cursor()
        
        cur.execute("""
            SELECT e.id, e.record_id, e.reason, e.detail, r.amount, r.reference_date, r.raw_reference
            FROM exceptions e
            JOIN records r ON e.record_id = r.id
            WHERE e.status = 'open' AND e.action_recommended IS NULL
        """)
        exceptions = cur.fetchall()
        
        if not exceptions:
            print("Orchestrator: No new exceptions to process.")
            cur.close()
            conn.close()
            return
            
        print(f"Orchestrator: Processing {len(exceptions)} exceptions...")
    except Exception as e:
        print(f"Orchestrator DB connect failed: {e}")
        return
        
    results = asyncio.run(_run_orchestrator_batch(exceptions, api_keys, db_url))
    
    success_count = 0
    for res in results:
        if res['status'] == 'success':
            cur.execute(
                "UPDATE exceptions SET action_recommended = %s WHERE id = %s",
                (json.dumps(res['action']), res['exc_id'])
            )
            success_count += 1
            
    print(f"Orchestrator complete. Generated {success_count} actions.")
    cur.close()
    conn.close()
