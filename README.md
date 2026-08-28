# 🚀 AI Finance Controller (Settlement Reconciliation Agent)

**Razorpay AI Buildathon | Track 04: AI Finance Controller**

A production-grade, agentic AI Finance Controller built to solve the complex problem of multi-way settlement reconciliation. This system ingests data from Razorpay, Bank Statements, and Internal Merchant Ledgers, automatically matching them using a multi-stage pipeline. 

When exceptions occur, it doesn't just flag them—an **Action Orchestrator** agent dynamically generates the precise operational payload needed to close the loop (e.g., emailing the merchant for proof, pinging an internal Slack channel, or creating a ledger adjustment).

---

## ✨ Key Features

- **🧠 Multi-Stage Matching Engine:**
  - **Stage 1 (Deterministic):** Fast, exact-match rules for perfect 1:1:1 reconciliations.
  - **Stage 2 (Fuzzy):** Handles slight date drifts and minor spelling variations.
  - **Stage 3 (LLM-Assisted):** Leverages `openai/gpt-oss-20b` (via Groq API) to resolve complex, ambiguous anomalies using reasoning (e.g., partial amount matches, transposed references).
- **⚡ High-Throughput Async Processing:** Uses `asyncio`, `httpx.AsyncClient`, and semaphores to concurrently process LLM requests while gracefully handling rate limits, completely bypassing synchronous bottlenecks.
- **🔐 Enterprise PII Vault:** Ensures total financial data privacy. Sensitive data (UTRs, Account Numbers) is intercepted and replaced with `{{SECURE_TOKEN}}` before ever reaching the LLM. 
- **🤖 Action Orchestrator (Closing the Loop):** Automatically analyzes unresolved exceptions and uses Structured JSON Outputs to generate actionable recovery payloads (Slack pings, Email drafts, Ledger adjustments).
- **📊 "Honest Exception" Dashboard:** A beautiful React/Vite dashboard displaying analytics, raw data, compliance audit logs, and an actionable exception queue featuring the AI-generated recovery payloads.

---

## 🛠️ Architecture & Tech Stack

- **Backend:** Python, FastAPI, PostgreSQL (via Docker)
- **Frontend:** React, Vite, Tailwind CSS, Recharts, Lucide Icons
- **AI/LLM:** Groq API (`openai/gpt-oss-20b`) with strict JSON Schema outputs
- **Infrastructure:** Docker Compose

---

## 🚀 Getting Started

### 1. Initial Setup
Clone the repository and set up your environment variables:
```bash
# Clone the repository
git clone https://github.com/Rutwik-M/ai-finance-controller.git
cd ai-finance-controller

# Setup environment variables
cp .env.example .env

# Add your Groq API Keys to .env
# GROQ_API_KEY=your_key_here
# GROQ_API_KEY_2=your_key_2_here
```

### 2. Start the Infrastructure (Database & API)
Run the docker compose stack in the background:
```bash
docker-compose up -d db api
```

### 3. Initialize the Database
Apply the database migrations to set up the schema:
```bash
# Activate your local python environment (if you have one)
source .venv/bin/activate
pip install -r requirements.txt

# Run the database migration
python -m src.db.migrate
```

### 4. Run the Pipeline (Data Gen & Matching)
Generate a synthetic batch of messy transaction data and run it through the complete agentic pipeline:
```bash
# 1. Generate 50 messy synthetic records
python data/generator.py --records 50 --out temp_data

# 2. Ingest them into the PostgreSQL database
python -m src.ingestion.load

# 3. Run the Multi-Stage Matching & Action Orchestrator
python -m src.matching.run
```

### 5. Launch the Dashboard
Start the React frontend to view the results:
```bash
cd dashboard
npm install
npm run dev
```
Navigate to **`http://localhost:5173`** to interact with the system!

---

## 🔍 How it Works (The Workflow)

1. **Ingestion:** Data is loaded from Razorpay, Bank, and Ledger sources into the DB.
2. **Matching Pipeline:** The deterministic and fuzzy engines instantly match identical records. 
3. **LLM Resolution:** Ambiguous records are passed to the Groq API (with PII masked) for advanced reasoning.
4. **Agentic Orchestration:** Any records that are still unresolved are flagged as `exceptions`. The Orchestrator agent reads these and generates a structured JSON action payload to recover the situation.
5. **Dashboard Audit:** The FinOps team logs into the dashboard, reviews the "Actionable Queue", sees the AI's recommended action (e.g., "Email Merchant"), and clicks **Execute Action**. The loop is closed!

---
*Built with ❤️ for the Razorpay AI Buildathon.*
