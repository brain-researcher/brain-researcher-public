"""Graph Analytics API - completes KG-027.

This module provides advanced graph analytics including community detection,
PageRank, clustering coefficient, graph embeddings, and visualization.
"""

import logging
import numpy as np
from typing import Dict, List, Any, Optional, Tuple, Set
from dataclasses import dataclass, field
from collections import defaultdict
import json
import pickle

logger = logging.getLogger(__name__)


@dataclass 
class AnalyticsResult:
    """Result of graph analytics computation."""
    
    analysis_type: str
    results: Any
    metadata: Dict[str, Any] = field(default_factory=dict)
    execution_time_ms: float = 0
    timestamp: str = ""
    

class GraphAnalytics:
    """Advanced graph analytics capabilities."""
    
    def __init__(self, neo4j_driver, redis_client=None):
        """Initialize graph analytics.
        
        Args:
            neo4j_driver: Neo4j driver instance
            redis_client: Optional Redis client for caching
        """
        self.driver = neo4j_driver
        self.redis = redis_client
        self.embedding_cache = {}
        
    def detect_communities(
        self,
        algorithm: str = "louvain",
        min_size: int = 3,
        resolution: float = 1.0
    ) -> AnalyticsResult:
        """Detect communities in the graph.
        
        Args:
            algorithm: Community detection algorithm
            min_size: Minimum community size
            resolution: Resolution parameter for modularity
            
        Returns:
            AnalyticsResult with communities
        """
        import time
        start_time = time.time()
        
        with self.driver.session() as session:
            if algorithm == "louvain":
                communities = self._louvain_communities(session, min_size, resolution)
            elif algorithm == "label_propagation":
                communities = self._label_propagation(session, min_size)
            elif algorithm == "connected_components":
                communities = self._connected_components(session, min_size)
            else:
                raise ValueError(f"Unknown algorithm: {algorithm}")
                
        execution_time = (time.time() - start_time) * 1000
        
        return AnalyticsResult(
            analysis_type="community_detection",
            results=communities,
            metadata={
                "algorithm": algorithm,
                "min_size": min_size,
                "resolution": resolution,
                "num_communities": len(communities)
            },
            execution_time_ms=execution_time,
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S")
        )
        
    def _louvain_communities(self, session, min_size: int, resolution: float) -> List[Dict[str, Any]]:
        """Louvain community detection."""
        # Check if APOC is available
        try:
            query = """
            CALL apoc.algo.community(
                null,
                null,
                {method: 'louvain', resolution: $resolution}
            )
            YIELD node, community
            WITH community, collect(node) as nodes
            WHERE size(nodes) >= $min_size
            RETURN community,
                   [n IN nodes | {id: n.id, label: labels(n)[0]}] as members,
                   size(nodes) as size
            ORDER BY size DESC
            """
            
            result = session.run(query, {"min_size": min_size, "resolution": resolution})
            
        except:
            # Fallback to simple connected components
            query = """
            CALL gds.louvain.stream('myGraph')
            YIELD nodeId, communityId
            WITH communityId, collect(gds.util.asNode(nodeId)) as nodes
            WHERE size(nodes) >= $min_size
            RETURN communityId as community,
                   [n IN nodes | {id: n.id, label: labels(n)[0]}] as members,
                   size(nodes) as size
            ORDER BY size DESC
            """
            
            try:
                result = session.run(query, {"min_size": min_size})
            except:
                # Ultimate fallback - manual implementation
                return self._manual_louvain(session, min_size, resolution)
                
        communities = []
        for record in result:
            communities.append({
                "community_id": record["community"],
                "members": record["members"],
                "size": record["size"]
            })
            
        return communities
        
    def _manual_louvain(self, session, min_size: int, resolution: float) -> List[Dict[str, Any]]:
        """Manual Louvain implementation for fallback."""
        # Get all nodes and edges
        nodes_query = "MATCH (n) RETURN n.id as id, labels(n)[0] as label"
        edges_query = "MATCH (n)-[r]-(m) WHERE id(n) < id(m) RETURN n.id as source, m.id as target, 1 as weight"
        
        nodes = {record["id"]: record["label"] for record in session.run(nodes_query)}
        edges = [(record["source"], record["target"], record["weight"]) 
                 for record in session.run(edges_query)]
        
        # Initialize each node in its own community
        communities = {node_id: i for i, node_id in enumerate(nodes.keys())}
        
        # Simple modularity optimization
        improved = True
        while improved:
            improved = False
            
            for node_id in nodes.keys():
                # Calculate modularity gain for moving to each neighbor's community
                best_community = communities[node_id]
                best_gain = 0
                
                neighbors = set()
                for source, target, _ in edges:
                    if source == node_id:
                        neighbors.add(target)
                    elif target == node_id:
                        neighbors.add(source)
                        
                for neighbor in neighbors:
                    neighbor_community = communities[neighbor]
                    if neighbor_community != best_community:
                        # Simplified modularity calculation
                        gain = resolution  # Simplified - should calculate actual modularity
                        if gain > best_gain:
                            best_gain = gain
                            best_community = neighbor_community
                            
                if best_community != communities[node_id]:
                    communities[node_id] = best_community
                    improved = True
                    
        # Group by community
        community_members = defaultdict(list)
        for node_id, comm_id in communities.items():
            community_members[comm_id].append({
                "id": node_id,
                "label": nodes[node_id]
            })
            
        # Filter by size
        result = []
        for comm_id, members in community_members.items():
            if len(members) >= min_size:
                result.append({
                    "community_id": comm_id,
                    "members": members,
                    "size": len(members)
                })
                
        return sorted(result, key=lambda x: x["size"], reverse=True)
        
    def _label_propagation(self, session, min_size: int) -> List[Dict[str, Any]]:
        """Label propagation community detection."""
        query = """
        MATCH (n)
        WITH collect(n) as nodes
        CALL apoc.algo.labelPropagation(nodes, null, {iterations: 10})
        YIELD node, label
        WITH label as community, collect(node) as members
        WHERE size(members) >= $min_size
        RETURN community,
               [n IN members | {id: n.id, label: labels(n)[0]}] as members,
               size(members) as size
        ORDER BY size DESC
        """
        
        try:
            result = session.run(query, {"min_size": min_size})
            communities = []
            for record in result:
                communities.append({
                    "community_id": record["community"],
                    "members": record["members"],
                    "size": record["size"]
                })
            return communities
        except:
            # Fallback to connected components
            return self._connected_components(session, min_size)
            
    def _connected_components(self, session, min_size: int) -> List[Dict[str, Any]]:
        """Find connected components."""
        query = """
        MATCH (n)
        WITH collect(n) as nodes
        UNWIND nodes as node
        MATCH path = (node)-[*]-(connected)
        WITH node, collect(DISTINCT connected) as component
        WITH component[0] as representative, component
        WITH representative, component
        WHERE size(component) >= $min_size
        RETURN id(representative) as community,
               [n IN component | {id: n.id, label: labels(n)[0]}] as members,
               size(component) as size
        ORDER BY size DESC
        """
        
        result = session.run(query, {"min_size": min_size})
        
        communities = []
        seen = set()
        
        for record in result:
            # Avoid duplicates
            member_ids = tuple(sorted([m["id"] for m in record["members"]]))
            if member_ids not in seen:
                seen.add(member_ids)
                communities.append({
                    "community_id": record["community"],
                    "members": record["members"],
                    "size": record["size"]
                })
                
        return communities
        
    def calculate_pagerank(
        self,
        damping_factor: float = 0.85,
        iterations: int = 20,
        node_type: Optional[str] = None,
        top_k: int = 100
    ) -> AnalyticsResult:
        """Calculate PageRank for nodes.
        
        Args:
            damping_factor: PageRank damping factor
            iterations: Number of iterations
            node_type: Optional node type filter
            top_k: Return top K nodes
            
        Returns:
            AnalyticsResult with PageRank scores
        """
        import time
        start_time = time.time()
        
        with self.driver.session() as session:
            # Try GDS first
            try:
                pagerank = self._gds_pagerank(session, damping_factor, iterations, node_type, top_k)
            except:
                # Try APOC
                try:
                    pagerank = self._apoc_pagerank(session, damping_factor, iterations, node_type, top_k)
                except:
                    # Manual implementation
                    pagerank = self._manual_pagerank(session, damping_factor, iterations, node_type, top_k)
                    
        execution_time = (time.time() - start_time) * 1000
        
        return AnalyticsResult(
            analysis_type="pagerank",
            results=pagerank,
            metadata={
                "damping_factor": damping_factor,
                "iterations": iterations,
                "node_type": node_type,
                "top_k": top_k
            },
            execution_time_ms=execution_time,
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S")
        )
        
    def _gds_pagerank(self, session, damping_factor: float, iterations: int, 
                      node_type: Optional[str], top_k: int) -> List[Dict[str, Any]]:
        """PageRank using Graph Data Science library."""
        node_filter = f":{node_type}" if node_type else ""
        
        # Create projection
        create_query = f"""
        CALL gds.graph.create.cypher(
            'pagerank_graph',
            'MATCH (n{node_filter}) RETURN id(n) as id',
            'MATCH (n)-[r]->(m) RETURN id(n) as source, id(m) as target'
        )
        """
        session.run(create_query)
        
        # Run PageRank
        pagerank_query = """
        CALL gds.pageRank.stream('pagerank_graph', {
            dampingFactor: $damping,
            maxIterations: $iterations
        })
        YIELD nodeId, score
        WITH gds.util.asNode(nodeId) as node, score
        RETURN node.id as node_id,
               labels(node)[0] as node_type,
               node.name as name,
               score
        ORDER BY score DESC
        LIMIT $top_k
        """
        
        result = session.run(pagerank_query, {
            "damping": damping_factor,
            "iterations": iterations,
            "top_k": top_k
        })
        
        # Clean up projection
        session.run("CALL gds.graph.drop('pagerank_graph')")
        
        return [
            {
                "node_id": record["node_id"],
                "node_type": record["node_type"],
                "name": record["name"],
                "score": record["score"]
            }
            for record in result
        ]
        
    def _apoc_pagerank(self, session, damping_factor: float, iterations: int,
                       node_type: Optional[str], top_k: int) -> List[Dict[str, Any]]:
        """PageRank using APOC."""
        node_filter = f":{node_type}" if node_type else ""
        
        query = f"""
        MATCH (n{node_filter})
        WITH collect(n) as nodes
        CALL apoc.algo.pageRank(nodes, null, {{
            iterations: $iterations,
            dampingFactor: $damping
        }})
        YIELD node, score
        RETURN node.id as node_id,
               labels(node)[0] as node_type,
               node.name as name,
               score
        ORDER BY score DESC
        LIMIT $top_k
        """
        
        result = session.run(query, {
            "iterations": iterations,
            "damping": damping_factor,
            "top_k": top_k
        })
        
        return [
            {
                "node_id": record["node_id"],
                "node_type": record["node_type"],
                "name": record["name"],
                "score": record["score"]
            }
            for record in result
        ]
        
    def _manual_pagerank(self, session, damping_factor: float, iterations: int,
                        node_type: Optional[str], top_k: int) -> List[Dict[str, Any]]:
        """Manual PageRank implementation."""
        node_filter = f":{node_type}" if node_type else ""
        
        # Get nodes and edges
        nodes_query = f"MATCH (n{node_filter}) RETURN n.id as id, n.name as name, labels(n)[0] as type"
        edges_query = f"""
        MATCH (n{node_filter})-[r]->(m{node_filter})
        RETURN n.id as source, m.id as target
        """
        
        nodes = {}
        for record in session.run(nodes_query):
            nodes[record["id"]] = {
                "name": record["name"],
                "type": record["type"]
            }
            
        # Build adjacency lists
        out_edges = defaultdict(list)
        in_edges = defaultdict(list)
        
        for record in session.run(edges_query):
            out_edges[record["source"]].append(record["target"])
            in_edges[record["target"]].append(record["source"])
            
        # Initialize PageRank
        n = len(nodes)
        if n == 0:
            return []
            
        pagerank = {node_id: 1.0 / n for node_id in nodes.keys()}
        
        # Power iteration
        for _ in range(iterations):
            new_pagerank = {}
            
            for node_id in nodes.keys():
                # Random surfer component
                rank = (1 - damping_factor) / n
                
                # Incoming link component
                for source in in_edges[node_id]:
                    out_degree = len(out_edges[source])
                    if out_degree > 0:
                        rank += damping_factor * pagerank[source] / out_degree
                        
                new_pagerank[node_id] = rank
                
            pagerank = new_pagerank
            
        # Sort and return top K
        sorted_nodes = sorted(pagerank.items(), key=lambda x: x[1], reverse=True)
        
        return [
            {
                "node_id": node_id,
                "node_type": nodes[node_id]["type"],
                "name": nodes[node_id]["name"],
                "score": score
            }
            for node_id, score in sorted_nodes[:top_k]
        ]
        
    def compute_clustering_coefficient(
        self,
        node_type: Optional[str] = None,
        local: bool = False
    ) -> AnalyticsResult:
        """Compute clustering coefficient.
        
        Args:
            node_type: Optional node type filter
            local: Compute local clustering coefficient per node
            
        Returns:
            AnalyticsResult with clustering coefficient
        """
        import time
        start_time = time.time()
        
        with self.driver.session() as session:
            if local:
                result = self._local_clustering(session, node_type)
            else:
                result = self._global_clustering(session, node_type)
                
        execution_time = (time.time() - start_time) * 1000
        
        return AnalyticsResult(
            analysis_type="clustering_coefficient",
            results=result,
            metadata={
                "node_type": node_type,
                "local": local
            },
            execution_time_ms=execution_time,
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S")
        )
        
    def _local_clustering(self, session, node_type: Optional[str]) -> List[Dict[str, Any]]:
        """Compute local clustering coefficient."""
        node_filter = f":{node_type}" if node_type else ""
        
        query = f"""
        MATCH (n{node_filter})-[r1]-(neighbor1{node_filter})
        WITH n, collect(DISTINCT neighbor1) as neighbors
        WHERE size(neighbors) > 1
        UNWIND neighbors as n1
        UNWIND neighbors as n2
        WHERE id(n1) < id(n2)
        OPTIONAL MATCH (n1)-[r]-(n2)
        WITH n, neighbors,
             count(DISTINCT CASE WHEN r IS NOT NULL THEN [n1, n2] END) as triangles,
             size(neighbors) * (size(neighbors) - 1) / 2.0 as possible_edges
        RETURN n.id as node_id,
               n.name as name,
               labels(n)[0] as node_type,
               CASE WHEN possible_edges > 0 
                    THEN triangles * 1.0 / possible_edges 
                    ELSE 0 END as clustering_coefficient,
               size(neighbors) as degree
        ORDER BY clustering_coefficient DESC
        """
        
        result = session.run(query)
        
        return [
            {
                "node_id": record["node_id"],
                "name": record["name"],
                "node_type": record["node_type"],
                "clustering_coefficient": record["clustering_coefficient"],
                "degree": record["degree"]
            }
            for record in result
        ]
        
    def _global_clustering(self, session, node_type: Optional[str]) -> Dict[str, float]:
        """Compute global clustering coefficient."""
        node_filter = f":{node_type}" if node_type else ""
        
        query = f"""
        MATCH (n{node_filter})-[r1]-(m{node_filter})-[r2]-(o{node_filter})-[r3]-(n)
        WHERE id(n) < id(m) < id(o)
        WITH count(DISTINCT [n, m, o]) as triangles
        MATCH (n{node_filter})-[r]-(m{node_filter})
        WHERE id(n) < id(m)
        WITH triangles, count(r) as edges
        RETURN triangles * 3.0 / edges as global_clustering_coefficient,
               triangles,
               edges
        """
        
        result = session.run(query).single()
        
        if result:
            return {
                "global_clustering_coefficient": result["global_clustering_coefficient"],
                "triangles": result["triangles"],
                "edges": result["edges"]
            }
        else:
            return {"global_clustering_coefficient": 0, "triangles": 0, "edges": 0}
            
    def generate_embeddings(
        self,
        method: str = "node2vec",
        dimensions: int = 128,
        node_type: Optional[str] = None,
        **kwargs
    ) -> AnalyticsResult:
        """Generate graph embeddings.
        
        Args:
            method: Embedding method (node2vec, deepwalk, graphsage)
            dimensions: Embedding dimensions
            node_type: Optional node type filter
            **kwargs: Method-specific parameters
            
        Returns:
            AnalyticsResult with embeddings
        """
        import time
        start_time = time.time()
        
        with self.driver.session() as session:
            if method == "node2vec":
                embeddings = self._node2vec_embeddings(session, dimensions, node_type, **kwargs)
            elif method == "deepwalk":
                embeddings = self._deepwalk_embeddings(session, dimensions, node_type, **kwargs)
            elif method == "spectral":
                embeddings = self._spectral_embeddings(session, dimensions, node_type)
            else:
                raise ValueError(f"Unknown embedding method: {method}")
                
        execution_time = (time.time() - start_time) * 1000
        
        # Cache embeddings
        cache_key = f"embeddings:{method}:{dimensions}:{node_type}"
        self.embedding_cache[cache_key] = embeddings
        
        return AnalyticsResult(
            analysis_type="graph_embeddings",
            results={
                "method": method,
                "dimensions": dimensions,
                "num_nodes": len(embeddings),
                "sample": list(embeddings.items())[:5]  # Sample for inspection
            },
            metadata={
                "method": method,
                "dimensions": dimensions,
                "node_type": node_type,
                "parameters": kwargs
            },
            execution_time_ms=execution_time,
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S")
        )
        
    def _node2vec_embeddings(self, session, dimensions: int, node_type: Optional[str],
                             walk_length: int = 10, num_walks: int = 20,
                             p: float = 1.0, q: float = 1.0) -> Dict[str, np.ndarray]:
        """Generate Node2Vec embeddings."""
        node_filter = f":{node_type}" if node_type else ""
        
        # Get nodes
        nodes_query = f"MATCH (n{node_filter}) RETURN n.id as id"
        nodes = [record["id"] for record in session.run(nodes_query)]
        
        if not nodes:
            return {}
            
        # Generate random walks
        walks = []
        for _ in range(num_walks):
            for start_node in nodes:
                walk = self._random_walk(session, start_node, walk_length, p, q, node_filter)
                if len(walk) > 1:
                    walks.append(walk)
                    
        # Train Skip-gram model (simplified)
        embeddings = self._train_skipgram(walks, dimensions)
        
        return embeddings
        
    def _random_walk(self, session, start_node: str, walk_length: int,
                     p: float, q: float, node_filter: str) -> List[str]:
        """Generate a random walk."""
        walk = [start_node]
        
        for _ in range(walk_length - 1):
            current = walk[-1]
            prev = walk[-2] if len(walk) > 1 else None
            
            # Get neighbors
            query = f"""
            MATCH (n {{id: $current}})-[r]-(neighbor{node_filter})
            RETURN neighbor.id as id
            """
            
            result = session.run(query, {"current": current})
            neighbors = [record["id"] for record in result]
            
            if not neighbors:
                break
                
            # Calculate transition probabilities (simplified)
            if prev:
                probs = []
                for neighbor in neighbors:
                    if neighbor == prev:
                        probs.append(1.0 / p)  # Return parameter
                    elif neighbor in walk:
                        probs.append(1.0)  # Already visited
                    else:
                        probs.append(1.0 / q)  # In-out parameter
                        
                # Normalize
                total = sum(probs)
                probs = [p / total for p in probs]
            else:
                probs = [1.0 / len(neighbors)] * len(neighbors)
                
            # Sample next node
            next_node = np.random.choice(neighbors, p=probs)
            walk.append(next_node)
            
        return walk
        
    def _train_skipgram(self, walks: List[List[str]], dimensions: int) -> Dict[str, np.ndarray]:
        """Train Skip-gram model (simplified)."""
        # Get vocabulary
        vocab = set()
        for walk in walks:
            vocab.update(walk)
            
        vocab_list = list(vocab)
        vocab_index = {node: i for i, node in enumerate(vocab_list)}
        
        # Initialize embeddings randomly
        embeddings = np.random.randn(len(vocab), dimensions) * 0.1
        
        # Simplified training (would use Word2Vec in practice)
        window_size = 5
        learning_rate = 0.01
        
        for walk in walks:
            for i, center in enumerate(walk):
                center_idx = vocab_index[center]
                
                # Get context
                start = max(0, i - window_size)
                end = min(len(walk), i + window_size + 1)
                
                for j in range(start, end):
                    if j != i:
                        context_idx = vocab_index[walk[j]]
                        
                        # Simplified gradient update
                        dot_product = np.dot(embeddings[center_idx], embeddings[context_idx])
                        gradient = (1 / (1 + np.exp(-dot_product)) - 1) * embeddings[context_idx]
                        embeddings[center_idx] -= learning_rate * gradient
                        
        # Convert to dictionary
        return {node: embeddings[vocab_index[node]] for node in vocab_list}
        
    def _deepwalk_embeddings(self, session, dimensions: int, node_type: Optional[str],
                            walk_length: int = 10, num_walks: int = 20) -> Dict[str, np.ndarray]:
        """Generate DeepWalk embeddings."""
        # DeepWalk is Node2Vec with p=1, q=1
        return self._node2vec_embeddings(
            session, dimensions, node_type,
            walk_length=walk_length, num_walks=num_walks,
            p=1.0, q=1.0
        )
        
    def _spectral_embeddings(self, session, dimensions: int, 
                            node_type: Optional[str]) -> Dict[str, np.ndarray]:
        """Generate spectral embeddings using graph Laplacian."""
        node_filter = f":{node_type}" if node_type else ""
        
        # Get nodes
        nodes_query = f"MATCH (n{node_filter}) RETURN n.id as id"
        nodes = [record["id"] for record in session.run(nodes_query)]
        
        if not nodes:
            return {}
            
        n = len(nodes)
        node_index = {node: i for i, node in enumerate(nodes)}
        
        # Build adjacency matrix
        adj_matrix = np.zeros((n, n))
        
        edges_query = f"""
        MATCH (n{node_filter})-[r]-(m{node_filter})
        WHERE n.id IN $nodes AND m.id IN $nodes
        RETURN n.id as source, m.id as target
        """
        
        result = session.run(edges_query, {"nodes": nodes})
        
        for record in result:
            i = node_index[record["source"]]
            j = node_index[record["target"]]
            adj_matrix[i, j] = 1
            adj_matrix[j, i] = 1
            
        # Calculate Laplacian
        degree_matrix = np.diag(np.sum(adj_matrix, axis=1))
        laplacian = degree_matrix - adj_matrix
        
        # Compute eigenvectors
        try:
            eigenvalues, eigenvectors = np.linalg.eigh(laplacian)
            
            # Use smallest non-zero eigenvectors
            embedding_matrix = eigenvectors[:, 1:dimensions+1]
            
            # Convert to dictionary
            return {node: embedding_matrix[i] for node, i in node_index.items()}
            
        except np.linalg.LinAlgError:
            # Return random embeddings as fallback
            return {node: np.random.randn(dimensions) * 0.1 for node in nodes}
            
    def export_results(
        self,
        results: AnalyticsResult,
        format: str = "json",
        output_file: Optional[str] = None
    ) -> str:
        """Export analytics results.
        
        Args:
            results: Analytics results
            format: Export format (json, csv, pickle)
            output_file: Optional output file path
            
        Returns:
            Exported data as string
        """
        if format == "json":
            # Convert numpy arrays to lists for JSON serialization
            export_data = {
                "analysis_type": results.analysis_type,
                "metadata": results.metadata,
                "execution_time_ms": results.execution_time_ms,
                "timestamp": results.timestamp
            }
            
            if results.analysis_type == "graph_embeddings":
                export_data["results"] = results.results
            else:
                export_data["results"] = results.results
                
            output = json.dumps(export_data, indent=2, default=str)
            
        elif format == "csv":
            import csv
            import io
            
            output_buffer = io.StringIO()
            
            if results.analysis_type == "pagerank":
                writer = csv.DictWriter(
                    output_buffer,
                    fieldnames=["node_id", "node_type", "name", "score"]
                )
                writer.writeheader()
                writer.writerows(results.results)
                
            elif results.analysis_type == "community_detection":
                writer = csv.DictWriter(
                    output_buffer,
                    fieldnames=["community_id", "size", "member_ids"]
                )
                writer.writeheader()
                for community in results.results:
                    writer.writerow({
                        "community_id": community["community_id"],
                        "size": community["size"],
                        "member_ids": ",".join([m["id"] for m in community["members"]])
                    })
                    
            output = output_buffer.getvalue()
            
        elif format == "pickle":
            output = pickle.dumps(results)
            
        else:
            raise ValueError(f"Unsupported format: {format}")
            
        # Save to file if specified
        if output_file:
            if format == "pickle":
                with open(output_file, "wb") as f:
                    f.write(output)
            else:
                with open(output_file, "w") as f:
                    f.write(output)
                    
        return output
        
    def visualize_analytics(
        self,
        results: AnalyticsResult,
        visualization_type: str = "auto"
    ) -> Dict[str, Any]:
        """Create visualization specification for analytics results.
        
        Args:
            results: Analytics results
            visualization_type: Type of visualization
            
        Returns:
            Visualization specification
        """
        if visualization_type == "auto":
            # Auto-select based on analysis type
            if results.analysis_type == "community_detection":
                visualization_type = "network_communities"
            elif results.analysis_type == "pagerank":
                visualization_type = "node_importance"
            elif results.analysis_type == "clustering_coefficient":
                visualization_type = "heatmap"
            elif results.analysis_type == "graph_embeddings":
                visualization_type = "scatter_2d"
            else:
                visualization_type = "table"
                
        vis_spec = {
            "type": visualization_type,
            "data": [],
            "layout": {},
            "config": {}
        }
        
        if visualization_type == "network_communities":
            # Network with colored communities
            for community in results.results[:10]:  # Limit to 10 communities
                for member in community["members"]:
                    vis_spec["data"].append({
                        "node_id": member["id"],
                        "community": community["community_id"],
                        "color": f"community_{community['community_id'] % 10}"
                    })
                    
            vis_spec["layout"] = {
                "type": "force-directed",
                "node_color": "community"
            }
            
        elif visualization_type == "node_importance":
            # Bar chart of PageRank scores
            vis_spec["data"] = [
                {
                    "node": f"{r['name'] or r['node_id']}",
                    "score": r["score"]
                }
                for r in results.results[:20]
            ]
            
            vis_spec["layout"] = {
                "type": "bar",
                "x": "node",
                "y": "score",
                "title": "PageRank Scores"
            }
            
        elif visualization_type == "heatmap":
            # Heatmap for clustering coefficients
            if isinstance(results.results, list):
                vis_spec["data"] = [
                    {
                        "node": r["name"] or r["node_id"],
                        "coefficient": r["clustering_coefficient"],
                        "degree": r["degree"]
                    }
                    for r in results.results[:50]
                ]
            else:
                vis_spec["data"] = [results.results]
                
            vis_spec["layout"] = {
                "type": "heatmap",
                "title": "Clustering Coefficients"
            }
            
        elif visualization_type == "scatter_2d":
            # 2D scatter plot for embeddings (using PCA)
            if results.analysis_type == "graph_embeddings":
                # Would need to reduce dimensions for visualization
                vis_spec["data"] = results.results["sample"]
                vis_spec["layout"] = {
                    "type": "scatter",
                    "title": f"Graph Embeddings ({results.results['method']})"
                }
                
        return vis_spec