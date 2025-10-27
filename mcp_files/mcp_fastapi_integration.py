"""
FastAPI Integration for Hybrid MCP Architecture
Mounts MCP server endpoints (HTTP and SSE) inside FastAPI
All traffic goes through MCP protocol
"""
import asyncio
import json
import logging
from typing import Any, Dict, Optional
from contextlib import asynccontextmanager

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from sse_starlette.sse import EventSourceResponse
from pydantic import ValidationError

from mcp_files.mcp_protocol import (
    MCPRequest,
    MCPResponse,
    MCPError,
    MCPErrorCode,
    InitializeRequest,
    ToolsListRequest,
    ToolCallRequest,
    create_error_response,
)
from mcp_files.mcp_server_hybrid import InProcessMCPServer
from mcp_files.mcp_router import MCPRouter, RouterConfig
from mcp_files.mcp_transport import InProcessTransport, TransportFactory

logger = logging.getLogger(__name__)


# ============================================================================
# Global MCP Infrastructure
# ============================================================================

# Global router (initialized on startup)
_mcp_router: Optional[MCPRouter] = None

# Global in-process server (initialized on startup)
_inprocess_server: Optional[InProcessMCPServer] = None


# ============================================================================
# Lifecycle Management
# ============================================================================

@asynccontextmanager
async def mcp_lifespan():
    """
    Lifespan context manager for MCP infrastructure
    Use this in FastAPI app lifespan
    """
    global _mcp_router, _inprocess_server

    logger.info("Starting MCP infrastructure...")

    try:
        # Create router
        _mcp_router = MCPRouter(
            config=RouterConfig(
                default_timeout=300.0,  # Increased from 60s to 300s (5 min) for large DB queries
                max_retries=3,
                enable_cancellation=True,
                enable_logging=True,
                enable_metrics=True,
            )
        )

        # Create in-process server
        _inprocess_server = InProcessMCPServer(
            name="bi-bot-mcp",
            version="1.0.0",
            user_id="default@example.com",
            user_group="default",
            logger_timestamp="mcp"
        )

        # Create in-process transport and link it to the server
        transport = TransportFactory.create_inprocess()
        transport.set_server(_inprocess_server)  # Connect transport to server

        # Register in-process server with router
        # Note: We bypass auto_initialize since InProcessMCPServer handles its own init
        await _mcp_router.register_server(
            name="in-process",
            transport=transport,
            priority=100,  # Highest priority
            auto_initialize=False  # We'll handle initialize manually
        )

        logger.info("MCP infrastructure started successfully")

        yield

    finally:
        # Cleanup
        logger.info("Shutting down MCP infrastructure...")
        if _mcp_router:
            await _mcp_router.close()


def get_mcp_router() -> MCPRouter:
    """Dependency to get MCP router"""
    if _mcp_router is None:
        raise HTTPException(status_code=503, detail="MCP router not initialized")
    return _mcp_router


def get_inprocess_server() -> InProcessMCPServer:
    """Dependency to get in-process server"""
    if _inprocess_server is None:
        raise HTTPException(status_code=503, detail="MCP server not initialized")
    return _inprocess_server


# ============================================================================
# Request Parsing
# ============================================================================

async def parse_mcp_request(request_data: Dict[str, Any]) -> MCPRequest:
    """Parse incoming JSON-RPC request"""
    try:
        method = request_data.get("method")

        # Route to appropriate request type
        if method == "initialize":
            return InitializeRequest(**request_data)
        elif method == "tools/list":
            return ToolsListRequest(**request_data)
        elif method == "tools/call":
            return ToolCallRequest(**request_data)
        else:
            raise ValueError(f"Unknown method: {method}")

    except (ValidationError, ValueError) as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid MCP request: {e}"
        )


# ============================================================================
# FastAPI Router
# ============================================================================

mcp_router = APIRouter(prefix="/mcp", tags=["MCP"])


@mcp_router.options("/")
@mcp_router.options("")
async def mcp_options():
    """Handle OPTIONS preflight for CORS"""
    return JSONResponse(content={"status": "ok"})


@mcp_router.post("/")
@mcp_router.post("")
async def mcp_endpoint(
    request: Request,
    server: InProcessMCPServer = Depends(get_inprocess_server),
    router: MCPRouter = Depends(get_mcp_router)
):
    """
    Main MCP endpoint (HTTP POST)
    Handles initialize, tools/list, tools/call
    Routes through MCP Router for retry/timeout/cancellation support
    """
    try:
        # Extract user context from query params (if provided)
        user_id = request.query_params.get("user_id")
        user_group = request.query_params.get("user_group")
        logger_timestamp = request.query_params.get("logger_timestamp")

        # Set user context on server if provided
        if user_id:
            server.set_user_context(
                user_id=user_id,
                user_group=user_group or "default",
                logger_timestamp=logger_timestamp or "mcp"
            )

        # Parse request body
        body = await request.json()

        # Parse as MCP request
        mcp_request = await parse_mcp_request(body)

        # ✅ Route request through MCP Router (provides retry/timeout/cancellation)
        response = await router.execute_request(
            request=mcp_request,
            server_name="in-process",
            timeout=300.0,  # Increased from 60s to 300s for large DB queries
            max_retries=3
        )

        # Return JSON-RPC response
        return JSONResponse(
            content=json.loads(response.model_dump_json())
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"MCP endpoint error: {e}", exc_info=True)

        # Return MCP error response
        error_response = create_error_response(
            request_id=body.get("id", "unknown") if "body" in locals() else "unknown",
            code=MCPErrorCode.INTERNAL_ERROR,
            message=str(e)
        )

        return JSONResponse(
            content=json.loads(error_response.model_dump_json()),
            status_code=500
        )


