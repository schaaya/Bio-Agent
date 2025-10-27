"""
SQL Agent - MCP Integration with Direct Tool Calls

IMPORTANT: This file contains both:
1. Unused Pydantic AI agent definitions (lines 68-292) - kept as reference
2. Active implementation using direct MCP calls (lines 299+)

CURRENT IMPLEMENTATION:
- The SQL_Agent_MCP() function (line 299) is the entry point
- It uses direct MCP calls: await mcp_client.call_tool("ask_database", args)
- It does NOT use the Pydantic AI agent or tool decorators above
- The Pydantic AI code remains for reference/future migration

WHY DIRECT MCP CALLS:
- We need precise control over retry logic based on confidence scores
- Custom error handling with context passing for retries
- Simple, predictable execution flow
- Still benefits from MCP protocol compliance and observability

See FINAL_ARCHITECTURE.md for complete documentation.
"""
import os
import json
from typing import Optional
from termcolor import colored
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from openai import AsyncAzureOpenAI

import core.globals as globals
from core.agent_dependencies import SQLAgentDependencies
from mcp_files.mcp_internal_client import get_internal_mcp_client

# Import evaluation system
from core.evaluation_manager import SQLEvaluationManager
from core.feedback_system import FeedbackCollector


# ============================================================================
# Pydantic Models for Agent Output
# ============================================================================

class SQLGenerationResult(BaseModel):
    """Result of SQL generation"""
    data: str
    sql_query: Optional[str] = None
    df_info: Optional[str] = None
    query_id: Optional[str] = None
    confidence_score: Optional[float] = None
    success: bool = True
    error: Optional[str] = None


# ============================================================================
# Global Evaluation Manager
# ============================================================================

_evaluation_manager = None
_feedback_collector = None

def get_evaluation_manager():
    """Get or create the global evaluation manager instance"""
    global _evaluation_manager, _feedback_collector
    if _evaluation_manager is None:
        confidence_threshold = float(os.getenv('SQL_CONFIDENCE_THRESHOLD', '75.0'))
        max_retries = int(os.getenv('SQL_MAX_RETRIES', '3'))
        enable_auto_retry = os.getenv('SQL_ENABLE_AUTO_RETRY', 'true').lower() == 'true'

        _feedback_collector = FeedbackCollector()
        _evaluation_manager = SQLEvaluationManager(
            feedback_collector=_feedback_collector,
            confidence_threshold=confidence_threshold,
            max_retries=max_retries,
            enable_auto_retry=enable_auto_retry
        )
    return _evaluation_manager, _feedback_collector


# ============================================================================
# Azure OpenAI Model Configuration
# ============================================================================

def create_azure_model():
    """Create Azure OpenAI model for Pydantic AI"""
    client = AsyncAzureOpenAI(
        azure_endpoint=os.getenv('AZURE_OPENAI_ENDPOINT'),
        api_version='2024-12-01-preview',
        api_key=os.getenv('AZURE_OPENAI_KEY') or os.getenv('AZURE_OPENAI_API_KEY'),
    )

    return OpenAIChatModel(
        'gpt-4o',
        provider=OpenAIProvider(openai_client=client),
    )


# ============================================================================
# Pydantic AI SQL Agent with MCP Integration
# ============================================================================

sql_agent_mcp = Agent(
    model=create_azure_model(),
    deps_type=SQLAgentDependencies,
    system_prompt=(
        "You are an expert SQL generation agent using MCP protocol for all tool execution. "
        "Your role is to coordinate SQL query generation, validation, and execution. "
        "All tools are accessed via MCP for consistency and observability. "
        "Always validate queries and provide confidence scores."
    ),
)


