"""Path finding algorithms for graph traversal."""

import heapq
from typing import List, Dict, Optional, Tuple, Set, Any
import networkx as nx


class PathFinder:
    """Algorithms for finding paths in graphs."""
    
    @staticmethod
    def dijkstra(graph: nx.Graph, 
                start: str, 
                end: str, 
                weight: str = 'weight') -> Tuple[List[str], float]:
        """Find shortest path using Dijkstra's algorithm.
        
        Args:
            graph: NetworkX graph
            start: Start node
            end: End node
            weight: Edge weight attribute name
            
        Returns:
            Tuple of (path, total_weight)
        """
        if start not in graph or end not in graph:
            return [], float('inf')
        
        # Priority queue: (distance, node, path)
        pq = [(0, start, [start])]
        visited = set()
        
        while pq:
            dist, node, path = heapq.heappop(pq)
            
            if node in visited:
                continue
            
            visited.add(node)
            
            if node == end:
                return path, dist
            
            for neighbor in graph.neighbors(node):
                if neighbor not in visited:
                    edge_weight = graph[node][neighbor].get(weight, 1)
                    new_dist = dist + edge_weight
                    new_path = path + [neighbor]
                    heapq.heappush(pq, (new_dist, neighbor, new_path))
        
        return [], float('inf')
    
    @staticmethod
    def a_star(graph: nx.Graph, 
              start: str, 
              end: str, 
              heuristic: Optional[Dict[str, float]] = None,
              weight: str = 'weight') -> Tuple[List[str], float]:
        """Find shortest path using A* algorithm.
        
        Args:
            graph: NetworkX graph
            start: Start node
            end: End node
            heuristic: Heuristic function values for each node
            weight: Edge weight attribute name
            
        Returns:
            Tuple of (path, total_weight)
        """
        if start not in graph or end not in graph:
            return [], float('inf')
        
        # Default heuristic (0 for all nodes - reduces to Dijkstra)
        if heuristic is None:
            heuristic = {node: 0 for node in graph.nodes()}
        
        # Priority queue: (f_score, g_score, node, path)
        pq = [(heuristic.get(start, 0), 0, start, [start])]
        visited = set()
        
        while pq:
            f_score, g_score, node, path = heapq.heappop(pq)
            
            if node in visited:
                continue
            
            visited.add(node)
            
            if node == end:
                return path, g_score
            
            for neighbor in graph.neighbors(node):
                if neighbor not in visited:
                    edge_weight = graph[node][neighbor].get(weight, 1)
                    new_g_score = g_score + edge_weight
                    new_f_score = new_g_score + heuristic.get(neighbor, 0)
                    new_path = path + [neighbor]
                    heapq.heappush(pq, (new_f_score, new_g_score, neighbor, new_path))
        
        return [], float('inf')
    
    @staticmethod
    def all_shortest_paths(graph: nx.Graph, 
                          start: str, 
                          end: str,
                          weight: str = 'weight') -> List[List[str]]:
        """Find all shortest paths between two nodes.
        
        Args:
            graph: NetworkX graph
            start: Start node
            end: End node
            weight: Edge weight attribute name
            
        Returns:
            List of all shortest paths
        """
        if start not in graph or end not in graph:
            return []
        
        # First find shortest distance
        _, shortest_dist = PathFinder.dijkstra(graph, start, end, weight)
        
        if shortest_dist == float('inf'):
            return []
        
        # BFS to find all paths with this distance
        paths = []
        queue = [(start, [start], 0)]
        
        while queue:
            node, path, dist = queue.pop(0)
            
            if dist > shortest_dist:
                continue
            
            if node == end and dist == shortest_dist:
                paths.append(path)
                continue
            
            for neighbor in graph.neighbors(node):
                if neighbor not in path:  # Avoid cycles
                    edge_weight = graph[node][neighbor].get(weight, 1)
                    new_dist = dist + edge_weight
                    
                    if new_dist <= shortest_dist:
                        new_path = path + [neighbor]
                        queue.append((neighbor, new_path, new_dist))
        
        return paths
    
    @staticmethod
    def find_paths_with_length(graph: nx.Graph,
                              start: str,
                              end: str,
                              min_length: int = 1,
                              max_length: int = 5,
                              max_paths: int = 10) -> List[List[str]]:
        """Find paths within a specified length range.
        
        Args:
            graph: NetworkX graph
            start: Start node
            end: End node
            min_length: Minimum path length
            max_length: Maximum path length
            max_paths: Maximum number of paths to return
            
        Returns:
            List of paths within the length range
        """
        if start not in graph or end not in graph:
            return []
        
        paths = []
        queue = [(start, [start])]
        
        while queue and len(paths) < max_paths:
            node, path = queue.pop(0)
            
            if len(path) - 1 > max_length:
                continue
            
            if node == end and min_length <= len(path) - 1 <= max_length:
                paths.append(path)
                continue
            
            if len(path) - 1 < max_length:
                for neighbor in graph.neighbors(node):
                    if neighbor not in path:  # Avoid cycles
                        new_path = path + [neighbor]
                        queue.append((neighbor, new_path))
        
        return paths[:max_paths]