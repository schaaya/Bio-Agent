"""
Janitorial Policy Module

Pure function policy for deciding between autonomous floor scrubbers vs human janitors.

Decision factors:
1. Occupancy levels (current and predicted)
2. Weather conditions (wet floors)
3. Staff availability and morale
4. Robot battery levels
5. Zone conditions and traffic patterns
6. Passenger mood

Output: DecisionBundle with specific deployment actions
"""
from typing import Dict, Any, List
from core.a2a_protocol import Context, DecisionBundle, DecisionAction


def execute_policy(context: Context, playbook: Dict[str, Any]) -> DecisionBundle:
    """
    Execute janitorial operations policy

    Args:
        context: Context with signal values
        playbook: Playbook configuration

    Returns:
        DecisionBundle with deployment decisions
    """

    # Extract signals with defaults
    current_occupancy = context.get_signal_value("current_occupancy_percent", 50.0)
    predicted_occupancy = context.get_signal_value("predicted_occupancy_1hr", 60.0)
    is_raining = context.get_signal_value("is_raining", False)
    available_janitors = context.get_signal_value("available_janitors_count", 2)
    available_scrubbers = context.get_signal_value("available_scrubbers_count", 1)
    robot_battery = context.get_signal_value("robot_battery_avg", 75.0)
    wet_floor_zones = context.get_signal_value("wet_floor_zones_count", 0)
    high_traffic_zones = context.get_signal_value("high_traffic_zones", [])
    passenger_mood = context.get_signal_value("passenger_mood_score", 5.0)
    staff_morale = context.get_signal_value("staff_morale_score", 7.0)

    # Get zone definitions from playbook
    zones = playbook.get("zones", {})
    low_traffic = zones.get("low_traffic", [])
    medium_traffic = zones.get("medium_traffic", [])
    high_traffic_defined = zones.get("high_traffic", [])
    entry_points = zones.get("entry_points", [])

    # Decision variables
    actions: List[DecisionAction] = []
    confidence_factors = []
    reasoning_notes = []

    # ========================================================================
    # Decision Logic
    # ========================================================================

    # Rule 1: High occupancy (>75%) - Avoid robots in high-traffic zones
    if current_occupancy >= 75:
        reasoning_notes.append(f"High occupancy ({current_occupancy}%) - deploying robots to low-traffic zones only")

        # Deploy robots to low-traffic zones
        if available_scrubbers > 0 and robot_battery >= 30:
            for zone in low_traffic:
                actions.append(DecisionAction(
                    action="DEPLOY_ROBOT_SCRUBBER",
                    target=zone,
                    zone_tags=["low_traffic"],
                    rationale=f"Low traffic zone safe for robot operation during high occupancy",
                    priority=6,
                    params={"battery_threshold": 30, "speed": "normal"}
                ))
            confidence_factors.append(0.8)

        # Deploy humans to high-traffic zones
        if available_janitors > 0:
            for zone in high_traffic_defined[:available_janitors]:
                actions.append(DecisionAction(
                    action="DISPATCH_JANITOR",
                    target=zone,
                    zone_tags=["high_traffic"],
                    rationale=f"Human janitor for high-traffic zone during peak occupancy",
                    priority=9,
                    params={"task": "spot_cleaning", "duration_min": 30}
                ))
            confidence_factors.append(0.9)

    # Rule 2: Rain + entry points - Prioritize entry cleaning
    elif is_raining and wet_floor_zones > 0:
        reasoning_notes.append(f"Rain detected with {wet_floor_zones} wet zones - prioritizing entry points")

        # Deploy humans to entry points (better for wet conditions)
        if available_janitors > 0:
            for zone in entry_points[:available_janitors]:
                actions.append(DecisionAction(
                    action="DISPATCH_JANITOR",
                    target=zone,
                    zone_tags=["entry_point", "wet"],
                    rationale=f"Human janitor for wet entry point cleaning (rain)",
                    priority=10,
                    params={"task": "wet_floor_cleanup", "duration_min": 20, "equipment": "wet_mop"}
                ))
            confidence_factors.append(0.95)

        # Deploy robots to dry zones if available
        dry_zones = [z for z in medium_traffic if z not in entry_points]
        if available_scrubbers > 0 and robot_battery >= 40 and len(dry_zones) > 0:
            actions.append(DecisionAction(
                action="DEPLOY_ROBOT_SCRUBBER",
                target=dry_zones[0],
                zone_tags=["medium_traffic", "dry"],
                rationale=f"Robot for dry zone maintenance while humans handle wet areas",
                priority=5,
                params={"battery_threshold": 40, "speed": "slow"}
            ))
            confidence_factors.append(0.75)

    # Rule 3: Low occupancy (<50%) + good robot battery - Maximize robot use
    elif current_occupancy < 50 and robot_battery >= 50:
        reasoning_notes.append(f"Low occupancy ({current_occupancy}%) with good battery ({robot_battery}%) - maximizing robot deployment")

        # Deploy robots to as many zones as possible
        if available_scrubbers > 0:
            all_zones = low_traffic + medium_traffic
            for zone in all_zones[:available_scrubbers]:
                actions.append(DecisionAction(
                    action="DEPLOY_ROBOT_SCRUBBER",
                    target=zone,
                    zone_tags=["automated_cleaning"],
                    rationale=f"Optimal conditions for autonomous cleaning",
                    priority=7,
                    params={"battery_threshold": 30, "speed": "fast", "mode": "deep_clean"}
                ))
            confidence_factors.append(0.95)

        # Keep humans on standby for spot tasks
        if available_janitors > 0:
            actions.append(DecisionAction(
                action="ASSIGN_STANDBY",
                target="janitor_team",
                zone_tags=["all"],
                rationale="Janitors on standby for spot cleaning and emergencies",
                priority=3,
                params={"response_time_min": 5}
            ))
            confidence_factors.append(0.8)

    # Rule 4: Low robot battery (<30%) - Prefer humans
    elif robot_battery < 30:
        reasoning_notes.append(f"Low robot battery ({robot_battery}%) - prioritizing human janitors")

        # Deploy humans to all zones
        if available_janitors > 0:
            deployment_zones = high_traffic_defined + medium_traffic
            for zone in deployment_zones[:available_janitors]:
                actions.append(DecisionAction(
                    action="DISPATCH_JANITOR",
                    target=zone,
                    zone_tags=["manual_cleaning"],
                    rationale=f"Robot battery low - using human janitor",
                    priority=8,
                    params={"task": "general_cleaning", "duration_min": 45}
                ))
            confidence_factors.append(0.85)

        # Send robots to charge
        if available_scrubbers > 0:
            actions.append(DecisionAction(
                action="SEND_TO_CHARGING",
                target="robot_fleet",
                zone_tags=["maintenance"],
                rationale="Robots need charging",
                priority=10,
                params={"min_charge_percent": 80}
            ))
            confidence_factors.append(1.0)

    # Rule 5: Insufficient janitors - Alert management
    elif available_janitors < 1:
        reasoning_notes.append("Insufficient janitors available - alerting management")

        actions.append(DecisionAction(
            action="ALERT_MANAGEMENT",
            target="ops_team",
            zone_tags=["alert"],
            rationale="No janitors available - requires staffing intervention",
            priority=10,
            params={"severity": "high", "message": "Insufficient janitorial staff"}
        ))
        confidence_factors.append(0.6)

        # Deploy available robots
        if available_scrubbers > 0 and robot_battery >= 30:
            for zone in low_traffic[:available_scrubbers]:
                actions.append(DecisionAction(
                    action="DEPLOY_ROBOT_SCRUBBER",
                    target=zone,
                    zone_tags=["low_traffic", "emergency"],
                    rationale="Using robots due to janitor shortage",
                    priority=7,
                    params={"battery_threshold": 30}
                ))
            confidence_factors.append(0.7)

    # Rule 6: Balanced hybrid approach (default)
    else:
        reasoning_notes.append(f"Balanced conditions (occupancy: {current_occupancy}%, battery: {robot_battery}%) - hybrid deployment")

        # Deploy robots to low-traffic
        if available_scrubbers > 0 and robot_battery >= 40:
            for zone in low_traffic[:available_scrubbers]:
                actions.append(DecisionAction(
                    action="DEPLOY_ROBOT_SCRUBBER",
                    target=zone,
                    zone_tags=["low_traffic", "hybrid"],
                    rationale="Robot for low-traffic maintenance",
                    priority=6,
                    params={"battery_threshold": 40, "speed": "normal"}
                ))
            confidence_factors.append(0.8)

        # Deploy humans to high-traffic
        if available_janitors > 0:
            for zone in high_traffic_defined[:available_janitors]:
                actions.append(DecisionAction(
                    action="DISPATCH_JANITOR",
                    target=zone,
                    zone_tags=["high_traffic", "hybrid"],
                    rationale="Human for high-traffic area maintenance",
                    priority=7,
                    params={"task": "general_cleaning", "duration_min": 30}
                ))
            confidence_factors.append(0.85)

    # ========================================================================
    # Additional Considerations
    # ========================================================================

    # Adjust for low passenger mood (frustration)
    if passenger_mood < 4.0:
        reasoning_notes.append(f"Low passenger mood ({passenger_mood}) - prioritizing visible cleaning")
        # Increase priority for high-traffic zone cleaning
        for action in actions:
            if "high_traffic" in action.zone_tags:
                action.priority = min(action.priority + 1, 10)
        confidence_factors.append(0.7)

    # Adjust for low staff morale
    if staff_morale < 5.0:
        reasoning_notes.append(f"Low staff morale ({staff_morale}) - reducing human workload")
        # Prefer robots where possible
        for action in actions:
            if action.action == "DEPLOY_ROBOT_SCRUBBER":
                action.priority = min(action.priority + 1, 10)
        confidence_factors.append(0.75)

    # ========================================================================
    # Calculate Overall Confidence Score
    # ========================================================================

    if len(confidence_factors) > 0:
        confidence_score = sum(confidence_factors) / len(confidence_factors)
    else:
        confidence_score = 0.5

    # Adjust confidence based on signal quality
    failed_signals = [name for name, sig in context.signals.items() if not sig.ok]
    if len(failed_signals) > 0:
        penalty = len(failed_signals) * 0.05
        confidence_score = max(0.0, confidence_score - penalty)
        reasoning_notes.append(f"Confidence reduced due to {len(failed_signals)} failed signals")

    # ========================================================================
    # Build Decision Bundle
    # ========================================================================

    if len(actions) == 0:
        # No actions - default to monitoring
        actions.append(DecisionAction(
            action="MONITOR",
            target="all_zones",
            zone_tags=["all"],
            rationale="No immediate cleaning actions required",
            priority=1,
            params={}
        ))
        confidence_score = max(confidence_score, 0.8)

    decision_bundle = DecisionBundle(
        policy_version="janitorial_v1.0",
        score=confidence_score,
        actions=actions,
        notes="; ".join(reasoning_notes),
        requires_hitl=False,  # Will be updated by HITL system
        signals_used=list(context.signals.keys()),
        metadata={
            "occupancy": current_occupancy,
            "predicted_occupancy": predicted_occupancy,
            "is_raining": is_raining,
            "available_janitors": available_janitors,
            "available_scrubbers": available_scrubbers,
            "robot_battery": robot_battery,
            "wet_floor_zones": wet_floor_zones,
            "passenger_mood": passenger_mood,
            "staff_morale": staff_morale,
            "failed_signals": failed_signals
        }
    )

    return decision_bundle
