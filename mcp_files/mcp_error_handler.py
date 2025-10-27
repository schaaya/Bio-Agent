"""
Comprehensive MCP Error Handling with Structured Errors
Provides error translation, recovery strategies, and user-friendly messages
"""
import sys
import traceback
import logging
from typing import Optional, Dict, Any, Callable
from functools import wraps

from mcp_files.mcp_protocol import (
    MCPError,
    MCPErrorCode,
    ToolCallError,
    create_error_response,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Error Classification
# ============================================================================

class MCPErrorClassifier:
    """
    Classifies exceptions into appropriate MCP error codes
    Provides context-aware error messages
    """

    @staticmethod
    def classify(error: Exception) -> tuple[MCPErrorCode, str]:
        """
        Classify exception and return (error_code, user_message)
        """

        error_type = type(error).__name__
        error_msg = str(error)

        # Parse errors
        if "json" in error_msg.lower() or "parse" in error_msg.lower():
            return MCPErrorCode.PARSE_ERROR, f"Failed to parse input: {error_msg}"

        # Validation errors
        if "validation" in error_msg.lower() or "invalid" in error_msg.lower():
            return MCPErrorCode.INVALID_PARAMS, f"Invalid parameters: {error_msg}"

        # Not found errors
        if "not found" in error_msg.lower() or error_type in ["KeyError", "FileNotFoundError"]:
            return MCPErrorCode.RESOURCE_NOT_FOUND, f"Resource not found: {error_msg}"

        # Timeout errors
        if "timeout" in error_msg.lower() or error_type == "TimeoutError":
            return MCPErrorCode.TIMEOUT, f"Operation timed out: {error_msg}"

        # Tool execution errors (business logic)
        if any(keyword in error_msg.lower() for keyword in ["sql", "query", "database", "plot", "csv", "pdf"]):
            return MCPErrorCode.TOOL_EXECUTION_ERROR, f"Tool execution failed: {error_msg}"

        # Generic server errors
        return MCPErrorCode.INTERNAL_ERROR, f"Internal error: {error_msg}"


# ============================================================================
# Error Recovery Strategies
# ============================================================================

class ErrorRecoveryStrategy:
    """Defines recovery strategies for different error types"""

    @staticmethod
    def should_retry(error_code: MCPErrorCode) -> bool:
        """Determine if error is retryable"""
        retryable = {
            MCPErrorCode.TIMEOUT,
            MCPErrorCode.SERVER_ERROR,
            MCPErrorCode.INTERNAL_ERROR,
        }
        return error_code in retryable

    @staticmethod
    def get_user_action(error_code: MCPErrorCode) -> str:
        """Get suggested user action for error"""
        actions = {
            MCPErrorCode.PARSE_ERROR: "Please check your input format and try again.",
            MCPErrorCode.INVALID_REQUEST: "Please verify your request structure.",
            MCPErrorCode.METHOD_NOT_FOUND: "The requested operation is not available.",
            MCPErrorCode.INVALID_PARAMS: "Please check the parameters and try again.",
            MCPErrorCode.RESOURCE_NOT_FOUND: "The requested resource was not found. Please verify and try again.",
            MCPErrorCode.TIMEOUT: "The operation took too long. Please try again or contact support.",
            MCPErrorCode.CANCELLED: "The operation was cancelled.",
            MCPErrorCode.TOOL_EXECUTION_ERROR: "The tool encountered an error. Please check your input or try a different approach.",
            MCPErrorCode.INTERNAL_ERROR: "An unexpected error occurred. Please try again or contact support.",
        }
        return actions.get(error_code, "An error occurred. Please try again.")


# ============================================================================
# Error Handler Decorator
# ============================================================================

def handle_mcp_errors(request_id_field: str = "id"):
    """
    Decorator to handle errors in MCP request handlers
    Converts exceptions to structured MCP error responses
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request_id = "unknown"

            try:
                # Try to extract request ID
                for arg in args:
                    if hasattr(arg, request_id_field):
                        request_id = getattr(arg, request_id_field)
                        break

                # Execute function
                return await func(*args, **kwargs)

            except Exception as e:
                # Classify error
                error_code, user_message = MCPErrorClassifier.classify(e)

                # Log error
                logger.error(
                    f"[{request_id}] {func.__name__} failed: {user_message}",
                    extra={
                        "request_id": request_id,
                        "error_code": error_code.value,
                        "error_type": type(e).__name__,
                        "function": func.__name__,
                    },
                    exc_info=True,
                )

                # Get recovery suggestion
                user_action = ErrorRecoveryStrategy.get_user_action(error_code)

                # Create error response
                return create_error_response(
                    request_id=request_id,
                    code=error_code,
                    message=user_message,
                    data={
                        "error_type": type(e).__name__,
                        "suggestion": user_action,
                        "retryable": ErrorRecoveryStrategy.should_retry(error_code),
                    }
                )

        return wrapper
    return decorator


# ============================================================================
# Context Manager for Error Handling
# ============================================================================

class MCPErrorContext:
    """
    Context manager for error handling in specific operations
    Provides additional context for error messages
    """

    def __init__(
        self,
        operation: str,
        request_id: str,
        context: Optional[Dict[str, Any]] = None
    ):
        self.operation = operation
        self.request_id = request_id
        self.context = context or {}

    async def __aenter__(self):
        logger.debug(f"[{self.request_id}] Starting {self.operation}")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            logger.debug(f"[{self.request_id}] Completed {self.operation}")
            return True

        # Error occurred
        error_code, user_message = MCPErrorClassifier.classify(exc_val)

        logger.error(
            f"[{self.request_id}] {self.operation} failed: {user_message}",
            extra={
                "request_id": self.request_id,
                "operation": self.operation,
                "error_code": error_code.value,
                "context": self.context,
            },
            exc_info=(exc_type, exc_val, exc_tb),
        )

        # Don't suppress exception, let it propagate
        return False


# ============================================================================
# Error Formatting
# ============================================================================

class MCPErrorFormatter:
    """Formats MCP errors for different audiences"""

    @staticmethod
    def format_for_user(error: MCPError) -> str:
        """Format error message for end user"""
        parts = [f"Error: {error.message}"]

        if error.data and "suggestion" in error.data:
            parts.append(f"Suggestion: {error.data['suggestion']}")

        if error.data and error.data.get("retryable"):
            parts.append("This error may be temporary. Please try again.")

        return "\n".join(parts)

    @staticmethod
    def format_for_debug(error: MCPError) -> str:
        """Format error message for debugging"""
        parts = [
            f"Error Code: {error.code.value}",
            f"Message: {error.message}",
            f"Request ID: {error.request_id}",
            f"Timestamp: {error.timestamp}",
        ]

        if error.data:
            parts.append(f"Data: {error.data}")

        return "\n".join(parts)

    @staticmethod
    def format_for_logging(error: MCPError, exc_info: Optional[tuple] = None) -> Dict[str, Any]:
        """Format error for structured logging"""
        log_data = {
            "error_code": error.code.value,
            "message": error.message,
            "request_id": error.request_id,
            "timestamp": error.timestamp,
            "data": error.data,
        }

        if exc_info:
            log_data["traceback"] = "".join(traceback.format_exception(*exc_info))

        return log_data


# ============================================================================
# Built-in Error Handlers
# ============================================================================

class ToolExecutionErrorHandler:
    """Specialized error handler for tool execution errors"""

    @staticmethod
    async def handle_sql_error(error: Exception, context: Dict[str, Any]) -> ToolCallError:
        """Handle SQL execution errors"""
        query = context.get("query", "")
        request_id = context.get("request_id", "unknown")

        user_message = "Database query failed. "

        if "syntax" in str(error).lower():
            user_message += "There was a syntax error in the SQL query."
        elif "permission" in str(error).lower():
            user_message += "You don't have permission to access this data."
        elif "timeout" in str(error).lower():
            user_message += "The query took too long to execute. Try simplifying your request."
        else:
            user_message += "Please check your input and try again."

        return create_error_response(
            request_id=request_id,
            code=MCPErrorCode.TOOL_EXECUTION_ERROR,
            message=user_message,
            data={
                "tool": "ask_database",
                "error_type": type(error).__name__,
                "suggestion": "Try rephrasing your question or using different filters.",
            }
        )

    @staticmethod
    async def handle_plot_error(error: Exception, context: Dict[str, Any]) -> ToolCallError:
        """Handle plotting errors"""
        request_id = context.get("request_id", "unknown")

        user_message = "Failed to generate plot. "

        if "empty" in str(error).lower() or "no data" in str(error).lower():
            user_message += "No data available for plotting."
        elif "column" in str(error).lower():
            user_message += "The requested column was not found in the data."
        else:
            user_message += "Please check your visualization request."

        return create_error_response(
            request_id=request_id,
            code=MCPErrorCode.TOOL_EXECUTION_ERROR,
            message=user_message,
            data={
                "tool": "gen_plotly_code",
                "error_type": type(error).__name__,
                "suggestion": "Ensure your data has the required columns and is not empty.",
            }
        )

    @staticmethod
    async def handle_file_error(error: Exception, context: Dict[str, Any]) -> ToolCallError:
        """Handle file operation errors (CSV, PDF)"""
        request_id = context.get("request_id", "unknown")
        file_type = context.get("file_type", "file")

        user_message = f"Failed to process {file_type}. "

        if isinstance(error, FileNotFoundError):
            user_message += "The file was not found. Please upload it first."
        elif "permission" in str(error).lower():
            user_message += "Permission denied to access the file."
        elif "corrupt" in str(error).lower() or "invalid" in str(error).lower():
            user_message += "The file appears to be corrupted or invalid."
        else:
            user_message += "Please check the file and try again."

        return create_error_response(
            request_id=request_id,
            code=MCPErrorCode.TOOL_EXECUTION_ERROR,
            message=user_message,
            data={
                "tool": f"{file_type}_query",
                "error_type": type(error).__name__,
                "suggestion": f"Ensure the {file_type} file is uploaded and accessible.",
            }
        )


# ============================================================================
# Export
# ============================================================================

__all__ = [
    "MCPErrorClassifier",
    "ErrorRecoveryStrategy",
    "handle_mcp_errors",
    "MCPErrorContext",
    "MCPErrorFormatter",
    "ToolExecutionErrorHandler",
]
