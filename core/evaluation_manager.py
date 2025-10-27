"""
SQL Evaluation Manager

This module orchestrates the complete feedback loop for SQL query evaluation:
1. Analyze SQL with confidence scoring
2. Regenerate if confidence < threshold
3. Collect user feedback
4. Log and classify performance
5. Track metrics for continuous improvement
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional, Callable, Awaitable
from datetime import datetime

from core.sql_analyzer import SQLAnalyzer
from core.feedback_system import (
    FeedbackCollector,
    FeedbackLog,
    FeedbackType,
    AnalyzerPerformance,
    EvaluationMetrics
)

logger = logging.getLogger(__name__)


class SQLEvaluationManager:
    """
    Manages the complete SQL evaluation and feedback loop.

    This class orchestrates:
    - SQL query analysis with confidence scoring
    - Automatic regeneration for low-confidence queries
    - User feedback collection
    - Performance tracking and metrics
    """

    def __init__(
        self,
        feedback_collector: Optional[FeedbackCollector] = None,
        confidence_threshold: float = 75.0,
        max_retries: int = 3,
        enable_auto_retry: bool = True
    ):
        """
        Initialize the evaluation manager.

        Args:
            feedback_collector: FeedbackCollector instance (creates new if None)
            confidence_threshold: Minimum confidence score to accept query
            max_retries: Maximum regeneration attempts
            enable_auto_retry: Whether to automatically retry low-confidence queries
        """
        self.feedback_collector = feedback_collector or FeedbackCollector()
        self.confidence_threshold = confidence_threshold
        self.max_retries = max_retries
        self.enable_auto_retry = enable_auto_retry

    async def evaluate_sql_query(
        self,
        analyzer: SQLAnalyzer,
        user_id: str,
        sql_regenerator: Optional[Callable[[str], Awaitable[str]]] = None,
        status_callback: Optional[Callable[[str], Awaitable[None]]] = None
    ) -> Dict[str, Any]:
        """
        Evaluate SQL query with automatic retry logic and feedback tracking.

        Args:
            analyzer: Configured SQLAnalyzer instance
            user_id: User identifier
            sql_regenerator: Async function to regenerate SQL query
                             Should accept reason (str) and return new SQL query (str)
            status_callback: Async function to send status updates to user

        Returns:
            Dict containing:
                - analysis: Full analysis result
                - sql_query: Final SQL query (potentially regenerated)
                - regeneration_count: Number of regeneration attempts
                - log_id: ID of the feedback log entry
                - accepted: Whether query met confidence threshold
        """
        retry_count = 0
        current_sql = analyzer.sql_query
        final_analysis = None

        while retry_count < self.max_retries:
            # Update analyzer with current SQL
            analyzer.sql_query = current_sql

            # Analyze the query
            analysis = await analyzer.analyze_query()
            final_analysis = analysis

            logger.info(
                f"SQL Analysis - Attempt {retry_count + 1}: "
                f"Confidence={analysis['confidence_score']:.2f}%, "
                f"Threshold={self.confidence_threshold}%"
            )

            # Check if confidence meets threshold
            if analyzer.meets_threshold(analysis):
                logger.info("✓ Query meets confidence threshold")
                break

            # Low confidence - check if we should retry
            if not self.enable_auto_retry or retry_count >= self.max_retries - 1:
                logger.warning(f"✗ Query below confidence threshold. Retries exhausted.")
                break

            # Get critical issues for regeneration context
            critical_issues = analyzer.get_critical_issues(analysis)
            issues_summary = "; ".join([issue['description'] for issue in critical_issues])
            reason = f"Confidence score {analysis['confidence_score']:.1f}% below threshold. Issues: {issues_summary}"

            logger.warning(f"Regenerating SQL query. Reason: {reason}")

            # Send status update to user
            if status_callback:
                await status_callback(
                    f"Refining query (attempt {retry_count + 2}/{self.max_retries})..."
                )

            # Regenerate SQL if regenerator provided
            if sql_regenerator:
                try:
                    current_sql = await sql_regenerator(reason)
                    retry_count += 1
                    logger.info(f"SQL regenerated. Attempt {retry_count + 1}")
                except Exception as e:
                    logger.error(f"SQL regeneration failed: {str(e)}")
                    break
            else:
                logger.warning("No SQL regenerator provided. Cannot retry.")
                break

        # Create feedback log
        feedback_log = self.feedback_collector.create_log(
            user_id=user_id,
            question=analyzer.user_question,
            sql_query=current_sql,
            confidence_score=final_analysis['confidence_score'],
            analyzer_result=final_analysis
        )

        # Update regeneration count
        feedback_log.regeneration_count = retry_count

        return {
            "analysis": final_analysis,
            "sql_query": current_sql,
            "regeneration_count": retry_count,
            "log_id": feedback_log.id,
            "accepted": final_analysis['confidence_score'] >= self.confidence_threshold
        }

    async def collect_user_feedback(
        self,
        log_id: str,
        feedback_type: FeedbackType,
        execution_success: bool,
        execution_time_ms: Optional[int] = None,
        result_count: Optional[int] = None,
        final_accepted: bool = False,
        notes: Optional[str] = None
    ) -> Optional[FeedbackLog]:
        """
        Collect user feedback for an evaluated query.

        Args:
            log_id: ID of the feedback log
            feedback_type: User's feedback
            execution_success: Whether query executed successfully
            execution_time_ms: Query execution time
            result_count: Number of rows returned
            final_accepted: Whether user accepted this query as final
            notes: Additional user notes

        Returns:
            Updated FeedbackLog or None if not found
        """
        # Update execution details
        log = self.feedback_collector.update_log(
            log_id,
            execution_success=execution_success,
            execution_time_ms=execution_time_ms,
            result_count=result_count
        )

        if not log:
            logger.error(f"Feedback log {log_id} not found")
            return None

        # Add user feedback
        log = self.feedback_collector.add_user_feedback(
            log_id,
            feedback_type,
            final_accepted,
            notes
        )

        # Log the performance classification
        if log:
            self._log_performance_analysis(log)

        return log

    def _log_performance_analysis(self, log: FeedbackLog) -> None:
        """
        Log analyzer performance analysis based on score vs feedback.

        Args:
            log: FeedbackLog with analyzer performance classification
        """
        performance = log.analyzer_performance
        score = log.confidence_score
        feedback = log.user_feedback

        if performance == AnalyzerPerformance.TRUE_POSITIVE.value:
            logger.info(
                f"✓ TRUE POSITIVE: High confidence ({score:.1f}%) + Positive feedback. "
                "Analyzer working well."
            )
        elif performance == AnalyzerPerformance.TRUE_NEGATIVE.value:
            logger.info(
                f"✓ TRUE NEGATIVE: Low confidence ({score:.1f}%) + Negative feedback. "
                "Analyzer correctly flagged issues."
            )
        elif performance == AnalyzerPerformance.FALSE_POSITIVE.value:
            logger.warning(
                f"✗ FALSE POSITIVE: High confidence ({score:.1f}%) + Negative feedback. "
                "Investigate analyzer over-confidence. User feedback: {feedback}"
            )
        elif performance == AnalyzerPerformance.FALSE_NEGATIVE.value:
            logger.warning(
                f"✗ FALSE NEGATIVE: Low confidence ({score:.1f}%) + Positive feedback. "
                "Review threshold or analyzer sensitivity. User feedback: {feedback}"
            )

    def get_performance_metrics(
        self,
        user_id: Optional[str] = None,
        days: int = 30
    ) -> EvaluationMetrics:
        """
        Get aggregate performance metrics.

        Args:
            user_id: Filter by user (optional)
            days: Number of days to look back (default: 30)

        Returns:
            EvaluationMetrics with calculated statistics
        """
        start_date = datetime.utcnow() - timedelta(days=days) if days else None

        return self.feedback_collector.get_metrics(
            user_id=user_id,
            start_date=start_date
        )

    def get_improvement_insights(self) -> Dict[str, Any]:
        """
        Get actionable insights for improving the analyzer.

        Returns:
            Dict with insights and recommendations
        """
        metrics = self.get_performance_metrics()

        # Get false positives and false negatives for analysis
        false_positives = self.feedback_collector.get_logs_by_performance(
            AnalyzerPerformance.FALSE_POSITIVE
        )
        false_negatives = self.feedback_collector.get_logs_by_performance(
            AnalyzerPerformance.FALSE_NEGATIVE
        )

        insights = {
            "overall_metrics": metrics.to_dict(),
            "recommendations": [],
            "threshold_analysis": {},
            "common_issues": []
        }

        # Precision analysis
        if metrics.precision < 80:
            insights["recommendations"].append({
                "priority": "high",
                "area": "false_positives",
                "message": f"Precision is {metrics.precision:.1f}%. Review false positives to reduce over-confidence.",
                "count": len(false_positives)
            })

        # Recall analysis
        if metrics.recall < 80:
            insights["recommendations"].append({
                "priority": "high",
                "area": "false_negatives",
                "message": f"Recall is {metrics.recall:.1f}%. Review false negatives - threshold may be too high.",
                "count": len(false_negatives)
            })

        # Threshold recommendation
        if metrics.false_negative_rate > 10:
            insights["threshold_analysis"]["recommendation"] = "Consider lowering threshold"
            insights["threshold_analysis"]["current"] = self.confidence_threshold
            insights["threshold_analysis"]["suggested"] = max(60.0, self.confidence_threshold - 10)

        # Common issues analysis
        all_issues = {}
        for log in self.feedback_collector.logs:
            for issue in log.analyzer_issues:
                issue_type = issue.get('type', 'unknown')
                all_issues[issue_type] = all_issues.get(issue_type, 0) + 1

        insights["common_issues"] = [
            {"type": issue_type, "count": count}
            for issue_type, count in sorted(all_issues.items(), key=lambda x: x[1], reverse=True)
        ]

        return insights

    def export_training_data(self) -> List[Dict[str, Any]]:
        """
        Export logs formatted for ML model retraining.

        Returns:
            List of training examples with features and labels
        """
        training_data = []

        for log in self.feedback_collector.logs:
            if log.user_feedback is None:
                continue  # Skip logs without feedback

            # Create feature vector
            features = {
                "confidence_score": log.confidence_score,
                "detailed_scores": log.detailed_scores,
                "issue_count": len(log.analyzer_issues),
                "critical_issue_count": sum(
                    1 for issue in log.analyzer_issues
                    if issue.get('severity') == 'critical'
                ),
                "regeneration_count": log.regeneration_count,
                "execution_time_ms": log.execution_time_ms,
                "result_count": log.result_count,
            }

            # Label: positive feedback = 1, negative = 0
            label = 1 if log.user_feedback in [
                FeedbackType.POSITIVE.value,
                FeedbackType.PARTIALLY_CORRECT.value
            ] else 0

            training_data.append({
                "features": features,
                "label": label,
                "sql_query": log.sql_query,
                "question": log.question,
                "timestamp": log.timestamp.isoformat()
            })

        return training_data


# Import for datetime
from datetime import timedelta
