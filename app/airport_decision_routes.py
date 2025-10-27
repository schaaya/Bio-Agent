"""
Airport Decision API Routes

REST endpoints for triggering A2A multi-agent decision making for airport operations

Endpoints:
- POST /airport/decide - Execute decision for a scenario
- GET /airport/scenarios - List available scenarios
- GET /airport/agent-cards - Get agent cards for all agents
"""
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

from core.decision_agent import get_decision_agent
from core.signal_agent import get_signal_agent
from app.dep import user_verification
from app.schema import SystemUser


router = APIRouter()


# ============================================================================
# Authentication Dependency
# ============================================================================

async def get_current_user(request: Request) -> SystemUser:
    """Extract user from JWT token in cookie or Authorization header"""
    # Try cookie first
    token = request.cookies.get("access_token")

    # If no cookie, try Authorization header
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.replace("Bearer ", "")

    if not token:
        raise HTTPException(status_code=401, detail="No authentication token provided")

    user = await user_verification(token)

    if user.disabled:
        raise HTTPException(status_code=401, detail="User is disabled")

    return user


# ============================================================================
# Request/Response Models
# ============================================================================

class DecisionRequest(BaseModel):
    """Request to execute a decision"""
    scenario: str = Field(..., description="Scenario name (e.g., 'janitorial_ops')")
    airport_code: str = Field(..., description="Airport code (e.g., 'SFO')")
    terminal: str = Field(..., description="Terminal identifier (e.g., 'A')")
    user_id: str = Field(default="system", description="User identifier")
    user_group: str = Field(default="default", description="User group")
    simulate: bool = Field(default=False, description="Simulate only (don't execute actions)")


class ActionResponse(BaseModel):
    """Single action in decision bundle"""
    action: str
    target: str
    zone_tags: List[str]
    rationale: str
    priority: int
    params: Dict[str, Any]


class DecisionResponse(BaseModel):
    """Response from decision execution"""
    policy_version: str
    score: float
    actions: List[ActionResponse]
    notes: Optional[str]
    requires_hitl: bool
    hitl_reason: Optional[str]
    signals_used: List[str]
    metadata: Dict[str, Any]
    timestamp: str


class ScenarioInfo(BaseModel):
    """Information about a scenario"""
    scenario: str
    version: str
    description: str
    required_signals_count: int
    policy_module: str
    guardrails_count: int


class AgentCardResponse(BaseModel):
    """Agent card response"""
    id: str
    name: str
    description: str
    version: str
    capabilities: List[str]
    endpoints: Dict[str, str]
    metadata: Dict[str, Any]


# ============================================================================
# Endpoints
# ============================================================================

@router.post("/airport/decide", response_model=DecisionResponse)
async def execute_decision(
    request: DecisionRequest,
    current_user: SystemUser = Depends(get_current_user)
):
    """
    Execute A2A multi-agent decision making for an airport scenario

    This endpoint:
    1. Loads the scenario playbook
    2. Retrieves required signals via Signal Agent
    3. Executes policy module
    4. Checks guardrails
    5. Determines HITL requirement
    6. Returns DecisionBundle

    Example request:
    ```json
    {
      "scenario": "janitorial_ops",
      "airport_code": "SFO",
      "terminal": "A",
      "simulate": false
    }
    ```
    """
    try:
        # Get decision agent
        decision_agent = get_decision_agent()

        # Execute decision with authenticated user info
        logger_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Use authenticated user's info, override request if provided
        user_id = request.user_id or current_user.email
        user_group = request.user_group or current_user.group_name

        decision_bundle = await decision_agent.execute_decision(
            scenario=request.scenario,
            airport_code=request.airport_code,
            terminal=request.terminal,
            user_id=user_id,
            user_group=user_group,
            logger_timestamp=logger_timestamp,
            simulate=request.simulate
        )

        # Convert actions to response format
        actions_response = [
            ActionResponse(
                action=action.action,
                target=action.target,
                zone_tags=action.zone_tags,
                rationale=action.rationale,
                priority=action.priority,
                params=action.params
            )
            for action in decision_bundle.actions
        ]

        return DecisionResponse(
            policy_version=decision_bundle.policy_version,
            score=decision_bundle.score,
            actions=actions_response,
            notes=decision_bundle.notes,
            requires_hitl=decision_bundle.requires_hitl,
            hitl_reason=decision_bundle.hitl_reason,
            signals_used=decision_bundle.signals_used,
            metadata=decision_bundle.metadata,
            timestamp=datetime.now().isoformat()
        )

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Decision execution failed: {str(e)}")


@router.get("/airport/scenarios", response_model=List[ScenarioInfo])
async def list_scenarios(current_user: SystemUser = Depends(get_current_user)):
    """
    List all available airport decision scenarios

    Returns information about each scenario including:
    - Scenario name and description
    - Required signals count
    - Policy module
    - Guardrails count
    """
    try:
        decision_agent = get_decision_agent()
        playbook_manager = decision_agent.playbook_manager

        scenarios = []
        for scenario_name in playbook_manager.list_scenarios():
            playbook = playbook_manager.get_playbook(scenario_name)
            if playbook:
                scenarios.append(ScenarioInfo(
                    scenario=playbook.get("scenario", scenario_name),
                    version=playbook.get("version", "unknown"),
                    description=playbook.get("description", ""),
                    required_signals_count=len(playbook.get("required_signals", [])),
                    policy_module=playbook.get("policy_module", ""),
                    guardrails_count=len(playbook.get("guardrails", []))
                ))

        return scenarios

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list scenarios: {str(e)}")


@router.get("/airport/agent-cards", response_model=Dict[str, AgentCardResponse])
async def get_agent_cards(current_user: SystemUser = Depends(get_current_user)):
    """
    Get agent cards for all A2A agents

    Returns agent cards for:
    - Decision Agent
    - Signal Agent

    Agent cards describe capabilities, endpoints, and metadata
    """
    try:
        decision_agent = get_decision_agent()
        signal_agent = get_signal_agent()

        decision_card = decision_agent.get_agent_card()
        signal_card = signal_agent.get_agent_card()

        return {
            "decision_agent": AgentCardResponse(**decision_card),
            "signal_agent": AgentCardResponse(**signal_card)
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get agent cards: {str(e)}")


@router.get("/airport/health")
async def health_check():
    """
    Health check endpoint for airport decision system

    Returns status of:
    - Decision Agent
    - Signal Agent
    - Playbook Manager
    - Signal Catalog
    """
    try:
        decision_agent = get_decision_agent()
        signal_agent = get_signal_agent()

        return {
            "status": "healthy",
            "decision_agent": {
                "loaded": True,
                "scenarios_count": len(decision_agent.playbook_manager.list_scenarios())
            },
            "signal_agent": {
                "loaded": True,
                "signals_count": len(signal_agent.catalog.list_signals())
            },
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }
