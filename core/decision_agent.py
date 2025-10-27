"""
Decision Agent - Airport Operations Decision Making with A2A Protocol

Main orchestrator agent that coordinates multi-agent decision making for
airport operations scenarios (janitorial, security, resource allocation, etc.)

Architecture:
1. Load scenario playbook (YAML)
2. Retrieve required signals via Signal Agent (A2A)
3. Build context from signals
4. Execute policy module (pure function)
5. Check guardrails
6. Determine HITL requirement
7. Return DecisionBundle

Agent Card:
{
  "id": "decision-agent",
  "name": "Airport Decision Agent",
  "version": "1.0.0",
  "capabilities": [
    "urn:airport:decision:execute",
    "urn:airport:decision:simulate",
    "urn:airport:playbook:list"
  ]
}
"""
import os
import yaml
from typing import Dict, Any, List, Optional
from termcolor import colored
from datetime import datetime
import importlib.util

from core.a2a_protocol import (
    AgentCard, Task, TaskStatus, Context, DecisionBundle, DecisionAction,
    SignalValue, create_agent_card, create_task
)
from core.signal_agent import retrieve_signals_batch, get_signal_agent


# ============================================================================
# Playbook Manager
# ============================================================================

class PlaybookManager:
    """Manages scenario playbooks loaded from YAML"""

    def __init__(self, playbooks_dir: str = None):
        if playbooks_dir is None:
            playbooks_dir = os.path.join(
                os.path.dirname(__file__),
                "..",
                "config",
                "playbooks"
            )
        self.playbooks_dir = playbooks_dir
        self.playbooks: Dict[str, Dict[str, Any]] = {}
        self.load_all_playbooks()

    def load_all_playbooks(self):
        """Load all playbooks from the playbooks directory"""
        try:
            if not os.path.exists(self.playbooks_dir):
                print(colored(f"⚠️  Playbooks directory not found: {self.playbooks_dir}", "yellow"))
                return

            for filename in os.listdir(self.playbooks_dir):
                if filename.endswith(".yaml") or filename.endswith(".yml"):
                    filepath = os.path.join(self.playbooks_dir, filename)
                    self.load_playbook(filepath)

            print(colored(f"✅ Loaded {len(self.playbooks)} playbooks", "green"))
        except Exception as e:
            print(colored(f"❌ Failed to load playbooks: {str(e)}", "red"))

    def load_playbook(self, filepath: str):
        """Load a single playbook from file"""
        try:
            with open(filepath, "r") as f:
                data = yaml.safe_load(f)
                scenario = data.get("scenario")
                if scenario:
                    self.playbooks[scenario] = data
                    print(colored(f"   Loaded playbook: {scenario}", "cyan"))
        except Exception as e:
            print(colored(f"❌ Failed to load playbook {filepath}: {str(e)}", "red"))

    def get_playbook(self, scenario: str) -> Optional[Dict[str, Any]]:
        """Get playbook for a scenario"""
        return self.playbooks.get(scenario)

    def list_scenarios(self) -> List[str]:
        """List all available scenarios"""
        return list(self.playbooks.keys())


# ============================================================================
# Guardrail Checker
# ============================================================================

