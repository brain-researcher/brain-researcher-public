"""Temporal Cypher query language extensions - completes KG-030 Temporal Graph.

This module provides a temporal query language that extends Cypher with
time-aware constructs for querying graph evolution and temporal patterns.
"""

import logging
import re
from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


class TemporalQueryType(Enum):
    """Types of temporal queries."""
    
    SNAPSHOT = "snapshot"  # Query at specific time
    INTERVAL = "interval"  # Query within time range
    EVOLUTION = "evolution"  # Query for changes over time
    PATTERN = "pattern"  # Query for temporal patterns
    SEQUENCE = "sequence"  # Query for event sequences


class TemporalOperator(Enum):
    """Temporal operators for query construction."""
    
    # Time point operators
    AT_TIME = "AT"  # At specific time
    BEFORE = "BEFORE"  # Before time
    AFTER = "AFTER"  # After time
    
    # Time range operators
    DURING = "DURING"  # During time range
    BETWEEN = "BETWEEN"  # Between two times
    
    # Evolution operators
    CHANGED = "CHANGED"  # Entity changed
    CREATED = "CREATED"  # Entity was created
    DELETED = "DELETED"  # Entity was deleted
    STABLE = "STABLE"  # Entity remained stable
    
    # Sequence operators
    FOLLOWS = "FOLLOWS"  # Event A follows event B
    PRECEDES = "PRECEDES"  # Event A precedes event B
    OVERLAPS = "OVERLAPS"  # Events overlap in time


@dataclass
class TemporalFilter:
    """Represents a temporal filter condition."""
    
    operator: TemporalOperator
    entity_path: str  # e.g., "n", "r", "n.property"
    time_value: Optional[datetime] = None
    time_range: Optional[tuple[datetime, datetime]] = None
    property_name: Optional[str] = None
    
    def to_cypher_condition(self, param_prefix: str = "temp") -> tuple[str, Dict[str, Any]]:
        """Convert to Cypher WHERE condition.
        
        Args:
            param_prefix: Prefix for parameter names
            
        Returns:
            Tuple of (condition_string, parameters)
        """
        conditions = []
        params = {}
        
        if self.operator == TemporalOperator.AT_TIME:
            if self.time_value:
                conditions.extend([
                    f"{self.entity_path}.transaction_time_start <= ${param_prefix}_at_time",
                    f"({self.entity_path}.transaction_time_end IS NULL OR {self.entity_path}.transaction_time_end > ${param_prefix}_at_time)"
                ])
                params[f"{param_prefix}_at_time"] = self.time_value
        
        elif self.operator == TemporalOperator.BEFORE:
            if self.time_value:
                conditions.append(f"{self.entity_path}.transaction_time_start < ${param_prefix}_before_time")
                params[f"{param_prefix}_before_time"] = self.time_value
        
        elif self.operator == TemporalOperator.AFTER:
            if self.time_value:
                conditions.append(f"{self.entity_path}.transaction_time_start > ${param_prefix}_after_time")
                params[f"{param_prefix}_after_time"] = self.time_value
        
        elif self.operator == TemporalOperator.DURING:
            if self.time_range:
                start_time, end_time = self.time_range
                conditions.extend([
                    f"{self.entity_path}.transaction_time_start >= ${param_prefix}_during_start",
                    f"{self.entity_path}.transaction_time_start <= ${param_prefix}_during_end"
                ])
                params[f"{param_prefix}_during_start"] = start_time
                params[f"{param_prefix}_during_end"] = end_time
        
        elif self.operator == TemporalOperator.BETWEEN:
            if self.time_range:
                start_time, end_time = self.time_range
                conditions.extend([
                    f"{self.entity_path}.transaction_time_start >= ${param_prefix}_between_start",
                    f"{self.entity_path}.transaction_time_start <= ${param_prefix}_between_end"
                ])
                params[f"{param_prefix}_between_start"] = start_time
                params[f"{param_prefix}_between_end"] = end_time
        
        elif self.operator == TemporalOperator.CREATED:
            if self.time_range:
                start_time, end_time = self.time_range
                conditions.extend([
                    f"{self.entity_path}.created_at >= ${param_prefix}_created_start",
                    f"{self.entity_path}.created_at <= ${param_prefix}_created_end"
                ])
                params[f"{param_prefix}_created_start"] = start_time
                params[f"{param_prefix}_created_end"] = end_time
        
        elif self.operator == TemporalOperator.CHANGED:
            if self.time_range:
                start_time, end_time = self.time_range
                conditions.extend([
                    f"{self.entity_path}.updated_at IS NOT NULL",
                    f"{self.entity_path}.updated_at >= ${param_prefix}_changed_start",
                    f"{self.entity_path}.updated_at <= ${param_prefix}_changed_end"
                ])
                params[f"{param_prefix}_changed_start"] = start_time
                params[f"{param_prefix}_changed_end"] = end_time
        
        elif self.operator == TemporalOperator.DELETED:
            if self.time_range:
                start_time, end_time = self.time_range
                conditions.extend([
                    f"{self.entity_path}.transaction_time_end IS NOT NULL",
                    f"{self.entity_path}.transaction_time_end >= ${param_prefix}_deleted_start",
                    f"{self.entity_path}.transaction_time_end <= ${param_prefix}_deleted_end"
                ])
                params[f"{param_prefix}_deleted_start"] = start_time
                params[f"{param_prefix}_deleted_end"] = end_time
        
        return " AND ".join(conditions) if conditions else "TRUE", params


