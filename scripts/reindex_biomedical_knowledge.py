"""
Reindex Biomedical Domain Knowledge to Qdrant

This script reindexes the biomedical SQL domain knowledge markdown file
into Qdrant vector database. Run this after updating:
- config/biomedical_sql_domain_knowledge.md

Usage:
    python scripts/reindex_biomedical_knowledge.py

What it does:
1. Connects to Qdrant (using QDRANT_ENDPOINT and QDRANT_API_KEY from .env)
2. Reads config/biomedical_sql_domain_knowledge.md
3. Chunks the markdown by ## headers
4. Generates embeddings for each chunk using Azure OpenAI
5. Uploads embeddings to Qdrant collection 'biomedical_sql_knowledge'

Time estimate: 2-3 minutes (depending on number of chunks and API speed)
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utility.biomedical_knowledge_qdrant import BiomedicalKnowledgeRetriever
from termcolor import colored


async def main():
    print(colored("\n" + "="*80, "cyan"))
    print(colored("Reindex Biomedical Domain Knowledge to Qdrant", "cyan", attrs=['bold']))
    print(colored("="*80 + "\n", "cyan"))

    # Create retriever
    print(colored("Step 1: Connecting to Qdrant...", "yellow"))
    retriever = await BiomedicalKnowledgeRetriever.create()
    print(colored("✅ Connected to Qdrant\n", "green"))

    # Find markdown file
    base_dir = Path(__file__).parent.parent
    markdown_path = base_dir / "config" / "biomedical_sql_domain_knowledge.md"

    if not markdown_path.exists():
        print(colored(f"❌ File not found: {markdown_path}", "red"))
        print(colored("   Make sure config/biomedical_sql_domain_knowledge.md exists\n", "yellow"))
        return

    print(colored(f"Step 2: Reading domain knowledge file...", "yellow"))
    print(colored(f"   File: {markdown_path}", "cyan"))
    file_size = markdown_path.stat().st_size / 1024
    print(colored(f"   Size: {file_size:.1f} KB\n", "cyan"))

    # Index knowledge
    await retriever.index_knowledge(str(markdown_path))

    # Verify
    print(colored("\nStep 4: Verifying indexing...", "yellow"))
    from qdrant_client.http import models as qdrant_models
    collection_info = await retriever.qdrant_client.get_collection(retriever.collection_name)
    print(colored(f"✅ Collection '{retriever.collection_name}' has {collection_info.points_count} points\n", "green"))

    print(colored("="*80, "cyan"))
    print(colored("✅ REINDEXING COMPLETE!", "green", attrs=['bold']))
    print(colored("="*80 + "\n", "cyan"))
    print(colored("Your chatbot will now use the updated domain knowledge.", "green"))
    print(colored("No need to restart the application - changes are live!\n", "green"))


if __name__ == "__main__":
    asyncio.run(main())
