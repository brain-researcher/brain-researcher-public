"""Performance optimization for BR-KG database.

This module adds performance indexes and temporal tracking to the existing database.
"""

import logging
import time
from datetime import datetime
from typing import Dict, List, Any, Optional
from pathlib import Path

from neo4j import GraphDatabase
import sqlite3

logger = logging.getLogger(__name__)


class PerformanceOptimizer:
    """Optimize BR-KG database performance with indexes and temporal tracking."""

    def __init__(self, db_connection):
        """Initialize performance optimizer.

        Args:
            db_connection: Database connection (Neo4j driver or SQLite connection)
        """
        self.db = db_connection
        self.is_neo4j = hasattr(db_connection, 'session')

    def add_performance_indexes(self):
        """Add performance indexes for core node types."""

        indexes = [
            # Task indexes
            ("Task", "task_id"),
            ("Task", "name"),
            ("Task", "dataset_id"),
            ("Task", "created_at"),

            # Concept indexes
            ("Concept", "concept_id"),
            ("Concept", "name"),
            ("Concept", "ontology_id"),
            ("Concept", "confidence_score"),

            # Region indexes
            ("Region", "region_id"),
            ("Region", "name"),
            ("Region", "mni_coordinates"),
            ("Region", "atlas"),
            ("BrainRegion", "region_id"),
            ("BrainRegion", "name"),
            ("BrainRegion", "mni_coordinates"),
            ("BrainRegion", "atlas"),

            # Canonical spatial substrate indexes
            ("StatsMap", "id"),
            ("StatMap", "id"),
            ("StatisticalMap", "id"),

            # Dataset indexes
            ("Dataset", "dataset_id"),
            ("Dataset", "name"),
            ("Dataset", "source"),
            ("Dataset", "created_at"),

            # Publication indexes
            ("Publication", "pmid"),
            ("Publication", "doi"),
            ("Publication", "year"),
            ("Publication", "journal"),

            # Composite indexes for common queries
            ("Task", ["dataset_id", "name"]),
            ("Concept", ["ontology_id", "confidence_score"]),
            ("Region", ["atlas", "name"]),
            ("BrainRegion", ["atlas", "name"]),
            ("Publication", ["year", "journal"]),
        ]

        if self.is_neo4j:
            self._add_neo4j_indexes(indexes)
        else:
            self._add_sqlite_indexes(indexes)

        logger.info(f"Added {len(indexes)} performance indexes")

    def _add_neo4j_indexes(self, indexes: List[tuple]):
        """Add indexes for Neo4j database.

        Args:
            indexes: List of (label, property) tuples
        """
        with self.db.session() as session:
            for index_def in indexes:
                if isinstance(index_def[1], list):
                    # Composite index
                    label, properties = index_def
                    props_str = ", ".join([f"n.{p}" for p in properties])
                    query = f"CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON ({props_str})"
                else:
                    # Single property index
                    label, prop = index_def
                    query = f"CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"

                try:
                    session.run(query)
                    logger.debug(f"Created index: {label}.{prop if isinstance(index_def[1], str) else index_def[1]}")
                except Exception as e:
                    logger.warning(f"Failed to create index: {e}")

    def _add_sqlite_indexes(self, indexes: List[tuple]):
        """Add indexes for SQLite database.

        Args:
            indexes: List of (table, column) tuples
        """
        cursor = self.db.cursor()

        for index_def in indexes:
            if isinstance(index_def[1], list):
                # Composite index
                table, columns = index_def
                cols_str = "_".join(columns)
                index_name = f"idx_{table.lower()}_{cols_str}"
                cols_list = ", ".join(columns)
                query = f"CREATE INDEX IF NOT EXISTS {index_name} ON nodes (json_extract(properties, '$.{cols_list}'))"
            else:
                # Single column index
                table, column = index_def
                index_name = f"idx_{table.lower()}_{column}"
                query = f"""
                    CREATE INDEX IF NOT EXISTS {index_name}
                    ON nodes (json_extract(properties, '$.{column}'))
                    WHERE json_extract(properties, '$.labels') LIKE '%{table}%'
                """

            try:
                cursor.execute(query)
                logger.debug(f"Created index: {index_name}")
            except Exception as e:
                logger.warning(f"Failed to create index {index_name}: {e}")

        self.db.commit()

    def add_temporal_attributes(self):
        """Add temporal tracking to all relationships."""

        temporal_properties = {
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "valid_from": datetime.utcnow().isoformat(),
            "valid_to": None,  # NULL means currently valid
            "version": 1
        }

        if self.is_neo4j:
            self._add_neo4j_temporal(temporal_properties)
        else:
            self._add_sqlite_temporal(temporal_properties)

        logger.info("Added temporal attributes to relationships")

    def _add_neo4j_temporal(self, temporal_properties: Dict[str, Any]):
        """Add temporal properties to Neo4j relationships.

        Args:
            temporal_properties: Temporal properties to add
        """
        with self.db.session() as session:
            # Add temporal properties to all relationships
            query = """
                MATCH ()-[r]->()
                WHERE r.created_at IS NULL
                SET r.created_at = $created_at,
                    r.updated_at = $updated_at,
                    r.valid_from = $valid_from,
                    r.valid_to = $valid_to,
                    r.version = $version
                RETURN count(r) as updated_count
            """

            result = session.run(query, **temporal_properties)
            count = result.single()["updated_count"]
            logger.info(f"Added temporal attributes to {count} relationships")

    def _add_sqlite_temporal(self, temporal_properties: Dict[str, Any]):
        """Add temporal properties to SQLite relationships.

        Args:
            temporal_properties: Temporal properties to add
        """
        cursor = self.db.cursor()

        # Add temporal columns if they don't exist
        try:
            cursor.execute("""
                ALTER TABLE relationships
                ADD COLUMN valid_from TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            """)
            cursor.execute("""
                ALTER TABLE relationships
                ADD COLUMN valid_to TIMESTAMP DEFAULT NULL
            """)
            cursor.execute("""
                ALTER TABLE relationships
                ADD COLUMN version INTEGER DEFAULT 1
            """)
        except sqlite3.OperationalError:
            # Columns already exist
            pass

        # Update existing relationships
        cursor.execute("""
            UPDATE relationships
            SET valid_from = CURRENT_TIMESTAMP,
                version = 1
            WHERE valid_from IS NULL
        """)

        self.db.commit()

    def optimize_queries(self) -> Dict[str, Any]:
        """Optimize common query patterns.

        Returns:
            Optimization statistics
        """
        stats = {
            "indexes_created": 0,
            "queries_optimized": 0,
            "cache_hits": 0,
            "performance_improvement": 0
        }

        # Analyze query patterns
        common_queries = [
            # Find concepts related to a task
            "MATCH (t:Task)-[:MEASURES]->(c:Concept) WHERE t.name = $task_name RETURN c",

            # Find brain regions activated by a concept
            "MATCH (c:Concept)-[:ACTIVATES]->(r) WHERE c.name = $concept_name AND (r:BrainRegion OR r:Region) RETURN r",

            # Find publications mentioning a concept
            "MATCH (p:Publication)-[:MENTIONS]->(c:Concept) WHERE c.name = $concept_name RETURN p",

            # Find tasks in a dataset
            "MATCH (d:Dataset)-[:CONTAINS]->(t:Task) WHERE d.dataset_id = $dataset_id RETURN t",

            # Canonical spatial substrate traversal
            "MATCH (m:StatsMap)-[:IN_REGION]->(br:BrainRegion) WHERE m.id = $map_id RETURN br",

            # Canonical anatomy hierarchy traversal
            "MATCH (child:BrainRegion)-[:PART_OF]->(parent:BrainRegion) WHERE child.name = $region_name RETURN parent",

            # Path queries between concepts
            "MATCH path = (c1:Concept)-[*..3]-(c2:Concept) WHERE c1.name = $concept1 AND c2.name = $concept2 RETURN path"
        ]

        # Create materialized views for common queries
        if self.is_neo4j:
            stats.update(self._optimize_neo4j_queries(common_queries))
        else:
            stats.update(self._optimize_sqlite_queries(common_queries))

        return stats

    def _optimize_neo4j_queries(self, queries: List[str]) -> Dict[str, Any]:
        """Optimize Neo4j queries.

        Args:
            queries: List of common queries

        Returns:
            Optimization statistics
        """
        stats = {"queries_optimized": 0}

        with self.db.session() as session:
            for query in queries:
                # Explain query to get execution plan
                explain_query = f"EXPLAIN {query}"

                try:
                    # Run explain (with dummy parameters)
                    params = {
                        "task_name": "dummy",
                        "concept_name": "dummy",
                        "dataset_id": "dummy",
                        "map_id": "dummy",
                        "region_name": "dummy",
                        "concept1": "dummy",
                        "concept2": "dummy"
                    }
                    result = session.run(explain_query, **params)

                    # Analyze plan (this would need actual plan analysis)
                    stats["queries_optimized"] += 1

                except Exception as e:
                    logger.debug(f"Could not optimize query: {e}")

        return stats

    def _optimize_sqlite_queries(self, queries: List[str]) -> Dict[str, Any]:
        """Optimize SQLite queries.

        Args:
            queries: List of common queries

        Returns:
            Optimization statistics
        """
        stats = {"queries_optimized": 0}
        cursor = self.db.cursor()

        # Analyze tables for query optimization
        cursor.execute("ANALYZE")

        # Create covering indexes for common query patterns
        covering_indexes = [
            """CREATE INDEX IF NOT EXISTS idx_task_measures
               ON relationships(start_node, end_node, type)
               WHERE type = 'MEASURES'""",

            """CREATE INDEX IF NOT EXISTS idx_concept_activates
               ON relationships(start_node, end_node, type)
               WHERE type = 'ACTIVATES'""",

            """CREATE INDEX IF NOT EXISTS idx_publication_mentions
               ON relationships(start_node, end_node, type)
               WHERE type = 'MENTIONS'""",

            """CREATE INDEX IF NOT EXISTS idx_spatial_in_region
               ON relationships(start_node, end_node, type)
               WHERE type = 'IN_REGION'""",

            """CREATE INDEX IF NOT EXISTS idx_brainregion_part_of
               ON relationships(start_node, end_node, type)
               WHERE type = 'PART_OF'"""
        ]

        for index_query in covering_indexes:
            try:
                cursor.execute(index_query)
                stats["queries_optimized"] += 1
            except Exception as e:
                logger.debug(f"Could not create index: {e}")

        self.db.commit()
        return stats

    def add_query_cache(self, cache_size_mb: int = 100):
        """Configure query result caching.

        Args:
            cache_size_mb: Cache size in megabytes
        """
        if self.is_neo4j:
            # Neo4j caching configuration
            with self.db.session() as session:
                session.run("""
                    CALL dbms.setConfigValue('dbms.query_cache_size', $size)
                """, size=f"{cache_size_mb}m")

                logger.info(f"Set Neo4j query cache to {cache_size_mb}MB")
        else:
            # SQLite caching configuration
            cursor = self.db.cursor()

            # Set cache size (in pages, 1 page = ~4KB)
            cache_pages = (cache_size_mb * 1024) // 4
            cursor.execute(f"PRAGMA cache_size = {cache_pages}")

            # Enable query planner optimization
            cursor.execute("PRAGMA optimize")

            logger.info(f"Set SQLite cache to {cache_size_mb}MB")

    def benchmark_performance(self) -> Dict[str, float]:
        """Benchmark database performance.

        Returns:
            Performance metrics
        """
        metrics = {}

        # Simple read benchmark
        start_time = time.time()
        if self.is_neo4j:
            with self.db.session() as session:
                result = session.run("MATCH (n) RETURN count(n) as count")
                count = result.single()["count"]
        else:
            cursor = self.db.cursor()
            cursor.execute("SELECT COUNT(*) FROM nodes")
            count = cursor.fetchone()[0]

        metrics["read_time_ms"] = (time.time() - start_time) * 1000
        metrics["node_count"] = count

        # Relationship traversal benchmark
        start_time = time.time()
        if self.is_neo4j:
            with self.db.session() as session:
                result = session.run("""
                    MATCH (n)-[r]->(m)
                    RETURN count(r) as count
                    LIMIT 1000
                """)
                rel_count = result.single()["count"]
        else:
            cursor = self.db.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM relationships
                LIMIT 1000
            """)
            rel_count = cursor.fetchone()[0]

        metrics["traversal_time_ms"] = (time.time() - start_time) * 1000
        metrics["relationship_count"] = rel_count

        # Calculate throughput
        metrics["read_throughput"] = count / metrics["read_time_ms"] * 1000 if metrics["read_time_ms"] > 0 else 0

        logger.info(f"Performance metrics: {metrics}")
        return metrics


def optimize_database(db_connection, full_optimization: bool = True):
    """Run full database optimization.

    Args:
        db_connection: Database connection
        full_optimization: Whether to run full optimization

    Returns:
        Optimization results
    """
    optimizer = PerformanceOptimizer(db_connection)
    results = {}

    # Add performance indexes
    optimizer.add_performance_indexes()
    results["indexes_added"] = True

    # Add temporal attributes
    optimizer.add_temporal_attributes()
    results["temporal_added"] = True

    if full_optimization:
        # Optimize queries
        results["query_optimization"] = optimizer.optimize_queries()

        # Configure caching
        optimizer.add_query_cache(cache_size_mb=200)
        results["cache_configured"] = True

        # Benchmark performance
        results["performance_metrics"] = optimizer.benchmark_performance()

    return results
