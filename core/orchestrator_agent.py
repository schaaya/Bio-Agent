"""
Orchestrator Agent with Reflective Loop
Meta-agent that plans, executes, reflects, and adapts
"""
import json
import time
from typing import List, Dict, Any, Optional, Tuple
from termcolor import colored
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext

from core.orchestrator_dependencies import (
    OrchestratorDependencies,
    BudgetTracker,
    MemoryManager,
    Source
)
from core.globals import send_status_to_user
from mcp_files.mcp_internal_client import get_internal_mcp_client

# Import Azure OpenAI model configuration
import os
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from openai import AsyncAzureOpenAI


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
# Pydantic Models for Orchestrator
# ============================================================================

class ExecutionStep(BaseModel):
    """Single step in execution plan"""
    step_number: int
    goal: str
    tool_type: str  # "database", "plotting", "document", "analysis"
    tool_name: Optional[str] = None  # Specific tool (filled during selection)
    action_input: Dict[str, Any] = {}
    expected_output: str
    success_criteria: List[str]
    retry_count: int = 0  # Track retry attempts
    max_retries: int = 1  # Maximum retry attempts (1 retry = 2 total attempts)


class ExecutionPlan(BaseModel):
    """Complete execution plan"""
    steps: List[ExecutionStep]
    overall_goal: str
    estimated_steps: int
    estimated_cost: Optional[float] = None


class Reflection(BaseModel):
    """Reflection on step execution"""
    step_goal: str
    status: str  # "success", "partial", "failed"
    evaluation: str
    has_result: bool
    is_complete: bool
    needs_more_info: bool
    next_action: str  # "continue", "replan", "stop"
    insights: List[str] = []


class GroundedAnswer(BaseModel):
    """Final answer with citations"""
    answer: str
    sources: List[Dict[str, Any]]
    confidence: float
    follow_ups: List[str]
    metadata: Dict[str, Any] = {}


# ============================================================================
# Orchestrator Agent Definition
# ============================================================================

orchestrator_agent = Agent(
    model=create_azure_model(),
    deps_type=OrchestratorDependencies,
    system_prompt="""
You are a meta-orchestrator agent for a biomedical gene expression database system.

🔬 DOMAIN CONTEXT:
This system contains gene expression data from:
- Human tissue samples (tumor vs normal)
- Cell lines with mutation profiles (KRAS, TP53, EGFR)
- RNA-seq TPM values for thousands of genes

Your role is to:
1. PLAN: Decompose user queries into executable steps
2. EXECUTE: Select and invoke appropriate tools via MCP
3. REFLECT: Evaluate results and adapt
4. COMPOSE: Generate grounded answers with citations

Key principles:
- Break complex queries into simple, achievable steps
- Select the right tool for each step (database, plotting, analysis, etc.)
- Reflect after each step to ensure quality
- Track sources for citation
- Respect budgets and stop if limits exceeded
- Provide transparent, grounded answers

Available tool types:
- database: Query SQL database for gene expression, mutations, comparisons
  * Use for: gene queries, expression levels, mutation analysis, tumor vs normal
  * Examples: "Compare EGFR in KRAS-mutant", "TP53 in tumor vs normal"
- plotting: Generate interactive visualizations (boxplots, heatmaps, bar charts)
- document: Query PDF/document repositories
- analysis: Comparative and statistical analysis
- weather: Get weather data (if applicable)

IMPORTANT: Queries about genes, expression, mutations, tumors, or cell lines should ALWAYS use the "database" tool.

Always be thoughtful, adaptive, and transparent.
""",
)


# ============================================================================
# Planning Functions
# ============================================================================

