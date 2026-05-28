"""Neo4j temporal extensions - completes KG-030 Temporal Graph.

This module provides temporal database capabilities for Neo4j, including
time-aware nodes, relationships, and queries for tracking graph evolution.
"""

import logging
import json
from typing import Dict, List, Any, Optional, Tuple, Union
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
import uuid

try:
    from neo4j import GraphDatabase, Transaction, Session
    from neo4j.exceptions import Neo4jError
    from neo4j.time import DateTime as Neo4jDateTime
    NEO4J_AVAILABLE = True
except ImportError:
    GraphDatabase = None
    Transaction = None
    Session = None
    Neo4jError = Exception
    Neo4jDateTime = None
    NEO4J_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class TimeRange:
    """Represents a time range."""
    
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    def __post_init__(self):
        """Validate time range."""
        if self.start_time and self.end_time:
            if self.start_time > self.end_time:
                raise ValueError("start_time must be before end_time")
    
    def contains(self, timestamp: datetime) -> bool:
        """Check if timestamp is within range."""
        if self.start_time and timestamp < self.start_time:
            return False
        if self.end_time and timestamp > self.end_time:
            return False
        return True
    
    def overlaps(self, other: "TimeRange") -> bool:
        """Check if this range overlaps with another."""
        if self.end_time and other.start_time and self.end_time < other.start_time:
            return False
        if self.start_time and other.end_time and self.start_time > other.end_time:
            return False
        return True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TimeRange":
        """Create from dictionary."""
        return cls(
            start_time=datetime.fromisoformat(data["start_time"]) if data["start_time"] else None,
            end_time=datetime.fromisoformat(data["end_time"]) if data["end_time"] else None
        )


@dataclass
class TemporalNode:
    """Represents a temporal node with time-aware properties."""
    
    node_id: str
    labels: List[str]
    properties: Dict[str, Any] = field(default_factory=dict)
    
    # Temporal metadata
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: Optional[datetime] = None
    valid_time: Optional[TimeRange] = None  # When this version is valid
    transaction_time: Optional[TimeRange] = None  # When this was recorded
    
    # Versioning
    version: int = 1
    previous_version: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "node_id": self.node_id,
            "labels": self.labels,
            "properties": self.properties,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "valid_time": self.valid_time.to_dict() if self.valid_time else None,
            "transaction_time": self.transaction_time.to_dict() if self.transaction_time else None,
            "version": self.version,
            "previous_version": self.previous_version
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TemporalNode":
        """Create from dictionary."""
        return cls(
            node_id=data["node_id"],
            labels=data["labels"],
            properties=data.get("properties", {}),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data["updated_at"] else None,
            valid_time=TimeRange.from_dict(data["valid_time"]) if data["valid_time"] else None,
            transaction_time=TimeRange.from_dict(data["transaction_time"]) if data["transaction_time"] else None,
            version=data.get("version", 1),
            previous_version=data.get("previous_version")
        )


@dataclass
class TemporalRelationship:
    """Represents a temporal relationship with time-aware properties."""
    
    relationship_id: str
    start_node_id: str
    end_node_id: str
    relationship_type: str
    properties: Dict[str, Any] = field(default_factory=dict)
    
    # Temporal metadata
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: Optional[datetime] = None
    valid_time: Optional[TimeRange] = None
    transaction_time: Optional[TimeRange] = None
    
    # Versioning
    version: int = 1
    previous_version: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "relationship_id": self.relationship_id,
            "start_node_id": self.start_node_id,
            "end_node_id": self.end_node_id,
            "relationship_type": self.relationship_type,
            "properties": self.properties,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "valid_time": self.valid_time.to_dict() if self.valid_time else None,
            "transaction_time": self.transaction_time.to_dict() if self.transaction_time else None,
            "version": self.version,
            "previous_version": self.previous_version
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TemporalRelationship":
        """Create from dictionary."""
        return cls(
            relationship_id=data["relationship_id"],
            start_node_id=data["start_node_id"],
            end_node_id=data["end_node_id"],
            relationship_type=data["relationship_type"],
            properties=data.get("properties", {}),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data["updated_at"] else None,
            valid_time=TimeRange.from_dict(data["valid_time"]) if data["valid_time"] else None,
            transaction_time=TimeRange.from_dict(data["transaction_time"]) if data["transaction_time"] else None,
            version=data.get("version", 1),
            previous_version=data.get("previous_version")
        )


