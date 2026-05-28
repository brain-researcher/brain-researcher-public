"""
Data Lineage Tracking System

Tracks data flow through ingestion, transformation, and analysis pipelines.
Provides full traceability and impact analysis.
"""

import uuid
import json
from datetime import datetime
from typing import Dict, List, Optional, Set, Any, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
import hashlib
from pathlib import Path
import networkx as nx
from collections import defaultdict
import pickle


class LineageEventType(Enum):
    """Types of lineage events"""
    INGESTION = "ingestion"
    TRANSFORMATION = "transformation"
    VALIDATION = "validation"
    ENRICHMENT = "enrichment"
    AGGREGATION = "aggregation"
    EXPORT = "export"
    DELETION = "deletion"


class DataSourceType(Enum):
    """Types of data sources"""
    FILE = "file"
    DATABASE = "database"
    API = "api"
    STREAM = "stream"
    MANUAL = "manual"


@dataclass
class DataEntity:
    """Represents a data entity in the lineage graph"""
    entity_id: str
    name: str
    entity_type: str
    source_type: DataSourceType
    location: str
    schema_version: Optional[str] = None
    checksum: Optional[str] = None
    size_bytes: Optional[int] = None
    record_count: Optional[int] = None
    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def calculate_checksum(self, data: bytes) -> str:
        """Calculate checksum for data"""
        self.checksum = hashlib.sha256(data).hexdigest()
        return self.checksum


@dataclass
class LineageEvent:
    """Represents a lineage event (transformation, etc.)"""
    event_id: str
    event_type: LineageEventType
    input_entities: List[str]  # Entity IDs
    output_entities: List[str]  # Entity IDs
    operation: str
    operator: str  # User or system that performed operation
    timestamp: datetime
    duration_ms: Optional[int] = None
    success: bool = True
    error_message: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LineageRelationship:
    """Represents a relationship between entities"""
    source_id: str
    target_id: str
    relationship_type: str
    event_id: str
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)