class TemporalCypherBuilder:
    """Builder for temporal Cypher queries."""
    
    def __init__(self):
        """Initialize temporal Cypher builder."""
        self.query_type = TemporalQueryType.SNAPSHOT
        self.match_patterns = []
        self.temporal_filters = []
        self.where_conditions = []
        self.return_clauses = []
        self.order_by_clauses = []
        self.limit_value = None
        self.parameters = {}
        
        self._current_entity_alias = None
        
    def snapshot_at(self, time: datetime) -> "TemporalCypherBuilder":
        """Query snapshot at specific time.
        
        Args:
            time: Time to query at
            
        Returns:
            Builder instance
        """
        self.query_type = TemporalQueryType.SNAPSHOT
        self.temporal_filters.append(
            TemporalFilter(TemporalOperator.AT_TIME, "n", time_value=time)
        )
        return self
    
    def during_interval(self, start_time: datetime, end_time: datetime) -> "TemporalCypherBuilder":
        """Query during time interval.
        
        Args:
            start_time: Start of interval
            end_time: End of interval
            
        Returns:
            Builder instance
        """
        self.query_type = TemporalQueryType.INTERVAL
        self.temporal_filters.append(
            TemporalFilter(TemporalOperator.DURING, "n", time_range=(start_time, end_time))
        )
        return self
    
    def evolution_between(self, start_time: datetime, end_time: datetime) -> "TemporalCypherBuilder":
        """Query evolution between times.
        
        Args:
            start_time: Start time
            end_time: End time
            
        Returns:
            Builder instance
        """
        self.query_type = TemporalQueryType.EVOLUTION
        # Don't add automatic filters for evolution queries
        return self
    
    def match_temporal_nodes(
        self,
        labels: Optional[List[str]] = None,
        alias: str = "n",
        properties: Optional[Dict[str, Any]] = None
    ) -> "TemporalCypherBuilder":
        """Match temporal nodes.
        
        Args:
            labels: Node labels
            alias: Node alias
            properties: Property filters
            
        Returns:
            Builder instance
        """
        label_str = ""
        if labels:
            all_labels = ["TemporalNode"] + labels
            label_str = ":" + ":".join(f"`{label}`" for label in all_labels)
        else:
            label_str = ":TemporalNode"
        
        pattern = f"({alias}{label_str})"
        self.match_patterns.append(pattern)
        self._current_entity_alias = alias
        
        # Add property filters
        if properties:
            for key, value in properties.items():
                param_name = f"{alias}_{key}"
                self.where_conditions.append(f"{alias}.{key} = ${param_name}")
                self.parameters[param_name] = value
        
        return self
    
    def match_temporal_relationships(
        self,
        relationship_type: Optional[str] = None,
        start_alias: str = "start",
        end_alias: str = "end",
        rel_alias: str = "r"
    ) -> "TemporalCypherBuilder":
        """Match temporal relationships.
        
        Args:
            relationship_type: Relationship type
            start_alias: Start node alias
            end_alias: End node alias
            rel_alias: Relationship alias
            
        Returns:
            Builder instance
        """
        if relationship_type:
            pattern = f"({start_alias}:TemporalNode)-[{rel_alias}:TEMPORAL_REL {{type: '{relationship_type}'}}]->({end_alias}:TemporalNode)"
        else:
            pattern = f"({start_alias}:TemporalNode)-[{rel_alias}:TEMPORAL_REL]->({end_alias}:TemporalNode)"
        
        self.match_patterns.append(pattern)
        return self
    
    def where_created_during(
        self,
        start_time: datetime,
        end_time: datetime,
        entity_alias: Optional[str] = None
    ) -> "TemporalCypherBuilder":
        """Add condition for entities created during time range.
        
        Args:
            start_time: Start time
            end_time: End time
            entity_alias: Entity alias (defaults to current)
            
        Returns:
            Builder instance
        """
        alias = entity_alias or self._current_entity_alias or "n"
        temp_filter = TemporalFilter(
            TemporalOperator.CREATED,
            alias,
            time_range=(start_time, end_time)
        )
        self.temporal_filters.append(temp_filter)
        return self
    
    def where_changed_during(
        self,
        start_time: datetime,
        end_time: datetime,
        entity_alias: Optional[str] = None
    ) -> "TemporalCypherBuilder":
        """Add condition for entities changed during time range.
        
        Args:
            start_time: Start time
            end_time: End time
            entity_alias: Entity alias (defaults to current)
            
        Returns:
            Builder instance
        """
        alias = entity_alias or self._current_entity_alias or "n"
        temp_filter = TemporalFilter(
            TemporalOperator.CHANGED,
            alias,
            time_range=(start_time, end_time)
        )
        self.temporal_filters.append(temp_filter)
        return self
    
    def where_deleted_during(
        self,
        start_time: datetime,
        end_time: datetime,
        entity_alias: Optional[str] = None
    ) -> "TemporalCypherBuilder":
        """Add condition for entities deleted during time range.
        
        Args:
            start_time: Start time
            end_time: End time
            entity_alias: Entity alias (defaults to current)
            
        Returns:
            Builder instance
        """
        alias = entity_alias or self._current_entity_alias or "n"
        temp_filter = TemporalFilter(
            TemporalOperator.DELETED,
            alias,
            time_range=(start_time, end_time)
        )
        self.temporal_filters.append(temp_filter)
        return self
    
    def where_stable_during(
        self,
        start_time: datetime,
        end_time: datetime,
        entity_alias: Optional[str] = None
    ) -> "TemporalCypherBuilder":
        """Add condition for entities that remained stable.
        
        Args:
            start_time: Start time
            end_time: End time
            entity_alias: Entity alias (defaults to current)
            
        Returns:
            Builder instance
        """
        alias = entity_alias or self._current_entity_alias or "n"
        
        # Stable means created before start_time and not changed during interval
        condition = f"""
        {alias}.created_at < $stable_start_time AND
        ({alias}.updated_at IS NULL OR {alias}.updated_at < $stable_start_time) AND
        ({alias}.transaction_time_end IS NULL OR {alias}.transaction_time_end > $stable_end_time)
        """
        
        self.where_conditions.append(condition.strip())
        self.parameters["stable_start_time"] = start_time
        self.parameters["stable_end_time"] = end_time
        
        return self
    
    def where_property_changed(
        self,
        property_name: str,
        start_time: datetime,
        end_time: datetime,
        entity_alias: Optional[str] = None
    ) -> "TemporalCypherBuilder":
        """Add condition for specific property changes.
        
        Args:
            property_name: Property name to check
            start_time: Start time
            end_time: End time
            entity_alias: Entity alias (defaults to current)
            
        Returns:
            Builder instance
        """
        alias = entity_alias or self._current_entity_alias or "n"
        
        # Check if there are different versions with different property values
        condition = f"""
        EXISTS {{
            MATCH ({alias}_old:{alias.__class__.__name__} {{id: {alias}.id}})
            WHERE {alias}_old.version < {alias}.version
            AND {alias}_old.transaction_time_start >= $prop_change_start_time
            AND {alias}_old.transaction_time_start <= $prop_change_end_time
            AND ({alias}_old.{property_name} <> {alias}.{property_name} OR 
                 ({alias}_old.{property_name} IS NULL AND {alias}.{property_name} IS NOT NULL) OR
                 ({alias}_old.{property_name} IS NOT NULL AND {alias}.{property_name} IS NULL))
        }}
        """
        
        self.where_conditions.append(condition.strip())
        self.parameters["prop_change_start_time"] = start_time
        self.parameters["prop_change_end_time"] = end_time
        
        return self
    
    def where_custom(self, condition: str, params: Optional[Dict[str, Any]] = None) -> "TemporalCypherBuilder":
        """Add custom WHERE condition.
        
        Args:
            condition: Cypher condition
            params: Parameters for the condition
            
        Returns:
            Builder instance
        """
        self.where_conditions.append(condition)
        if params:
            self.parameters.update(params)
        return self
    
    def return_entities(self, *aliases: str) -> "TemporalCypherBuilder":
        """Return specified entities.
        
        Args:
            *aliases: Entity aliases to return
            
        Returns:
            Builder instance
        """
        for alias in aliases:
            self.return_clauses.append(alias)
        return self
    
    def return_properties(self, alias: str, *properties: str) -> "TemporalCypherBuilder":
        """Return specific properties of an entity.
        
        Args:
            alias: Entity alias
            *properties: Property names
            
        Returns:
            Builder instance
        """
        for prop in properties:
            self.return_clauses.append(f"{alias}.{prop}")
        return self
    
    def return_temporal_info(self, alias: str) -> "TemporalCypherBuilder":
        """Return temporal information for entity.
        
        Args:
            alias: Entity alias
            
        Returns:
            Builder instance
        """
        temporal_props = [
            f"{alias}.created_at",
            f"{alias}.updated_at",
            f"{alias}.version",
            f"{alias}.transaction_time_start",
            f"{alias}.transaction_time_end",
            f"{alias}.valid_time_start",
            f"{alias}.valid_time_end"
        ]
        self.return_clauses.extend(temporal_props)
        return self
    
    def return_evolution_summary(
        self,
        alias: str,
        start_time: datetime,
        end_time: datetime
    ) -> "TemporalCypherBuilder":
        """Return evolution summary for entity.
        
        Args:
            alias: Entity alias
            start_time: Start time
            end_time: End time
            
        Returns:
            Builder instance
        """
        # Count versions in time range
        summary_expr = f"""
        {{
            entity_id: {alias}.id,
            versions_in_range: size([
                ({alias}_hist:{alias.__class__.__name__} {{id: {alias}.id}})
                WHERE {alias}_hist.transaction_time_start >= $evolution_start_time
                AND {alias}_hist.transaction_time_start <= $evolution_end_time
                | {alias}_hist
            ]),
            first_version_time: min([
                ({alias}_hist:{alias.__class__.__name__} {{id: {alias}.id}})
                WHERE {alias}_hist.transaction_time_start >= $evolution_start_time
                AND {alias}_hist.transaction_time_start <= $evolution_end_time
                | {alias}_hist.transaction_time_start
            ]),
            last_version_time: max([
                ({alias}_hist:{alias.__class__.__name__} {{id: {alias}.id}})
                WHERE {alias}_hist.transaction_time_start >= $evolution_start_time
                AND {alias}_hist.transaction_time_start <= $evolution_end_time
                | {alias}_hist.transaction_time_start
            ])
        }} as evolution_summary
        """
        
        self.return_clauses.append(summary_expr.strip())
        self.parameters["evolution_start_time"] = start_time
        self.parameters["evolution_end_time"] = end_time
        
        return self
    
    def order_by_time(self, alias: str, ascending: bool = True) -> "TemporalCypherBuilder":
        """Order by temporal fields.
        
        Args:
            alias: Entity alias
            ascending: Sort direction
            
        Returns:
            Builder instance
        """
        direction = "ASC" if ascending else "DESC"
        self.order_by_clauses.append(f"{alias}.transaction_time_start {direction}")
        return self
    
    def order_by_creation(self, alias: str, ascending: bool = True) -> "TemporalCypherBuilder":
        """Order by creation time.
        
        Args:
            alias: Entity alias
            ascending: Sort direction
            
        Returns:
            Builder instance
        """
        direction = "ASC" if ascending else "DESC"
        self.order_by_clauses.append(f"{alias}.created_at {direction}")
        return self
    
    def limit(self, count: int) -> "TemporalCypherBuilder":
        """Limit results.
        
        Args:
            count: Maximum number of results
            
        Returns:
            Builder instance
        """
        self.limit_value = count
        return self
    
    def build(self) -> tuple[str, Dict[str, Any]]:
        """Build the temporal Cypher query.
        
        Returns:
            Tuple of (cypher_query, parameters)
        """
        query_parts = []
        all_params = self.parameters.copy()
        
        # MATCH clauses
        if self.match_patterns:
            query_parts.append("MATCH " + ", ".join(self.match_patterns))
        
        # WHERE clauses
        all_conditions = self.where_conditions.copy()
        
        # Add temporal filter conditions
        for i, temp_filter in enumerate(self.temporal_filters):
            condition, params = temp_filter.to_cypher_condition(f"temp_{i}")
            if condition and condition != "TRUE":
                all_conditions.append(condition)
                all_params.update(params)
        
        if all_conditions:
            query_parts.append("WHERE " + " AND ".join(all_conditions))
        
        # RETURN clauses
        if self.return_clauses:
            query_parts.append("RETURN " + ", ".join(self.return_clauses))
        else:
            # Default return for different query types
            if self.query_type == TemporalQueryType.SNAPSHOT:
                query_parts.append("RETURN n")
            elif self.query_type == TemporalQueryType.EVOLUTION:
                query_parts.append("RETURN n, n.version, n.transaction_time_start")
            else:
                query_parts.append("RETURN n")
        
        # ORDER BY clauses
        if self.order_by_clauses:
            query_parts.append("ORDER BY " + ", ".join(self.order_by_clauses))
        
        # LIMIT clause
        if self.limit_value:
            query_parts.append(f"LIMIT {self.limit_value}")
        
        cypher_query = " ".join(query_parts)
        
        logger.debug(f"Built temporal Cypher query: {cypher_query}")
        return cypher_query, all_params
    
    @classmethod
    def snapshot_query(
        cls,
        time: datetime,
        labels: Optional[List[str]] = None,
        properties: Optional[Dict[str, Any]] = None
    ) -> tuple[str, Dict[str, Any]]:
        """Create a snapshot query.
        
        Args:
            time: Time to query at
            labels: Node labels to filter
            properties: Property filters
            
        Returns:
            Tuple of (cypher_query, parameters)
        """
        builder = cls()
        builder.snapshot_at(time)
        builder.match_temporal_nodes(labels=labels, properties=properties)
        return builder.build()
    
    @classmethod
    def evolution_query(
        cls,
        entity_id: str,
        start_time: datetime,
        end_time: datetime
    ) -> tuple[str, Dict[str, Any]]:
        """Create an evolution query for specific entity.
        
        Args:
            entity_id: Entity ID to track
            start_time: Start time
            end_time: End time
            
        Returns:
            Tuple of (cypher_query, parameters)
        """
        builder = cls()
        builder.evolution_between(start_time, end_time)
        builder.match_temporal_nodes(properties={"id": entity_id})
        builder.where_custom(
            "n.transaction_time_start >= $evolution_start AND n.transaction_time_start <= $evolution_end",
            {"evolution_start": start_time, "evolution_end": end_time}
        )
        builder.return_entities("n")
        builder.return_temporal_info("n")
        builder.order_by_time("n")
        
        return builder.build()
    
    @classmethod
    def change_detection_query(
        cls,
        start_time: datetime,
        end_time: datetime,
        labels: Optional[List[str]] = None
    ) -> tuple[str, Dict[str, Any]]:
        """Create a change detection query.
        
        Args:
            start_time: Start time
            end_time: End time
            labels: Node labels to filter
            
        Returns:
            Tuple of (cypher_query, parameters)
        """
        builder = cls()
        builder.during_interval(start_time, end_time)
        builder.match_temporal_nodes(labels=labels)
        builder.where_changed_during(start_time, end_time)
        builder.return_entities("n")
        builder.return_temporal_info("n")
        builder.order_by_time("n", ascending=False)
        
        return builder.build()
    
    def reset(self) -> "TemporalCypherBuilder":
        """Reset builder to initial state.
        
        Returns:
            Builder instance
        """
        self.query_type = TemporalQueryType.SNAPSHOT
        self.match_patterns.clear()
        self.temporal_filters.clear()
        self.where_conditions.clear()
        self.return_clauses.clear()
        self.order_by_clauses.clear()
        self.limit_value = None
        self.parameters.clear()
        self._current_entity_alias = None
        
        return self


