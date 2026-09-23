import json
import os
import time

from app.db.documentdb import db
from app.services.embeddings import generate_embedding


def seed_faqs():
    """Load FAQ data from JSON, generate embeddings, and insert into DocumentDB.

    Re-running the seed replaces existing FAQ entries (matched by source_id)
    instead of creating duplicates. Uploaded documents are left untouched.
    """

    data_path = os.path.join(os.path.dirname(__file__), "..", "data", "faqs.json")

    with open(data_path, "r") as f:
        faqs = json.load(f)

    documents = db["documents"]

    # Remove only FAQ entries that we are about to re-insert.
    source_ids = [f["metadata"]["source_id"] for f in faqs if f.get("metadata")]
    if source_ids:
        deleted = documents.delete_many({"metadata.source_id": {"$in": source_ids}})
        print(f"Removed {deleted.deleted_count} existing FAQ document(s) for re-seed.\n")

    print(f"Seeding {len(faqs)} FAQ documents...\n")

    for i, faq in enumerate(faqs, start=1):
        text = faq["text"]
        metadata = faq["metadata"]

        embedding = generate_embedding(text)

        document = {
            "text": text,
            "metadata": metadata,
            "vector": embedding
        }

        result = documents.insert_one(document)

        print(f"[{i}/{len(faqs)}] Inserted: {metadata.get('source_id', 'unknown')} (ID: {result.inserted_id})")

        # Small delay to avoid rate limiting
        time.sleep(0.3)

    print(f"\nDone! Seeded {len(faqs)} documents into the 'documents' collection.")


if __name__ == "__main__":
    seed_faqs()