import json
import time
import uuid
import asyncio
from cachetools import TTLCache
from termcolor import colored
from datetime import datetime
from dotenv import load_dotenv
from core.Agent_COT_v2_pydantic import COT_Agent_Pydantic
from core.metadata_manager import MetadataManager
from utility.function_dicts import tools
from core.summarization import summary
from core.logger import chat_logs, log_error, file_logs, code_logs
from core.globals import (
    add_conversation_id, 
    clear_tool, 
    session_data,
    send_status_to_user, 
    conv_his, 
    session_data, 
    functions_time_log, 
    api_time_log
)
from utility.tools import _generate_cache_key, chat_completion_request
from schemas.db_models import Base as StorageBase, StorageSessionLocal as SessionLocal
from utility.decorators import time_it
import keyring

load_dotenv()

# Increase cache size and TTL for better performance
cache_client = TTLCache(maxsize=5000, ttl=7200)

from core.globals import db_description

# Pre-build tool descriptions once instead of repeatedly
_TOOL_DESCRIPTIONS_CACHE = {}

def get_tool_descriptions(tools):
    """Cache tool descriptions to avoid rebuilding strings repeatedly"""
    cache_key = hash(tuple(sorted([tool["function"]["name"] for tool in tools])))
    
    if cache_key not in _TOOL_DESCRIPTIONS_CACHE:
        tool_names = [tool["function"]["name"] for tool in tools]
        tool_descriptions = [tool["function"]["description"] for tool in tools]
        tool_str = "\n".join(f"- **{name}**: {desc}" for name, desc in zip(tool_names, tool_descriptions))
        _TOOL_DESCRIPTIONS_CACHE[cache_key] = tool_str
        
    return _TOOL_DESCRIPTIONS_CACHE[cache_key]

async def is_tool_required(user_id: str, user_text: str, tools, context_message) -> bool:
    """
    Uses an LLM to determine if a user's question requires a tool call.
    Returns True if a tool is needed, False otherwise.
    
    Optimized to use a simpler prompt and fewer tokens.
    """
    # No caching of decisions as they might be incorrect
    tool_str = get_tool_descriptions(tools)
    db_descrip = db_description()
    
    # Simplified prompt using fewer tokens
    messages = [
        {
            "role": "system",
            "content": (
                "Determine if the user question requires using tools (database, plotting, analysis, etc.) or can be answered directly.\n"
                f"Available Tools:\n {tool_str}\n"
                f"Database Info:\n{db_descrip}\n\n"
                "IMPORTANT: Requests for plotting, visualization, graphs, or modifying plots REQUIRE tools (answer 'yes').\n"
                "Questions ABOUT previous plots/visualizations also REQUIRE tools (answer 'yes') to access the actual data.\n"
                "Examples that REQUIRE tools:\n"
                "- 'Plot a graph for above data' → yes\n"
                "- 'Visualize the results' → yes\n"
                "- 'Create a chart' → yes\n"
                "- 'Modify the plot' → yes\n"
                "- 'Show me EGFR expression' → yes (database query)\n"
                "- 'Is this a box plot?' → yes (needs to check actual visualization)\n"
                "- 'What type of plot is this?' → yes (needs to check actual visualization)\n"
                "- 'Analyze the plot' → yes (needs to access plot data)\n\n"
                "Examples that DON'T require tools:\n"
                "- 'What is EGFR?' → no (general knowledge)\n"
                "- 'Thank you' → no (conversation)\n"
                "- 'What is a box plot?' → no (general knowledge about plot types)\n\n"
                "Return ONLY a JSON object with format {\"Required\": \"yes\"} or {\"Required\": \"no\"}"
            ),
        },
        {
            "role": "user",
            "content": f"Question: {user_text}\nContext: {context_message}"
        }
    ]

    try:
        # Use a smaller, faster model for this binary decision
        response = await chat_completion_request(
            user_id, 
            messages, 
            model="gpt-35-turbo-16k", 
            max_tokens=20,  # Reduced from 30
            temperature=0.0
        )
        content = response.choices[0].message.content.strip()
        
        # More robust JSON parsing with fallbacks
        try:
            response_dict = json.loads(content)
            result = response_dict.get("Required", "yes").lower() == "yes"
        except json.JSONDecodeError:
            # Fallback for non-JSON responses
            result = "no" not in content.lower()
            
        return result
    except Exception as e:
        await log_error(user_id, str(e), "Error in is_tool_required")
        return True


