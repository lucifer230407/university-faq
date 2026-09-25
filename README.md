# University FAQ - RAG Assistant (Chitkara University)

AI-powered FAQ assistant for **Chitkara University, Rajpura**. Students ask natural-language questions and get grounded answers built over an Azure CosmosDB **MongoDB vCore** knowledge base with vector search, using Azure OpenAI for embeddings and chat. When the local knowledge base has no answer (or you ask about current info), the assistant **searches the live web** for up-to-date Chitkara University information and cites the pages it used.

🌐 **Live Production URL**: [https://chitkara-faq-assistant.azurewebsites.net](https://chitkara-faq-assistant.azurewebsites.net)


## Features

- **RAG pipeline** `/api/ask` — question → embedding → vector search (cosine, top-5) → GPT-4.1-mini answer with cited sources.
- **Web grounding** — optional live web search (DuckDuckGo / Bing API / Wikipedia) for current, uncovered, or transferred topics. Top pages are fetched, their text added to the prompt, and shown as clickable source links in the chat UI.
- **Help-desk email fallback** — when the RAG system has nothing reliable to ground an answer on (nothing clears the similarity threshold and no web context exists, or the model explicitly says it cannot answer), the chat offers a **Contact Help Desk** button. It generates a professional email draft from the student's question, shows a preview for review, and only sends it to the configured `HELPDESK_EMAIL` over SMTP **after the user explicitly confirms**. Credentials never reach the frontend.
- **Redesigned Stitch Editorial Frontend** — elegant modern UI using Tailwind CSS with an academic typography scale (**EB Garamond** display headings and **Plus Jakarta Sans** body), refined university color palette, smooth micro-interactions, responsive drawer, and Material Symbols.
- **Live RAG Trace & Inspector** — side panel revealing real-time cosine similarity scores, matched chunk excerpts, top-k ranking, and retrieval/generation latency for full auditability and transparency.
- **System Health & Latency Monitor** — live status badge measuring real-time `/api/health` round-trip latency and Cosmos DB connection state.
- **Interactive Developer Workbench** — switchable live curl command snippets for `/api/ask`, `/api/documents`, and `/api/health` right in the UI.
- **Conversation memory** — multi-turn chat via `session_id` (latest 12 messages). Follow-ups are rewritten into standalone search queries using the history before retrieval. Optional Redis backend shares history across workers/restarts.
- **Admin-Gated Document Ingestion & Source Verification** — upload `.txt`, `.md`, `.json`, or `.pdf` files (course handouts); documents are automatically chunked, embedded, and tagged. Strictly restricted to administrators (`role: admin`) with untrusted sources filtered out by `is_official_source()` to prevent knowledge poisoning.
- **Expanded FAQ data** — 34 seeded documents covering academics, admissions, fees, hostels, exams, placements, transport, campus, anti-ragging, and Ph.D.
- **Authentication** — username/password login via `POST /api/auth/login` issuing signed JWT access tokens (HS256). Anyone can self-register via `POST /api/auth/register` when `ALLOW_SIGNUP=true` (default); the env-defined `ADMIN_USERNAME`/`ADMIN_PASSWORD` admin needs no seed step, and extra users can be stored in the `users` collection via `scripts/create_user.py`. Protected routes accept `Authorization: Bearer <token>`; the legacy `X-API-Key` header keeps working for scripts and automated access.
- **Rate limiting** — sliding-window limiter per client IP with proper `X-Forwarded-For` handling behind trusted proxies; optional Redis for distributed limiting.
- **Markdown & Security** — chat messages render GitHub-flavored markdown via `marked` with strict sanitization via `DOMPurify` to prevent XSS.

## Tech Stack

FastAPI · Uvicorn · Python 3.14 · PyMongo · Azure CosmosDB for MongoDB (vCore, IVF vector index, 1536 dims) · Azure OpenAI (`text-embedding-3-small`, `gpt-4.1-mini`) · Tailwind CSS & Material Symbols · httpx web search · JWT (PyJWT, HS256) · Optional Redis

## Project Structure

```
university-faq/
├── docker-compose.yml              # API + optional Redis
├── backend/
│   ├── .env                        # Config (gitignored)
│   ├── .env.example                # Documented config template (commit this)
│   ├── requirements.txt / requirements-dev.txt
│   ├── data/faqs.json              # 34 seed FAQ entries
│   ├── Dockerfile
│   ├── app/
│   │   ├── main.py                 # FastAPI app (routes below)
│   │   ├── config.py               # Typed settings (pydantic-settings)
│   │   ├── seed.py                 # Idempotent FAQ re-seed (replaces by source_id)
│   │   ├── db/documentdb.py        # Mongo client + collections
│   │   └── services/
│   │       ├── auth.py            # JWT login, password hashing, admin verification
│   │       ├── embeddings.py       # generate_embedding()
│   │       ├── search.py           # vector search + source verification
│   │       ├── web_search.py       # web grounding (search + page fetch)
│   │       ├── chat.py             # RAG + conversation memory + web grounding
│   │       ├── helpdesk_email.py   # email draft generation + SMTP sending
│   │       ├── conversations.py    # session store (memory or Redis)
│   │       ├── ingestion.py        # extract → chunk (overlap) → embed → store
│   │       └── security.py         # API-key auth + rate limiting (Redis-capable)
│   ├── scripts/                    # Dev/ops tools
│   │   ├── create_user.py          # python -m scripts.create_user --username alice ...
│   │   ├── create_vector_index.py  # python -m scripts.create_vector_index
│   │   └── ...                     # ad-hoc debug scripts (vector_search, etc.)
│   └── tests/                      # pytest suite (mocked Mongo/OpenAI/web/trust)
└── frontend/
    ├── index.html                  # Redesigned Stitch editorial layout & RAG inspector
    ├── style.css                   # Custom styles, animations & design token overrides
    └── script.js                   # Chat logic, session sync, live health, RAG inspector
```

## Environment Variables (`backend/.env` — template in `backend/.env.example`)

```env
DOCUMENTDB_URI=<Azure CosmosDB MongoDB connection string>
AZURE_OPENAI_ENDPOINT=<Azure OpenAI endpoint>
AZURE_OPENAI_API_KEY=<Azure OpenAI API key>
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-small
AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4.1-mini

# JWT login. Generate JWT_SECRET with: python -c "import secrets;print(secrets.token_urlsafe(48))"
JWT_SECRET=<random secret>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480
# Bootstrap admin account (verified at request time; no seed step needed).
ADMIN_USERNAME=admin
ADMIN_PASSWORD=change-me

# Allow anyone to create an account via POST /api/auth/register (role "user").
ALLOW_SIGNUP=true

# Optional. Comma-separated accepted keys; empty disables API-key auth.
API_KEYS=your-secret-key
CONVERSATION_HISTORY_LIMIT=12
RATE_LIMIT_ASK=10
RATE_LIMIT_DOCS=5
RATE_LIMIT_CLEAR=10
RATE_LIMIT_WINDOW=60
MAX_UPLOAD_BYTES=10485760
CHUNK_SIZE=800
CHUNK_OVERLAP=100
# Drop retrieval hits below this similarity score before prompt building.
SIMILARITY_THRESHOLD=0.30
VECTOR_INDEX_DIMENSIONS=1536
VECTOR_INDEX_NUMLISTS=16

GPT_TEMPERATURE=0.3
GPT_MAX_TOKENS=1024
LOG_LEVEL=INFO

# CORS -- "*" for dev; set your frontend origin in production.
CORS_ORIGINS=*
# Serve the frontend at "/" so no CORS is needed (set in Dockerfile).
# STATIC_DIR=../frontend
# Only trust X-Forwarded-For from these proxy IPs, else the socket address is used.
# TRUSTED_PROXY_IPS=10.0.0.4

# --- Web search grounding ---
WEB_SEARCH_PROVIDER=duckduckgo    # duckduckgo | bing | wikipedia | none
WEB_SEARCH_ENABLED=true
WEB_SEARCH_FALLBACK=true          # only search the web when local finds nothing
WEB_PAGE_FETCH_ENABLED=true
WEB_PAGE_FETCH_LIMIT=3
WEB_PAGE_FETCH_MAX_BYTES=12000
WEB_SEARCH_RESULT_LIMIT=5
# BING_SEARCH_API_KEY=            # required only for WEB_SEARCH_PROVIDER=bing

# Optional Redis: shared conversation memory + distributed rate limiting.
# REDIS_URL=redis://localhost:6379/0

# --- Help desk email / SMTP fallback ---
# Used by the optional "Contact Help Desk" flow. When the RAG system cannot
# answer, the user can draft + confirm an email that is sent to HELPDESK_EMAIL.
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USE_TLS=true          # STARTTLS; set false for implicit TLS (port 465)
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-app-password
HELPDESK_EMAIL=helpdesk@example.com
EMAIL_SEND_TIMEOUT=15
EMAIL_SIGNATURE_NAME=University FAQ Assistant User
# Rate limits for the email endpoints
RATE_LIMIT_DRAFT=10
RATE_LIMIT_SEND=5
```

## Running

### Local (dev)

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt

# One-time setup (already done on the deployed DB)
python -m scripts.create_vector_index   # create/replace IVF vector index
python -m app.seed                      # seed/refresh the 34 FAQs

uvicorn app.main:app --reload --port 8000
```

Open `frontend/index.html` in a browser, or set `STATIC_DIR=../frontend` in `.env` and open `http://localhost:8000`. If authentication is enabled, sign in with the `ADMIN_USERNAME`/`ADMIN_PASSWORD` account via the user icon (the token is stored in `localStorage`).

### Docker

```bash
docker compose up --build
# => http://localhost:8000 (frontend + API, Redis-backed memory/limits)
```

## Tests

```bash
cd backend
python -m pytest tests -q      # Unit & integration test suite (mocked Mongo/OpenAI/web)
```

## API

| Method | Path | Description | Access | Rate limit |
| ------ | ---- | ----------- | ------ | ---------- |
| GET | `/api/health` | DB connectivity + web-search status | Public | – |
| GET | `/api/auth/status` | Auth mode (JWT/API-key) and whether login is enabled | Public | – |
| POST | `/api/auth/login` | `{username, password}` → `{access_token, user}` (JWT) | Public | – |
| POST | `/api/auth/register` | `{username, password, name?}` → `{access_token, user}` | Public | 5/min |
| GET | `/api/auth/me` | Currently authenticated user info | Bearer token | – |
| POST | `/api/ask` | `{question, session_id?}` → `{answer, sources, session_id, email_available, email_required}` | Authenticated | 10/min |
| POST | `/api/clear` | `{session_id?}` → forget conversation history | Authenticated | 10/min |
| POST | `/api/documents` | Multipart upload `file` + optional `agent_ns` | **Admin only** | 5/min |
| POST | `/api/email/draft` | `{question}` → `{success, email:{to, subject, body}}` | Authenticated | 10/min |
| POST | `/api/email/send` | `{subject, body}` → `{success, message}` (recipient is always the configured `HELPDESK_EMAIL`) | Authenticated | 5/min |

Protected routes require `Authorization: Bearer <token>` (from `/api/auth/login`) or, for backwards compatibility, an `X-API-Key` header when `API_KEYS` is configured. Auth is verified before the rate limiter runs, so anonymous callers cannot exhaust user budgets.

```bash
# 1. Get a token
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"change-me"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 2. Use it
curl -X POST http://localhost:8000/api/ask \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" \
  -d '{"question":"How do I get an exam paper re-evaluated?", "session_id":"abc"}'
```

Add extra users (stored hashed in the `users` collection):

```bash
cd backend
python -m scripts.create_user --username alice --password 's3cret' --name 'Alice Singh'
```

Or let users self-register from the UI / API (see `ALLOW_SIGNUP`): new accounts get the `user` role automatically.

Web-sourced answers include `sources[]` entries with `metadata.kind = "web"`,
`metadata.source_url`, and `metadata.title`; the frontend renders them as links and displays them in the Live RAG Inspector.

## Help-desk email fallback

When `/api/ask` returns `email_available: true`, the frontend offers a
**Contact Help Desk** button. This only happens when (a) no local retrieval hit
cleared `SIMILARITY_THRESHOLD` and no web context was found, or (b) the model
explicitly said it lacks the information — a single low-score hit never
triggers an email.

The flow is opt-in: **Draft Email** → reviewer sees `To`/`Subject`/`Body` →
**Send Email** sends over SMTP to the configured `HELPDESK_EMAIL` (the client
can never choose the recipient). SMTP credentials are read from the environment
only, are never returned by the API, and are never logged (on failure only the
exception type is recorded). See `.env.example` for Gmail/Outlook settings.

### Configuring Gmail / Outlook

- **Gmail (port 587, STARTTLS):** `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`,
  `SMTP_USERNAME` = your Gmail address, `SMTP_PASSWORD` = a 16-character
  **App Password** generated at https://myaccount.google.com/apppasswords
  (2-Step Verification must be enabled; your normal account password will not
  work).
- **Outlook / Office 365:** `SMTP_HOST=smtp.office365.com`, `SMTP_PORT=587`,
  `SMTP_PASSWORD` = your account (or app) password.
- **Local testing without a real inbox:** run a debug server such as MailHog
  (`docker run -d -p 1025:1025 -p 8025:8025 mailhog/mailhog`) and point
  `SMTP_HOST=smtp.test.local`/`SMTP_HOST=localhost`, `SMTP_PORT=1025`,
  `SMTP_USERNAME`/`SMTP_PASSWORD` to any value, `HELPDESK_EMAIL` to any address,
  then open http://localhost:8025 to read the captured mail.

## Notes / Limitations

- Conversation history and rate limits are in-memory by default (lost on restart / not shared across workers). Set `REDIS_URL` (see `docker-compose.yml`) to make both distributed.
- Web grounding defaults to DuckDuckGo's free HTML endpoint — no API key, but it's an unofficial endpoint. For production use, set `WEB_SEARCH_PROVIDER=bing` and provide `BING_SEARCH_API_KEY` (Azure resource).
- JWT tokens expire after `ACCESS_TOKEN_EXPIRE_MINUTES`; the frontend silently re-prompts for sign-in on 401. For a production multi-user deployment set `ALLOW_SIGNUP=false` (or restrict the `users` collection) so only admin-created accounts can sign in.
- Handout ingestion is strictly restricted to administrator accounts, and knowledge retrieval ignores untrusted submissions.
- `UserWarning` about CosmosDB from PyMongo on startup is harmless.
- `backend/.env` is gitignored and must never be committed; rotate the CosmosDB/OpenAI credentials immediately if the file is ever exposed.