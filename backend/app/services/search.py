import logging
import re
import time

from app.db.documentdb import db
from app.services.embeddings import generate_embedding

logger = logging.getLogger(__name__)

_CODE_PATTERNS = (
    (re.compile(r"\bfa\s*-?\s*2\b", re.I), "FA2"),
    (re.compile(r"formative\s+assessment\s*-?\s*2\b", re.I), "FA2"),
    (re.compile(r"\bfa\s*-?\s*1\b", re.I), "FA1"),
    (re.compile(r"formative\s+assessment\s*-?\s*1\b", re.I), "FA1"),
    (re.compile(r"\bst\s*-?\s*2\b", re.I), "ST2"),
    (re.compile(r"sessional\s+test\s*-?\s*2\b", re.I), "ST2"),
    (re.compile(r"\bst\s*-?\s*1\b", re.I), "ST1"),
    (re.compile(r"sessional\s+test\s*-?\s*1\b", re.I), "ST1"),
    (re.compile(r"\bete\b", re.I), "ETE"),
)

_STOPWORDS = {
    "what", "when", "where", "which", "who", "whom", "whose", "why", "how",
    "the", "and", "for", "with", "from", "that", "this", "about", "into",
    "your", "course", "university", "chitkara", "please", "tell", "give",
    "date", "dates", "schedule", "details", "specific", "information",
    "formative", "assessment", "sessional", "test", "exam", "examination",
}

_DATE_RE = re.compile(
    r"\b(?:mon|tue|wed|thu|fri|sat|sun|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b",
    re.I,
)


def is_official_source(metadata: dict | None) -> bool:
    """Seeded FAQs and admin-marked uploads only.

    Older student uploads use source_id ``upload:...`` without ``trusted`` and
    must not ground answers.
    """
    meta = metadata or {}
    source_id = str(meta.get("source_id") or "")
    if source_id.startswith("upload:") and not meta.get("trusted"):
        return False
    return True


def search_documents(query: str, limit: int = 5, agent_ns: str = None) -> list[dict]:
    """
    Perform a vector search against the documents collection.

    Args:
        query: The user's natural language question.
        limit: Maximum number of results to return.
        agent_ns: Optional namespace filter (e.g., 'academics', 'admissions').
            Applied as a pre-filter inside the search itself so k results are
            *all* from the requested namespace.

    Returns:
        A list of matching documents with text, metadata, and similarity score.
    """
    query_vector = generate_embedding(query)

    documents = db["documents"]

    search_options = {
        "vector": query_vector,
        "path": "vector",
        "k": max(limit * 4, limit)
    }

    # Pre-filter inside cosmosSearch so retrieval stays within the namespace.
    if agent_ns:
        search_options["filter"] = {
            "metadata.agent_ns": {"$eq": agent_ns}
        }

    pipeline = [
        {
            "$search": {
                "cosmosSearch": search_options
            }
        },
        {
            "$project": {
                "_id": 0,
                "text": 1,
                "metadata": 1,
                "score": {
                    "$meta": "searchScore"
                }
            }
        }
    ]

    results = list(documents.aggregate(pipeline))

    results = [r for r in results if is_official_source(r.get("metadata"))]
    if agent_ns:
        results = [
            r for r in results
            if r.get("metadata", {}).get("agent_ns") == agent_ns
        ]

    return results[:limit]


def schedule_codes(query: str) -> list[str]:
    """Assessment codes named in the question, in match order."""
    found = []
    for pattern, code in _CODE_PATTERNS:
        if pattern.search(query) and code not in found:
            found.append(code)
    return found


def course_tokens(query: str) -> list[str]:
    """Distinctive course-name tokens, ignoring assessment codes and stopwords."""
    codes = {c.lower() for c in schedule_codes(query)}
    tokens = []
    for raw in re.findall(r"[A-Za-z][A-Za-z0-9&+-]*", query):
        token = raw.lower()
        if token in codes or token in _STOPWORDS:
            continue
        if len(token) < 3 and not raw.isupper():
            continue
        if token not in tokens:
            tokens.append(token)
    return tokens


def _code_regex(codes: list[str]) -> str:
    parts = []
    for code in codes:
        if len(code) == 3 and code[:2] in {"FA", "ST"} and code[2].isdigit():
            prefix, num = code[:2], code[2]
            parts.append(rf"{prefix}\s*-?\s*{num}")
            if prefix == "FA":
                parts.append(rf"Formative\s+Assessment\s*-?\s*{num}")
            else:
                parts.append(rf"Sessional\s+Test\s*-?\s*{num}")
        else:
            parts.append(re.escape(code))
    return "|".join(parts)


