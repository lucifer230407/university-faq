import os

from dotenv import load_dotenv
from openai import OpenAI

from app.db.documentdb import db


load_dotenv()

# Azure OpenAI
client = OpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    base_url=f"{os.getenv('AZURE_OPENAI_ENDPOINT')}/openai/v1/"
)

deployment = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")


def search_documents(query, limit=3):

    # Convert user query into an embedding
    response = client.embeddings.create(
        model=deployment,
        input=query
    )

    query_vector = response.data[0].embedding

    documents = db["documents"]

    # Azure DocumentDB vector search
    pipeline = [
        {
            "$search": {
                "cosmosSearch": {
                    "vector": query_vector,
                    "path": "vector",
                    "k": limit
                }
            }
        },
        {
            "$project": {
                "_id": 0,
                "text": 1,
                "metadata": 1,
                "score": {
                    "$meta": "searchScore"
                }
            }
        }
    ]

    results = documents.aggregate(pipeline)

    return list(results)


if __name__ == "__main__":

    query = "What subjects are covered in the B.Tech CSE program?"

    results = search_documents(query)

    print("\nSearch Results:\n")

    for i, result in enumerate(results, start=1):

        print(f"--- Result {i} ---")
        print("Score:", result.get("score"))
        print("Text:", result.get("text"))
        print("Metadata:", result.get("metadata"))
        print()