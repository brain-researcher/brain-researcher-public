-- SQLite schema for Brain Researcher Job Queue
-- Optimized for concurrent reads/writes with WAL mode

-- Enable Write-Ahead Logging for better concurrency
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA busy_timeout=5000;

-- ============================================================================
-- Main Jobs Table
-- ============================================================================
CREATE TABLE IF NOT EXISTS jobs (
    -- Identity
    job_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,  -- 'tool', 'dag', 'batch'
    payload_json TEXT NOT NULL,  -- JSON blob with tool params, steps, artifacts

    -- State tracking
    state TEXT NOT NULL,  -- pending, queued, claimed, running, succeeded, failed, cancelled, timeout, skipped, paused, retrying
    priority INTEGER NOT NULL DEFAULT 0,

    -- Timestamps (Unix epoch seconds)
    created_at INTEGER NOT NULL,
    queued_at INTEGER,
    claimed_at INTEGER,
    started_at INTEGER,
    finished_at INTEGER,
    run_after INTEGER,  -- Delayed execution support

    -- Worker tracking
    worker_id TEXT,
    lease_expires_at INTEGER,
    last_heartbeat INTEGER,

    -- Retry logic
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,

    -- Cancellation
    cancel_reason TEXT,
    cancellation_requested INTEGER NOT NULL DEFAULT 0,  -- Boolean: 0=false, 1=true

    -- Execution results
    exit_code INTEGER,
    error_message TEXT,
    skip_reason TEXT,

    -- GPU tracking
    gpu_req INTEGER NOT NULL DEFAULT 0,
    gpu_type TEXT,

    -- CPU/Memory/Walltime tracking
    cpus INTEGER NOT NULL DEFAULT 1,
    memory_gb REAL NOT NULL DEFAULT 4.0,
    walltime_minutes INTEGER NOT NULL DEFAULT 60,
    backend TEXT,
    job_name TEXT,

    -- Provenance
    run_id TEXT,
    run_dir TEXT,
    provenance_path TEXT,

    -- User context
    user_id TEXT,
    session_id TEXT,
    project_id TEXT,

    -- Audit
    updated_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
);

-- ============================================================================
-- Projects Table
-- ============================================================================
CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    is_archived INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_projects_archived
    ON projects(is_archived, updated_at DESC);

-- ============================================================================
-- Indexes for Performance
-- ============================================================================

-- Primary index for claim_next query (most critical for performance)
CREATE INDEX IF NOT EXISTS idx_jobs_state_priority_created
    ON jobs(state, priority DESC, created_at ASC);

-- Index for delayed execution queries
CREATE INDEX IF NOT EXISTS idx_jobs_run_after
    ON jobs(run_after) WHERE run_after IS NOT NULL;

-- Index for recovery sweeper (finding stale leases)
CREATE INDEX IF NOT EXISTS idx_jobs_lease_expires
    ON jobs(lease_expires_at) WHERE lease_expires_at IS NOT NULL;

-- Index for worker queries
CREATE INDEX IF NOT EXISTS idx_jobs_worker_id
    ON jobs(worker_id) WHERE worker_id IS NOT NULL;

-- Index for user job lookup
CREATE INDEX IF NOT EXISTS idx_jobs_user_id
    ON jobs(user_id) WHERE user_id IS NOT NULL;

-- Index for project-scoped listing
CREATE INDEX IF NOT EXISTS idx_jobs_project_id
    ON jobs(project_id) WHERE project_id IS NOT NULL;

-- Composite index for user+project recent listings
CREATE INDEX IF NOT EXISTS idx_jobs_user_project_created
    ON jobs(user_id, project_id, created_at DESC);

-- ============================================================================
-- GPU Slots Table
-- ============================================================================
CREATE TABLE IF NOT EXISTS gpu_slots (
    id INTEGER PRIMARY KEY,  -- Slot number (1, 2, 3, ...)
    in_use INTEGER NOT NULL DEFAULT 0,  -- Boolean: 0=free, 1=allocated
    job_id TEXT,  -- Which job owns this slot (NULL if free)
    updated_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),

    FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE SET NULL
);

-- Index for finding free GPU slots
CREATE INDEX IF NOT EXISTS idx_gpu_slots_in_use
    ON gpu_slots(in_use, id);

-- ============================================================================
-- Job Logs Table (for streaming stdout/stderr)
-- ============================================================================
CREATE TABLE IF NOT EXISTS job_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    offset INTEGER NOT NULL,  -- Line offset for streaming
    stream TEXT NOT NULL,  -- 'stdout' or 'stderr'
    payload BLOB NOT NULL,  -- Log content
    created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),

    UNIQUE(job_id, stream, offset),
    FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_job_logs_job_id
    ON job_logs(job_id, stream, offset);

-- ============================================================================
-- Audit Log Table (for debugging and compliance)
-- ============================================================================
CREATE TABLE IF NOT EXISTS job_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    event_type TEXT NOT NULL,  -- 'enqueued', 'claimed', 'started', 'completed', 'failed', 'cancelled', 'recovered'
    payload_json TEXT,  -- Additional event metadata
    created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),

    FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_job_audit_job_id
    ON job_audit(job_id, created_at);

-- ============================================================================
-- Triggers
-- ============================================================================

-- Auto-update timestamp on job changes
CREATE TRIGGER IF NOT EXISTS trg_jobs_update_timestamp
    AFTER UPDATE ON jobs
    FOR EACH ROW
    BEGIN
        UPDATE jobs
        SET updated_at = strftime('%s','now')
        WHERE job_id = NEW.job_id;
    END;

