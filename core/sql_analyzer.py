"""
SQL Query Analyzer and Evaluation System

This module provides comprehensive SQL query analysis with confidence scoring,
feedback collection, and continuous improvement tracking.
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum
from openai import AsyncAzureOpenAI
import logging

# Configure logging
logger = logging.getLogger(__name__)


class IssueSeverity(Enum):
    """Severity levels for SQL query issues"""
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class IssueType(Enum):
    """Types of issues that can be detected in SQL queries"""
    SYNTAX = "syntax"
    LOGIC = "logic"
    PERFORMANCE = "performance"
    DATA_QUALITY = "data_quality"
    SCHEMA_MISMATCH = "schema_mismatch"


class FeedbackType(Enum):
    """User feedback types"""
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    PARTIALLY_CORRECT = "partially_correct"


class SQLAnalyzer:
    """
    Analyzes SQL queries for correctness and relevance using Azure OpenAI.

    Attributes:
        schema (str): The database schema.
        relevant_query (list): List of similar past queries.
        relevant_domain_knowledge (list): List of relevant domain knowledge.
        description (str): Description of the database.
        custom_instructions (str): Any custom instructions provided by the user.
        tables_description (str): Description of the tables involved in the query.
        user_question (str): The user's original question.
        sql_query (str): The SQL query to be analyzed.
        dialect (str): The SQL dialect used (e.g., MySQL, PostgreSQL).
        df_preview (str): A preview of the dataframe resulting from the SQL query.
        confidence_threshold (float): Minimum confidence score required (default: 75.0).
        max_retries (int): Maximum number of query regeneration attempts (default: 3).
    """

    def __init__(
        self,
        schema: str,
        relevant_query: List[str],
        relevant_domain_knowledge: List[str],
        description: str,
        custom_instructions: str,
        tables_description: str,
        user_question: str,
        sql_query: str,
        dialect: str,
        df_preview: str,
        confidence_threshold: float = 75.0,
        max_retries: int = 3,
        api_key: Optional[str] = None,
        api_version: str = "2023-03-15-preview",
        azure_endpoint: Optional[str] = None
    ):
        """
        Initialize SQLAnalyzer with query context and configuration.

        Args:
            api_key: Azure OpenAI API key (defaults to AZURE_OPENAI_API_KEY env var)
            azure_endpoint: Azure OpenAI endpoint (defaults to AZURE_OPENAI_ENDPOINT env var)
        """
        self.schema = schema
        self.relevant_query = relevant_query
        self.relevant_domain_knowledge = relevant_domain_knowledge
        self.description = description
        self.custom_instructions = custom_instructions
        self.tables_description = tables_description
        self.user_question = user_question
        self.sql_query = sql_query
        self.dialect = dialect
        self.df_preview = df_preview
        self.confidence_threshold = confidence_threshold
        self.max_retries = max_retries

        # Initialize Azure OpenAI client with environment variables
        # Support both AZURE_OPENAI_API_KEY and AZURE_OPENAI_KEY for compatibility
        api_key_value = api_key or os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("AZURE_OPENAI_KEY")
        endpoint_value = azure_endpoint or os.getenv("AZURE_OPENAI_ENDPOINT")

        # Validate before creating client
        if not api_key_value:
            raise ValueError("Azure OpenAI API key not provided. Set AZURE_OPENAI_API_KEY or AZURE_OPENAI_KEY environment variable.")
        if not endpoint_value:
            raise ValueError("Azure OpenAI endpoint not provided. Set AZURE_OPENAI_ENDPOINT environment variable.")

        self.client = AsyncAzureOpenAI(
            api_key=api_key_value,
            api_version=api_version,
            azure_endpoint=endpoint_value
        )

    def _create_prompt(self) -> str:
        """
        Create a comprehensive prompt for SQL query analysis.

        Returns:
            str: Formatted prompt for the LLM
        """
        return f"""
You are an expert SQL analyzer with deep knowledge of database design, query optimization, and data quality.

DATABASE CONTEXT:
Schema: {self.schema}
Tables Description: {self.tables_description}
Database Description: {self.description}
SQL Dialect: {self.dialect}

USER REQUEST:
Question: {self.user_question}
Custom Instructions: {self.custom_instructions}

REFERENCE DATA:
Similar Past Queries: {self.relevant_query}
Domain Knowledge: {self.relevant_domain_knowledge}

GENERATED SOLUTION:
SQL Query:
{self.sql_query}

