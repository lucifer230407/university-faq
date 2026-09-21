from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import settings
from app.db.documentdb import test_connection
from app.services.chat import ask, clear_conversation
from app.services.ingestion import ingest_document
from app.services.security import api_key_dependency, rate_limit


app = FastAPI(
    title="Chitkara University FAQ API",
    description="AI-powered FAQ assistant for Chitkara University, Rajpura",
    version="1.1.0"
)

# Allow frontend to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class QuestionRequest(BaseModel):
    question: str
    session_id: str | None = None


class SourceItem(BaseModel):
    text: str
    metadata: dict
    score: float


class AnswerResponse(BaseModel):
    answer: str
    sources: list[SourceItem]
    session_id: str


@app.get("/api/health")
def health_check():
    """Check if the API and database are running."""
    try:
        test_connection()
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "database": str(e)}


@app.get("/api/auth/status")
def auth_status():
    """Report whether API-key authentication is required."""
    return {"auth_enabled": settings.auth_enabled}


@app.post("/api/ask", response_model=AnswerResponse, dependencies=api_key_dependency() + rate_limit("ask"))
def ask_question(request: QuestionRequest):
    """Answer a student's question using RAG with conversation memory."""
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    try:
        return ask(request.question, session_id=request.session_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/clear", dependencies=api_key_dependency() + rate_limit("clear"))
def clear_session(request: QuestionRequest):
    """Forget the conversation history for a session."""
    clear_conversation(request.session_id)
    return {"status": "cleared", "session_id": request.session_id or "default"}


@app.post(
    "/api/documents",
    dependencies=api_key_dependency() + rate_limit("documents"),
)
async def upload_document(
    file: UploadFile,
    agent_ns: str = Form(default="knowledge_base"),
):
    """Ingest a text/PDF document into the knowledge base."""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")
    if settings.MAX_UPLOAD_BYTES and len(data) > settings.MAX_UPLOAD_BYTES:
        limit_mb = settings.MAX_UPLOAD_BYTES // (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {limit_mb} MB.",
        )

    try:
        chunk_count = ingest_document(file.filename, data, agent_ns)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "ingested",
        "filename": file.filename,
        "chunks": chunk_count,
        "agent_ns": agent_ns,
    }