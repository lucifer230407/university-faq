import logging

from dotenv import load_dotenv
from openai import OpenAI

from app.config import settings
from app.services.conversations import conversations
from app.services.search import search_documents
from app.services import web_search

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
Your job is to answer student questions using the provided context.

The context may contain two kinds of information:
1. "Knowledge base" entries — from the university FAQ / uploaded handouts.
2. "Web search" entries — freshly fetched from the web (marked with a URL).

Rules:
- Answer based ONLY on the provided context. Do not make up information.
- Use knowledge base entries first; use web entries to fill gaps or when asked
  about current/up-to-date information.
- If neither source contains enough information to answer, say:
  "I don't have enough information to answer that question. Please contact the university helpdesk."
- Be concise, friendly, and professional.
- Use bullet points or numbered lists when listing multiple items.
- If a question is about fees, dates, or deadlines, be precise with numbers.
- A short conversation history follows the context. Use it to follow up on
  previous questions, but never invent facts that are missing from the context.

Context:
{context}

Conversation history (most recent last):
{history}
"""


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


def retrieve_local(query: str):
    """Vector-search the knowledge base; returns (context_parts, sources)."""
    results = search_documents(query, limit=5)

    context_parts = []
    sources = []

    for r in results:
        score = r.get("score", 0)
        if score < SIMILARITY_THRESHOLD:
            continue
        context_parts.append(r["text"])
        sources.append({
            "text": r["text"][:200] + "..." if len(r["text"]) > 200 else r["text"],
            "metadata": r.get("metadata", {}),
            "score": score
        })
    return context_parts, sources


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
    local_parts, local_sources = retrieve_local(search_query)

    # Step 2: Web grounding (current info about Chitkara University)
    web_parts, web_sources = retrieve_web(search_query, local_found=bool(local_parts))

    context_parts = local_parts + web_parts
    sources = local_sources + web_sources
    context = "\n\n---\n\n".join(context_parts) if context_parts else "No relevant information found."

    # Step 3: Build messages with history
    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT.format(
                context=context,
                history=history_text,
            )
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

    # Step 4: Store the exchange
    conversations.append(session_id, "user", question)
    conversations.append(session_id, "assistant", answer)

    return {
        "answer": answer,
        "sources": sources,
        "session_id": session_id,
    }


def clear_conversation(session_id: str) -> None:
    conversations.clear(session_id or "default")