-- Auto-release GPU slots when job reaches terminal state
CREATE TRIGGER IF NOT EXISTS trg_gpu_release_on_terminal
    AFTER UPDATE ON jobs
    FOR EACH ROW
    WHEN NEW.state IN ('succeeded','failed','cancelled','timeout','skipped')
    BEGIN
        UPDATE gpu_slots
        SET in_use = 0,
            job_id = NULL,
            updated_at = strftime('%s','now')
        WHERE job_id = NEW.job_id;
    END;

-- ============================================================================
-- Cache Table (P2.5 - Deterministic Result Cache)
-- ============================================================================
CREATE TABLE IF NOT EXISTS run_cache (
    -- Identity
    cache_key TEXT PRIMARY KEY,  -- sha256:... format
    run_id TEXT NOT NULL,
    run_dir TEXT NOT NULL,

    -- State tracking (pending prevents race conditions)
    state TEXT NOT NULL DEFAULT 'pending',  -- pending, completed, failed

    -- Metadata (JSON blob with tool, version, params summary)
    meta_json TEXT NOT NULL,

    -- Timestamps
    created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    last_accessed_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),

    -- Indexable fields for cache invalidation
    tool_version TEXT,
    git_sha TEXT,

    -- Size tracking for LRU eviction
    size_bytes INTEGER
);

-- Index for LRU eviction (find oldest entries)
CREATE INDEX IF NOT EXISTS idx_cache_accessed
    ON run_cache(last_accessed_at);

-- Index for tool-based cache invalidation
CREATE INDEX IF NOT EXISTS idx_cache_tool
    ON run_cache(tool_version);

-- Index for git-based cache invalidation
CREATE INDEX IF NOT EXISTS idx_cache_git
    ON run_cache(git_sha) WHERE git_sha IS NOT NULL;

-- Trigger to update last_accessed_at on lookup
CREATE TRIGGER IF NOT EXISTS trg_cache_update_accessed
    AFTER UPDATE ON run_cache
    FOR EACH ROW
    WHEN OLD.state = 'pending' AND NEW.state = 'completed'
    BEGIN
        UPDATE run_cache
        SET last_accessed_at = strftime('%s','now')
        WHERE cache_key = NEW.cache_key;
    END;

-- ============================================================================
-- Benchmark Board Tables (Phase 1)
-- ============================================================================

CREATE TABLE IF NOT EXISTS benchmark_datasets (
    dataset_id TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    source_type TEXT NOT NULL,  -- registry|file|inline|huggingface
    source_ref_json TEXT NOT NULL,  -- JSON: url/repo/commit
    status TEXT NOT NULL DEFAULT 'active',  -- active|deprecated
    imported_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS benchmark_tasks (
    dataset_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    task_spec_json TEXT NOT NULL,  -- Full TaskSpecV1 JSON
    source_created_by_name TEXT,
    source_category TEXT,
    source_difficulty TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (dataset_id, task_id),
    FOREIGN KEY (dataset_id) REFERENCES benchmark_datasets(dataset_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS benchmark_task_governance (
    dataset_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'imported',  -- imported|triaged|validated|active|deprecated|archived
    category TEXT,
    notes TEXT,
    owner TEXT,
    created_by_name TEXT,
    created_by_email TEXT,
    created_by_profile TEXT,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (dataset_id, task_id),
    FOREIGN KEY (dataset_id, task_id) REFERENCES benchmark_tasks(dataset_id, task_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS benchmark_task_tags (
    dataset_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    PRIMARY KEY (dataset_id, task_id, tag),
    FOREIGN KEY (dataset_id, task_id) REFERENCES benchmark_tasks(dataset_id, task_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS benchmark_task_validations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    validator TEXT NOT NULL,
    type TEXT NOT NULL,  -- manual_review|ci_tests|oracle_solution|security_audit|llm_judge
    result TEXT NOT NULL,  -- pass|fail|needs_fix
    evidence_url TEXT,
    notes TEXT,
    validated_at INTEGER NOT NULL,
    FOREIGN KEY (dataset_id, task_id) REFERENCES benchmark_tasks(dataset_id, task_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS benchmark_import_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id TEXT NOT NULL,
    version TEXT NOT NULL,
    source_url TEXT,
    started_at INTEGER NOT NULL,
    finished_at INTEGER,
    status TEXT NOT NULL,  -- running|succeeded|failed|partial
    summary_json TEXT  -- Counts: added/updated/skipped/failed
);

-- Benchmark indexes
CREATE INDEX IF NOT EXISTS idx_benchmark_governance_status
    ON benchmark_task_governance(status);
CREATE INDEX IF NOT EXISTS idx_benchmark_governance_category
    ON benchmark_task_governance(category) WHERE category IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_benchmark_tags_tag
    ON benchmark_task_tags(tag);
CREATE INDEX IF NOT EXISTS idx_benchmark_validations_task
    ON benchmark_task_validations(dataset_id, task_id);
CREATE INDEX IF NOT EXISTS idx_benchmark_tasks_category
    ON benchmark_tasks(source_category) WHERE source_category IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_benchmark_tasks_difficulty
    ON benchmark_tasks(source_difficulty) WHERE source_difficulty IS NOT NULL;

-- ============================================================================
-- Schema Version
-- ============================================================================
-- Store schema version for future migrations
PRAGMA user_version = 5;  -- Benchmark board governance created_by fields
