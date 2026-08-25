import os
import json
import httpx
import psycopg2
import re
import time
from psycopg2.extras import execute_values
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

def mask_pii(text):
    if not text:
        return text
    # Mask alphanumeric strings longer than 6 chars (simulating UTR/Account numbers)
    return re.sub(r'[A-Za-z0-9]{6,}', '[MASKED_PII]', text)


# Global key index for rotation
_current_key_idx = 0

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(httpx.HTTPStatusError),
    reraise=True
)
def _call_llm(api_keys, payload):
    global _current_key_idx
    # Use the current key
    key = api_keys[_current_key_idx % len(api_keys)]
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }
    
    response = httpx.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=30.0
    )
    
    # If rate limited, rotate the key for the next retry
    if response.status_code == 429 and len(api_keys) > 1:
        print(f"Key {key[:10]}... rate limited! Switching to next key.")
        _current_key_idx += 1
        
    response.raise_for_status()
    return response

# Global in-memory cache for the batch run
_llm_cache = {}

def resolve_with_llm(ambiguous_records):
    if not ambiguous_records:
        return

    api_keys = []
    key1 = os.getenv("GROQ_API_KEY")
    key2 = os.getenv("GROQ_API_KEY_2")
    if key1: api_keys.append(key1)
    if key2: api_keys.append(key2)
    
    if not api_keys:
        print("Warning: GROQ_API_KEY not found. Skipping LLM resolution.")
        return
        
    db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgrespassword@localhost:5432/settlement_reconciliation")
    
    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        cur = conn.cursor()
    except Exception as e:
        print(f"Failed to connect to DB: {e}")
        return
    
    hits = 0
    misses = 0

    for record_group in ambiguous_records:
        r_id = record_group['r_id']
        candidates = record_group['candidates']
        
        # We replace candidate_id with an index so we can cache identical amounts/narrations
        # regardless of their underlying UUIDs.
        cache_key_components = [
            str(record_group['r_amount']),
            str(record_group['r_date']),
            str(record_group['r_ref'])
        ]
        
        candidates_for_prompt = []
        candidate_mapping = {} # index -> b_id
        
        for idx, c in enumerate(candidates):
            idx_str = str(idx)
            candidate_mapping[idx_str] = str(c['b_id'])
            candidates_for_prompt.append({
                "candidate_id": idx_str,
                "amount": float(c['b_amount']),
                "date": str(c['b_date']),
                "reference": c['b_ref'],
                "rule_score": float(c['rule_score'])
            })
            cache_key_components.extend([
                str(float(c['b_amount'])), str(c['b_date']), str(c['b_ref'])
            ])
            
        cache_key = "|".join(cache_key_components)
        
        if cache_key in _llm_cache:
            hits += 1
            decision = _llm_cache[cache_key]
        else:
            misses += 1
            prompt = {
                "instruction": "You are a financial reconciliation expert. Given the target Razorpay settlement record and a list of candidate Bank records, decide which candidate is the correct match. Compare amounts, dates, and text narrations. If none match confidently, return null for the candidate ID.",
                "target_record": {
                    "amount": float(record_group['r_amount']),
                    "date": str(record_group['r_date']),
                    "reference": mask_pii(record_group['r_ref'])
                },
                "candidates": [{**c, "reference": mask_pii(c["reference"])} for c in candidates_for_prompt]
            }

            payload = {
                "model": "openai/gpt-oss-20b",
                "messages": [
                    {"role": "user", "content": json.dumps(prompt)}
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "match_decision",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "match_candidate_id": {"type": ["string", "null"]},
                                "confidence": {"type": "number"},
                                "reasoning": {"type": "string"},
                                "confidence_breakdown": {
                                    "type": "object",
                                    "properties": {
                                        "amount_similarity_score": {"type": "number"},
                                        "reference_similarity_score": {"type": "number"}
                                    },
                                    "required": ["amount_similarity_score", "reference_similarity_score"],
                                    "additionalProperties": False
                                }
                            },
                            "required": ["match_candidate_id", "confidence", "reasoning", "confidence_breakdown"],
                            "additionalProperties": False
                        },
                        "strict": True
                    }
                }
            }
            
            try:
                # Add a 10-second delay to completely avoid free-tier rate limits!
                time.sleep(10)
                
                response = _call_llm(api_keys, payload)
                result = response.json()
                content = result['choices'][0]['message'].get('content', '')
                if not content:
                    raise ValueError("Empty response from LLM")
                
                content = content.strip()
                if content.startswith("```"):
                    start = content.find("{")
                    end = content.rfind("}")
                    if start != -1 and end != -1:
                        content = content[start:end+1]
                
                decision = json.loads(content)
                _llm_cache[cache_key] = decision
            except Exception as e:
                print(f"LLM call failed for {r_id}: {e}")
                cur.execute(
                    "INSERT INTO exceptions (record_id, reason, detail) VALUES (%s, %s, %s)",
                    (str(r_id), "llm_error", json.dumps({"error": str(e)}))
                )
                continue
            
        # Confidence Gate
        llm_confidence = float(decision.get('confidence', 0.0))
        best_index = decision.get('match_candidate_id')
        
        # Hallucination Guardrail Check
        if best_index and str(best_index) not in candidate_mapping:
            cur.execute(
                "INSERT INTO exceptions (record_id, reason, detail) VALUES (%s, %s, %s)",
                (str(r_id), "llm_hallucination", json.dumps({"error": f"LLM hallucinated candidate ID: {best_index}"}))
            )
            print(f"LLM hallucinated for {r_id}")
            continue

        if best_index and str(best_index) in candidate_mapping:
            best_candidate_id = candidate_mapping[str(best_index)]
            # Find the corresponding candidate's rule score
            candidate = next((c for c in candidates if str(c['b_id']) == best_candidate_id), None)
            if candidate:
                rule_score = candidate['rule_score']
                final_confidence = (rule_score * 0.4) + (llm_confidence * 0.6)
                
                # Format XAI Reasoning
                xai_reasoning = decision.get('reasoning', '')
                if 'confidence_breakdown' in decision:
                    xai_reasoning += f" | XAI Breakdown: Amount Match: {decision['confidence_breakdown']['amount_similarity_score']*100:.0f}%, Ref Match: {decision['confidence_breakdown']['reference_similarity_score']*100:.0f}%"
                
                if final_confidence >= 0.90:
                    # Auto-resolve
                    record_ids = [str(r_id), best_candidate_id, str(candidate['l_id'])]
                    cur.execute(
                        "INSERT INTO matches (record_ids, match_type, confidence, status) VALUES (%s::uuid[], %s, %s, %s) RETURNING id;",
                        (record_ids, "llm", final_confidence, "auto_resolved")
                    )
                    match_id = cur.fetchone()[0]
                    
                    cur.execute(
                        "INSERT INTO audit_log (match_id, decision, llm_reasoning) VALUES (%s, %s, %s)",
                        (match_id, "auto-resolved", xai_reasoning + (f" [Cache Hit]" if cache_key in _llm_cache and _llm_cache[cache_key] == decision and hits > 0 else ""))
                    )
                    print(f"LLM auto-resolved {r_id} with final confidence {final_confidence:.2f}")
                    continue
                    
        # Escalate
        xai_reasoning = decision.get('reasoning', '')
        if 'confidence_breakdown' in decision:
            xai_reasoning += f" | XAI Breakdown: Amount Match: {decision.get('confidence_breakdown', {}).get('amount_similarity_score', 0)*100:.0f}%, Ref Match: {decision.get('confidence_breakdown', {}).get('reference_similarity_score', 0)*100:.0f}%"

        cur.execute(
            "INSERT INTO exceptions (record_id, reason, detail) VALUES (%s, %s, %s)",
            (str(r_id), "ambiguous_match", json.dumps({"llm_reasoning": xai_reasoning, "candidates": len(candidates)}))
        )
        print(f"LLM escalated {r_id}")
            
    print(f"LLM Matcher complete. Cache stats: {hits} hits, {misses} misses.")
    cur.close()
    conn.close()