Result Preview (first 5 rows):
{self.df_preview}

ANALYSIS REQUIRED:
Evaluate this SQL query comprehensively across the following dimensions:

1. **Correctness** (30 points):
   - Does the SQL syntax match the schema and dialect?
   - Are all referenced tables and columns valid?
   - Are data types used correctly?

2. **Relevance** (30 points):
   - Does this query answer the user's question?
   - Are all required data points included?
   - ⚠️ CRITICAL: Are filters mentioned in user question present? (year, date ranges, status, etc.)
   - Is the query scope appropriate (not too broad/narrow)?

3. **Completeness** (20 points):
   - Are all necessary JOINs included?
   - ⚠️ CRITICAL: Are WHERE clauses matching user's filtering requirements?
   - ⚠️ CRITICAL: Are aggregations correct?
   - ⚠️ CRITICAL AGGREGATION RULE: If user asks for "levels", "expression", "compare groups", or summary statistics:
     * Query MUST include GROUP BY with aggregations (AVG, MEDIAN, STDDEV, COUNT)
     * Query MUST NOT return raw individual sample rows
     * Missing GROUP BY = "warning" severity, deduct 10 points from Completeness
   - ⚠️ If user specifies a year/date/time period, is it filtered in WHERE clause?

4. **Performance** (10 points):
   - Are there obvious optimization issues?
   - Cartesian products or missing indexes?
   - Unnecessary complexity?
   - ⚠️ CRITICAL PERFORMANCE RULES:
     * If query returns >1000 rows without GROUP BY → CRITICAL issue, score Performance ≤ 3/10
     * If query uses gene_expression without WHERE filtering to specific genes → CRITICAL issue
     * If query could use gene_statistics but uses gene_expression → WARNING issue
       (EXCEPTION: Mutation-stratified queries with cell_line_metadata join are OK)
     * Missing LIMIT clause on large result sets → WARNING issue

5. **Data Quality** (10 points):
   - Do results look reasonable given the preview?
   - Are NULLs handled appropriately?
   - Are there data type mismatches?

6. **Table Selection** (NEW CHECK):
   - **FIRST CHECK**: Does user ask for "RAW", "individual", "sample-level" data?
     * If YES → gene_expression is CORRECT (do NOT suggest gene_statistics)
     * User Query examples: "RAW expression values", "individual sample TPM", "sample-level data"
   - For simple "show/compare expression" queries → Should use gene_statistics (NOT gene_expression)
   - For tumor vs normal comparisons → Use gene_statistics table (UNLESS user asks for RAW data)
   - **EXCEPTION**: Mutation-stratified queries (EGFR_status, KRAS_status, TP53_status) MUST use gene_expression
   - Use gene_expression for: RAW/individual/sample-level data, mutation filtering, or custom aggregations

IMPORTANT RULES FOR SCORING:
- If user mentions a specific year/date/time period and it's NOT in WHERE clause → Mark as CRITICAL issue with "critical" severity
- If query returns data from wrong time period → Deduct at least 10 points from Relevance
- Missing filters = Incomplete query, score Completeness ≤ 12/20
- ⚠️ AGGREGATION RULE: If user asks for "levels", "expression", "compare", or summary statistics (WITHOUT "RAW", "individual"):
  * Query WITHOUT GROUP BY and aggregations → Mark as WARNING issue with "warning" severity
  * Description: "Query returns raw sample rows instead of aggregated statistics (mean, median, SD, n)"
  * Score Completeness ≤ 10/20 (50% penalty)
  * This will drop confidence below 75%, triggering retry with correct GROUP BY pattern
  * **EXCEPTION**: If user explicitly asks for "RAW" or "individual" values, raw data is CORRECT
- ⚠️ PERFORMANCE RULE: If query would return >10,000 rows:
  * Mark as CRITICAL issue with "critical" severity
  * Description: "Query will return too many rows (>10K). Add WHERE filters or use gene_statistics table."
  * Score Performance ≤ 2/10
  * This will drop confidence below 75%, triggering retry with proper filtering
  * **EXCEPTION**: If user asks for "RAW" or "individual" data, this is expected
