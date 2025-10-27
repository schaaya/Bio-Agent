"""
Chain-of-Thought Agent - MCP Integration with Direct Tool Calls

IMPORTANT: This file contains both:
1. Unused Pydantic AI agent definitions (lines 54-382) - kept as reference
2. Active implementation using direct MCP calls (lines 389+)

CURRENT IMPLEMENTATION:
- The COT_Agent_Pydantic() function (line 389) is the entry point
- It uses LLM to plan execution steps, then executes via direct MCP calls
- It does NOT use the Pydantic AI agent or tool decorators above
- The Pydantic AI code remains for reference/future migration

WHY DIRECT MCP CALLS:
- We need precise control over multi-step execution order
- LLM-powered planning with manual orchestration
- Context passing between steps (sub_question_list for plotting)
- Complex result accumulation (base64_code, fig_json, etc.)
- Still benefits from MCP protocol compliance and observability

KEY FEATURES:
- Handles OpenAI function dict format for tools parameter
- Decomposes complex queries into multiple steps
- Executes tools in sequence via MCP
- Generates follow-up questions

See FINAL_ARCHITECTURE.md for complete documentation.
"""
import os
import json
from typing import List, Dict, Any, Optional
from termcolor import colored
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from openai import AsyncAzureOpenAI

from core.agent_dependencies import COTAgentDependencies
from core.globals import send_status_to_user
from mcp_files.mcp_internal_client import get_internal_mcp_client


# ============================================================================
# Pydantic Models for Agent Output
# ============================================================================

class ExecutionStep(BaseModel):
    """Single step in execution plan"""
    sub_question: str
    action_input: Any
    tool: str


class ExecutionPlan(BaseModel):
    """Complete execution plan from planner"""
    ExecutionPlan: List[ExecutionStep]


class COTResult(BaseModel):
    """Result of Chain-of-Thought execution"""
    scratchpad: str
    sql: Optional[str] = None
    base64_code_list: List[str] = []
    code_list: List[str] = []
    fig_json_list: List[str] = []
    report_content: Optional[str] = None
    parsed_questions: Optional[List[str]] = None
    query_id: Optional[str] = None
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

    return OpenAIChatModel(
        'gpt-4o',
        provider=OpenAIProvider(openai_client=client),
    )


# ============================================================================
# Pydantic AI Chain-of-Thought Agent
# ============================================================================

cot_agent = Agent(
    model=create_azure_model(),
    deps_type=COTAgentDependencies,
    system_prompt=(
        "You are a Chain-of-Thought orchestration agent. Your role is to break down complex queries "
        "into manageable steps, select appropriate tools, and coordinate their execution. "
        "You can use multiple tools in sequence to answer complex questions involving databases, "
        "weather data, plotting, and document analysis."
    ),
)


