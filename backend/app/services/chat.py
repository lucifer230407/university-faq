import logging
import re

from dotenv import load_dotenv
from openai import OpenAI

from app.config import settings
from app.services import helpdesk_email, web_search
from app.services.conversations import conversations
from app.services.search import lexical_search, reading_context, search_documents

load_dotenv()

logger = logging.getLogger(__name__)

client = OpenAI(
    api_key=settings.AZURE_OPENAI_API_KEY,
    base_url=f"{settings.AZURE_OPENAI_ENDPOINT}/openai/v1/"
)

CHAT_DEPLOYMENT = settings.AZURE_OPENAI_CHAT_DEPLOYMENT
SIMILARITY_THRESHOLD = settings.SIMILARITY_THRESHOLD

REWRITE_PROMPT = """Rewrite the latest user message into a single standalone question so it can be used to search a university FAQ knowledge base or the web. Resolve pronouns and references using the conversation history. Output ONLY the rewritten question, no explanation.

Latest user message: {question}

Conversation history (most recent last):
{history}
"""

SYSTEM_PROMPT = """You are a helpful FAQ assistant for Chitkara University, Rajpura.
You are given the full text of the uploaded PDFs (course handouts, academic
calendar, mess menu, hostel rules) and the university FAQ. Read them and answer
from what they actually say.

The context may also contain "Web search" entries marked with a URL.

Rules:
- Use the uploaded documents first. You may explain, compare, list, and connect
  facts that are in those documents. That is in scope.
- Do not invent dates, marks, names, fees, or policies that are not in the context.
- Use web entries only to fill a gap the documents do not cover.
- If the documents do not contain the answer, say:
  "I don't have enough information to answer that question. Please contact the university helpdesk."
- Be concise, friendly, and professional.
- Use bullet points or numbered lists when listing multiple items.
- If a question is about fees, dates, or deadlines, be precise with numbers.
- Excerpts under "Most relevant excerpts" are the closest lines. For a named
  assessment or date, answer from the excerpt that contains that exact code
  and course. Then use the full document for related details.
- For a date or assessment schedule (FA, ST, ETE, formative, sessional), use
  the academic calendar row that names that exact activity and course.
  FA1 is not FA2, and a different course's row is not an answer.
- If that exact schedule row is in the context, state its date and remarks.
  Do not say the detail is missing, and do not send the student to a
  coordinator or syllabus instead.
- Course handouts describe weightage, topics, and coordinators. They do not
  replace calendar dates.
- A short conversation history follows the context. Use it to follow up on
  previous questions, but never invent facts that are missing from the context.

Context:
{context}

Conversation history (most recent last):
{history}
"""


def render_prompt(context: str, history_text: str) -> str:
    """Substitute context without str.format, so PDF braces are safe."""
    return (
        SYSTEM_PROMPT
        .replace("{context}", context)
        .replace("{history}", history_text)
    )


def rewrite_query(question: str, history_text: str) -> str:
    """
    Expand a follow-up question into a standalone search query using the
    conversation history (e.g. "what about the fee?" -> "what is the
    re-evaluation fee?"). Falls back to the original question on failure.
    """
    if not question.strip():
        return question

    try:
        response = client.chat.completions.create(
            model=CHAT_DEPLOYMENT,
            messages=[
                {"role": "system", "content": "You rewrite questions for search."},
                {"role": "user", "content": REWRITE_PROMPT.format(
                    question=question,
                    history=history_text,
                )},
            ],
            temperature=0.0,
            max_tokens=settings.QUERY_REWRITE_MAX_TOKENS,
        )
        rewritten = response.choices[0].message.content.strip()
        return rewritten or question
    except Exception as e:
        logger.warning("Query rewrite failed, using original question: %s", e)
        return question


def _format_local_hit(result: dict) -> str:
    meta = result.get("metadata") or {}
    label = meta.get("filename") or meta.get("source_id") or "knowledge base"
    ns = meta.get("agent_ns")
    header = f"[Knowledge base: {label}" + (f" | {ns}]" if ns else "]")
    return f"{header}\n{result['text']}"


# Phrases the LLM is told to emit (or naturally uses) when the context cannot
# answer. When one is found, the assistant offers the help-desk email option.
_LACKS_INFO_PATTERNS = (
    r"don'?t have enough information",
    r"do not have enough information",
    r"doesn'?t have enough information",
    r"does not have enough information",
    r"don'?t have sufficient information",
    r"do not have sufficient information",
    r"not enough information",
    r"couldn'?t find (?:reliable )?information",
    r"could not find (?:reliable )?information",
    r"i (?:couldn'?t|could not) find",
    r"cannot answer that question",
    r"can'?t answer that question",
    r"unable to answer",
    r"i don'?t know",
    r"i do not know",
    r"not (?:available|covered|included) in (?:my|the)",
    r"no (?:reliable )?information",
    r"contact the (?:university )?helpdesk",
    r"university helpdesk",
)
_LACKS_INFO_RE = re.compile(
    "|".join(_LACKS_INFO_PATTERNS), re.IGNORECASE
)