@sql_agent_mcp.tool
async def execute_sql_query_via_mcp(
    ctx: RunContext[SQLAgentDependencies],
    user_question: str
) -> dict:
    """
    Execute complete SQL query generation pipeline via MCP ask_database tool.

    This is the main tool that leverages the existing MCP ask_database tool
    which internally handles:
    - Database selection
    - Context gathering
    - SQL generation
    - Query execution
    - Result saving
    - Confidence scoring

    Args:
        user_question: The user's natural language question

    Returns:
        Dictionary with SQL results, query_id, and confidence score
    """
    try:
        await globals.send_status_to_user(ctx.deps.user_id, status="Processing SQL query via MCP...")

        # Get MCP client
        mcp_client = get_internal_mcp_client()

        # Prepare arguments for ask_database tool
        # The ask_database tool expects specific parameters based on the MCP schema
        tool_args = {
            "question": user_question,
            "user_id": ctx.deps.user_id,
            "user_group": ctx.deps.user_group,
            "logger_timestamp": ctx.deps.logger_timestamp,
            "tool_id": ctx.deps.tool_id or "sql_query",
            "tag": ctx.deps.tag or "general_query"
        }

        # Add context if this is a retry
        if ctx.deps.previous_error:
            tool_args["previous_error"] = ctx.deps.previous_error
        if ctx.deps.previous_query:
            tool_args["previous_query"] = ctx.deps.previous_query

        print(colored(f"🔧 MCP Tool Call: ask_database", "cyan"))
        print(colored(f"   Arguments: {json.dumps(tool_args, indent=2)}", "cyan"))

        # Call the MCP tool
        result = await mcp_client.call_tool("ask_database", tool_args)

        print(colored(f"✅ MCP Tool Response received", "green"))

        # Parse MCP response
        if not result or "content" not in result:
            return {
                "success": False,
                "error": "MCP tool returned empty response"
            }

        content = result["content"]
        if isinstance(content, list) and len(content) > 0:
            text_content = content[0].get("text", "")

            # The ask_database tool returns a structured response
            try:
                parsed_result = json.loads(text_content)

                # Extract components
                data = parsed_result.get("data", "No data returned")
                sql_query = parsed_result.get("sql_query")
                df_info = parsed_result.get("df_info")
                query_id = parsed_result.get("query_id")
                confidence_score = parsed_result.get("confidence_score", 0.0)

                # Store in dependencies for potential retry
                ctx.deps.database = parsed_result.get("database")
                ctx.deps.dialect = parsed_result.get("dialect")

                return {
                    "success": True,
                    "data": data,
                    "sql_query": sql_query,
                    "df_info": df_info,
                    "query_id": query_id,
                    "confidence_score": confidence_score
                }

            except json.JSONDecodeError:
                # If not JSON, treat as raw text response
                return {
                    "success": True,
                    "data": text_content,
                    "sql_query": None,
                    "df_info": None,
                    "query_id": None,
                    "confidence_score": 0.0
                }
        else:
            return {
                "success": False,
                "error": "MCP tool returned invalid content format"
            }

    except Exception as e:
        print(colored(f"❌ MCP Tool Error: {str(e)}", "red"))
        return {
            "success": False,
            "error": str(e)
        }


@sql_agent_mcp.tool
async def check_query_confidence(
    ctx: RunContext[SQLAgentDependencies],
    confidence_score: float,
    sql_query: str
) -> dict:
    """
    Check if query confidence meets threshold and determine if retry is needed.

    Args:
        confidence_score: The confidence score from query analysis
        sql_query: The generated SQL query

    Returns:
        Dictionary with should_retry flag and analysis
    """
    # Get threshold from environment
    threshold = float(os.getenv('SQL_CONFIDENCE_THRESHOLD', '75.0'))

    print(colored(f"📊 Confidence Check: {confidence_score:.1f}% (Threshold: {threshold}%)", "yellow"))

    should_retry = confidence_score < threshold

    if should_retry:
        print(colored(f"⚠️  Confidence below threshold. Retry recommended.", "yellow"))
        ctx.deps.previous_query = sql_query

        # Get detailed error message from analyzer (stored in globals)
        issues_summary = "No specific issues"
        improvements_summary = "No suggestions"
        if hasattr(globals, 'query_evaluations') and ctx.deps.user_id in globals.query_evaluations:
            analysis = globals.query_evaluations[ctx.deps.user_id].get('analysis', {})
            all_issues = analysis.get("issues", [])
            improvements = analysis.get("suggested_improvements", [])

            if all_issues:
                issues_summary = "; ".join([issue['description'] for issue in all_issues])
            if improvements:
                improvements_summary = "; ".join(improvements)

        ctx.deps.previous_error = f"Confidence Score {confidence_score:.1f}% below threshold. Issues: {issues_summary}. Suggestions: {improvements_summary}"
        print(colored(f"   Issues: {issues_summary}", "yellow"))
        print(colored(f"   Suggestions: {improvements_summary}", "blue"))
    else:
        print(colored(f"✅ Confidence meets threshold. Query accepted.", "green"))

    return {
        "confidence_score": confidence_score,
        "threshold": threshold,
        "should_retry": should_retry,
        "meets_threshold": not should_retry
    }


