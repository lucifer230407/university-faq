# University FAQ - RAG Assistant (Chitkara University)

AI-powered FAQ assistant for **Chitkara University, Rajpura**. Students ask natural-language questions and get grounded answers built over an Azure CosmosDB **MongoDB vCore** knowledge base with vector search, using Azure OpenAI for embeddings and chat.

## Features

- **RAG pipeline** `/api/ask` — question → embedding → vector search (cosine, top-5) → GPT-4.1-mini answer with cited sources.
- **Conversation memory** — multi-turn chat via `session_id` (in-process history, kept to the latest 12 messages).
- **Document ingestion** — upload `.txt`, `.md`, `.json`, or `.pdf` files (course handouts) from the chat UI (upload button in the header) or `POST /api/documents`; automatically chunked, embedded, and stored into the knowledge base.
- **Expanded FAQ data** — 34 seeded documents covering academics, admissions, fees, hostels, exams (incl. re-evaluation, backlogs, hall tickets), placements, transport, campus, anti-ragging, and Ph.D.
- **Authentication** — optional API-key auth via `X-API-Key` header.
- **Rate limiting** — sliding-window limiter per client IP for all protected routes.
- **Frontend** — vanilla HTML/CSS/JS chat UI with suggestion chips, typing indicator, markdown rendering, source tags, "new chat," and API-key input.

## Tech Stack

FastAPI · Uvicorn · Python 3.14 · PyMongo · Azure CosmosDB for MongoDB (vCore, IVF vector index, 1536 dims) · Azure OpenAI (`text-embedding-3-small`, `gpt-4.1-mini`) · Vanilla frontend

## Project Structure

```
university-faq/
├── backend/
│   ├── .env                          # Config (gitignored)
│   ├── requirements.txt
│   ├── data/faqs.json                # 34 seed FAQ entries
│   └── app/
│       ├── main.py                   # FastAPI app (routes below)
│       ├── config.py                 # Centralized settings
│       ├── seed.py                   # Idempotent FAQ re-seed (replaces by source_id)
│       ├── db/documentdb.py          # Mongo client + collections
│       └── services/
│           ├── embeddings.py         # generate_embedding()
│           ├── search.py             # vector search
│           ├── chat.py               # RAG + conversation memory
│           ├── conversations.py      # In-process session store
│           ├── ingestion.py          # extract → chunk → embed → store
│           └── security.py           # API-key auth + rate limiting
└── frontend/
    ├── index.html / style.css / script.js
```

## Environment Variables (`backend/.env`)

```env
DOCUMENTDB_URI=<Azure CosmosDB MongoDB connection string>
AZURE_OPENAI_ENDPOINT=<Azure OpenAI endpoint>
AZURE_OPENAI_API_KEY=<Azure OpenAI API key>
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-small
AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4.1-mini

# Optional. Comma-separated accepted keys; empty disables auth.
API_KEYS=your-secret-key
CONVERSATION_HISTORY_LIMIT=12
RATE_LIMIT_ASK=10
RATE_LIMIT_DOCS=5
RATE_LIMIT_CLEAR=10
RATE_LIMIT_WINDOW=60
MAX_UPLOAD_BYTES=10485760
```

## Running

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# One-time setup (already done on the deployed DB)
python -m app.create_vector_index   # create IVF vector index
python -m app.seed                  # seed/refresh the 34 FAQs

uvicorn app.main:app --reload --port 8000
```

Open `frontend/index.html` in a browser. If `API_KEYS` is set, enter a key via the key icon in the header (stored in `localStorage`).

## API

| Method | Path | Description | Rate limit |
| ------ | ---- | ----------- | ---------- |
| GET | `/api/health` | DB connectivity check | – |
| POST | `/api/ask` | `{question, session_id?}` → `{answer, sources, session_id}` | 10/min |
| POST | `/api/clear` | `{session_id?}` → forget history | 10/min |
| POST | `/api/documents` | Multipart upload `file` + optional `agent_ns` | 5/min |

Protected routes require `X-API-Key` when `API_KEYS` is configured.

```bash
curl -X POST http://localhost:8000/api/ask \
  -H "Content-Type: application/json" -H "X-API-Key: your-secret-key" \
  -d '{"question":"How do I get an exam paper re-evaluated?", "session_id":"abc"}'
```

## Notes / Limitations

- Conversation history lives in process memory (lost on restart / not shared across workers). Swap in Redis or CosmosDB for multi-worker deployments.
- Rate limiting is in-memory and per-IP; use a distributed store (e.g., Redis) for scale.
- `UserWarning` about CosmosDB from PyMongo on startup is harmless.