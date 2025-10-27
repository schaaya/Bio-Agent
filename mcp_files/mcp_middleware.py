"""
MCP Middleware for Request-ID Logging and Metrics
Tracks all MCP requests with structured logging
"""
import time
import uuid
import logging
from typing import Callable
from contextvars import ContextVar

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

# Context variables for request tracking
request_id_ctx: ContextVar[str] = ContextVar("request_id", default=None)
user_id_ctx: ContextVar[str] = ContextVar("user_id", default=None)


# ============================================================================
# Request ID Middleware
# ============================================================================

class MCPRequestIDMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add request IDs to all MCP requests
    Helps with debugging and tracing
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generate or extract request ID
        request_id = request.headers.get("X-Request-ID")
        if not request_id:
            request_id = str(uuid.uuid4())

        # Set in context
        request_id_ctx.set(request_id)

        # Add to request state
        request.state.request_id = request_id

        # Log request
        logger.info(
            f"[{request_id}] {request.method} {request.url.path}",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "client": request.client.host if request.client else None,
            }
        )

        # Process request
        start_time = time.time()
        response = await call_next(request)
        duration = time.time() - start_time

        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id

        # Log response
        logger.info(
            f"[{request_id}] {response.status_code} - {duration*1000:.2f}ms",
            extra={
                "request_id": request_id,
                "status_code": response.status_code,
                "duration_ms": duration * 1000,
            }
        )

        return response


# ============================================================================
# Metrics Middleware
# ============================================================================

class MCPMetricsMiddleware(BaseHTTPMiddleware):
    """
    Middleware to collect metrics on MCP requests
    Tracks request counts, durations, error rates
    """

    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.request_count = 0
        self.error_count = 0
        self.total_duration = 0.0

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip non-MCP endpoints
        if not request.url.path.startswith("/mcp"):
            return await call_next(request)

        self.request_count += 1
        start_time = time.time()

        try:
            response = await call_next(request)

            # Record duration
            duration = time.time() - start_time
            self.total_duration += duration

            # Count errors
            if response.status_code >= 400:
                self.error_count += 1

            # Add metrics to response headers
            response.headers["X-MCP-Request-Count"] = str(self.request_count)
            response.headers["X-MCP-Duration-Ms"] = f"{duration*1000:.2f}"

            return response

        except Exception as e:
            self.error_count += 1
            logger.error(f"Request processing error: {e}", exc_info=True)
            raise

    def get_metrics(self):
        """Get current metrics"""
        return {
            "request_count": self.request_count,
            "error_count": self.error_count,
            "total_duration_ms": self.total_duration * 1000,
            "avg_duration_ms": (
                self.total_duration * 1000 / self.request_count
                if self.request_count > 0
                else 0
            ),
            "error_rate": (
                self.error_count / self.request_count * 100
                if self.request_count > 0
                else 0
            ),
        }


# ============================================================================
# Structured Logging
# ============================================================================

class MCPStructuredLogger:
    """
    Structured logger for MCP operations
    Logs with consistent format and context
    """

    def __init__(self, logger_name: str = "mcp"):
        self.logger = logging.getLogger(logger_name)

    def log_request(
        self,
        method: str,
        params: dict = None,
        request_id: str = None,
        user_id: str = None,
    ):
        """Log an incoming MCP request"""
        request_id = request_id or request_id_ctx.get()
        user_id = user_id or user_id_ctx.get()

        self.logger.info(
            f"MCP Request: {method}",
            extra={
                "request_id": request_id,
                "user_id": user_id,
                "method": method,
                "params": params,
                "event_type": "mcp_request",
            }
        )

    def log_response(
        self,
        method: str,
        status: str,
        duration_ms: float,
        request_id: str = None,
        error: str = None,
    ):
        """Log an MCP response"""
        request_id = request_id or request_id_ctx.get()

        level = logging.INFO if status == "success" else logging.ERROR

        self.logger.log(
            level,
            f"MCP Response: {method} - {status} ({duration_ms:.2f}ms)",
            extra={
                "request_id": request_id,
                "method": method,
                "status": status,
                "duration_ms": duration_ms,
                "error": error,
                "event_type": "mcp_response",
            }
        )

    def log_tool_call(
        self,
        tool_name: str,
        arguments: dict,
        request_id: str = None,
        user_id: str = None,
    ):
        """Log a tool call"""
        request_id = request_id or request_id_ctx.get()
        user_id = user_id or user_id_ctx.get()

        self.logger.info(
            f"Tool Call: {tool_name}",
            extra={
                "request_id": request_id,
                "user_id": user_id,
                "tool_name": tool_name,
                "arguments": arguments,
                "event_type": "tool_call",
            }
        )

    def log_tool_result(
        self,
        tool_name: str,
        status: str,
        duration_ms: float,
        request_id: str = None,
        error: str = None,
    ):
        """Log a tool result"""
        request_id = request_id or request_id_ctx.get()

        level = logging.INFO if status == "success" else logging.ERROR

        self.logger.log(
            level,
            f"Tool Result: {tool_name} - {status} ({duration_ms:.2f}ms)",
            extra={
                "request_id": request_id,
                "tool_name": tool_name,
                "status": status,
                "duration_ms": duration_ms,
                "error": error,
                "event_type": "tool_result",
            }
        )

    def log_error(
        self,
        message: str,
        error: Exception,
        context: dict = None,
        request_id: str = None,
    ):
        """Log an error with context"""
        request_id = request_id or request_id_ctx.get()

        self.logger.error(
            message,
            extra={
                "request_id": request_id,
                "error_type": type(error).__name__,
                "error_message": str(error),
                "context": context or {},
                "event_type": "error",
            },
            exc_info=True,
        )


# ============================================================================
# Global Logger Instance
# ============================================================================

mcp_logger = MCPStructuredLogger()


# ============================================================================
# Export
# ============================================================================

__all__ = [
    "MCPRequestIDMiddleware",
    "MCPMetricsMiddleware",
    "MCPStructuredLogger",
    "mcp_logger",
    "request_id_ctx",
    "user_id_ctx",
]
