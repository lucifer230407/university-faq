import io
import time

from pypdf import PdfReader

from app.config import settings
from app.db.documentdb import db
from app.services.embeddings import generate_embedding

TEXT_EXTENSIONS = {".txt", ".text", ".md", ".json"}
PDF_EXTENSION = ".pdf"


def extract_text(filename: str, data: bytes) -> str:
    """Extract plain text from an uploaded file based on its extension."""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    ext = f".{ext}"

    if ext in TEXT_EXTENSIONS:
        return data.decode("utf-8", errors="replace").strip()

    if ext == PDF_EXTENSION:
        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages).strip()

    raise ValueError(
        f"Unsupported file type '{ext or 'unknown'}'. "
        "Supported: .txt, .md, .json, .pdf"
    )


def chunk_text(text: str, size: int = None, overlap: int = None) -> list[str]:
    """
    Split text into overlapping chunks on paragraph boundaries.

    Falls back to hard character cuts for very long paragraphs.
    """
    size = size or settings.CHUNK_SIZE
    overlap = overlap or settings.CHUNK_OVERLAP

    if len(text) <= size:
        return [text] if text.strip() else []

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []

    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 2 <= size:
            current = f"{current}\n\n{para}".strip()
            continue

        if current:
            chunks.append(current)

        # Split overly long paragraphs at word boundaries.
        while len(para) > size:
            cut = para.rfind(" ", 0, size)
            if cut == -1:
                cut = size
            chunks.append(para[:cut])
            para = para[cut:].strip()
            if para:
                para = para[overlap:].strip()

        current = para

    if current:
        chunks.append(current)

    return chunks


def ingest_document(filename: str, data: bytes, agent_ns: str = "knowledge_base") -> int:
    """
    Extract, chunk, embed, and store a document into the 'documents' collection.

    Returns the number of chunks inserted.
    """
    text = extract_text(filename, data)
    if not text:
        raise ValueError("No readable text found in the uploaded file.")

    chunks = chunk_text(text)
    if not chunks:
        raise ValueError("Document produced no text chunks.")

    # De-duplicate: remove previously ingested chunks for the same file.
    db["documents"].delete_many({"metadata.filename": filename})

    collection = db["documents"]
    for i, chunk in enumerate(chunks, start=1):
        vector = generate_embedding(chunk)
        collection.insert_one({
            "text": chunk,
            "vector": vector,
            "metadata": {
                "agent_ns": agent_ns or "knowledge_base",
                "source_id": f"upload:{filename}",
                "filename": filename,
                "chunk_index": i,
                "chunk_count": len(chunks),
            },
        })
        time.sleep(0.1)

    return len(chunks)