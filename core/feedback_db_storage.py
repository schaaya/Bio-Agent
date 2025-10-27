"""
Database-Backed Feedback Storage (Optional Enhancement)

This module provides persistent storage for feedback logs using PostgreSQL.
Use this instead of in-memory FeedbackCollector for production deployments.

Setup:
1. Run schemas/evaluation_schema.sql on your PostgreSQL database
2. Set EVALUATION_DB connection string in .env
3. Replace FeedbackCollector with DatabaseFeedbackCollector in evaluation_manager.py
"""

import os
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy import create_engine, Column, String, Float, Integer, Boolean, DateTime, Text, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.dialects.postgresql import UUID
import uuid

from core.feedback_system import FeedbackLog, FeedbackType, EvaluationMetrics, AnalyzerPerformance

Base = declarative_base()


class QueryEvaluationDB(Base):
    """SQLAlchemy model for query_evaluations table"""
    __tablename__ = 'query_evaluations'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)

    # User and query context
    user_id = Column(String(255), nullable=False, index=True)
    question = Column(Text, nullable=False)
    sql_query = Column(Text, nullable=False)
    sql_dialect = Column(String(50))

    # Analyzer scores
    confidence_score = Column(Float, nullable=False, index=True)
    correctness_score = Column(Float)
    relevance_score = Column(Float)
    completeness_score = Column(Float)
    performance_score = Column(Float)
    data_quality_score = Column(Float)

    # Feedback and results
    user_feedback = Column(String(50), index=True)
    execution_success = Column(Boolean)
    execution_time_ms = Column(Integer)
    result_count = Column(Integer)

    # Process tracking
    regeneration_count = Column(Integer, default=0)
    final_accepted = Column(Boolean, default=False, index=True)
    analyzer_performance = Column(String(50), index=True)

    # Additional context (stored as JSON)
    analyzer_issues = Column(JSON)
    analyzer_improvements = Column(JSON)
    notes = Column(Text)


