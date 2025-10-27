"""
Test script to verify biomedical domain knowledge retrieval
"""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path to import utility modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from utility.biomedical_knowledge_qdrant import get_relevant_domain_knowledge
from termcolor import colored


async def test_retrieval():
    """
    Test semantic retrieval of biomedical domain knowledge.
    """
    print(colored("\n" + "="*80, "cyan"))
    print(colored("Testing Biomedical Domain Knowledge Retrieval", "cyan", attrs=['bold']))
    print(colored("="*80 + "\n", "cyan"))

    test_queries = [
        {
            "query": "differential expression analysis tumor vs normal",
            "expected_topics": ["gene_statistics", "gene_comparison", "fold change", "tumor vs normal"]
        },
        {
            "query": "which table to use for fold change",
            "expected_topics": ["gene_comparison", "log2_fold_change", "precomputed"]
        },
        {
            "query": "how to interpret TPM values",
            "expected_topics": ["TPM", "detected", "expressed", "thresholds"]
        },
        {
            "query": "mutation stratified analysis KRAS",
            "expected_topics": ["cell_line_metadata", "KRAS_status", "mutation"]
        },
        {
            "query": "comprehensive statistics for gene expression",
            "expected_topics": ["mean", "median", "standard deviation", "n_samples"]
        }
    ]

    for i, test in enumerate(test_queries, 1):
        print(colored(f"\n{'='*80}", "yellow"))
        print(colored(f"Test {i}/{len(test_queries)}: {test['query']}", "yellow", attrs=['bold']))
        print(colored(f"{'='*80}", "yellow"))

        try:
            knowledge = await get_relevant_domain_knowledge(test['query'])

            if knowledge:
                print(colored("\n✅ Retrieved knowledge:", "green"))
                print(colored("-" * 80, "white"))

                # Show first 500 characters
                preview = knowledge[:500]
                print(preview)
                if len(knowledge) > 500:
                    print(colored("\n... (truncated, full content available)", "cyan"))

                print(colored("\n-" * 80, "white"))

                # Check if expected topics are present
                print(colored("\nExpected topics check:", "yellow"))
                for topic in test['expected_topics']:
                    if topic.lower() in knowledge.lower():
                        print(colored(f"  ✅ Found: {topic}", "green"))
                    else:
                        print(colored(f"  ❌ Missing: {topic}", "red"))

            else:
                print(colored("❌ No knowledge retrieved", "red"))

        except Exception as e:
            print(colored(f"❌ Error: {e}", "red"))
            import traceback
            traceback.print_exc()

    print(colored("\n" + "="*80, "cyan"))
    print(colored("Testing Complete", "cyan", attrs=['bold']))
    print(colored("="*80 + "\n", "cyan"))


if __name__ == "__main__":
    try:
        asyncio.run(test_retrieval())
    except KeyboardInterrupt:
        print(colored("\n\nTest interrupted by user", "yellow"))
    except Exception as e:
        print(colored(f"\n\nERROR: {e}", "red"))
        import traceback
        traceback.print_exc()
