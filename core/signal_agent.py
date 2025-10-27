"""
Signal Agent - A2A Protocol Wrapper for Signal Data Retrieval

This agent wraps the existing SQL_Agent_MCP to provide signal data retrieval
using the official A2A protocol (2025 specification).

Capabilities:
- urn:airport:signal:retrieve - Retrieve single signal value
- urn:airport:signal:batch - Retrieve multiple signals
- urn:airport:signal:catalog - Get available signals from catalog

Agent Card:
{
  "id": "signal-agent",
  "name": "Airport Signal Agent",
  "version": "1.0.0",
  "capabilities": [
    "urn:airport:signal:retrieve",
    "urn:airport:signal:batch",
    "urn:airport:signal:catalog"
  ]
}
"""
import os
import yaml
from typing import Dict, Any, List, Optional
from termcolor import colored
from datetime import datetime

from core.a2a_protocol import (
    AgentCard, Task, TaskStatus, A2AMessage, SignalRequest, SignalValue,
    create_agent_card, create_a2a_response
)
from core.Agent_SQL_pydantic_mcp import SQL_Agent_MCP


# ============================================================================
# Signal Catalog Manager
# ============================================================================

class SignalCatalog:
    """Manages the signal catalog loaded from YAML"""

    def __init__(self, catalog_path: str = None):
        if catalog_path is None:
            catalog_path = os.path.join(
                os.path.dirname(__file__),
                "..",
                "config",
                "signal_catalog.yaml"
            )
        self.catalog_path = catalog_path
        self.catalog: Dict[str, Any] = {}
        self.load_catalog()

    def load_catalog(self):
        """Load signal catalog from YAML"""
        try:
            with open(self.catalog_path, "r") as f:
                data = yaml.safe_load(f)
                self.catalog = data.get("signals", {})
            print(colored(f"✅ Loaded {len(self.catalog)} signals from catalog", "green"))
        except Exception as e:
            print(colored(f"❌ Failed to load signal catalog: {str(e)}", "red"))
            self.catalog = {}

    def get_signal_definition(self, signal_name: str) -> Optional[Dict[str, Any]]:
        """Get signal definition from catalog"""
        return self.catalog.get(signal_name)

    def list_signals(self) -> List[str]:
        """List all available signal names"""
        return list(self.catalog.keys())

    def get_all_signals(self) -> Dict[str, Any]:
        """Get entire catalog"""
        return self.catalog


# ============================================================================
# Signal Agent
# ============================================================================

