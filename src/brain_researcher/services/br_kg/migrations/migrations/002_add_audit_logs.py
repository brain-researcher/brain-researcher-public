"""
Migration: Add audit logging tables
Version: 002_add_audit_logs
Created: 2025-08-18
"""

from brain_researcher.services.br_kg.migrations import Migration
import sqlite3


class Migration_002(Migration):
    """
    Add audit logging tables for tracking API usage and data changes.
    """

    def __init__(self):
        super().__init__(
            version="002_add_audit_logs",
            description="Add audit logging tables"
        )

    def up(self, db):
        """
        Create audit log tables.
        """
        if isinstance(db, sqlite3.Connection):
            conn = db
        else:
            conn = sqlite3.connect(db.db_path)

        try:
            # Create audit_logs table for general API usage
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    user_id TEXT,
                    ip_address TEXT,
                    endpoint TEXT NOT NULL,
                    method TEXT NOT NULL,
                    status_code INTEGER,
                    response_time_ms INTEGER,
                    error_message TEXT,
                    request_body TEXT,
                    response_size INTEGER
                )
            """)

            # Create data_changes table for tracking modifications
            conn.execute("""
                CREATE TABLE IF NOT EXISTS data_changes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    user_id TEXT,
                    operation TEXT NOT NULL, -- INSERT, UPDATE, DELETE
                    entity_type TEXT NOT NULL, -- node, relationship
                    entity_id TEXT NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    change_reason TEXT
                )
            """)

            # Create query_logs table for tracking complex queries
            conn.execute("""
                CREATE TABLE IF NOT EXISTS query_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    user_id TEXT,
                    query_type TEXT NOT NULL, -- graphql, cypher, persisted
                    query_text TEXT NOT NULL,
                    execution_time_ms INTEGER,
                    result_count INTEGER,
                    cache_hit BOOLEAN DEFAULT FALSE
                )
            """)

            # Create indexes for efficient querying
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp
                ON audit_logs(timestamp DESC)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_logs_user
                ON audit_logs(user_id)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_data_changes_entity
                ON data_changes(entity_type, entity_id)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_data_changes_timestamp
                ON data_changes(timestamp DESC)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_query_logs_user
                ON query_logs(user_id)
            """)

            conn.commit()
            print("✓ Created audit logging tables")

        finally:
            if not isinstance(db, sqlite3.Connection):
                conn.close()

    def down(self, db):
        """
        Drop audit log tables.
        """
        if isinstance(db, sqlite3.Connection):
            conn = db
        else:
            conn = sqlite3.connect(db.db_path)

        try:
            # Drop indexes
            conn.execute("DROP INDEX IF EXISTS idx_query_logs_user")
            conn.execute("DROP INDEX IF EXISTS idx_data_changes_timestamp")
            conn.execute("DROP INDEX IF EXISTS idx_data_changes_entity")
            conn.execute("DROP INDEX IF EXISTS idx_audit_logs_user")
            conn.execute("DROP INDEX IF EXISTS idx_audit_logs_timestamp")

            # Drop tables
            conn.execute("DROP TABLE IF EXISTS query_logs")
            conn.execute("DROP TABLE IF EXISTS data_changes")
            conn.execute("DROP TABLE IF EXISTS audit_logs")

            conn.commit()
            print("✓ Dropped audit logging tables")

        finally:
            if not isinstance(db, sqlite3.Connection):
                conn.close()