async def plan_execution(
    query: str,
    ctx: OrchestratorDependencies
) -> ExecutionPlan:
    """
    Use LLM to decompose query into execution plan
    """
    await send_status_to_user(ctx.user_id, status="Planning execution strategy...")

    planning_prompt = f"""
Analyze this user query and create an execution plan.

User Query: {query}

Available tool types:
- database: Query SQL databases (gene expression, mutations, tissue data, cell lines)
- plotting: Generate visualizations (charts, graphs, heatmaps)
- document: Search PDF documents
- analysis: Comparative analysis (statistical comparisons)

🔬 IMPORTANT: This is a biomedical gene expression database system.

Queries about genes, expression levels, mutations, tumors, tissues, or cell lines should use "database" tool.

Examples of DATABASE queries:
- "Compare EGFR in KRAS-mutant cell lines" → database
- "Show TP53 expression in tumor vs normal" → database
- "Which genes are upregulated in tumor" → database
- "EGFR levels in mutant cells" → database
- "Expression of [gene] in [condition]" → database
- "Differential expression of [gene]" → database
- "Genes with fold change > 2" → database
- Any query mentioning: genes, expression, TPM, tumor, normal, mutant, wildtype, cell lines

Examples of PLOTTING queries:
- "Visualize the results" → plotting (after database query)
- "Create a heatmap" → plotting
- "Plot expression levels" → database + plotting

Examples of ANALYSIS queries:
- "Statistical comparison of groups" → analysis (after database query)

Create a step-by-step plan. Each step should:
1. Have a clear, specific goal
2. Specify which tool type to use
3. Define success criteria

Respond with JSON in this format:
{{
    "overall_goal": "Brief description of what we're trying to achieve",
    "estimated_steps": <number>,
    "steps": [
        {{
            "step_number": 1,
            "goal": "Specific goal for this step",
            "tool_type": "database|plotting|document|analysis",
            "action_input": {{}},
            "expected_output": "What we expect to get",
            "success_criteria": ["criterion 1", "criterion 2"]
        }}
    ]
}}

Be concise. Most biomedical queries need 1-2 steps (database query, then optional visualization/analysis).
"""

    try:
        if ctx.llm_generate_response:
            response = await ctx.llm_generate_response(
                [{"role": "user", "content": planning_prompt}],
                ctx.user_id,
                response_format=True
            )
            plan_json = response.choices[0].message.content

            # Track LLM usage
            if hasattr(response, 'usage'):
                ctx.budget_tracker.track_llm_call(response.usage.__dict__)
        else:
            # Fallback: single-step plan
            plan_json = json.dumps({
                "overall_goal": query,
                "estimated_steps": 1,
                "steps": [{
                    "step_number": 1,
                    "goal": query,
                    "tool_type": "database",
                    "action_input": {"question": query},
                    "expected_output": "Query results",
                    "success_criteria": ["Data returned"]
                }]
            })

        plan_dict = json.loads(plan_json)
        plan = ExecutionPlan(**plan_dict)

        print(colored(f"\n📋 Execution Plan Created:", "cyan", attrs=["bold"]))
        print(colored(f"   Goal: {plan.overall_goal}", "cyan"))
        print(colored(f"   Steps: {len(plan.steps)}", "cyan"))
        for step in plan.steps:
            print(colored(f"     {step.step_number}. {step.goal} (via {step.tool_type})", "cyan"))

        return plan

    except Exception as e:
        print(colored(f"Error in planning: {e}", "red"))
        # Fallback plan
        return ExecutionPlan(
            overall_goal=query,
            estimated_steps=1,
            steps=[
                ExecutionStep(
                    step_number=1,
                    goal=query,
                    tool_type="database",
                    action_input={"question": query},
                    expected_output="Query results",
                    success_criteria=["Data returned"]
                )
            ]
        )


# ============================================================================
# Tool Selection Functions
# ============================================================================

def get_tool_mapping() -> Dict[str, str]:
    """Map tool types to MCP tool names"""
    return {
        "database": "ask_database",
        "plotting": "gen_plotly_code",
        "document": "pdf_query",
        "analysis": "comparative_analyzer",
        "weather": "get_weather_data"
    }


async def select_tool_for_step(
    step: ExecutionStep,
    ctx: OrchestratorDependencies
) -> str:
    """
    Select specific MCP tool for a step
    Currently uses simple mapping, can be enhanced with dynamic selection
    """
    tool_mapping = get_tool_mapping()
    tool_name = tool_mapping.get(step.tool_type, "ask_database")

    # Update step with selected tool
    step.tool_name = tool_name

    print(colored(f"   🔧 Selected tool: {tool_name}", "yellow"))
    return tool_name


# ============================================================================
# Reflection Functions
# ============================================================================