@mcp_router.post("/stream")
async def mcp_stream_endpoint(
    request: Request,
    server: InProcessMCPServer = Depends(get_inprocess_server)
):
    """
    MCP streaming endpoint (SSE)
    For long-running tool calls with progress updates
    """
    try:
        body = await request.json()
        mcp_request = await parse_mcp_request(body)

        async def event_generator():
            try:
                # Send progress notification
                yield {
                    "event": "message",
                    "data": json.dumps({
                        "jsonrpc": "2.0",
                        "method": "notifications/progress",
                        "params": {"message": "Processing request..."}
                    })
                }

                # Handle request
                response = await server.handle_request(mcp_request)

                # Send final response
                yield {
                    "event": "message",
                    "data": json.dumps(json.loads(response.model_dump_json()))
                }

                # Send done signal
                yield {
                    "event": "message",
                    "data": "[DONE]"
                }

            except Exception as e:
                logger.error(f"Stream error: {e}", exc_info=True)

                error_response = create_error_response(
                    request_id=getattr(mcp_request, 'id', 'unknown'),
                    code=MCPErrorCode.INTERNAL_ERROR,
                    message=str(e)
                )

                yield {
                    "event": "error",
                    "data": json.dumps(json.loads(error_response.model_dump_json()))
                }

        return EventSourceResponse(event_generator())

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Stream endpoint error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Health and Metrics Endpoints
# ============================================================================

@mcp_router.get("/health")
async def health_endpoint(
    router: MCPRouter = Depends(get_mcp_router),
    server: InProcessMCPServer = Depends(get_inprocess_server)
):
    """Health check endpoint"""
    try:
        router_health = router.get_health()
        server_health = await server.health_check()

        return {
            "status": "healthy" if router_health["status"] == "healthy" else "degraded",
            "router": router_health,
            "server": server_health,
        }
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return JSONResponse(
            content={"status": "unhealthy", "error": str(e)},
            status_code=503
        )


@mcp_router.get("/ready")
async def readiness_endpoint(
    server: InProcessMCPServer = Depends(get_inprocess_server)
):
    """
    Readiness probe endpoint
    Checks if server is ready to accept requests
    Helps debug stdio startup hang issues
    """
    try:
        health = await server.health_check()

        if health["tool_handler_ready"]:
            return {"status": "ready", "health": health}
        else:
            return JSONResponse(
                content={"status": "not_ready", "health": health},
                status_code=503
            )
    except Exception as e:
        logger.error(f"Readiness check error: {e}")
        return JSONResponse(
            content={"status": "not_ready", "error": str(e)},
            status_code=503
        )


@mcp_router.get("/metrics")
async def metrics_endpoint(router: MCPRouter = Depends(get_mcp_router)):
    """Metrics endpoint"""
    return router.get_metrics()


@mcp_router.get("/servers")
async def servers_endpoint(router: MCPRouter = Depends(get_mcp_router)):
    """List registered MCP servers"""
    servers = router.list_servers()
    return {
        "servers": [
            {
                "name": s.name,
                "active": s.active,
                "priority": s.priority,
                "tools": len(s.tools),
                "resources": len(s.resources),
                "capabilities": [c.value for c in s.info.capabilities],
            }
            for s in servers
        ]
    }


@mcp_router.get("/tools")
async def tools_endpoint(router: MCPRouter = Depends(get_mcp_router)):
    """List all available tools"""
    tools = router.list_all_tools()
    return {
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "parameters": json.loads(t.inputSchema.model_dump_json()),
            }
            for t in tools
        ]
    }


# ============================================================================
# User Context Management
# ============================================================================

async def set_user_context_dependency(
    request: Request,
    server: InProcessMCPServer = Depends(get_inprocess_server)
):
    """
    Dependency to set user context from request
    Can extract user_id, user_group from JWT, session, etc.
    """
    # TODO: Extract from JWT/session
    # For now, use defaults or query params
    user_id = request.query_params.get("user_id", "default@example.com")
    user_group = request.query_params.get("user_group", "default")
    logger_timestamp = request.query_params.get("logger_timestamp", "mcp")

    server.set_user_context(user_id, user_group, logger_timestamp)


# ============================================================================
# Cancellation Endpoint
# ============================================================================

@mcp_router.post("/cancel/{request_id}")
async def cancel_request_endpoint(
    request_id: str,
    router: MCPRouter = Depends(get_mcp_router)
):
    """Cancel an active request"""
    router.cancel_request(request_id)
    return {"status": "cancelled", "request_id": request_id}


# ============================================================================
# Export for main.py
# ============================================================================

__all__ = [
    "mcp_router",
    "mcp_lifespan",
    "get_mcp_router",
    "get_inprocess_server",
]
