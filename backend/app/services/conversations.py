from app.config import settings


class ConversationStore:
    """
    Simple in-process conversation memory keyed by session_id.

    Note: stored in memory only; history is lost on process restart or when
    running multiple workers. Suitable for the current single-process setup.
    """

    def __init__(self, limit: int = None):
        self._limit = limit or settings.CONVERSATION_HISTORY_LIMIT
        self._sessions: dict[str, list[dict]] = {}

    def get(self, session_id: str) -> list[dict]:
        return self._sessions.get(session_id, [])

    def append(self, session_id: str, role: str, content: str) -> None:
        history = self._sessions.setdefault(session_id, [])
        history.append({"role": role, "content": content})
        # Trim oldest messages when history grows too large.
        if len(history) > self._limit:
            del history[: len(history) - self._limit]

    def trimmed(self, session_id: str) -> list[dict]:
        """Return the most recent messages, always ending on an assistant turn."""
        history = self.get(session_id)[-self._limit :]
        # If the last stored turn is a user message, drop it so the newest
        # user question is never duplicated in the prompt.
        if history and history[-1]["role"] == "user":
            history = history[:-1]
        return history

    def clear(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


conversations = ConversationStore()