async def reflect_on_step(
    step: ExecutionStep,
    result: Dict[str, Any],
    ctx: OrchestratorDependencies
) -> Reflection:
    """
    LLM reflects on step execution and decides next action
    """
    # Extract observation for reflection
    observation = result.get("observation") or result.get("data") or result.get("report") or str(result)

    # Check if this was a database query that returned data
    is_database_query = step.tool_type == "database" and result.get("observation")
    has_data = bool(observation and observation != "Error" and "error" not in str(observation).lower())

    reflection_prompt = f"""
Reflect on this execution step:

Goal: {step.goal}
Expected: {step.expected_output}
Success Criteria: {step.success_criteria}
Tool Type: {step.tool_type}

Actual Result: {str(observation)[:500]}

IMPORTANT REFLECTION GUIDELINES:
1. For database queries: If the query executed successfully and returned data, mark as SUCCESS (not partial)
   - Don't penalize for "incomplete column descriptions" - focus on whether data was retrieved
   - Only mark as PARTIAL if the data is clearly wrong or missing critical information
   - Only mark as FAILED if there was an error or no data returned
2. For plotting: Be lenient - chart type preferences are subjective
3. For other tools: Evaluate if the goal was achieved

Evaluate:
1. Was the goal achieved? (yes/no/partial)
2. Is the result valid (no errors)?
3. For database queries: Did we get actual data back?
4. Should we proceed (continue) or retry (replan)?

Respond with JSON:
{{
    "status": "success|partial|failed",
    "evaluation": "Brief assessment",
    "has_result": true/false,
    "is_complete": true/false,
    "needs_more_info": true/false,
    "next_action": "continue|replan|stop",
    "insights": ["insight 1", "insight 2"]
}}

IMPORTANT: Be pragmatic. If a database query returned data without errors, mark it as SUCCESS and use "continue" as next_action.
"""

    try:
        if ctx.llm_generate_response:
            response = await ctx.llm_generate_response(
                [{"role": "user", "content": reflection_prompt}],
                ctx.user_id,
                response_format=True
            )
            reflection_json = response.choices[0].message.content

            # Track LLM usage
            if hasattr(response, 'usage'):
                ctx.budget_tracker.track_llm_call(response.usage.__dict__)

            reflection_dict = json.loads(reflection_json)
            reflection_dict["step_goal"] = step.goal
            reflection = Reflection(**reflection_dict)

            print(colored(f"   🧠 Reflection: {reflection.status.upper()} - {reflection.evaluation}", "magenta"))
            print(colored(f"      Next action: {reflection.next_action}", "magenta"))

            return reflection
        else:
            # Fallback: assume success
            return Reflection(
                step_goal=step.goal,
                status="success",
                evaluation="Step completed",
                has_result=True,
                is_complete=True,
                needs_more_info=False,
                next_action="continue"
            )

    except Exception as e:
        print(colored(f"Error in reflection: {e}", "red"))
        return Reflection(
            step_goal=step.goal,
            status="success",
            evaluation="Step completed (reflection error)",
            has_result=True,
            is_complete=True,
            needs_more_info=False,
            next_action="continue"
        )


# ============================================================================
# Execution Loop
# ============================================================================

