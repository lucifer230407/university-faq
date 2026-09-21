from app.db.documentdb import db


def test_database():
    documents = db["documents"]

    result = documents.insert_one({
        "text": "TEST DOCUMENT - DELETE ME",
        "metadata": {
            "agent_ns": "test",
            "source_id": "test_document"
        }
    })

    print("Inserted:", result.inserted_id)

    document = documents.find_one({
        "_id": result.inserted_id
    })

    print("Found:", document)

    documents.delete_one({
        "_id": result.inserted_id
    })

    print("Test document deleted")


if __name__ == "__main__":
    test_database()