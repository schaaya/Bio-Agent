"""
Check the current state of the biomedical_sql_knowledge Qdrant collection
"""
import asyncio
import os
from dotenv import load_dotenv
from qdrant_client import AsyncQdrantClient

load_dotenv()

async def check_collection():
    """Check Qdrant collection stats"""

    # Get Qdrant connection details
    qdrant_endpoint = os.getenv("QDRANT_ENDPOINT")
    qdrant_api_key = os.getenv("QDRANT_API_KEY")

    if not qdrant_endpoint or not qdrant_api_key:
        print("❌ QDRANT_ENDPOINT or QDRANT_API_KEY not found in .env")
        return

    print("="*80)
    print("Checking Qdrant Collection: biomedical_sql_knowledge")
    print("="*80)
    print(f"\nQdrant Endpoint: {qdrant_endpoint}")

    try:
        # Connect to Qdrant
        client = AsyncQdrantClient(
            url=qdrant_endpoint,
            api_key=qdrant_api_key
        )

        # Get collection info
        collection_name = "biomedical_sql_knowledge"
        collection_info = await client.get_collection(collection_name)

        print(f"\n✅ Collection '{collection_name}' exists!")
        print(f"\n📊 Collection Stats:")
        print(f"   - Total points: {collection_info.points_count}")
        print(f"   - Vector size: {collection_info.config.params.vectors.size}")

        # Try to retrieve a few sample points to see their payloads
        print(f"\n📝 Sample Points:")

        scroll_result = await client.scroll(
            collection_name=collection_name,
            limit=5,
            with_payload=True,
            with_vectors=False
        )

        points = scroll_result[0]

        for i, point in enumerate(points, 1):
            print(f"\n   Point {i}:")
            payload = point.payload
            text_preview = payload.get('text', '')[:200] + "..." if len(payload.get('text', '')) > 200 else payload.get('text', '')
            print(f"      Text: {text_preview}")
            if 'metadata' in payload:
                print(f"      Metadata: {payload['metadata']}")

        # Search for mutation-related content
        print(f"\n🔍 Searching for mutation filtering rules...")

        from openai import AzureOpenAI

        azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        azure_key = os.getenv("AZURE_OPENAI_KEY")

        if azure_endpoint and azure_key:
            openai_client = AzureOpenAI(
                azure_endpoint=azure_endpoint,
                api_key=azure_key,
                api_version="2024-02-01"
            )

            # Create embedding for mutation-related query
            embedding_response = openai_client.embeddings.create(
                model="text-embedding-3-large",
                input="KRAS mutation filtering exclude Unknown"
            )
            query_vector = embedding_response.data[0].embedding

            # Search in Qdrant
            search_results = await client.search(
                collection_name=collection_name,
                query_vector=query_vector,
                limit=3,
                with_payload=True
            )

            print(f"\n   Top 3 results for 'KRAS mutation filtering':")
            for i, result in enumerate(search_results, 1):
                text_preview = result.payload.get('text', '')[:300]
                print(f"\n   Result {i} (score: {result.score:.4f}):")
                print(f"      {text_preview}...")

                # Check if it contains our new rules
                if "NOT IN ('WT', 'Unknown', '')" in result.payload.get('text', ''):
                    print(f"      ✅ Contains NEW mutation filtering rules!")
                elif "!= 'WT'" in result.payload.get('text', ''):
                    print(f"      ⚠️  Contains OLD filtering pattern")
        else:
            print("   ⚠️  Azure OpenAI credentials not found, skipping semantic search")

        await client.close()

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(check_collection())