async def execute_step_via_mcp(
    step: ExecutionStep,
    ctx: OrchestratorDependencies
) -> Tuple[Dict[str, Any], Optional[Source]]:
    """
    Execute a single step via MCP
    Returns the full result dict and source for proper extraction
    """
    # Select tool
    tool_name = await select_tool_for_step(step, ctx)

    # Prepare arguments
    action_input = step.action_input.copy()
    if "question" not in action_input:
        action_input["question"] = step.goal

    # Add user context
    action_input["user_id"] = ctx.user_id
    action_input["user_group"] = ctx.user_group
    action_input["logger_timestamp"] = ctx.logger_timestamp

    # Auto-generate tag for ask_database to prevent CSV overwrites
    if tool_name == "ask_database" and "tag" not in action_input:
        # Extract key words from goal for tag (e.g., "tumor", "normal", etc.)
        import re
        goal_lower = step.goal.lower()
        keywords = re.findall(r'\b(tumor|normal|cancer|control|treated|untreated|mutant|wildtype|case|control)\b', goal_lower)
        tag_suffix = "_".join(keywords[:2]) if keywords else "data"
        action_input["tag"] = f"step{step.step_number}_{tag_suffix}"
        print(colored(f"   🏷️  Auto-generated tag: {action_input['tag']}", "cyan"))

    # Auto-collect tags for plotting to use all datasets
    if tool_name == "gen_plotly_code" and "tags" not in action_input:
        # Collect all tags from previous ask_database steps
        tags = []
        for mem_step in ctx.memory.scratchpad:
            if mem_step.metadata.get("tool_name") == "ask_database":
                # Extract tag from the step's result or reconstruct from step number
                step_num = mem_step.metadata.get("step_number")
                if step_num:
                    # Reconstruct tag pattern (matches auto-generated tags above)
                    import re
                    goal_lower = mem_step.goal.lower()
                    keywords = re.findall(r'\b(tumor|normal|cancer|control|treated|untreated|mutant|wildtype|case|control)\b', goal_lower)
                    tag_suffix = "_".join(keywords[:2]) if keywords else "data"
                    tags.append(f"step{step_num}_{tag_suffix}")

        if tags:
            action_input["tags"] = tags
            print(colored(f"   🏷️  Collected tags for plotting: {tags}", "cyan"))

    print(colored(f"   ⚙️  Executing: {tool_name}", "yellow"))

    # Track start time
    start_time = time.time()

    try:
        # Call MCP tool
        result = await ctx.mcp_client.call_tool(
            tool_name,
            action_input,
            user_id=ctx.user_id,
            user_group=ctx.user_group,
            logger_timestamp=ctx.logger_timestamp
        )

        # Track latency
        latency = time.time() - start_time
        ctx.budget_tracker.track_tool_call(tool_name, latency)

        # Extract observation for display
        observation = None
        source = None

        if result:
            # MCP client returns parsed payload directly
            observation = (
                result.get("observation") or
                result.get("data") or
                result.get("report") or
                result.get("results_data")
            )

            # Create source for citation
            query_id = result.get("query_id")
            if query_id:
                source = Source(
                    id=query_id,
                    type="sql_query" if tool_name == "ask_database" else tool_name,
                    content=result.get("sql") or result.get("sql_query") or observation,
                    metadata={
                        "tool": tool_name,
                        "latency": latency,
                        "sql": result.get("sql") or result.get("sql_query"),
                        "query_id": query_id
                    }
                )

        print(colored(f"   ✅ Completed in {latency:.2f}s", "green"))

        # Return the full result dict (not just observation) so we can extract SQL, plots, etc.
        return result if result else {"observation": observation}, source

    except Exception as e:
        print(colored(f"   ❌ Error: {e}", "red"))
        latency = time.time() - start_time
        ctx.budget_tracker.track_tool_call(tool_name, latency)
        return f"Error: {str(e)}", None


