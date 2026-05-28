"""Execution provenance tracking for agent workflows."""

import json
import uuid
import hashlib
from typing import Any, Dict, List, Optional, Tuple, Union
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
import pickle
import sqlite3
import threading
from collections import defaultdict

# Try to import networkx for lineage graphs
try:
    import networkx as nx
    NETWORKX_AVAILABLE = True
except ImportError:
    NETWORKX_AVAILABLE = False


class ExecutionStatus(str, Enum):
    """Status of an execution."""
    
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


class ArtifactType(str, Enum):
    """Types of artifacts produced during execution."""
    
    INPUT = "input"
    OUTPUT = "output"
    INTERMEDIATE = "intermediate"
    LOG = "log"
    METRIC = "metric"
    VISUALIZATION = "visualization"
    MODEL = "model"
    REPORT = "report"


@dataclass
class ExecutionMetadata:
    """Metadata for an execution."""
    
    execution_id: str
    parent_id: Optional[str] = None
    workflow_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    environment: Dict[str, str] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    custom_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionNode:
    """Node in execution graph representing a single operation."""
    
    node_id: str
    execution_id: str
    operation_name: str
    tool_name: str
    status: ExecutionStatus
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    input_parameters: Dict[str, Any] = field(default_factory=dict)
    output_data: Any = None
    error: Optional[str] = None
    retry_count: int = 0
    dependencies: List[str] = field(default_factory=list)
    artifacts: List['Artifact'] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)
    
    def calculate_duration(self):
        """Calculate execution duration."""
        if self.completed_at and self.started_at:
            delta = self.completed_at - self.started_at
            self.duration_seconds = delta.total_seconds()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'node_id': self.node_id,
            'execution_id': self.execution_id,
            'operation_name': self.operation_name,
            'tool_name': self.tool_name,
            'status': self.status.value,
            'started_at': self.started_at.isoformat(),
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'duration_seconds': self.duration_seconds,
            'input_parameters': self.input_parameters,
            'output_data': str(self.output_data) if self.output_data else None,
            'error': self.error,
            'retry_count': self.retry_count,
            'dependencies': self.dependencies,
            'artifacts': [a.to_dict() for a in self.artifacts],
            'metrics': self.metrics
        }


@dataclass
class Artifact:
    """Artifact produced during execution."""
    
    artifact_id: str
    name: str
    type: ArtifactType
    path: Optional[str] = None
    content: Optional[Any] = None
    size_bytes: int = 0
    checksum: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def calculate_checksum(self):
        """Calculate checksum for artifact content."""
        if self.content:
            if isinstance(self.content, bytes):
                data = self.content
            elif isinstance(self.content, str):
                data = self.content.encode()
            else:
                data = json.dumps(self.content, sort_keys=True).encode()
            
            self.checksum = hashlib.sha256(data).hexdigest()
            self.size_bytes = len(data)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'artifact_id': self.artifact_id,
            'name': self.name,
            'type': self.type.value,
            'path': self.path,
            'size_bytes': self.size_bytes,
            'checksum': self.checksum,
            'created_at': self.created_at.isoformat(),
            'metadata': self.metadata
        }


@dataclass
class ExecutionTrace:
    """Complete execution trace with lineage."""
    
    execution_id: str
    metadata: ExecutionMetadata
    nodes: List[ExecutionNode]
    artifacts: List[Artifact]
    status: ExecutionStatus
    started_at: datetime
    completed_at: Optional[datetime] = None
    total_duration_seconds: Optional[float] = None
    
    def calculate_total_duration(self):
        """Calculate total execution duration."""
        if self.completed_at and self.started_at:
            delta = self.completed_at - self.started_at
            self.total_duration_seconds = delta.total_seconds()
    
    def get_lineage_graph(self) -> Optional['nx.DiGraph']:
        """Get execution lineage as directed graph.
        
        Returns:
            NetworkX directed graph or None if not available
        """
        if not NETWORKX_AVAILABLE:
            return None
        
        G = nx.DiGraph()
        
        # Add nodes
        for node in self.nodes:
            G.add_node(
                node.node_id,
                operation=node.operation_name,
                tool=node.tool_name,
                status=node.status.value,
                duration=node.duration_seconds
            )
        
        # Add edges based on dependencies
        for node in self.nodes:
            for dep in node.dependencies:
                G.add_edge(dep, node.node_id)
        
        return G
    
    def get_critical_path(self) -> List[str]:
        """Get critical path through execution.
        
        Returns:
            List of node IDs in critical path
        """
        if not NETWORKX_AVAILABLE:
            return []
        
        G = self.get_lineage_graph()
        if not G:
            return []
        
        # Find longest path (critical path)
        try:
            return nx.dag_longest_path(G, weight='duration')
        except:
            return []
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'execution_id': self.execution_id,
            'metadata': asdict(self.metadata),
            'nodes': [n.to_dict() for n in self.nodes],
            'artifacts': [a.to_dict() for a in self.artifacts],
            'status': self.status.value,
            'started_at': self.started_at.isoformat(),
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'total_duration_seconds': self.total_duration_seconds
        }


