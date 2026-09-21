import os

from dotenv import load_dotenv
from openai import OpenAI

from app.config import settings
from app.services.conversations import conversations
from app.services.search import search_documents

load_dotenv()

client = OpenAI(
    api_key=settings.AZURE_OPENAI_API_KEY,
    base_url=f"{settings.AZURE_OPENAI_ENDPOINT}/openai/v1/"
)

CHAT_DEPLOYMENT = settings.AZURE_OPENAI_CHAT_DEPLOYMENT

SYSTEM_PROMPT = """You are a helpful FAQ assistant for Chitkara University, Rajpura.
Your job is to answer student questions using ONLY the context provided below.

Rules:
- Answer based ONLY on the provided context. Do not make up information.
- If the context does not contain enough information to answer, say:
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


def ask(question: str, session_id: str = None) -> dict:
    """
    Answer a student's question using RAG.

    1. Retrieve relevant documents via vector search.
    2. Build a prompt with the retrieved context and conversation history.
    3. Call Azure OpenAI chat completion.
    4. Store the exchange in the conversation memory and return the result.
    """
    session_id = session_id or "default"

    # Step 1: Retrieve relevant documents
    results = search_documents(question, limit=5)

    # Step 2: Build context from search results
    context_parts = []
    sources = []

    for r in results:
        context_parts.append(r["text"])
        sources.append({
            "text": r["text"][:200] + "..." if len(r["text"]) > 200 else r["text"],
            "metadata": r.get("metadata", {}),
            "score": r.get("score", 0)
        })

    context = "\n\n---\n\n".join(context_parts) if context_parts else "No relevant documents found."

    # Step 3: Build messages with history
    history = conversations.trimmed(session_id)
    if history:
        history_text = "\n".join(
            f"{m['role']}: {m['content']}" for m in history
        )
    else:
        history_text = "(no previous conversation)"

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
        temperature=0.3,
        max_tokens=1024
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