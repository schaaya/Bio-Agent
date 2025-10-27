"""
MCP Router - Transport-agnostic routing with capability discovery,
timeouts, retries, cancellation, logging, and metrics
"""
import asyncio
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime
import logging

from mcp_files.mcp_protocol import (
    MCPRequest,
    MCPResponse,
    MCPError,
    MCPErrorCode,
    Tool,
    Resource,
    ServerInfo,
    MCPCapability,
    InitializeRequest,
    InitializeResponse,
    ToolsListRequest,
    ToolsListResponse,
    ToolCallRequest,
    ToolCallResponse,
    ResourcesListRequest,
    ResourcesListResponse,
    ResourceReadRequest,
    ResourceReadResponse,
    CancelRequest,
    create_error_response,
    create_text_content,
)
from mcp_files.mcp_transport import MCPTransport

logger = logging.getLogger(__name__)


# ============================================================================
# Request Tracking and Metrics
# ============================================================================

@dataclass
class RequestMetrics:
    """Metrics for a single request"""
    request_id: str
    method: str
    start_time: float
    end_time: Optional[float] = None
    duration_ms: Optional[float] = None
    status: str = "pending"  # pending, completed, error, cancelled, timeout
    error: Optional[str] = None
    retries: int = 0


@dataclass
class ServerMetrics:
    """Aggregate server metrics"""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    cancelled_requests: int = 0
    timeout_requests: int = 0
    total_duration_ms: float = 0.0
    active_requests: int = 0
    request_history: List[RequestMetrics] = field(default_factory=list)

    def record_request(self, metrics: RequestMetrics):
        """Record a completed request"""
        self.total_requests += 1
        self.request_history.append(metrics)

        if metrics.status == "completed":
            self.successful_requests += 1
            if metrics.duration_ms:
                self.total_duration_ms += metrics.duration_ms
        elif metrics.status == "error":
            self.failed_requests += 1
        elif metrics.status == "cancelled":
            self.cancelled_requests += 1
        elif metrics.status == "timeout":
            self.timeout_requests += 1

    @property
    def avg_duration_ms(self) -> float:
        """Average request duration"""
        if self.successful_requests == 0:
            return 0.0
        return self.total_duration_ms / self.successful_requests

    def get_summary(self) -> Dict[str, Any]:
        """Get metrics summary"""
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "cancelled_requests": self.cancelled_requests,
            "timeout_requests": self.timeout_requests,
            "active_requests": self.active_requests,
            "avg_duration_ms": round(self.avg_duration_ms, 2),
            "success_rate": round(
                self.successful_requests / self.total_requests * 100, 2
            ) if self.total_requests > 0 else 0.0,
        }


# ============================================================================
# MCP Router Configuration
# ============================================================================

@dataclass
class RouterConfig:
    """Configuration for MCP router"""
    default_timeout: float = 30.0
    max_retries: int = 3
    retry_delay: float = 1.0
    retry_backoff: float = 2.0  # Exponential backoff multiplier
    enable_cancellation: bool = True
    enable_logging: bool = True
    enable_metrics: bool = True
    max_concurrent_requests: int = 100


# ============================================================================
# MCP Server Registration
# ============================================================================

@dataclass
class MCPServerRegistration:
    """Registration info for an MCP server (in-process, subprocess, or remote)"""
    name: str
    transport: MCPTransport
    info: ServerInfo
    tools: List[Tool] = field(default_factory=list)
    resources: List[Resource] = field(default_factory=list)
    active: bool = True
    priority: int = 0  # Higher priority servers are queried first


# ============================================================================
# MCP Router
# ============================================================================

