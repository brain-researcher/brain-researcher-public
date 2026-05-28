"""Centrality measures for graph analysis."""

import numpy as np
import networkx as nx
from typing import Dict, Optional
from functools import lru_cache
import time


class CentralityCalculator:
    """Calculator for various centrality measures."""
    
    def __init__(self, cache_ttl: int = 3600):
        """Initialize calculator with caching.
        
        Args:
            cache_ttl: Cache time-to-live in seconds
        """
        self.cache_ttl = cache_ttl
        self._cache = {}
        self._cache_times = {}
    
    def _get_cached(self, key: str) -> Optional[Dict[str, float]]:
        """Get cached result if still valid."""
        if key in self._cache:
            if time.time() - self._cache_times[key] < self.cache_ttl:
                return self._cache[key]
        return None
    
    def _set_cache(self, key: str, value: Dict[str, float]):
        """Cache a result."""
        self._cache[key] = value
        self._cache_times[key] = time.time()
    
    def betweenness(self, 
                   graph: nx.Graph, 
                   normalized: bool = True) -> Dict[str, float]:
        """Calculate betweenness centrality.
        
        Args:
            graph: NetworkX graph
            normalized: Whether to normalize values
            
        Returns:
            Dict mapping nodes to betweenness centrality
        """
        cache_key = f"betweenness_{id(graph)}_{normalized}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached
        
        n = len(graph)
        betweenness = {node: 0.0 for node in graph.nodes()}
        
        for s in graph.nodes():
            # Single source shortest paths
            S = []  # Stack of nodes in order of distance from s
            P = {w: [] for w in graph.nodes()}  # Predecessors
            sigma = {w: 0 for w in graph.nodes()}  # Number of shortest paths
            sigma[s] = 1
            d = {w: -1 for w in graph.nodes()}  # Distance from s
            d[s] = 0
            Q = [s]  # Queue for BFS
            
            while Q:
                v = Q.pop(0)
                S.append(v)
                
                for w in graph.neighbors(v):
                    # First time we reach w?
                    if d[w] < 0:
                        Q.append(w)
                        d[w] = d[v] + 1
                    
                    # Shortest path to w via v?
                    if d[w] == d[v] + 1:
                        sigma[w] += sigma[v]
                        P[w].append(v)
            
            # Accumulation
            delta = {w: 0 for w in graph.nodes()}
            
            while S:
                w = S.pop()
                for v in P[w]:
                    delta[v] += (sigma[v] / sigma[w]) * (1 + delta[w])
                
                if w != s:
                    betweenness[w] += delta[w]
        
        # Normalization
        if normalized and n > 2:
            scale = 1.0 / ((n - 1) * (n - 2))
            for node in betweenness:
                betweenness[node] *= scale
        
        self._set_cache(cache_key, betweenness)
        return betweenness
    
    def pagerank(self, 
                graph: nx.Graph, 
                alpha: float = 0.85, 
                max_iter: int = 100,
                tol: float = 1e-6) -> Dict[str, float]:
        """Calculate PageRank centrality.
        
        Args:
            graph: NetworkX graph
            alpha: Damping parameter
            max_iter: Maximum iterations
            tol: Convergence tolerance
            
        Returns:
            Dict mapping nodes to PageRank values
        """
        cache_key = f"pagerank_{id(graph)}_{alpha}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached
        
        n = len(graph)
        if n == 0:
            return {}
        
        # Initialize PageRank values
        pagerank = {node: 1.0 / n for node in graph.nodes()}
        
        # Power iteration
        for iteration in range(max_iter):
            prev_pagerank = pagerank.copy()
            
            for node in graph.nodes():
                rank_sum = 0
                for neighbor in graph.neighbors(node):
                    rank_sum += prev_pagerank[neighbor] / graph.degree(neighbor)
                
                pagerank[node] = (1 - alpha) / n + alpha * rank_sum
            
            # Check convergence
            err = sum(abs(pagerank[node] - prev_pagerank[node]) 
                     for node in graph.nodes())
            if err < n * tol:
                break
        
        self._set_cache(cache_key, pagerank)
        return pagerank
    
    def eigenvector(self, 
                   graph: nx.Graph, 
                   max_iter: int = 100,
                   tol: float = 1e-6) -> Dict[str, float]:
        """Calculate eigenvector centrality.
        
        Args:
            graph: NetworkX graph
            max_iter: Maximum iterations
            tol: Convergence tolerance
            
        Returns:
            Dict mapping nodes to eigenvector centrality
        """
        cache_key = f"eigenvector_{id(graph)}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached
        
        n = len(graph)
        if n == 0:
            return {}
        
        # Initialize eigenvector
        x = {node: 1.0 for node in graph.nodes()}
        
        # Power iteration
        for iteration in range(max_iter):
            prev_x = x.copy()
            
            # Calculate Ax
            for node in graph.nodes():
                x[node] = sum(prev_x[neighbor] for neighbor in graph.neighbors(node))
            
            # Normalize
            norm = np.sqrt(sum(v * v for v in x.values()))
            if norm == 0:
                return {node: 0.0 for node in graph.nodes()}
            
            for node in x:
                x[node] /= norm
            
            # Check convergence
            err = sum(abs(x[node] - prev_x.get(node, 0)) for node in graph.nodes())
            if err < n * tol:
                break
        
        self._set_cache(cache_key, x)
        return x
    
    def degree_centrality(self, graph: nx.Graph) -> Dict[str, float]:
        """Calculate degree centrality.
        
        Args:
            graph: NetworkX graph
            
        Returns:
            Dict mapping nodes to degree centrality
        """
        n = len(graph)
        if n <= 1:
            return {node: 0.0 for node in graph.nodes()}
        
        scale = 1.0 / (n - 1)
        return {node: graph.degree(node) * scale for node in graph.nodes()}
    
    def closeness_centrality(self, graph: nx.Graph) -> Dict[str, float]:
        """Calculate closeness centrality.
        
        Args:
            graph: NetworkX graph
            
        Returns:
            Dict mapping nodes to closeness centrality
        """
        closeness = {}
        
        for node in graph.nodes():
            # Calculate shortest paths from node
            lengths = nx.single_source_shortest_path_length(graph, node)
            
            if len(lengths) > 1:
                total_distance = sum(lengths.values())
                closeness[node] = (len(lengths) - 1) / total_distance
            else:
                closeness[node] = 0.0
        
        return closeness