def lexical_match_score(text: str, codes: list[str], tokens: list[str]) -> float:
    """
    Score a chunk by how tightly an assessment code sits next to the course
    name and a date. A chunk that only pairs FA2 with a different course, or
    the course with FA1, scores lower than the exact schedule row.
    """
    compact = re.sub(r"\s+", " ", text)
    score = 0.0
    for code in codes:
        prefix = code[:2]
        num = code[2:] if len(code) == 3 else ""
        if prefix in {"FA", "ST"} and num.isdigit():
            pattern = re.compile(rf"{prefix}\s*-?\s*{num}", re.I)
        else:
            pattern = re.compile(re.escape(code), re.I)
        for match in pattern.finditer(compact):
            window = compact[match.start(): match.start() + 140]
            score += 1.0
            token_hits = sum(1 for token in tokens if token in window.lower())
            score += token_hits * 2.0
            if _DATE_RE.search(window):
                score += 3.0
            around = compact[max(0, match.start() - 80): match.end() + 80]
            if "Date(s)" in around or "Name of Activity" in around:
                score += 2.0
    if score and (compact.count("I]") or "Willibe" in compact or "ee oe" in compact):
        score *= 0.85
    return score


def lexical_search(query: str, limit: int = 3) -> list[dict]:
    """
    Find schedule chunks that literally contain the asked assessment code.

    Vector search ranks course-handout intros above the calendar row that
    names FA2 for a specific course, so date questions miss the uploaded
    academic calendar. This pulls those rows back in.
    """
    codes = schedule_codes(query)
    if not codes:
        return []

    tokens = course_tokens(query)
    try:
        cursor = db["documents"].find(
            {"text": {"$regex": _code_regex(codes), "$options": "i"}},
            {"_id": 0, "text": 1, "metadata": 1},
        )
    except Exception as e:
        logger.warning("Lexical schedule search failed: %s", e)
        return []

    ranked = []
    for doc in cursor:
        if not is_official_source(doc.get("metadata")):
            continue
        text = doc.get("text") or ""
        score = lexical_match_score(text, codes, tokens)
        if score <= 0:
            continue
        ranked.append({
            "text": text,
            "metadata": doc.get("metadata") or {},
            "score": score,
            "lexical": True,
        })

    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked[:limit]


_CORPUS_TTL_SECONDS = 60
_corpus_cache = {"expires": 0.0, "text": ""}


def clear_knowledge_cache() -> None:
    _corpus_cache["expires"] = 0.0
    _corpus_cache["text"] = ""


def stitch_chunks(chunks: list[dict]) -> str:
    """Join chunks in order, dropping a repeated overlap prefix."""
    ordered = sorted(
        chunks,
        key=lambda item: (item.get("metadata") or {}).get("chunk_index") or 0,
    )
    texts = [(item.get("text") or "").strip() for item in ordered]
    texts = [text for text in texts if text]
    if not texts:
        return ""
    merged = texts[0]
    for nxt in texts[1:]:
        overlap = 0
        limit = min(len(merged), len(nxt), 180)
        for size in range(limit, 19, -1):
            if merged[-size:] == nxt[:size]:
                overlap = size
                break
        addition = nxt[overlap:].strip() if overlap else nxt
        if addition:
            merged = f"{merged}\n\n{addition}"
    return merged


def render_corpus(docs: list[dict]) -> str:
    """
    Turn stored chunks into labeled documents the model can read end to end.

    OCR twins of a cleaner file in the same namespace are dropped so a garbled
    scan does not contradict the readable copy.
    """
    grouped: dict[tuple, list[dict]] = {}
    faqs = []
    for doc in docs:
        if not is_official_source(doc.get("metadata")):
            continue
        meta = doc.get("metadata") or {}
        source_id = str(meta.get("source_id") or "")
        if source_id.startswith("test"):
            continue
        filename = meta.get("filename")
        if filename:
            grouped.setdefault((meta.get("agent_ns") or "", filename), []).append(doc)
        else:
            faqs.append(doc)

    by_ns: dict[str, list[tuple]] = {}
    for key in grouped:
        by_ns.setdefault(key[0], []).append(key)
    for keys in by_ns.values():
        if len(keys) < 2:
            continue
        ocr = [key for key in keys if "ocr" in key[1].lower()]
        clean = [key for key in keys if key not in ocr]
        if ocr and clean:
            for key in ocr:
                grouped.pop(key, None)

    sections = []
    for (ns, filename) in sorted(grouped):
        body = stitch_chunks(grouped[(ns, filename)])
        if not body:
            continue
        label = f"{filename} | {ns}" if ns else filename
        sections.append(f"===== DOCUMENT: {label} =====\n{body}")
    if faqs:
        faq_body = "\n\n".join(
            (item.get("text") or "").strip() for item in faqs if (item.get("text") or "").strip()
        )
        if faq_body:
            sections.append(f"===== UNIVERSITY FAQ =====\n{faq_body}")
    return "\n\n".join(sections)


def cached_documents() -> list[dict]:
    now = time.time()
    cached = _corpus_cache.get("docs")
    if now < _corpus_cache["expires"] and cached is not None:
        return cached
    try:
        docs = list(db["documents"].find({}, {"_id": 0, "text": 1, "metadata": 1}))
    except Exception as e:
        logger.warning("Knowledge corpus load failed: %s", e)
        return cached or []
    _corpus_cache["docs"] = docs
    _corpus_cache["expires"] = now + _CORPUS_TTL_SECONDS
    return docs


