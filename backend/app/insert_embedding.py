import os

from dotenv import load_dotenv
from openai import OpenAI

from app.db.documentdb import db


load_dotenv()


# Azure OpenAI client
endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
api_key = os.getenv("AZURE_OPENAI_API_KEY")
deployment = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")

client = OpenAI(
    api_key=api_key,
    base_url=f"{endpoint}/openai/v1/"
)


# Example university document
text = """
B.Tech Computer Science and Engineering is an undergraduate program.
Students seeking admission must satisfy the university's published
eligibility requirements. The program covers computer science,
programming, data structures, artificial intelligence, machine learning,
databases, and software engineering.
"""


# Generate embedding
response = client.embeddings.create(
    model=deployment,
    input=text
)

embedding = response.data[0].embedding


# Store in DocumentDB
documents = db["documents"]

document = {
    "text": text.strip(),
    "metadata": {
        "agent_ns": "academics",
        "source_id": "test_academics_001",
        "page": 1,
        "campus": "Chandigarh",
        "level": "UG"
    },
    "vector": embedding
}

result = documents.insert_one(document)

print("Document inserted successfully!")
print("Document ID:", result.inserted_id)
print("Vector dimensions:", len(embedding))