class MCPRouter:
    """
    Transport-agnostic MCP router with capability discovery,
    timeouts, retries, cancellation, and metrics
    """

    def __init__(self, config: Optional[RouterConfig] = None):
        self.config = config or RouterConfig()
        self.metrics = ServerMetrics()

        # Server registry
        self._servers: Dict[str, MCPServerRegistration] = {}

        # Request tracking
        self._active_requests: Dict[str, asyncio.Task] = {}
        self._cancellation_tokens: Dict[str, asyncio.Event] = {}

        # Semaphore for max concurrent requests
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent_requests)

        # Initialized flag
        self._initialized = False

    # ========================================================================
    # Server Management
    # ========================================================================

    async def register_server(
        self,
        name: str,
        transport: MCPTransport,
        priority: int = 0,
        auto_initialize: bool = True
    ) -> MCPServerRegistration:
        """
        Register an MCP server (in-process, subprocess, or remote)
        Performs capability discovery
        """
        logger.info(f"Registering MCP server: {name}")

        if auto_initialize:
            # Initialize the server to discover capabilities
            from mcp_files.mcp_protocol import ClientInfo

            init_request = InitializeRequest(
                params=ClientInfo(
                    name="bi-bot-router",
                    version="1.0.0",
                    capabilities=["tools", "resources", "cancellation"]
                )
            )

            # Send initialize request based on transport type
            if hasattr(transport, 'call'):
                # HTTP/SSE or in-process
                init_response = await transport.call(init_request)
            else:
                # Stdio
                await transport.send(init_request)
                init_response = await transport.receive()

            if isinstance(init_response, InitializeResponse):
                server_info = init_response.result
            else:
                raise RuntimeError(f"Failed to initialize server {name}")

            # Discover tools
            tools_request = ToolsListRequest()
            if hasattr(transport, 'call'):
                tools_response = await transport.call(tools_request)
            else:
                await transport.send(tools_request)
                tools_response = await transport.receive()

            tools = []
            if isinstance(tools_response, ToolsListResponse):
                tools = tools_response.result.get("tools", [])

            # Discover resources
            resources = []
            if MCPCapability.RESOURCES in server_info.capabilities:
                resources_request = ResourcesListRequest()
                if hasattr(transport, 'call'):
                    resources_response = await transport.call(resources_request)
                else:
                    await transport.send(resources_request)
                    resources_response = await transport.receive()

                if isinstance(resources_response, ResourcesListResponse):
                    resources = resources_response.result.get("resources", [])

        else:
            # Manual registration without initialization
            server_info = ServerInfo(
                name=name,
                version="1.0.0",
                capabilities=[MCPCapability.TOOLS]
            )
            tools = []
            resources = []

        # Create registration
        registration = MCPServerRegistration(
            name=name,
            transport=transport,
            info=server_info,
            tools=tools,
            resources=resources,
            priority=priority
        )

        self._servers[name] = registration
        logger.info(
            f"Server {name} registered with {len(tools)} tools and {len(resources)} resources"
        )

        return registration

    def unregister_server(self, name: str):
        """Unregister an MCP server"""
        if name in self._servers:
            del self._servers[name]
            logger.info(f"Server {name} unregistered")

    def get_server(self, name: str) -> Optional[MCPServerRegistration]:
        """Get server registration by name"""
        return self._servers.get(name)

    def list_servers(self) -> List[MCPServerRegistration]:
        """List all registered servers"""
        return sorted(
            [s for s in self._servers.values() if s.active],
            key=lambda s: s.priority,
            reverse=True
        )

    # ========================================================================
    # Tool Discovery
    # ========================================================================

    def list_all_tools(self) -> List[Tool]:
        """List all tools from all registered servers"""
        tools = []
        for server in self.list_servers():
            tools.extend(server.tools)
        return tools

    def find_tool(self, tool_name: str) -> Optional[tuple[Tool, MCPServerRegistration]]:
        """Find a tool by name across all servers"""
        for server in self.list_servers():
            for tool in server.tools:
                if tool.name == tool_name:
                    return tool, server
        return None

    # ========================================================================
    # Request Execution with Retries, Timeouts, Cancellation
    # ========================================================================

    async def execute_request(
        self,
        request: MCPRequest,
        server_name: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> MCPResponse:
        """
        Execute an MCP request with retries, timeout, and cancellation support
        """
        request_id = getattr(request, 'id', str(uuid.uuid4()))
        method = getattr(request, 'method', 'unknown')

        # Create metrics
        metrics = RequestMetrics(
            request_id=request_id,
            method=method,
            start_time=time.time()
        )

        # Use config defaults if not specified
        timeout = timeout or self.config.default_timeout
        max_retries = max_retries if max_retries is not None else self.config.max_retries

        # Create cancellation token
        if self.config.enable_cancellation:
            self._cancellation_tokens[request_id] = asyncio.Event()

        try:
            # Acquire semaphore
            async with self._semaphore:
                self.metrics.active_requests += 1

                # Execute with retries
                attempt = 0
                last_error = None

                while attempt <= max_retries:
                    try:
                        metrics.retries = attempt

                        # Check cancellation
                        if self._is_cancelled(request_id):
                            metrics.status = "cancelled"
                            return create_error_response(
                                request_id=request_id,
                                code=MCPErrorCode.CANCELLED,
                                message="Request was cancelled"
                            )

                        # Execute with timeout
                        response = await asyncio.wait_for(
                            self._execute_request_internal(request, server_name),
                            timeout=timeout
                        )

                        # Success
                        metrics.status = "completed"
                        metrics.end_time = time.time()
                        metrics.duration_ms = (metrics.end_time - metrics.start_time) * 1000

                        if self.config.enable_logging:
                            logger.info(
                                f"Request {request_id} completed in {metrics.duration_ms:.2f}ms "
                                f"(attempt {attempt + 1})"
                            )

                        return response

                    except asyncio.TimeoutError:
                        last_error = f"Request timed out after {timeout}s"
                        if attempt >= max_retries:
                            metrics.status = "timeout"
                            metrics.error = last_error
                            logger.error(f"Request {request_id} timed out after {max_retries} retries")
                            return create_error_response(
                                request_id=request_id,
                                code=MCPErrorCode.TIMEOUT,
                                message=last_error
                            )

                    except Exception as e:
                        last_error = str(e)
                        if attempt >= max_retries:
                            metrics.status = "error"
                            metrics.error = last_error
                            logger.error(f"Request {request_id} failed: {e}")
                            return create_error_response(
                                request_id=request_id,
                                code=MCPErrorCode.INTERNAL_ERROR,
                                message=last_error
                            )

                    # Retry with exponential backoff
                    attempt += 1
                    if attempt <= max_retries:
                        delay = self.config.retry_delay * (self.config.retry_backoff ** (attempt - 1))
                        logger.warning(
                            f"Request {request_id} failed (attempt {attempt}), "
                            f"retrying in {delay:.2f}s: {last_error}"
                        )
                        await asyncio.sleep(delay)

                # Should not reach here
                return create_error_response(
                    request_id=request_id,
                    code=MCPErrorCode.INTERNAL_ERROR,
                    message="Unexpected error in retry loop"
                )

        finally:
            # Cleanup
            self.metrics.active_requests -= 1
            if self.config.enable_cancellation and request_id in self._cancellation_tokens:
                del self._cancellation_tokens[request_id]

            # Record metrics
            if self.config.enable_metrics:
                if metrics.end_time is None:
                    metrics.end_time = time.time()
                    metrics.duration_ms = (metrics.end_time - metrics.start_time) * 1000
                self.metrics.record_request(metrics)

    async def _execute_request_internal(
        self,
        request: MCPRequest,
        server_name: Optional[str] = None
    ) -> MCPResponse:
        """Internal request execution (called by retry logic)"""

        # Determine target server
        if server_name:
            server = self.get_server(server_name)
            if not server or not server.active:
                raise ValueError(f"Server {server_name} not found or inactive")
        else:
            # For tool calls, find server with the tool
            if isinstance(request, ToolCallRequest):
                tool_name = request.params.get("name")
                result = self.find_tool(tool_name)
                if not result:
                    raise ValueError(f"Tool {tool_name} not found in any server")
                _, server = result
            else:
                # Use first available server
                servers = self.list_servers()
                if not servers:
                    raise ValueError("No active servers registered")
                server = servers[0]

        # Execute request on transport
        transport = server.transport

        if hasattr(transport, 'call'):
            # HTTP/SSE or in-process transport
            return await transport.call(request)
        else:
            # Stdio transport
            await transport.send(request)
            response = await transport.receive()
            if response is None:
                raise RuntimeError("No response received from server")
            return response

    # ========================================================================
    # Cancellation
    # ========================================================================

    def cancel_request(self, request_id: str):
        """Cancel an active request"""
        if request_id in self._cancellation_tokens:
            self._cancellation_tokens[request_id].set()
            logger.info(f"Cancellation requested for {request_id}")

    def _is_cancelled(self, request_id: str) -> bool:
        """Check if request is cancelled"""
        if request_id in self._cancellation_tokens:
            return self._cancellation_tokens[request_id].is_set()
        return False

    # ========================================================================
    # Convenience Methods
    # ========================================================================

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        server_name: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> ToolCallResponse:
        """Convenience method to call a tool"""
        request = ToolCallRequest(
            params={"name": tool_name, "arguments": arguments}
        )
        return await self.execute_request(request, server_name, timeout)

    # ========================================================================
    # Metrics and Health
    # ========================================================================

    def get_metrics(self) -> Dict[str, Any]:
        """Get router metrics"""
        return self.metrics.get_summary()

    def get_health(self) -> Dict[str, Any]:
        """Get health status"""
        return {
            "status": "healthy" if len(self._servers) > 0 else "degraded",
            "servers": len(self._servers),
            "active_servers": len(self.list_servers()),
            "active_requests": self.metrics.active_requests,
            "total_tools": len(self.list_all_tools()),
        }

    async def close(self):
        """Close all transports"""
        for server in self._servers.values():
            await server.transport.close()
