import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    DOCUMENTDB_URI = os.getenv("DOCUMENTDB_URI")
    AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
    AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
    AZURE_OPENAI_CHAT_DEPLOYMENT = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT")

    # Comma-separated list of allowed API keys (optional).
    # If empty/unset, authentication is disabled.
    API_KEYS = [
        k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()
    ]

    # Conversation memory (in-process). Number of history messages kept per session.
    CONVERSATION_HISTORY_LIMIT = int(os.getenv("CONVERSATION_HISTORY_LIMIT", "12"))

    # Rate limits: {route_name: (max_requests, window_seconds)}
    RATE_LIMITS = {
        "ask": (int(os.getenv("RATE_LIMIT_ASK", "10")), int(os.getenv("RATE_LIMIT_WINDOW", "60"))),
        "documents": (int(os.getenv("RATE_LIMIT_DOCS", "5")), int(os.getenv("RATE_LIMIT_WINDOW", "60"))),
        "clear": (int(os.getenv("RATE_LIMIT_CLEAR", "10")), int(os.getenv("RATE_LIMIT_WINDOW", "60"))),
    }

    # Chunking settings for document ingestion
    CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "800"))
    CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "100"))
    MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))

    @property
    def auth_enabled(self) -> bool:
        return len(self.API_KEYS) > 0


settings = Settings()