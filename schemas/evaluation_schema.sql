-- SQL Evaluation and Feedback Database Schema
-- This schema supports storing query evaluations, feedback, and performance metrics
-- for continuous improvement of SQL generation

-- Main table for query evaluations
CREATE TABLE IF NOT EXISTS query_evaluations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- User and query context
    user_id VARCHAR(255) NOT NULL,
    question TEXT NOT NULL,
    sql_query TEXT NOT NULL,
    sql_dialect VARCHAR(50),

    -- Analyzer scores
    confidence_score DECIMAL(5,2) NOT NULL CHECK (confidence_score >= 0 AND confidence_score <= 100),
    correctness_score DECIMAL(5,2),
    relevance_score DECIMAL(5,2),
    completeness_score DECIMAL(5,2),
    performance_score DECIMAL(5,2),
    data_quality_score DECIMAL(5,2),

    -- Feedback and results
    user_feedback VARCHAR(50),  -- 'positive', 'negative', 'neutral', 'partially_correct', etc.
    execution_success BOOLEAN,
    execution_time_ms INTEGER,
    result_count INTEGER,

    -- Process tracking
    regeneration_count INTEGER DEFAULT 0,
    final_accepted BOOLEAN DEFAULT FALSE,
    analyzer_performance VARCHAR(50),  -- 'true_positive', 'true_negative', 'false_positive', 'false_negative'

    -- Additional context
    notes TEXT,

    -- Indexes for common queries
    CONSTRAINT valid_feedback CHECK (
        user_feedback IN ('positive', 'negative', 'neutral', 'partially_correct',
                         'missing_data', 'formatting_issue', NULL)
    ),
    CONSTRAINT valid_performance CHECK (
        analyzer_performance IN ('true_positive', 'true_negative',
                                'false_positive', 'false_negative', NULL)
    )
);

-- Indexes for performance
CREATE INDEX idx_evaluations_user_id ON query_evaluations(user_id);
CREATE INDEX idx_evaluations_timestamp ON query_evaluations(timestamp DESC);
CREATE INDEX idx_evaluations_confidence ON query_evaluations(confidence_score);
CREATE INDEX idx_evaluations_feedback ON query_evaluations(user_feedback);
CREATE INDEX idx_evaluations_performance ON query_evaluations(analyzer_performance);
CREATE INDEX idx_evaluations_accepted ON query_evaluations(final_accepted);

-- Table for detailed analyzer issues
CREATE TABLE IF NOT EXISTS analyzer_issues (
    id SERIAL PRIMARY KEY,
    evaluation_id UUID NOT NULL REFERENCES query_evaluations(id) ON DELETE CASCADE,
    issue_type VARCHAR(50) NOT NULL,  -- 'syntax', 'logic', 'performance', 'data_quality', 'schema_mismatch'
    severity VARCHAR(20) NOT NULL,    -- 'critical', 'warning', 'info'
    description TEXT NOT NULL,

    CONSTRAINT valid_issue_type CHECK (
        issue_type IN ('syntax', 'logic', 'performance', 'data_quality',
                      'schema_mismatch', 'analysis_error')
    ),
    CONSTRAINT valid_severity CHECK (
        severity IN ('critical', 'warning', 'info')
    )
);

CREATE INDEX idx_issues_evaluation_id ON analyzer_issues(evaluation_id);
CREATE INDEX idx_issues_type ON analyzer_issues(issue_type);
CREATE INDEX idx_issues_severity ON analyzer_issues(severity);

-- Table for suggested improvements
CREATE TABLE IF NOT EXISTS analyzer_improvements (
    id SERIAL PRIMARY KEY,
    evaluation_id UUID NOT NULL REFERENCES query_evaluations(id) ON DELETE CASCADE,
    suggestion TEXT NOT NULL,
    priority INTEGER DEFAULT 0  -- For ordering suggestions
);

CREATE INDEX idx_improvements_evaluation_id ON analyzer_improvements(evaluation_id);

-- Table for tracking analyzer configuration over time
CREATE TABLE IF NOT EXISTS analyzer_config_history (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    confidence_threshold DECIMAL(5,2) NOT NULL,
    max_retries INTEGER NOT NULL,
    model_version VARCHAR(100),
    prompt_version VARCHAR(100),
    notes TEXT
);

CREATE INDEX idx_config_timestamp ON analyzer_config_history(timestamp DESC);

