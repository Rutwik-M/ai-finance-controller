import sys
from .deterministic import run_deterministic_matching
from .fuzzy import run_fuzzy_matching
from .llm import resolve_with_llm
from .orchestrator import run_orchestrator

def main():
    print("=== Stage 1: Deterministic Matching ===")
    run_deterministic_matching()
    
    print("\n=== Stage 2: Fuzzy Matching ===")
    ambiguous_candidates = run_fuzzy_matching()
    
    if ambiguous_candidates:
        print(f"\n=== Stage 3: LLM-Assisted Matching ({len(ambiguous_candidates)} candidates) ===")
        resolve_with_llm(ambiguous_candidates)
    else:
        print("\n=== Stage 3: LLM-Assisted Matching ===")
        print("No ambiguous candidates to send to LLM.")
        
    print("\n=== Stage 4: Agentic Orchestrator (Action Recovery) ===")
    run_orchestrator()
    
    print("\nMatching pipeline complete.")

if __name__ == "__main__":
    main()
