"""
A2A (Agent-to-Agent) Protocol - 2025 Specification Compliant
Enables structured communication between AI agents using the official A2A protocol
Reference: https://github.com/google/a2a-protocol

This implementation combines:
1. Official A2A Protocol (JSON-RPC 2.0, Agent Card, Task lifecycle)
2. Domain-specific extensions for airport operations (signals, policies, guardrails)
3. Integration with existing MCP tool infrastructure
"""
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Literal, Union
from datetime import datetime
from enum import Enum
import uuid


# ============================================================================
# Official A2A Protocol - Core Data Structures
# ============================================================================

class TaskStatus(str, Enum):
    """Task lifecycle states per A2A spec"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class AgentCard:
    """
    Agent Card - Official A2A format
    Describes an agent's capabilities and how to interact with it
    """
    id: str  # Unique agent identifier
    name: str
    description: str
    version: str
    capabilities: List[str]  # List of capability URNs
    endpoints: Dict[str, str]  # {"rpc": "http://...", "grpc": "grpc://..."}
    schemas: Dict[str, Any] = field(default_factory=dict)  # JSON schemas for tasks
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict"""
        return asdict(self)


@dataclass
class Task:
    """
    Task object - Official A2A format
    Represents a unit of work passed between agents
    """
    id: str  # Unique task ID
    capability: str  # URN identifying the capability (e.g., "urn:a2a:sql:query")
    params: Dict[str, Any]  # Task-specific parameters
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict"""
        d = asdict(self)
        d["created_at"] = self.created_at.isoformat()
        d["updated_at"] = self.updated_at.isoformat()
        d["status"] = self.status.value
        return d


@dataclass
class A2AMessage:
    """
    JSON-RPC 2.0 message format for A2A communication
    """
    jsonrpc: str = "2.0"
    id: Optional[str] = None
    method: Optional[str] = None  # For requests
    params: Optional[Dict[str, Any]] = None  # For requests
    result: Optional[Any] = None  # For responses
    error: Optional[Dict[str, str]] = None  # For errors

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict"""
        d = {"jsonrpc": self.jsonrpc}
        if self.id:
            d["id"] = self.id
        if self.method:
            d["method"] = self.method
        if self.params is not None:
            d["params"] = self.params
        if self.result is not None:
            d["result"] = self.result
        if self.error:
            d["error"] = self.error
        return d


# ============================================================================
# Domain-Specific Extensions for Airport Operations
# ============================================================================

class AgentRole(str, Enum):
    """Agent roles in the airport operations A2A system"""
    DECISION = "Decision"
    SIGNAL = "Signal"  # Renamed from T2SQL
    POLICY = "Policy"
    GUARDRAIL = "Guardrail"
    OPS = "Ops"


@dataclass
class SignalRequest:
    """Request for a specific signal/data point"""
    name: str
    args: Dict[str, Any] = field(default_factory=dict)
    catalog_version: str = "v1"
    nl_prompt: Optional[str] = None
    sql_template: Optional[str] = None
    dtype: str = "str"  # int, float, str, bool, json


@dataclass
class SignalValue:
    """Response with signal data"""
    name: str
    ok: bool
    value: Any
    dtype: str
    source: str  # "sql", "api", "cache", "default"
    freshness_s: Optional[float] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class DecisionAction:
    """Single action in a decision bundle"""
    action: str  # "DEPLOY_ROBOT", "DISPATCH_HUMAN", "ALERT", etc.
    target: str  # "zone_A", "janitor_001", etc.
    zone_tags: List[str] = field(default_factory=list)
    rationale: str = ""
    priority: int = 5  # 1-10
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DecisionBundle:
    """Complete decision output"""
    policy_version: str
    score: float  # 0.0-1.0 confidence
    actions: List[DecisionAction]
    notes: Optional[str] = None
    requires_hitl: bool = False
    hitl_reason: Optional[str] = None
    signals_used: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Context:
    """Normalized context for decision making"""
    scenario: str
    terminal: str
    airport_code: str
    timestamp: datetime
    signals: Dict[str, SignalValue]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_signal_value(self, name: str, default: Any = None) -> Any:
        """Get signal value safely"""
        signal = self.signals.get(name)
        if signal and signal.ok:
            return signal.value
        return default

    def get_signal(self, name: str) -> Optional[SignalValue]:
        """Get full signal object"""
        return self.signals.get(name)


# ============================================================================
# A2A Protocol Helper Functions
# ============================================================================

def create_task(
    capability: str,
    params: Dict[str, Any],
    task_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Task:
    """
    Create a new A2A Task

    Args:
        capability: URN identifying the capability (e.g., "urn:a2a:sql:query")
        params: Task-specific parameters
        task_id: Optional task ID (generates UUID if not provided)
        metadata: Optional metadata

    Returns:
        Task object
    """
    return Task(
        id=task_id or str(uuid.uuid4()),
        capability=capability,
        params=params,
        metadata=metadata or {}
    )


def create_a2a_request(
    method: str,
    params: Dict[str, Any],
    request_id: Optional[str] = None
) -> A2AMessage:
    """
    Create a JSON-RPC 2.0 request message

    Args:
        method: Method name (e.g., "execute_task", "get_signals")
        params: Method parameters
        request_id: Optional request ID

    Returns:
        A2AMessage configured as a request
    """
    return A2AMessage(
        jsonrpc="2.0",
        id=request_id or str(uuid.uuid4()),
        method=method,
        params=params
    )


def create_a2a_response(
    request_id: str,
    result: Optional[Any] = None,
    error: Optional[Dict[str, str]] = None
) -> A2AMessage:
    """
    Create a JSON-RPC 2.0 response message

    Args:
        request_id: ID from the request message
        result: Response result (only if successful)
        error: Error object with code and message (only if failed)

    Returns:
        A2AMessage configured as a response
    """
    return A2AMessage(
        jsonrpc="2.0",
        id=request_id,
        result=result,
        error=error
    )


def normalize_signals_to_context(
    scenario: str,
    terminal: str,
    airport_code: str,
    signals: List[SignalValue]
) -> Context:
    """Convert signal list to typed context"""
    signals_dict = {signal.name: signal for signal in signals}
    return Context(
        scenario=scenario,
        terminal=terminal,
        airport_code=airport_code,
        timestamp=datetime.now(),
        signals=signals_dict
    )


def create_agent_card(
    agent_id: str,
    name: str,
    description: str,
    version: str,
    capabilities: List[str],
    endpoints: Dict[str, str],
    schemas: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> AgentCard:
    """
    Create an Agent Card for agent discovery and capability advertising

    Args:
        agent_id: Unique agent identifier
        name: Human-readable agent name
        description: Agent description
        version: Agent version
        capabilities: List of capability URNs
        endpoints: Dict of endpoint types to URLs
        schemas: Optional JSON schemas for task types
        metadata: Optional additional metadata

    Returns:
        AgentCard object
    """
    return AgentCard(
        id=agent_id,
        name=name,
        description=description,
        version=version,
        capabilities=capabilities,
        endpoints=endpoints,
        schemas=schemas or {},
        metadata=metadata or {}
    )