class ProvenanceStore:
    """Storage backend for provenance data."""
    
    def __init__(self, db_path: str = ":memory:"):
        """Initialize provenance store.
        
        Args:
            db_path: Path to SQLite database (":memory:" for in-memory)
        """
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.lock = threading.Lock()
        self._initialize_schema()
    
    def _initialize_schema(self):
        """Initialize database schema."""
        with self.lock:
            cursor = self.conn.cursor()
            
            # Executions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS executions (
                    execution_id TEXT PRIMARY KEY,
                    parent_id TEXT,
                    workflow_id TEXT,
                    user_id TEXT,
                    session_id TEXT,
                    status TEXT,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    duration_seconds REAL,
                    metadata TEXT
                )
            """)
            
            # Nodes table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS nodes (
                    node_id TEXT PRIMARY KEY,
                    execution_id TEXT,
                    operation_name TEXT,
                    tool_name TEXT,
                    status TEXT,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    duration_seconds REAL,
                    input_parameters TEXT,
                    output_data TEXT,
                    error TEXT,
                    retry_count INTEGER,
                    metrics TEXT,
                    FOREIGN KEY (execution_id) REFERENCES executions(execution_id)
                )
            """)
            
            # Dependencies table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS dependencies (
                    node_id TEXT,
                    dependency_id TEXT,
                    PRIMARY KEY (node_id, dependency_id),
                    FOREIGN KEY (node_id) REFERENCES nodes(node_id)
                )
            """)
            
            # Artifacts table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    node_id TEXT,
                    name TEXT,
                    type TEXT,
                    path TEXT,
                    size_bytes INTEGER,
                    checksum TEXT,
                    created_at TIMESTAMP,
                    metadata TEXT,
                    FOREIGN KEY (node_id) REFERENCES nodes(node_id)
                )
            """)
            
            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_execution_status ON executions(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_execution_user ON executions(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_execution_workflow ON executions(workflow_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_node_execution ON nodes(execution_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_artifact_node ON artifacts(node_id)")
            
            self.conn.commit()
    
    def save_execution(self, trace: ExecutionTrace):
        """Save execution trace to store.
        
        Args:
            trace: Execution trace to save
        """
        with self.lock:
            cursor = self.conn.cursor()
            
            # Save execution
            cursor.execute("""
                INSERT OR REPLACE INTO executions 
                (execution_id, parent_id, workflow_id, user_id, session_id, 
                 status, started_at, completed_at, duration_seconds, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trace.execution_id,
                trace.metadata.parent_id,
                trace.metadata.workflow_id,
                trace.metadata.user_id,
                trace.metadata.session_id,
                trace.status.value,
                trace.started_at,
                trace.completed_at,
                trace.total_duration_seconds,
                json.dumps(asdict(trace.metadata))
            ))
            
            # Save nodes
            for node in trace.nodes:
                cursor.execute("""
                    INSERT OR REPLACE INTO nodes
                    (node_id, execution_id, operation_name, tool_name, status,
                     started_at, completed_at, duration_seconds, input_parameters,
                     output_data, error, retry_count, metrics)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    node.node_id,
                    node.execution_id,
                    node.operation_name,
                    node.tool_name,
                    node.status.value,
                    node.started_at,
                    node.completed_at,
                    node.duration_seconds,
                    json.dumps(node.input_parameters),
                    str(node.output_data) if node.output_data else None,
                    node.error,
                    node.retry_count,
                    json.dumps(node.metrics)
                ))
                
                # Save dependencies
                for dep in node.dependencies:
                    cursor.execute("""
                        INSERT OR REPLACE INTO dependencies (node_id, dependency_id)
                        VALUES (?, ?)
                    """, (node.node_id, dep))
                
                # Save artifacts
                for artifact in node.artifacts:
                    cursor.execute("""
                        INSERT OR REPLACE INTO artifacts
                        (artifact_id, node_id, name, type, path, size_bytes,
                         checksum, created_at, metadata)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        artifact.artifact_id,
                        node.node_id,
                        artifact.name,
                        artifact.type.value,
                        artifact.path,
                        artifact.size_bytes,
                        artifact.checksum,
                        artifact.created_at,
                        json.dumps(artifact.metadata)
                    ))
            
            self.conn.commit()
    
    def get_execution(self, execution_id: str) -> Optional[ExecutionTrace]:
        """Get execution trace by ID.
        
        Args:
            execution_id: Execution ID
            
        Returns:
            Execution trace or None
        """
        with self.lock:
            cursor = self.conn.cursor()
            
            # Get execution
            cursor.execute("""
                SELECT * FROM executions WHERE execution_id = ?
            """, (execution_id,))
            
            row = cursor.fetchone()
            if not row:
                return None
            
            # Parse metadata
            metadata_dict = json.loads(row[9])
            metadata = ExecutionMetadata(
                execution_id=row[0],
                parent_id=row[1],
                workflow_id=row[2],
                user_id=row[3],
                session_id=row[4],
                timestamp=datetime.fromisoformat(metadata_dict['timestamp']),
                environment=metadata_dict.get('environment', {}),
                tags=metadata_dict.get('tags', []),
                custom_metadata=metadata_dict.get('custom_metadata', {})
            )
            
            # Get nodes
            cursor.execute("""
                SELECT * FROM nodes WHERE execution_id = ?
            """, (execution_id,))
            
            nodes = []
            for node_row in cursor.fetchall():
                node = ExecutionNode(
                    node_id=node_row[0],
                    execution_id=node_row[1],
                    operation_name=node_row[2],
                    tool_name=node_row[3],
                    status=ExecutionStatus(node_row[4]),
                    started_at=datetime.fromisoformat(node_row[5]) if node_row[5] else None,
                    completed_at=datetime.fromisoformat(node_row[6]) if node_row[6] else None,
                    duration_seconds=node_row[7],
                    input_parameters=json.loads(node_row[8]) if node_row[8] else {},
                    output_data=node_row[9],
                    error=node_row[10],
                    retry_count=node_row[11],
                    metrics=json.loads(node_row[12]) if node_row[12] else {}
                )
                
                # Get dependencies
                cursor.execute("""
                    SELECT dependency_id FROM dependencies WHERE node_id = ?
                """, (node.node_id,))
                node.dependencies = [dep[0] for dep in cursor.fetchall()]
                
                # Get artifacts
                cursor.execute("""
                    SELECT * FROM artifacts WHERE node_id = ?
                """, (node.node_id,))
                
                for artifact_row in cursor.fetchall():
                    artifact = Artifact(
                        artifact_id=artifact_row[0],
                        name=artifact_row[2],
                        type=ArtifactType(artifact_row[3]),
                        path=artifact_row[4],
                        size_bytes=artifact_row[5],
                        checksum=artifact_row[6],
                        created_at=datetime.fromisoformat(artifact_row[7]) if artifact_row[7] else None,
                        metadata=json.loads(artifact_row[8]) if artifact_row[8] else {}
                    )
                    node.artifacts.append(artifact)
                
                nodes.append(node)
            
            # Create trace
            trace = ExecutionTrace(
                execution_id=execution_id,
                metadata=metadata,
                nodes=nodes,
                artifacts=[],  # Artifacts are attached to nodes
                status=ExecutionStatus(row[5]),
                started_at=datetime.fromisoformat(row[6]) if row[6] else None,
                completed_at=datetime.fromisoformat(row[7]) if row[7] else None,
                total_duration_seconds=row[8]
            )
            
            return trace
    
    def query_executions(self, 
                        user_id: Optional[str] = None,
                        workflow_id: Optional[str] = None,
                        status: Optional[ExecutionStatus] = None,
                        start_date: Optional[datetime] = None,
                        end_date: Optional[datetime] = None,
                        limit: int = 100) -> List[ExecutionTrace]:
        """Query executions with filters.
        
        Args:
            user_id: Filter by user
            workflow_id: Filter by workflow
            status: Filter by status
            start_date: Filter by start date
            end_date: Filter by end date
            limit: Maximum results
            
        Returns:
            List of matching execution traces
        """
        with self.lock:
            query = "SELECT execution_id FROM executions WHERE 1=1"
            params = []
            
            if user_id:
                query += " AND user_id = ?"
                params.append(user_id)
            
            if workflow_id:
                query += " AND workflow_id = ?"
                params.append(workflow_id)
            
            if status:
                query += " AND status = ?"
                params.append(status.value)
            
            if start_date:
                query += " AND started_at >= ?"
                params.append(start_date)
            
            if end_date:
                query += " AND started_at <= ?"
                params.append(end_date)
            
            query += " ORDER BY started_at DESC LIMIT ?"
            params.append(limit)
            
            cursor = self.conn.cursor()
            cursor.execute(query, params)
            
            traces = []
            for row in cursor.fetchall():
                trace = self.get_execution(row[0])
                if trace:
                    traces.append(trace)
            
            return traces
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get provenance statistics.
        
        Returns:
            Statistics dictionary
        """
        with self.lock:
            cursor = self.conn.cursor()
            
            stats = {}
            
            # Total executions
            cursor.execute("SELECT COUNT(*) FROM executions")
            stats['total_executions'] = cursor.fetchone()[0]
            
            # Executions by status
            cursor.execute("""
                SELECT status, COUNT(*) FROM executions 
                GROUP BY status
            """)
            stats['by_status'] = dict(cursor.fetchall())
            
            # Average duration
            cursor.execute("""
                SELECT AVG(duration_seconds) FROM executions 
                WHERE duration_seconds IS NOT NULL
            """)
            stats['avg_duration_seconds'] = cursor.fetchone()[0]
            
            # Total nodes
            cursor.execute("SELECT COUNT(*) FROM nodes")
            stats['total_nodes'] = cursor.fetchone()[0]
            
            # Total artifacts
            cursor.execute("SELECT COUNT(*) FROM artifacts")
            stats['total_artifacts'] = cursor.fetchone()[0]
            
            # Most used tools
            cursor.execute("""
                SELECT tool_name, COUNT(*) as count FROM nodes 
                GROUP BY tool_name 
                ORDER BY count DESC 
                LIMIT 10
            """)
            stats['top_tools'] = dict(cursor.fetchall())
            
            return stats


class ProvenanceTracker:
    """Main provenance tracking interface."""
    
    def __init__(self, store: Optional[ProvenanceStore] = None):
        """Initialize provenance tracker.
        
        Args:
            store: Provenance store (creates in-memory if None)
        """
        self.store = store or ProvenanceStore()
        self.active_executions: Dict[str, ExecutionTrace] = {}
        self.active_nodes: Dict[str, ExecutionNode] = {}
    
    def start_execution(self, 
                       workflow_id: Optional[str] = None,
                       user_id: Optional[str] = None,
                       session_id: Optional[str] = None,
                       parent_id: Optional[str] = None,
                       tags: List[str] = None) -> str:
        """Start tracking a new execution.
        
        Args:
            workflow_id: Workflow being executed
            user_id: User initiating execution
            session_id: Session ID
            parent_id: Parent execution ID
            tags: Tags for execution
            
        Returns:
            Execution ID
        """
        execution_id = str(uuid.uuid4())
        
        metadata = ExecutionMetadata(
            execution_id=execution_id,
            parent_id=parent_id,
            workflow_id=workflow_id,
            user_id=user_id,
            session_id=session_id,
            tags=tags or []
        )
        
        trace = ExecutionTrace(
            execution_id=execution_id,
            metadata=metadata,
            nodes=[],
            artifacts=[],
            status=ExecutionStatus.RUNNING,
            started_at=datetime.now()
        )
        
        self.active_executions[execution_id] = trace
        
        return execution_id
    
    def start_operation(self,
                       execution_id: str,
                       operation_name: str,
                       tool_name: str,
                       input_parameters: Dict[str, Any] = None,
                       dependencies: List[str] = None) -> str:
        """Start tracking an operation within an execution.
        
        Args:
            execution_id: Parent execution ID
            operation_name: Name of operation
            tool_name: Tool being used
            input_parameters: Input parameters
            dependencies: Dependencies on other nodes
            
        Returns:
            Node ID
        """
        if execution_id not in self.active_executions:
            raise ValueError(f"Execution {execution_id} not found")
        
        node_id = str(uuid.uuid4())
        
        node = ExecutionNode(
            node_id=node_id,
            execution_id=execution_id,
            operation_name=operation_name,
            tool_name=tool_name,
            status=ExecutionStatus.RUNNING,
            started_at=datetime.now(),
            input_parameters=input_parameters or {},
            dependencies=dependencies or []
        )
        
        self.active_nodes[node_id] = node
        self.active_executions[execution_id].nodes.append(node)
        
        return node_id
    
    def complete_operation(self,
                          node_id: str,
                          output_data: Any = None,
                          artifacts: List[Artifact] = None,
                          metrics: Dict[str, float] = None):
        """Complete an operation.
        
        Args:
            node_id: Node ID
            output_data: Output data
            artifacts: Artifacts produced
            metrics: Performance metrics
        """
        if node_id not in self.active_nodes:
            raise ValueError(f"Node {node_id} not found")
        
        node = self.active_nodes[node_id]
        node.status = ExecutionStatus.COMPLETED
        node.completed_at = datetime.now()
        node.calculate_duration()
        node.output_data = output_data
        
        if artifacts:
            node.artifacts.extend(artifacts)
        
        if metrics:
            node.metrics.update(metrics)
    
    def fail_operation(self, node_id: str, error: str):
        """Mark operation as failed.
        
        Args:
            node_id: Node ID
            error: Error message
        """
        if node_id not in self.active_nodes:
            raise ValueError(f"Node {node_id} not found")
        
        node = self.active_nodes[node_id]
        node.status = ExecutionStatus.FAILED
        node.completed_at = datetime.now()
        node.calculate_duration()
        node.error = error
    
    def complete_execution(self, execution_id: str):
        """Complete an execution.
        
        Args:
            execution_id: Execution ID
        """
        if execution_id not in self.active_executions:
            raise ValueError(f"Execution {execution_id} not found")
        
        trace = self.active_executions[execution_id]
        trace.status = ExecutionStatus.COMPLETED
        trace.completed_at = datetime.now()
        trace.calculate_total_duration()
        
        # Save to store
        self.store.save_execution(trace)
        
        # Clean up
        del self.active_executions[execution_id]
        
        # Clean up nodes
        for node in trace.nodes:
            if node.node_id in self.active_nodes:
                del self.active_nodes[node.node_id]
    
    def fail_execution(self, execution_id: str, error: str):
        """Mark execution as failed.
        
        Args:
            execution_id: Execution ID
            error: Error message
        """
        if execution_id not in self.active_executions:
            raise ValueError(f"Execution {execution_id} not found")
        
        trace = self.active_executions[execution_id]
        trace.status = ExecutionStatus.FAILED
        trace.completed_at = datetime.now()
        trace.calculate_total_duration()
        
        # Save to store
        self.store.save_execution(trace)
        
        # Clean up
        del self.active_executions[execution_id]
    
    def add_artifact(self,
                    node_id: str,
                    name: str,
                    artifact_type: ArtifactType,
                    content: Any = None,
                    path: str = None) -> str:
        """Add artifact to operation.
        
        Args:
            node_id: Node ID
            name: Artifact name
            artifact_type: Type of artifact
            content: Artifact content
            path: Path to artifact
            
        Returns:
            Artifact ID
        """
        if node_id not in self.active_nodes:
            raise ValueError(f"Node {node_id} not found")
        
        artifact_id = str(uuid.uuid4())
        
        artifact = Artifact(
            artifact_id=artifact_id,
            name=name,
            type=artifact_type,
            content=content,
            path=path
        )
        
        artifact.calculate_checksum()
        
        self.active_nodes[node_id].artifacts.append(artifact)
        
        return artifact_id
    
    def get_execution_trace(self, execution_id: str) -> Optional[ExecutionTrace]:
        """Get execution trace.
        
        Args:
            execution_id: Execution ID
            
        Returns:
            Execution trace or None
        """
        # Check active executions first
        if execution_id in self.active_executions:
            return self.active_executions[execution_id]
        
        # Check store
        return self.store.get_execution(execution_id)
    
    def query_executions(self, **kwargs) -> List[ExecutionTrace]:
        """Query execution history.
        
        Args:
            **kwargs: Query parameters
            
        Returns:
            List of matching executions
        """
        return self.store.query_executions(**kwargs)
    
    def get_lineage(self, artifact_id: str) -> Dict[str, Any]:
        """Get lineage for an artifact.
        
        Args:
            artifact_id: Artifact ID
            
        Returns:
            Lineage information
        """
        # Find artifact in store
        with self.store.lock:
            cursor = self.store.conn.cursor()
            
            cursor.execute("""
                SELECT node_id FROM artifacts WHERE artifact_id = ?
            """, (artifact_id,))
            
            row = cursor.fetchone()
            if not row:
                return {}
            
            node_id = row[0]
            
            # Get node information
            cursor.execute("""
                SELECT execution_id, operation_name, tool_name 
                FROM nodes WHERE node_id = ?
            """, (node_id,))
            
            node_row = cursor.fetchone()
            if not node_row:
                return {}
            
            execution_id = node_row[0]
            
            # Get full execution trace
            trace = self.get_execution_trace(execution_id)
            if not trace:
                return {}
            
            # Build lineage
            lineage = {
                'artifact_id': artifact_id,
                'node_id': node_id,
                'execution_id': execution_id,
                'operation': node_row[1],
                'tool': node_row[2],
                'upstream': [],
                'downstream': []
            }
            
            # Find upstream nodes (dependencies)
            node = next((n for n in trace.nodes if n.node_id == node_id), None)
            if node:
                for dep_id in node.dependencies:
                    dep_node = next((n for n in trace.nodes if n.node_id == dep_id), None)
                    if dep_node:
                        lineage['upstream'].append({
                            'node_id': dep_id,
                            'operation': dep_node.operation_name,
                            'artifacts': [a.artifact_id for a in dep_node.artifacts]
                        })
            
            # Find downstream nodes (nodes that depend on this one)
            for other_node in trace.nodes:
                if node_id in other_node.dependencies:
                    lineage['downstream'].append({
                        'node_id': other_node.node_id,
                        'operation': other_node.operation_name,
                        'artifacts': [a.artifact_id for a in other_node.artifacts]
                    })
            
            return lineage
    
    def export_trace(self, execution_id: str, format: str = 'json') -> str:
        """Export execution trace.
        
        Args:
            execution_id: Execution ID
            format: Export format ('json' or 'dot')
            
        Returns:
            Exported trace
        """
        trace = self.get_execution_trace(execution_id)
        if not trace:
            raise ValueError(f"Execution {execution_id} not found")
        
        if format == 'json':
            return json.dumps(trace.to_dict(), indent=2)
        
        elif format == 'dot':
            # Export as Graphviz DOT format
            lines = ['digraph execution {']
            lines.append('  rankdir=TB;')
            
            # Add nodes
            for node in trace.nodes:
                color = 'green' if node.status == ExecutionStatus.COMPLETED else 'red'
                label = f"{node.operation_name}\\n{node.tool_name}"
                lines.append(f'  "{node.node_id}" [label="{label}", color={color}];')
            
            # Add edges
            for node in trace.nodes:
                for dep in node.dependencies:
                    lines.append(f'  "{dep}" -> "{node.node_id}";')
            
            lines.append('}')
            return '\n'.join(lines)
        
        else:
            raise ValueError(f"Unknown format: {format}")


# Global tracker instance
_global_tracker: Optional[ProvenanceTracker] = None


def get_provenance_tracker() -> ProvenanceTracker:
    """Get global provenance tracker."""
    global _global_tracker
    
    if _global_tracker is None:
        _global_tracker = ProvenanceTracker()
    
    return _global_tracker


def set_provenance_tracker(tracker: ProvenanceTracker):
    """Set global provenance tracker."""
    global _global_tracker
    _global_tracker = tracker