# search.py

import os
import json
import logging
import asyncio
import numpy as np
import openai
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.storage.blob import BlobServiceClient, BlobClient
from dotenv import load_dotenv
from termcolor import colored

# Load environment variables
load_dotenv()

SEARCH_ENDPOINT = os.getenv("SEARCH_ENDPOINT")
SEARCH_KEY = os.getenv("SEARCH_KEY")
SEARCH_INDEX_NAME = "sql-queries-index"

AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")

BLOB_CONNECTION_STRING = os.getenv("BLOB_CONNECTION_STRING")
EMBEDDINGS_CONTAINER = "custom-ins-embeddings"
EMBEDDINGS_BLOB_NAME = "embeddings.json"

TOP_K = 5 

llm = openai.AsyncAzureOpenAI(
    api_key=AZURE_OPENAI_KEY,
    api_version="2023-03-15-preview",
    azure_endpoint=AZURE_OPENAI_ENDPOINT
)

blob_service_client = BlobServiceClient.from_connection_string(BLOB_CONNECTION_STRING)
embeddings_blob_client = blob_service_client.get_blob_client(container=EMBEDDINGS_CONTAINER, blob=EMBEDDINGS_BLOB_NAME)


credential = AzureKeyCredential(SEARCH_KEY)
search_client = SearchClient(endpoint=SEARCH_ENDPOINT, index_name=SEARCH_INDEX_NAME, credential=credential)

def load_embeddings_from_blob() -> dict:
    """
    Load embeddings from Azure Blob Storage.
    """
    try:
        download_stream = embeddings_blob_client.download_blob()
        embeddings_data = download_stream.readall().decode('utf-8')
        embeddings_dict = json.loads(embeddings_data)
        return embeddings_dict
    except Exception as e:
        logging.error(f"Error loading embeddings from Blob Storage: {e}")
        return {}

async def generate_query_embedding(query: str) -> list:
    """
    Generate embedding for the user query using Azure OpenAI.
    """
    try:
        response = await llm.embeddings.create(model="text-embedding-3-small", input=query)
        embedding = response.data[0].embedding
        return embedding
    except Exception as e:
        logging.error(f"Error generating query embedding: {e}")
        return []

def cosine_similarity(vec1: list, vec2: list) -> float:
    """
    Compute cosine similarity between two vectors.
    """
    vec1 = np.array(vec1)
    vec2 = np.array(vec2)
    if np.linalg.norm(vec1) == 0 or np.linalg.norm(vec2) == 0:
        return 0.0
    return float(np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2)))

async def search_semantic(query: str) -> list:
    """
    Perform a two-stage semantic search:
      1. Use Azure Cognitive Search to retrieve top-k documents based on BM25.
      2. Re-rank the top-k documents based on cosine similarity of embeddings.

    :param query: User query string.
    :return: List of re-ranked documents with similarity scores.
    """
    
    # Search with total count enabled
    results = search_client.search(search_text="*", include_total_count=True)

    # Retrieve and print the total document count
    total_count = results.get_count()  # Returns the total number of documents matching the query
    print(f"Total number of documents in the index: {total_count}")

    try:
        results = search_client.search(search_text=query, top=TOP_K)
    except Exception as e:
        logging.error(f"Search query failed: {e}")
        return []

    retrieved_docs = []
    for result in results:
        retrieved_docs.append({
            "id": result["id"],
            "content": result["content"],
            "filename": result["filename"]
        })

    if not retrieved_docs:
        logging.info("No documents found.")
        return []

    
    query_embedding = await generate_query_embedding(query)
    if not query_embedding:
        logging.error("Failed to generate query embedding.")
        return retrieved_docs  

    embeddings_dict = load_embeddings_from_blob()

    
    for doc in retrieved_docs:
        doc_id = doc["id"]
        doc_embedding = embeddings_dict.get(doc_id)
        if doc_embedding:
            similarity = cosine_similarity(query_embedding, doc_embedding)
        else:
            similarity = 0.0 
        doc["similarity"] = similarity

    retrieved_docs = sorted(retrieved_docs, key=lambda x: x["similarity"], reverse=True)

    return retrieved_docs


async def get_relevant_domain_knowledge(query: str) -> list:
    """
    Retrieve relevant domain knowledge based on the user query.
    """
    results = await search_semantic(query)
    
    content = "\n".join([doc["content"] for doc in results])
    return content


