import os
import uuid
import pandas as pd
import openai
from dotenv import load_dotenv
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
import asyncio

# Load environment variables
load_dotenv()

search_service_name = os.getenv("SEARCH_SERVICE_NAME")
search_api_key = os.getenv("SEARCH_KEY")
openai_api_key = os.getenv("OPENAI_API_KEY")
index_name = "sql-queries-index"

# Initialize Azure Cognitive Search client
endpoint = f"https://{search_service_name}.search.windows.net"
credential = AzureKeyCredential(search_api_key)
search_client = SearchClient(endpoint=endpoint, index_name=index_name, credential=credential)

# Initialize OpenAI
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")

llm = openai.AsyncAzureOpenAI(
            api_key=AZURE_OPENAI_KEY,  
            api_version="2023-03-15-preview",
            azure_endpoint=AZURE_OPENAI_ENDPOINT
        )


async def get_embedding(text, model="text-embedding-3-small"):
    try:
        response = await llm.embeddings.create(model="text-embedding-3-small", input=text)
        return response.data[0].embedding
    except Exception as e:
        print(f"Error generating embedding for text '{text}': {e}")
        return None

def delete_all_documents(search_client):
    try:
        print("Retrieving all document IDs for deletion...")
        results = search_client.search(search_text="*", select="id", include_total_count=False)
        documents_to_delete = [{"@search.action": "delete", "id": doc["id"]} for doc in results]

        if not documents_to_delete:
            print("No documents to delete.")
            return

        batch_size = 1000
        for i in range(0, len(documents_to_delete), batch_size):
            batch = documents_to_delete[i:i + batch_size]
            search_client.upload_documents(documents=batch)
            print(f"Deleted documents {i + 1} to {i + len(batch)}")

        print("All documents deleted successfully.")
    except Exception as e:
        print(f"Error deleting documents: {e}")

def upload_documents(search_client, documents):
    try:
        print("Uploading documents to the index...")
        result = search_client.upload_documents(documents=documents)
        print(f"Uploaded {len(result)} documents successfully.")
    except Exception as e:
        print(f"Error uploading documents: {e}")

async def prepare_documents_with_embeddings(csv_file_path):
    data = pd.read_csv(csv_file_path)
    documents = []
    failed_documents = []

    for _, row in data.iterrows():
        user_query = row["user_query"]
        sql_query = row["sql_query"]
        doc_id = str(uuid.uuid4())

        embedding = await get_embedding(user_query)
        if embedding:
            doc = {
                "id": doc_id,
                "user_query": user_query,
                "sql_query": sql_query,
                "user_query_vector": embedding
            }
            documents.append(doc)
            print(f"Prepared document ID {doc_id}")
        else:
            failed_documents.append(doc_id)
            print(f"Failed to generate embedding for document ID {doc_id}")

    print(f"Total documents prepared: {len(documents)}")
    if failed_documents:
        print(f"Failed to prepare {len(failed_documents)} documents.")
    return documents

async def main():
    # Step 1: Delete all existing documents
    # Uncomment the following line if you want to delete existing documents before uploading
    delete_all_documents(search_client)

    # Step 2: Prepare documents with embeddings
    # csv_file_path = "utility/queries.csv" 
    # documents = await prepare_documents_with_embeddings(csv_file_path)

    # if not documents:
    #     print("No documents to upload. Exiting.")
    #     return

    # # Step 3: Upload documents to Azure Cognitive Search
    # upload_documents(search_client, documents)

    # # Optional: Verify upload
    # verify_upload(search_client, len(documents))

def verify_upload(search_client, expected_count):
    try:
        print("Verifying the number of documents in the index...")
        results = search_client.search(search_text="*", select="id", include_total_count=True)
        count = sum(1 for _ in results)
        if count == expected_count:
            print(f"All {expected_count} documents are successfully indexed.")
        else:
            print(f"Indexed documents count mismatch. Expected: {expected_count}, Found: {count}")
    except Exception as e:
        print(f"Error verifying upload: {e}")



if __name__ == "__main__":
    asyncio.run(main())
