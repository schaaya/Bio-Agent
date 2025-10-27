"""
Pydantic AI Agent for SQL Generation
Converts the original Agent_SQL to use Pydantic AI framework
"""
import os
import io
import json
import uuid
import pandas as pd
from typing import Optional
from termcolor import colored
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIModel
from openai import AsyncAzureOpenAI

import core.globals as globals
from core.DB_selector import DBSelector
from core.query_executer import execute_query
from core.logger import log_sql_error
from core.Agent_Validator import Validator
from utility import search_semantic
from utility.retrieval import get_similar_query
from core.SQL_engine_stage2 import Stage_two
from core.SQL_engine_stage1 import SQLGenerator
from core.agent_dependencies import SQLAgentDependencies

# Import evaluation system
from core.sql_analyzer import SQLAnalyzer
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
# Azure OpenAI Model Configuration
# ============================================================================

def create_azure_model():
    """Create Azure OpenAI model for Pydantic AI"""
    client = AsyncAzureOpenAI(
        azure_endpoint=os.getenv('AZURE_OPENAI_ENDPOINT'),
        api_version='2024-12-01-preview',
        api_key=os.getenv('AZURE_OPENAI_KEY') or os.getenv('AZURE_OPENAI_API_KEY'),
    )

    return OpenAIModel(
        'gpt-4o',
        openai_client=client,
    )


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
# Pydantic AI SQL Agent
# ============================================================================

# Create the agent
sql_agent = Agent(
    model=create_azure_model(),
    deps_type=SQLAgentDependencies,
    result_type=SQLGenerationResult,
    system_prompt=(
        "You are an expert SQL generation agent. Your role is to coordinate SQL query generation, "
        "validation, and execution using the available tools. "
        "Always validate queries before execution and provide confidence scores."
    ),
)


@sql_agent.tool
async def select_database(
    ctx: RunContext[SQLAgentDependencies],
    user_question: str
) -> dict:
    """
    Select the appropriate database for the user's query.

    Args:
        user_question: The user's natural language question

    Returns:
        Dictionary with database, schema, description, and dialect
    """
    await globals.send_status_to_user(ctx.deps.user_id, status="Selecting Database...")

    # Check cache first
    cache_key = (ctx.deps.user_id, ctx.deps.user_group)
    if cache_key in globals.db_cache:
        print(colored(f"Database Cache Hit", "green"))
        database, db_schema, description, dialect = globals.db_cache[cache_key]
    else:
        database, db_schema, description, dialect = await DBSelector.database_selection(
            ctx.deps.user_id,
            ctx.deps.user_group,
            user_question
        )
        globals.db_cache[cache_key] = (database, db_schema, description, dialect)

    # Update dependencies
    ctx.deps.database = database
    ctx.deps.db_schema = db_schema
    ctx.deps.description = description
    ctx.deps.dialect = dialect

    if database is False:
        return {
            "success": False,
            "error": "Database not available or user does not have access"
        }

    return {
        "success": True,
        "database": database,
        "schema": db_schema[:500],  # Truncate for display
        "description": description,
        "dialect": dialect
    }


@sql_agent.tool
async def gather_context(
    ctx: RunContext[SQLAgentDependencies],
    user_question: str
) -> dict:
    """
    Gather relevant queries and domain knowledge for the user's question.

    Args:
        user_question: The user's natural language question

    Returns:
        Dictionary with relevant queries and domain knowledge
    """
    await globals.send_status_to_user(ctx.deps.user_id, status="Gathering context...")

    # Get similar queries
    relevant_queries = await get_similar_query(
        user_question,
        top_n=2,
        csv_path=r'utility/queries.csv',
        embedding_path=r'utility/queries_embedding.csv'
    )

    # Get domain knowledge
    relevant_domain_knowledge = await search_semantic.get_relevant_domain_knowledge(user_question)

    # Update dependencies
    ctx.deps.relevant_queries = relevant_queries if relevant_queries else []
    ctx.deps.relevant_domain_knowledge = relevant_domain_knowledge if relevant_domain_knowledge else []

    return {
        "relevant_queries_count": len(ctx.deps.relevant_queries),
        "domain_knowledge_count": len(ctx.deps.relevant_domain_knowledge),
        "context_ready": True
    }


