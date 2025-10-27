#!/usr/bin/env python
import os
from dotenv import load_dotenv
from qdrant_client import QdrantClient

# Load environment variables
load_dotenv()

# Get the Qdrant endpoint and API key from environment variables
QUADRANT_URL = os.getenv("QDRANT_ENDPOINT")
QUADRANT_API_KEY = os.getenv("QDRANT_API_KEY")

# Specify the collection name you want to delete
COLLECTION_NAME = "schema_collection"

def delete_collection():
    """
    Connects to Qdrant and deletes the specified collection if it exists.
    This will remove all embeddings stored in that collection.
    """
    client = QdrantClient(url=QUADRANT_URL, api_key=QUADRANT_API_KEY)
    try:
        # Retrieve list of collections
        collections = client.get_collections()
        collection_names = [c.name for c in collections.collections]
        if COLLECTION_NAME in collection_names:
            print(f"Deleting collection '{COLLECTION_NAME}'...")
            client.delete_collection(collection_name=COLLECTION_NAME)
            print(f"Collection '{COLLECTION_NAME}' deleted successfully.")
        else:
            print(f"Collection '{COLLECTION_NAME}' does not exist. Nothing to delete.")
    except Exception as e:
        print(f"Error deleting collection '{COLLECTION_NAME}': {e}")

if __name__ == '__main__':
    delete_collection()
