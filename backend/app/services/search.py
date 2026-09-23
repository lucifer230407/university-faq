from app.db.documentdb import db
from app.services.embeddings import generate_embedding


def is_official_source(metadata: dict | None) -> bool:
    """Seeded FAQs and admin-marked uploads only.

    Older student uploads use source_id ``upload:...`` without ``trusted`` and
    must not ground answers.
    """
    meta = metadata or {}
    source_id = str(meta.get("source_id") or "")
    if source_id.startswith("upload:") and not meta.get("trusted"):
        return False
    return True


def search_documents(query: str, limit: int = 5, agent_ns: str = None) -> list[dict]:
    """
    Perform a vector search against the documents collection.

    Args:
        query: The user's natural language question.
        limit: Maximum number of results to return.
        agent_ns: Optional namespace filter (e.g., 'academics', 'admissions').
            Applied as a pre-filter inside the search itself so k results are
            *all* from the requested namespace.

    Returns:
        A list of matching documents with text, metadata, and similarity score.
    """
    query_vector = generate_embedding(query)

    documents = db["documents"]

    search_options = {
        "vector": query_vector,
        "path": "vector",
        "k": max(limit * 4, limit)
    }

    # Pre-filter inside cosmosSearch so retrieval stays within the namespace.
    if agent_ns:
        search_options["filter"] = {
            "metadata.agent_ns": {"$eq": agent_ns}
        }

    pipeline = [
        {
            "$search": {
                "cosmosSearch": search_options
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

    results = [r for r in results if is_official_source(r.get("metadata"))]
    if agent_ns:
        results = [
            r for r in results
            if r.get("metadata", {}).get("agent_ns") == agent_ns
        ]

    return results[:limit]
