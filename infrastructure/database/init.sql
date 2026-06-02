-- Brain Researcher Database Initialization Script
-- This script sets up the database schema, users, and optimizations
-- for the Brain Researcher platform with connection pooling

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "btree_gist";

-- Create database if not exists (for development)
SELECT 'CREATE DATABASE brain_researcher'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'brain_researcher')\gexec

SELECT 'CREATE DATABASE brain_researcher_test'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'brain_researcher_test')\gexec

SELECT 'CREATE DATABASE br-kg'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'br-kg')\gexec

-- Connect to main database
\c brain_researcher;

-- Create application users with appropriate permissions
DO $$
BEGIN
    -- Read-only user for analytics
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'readonly') THEN
        CREATE ROLE readonly WITH LOGIN PASSWORD 'readonly_pass_change_me';
    END IF;

    -- Analytics user with more permissions
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'analytics') THEN
        CREATE ROLE analytics WITH LOGIN PASSWORD 'analytics_pass_change_me';
    END IF;

    -- Batch processing user
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'batch_user') THEN
        CREATE ROLE batch_user WITH LOGIN PASSWORD 'batch_pass_change_me';
    END IF;

    -- Service-specific users
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'orchestrator_user') THEN
        CREATE ROLE orchestrator_user WITH LOGIN PASSWORD 'orchestrator_pass_change_me';
    END IF;

    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'br_kg_user') THEN
        CREATE ROLE br_kg_user WITH LOGIN PASSWORD 'br_kg_pass_change_me';
    END IF;

    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'agent_user') THEN
        CREATE ROLE agent_user WITH LOGIN PASSWORD 'agent_pass_change_me';
    END IF;

    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'webui_user') THEN
        CREATE ROLE webui_user WITH LOGIN PASSWORD 'webui_pass_change_me';
    END IF;

    -- Monitoring user
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'grafana') THEN
        CREATE ROLE grafana WITH LOGIN PASSWORD 'grafana_pass_change_me';
    END IF;
END
$$;

-- Create schemas for different components
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS analytics;
CREATE SCHEMA IF NOT EXISTS ingestion;
CREATE SCHEMA IF NOT EXISTS kg;
CREATE SCHEMA IF NOT EXISTS monitoring;

-- Set default search path
ALTER DATABASE brain_researcher SET search_path TO core, public;

-- Core application tables
CREATE TABLE IF NOT EXISTS core.users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT true,
    last_login TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS core.sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES core.users(id) ON DELETE CASCADE,
    session_token VARCHAR(255) UNIQUE NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    ip_address INET,
    user_agent TEXT
);

CREATE TABLE IF NOT EXISTS core.jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES core.users(id) ON DELETE CASCADE,
    job_type VARCHAR(100) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    priority INTEGER DEFAULT 0,
    parameters JSONB,
    result JSONB,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS core.datasets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    type VARCHAR(100) NOT NULL,
    source VARCHAR(255),
    metadata JSONB,
    file_paths JSONB,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    is_public BOOLEAN DEFAULT false,
    owner_id UUID REFERENCES core.users(id)
);

