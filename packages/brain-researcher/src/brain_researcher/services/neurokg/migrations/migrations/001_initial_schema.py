"""
Migration: Initial BR-KG Schema
Version: 001_initial_schema
Created: 2025-08-18
"""

from brain_researcher.services.neurokg.migrations import Migration
import sqlite3


class Migration_001(Migration):
    """
    Create initial BR-KG schema with core tables and indexes.
    """
    
    def __init__(self):
        super().__init__(
            version="001_initial_schema",
            description="Create initial BR-KG schema"
        )
    
    def up(self, db):
        """
        Create initial schema.
        """
        # Check if this is a SQLite connection or NeuroKGGraphDB
        if isinstance(db, sqlite3.Connection):
            conn = db
        else:
            # For NeuroKGGraphDB, get the underlying connection
            conn = sqlite3.connect(db.db_path)
        
        try:
            # Create nodes table if it doesn't exist
            conn.execute("""
                CREATE TABLE IF NOT EXISTS nodes (
                    id TEXT PRIMARY KEY,
                    node_type TEXT NOT NULL,
                    properties TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create relationships table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS relationships (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    rel_type TEXT NOT NULL,
                    properties TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (source_id) REFERENCES nodes(id),
                    FOREIGN KEY (target_id) REFERENCES nodes(id)
                )
            """)
            
            # Create indexes for performance
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_nodes_type 
                ON nodes(node_type)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_relationships_source 
                ON relationships(source_id)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_relationships_target 
                ON relationships(target_id)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_relationships_type 
                ON relationships(rel_type)
            """)
            
            # Create metadata table for storing graph-level information
            conn.execute("""
                CREATE TABLE IF NOT EXISTS graph_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Insert initial metadata
            conn.execute("""
                INSERT OR REPLACE INTO graph_metadata (key, value)
                VALUES ('schema_version', '1.0'),
                       ('graph_name', 'BR-KG'),
                       ('created_at', datetime('now'))
            """)
            
            conn.commit()
            print("✓ Created initial schema tables and indexes")
            
        finally:
            if not isinstance(db, sqlite3.Connection):
                conn.close()
    
    def down(self, db):
        """
        Drop initial schema.
        """
        # Check if this is a SQLite connection or NeuroKGGraphDB
        if isinstance(db, sqlite3.Connection):
            conn = db
        else:
            conn = sqlite3.connect(db.db_path)
        
        try:
            # Drop indexes first
            conn.execute("DROP INDEX IF EXISTS idx_relationships_type")
            conn.execute("DROP INDEX IF EXISTS idx_relationships_target")
            conn.execute("DROP INDEX IF EXISTS idx_relationships_source")
            conn.execute("DROP INDEX IF EXISTS idx_nodes_type")
            
            # Drop tables
            conn.execute("DROP TABLE IF EXISTS graph_metadata")
            conn.execute("DROP TABLE IF EXISTS relationships")
            conn.execute("DROP TABLE IF EXISTS nodes")
            
            conn.commit()
            print("✓ Dropped initial schema tables and indexes")
            
        finally:
            if not isinstance(db, sqlite3.Connection):
                conn.close()