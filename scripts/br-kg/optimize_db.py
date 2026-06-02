import logging
import sqlite3
from pathlib import Path

import psutil


def setup_logging():
    logging.basicConfig(
        filename="data/br-kg/logs/optimization.log",
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )


def get_system_memory():
    """Get system memory information"""
    mem = psutil.virtual_memory()
    return {"total": mem.total, "available": mem.available, "percent": mem.percent}


def optimize_sqlite_connection(conn):
    """Optimize SQLite connection settings"""
    conn.execute("PRAGMA journal_mode = WAL")  # Write-Ahead Logging
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA mmap_size = 17179869184")  # 16GB
    conn.execute("PRAGMA page_size = 4096")
    conn.execute("PRAGMA cache_size = -8000000")  # 8GB cache
    conn.execute("PRAGMA busy_timeout = 60000")
    conn.execute("PRAGMA foreign_keys = ON")


def create_indexes(conn):
    """Create optimized indexes"""
    logging.info("Creating indexes...")
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_nodes_labels ON nodes(labels)",
        "CREATE INDEX IF NOT EXISTS idx_nodes_properties ON nodes(properties)",
        "CREATE INDEX IF NOT EXISTS idx_relationships_type ON relationships(type)",
        "CREATE INDEX IF NOT EXISTS idx_relationships_start ON relationships(start_node)",
        "CREATE INDEX IF NOT EXISTS idx_relationships_end ON relationships(end_node)",
        "CREATE INDEX IF NOT EXISTS idx_relationships_nodes ON relationships(start_node, end_node)",
    ]
    for idx in indexes:
        conn.execute(idx)
    conn.commit()


def vacuum_database(conn):
    """Vacuum database to optimize storage"""
    logging.info("Vacuuming database...")
    conn.execute("VACUUM")
    conn.commit()


def analyze_database(conn):
    """Analyze database statistics"""
    logging.info("Analyzing database...")
    conn.execute("ANALYZE")
    conn.commit()


def optimize_database(db_path):
    """Main optimization function"""
    raise RuntimeError(
        "SQLite optimize_db is deprecated. Use Neo4j admin tooling instead."
    )
    setup_logging()

    # Create directories if they don't exist
    Path("data/br-kg/logs").mkdir(parents=True, exist_ok=True)

    # Log system information
    mem_info = get_system_memory()
    logging.info(f"System memory: {mem_info}")

    # Connect to database
    logging.info(f"Connecting to database: {db_path}")
    conn = sqlite3.connect(db_path)

    try:
        # Optimize connection
        optimize_sqlite_connection(conn)
        logging.info("Connection optimized")

        # Create indexes
        create_indexes(conn)
        logging.info("Indexes created")

        # Analyze database
        analyze_database(conn)
        logging.info("Database analyzed")

        # Vacuum database
        vacuum_database(conn)
        logging.info("Database vacuumed")

    except Exception as e:
        logging.error(f"Error during optimization: {str(e)}")
        raise
    finally:
        conn.close()
        logging.info("Database optimization completed")


if __name__ == "__main__":
    db_path = "data/br-kg/db/br_kg_full.db"
    optimize_database(db_path)
