from app.db.documentdb import db

documents = db["documents"]

try:
    indexes = documents.index_information()

    print("Indexes on documents collection:")
    for name, info in indexes.items():
        print(f"\n{name}")
        print(info)

except Exception as e:
    print("Failed to retrieve indexes:")
    print(e)