"""
MCP Transport Abstraction Layer
Supports multiple transports: in-process HTTP/SSE, stdio, remote HTTP
All transports use the same MCP protocol layer
"""
import abc
import asyncio
import json
import sys
from typing import Any, AsyncIterator, Callable, Dict, Optional
from contextlib import asynccontextmanager
import httpx
from pydantic import ValidationError

from mcp_files.mcp_protocol import (
    MCPRequest,
    MCPResponse,
    MCPError,
    MCPErrorCode,
    create_error_response,
)


# ============================================================================
# Base Transport Interface
# ============================================================================

class MCPTransport(abc.ABC):
    """Abstract base class for MCP transports"""

    def __init__(self, name: str):
        self.name = name
        self._closed = False

    @abc.abstractmethod
    async def send(self, message: MCPResponse) -> None:
        """Send a response message"""
        pass

    @abc.abstractmethod
    async def receive(self) -> Optional[MCPRequest]:
        """Receive a request message"""
        pass

    @abc.abstractmethod
    async def close(self) -> None:
        """Close the transport"""
        pass

    @property
    def is_closed(self) -> bool:
        return self._closed

    def serialize_message(self, message: MCPResponse) -> str:
        """Serialize message to JSON-RPC format"""
        return message.model_dump_json()

    def deserialize_message(self, data: str, request_id: Optional[str] = None) -> MCPRequest:
        """Deserialize JSON-RPC message to request object"""
        try:
            obj = json.loads(data)

            # Route to appropriate request type based on method
            method = obj.get("method")

            # Import here to avoid circular dependency
            from mcp_files.mcp_protocol import (
                InitializeRequest,
                ToolsListRequest,
                ToolCallRequest,
                ResourcesListRequest,
                ResourceReadRequest,
                CancelRequest,
            )

            method_map = {
                "initialize": InitializeRequest,
                "tools/list": ToolsListRequest,
                "tools/call": ToolCallRequest,
                "resources/list": ResourcesListRequest,
                "resources/read": ResourceReadRequest,
                "notifications/cancelled": CancelRequest,
            }

            request_class = method_map.get(method)
            if not request_class:
                raise ValueError(f"Unknown method: {method}")

            return request_class(**obj)

        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            # Return error that can be sent back
            raise ValueError(f"Failed to parse request: {e}")


# ============================================================================
# In-Process Transport (for mounting in FastAPI)
# ============================================================================

class InProcessTransport(MCPTransport):
    """
    In-process transport for direct function calls
    Used when MCP server is mounted inside the FastAPI app
    """

    def __init__(self, name: str = "in-process", server=None):
        super().__init__(name)
        self._request_queue: asyncio.Queue[MCPRequest] = asyncio.Queue()
        self._response_future: Optional[asyncio.Future[MCPResponse]] = None
        self._server = server  # Direct reference to server for in-process calls

    def set_server(self, server):
        """Set the server instance for direct calls"""
        self._server = server

    async def send(self, message: MCPResponse) -> None:
        """Send response by completing the future"""
        if self._response_future and not self._response_future.done():
            self._response_future.set_result(message)

    async def receive(self) -> Optional[MCPRequest]:
        """Receive request from queue"""
        if self._closed:
            return None
        return await self._request_queue.get()

    async def call(self, request: MCPRequest) -> MCPResponse:
        """
        Direct call interface for in-process usage
        Directly calls server.handle_request() for efficiency
        """
        if self._server:
            # Direct call to server (most efficient for in-process)
            return await self._server.handle_request(request)
        else:
            # Fallback to queue-based approach
            self._response_future = asyncio.Future()
            await self._request_queue.put(request)
            return await self._response_future

    async def close(self) -> None:
        self._closed = True


# ============================================================================
# HTTP/SSE Transport (for remote MCP servers)
# ============================================================================