def knowledge_corpus() -> str:
    """Full text of trusted uploads and seeded FAQs, cached briefly."""
    return render_corpus(cached_documents())


def focus_excerpt(text: str, query: str, radius: int = 240) -> str | None:
    """The schedule line that pairs the asked code with the asked course."""
    codes = schedule_codes(query)
    if not codes or not text:
        return None
    tokens = course_tokens(query)
    compact = re.sub(r"\s+", " ", text)
    best = None
    best_score = 0.0
    for code in codes:
        prefix, num = code[:2], code[2:] if len(code) == 3 else ""
        if prefix in {"FA", "ST"} and num.isdigit():
            pattern = re.compile(rf"{prefix}\s*-?\s*{num}", re.I)
        else:
            pattern = re.compile(re.escape(code), re.I)
        for match in pattern.finditer(compact):
            window = compact[match.start(): match.start() + 72]
            score = 1.0 + 2.0 * sum(token in window.lower() for token in tokens)
            if _DATE_RE.search(window):
                score += 3.0
            if score > best_score:
                best_score = score
                best = compact[match.start(): match.end() + radius].strip()
    if best_score < 3:
        return None
    return best


def _grouped_files(docs: list[dict]) -> dict[tuple, list[dict]]:
    grouped: dict[tuple, list[dict]] = {}
    for doc in docs:
        if not is_official_source(doc.get("metadata")):
            continue
        meta = doc.get("metadata") or {}
        filename = meta.get("filename")
        if not filename:
            continue
        grouped.setdefault((meta.get("agent_ns") or "", filename), []).append(doc)
    by_ns: dict[str, list[tuple]] = {}
    for key in list(grouped):
        by_ns.setdefault(key[0], []).append(key)
    for keys in by_ns.values():
        if len(keys) < 2:
            continue
        ocr = [key for key in keys if "ocr" in key[1].lower()]
        if ocr and len(ocr) < len(keys):
            for key in ocr:
                grouped.pop(key, None)
    return grouped


def reading_context(query: str, hits: list[dict], docs: list[dict] | None = None) -> str:
    """
    Excerpts plus the full text of the PDFs that match the question.

    The model reads the whole handout or calendar, not a single 800-character
    slice, so related questions about that file can be answered.
    """
    excerpts = []
    seen_excerpts = set()
    for hit in hits:
        excerpt = focus_excerpt(hit.get("text") or "", query)
        if not excerpt or excerpt in seen_excerpts:
            continue
        seen_excerpts.add(excerpt)
        meta = hit.get("metadata") or {}
        label = meta.get("filename") or meta.get("agent_ns") or "knowledge base"
        excerpts.append(f"[{label}] {excerpt}")

    expandable = [
        hit for hit in hits
        if (hit.get("metadata") or {}).get("filename")
        and (hit.get("metadata") or {}).get("chunk_index")
    ]
    if docs is None and not expandable:
        if not excerpts:
            return ""
        return "Most relevant excerpts:\n" + "\n\n".join(excerpts[:4])

    if docs is None:
        docs = cached_documents()
    grouped = _grouped_files(docs)

    chosen: list[tuple] = []
    seen_files = set()
    seen_calendar = False

    def add_file(ns: str, filename: str) -> None:
        nonlocal seen_calendar
        key = (ns, filename)
        if key not in grouped or filename in seen_files:
            return
        if ns == "academic calendar" and seen_calendar:
            return
        seen_files.add(filename)
        if ns == "academic calendar":
            seen_calendar = True
        chosen.append(key)

    ranked_hits = sorted(
        expandable,
        key=lambda hit: (1 if hit.get("lexical") else 0, hit.get("score") or 0),
        reverse=True,
    )
    for hit in ranked_hits:
        meta = hit.get("metadata") or {}
        add_file(meta.get("agent_ns") or "", meta.get("filename"))
        if len(chosen) >= 3:
            break

    tokens = [token for token in course_tokens(query) if len(token) >= 4]
    if len(tokens) >= 2 and len(chosen) < 3:
        scored = []
        for ns, filename in grouped:
            if filename in seen_files:
                continue
            name = filename.lower()
            scored.append((sum(token in name for token in tokens), ns, filename))
        for score, ns, filename in sorted(scored, reverse=True):
            if score < 2 or len(chosen) >= 3:
                break
            add_file(ns, filename)

    sections = []
    if excerpts:
        sections.append("Most relevant excerpts:\n" + "\n\n".join(excerpts[:4]))
    for ns, filename in chosen:
        body = stitch_chunks(grouped[(ns, filename)])
        if not body:
            continue
        label = f"{filename} | {ns}" if ns else filename
        sections.append(f"===== DOCUMENT: {label} =====\n{body}")
    return "\n\n".join(sections)
