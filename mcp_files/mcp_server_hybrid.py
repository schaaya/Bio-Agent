"""
Hybrid In-Process MCP Server with Lazy Initialization
Mounts inside FastAPI, shares DB/WebSocket/global state
All traffic goes through MCP protocol
"""
import asyncio
import sys
import json
import logging
from typing import Any, Dict, List, Optional, Callable
from contextlib import asynccontextmanager

from mcp_files.mcp_protocol import (
    MCPRequest,
    MCPResponse,
    Tool,
    ToolParameter,
    ToolParameterProperty,
    ServerInfo,
    MCPCapability,
    InitializeRequest,
    InitializeResponse,
    ToolsListRequest,
    ToolsListResponse,
    ToolCallRequest,
    ToolCallResponse,
    MCPErrorCode,
    create_error_response,
    create_text_content,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Lazy Import Manager (fixes stdio startup hang)
# ============================================================================

class LazyImportManager:
    """
    Manages lazy imports to avoid module-level initialization
    Fixes stdio startup hang by deferring DB connections and heavy imports
    """

    def __init__(self):
        self._imports: Dict[str, Any] = {}
        self._initialized = False

    def ensure_imports(self):
        """Lazy import all dependencies when first needed"""
        if self._initialized:
            return

        logger.info("Performing lazy imports...")

        try:
            # Import logger first (lightweight)
            from core.logger import log_error
            self._imports['log_error'] = log_error

            # Import ToolHandler (may trigger DB connections)
            from core.tools_calls import ToolHandler
            self._imports['ToolHandler'] = ToolHandler

            # Import cache
            from cachetools import TTLCache
            self._imports['TTLCache'] = TTLCache

            self._initialized = True
            logger.info("Lazy imports completed successfully")

        except Exception as e:
            logger.error(f"Failed to perform lazy imports: {e}")
            raise

    def get(self, name: str) -> Any:
        """Get imported module/class"""
        self.ensure_imports()
        return self._imports.get(name)


# ============================================================================
# In-Process MCP Server
# ============================================================================

class InProcessMCPServer:
    """
    In-process MCP server that can be mounted in FastAPI
    Provides lazy initialization and access to shared state
    """

    def __init__(
        self,
        name: str = "bi-bot-mcp",
        version: str = "1.0.0",
        user_id: Optional[str] = None,
        user_group: Optional[str] = None,
        logger_timestamp: Optional[str] = None,
    ):
        self.name = name
        self.version = version
        self.user_id = user_id or "default@example.com"
        self.user_group = user_group or "default"
        self.logger_timestamp = logger_timestamp or "mcp"

        # Lazy initialization
        self._lazy_imports = LazyImportManager()
        self._tool_handler: Optional[Any] = None
        self._cache_client: Optional[Any] = None

        # Server state
        self._initialized = False
        self._server_info: Optional[ServerInfo] = None

        # Tool registry (defined eagerly, initialized lazily)
        self._tool_definitions = self._define_tools()

    def _define_tools(self) -> List[Tool]:
        """
        Define tool schemas (JSON Schema)
        This is done eagerly (no imports needed), actual execution is lazy
        """
        return [
            Tool(
                name="get_weather_data",
                description="Get weather data for a location",
                inputSchema=ToolParameter(
                    properties={
                        "location": ToolParameterProperty(
                            type="string",
                            description="Location to get weather for"
                        )
                    },
                    required=["location"]
                )
            ),
            Tool(
                name="ask_database",
                description="Query database with a tag and optional question",
                inputSchema=ToolParameter(
                    properties={
                        "tag": ToolParameterProperty(
                            type="string",
                            description="Database tag (e.g., 'facilities_df')"
                        ),
                        "question": ToolParameterProperty(
                            type="string",
                            description="Natural language question"
                        ),
                        "meta": ToolParameterProperty(
                            type="object",
                            description="Optional metadata"
                        )
                    },
                    required=["tag"]
                )
            ),
            Tool(
                name="gen_plotly_code",
                description="Generate Plotly visualization code",
                inputSchema=ToolParameter(
                    properties={
                        "question": ToolParameterProperty(
                            type="string",
                            description="Visualization question"
                        ),
                        "tags": ToolParameterProperty(
                            type="array",
                            description="CSV file tags to use",
                            items={"type": "string"}
                        ),
                        "modify": ToolParameterProperty(
                            type="boolean",
                            description="Whether to modify existing code",
                            default=False
                        ),
                        "sub_question_list": ToolParameterProperty(
                            type="array",
                            description="List of sub-questions",
                            items={"type": "string"}
                        )
                    },
                    required=["question", "tags", "modify"]
                )
            ),
            Tool(
                name="csv_query",
                description="Query CSV data",
                inputSchema=ToolParameter(
                    properties={
                        "query": ToolParameterProperty(
                            type="string",
                            description="Natural language query"
                        )
                    },
                    required=["query"]
                )
            ),
            Tool(
                name="pdf_query",
                description="Query PDF documents",
                inputSchema=ToolParameter(
                    properties={
                        "query": ToolParameterProperty(
                            type="string",
                            description="Natural language query"
                        )
                    },
                    required=["query"]
                )
            ),
            Tool(
                name="comparative_analyzer",
                description="Analyze and compare data from multiple sources",
                inputSchema=ToolParameter(
                    properties={
                        "question": ToolParameterProperty(
                            type="string",
                            description="Analysis question"
                        ),
                        "data": ToolParameterProperty(
                            type="object",
                            description="Optional additional data"
                        ),
                        "custom_instructions": ToolParameterProperty(
                            type="string",
                            description="Custom analysis instructions"
                        )
                    },
                    required=["question"]
                )
            ),
        ]

    async def _ensure_initialized(self):
        """Ensure ToolHandler is initialized (lazy)"""
        if self._tool_handler is not None:
            return

        logger.info("Initializing ToolHandler (lazy)...")

        # Trigger lazy imports
        self._lazy_imports.ensure_imports()

        # Get imported classes
        ToolHandler = self._lazy_imports.get('ToolHandler')
        TTLCache = self._lazy_imports.get('TTLCache')

        # Create cache and handler
        self._cache_client = TTLCache(maxsize=5000, ttl=7200)
        self._tool_handler = ToolHandler(
            cache_client=self._cache_client,
            user_id=self.user_id,
            logger_timestamp=self.logger_timestamp,
            user_group=self.user_group,
        )

        logger.info("ToolHandler initialized successfully")

    # ========================================================================
    # MCP Protocol Handlers
    # ========================================================================

    async def handle_initialize(self, request: InitializeRequest) -> InitializeResponse:
        """Handle initialize request"""
        logger.info(f"Initialize request from {request.params.name}")

        self._server_info = ServerInfo(
            name=self.name,
            version=self.version,
            protocol_version="2024-11-05",
            capabilities=[
                MCPCapability.TOOLS,
                MCPCapability.CANCELLATION,
                MCPCapability.STREAMING,
            ],
            metadata={
                "user_id": self.user_id,
                "user_group": self.user_group,
            }
        )

        self._initialized = True

        return InitializeResponse(
            id=request.id,
            result=self._server_info
        )

    async def handle_tools_list(self, request: ToolsListRequest) -> ToolsListResponse:
        """Handle tools/list request"""
        logger.info("Tools list request")

        return ToolsListResponse(
            id=request.id,
            result={"tools": self._tool_definitions}
        )

    async def handle_tools_call(self, request: ToolCallRequest) -> ToolCallResponse:
        """Handle tools/call request"""
        tool_name = request.params.get("name")
        arguments = request.params.get("arguments", {})

        logger.info(f"Tool call: {tool_name} with args: {arguments}")

        try:
            # Ensure ToolHandler is initialized
            await self._ensure_initialized()

            # Extract context parameters
            sub_question = arguments.get("question")
            sub_question_list = arguments.get("sub_question_list")
            custom_instructions = arguments.get("custom_instructions")

            # Build tool_call structure expected by ToolHandler
            tool_call = {
                "function": {
                    "name": tool_name,
                    "arguments": arguments
                }
            }

            # Call ToolHandler
            sql, base64_list, code_list, tool_types_used, report_content, fig_json_list, query_id = \
                await self._tool_handler.handle_tool_call(
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

            # Build response payload
            payload = {
                "ok": True,
                "name": tool_name,
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
            }

            # Return as text content
            return ToolCallResponse(
                id=request.id,
                result={"content": [create_text_content(json.dumps(payload))]}
            )

        except Exception as e:
            logger.error(f"Tool call error: {e}", exc_info=True)

            # Try to log error
            try:
                log_error = self._lazy_imports.get('log_error')
                if log_error:
                    await log_error(self.user_id, str(e), f"mcp.{tool_name}")
            except:
                pass

            # Return error response
            return create_error_response(
                request_id=request.id,
                code=MCPErrorCode.TOOL_EXECUTION_ERROR,
                message=str(e),
                data={"tool": tool_name, "arguments": arguments}
            )

    async def handle_request(self, request: MCPRequest) -> MCPResponse:
        """Route request to appropriate handler"""
        try:
            if isinstance(request, InitializeRequest):
                return await self.handle_initialize(request)
            elif isinstance(request, ToolsListRequest):
                return await self.handle_tools_list(request)
            elif isinstance(request, ToolCallRequest):
                return await self.handle_tools_call(request)
            else:
                return create_error_response(
                    request_id=getattr(request, 'id', 'unknown'),
                    code=MCPErrorCode.METHOD_NOT_FOUND,
                    message=f"Method not supported: {type(request).__name__}"
                )

        except Exception as e:
            logger.error(f"Request handling error: {e}", exc_info=True)
            return create_error_response(
                request_id=getattr(request, 'id', 'unknown'),
                code=MCPErrorCode.INTERNAL_ERROR,
                message=str(e)
            )

    # ========================================================================
    # Shared State Access (for FastAPI integration)
    # ========================================================================

    def set_user_context(self, user_id: str, user_group: str, logger_timestamp: str):
        """Update user context (can be called per-request in FastAPI)"""
        self.user_id = user_id
        self.user_group = user_group
        self.logger_timestamp = logger_timestamp

        # Recreate ToolHandler with new context if already initialized
        if self._tool_handler is not None:
            ToolHandler = self._lazy_imports.get('ToolHandler')
            self._tool_handler = ToolHandler(
                cache_client=self._cache_client,
                user_id=self.user_id,
                logger_timestamp=self.logger_timestamp,
                user_group=self.user_group,
            )

    def get_cache_client(self):
        """Access shared cache (for FastAPI routes)"""
        return self._cache_client

    async def health_check(self) -> Dict[str, Any]:
        """Health check for readiness probe"""
        return {
            "status": "healthy",
            "initialized": self._initialized,
            "tool_handler_ready": self._tool_handler is not None,
            "tools_available": len(self._tool_definitions),
        }


# ============================================================================
# Factory Function
# ============================================================================

def create_inprocess_server(
    user_id: Optional[str] = None,
    user_group: Optional[str] = None,
    logger_timestamp: Optional[str] = None,
) -> InProcessMCPServer:
    """Create an in-process MCP server instance"""
    return InProcessMCPServer(
        user_id=user_id,
        user_group=user_group,
        logger_timestamp=logger_timestamp,
    )
