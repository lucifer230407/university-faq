import os

from dotenv import load_dotenv
# pyrefly: ignore [missing-import]
from openai import OpenAI

load_dotenv()

endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
api_key = os.getenv("AZURE_OPENAI_API_KEY")
deployment = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")

client = OpenAI(
    api_key=api_key,
    base_url=f"{endpoint}/openai/v1/"
)

text = "The university offers B.Tech Computer Science and Engineering."

response = client.embeddings.create(
    model=deployment,
    input=text
)

embedding = response.data[0].embedding

print("Embedding generated successfully!")
print("Dimensions:", len(embedding))
print("First 5 values:", embedding[:5])