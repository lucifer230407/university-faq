import io
import json
import re
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
        if ext == ".json":
            # Flatten the JSON structure instead of dumping raw object syntax.
            return _flatten_json(data)
        return data.decode("utf-8", errors="replace").strip()

    if ext == PDF_EXTENSION:
        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages).strip()

    raise ValueError(
        f"Unsupported file type '{ext or 'unknown'}'. "
        "Supported: .txt, .md, .json, .pdf"
    )


def _flatten_json(data: bytes) -> str:
    """Recursively flatten a JSON document into readable 'key: value' text."""
    try:
        payload = json.loads(data.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, ValueError):
        return data.decode("utf-8", errors="replace").strip()

    def walk(node, prefix=""):
        lines = []
        if isinstance(node, dict):
            for k, v in node.items():
                key = f"{prefix}{k}"
                if isinstance(v, (dict, list)):
                    lines.extend(walk(v, f"{key} " if isinstance(v, dict) else f"{key} "))
                else:
                    lines.append(f"{key}: {v}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                if isinstance(v, (dict, list)):
                    lines.extend(walk(v, f"{prefix}"))
                else:
                    lines.append(f"{prefix}. {v}")
        else:
            lines.append(str(node))
        return lines

    return "\n".join(line.strip() for line in walk(payload)).strip()


def chunk_text(text: str, size: int = None, overlap: int = None) -> list[str]:
    """
    Split text into overlapping chunks on paragraph boundaries.

    Overlap is applied as the real tail of each previous chunk, re-attached to
    the head of the next chunk so context carries across the cut.
    """
    size = size or settings.CHUNK_SIZE
    overlap = min(overlap or settings.CHUNK_OVERLAP, size // 2)
    text = text.strip()

    if not text:
        return []
    if len(text) <= size:
        return [text]

    # Body budget: chunks after the first also carry the previous chunk's tail
    # (plus a paragraph separator) as an overlap prefix, so slice paragraphs
    # into pieces that leave that much headroom. This guarantees the head never
    # needs trimming and no text is ever dropped.
    max_body = max(size - overlap - 2, 1)

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    pieces: list[str] = []
    buffer = ""

    for para in paragraphs:
        while len(para) > max_body:
            if buffer:
                pieces.append(buffer)
                buffer = ""
            cut = para.rfind(" ", 0, max_body)
            if cut < max_body // 2:
                cut = max_body
            piece = para[:cut].strip()
            if piece:
                pieces.append(piece)
            para = para[cut:].strip()
            if not para:
                break
        else:
            if buffer:
                if len(buffer) + len(para) + 2 <= max_body:
                    buffer = f"{buffer}\n\n{para}"
                else:
                    pieces.append(buffer)
                    buffer = para
            else:
                buffer = para

    if buffer:
        pieces.append(buffer)

    # Attach the true tail of each chunk to the head of the next so context
    # carries across the cut. Every piece already fits next to the prefix, so
    # the combined chunk stays within `size` without lossy trimming.
    chunks = [pieces[0]]
    prev_tail = pieces[0][-overlap:].lstrip()
    for body in pieces[1:]:
        head = f"{prev_tail}\n\n{body}".strip() if prev_tail else body
        chunks.append(head)
        prev_tail = head[-overlap:].lstrip()

    return chunks


def ingest_document(filename: str, data: bytes, agent_ns: str = "knowledge_base") -> int:
    """
    Extract, chunk, embed, and store a document into the 'documents' collection.

    Returns the number of chunks inserted.
    """
    ns = (agent_ns or "knowledge_base").strip()
    text = extract_text(filename, data)
    if not text:
        raise ValueError("No readable text found in the uploaded file.")

    chunks = chunk_text(text)
    if not chunks:
        raise ValueError("Document produced no text chunks.")

    # De-duplicate: remove previously ingested chunks for the same file *within
    # this namespace only* so different namespaces can share a filename safely.
    db["documents"].delete_many(
        {"metadata.filename": filename, "metadata.agent_ns": ns}
    )

    collection = db["documents"]
    for i, chunk in enumerate(chunks, start=1):
        vector = generate_embedding(chunk)
        collection.insert_one({
            "text": chunk,
            "vector": vector,
            "metadata": {
                "agent_ns": ns,
                "source_id": f"upload:{filename}",
                "filename": filename,
                "chunk_index": i,
                "chunk_count": len(chunks),
            },
        })
        time.sleep(0.1)

    return len(chunks)