@dataclass 
class TemporalQuery:
    """Represents a temporal query with time constraints."""
    
    query_id: str
    cypher: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    
    # Time constraints
    as_of_time: Optional[datetime] = None  # Query as of specific time
    time_range: Optional[TimeRange] = None  # Query within time range
    include_history: bool = False  # Include historical versions
    
    # Query metadata
    created_at: datetime = field(default_factory=datetime.now)
    executed_at: Optional[datetime] = None
    execution_time_ms: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "query_id": self.query_id,
            "cypher": self.cypher,
            "parameters": self.parameters,
            "as_of_time": self.as_of_time.isoformat() if self.as_of_time else None,
            "time_range": self.time_range.to_dict() if self.time_range else None,
            "include_history": self.include_history,
            "created_at": self.created_at.isoformat(),
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
            "execution_time_ms": self.execution_time_ms
        }


class TemporalError(Exception):
    """Temporal database related errors."""
    pass


class TemporalNeo4jDB:
    """Temporal-aware Neo4j database wrapper."""
    
    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        database: Optional[str] = None,
        enable_temporal_constraints: bool = True
    ):
        """Initialize temporal Neo4j database.
        
        Args:
            uri: Neo4j URI
            user: Username
            password: Password
            database: Database name
            enable_temporal_constraints: Whether to enable temporal constraints
        """
        if not NEO4J_AVAILABLE:
            raise ImportError("neo4j driver is required for temporal database")
            
        self.uri = uri
        self.user = user
        self.password = password
        self.database = database
        
        # Connect to Neo4j
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        
        # Initialize temporal schema if needed
        if enable_temporal_constraints:
            self._setup_temporal_schema()
        
        logger.info("Initialized temporal Neo4j database")
    
    def close(self):
        """Close database connection."""
        if self.driver:
            self.driver.close()
    
    def _setup_temporal_schema(self):
        """Setup temporal schema constraints and indexes."""
        with self.driver.session(database=self.database) as session:
            # Create temporal constraints
            constraints = [
                # Ensure temporal nodes have required temporal properties
                "CREATE CONSTRAINT temporal_node_created_at IF NOT EXISTS FOR (n:TemporalNode) REQUIRE n.created_at IS NOT NULL",
                "CREATE CONSTRAINT temporal_node_version IF NOT EXISTS FOR (n:TemporalNode) REQUIRE n.version IS NOT NULL",
                
                # Ensure temporal relationships have required properties
                "CREATE CONSTRAINT temporal_rel_created_at IF NOT EXISTS FOR ()-[r:TEMPORAL_REL]-() REQUIRE r.created_at IS NOT NULL",
                "CREATE CONSTRAINT temporal_rel_version IF NOT EXISTS FOR ()-[r:TEMPORAL_REL]-() REQUIRE r.version IS NOT NULL",
            ]
            
            indexes = [
                # Temporal indexes for efficient time-based queries
                "CREATE INDEX temporal_node_created_at IF NOT EXISTS FOR (n:TemporalNode) ON (n.created_at)",
                "CREATE INDEX temporal_node_valid_time_start IF NOT EXISTS FOR (n:TemporalNode) ON (n.valid_time_start)",
                "CREATE INDEX temporal_node_valid_time_end IF NOT EXISTS FOR (n:TemporalNode) ON (n.valid_time_end)",
                "CREATE INDEX temporal_node_version IF NOT EXISTS FOR (n:TemporalNode) ON (n.version)",
                
                "CREATE INDEX temporal_rel_created_at IF NOT EXISTS FOR ()-[r:TEMPORAL_REL]-() ON (r.created_at)",
                "CREATE INDEX temporal_rel_valid_time_start IF NOT EXISTS FOR ()-[r:TEMPORAL_REL]-() ON (r.valid_time_start)",
                "CREATE INDEX temporal_rel_valid_time_end IF NOT EXISTS FOR ()-[r:TEMPORAL_REL]-() ON (r.valid_time_end)",
                "CREATE INDEX temporal_rel_version IF NOT EXISTS FOR ()-[r:TEMPORAL_REL]-() ON (r.version)",
            ]
            
            for constraint in constraints:
                try:
                    session.run(constraint)
                except Neo4jError as e:
                    logger.debug(f"Constraint already exists or error: {e}")
            
            for index in indexes:
                try:
                    session.run(index)
                except Neo4jError as e:
                    logger.debug(f"Index already exists or error: {e}")
        
        logger.info("Set up temporal schema")
    
    def create_temporal_node(
        self,
        node: TemporalNode,
        transaction_time: Optional[datetime] = None
    ) -> str:
        """Create a temporal node.
        
        Args:
            node: Temporal node to create
            transaction_time: Transaction timestamp
            
        Returns:
            Node ID
        """
        transaction_time = transaction_time or datetime.now()
        
        # Update temporal metadata
        if node.transaction_time is None:
            node.transaction_time = TimeRange(start_time=transaction_time)
        
        # Prepare node properties for Neo4j
        node_props = {
            "id": node.node_id,
            "created_at": node.created_at,
            "updated_at": node.updated_at,
            "version": node.version,
            "previous_version": node.previous_version,
            **node.properties
        }
        
        # Add valid time properties if present
        if node.valid_time:
            if node.valid_time.start_time:
                node_props["valid_time_start"] = node.valid_time.start_time
            if node.valid_time.end_time:
                node_props["valid_time_end"] = node.valid_time.end_time
        
        # Add transaction time properties
        if node.transaction_time:
            if node.transaction_time.start_time:
                node_props["transaction_time_start"] = node.transaction_time.start_time
            if node.transaction_time.end_time:
                node_props["transaction_time_end"] = node.transaction_time.end_time
        
        # Create labels
        labels = ["TemporalNode"] + node.labels
        label_str = ":".join(f"`{label}`" for label in labels)
        
        with self.driver.session(database=self.database) as session:
            query = f"""
            CREATE (n:{label_str} $props)
            RETURN n.id as node_id
            """
            
            result = session.run(query, {"props": node_props})
            record = result.single()
            
            if record:
                logger.info(f"Created temporal node {record['node_id']}")
                return record["node_id"]
            else:
                raise TemporalError("Failed to create temporal node")
    
    def update_temporal_node(
        self,
        node_id: str,
        properties: Dict[str, Any],
        valid_time: Optional[TimeRange] = None,
        create_new_version: bool = True
    ) -> TemporalNode:
        """Update a temporal node.
        
        Args:
            node_id: Node ID to update
            properties: Properties to update
            valid_time: Valid time for the update
            create_new_version: Whether to create a new version
            
        Returns:
            Updated temporal node
        """
        current_time = datetime.now()
        
        with self.driver.session(database=self.database) as session:
            if create_new_version:
                # Get current version
                current_query = """
                MATCH (n:TemporalNode {id: $node_id})
                WHERE n.transaction_time_end IS NULL
                RETURN n
                """
                
                result = session.run(current_query, {"node_id": node_id})
                current_record = result.single()
                
                if not current_record:
                    raise TemporalError(f"Node {node_id} not found")
                
                current_node = current_record["n"]
                current_version = current_node["version"]
                
                # Close current version
                close_query = """
                MATCH (n:TemporalNode {id: $node_id, version: $version})
                SET n.transaction_time_end = $current_time
                """
                
                session.run(close_query, {
                    "node_id": node_id,
                    "version": current_version,
                    "current_time": current_time
                })
                
                # Create new version
                new_props = dict(current_node)
                new_props.update(properties)
                new_props["version"] = current_version + 1
                new_props["previous_version"] = str(current_version)
                new_props["updated_at"] = current_time
                new_props["transaction_time_start"] = current_time
                
                # Add valid time if provided
                if valid_time:
                    if valid_time.start_time:
                        new_props["valid_time_start"] = valid_time.start_time
                    if valid_time.end_time:
                        new_props["valid_time_end"] = valid_time.end_time
                
                # Remove internal Neo4j properties
                for key in ["elementId", "labels"]:
                    new_props.pop(key, None)
                
                labels = list(current_node.labels)
                label_str = ":".join(f"`{label}`" for label in labels)
                
                create_query = f"""
                CREATE (n:{label_str} $props)
                RETURN n
                """
                
                result = session.run(create_query, {"props": new_props})
                new_record = result.single()
                
                if new_record:
                    new_node = new_record["n"]
                    logger.info(f"Created new version {new_props['version']} of node {node_id}")
                    
                    # Convert to TemporalNode
                    return self._neo4j_node_to_temporal(new_node)
                else:
                    raise TemporalError("Failed to create new node version")
            
            else:
                # Update in place
                update_query = """
                MATCH (n:TemporalNode {id: $node_id})
                WHERE n.transaction_time_end IS NULL
                SET n += $properties, n.updated_at = $current_time
                RETURN n
                """
                
                result = session.run(update_query, {
                    "node_id": node_id,
                    "properties": properties,
                    "current_time": current_time
                })
                
                record = result.single()
                if record:
                    logger.info(f"Updated node {node_id}")
                    return self._neo4j_node_to_temporal(record["n"])
                else:
                    raise TemporalError(f"Failed to update node {node_id}")
    
    def create_temporal_relationship(
        self,
        relationship: TemporalRelationship,
        transaction_time: Optional[datetime] = None
    ) -> str:
        """Create a temporal relationship.
        
        Args:
            relationship: Temporal relationship to create
            transaction_time: Transaction timestamp
            
        Returns:
            Relationship ID
        """
        transaction_time = transaction_time or datetime.now()
        
        # Update temporal metadata
        if relationship.transaction_time is None:
            relationship.transaction_time = TimeRange(start_time=transaction_time)
        
        # Prepare relationship properties
        rel_props = {
            "id": relationship.relationship_id,
            "created_at": relationship.created_at,
            "updated_at": relationship.updated_at,
            "version": relationship.version,
            "previous_version": relationship.previous_version,
            **relationship.properties
        }
        
        # Add temporal properties
        if relationship.valid_time:
            if relationship.valid_time.start_time:
                rel_props["valid_time_start"] = relationship.valid_time.start_time
            if relationship.valid_time.end_time:
                rel_props["valid_time_end"] = relationship.valid_time.end_time
        
        if relationship.transaction_time:
            if relationship.transaction_time.start_time:
                rel_props["transaction_time_start"] = relationship.transaction_time.start_time
            if relationship.transaction_time.end_time:
                rel_props["transaction_time_end"] = relationship.transaction_time.end_time
        
        with self.driver.session(database=self.database) as session:
            query = """
            MATCH (start:TemporalNode {id: $start_id})
            MATCH (end:TemporalNode {id: $end_id})
            WHERE start.transaction_time_end IS NULL AND end.transaction_time_end IS NULL
            CREATE (start)-[r:TEMPORAL_REL {type: $rel_type}]->(end)
            SET r += $props
            RETURN r.id as relationship_id
            """
            
            result = session.run(query, {
                "start_id": relationship.start_node_id,
                "end_id": relationship.end_node_id,
                "rel_type": relationship.relationship_type,
                "props": rel_props
            })
            
            record = result.single()
            if record:
                logger.info(f"Created temporal relationship {record['relationship_id']}")
                return record["relationship_id"]
            else:
                raise TemporalError("Failed to create temporal relationship")
    
    def query_temporal_nodes(
        self,
        labels: Optional[List[str]] = None,
        properties: Optional[Dict[str, Any]] = None,
        as_of_time: Optional[datetime] = None,
        time_range: Optional[TimeRange] = None,
        include_history: bool = False
    ) -> List[TemporalNode]:
        """Query temporal nodes with time constraints.
        
        Args:
            labels: Node labels to filter by
            properties: Properties to filter by
            as_of_time: Query as of specific time
            time_range: Query within time range
            include_history: Include historical versions
            
        Returns:
            List of temporal nodes
        """
        # Build query
        label_filter = ""
        if labels:
            label_filter = ":" + ":".join(f"`{label}`" for label in labels)
        
        where_conditions = ["n:TemporalNode"]
        params = {}
        
        # Add property filters
        if properties:
            for key, value in properties.items():
                param_name = f"prop_{key}"
                where_conditions.append(f"n.{key} = ${param_name}")
                params[param_name] = value
        
        # Add temporal filters
        if as_of_time:
            where_conditions.extend([
                "n.transaction_time_start <= $as_of_time",
                "(n.transaction_time_end IS NULL OR n.transaction_time_end > $as_of_time)"
            ])
            params["as_of_time"] = as_of_time
            
            if not include_history:
                # Only get latest version as of the specified time
                where_conditions.append("""
                NOT EXISTS {
                    MATCH (newer:TemporalNode {id: n.id})
                    WHERE newer.version > n.version
                    AND newer.transaction_time_start <= $as_of_time
                }
                """)
        
        elif time_range:
            if time_range.start_time:
                where_conditions.append("n.transaction_time_start >= $time_start")
                params["time_start"] = time_range.start_time
            if time_range.end_time:
                where_conditions.append("n.transaction_time_start <= $time_end")
                params["time_end"] = time_range.end_time
        
        elif not include_history:
            # Default: only current versions
            where_conditions.append("n.transaction_time_end IS NULL")
        
        where_clause = " AND ".join(where_conditions)
        
        query = f"""
        MATCH (n{label_filter})
        WHERE {where_clause}
        RETURN n
        ORDER BY n.id, n.version DESC
        """
        
        with self.driver.session(database=self.database) as session:
            result = session.run(query, params)
            
            nodes = []
            seen_ids = set()
            
            for record in result:
                temporal_node = self._neo4j_node_to_temporal(record["n"])
                
                # If not including history, only take first (latest) version of each node
                if not include_history:
                    if temporal_node.node_id not in seen_ids:
                        nodes.append(temporal_node)
                        seen_ids.add(temporal_node.node_id)
                else:
                    nodes.append(temporal_node)
            
            logger.info(f"Found {len(nodes)} temporal nodes")
            return nodes
    
    def query_temporal_relationships(
        self,
        relationship_type: Optional[str] = None,
        start_node_id: Optional[str] = None,
        end_node_id: Optional[str] = None,
        as_of_time: Optional[datetime] = None,
        time_range: Optional[TimeRange] = None,
        include_history: bool = False
    ) -> List[TemporalRelationship]:
        """Query temporal relationships with time constraints.
        
        Args:
            relationship_type: Relationship type to filter by
            start_node_id: Start node ID
            end_node_id: End node ID
            as_of_time: Query as of specific time
            time_range: Query within time range
            include_history: Include historical versions
            
        Returns:
            List of temporal relationships
        """
        where_conditions = []
        params = {}
        
        # Add node filters
        if start_node_id:
            where_conditions.append("start.id = $start_id")
            params["start_id"] = start_node_id
        
        if end_node_id:
            where_conditions.append("end.id = $end_id")
            params["end_id"] = end_node_id
        
        # Add relationship type filter
        if relationship_type:
            where_conditions.append("r.type = $rel_type")
            params["rel_type"] = relationship_type
        
        # Add temporal filters
        if as_of_time:
            where_conditions.extend([
                "r.transaction_time_start <= $as_of_time",
                "(r.transaction_time_end IS NULL OR r.transaction_time_end > $as_of_time)"
            ])
            params["as_of_time"] = as_of_time
            
        elif time_range:
            if time_range.start_time:
                where_conditions.append("r.transaction_time_start >= $time_start")
                params["time_start"] = time_range.start_time
            if time_range.end_time:
                where_conditions.append("r.transaction_time_start <= $time_end")
                params["time_end"] = time_range.end_time
                
        elif not include_history:
            where_conditions.append("r.transaction_time_end IS NULL")
        
        where_clause = " AND ".join(where_conditions) if where_conditions else "TRUE"
        
        query = f"""
        MATCH (start:TemporalNode)-[r:TEMPORAL_REL]->(end:TemporalNode)
        WHERE {where_clause}
        RETURN r, start.id as start_id, end.id as end_id
        ORDER BY r.id, r.version DESC
        """
        
        with self.driver.session(database=self.database) as session:
            result = session.run(query, params)
            
            relationships = []
            seen_ids = set()
            
            for record in result:
                temporal_rel = self._neo4j_rel_to_temporal(
                    record["r"],
                    record["start_id"],
                    record["end_id"]
                )
                
                # If not including history, only take first (latest) version
                if not include_history:
                    if temporal_rel.relationship_id not in seen_ids:
                        relationships.append(temporal_rel)
                        seen_ids.add(temporal_rel.relationship_id)
                else:
                    relationships.append(temporal_rel)
            
            logger.info(f"Found {len(relationships)} temporal relationships")
            return relationships
    
    def execute_temporal_query(self, temporal_query: TemporalQuery) -> List[Dict[str, Any]]:
        """Execute a temporal query.
        
        Args:
            temporal_query: Temporal query to execute
            
        Returns:
            Query results
        """
        start_time = datetime.now()
        
        # Enhance query with temporal constraints
        enhanced_cypher = self._enhance_cypher_with_temporal_constraints(
            temporal_query.cypher,
            temporal_query.as_of_time,
            temporal_query.time_range,
            temporal_query.include_history
        )
        
        # Merge parameters
        params = temporal_query.parameters.copy()
        if temporal_query.as_of_time:
            params["_temporal_as_of_time"] = temporal_query.as_of_time
        if temporal_query.time_range:
            if temporal_query.time_range.start_time:
                params["_temporal_time_start"] = temporal_query.time_range.start_time
            if temporal_query.time_range.end_time:
                params["_temporal_time_end"] = temporal_query.time_range.end_time
        
        with self.driver.session(database=self.database) as session:
            result = session.run(enhanced_cypher, params)
            
            records = []
            for record in result:
                records.append(dict(record))
            
            # Update query metadata
            temporal_query.executed_at = datetime.now()
            temporal_query.execution_time_ms = (temporal_query.executed_at - start_time).total_seconds() * 1000
            
            logger.info(f"Executed temporal query {temporal_query.query_id} in {temporal_query.execution_time_ms:.2f}ms")
            return records
    
    def _enhance_cypher_with_temporal_constraints(
        self,
        cypher: str,
        as_of_time: Optional[datetime],
        time_range: Optional[TimeRange],
        include_history: bool
    ) -> str:
        """Enhance Cypher query with temporal constraints."""
        # This is a simplified implementation
        # In practice, you'd want a proper Cypher parser
        
        enhanced = cypher
        
        # Add temporal constraints for nodes
        if "MATCH" in cypher and ":TemporalNode" in cypher:
            if as_of_time and not include_history:
                temporal_constraint = """
                AND n.transaction_time_start <= $_temporal_as_of_time
                AND (n.transaction_time_end IS NULL OR n.transaction_time_end > $_temporal_as_of_time)
                """
                enhanced = enhanced.replace("WHERE", f"WHERE {temporal_constraint.strip()} AND", 1)
            
            elif time_range:
                constraints = []
                if time_range.start_time:
                    constraints.append("n.transaction_time_start >= $_temporal_time_start")
                if time_range.end_time:
                    constraints.append("n.transaction_time_start <= $_temporal_time_end")
                
                if constraints:
                    temporal_constraint = " AND ".join(constraints)
                    enhanced = enhanced.replace("WHERE", f"WHERE {temporal_constraint} AND", 1)
            
            elif not include_history:
                enhanced = enhanced.replace("WHERE", "WHERE n.transaction_time_end IS NULL AND", 1)
        
        return enhanced
    
    def _neo4j_node_to_temporal(self, neo4j_node) -> TemporalNode:
        """Convert Neo4j node to TemporalNode."""
        props = dict(neo4j_node)
        
        # Extract temporal properties
        created_at = props.pop("created_at", datetime.now())
        updated_at = props.pop("updated_at", None)
        version = props.pop("version", 1)
        previous_version = props.pop("previous_version", None)
        
        # Extract valid time
        valid_time = None
        valid_start = props.pop("valid_time_start", None)
        valid_end = props.pop("valid_time_end", None)
        if valid_start or valid_end:
            valid_time = TimeRange(start_time=valid_start, end_time=valid_end)
        
        # Extract transaction time
        transaction_time = None
        trans_start = props.pop("transaction_time_start", None)
        trans_end = props.pop("transaction_time_end", None)
        if trans_start or trans_end:
            transaction_time = TimeRange(start_time=trans_start, end_time=trans_end)
        
        # Remove internal properties
        node_id = props.pop("id", str(uuid.uuid4()))
        for key in ["elementId"]:
            props.pop(key, None)
        
        # Get labels (excluding TemporalNode)
        labels = [label for label in neo4j_node.labels if label != "TemporalNode"]
        
        return TemporalNode(
            node_id=node_id,
            labels=labels,
            properties=props,
            created_at=created_at,
            updated_at=updated_at,
            valid_time=valid_time,
            transaction_time=transaction_time,
            version=version,
            previous_version=previous_version
        )
    
    def _neo4j_rel_to_temporal(self, neo4j_rel, start_id: str, end_id: str) -> TemporalRelationship:
        """Convert Neo4j relationship to TemporalRelationship."""
        props = dict(neo4j_rel)
        
        # Extract temporal properties
        created_at = props.pop("created_at", datetime.now())
        updated_at = props.pop("updated_at", None)
        version = props.pop("version", 1)
        previous_version = props.pop("previous_version", None)
        relationship_type = props.pop("type", "UNKNOWN")
        
        # Extract valid time
        valid_time = None
        valid_start = props.pop("valid_time_start", None)
        valid_end = props.pop("valid_time_end", None)
        if valid_start or valid_end:
            valid_time = TimeRange(start_time=valid_start, end_time=valid_end)
        
        # Extract transaction time
        transaction_time = None
        trans_start = props.pop("transaction_time_start", None)
        trans_end = props.pop("transaction_time_end", None)
        if trans_start or trans_end:
            transaction_time = TimeRange(start_time=trans_start, end_time=trans_end)
        
        # Remove internal properties
        rel_id = props.pop("id", str(uuid.uuid4()))
        for key in ["elementId"]:
            props.pop(key, None)
        
        return TemporalRelationship(
            relationship_id=rel_id,
            start_node_id=start_id,
            end_node_id=end_id,
            relationship_type=relationship_type,
            properties=props,
            created_at=created_at,
            updated_at=updated_at,
            valid_time=valid_time,
            transaction_time=transaction_time,
            version=version,
            previous_version=previous_version
        )
    
    def get_node_history(self, node_id: str) -> List[TemporalNode]:
        """Get complete history of a node.
        
        Args:
            node_id: Node ID
            
        Returns:
            List of all versions of the node
        """
        return self.query_temporal_nodes(
            properties={"id": node_id},
            include_history=True
        )
    
    def get_relationship_history(self, relationship_id: str) -> List[TemporalRelationship]:
        """Get complete history of a relationship.
        
        Args:
            relationship_id: Relationship ID
            
        Returns:
            List of all versions of the relationship
        """
        with self.driver.session(database=self.database) as session:
            query = """
            MATCH (start:TemporalNode)-[r:TEMPORAL_REL]->(end:TemporalNode)
            WHERE r.id = $rel_id
            RETURN r, start.id as start_id, end.id as end_id
            ORDER BY r.version DESC
            """
            
            result = session.run(query, {"rel_id": relationship_id})
            
            relationships = []
            for record in result:
                temporal_rel = self._neo4j_rel_to_temporal(
                    record["r"],
                    record["start_id"],
                    record["end_id"]
                )
                relationships.append(temporal_rel)
            
            return relationships
    
    def get_temporal_stats(self) -> Dict[str, Any]:
        """Get temporal database statistics."""
        with self.driver.session(database=self.database) as session:
            # Count temporal nodes and relationships
            counts_query = """
            MATCH (n:TemporalNode)
            OPTIONAL MATCH ()-[r:TEMPORAL_REL]->()
            RETURN 
                count(n) as temporal_nodes,
                count(r) as temporal_relationships,
                count(DISTINCT n.id) as unique_nodes,
                count(DISTINCT r.id) as unique_relationships
            """
            
            result = session.run(counts_query)
            counts = result.single()
            
            # Get version distribution
            version_query = """
            MATCH (n:TemporalNode)
            RETURN n.version as version, count(*) as count
            ORDER BY n.version
            """
            
            version_result = session.run(version_query)
            version_distribution = {record["version"]: record["count"] for record in version_result}
            
            # Get temporal range
            range_query = """
            MATCH (n:TemporalNode)
            RETURN 
                min(n.created_at) as earliest_created,
                max(n.created_at) as latest_created,
                min(n.transaction_time_start) as earliest_transaction,
                max(n.transaction_time_start) as latest_transaction
            """
            
            range_result = session.run(range_query)
            temporal_range = range_result.single()
            
            return {
                "temporal_nodes": counts["temporal_nodes"],
                "temporal_relationships": counts["temporal_relationships"],
                "unique_nodes": counts["unique_nodes"],
                "unique_relationships": counts["unique_relationships"],
                "version_distribution": version_distribution,
                "earliest_created": temporal_range["earliest_created"],
                "latest_created": temporal_range["latest_created"],
                "earliest_transaction": temporal_range["earliest_transaction"],
                "latest_transaction": temporal_range["latest_transaction"]
            }