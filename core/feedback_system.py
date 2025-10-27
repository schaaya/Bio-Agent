"""
Feedback Collection and Evaluation Management System

This module handles user feedback collection, logging, and the feedback loop
for continuous improvement of SQL query generation.
"""

import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class FeedbackType(Enum):
    """User feedback types"""
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    PARTIALLY_CORRECT = "partially_correct"
    MISSING_DATA = "missing_data"
    FORMATTING_ISSUE = "formatting_issue"


class AnalyzerPerformance(Enum):
    """Analyzer performance classification based on score vs feedback"""
    TRUE_POSITIVE = "true_positive"      # High score + positive feedback
    TRUE_NEGATIVE = "true_negative"      # Low score + negative feedback
    FALSE_POSITIVE = "false_positive"    # High score + negative feedback
    FALSE_NEGATIVE = "false_negative"    # Low score + positive feedback


@dataclass
class FeedbackLog:
    """
    Structured feedback log for SQL query evaluations.

    Attributes:
        id: Unique identifier for this evaluation
        timestamp: When the evaluation occurred
        user_id: ID of the user who submitted the query
        question: Original user question
        sql_query: Generated SQL query
        confidence_score: Analyzer's confidence score (0-100)
        user_feedback: User's feedback on the result
        execution_success: Whether the query executed successfully
        execution_time_ms: Query execution time in milliseconds
        result_count: Number of rows returned
        regeneration_count: Number of times query was regenerated
        final_accepted: Whether this query was ultimately accepted
        analyzer_issues: Detailed issues from analyzer
        analyzer_improvements: Suggested improvements from analyzer
        detailed_scores: Breakdown of analyzer scoring
        analyzer_performance: Classification of analyzer performance
        notes: Additional notes or context
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.utcnow)
    user_id: Optional[str] = None
    question: Optional[str] = None
    sql_query: Optional[str] = None
    confidence_score: float = 0.0
    user_feedback: Optional[str] = None
    execution_success: bool = False
    execution_time_ms: Optional[int] = None
    result_count: Optional[int] = None
    regeneration_count: int = 0
    final_accepted: bool = False
    analyzer_issues: List[Dict[str, str]] = field(default_factory=list)
    analyzer_improvements: List[str] = field(default_factory=list)
    detailed_scores: Dict[str, float] = field(default_factory=dict)
    analyzer_performance: Optional[str] = None
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert feedback log to dictionary for storage"""
        data = asdict(self)
        # Convert datetime to ISO format string
        data['timestamp'] = self.timestamp.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FeedbackLog':
        """Create FeedbackLog from dictionary"""
        if isinstance(data.get('timestamp'), str):
            data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return cls(**data)

    def classify_analyzer_performance(
        self,
        threshold: float = 75.0
    ) -> AnalyzerPerformance:
        """
        Classify analyzer performance based on confidence score vs user feedback.

        Args:
            threshold: Confidence threshold for high/low classification

        Returns:
            AnalyzerPerformance classification
        """
        high_confidence = self.confidence_score >= threshold
        positive_feedback = self.user_feedback in [
            FeedbackType.POSITIVE.value,
            FeedbackType.PARTIALLY_CORRECT.value
        ]

        if high_confidence and positive_feedback:
            return AnalyzerPerformance.TRUE_POSITIVE
        elif not high_confidence and not positive_feedback:
            return AnalyzerPerformance.TRUE_NEGATIVE
        elif high_confidence and not positive_feedback:
            return AnalyzerPerformance.FALSE_POSITIVE
        else:  # low confidence and positive feedback
            return AnalyzerPerformance.FALSE_NEGATIVE