-- Knowledge graph tables
CREATE TABLE IF NOT EXISTS kg.entities (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    type VARCHAR(100) NOT NULL,
    name VARCHAR(255) NOT NULL,
    properties JSONB,
    embeddings VECTOR(768), -- Assuming 768-dimensional embeddings
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS kg.relationships (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id UUID REFERENCES kg.entities(id) ON DELETE CASCADE,
    target_id UUID REFERENCES kg.entities(id) ON DELETE CASCADE,
    relationship_type VARCHAR(100) NOT NULL,
    properties JSONB,
    weight FLOAT DEFAULT 1.0,
    confidence FLOAT DEFAULT 1.0,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Analytics tables
CREATE TABLE IF NOT EXISTS analytics.query_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES core.users(id),
    query_type VARCHAR(100),
    query_text TEXT,
    parameters JSONB,
    execution_time_ms INTEGER,
    result_count INTEGER,
    status VARCHAR(50),
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analytics.usage_metrics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    metric_type VARCHAR(100) NOT NULL,
    metric_name VARCHAR(255) NOT NULL,
    value FLOAT NOT NULL,
    dimensions JSONB,
    timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    aggregation_window INTERVAL
);

CREATE TABLE IF NOT EXISTS analytics.performance_metrics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    service_name VARCHAR(100) NOT NULL,
    metric_type VARCHAR(100) NOT NULL,
    value FLOAT NOT NULL,
    tags JSONB,
    timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Ingestion tables
CREATE TABLE IF NOT EXISTS ingestion.ingestion_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_type VARCHAR(100) NOT NULL,
    source_type VARCHAR(100) NOT NULL,
    source_location TEXT NOT NULL,
    target_location TEXT,
    parameters JSONB,
    status VARCHAR(50) DEFAULT 'pending',
    progress FLOAT DEFAULT 0.0,
    total_items INTEGER,
    processed_items INTEGER DEFAULT 0,
    failed_items INTEGER DEFAULT 0,
    error_log JSONB,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS ingestion.data_sources (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    type VARCHAR(100) NOT NULL,
    connection_string TEXT,
    configuration JSONB,
    is_active BOOLEAN DEFAULT true,
    last_sync_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Monitoring tables
CREATE TABLE IF NOT EXISTS monitoring.health_checks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    service_name VARCHAR(100) NOT NULL,
    check_type VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL,
    response_time_ms INTEGER,
    details JSONB,
    timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS monitoring.alerts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    alert_type VARCHAR(100) NOT NULL,
    severity VARCHAR(50) NOT NULL,
    message TEXT NOT NULL,
    details JSONB,
    acknowledged BOOLEAN DEFAULT false,
    resolved BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    acknowledged_at TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ
);

-- Create indexes for performance
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_username ON core.users(username);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_email ON core.users(email);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sessions_token ON core.sessions(session_token);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sessions_user_id ON core.sessions(user_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_jobs_user_id ON core.jobs(user_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_jobs_status ON core.jobs(status);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_jobs_created_at ON core.jobs(created_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_datasets_owner_id ON core.datasets(owner_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_datasets_type ON core.datasets(type);

-- Knowledge graph indexes
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_entities_type ON kg.entities(type);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_entities_name ON kg.entities USING gin(name gin_trgm_ops);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_relationships_source ON kg.relationships(source_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_relationships_target ON kg.relationships(target_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_relationships_type ON kg.relationships(relationship_type);

-- Analytics indexes
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_query_logs_user_id ON analytics.query_logs(user_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_query_logs_created_at ON analytics.query_logs(created_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_usage_metrics_timestamp ON analytics.usage_metrics(timestamp);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_performance_metrics_service ON analytics.performance_metrics(service_name, timestamp);

-- Monitoring indexes
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_health_checks_service ON monitoring.health_checks(service_name, timestamp);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_alerts_created_at ON monitoring.alerts(created_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_alerts_severity ON monitoring.alerts(severity, resolved);

-- Grant permissions

-- Read-only user permissions
GRANT USAGE ON SCHEMA core, analytics, kg, monitoring TO readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA core, analytics, kg, monitoring TO readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA core, analytics, kg, monitoring GRANT SELECT ON TABLES TO readonly;

-- Analytics user permissions (read + limited write to analytics schema)
GRANT USAGE ON SCHEMA core, analytics, kg, monitoring TO analytics;
GRANT SELECT ON ALL TABLES IN SCHEMA core, kg, monitoring TO analytics;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA analytics TO analytics;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA analytics TO analytics;
ALTER DEFAULT PRIVILEGES IN SCHEMA analytics GRANT SELECT, INSERT, UPDATE ON TABLES TO analytics;

-- Batch user permissions (for data ingestion)
GRANT USAGE ON SCHEMA ingestion, core TO batch_user;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA ingestion TO batch_user;
GRANT INSERT, UPDATE ON core.datasets TO batch_user;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA ingestion, core TO batch_user;

-- Service-specific permissions
GRANT USAGE ON SCHEMA core TO orchestrator_user, agent_user, webui_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA core TO orchestrator_user;
GRANT SELECT, INSERT, UPDATE ON core.jobs, core.sessions TO agent_user;
GRANT SELECT ON ALL TABLES IN SCHEMA core TO webui_user;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA core TO orchestrator_user, agent_user, webui_user;

GRANT USAGE ON SCHEMA kg TO br_kg_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA kg TO br_kg_user;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA kg TO br_kg_user;

-- Monitoring user permissions
GRANT USAGE ON SCHEMA monitoring, analytics TO grafana;
GRANT SELECT ON ALL TABLES IN SCHEMA monitoring, analytics TO grafana;

-- Create functions for common operations

-- Function to update timestamps
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create triggers for updated_at columns
CREATE TRIGGER trigger_users_updated_at
    BEFORE UPDATE ON core.users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trigger_jobs_updated_at
    BEFORE UPDATE ON core.jobs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trigger_datasets_updated_at
    BEFORE UPDATE ON core.datasets
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trigger_entities_updated_at
    BEFORE UPDATE ON kg.entities
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Function for job queue management
CREATE OR REPLACE FUNCTION get_next_job(job_types VARCHAR[] DEFAULT NULL)
RETURNS UUID AS $$
DECLARE
    job_id UUID;
BEGIN
    SELECT id INTO job_id
    FROM core.jobs
    WHERE status = 'pending'
      AND (job_types IS NULL OR job_type = ANY(job_types))
    ORDER BY priority DESC, created_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED;

    IF job_id IS NOT NULL THEN
        UPDATE core.jobs
        SET status = 'running', started_at = CURRENT_TIMESTAMP
        WHERE id = job_id;
    END IF;

    RETURN job_id;
END;
$$ LANGUAGE plpgsql;

-- Function for cleanup operations
CREATE OR REPLACE FUNCTION cleanup_old_sessions()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM core.sessions
    WHERE expires_at < CURRENT_TIMESTAMP;

    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Function for analytics aggregation
CREATE OR REPLACE FUNCTION aggregate_usage_metrics(
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ,
    window_size INTERVAL
)
RETURNS TABLE(
    metric_type VARCHAR,
    metric_name VARCHAR,
    avg_value FLOAT,
    min_value FLOAT,
    max_value FLOAT,
    count_value BIGINT,
    time_bucket TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        um.metric_type,
        um.metric_name,
        AVG(um.value)::FLOAT as avg_value,
        MIN(um.value)::FLOAT as min_value,
        MAX(um.value)::FLOAT as max_value,
        COUNT(*)::BIGINT as count_value,
        date_trunc(window_size::TEXT, um.timestamp) as time_bucket
    FROM analytics.usage_metrics um
    WHERE um.timestamp >= start_time
      AND um.timestamp <= end_time
    GROUP BY um.metric_type, um.metric_name, date_trunc(window_size::TEXT, um.timestamp)
    ORDER BY time_bucket;
END;
$$ LANGUAGE plpgsql;

-- Optimize PostgreSQL settings for connection pooling
-- These settings work well with PgBouncer transaction pooling

-- Connection and memory settings
ALTER SYSTEM SET max_connections = 200;  -- Lower since PgBouncer handles connections
ALTER SYSTEM SET shared_buffers = '256MB';
ALTER SYSTEM SET effective_cache_size = '1GB';
ALTER SYSTEM SET work_mem = '4MB';
ALTER SYSTEM SET maintenance_work_mem = '64MB';

-- Query optimization
ALTER SYSTEM SET random_page_cost = 1.1;
ALTER SYSTEM SET effective_io_concurrency = 200;
ALTER SYSTEM SET min_wal_size = '1GB';
ALTER SYSTEM SET max_wal_size = '4GB';

-- Connection optimization
ALTER SYSTEM SET tcp_keepalives_idle = 600;
ALTER SYSTEM SET tcp_keepalives_interval = 30;
ALTER SYSTEM SET tcp_keepalives_count = 3;

-- Logging for monitoring
ALTER SYSTEM SET log_min_duration_statement = 1000;  -- Log slow queries
ALTER SYSTEM SET log_connections = on;
ALTER SYSTEM SET log_disconnections = on;
ALTER SYSTEM SET log_line_prefix = '%t [%p-%l] %q%u@%d ';

-- Enable query statistics
ALTER SYSTEM SET shared_preload_libraries = 'pg_stat_statements';
ALTER SYSTEM SET pg_stat_statements.track = all;

-- Reload configuration
SELECT pg_reload_conf();

-- Insert initial monitoring data
INSERT INTO monitoring.health_checks (service_name, check_type, status, response_time_ms, details)
VALUES ('database', 'initialization', 'healthy', 0, '{"message": "Database initialized successfully"}')
ON CONFLICT DO NOTHING;

-- Create some sample data for testing (only in development)
DO $$
BEGIN
    IF current_database() LIKE '%test%' OR current_database() = 'brain_researcher' THEN
        -- Insert test user
        INSERT INTO core.users (username, email, password_hash, is_active)
        VALUES ('testuser', 'test@example.com', 'test_hash', true)
        ON CONFLICT (username) DO NOTHING;

        -- Insert sample dataset
        INSERT INTO core.datasets (name, description, type, source, is_public)
        VALUES ('Sample Dataset', 'A sample dataset for testing', 'fmri', 'test_source', true)
        ON CONFLICT DO NOTHING;
    END IF;
END $$;

-- Final status message
DO $$
BEGIN
    RAISE NOTICE 'Brain Researcher database initialization completed successfully';
    RAISE NOTICE 'Database: %', current_database();
    RAISE NOTICE 'Schemas created: core, analytics, ingestion, kg, monitoring';
    RAISE NOTICE 'Users created: readonly, analytics, batch_user, service users';
    RAISE NOTICE 'Remember to:';
    RAISE NOTICE '1. Change default passwords in production';
    RAISE NOTICE '2. Configure PgBouncer userlist.txt with proper password hashes';
    RAISE NOTICE '3. Set up monitoring and alerting';
    RAISE NOTICE '4. Review and adjust PostgreSQL configuration';
END $$;