class SignalAgent:
    """
    A2A-compliant agent for retrieving signal data from databases

    Uses existing SQL_Agent_MCP internally but provides A2A protocol interface
    """

    def __init__(self):
        self.catalog = SignalCatalog()
        self.agent_card = self._create_agent_card()

    def _create_agent_card(self) -> AgentCard:
        """Create agent card for this agent"""
        return create_agent_card(
            agent_id="signal-agent",
            name="Airport Signal Agent",
            description="Retrieves real-time signal data from airport databases",
            version="1.0.0",
            capabilities=[
                "urn:airport:signal:retrieve",
                "urn:airport:signal:batch",
                "urn:airport:signal:catalog"
            ],
            endpoints={
                "rpc": "internal"  # Internal agent, not exposed via HTTP
            },
            metadata={
                "signal_count": len(self.catalog.list_signals()),
                "catalog_version": "v1"
            }
        )

    def get_agent_card(self) -> Dict[str, Any]:
        """Return agent card as dict"""
        return self.agent_card.to_dict()

    async def handle_task(self, task: Task) -> Task:
        """
        Handle an A2A Task

        Args:
            task: Task object with capability and params

        Returns:
            Updated Task object with result or error
        """
        task.status = TaskStatus.IN_PROGRESS
        task.updated_at = datetime.now()

        try:
            if task.capability == "urn:airport:signal:retrieve":
                result = await self._retrieve_signal(task.params)
            elif task.capability == "urn:airport:signal:batch":
                result = await self._retrieve_batch(task.params)
            elif task.capability == "urn:airport:signal:catalog":
                result = self._get_catalog(task.params)
            else:
                raise ValueError(f"Unknown capability: {task.capability}")

            task.status = TaskStatus.COMPLETED
            task.result = result
            task.updated_at = datetime.now()

        except Exception as e:
            print(colored(f"❌ Signal Agent Error: {str(e)}", "red"))
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.updated_at = datetime.now()

        return task

    async def _retrieve_signal(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Retrieve a single signal value

        Expected params:
            - signal_name: str
            - args: Dict[str, Any] (e.g., {"airport_code": "SFO", "terminal": "A"})
            - user_id: str
            - user_group: str
            - logger_timestamp: str
        """
        signal_name = params.get("signal_name")
        args = params.get("args", {})
        user_id = params.get("user_id", "system")
        user_group = params.get("user_group", "default")
        logger_timestamp = params.get("logger_timestamp", datetime.now().strftime("%Y%m%d_%H%M%S"))

        print(colored(f"\n🔍 Retrieving signal: {signal_name}", "cyan"))
        print(colored(f"   Args: {args}", "cyan"))

        # Get signal definition from catalog
        signal_def = self.catalog.get_signal_definition(signal_name)
        if not signal_def:
            raise ValueError(f"Signal '{signal_name}' not found in catalog")

        # Build natural language prompt from signal definition
        nl_prompt = signal_def.get("nl_prompt", signal_def.get("description", ""))

        # Substitute args into prompt
        for key, value in args.items():
            nl_prompt = nl_prompt.replace(f"{{{key}}}", str(value))

        print(colored(f"   NL Prompt: {nl_prompt}", "cyan"))

        # Initialize MOI_OPS database with descriptions for signal queries
        try:
            from core.moi_ops_db_loader import initialize_moi_ops_for_signals
            import core.globals as globals

            # Load MOI_OPS database configuration
            db_name, db_schema, descriptions, dialect = initialize_moi_ops_for_signals(user_group)

            if not db_name:
                raise RuntimeError("Failed to initialize MOI_OPS database for signal retrieval")

            # Force database cache to use MOI_OPS for this query
            cache_key = (user_id, user_group)
            original_cache = globals.db_cache.get(cache_key)

            try:
                # Override cache to force MOI_OPS database selection
                globals.db_cache[cache_key] = (db_name, db_schema, descriptions, dialect)
                print(colored(f"   🔄 Forced database to: {db_name} with {len(descriptions)} table descriptions", "yellow"))

                # Use existing SQL agent to execute query
                data, sql_query, df_info, query_id = await SQL_Agent_MCP(
                    userText=nl_prompt,
                    user_id=user_id,
                    user_group=user_group,
                    logger_timestamp_mod=logger_timestamp,
                    tool_id=f"signal_{signal_name}",
                    tag="signal_retrieval"
                )

            finally:
                # Restore original cache after query
                if original_cache:
                    globals.db_cache[cache_key] = original_cache
                else:
                    globals.db_cache.pop(cache_key, None)

            # Parse the result to extract the actual value
            # The SQL query should return a single value in the 'value' column
            value = self._extract_value_from_data(data, signal_def.get("dtype", "str"))

            signal_value = SignalValue(
                name=signal_name,
                ok=True,
                value=value,
                dtype=signal_def.get("dtype", "str"),
                source="sql",
                freshness_s=None,  # TODO: Calculate from query execution time
                metadata={
                    "sql_query": sql_query,
                    "query_id": query_id,
                    "args": args
                }
            )

            print(colored(f"✅ Signal retrieved: {signal_name} = {value}", "green"))

            return {
                "signal": {
                    "name": signal_value.name,
                    "ok": signal_value.ok,
                    "value": signal_value.value,
                    "dtype": signal_value.dtype,
                    "source": signal_value.source,
                    "freshness_s": signal_value.freshness_s,
                    "metadata": signal_value.metadata,
                    "timestamp": signal_value.timestamp.isoformat()
                }
            }

        except Exception as e:
            print(colored(f"❌ Failed to retrieve signal: {str(e)}", "red"))
            signal_value = SignalValue(
                name=signal_name,
                ok=False,
                value=signal_def.get("default"),
                dtype=signal_def.get("dtype", "str"),
                source="default",
                error=str(e)
            )

            return {
                "signal": {
                    "name": signal_value.name,
                    "ok": signal_value.ok,
                    "value": signal_value.value,
                    "dtype": signal_value.dtype,
                    "source": signal_value.source,
                    "error": signal_value.error,
                    "timestamp": signal_value.timestamp.isoformat()
                }
            }

    async def _retrieve_batch(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Retrieve multiple signals in batch

        Expected params:
            - signal_requests: List[Dict] with signal_name and args for each
            - user_id: str
            - user_group: str
            - logger_timestamp: str
        """
        signal_requests = params.get("signal_requests", [])
        user_id = params.get("user_id", "system")
        user_group = params.get("user_group", "default")
        logger_timestamp = params.get("logger_timestamp", datetime.now().strftime("%Y%m%d_%H%M%S"))

        print(colored(f"\n🔍 Retrieving batch of {len(signal_requests)} signals", "cyan"))

        signals = []
        for req in signal_requests:
            signal_name = req.get("signal_name")
            args = req.get("args", {})

            # Call single signal retrieval
            result = await self._retrieve_signal({
                "signal_name": signal_name,
                "args": args,
                "user_id": user_id,
                "user_group": user_group,
                "logger_timestamp": logger_timestamp
            })

            signals.append(result["signal"])

        print(colored(f"✅ Retrieved {len(signals)} signals", "green"))

        return {
            "signals": signals,
            "total_count": len(signals),
            "success_count": sum(1 for s in signals if s["ok"]),
            "failure_count": sum(1 for s in signals if not s["ok"])
        }

    def _get_catalog(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get signal catalog information

        Expected params:
            - signal_names: Optional[List[str]] - specific signals to get, or all if None
        """
        signal_names = params.get("signal_names")

        if signal_names:
            # Return specific signals
            signals_info = {
                name: self.catalog.get_signal_definition(name)
                for name in signal_names
                if self.catalog.get_signal_definition(name) is not None
            }
        else:
            # Return all signals
            signals_info = self.catalog.get_all_signals()

        return {
            "catalog_version": "v1",
            "signals": signals_info,
            "total_count": len(signals_info)
        }

    def _extract_value_from_data(self, data: str, dtype: str) -> Any:
        """
        Extract the actual value from SQL agent response data

        The data is typically a markdown table or text description.
        We need to parse it to extract the 'value' column.
        """
        # Simple parsing: look for "value" in the data
        # This is a simplified version - may need more robust parsing

        # If data contains error message
        if "Error" in data or "error" in data:
            return None

        # Try to extract numeric value if dtype is int or float
        if dtype == "int":
            import re
            match = re.search(r'\b(\d+)\b', data)
            if match:
                return int(match.group(1))
            return 0

        if dtype == "float":
            import re
            match = re.search(r'\b(\d+\.?\d*)\b', data)
            if match:
                return float(match.group(1))
            return 0.0

        if dtype == "bool":
            return "true" in data.lower() or "yes" in data.lower()

        # For string or unknown types, return the data as-is
        return data.strip()


# ============================================================================
# Global Signal Agent Instance
# ============================================================================

_signal_agent_instance: Optional[SignalAgent] = None


def get_signal_agent() -> SignalAgent:
    """Get or create the global Signal Agent instance"""
    global _signal_agent_instance
    if _signal_agent_instance is None:
        _signal_agent_instance = SignalAgent()
    return _signal_agent_instance


# ============================================================================
# Convenience Functions
# ============================================================================

async def retrieve_signal(
    signal_name: str,
    args: Dict[str, Any],
    user_id: str = "system",
    user_group: str = "default",
    logger_timestamp: Optional[str] = None
) -> SignalValue:
    """
    Convenience function to retrieve a single signal

    Args:
        signal_name: Name of signal from catalog
        args: Arguments for signal (e.g., airport_code, terminal)
        user_id: User identifier
        user_group: User group
        logger_timestamp: Logging timestamp

    Returns:
        SignalValue object
    """
    agent = get_signal_agent()

    if logger_timestamp is None:
        logger_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    result = await agent._retrieve_signal({
        "signal_name": signal_name,
        "args": args,
        "user_id": user_id,
        "user_group": user_group,
        "logger_timestamp": logger_timestamp
    })

    signal_data = result["signal"]
    return SignalValue(
        name=signal_data["name"],
        ok=signal_data["ok"],
        value=signal_data["value"],
        dtype=signal_data["dtype"],
        source=signal_data["source"],
        freshness_s=signal_data.get("freshness_s"),
        error=signal_data.get("error"),
        metadata=signal_data.get("metadata", {}),
        timestamp=datetime.fromisoformat(signal_data["timestamp"])
    )


async def retrieve_signals_batch(
    signal_requests: List[Dict[str, Any]],
    user_id: str = "system",
    user_group: str = "default",
    logger_timestamp: Optional[str] = None
) -> List[SignalValue]:
    """
    Convenience function to retrieve multiple signals

    Args:
        signal_requests: List of dicts with signal_name and args
        user_id: User identifier
        user_group: User group
        logger_timestamp: Logging timestamp

    Returns:
        List of SignalValue objects
    """
    agent = get_signal_agent()

    if logger_timestamp is None:
        logger_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    result = await agent._retrieve_batch({
        "signal_requests": signal_requests,
        "user_id": user_id,
        "user_group": user_group,
        "logger_timestamp": logger_timestamp
    })

    signal_values = []
    for signal_data in result["signals"]:
        signal_values.append(SignalValue(
            name=signal_data["name"],
            ok=signal_data["ok"],
            value=signal_data["value"],
            dtype=signal_data["dtype"],
            source=signal_data["source"],
            freshness_s=signal_data.get("freshness_s"),
            error=signal_data.get("error"),
            metadata=signal_data.get("metadata", {}),
            timestamp=datetime.fromisoformat(signal_data["timestamp"])
        ))

    return signal_values