@time_it
async def analyze_user_input(user_text: str, user_id: str, logger_timestamp_mod: str, user_group: str, context_msg: str, selected_tool: any) -> tuple:
    """
    Asynchronously analyzes user input and processes it through various tools and summarization.
    
    Returns:
        A tuple containing:
          ( final_answer, sql, base64_code_list, code_list, fig_json_list, parsed_questions )

    In case of error, it returns:
          ( "We encountered an error...", None, [], [], [], None )
    """
    await send_status_to_user(user_id, status="Analyzing your input...")
    db = None
    try:
        # Initialize result variables
        final_answer = None
        sql = None
        base64_code_list = []
        code_list = []
        fig_json_list = []
        parsed_questions = None
        user_email = user_id.split("_")[0]
        query_id = None

        # Generate conversation ID and cache key once
        conversation_id = uuid.uuid4().hex
        cache_key = _generate_cache_key(conversation_id, user_id)
        keyring.set_password("chatengine", user_email, cache_key)
        
        # Minimize message content
        message = [
            {"role": "user", "content": f"Conversation history: {context_msg}"},
            {"role": "user", "content": f"User Question: {user_text}"}
        ]

        # Get tools only once
        greetings_tools = tools(user_id=user_id, logger_timestamp=logger_timestamp_mod)

        # Determine if tool is required - skip this check if a tool is already selected
        check_required = True if selected_tool else await is_tool_required(user_id, user_text, greetings_tools, message)
        
        if not check_required:
            # Handle the case where no tool is required - use a simpler, direct approach
            # Format conversation history with metadata for better context
            history_lines = []
            recent_plot_info = None

            for msg in context_msg[-6:]:  # Last 6 messages
                role = msg.get('role', 'unknown')
                content = msg.get('content', '')[:200]  # Limit content length
                metadata = msg.get('metadata', {})

                # Track most recent plot
                if metadata.get('has_plot'):
                    recent_plot_info = {
                        'plot_count': metadata.get('plot_count', 0),
                        'query_id': metadata.get('query_id'),
                        'timestamp': metadata.get('timestamp')
                    }

                # Format message with metadata indicators
                meta_str = ""
                if metadata.get('has_plot'):
                    meta_str = f" [PLOT: {metadata.get('plot_count')} visualization(s)]"
                elif metadata.get('has_sql'):
                    meta_str = " [SQL Query Result]"

                history_lines.append(f"{role}: {content}{meta_str}")

            history_context = "\n".join(history_lines)

            # Add recent plot context if available
            plot_context = ""
            if recent_plot_info:
                plot_context = (
                    f"\n\n**IMPORTANT**: A visualization was recently shown with {recent_plot_info['plot_count']} plot(s). "
                    f"Query ID: {recent_plot_info['query_id']}. "
                    "If user is asking about 'this plot' or 'the plot', they are referring to this recent visualization."
                )

            check_message = [
                {
                    "role": "system",
                    "content": (
                        "Answer the user query directly based on the conversation history provided.\n"
                        "If the user is asking about a previous visualization/plot/chart/graph:\n"
                        "- Check the conversation history for messages marked with [PLOT: X visualization(s)]\n"
                        "- If a plot was recently shown, you can reference it in your answer\n"
                        "- If asking 'is this a box plot?', check:\n"
                        "  * Was 'box plot' mentioned in the query?\n"
                        "  * Does the data description mention raw values vs aggregates?\n"
                        "  * Aggregated data (mean, median only) → NOT a proper box plot\n"
                        "  * Raw individual values → CAN be a box plot\n\n"
                        "If you lack sufficient information, suggest using relevant tools.\n"
                        "Respond in JSON: {\"Response\": \"<answer>\"}"
                    )
                },
                {
                    "role": "user",
                    "content": f"Conversation History:\n{history_context}{plot_context}\n\nCurrent Question: {user_text}"
                }
            ]
            
            try:
                # Use a faster model for direct responses
                response = await chat_completion_request(
                    user_id, 
                    check_message, 
                    model="gpt-4o-mini", 
                    max_tokens=400
                )
                
                # More robust JSON parsing with fallback
                content = response.choices[0].message.content
                try:
                    response_dict = json.loads(content)
                    response_value = response_dict.get("Response", "No response found")
                except json.JSONDecodeError:
                    # If JSON parsing fails, use the raw response
                    await log_error(user_id, f"JSON parse warning (direct): using raw response", "analyze_user_input")
                    response_value = content
                
                # Ensure response is string
                if not isinstance(response_value, str):
                    response_value = str(response_value)
                
                # Update conversation history (direct answer path)
                data = {
                    'role': 'assistant',
                    'content': f"Final Answer: {response_value}",
                    'metadata': {
                        'has_plot': False,
                        'plot_count': 0,
                        'has_sql': False,
                        'direct_answer': True
                    }
                }
                conv_his(user_id, data)

                return response_value, None, [], [], [], None, None, []  # NEW: Add empty reasoning_steps

            except Exception as e:
                print(colored(f"Error answering trivially: {e}", "red"))
                await log_error(user_id, str(e), "Error answering trivially in analyze_user_input")
                return "We encountered an error. Please try again or contact support.", None, [], [], [], None, None, []  # NEW: Add empty reasoning_steps

        # LLM wrapper without caching responses as they can sometimes be incorrect
        @time_it
        def llm_generate_response_wrapper(messages, user_id, tools=None, model="gpt-4o", response_format=None, stop=None):
            # Direct call without caching actual responses
            return chat_completion_request(
                user_id, messages, model=model, tools=tools, 
                response_format=response_format, stop=stop
            )
    
        # Open DB connection only when needed
        db = SessionLocal()

        # Process the query with Pydantic AI Agent
        start = time.time()
        results, sql, base64_code_list, code_list, fig_json_list, report_content, parsed_questions, query_id, reasoning_steps = \
            await COT_Agent_Pydantic(
                user_query=user_text,
                user_id=user_id,
                user_group=user_group,
                logger_timestamp=logger_timestamp_mod,
                cache=cache_client,
                tools=greetings_tools,
                llm_generate_response=llm_generate_response_wrapper,
                selected_tools=selected_tool,
                custom_instructions=None,
                message=message
            )
        end = time.time()
        functions_time_log.append(f"COT total time: {round(end - start, 2)} seconds")

        # Generate final answer
        start = time.time()
        if report_content:
            if isinstance(report_content, dict):
                final_answer = report_content.get("Report", "No report found")
            elif isinstance(report_content, str):
                try:
                    report_dict = json.loads(report_content)
                    final_answer = report_dict.get("Report", report_content)
                except json.JSONDecodeError:
                    final_answer = report_content
        else:
            # Only summarize when needed
            final_answer = await summary.summarize_results_v2(
                user_id, results, user_text, sql, base64_code_list, fig_json_list=fig_json_list
            )
        end = time.time()
        functions_time_log.append(f"FinalSummarization total time: {round(end - start, 2)} seconds")

        # Update conversation ID
        add_conversation_id(cache_key)

        # Optimize base64 decoding - only decode when needed
        cache_data = {
            "final_answer": final_answer,
            "sql": sql,
            "base64_code": base64_code_list,  # Store raw to avoid encode/decode cycle
            "code": code_list,
            "fig_json": fig_json_list,
            "input": user_text,
            "query_id": query_id  # Store query_id for CSV file retrieval
        }
        cache_client[cache_key] = json.dumps(cache_data)

        # Update conversation history with rich metadata
        data = {
            'role': 'assistant',
            'content': f"Final Answer: {final_answer}",
            'metadata': {
                'has_plot': bool(fig_json_list),
                'plot_count': len(fig_json_list) if fig_json_list else 0,
                'has_sql': bool(sql),
                'query_id': query_id,
                'plot_code': code_list if code_list else None,
                'timestamp': logger_timestamp_mod
            }
        }
        conv_his(user_id, data)

        # Clear tool selection
        clear_tool()

        return final_answer, sql, base64_code_list, code_list, fig_json_list, parsed_questions, query_id, reasoning_steps

    except Exception as e:
        print(colored(f"Error in analyze_user_input: {e}", "red"))
        await log_error(user_id, str(e), "Error at analyze_user_input")
        return (
            "We encountered an internal error. Please try again later.",
            None, [], [], [], None, None, []  # NEW: Add empty reasoning_steps
        )
    
    finally:
        # Close DB connection if it was opened
        if 'db' in locals() and db:
            db.close()
        # Note: MCP client cleanup is handled automatically by the MCP infrastructure


