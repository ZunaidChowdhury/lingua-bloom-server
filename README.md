# 🌸🌱 LinguaBloom Server – AI-Powered English Learning Chatbot (Backend)

> **Little words. Big worlds.** 🌸  
> A high-performance, child-safe FastAPI backend powering **LinguaBloom**, an adaptive English-learning companion designed specifically for children under 7.

LinguaBloom Server combines a **deterministic Python domain core** (for scoring, progression, pacing, and child safety) with a **Groq-accelerated LLM pipeline** (for warm, age-appropriate conversation) to achieve sub-2-second end-to-end response latency.

---

## 🌐 Live URLs & Repositories

| Component | Live Deployment | GitHub Repository |
|---|---|---|
| **Frontend** | [https://lingua-bloom-sigma.vercel.app](https://lingua-bloom-sigma.vercel.app) | [github.com/ZunaidChowdhury/lingua-bloom](https://github.com/ZunaidChowdhury/lingua-bloom) |
| **Backend API** | [https://lingua-bloom-server.onrender.com](https://lingua-bloom-server.onrender.com) | [github.com/ZunaidChowdhury/lingua-bloom-server](https://github.com/ZunaidChowdhury/lingua-bloom-server) |
| **API Docs (Swagger)** | [https://lingua-bloom-server.onrender.com/docs](https://lingua-bloom-server.onrender.com/docs) | — |
| **Health Endpoint** | [https://lingua-bloom-server.onrender.com/health](https://lingua-bloom-server.onrender.com/health) | — |

---

## 📐 System Design & Architecture Document

The comprehensive architecture documentation, decision records (ADRs), threat model, latency budget, and curriculum specifications are located in:

👉 **[`docs/SYSTEM_DESIGN.md`](./docs/SYSTEM_DESIGN.md)**

```mermaid
flowchart LR
  Child([Child / Grown-up]) -->|HTTPS| FE["Next.js App<br/>(Vercel CDN)"]
  FE -->|"Direct HTTPS REST<br/>Bearer Session Token"| API["FastAPI Backend<br/>(Render, Singapore)"]
  API -->|"asyncpg Connection Pool<br/>Supavisor (Port 6543)"| DB[("Supabase PostgreSQL<br/>(Singapore)")]
  API -->|"AsyncGroq SDK<br/>1.5s Hard Timeout"| LLM["Groq LPU Engine<br/>(openai/gpt-oss-120b)"]
  Mon["Uptime Keep-Warm<br/>(Every 5 mins)"] -->|"GET /health"| API
```

### Core Architecture Principles
1. **Hybrid Deterministic Design**: Python makes 100% of the pedagogical decisions (scoring, level progression, mode transitions, and safety checks). The LLM is strictly used for conversational wording within strict guardrails.
2. **Single LLM Call per Turn**: Each user turn triggers at most one structured LLM call with a hard 1.5-second timeout. If the LLM is slow or unavailable, deterministic fallback templates preserve a seamless, sub-2s experience with zero error screens.
3. **Pure Domain Core**: `app/domain` contains zero I/O and zero framework dependencies—pure Python logic, completely unit-tested.
4. **Child Safety by Default**: Anonymous sessions (SHA-256 hashed tokens), PII redaction on inputs, output safety filter, and deterministic support escalation for distress signals.

---

## 🎯 Purpose

Young children learning English need an experience fundamentally different from adults:
- **No Demotion or Stress**: Children never see a "wrong" mark or penalty. Every effort is celebrated with positive reinforcement.
- **Adaptive Modes**: The bot detects when a child wants to learn, chat, hear a story, or needs emotional comfort—ensuring it never forces teaching into every moment.
- **Strict Reading Limits**: Output sentence lengths are strictly bounded by age (Level 1: ≤ 6 words/sentence, Level 2: ≤ 8 words, Level 3: ≤ 12 words).

---

## ✨ Key Features

### 🎓 Progressive 3-Level Curriculum
* **Level 1 (Seedling 🌱)**: Single words, phonics sounds, emoji-rich prompts (Ages 3–4).
* **Level 2 (Growing 🌿)**: 2–3 word phrases, simple sentence building, curiosity questions (Ages 4–5).
* **Level 3 (Blooming 🌸)**: Little story adventures, feelings expression, compound sentences (Ages 5–7).
* **Mastery Engine**: Evaluates attempts in a rolling window. Advancement requires multi-skill mastery without demoting on mistakes.

### 🎭 Child Mode Detection & Pacing
* **Learning Mode**: Canonical curriculum item quizzes attached deterministically by Python.
* **Conversation Mode**: Open-ended friendly chat about pets, favorite foods, weather, and toys.
* **Engagement Mode**: Rhymes, imaginative stories, silly animal sounds, and playful riddles.
* **Support Mode**: Gentle social-emotional listening (SEL). If sadness or fatigue is detected, active quizzes are preempted to offer comfort.
* **Pacing Guardrail**: Maximum 3 consecutive learning turns before offering a playful break.

### 🛡️ Privacy & Child Safety
* **Zero Personal Identifiable Information (PII)**: No email, passwords, real names, or locations.
* **Regex Redaction**: Automatic redaction of phone numbers, emails, and address patterns.
* **Prompt Injection Defense**: User messages are treated as untrusted strings wrapped in boundary tags.
* **Distress Escalation**: Deterministic empathetic message directing child to a trusted grown-up with zero LLM call.
* **Instant Data Deletion**: `DELETE /v1/sessions/me` wipes the child's session, progress, and history immediately.

### ⚡ Low-Latency Engineering (< 2s SLA)
* **Same-Region Hosting**: Render service and Supabase database both deployed in Singapore (`ap-southeast-1`).
* **Connection Pooling**: `asyncpg` with Supabase Supavisor transaction pooler.
* **Direct Browser-to-API**: Browser chats directly with FastAPI (no Next.js proxy overhead).
* **In-Memory Per-Session Locks**: Prevents turn race conditions and out-of-order responses.

---

## 🛠️ Tech Stack

* **Language**: Python 3.12
* **Framework**: FastAPI 0.143+
* **Validation & Settings**: Pydantic v2, `pydantic-settings`
* **ASGI Server**: Uvicorn (Single Worker)
* **LLM Engine**: Groq Cloud SDK (`AsyncGroq`)
* **Database Driver**: `asyncpg` (PostgreSQL 15+ on Supabase)
* **Linting & Types**: Ruff (formatting & linting), Mypy (strict type checking)
* **Testing**: Pytest, Pytest-Asyncio, HTTPX

---

## 📦 Python Dependencies

From [`requirements.txt`](./requirements.txt):

```txt
fastapi==0.143.3
uvicorn[standard]==0.54.0
pydantic==2.14.1
pydantic-settings==2.16.0
asyncpg==0.32.0
groq==1.7.0
httpx==0.28.1
pytest==9.1.1
pytest-asyncio==1.4.0
ruff==0.17.1
mypy==2.4.0
```

---

## 🚀 Installation & Local Setup

### 1. Prerequisites
* Python 3.12+
* Git
* A Supabase PostgreSQL instance (or local PostgreSQL)
* A Groq API key

### 2. Clone the Repository

```bash
git clone https://github.com/ZunaidChowdhury/lingua-bloom-server.git
cd lingua-bloom-server
```

### 3. Set Up Virtual Environment

On Windows (PowerShell):
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

On macOS / Linux:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create your `.env` file based on `.env.example`:

```bash
cp .env.example .env
```

Fill in the required values:

```env
# Groq API key from https://console.groq.com
GROQ_API_KEY=your_groq_api_key_here

# Groq Model ID (e.g. openai/gpt-oss-120b or qwen/qwen3-8b-27b)
GROQ_MODEL=openai/gpt-oss-120b

# Supabase PostgreSQL Connection String (Transaction Pooler, port 6543)
DATABASE_URL=postgresql://postgres.xxx:your_password@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres

# Allowed frontend origin for CORS
FRONTEND_ORIGIN=http://localhost:3000

# Application Settings
LOG_LEVEL=INFO
LLM_TIMEOUT_S=1.5
ADMIN_KEY=your_admin_secret_key
```

### 5. Apply Database Migrations

Run the automated migration runner to create all required tables:

```powershell
python scripts/apply_migrations.py
```

### 6. Start the Local Server

```powershell
python -m uvicorn app.main:app --reload --port 8000
```

* API will be available at: `http://localhost:8000`
* Interactive API Documentation (Swagger): `http://localhost:8000/docs`
* Health Check: `http://localhost:8000/health`

---

## 🚢 Production Deployment (Render)

1. **Create Web Service on Render**:
   - Environment: `Python 3`
   - Region: `Singapore (Southeast Asia)`
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT`
2. **Set Environment Variables in Render Dashboard**:
   - `GROQ_API_KEY`: Groq API key
   - `GROQ_MODEL`: `openai/gpt-oss-120b` (or preferred model)
   - `DATABASE_URL`: Supabase Transaction Pooler connection string (port 6543)
   - `FRONTEND_ORIGIN`: `https://lingua-bloom-sigma.vercel.app`
   - `LLM_TIMEOUT_S`: `1.5`
   - `LOG_LEVEL`: `INFO`
   - `ADMIN_KEY`: Generated secret key
3. **Database Migrations on Supabase**:
   - Run `python scripts/apply_migrations.py` with your production `DATABASE_URL`.
4. **Keep-Warm Setup**:
   - Configure a free monitor (e.g., Cron-Job.org / UptimeRobot) to ping `https://lingua-bloom-server.onrender.com/health` every 5 minutes to prevent Render free-tier spin-down.

---

## 🧪 Testing & Verification

The test suite contains **640+ unit and API tests** running against `FakeLLM` and an in-memory repository without requiring live credentials:

```powershell
# Run full test suite
pytest -m "not integration"

# Run with verbose output
pytest -v

# Run lint and code format check
ruff check .

# Run strict type checking
mypy app
```

---

## 📡 Core API Reference

| Method | Endpoint | Description | Auth Required |
|---|---|---|---|
| `GET` | `/health` | Service liveness probe | No |
| `GET` | `/ready` | Database & LLM readiness check | No |
| `POST` | `/v1/sessions` | Create anonymous child session | No |
| `GET` | `/v1/sessions/me` | Fetch active session & nickname | Bearer Token |
| `DELETE` | `/v1/sessions/me` | Delete all child data & history | Bearer Token |
| `POST` | `/v1/chat/turns` | Process conversation / quiz turn | Bearer Token |
| `GET` | `/v1/progress` | Fetch current level & stars progress | Bearer Token |

---

## 👨‍💻 Author

**Zunaid Chowdhury**  
*Full Stack & AI Engineer*  
GitHub: [@ZunaidChowdhury](https://github.com/ZunaidChowdhury)

---

## ⭐ Star the Project

If you find LinguaBloom helpful or inspiring, please give the repositories a star! 🌟

---

## 📸 Preview

<div align="center">
  <img src="./lingua-bloom-chat.png" width="100%" alt="LinguaBloom Chat Interface" />
</div>

