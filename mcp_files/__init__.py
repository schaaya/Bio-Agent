"""
MCP Hybrid Architecture for BI-Bot
Fully MCP-compliant architecture with transport abstraction
"""

__version__ = "1.0.0"

# Core protocol
from mcp_files.mcp_protocol import (
    MCPRequest,
    MCPResponse,
    MCPError,
    MCPErrorCode,
    Tool,
    ServerInfo,
    MCPCapability,
    create_error_response,
    create_text_content,
)

# Transport layer
from mcp_files.mcp_transport import (
    MCPTransport,
    InProcessTransport,
    HTTPTransport,
    SSETransport,
    StdioTransport,
    TransportFactory,
)

# Router
from mcp_files.mcp_router import (
    MCPRouter,
    RouterConfig,
    MCPServerRegistration,
)

# Server
from mcp_files.mcp_server_hybrid import (
    InProcessMCPServer,
    create_inprocess_server,
)

# FastAPI integration
from mcp_files.mcp_fastapi_integration import (
    mcp_router as fastapi_mcp_router,
    mcp_lifespan,
    get_mcp_router,
    get_inprocess_server,
)

# Middleware
from mcp_files.mcp_middleware import (
    MCPRequestIDMiddleware,
    MCPMetricsMiddleware,
    MCPStructuredLogger,
    mcp_logger,
)

# Sidecar management
from mcp_files.mcp_sidecar_manager import (
    MCPSidecarManager,
    SidecarConfig,
    SidecarType,
)

# Error handling
from mcp_files.mcp_error_handler import (
    MCPErrorClassifier,
    ErrorRecoveryStrategy,
    handle_mcp_errors,
    MCPErrorContext,
    MCPErrorFormatter,
    ToolExecutionErrorHandler,
)

# Tool adapter
from mcp_files.mcp_tool_adapter import (
    StatelessToolAdapter,
    ToolContext,
    MCPToolRegistry,
)

# Internal client
from mcp_files.mcp_internal_client import (
    MCPInternalClient,
    get_internal_mcp_client,
    close_internal_mcp_client,
)

__all__ = [
    # Version
    "__version__",

    # Protocol
    "MCPRequest",
    "MCPResponse",
    "MCPError",
    "MCPErrorCode",
    "Tool",
    "ServerInfo",
    "MCPCapability",
    "create_error_response",
    "create_text_content",

    # Transport
    "MCPTransport",
    "InProcessTransport",
    "HTTPTransport",
    "SSETransport",
    "StdioTransport",
    "TransportFactory",

    # Router
    "MCPRouter",
    "RouterConfig",
    "MCPServerRegistration",

    # Server
    "InProcessMCPServer",
    "create_inprocess_server",

    # FastAPI
    "fastapi_mcp_router",
    "mcp_lifespan",
    "get_mcp_router",
    "get_inprocess_server",

    # Middleware
    "MCPRequestIDMiddleware",
    "MCPMetricsMiddleware",
    "MCPStructuredLogger",
    "mcp_logger",

    # Sidecar
    "MCPSidecarManager",
    "SidecarConfig",
    "SidecarType",

    # Error handling
    "MCPErrorClassifier",
    "ErrorRecoveryStrategy",
    "handle_mcp_errors",
    "MCPErrorContext",
    "MCPErrorFormatter",
    "ToolExecutionErrorHandler",

    # Tool adapter
    "StatelessToolAdapter",
    "ToolContext",
    "MCPToolRegistry",

    # Internal client
    "MCPInternalClient",
    "get_internal_mcp_client",
    "close_internal_mcp_client",
]
