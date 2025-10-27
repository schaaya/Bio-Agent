"""
Enhanced SQL Engine Stage 2 with Query Pattern Matching
Includes Tier 2 improvements for better JOIN accuracy
"""
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from core.DB_rules import rules
from core.globals import instructions_dict
from utility.tools import chat_completion_request
from utility.decorators import time_it


class QueryPatternMatcher:
    """Matches user queries to predefined SQL patterns"""

    def __init__(self, patterns_file: str = None):
        """
        Initialize pattern matcher

        Args:
            patterns_file: Path to biomedical_sql_patterns.json
        """
        if patterns_file is None:
            # Default path
            base_dir = Path(__file__).parent.parent
            patterns_file = base_dir / "NSLC" / "query_patterns" / "biomedical_sql_patterns.json"

        self.patterns_file = patterns_file
        self.patterns = self._load_patterns()

    def _load_patterns(self) -> List[Dict]:
        """Load query patterns from JSON file"""
        try:
            if not os.path.exists(self.patterns_file):
                print(f"Warning: Patterns file not found: {self.patterns_file}")
                return []

            with open(self.patterns_file, 'r') as f:
                data = json.load(f)
                return data.get('patterns', [])
        except Exception as e:
            print(f"Error loading query patterns: {e}")
            return []

    def match_pattern(self, user_query: str, top_k: int = 3) -> List[Tuple[Dict, float]]:
        """
        Match user query to patterns based on keyword matching

        Args:
            user_query: User's natural language question
            top_k: Number of top matches to return

        Returns:
            List of (pattern, score) tuples, sorted by score
        """
        if not self.patterns:
            return []

        query_lower = user_query.lower()
        matches = []

        for pattern in self.patterns:
            score = 0
            keywords = pattern.get('keywords', [])

            # Check if any keywords match
            for keyword in keywords:
                if keyword.lower() in query_lower:
                    # Weight longer matches higher
                    score += len(keyword.split())

            # Bonus for exact phrase matches
            for example in pattern.get('example_queries', []):
                if example.lower() in query_lower or query_lower in example.lower():
                    score += 5

            if score > 0:
                matches.append((pattern, score))

        # Sort by score descending
        matches.sort(key=lambda x: x[1], reverse=True)

        return matches[:top_k]

    def format_pattern_hint(self, pattern: Dict) -> str:
        """
        Format a matched pattern into a hint for the LLM

        Args:
            pattern: Pattern dictionary

        Returns:
            Formatted hint string
        """
        hint = f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║ MATCHED QUERY PATTERN: {pattern['pattern_name']}
║ Complexity Level: {pattern['complexity']}/5
╚══════════════════════════════════════════════════════════════════════════════╝

📋 REQUIRED TABLES:
   {', '.join(pattern['required_tables'])}

🔑 CRITICAL COLUMNS TO INCLUDE:
   {', '.join(pattern['critical_columns'])}

📝 SQL TEMPLATE (adapt as needed):
{pattern['sql_template']}

💡 EXPLANATION:
{pattern['explanation']}

⚠️  IMPORTANT REMINDERS:
"""
        # Add specific reminders based on pattern type
        if 'human_tissue_metadata' in pattern['required_tables']:
            hint += """
   • This query requires tumor/normal classification
   • MUST join human_tissue_metadata via samples table
   • MUST include tissue_type in SELECT clause for grouping
   • Use: gene_expression -> samples -> human_tissue_metadata
"""

        if 'cell_line_metadata' in pattern['required_tables']:
            hint += """
   • This query involves cell line mutation data
   • MUST join cell_line_metadata via samples table
   • Include mutation status columns (TP53_status, EGFR_status, KRAS_status) as needed
   • Use: gene_expression -> samples -> cell_line_metadata
"""

        if 'gene_statistics' in pattern['required_tables']:
            hint += """
   • Use gene_statistics for faster aggregated queries (precomputed)
   • This is PREFERRED over computing aggregations on gene_expression
   • Always include n_samples for transparency
