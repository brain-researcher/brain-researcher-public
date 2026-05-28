"""Cypher query generation for graph traversal."""

from typing import List, Dict, Optional, Any


class TraversalQueryBuilder:
    """Builder for Cypher traversal queries."""
    
    @staticmethod
    def variable_length_path(start_id: str,
                           end_id: str,
                           min_hops: int = 1,
                           max_hops: int = 5,
                           edge_types: Optional[List[str]] = None,
                           limit: int = 10) -> str:
        """Generate Cypher query for variable-length paths.
        
        Args:
            start_id: Start node ID
            end_id: End node ID
            min_hops: Minimum path length
            max_hops: Maximum path length
            edge_types: Filter by edge types
            limit: Maximum paths to return
            
        Returns:
            Cypher query string
        """
        edge_pattern = ""
        if edge_types:
            edge_pattern = f":{('|').join(edge_types)}"
        
        query = f"""
        MATCH p = (start {{id: $start_id}})-[{edge_pattern}*{min_hops}..{max_hops}]->(end {{id: $end_id}})
        RETURN p, length(p) as path_length
        ORDER BY path_length
        LIMIT {limit}
        """
        
        return query.strip()
    
    @staticmethod
    def shortest_path(start_id: str,
                     end_id: str,
                     weighted: bool = False,
                     weight_property: str = "weight") -> str:
        """Generate Cypher query for shortest path.
        
        Args:
            start_id: Start node ID
            end_id: End node ID
            weighted: Use weighted shortest path
            weight_property: Property name for weights
            
        Returns:
            Cypher query string
        """
        if weighted:
            # Use APOC for weighted shortest path
            query = f"""
            MATCH (start {{id: $start_id}}), (end {{id: $end_id}})
            CALL apoc.algo.dijkstra(start, end, '', '{weight_property}')
            YIELD path, weight
            RETURN path, weight
            """
        else:
            query = f"""
            MATCH (start {{id: $start_id}}), (end {{id: $end_id}})
            MATCH p = shortestPath((start)-[*]-(end))
            RETURN p, length(p) as path_length
            """
        
        return query.strip()
    
    @staticmethod
    def all_paths(start_id: str,
                 end_id: str,
                 max_length: int = 5,
                 limit: int = 100) -> str:
        """Generate query for all paths up to max length.
        
        Args:
            start_id: Start node ID
            end_id: End node ID
            max_length: Maximum path length
            limit: Maximum paths to return
            
        Returns:
            Cypher query string
        """
        query = f"""
        MATCH p = (start {{id: $start_id}})-[*1..{max_length}]-(end {{id: $end_id}})
        RETURN p, length(p) as path_length
        ORDER BY path_length
        LIMIT {limit}
        """
        
        return query.strip()
    
    @staticmethod
    def path_with_filters(start_id: str,
                         end_id: str,
                         node_filters: Optional[Dict[str, Any]] = None,
                         edge_filters: Optional[Dict[str, Any]] = None,
                         max_length: int = 5) -> str:
        """Generate query for paths with node/edge filters.
        
        Args:
            start_id: Start node ID
            end_id: End node ID
            node_filters: Filters for intermediate nodes
            edge_filters: Filters for edges
            max_length: Maximum path length
            
        Returns:
            Cypher query string
        """
        where_clauses = []
        
        if node_filters:
            node_conditions = []
            for prop, value in node_filters.items():
                node_conditions.append(f"n.{prop} = '{value}'")
            where_clauses.append(f"all(n IN nodes(p) WHERE {' AND '.join(node_conditions)})")
        
        if edge_filters:
            edge_conditions = []
            for prop, value in edge_filters.items():
                edge_conditions.append(f"r.{prop} = '{value}'")
            where_clauses.append(f"all(r IN relationships(p) WHERE {' AND '.join(edge_conditions)})")
        
        where_clause = ""
        if where_clauses:
            where_clause = f"WHERE {' AND '.join(where_clauses)}"
        
        query = f"""
        MATCH p = (start {{id: $start_id}})-[*1..{max_length}]-(end {{id: $end_id}})
        {where_clause}
        RETURN p, length(p) as path_length
        ORDER BY path_length
        LIMIT 10
        """
        
        return query.strip()
    
    @staticmethod
    def betweenness_centrality(limit: int = 100) -> str:
        """Generate query for betweenness centrality.
        
        Args:
            limit: Number of top nodes to return
            
        Returns:
            Cypher query string
        """
        query = f"""
        CALL algo.betweenness.stream(null, null, {{direction: 'BOTH'}})
        YIELD nodeId, centrality
        RETURN algo.getNodeById(nodeId).id AS node_id, centrality
        ORDER BY centrality DESC
        LIMIT {limit}
        """
        
        return query.strip()
    
    @staticmethod
    def pagerank(iterations: int = 20,
                damping_factor: float = 0.85,
                limit: int = 100) -> str:
        """Generate query for PageRank.
        
        Args:
            iterations: Number of iterations
            damping_factor: Damping factor
            limit: Number of top nodes to return
            
        Returns:
            Cypher query string
        """
        query = f"""
        CALL algo.pageRank.stream(null, null, {{
            iterations: {iterations}, 
            dampingFactor: {damping_factor}
        }})
        YIELD nodeId, score
        RETURN algo.getNodeById(nodeId).id AS node_id, score
        ORDER BY score DESC
        LIMIT {limit}
        """
        
        return query.strip()
    
    @staticmethod
    def connected_components() -> str:
        """Generate query for connected components.
        
        Returns:
            Cypher query string
        """
        query = """
        CALL algo.unionFind.stream(null, null)
        YIELD nodeId, setId
        RETURN setId AS component_id, 
               collect(algo.getNodeById(nodeId).id) AS nodes,
               count(*) AS size
        ORDER BY size DESC
        """
        
        return query.strip()
    
    @staticmethod
    def community_detection() -> str:
        """Generate query for community detection using Louvain.
        
        Returns:
            Cypher query string
        """
        query = """
        CALL algo.louvain.stream(null, null)
        YIELD nodeId, community
        RETURN community, 
               collect(algo.getNodeById(nodeId).id) AS nodes,
               count(*) AS size
        ORDER BY size DESC
        """
        
        return query.strip()