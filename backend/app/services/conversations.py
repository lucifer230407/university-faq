import logging

from app.config import settings

logger = logging.getLogger(__name__)


class ConversationStore:
    """
    In-process conversation memory keyed by session_id.

    Optional: when REDIS_URL is configured, history is persisted in Redis as a
    list per session so it survives restarts and works across workers.
    """

    def __init__(self, limit: int = None):
        self._limit = limit or settings.CONVERSATION_HISTORY_LIMIT
        self._sessions: dict[str, list[dict]] = {}
        self._redis = None

        if settings.REDIS_URL and settings.REDIS_URL.strip():
            try:
                import redis  # type: ignore

                self._redis = redis.Redis.from_url(
                    settings.REDIS_URL, decode_responses=True
                )
                logger.info("Conversation memory backed by Redis at %s", settings.REDIS_URL)
            except Exception as e:  # pragma: no cover
                logger.error("Failed to init Redis conversation store, using memory: %s", e)

    @staticmethod
    def _key(session_id: str) -> str:
        return f"chat:history:{session_id}"

    def get(self, session_id: str) -> list[dict]:
        if self._redis is not None:
            raw = self._redis.lrange(self._key(session_id), 0, self._limit - 1)
            return [{"role": m[1], "content": m[2]} for m in (r.split("\x1f", 2) for r in raw) if len(m) == 3]
        return self._sessions.get(session_id, [])

    def append(self, session_id: str, role: str, content: str) -> None:
        if self._redis is not None:
            key = self._key(session_id)
            self._redis.rpush(key, f"{role}\x1f{content}")
            self._redis.ltrim(key, -self._limit, -1)
            self._redis.expire(key, 24 * 3600)
            return
        history = self._sessions.setdefault(session_id, [])
        history.append({"role": role, "content": content})
        if len(history) > self._limit:
            del history[: len(history) - self._limit]

    def trimmed(self, session_id: str) -> list[dict]:
        """Return the most recent messages, always ending on an assistant turn."""
        history = self.get(session_id)[-self._limit:]
        # If the last stored turn is a user message, drop it so the newest
        # user question is never duplicated in the prompt.
        if history and history[-1]["role"] == "user":
            history = history[:-1]
        return history

    def clear(self, session_id: str) -> None:
        if self._redis is not None:
            self._redis.delete(self._key(session_id))
            return
        self._sessions.pop(session_id, None)


conversations = ConversationStore()