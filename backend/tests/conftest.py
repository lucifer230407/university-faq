import os

# Neutral env BEFORE any app module imports settings from .env.
os.environ.setdefault("WEB_SEARCH_PROVIDER", "none")
os.environ.setdefault("WEB_SEARCH_ENABLED", "false")
os.environ.setdefault("REDIS_URL", "")
os.environ.setdefault("TRUSTED_PROXY_IPS", "")
os.environ.setdefault("CORS_ORIGINS", "*")
os.environ.setdefault("API_KEYS", "test-key-1,test-key-2")
os.environ.setdefault("JWT_SECRET", "")
os.environ.setdefault("ADMIN_USERNAME", "")
os.environ.setdefault("ADMIN_PASSWORD", "")
os.environ.setdefault("DOCUMENTDB_URI", "mongodb://fake.local/test")
os.environ.setdefault("SIMILARITY_THRESHOLD", "0.30")
# Keep the help-desk email service inactive unless a test configures it.
os.environ.setdefault("SMTP_HOST", "")
os.environ.setdefault("SMTP_PORT", "0")
os.environ.setdefault("SMTP_USERNAME", "")
os.environ.setdefault("SMTP_PASSWORD", "")
os.environ.setdefault("HELPDESK_EMAIL", "")

# Dummy Azure OpenAI creds so import-time OpenAI(...) construction never fails
# in CI (where no .env exists). Tests never call the real client; they use the
# FakeChat/fake-embedding fakes below.
os.environ.setdefault("AZURE_OPENAI_ENDPOINT", "https://dummy.openai.azure.com")
os.environ.setdefault("AZURE_OPENAI_API_KEY", "dummy-openai-key")
os.environ.setdefault("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small")
os.environ.setdefault("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4.1-mini")


class FakeResponse:
    """Minimal stand-in for an OpenAI chat completion response."""

    def __init__(self, content):
        self.choices = [SimpleMessage(content)]


class SimpleMessage:
    def __init__(self, content):
        self.message = FakeMessage(content)
        # Alias used by some openai versions
        self.text = content


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChat:
    def __init__(self, returns=None, raises=None):
        class _Completions:
            def __init__(self, owner):
                self.owner = owner
                self.calls = owner.calls

            def create(self, **kwargs):
                self.owner.calls.append(kwargs)
                if self.owner.raises:
                    raise self.owner.raises
                return FakeResponse(self.owner.returns)

        class _Chat:
            def __init__(self, owner):
                self.completions = _Completions(owner)

        self.calls = []
        self.returns = returns
        self.raises = raises
        self.chat = _Chat(self)