async def reflective_execution_loop(
    plan: ExecutionPlan,
    ctx: OrchestratorDependencies
) -> MemoryManager:
    """
    Execute plan with reflection after each step
    Core of the orchestrator's intelligence
    """
    print(colored(f"\n🔄 Starting Reflective Execution Loop", "cyan", attrs=["bold"]))

    for step in plan.steps:
        # Retry loop for handling replans
        while True:
            # Check budget before each attempt
            if ctx.budget_tracker.is_over_budget():
                print(colored(f"\n⚠️  Budget limit reached!", "yellow", attrs=["bold"]))
                print(ctx.budget_tracker.get_budget_status())
                break

            print(colored(f"\n📍 Step {step.step_number}: {step.goal}", "cyan", attrs=["bold"]))
            if step.retry_count > 0:
                print(colored(f"   🔄 Retry {step.retry_count}/{step.max_retries}", "yellow"))

            await send_status_to_user(
                ctx.user_id,
                status=f"Step {step.step_number}/{len(plan.steps)}: {step.goal}..."
            )

            # Execute step
            result, source = await execute_step_via_mcp(step, ctx)

            # Store in memory
            ctx.memory.add_step(
                goal=step.goal,
                result=result,
                source=source,
                metadata={
                    "step_number": step.step_number,
                    "tool_type": step.tool_type,
                    "tool_name": step.tool_name,
                    "retry_count": step.retry_count
                }
            )

            # CRITICAL FIX: Bridge orchestrator memory to global cache for comparative_analyzer
            if step.tool_name == "ask_database" and source and source.id:
                try:
                    # Get observation from result
                    observation = (
                        result.get("observation") or
                        result.get("data") or
                        result.get("results_data") or
                        result.get("report") or  # MCP returns 'report' field
                        result.get("output")
                    ) if isinstance(result, dict) else result

                    # Cache for comparative_analyzer to find
                    cache_data = {
                        "tool_name": step.tool_name,
                        "observation": str(observation),
                        "sql": result.get("sql") if isinstance(result, dict) else None,
                        "query_id": source.id
                    }

                    # Use global tool_cache instead of ctx.cache_client
                    from core.globals import tool_ids, tool_cache, add_csv_path_mapping
                    tool_cache[source.id] = json.dumps(cache_data)
                    tool_ids.append(source.id)

                    # CRITICAL FIX: Store CSV file path mapping for summarizer
                    # Extract CSV file path from result (could be in multiple fields)
                    csv_file_path = None
                    if isinstance(result, dict):
                        csv_file_path = (
                            result.get("csv_file_path") or
                            result.get("csv_path") or
                            result.get("file_path") or
                            result.get("csv") or
                            result.get("file")
                        )

                        # DEBUG: Show what's in result dict
                        print(colored(f"   🔍 DEBUG result keys: {list(result.keys())}", "yellow"))

                    # If not in result dict, try to construct from source.id and user info
                    if not csv_file_path and isinstance(result, dict):
                        # Try to extract from observation text
                        obs_str = str(observation) if observation else ""

                        # DEBUG: Show first 500 chars of observation
                        print(colored(f"   🔍 DEBUG observation (first 500): {obs_str[:500]}", "yellow"))

                        if "Results: temp/" in obs_str:
                            import re
                            match = re.search(r'Results: (temp/[^\s]+\.csv)', obs_str)
                            if match:
                                csv_file_path = match.group(1)
                        elif "temp/" in obs_str and ".csv" in obs_str:
                            # More flexible pattern
                            import re
                            match = re.search(r'(temp/[^\s\n]+\.csv)', obs_str)
                            if match:
                                csv_file_path = match.group(1)

                    # If still not found, construct from known MCP pattern
                    if not csv_file_path:
                        # MCP tools save CSV as: temp/{user_id}_{logger_timestamp}_mcp_{tag}_results.csv
                        # Extract tag from action_input (where it's stored during tool selection)
                        tag = None
                        if hasattr(step, 'action_input') and isinstance(step.action_input, dict):
                            tag = step.action_input.get('tag')

                        # Fallback: try to reconstruct tag from goal
                        if not tag:
                            import re
                            goal_lower = step.goal.lower()
                            keywords = re.findall(r'\b(tumor|normal|cancer|control|treated|untreated|mutant|wildtype|case|control)\b', goal_lower)
                            tag_suffix = "_".join(keywords[:2]) if keywords else "data"
                            tag = f"step{step.step_number}_{tag_suffix}"

                        # Construct the path
                        csv_file_path = f"temp/{ctx.user_id}_{ctx.logger_timestamp}_mcp_{tag}_results.csv"

                        # Verify file exists before using constructed path
                        import os
                        if os.path.exists(csv_file_path):
                            print(colored(f"   🔨 Constructed CSV path from tag '{tag}': {csv_file_path}", "cyan"))
                        else:
                            print(colored(f"   ⚠️  Constructed path doesn't exist: {csv_file_path}", "yellow"))
                            print(colored(f"   ℹ️  Tag used: {tag}", "yellow"))
                            csv_file_path = None

                    # Store the mapping if we found the path
                    if csv_file_path:
                        user_email = ctx.user_id.split("_")[0]
                        add_csv_path_mapping(user_email, source.id, csv_file_path)
                        print(colored(f"   📁 Stored CSV path mapping: {source.id} -> {csv_file_path}", "cyan"))
                    else:
                        print(colored(f"   ⚠️  Could not extract CSV file path from result", "yellow"))
                        print(colored(f"   ℹ️  Result type: {type(result)}, has keys: {list(result.keys()) if isinstance(result, dict) else 'N/A'}", "yellow"))

                    print(colored(f"   💾 Cached result with ID: {source.id} for comparative_analyzer", "cyan"))
                except Exception as e:
                    print(colored(f"   ⚠️  Failed to cache result: {e}", "yellow"))

            # Reflect on result
            reflection = await reflect_on_step(step, result, ctx)

            # Decide next action based on reflection
            if reflection.next_action == "stop":
                print(colored(f"   🛑 Stopping execution (reflection decision)", "yellow"))
                return ctx.memory

            elif reflection.next_action == "replan":
                # Special handling for plotting steps - don't retry
                if step.tool_type == "plotting":
                    print(colored(f"   ℹ️  Plotting failures are subjective (chart type preferences). Accepting current result.", "cyan"))
                    if reflection.insights:
                        print(colored(f"   💡 Note: {', '.join(reflection.insights)}", "cyan"))
                    break  # Don't retry plotting, move to next step

                # Check if we can retry (for non-plotting steps)
                if step.retry_count < step.max_retries:
                    step.retry_count += 1
                    print(colored(f"   🔄 Replanning: Retrying step {step.step_number} (attempt {step.retry_count + 1})", "yellow"))

                    # Track retry in budget
                    ctx.budget_tracker.track_tool_call(
                        f"{step.tool_name}_retry",
                        0.0  # No additional latency for retry decision
                    )

                    # Modify step based on reflection insights if available
                    if reflection.insights:
                        print(colored(f"   💡 Insights: {', '.join(reflection.insights)}", "cyan"))

                    # Continue to next iteration of while loop (retry)
                    continue
                else:
                    # Max retries reached, continue with what we have
                    print(colored(f"   ⚠️  Max retries ({step.max_retries}) reached. Continuing with partial result.", "yellow"))
                    break  # Exit retry loop, proceed to next step

            else:  # next_action == "continue" or any other value
                # Success or acceptable partial result, move to next step
                break  # Exit retry loop

        # Check budget again after potentially multiple retries
        if ctx.budget_tracker.is_over_budget():
            break

    # Print final budget status
    print(colored(f"\n💰 Final Budget Status:", "cyan", attrs=["bold"]))
    print(ctx.budget_tracker.get_budget_status())

    return ctx.memory


