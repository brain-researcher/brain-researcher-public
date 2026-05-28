"""Advanced multi-hop graph traversal for complex knowledge discovery.

This module provides sophisticated graph traversal capabilities for:
- Multi-hop relationship discovery with path constraints
- Weighted path analysis based on edge types and strengths
- Pattern-based graph queries (e.g., motif discovery)
- Bidirectional search and path optimization
- Context-aware traversal with semantic filtering
"""

import json
import logging
import numpy as np
import time
from typing import Dict, List, Any, Optional, Tuple, Union, Set, Callable
from dataclasses import dataclass, asdict
from enum import Enum
from collections import defaultdict, deque
import heapq
from itertools import combinations

logger = logging.getLogger(__name__)

try:  # pragma: no cover - neo4j optional in unit tests
    from neo4j import Query as Neo4jQuery
except Exception:  # pragma: no cover - defensive fallback
    Neo4jQuery = None


class TraversalMode(str, Enum):
    """Graph traversal modes."""
    BREADTH_FIRST = "bfs"
    DEPTH_FIRST = "dfs"
    SHORTEST_PATH = "shortest"
    WEIGHTED_PATH = "weighted"
    BIDIRECTIONAL = "bidirectional"
    PATTERN_MATCH = "pattern"


class EdgeDirection(str, Enum):
    """Edge traversal directions."""
    OUTGOING = "outgoing"
    INCOMING = "incoming"
    BOTH = "both"


@dataclass
class TraversalConstraints:
    """Constraints for graph traversal."""
    
    max_depth: int = 5
    max_results: int = 100
    query_timeout_ms: Optional[int] = None
    min_edge_weight: Optional[float] = None
    allowed_edge_types: Optional[Set[str]] = None
    forbidden_edge_types: Optional[Set[str]] = None
    node_filters: Optional[Dict[str, Any]] = None
    edge_filters: Optional[Dict[str, Any]] = None
    direction: EdgeDirection = EdgeDirection.BOTH
    require_return_path: bool = False


@dataclass
class TraversalPath:
    """Represents a path through the graph."""
    
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    total_weight: float
    path_length: int
    start_node_id: str
    end_node_id: str
    semantic_coherence: Optional[float] = None
    path_type: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class TraversalResult:
    """Result of a multi-hop traversal query."""
    
    query_id: str
    start_nodes: List[str]
    paths: List[TraversalPath]
    total_paths_found: int
    execution_time_ms: float
    traversal_mode: TraversalMode
    constraints: TraversalConstraints
    statistics: Dict[str, Any]


class PathPattern:
    """Defines a pattern for path matching."""
    
    def __init__(self, pattern_spec: Dict[str, Any]):
        """Initialize path pattern.
        
        Args:
            pattern_spec: Pattern specification dictionary
        """
        self.node_patterns = pattern_spec.get('nodes', [])
        self.edge_patterns = pattern_spec.get('edges', [])
        self.min_length = pattern_spec.get('min_length', 1)
        self.max_length = pattern_spec.get('max_length', 10)
        self.pattern_type = pattern_spec.get('type', 'linear')
    
    def matches_path(self, path: TraversalPath) -> bool:
        """Check if path matches this pattern.
        
        Args:
            path: Path to check
            
        Returns:
            True if path matches pattern
        """
        if not (self.min_length <= path.path_length <= self.max_length):
            return False
        
        # Simple linear pattern matching
        if self.pattern_type == 'linear':
            return self._matches_linear_pattern(path)
        elif self.pattern_type == 'star':
            return self._matches_star_pattern(path)
        elif self.pattern_type == 'cycle':
            return self._matches_cycle_pattern(path)
        
        return True
    
    def _matches_linear_pattern(self, path: TraversalPath) -> bool:
        """Check linear pattern match."""
        # Check if node types match pattern
        if self.node_patterns:
            for i, node_pattern in enumerate(self.node_patterns):
                if i >= len(path.nodes):
                    break
                node = path.nodes[i]
                if not self._node_matches_pattern(node, node_pattern):
                    return False
        
        # Check if edge types match pattern
        if self.edge_patterns:
            for i, edge_pattern in enumerate(self.edge_patterns):
                if i >= len(path.edges):
                    break
                edge = path.edges[i]
                if not self._edge_matches_pattern(edge, edge_pattern):
                    return False
        
        return True
    
    def _matches_star_pattern(self, path: TraversalPath) -> bool:
        """Check star pattern (hub with spokes)."""
        if path.path_length < 2:
            return False
        
        # Find potential hub (node with highest connectivity)
        node_degrees = defaultdict(int)
        for edge in path.edges:
            node_degrees[edge.get('start_node')] += 1
            node_degrees[edge.get('end_node')] += 1
        
        # Check if there's a clear hub
        max_degree = max(node_degrees.values())
        return max_degree >= len(path.nodes) // 2
    
    def _matches_cycle_pattern(self, path: TraversalPath) -> bool:
        """Check cycle pattern."""
        return (path.start_node_id == path.end_node_id and 
                path.path_length >= 3)
    
    def _node_matches_pattern(self, node: Dict[str, Any], pattern: Dict[str, Any]) -> bool:
        """Check if node matches pattern."""
        for key, value in pattern.items():
            if key not in node or node[key] != value:
                return False
        return True
    
    def _edge_matches_pattern(self, edge: Dict[str, Any], pattern: Dict[str, Any]) -> bool:
        """Check if edge matches pattern."""
        for key, value in pattern.items():
            if key not in edge or edge[key] != value:
                return False
        return True