class GuardrailChecker:
    """Checks guardrails and determines actions"""

    @staticmethod
    def check_guardrails(
        context: Context,
        guardrails: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Check all guardrails against the context

        Returns:
            {
                "passed": bool,
                "triggered": List[Dict],
                "requires_hitl": bool,
                "hitl_reason": Optional[str]
            }
        """
        triggered_guardrails = []
        requires_hitl = False
        hitl_reasons = []

        for guardrail in guardrails:
            name = guardrail.get("name")
            condition = guardrail.get("condition")
            action = guardrail.get("action")
            severity = guardrail.get("severity", "warning")
            message = guardrail.get("message", "")

            try:
                # Evaluate condition
                # Build evaluation context with signal values
                eval_context = {}
                for signal_name, signal_value in context.signals.items():
                    if signal_value.ok:
                        eval_context[signal_name] = signal_value.value

                # Evaluate the condition string
                if GuardrailChecker._evaluate_condition(condition, eval_context):
                    print(colored(f"⚠️  Guardrail triggered: {name}", "yellow"))
                    print(colored(f"   Condition: {condition}", "yellow"))
                    print(colored(f"   Action: {action}", "yellow"))

                    triggered_guardrails.append({
                        "name": name,
                        "condition": condition,
                        "action": action,
                        "severity": severity,
                        "message": message
                    })

                    # Check if requires HITL
                    if action == "require_hitl" or severity == "critical":
                        requires_hitl = True
                        hitl_reasons.append(message)

            except Exception as e:
                print(colored(f"❌ Error evaluating guardrail {name}: {str(e)}", "red"))

        passed = len(triggered_guardrails) == 0

        return {
            "passed": passed,
            "triggered": triggered_guardrails,
            "requires_hitl": requires_hitl,
            "hitl_reason": "; ".join(hitl_reasons) if hitl_reasons else None
        }

    @staticmethod
    def _evaluate_condition(condition: str, context: Dict[str, Any]) -> bool:
        """
        Safely evaluate a condition string with the given context

        Examples:
            condition: "current_occupancy_percent >= 80"
            context: {"current_occupancy_percent": 85}
            returns: True
        """
        try:
            # Replace variable names with their values
            eval_str = condition
            for key, value in context.items():
                # Handle different types
                if isinstance(value, str):
                    eval_str = eval_str.replace(key, f'"{value}"')
                elif isinstance(value, bool):
                    eval_str = eval_str.replace(key, str(value))
                elif value is None:
                    eval_str = eval_str.replace(key, "None")
                else:
                    eval_str = eval_str.replace(key, str(value))

            # Evaluate (restricted to basic comparisons)
            result = eval(eval_str, {"__builtins__": {}}, {})
            return bool(result)

        except Exception as e:
            print(colored(f"❌ Condition evaluation error: {str(e)}", "red"))
            print(colored(f"   Condition: {condition}", "red"))
            return False


# ============================================================================
# HITL Decision System
# ============================================================================

class HITLDecisionSystem:
    """Determines if human-in-the-loop approval is required"""

    @staticmethod
    def check_hitl_requirement(
        decision_bundle: DecisionBundle,
        hitl_config: Dict[str, Any],
        guardrail_result: Dict[str, Any]
    ) -> tuple[bool, Optional[str]]:
        """
        Check if HITL is required based on:
        1. Guardrails
        2. Confidence score threshold
        3. Action types

        Returns:
            (requires_hitl: bool, reason: str)
        """
        reasons = []

        # Check guardrails
        if guardrail_result.get("requires_hitl"):
            reasons.append(f"Guardrails: {guardrail_result.get('hitl_reason')}")

        # Check confidence threshold
        score_threshold = hitl_config.get("score_threshold", 0.7)
        if decision_bundle.score < score_threshold:
            reasons.append(f"Low confidence: {decision_bundle.score:.2f} < {score_threshold}")

        # Check action types
        require_approval_actions = hitl_config.get("require_approval_actions", [])
        for action in decision_bundle.actions:
            if action.action in require_approval_actions:
                reasons.append(f"Action requires approval: {action.action}")

        requires_hitl = len(reasons) > 0

        return requires_hitl, "; ".join(reasons) if reasons else None


# ============================================================================
# Decision Agent
# ============================================================================

class DecisionAgent:
    """
    Main decision agent that orchestrates multi-agent decision making
    """

    def __init__(self):
        self.playbook_manager = PlaybookManager()
        self.signal_agent = get_signal_agent()
        self.agent_card = self._create_agent_card()
        self.policy_modules: Dict[str, Any] = {}

    def _create_agent_card(self) -> AgentCard:
        """Create agent card for this agent"""
        return create_agent_card(
            agent_id="decision-agent",
            name="Airport Decision Agent",
            description="Orchestrates multi-agent decision making for airport operations",
            version="1.0.0",
            capabilities=[
                "urn:airport:decision:execute",
                "urn:airport:decision:simulate",
                "urn:airport:playbook:list"
            ],
            endpoints={
                "rpc": "internal"
            },
            metadata={
                "scenarios": self.playbook_manager.list_scenarios()
            }
        )

    def get_agent_card(self) -> Dict[str, Any]:
        """Return agent card as dict"""
        return self.agent_card.to_dict()

    async def execute_decision(
        self,
        scenario: str,
        airport_code: str,
        terminal: str,
        user_id: str = "system",
        user_group: str = "default",
        logger_timestamp: Optional[str] = None,
        simulate: bool = False
    ) -> DecisionBundle:
        """
        Execute decision-making for a scenario

        Args:
            scenario: Scenario name (e.g., "janitorial_ops")
            airport_code: Airport code (e.g., "SFO")
            terminal: Terminal identifier (e.g., "A")
            user_id: User identifier
            user_group: User group
            logger_timestamp: Logging timestamp
            simulate: If True, don't execute actions (dry run)

        Returns:
            DecisionBundle with actions and metadata
        """
        if logger_timestamp is None:
            logger_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        print(colored(f"\n{'='*80}", "cyan", attrs=["bold"]))
        print(colored(f"🎯 Decision Agent - {scenario}", "cyan", attrs=["bold"]))
        print(colored(f"{'='*80}\n", "cyan"))

        # Step 1: Load playbook
        print(colored("📖 Step 1: Loading playbook...", "cyan"))
        playbook = self.playbook_manager.get_playbook(scenario)
        if not playbook:
            raise ValueError(f"Playbook not found for scenario: {scenario}")

        print(colored(f"   Playbook: {playbook.get('description')}", "cyan"))
        print(colored(f"   Version: {playbook.get('version')}", "cyan"))
        print(colored(f"   Required signals: {len(playbook.get('required_signals', []))}", "cyan"))

        # Step 2: Retrieve signals
        print(colored("\n🔍 Step 2: Retrieving signals...", "cyan"))
        required_signals = playbook.get("required_signals", [])

        signal_requests = [
            {
                "signal_name": signal_name,
                "args": {
                    "airport_code": airport_code,
                    "terminal": terminal
                }
            }
            for signal_name in required_signals
        ]

        signals = await retrieve_signals_batch(
            signal_requests=signal_requests,
            user_id=user_id,
            user_group=user_group,
            logger_timestamp=logger_timestamp
        )

        print(colored(f"   Retrieved: {len(signals)} signals", "green"))
        print(colored(f"   Success: {sum(1 for s in signals if s.ok)}/{len(signals)}", "green"))

        # Step 3: Build context
        print(colored("\n🏗️  Step 3: Building context...", "cyan"))
        context = Context(
            scenario=scenario,
            terminal=terminal,
            airport_code=airport_code,
            timestamp=datetime.now(),
            signals={s.name: s for s in signals}
        )

        # Step 4: Run policy module
        print(colored("\n⚙️  Step 4: Running policy module...", "cyan"))
        policy_module_name = playbook.get("policy_module")
        if not policy_module_name:
            raise ValueError(f"No policy module specified in playbook for scenario: {scenario}")

        decision_bundle = self._run_policy_module(policy_module_name, context, playbook)

        print(colored(f"   Actions: {len(decision_bundle.actions)}", "green"))
        print(colored(f"   Confidence: {decision_bundle.score:.2f}", "green"))

        # Step 5: Check guardrails
        print(colored("\n🛡️  Step 5: Checking guardrails...", "cyan"))
        guardrails = playbook.get("guardrails", [])
        guardrail_result = GuardrailChecker.check_guardrails(context, guardrails)

        print(colored(f"   Passed: {guardrail_result['passed']}", "green" if guardrail_result['passed'] else "yellow"))
        if guardrail_result['triggered']:
            print(colored(f"   Triggered: {len(guardrail_result['triggered'])} guardrails", "yellow"))

        # Step 6: Determine HITL requirement
        print(colored("\n👤 Step 6: Checking HITL requirement...", "cyan"))
        hitl_config = playbook.get("hitl_config", {})
        requires_hitl, hitl_reason = HITLDecisionSystem.check_hitl_requirement(
            decision_bundle, hitl_config, guardrail_result
        )

        decision_bundle.requires_hitl = requires_hitl
        decision_bundle.hitl_reason = hitl_reason

        if requires_hitl:
            print(colored(f"   ⚠️  HITL Required: {hitl_reason}", "yellow"))
        else:
            print(colored(f"   ✅ Auto-approve enabled", "green"))

        # Step 7: Add metadata
        decision_bundle.metadata.update({
            "scenario": scenario,
            "airport_code": airport_code,
            "terminal": terminal,
            "timestamp": datetime.now().isoformat(),
            "guardrails": guardrail_result,
            "simulate": simulate
        })

        print(colored(f"\n{'='*80}", "cyan"))
        print(colored(f"✅ Decision Agent Completed", "green", attrs=["bold"]))
        print(colored(f"{'='*80}\n", "cyan"))

        return decision_bundle

    def _run_policy_module(
        self,
        policy_module_name: str,
        context: Context,
        playbook: Dict[str, Any]
    ) -> DecisionBundle:
        """
        Run a policy module (pure function) to generate decisions

        The policy module should be a Python file in policies/ directory
        with a function: execute_policy(context: Context, playbook: Dict) -> DecisionBundle
        """
        try:
            # Try to load policy module
            policy_path = os.path.join(
                os.path.dirname(__file__),
                "..",
                "policies",
                f"{policy_module_name}.py"
            )

            if not os.path.exists(policy_path):
                print(colored(f"⚠️  Policy module not found: {policy_path}", "yellow"))
                print(colored(f"   Using default policy...", "yellow"))
                return self._default_policy(context, playbook)

            # Load the module dynamically
            spec = importlib.util.spec_from_file_location(policy_module_name, policy_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Call the execute_policy function
            if hasattr(module, "execute_policy"):
                print(colored(f"   Executing policy: {policy_module_name}", "cyan"))
                return module.execute_policy(context, playbook)
            else:
                raise ValueError(f"Policy module {policy_module_name} missing execute_policy function")

        except Exception as e:
            print(colored(f"❌ Error running policy module: {str(e)}", "red"))
            print(colored(f"   Using default policy...", "yellow"))
            return self._default_policy(context, playbook)

    def _default_policy(self, context: Context, playbook: Dict[str, Any]) -> DecisionBundle:
        """
        Default policy when specific policy module is not found

        Returns a simple decision bundle based on basic rules
        """
        actions = [
            DecisionAction(
                action="MONITOR",
                target="all_zones",
                rationale="Default policy - monitoring mode",
                priority=5
            )
        ]

        return DecisionBundle(
            policy_version="default_v1",
            score=0.5,
            actions=actions,
            notes="Using default policy - specific policy module not found",
            requires_hitl=True,
            hitl_reason="Default policy requires approval",
            signals_used=list(context.signals.keys())
        )


# ============================================================================
# Global Decision Agent Instance
# ============================================================================

_decision_agent_instance: Optional[DecisionAgent] = None


def get_decision_agent() -> DecisionAgent:
    """Get or create the global Decision Agent instance"""
    global _decision_agent_instance
    if _decision_agent_instance is None:
        _decision_agent_instance = DecisionAgent()
    return _decision_agent_instance
