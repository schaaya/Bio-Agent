"""
MCP Protocol Layer - Standardized request/response types and protocol definitions
Compliant with MCP specification: initialize, tools/list, tools/call, resources/*, errors
"""
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field
from enum import Enum
import uuid
from datetime import datetime


# ============================================================================
# Core MCP Protocol Types
# ============================================================================

class MCPErrorCode(str, Enum):
    """Standard MCP error codes"""
    PARSE_ERROR = "ParseError"
    INVALID_REQUEST = "InvalidRequest"
    METHOD_NOT_FOUND = "MethodNotFound"
    INVALID_PARAMS = "InvalidParams"
    INTERNAL_ERROR = "InternalError"
    SERVER_ERROR = "ServerError"
    TIMEOUT = "Timeout"
    CANCELLED = "Cancelled"
    RESOURCE_NOT_FOUND = "ResourceNotFound"
    TOOL_EXECUTION_ERROR = "ToolExecutionError"


class MCPError(BaseModel):
    """Structured MCP error response"""
    code: MCPErrorCode
    message: str
    data: Optional[Dict[str, Any]] = None
    request_id: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class MCPCapability(str, Enum):
    """MCP server capabilities"""
    TOOLS = "tools"
    RESOURCES = "resources"
    PROMPTS = "prompts"
    LOGGING = "logging"
    SAMPLING = "sampling"
    CANCELLATION = "cancellation"
    STREAMING = "streaming"


class ServerInfo(BaseModel):
    """Server identification and capabilities"""
    name: str
    version: str
    protocol_version: str = "2024-11-05"  # Latest MCP protocol version
    capabilities: List[MCPCapability]
    metadata: Optional[Dict[str, Any]] = None


class ClientInfo(BaseModel):
    """Client identification"""
    name: str
    version: str
    capabilities: Optional[List[str]] = None


# ============================================================================
# Initialize Protocol
# ============================================================================

class InitializeRequest(BaseModel):
    """MCP initialize request"""
    jsonrpc: Literal["2.0"] = "2.0"
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    method: Literal["initialize"] = "initialize"
    params: ClientInfo


class InitializeResponse(BaseModel):
    """MCP initialize response"""
    jsonrpc: Literal["2.0"] = "2.0"
    id: str
    result: ServerInfo


# ============================================================================
# Tools Protocol
# ============================================================================

class ToolParameterProperty(BaseModel):
    """JSON Schema property for tool parameter"""
    type: str
    description: Optional[str] = None
    enum: Optional[List[Any]] = None
    default: Optional[Any] = None
    items: Optional[Dict[str, Any]] = None  # For array types


class ToolParameter(BaseModel):
    """Tool parameter definition (JSON Schema)"""
    type: Literal["object"] = "object"
    properties: Dict[str, ToolParameterProperty]
    required: Optional[List[str]] = None
    additionalProperties: bool = False


class Tool(BaseModel):
    """MCP tool definition"""
    name: str
    description: str
    inputSchema: ToolParameter


class ToolsListRequest(BaseModel):
    """Request to list available tools"""
    jsonrpc: Literal["2.0"] = "2.0"
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    method: Literal["tools/list"] = "tools/list"
    params: Optional[Dict[str, Any]] = None


class ToolsListResponse(BaseModel):
    """Response with available tools"""
    jsonrpc: Literal["2.0"] = "2.0"
    id: str
    result: Dict[Literal["tools"], List[Tool]]


class ToolCallRequest(BaseModel):
    """Request to execute a tool"""
    jsonrpc: Literal["2.0"] = "2.0"
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    method: Literal["tools/call"] = "tools/call"
    params: Dict[str, Any]  # Must contain 'name' and 'arguments'


class TextContent(BaseModel):
    """Text content type"""
    type: Literal["text"] = "text"
    text: str


class ImageContent(BaseModel):
    """Image content type"""
    type: Literal["image"] = "image"
    data: str  # base64 encoded
    mimeType: str = "image/png"


class ResourceContent(BaseModel):
    """Resource reference content"""
    type: Literal["resource"] = "resource"
    resource: Dict[str, Any]


ContentType = Union[TextContent, ImageContent, ResourceContent]


class ToolCallResponse(BaseModel):
    """Response from tool execution"""
    jsonrpc: Literal["2.0"] = "2.0"
    id: str
    result: Dict[Literal["content"], List[ContentType]]


class ToolCallError(BaseModel):
    """Error response from tool execution"""
    jsonrpc: Literal["2.0"] = "2.0"
    id: str
    error: MCPError


# ============================================================================
# Resources Protocol
# ============================================================================

class Resource(BaseModel):
    """MCP resource definition"""
    uri: str
    name: str
    description: Optional[str] = None
    mimeType: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class ResourcesListRequest(BaseModel):
    """Request to list resources"""
    jsonrpc: Literal["2.0"] = "2.0"
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    method: Literal["resources/list"] = "resources/list"
    params: Optional[Dict[str, Any]] = None


class ResourcesListResponse(BaseModel):
    """Response with available resources"""
    jsonrpc: Literal["2.0"] = "2.0"
    id: str
    result: Dict[Literal["resources"], List[Resource]]


class ResourceReadRequest(BaseModel):
    """Request to read a resource"""
    jsonrpc: Literal["2.0"] = "2.0"
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    method: Literal["resources/read"] = "resources/read"
    params: Dict[Literal["uri"], str]


class ResourceReadResponse(BaseModel):
    """Response with resource contents"""
    jsonrpc: Literal["2.0"] = "2.0"
    id: str
    result: Dict[Literal["contents"], List[ContentType]]


# ============================================================================
# Cancellation Protocol
# ============================================================================

class CancelRequest(BaseModel):
    """Request to cancel an operation"""
    jsonrpc: Literal["2.0"] = "2.0"
    method: Literal["notifications/cancelled"] = "notifications/cancelled"
    params: Dict[Literal["requestId"], str]


# ============================================================================
# Streaming Protocol (SSE)
# ============================================================================

class ProgressNotification(BaseModel):
    """Progress notification during long operations"""
    jsonrpc: Literal["2.0"] = "2.0"
    method: Literal["notifications/progress"] = "notifications/progress"
    params: Dict[str, Any]  # progress, total, message, etc.


class StreamChunk(BaseModel):
    """Streaming response chunk"""
    jsonrpc: Literal["2.0"] = "2.0"
    method: Literal["notifications/message"] = "notifications/message"
    params: Dict[str, Any]


# ============================================================================
# Request/Response Unions
# ============================================================================

MCPRequest = Union[
    InitializeRequest,
    ToolsListRequest,
    ToolCallRequest,
    ResourcesListRequest,
    ResourceReadRequest,
    CancelRequest,
]

MCPResponse = Union[
    InitializeResponse,
    ToolsListResponse,
    ToolCallResponse,
    ResourcesListResponse,
    ResourceReadResponse,
    ToolCallError,
]


# ============================================================================
# Utility Functions
# ============================================================================

def create_error_response(
    request_id: str,
    code: MCPErrorCode,
    message: str,
    data: Optional[Dict[str, Any]] = None
) -> ToolCallError:
    """Create a standardized error response"""
    return ToolCallError(
        id=request_id,
        error=MCPError(
            code=code,
            message=message,
            data=data,
            request_id=request_id
        )
    )


def create_text_content(text: str) -> TextContent:
    """Create text content for responses"""
    return TextContent(text=text)


def create_image_content(base64_data: str, mime_type: str = "image/png") -> ImageContent:
    """Create image content for responses"""
    return ImageContent(data=base64_data, mimeType=mime_type)
