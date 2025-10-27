"""
Internal MCP HTTP Client
Used by Agent_COT_v2 to call tools through MCP protocol (localhost)
"""
import httpx
import json
import uuid
from typing import Any, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class MCPInternalClient:
    """
    HTTP client for calling MCP endpoints from within the same application.

    This ensures ALL tool calls go through the MCP protocol, even internal ones,
    providing consistent behavior: retries, timeouts, cancellation, metrics, etc.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        timeout: float = 300.0  # Increased from 60s to 300s (5 min) for large database queries
    ):
        """
        Initialize internal MCP client

        Args:
            base_url: Base URL of FastAPI app (default: localhost:8000)
            timeout: Request timeout in seconds (default: 300s / 5 min for large DB queries)
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._initialized = False

    async def _ensure_client(self):
        """Ensure HTTP client is initialized"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=True
            )

    async def initialize(self) -> Dict[str, Any]:
        """
        Send MCP initialize request

        Returns:
            Server info with capabilities
        """
        await self._ensure_client()

        request = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "initialize",
            "params": {
                "name": "internal-agent",
                "version": "1.0.0",
                "capabilities": ["tools", "cancellation"]
            }
        }

        try:
            response = await self._client.post(
                f"{self.base_url}/mcp",
                json=request
            )
            response.raise_for_status()
            result = response.json()

            if "error" in result:
                raise Exception(f"Initialize failed: {result['error']}")

            self._initialized = True
            logger.info("MCP client initialized successfully")
            return result.get("result", {})

        except Exception as e:
            logger.error(f"Failed to initialize MCP client: {e}")
            raise

    async def list_tools(self) -> list:
        """
        List available tools

        Returns:
            List of tool definitions
        """
        await self._ensure_client()

        request = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tools/list"
        }

        try:
            response = await self._client.post(
                f"{self.base_url}/mcp",
                json=request
            )
            response.raise_for_status()
            result = response.json()

            if "error" in result:
                raise Exception(f"List tools failed: {result['error']}")

            return result.get("result", {}).get("tools", [])

        except Exception as e:
            logger.error(f"Failed to list tools: {e}")
            raise

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user_id: Optional[str] = None,
        user_group: Optional[str] = None,
        logger_timestamp: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Call a tool via MCP protocol

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments
            user_id: Optional user ID for context
            user_group: Optional user group for context
            logger_timestamp: Optional logger timestamp for context

        Returns:
            Tool execution result
        """
        await self._ensure_client()

        request = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }

        # Add user context via query params if provided
        url = f"{self.base_url}/mcp"
        query_params = []
        if user_id:
            query_params.append(f"user_id={user_id}")
        if user_group:
            query_params.append(f"user_group={user_group}")
        if logger_timestamp:
            query_params.append(f"logger_timestamp={logger_timestamp}")

        if query_params:
            url += "?" + "&".join(query_params)

        try:
            logger.debug(f"Calling tool {tool_name} with args: {arguments}")

            response = await self._client.post(url, json=request)
            response.raise_for_status()
            result = response.json()

            # Check for MCP error
            if "error" in result:
                error = result["error"]
                error_msg = error.get("message", "Unknown error")
                logger.error(f"Tool call failed: {error_msg}")
                return {
                    "ok": False,
                    "error": error_msg,
                    "error_code": error.get("code"),
                    "error_data": error.get("data")
                }

            # Parse MCP response
            mcp_result = result.get("result", {})
            content_list = mcp_result.get("content", [])

            if not content_list:
                logger.warning(f"Tool {tool_name} returned empty content")
                return {"ok": True, "result": None}

            # Extract text content
            text_content = content_list[0].get("text", "{}")

            try:
                # Parse the JSON payload from text content
                payload = json.loads(text_content)
                logger.debug(f"Tool {tool_name} returned: {payload}")
                return payload
            except json.JSONDecodeError:
                # Return as-is if not JSON
                return {"ok": True, "result": text_content}

        except httpx.HTTPError as e:
            logger.error(f"HTTP error calling tool {tool_name}: {e}")
            return {
                "ok": False,
                "error": f"HTTP error: {e}"
            }
        except Exception as e:
            logger.error(f"Unexpected error calling tool {tool_name}: {e}")
            return {
                "ok": False,
                "error": f"Unexpected error: {e}"
            }

    async def cancel_request(self, request_id: str):
        """
        Cancel a running request

        Args:
            request_id: ID of request to cancel
        """
        await self._ensure_client()

        try:
            response = await self._client.post(
                f"{self.base_url}/mcp/cancel/{request_id}"
            )
            response.raise_for_status()
            logger.info(f"Cancelled request {request_id}")
        except Exception as e:
            logger.error(f"Failed to cancel request {request_id}: {e}")

    async def get_health(self) -> Dict[str, Any]:
        """
        Check MCP server health

        Returns:
            Health status
        """
        await self._ensure_client()

        try:
            response = await self._client.get(f"{self.base_url}/mcp/health")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {"status": "unhealthy", "error": str(e)}

    async def close(self):
        """Close the HTTP client"""
        if self._client:
            await self._client.aclose()
            self._client = None
            self._initialized = False
            logger.info("MCP client closed")

    async def __aenter__(self):
        """Async context manager entry"""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()


# Singleton instance for app-wide use
_internal_client: Optional[MCPInternalClient] = None


def get_internal_mcp_client(
    base_url: str = "http://localhost:8000",
    timeout: float = 300.0  # Increased from 60s to 300s for database queries
) -> MCPInternalClient:
    """
    Get or create singleton internal MCP client

    Args:
        base_url: Base URL of FastAPI app
        timeout: Request timeout

    Returns:
        MCPInternalClient instance
    """
    global _internal_client

    if _internal_client is None:
        _internal_client = MCPInternalClient(
            base_url=base_url,
            timeout=timeout
        )

    return _internal_client


async def close_internal_mcp_client():
    """Close the singleton internal MCP client"""
    global _internal_client

    if _internal_client:
        await _internal_client.close()
        _internal_client = None