# Predefined temporal query templates
TEMPORAL_QUERY_TEMPLATES = {
    "snapshot_at_time": """
    MATCH (n:TemporalNode)
    WHERE n.transaction_time_start <= $snapshot_time
    AND (n.transaction_time_end IS NULL OR n.transaction_time_end > $snapshot_time)
    AND NOT EXISTS {
        MATCH (newer:TemporalNode {id: n.id})
        WHERE newer.version > n.version
        AND newer.transaction_time_start <= $snapshot_time
    }
    RETURN n
    ORDER BY n.id
    """,
    
    "entities_created_during": """
    MATCH (n:TemporalNode)
    WHERE n.created_at >= $start_time
    AND n.created_at <= $end_time
    RETURN n, n.created_at
    ORDER BY n.created_at DESC
    """,
    
    "entities_changed_during": """
    MATCH (n:TemporalNode)
    WHERE n.updated_at IS NOT NULL
    AND n.updated_at >= $start_time
    AND n.updated_at <= $end_time
    RETURN n, n.updated_at, n.version
    ORDER BY n.updated_at DESC
    """,
    
    "entity_evolution": """
    MATCH (n:TemporalNode {id: $entity_id})
    WHERE n.transaction_time_start >= $start_time
    AND n.transaction_time_start <= $end_time
    RETURN n, n.version, n.transaction_time_start, n.updated_at
    ORDER BY n.version ASC
    """,
    
    "relationship_evolution": """
    MATCH ()-[r:TEMPORAL_REL {id: $rel_id}]->()
    WHERE r.transaction_time_start >= $start_time
    AND r.transaction_time_start <= $end_time
    RETURN r, r.version, r.transaction_time_start, r.updated_at
    ORDER BY r.version ASC
    """,
    
    "most_changed_entities": """
    MATCH (n:TemporalNode)
    WHERE n.transaction_time_start >= $start_time
    AND n.transaction_time_start <= $end_time
    WITH n.id as entity_id, count(*) as change_count, collect(n) as versions
    ORDER BY change_count DESC
    LIMIT $top_k
    RETURN entity_id, change_count, 
           [v IN versions | {version: v.version, time: v.transaction_time_start}] as changes
    """,
    
    "temporal_pattern_match": """
    MATCH (n1:TemporalNode)-[r:TEMPORAL_REL]->(n2:TemporalNode)
    WHERE n1.transaction_time_start <= $pattern_time
    AND n2.transaction_time_start <= $pattern_time
    AND r.transaction_time_start <= $pattern_time
    AND (n1.transaction_time_end IS NULL OR n1.transaction_time_end > $pattern_time)
    AND (n2.transaction_time_end IS NULL OR n2.transaction_time_end > $pattern_time)
    AND (r.transaction_time_end IS NULL OR r.transaction_time_end > $pattern_time)
    RETURN n1, r, n2
    """
}