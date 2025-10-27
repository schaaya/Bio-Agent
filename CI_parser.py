import os
import logging
import json
import asyncio
import openai
import spacy
import tiktoken
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.storage.blob import BlobServiceClient, BlobClient
from dotenv import load_dotenv
from termcolor import colored

from utility.tools import chat_completion_request


load_dotenv()

SEARCH_ENDPOINT = "https://bibotsearch.search.windows.net"
SEARCH_KEY = "v3pT7Q11rYvUFVEb2Rqaod35kBb5uOL8Ty62Ha4j7cAzSeDo6tqj"
SEARCH_INDEX_NAME = "sql-queries-index"

AZURE_OPENAI_KEY = '7d27e20cb4e54bf791b3f112f782ab59'
AZURE_OPENAI_ENDPOINT = "https://bibot.openai.azure.com/"

BLOB_CONNECTION_STRING = "DefaultEndpointsProtocol=https;AccountName=bibot;AccountKey=zPnWegYSh4PfzH8n5vgFy3Bh+kSjA3sf0BiJBo7HyjOcpASUmMFhH0A3yKqCnK4ltWZgynufEsl3+AStgPKMbg==;EndpointSuffix=core.windows.net"
EMBEDDINGS_CONTAINER = "custom-ins-embeddings"
EMBEDDINGS_BLOB_NAME = "embeddings.json"


# Initialize OpenAI client
llm = openai.AsyncAzureOpenAI(
    api_key=AZURE_OPENAI_KEY,
    api_version="2023-03-15-preview",
    azure_endpoint=AZURE_OPENAI_ENDPOINT
)

# Initialize Blob Service Client
blob_service_client = BlobServiceClient.from_connection_string(BLOB_CONNECTION_STRING)
embeddings_blob_client = blob_service_client.get_blob_client(container=EMBEDDINGS_CONTAINER, blob=EMBEDDINGS_BLOB_NAME)

# Initialize Search Client
credential = AzureKeyCredential(SEARCH_KEY)
search_client = SearchClient(endpoint=SEARCH_ENDPOINT, index_name=SEARCH_INDEX_NAME, credential=credential)

try:
    nlp = spacy.load("en_core_web_sm", disable=["ner", "parser"])
    if not nlp.has_pipe("sentencizer"):
        nlp.add_pipe("sentencizer", first=True)
except OSError:
    logging.info("Downloading spaCy model...")
    spacy.cli.download("en_core_web_sm")
    nlp = spacy.load("en_core_web_sm", disable=["ner", "parser"])
    if not nlp.has_pipe("sentencizer"):
        nlp.add_pipe("sentencizer", first=True)
        
def extract_text_from_blob(container_name: str, blob_name: str) -> str:
    """
    Extract text from a blob in Azure Blob Storage.
    """
    try:
        blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)
        download_stream = blob_client.download_blob()
        file_content = download_stream.readall().decode('utf-8')
        return file_content
    except UnicodeDecodeError:
        logging.warning("Failed to decode as UTF-8 text; handle PDF/Doc parsing.")
        return "Extracted content from non-UTF8-based doc..."
    except Exception as e:
        logging.error(f"Error extracting text from blob: {e}")
        return ""

def split_into_sentences(text: str, model="en_core_web_sm") -> list:
    """
    Splits text into a list of sentences using spaCy's sentence segmentation.
    """

    doc = nlp(text)
    sentences = [sent.text.strip() for sent in doc.sents if sent.text.strip()]
    return sentences