@sql_agent_mcp.tool
async def format_sql_response(
    ctx: RunContext[SQLAgentDependencies],
    data: str,
    sql_query: Optional[str],
    df_info: Optional[str],
    query_id: Optional[str],
    confidence_score: Optional[float]
) -> SQLGenerationResult:
    """
    Format the final SQL response with all metadata.

    Args:
        data: The query results or error message
        sql_query: The generated SQL query
        df_info: DataFrame information
        query_id: Unique query identifier
        confidence_score: Confidence score from analysis

    Returns:
        Formatted SQLGenerationResult
    """
    # Add confidence info to data if available
    if confidence_score and confidence_score > 0:
        confidence_info = f"\n📊 Query Confidence: {confidence_score:.1f}%\n"
        # Only add if not already present
        if "Query Confidence:" not in data:
            # Insert before download link if present
            if "/download/csv/" in data:
                data = data.replace(
                    "Download",
                    f"{confidence_info}Download"
                )
            else:
                data = f"{data}\n{confidence_info}"

    return SQLGenerationResult(
        data=data,
        sql_query=sql_query,
        df_info=df_info,
        query_id=query_id,
        confidence_score=confidence_score,
        success=True
    )


# ============================================================================
# Main SQL Agent Function (MCP-based, Backward Compatible)
# ============================================================================