@dataclass
class EvaluationMetrics:
    """
    Aggregate metrics for analyzer performance over time.

    Attributes:
        total_evaluations: Total number of evaluations
        true_positives: Count of true positives
        true_negatives: Count of true negatives
        false_positives: Count of false positives
        false_negatives: Count of false negatives
        avg_confidence_score: Average confidence score
        avg_regeneration_count: Average number of regenerations
        acceptance_rate: % of queries ultimately accepted
        avg_execution_time_ms: Average query execution time
    """
    total_evaluations: int = 0
    true_positives: int = 0
    true_negatives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    avg_confidence_score: float = 0.0
    avg_regeneration_count: float = 0.0
    acceptance_rate: float = 0.0
    avg_execution_time_ms: float = 0.0

    @property
    def precision(self) -> float:
        """
        Calculate precision: TP / (TP + FP)
        % of high-confidence queries that got positive feedback
        """
        denominator = self.true_positives + self.false_positives
        return (self.true_positives / denominator * 100) if denominator > 0 else 0.0

    @property
    def recall(self) -> float:
        """
        Calculate recall: TP / (TP + FN)
        % of positive feedback cases that had high confidence
        """
        denominator = self.true_positives + self.false_negatives
        return (self.true_positives / denominator * 100) if denominator > 0 else 0.0

    @property
    def f1_score(self) -> float:
        """Calculate F1 score: harmonic mean of precision and recall"""
        if self.precision + self.recall == 0:
            return 0.0
        return 2 * (self.precision * self.recall) / (self.precision + self.recall)

    @property
    def false_positive_rate(self) -> float:
        """% of total evaluations that were false positives"""
        return (self.false_positives / self.total_evaluations * 100) if self.total_evaluations > 0 else 0.0

    @property
    def false_negative_rate(self) -> float:
        """% of total evaluations that were false negatives"""
        return (self.false_negatives / self.total_evaluations * 100) if self.total_evaluations > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary including calculated properties"""
        return {
            'total_evaluations': self.total_evaluations,
            'true_positives': self.true_positives,
            'true_negatives': self.true_negatives,
            'false_positives': self.false_positives,
            'false_negatives': self.false_negatives,
            'avg_confidence_score': round(self.avg_confidence_score, 2),
            'avg_regeneration_count': round(self.avg_regeneration_count, 2),
            'acceptance_rate': round(self.acceptance_rate, 2),
            'avg_execution_time_ms': round(self.avg_execution_time_ms, 2),
            'precision': round(self.precision, 2),
            'recall': round(self.recall, 2),
            'f1_score': round(self.f1_score, 2),
            'false_positive_rate': round(self.false_positive_rate, 2),
            'false_negative_rate': round(self.false_negative_rate, 2),
        }


class FeedbackCollector:
    """
    Collects and manages feedback logs for SQL query evaluations.
    """

    def __init__(self):
        """Initialize feedback collector with in-memory storage"""
        self.logs: List[FeedbackLog] = []

    def create_log(
        self,
        user_id: str,
        question: str,
        sql_query: str,
        confidence_score: float,
        analyzer_result: Dict[str, Any]
    ) -> FeedbackLog:
        """
        Create a new feedback log entry.

        Args:
            user_id: User identifier
            question: Original user question
            sql_query: Generated SQL query
            confidence_score: Analyzer confidence score
            analyzer_result: Full analyzer result dictionary

        Returns:
            FeedbackLog instance
        """
        log = FeedbackLog(
            user_id=user_id,
            question=question,
            sql_query=sql_query,
            confidence_score=confidence_score,
            analyzer_issues=analyzer_result.get("issues", []),
            analyzer_improvements=analyzer_result.get("suggested_improvements", []),
            detailed_scores={
                "correctness": analyzer_result.get("correctness_score", 0.0),
                "relevance": analyzer_result.get("relevance_score", 0.0),
                "completeness": analyzer_result.get("completeness_score", 0.0),
                "performance": analyzer_result.get("performance_score", 0.0),
                "data_quality": analyzer_result.get("data_quality_score", 0.0),
            }
        )
        self.logs.append(log)
        return log

    def update_log(
        self,
        log_id: str,
        **kwargs
    ) -> Optional[FeedbackLog]:
        """
        Update an existing feedback log.

        Args:
            log_id: ID of the log to update
            **kwargs: Fields to update

        Returns:
            Updated FeedbackLog or None if not found
        """
        for log in self.logs:
            if log.id == log_id:
                for key, value in kwargs.items():
                    if hasattr(log, key):
                        setattr(log, key, value)
                return log
        return None

    def add_user_feedback(
        self,
        log_id: str,
        feedback_type: FeedbackType,
        final_accepted: bool = False,
        notes: Optional[str] = None
    ) -> Optional[FeedbackLog]:
        """
        Add user feedback to a log entry.

        Args:
            log_id: ID of the log to update
            feedback_type: Type of feedback
            final_accepted: Whether query was ultimately accepted
            notes: Additional notes

        Returns:
            Updated FeedbackLog or None if not found
        """
        log = self.update_log(
            log_id,
            user_feedback=feedback_type.value,
            final_accepted=final_accepted,
            notes=notes
        )

        if log:
            # Classify analyzer performance
            performance = log.classify_analyzer_performance()
            log.analyzer_performance = performance.value
            logger.info(f"Feedback added to log {log_id}: {feedback_type.value} - Performance: {performance.value}")

        return log

    def get_metrics(
        self,
        user_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> EvaluationMetrics:
        """
        Calculate aggregate metrics from feedback logs.

        Args:
            user_id: Filter by user ID (optional)
            start_date: Filter logs after this date (optional)
            end_date: Filter logs before this date (optional)

        Returns:
            EvaluationMetrics with calculated statistics
        """
        # Filter logs
        filtered_logs = self.logs

        if user_id:
            filtered_logs = [log for log in filtered_logs if log.user_id == user_id]
        if start_date:
            filtered_logs = [log for log in filtered_logs if log.timestamp >= start_date]
        if end_date:
            filtered_logs = [log for log in filtered_logs if log.timestamp <= end_date]

        if not filtered_logs:
            return EvaluationMetrics()

        # Calculate metrics
        metrics = EvaluationMetrics()
        metrics.total_evaluations = len(filtered_logs)

        # Count performance classifications
        for log in filtered_logs:
            if log.analyzer_performance == AnalyzerPerformance.TRUE_POSITIVE.value:
                metrics.true_positives += 1
            elif log.analyzer_performance == AnalyzerPerformance.TRUE_NEGATIVE.value:
                metrics.true_negatives += 1
            elif log.analyzer_performance == AnalyzerPerformance.FALSE_POSITIVE.value:
                metrics.false_positives += 1
            elif log.analyzer_performance == AnalyzerPerformance.FALSE_NEGATIVE.value:
                metrics.false_negatives += 1

        # Calculate averages
        metrics.avg_confidence_score = sum(log.confidence_score for log in filtered_logs) / len(filtered_logs)
        metrics.avg_regeneration_count = sum(log.regeneration_count for log in filtered_logs) / len(filtered_logs)
        metrics.acceptance_rate = sum(1 for log in filtered_logs if log.final_accepted) / len(filtered_logs) * 100

        execution_times = [log.execution_time_ms for log in filtered_logs if log.execution_time_ms is not None]
        if execution_times:
            metrics.avg_execution_time_ms = sum(execution_times) / len(execution_times)

        return metrics

    def get_logs_by_performance(
        self,
        performance_type: AnalyzerPerformance
    ) -> List[FeedbackLog]:
        """
        Get all logs matching a specific analyzer performance classification.

        Args:
            performance_type: Performance classification to filter by

        Returns:
            List of matching FeedbackLog instances
        """
        return [
            log for log in self.logs
            if log.analyzer_performance == performance_type.value
        ]

    def export_logs(self) -> List[Dict[str, Any]]:
        """
        Export all logs as dictionaries for storage or analysis.

        Returns:
            List of log dictionaries
        """
        return [log.to_dict() for log in self.logs]