@cot_agent.tool
async def plan_execution(
    ctx: RunContext[COTAgentDependencies],
    user_query: str,
    available_tools: List[str],
    selected_tools: Optional[List[str]] = None
) -> ExecutionPlan:
    """
    Create an execution plan by decomposing the user query into steps.

    Args:
        user_query: The user's question or request
        available_tools: List of available tool names
        selected_tools: Optional list of pre-selected tools by user

    Returns:
        ExecutionPlan with ordered steps
    """
    await send_status_to_user(ctx.deps.user_id, status="Planning execution...")

    # Build tools description
    tools_descriptions = {
        "ask_database": "Query databases with natural language questions",
        "get_weather_data": "Get weather information for a location",
        "gen_plotly_code": "Generate interactive Plotly visualizations",
        "pdf_query": "Query and extract information from PDF documents",
        "comparative_analyzer": "Compare and analyze multiple data sources"
    }

    tools_str = "\n".join([
        f"- {tool}: {tools_descriptions.get(tool, 'Tool description not available')}"
        for tool in available_tools
    ])

    # Use the LLM to generate execution plan
    planning_prompt = [
        {
            "role": "system",
            "content": (
                "You are an expert query planner. Break down user queries into executable steps.\n\n"
                f"## Available Tools\n{tools_str}\n\n"
                "## Task\n"
                "1. Decide if the query needs decomposition or can be handled in one step.\n"
                "2. If one step is sufficient: Set 'ExecutionPlan' to a single step with the best tool.\n"
                "3. If decomposition is needed: Break into sub-questions requiring different tools.\n\n"
                "## CRITICAL INSTRUCTION FOR PLOTTING:\n"
                "When creating a sub-question for gen_plotly_code, you MUST preserve the exact plot type specified by the user.\n"
                "- If user says 'box plots' or 'box plot' → sub-question MUST include 'box plots' or 'box plot'\n"
                "- If user says 'bar chart' or 'bar plot' → sub-question MUST include 'bar chart' or 'bar plot'\n"
                "- If user says 'scatter plot' → sub-question MUST include 'scatter plot'\n"
                "- If user says 'line plot' or 'line chart' → sub-question MUST include 'line plot' or 'line chart'\n"
                "- If user says 'violin plot' → sub-question MUST include 'violin plot'\n"
                "NEVER change the plot type. ALWAYS copy the exact plot type from the user's query.\n\n"
                "### Examples\n"
                "**Single-Step**: User Query: 'What is the weather in Paris?'\n"
                "ExecutionPlan: [{'sub-question': 'Get Paris weather', 'action_input': {}, 'tool': 'get_weather_data'}]\n\n"
                "**Multi-Step**: User Query: 'plot me a graph for all facilities with their capacities'\n"
                "ExecutionPlan: [\n"
                "   {'sub-question': 'Fetch facilities and capacities', 'action_input': {}, 'tool': 'ask_database'},\n"
                "   {'sub-question': 'Plot facilities and capacities', 'action_input': {}, 'tool': 'gen_plotly_code'}\n"
                "]\n\n"
                "**Multi-Step with Plot Type**: User Query: 'Show me the expression of gene EGFR across tissues. Plot as box plots.'\n"
                "ExecutionPlan: [\n"
                "   {'sub-question': 'Fetch expression of gene EGFR across tissues', 'action_input': {}, 'tool': 'ask_database'},\n"
                "   {'sub-question': 'Plot EGFR expression as box plots', 'action_input': {}, 'tool': 'gen_plotly_code'}\n"
                "]\n\n"
                "Respond with valid JSON containing 'ExecutionPlan'."
            )
        },
        {
            "role": "user",
            "content": f"User Input: {user_query}\nUser selected tools: {selected_tools or 'None'}"
        }
    ]

    # Call LLM via backward compatibility
    if ctx.deps.llm_generate_response:
        response = await ctx.deps.llm_generate_response(
            planning_prompt,
            ctx.deps.user_id,
            response_format=True
        )
        parsed_response = response.choices[0].message.content
    else:
        # Fallback to direct OpenAI call
        client = create_azure_model()
        response = await client.call(planning_prompt)
        parsed_response = response

    try:
        execution_plan_dict = json.loads(parsed_response)
        execution_plan = ExecutionPlan(**execution_plan_dict)
        print("Execution Plan:\n", json.dumps(execution_plan.model_dump(), indent=2))
        return execution_plan
    except Exception as e:
        print(colored(f"Failed to parse execution plan: {e}", "red"))
        # Return a single-step fallback plan
        return ExecutionPlan(ExecutionPlan=[
            ExecutionStep(
                sub_question=user_query,
                action_input={},
                tool=selected_tools[0] if selected_tools else "ask_database"
            )
        ])


