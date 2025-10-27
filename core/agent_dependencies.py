"""
Shared Dependencies for Pydantic AI Agents
Provides context and services for agent tools
"""
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from cachetools import TTLCache


@dataclass
class SQLAgentDependencies:
    """Dependencies for SQL Agent"""
    user_id: str
    user_group: str
    logger_timestamp: str
    tool_id: Optional[str] = None
    tag: Optional[str] = None

    # Database context
    database: Optional[str] = None
    db_schema: Optional[str] = None
    description: Optional[str] = None
    dialect: Optional[str] = None

    # Query context
    relevant_queries: Optional[List[str]] = None
    relevant_domain_knowledge: Optional[List[str]] = None
    context_messages: Optional[List[Dict[str, str]]] = None

    # Error tracking
    previous_error: Optional[str] = None
    previous_query: Optional[str] = None
    attempt: int = 0


@dataclass
class COTAgentDependencies:
    """Dependencies for Chain-of-Thought Agent"""
    user_id: str
    user_group: str
    logger_timestamp: str

    # Tool context
    cache: Optional[TTLCache] = None
    tools: Optional[Dict[str, Any]] = None

    # Execution context
    scratchpad: Optional[List] = None
    sub_question_list: Optional[List[str]] = None
    base64_code_list: Optional[List[str]] = None
    code_list: Optional[List[str]] = None
    fig_json_list: Optional[List[str]] = None

    # LLM generator (for backward compatibility)
    llm_generate_response: Optional[Any] = None

    # Custom instructions
    custom_instructions: Optional[str] = None

    # Conversation context
    message: Optional[List[Dict[str, str]]] = None
