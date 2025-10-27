"""
Script to index biomedical domain knowledge into Azure Cognitive Search
"""
import re
import json
import asyncio
import os
from pathlib import Path
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.storage.blob import BlobServiceClient
import openai
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


def chunk_markdown(file_path):
    """
    Split markdown into sections by ## headers.
    Each section becomes a searchable chunk.
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Split by ## headers (second-level headers)
    sections = re.split(r'\n## ', content)
    chunks = []

    for i, section in enumerate(sections[1:], start=1):  # Skip first (title)
        lines = section.split('\n', 1)
        title = lines[0].strip()
        body = lines[1] if len(lines) > 1 else ''

        chunk = {
            'id': f'biomedical_knowledge_{i:03d}',
            'title': title,
            'content': f"## {title}\n{body}",
            'filename': 'biomedical_sql_domain_knowledge.md',
            'category': 'biomedical_sql_knowledge'
        }
        chunks.append(chunk)
        print(colored(f"  Chunk {i}: {title[:60]}...", "cyan"))

    return chunks


async def generate_embeddings(texts):
    """
    Generate embeddings using Azure OpenAI for semantic search.
    """
    llm = openai.AsyncAzureOpenAI(
        api_key=AZURE_OPENAI_KEY,
        api_version="2023-03-15-preview",
        azure_endpoint=AZURE_OPENAI_ENDPOINT
    )

    embeddings = []
    for i, text in enumerate(texts, 1):
        print(colored(f"  Generating embedding {i}/{len(texts)}...", "yellow"), end='\r')
        response = await llm.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        embeddings.append(response.data[0].embedding)

    print()  # New line after progress
    return embeddings


def upload_to_search(chunks):
    """
    Upload chunks to Azure Cognitive Search index.
    """
    search_client = SearchClient(
        endpoint=SEARCH_ENDPOINT,
        index_name=SEARCH_INDEX_NAME,
        credential=AzureKeyCredential(SEARCH_KEY)
    )

    # Prepare documents for upload
    documents = []
    for chunk in chunks:
        doc = {
            "id": chunk['id'],
            "content": chunk['content'],
            "filename": chunk['filename']
        }
        documents.append(doc)

    # Upload in batches
    result = search_client.upload_documents(documents=documents)

    success_count = sum(1 for r in result if r.succeeded)
    fail_count = sum(1 for r in result if not r.succeeded)

    print(colored(f"  Uploaded {success_count} documents successfully", "green"))
    if fail_count > 0:
        print(colored(f"  Failed to upload {fail_count} documents", "red"))

    return result


async def update_embeddings_blob(chunks, embeddings):
    """
    Update the embeddings blob with new embeddings.
    """
    blob_service = BlobServiceClient.from_connection_string(BLOB_CONNECTION_STRING)
    embeddings_blob = blob_service.get_blob_client(
        container=EMBEDDINGS_CONTAINER,
        blob=EMBEDDINGS_BLOB_NAME
    )

    # Load existing embeddings
    try:
        download_stream = embeddings_blob.download_blob()
        existing_data = download_stream.readall().decode('utf-8')
        existing_embeddings = json.loads(existing_data)
        print(colored(f"  Loaded {len(existing_embeddings)} existing embeddings", "cyan"))
    except Exception as e:
        print(colored(f"  No existing embeddings found, creating new: {e}", "yellow"))
        existing_embeddings = {}

    # Add new embeddings
    for chunk, embedding in zip(chunks, embeddings):
        existing_embeddings[chunk['id']] = embedding

    # Upload updated embeddings
    embeddings_json = json.dumps(existing_embeddings)
    embeddings_blob.upload_blob(embeddings_json, overwrite=True)

    print(colored(f"  Updated embeddings blob with {len(chunks)} new entries", "green"))
    print(colored(f"  Total embeddings in blob: {len(existing_embeddings)}", "green"))


async def main():
    """
    Main function to chunk, embed, and index biomedical domain knowledge.
    """
    print(colored("\n" + "="*80, "cyan"))
    print(colored("Biomedical Domain Knowledge Indexing", "cyan", attrs=['bold']))
    print(colored("="*80 + "\n", "cyan"))

    # Step 1: Chunk the markdown
    print(colored("Step 1: Chunking markdown file...", "yellow", attrs=['bold']))
    base_dir = Path(__file__).parent.parent
    markdown_path = base_dir / "config" / "biomedical_sql_domain_knowledge.md"

    if not markdown_path.exists():
        print(colored(f"ERROR: File not found: {markdown_path}", "red"))
        return

    chunks = chunk_markdown(markdown_path)
    print(colored(f"✅ Created {len(chunks)} chunks\n", "green"))

    # Step 2: Generate embeddings
    print(colored("Step 2: Generating embeddings...", "yellow", attrs=['bold']))
    texts = [chunk['content'] for chunk in chunks]
    embeddings = await generate_embeddings(texts)
    print(colored(f"✅ Generated {len(embeddings)} embeddings\n", "green"))

    # Step 3: Upload to search index
    print(colored("Step 3: Uploading to Azure Cognitive Search...", "yellow", attrs=['bold']))
    upload_to_search(chunks)
    print(colored(f"✅ Uploaded to search index\n", "green"))

    # Step 4: Update embeddings blob
    print(colored("Step 4: Updating embeddings blob...", "yellow", attrs=['bold']))
    await update_embeddings_blob(chunks, embeddings)
    print(colored(f"✅ Updated embeddings blob\n", "green"))

    # Summary
    print(colored("="*80, "cyan"))
    print(colored("✅ SUCCESS: Biomedical domain knowledge indexed!", "green", attrs=['bold']))
    print(colored("="*80 + "\n", "cyan"))
    print(colored("Next steps:", "yellow"))
    print(colored("1. Test retrieval: python scripts/test_knowledge_retrieval.py", "white"))
    print(colored("2. Disable pattern matching (optional)", "white"))
    print(colored("3. Test queries to verify LLM is using domain knowledge\n", "white"))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(colored("\n\nIndexing interrupted by user", "yellow"))
    except Exception as e:
        print(colored(f"\n\nERROR: {e}", "red"))
        import traceback
        traceback.print_exc()