- ⚠️ TABLE SELECTION RULE: If query uses gene_expression for simple "show/compare expression" questions:
  * **EXCEPTION 1**: User explicitly asks for "RAW", "individual", or "sample-level" data → gene_expression is CORRECT
  * **EXCEPTION 2**: Mutation-stratified queries (filtering by EGFR_status, KRAS_status, TP53_status) MUST use gene_expression
  * Check if query joins with cell_line_metadata for mutation filtering - if YES, gene_expression is CORRECT
  * If NO mutation filtering AND NO "RAW"/"individual" request (simple Tumor vs Normal comparison), mark as CRITICAL issue
  * Description: "Should use gene_statistics table (pre-aggregated) instead of gene_expression for simple comparison queries"
  * Score Relevance ≤ 15/30
  * This will drop confidence below 75%, triggering retry with correct table

Return ONLY valid JSON with this exact structure:
{{
    "confidence_score": <float 0-100>,
    "feedback": "<brief 2-3 sentence summary>",
    "issues": [
        {{
            "type": "<syntax|logic|performance|data_quality|schema_mismatch>",
            "severity": "<critical|warning|info>",
            "description": "<specific issue description>"
        }}
    ],
    "suggested_improvements": [
        "<actionable improvement suggestion>"
    ],
    "correctness_score": <float 0-30>,
    "relevance_score": <float 0-30>,
    "completeness_score": <float 0-20>,
    "performance_score": <float 0-10>,
    "data_quality_score": <float 0-10>
}}
"""

    async def analyze_query(self) -> Dict[str, Any]:
        """
        Analyze the SQL query and return detailed feedback with confidence score.

        Returns:
            Dict containing:
                - confidence_score: float (0-100)
                - feedback: str
                - issues: List[Dict]
                - suggested_improvements: List[str]
                - detailed scores for each dimension
        """
        try:
            prompt = self._create_prompt()

            response = await self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a highly skilled SQL analyzer and database engineer. "
                                   "Provide thorough, accurate analysis with actionable feedback."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0,
                response_format={"type": "json_object"}
            )

            analysis_result = json.loads(response.choices[0].message.content)

            # Validate and sanitize the response
            return self._validate_analysis_result(analysis_result)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse analyzer response: {str(e)}")
            return self._create_error_response(f"JSON parsing error: {str(e)}")
        except Exception as e:
            logger.error(f"Error analyzing SQL query: {str(e)}")
            return self._create_error_response(str(e))

    def _validate_analysis_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate and ensure all required fields are present in analysis result.

        Args:
            result: Raw analysis result from LLM

        Returns:
            Validated and sanitized analysis result
        """
        validated = {
            "confidence_score": float(result.get("confidence_score", 0.0)),
            "feedback": result.get("feedback", "No feedback provided"),
            "issues": result.get("issues", []),
            "suggested_improvements": result.get("suggested_improvements", []),
            "correctness_score": float(result.get("correctness_score", 0.0)),
            "relevance_score": float(result.get("relevance_score", 0.0)),
            "completeness_score": float(result.get("completeness_score", 0.0)),
            "performance_score": float(result.get("performance_score", 0.0)),
            "data_quality_score": float(result.get("data_quality_score", 0.0)),
        }

        # Ensure confidence score is within bounds
        validated["confidence_score"] = max(0.0, min(100.0, validated["confidence_score"]))

        return validated

    def _create_error_response(self, error_message: str) -> Dict[str, Any]:
        """
        Create a standardized error response.

        Args:
            error_message: Error description

        Returns:
            Error response dictionary
        """
        return {
            "confidence_score": 0.0,
            "feedback": f"Error analyzing SQL query: {error_message}",
            "issues": [
                {
                    "type": "analysis_error",
                    "severity": "critical",
                    "description": error_message
                }
            ],
            "suggested_improvements": ["Unable to provide suggestions due to analysis error"],
            "correctness_score": 0.0,
            "relevance_score": 0.0,
            "completeness_score": 0.0,
            "performance_score": 0.0,
            "data_quality_score": 0.0,
        }

    def meets_threshold(self, analysis_result: Dict[str, Any]) -> bool:
        """
        Check if the confidence score meets the configured threshold.

        Args:
            analysis_result: Analysis result from analyze_query()

        Returns:
            bool: True if confidence score >= threshold
        """
        return analysis_result.get("confidence_score", 0.0) >= self.confidence_threshold

    def get_critical_issues(self, analysis_result: Dict[str, Any]) -> List[Dict[str, str]]:
        """
        Extract only critical issues from analysis result.

        Args:
            analysis_result: Analysis result from analyze_query()

        Returns:
            List of critical issues
        """
        return [
            issue for issue in analysis_result.get("issues", [])
            if issue.get("severity") == "critical"
        ]