class DatabaseFeedbackCollector:
    """
    Database-backed feedback collector for persistent storage.

    Drop-in replacement for in-memory FeedbackCollector.
    """

    def __init__(self, connection_string: Optional[str] = None):
        """
        Initialize database connection.

        Args:
            connection_string: PostgreSQL connection string
                              (defaults to EVALUATION_DB env var)
        """
        self.connection_string = connection_string or os.getenv(
            'EVALUATION_DB',
            os.getenv('APP_DB_POSTGRES') or os.getenv('USERS_POSTGRES')  # Fallback chain
        )

        if not self.connection_string:
            raise ValueError(
                "Database connection string required. "
                "Set EVALUATION_DB environment variable or pass connection_string"
            )

        # Create engine and session
        self.engine = create_engine(self.connection_string)
        self.SessionLocal = sessionmaker(bind=self.engine)

        # Create tables if they don't exist
        Base.metadata.create_all(self.engine)

    def _get_session(self) -> Session:
        """Get a new database session"""
        return self.SessionLocal()

    def create_log(
        self,
        user_id: str,
        question: str,
        sql_query: str,
        confidence_score: float,
        analyzer_result: Dict[str, Any]
    ) -> FeedbackLog:
        """
        Create a new feedback log entry in the database.

        Args:
            user_id: User identifier
            question: Original user question
            sql_query: Generated SQL query
            confidence_score: Analyzer confidence score
            analyzer_result: Full analyzer result dictionary

        Returns:
            FeedbackLog instance
        """
        session = self._get_session()

        try:
            # Create database record
            db_record = QueryEvaluationDB(
                user_id=user_id,
                question=question,
                sql_query=sql_query,
                confidence_score=confidence_score,
                correctness_score=analyzer_result.get("correctness_score", 0.0),
                relevance_score=analyzer_result.get("relevance_score", 0.0),
                completeness_score=analyzer_result.get("completeness_score", 0.0),
                performance_score=analyzer_result.get("performance_score", 0.0),
                data_quality_score=analyzer_result.get("data_quality_score", 0.0),
                analyzer_issues=analyzer_result.get("issues", []),
                analyzer_improvements=analyzer_result.get("suggested_improvements", [])
            )

            session.add(db_record)
            session.commit()

            # Convert to FeedbackLog for compatibility
            feedback_log = self._db_to_feedback_log(db_record)

            return feedback_log

        finally:
            session.close()

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
        session = self._get_session()

        try:
            db_record = session.query(QueryEvaluationDB).filter_by(
                id=uuid.UUID(log_id)
            ).first()

            if not db_record:
                return None

            # Update fields
            for key, value in kwargs.items():
                if hasattr(db_record, key):
                    setattr(db_record, key, value)

            session.commit()

            return self._db_to_feedback_log(db_record)

        finally:
            session.close()

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
            notes: Additional user notes

        Returns:
            Updated FeedbackLog or None if not found
        """
        session = self._get_session()

        try:
            db_record = session.query(QueryEvaluationDB).filter_by(
                id=uuid.UUID(log_id)
            ).first()

            if not db_record:
                return None

            # Update feedback fields
            db_record.user_feedback = feedback_type.value
            db_record.final_accepted = final_accepted
            if notes:
                db_record.notes = notes

            # Classify analyzer performance
            feedback_log = self._db_to_feedback_log(db_record)
            performance = feedback_log.classify_analyzer_performance()
            db_record.analyzer_performance = performance.value

            session.commit()

            return self._db_to_feedback_log(db_record)

        finally:
            session.close()

    def get_metrics(
        self,
        user_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> EvaluationMetrics:
        """
        Calculate aggregate metrics from database.

        Args:
            user_id: Filter by user ID (optional)
            start_date: Filter logs after this date (optional)
            end_date: Filter logs before this date (optional)

        Returns:
            EvaluationMetrics with calculated statistics
        """
        session = self._get_session()

        try:
            # Build query with filters
            query = session.query(QueryEvaluationDB)

            if user_id:
                query = query.filter(QueryEvaluationDB.user_id == user_id)
            if start_date:
                query = query.filter(QueryEvaluationDB.timestamp >= start_date)
            if end_date:
                query = query.filter(QueryEvaluationDB.timestamp <= end_date)

            records = query.all()

            if not records:
                return EvaluationMetrics()

            # Calculate metrics
            metrics = EvaluationMetrics()
            metrics.total_evaluations = len(records)

            # Count performance classifications
            for record in records:
                if record.analyzer_performance == AnalyzerPerformance.TRUE_POSITIVE.value:
                    metrics.true_positives += 1
                elif record.analyzer_performance == AnalyzerPerformance.TRUE_NEGATIVE.value:
                    metrics.true_negatives += 1
                elif record.analyzer_performance == AnalyzerPerformance.FALSE_POSITIVE.value:
                    metrics.false_positives += 1
                elif record.analyzer_performance == AnalyzerPerformance.FALSE_NEGATIVE.value:
                    metrics.false_negatives += 1

            # Calculate averages
            metrics.avg_confidence_score = sum(r.confidence_score for r in records) / len(records)
            metrics.avg_regeneration_count = sum(r.regeneration_count for r in records) / len(records)
            metrics.acceptance_rate = sum(1 for r in records if r.final_accepted) / len(records) * 100

            execution_times = [r.execution_time_ms for r in records if r.execution_time_ms is not None]
            if execution_times:
                metrics.avg_execution_time_ms = sum(execution_times) / len(execution_times)

            return metrics

        finally:
            session.close()

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
        session = self._get_session()

        try:
            records = session.query(QueryEvaluationDB).filter_by(
                analyzer_performance=performance_type.value
            ).all()

            return [self._db_to_feedback_log(r) for r in records]

        finally:
            session.close()

    def export_logs(self) -> List[Dict[str, Any]]:
        """
        Export all logs as dictionaries.

        Returns:
            List of log dictionaries
        """
        session = self._get_session()

        try:
            records = session.query(QueryEvaluationDB).all()
            return [self._db_to_feedback_log(r).to_dict() for r in records]

        finally:
            session.close()

    def _db_to_feedback_log(self, db_record: QueryEvaluationDB) -> FeedbackLog:
        """Convert database record to FeedbackLog instance"""
        return FeedbackLog(
            id=str(db_record.id),
            timestamp=db_record.timestamp,
            user_id=db_record.user_id,
            question=db_record.question,
            sql_query=db_record.sql_query,
            confidence_score=db_record.confidence_score,
            user_feedback=db_record.user_feedback,
            execution_success=db_record.execution_success,
            execution_time_ms=db_record.execution_time_ms,
            result_count=db_record.result_count,
            regeneration_count=db_record.regeneration_count,
            final_accepted=db_record.final_accepted,
            analyzer_issues=db_record.analyzer_issues or [],
            analyzer_improvements=db_record.analyzer_improvements or [],
            detailed_scores={
                "correctness": db_record.correctness_score or 0.0,
                "relevance": db_record.relevance_score or 0.0,
                "completeness": db_record.completeness_score or 0.0,
                "performance": db_record.performance_score or 0.0,
                "data_quality": db_record.data_quality_score or 0.0,
            },
            analyzer_performance=db_record.analyzer_performance,
            notes=db_record.notes
        )


# Example usage:
"""
# In your .env file, add:
EVALUATION_DB=postgresql://user:password@host:port/database

# In core/Agent_SQL.py, replace:
from core.feedback_system import FeedbackCollector

# With:
from core.feedback_db_storage import DatabaseFeedbackCollector as FeedbackCollector

# Everything else stays the same!
"""
