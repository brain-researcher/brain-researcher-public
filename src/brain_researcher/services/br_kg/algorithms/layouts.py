"""Graph layout algorithms for visualization."""

import math
import random
from typing import Any, Dict, List, Optional, Tuple

import networkx as nx


class LayoutEngine:
    """Engine for computing graph layouts."""

    def __init__(self, viewport_width: float = 1000, viewport_height: float = 800):
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height

    def force_directed(
        self, graph: nx.Graph, iterations: int = 100, k: Optional[float] = None
    ) -> Dict[str, Tuple[float, float]]:
        """Compute force-directed layout using Fruchterman-Reingold algorithm.

        Args:
            graph: NetworkX graph
            iterations: Number of iterations
            k: Optimal distance between nodes

        Returns:
            Dict mapping node IDs to (x, y) coordinates
        """
        nodes = list(graph.nodes())
        n = len(nodes)
        if n == 0:
            return {}

        # Initialize positions randomly
        pos = {
            node: (
                random.uniform(0, self.viewport_width),
                random.uniform(0, self.viewport_height),
            )
            for node in nodes
        }

        # Optimal distance between nodes
        if k is None:
            area = self.viewport_width * self.viewport_height
            k = math.sqrt(area / n)

        # Temperature for simulated annealing
        temp = min(self.viewport_width, self.viewport_height) / 10

        for iteration in range(iterations):
            # Calculate repulsive forces
            disp = {node: (0.0, 0.0) for node in nodes}

            for i, v in enumerate(nodes):
                for j, u in enumerate(nodes):
                    if i != j:
                        dx = pos[v][0] - pos[u][0]
                        dy = pos[v][1] - pos[u][1]
                        dist = math.sqrt(dx * dx + dy * dy)
                        if dist > 0:
                            # Repulsive force
                            f = k * k / dist
                            disp[v] = (
                                disp[v][0] + dx / dist * f,
                                disp[v][1] + dy / dist * f,
                            )

            # Calculate attractive forces for edges
            for edge in graph.edges():
                v, u = edge
                dx = pos[v][0] - pos[u][0]
                dy = pos[v][1] - pos[u][1]
                dist = math.sqrt(dx * dx + dy * dy)
                if dist > 0:
                    # Attractive force
                    f = dist * dist / k
                    disp[v] = (disp[v][0] - dx / dist * f, disp[v][1] - dy / dist * f)
                    disp[u] = (disp[u][0] + dx / dist * f, disp[u][1] + dy / dist * f)

            # Update positions
            for node in nodes:
                dx, dy = disp[node]
                dist = math.sqrt(dx * dx + dy * dy)
                if dist > 0:
                    # Limit displacement by temperature
                    pos[node] = (
                        pos[node][0] + dx / dist * min(dist, temp),
                        pos[node][1] + dy / dist * min(dist, temp),
                    )

                    # Keep within viewport
                    pos[node] = (
                        max(0, min(self.viewport_width, pos[node][0])),
                        max(0, min(self.viewport_height, pos[node][1])),
                    )

            # Cool down temperature
            temp *= 0.95

        return pos

    def hierarchical(
        self, graph: nx.Graph, root: Optional[str] = None
    ) -> Dict[str, Tuple[float, float]]:
        """Compute hierarchical layout for tree-like structures.

        Args:
            graph: NetworkX graph (should be tree-like)
            root: Root node for hierarchy

        Returns:
            Dict mapping node IDs to (x, y) coordinates
        """
        if len(graph) == 0:
            return {}

        # Convert to directed graph for hierarchy
        if not graph.is_directed():
            digraph = nx.DiGraph()

            # Find root if not specified
            if root is None:
                # Use node with highest degree centrality
                centrality = nx.degree_centrality(graph)
                root = max(centrality, key=centrality.get)

            # BFS to create hierarchy
            visited = set()
            queue = [root]
            while queue:
                node = queue.pop(0)
                if node in visited:
                    continue
                visited.add(node)

                for neighbor in graph.neighbors(node):
                    if neighbor not in visited:
                        digraph.add_edge(node, neighbor)
                        queue.append(neighbor)
        else:
            digraph = graph
            if root is None:
                # Find nodes with no incoming edges
                roots = [n for n in digraph.nodes() if digraph.in_degree(n) == 0]
                root = roots[0] if roots else list(digraph.nodes())[0]

        # Compute levels
        levels = {root: 0}
        queue = [root]
        max_level = 0

        while queue:
            node = queue.pop(0)
            level = levels[node]
            max_level = max(max_level, level)

            for child in digraph.successors(node):
                if child not in levels:
                    levels[child] = level + 1
                    queue.append(child)

        # Count nodes at each level
        level_counts = {}
        for node, level in levels.items():
            level_counts[level] = level_counts.get(level, 0) + 1

        # Assign positions
        level_indices = {level: 0 for level in range(max_level + 1)}
        positions = {}

        for node, level in sorted(levels.items(), key=lambda x: x[1]):
            y = (level + 0.5) * self.viewport_height / (max_level + 1)
            x = (level_indices[level] + 0.5) * self.viewport_width / level_counts[level]
            positions[node] = (x, y)
            level_indices[level] += 1

        return positions

    def circular(
        self, graph: nx.Graph, ordering: str = "degree"
    ) -> Dict[str, Tuple[float, float]]:
        """Compute circular layout.

        Args:
            graph: NetworkX graph
            ordering: Node ordering ('degree', 'random', or 'alphabetical')

        Returns:
            Dict mapping node IDs to (x, y) coordinates
        """
        nodes = list(graph.nodes())
        n = len(nodes)
        if n == 0:
            return {}

        # Order nodes
        if ordering == "degree":
            nodes = sorted(nodes, key=lambda x: graph.degree(x), reverse=True)
        elif ordering == "alphabetical":
            nodes = sorted(nodes)
        else:  # random
            random.shuffle(nodes)

        # Compute circle parameters
        center_x = self.viewport_width / 2
        center_y = self.viewport_height / 2
        radius = min(center_x, center_y) * 0.8

        # Assign positions
        positions = {}
        for i, node in enumerate(nodes):
            angle = 2 * math.pi * i / n
            x = center_x + radius * math.cos(angle)
            y = center_y + radius * math.sin(angle)
            positions[node] = (x, y)

        return positions