class DataLineageTracker:
    """Tracks data lineage across the system"""
    
    def __init__(self, storage_path: Optional[Path] = None):
        """
        Initialize lineage tracker
        
        Args:
            storage_path: Path to persist lineage data
        """
        self.storage_path = storage_path or Path("data/lineage")
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        # In-memory storage
        self.entities: Dict[str, DataEntity] = {}
        self.events: Dict[str, LineageEvent] = {}
        self.relationships: List[LineageRelationship] = []
        
        # Lineage graph
        self.graph = nx.DiGraph()
        
        # Indexes for fast lookup
        self.entity_by_name: Dict[str, Set[str]] = defaultdict(set)
        self.events_by_entity: Dict[str, Set[str]] = defaultdict(set)
        self.entity_children: Dict[str, Set[str]] = defaultdict(set)
        self.entity_parents: Dict[str, Set[str]] = defaultdict(set)
        
        # Load existing lineage
        self._load_lineage()
    
    def track_ingestion(
        self,
        source_location: str,
        source_type: DataSourceType,
        entity_name: str,
        entity_type: str,
        operator: str,
        schema_version: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, str]:
        """
        Track data ingestion
        
        Returns:
            Tuple of (entity_id, event_id)
        """
        # Create entity
        entity_id = str(uuid.uuid4())
        entity = DataEntity(
            entity_id=entity_id,
            name=entity_name,
            entity_type=entity_type,
            source_type=source_type,
            location=source_location,
            schema_version=schema_version,
            metadata=metadata or {}
        )
        
        # Create ingestion event
        event_id = str(uuid.uuid4())
        event = LineageEvent(
            event_id=event_id,
            event_type=LineageEventType.INGESTION,
            input_entities=[],
            output_entities=[entity_id],
            operation=f"Ingest from {source_type.value}",
            operator=operator,
            timestamp=datetime.now(),
            parameters={"source": source_location}
        )
        
        # Store
        self._add_entity(entity)
        self._add_event(event)
        
        return entity_id, event_id
    
    def track_transformation(
        self,
        input_entity_ids: List[str],
        output_entity_name: str,
        output_entity_type: str,
        operation: str,
        operator: str,
        parameters: Optional[Dict[str, Any]] = None,
        metrics: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, str]:
        """
        Track data transformation
        
        Returns:
            Tuple of (output_entity_id, event_id)
        """
        # Create output entity
        output_entity_id = str(uuid.uuid4())
        output_entity = DataEntity(
            entity_id=output_entity_id,
            name=output_entity_name,
            entity_type=output_entity_type,
            source_type=DataSourceType.MANUAL,
            location="derived",
            metadata={"derived_from": input_entity_ids}
        )
        
        # Create transformation event
        event_id = str(uuid.uuid4())
        event = LineageEvent(
            event_id=event_id,
            event_type=LineageEventType.TRANSFORMATION,
            input_entities=input_entity_ids,
            output_entities=[output_entity_id],
            operation=operation,
            operator=operator,
            timestamp=datetime.now(),
            parameters=parameters or {},
            metrics=metrics or {}
        )
        
        # Create relationships
        for input_id in input_entity_ids:
            relationship = LineageRelationship(
                source_id=input_id,
                target_id=output_entity_id,
                relationship_type="transformed_to",
                event_id=event_id
            )
            self.relationships.append(relationship)
        
        # Store
        self._add_entity(output_entity)
        self._add_event(event)
        
        return output_entity_id, event_id
    
    def track_validation(
        self,
        entity_id: str,
        validation_type: str,
        operator: str,
        success: bool,
        error_message: Optional[str] = None,
        metrics: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Track data validation
        
        Returns:
            Event ID
        """
        event_id = str(uuid.uuid4())
        event = LineageEvent(
            event_id=event_id,
            event_type=LineageEventType.VALIDATION,
            input_entities=[entity_id],
            output_entities=[entity_id],
            operation=f"Validation: {validation_type}",
            operator=operator,
            timestamp=datetime.now(),
            success=success,
            error_message=error_message,
            metrics=metrics or {}
        )
        
        self._add_event(event)
        return event_id
    
    def get_entity_lineage(
        self,
        entity_id: str,
        direction: str = "both",
        max_depth: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get lineage for an entity
        
        Args:
            entity_id: Entity to trace
            direction: "upstream", "downstream", or "both"
            max_depth: Maximum depth to traverse
            
        Returns:
            Lineage information
        """
        if entity_id not in self.entities:
            raise ValueError(f"Entity {entity_id} not found")
        
        result = {
            "entity": asdict(self.entities[entity_id]),
            "upstream": [],
            "downstream": [],
            "events": []
        }
        
        if direction in ["upstream", "both"]:
            # Trace upstream (ancestors)
            upstream = self._trace_ancestors(entity_id, max_depth)
            result["upstream"] = [
                asdict(self.entities[eid]) for eid in upstream
                if eid in self.entities
            ]
        
        if direction in ["downstream", "both"]:
            # Trace downstream (descendants)
            downstream = self._trace_descendants(entity_id, max_depth)
            result["downstream"] = [
                asdict(self.entities[eid]) for eid in downstream
                if eid in self.entities
            ]
        
        # Get related events
        event_ids = self.events_by_entity.get(entity_id, set())
        result["events"] = [
            asdict(self.events[eid]) for eid in event_ids
            if eid in self.events
        ]
        
        return result
    
    def get_impact_analysis(
        self,
        entity_id: str,
        change_type: str = "modification"
    ) -> Dict[str, Any]:
        """
        Analyze impact of changes to an entity
        
        Args:
            entity_id: Entity that changed
            change_type: Type of change
            
        Returns:
            Impact analysis
        """
        if entity_id not in self.entities:
            raise ValueError(f"Entity {entity_id} not found")
        
        # Get all downstream entities
        affected_entities = self._trace_descendants(entity_id)
        
        # Categorize by type
        impact_by_type = defaultdict(list)
        for eid in affected_entities:
            if eid in self.entities:
                entity = self.entities[eid]
                impact_by_type[entity.entity_type].append({
                    "id": eid,
                    "name": entity.name,
                    "location": entity.location
                })
        
        # Calculate impact metrics
        total_affected = len(affected_entities)
        
        return {
            "source_entity": asdict(self.entities[entity_id]),
            "change_type": change_type,
            "total_affected_entities": total_affected,
            "affected_by_type": dict(impact_by_type),
            "affected_entity_ids": list(affected_entities),
            "risk_level": self._calculate_risk_level(total_affected)
        }
    
    def find_data_sources(
        self,
        entity_id: str
    ) -> List[Dict[str, Any]]:
        """
        Find original data sources for an entity
        
        Args:
            entity_id: Entity to trace
            
        Returns:
            List of source entities
        """
        # Trace to root sources
        ancestors = self._trace_ancestors(entity_id)
        
        sources = []
        for aid in ancestors:
            if aid in self.entities:
                entity = self.entities[aid]
                # Check if this is a source (no parents)
                if not self.entity_parents.get(aid):
                    sources.append(asdict(entity))
        
        return sources
    
    def validate_lineage_integrity(self) -> Dict[str, Any]:
        """
        Validate lineage graph integrity
        
        Returns:
            Validation report
        """
        issues = []
        
        # Check for orphaned entities
        for entity_id in self.entities:
            if entity_id not in self.graph:
                issues.append({
                    "type": "orphaned_entity",
                    "entity_id": entity_id,
                    "message": "Entity not in lineage graph"
                })
        
        # Check for cycles
        if not nx.is_directed_acyclic_graph(self.graph):
            cycles = list(nx.simple_cycles(self.graph))
            for cycle in cycles:
                issues.append({
                    "type": "cycle_detected",
                    "entities": cycle,
                    "message": "Circular dependency detected"
                })
        
        # Check for missing entities in events
        for event in self.events.values():
            for entity_id in event.input_entities + event.output_entities:
                if entity_id not in self.entities:
                    issues.append({
                        "type": "missing_entity",
                        "event_id": event.event_id,
                        "entity_id": entity_id,
                        "message": "Entity referenced in event but not found"
                    })
        
        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "total_entities": len(self.entities),
            "total_events": len(self.events),
            "total_relationships": len(self.relationships)
        }
    
    def export_lineage_graph(
        self,
        format: str = "json",
        output_path: Optional[Path] = None
    ) -> Optional[str]:
        """
        Export lineage graph
        
        Args:
            format: Export format (json, graphml, dot)
            output_path: Output file path
            
        Returns:
            Exported data as string if no output_path
        """
        if format == "json":
            data = {
                "entities": {k: asdict(v) for k, v in self.entities.items()},
                "events": {k: asdict(v) for k, v in self.events.items()},
                "relationships": [asdict(r) for r in self.relationships]
            }
            
            # Custom JSON encoder for datetime
            def json_encoder(obj):
                if isinstance(obj, datetime):
                    return obj.isoformat()
                raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
            
            json_str = json.dumps(data, default=json_encoder, indent=2)
            
            if output_path:
                output_path.write_text(json_str)
                return None
            return json_str
            
        elif format == "graphml":
            if output_path:
                nx.write_graphml(self.graph, str(output_path))
                return None
            # Return GraphML as string
            import io
            buffer = io.BytesIO()
            nx.write_graphml(self.graph, buffer)
            return buffer.getvalue().decode()
            
        elif format == "dot":
            dot_lines = ["digraph lineage {"]
            for edge in self.graph.edges():
                source_name = self.entities[edge[0]].name if edge[0] in self.entities else edge[0]
                target_name = self.entities[edge[1]].name if edge[1] in self.entities else edge[1]
                dot_lines.append(f'  "{source_name}" -> "{target_name}";')
            dot_lines.append("}")
            dot_str = "\n".join(dot_lines)
            
            if output_path:
                output_path.write_text(dot_str)
                return None
            return dot_str
        
        else:
            raise ValueError(f"Unsupported format: {format}")
    
    def _add_entity(self, entity: DataEntity):
        """Add entity to tracker"""
        self.entities[entity.entity_id] = entity
        self.entity_by_name[entity.name].add(entity.entity_id)
        self.graph.add_node(entity.entity_id, **asdict(entity))
    
    def _add_event(self, event: LineageEvent):
        """Add event to tracker"""
        self.events[event.event_id] = event
        
        # Update indexes
        for entity_id in event.input_entities + event.output_entities:
            self.events_by_entity[entity_id].add(event.event_id)
        
        # Update graph
        for input_id in event.input_entities:
            for output_id in event.output_entities:
                self.graph.add_edge(input_id, output_id, event_id=event.event_id)
                self.entity_children[input_id].add(output_id)
                self.entity_parents[output_id].add(input_id)
    
    def _trace_ancestors(
        self,
        entity_id: str,
        max_depth: Optional[int] = None,
        visited: Optional[Set[str]] = None
    ) -> Set[str]:
        """Recursively trace ancestors"""
        if visited is None:
            visited = set()
        
        if entity_id in visited:
            return visited
        
        if max_depth is not None and max_depth <= 0:
            return visited
        
        visited.add(entity_id)
        
        for parent_id in self.entity_parents.get(entity_id, []):
            self._trace_ancestors(
                parent_id,
                max_depth - 1 if max_depth else None,
                visited
            )
        
        return visited
    
    def _trace_descendants(
        self,
        entity_id: str,
        max_depth: Optional[int] = None,
        visited: Optional[Set[str]] = None
    ) -> Set[str]:
        """Recursively trace descendants"""
        if visited is None:
            visited = set()
        
        if entity_id in visited:
            return visited
        
        if max_depth is not None and max_depth <= 0:
            return visited
        
        visited.add(entity_id)
        
        for child_id in self.entity_children.get(entity_id, []):
            self._trace_descendants(
                child_id,
                max_depth - 1 if max_depth else None,
                visited
            )
        
        return visited
    
    def _calculate_risk_level(self, affected_count: int) -> str:
        """Calculate risk level based on impact"""
        if affected_count == 0:
            return "none"
        elif affected_count < 5:
            return "low"
        elif affected_count < 20:
            return "medium"
        elif affected_count < 50:
            return "high"
        else:
            return "critical"
    
    def _save_lineage(self):
        """Save lineage to disk"""
        lineage_file = self.storage_path / "lineage.pkl"
        with open(lineage_file, "wb") as f:
            pickle.dump({
                "entities": self.entities,
                "events": self.events,
                "relationships": self.relationships
            }, f)
    
    def _load_lineage(self):
        """Load lineage from disk"""
        lineage_file = self.storage_path / "lineage.pkl"
        if lineage_file.exists():
            try:
                with open(lineage_file, "rb") as f:
                    data = pickle.load(f)
                    self.entities = data.get("entities", {})
                    self.events = data.get("events", {})
                    self.relationships = data.get("relationships", [])
                    
                    # Rebuild graph and indexes
                    for entity in self.entities.values():
                        self._add_entity(entity)
                    for event in self.events.values():
                        self._add_event(event)
            except Exception as e:
                print(f"Failed to load lineage: {e}")


# Custom exceptions
class LineageException(Exception):
    """Base exception for lineage errors"""
    pass

class EntityNotFoundException(LineageException):
    """Entity not found in lineage"""
    pass

class CyclicDependencyException(LineageException):
    """Cyclic dependency detected in lineage"""
    pass

class LineageIntegrityException(LineageException):
    """Lineage integrity validation failed"""
    pass