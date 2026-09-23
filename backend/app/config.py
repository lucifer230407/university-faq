from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Azure resources ---
    DOCUMENTDB_URI: str | None = None
    AZURE_OPENAI_ENDPOINT: str | None = None
    AZURE_OPENAI_API_KEY: str | None = None
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT: str | None = "text-embedding-3-small"
    AZURE_OPENAI_CHAT_DEPLOYMENT: str | None = "gpt-4.1-mini"

    # --- Auth ---
    # Comma-separated list of accepted API keys. Empty disables API-key auth.
    API_KEYS_RAW: str = Field(default="", validation_alias="API_KEYS")

    # JWT username/password login. JWT_SECRET must be set to enable login.
    # The bootstrap admin user is defined via ADMIN_USERNAME / ADMIN_PASSWORD.
    JWT_SECRET: str | None = None
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8
    ADMIN_USERNAME: str | None = None
    ADMIN_PASSWORD: str | None = None
    ADMIN_DISPLAY_NAME: str | None = None

    # Allow anyone to self-register via POST /api/auth/register (role "user").
    # Applies only when JWT login is enabled (JWT_SECRET set).
    ALLOW_SIGNUP: bool = True

    CONVERSATION_HISTORY_LIMIT: int = 12

    # --- Rate limits: N requests per window (seconds) ---
    RATE_LIMIT_ASK: int = 10
    RATE_LIMIT_DOCS: int = 5
    RATE_LIMIT_CLEAR: int = 10
    RATE_LIMIT_REGISTER: int = 5
    RATE_LIMIT_WINDOW: int = 60

    # --- Ingestion / chunking ---
    CHUNK_SIZE: int = 800
    CHUNK_OVERLAP: int = 100
    MAX_UPLOAD_BYTES: int = 10 * 1024 * 1024

    # Minimum vector search score for a source to be used as context.
    # For text-embedding-3-small, cosine scores for genuinely relevant text are
    # typically 0.30+; tune with real queries rather than guessing.
    SIMILARITY_THRESHOLD: float = 0.30

    # IVF vector index settings (used by scripts/create_vector_index.py)
    VECTOR_INDEX_DIMENSIONS: int = 1536
    VECTOR_INDEX_NUMLISTS: int = 16
    VECTOR_INDEX_SIMILARITY: str = "COS"

    # --- LLM generation ---
    GPT_TEMPERATURE: float = 0.3
    GPT_MAX_TOKENS: int = 1024
    QUERY_REWRITE_MAX_TOKENS: int = 80

    # --- Server / CORS ---
    # Comma-separated allowed origins. "*" allows all (dev default). When "*" is
    # used, credentials are disabled because browsers reject credentialed
    # wildcard CORS requests anyway.
    CORS_ORIGINS_RAW: str = Field(default="*", validation_alias="CORS_ORIGINS")

    # Serve the frontend directly from this directory at "/" (same origin, no
    # CORS). Leave empty to skip static serving (pure API mode / file:// dev).
    STATIC_DIR: str | None = None

    # Comma-separated proxy IPs that the app sits behind. When the direct peer
    # is one of these, the client IP is read from the left-most X-Forwarded-For
    # entry. Leave empty to trust only the socket address.
    TRUSTED_PROXY_IPS_RAW: str = Field(
        default="", validation_alias="TRUSTED_PROXY_IPS"
    )

    # --- Logging ---
    LOG_LEVEL: str = "INFO"

    # --- Web search grounding (Chitkara University web info) ---
    # Providers: "duckduckgo" | "bing" | "wikipedia" | "none".
    WEB_SEARCH_PROVIDER: str = "duckduckgo"
    WEB_SEARCH_ENABLED: bool = True
    # Search the web only when no local context cleared the threshold.
    WEB_SEARCH_FALLBACK: bool = True
    # Fetch full page text for the top N results to use as grounded context.
    WEB_PAGE_FETCH_ENABLED: bool = True
    WEB_PAGE_FETCH_LIMIT: int = 3
    WEB_PAGE_FETCH_MAX_BYTES: int = 12000
    WEB_SEARCH_RESULT_LIMIT: int = 5
    BING_SEARCH_API_KEY: str | None = None

    # --- Redis (optional). If set, conversations and the rate limiter swap to
    # --- Redis so history/limits survive restarts and multi-worker deploys.
    REDIS_URL: str | None = None

    @property
    def api_keys(self) -> list[str]:
        return [k.strip() for k in self.API_KEYS_RAW.split(",") if k.strip()]

    @property
    def auth_enabled(self) -> bool:
        # Authentication is "enabled" when either credential mechanism is on.
        return len(self.api_keys) > 0 or bool(self.JWT_SECRET)

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS_RAW.split(",") if o.strip()]

    @property
    def trusted_proxy_ips(self) -> list[str]:
        return [
            o.strip() for o in self.TRUSTED_PROXY_IPS_RAW.split(",") if o.strip()
        ]

    @property
    def rate_limits(self) -> dict[str, tuple[int, int]]:
        return {
            "ask": (self.RATE_LIMIT_ASK, self.RATE_LIMIT_WINDOW),
            "documents": (self.RATE_LIMIT_DOCS, self.RATE_LIMIT_WINDOW),
            "clear": (self.RATE_LIMIT_CLEAR, self.RATE_LIMIT_WINDOW),
            "register": (self.RATE_LIMIT_REGISTER, self.RATE_LIMIT_WINDOW),
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()