class MultiHopQueryEngine:
    """Advanced multi-hop graph traversal engine."""
    
    def __init__(self, neo4j_db, max_concurrent_queries: int = 5):
        """Initialize multi-hop query engine.
        
        Args:
            neo4j_db: Neo4j database connection
            max_concurrent_queries: Maximum concurrent traversal queries
        """
        self.neo4j_db = neo4j_db
        self.max_concurrent_queries = max_concurrent_queries
        
        # Query cache for expensive traversals
        self.query_cache = {}
        self.cache_ttl = 3600  # 1 hour
        
        # Performance tracking
        self.query_stats = {
            'total_queries': 0,
            'cache_hits': 0,
            'avg_execution_time_ms': 0.0,
            'paths_per_query': 0.0,
            'traversal_mode_usage': defaultdict(int)
        }
        
        # Precomputed patterns for common queries
        self.common_patterns = {
            'concept_activation_region': PathPattern({
                'nodes': [{'type': 'Concept'}, {'type': 'Region'}],
                'edges': [{'type': 'ACTIVATES'}],
                'type': 'linear'
            }),
            'task_concept_region': PathPattern({
                'nodes': [{'type': 'Task'}, {'type': 'Concept'}, {'type': 'Region'}],
                'edges': [{'type': 'MEASURES'}, {'type': 'ACTIVATES'}],
                'type': 'linear'
            }),
            'concept_network': PathPattern({
                'type': 'star',
                'min_length': 3,
                'max_length': 8
            })
        }
        
        logger.info("Initialized MultiHopQueryEngine")
    
    def traverse_from_node(self,
                          start_node_id: str,
                          constraints: Optional[TraversalConstraints] = None,
                          mode: TraversalMode = TraversalMode.BREADTH_FIRST,
                          target_node_id: Optional[str] = None,
                          pattern: Optional[PathPattern] = None) -> TraversalResult:
        """Perform multi-hop traversal from a starting node.
        
        Args:
            start_node_id: Starting node ID
            constraints: Traversal constraints
            mode: Traversal mode
            target_node_id: Optional target node for directed search
            pattern: Optional pattern to match
            
        Returns:
            Traversal result with discovered paths
        """
        start_time = time.time()
        self.query_stats['total_queries'] += 1
        self.query_stats['traversal_mode_usage'][mode.value] += 1
        
        if constraints is None:
            constraints = TraversalConstraints()
        
        # Generate cache key
        cache_key = self._generate_cache_key(
            start_node_id, constraints, mode, target_node_id, pattern
        )
        
        # Check cache
        cached_result = self._get_cached_result(cache_key)
        if cached_result:
            self.query_stats['cache_hits'] += 1
            return cached_result
        
        # Perform traversal based on mode
        if mode == TraversalMode.BREADTH_FIRST:
            paths = self._breadth_first_traversal(start_node_id, constraints, target_node_id)
        elif mode == TraversalMode.DEPTH_FIRST:
            paths = self._depth_first_traversal(start_node_id, constraints, target_node_id)
        elif mode == TraversalMode.SHORTEST_PATH:
            paths = self._shortest_path_traversal(start_node_id, constraints, target_node_id)
        elif mode == TraversalMode.WEIGHTED_PATH:
            paths = self._weighted_path_traversal(start_node_id, constraints, target_node_id)
        elif mode == TraversalMode.BIDIRECTIONAL:
            paths = self._bidirectional_traversal(start_node_id, constraints, target_node_id)
        elif mode == TraversalMode.PATTERN_MATCH:
            paths = self._pattern_matching_traversal(start_node_id, constraints, pattern)
        else:
            paths = self._breadth_first_traversal(start_node_id, constraints, target_node_id)
        
        # Filter paths by pattern if specified
        if pattern and mode != TraversalMode.PATTERN_MATCH:
            paths = [path for path in paths if pattern.matches_path(path)]
        
        # Calculate execution time
        execution_time_ms = (time.time() - start_time) * 1000
        
        # Generate statistics
        statistics = self._generate_traversal_statistics(paths, execution_time_ms)
        
        # Create result
        result = TraversalResult(
            query_id=cache_key[:8],
            start_nodes=[start_node_id],
            paths=paths,
            total_paths_found=len(paths),
            execution_time_ms=execution_time_ms,
            traversal_mode=mode,
            constraints=constraints,
            statistics=statistics
        )
        
        # Cache result
        self._cache_result(cache_key, result)
        
        # Update performance stats
        self._update_performance_stats(execution_time_ms, len(paths))
        
        logger.info(f"Multi-hop traversal completed: {len(paths)} paths in {execution_time_ms:.2f}ms")
        
        return result
    
    def _breadth_first_traversal(self,
                                start_node_id: str,
                                constraints: TraversalConstraints,
                                target_node_id: Optional[str] = None) -> List[TraversalPath]:
        """Breadth-first traversal implementation."""
        query = """
        MATCH path = (start)-[*1..%d]-(end)
        WHERE start.%s = $start_id
        %s
        WITH path, nodes(path) as path_nodes, relationships(path) as path_rels,
             length(path) as path_length
        WHERE path_length <= $max_depth
        %s
        RETURN path_nodes, path_rels, path_length,
               reduce(weight = 0, r in path_rels | weight + coalesce(r.weight, 1.0)) as total_weight
        ORDER BY path_length ASC, total_weight DESC
        LIMIT $max_results
        """ % (
            constraints.max_depth,
            self._get_node_id_field(start_node_id),
            self._build_target_filter(target_node_id),
            self._build_path_filters(constraints)
        )
        
        return self._execute_traversal_query(query, start_node_id, target_node_id, constraints)
    
    def _depth_first_traversal(self,
                              start_node_id: str,
                              constraints: TraversalConstraints,
                              target_node_id: Optional[str] = None) -> List[TraversalPath]:
        """Depth-first traversal implementation."""
        # DFS using APOC path expansion
        query = """
        MATCH (start)
        WHERE start.%s = $start_id
        CALL apoc.path.expandConfig(start, {
            minLevel: 1,
            maxLevel: $max_depth,
            relationshipFilter: "%s",
            labelFilter: "%s",
            bfs: false,
            limit: $max_results
        }) YIELD path
        %s
        WITH path, nodes(path) as path_nodes, relationships(path) as path_rels,
             length(path) as path_length
        RETURN path_nodes, path_rels, path_length,
               reduce(weight = 0, r in path_rels | weight + coalesce(r.weight, 1.0)) as total_weight
        ORDER BY path_length DESC, total_weight DESC
        """ % (
            self._get_node_id_field(start_node_id),
            self._build_relationship_filter(constraints),
            self._build_label_filter(constraints),
            self._build_target_filter(target_node_id, "path")
        )
        
        return self._execute_traversal_query(query, start_node_id, target_node_id, constraints)
    
    def _shortest_path_traversal(self,
                                start_node_id: str,
                                constraints: TraversalConstraints,
                                target_node_id: Optional[str] = None) -> List[TraversalPath]:
        """Shortest path traversal using Dijkstra-like algorithm."""
        if not target_node_id:
            # If no target, find shortest paths to all reachable nodes
            return self._breadth_first_traversal(start_node_id, constraints, target_node_id)
        
        query = """
        MATCH (start), (end)
        WHERE start.%s = $start_id AND end.%s = $target_id
        MATCH path = shortestPath((start)-[*1..%d]-(end))
        WITH path, nodes(path) as path_nodes, relationships(path) as path_rels,
             length(path) as path_length
        %s
        RETURN path_nodes, path_rels, path_length,
               reduce(weight = 0, r in path_rels | weight + coalesce(r.weight, 1.0)) as total_weight
        """ % (
            self._get_node_id_field(start_node_id),
            self._get_node_id_field(target_node_id),
            constraints.max_depth,
            self._build_path_filters(constraints)
        )
        
        return self._execute_traversal_query(query, start_node_id, target_node_id, constraints)
    
    def _weighted_path_traversal(self,
                                start_node_id: str,
                                constraints: TraversalConstraints,
                                target_node_id: Optional[str] = None) -> List[TraversalPath]:
        """Weighted path traversal considering edge weights."""
        # Use APOC weighted path algorithms
        query = """
        MATCH (start)
        WHERE start.%s = $start_id
        CALL apoc.algo.dijkstra(start, null, 'weight', %d) YIELD path, weight
        %s
        WITH path, nodes(path) as path_nodes, relationships(path) as path_rels,
             length(path) as path_length, weight as total_weight
        WHERE path_length <= $max_depth
        %s
        RETURN path_nodes, path_rels, path_length, total_weight
        ORDER BY total_weight ASC
        LIMIT $max_results
        """ % (
            self._get_node_id_field(start_node_id),
            constraints.max_depth,
            self._build_target_filter(target_node_id, "path"),
            self._build_path_filters(constraints)
        )
        
        return self._execute_traversal_query(query, start_node_id, target_node_id, constraints)
    
    def _bidirectional_traversal(self,
                                start_node_id: str,
                                constraints: TraversalConstraints,
                                target_node_id: Optional[str] = None) -> List[TraversalPath]:
        """Bidirectional traversal from both ends."""
        if not target_node_id:
            return self._breadth_first_traversal(start_node_id, constraints, target_node_id)
        
        # Bidirectional search
        query = """
        MATCH (start), (end)
        WHERE start.%s = $start_id AND end.%s = $target_id
        
        // Forward search
        MATCH forward_path = (start)-[*1..%d]-(middle)
        WITH start, end, middle, forward_path
        
        // Backward search  
        MATCH backward_path = (middle)-[*1..%d]-(end)
        WHERE length(forward_path) + length(backward_path) <= $max_depth
        
        // Combine paths
        WITH nodes(forward_path) + tail(nodes(backward_path)) as combined_nodes,
             relationships(forward_path) + relationships(backward_path) as combined_rels
        
        RETURN combined_nodes as path_nodes, combined_rels as path_rels,
               size(combined_nodes) - 1 as path_length,
               reduce(weight = 0, r in combined_rels | weight + coalesce(r.weight, 1.0)) as total_weight
        ORDER BY path_length ASC, total_weight ASC
        LIMIT $max_results
        """ % (
            self._get_node_id_field(start_node_id),
            self._get_node_id_field(target_node_id),
            constraints.max_depth // 2 + 1,
            constraints.max_depth // 2 + 1
        )
        
        return self._execute_traversal_query(query, start_node_id, target_node_id, constraints)
    
    def _pattern_matching_traversal(self,
                                   start_node_id: str,
                                   constraints: TraversalConstraints,
                                   pattern: Optional[PathPattern] = None) -> List[TraversalPath]:
        """Pattern-based traversal for specific graph motifs."""
        if not pattern:
            return self._breadth_first_traversal(start_node_id, constraints, None)
        
        # Build pattern-specific query
        if pattern.pattern_type == 'linear':
            return self._linear_pattern_query(start_node_id, constraints, pattern)
        elif pattern.pattern_type == 'star':
            return self._star_pattern_query(start_node_id, constraints, pattern)
        elif pattern.pattern_type == 'cycle':
            return self._cycle_pattern_query(start_node_id, constraints, pattern)
        
        return []
    
    def _linear_pattern_query(self,
                             start_node_id: str,
                             constraints: TraversalConstraints,
                             pattern: PathPattern) -> List[TraversalPath]:
        """Execute linear pattern matching query."""
        # Build pattern match based on node and edge patterns
        pattern_parts = []
        
        for i, node_pattern in enumerate(pattern.node_patterns):
            if i == 0:
                pattern_parts.append(f"(n{i}:{node_pattern.get('type', '')})")
            else:
                edge_pattern = pattern.edge_patterns[i-1] if i-1 < len(pattern.edge_patterns) else {}
                edge_type = edge_pattern.get('type', '')
                pattern_parts.append(f"-[r{i-1}:{edge_type}]-(n{i}:{node_pattern.get('type', '')})")
        
        pattern_match = "".join(pattern_parts)
        
        query = f"""
        MATCH path = {pattern_match}
        WHERE n0.{self._get_node_id_field(start_node_id)} = $start_id
        WITH path, nodes(path) as path_nodes, relationships(path) as path_rels,
             length(path) as path_length
        WHERE path_length >= {pattern.min_length} AND path_length <= {pattern.max_length}
        RETURN path_nodes, path_rels, path_length,
               reduce(weight = 0, r in path_rels | weight + coalesce(r.weight, 1.0)) as total_weight
        ORDER BY total_weight DESC
        LIMIT $max_results
        """
        
        return self._execute_traversal_query(query, start_node_id, None, constraints)
    
    def _star_pattern_query(self,
                           start_node_id: str,
                           constraints: TraversalConstraints,
                           pattern: PathPattern) -> List[TraversalPath]:
        """Execute star pattern matching query."""
        query = """
        MATCH (center)-[r*1..2]-(leaf)
        WHERE center.%s = $start_id
        WITH center, collect(DISTINCT leaf) as leaves, collect(r) as all_rels
        WHERE size(leaves) >= 3  // Minimum for star pattern
        
        // Create star paths
        UNWIND leaves as leaf
        MATCH star_path = (center)-[*1..2]-(leaf)
        WITH center, leaf, star_path, nodes(star_path) as path_nodes, 
             relationships(star_path) as path_rels, length(star_path) as path_length
        
        RETURN path_nodes, path_rels, path_length,
               reduce(weight = 0, r in path_rels | weight + coalesce(r.weight, 1.0)) as total_weight
        ORDER BY total_weight DESC
        LIMIT $max_results
        """ % self._get_node_id_field(start_node_id)
        
        return self._execute_traversal_query(query, start_node_id, None, constraints)
    
    def _cycle_pattern_query(self,
                            start_node_id: str,
                            constraints: TraversalConstraints,
                            pattern: PathPattern) -> List[TraversalPath]:
        """Execute cycle pattern matching query."""
        query = """
        MATCH cycle_path = (start)-[*%d..%d]-(start)
        WHERE start.%s = $start_id
        WITH cycle_path, nodes(cycle_path) as path_nodes, relationships(cycle_path) as path_rels,
             length(cycle_path) as path_length
        WHERE path_length >= %d
        RETURN path_nodes, path_rels, path_length,
               reduce(weight = 0, r in path_rels | weight + coalesce(r.weight, 1.0)) as total_weight
        ORDER BY path_length ASC, total_weight DESC
        LIMIT $max_results
        """ % (
            pattern.min_length, pattern.max_length,
            self._get_node_id_field(start_node_id),
            pattern.min_length
        )
        
        return self._execute_traversal_query(query, start_node_id, None, constraints)
    
    def _execute_traversal_query(self,
                                query: str,
                                start_node_id: str,
                                target_node_id: Optional[str],
                                constraints: TraversalConstraints) -> List[TraversalPath]:
        """Execute traversal query and convert results."""
        try:
            with self.neo4j_db.session() as session:
                params = {
                    'start_id': start_node_id,
                    'max_depth': constraints.max_depth,
                    'max_results': constraints.max_results
                }
                
                if target_node_id:
                    params['target_id'] = target_node_id

                query_payload: Any = query
                timeout_ms = constraints.query_timeout_ms
                if (
                    Neo4jQuery is not None
                    and isinstance(timeout_ms, int)
                    and timeout_ms > 0
                ):
                    query_payload = Neo4jQuery(
                        query,
                        timeout=max(0.001, float(timeout_ms) / 1000.0),
                    )

                result = session.run(query_payload, **params)
                paths = []
                
                for record in result:
                    path_nodes = [dict(node) for node in record['path_nodes']]
                    path_rels = [dict(rel) for rel in record['path_rels']]
                    
                    path = TraversalPath(
                        nodes=path_nodes,
                        edges=path_rels,
                        total_weight=record['total_weight'],
                        path_length=record['path_length'],
                        start_node_id=start_node_id,
                        end_node_id=path_nodes[-1].get('concept_id', path_nodes[-1].get('id', ''))
                    )
                    
                    # Calculate semantic coherence if possible
                    path.semantic_coherence = self._calculate_semantic_coherence(path)
                    
                    paths.append(path)
                
                return paths
                
        except Exception as e:
            logger.error(f"Traversal query execution failed: {e}")
            return []
    
    def _calculate_semantic_coherence(self, path: TraversalPath) -> float:
        """Calculate semantic coherence score for a path."""
        # Simplified semantic coherence based on node types and edge types
        coherence_score = 1.0
        
        # Penalize type switches
        for i in range(1, len(path.nodes)):
            prev_node = path.nodes[i-1]
            curr_node = path.nodes[i]
            
            prev_labels = prev_node.get('labels', [])
            curr_labels = curr_node.get('labels', [])
            
            if not any(label in curr_labels for label in prev_labels):
                coherence_score *= 0.9  # Penalty for type change
        
        # Boost score for consistent edge types
        edge_types = [edge.get('type', '') for edge in path.edges]
        unique_edge_types = set(edge_types)
        
        if len(unique_edge_types) == 1:
            coherence_score *= 1.2  # Boost for consistent relationships
        elif len(unique_edge_types) <= 2:
            coherence_score *= 1.1  # Small boost for few relationship types
        
        return min(coherence_score, 1.0)
    
    def find_connection_paths(self,
                             source_ids: List[str],
                             target_ids: List[str],
                             constraints: Optional[TraversalConstraints] = None) -> Dict[str, List[TraversalPath]]:
        """Find connection paths between sets of nodes.
        
        Args:
            source_ids: Source node IDs
            target_ids: Target node IDs  
            constraints: Traversal constraints
            
        Returns:
            Dictionary mapping source_id -> target_id -> paths
        """
        if constraints is None:
            constraints = TraversalConstraints(max_depth=4)
        
        connection_paths = {}
        
        for source_id in source_ids:
            connection_paths[source_id] = {}
            
            for target_id in target_ids:
                if source_id == target_id:
                    continue
                
                # Find paths between source and target
                result = self.traverse_from_node(
                    start_node_id=source_id,
                    constraints=constraints,
                    mode=TraversalMode.SHORTEST_PATH,
                    target_node_id=target_id
                )
                
                connection_paths[source_id][target_id] = result.paths
        
        return connection_paths
    
    def discover_subgraphs(self,
                          seed_nodes: List[str],
                          constraints: Optional[TraversalConstraints] = None,
                          min_subgraph_size: int = 5) -> List[Dict[str, Any]]:
        """Discover connected subgraphs around seed nodes.
        
        Args:
            seed_nodes: Seed node IDs
            constraints: Traversal constraints
            min_subgraph_size: Minimum nodes in subgraph
            
        Returns:
            List of discovered subgraphs
        """
        if constraints is None:
            constraints = TraversalConstraints(max_depth=3)
        
        subgraphs = []
        
        for seed_node in seed_nodes:
            # Discover local neighborhood
            result = self.traverse_from_node(
                start_node_id=seed_node,
                constraints=constraints,
                mode=TraversalMode.BREADTH_FIRST
            )
            
            # Extract unique nodes and edges
            all_nodes = {}
            all_edges = []
            
            for path in result.paths:
                for node in path.nodes:
                    node_id = node.get('concept_id', node.get('id', ''))
                    all_nodes[node_id] = node
                
                all_edges.extend(path.edges)
            
            # Filter subgraphs by size
            if len(all_nodes) >= min_subgraph_size:
                subgraph = {
                    'seed_node': seed_node,
                    'nodes': list(all_nodes.values()),
                    'edges': all_edges,
                    'size': len(all_nodes),
                    'density': len(all_edges) / max(1, len(all_nodes) * (len(all_nodes) - 1) / 2)
                }
                subgraphs.append(subgraph)
        
        # Sort by size and density
        subgraphs.sort(key=lambda x: (x['size'], x['density']), reverse=True)
        
        return subgraphs
    
    def _get_node_id_field(self, node_id: str) -> str:
        """Get the appropriate node ID field name."""
        # Simple heuristic based on ID format
        if node_id.startswith('C'):
            return 'concept_id'
        elif node_id.startswith('T'):
            return 'task_id'
        elif node_id.startswith('R'):
            return 'region_id'
        else:
            return 'id'
    
    def _build_target_filter(self, target_node_id: Optional[str], path_var: str = "end") -> str:
        """Build target node filter for query."""
        if not target_node_id:
            return ""
        
        field = self._get_node_id_field(target_node_id)
        if path_var == "path":
            return f"WHERE endNode(path).{field} = $target_id"
        else:
            return f"AND {path_var}.{field} = $target_id"
    
    def _build_path_filters(self, constraints: TraversalConstraints) -> str:
        """Build path filtering conditions."""
        filters = []
        
        if constraints.min_edge_weight is not None:
            filters.append(f"ALL(r IN path_rels WHERE coalesce(r.weight, 1.0) >= {constraints.min_edge_weight})")
        
        if constraints.allowed_edge_types:
            edge_types = "', '".join(constraints.allowed_edge_types)
            filters.append(f"ALL(r IN path_rels WHERE type(r) IN ['{edge_types}'])")
        
        if constraints.forbidden_edge_types:
            edge_types = "', '".join(constraints.forbidden_edge_types)
            filters.append(f"NONE(r IN path_rels WHERE type(r) IN ['{edge_types}'])")
        
        return "AND " + " AND ".join(filters) if filters else ""
    
    def _build_relationship_filter(self, constraints: TraversalConstraints) -> str:
        """Build relationship filter for APOC queries."""
        if constraints.allowed_edge_types:
            return "|".join(constraints.allowed_edge_types)
        elif constraints.forbidden_edge_types:
            return f">{('|'.join(constraints.forbidden_edge_types))}"
        else:
            return ""
    
    def _build_label_filter(self, constraints: TraversalConstraints) -> str:
        """Build node label filter for APOC queries."""
        if constraints.node_filters:
            # Simple implementation - would be more sophisticated in production
            return ""
        return ""
    
    def _generate_cache_key(self, *args) -> str:
        """Generate cache key for query."""
        import hashlib
        key_data = json.dumps([str(arg) for arg in args], sort_keys=True)
        return hashlib.md5(key_data.encode()).hexdigest()
    
    def _get_cached_result(self, cache_key: str) -> Optional[TraversalResult]:
        """Get cached traversal result."""
        if cache_key in self.query_cache:
            cached_data, timestamp = self.query_cache[cache_key]
            if time.time() - timestamp < self.cache_ttl:
                return cached_data
            else:
                del self.query_cache[cache_key]
        return None
    
    def _cache_result(self, cache_key: str, result: TraversalResult):
        """Cache traversal result."""
        self.query_cache[cache_key] = (result, time.time())
    
    def _generate_traversal_statistics(self, paths: List[TraversalPath], execution_time_ms: float) -> Dict[str, Any]:
        """Generate statistics for traversal result."""
        if not paths:
            return {}
        
        path_lengths = [path.path_length for path in paths]
        total_weights = [path.total_weight for path in paths]
        
        return {
            'min_path_length': min(path_lengths),
            'max_path_length': max(path_lengths),
            'avg_path_length': sum(path_lengths) / len(path_lengths),
            'min_path_weight': min(total_weights),
            'max_path_weight': max(total_weights),
            'avg_path_weight': sum(total_weights) / len(total_weights),
            'unique_nodes': len(set(
                node.get('concept_id', node.get('id', ''))
                for path in paths for node in path.nodes
            )),
            'unique_edges': len(set(
                edge.get('id', f"{edge.get('start')}-{edge.get('end')}")
                for path in paths for edge in path.edges
            ))
        }
    
    def _update_performance_stats(self, execution_time_ms: float, path_count: int):
        """Update performance statistics."""
        total_queries = self.query_stats['total_queries']
        
        # Update rolling averages
        current_avg_time = self.query_stats['avg_execution_time_ms']
        self.query_stats['avg_execution_time_ms'] = (
            (current_avg_time * (total_queries - 1) + execution_time_ms) / total_queries
        )
        
        current_avg_paths = self.query_stats['paths_per_query']
        self.query_stats['paths_per_query'] = (
            (current_avg_paths * (total_queries - 1) + path_count) / total_queries
        )
    
    def get_query_statistics(self) -> Dict[str, Any]:
        """Get comprehensive query statistics."""
        return {
            **self.query_stats,
            'cache_size': len(self.query_cache),
            'cache_hit_rate': (
                self.query_stats['cache_hits'] / max(1, self.query_stats['total_queries'])
            ),
            'common_patterns_available': list(self.common_patterns.keys())
        }