@cot_agent.tool
async def execute_tool_via_mcp(
    ctx: RunContext[COTAgentDependencies],
    tool_name: str,
    action_input: Any,
    sub_question: Optional[str] = None
) -> dict:
    """
    Execute a tool via MCP protocol.

    Args:
        tool_name: Name of the tool to execute
        action_input: Input parameters for the tool
        sub_question: Optional sub-question context

    Returns:
        Dictionary with tool execution results
    """
    await send_status_to_user(ctx.deps.user_id, status=f"Executing {tool_name}...")

    try:
        # Get MCP client
        mcp_client = get_internal_mcp_client()

        # Prepare tool arguments
        if isinstance(action_input, str):
            try:
                action_input = json.loads(action_input)
            except json.JSONDecodeError:
                action_input = {"question": action_input}

        # Add context to tool arguments
        if sub_question and "question" not in action_input:
            action_input["question"] = sub_question

        # Add user context
        action_input["user_id"] = ctx.deps.user_id
        action_input["user_group"] = ctx.deps.user_group
        action_input["logger_timestamp"] = ctx.deps.logger_timestamp

        # Call tool via MCP
        result = await mcp_client.call_tool(tool_name, action_input)

        # Extract results from MCP response
        observation = None
        sql = None
        base64_code = None
        code = None
        fig_json = None
        report_content = None
        query_id = None

        if result and "content" in result:
            content = result["content"]
            if isinstance(content, list) and len(content) > 0:
                text_content = content[0].get("text", "")
                try:
                    parsed = json.loads(text_content)
                    observation = parsed.get("observation")
                    sql = parsed.get("sql")
                    base64_code = parsed.get("base64_code")
                    code = parsed.get("code")
                    fig_json = parsed.get("fig_json")
                    report_content = parsed.get("report_content")
                    query_id = parsed.get("query_id")
                except json.JSONDecodeError:
                    observation = text_content

        return {
            "success": True,
            "observation": observation,
            "sql": sql,
            "base64_code": base64_code,
            "code": code,
            "fig_json": fig_json,
            "report_content": report_content,
            "query_id": query_id
        }

    except Exception as e:
        print(colored(f"Error executing {tool_name}: {e}", "red"))
        return {
            "success": False,
            "error": str(e)
        }


@cot_agent.tool
async def execute_ask_database(
    ctx: RunContext[COTAgentDependencies],
    sub_question: str,
    action_input: Any
) -> dict:
    """
    Execute ask_database tool with special handling for scratchpad.

    Args:
        sub_question: The database query question
        action_input: Query parameters

    Returns:
        Dictionary with query results
    """
    # Add to sub_question_list for context
    if ctx.deps.sub_question_list is None:
        ctx.deps.sub_question_list = []
    ctx.deps.sub_question_list.append(sub_question)

    # Execute via MCP
    result = await execute_tool_via_mcp(ctx, "ask_database", action_input, sub_question)

    return result


@cot_agent.tool
async def execute_gen_plotly_code(
    ctx: RunContext[COTAgentDependencies],
    sub_question: str,
    action_input: Any
) -> dict:
    """
    Execute gen_plotly_code tool with context from previous database queries.

    Args:
        sub_question: The plotting instruction
        action_input: Plotting parameters

    Returns:
        Dictionary with plot data
    """
    # Include sub_question_list for context if available
    if ctx.deps.sub_question_list and len(ctx.deps.sub_question_list) > 0:
        if isinstance(action_input, dict):
            action_input["sub_question_list"] = ctx.deps.sub_question_list
    else:
        if isinstance(action_input, dict):
            action_input["sub_question"] = sub_question

    # Execute via MCP
    result = await execute_tool_via_mcp(ctx, "gen_plotly_code", action_input, sub_question)

    return result


