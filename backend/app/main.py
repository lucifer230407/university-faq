import logging

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.config import settings
from app.db.documentdb import test_connection
from app.services.auth import (
    authenticate_user,
    create_access_token,
    login_enabled,
    public_user,
    register_user,
    require_auth,
    signup_enabled,
)
from app.services.chat import ask, clear_conversation
from app.services.ingestion import ingest_document
from app.services.security import rate_limit

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("university-faq")

if not settings.DOCUMENTDB_URI or not settings.AZURE_OPENAI_API_KEY:
    logger.warning(
        "Missing DOCUMENTDB_URI or AZURE_OPENAI_API_KEY — /api/* will fail at runtime. "
        "Check backend/.env"
    )

app = FastAPI(
    title="Chitkara University FAQ API",
    description=(
        "AI-powered FAQ assistant for Chitkara University, Rajpura. Answers are "
        "grounded on the university knowledge base plus optional live web search."
    ),
    version="1.2.0",
)

# --- CORS ---
# "*" origin (dev) rejects credentialed browsers, so credentials are only enabled
# for an explicit allow-list.
origins = settings.cors_origins
is_wildcard = "*" in origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=not is_wildcard,
    allow_methods=["*"],
    allow_headers=["*"],
)


class QuestionRequest(BaseModel):
    question: str = Field(..., max_length=500, min_length=1)
    session_id: str | None = None


class ClearRequest(BaseModel):
    session_id: str | None = None


class SourceItem(BaseModel):
    text: str
    metadata: dict
    score: float


class AnswerResponse(BaseModel):
    answer: str
    sources: list[SourceItem]
    session_id: str


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=200)


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=8, max_length=200)
    name: str = Field(default="", max_length=80)


class UserInfo(BaseModel):
    username: str
    name: str
    role: str


class UserResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserInfo


@app.get("/api/health")
def health_check():
    """Check if the API and database are running."""
    try:
        test_connection()
        return {
            "status": "healthy",
            "database": "connected",
            "web_search": settings.WEB_SEARCH_ENABLED
            and settings.WEB_SEARCH_PROVIDER != "none",
        }
    except Exception as e:
        # Log the detail server-side but keep the response generic so internal
        # hostnames/topology info isn't leaked to clients.
        logger.error("Health check failed: %s", e)
        return {"status": "unhealthy", "database": "disconnected"}


@app.get("/api/auth/status")
def auth_status():
    """Report whether authentication is required / how to authenticate."""
    return {
        "auth_enabled": settings.auth_enabled,
        "login_enabled": login_enabled(),
        "signup_enabled": signup_enabled(),
        "methods": {
            "jwt": bool(settings.JWT_SECRET),
            "api_key": bool(settings.api_keys),
        },
    }


@app.post("/api/auth/login", response_model=UserResponse)
def login(request: LoginRequest):
    """Authenticate with username/password and return a JWT access token."""
    if not login_enabled():
        raise HTTPException(
            status_code=403,
            detail="JWT login is not configured. Set JWT_SECRET and ADMIN_USERNAME/ADMIN_PASSWORD.",
        )
    user = authenticate_user(request.username, request.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    token = create_access_token(user["username"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "user": public_user(user),
    }


@app.post(
    "/api/auth/register",
    response_model=UserResponse,
    dependencies=rate_limit("register"),
)
def register(request: RegisterRequest):
    """Create a new standard account and return a JWT access token."""
    if not signup_enabled():
        raise HTTPException(
            status_code=403,
            detail="Sign-up is disabled on this server.",
        )
    try:
        user = register_user(
            username=request.username,
            password=request.password,
            name=request.name,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    token = create_access_token(user["username"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "user": public_user(user),
    }


@app.get("/api/auth/me", response_model=UserInfo)
def auth_me(user: dict = Depends(require_auth)):
    """Return the currently authenticated user."""
    return public_user(user)


@app.post("/api/ask", response_model=AnswerResponse, dependencies=[Depends(require_auth), *rate_limit("ask")])
def ask_question(request: QuestionRequest):
    """Answer a student's question using RAG with conversation memory."""
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    try:
        return ask(request.question, session_id=request.session_id)
    except Exception:
        # Log the detail server-side; keep the client response generic.
        logger.exception("/api/ask failed")
        raise HTTPException(status_code=500, detail="There was an error processing your question.")


@app.post("/api/clear", dependencies=[Depends(require_auth), *rate_limit("clear")])
def clear_session(request: ClearRequest):
    """Forget the conversation history for a session."""
    clear_conversation(request.session_id)
    return {"status": "cleared", "session_id": request.session_id or "default"}


@app.post(
    "/api/documents",
    dependencies=[Depends(require_auth), *rate_limit("documents")],
)
async def upload_document(
    file: UploadFile,
    agent_ns: str = Form(default="knowledge_base", max_length=80),
):
    """Ingest a text/PDF document into the knowledge base."""
    # Stream the upload in chunks and reject early once the size cap is hit,
    # instead of buffering arbitrarily large files in memory first.
    max_bytes = settings.MAX_UPLOAD_BYTES
    data = bytearray()
    while True:
        chunk = await file.read(1024 * 512)
        if not chunk:
            break
        data.extend(chunk)
        if max_bytes and len(data) > max_bytes:
            limit_mb = max_bytes // (1024 * 1024)
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Maximum size is {limit_mb} MB.",
            )

    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")

    try:
        chunk_count = ingest_document(file.filename, bytes(data), agent_ns)
    except ValueError as e:
        # Expected client errors (bad file type, no text) — safe to surface.
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("/api/documents failed")
        raise HTTPException(status_code=500, detail="There was an error ingesting the document.")

    return {
        "status": "ingested",
        "filename": file.filename,
        "chunks": chunk_count,
        "agent_ns": agent_ns,
    }


# Optional: serve the frontend from the same origin so no CORS is involved.
if settings.STATIC_DIR:
    import os

    from fastapi.staticfiles import StaticFiles

    static = os.path.abspath(settings.STATIC_DIR)
    if os.path.isdir(static):
        logger.info("Serving frontend from %s at /", static)
        app.mount("/", StaticFiles(directory=static, html=True), name="static")
    else:
        logger.warning("STATIC_DIR %s not found; not serving static files", static)