# ============================================================================
# Answer Composition
# ============================================================================

async def compose_grounded_answer(
    ctx: OrchestratorDependencies
) -> GroundedAnswer:
    """
    Compose final answer with citations
    """
    await send_status_to_user(ctx.user_id, status="Composing final answer...")

    scratchpad_text = ctx.memory.get_scratchpad_text()
    sources = ctx.memory.get_sources_for_citation()

    composer_prompt = f"""
Based on the execution results, compose a final answer to the user's query.

Original Query: {ctx.original_query}

Execution Results:
{scratchpad_text}

Available Sources for Citation:
{json.dumps(sources, indent=2)}

Instructions:
1. Directly answer the user's question
2. Cite sources using [source_id] format
3. Be concise and clear
4. Highlight any uncertainties
5. Suggest 3 relevant follow-up questions

Respond with JSON:
{{
    "answer": "Your answer with [source_id] citations",
    "confidence": 0.0-1.0,
    "follow_ups": ["question 1", "question 2", "question 3"]
}}
"""

    try:
        if ctx.llm_generate_response:
            response = await ctx.llm_generate_response(
                [{"role": "user", "content": composer_prompt}],
                ctx.user_id,
                response_format=True
            )
            answer_json = response.choices[0].message.content

            # Track LLM usage
            if hasattr(response, 'usage'):
                ctx.budget_tracker.track_llm_call(response.usage.__dict__)

            answer_dict = json.loads(answer_json)
            answer = GroundedAnswer(
                answer=answer_dict["answer"],
                sources=sources,
                confidence=answer_dict.get("confidence", 0.8),
                follow_ups=answer_dict.get("follow_ups", []),
                metadata={
                    "budget": ctx.budget_tracker.get_consumed(),
                    "steps_executed": len(ctx.memory.scratchpad)
                }
            )

            return answer
        else:
            # Fallback: return scratchpad
            return GroundedAnswer(
                answer=scratchpad_text,
                sources=sources,
                confidence=0.7,
                follow_ups=[],
                metadata={}
            )

    except Exception as e:
        print(colored(f"Error in answer composition: {e}", "red"))
        return GroundedAnswer(
            answer=scratchpad_text,
            sources=sources,
            confidence=0.7,
            follow_ups=[],
            metadata={"error": str(e)}
        )


