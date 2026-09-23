"""Create (or replace) the IVF vector index on the 'documents' collection.

Usage (from the backend/ directory):
    python -m scripts.create_vector_index

Sizes read from the app config (VECTOR_INDEX_DIMENSIONS / VECTOR_INDEX_NUMLISTS).
"""
from app.config import settings
from app.db.documentdb import db


def create_vector_index():
    documents = db["documents"]

    command = {
        "createIndexes": "documents",
        "indexes": [
            {
                "name": "vector_search_index",
                "key": {
                    "vector": "cosmosSearch"
                },
                "cosmosSearchOptions": {
                    "kind": "vector-ivf",
                    "dimensions": settings.VECTOR_INDEX_DIMENSIONS,
                    "similarity": settings.VECTOR_INDEX_SIMILARITY,
                    "numLists": settings.VECTOR_INDEX_NUMLISTS
                }
            }
        ]
    }

    result = db.command(command)

    print("Vector index created successfully!")
    print(result)


if __name__ == "__main__":
    create_vector_index()