def chunk_text_for_semantic_search(
    text: str,
    model_name: str = "gpt-4o-mini",
    chunk_size: int = 512,
    sentence_overlap: int = 1
) -> list:
    """
    Splits text into token-based chunks, preserving sentence boundaries
    and adds a sliding window overlap of N sentences.
    """
    sentences = split_into_sentences(text)
    tokenizer = tiktoken.encoding_for_model(model_name)

    chunks = []
    current_chunk_sentences = []
    current_token_count = 0

    for i, sentence in enumerate(sentences):
        sentence_tokens = tokenizer.encode(sentence, disallowed_special=())

        if current_token_count + len(sentence_tokens) > chunk_size:
            chunk_text = " ".join(current_chunk_sentences).strip()
            if chunk_text:
                chunks.append(chunk_text)

            # Reset for the next chunk
            current_chunk_sentences = []
            current_token_count = 0

            # Add overlap sentences
            overlap_start_idx = max(0, i - sentence_overlap)
            for j in range(overlap_start_idx, i):
                overlap_sentence = sentences[j]
                overlap_tokens = tokenizer.encode(overlap_sentence, disallowed_special=())
                current_chunk_sentences.append(overlap_sentence)
                current_token_count += len(overlap_tokens)

        # Add the current sentence
        current_chunk_sentences.append(sentence)
        current_token_count += len(sentence_tokens)

    # Add any leftover sentences as the last chunk
    if current_chunk_sentences:
        chunk_text = " ".join(current_chunk_sentences).strip()
        chunks.append(chunk_text)

    print(colored(f"Number of chunks: {len(chunks)}", "green"))
    print(colored(f"Chunks:\n{chunks}", "green"))
    return chunks

async def generate_embedding(text: str) -> list:
    """
    Generate embedding for a given text using Azure OpenAI.
    """
    try:
        response = await llm.embeddings.create(model="text-embedding-3-small", input=text)
        embedding = response.data[0].embedding
        return embedding
    except Exception as e:
        logging.error(f"Error generating embedding: {e}")
        return []

async def get_embeddings(chunks: list) -> list:
    """
    Generate embeddings for a list of text chunks.
    """
    embeddings = []
    for chunk in chunks:
        embedding = await generate_embedding(chunk)
        if embedding:
            embeddings.append(embedding)
    return embeddings

async def transform_text_into_facts(custom_instructions: str) -> str:
    """
    Transform the extracted custom_instructions into a facts document using a language model
    to make it easier for chunking.
    """
    messages = [
        {
            "role": "system",
            "content": (
                "You are a helpful assistant that transforms user instructions into a series of clear, "
                "comprehensive factual statements or bullet points while retaining all necessary information and keywords provided. The goal is to make the text easy to parse "
                "or chunk for further processing."
            )
        },
        {
            "role": "user",
            "content": (
                f"Please transform the following instructions into a factual representation:\n\n"
                f"{custom_instructions}"
            )
        }
    ]

    response = await chat_completion_request(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.3
    )

    facts_document = response.choices[0].message.content.strip()
    # print(colored(f"Facts Document:\n{facts_document}", "green"))
    return facts_document

def load_existing_embeddings() -> dict:
    """
    Load existing embeddings from Azure Blob Storage.
    """
    try:
        if not embeddings_blob_client.exists():
            return {}
        
        download_stream = embeddings_blob_client.download_blob()
        embeddings_data = download_stream.readall().decode('utf-8')
        embeddings_dict = json.loads(embeddings_data)
        return embeddings_dict
    except Exception as e:
        logging.warning(f"Could not load existing embeddings: {e}")
        return {}

def save_embeddings_to_blob(embeddings_dict: dict):
    """
    Save embeddings dictionary to Azure Blob Storage as JSON.
    """
    try:
        embeddings_json = json.dumps(embeddings_dict)
        embeddings_blob_client.upload_blob(embeddings_json, overwrite=True)
        logging.info(f"Embeddings successfully saved to Blob Storage ({EMBEDDINGS_BLOB_NAME}).")
    except Exception as e:
        logging.error(f"Failed to save embeddings to Blob Storage: {e}")

