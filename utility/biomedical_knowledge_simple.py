"""
Simple in-memory biomedical domain knowledge retrieval
NO external dependencies - just keyword matching and caching
"""
import os
import re
from pathlib import Path
from typing import Dict, List
from dotenv import load_dotenv

load_dotenv()


class SimpleBiomedicalKnowledgeRetriever:
    """
    Lightweight retriever using keyword matching instead of semantic search.
    No external dependencies (no Qdrant, no Azure Search).
    """

    def __init__(self, markdown_path: str = None):
        if markdown_path is None:
            base_dir = Path(__file__).parent.parent
            markdown_path = base_dir / "config" / "biomedical_sql_domain_knowledge.md"

        self.markdown_path = markdown_path
        self.chunks: List[Dict] = []
        self._load_and_chunk()

    def _load_and_chunk(self):
        """Load markdown and chunk by ## headers"""
        if not os.path.exists(self.markdown_path):
            print(f"Warning: Domain knowledge file not found: {self.markdown_path}")
            return

        with open(self.markdown_path, 'r', encoding='utf-8') as f:
            content = f.read()

        sections = re.split(r'\n## ', content)

        for i, section in enumerate(sections[1:], start=1):
            lines = section.split('\n', 1)
            title = lines[0].strip()
            body = lines[1] if len(lines) > 1 else ''
            full_content = f"## {title}\n{body}"

            # Extract keywords for matching (lowercase)
            keywords = self._extract_keywords(title + " " + body)

            self.chunks.append({
                'id': i,
                'title': title,
                'content': full_content,
                'keywords': keywords
            })

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract relevant keywords from text"""
        text_lower = text.lower()

        # Domain-specific keywords to extract
        important_terms = [
            'differential', 'expression', 'fold change', 'log2fc',
            'tumor', 'normal', 'tissue', 'cell line',
            'mutation', 'kras', 'tp53', 'egfr',
            'gene_statistics', 'gene_comparison', 'gene_expression',
            'tpm', 'mean', 'median', 'statistics',
            'join', 'sample', 'metadata',
            'upregulated', 'downregulated', 'significant',
            'comparison', 'aggregate', 'precomputed'
        ]

        found_keywords = []
        for term in important_terms:
            if term in text_lower:
                found_keywords.append(term)

        return found_keywords

    def search(self, query: str, top_k: int = 3) -> str:
        """
        Simple keyword-based search for relevant chunks.

        Args:
            query: User's question
            top_k: Number of top chunks to return

        Returns:
            Concatenated content of top matching chunks
        """
        if not self.chunks:
            return ""

        query_lower = query.lower()
        query_keywords = self._extract_keywords(query)

        # Score each chunk
        scored_chunks = []
        for chunk in self.chunks:
            score = 0

            # Keyword matching
            for keyword in query_keywords:
                if keyword in chunk['keywords']:
                    score += 2  # Keyword match

                # Check if keyword appears in title (higher weight)
                if keyword in chunk['title'].lower():
                    score += 5

            # Check for exact phrase matches in content
            for phrase in ['differential expression', 'fold change', 'tumor vs normal',
                          'gene_statistics', 'gene_comparison']:
                if phrase in query_lower and phrase in chunk['content'].lower():
                    score += 3

            if score > 0:
                scored_chunks.append((chunk, score))

        # Sort by score descending
        scored_chunks.sort(key=lambda x: x[1], reverse=True)

        # Return top_k chunks
        top_chunks = scored_chunks[:top_k]

        if not top_chunks:
            # Fallback: return general guidance chunks
            return self._get_general_chunks(top_k)

        return "\n\n".join([chunk['content'] for chunk, score in top_chunks])

    def _get_general_chunks(self, top_k: int) -> str:
        """Fallback: return general guidance when no specific matches"""
        # Return first few chunks as general guidance
        return "\n\n".join([chunk['content'] for chunk in self.chunks[:top_k]])


# Singleton instance
_simple_retriever = None


def get_simple_biomedical_knowledge_retriever() -> SimpleBiomedicalKnowledgeRetriever:
    """Get or create simple knowledge retriever (singleton)"""
    global _simple_retriever
    if _simple_retriever is None:
        _simple_retriever = SimpleBiomedicalKnowledgeRetriever()
    return _simple_retriever


def get_relevant_domain_knowledge_simple(query: str, top_k: int = 3) -> str:
    """
    Retrieve relevant biomedical domain knowledge using simple keyword matching.

    NO external dependencies - works immediately without indexing.
    Drop-in replacement for Azure Search and Qdrant versions.
    """
    retriever = get_simple_biomedical_knowledge_retriever()
    return retriever.search(query, top_k)


# Test function
if __name__ == "__main__":
    retriever = SimpleBiomedicalKnowledgeRetriever()

    test_queries = [
        "differential expression analysis tumor vs normal",
        "which table to use for fold change",
        "how to interpret TPM values"
    ]

    print("=" * 80)
    print("Testing Simple Biomedical Knowledge Retrieval")
    print("=" * 80)

    for query in test_queries:
        print(f"\nQuery: {query}")
        print("-" * 80)
        result = retriever.search(query, top_k=2)
        print(result[:300] + "...")
        print()