class HTTPTransport(MCPTransport):
    """
    HTTP transport for remote MCP servers
    Uses POST requests for standard requests
    """

    def __init__(
        self,
        base_url: str,
        name: str = "http",
        timeout: float = 30.0,
        headers: Optional[Dict[str, str]] = None
    ):
        super().__init__(name)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = headers or {}
        self._client: Optional[httpx.AsyncClient] = None

    async def _ensure_client(self):
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                headers=self.headers
            )

    async def send(self, message: MCPResponse) -> None:
        """HTTP transport doesn't send unsolicited responses"""
        pass

    async def receive(self) -> Optional[MCPRequest]:
        """HTTP transport doesn't receive unsolicited requests"""
        return None

    async def call(self, request: MCPRequest) -> MCPResponse:
        """Make HTTP POST request and get response"""
        await self._ensure_client()

        try:
            response = await self._client.post(
                f"{self.base_url}/mcp",
                json=json.loads(self.serialize_message(request)),
            )
            response.raise_for_status()

            # Parse response
            data = response.json()

            # Import response types
            from mcp_files.mcp_protocol import (
                InitializeResponse,
                ToolsListResponse,
                ToolCallResponse,
                ResourcesListResponse,
                ResourceReadResponse,
                ToolCallError,
            )

            # Check if error response
            if "error" in data:
                return ToolCallError(**data)

            # Route based on request method
            if hasattr(request, 'method'):
                method = request.method
                if method == "initialize":
                    return InitializeResponse(**data)
                elif method == "tools/list":
                    return ToolsListResponse(**data)
                elif method == "tools/call":
                    return ToolCallResponse(**data)
                elif method == "resources/list":
                    return ResourcesListResponse(**data)
                elif method == "resources/read":
                    return ResourceReadResponse(**data)

            # Fallback
            return ToolCallResponse(**data)

        except httpx.HTTPError as e:
            # Convert to MCP error
            error_response = create_error_response(
                request_id=getattr(request, 'id', 'unknown'),
                code=MCPErrorCode.SERVER_ERROR,
                message=f"HTTP transport error: {e}",
            )
            return error_response

    async def close(self) -> None:
        self._closed = True
        if self._client:
            await self._client.aclose()


class SSETransport(HTTPTransport):
    """
    SSE (Server-Sent Events) transport for streaming responses
    Extends HTTP transport with streaming capabilities
    """

    async def stream_call(self, request: MCPRequest) -> AsyncIterator[MCPResponse]:
        """Make streaming SSE request"""
        await self._ensure_client()

        try:
            async with self._client.stream(
                "POST",
                f"{self.base_url}/mcp/stream",
                json=json.loads(self.serialize_message(request)),
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]  # Remove "data: " prefix
                        if data_str.strip() == "[DONE]":
                            break

                        try:
                            data = json.loads(data_str)

                            # Parse as appropriate response type
                            from mcp_files.mcp_protocol import (
                                ToolCallResponse,
                                ProgressNotification,
                            )

                            if "method" in data and data["method"] == "notifications/progress":
                                # Progress notification
                                continue  # Could yield these if needed
                            else:
                                # Actual response chunk
                                yield ToolCallResponse(**data)

                        except json.JSONDecodeError:
                            continue

        except httpx.HTTPError as e:
            error_response = create_error_response(
                request_id=getattr(request, 'id', 'unknown'),
                code=MCPErrorCode.SERVER_ERROR,
                message=f"SSE transport error: {e}",
            )
            yield error_response


# ============================================================================
# Stdio Transport (for subprocess MCP servers)
# ============================================================================

class StdioTransport(MCPTransport):
    """
    Stdio transport for subprocess MCP servers
    Uses stdin/stdout for JSON-RPC communication
    """

    def __init__(
        self,
        name: str = "stdio",
        process: Optional[asyncio.subprocess.Process] = None
    ):
        super().__init__(name)
        self.process = process
        self._read_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()

    async def send(self, message: MCPResponse) -> None:
        """Write message to stdout"""
        if not self.process or not self.process.stdin:
            raise RuntimeError("Stdio transport not connected to process")

        async with self._write_lock:
            data = self.serialize_message(message) + "\n"
            self.process.stdin.write(data.encode())
            await self.process.stdin.drain()

    async def receive(self) -> Optional[MCPRequest]:
        """Read message from stdin"""
        if not self.process or not self.process.stdout:
            return None

        async with self._read_lock:
            try:
                line = await self.process.stdout.readline()
                if not line:
                    return None

                return self.deserialize_message(line.decode().strip())

            except Exception as e:
                print(f"Error reading from stdio: {e}", file=sys.stderr)
                return None

    async def close(self) -> None:
        self._closed = True
        if self.process:
            if self.process.stdin:
                self.process.stdin.close()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()


# ============================================================================
# Transport Factory
# ============================================================================

class TransportFactory:
    """Factory for creating transport instances"""

    @staticmethod
    def create_inprocess() -> InProcessTransport:
        """Create in-process transport"""
        return InProcessTransport()

    @staticmethod
    def create_http(base_url: str, timeout: float = 30.0) -> HTTPTransport:
        """Create HTTP transport"""
        return HTTPTransport(base_url=base_url, timeout=timeout)

    @staticmethod
    def create_sse(base_url: str, timeout: float = 30.0) -> SSETransport:
        """Create SSE transport"""
        return SSETransport(base_url=base_url, timeout=timeout)

    @staticmethod
    async def create_stdio(
        command: str,
        args: list[str],
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None
    ) -> StdioTransport:
        """Create stdio transport by spawning subprocess"""
        process = await asyncio.create_subprocess_exec(
            command,
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
        return StdioTransport(process=process)
