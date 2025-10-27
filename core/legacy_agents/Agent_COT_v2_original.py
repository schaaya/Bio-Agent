import json
import logging
import time
from typing import Any, Dict
import uuid
import hashlib

from cachetools import TTLCache
from termcolor import colored

from core.globals import add_tool, conv_his, functions_time_log, send_status_to_user
from core.logger import log_error
from core.metadata_manager import MetadataManager
from core.summarization import summary
# Using MCP protocol for ALL tool calls
from mcp_files.mcp_internal_client import get_internal_mcp_client
from utility.tools import _generate_cache_key

import json
import uuid
from typing import Dict, Any, List

from utility.decorators import time_it


class QueryProcessor:
    def __init__(
        self, 
        cache: Any, 
        tools: Dict[str, Any], 
        llm_generate_response: Any,
        user_id: str = None, 
        logger_timestamp: str = None, 
        user_group: str = None, 
        message: List[Dict[str, str]] = None
        
    ):
        """
        Initializes an instance of the MultiToolAgentWithLLM class.
        """
        self.cache = cache
        self.tools = tools 
        self.llm_generate_response = llm_generate_response
        
        self.scratchpad = []
        self.base64_code_list = []
        self.code_list = []
        self.fig_json_list = []
        self.sub_question_list = []
        
        self.user_id = user_id
        self.logger_timestamp = logger_timestamp
        self.user_group = user_group
        self.message = message

        self.sql = None
        self.base64_code = None
        self.code = None

        # Get MCP internal client - ALL tool calls go through MCP protocol
        # This ensures consistent behavior: retries, timeouts, cancellation, metrics
        self.mcp_client = get_internal_mcp_client()

        self.tool_names = [tool["function"]["name"] for tool in self.tools]
        self.tool_descriptions = [tool["function"]["description"] for tool in self.tools]

        self.tools_str = "\n".join(
            f"   - {name}: {desc}"
            for name, desc in zip(self.tool_names, self.tool_descriptions)
        )

    async def ensure_mcp_initialized(self):
        """Ensure MCP client is initialized"""
        if not self.mcp_client._initialized:
            await self.mcp_client.initialize()

    async def cleanup(self):
        """Cleanup resources (MCP client persists as singleton)"""
        # MCP client is a singleton, don't close it here
        # It will be closed on app shutdown
        pass

    @time_it
    def prompt_generator(self, input_query: str, selected_tools: any = None):
        """
        A generator function that yields the next prompt to be sent to the language model.
        """
        base_prompt = [
            {
                "role": "system",
                "content": (
                "You are an advanced AI system that determines whether to break down complex queries into sub-questions "
                "or handle them with a single tool call. Your goal is to optimize efficiency by minimizing the number of steps.\n\n"
                "## Conditions\n"
                "- **Complexity Assessment**: First, assess if the query can be fully resolved with a single tool call. If yes, do NOT split it.\n For example: queries requiring data for distinct metrics should be split.\n"
                "- **Selected Tools Priority**: If the user provides selected tools, use them in the most efficient way (even if that means 1 step).\n"
                "- **Decomposition Only When Needed**: Split into sub-questions ONLY if:\n"
                "   a) The query inherently requires multiple distinct actions/tools, OR\n"
                "   b) A single tool cannot fully address the query.\n\n"
                f"## Available Tools\n{self.tools_str}\n\n"
                "## Task\n"
                "1. Decide if the query needs decomposition or can be handled in one step.\n"
                "2. If one step is sufficient:\n"
                "   - Set 'ExecutionPlan' to a single step with the best tool and its input.\n"
                "3. If decomposition is needed:\n"
                "   - Break the query into sub-questions requiring different tools/actions.\n\n"
                "### Examples\n"
                "**Single-Step Example**:\n"
                "User Query: 'What is the weather in Paris?'\n"
                "ExecutionPlan: [{'sub-question': 'Get Paris weather', 'action_input': <action_input>, 'tool': 'get_weather_data'}]\n\n"
                "**Multi-Step Example**:\n"
                "User Query: 'plot me a graph for all facilities along with their names and capacities'\n"
                "ExecutionPlan: [\n"
                "   {'sub-question': 'Fetch all facilities along with their names and capacities', 'action_input': <action_input>, 'tool': 'ask_database'},\n"
                "   {'sub-question': 'Plot all facilities along with their names and capacities ', 'action_input': <action_input> , 'tool': 'gen_plotly_code'},\n"
                "]\n\n"
                "### Response Format\n"
                "Respond with a strictly valid JSON object containing 'ExecutionPlan'. Use ONE step if possible.\n"
                    
                )
            },
            {
                "role": "user",
                "content": f"User Input : {input_query}\n User selected tools: {selected_tools}\n"
            }
        ]
        
        if self.message:
            base_prompt.extend(self.message)
        
        return base_prompt
    
    @time_it
    async def answer_query(self, input_query: str, selected_tools: any = None, custom_instructions: str = None):
        """
        Answers the user's query by breaking it down into sub-questions, identifying the tools required, 
        and generating a sequential execution plan.
        """
        observation = sql = base64_code = code = fig_json = report_content = parsed_questions = query_id = None
        base64_code_list = []
        code_list = []
        fig_json_list = []
        query_ids = []  # Store all query_ids
        
        await send_status_to_user(self.user_id, status="Pipeline intiated...")
        prompt_generator = self.prompt_generator(input_query, selected_tools)
        response = await self.llm_generate_response(prompt_generator, self.user_id, response_format=True)
        
        parsed_response = response.choices[0].message.content
        
        try:
            execution_plan = json.loads(parsed_response)
            formatted_plan = json.dumps(execution_plan, indent=4)
            print("Execution Plan from LLM:\n", formatted_plan)
            
            if isinstance(execution_plan, dict) and "ExecutionPlan" in execution_plan:
                steps = execution_plan["ExecutionPlan"]
                
                if not all(
                    "sub-question" in step and "action_input" in step and "tool" in step 
                    for step in steps
                ):
                    raise ValueError("Invalid step format in ExecutionPlan.")
            
                for step in steps:
                    sub_question = step["sub-question"]
                    action_input = step["action_input"]
                    # Parse action_input if it's a JSON string
                    if isinstance(action_input, str):
                        try:
                            action_input = json.loads(action_input)
                        except json.JSONDecodeError:
                            pass  # Keep as string if not valid JSON
                    tool = step["tool"]

                    self.scratchpad.append((sub_question, ""))

                    if tool == "get_weather_data":
                        observation, sql, base64_code, code, fig_json, report_content, current_query_id = await self.call_tool(
                            tool, action_input
                        )

                    elif tool == "comparative_analyzer":
                        observation, sql, base64_code, code, fig_json, report_content, current_query_id = await self.call_tool(
                            tool, action_input, custom_instructions=custom_instructions
                        )
                    elif tool == "gen_plotly_code":
                        if len(self.sub_question_list) > 0:
                            observation, sql, base64_code, code, fig_json, _, current_query_id = await self.call_tool(
                                tool, action_input, sub_question_list=self.sub_question_list
                            )
                        else:
                            observation, sql, base64_code, code, fig_json, _, current_query_id = await self.call_tool(
                                tool, action_input, sub_question=sub_question
                            )
                    elif tool == "ask_database":
                        self.sub_question_list.append(sub_question)
                        observation, sql, base64_code, code, fig_json, _, current_query_id = await self.call_tool(
                            tool, action_input, sub_question=sub_question
                        )
                    else:
                        observation, sql, base64_code, code, fig_json, _, current_query_id = await self.call_tool(
                            tool, sub_question
                        )

                    # Update scratchpad with observation
                    if observation:
                        self.scratchpad[-1] = (sub_question, observation)

                    # Accumulate results from each tool call
                    if base64_code:
                        if isinstance(base64_code, list):
                            self.base64_code_list.extend(base64_code)
                        else:
                            self.base64_code_list.append(base64_code)

                    if code:
                        if isinstance(code, list):
                            self.code_list.extend(code)
                        else:
                            self.code_list.append(code)

                    if fig_json:
                        if isinstance(fig_json, list):
                            self.fig_json_list.extend(fig_json)
                        else:
                            self.fig_json_list.append(fig_json)

                    # If we got a valid query_id, add it to our list
                    if current_query_id is not None:
                        query_ids.append(current_query_id)
                
                parsed_questions = await self.recommend_followup_questions(input_query, execution_plan)
                
            else:
                raise ValueError("Invalid response format: missing 'ExecutionPlan' key.")
            
            # Return the most recent query_id if available, or None
            final_query_id = query_ids[-1] if query_ids else None
            
            return (
                self.get_scratchpad_log(),
                sql,
                self.base64_code_list,
                self.code_list,
                self.fig_json_list,
                report_content,
                parsed_questions,
                final_query_id
            )
            
        except json.JSONDecodeError as e:
            error_msg = f"JSON parsing failed: {str(e)}"
            await log_error(self.user_id, str(e), "Error at answer_query(Agent_COT_v2)")
            print(error_msg)
            return (
                f"Error: {error_msg}",
                None,
                [],
                [],
                [],
                None,
                {"followup_questions": []},
                None
            )

        except (ValueError, KeyError) as e:
            error_msg = f"Execution plan error: {str(e)}"
            await log_error(self.user_id, str(e), "Error at answer_query(Agent_COT_v2)")
            print(error_msg)
            return (
                f"Error: {error_msg}",
                None,
                [],
                [],
                [],
                None,
                {"followup_questions": []},
                None
            )

        except Exception as e:
            error_msg = f"An unexpected error occurred: {str(e)}"
            await log_error(self.user_id, str(e), "Error at answer_query(Agent_COT_v2)")
            print(error_msg)
            return (
                f"Error: {error_msg}",
                None,
                [],
                [],
                [],
                None,
                {"followup_questions": []},
                None
            )
    
    @time_it
    async def call_tool(
        self,
        tool_name: str,
        input_data: Any = None,
        sub_question: str = None,
        sub_question_list: List[str] = None,
        custom_instructions: str = None
    ):
        """
        Call tools via MCP protocol (HTTP to localhost:8000/mcp).

        ALL tool calls now go through the MCP layer, ensuring:
        - Consistent retry logic
        - Timeout management
        - Cancellation support
        - Request-ID tracking
        - Metrics collection
        - Structured error handling

        Returns: (observation, sql, base64_code_list, code_list, fig_json_list, report_content, query_id)
        """
        try:
            # Ensure MCP client is initialized
            await self.ensure_mcp_initialized()

            # Build arguments based on tool type
            arguments = {}

            if not isinstance(input_data, dict):
                input_data = {}

            # Build tool-specific arguments
            if tool_name == "get_weather_data":
                arguments = {"location": input_data.get("location")}

            elif tool_name == "ask_database":
                arguments = {
                    "tag": input_data.get("tag"),
                    "question": sub_question,
                    "meta": input_data.get("meta")
                }

            elif tool_name == "gen_plotly_code":
                arguments = {
                    "question": input_data.get("question") or sub_question,
                    "tags": input_data.get("tags", []),
                    "modify": bool(input_data.get("modify", False)),
                    "sub_question_list": sub_question_list
                }

            elif tool_name == "csv_query":
                arguments = {"query": input_data.get("query") or sub_question}

            elif tool_name == "pdf_query":
                arguments = {"query": input_data.get("query") or sub_question}

            elif tool_name == "comparative_analyzer":
                arguments = {
                    "question": input_data.get("question") or sub_question,
                    "data": input_data.get("data"),
                    "custom_instructions": custom_instructions
                }

            else:
                # Pass through for unknown tools
                arguments = input_data

            # Call tool via MCP protocol
            print(colored(f"[MCP] Calling tool: {tool_name} via MCP protocol", "cyan"))
            payload = await self.mcp_client.call_tool(
                tool_name=tool_name,
                arguments=arguments,
                user_id=self.user_id,
                user_group=self.user_group,
                logger_timestamp=self.logger_timestamp
            )

            # Check for error
            if not payload.get("ok", False):
                error_msg = payload.get("error", "Tool call failed")
                print(colored(f"[MCP ERROR] {error_msg}", "red"))
                await log_error(self.user_id, error_msg, f"mcp.call_tool.{tool_name}")
                return (
                    f"Error: {error_msg}",
                    None,
                    [],
                    [],
                    [],
                    None,
                    None
                )

            # Extract results from MCP payload
            sql = payload.get("sql")
            base64_list = payload.get("base64", [])
            code_list = payload.get("code", [])
            fig_json_list = payload.get("fig_json", [])
            report = payload.get("report")
            query_id = payload.get("query_id")

            # Build observation
            observation = report if report else f"Tool {tool_name} completed successfully"

            print(colored(f"[MCP] Tool {tool_name} completed successfully", "green"))

            return (
                observation,
                sql,
                base64_list,
                code_list,
                fig_json_list,
                report,
                query_id
            )

        except Exception as e:
            import traceback
            error_msg = f"Failed to call tool {tool_name} via MCP: {e}"
            print(colored(f"[MCP ERROR] {error_msg}", "red"))
            print(colored(f"[TRACEBACK] {traceback.format_exc()}", "red"))
            await log_error(self.user_id, error_msg, "call_tool.mcp.exception")

            return (
                f"Error: {error_msg}",
                None,
                [],
                [],
                [],
                None,
                None
            )

    
    @time_it
    def get_scratchpad_log(self) -> str:
        """
        Returns a formatted log of all thoughts, actions, and observations stored in the scratchpad.
        """
        log = ""
        for thought, observation in self.scratchpad:
            log += f"{thought}\n"
            if observation:
                log += f"{observation}\n"
            log += "\n"
        return log
            
    async def recommend_followup_questions(
        self,
        user_query: str,
        execution_plan: dict
    ) -> dict:
        """
        Uses the LLM to analyze the original user query and the resulting execution plan,
        then proposes additional or clarifying follow-up questions.

        :param user_query: The original user query.
        :return: A dictionary with the LLM's suggested questions, e.g.:
          {
            "followup_questions": ["...","..."]
          }
        """
        available_tool_names = [tool["function"]["name"] for tool in self.tools]
        available_tool_descriptions = [
            tool["function"]["description"] for tool in self.tools
        ]
        prompt = [
            {
                "role": "system",
                "content": (
                    "You are an AI assistant that suggests concise, user-style follow-up queries.\n"

                    "### Output Format\n"
                    "Provide a JSON with a structure like:\n"
                    "{\n"
                    "  'followup_questions': [\n"
                    "    { 'question': 'question1', 'tool': 'tool1' },\n"
                    "    { 'question': 'question2', 'tool': 'tool2' }\n"
                    "  ]\n"
                    "}\n\n"
                    
                )
            },
            {
                "role": "user",
                "content": (
                    f"User query:\n{user_query}\n\n"
                    f"Observation logs:\n{self.get_scratchpad_log()}\n\n"
                    f"Tools available:\n"
                    + "\n".join(
                        f"   - {name}: {desc}"
                        for name, desc in zip(available_tool_names, available_tool_descriptions)
                    ) + "\n\n"
                    
                    "Generate 3 possible next questions a user might ask."
                )
            }
        ]

        response = await self.llm_generate_response(
            prompt, 
            self.user_id, 
            response_format=True
        )
        
        llm_content = response.choices[0].message.content.strip()
        
        
        try:
            parsed_questions = json.loads(llm_content)
            
            if "followup_questions" in parsed_questions:
                return parsed_questions["followup_questions"]
            else:
                raise ValueError("Expected 'followup_questions' key in the LLM response.")
        
        except Exception as e:
            error_msg = f"Error generating follow-up questions: {str(e)}"
            await log_error(self.user_id, str(e), "Error at recommend_followup_questions(Agent_COT_v2)")
            print(error_msg)
            return {"followup_questions": []}

