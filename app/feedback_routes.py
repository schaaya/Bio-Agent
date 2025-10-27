"""
Feedback Collection Routes for SQL Query Evaluation

This module provides API endpoints for collecting user feedback on SQL queries
and retrieving evaluation metrics.
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime
import logging

from core.Agent_SQL_pydantic_mcp import get_evaluation_manager
from core.feedback_system import FeedbackType
import core.globals as globals
from app.user_depends import get_admin_status
from app.schema import SystemUser

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/evaluation",
    tags=["SQL Evaluation & Feedback"]
)


# Pydantic models for request/response
class QueryFeedbackRequest(BaseModel):
    """Request model for submitting query feedback"""
    user_id: str
    feedback_type: str  # 'positive', 'negative', 'partially_correct', etc.
    final_accepted: bool = True
    notes: Optional[str] = None


class MetricsRequest(BaseModel):
    """Request model for retrieving metrics"""
    user_id: Optional[str] = None
    days: int = 30


class FeedbackResponse(BaseModel):
    """Response model for feedback submission"""
    success: bool
    message: str
    log_id: Optional[str] = None
    analyzer_performance: Optional[str] = None


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_query_feedback(
    request: QueryFeedbackRequest,
    current_user: SystemUser = Depends(get_admin_status)
):
    """
    Submit user feedback for a SQL query.

    This endpoint allows users to provide feedback on query results,
    which is used to evaluate and improve the SQL analyzer.

    Args:
        request: Feedback request containing user_id, feedback_type, etc.
        current_user: Authenticated user (from dependency)

    Returns:
        FeedbackResponse with success status and analyzer performance classification
    """
    try:
        # Validate feedback type
        try:
            feedback_enum = FeedbackType[request.feedback_type.upper()]
        except KeyError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid feedback_type. Must be one of: {', '.join([ft.name for ft in FeedbackType])}"
            )

        # Get evaluation data from globals
        if not hasattr(globals, 'query_evaluations') or request.user_id not in globals.query_evaluations:
            raise HTTPException(
                status_code=404,
                detail="No evaluation found for this user. Query may have expired or not been analyzed."
            )

        eval_data = globals.query_evaluations[request.user_id]
        log_id = eval_data.get('log_id')

        if not log_id:
            raise HTTPException(
                status_code=404,
                detail="Evaluation log ID not found. Cannot submit feedback."
            )

        # Get evaluation manager
        eval_manager, _ = get_evaluation_manager()

        # Submit feedback
        feedback_log = await eval_manager.collect_user_feedback(
            log_id=log_id,
            feedback_type=feedback_enum,
            execution_success=True,  # Already stored in log
            execution_time_ms=None,  # Already stored in log
            result_count=None,  # Already stored in log
            final_accepted=request.final_accepted,
            notes=request.notes
        )

        if not feedback_log:
            raise HTTPException(
                status_code=404,
                detail=f"Feedback log with ID {log_id} not found"
            )

        logger.info(
            f"Feedback submitted - User: {request.user_id}, "
            f"Type: {request.feedback_type}, "
            f"Performance: {feedback_log.analyzer_performance}"
        )

        return FeedbackResponse(
            success=True,
            message="Feedback submitted successfully",
            log_id=feedback_log.id,
            analyzer_performance=feedback_log.analyzer_performance
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting feedback: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to submit feedback: {str(e)}"
        )


@router.get("/metrics")
async def get_evaluation_metrics(
    user_id: Optional[str] = None,
    days: int = 30,
    current_user: SystemUser = Depends(get_admin_status)
):
    """
    Get evaluation metrics for SQL analyzer performance.

    This endpoint returns comprehensive metrics including precision, recall,
    F1 score, and performance classifications.

    Args:
        user_id: Optional user ID to filter metrics (admin only)
        days: Number of days to look back (default: 30)
        current_user: Authenticated user

    Returns:
        Dict with evaluation metrics
    """
    try:
        eval_manager, _ = get_evaluation_manager()

        # Get metrics
        metrics = eval_manager.get_performance_metrics(
            user_id=user_id,
            days=days
        )

        return {
            "success": True,
            "period_days": days,
            "user_id": user_id,
            "metrics": metrics.to_dict()
        }

    except Exception as e:
        logger.error(f"Error retrieving metrics: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve metrics: {str(e)}"
        )


@router.get("/insights")
async def get_improvement_insights(
    current_user: SystemUser = Depends(get_admin_status)
):
    """
    Get actionable insights for improving the SQL analyzer.

    This endpoint analyzes false positives, false negatives, and provides
    recommendations for threshold adjustments and prompt improvements.

    Args:
        current_user: Authenticated admin user

    Returns:
        Dict with insights and recommendations
    """
    try:
        eval_manager, _ = get_evaluation_manager()

        insights = eval_manager.get_improvement_insights()

        return {
            "success": True,
            "insights": insights
        }

    except Exception as e:
        logger.error(f"Error retrieving insights: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve insights: {str(e)}"
        )


@router.get("/training-data")
async def export_training_data(
    current_user: SystemUser = Depends(get_admin_status)
):
    """
    Export evaluation logs formatted for ML model retraining.

    This endpoint is for admins to download training data for improving
    the SQL analyzer model.

    Args:
        current_user: Authenticated admin user

    Returns:
        List of training examples with features and labels
    """
    try:
        eval_manager, _ = get_evaluation_manager()

        training_data = eval_manager.export_training_data()

        return {
            "success": True,
            "count": len(training_data),
            "data": training_data
        }

    except Exception as e:
        logger.error(f"Error exporting training data: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to export training data: {str(e)}"
        )


@router.get("/status/{user_id}")
async def get_query_evaluation_status(
    user_id: str,
    current_user: SystemUser = Depends(get_admin_status)
):
    """
    Get the current evaluation status for a user's query.

    This endpoint returns the analysis results and confidence score
    for the most recent query.

    Args:
        user_id: User identifier
        current_user: Authenticated user

    Returns:
        Dict with evaluation status and details
    """
    try:
        if not hasattr(globals, 'query_evaluations') or user_id not in globals.query_evaluations:
            raise HTTPException(
                status_code=404,
                detail="No evaluation found for this user"
            )

        eval_data = globals.query_evaluations[user_id]

        return {
            "success": True,
            "user_id": user_id,
            "evaluation": {
                "confidence_score": eval_data.get('confidence_score', 0),
                "sql_query": eval_data.get('sql_query'),
                "user_question": eval_data.get('user_question'),
                "attempt": eval_data.get('attempt', 0),
                "log_id": eval_data.get('log_id'),
                "analysis": eval_data.get('analysis', {})
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving evaluation status: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve evaluation status: {str(e)}"
        )