async def SQL_Agent_MCP(
    userText: str,
    user_id: str,
    user_group: str,
    logger_timestamp_mod: str,
    tool_id: str = None,
    tag: str = None
) -> tuple:
    """
    Main SQL Agent function using MCP protocol for all tool execution.

    This uses direct MCP calls to the ask_database tool, which internally handles:
    - Database selection
    - SQL generation
    - Query execution
    - Result handling
    - Confidence scoring

    Maintains backward compatibility with the original Agent_SQL interface.

    Args:
        userText: User's natural language question
        user_id: User identifier
        user_group: User group
        logger_timestamp_mod: Timestamp for logging
        tool_id: Optional tool identifier
        tag: Optional tag for categorization

    Returns:
        Tuple of (data, sql_query, df_info, query_id)
    """
    max_attempts = 4
    attempts = 0
    previous_error = None
    previous_query = None

    await globals.send_status_to_user(user_id, status="Receiving your query...")

    # Get MCP client
    mcp_client = get_internal_mcp_client()

    while attempts < max_attempts:
        print(colored(f"\n{'='*80}", "cyan"))
        print(colored(f"🔄 SQL MCP Agent - Attempt {attempts + 1}/{max_attempts}", "cyan", attrs=["bold"]))
        print(colored(f"{'='*80}\n", "cyan"))

        try:
            await globals.send_status_to_user(user_id, status="Processing SQL query via MCP...")

            # Prepare arguments for ask_database tool
            tool_args = {
                "question": userText,
                "user_id": user_id,
                "user_group": user_group,
                "logger_timestamp": logger_timestamp_mod,
                "tool_id": tool_id or "sql_query",
                "tag": tag or "general_query"
            }

            # Add context if this is a retry
            if previous_error:
                tool_args["previous_error"] = previous_error
            if previous_query:
                tool_args["previous_query"] = previous_query

            print(colored(f"🔧 MCP Tool Call: ask_database", "cyan"))
            print(colored(f"   Arguments: {json.dumps(tool_args, indent=2)}", "cyan"))

            # Call the MCP tool with user context
            result = await mcp_client.call_tool(
                "ask_database",
                tool_args,
                user_id=user_id,
                user_group=user_group,
                logger_timestamp=logger_timestamp_mod
            )

            print(colored(f"✅ MCP Tool Response received", "green"))

            # Parse MCP response - handle both standard and custom formats
            if not result:
                previous_error = "MCP tool returned None"
                attempts += 1
                await globals.send_status_to_user(user_id, status="Retrying your request...")
                continue

            # Check if result is in custom format (direct dict with ok, name, sql, etc.)
            if isinstance(result, dict) and "ok" in result and "query_id" in result:
                print(colored(f"✅ Detected custom MCP format (direct dict)", "yellow"))
                # Custom format - extract directly
                # The "report" field contains the data output
                data = result.get("report", "No data returned")
                sql_query = result.get("sql")
                df_info = None  # Not provided in custom format
                query_id = result.get("query_id")
                confidence_score = 95.0  # Assume high confidence if query succeeded

            # Check for standard MCP format (content key with list)
            elif isinstance(result, dict) and "content" in result:
                print(colored(f"✅ Detected standard MCP format (content list)", "yellow"))
                content = result["content"]
                if not isinstance(content, list) or len(content) == 0:
                    previous_error = "MCP content is not a list or is empty"
                    attempts += 1
                    await globals.send_status_to_user(user_id, status="Retrying your request...")
                    continue

                text_content = content[0].get("text", "")

                # The ask_database tool returns a structured response
                try:
                    parsed_result = json.loads(text_content)

                    # Extract components
                    data = parsed_result.get("data", "No data returned")
                    sql_query = parsed_result.get("sql_query")
                    df_info = parsed_result.get("df_info")
                    query_id = parsed_result.get("query_id")
                    confidence_score = parsed_result.get("confidence_score", 0.0)
                except json.JSONDecodeError:
                    # If not JSON, treat as raw text response
                    print(colored(f"⚠️  Non-JSON response from MCP tool", "yellow"))
                    return (text_content, None, None, None)
            else:
                previous_error = f"MCP tool returned unknown format (keys: {list(result.keys()) if isinstance(result, dict) else 'not a dict'})"
                attempts += 1
                await globals.send_status_to_user(user_id, status="Retrying your request...")
                continue

            # Check confidence score (common to both formats)
            threshold = float(os.getenv('SQL_CONFIDENCE_THRESHOLD', '75.0'))
            print(colored(f"📊 Confidence Check: {confidence_score:.1f}% (Threshold: {threshold}%)", "yellow"))

            if confidence_score > 0 and confidence_score < threshold and sql_query:
                if attempts < max_attempts - 1:
                    print(colored(f"⚠️  Confidence below threshold. Retry recommended.", "yellow"))
                    previous_query = sql_query

                    # Get detailed error message from analyzer (stored in globals by SQL_Agent)
                    issues_summary = "No specific issues"
                    improvements_summary = "No suggestions"
                    if hasattr(globals, 'query_evaluations') and user_id in globals.query_evaluations:
                        analysis = globals.query_evaluations[user_id].get('analysis', {})
                        all_issues = analysis.get("issues", [])
                        improvements = analysis.get("suggested_improvements", [])

                        if all_issues:
                            issues_summary = "; ".join([issue['description'] for issue in all_issues])
                        if improvements:
                            improvements_summary = "; ".join(improvements)

                    previous_error = f"Confidence Score {confidence_score:.1f}% below threshold. Issues: {issues_summary}. Suggestions: {improvements_summary}"
                    print(colored(f"   Issues: {issues_summary}", "yellow"))
                    print(colored(f"   Suggestions: {improvements_summary}", "blue"))

                    attempts += 1
                    await globals.send_status_to_user(user_id, status="Refining query...")
                    continue
            else:
                print(colored(f"✅ Confidence meets threshold. Query accepted.", "green"))

            # Add confidence info to data if available
            if confidence_score and confidence_score > 0:
                confidence_info = f"\n📊 Query Confidence: {confidence_score:.1f}%\n"
                # Only add if not already present
                if "Query Confidence:" not in str(data):
                    # Insert before download link if present
                    if "/download/csv/" in str(data):
                        data = str(data).replace("Download", f"{confidence_info}Download")
                    else:
                        data = f"{data}\n{confidence_info}"

            print(colored(f"\n✅ SQL Query Completed Successfully!", "green", attrs=["bold"]))
            print(colored(f"   Query ID: {query_id}", "green"))
            print(colored(f"   Confidence: {confidence_score:.1f}%\n", "green"))

            return (data, sql_query, df_info, query_id)

        except Exception as e:
            print(colored(f"❌ MCP Tool Error: {str(e)}", "red"))
            import traceback
            traceback.print_exc()
            previous_error = str(e)
            attempts += 1
            await globals.send_status_to_user(user_id, status="Ran into Error, Retrying your request...")

    print(colored(f"\n❌ Max attempts reached. Query failed.", "red", attrs=["bold"]))
    return "Ran into Error, Please try again.", None, None, None