@sql_agent.tool
async def generate_sql_query(
    ctx: RunContext[SQLAgentDependencies],
    user_question: str
) -> dict:
    """
    Generate SQL query using two-stage approach: table selection + SQL generation.

    Args:
        user_question: The user's natural language question

    Returns:
        Dictionary with SQL query and table descriptions
    """
    await globals.send_status_to_user(ctx.deps.user_id, status="Generating SQL query...")

    # Build message with error context if retrying
    message = {
        "User_Question": user_question,
        "Error_Message": ctx.deps.previous_error or ''
    }
    if ctx.deps.previous_query:
        message["Previous_Query"] = ctx.deps.previous_query

    user_str = json.dumps(message)

    # Get context messages
    context_msg = globals.session_data.get(ctx.deps.user_id, [])[-4:]
    ctx.deps.context_messages = context_msg

    # Stage 1: Select relevant tables
    await globals.send_status_to_user(ctx.deps.user_id, status="Gathering Schema...")
    engine = await SQLGenerator.create(ctx.deps.db_schema, ctx.deps.database)
    response = await engine.generate_query(
        ctx.deps.user_id,
        user_str,
        context_msg,
        ctx.deps.description,
        ctx.deps.relevant_queries,
        ctx.deps.relevant_domain_knowledge
    )
    json_response = json.loads(response)
    tables_description = json_response["tables"]

    # Stage 2: Generate SQL query
    sql_response = await Stage_two.generate_query(
        ctx.deps.user_id,
        question=user_str,
        description=tables_description,
        dialect=ctx.deps.dialect,
        relevent_query=ctx.deps.relevant_queries,
        relevant_domain_knowledge=ctx.deps.relevant_domain_knowledge
    )
    json_results = json.loads(sql_response)
    sql_query = json_results["sql_query"]

    print(colored(f"SQL Query: {sql_query}", "yellow"))

    return {
        "sql_query": sql_query,
        "tables_description": tables_description,
        "success": True
    }


@sql_agent.tool
async def analyze_sql_quality(
    ctx: RunContext[SQLAgentDependencies],
    sql_query: str,
    user_question: str
) -> dict:
    """
    Analyze SQL query quality with confidence scoring.

    Args:
        sql_query: The generated SQL query
        user_question: The user's original question

    Returns:
        Dictionary with confidence score, issues, and analysis
    """
    await globals.send_status_to_user(ctx.deps.user_id, status="Analyzing query quality...")

    # Execute query to get preview
    temp_results = execute_query(ctx.deps.database, sql_query)
    if temp_results is None:
        return {
            "success": False,
            "error": "Query execution returned no results for analysis"
        }

    # Create dataframe preview
    temp_df = pd.DataFrame(temp_results)
    df_preview = temp_df.head(5).to_string()

    # Get evaluation manager
    eval_manager, _ = get_evaluation_manager()

    # Create analyzer
    analyzer = SQLAnalyzer(
        schema=ctx.deps.db_schema,
        relevant_query=ctx.deps.relevant_queries or [],
        relevant_domain_knowledge=ctx.deps.relevant_domain_knowledge or [],
        description=ctx.deps.description,
        custom_instructions="",
        tables_description="",  # This would be passed from generate_sql_query tool
        user_question=user_question,
        sql_query=sql_query,
        dialect=ctx.deps.dialect,
        df_preview=df_preview,
        confidence_threshold=eval_manager.confidence_threshold,
        max_retries=eval_manager.max_retries
    )

    # Analyze the query
    analysis_response = await analyzer.analyze_query()
    confidence_score = analysis_response.get("confidence_score", 0.0)

    # Log detailed evaluation
    print(colored("\n" + "="*80, "cyan"))
    print(colored("📊 SQL QUALITY EVALUATION REPORT", "cyan", attrs=["bold"]))
    print(colored("="*80, "cyan"))
    print(colored(f"\n🎯 Overall Confidence Score: {confidence_score:.2f}%", "cyan", attrs=["bold"]))
    print(colored(f"📝 Summary: {analysis_response.get('feedback', '')}\n", "cyan"))

    # Check for blocking issues
    critical_issues = analyzer.get_critical_issues(analysis_response)
    completeness_issues = [
        issue for issue in analysis_response.get("issues", [])
        if issue.get("type") in ["completeness", "relevance"]
        and any(keyword in issue.get("description", "").lower()
                for keyword in ["filter", "where", "year", "missing"])
    ]

    blocking_issues = critical_issues + completeness_issues
    should_retry = (len(blocking_issues) > 0) or (confidence_score < eval_manager.confidence_threshold)

    return {
        "confidence_score": confidence_score,
        "analysis": analysis_response,
        "should_retry": should_retry,
        "blocking_issues": blocking_issues,
        "success": True
    }


@sql_agent.tool
async def validate_sql_query(
    ctx: RunContext[SQLAgentDependencies],
    sql_query: str,
    user_question: str,
    tables_description: str
) -> dict:
    """
    Validate SQL query for correctness (only after 2+ attempts).

    Args:
        sql_query: The SQL query to validate
        user_question: The user's original question
        tables_description: Description of tables involved

    Returns:
        Dictionary with validation result
    """
    if ctx.deps.attempt < 2:
        return {"validated": True, "skipped": True, "reason": "Not enough attempts"}

    await globals.send_status_to_user(ctx.deps.user_id, status="Validating SQL query...")

    message = {"User_Question": user_question, "Error_Message": ctx.deps.previous_error or ''}
    user_str = json.dumps(message)

    validation_response = json.loads(
        await Validator.approve_query(
            ctx.deps.user_id,
            question=user_str,
            description=tables_description,
            dialect=ctx.deps.dialect,
            query=sql_query
        )
    )

    validation_status = validation_response["Result"]

    if validation_status == "False":
        print(colored(f"SQL Query Validation Failed", "red"))
        return {
            "validated": False,
            "error": validation_response["Reason"],
            "success": False
        }

    print(colored(f"SQL Query Validated", "green"))
    return {"validated": True, "success": True}


