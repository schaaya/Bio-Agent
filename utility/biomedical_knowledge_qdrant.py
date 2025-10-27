"""
Biomedical Domain Knowledge Retrieval using Qdrant
Alternative to Azure Cognitive Search
"""
import os
import sys
import re
import asyncio
from pathlib import Path
from typing import List, Dict

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models
from dotenv import load_dotenv
from termcolor import colored
from utility.tools import generate_embedding

load_dotenv()

QDRANT_URL = os.getenv("QDRANT_ENDPOINT")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")


class BiomedicalKnowledgeRetriever:
    """
    Retrieves biomedical SQL domain knowledge using Qdrant vector search.
    """

    def __init__(self, collection_name: str = "biomedical_sql_knowledge"):
        self.collection_name = collection_name
        self.qdrant_client = AsyncQdrantClient(
            url=QDRANT_URL,
            api_key=QDRANT_API_KEY,
            timeout=120,
            prefer_grpc=True
        )

    @classmethod
    async def create(cls, collection_name: str = "biomedical_sql_knowledge"):
        """Factory method to create and initialize retriever"""
        self = cls(collection_name)
        await self._create_collection_if_not_exists()
        return self

    async def _create_collection_if_not_exists(self, vector_size: int = 3072):
        """Create Qdrant collection if it doesn't exist"""
        try:
            existing = await self.qdrant_client.get_collections()
            collection_names = [c.name for c in existing.collections]

            if self.collection_name not in collection_names:
                await self.qdrant_client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(
                        size=vector_size,
                        distance=models.Distance.COSINE
                    )
                )
                print(colored(f"✅ Created collection '{self.collection_name}'", "green"))
            else:
                print(colored(f"✅ Collection '{self.collection_name}' exists", "cyan"))
        except Exception as e:
            print(colored(f"❌ Error creating collection: {e}", "red"))

    def chunk_markdown(self, file_path: str) -> List[Dict]:
        """Split markdown into sections by ## headers"""
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        sections = re.split(r'\n## ', content)
        chunks = []

        for i, section in enumerate(sections[1:], start=1):
            lines = section.split('\n', 1)
            title = lines[0].strip()
            body = lines[1] if len(lines) > 1 else ''

            chunk = {
                'id': i,
                'title': title,
                'content': f"## {title}\n{body}",
                'category': 'biomedical_sql_knowledge'
            }
            chunks.append(chunk)

        return chunks

    async def index_knowledge(self, markdown_path: str):
        """Index biomedical domain knowledge into Qdrant"""
        print(colored("\n" + "="*80, "cyan"))
        print(colored("Indexing Biomedical Knowledge to Qdrant", "cyan", attrs=['bold']))
        print(colored("="*80 + "\n", "cyan"))

        # Step 1: Chunk markdown
        print(colored("Step 1: Chunking markdown...", "yellow"))
        chunks = self.chunk_markdown(markdown_path)
        print(colored(f"✅ Created {len(chunks)} chunks\n", "green"))

        # Step 2: Generate embeddings
        print(colored("Step 2: Generating embeddings...", "yellow"))
        texts = [chunk['content'] for chunk in chunks]
        embeddings = await generate_embedding(texts)
        print(colored(f"✅ Generated {len(embeddings)} embeddings\n", "green"))

        # Step 3: Create points for Qdrant
        print(colored("Step 3: Uploading to Qdrant...", "yellow"))
        points = []
        for chunk, embedding in zip(chunks, embeddings):
            point = models.PointStruct(
                id=chunk['id'],
                vector=embedding if isinstance(embedding, list) else embedding.tolist(),
                payload={
                    "title": chunk['title'],
                    "content": chunk['content'],
                    "category": chunk['category']
                }
            )
            points.append(point)

        # Upsert in batches
        batch_size = 20
        for i in range(0, len(points), batch_size):
            batch = points[i:i+batch_size]
            await self.qdrant_client.upsert(
                collection_name=self.collection_name,
                wait=True,
                points=batch
            )
            print(colored(f"  Uploaded batch {i//batch_size + 1}/{(len(points)-1)//batch_size + 1}", "cyan"))

        print(colored(f"\n✅ Successfully indexed {len(points)} knowledge chunks!\n", "green"))
        print(colored("="*80, "cyan"))

    async def search(self, query: str, top_k: int = 3) -> str:
        """Search for relevant biomedical knowledge"""
        # Generate query embedding
        query_embedding = (await generate_embedding([query]))[0]
        if not isinstance(query_embedding, list):
            query_embedding = query_embedding.tolist()

        # Search Qdrant
        results = await self.qdrant_client.search(
            collection_name=self.collection_name,
            query_vector=query_embedding,
            limit=top_k,
            with_payload=True
        )

        # Combine results
        knowledge_texts = [hit.payload['content'] for hit in results]
        return "\n\n".join(knowledge_texts)


# Singleton instance
_retriever = None


async def get_biomedical_knowledge_retriever():
    """Get or create biomedical knowledge retriever"""
    global _retriever
    if _retriever is None:
        _retriever = await BiomedicalKnowledgeRetriever.create()
    return _retriever


async def get_relevant_domain_knowledge(query: str, top_k: int = 3) -> str:
    """
    Retrieve relevant biomedical domain knowledge.
    Drop-in replacement for Azure Search version.
    """
    retriever = await get_biomedical_knowledge_retriever()
    return await retriever.search(query, top_k)


async def search_biomedical_knowledge(query: str, top_k: int = 3) -> List[str]:
    """
    Search biomedical knowledge and return list of matching chunks.
    Used by visualization generator to get guidelines.
    """
    retriever = await get_biomedical_knowledge_retriever()
    query_embedding = (await generate_embedding([query]))[0]
    if not isinstance(query_embedding, list):
        query_embedding = query_embedding.tolist()

    results = await retriever.qdrant_client.search(
        collection_name=retriever.collection_name,
        query_vector=query_embedding,
        limit=top_k,
        with_payload=True
    )

    return [hit.payload['content'] for hit in results]


# CLI for indexing
async def main():
    """Index biomedical knowledge from command line"""
    retriever = await BiomedicalKnowledgeRetriever.create()

    base_dir = Path(__file__).parent.parent
    markdown_path = base_dir / "config" / "biomedical_sql_domain_knowledge.md"

    if not markdown_path.exists():
        print(colored(f"❌ File not found: {markdown_path}", "red"))
        return

    await retriever.index_knowledge(str(markdown_path))


if __name__ == "__main__":
    asyncio.run(main())
