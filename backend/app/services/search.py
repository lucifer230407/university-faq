from app.db.documentdb import db
from app.services.embeddings import generate_embedding


def search_documents(query: str, limit: int = 5, agent_ns: str = None) -> list[dict]:
    """
    Perform a vector search against the documents collection.

    Args:
        query: The user's natural language question.
        limit: Maximum number of results to return.
        agent_ns: Optional namespace filter (e.g., 'academics', 'admissions').

    Returns:
        A list of matching documents with text, metadata, and similarity score.
    """
    query_vector = generate_embedding(query)

    documents = db["documents"]

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

    results = list(documents.aggregate(pipeline))

    # Filter by namespace if provided
    if agent_ns:
        results = [
            r for r in results
            if r.get("metadata", {}).get("agent_ns") == agent_ns
        ]

    return results