def upsert_chunks_into_search(chunks: list, embeddings: list, doc_name: str):
    """
    For each chunk, create a record to index into Azure Cognitive Search.
    Store embeddings externally in Azure Blob Storage.

    E.g., 
    {
      "id": "<unique>",
      "content": "<chunk text>",
      "filename": "<original doc name>"
    }
    """
    docs_to_upsert = []
    embeddings_to_save = {}

    for i, (chunk, vector) in enumerate(zip(chunks, embeddings)):
        doc_id = f"{doc_name}-{i}"
        doc_obj = {
            "id": doc_id,
            "content": chunk,
            "filename": doc_name
        }
        docs_to_upsert.append(doc_obj)
        embeddings_to_save[doc_id] = vector

    try:
        result = search_client.upload_documents(documents=docs_to_upsert)
        logging.info(f"Upserted {len(docs_to_upsert)} chunks into Azure Search for doc '{doc_name}'.")
        # print(f"Upload results: {result}")
    except Exception as e:
        logging.error(f"Failed to upload documents to Azure Search: {e}")
        return

    # Load existing embeddings
    existing_embeddings = load_existing_embeddings()
    existing_embeddings.update(embeddings_to_save)

    # Save updated embeddings to Blob Storage
    save_embeddings_to_blob(existing_embeddings)

async def delete_existing_documents(doc_name: str):
    """
    Deletes all documents in the Azure Cognitive Search index with the given filename.
    """
    try:
        loop = asyncio.get_event_loop()
        # Search for documents with the given filename
        search_results = await loop.run_in_executor(
            None,
            lambda: list(search_client.search(search_text="*", filter=f"filename eq '{doc_name}'", select="id"))
        )
        ids_to_delete = [result["id"] for result in search_results]

        if ids_to_delete:
            # Delete the documents
            await loop.run_in_executor(
                None,
                lambda: search_client.delete_documents(documents=[{"id": id} for id in ids_to_delete])
            )
            logging.info(f"Deleted {len(ids_to_delete)} existing documents for '{doc_name}' from search index.")
        else:
            logging.info(f"No existing documents found for '{doc_name}' in search index.")
    except Exception as e:
        logging.error(f"Error deleting documents: {e}")

def remove_embeddings_for_doc(doc_name: str, embeddings_dict: dict) -> dict:
    """
    Removes all embeddings entries for the given document name.
    """
    prefix = f"{doc_name}-"
    return {k: v for k, v in embeddings_dict.items() if not k.startswith(prefix)}

async def process_document():
    """
    High-level pipeline that:
      1) Deletes existing entries for the document
      2) Extracts text from the blob
      3) Transforms it into factual statements
      4) Splits into chunks
      5) Generates embeddings
      6) Upserts into Azure Cognitive Search
    """
    container_name = "custom-instructions-docs"
    blob_name = "custom_instructions.txt"
    doc_name = "custom-instructions"  # Define the document name

    # Step 1: Delete existing documents from search index
    await delete_existing_documents(doc_name)

    # Step 2: Remove existing embeddings for this document
    existing_embeddings = load_existing_embeddings()
    existing_embeddings = remove_embeddings_for_doc(doc_name, existing_embeddings)
    save_embeddings_to_blob(existing_embeddings)

    # Proceed with processing the document
    custom_instructions = extract_text_from_blob(container_name, blob_name)
    if not custom_instructions:
        logging.error("No content extracted from the blob. Exiting.")
        return
    
    # print(colored(f"Extracted Content:\n{custom_instructions}", "yellow"))

    transformed_text = await transform_text_into_facts(custom_instructions)
    chunks = chunk_text_for_semantic_search(transformed_text)

    if not chunks:
        logging.info("No content found to chunk. Exiting.")
        return

    embeddings = await get_embeddings(chunks)
    if not embeddings:
        logging.error("No embeddings generated. Exiting.")
        return

    upsert_chunks_into_search(chunks, embeddings, doc_name)
    logging.info(f"Document '{doc_name}' processed successfully.")

if __name__ == "__main__":
    
    logging.basicConfig(level=logging.INFO)
    asyncio.run(process_document())