@time_it
async def process_user_input(data, user_id, user_group):
    """
    Processes the user's input by analyzing it and generating a response.
    Optimized for better error handling and fewer retries when appropriate.
    
    Returns:
        (output, base64_code (or None), is_image (bool), sql, logger_timestamp_mod, code_list, fig_json_list, parsed_questions)
        
    In case of repeated errors, returns:
        ("Ran into an error. Please try again.", None, False, None, None, None, None, None)
    """
    
    # Clear previous logs
    functions_time_log.clear()
    api_time_log.clear()
    
    start = time.time()
    logger_timestamp = datetime.now().isoformat(' ', 'seconds')
    logger_timestamp_mod = logger_timestamp.replace("-", "_").replace(":", "_").replace(" ", "_")
    
    # Reduce retry count for faster failures
    max_attempts = 2  # Changed from 3 to 2
    user_text = data.get("message", "")
    selected_tool = data.get("tool", None)
    
    # Initialize variables
    output = None
    sql = None
    base64_code_list = []
    code_list = []
    fig_json_list = []
    parsed_questions = None
    query_id = None
    
    # Update conversation history
    in_msg = {"role": "user", "content": user_text}
    conv_his(user_id, in_msg)
    
    # Get context efficiently - limit to most recent messages
    context_msg = session_data[user_id][-6:]
    
    # Simplified message payload
    message_payload = {
        "User_Question": user_text
    }
    user_str = json.dumps(message_payload)

    for attempt in range(max_attempts):
        print(colored(f"ChatEngine Attempt: {attempt + 1}/{max_attempts}", "yellow"))
        
        try:
            # Process user input
            model = "deployment"
            output, sql, base64_code_list, code_list, fig_json_list, parsed_questions, query_id, reasoning_steps = \
                await analyze_user_input(
                    user_str,
                    user_id,
                    logger_timestamp_mod, 
                    user_group, 
                    context_msg, 
                    selected_tool
                )
            
            # Log the interaction
            chat_logs(user_text, output, sql, logger_timestamp, model, user_id)

            # Calculate timing stats
            end = time.time()
            print(f"Total Time: {round(end - start, 2)} seconds")
            for i in functions_time_log:
                print(colored(i, "cyan"))
            print(colored(f"Total OpenAI API calls: {round(sum(api_time_log), 2)} seconds", "magenta"))

            # Process output
            if output is not None:
                is_image = bool(fig_json_list)
                return (
                    output,
                    base64_code_list if is_image else None,
                    is_image,
                    sql,
                    logger_timestamp_mod,
                    code_list,
                    fig_json_list if is_image else None,
                    parsed_questions,
                    query_id,
                    reasoning_steps  # NEW: Add reasoning steps
                )
            
        except Exception as e:
            await log_error(user_id, str(e), "Error in process_user_input loop")
            await send_status_to_user(user_id, status="An internal error occurred. Retrying...")
            print(colored(f"Error at process_user_query: {e}", "red"))
            
            # Only retry for certain types of errors
            if "Rate limit" in str(e) or "timeout" in str(e).lower():
                # Add exponential backoff between retries
                if attempt < max_attempts - 1:
                    backoff_time = 2 ** attempt  # 1s, 2s, 4s, etc.
                    await asyncio.sleep(backoff_time)
            else:
                # Don't retry for logical errors
                break

    return (
        "Ran into an error. Please try again.",
        None,
        False,
        None,
        None,
        None,
        None,
        None,
        None,
        []  # NEW: Add empty reasoning steps
    )