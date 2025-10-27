"""
Orchestrator Dependencies
Provides context, budget tracking, memory management for the orchestrator agent
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime
from cachetools import TTLCache


@dataclass
class Source:
    """Represents a data source for citation"""
    id: str
    type: str  # "sql_query", "document", "api", "chart"
    content: Any
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class ExecutionStep:
    """Single step in execution"""
    goal: str
    result: Any
    source: Optional[Source] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


class BudgetTracker:
    """
    Track resource consumption (tokens, cost, time)
    Prevents runaway costs and enables budget-aware planning
    """

    def __init__(
        self,
        max_tokens: int = 50000,
        max_cost: float = 5.0,
        max_time: float = 300.0,  # seconds
        max_tool_calls: int = 20
    ):
        self.max_tokens = max_tokens
        self.max_cost = max_cost
        self.max_time = max_time
        self.max_tool_calls = max_tool_calls

        self.consumed_tokens = 0
        self.consumed_cost = 0.0
        self.consumed_time = 0.0
        self.tool_calls = 0
        self.start_time = datetime.now()

        # Pricing (per 1K tokens) - GPT-4o
        self.pricing = {
            "gpt-4o": {
                "input": 0.0025,   # $2.50 per 1M input tokens
                "output": 0.010    # $10.00 per 1M output tokens
            }
        }

    def track_llm_call(self, usage: Dict[str, int], model: str = "gpt-4o"):
        """Track LLM token usage and cost"""
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        total_tokens = usage.get("total_tokens", input_tokens + output_tokens)

        self.consumed_tokens += total_tokens

        # Calculate cost
        pricing = self.pricing.get(model, self.pricing["gpt-4o"])
        cost = (
            (input_tokens / 1000) * pricing["input"] +
            (output_tokens / 1000) * pricing["output"]
        )
        self.consumed_cost += cost

    def track_tool_call(self, tool_name: str, latency: float):
        """Track tool call"""
        self.tool_calls += 1
        self.consumed_time += latency

    def get_elapsed_time(self) -> float:
        """Get total elapsed time"""
        return (datetime.now() - self.start_time).total_seconds()

    def is_over_budget(self) -> bool:
        """Check if any limit exceeded"""
        return (
            self.consumed_tokens >= self.max_tokens or
            self.consumed_cost >= self.max_cost or
            self.get_elapsed_time() >= self.max_time or
            self.tool_calls >= self.max_tool_calls
        )

    def get_remaining(self) -> Dict[str, float]:
        """Get remaining budget"""
        return {
            "tokens": max(0, self.max_tokens - self.consumed_tokens),
            "cost": max(0, self.max_cost - self.consumed_cost),
            "time": max(0, self.max_time - self.get_elapsed_time()),
            "tool_calls": max(0, self.max_tool_calls - self.tool_calls)
        }

    def get_consumed(self) -> Dict[str, float]:
        """Get consumed resources"""
        return {
            "tokens": self.consumed_tokens,
            "cost": round(self.consumed_cost, 4),
            "time": round(self.get_elapsed_time(), 2),
            "tool_calls": self.tool_calls
        }

    def get_budget_status(self) -> str:
        """Get budget status message"""
        remaining = self.get_remaining()
        consumed = self.get_consumed()

        status = f"Budget Status:\n"
        status += f"  Tokens: {consumed['tokens']}/{self.max_tokens} ({remaining['tokens']} remaining)\n"
        status += f"  Cost: ${consumed['cost']:.4f}/${self.max_cost:.2f} (${remaining['cost']:.4f} remaining)\n"
        status += f"  Time: {consumed['time']:.1f}s/{self.max_time:.0f}s ({remaining['time']:.1f}s remaining)\n"
        status += f"  Tool Calls: {consumed['tool_calls']}/{self.max_tool_calls} ({remaining['tool_calls']} remaining)"

        return status


class MemoryManager:
    """
    Manage execution memory, scratchpad, and sources
    Enables context passing and citation tracking
    """

    def __init__(self):
        self.scratchpad: List[ExecutionStep] = []
        self.sources: List[Source] = []
        self.cache: TTLCache = TTLCache(maxsize=100, ttl=3600)
        self.metadata: Dict[str, Any] = {}

    def add_step(
        self,
        goal: str,
        result: Any,
        source: Optional[Source] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Add execution step to scratchpad"""
        step = ExecutionStep(
            goal=goal,
            result=result,
            source=source,
            metadata=metadata or {}
        )
        self.scratchpad.append(step)

        # Track source separately for citations
        if source:
            self.sources.append(source)

    def add_source(
        self,
        source_id: str,
        source_type: str,
        content: Any,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Add a source for citation"""
        source = Source(
            id=source_id,
            type=source_type,
            content=content,
            metadata=metadata or {}
        )
        self.sources.append(source)

    def get_scratchpad_text(self) -> str:
        """Get scratchpad as formatted text"""
        if not self.scratchpad:
            return "No execution steps yet."

        lines = []
        for i, step in enumerate(self.scratchpad, 1):
            lines.append(f"Step {i}: {step.goal}")
            lines.append(f"Result: {step.result}")
            if step.source:
                lines.append(f"Source: {step.source.type} ({step.source.id})")
            lines.append("")

        return "\n".join(lines)

    def get_sources_for_citation(self) -> List[Dict[str, Any]]:
        """Get sources formatted for citation"""
        return [
            {
                "id": source.id,
                "type": source.type,
                "content": str(source.content)[:200],  # Truncate for display
                "metadata": source.metadata
            }
            for source in self.sources
        ]

    def get_last_step(self) -> Optional[ExecutionStep]:
        """Get the most recent execution step"""
        return self.scratchpad[-1] if self.scratchpad else None

    def get_context_for_planning(self) -> str:
        """Get relevant context for planning"""
        if not self.scratchpad:
            return "No previous execution context."

        # Get last 3 steps for context
        recent_steps = self.scratchpad[-3:]
        lines = ["Recent execution context:"]
        for step in recent_steps:
            lines.append(f"  - {step.goal}: {str(step.result)[:100]}")

        return "\n".join(lines)

    def clear(self):
        """Clear all memory"""
        self.scratchpad.clear()
        self.sources.clear()
        self.cache.clear()
        self.metadata.clear()


@dataclass
class OrchestratorDependencies:
    """
    Dependencies for Orchestrator Agent
    Provides all context needed for orchestration
    """
    # User context
    user_id: str
    user_group: str
    logger_timestamp: str
    original_query: str

    # Budget tracking
    budget_tracker: BudgetTracker

    # Memory management
    memory: MemoryManager

    # MCP client for tool calls
    mcp_client: Any

    # LLM wrapper for backward compatibility
    llm_generate_response: Optional[Any] = None

    # Available tools (from MCP registry)
    available_tools: Optional[List[Dict[str, Any]]] = None

    # Additional context
    custom_instructions: Optional[str] = None
    message_history: Optional[List[Dict[str, str]]] = None
