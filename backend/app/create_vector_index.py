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
                    "dimensions": 1536,
                    "similarity": "COS",
                    "numLists": 1
                }
            }
        ]
    }

    result = db.command(command)

    print("Vector index created successfully!")
    print(result)


if __name__ == "__main__":
    create_vector_index()