"""

        if 'gene_comparison' in pattern['required_tables']:
            hint += """
   • Use gene_comparison for differential expression (precomputed fold changes)
   • Filter by |log2_fold_change| > 1 for 2-fold change (typical significance threshold)
   • Include comparison_type in SELECT
"""

        return hint


class Stage_two:
    """Enhanced SQL Generation Stage 2 with Pattern Matching"""

    # Class-level pattern matcher (lazy-loaded)
    _pattern_matcher: Optional[QueryPatternMatcher] = None

    @classmethod
    def _get_pattern_matcher(cls) -> QueryPatternMatcher:
        """Get or create pattern matcher instance"""
        if cls._pattern_matcher is None:
            cls._pattern_matcher = QueryPatternMatcher()
        return cls._pattern_matcher

    @classmethod
    @time_it
    def _create_prompt(cls, question, description, dialect, relevent_query, matched_patterns: List[Tuple[Dict, float]] = None):
        """
        Create prompt with optional pattern matching hints

        Args:
            question: User's question
            description: Schema description
            dialect: SQL dialect
            relevent_query: Similar query from history
            matched_patterns: List of (pattern, score) tuples from pattern matching
        """
        db_rules = rules[dialect]

        # Base prompt
        prompt = f"""
"Guidelines for generating query in {dialect}: {db_rules}"
"User's question and error message(if any): <<<{question}>>>"
"""

        # Add pattern hints if available
        if matched_patterns and len(matched_patterns) > 0:
            pattern, score = matched_patterns[0]  # Use top match

            pattern_hint = cls._get_pattern_matcher().format_pattern_hint(pattern)

            prompt += f"""
{pattern_hint}

IMPORTANT: The above pattern was matched with confidence score {score}/10.
Use it as a STRONG GUIDE for structuring your query, especially for:
- Which tables to join
- Which columns MUST be in SELECT clause
- The correct JOIN order and conditions

"""

        # Continue with rest of prompt
        prompt += f"""
"Tables and respective columns(with their dtypes) to answer user question: ((({description} )))"
"Relevant Query: ^^^ {relevent_query} ^^^"
"Don't use the columns and table names that are not in schema. Return the output in strict JSON format with no additional text, containing the validated query in proper dialect under the key 'sql_query'. The output must be a valid JSON object that can be extracted using `json.loads` and executed with `pd.read_sql(sql_query, engine)` on a database."
"If there is an Error Message, analyze it and make the necessary corrections to the query or data."
"""

        return prompt

    @classmethod
    @time_it
    async def generate_query(cls, user_id, question, description, dialect, relevent_query, relevant_domain_knowledge=None):
        """
        Generate SQL query with pattern matching

        Args:
            user_id: User identifier
            question: User's natural language question
            description: Schema description from Stage 1
            dialect: SQL dialect (e.g., 'SQLite')
            relevent_query: Similar query from history
            relevant_domain_knowledge: Domain-specific knowledge

        Returns:
            JSON string with generated SQL query
        """
        # Match query to patterns
        pattern_matcher = cls._get_pattern_matcher()
        matched_patterns = pattern_matcher.match_pattern(question, top_k=3)

        if matched_patterns:
            top_pattern = matched_patterns[0][0]
            print(f"✅ Matched pattern: {top_pattern['pattern_name']} (complexity {top_pattern['complexity']}/5)")
        else:
            print("⚠️  No pattern match found - using standard generation")

        # Get system prompt
        sql_engine_stage_2 = instructions_dict["SQL Engine stage 2"]

        # Add domain knowledge
        if relevant_domain_knowledge:
            sql_engine_stage_2 += f"\n\nRelevant Domain Specific Knowledge: {relevant_domain_knowledge}"

        # Create prompt with pattern hints
        prompt = cls._create_prompt(question, description, dialect, relevent_query, matched_patterns)

        messages = [
            {"role": "system", "content": f"""{sql_engine_stage_2}"""},
            {"role": "user", "content": prompt}
        ]

        # Generate query
        response = await chat_completion_request(user_id, messages, response_format=True)
        return response.model_dump()['choices'][0]['message']['content']