@sql_agent.tool
async def execute_and_save_results(
    ctx: RunContext[SQLAgentDependencies],
    sql_query: str,
    user_question: str,
    confidence_score: float
) -> dict:
    """
    Execute SQL query and save results to CSV.

    Args:
        sql_query: The SQL query to execute
        user_question: The user's original question
        confidence_score: Confidence score from analysis

    Returns:
        Dictionary with results, query_id, and file path
    """
    await globals.send_status_to_user(ctx.deps.user_id, status="Executing final query...")

    # Execute query
    results = execute_query(ctx.deps.database, sql_query)

    if results is None:
        return {
            "success": False,
            "error": "Query execution returned no results"
        }

    # Generate query ID
    query_id = uuid.uuid4().hex[:10]
    print(colored(f"Query ID: {query_id}", "green"))

    # Save to CSV
    csv_file_path = f"temp/{ctx.deps.user_id}_{ctx.deps.logger_timestamp}_{ctx.deps.tool_id}_{ctx.deps.tag}_results.csv"
    df = pd.DataFrame(results)
    df.to_csv(csv_file_path, index=False)

    # Get df info
    buffer = io.StringIO()
    df.info(buf=buffer)
    df_info = buffer.getvalue()

    # Store paths
    user_email = ctx.deps.user_id.split("_")[0]
    globals.csv_path(user_email, file_path=csv_file_path)
    globals.add_csv_path_mapping(user_email, query_id, csv_file_path)

    # Create feedback log
    eval_manager, feedback_collector = get_evaluation_manager()
    feedback_log = feedback_collector.create_log(
        user_id=ctx.deps.user_id,
        question=user_question,
        sql_query=sql_query,
        confidence_score=confidence_score,
        analyzer_result={}  # Would be passed from analyze_sql_quality
    )
    feedback_log.execution_success = True
    feedback_log.result_count = len(df)
    feedback_log.regeneration_count = ctx.deps.attempt

    # Create response message
    sample_size = min(len(df), 31)
    df_sample = df.sample(n=sample_size).sort_index()
    df_preview_display = df_sample.to_string()

    confidence_info = f"\n📊 Query Confidence: {confidence_score:.1f}%\n"

    if len(df) > sample_size:
        data = (
            f"The result set is large; here's a sample of {sample_size} rows out of {len(df)} total rows:\n\n"
            f"{df_preview_display}\n\n"
            f"Summary:\n{df_info}\n\n"
            f"{confidence_info}"
            f"Download the full results CSV with: /download/csv/{query_id}"
        )
    else:
        data = (
            f"Here are the results ({len(df)} rows):\n\n"
            f"{df_preview_display}\n\n"
            f"Summary:\n{df_info}\n\n"
            f"{confidence_info}"
            f"Download the results CSV with: /download/csv/{query_id}"
        )

    return {
        "success": True,
        "data": data,
        "sql_query": sql_query,
        "df_info": df_info,
        "query_id": query_id,
        "confidence_score": confidence_score,
        "result_count": len(df),
        "log_id": feedback_log.id
    }


# ============================================================================
# Main SQL Agent Function (Backward Compatible)
# ============================================================================

async def SQL_Agent_Pydantic(userText: str, user_id: str, user_group: str,
                             logger_timestamp_mod: str, tool_id: str = None,
                             tag: str = None) -> tuple:
    """
    Main SQL Agent function using Pydantic AI framework.

    This is the entry point that maintains backward compatibility with the original Agent_SQL.
    """
    max_attempts = 4
    attempts = 0

    await globals.send_status_to_user(user_id, status="Receiving your query...")

    while attempts < max_attempts:
        print(colored(f"SQLEngine Attempt: {attempts}", "yellow"))

        try:
            # Create dependencies
            deps = SQLAgentDependencies(
                user_id=user_id,
                user_group=user_group,
                logger_timestamp=logger_timestamp_mod,
                tool_id=tool_id,
                tag=tag,
                attempt=attempts
            )

            # Run the agent
            result = await sql_agent.run(
                f"Generate and execute SQL query for: {userText}",
                deps=deps
            )

            # Extract result
            if result.data.success:
                return (
                    result.data.data,
                    result.data.sql_query,
                    result.data.df_info,
                    result.data.query_id
                )
            else:
                # Update for retry
                deps.previous_error = result.data.error
                attempts += 1
                await globals.send_status_to_user(user_id, status="Retrying your request...")

        except Exception as e:
            await globals.send_status_to_user(user_id, status="Ran into Error, Retrying your request...")
            print(colored(f"Error at SQL_Agent_Pydantic: {e}", "red"))

            # Log error
            if deps.dialect and deps.previous_query:
                await log_sql_error(deps.dialect, deps.previous_query, str(e))

            attempts += 1

    return "Ran into Error, Please try again.", None, None, None