-- View for quick performance metrics
CREATE OR REPLACE VIEW evaluation_metrics AS
SELECT
    COUNT(*) as total_evaluations,
    AVG(confidence_score) as avg_confidence_score,
    AVG(regeneration_count) as avg_regeneration_count,
    SUM(CASE WHEN final_accepted THEN 1 ELSE 0 END)::DECIMAL / NULLIF(COUNT(*), 0) * 100 as acceptance_rate,
    AVG(execution_time_ms) as avg_execution_time_ms,

    -- Performance classification counts
    SUM(CASE WHEN analyzer_performance = 'true_positive' THEN 1 ELSE 0 END) as true_positives,
    SUM(CASE WHEN analyzer_performance = 'true_negative' THEN 1 ELSE 0 END) as true_negatives,
    SUM(CASE WHEN analyzer_performance = 'false_positive' THEN 1 ELSE 0 END) as false_positives,
    SUM(CASE WHEN analyzer_performance = 'false_negative' THEN 1 ELSE 0 END) as false_negatives,

    -- Calculated metrics
    CASE
        WHEN SUM(CASE WHEN analyzer_performance IN ('true_positive', 'false_positive') THEN 1 ELSE 0 END) > 0
        THEN SUM(CASE WHEN analyzer_performance = 'true_positive' THEN 1 ELSE 0 END)::DECIMAL /
             SUM(CASE WHEN analyzer_performance IN ('true_positive', 'false_positive') THEN 1 ELSE 0 END) * 100
        ELSE 0
    END as precision,

    CASE
        WHEN SUM(CASE WHEN analyzer_performance IN ('true_positive', 'false_negative') THEN 1 ELSE 0 END) > 0
        THEN SUM(CASE WHEN analyzer_performance = 'true_positive' THEN 1 ELSE 0 END)::DECIMAL /
             SUM(CASE WHEN analyzer_performance IN ('true_positive', 'false_negative') THEN 1 ELSE 0 END) * 100
        ELSE 0
    END as recall,

    SUM(CASE WHEN analyzer_performance = 'false_positive' THEN 1 ELSE 0 END)::DECIMAL / NULLIF(COUNT(*), 0) * 100 as false_positive_rate,
    SUM(CASE WHEN analyzer_performance = 'false_negative' THEN 1 ELSE 0 END)::DECIMAL / NULLIF(COUNT(*), 0) * 100 as false_negative_rate

FROM query_evaluations
WHERE timestamp >= CURRENT_DATE - INTERVAL '30 days';

-- View for user-specific metrics
CREATE OR REPLACE VIEW user_evaluation_metrics AS
SELECT
    user_id,
    COUNT(*) as total_evaluations,
    AVG(confidence_score) as avg_confidence_score,
    AVG(regeneration_count) as avg_regeneration_count,
    SUM(CASE WHEN final_accepted THEN 1 ELSE 0 END)::DECIMAL / NULLIF(COUNT(*), 0) * 100 as acceptance_rate,
    SUM(CASE WHEN analyzer_performance = 'false_positive' THEN 1 ELSE 0 END) as false_positives,
    SUM(CASE WHEN analyzer_performance = 'false_negative' THEN 1 ELSE 0 END) as false_negatives
FROM query_evaluations
WHERE timestamp >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY user_id;

-- View for issue frequency analysis
CREATE OR REPLACE VIEW issue_frequency AS
SELECT
    issue_type,
    severity,
    COUNT(*) as occurrence_count,
    COUNT(DISTINCT evaluation_id) as affected_evaluations,
    AVG(qe.confidence_score) as avg_confidence_when_present
FROM analyzer_issues ai
JOIN query_evaluations qe ON ai.evaluation_id = qe.id
WHERE qe.timestamp >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY issue_type, severity
ORDER BY occurrence_count DESC;

-- Function to calculate F1 score
CREATE OR REPLACE FUNCTION calculate_f1_score(precision DECIMAL, recall DECIMAL)
RETURNS DECIMAL AS $$
BEGIN
    IF precision + recall = 0 THEN
        RETURN 0;
    END IF;
    RETURN 2 * (precision * recall) / (precision + recall);
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Materialized view for dashboard metrics (refresh periodically)
CREATE MATERIALIZED VIEW IF NOT EXISTS dashboard_metrics AS
SELECT
    DATE(timestamp) as date,
    COUNT(*) as queries_analyzed,
    AVG(confidence_score) as avg_confidence,
    SUM(CASE WHEN confidence_score >= 75 THEN 1 ELSE 0 END)::DECIMAL / NULLIF(COUNT(*), 0) * 100 as queries_above_threshold,
    AVG(regeneration_count) as avg_regenerations,
    SUM(CASE WHEN final_accepted THEN 1 ELSE 0 END)::DECIMAL / NULLIF(COUNT(*), 0) * 100 as acceptance_rate
FROM query_evaluations
WHERE timestamp >= CURRENT_DATE - INTERVAL '90 days'
GROUP BY DATE(timestamp)
ORDER BY date DESC;

CREATE UNIQUE INDEX idx_dashboard_metrics_date ON dashboard_metrics(date);

-- Sample queries for common analytics tasks

-- 1. Get false positives for review
-- SELECT qe.*, ai.issue_type, ai.description
-- FROM query_evaluations qe
-- LEFT JOIN analyzer_issues ai ON qe.id = ai.evaluation_id
-- WHERE qe.analyzer_performance = 'false_positive'
-- ORDER BY qe.timestamp DESC
-- LIMIT 50;

-- 2. Get false negatives to review threshold
-- SELECT qe.*, qe.confidence_score, qe.user_feedback
-- FROM query_evaluations qe
-- WHERE qe.analyzer_performance = 'false_negative'
-- ORDER BY qe.confidence_score DESC
-- LIMIT 50;

-- 3. Track threshold effectiveness over time
-- SELECT
--     DATE_TRUNC('week', timestamp) as week,
--     AVG(CASE WHEN confidence_score >= 75 THEN 1 ELSE 0 END) * 100 as pct_above_threshold,
--     AVG(CASE WHEN final_accepted THEN 1 ELSE 0 END) * 100 as pct_accepted
-- FROM query_evaluations
-- GROUP BY DATE_TRUNC('week', timestamp)
-- ORDER BY week DESC;

-- 4. Most common issues by type
-- SELECT issue_type, severity, COUNT(*) as count
-- FROM analyzer_issues
-- WHERE evaluation_id IN (
--     SELECT id FROM query_evaluations
--     WHERE timestamp >= CURRENT_DATE - INTERVAL '7 days'
-- )
-- GROUP BY issue_type, severity
-- ORDER BY count DESC;
