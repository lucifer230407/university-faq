import os
from pymongo import MongoClient
from dotenv import load_dotenv
import certifi

load_dotenv()

DOCUMENTDB_URI = os.getenv("DOCUMENTDB_URI")

client = MongoClient(
    DOCUMENTDB_URI,
    tlsCAFile=certifi.where(),
    serverSelectionTimeoutMS=5000
)

db = client["university_faq"]

documents = db["documents"]
fee_deadlines = db["fee_deadlines"]
exam_schedules = db["exam_schedules"]
holidays = db["holidays"]


def test_connection():
    try:
        client.admin.command("ping")
        print("Connected to Azure DocumentDB successfully!")
        return True
    except Exception as e:
        print("DocumentDB connection failed:")
        print(e)
        raise