def _answer_lacks_info(answer: str) -> bool:
    """Best-effort check that the model admitted it had no grounded answer."""
    return bool(answer and _LACKS_INFO_RE.search(answer))


def retrieve_local(query: str):
    """Vector-search the knowledge base; returns (context_parts, sources, hits)."""
    vector_hits = search_documents(query, limit=8)
    lexical_hits = lexical_search(query, limit=4)

    context_parts = []
    sources = []
    hits = []
    seen = set()

    for r in lexical_hits + vector_hits:
        text = r.get("text") or ""
        key = text[:240]
        if not text or key in seen:
            continue
        score = r.get("score", 0)
        if not r.get("lexical") and score < SIMILARITY_THRESHOLD:
            continue
        seen.add(key)
        hits.append(r)
        context_parts.append(_format_local_hit(r))
        sources.append({
            "text": text[:200] + "..." if len(text) > 200 else text,
            "metadata": r.get("metadata", {}),
            "score": score
        })
    return context_parts, sources, hits


def retrieve_web(query: str, local_found: bool):
    """
    Search the web when enabled. When WEB_SEARCH_FALLBACK is true the web is
    only consulted if the local knowledge base turned up nothing; otherwise it
    runs alongside local retrieval to ground current/quick-changing facts.
    """
    provider = (settings.WEB_SEARCH_PROVIDER or "duckduckgo").lower()
    if provider == "none" or not settings.WEB_SEARCH_ENABLED:
        return [], []
    if settings.WEB_SEARCH_FALLBACK and local_found:
        return [], []

    results, pages = web_search.search_with_pages(query)
    web_context = web_search.format_web_context(results, pages)
    if not web_context:
        return [], []
    sources = web_search.web_sources_as_items(results, pages)
    return [web_context], sources


def ask(question: str, session_id: str = None) -> dict:
    """
    Answer a student's question using RAG plus optional web grounding.

    1. Retrieve relevant documents via vector search (with query rewriting
       when conversation history exists).
    2. When enabled, add web search results for current/uncovered topics.
    3. Build a prompt with the retrieved context, filtered by a minimum
       similarity score, and the conversation history.
    4. Call Azure OpenAI chat completion.
    5. Store the exchange in the conversation memory and return the result.
    """
    session_id = session_id or "default"
    history = conversations.trimmed(session_id)

    history_text = "(no previous conversation)"
    if history:
        history_text = "\n".join(
            f"{m['role']}: {m['content']}" for m in history
        )

    # Step 1: Retrieve relevant documents
    search_query = question
    if history:
        search_query = rewrite_query(question, history_text)
    local_parts, local_sources, hits = retrieve_local(search_query)
    packed = reading_context(search_query, hits)

    # Step 2: Web grounding only when nothing local was retrieved.
    web_parts, web_sources = retrieve_web(
        search_query,
        local_found=bool(packed or local_parts),
    )

    sources = local_sources + web_sources
    if packed:
        context = packed
        if web_parts:
            context = f"{packed}\n\n---\n\n" + "\n\n---\n\n".join(web_parts)
    else:
        context_parts = local_parts + web_parts
        context = "\n\n---\n\n".join(context_parts) if context_parts else "No relevant information found."

    # Help-desk email fallback is only offered when it is configured AND the
    # retrieval/answer genuinely indicates no reliable information exists.
    email_available = False

    if not sources:
        # Nothing cleared the similarity threshold locally or reached the web
        # grounding. Never let the model hallucinate: return the deterministic
        # fallback without a generation round-trip.
        answer = helpdesk_email.NO_INFO_ANSWER
        email_available = helpdesk_email.email_configured()
    else:
        # Step 3: Build messages with history
        messages = [
            {
                "role": "system",
                "content": render_prompt(context, history_text)
            },
            *history,
            {"role": "user", "content": question},
        ]

        response = client.chat.completions.create(
            model=CHAT_DEPLOYMENT,
            messages=messages,
            temperature=settings.GPT_TEMPERATURE,
            max_tokens=settings.GPT_MAX_TOKENS
        )

        answer = response.choices[0].message.content
        if _answer_lacks_info(answer):
            email_available = helpdesk_email.email_configured()

    # Step 4: Store the exchange
    conversations.append(session_id, "user", question)
    conversations.append(session_id, "assistant", answer)

    return {
        "answer": answer,
        "sources": sources,
        "session_id": session_id,
        "email_available": email_available,
        "email_required": False,
    }


def clear_conversation(session_id: str) -> None:
    conversations.clear(session_id or "default")