# ============================================================================
# Main Orchestrator Function
# ============================================================================

async def Orchestrator_Agent(
    user_query: str,
    user_id: str,
    user_group: str,
    logger_timestamp: str,
    llm_generate_response: Any = None,
    custom_instructions: Optional[str] = None,
    message_history: Optional[List[Dict[str, str]]] = None,
    max_tokens: int = 50000,
    max_cost: float = 5.0
) -> Tuple[str, Optional[str], List[str], List[str], List[Any], List[str], Optional[str]]:
    """
    Main orchestrator function
    Entry point for the orchestrator agent

    Returns:
        Tuple of (answer, sql, base64_code_list, code_list, fig_json_list, follow_ups, query_id)
    """
    print(colored(f"\n{'='*80}", "cyan", attrs=["bold"]))
    print(colored(f"🎯 ORCHESTRATOR AGENT STARTED", "cyan", attrs=["bold"]))
    print(colored(f"{'='*80}\n", "cyan", attrs=["bold"]))

    try:
        # Initialize dependencies
        budget_tracker = BudgetTracker(
            max_tokens=max_tokens,
            max_cost=max_cost
        )
        memory = MemoryManager()
        mcp_client = get_internal_mcp_client()

        ctx = OrchestratorDependencies(
            user_id=user_id,
            user_group=user_group,
            logger_timestamp=logger_timestamp,
            original_query=user_query,
            budget_tracker=budget_tracker,
            memory=memory,
            mcp_client=mcp_client,
            llm_generate_response=llm_generate_response,
            custom_instructions=custom_instructions,
            message_history=message_history
        )

        # 1. PLAN: Create execution plan
        plan = await plan_execution(user_query, ctx)

        # 2. EXECUTE: Run reflective execution loop
        memory = await reflective_execution_loop(plan, ctx)

        # 3. COMPOSE: Generate grounded answer
        grounded_answer = await compose_grounded_answer(ctx)

        print(colored(f"\n✅ Orchestrator completed successfully", "green", attrs=["bold"]))

        # Extract results from memory for UI display
        sql_queries = []
        base64_code_list = []
        code_list = []
        fig_json_list = []
        query_id = None

        # Iterate through scratchpad to extract tool outputs
        for step in memory.scratchpad:
            result = step.result

            # Extract from MCP result if it's a dict
            if isinstance(result, dict):
                # SQL query
                sql = result.get("sql") or result.get("sql_query")
                if sql:
                    sql_queries.append(sql)

                # Base64 code
                base64_code = result.get("base64_code") or result.get("base64")
                if base64_code:
                    if isinstance(base64_code, list):
                        base64_code_list.extend(base64_code)
                    else:
                        base64_code_list.append(base64_code)

                # Code
                code = result.get("code")
                if code:
                    if isinstance(code, list):
                        code_list.extend(code)
                    else:
                        code_list.append(code)

                # Fig JSON
                fig_json = result.get("fig_json")
                if fig_json:
                    if isinstance(fig_json, list):
                        fig_json_list.extend(fig_json)
                    else:
                        fig_json_list.append(fig_json)

                # Query ID
                qid = result.get("query_id")
                if qid:
                    query_id = qid

        # Get query_id from sources if not found
        if not query_id and memory.sources:
            query_id = memory.sources[-1].id

        # Combine SQL queries
        combined_sql = ','.join(sql_queries) if sql_queries else None

        print(colored(f"\n📊 Extracted Results:", "cyan"))
        print(colored(f"   SQL: {combined_sql}", "cyan"))
        print(colored(f"   Plots: {len(fig_json_list)}", "cyan"))
        print(colored(f"   Follow-ups: {len(grounded_answer.follow_ups)}", "cyan"))
        print(colored(f"   Query ID: {query_id}", "cyan"))

        # Return in format compatible with ChatEngine
        return (
            grounded_answer.answer,
            combined_sql,
            base64_code_list,
            code_list,
            fig_json_list,
            grounded_answer.follow_ups,
            query_id
        )

    except Exception as e:
        print(colored(f"\n❌ Orchestrator error: {e}", "red", attrs=["bold"]))
        import traceback
        traceback.print_exc()

        return (
            f"Error in orchestrator: {str(e)}",
            None,
            [],
            [],
            [],
            [],
            None
        )
