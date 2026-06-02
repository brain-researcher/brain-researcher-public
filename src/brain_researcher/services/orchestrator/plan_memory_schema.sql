-- Plan Memory Schema (MVP - Slice 1)
-- Stores execution plans for learning, recall, and observability
--
-- This schema is used by PlanMemory (brain_researcher/services/agent/plan_memory.py)
-- to persist execution plans and track their outcomes.
--
-- Usage:
--   - Schema is auto-created by PlanMemory on initialization
--   - Can be used standalone with: sqlite3 plan_memory.db < plan_memory_schema.sql

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- Main plan records table
CREATE TABLE IF NOT EXISTS plan_records (
    -- Identity
    plan_id           TEXT PRIMARY KEY,
    created_at        INTEGER NOT NULL,
    finished_at       INTEGER,

    -- Ownership & Scope
    user_id           TEXT NOT NULL,
    workspace_id      TEXT,
    shared_level      TEXT NOT NULL DEFAULT 'user'
                      CHECK(shared_level IN ('user', 'workspace', 'global')),

    -- Query & Intent
    query_text        TEXT NOT NULL,
    query_hash        TEXT NOT NULL,  -- MD5 for exact-match dedup
    complexity_level  TEXT CHECK(complexity_level IN ('simple', 'complex', NULL)),
    complexity_reason TEXT,

    -- Plan Content
    plan_json         TEXT NOT NULL,  -- Serialized ExecutionPlan
    step_count        INTEGER NOT NULL,
    tools_used        TEXT,           -- JSON array of tool names

    -- Execution Outcome
    outcome           TEXT CHECK(outcome IN ('pending', 'succeeded', 'failed', 'cancelled'))
                      DEFAULT 'pending',
    execution_time_ms INTEGER,
    error_message     TEXT,

    -- Provenance
    source_plan_id    TEXT,           -- If adapted from another plan
    markdown_path     TEXT,           -- Path to human-readable .md file

    -- External tracker integration (Slice 3+)
    tracker_provider  TEXT,           -- Tracker provider key (e.g., linear)
    tracker_issue_id  TEXT,           -- Provider issue ID
    linear_issue_id   TEXT,           -- Deprecated compatibility column

    FOREIGN KEY(source_plan_id) REFERENCES plan_records(plan_id) ON DELETE SET NULL
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_plan_user_created
    ON plan_records(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_plan_workspace_shared
    ON plan_records(workspace_id, shared_level, outcome);

CREATE INDEX IF NOT EXISTS idx_plan_query_hash
    ON plan_records(query_hash);

CREATE INDEX IF NOT EXISTS idx_plan_outcome_created
    ON plan_records(outcome, created_at DESC);

-- Failure records for step-level recovery learning
CREATE TABLE IF NOT EXISTS failure_records (
    failure_id      TEXT PRIMARY KEY,
    plan_id         TEXT NOT NULL,
    created_at      INTEGER NOT NULL,
    step_id         TEXT,
    tool_id         TEXT,
    error_category  TEXT,
    recovery_action TEXT,
    is_retryable    INTEGER,
    error_message   TEXT,
    error_taxonomy  TEXT,
    recovery_actions TEXT,
    attempt         INTEGER,
    max_attempts    INTEGER,
    recovered       INTEGER,
    FOREIGN KEY(plan_id) REFERENCES plan_records(plan_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_failure_plan_created
    ON failure_records(plan_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_failure_category
    ON failure_records(error_category, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_failure_tool
    ON failure_records(tool_id, created_at DESC);


-- =============================================================================
-- FUTURE SLICES - Tables below are documented for completeness but not yet used
-- =============================================================================

-- Slice 2: Intent category for metrics grouping
-- ALTER TABLE plan_records ADD COLUMN intent_category TEXT;
-- CREATE INDEX IF NOT EXISTS idx_plan_intent_outcome ON plan_records(intent_category, outcome);

-- Slice 3: Embedding support (384-dim float32 from all-MiniLM-L6-v2)
-- ALTER TABLE plan_records ADD COLUMN query_embedding BLOB;

-- Slice 4: Plan feedback/ratings table (for learning)
-- CREATE TABLE IF NOT EXISTS plan_feedback (
--     feedback_id       INTEGER PRIMARY KEY AUTOINCREMENT,
--     plan_id           TEXT NOT NULL,
--     user_id           TEXT NOT NULL,
--     rating            INTEGER CHECK(rating BETWEEN 1 AND 5),
--     feedback_text     TEXT,
--     created_at        INTEGER NOT NULL,
--     FOREIGN KEY(plan_id) REFERENCES plan_records(plan_id) ON DELETE CASCADE
-- );

-- Slice 4: Plan metrics aggregation (updated periodically)
-- CREATE TABLE IF NOT EXISTS plan_metrics_daily (
--     metric_date       TEXT NOT NULL,  -- YYYY-MM-DD
--     intent_category   TEXT,
--     scope             TEXT NOT NULL,  -- user_id or workspace_id or 'global'
--     total_plans       INTEGER NOT NULL DEFAULT 0,
--     succeeded         INTEGER NOT NULL DEFAULT 0,
--     failed            INTEGER NOT NULL DEFAULT 0,
--     avg_execution_ms  INTEGER,
--     memory_reuse_count INTEGER NOT NULL DEFAULT 0,
--     PRIMARY KEY(metric_date, intent_category, scope)
-- );

-- Slice 4: Trigger to update daily metrics on plan completion
-- CREATE TRIGGER IF NOT EXISTS trg_update_plan_metrics
-- AFTER UPDATE OF outcome ON plan_records
-- WHEN NEW.outcome IN ('succeeded', 'failed')
-- BEGIN
--     INSERT INTO plan_metrics_daily (metric_date, intent_category, scope, total_plans, succeeded, failed)
--     VALUES (
--         date('now'),
--         NEW.intent_category,
--         NEW.user_id,
--         1,
--         CASE WHEN NEW.outcome = 'succeeded' THEN 1 ELSE 0 END,
--         CASE WHEN NEW.outcome = 'failed' THEN 1 ELSE 0 END
--     )
--     ON CONFLICT(metric_date, intent_category, scope) DO UPDATE SET
--         total_plans = total_plans + 1,
--         succeeded = succeeded + CASE WHEN NEW.outcome = 'succeeded' THEN 1 ELSE 0 END,
--         failed = failed + CASE WHEN NEW.outcome = 'failed' THEN 1 ELSE 0 END;
-- END;