@cot_agent.tool
async def recommend_followup_questions(
    ctx: RunContext[COTAgentDependencies],
    original_query: str,
    execution_plan: ExecutionPlan
) -> List[str]:
    """
    Generate follow-up question recommendations based on the query and execution.

    Args:
        original_query: The original user query
        execution_plan: The execution plan that was used

    Returns:
        List of recommended follow-up questions
    """
    await send_status_to_user(ctx.deps.user_id, status="Generating follow-up questions...")

    # Build prompt for follow-up questions
    followup_prompt = [
        {
            "role": "system",
            "content": (
                "Based on the user's query and the tools used, suggest 3 relevant follow-up questions "
                "the user might want to ask next. Make them specific and actionable."
            )
        },
        {
            "role": "user",
            "content": (
                f"Original Query: {original_query}\n"
                f"Tools Used: {[step.tool for step in execution_plan.ExecutionPlan]}\n"
                "Suggest 3 follow-up questions:"
            )
        }
    ]

    try:
        # Call LLM
        if ctx.deps.llm_generate_response:
            response = await ctx.deps.llm_generate_response(
                followup_prompt,
                ctx.deps.user_id,
                response_format=False
            )
            followup_text = response.choices[0].message.content
        else:
            client = create_azure_model()
            followup_text = await client.call(followup_prompt)

        # Parse questions (assuming LLM returns numbered list)
        questions = [
            line.strip().lstrip("0123456789.-) ").strip()
            for line in followup_text.split("\n")
            if line.strip() and any(char.isalpha() for char in line)
        ][:3]

        return questions

    except Exception as e:
        print(colored(f"Error generating follow-up questions: {e}", "red"))
        return []


# ============================================================================
# Main COT Agent Function (Backward Compatible)
# ============================================================================

