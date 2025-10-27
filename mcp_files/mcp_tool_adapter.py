"""
MCP Tool Adapter - Makes ToolHandler progressively stateless
Wraps existing ToolHandler to work with MCP protocol
Eventually, individual tools can be migrated to separate MCP servers (sidecars)
"""
import json
from typing import Any, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass

from mcp_files.mcp_protocol import (
    ToolCallRequest,
    ToolCallResponse,
    create_text_content,
)


@dataclass
class ToolContext:
    """
    Request-scoped context for tool execution
    Replaces instance variables in ToolHandler
    """
    user_id: str
    user_group: str
    logger_timestamp: str
    cache_client: Any
    sql_list: List[str] = None
    sanitized_code_list: List[str] = None
    fig_json_list: List[Any] = None
    base64_code_list: List[bytes] = None

    def __post_init__(self):
        if self.sql_list is None:
            self.sql_list = []
        if self.sanitized_code_list is None:
            self.sanitized_code_list = []
        if self.fig_json_list is None:
            self.fig_json_list = []
        if self.base64_code_list is None:
            self.base64_code_list = []


class StatelessToolAdapter:
    """
    Adapter that makes ToolHandler progressively stateless
    Uses request-scoped context instead of instance state
    """

    def __init__(self, tool_handler_class: type):
        """
        Args:
            tool_handler_class: The ToolHandler class (not instance)
        """
        self.tool_handler_class = tool_handler_class

    async def execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        context: ToolContext,
    ) -> Dict[str, Any]:
        """
        Execute a tool in a stateless manner
        Creates a temporary ToolHandler instance per request
        """

        # Create temporary handler with context
        handler = self.tool_handler_class(
            cache_client=context.cache_client,
            user_id=context.user_id,
            logger_timestamp=context.logger_timestamp,
            user_group=context.user_group,
        )

        # Build tool_call structure
        tool_call = {
            "function": {
                "name": tool_name,
                "arguments": arguments
            }
        }

        # Extract context parameters
        sub_question = arguments.get("question")
        sub_question_list = arguments.get("sub_question_list")
        custom_instructions = arguments.get("custom_instructions")

        # Execute
        sql, base64_list, code_list, tool_types_used, report_content, fig_json_list, query_id = \
            await handler.handle_tool_call(
                tool_call=tool_call,
                report_content=None,
                summary_data=[],
                user_text=arguments,
                tool_types_used=set(),
                tool_id="mcp",
                fig_json=None,
                sub_question=sub_question,
                sub_question_list=sub_question_list,
                custom_instructions=custom_instructions,
                context_msg=None,
                query_id=None,
            )

        # Store results in context (for potential chaining)
        if sql:
            context.sql_list.append(sql)
        if code_list:
            context.sanitized_code_list.extend(code_list)
        if fig_json_list:
            context.fig_json_list.extend(fig_json_list)
        if base64_list:
            context.base64_code_list.extend(base64_list)

        # Build result
        result = {
            "ok": True,
            "tool": tool_name,
            "sql": sql,
            "code": code_list,
            "base64": [
                b.decode("utf-8") if hasattr(b, "decode") else b
                for b in base64_list
            ],
            "fig_json": fig_json_list,
            "report": (
                report_content.choices[0].message.content
                if getattr(report_content, "choices", None)
                else report_content
            ),
            "query_id": query_id,
            "tool_types_used": list(tool_types_used),
        }

        return result


class MCPToolRegistry:
    """
    Registry for mapping MCP tools to handlers
    Supports both in-process and sidecar tools
    """

    def __init__(self):
        self._tools: Dict[str, str] = {}  # tool_name -> server_name
        self._adapters: Dict[str, StatelessToolAdapter] = {}  # server_name -> adapter

    def register_inprocess_tool(
        self,
        tool_name: str,
        server_name: str = "in-process",
        adapter: Optional[StatelessToolAdapter] = None
    ):
        """Register a tool that runs in-process"""
        self._tools[tool_name] = server_name
        if adapter and server_name not in self._adapters:
            self._adapters[server_name] = adapter

    def register_sidecar_tool(self, tool_name: str, server_name: str):
        """
        Register a tool that runs in a sidecar MCP server
        Future use: migrate heavy tools to separate processes
        """
        self._tools[tool_name] = server_name

    def get_server_for_tool(self, tool_name: str) -> Optional[str]:
        """Get the server that handles this tool"""
        return self._tools.get(tool_name)

    def get_adapter(self, server_name: str) -> Optional[StatelessToolAdapter]:
        """Get adapter for in-process server"""
        return self._adapters.get(server_name)

    def list_tools(self) -> List[str]:
        """List all registered tools"""
        return list(self._tools.keys())

    def list_servers(self) -> List[str]:
        """List all registered servers"""
        return list(set(self._tools.values()))


# ============================================================================
# Migration Guide
# ============================================================================

"""
MIGRATION GUIDE: Making tools progressively stateless

Current state (main.py, ToolHandler):
- ToolHandler stores state in instance variables (sql_list, code_list, etc.)
- Tools access global state (conv_his, get_metadata, etc.)
- Hard to isolate, test, or move to sidecars

Target state (progressive):
1. SHORT TERM: Use StatelessToolAdapter
   - Wraps existing ToolHandler
   - Creates per-request instances (stateless at request level)
   - No code changes to ToolHandler needed yet

2. MEDIUM TERM: Refactor individual tools
   - Move tools to accept ToolContext parameter
   - Remove instance state, use context instead
   - Example:

     # Before:
     async def handle_ask_database(self, tool_call, ...):
         self.sql_list.append(sql)  # Instance state!

     # After:
     async def handle_ask_database(tool_call, context: ToolContext, ...):
         context.sql_list.append(sql)  # Request state

3. LONG TERM: Migrate heavy tools to sidecars
   - Tools like gen_plotly_code, pdf_query can be separate MCP servers
   - Register via MCPRouter as stdio/HTTP sidecars
   - Benefits:
     * Isolation (crashes don't affect main server)
     * Scalability (distribute load)
     * Independent deployment

   Example sidecar registration:

   router = MCPRouter()

   # Heavy tool in subprocess
   plotly_transport = await TransportFactory.create_stdio(
       command="python",
       args=["mcp_files/tools/plotly_server.py"],
   )
   await router.register_server("plotly-sidecar", plotly_transport)

   # Router automatically discovers tools and routes requests

CURRENT IMPLEMENTATION:
- We use StatelessToolAdapter (step 1)
- ToolHandler unchanged
- Foundation for future migration
"""
