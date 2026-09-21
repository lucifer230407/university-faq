import os

from dotenv import load_dotenv
from openai import OpenAI

from app.config import settings

load_dotenv()

client = OpenAI(
    api_key=settings.AZURE_OPENAI_API_KEY,
    base_url=f"{settings.AZURE_OPENAI_ENDPOINT}/openai/v1/"
)

EMBEDDING_DEPLOYMENT = settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT


def generate_embedding(text: str) -> list[float]:
    """Generate a vector embedding for the given text."""
    response = client.embeddings.create(
        model=EMBEDDING_DEPLOYMENT,
        input=text
    )
    return response.data[0].embedding