async def COT_Agent_Pydantic(
    user_query: str,
    user_id: str,
    user_group: str,
    logger_timestamp: str,
    cache: Any = None,
    tools: Dict[str, Any] = None,
    llm_generate_response: Any = None,
    selected_tools: Optional[List[str]] = None,
    custom_instructions: Optional[str] = None,
    message: Optional[List[Dict[str, str]]] = None
) -> tuple:
    """
    Main Chain-of-Thought Agent function using direct MCP calls.

    This orchestrates the workflow manually rather than using Pydantic AI's
    automatic tool calling, since we need precise control over the execution flow.
    """
    try:
        await send_status_to_user(user_id, status="Initializing Chain-of-Thought agent...")

        # Get available tools
        if tools:
            # Handle different tool formats
            if isinstance(tools, dict):
                # If tools is a dict, get the keys
                available_tools = list(tools.keys())
            elif isinstance(tools, list):
                # If tools is a list of OpenAI function dicts, extract names
                if len(tools) > 0 and isinstance(tools[0], dict):
                    available_tools = [
                        tool.get("function", {}).get("name", "")
                        for tool in tools
                        if "function" in tool and "name" in tool["function"]
                    ]
                else:
                    # Simple list of tool names
                    available_tools = tools
            else:
                # Fallback
                available_tools = [
                    "ask_database", "get_weather_data", "gen_plotly_code", "pdf_query", "comparative_analyzer"
                ]
        else:
            available_tools = [
                "ask_database", "get_weather_data", "gen_plotly_code", "pdf_query", "comparative_analyzer"
            ]

        # Initialize tracking variables
        scratchpad = []
        query_ids = []
        csv_file_paths = []  # Track CSV file paths
        sql_list = []
        base64_code_list = []
        code_list = []
        fig_json_list = []
        sub_question_list = []

        # NEW: Initialize reasoning steps tracking for frontend
        reasoning_steps = []

        # Step 1: Plan execution using LLM
        await send_status_to_user(user_id, status="Planning execution...")

        tools_descriptions = {
            "ask_database": "Query databases with natural language questions",
            "get_weather_data": "Get weather information for a location",
            "gen_plotly_code": "Generate interactive Plotly visualizations",
            "pdf_query": "Query and extract information from PDF documents",
            "comparative_analyzer": "Compare and analyze multiple data sources"
        }

        tools_str = "\n".join([
            f"- {tool}: {tools_descriptions.get(tool, 'Tool description not available')}"
            for tool in available_tools
        ])

        # Check if this is a plot modification request by looking at conversation history
        is_plot_modification = False
        if message and len(message) > 1:
            # Check last few messages for plot-related content
            recent_messages = message[-4:] if len(message) >= 4 else message
            for msg in recent_messages:
                if msg.get("role") == "assistant":
                    content = msg.get("content", "").lower()
                    # Check if recent response contained visualization
                    if any(keyword in content for keyword in ["visualization", "plot", "chart", "graph", "figure"]):
                        # Now check if current query is a modification request
                        user_query_lower = user_query.lower()
                        modification_keywords = [
                            "above data", "this data", "that plot", "this plot", "previous plot",
                            "same data", "change to", "modify", "update the plot", "make it",
                            "instead show", "convert to", "use box plot", "as box plot"
                        ]
                        if any(keyword in user_query_lower for keyword in modification_keywords):
                            is_plot_modification = True
                            print(colored(f"🔄 Detected plot modification request", "magenta"))
                            break

        planning_prompt = [
            {
                "role": "system",
                "content": (
                    "You are an expert query planner. Break down user queries into executable steps.\n\n"
                    f"## Available Tools\n{tools_str}\n\n"
                    "## Task\n"
                    "1. Decide if the query needs decomposition or can be handled in one step.\n"
                    "2. If one step is sufficient: Set 'ExecutionPlan' to a single step with the best tool.\n"
                    "3. If decomposition is needed: Break into sub-questions requiring different tools.\n\n"

                    "## PRIORITY 1: Plot Modification Requests\n"
                    "When user wants to modify/change an existing plot (e.g., 'i want box plots for above data'):\n"
                    "- Create ONLY ONE step using gen_plotly_code with 'modify': true in action_input\n"
                    "- DO NOT fetch data again - reuse existing data from conversation history\n"
                    "- The sub_question MUST preserve the exact plot type requested (box plots, bar chart, scatter, etc.)\n\n"

                    "## PRIORITY 2: Plot Type Preservation (New Plots)\n"
                    "When creating ANY sub-question for gen_plotly_code, you MUST preserve the exact plot type:\n"
                    "- If user says 'box plots' or 'box plot' → sub-question MUST include 'box plots' or 'box plot'\n"
                    "- If user says 'bar chart' or 'bar plot' → sub-question MUST include 'bar chart' or 'bar plot'\n"
                    "- If user says 'scatter plot' → sub-question MUST include 'scatter plot'\n"
                    "- If user says 'line plot' or 'line chart' → sub-question MUST include 'line plot' or 'line chart'\n"
                    "- If user says 'violin plot' → sub-question MUST include 'violin plot'\n"
                    "NEVER change the plot type. ALWAYS copy the exact plot type from the user's query.\n\n"

                    "## PRIORITY 3: Box Plots with Multiple Groups\n"
                    "**CRITICAL FOR BOX PLOTS**: Box plots REQUIRE raw sample-level data, NOT aggregated statistics.\n"
                    "When user asks for box plots or visualizations comparing MULTIPLE GROUPS (e.g., Normal vs Tumor vs Cell lines):\n"
                    "- Create SEPARATE database queries for EACH group\n"
                    "- **EACH QUERY MUST FETCH RAW DATA**: Use 'Fetch RAW expression values' or 'Fetch individual sample TPM values'\n"
                    "- **DO NOT use**: 'Fetch expression levels' or 'Fetch statistics' (these return aggregates)\n"
                    "- Each sub_question should say: 'Fetch RAW/individual expression values of gene X in [group]'\n"
                    "- After all database queries, add ONE plotting step with preserved plot type\n\n"

                    "### Examples (Decision Priority: Modification > Type Preservation > Multiple Groups)\n\n"

                    "**1. Single-Step**: User Query: 'What is the weather in Paris?'\n"
                    "ExecutionPlan: [{'sub_question': 'Get Paris weather', 'action_input': {}, 'tool': 'get_weather_data'}]\n\n"

                    "**2. Multi-Step Basic**: User Query: 'plot me a graph for all facilities with their capacities'\n"
                    "ExecutionPlan: [\n"
                    "   {'sub_question': 'Fetch facilities and capacities', 'action_input': {}, 'tool': 'ask_database'},\n"
                    "   {'sub_question': 'Plot facilities and capacities', 'action_input': {}, 'tool': 'gen_plotly_code'}\n"
                    "]\n\n"

                    "**3. Plot with Type Preservation**: User Query: 'Show me EGFR expression. Plot as box plots.'\n"
                    "ExecutionPlan: [\n"
                    "   {'sub_question': 'Fetch expression of gene EGFR', 'action_input': {}, 'tool': 'ask_database'},\n"
                    "   {'sub_question': 'Plot EGFR expression as box plots', 'action_input': {}, 'tool': 'gen_plotly_code'}\n"
                    "]\n\n"

                    "**4. Box Plots Multiple Groups**: User Query: 'Show EGFR expression as box plots: one for normal, one for tumor, one for cell lines'\n"
                    "ExecutionPlan: [\n"
                    "   {'sub_question': 'Fetch RAW individual expression values of gene EGFR in normal tissues', 'action_input': {}, 'tool': 'ask_database'},\n"
                    "   {'sub_question': 'Fetch RAW individual expression values of gene EGFR in tumor tissues', 'action_input': {}, 'tool': 'ask_database'},\n"
                    "   {'sub_question': 'Fetch RAW individual expression values of gene EGFR in cell lines', 'action_input': {}, 'tool': 'ask_database'},\n"
                    "   {'sub_question': 'Generate box plots for the expression of gene EGFR in normal tissues, tumor tissues, and cell lines', 'action_input': {}, 'tool': 'gen_plotly_code'}\n"
                    "]\n\n"

                    "**5. Plot Modification**: User Query: 'i want box plots for above data'\n"
                    "ExecutionPlan: [{'sub_question': 'Modify plot to show data as box plots', 'action_input': {'modify': true}, 'tool': 'gen_plotly_code'}]\n\n"

                    "Respond with valid JSON containing 'ExecutionPlan'."
                )
            },
            {
                "role": "user",
                "content": (
                    f"User Input: {user_query}\n"
                    f"User selected tools: {selected_tools or 'None'}\n"
                    f"Is Plot Modification Request: {is_plot_modification}\n\n"
                    f"Recent Conversation History (last 6 messages):\n"
                    f"{json.dumps(message[-6:] if message and len(message) > 0 else [], indent=2)}"
                )
            }
        ]

        # Call LLM for planning
        if llm_generate_response:
            response = await llm_generate_response(
                planning_prompt,
                user_id,
                response_format=True
            )
            parsed_response = response.choices[0].message.content
        else:
            # Fallback: create simple plan
            parsed_response = json.dumps({
                "ExecutionPlan": [{
                    "sub_question": user_query,
                    "action_input": {},
                    "tool": selected_tools[0] if selected_tools else "ask_database"
                }]
            })

        try:
            execution_plan_dict = json.loads(parsed_response)
            execution_steps = execution_plan_dict.get("ExecutionPlan", [])
        except Exception as e:
            print(colored(f"Failed to parse execution plan: {e}", "red"))
            # Fallback to single-step plan
            execution_steps = [{
                "sub_question": user_query,
                "action_input": {},
                "tool": selected_tools[0] if selected_tools else "ask_database"
            }]

        # Log execution plan clearly
        print(colored(f"\n{'='*80}", "cyan"))
        print(colored(f"📋 EXECUTION PLAN: {len(execution_steps)} steps", "cyan", attrs=["bold"]))
        print(colored(f"{'='*80}", "cyan"))
        for idx, step in enumerate(execution_steps, 1):
            tool = step.get('tool', 'unknown')
            sub_q = step.get('sub_question', 'N/A')
            print(colored(f"  Step {idx}: [{tool}]", "yellow", attrs=["bold"]))
            print(colored(f"          → {sub_q}", "white"))
        print(colored(f"{'='*80}\n", "cyan"))

        # NEW: Add planning step to reasoning
        reasoning_steps.append({
            "type": "planning",
            "title": "Query Planning",
            "details": f"Decomposed query into {len(execution_steps)} execution step(s)",
            "steps": [
                {
                    "step_num": idx,
                    "tool": step.get('tool', 'unknown'),
                    "sub_question": step.get('sub_question', 'N/A')
                }
                for idx, step in enumerate(execution_steps, 1)
            ]
        })

        # Step 2: Execute each step via MCP
        mcp_client = get_internal_mcp_client()

        for idx, step in enumerate(execution_steps):
            sub_question = step.get("sub_question", user_query)
            action_input = step.get("action_input", {})
            tool_name = step.get("tool", "ask_database")

            await send_status_to_user(user_id, status=f"Executing step {idx+1}/{len(execution_steps)}: {tool_name}...")

            scratchpad.append((sub_question, ""))

            # Prepare tool arguments
            if isinstance(action_input, str):
                try:
                    action_input = json.loads(action_input)
                except json.JSONDecodeError:
                    action_input = {"question": action_input}

            if "question" not in action_input:
                action_input["question"] = sub_question

            # Add context
            action_input["user_id"] = user_id
            action_input["user_group"] = user_group
            action_input["logger_timestamp"] = logger_timestamp

            # Special handling for gen_plotly_code - pass sub_question_list, query_ids, and CSV paths
            if tool_name == "gen_plotly_code":
                if sub_question_list:
                    action_input["sub_question_list"] = sub_question_list
                if query_ids:
                    action_input["query_ids"] = query_ids
                if csv_file_paths:
                    action_input["csv_file_paths"] = csv_file_paths
                    print(colored(f"📊 Passing {len(csv_file_paths)} CSV paths to plotting", "cyan"))

            try:
                # Execute tool via MCP with user context
                result = await mcp_client.call_tool(
                    tool_name,
                    action_input,
                    user_id=user_id,
                    user_group=user_group,
                    logger_timestamp=logger_timestamp
                )

                # Parse MCP response
                observation = None
                sql = None
                base64_code = None
                code = None
                fig_json = None
                query_id = None

                if result:
                    # MCP client returns the parsed payload directly
                    # Try multiple field names for the main result data
                    observation = (
                        result.get("observation") or
                        result.get("data") or
                        result.get("report") or
                        result.get("results_data")
                    )
                    sql = result.get("sql_query") or result.get("sql")
                    base64_code = result.get("base64_code") or result.get("base64")
                    code = result.get("code")
                    fig_json = result.get("fig_json")
                    query_id = result.get("query_id")

                # Update scratchpad
                if observation:
                    scratchpad[-1] = (sub_question, observation)

                # NEW: Add execution step to reasoning
                step_result = {
                    "type": "execution",
                    "step_num": idx + 1,
                    "tool": tool_name,
                    "sub_question": sub_question,
                    "status": "success",
                    "has_sql": bool(sql),
                    "has_result": bool(observation),
                    "has_visualization": bool(fig_json)
                }
                if query_id:
                    step_result["query_id"] = query_id
                reasoning_steps.append(step_result)

                # Track sub-questions for ask_database
                if tool_name == "ask_database":
                    sub_question_list.append(sub_question)

                # Accumulate SQL queries
                if sql:
                    sql_list.append(sql)

                # Accumulate results
                if base64_code:
                    if isinstance(base64_code, list):
                        base64_code_list.extend(base64_code)
                    else:
                        base64_code_list.append(base64_code)

                if code:
                    if isinstance(code, list):
                        code_list.extend(code)
                    else:
                        code_list.append(code)

                if fig_json:
                    if isinstance(fig_json, list):
                        fig_json_list.extend(fig_json)
                    else:
                        fig_json_list.append(fig_json)

                if query_id:
                    query_ids.append(query_id)

                    # Construct CSV path from query_id
                    # Actual pattern from SQL agent: temp/{user_id}_{logger_timestamp_mod}_mcp_{query_id}_results.csv
                    # where logger_timestamp_mod is the logger_timestamp with underscores
                    # The tool_id is always "mcp" when called through MCP protocol
                    logger_timestamp_underscored = logger_timestamp.replace("-", "_")
                    csv_path = f"temp/{user_id}_{logger_timestamp_underscored}_mcp_{query_id}_results.csv"
                    csv_file_paths.append(csv_path)
                    print(colored(f"📊 Query ID {len(query_ids)}: {query_id}", "cyan"))
                    print(colored(f"📁 Constructed CSV path: {csv_path}", "green"))

            except Exception as e:
                print(colored(f"Error executing {tool_name}: {e}", "red"))
                scratchpad[-1] = (sub_question, f"Error: {str(e)}")

                # NEW: Add error step to reasoning
                reasoning_steps.append({
                    "type": "execution",
                    "step_num": idx + 1,
                    "tool": tool_name,
                    "sub_question": sub_question,
                    "status": "error",
                    "error": str(e)
                })

        # Step 3: Generate follow-up questions
        await send_status_to_user(user_id, status="Generating follow-up questions...")

        followup_prompt = [
            {
                "role": "system",
                "content": (
                    "Based on the user's query and the tools used, suggest 3 relevant follow-up questions "
                    "the user might want to ask next. Make them specific and actionable."
                )
            },
            {
                "role": "user",
                "content": (
                    f"Original Query: {user_query}\n"
                    f"Tools Used: {[step.get('tool') for step in execution_steps]}\n"
                    "Suggest 3 follow-up questions:"
                )
            }
        ]

        parsed_questions = []
        try:
            if llm_generate_response:
                response = await llm_generate_response(
                    followup_prompt,
                    user_id,
                    response_format=False
                )
                followup_text = response.choices[0].message.content

                # Parse questions
                parsed_questions = [
                    line.strip().lstrip("0123456789.-) ").strip()
                    for line in followup_text.split("\n")
                    if line.strip() and any(char.isalpha() for char in line)
                ][:3]

                print(colored(f"📝 Generated {len(parsed_questions)} follow-up questions:", "cyan"))
                for i, q in enumerate(parsed_questions, 1):
                    print(colored(f"   {i}. {q}", "cyan"))
        except Exception as e:
            print(colored(f"Error generating follow-up questions: {e}", "red"))

        # Format scratchpad
        scratchpad_log = "\n\n".join([
            f"**Q:** {q}\n**A:** {a}" for q, a in scratchpad
        ])

        final_query_id = query_ids[-1] if query_ids else None

        # Combine SQL queries if multiple steps - use special delimiter
        combined_sql = '\n\n--- NEXT QUERY ---\n\n'.join(sql_list) if sql_list else None

        # print(colored(f"✅ COT Agent returning:", "green"))
        # print(colored(f"   - SQL: {combined_sql}", "green"))
        # print(colored(f"   - Parsed Questions: {parsed_questions}", "green"))
        # print(colored(f"   - Query ID: {final_query_id}", "green"))

        # NEW: Add summary reasoning step
        reasoning_steps.append({
            "type": "summary",
            "title": "Execution Complete",
            "total_steps": len(execution_steps),
            "sql_generated": bool(combined_sql),
            "visualizations_created": len(fig_json_list),
            "followup_questions": len(parsed_questions)
        })

        return (
            scratchpad_log,
            combined_sql,  # Return accumulated SQL queries
            base64_code_list,
            code_list,
            fig_json_list,
            None,  # report_content
            parsed_questions,
            final_query_id,
            reasoning_steps  # NEW: Return reasoning steps
        )

    except Exception as e:
        print(colored(f"Error in COT_Agent_Pydantic: {e}", "red"))
        import traceback
        traceback.print_exc()
        return (
            f"Error: {str(e)}",
            None,
            [],
            [],
            [],
            None,
            None,
            None,
            []  # NEW: Return empty reasoning steps on error
        )
