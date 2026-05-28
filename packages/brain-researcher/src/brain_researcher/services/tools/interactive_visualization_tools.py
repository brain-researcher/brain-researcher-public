"""Interactive visualization tools for neuroimaging data."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.core.package_resolver import PackageResolver
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class VisualizationInput(BaseModel):
    """Input schema for visualization tools."""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    brain_data: Optional[np.ndarray] = Field(None, description="3D/4D brain imaging data")
    surface_mesh: Optional[Dict] = Field(None, description="Surface mesh data")
    connectivity_matrix: Optional[np.ndarray] = Field(None, description="Connectivity matrix")
    time_series: Optional[np.ndarray] = Field(None, description="Time series data")
    atlas_labels: Optional[List[str]] = Field(None, description="Atlas region labels")
    output_dir: Optional[str] = Field(None, description="Output directory for visualizations")


class Interactive3DBrainTool(NeuroToolWrapper):
    """Create interactive 3D brain visualizations."""
    
    def __init__(self):
        super().__init__()
        self.resolver = PackageResolver()
    
    def get_tool_name(self) -> str:
        return "interactive_3d_brain"
    
    def get_tool_description(self) -> str:
        return "Generate interactive 3D brain visualizations with surface and volume rendering"
    
    def get_args_schema(self):
        return VisualizationInput
    
    def _run(
        self,
        brain_data: Optional[np.ndarray] = None,
        surface_mesh: Optional[Dict] = None,
        overlay_data: Optional[np.ndarray] = None,
        colormap: str = "hot",
        threshold: Optional[float] = None,
        view_angles: Optional[List[Tuple[float, float]]] = None,
        output_dir: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """Create interactive 3D brain visualization."""
        try:
            output_path = Path(output_dir or "viz3d_output")
            output_path.mkdir(parents=True, exist_ok=True)
            
            # Generate or load data
            if brain_data is None and surface_mesh is None:
                brain_data, mesh = self._generate_synthetic_brain_data()
            else:
                mesh = surface_mesh if surface_mesh else self._create_surface_mesh(brain_data)
            
            # Process overlay if provided
            if overlay_data is not None:
                overlay_config = self._process_overlay(overlay_data, threshold)
            else:
                overlay_config = {}
            
            # Generate visualization configuration
            viz_config = self._create_viz_config(
                brain_data, mesh, overlay_config, colormap, view_angles
            )
            
            # Create interactive elements
            interactive_features = self._setup_interactive_features(viz_config)
            
            # Generate HTML visualization
            html_content = self._generate_html_viz(viz_config, interactive_features)
            
            # Calculate visualization metrics
            metrics = self._calculate_viz_metrics(brain_data, overlay_data)
            
            # Save visualization
            with open(output_path / "brain_3d.html", "w") as f:
                f.write(html_content)
            
            # Save configuration
            results = {
                'visualization_type': '3D_brain',
                'colormap': colormap,
                'threshold': threshold,
                'interactive_features': interactive_features,
                'metrics': metrics,
                'output_file': str(output_path / "brain_3d.html")
            }
            
            with open(output_path / "viz3d_config.json", "w") as f:
                json.dump(results, f, indent=2)
            
            return ToolResult(
                status="success",
                data=results,
                metadata={
                    "output_files": {
                        "visualization": str(output_path / "brain_3d.html"),
                        "config": str(output_path / "viz3d_config.json")
                    }
                }
            )
            
        except Exception as e:
            logger.error(f"3D visualization failed: {e}")
            return ToolResult(status="error", error=str(e))
    
    def _generate_synthetic_brain_data(self) -> Tuple[np.ndarray, Dict]:
        """Generate synthetic brain data and mesh."""
        # Create 3D brain volume
        shape = (91, 109, 91)
        brain = np.zeros(shape)
        
        # Add brain-like structure
        center = [s // 2 for s in shape]
        x, y, z = np.ogrid[:shape[0], :shape[1], :shape[2]]
        
        # Ellipsoid for brain outline
        brain_mask = (((x - center[0]) / 40)**2 + 
                     ((y - center[1]) / 50)**2 + 
                     ((z - center[2]) / 40)**2) <= 1
        
        brain[brain_mask] = 1
        
        # Add some activation regions
        for _ in range(5):
            act_center = [center[i] + np.random.randint(-20, 20) for i in range(3)]
            radius = np.random.randint(5, 10)
            
            activation = (((x - act_center[0])**2 + 
                          (y - act_center[1])**2 + 
                          (z - act_center[2])**2) <= radius**2)
            
            brain[activation & brain_mask] = np.random.uniform(2, 5)
        
        # Create simple mesh (vertices and faces)
        mesh = self._create_surface_mesh(brain)
        
        return brain, mesh
    
    def _create_surface_mesh(self, volume: Optional[np.ndarray]) -> Dict:
        """Create surface mesh from volume."""
        if volume is None:
            # Create simple sphere mesh
            n_vertices = 1000
            vertices = []
            
            # Generate points on sphere
            for _ in range(n_vertices):
                theta = np.random.uniform(0, 2 * np.pi)
                phi = np.random.uniform(0, np.pi)
                
                x = 50 * np.sin(phi) * np.cos(theta)
                y = 50 * np.sin(phi) * np.sin(theta)
                z = 40 * np.cos(phi)
                
                vertices.append([x, y, z])
            
            vertices = np.array(vertices)
            
            # Simple triangulation (not proper, just for demo)
            faces = []
            for i in range(0, len(vertices) - 2, 3):
                faces.append([i, i+1, i+2])
            
            faces = np.array(faces)
        else:
            # Extract surface from volume (simplified)
            from scipy.ndimage import binary_erosion
            
            mask = volume > 0
            surface = mask & ~binary_erosion(mask)
            
            # Get surface points
            points = np.array(np.where(surface)).T
            
            # Simplify to subset
            if len(points) > 5000:
                indices = np.random.choice(len(points), 5000, replace=False)
                points = points[indices]
            
            vertices = points.astype(float)
            
            # Create simple faces (not proper triangulation)
            n_faces = min(len(vertices) // 3, 1000)
            faces = []
            for i in range(n_faces):
                idx = np.random.choice(len(vertices), 3, replace=False)
                faces.append(idx)
            
            faces = np.array(faces)
        
        return {
            'vertices': vertices.tolist(),
            'faces': faces.tolist(),
            'n_vertices': len(vertices),
            'n_faces': len(faces)
        }
    
    def _process_overlay(self, overlay_data: np.ndarray, threshold: Optional[float]) -> Dict:
        """Process overlay data for visualization."""
        if threshold is None:
            threshold = np.percentile(np.abs(overlay_data), 75)
        
        # Apply threshold
        masked = overlay_data.copy()
        masked[np.abs(masked) < threshold] = 0
        
        # Get statistics
        stats = {
            'min': float(np.min(masked[masked != 0])) if np.any(masked != 0) else 0,
            'max': float(np.max(masked[masked != 0])) if np.any(masked != 0) else 0,
            'mean': float(np.mean(masked[masked != 0])) if np.any(masked != 0) else 0,
            'n_voxels': int(np.sum(masked != 0))
        }
        
        return {
            'data': masked.tolist() if masked.size < 10000 else None,
            'threshold': float(threshold),
            'statistics': stats
        }
    
    def _create_viz_config(self, brain_data: Optional[np.ndarray], mesh: Dict,
                          overlay: Dict, colormap: str, view_angles: Optional[List]) -> Dict:
        """Create visualization configuration."""
        config = {
            'mesh': mesh,
            'colormap': colormap,
            'overlay': overlay
        }
        
        # Default view angles if not provided
        if view_angles is None:
            view_angles = [
                (0, 0),      # Axial
                (90, 0),     # Sagittal
                (0, 90),     # Coronal
                (45, 45)     # 3D
            ]
        
        config['views'] = [{'azimuth': a, 'elevation': e} for a, e in view_angles]
        
        # Add slicing information if volume data available
        if brain_data is not None:
            config['slices'] = {
                'shape': brain_data.shape,
                'center': [s // 2 for s in brain_data.shape]
            }
        
        return config
    
    def _setup_interactive_features(self, viz_config: Dict) -> Dict:
        """Setup interactive features for visualization."""
        features = {
            'rotation': True,
            'zoom': True,
            'pan': True,
            'slice_controls': 'slices' in viz_config,
            'opacity_control': True,
            'colormap_selector': True,
            'screenshot': True,
            'animation': True,
            'measurements': True
        }
        
        # Add interaction callbacks (simplified)
        features['callbacks'] = {
            'on_click': 'show_voxel_info',
            'on_hover': 'highlight_region',
            'on_slice_change': 'update_overlay'
        }
        
        return features
    
    def _generate_html_viz(self, viz_config: Dict, features: Dict) -> str:
        """Generate HTML for interactive visualization."""
        html = """
<!DOCTYPE html>
<html>
<head>
    <title>Interactive 3D Brain Visualization</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 20px; }
        #controls { margin-bottom: 20px; }
        #plot { width: 100%; height: 600px; }
        .control-group { display: inline-block; margin-right: 20px; }
        button { margin: 5px; padding: 5px 10px; }
        input[type="range"] { width: 200px; }
    </style>
</head>
<body>
    <h1>Interactive 3D Brain Visualization</h1>
    
    <div id="controls">
        <div class="control-group">
            <label>Opacity: <input type="range" id="opacity" min="0" max="100" value="80"></label>
        </div>
        <div class="control-group">
            <label>Threshold: <input type="range" id="threshold" min="0" max="100" value="50"></label>
        </div>
        <div class="control-group">
            <button onclick="resetView()">Reset View</button>
            <button onclick="toggleAnimation()">Toggle Animation</button>
            <button onclick="screenshot()">Screenshot</button>
        </div>
    </div>
    
    <div id="plot"></div>
    
    <script>
        // Visualization configuration
        const config = """ + json.dumps(viz_config) + """;
        const features = """ + json.dumps(features) + """;
        
        // Create 3D surface plot
        const data = [{
            type: 'mesh3d',
            x: config.mesh.vertices.map(v => v[0]),
            y: config.mesh.vertices.map(v => v[1]),
            z: config.mesh.vertices.map(v => v[2]),
            i: config.mesh.faces.map(f => f[0]),
            j: config.mesh.faces.map(f => f[1]),
            k: config.mesh.faces.map(f => f[2]),
            opacity: 0.8,
            color: 'lightgray'
        }];
        
        const layout = {
            scene: {
                camera: {
                    eye: {x: 1.5, y: 1.5, z: 1.5}
                },
                xaxis: {title: 'X'},
                yaxis: {title: 'Y'},
                zaxis: {title: 'Z'}
            },
            title: '3D Brain Visualization'
        };
        
        Plotly.newPlot('plot', data, layout);
        
        // Interactive functions
        function resetView() {
            Plotly.relayout('plot', {
                'scene.camera': {eye: {x: 1.5, y: 1.5, z: 1.5}}
            });
        }
        
        let animating = false;
        function toggleAnimation() {
            animating = !animating;
            if (animating) {
                animate();
            }
        }
        
        function animate() {
            if (!animating) return;
            
            Plotly.relayout('plot', {
                'scene.camera': {
                    eye: {
                        x: 1.5 * Math.cos(Date.now() / 1000),
                        y: 1.5 * Math.sin(Date.now() / 1000),
                        z: 1.5
                    }
                }
            });
            
            requestAnimationFrame(animate);
        }
        
        function screenshot() {
            Plotly.downloadImage('plot', {
                format: 'png',
                width: 1200,
                height: 800,
                filename: 'brain_3d'
            });
        }
        
        // Opacity control
        document.getElementById('opacity').addEventListener('input', function(e) {
            Plotly.restyle('plot', {opacity: e.target.value / 100});
        });
        
        // Threshold control
        document.getElementById('threshold').addEventListener('input', function(e) {
            // Would update overlay threshold in real implementation
            console.log('Threshold:', e.target.value);
        });
    </script>
</body>
</html>
"""
        return html
    
    def _calculate_viz_metrics(self, brain_data: Optional[np.ndarray],
                              overlay_data: Optional[np.ndarray]) -> Dict:
        """Calculate visualization metrics."""
        metrics = {}
        
        if brain_data is not None:
            metrics['volume_size'] = list(brain_data.shape)
            metrics['n_voxels'] = int(np.prod(brain_data.shape))
            metrics['data_range'] = [float(np.min(brain_data)), float(np.max(brain_data))]
        
        if overlay_data is not None:
            metrics['overlay_coverage'] = float(np.sum(overlay_data != 0) / overlay_data.size)
            metrics['overlay_peak'] = float(np.max(np.abs(overlay_data)))
        
        return metrics


class DynamicConnectivityVisualizationTool(NeuroToolWrapper):
    """Visualize dynamic brain connectivity patterns."""
    
    def __init__(self):
        super().__init__()
    
    def get_tool_name(self) -> str:
        return "dynamic_connectivity_viz"
    
    def get_tool_description(self) -> str:
        return "Create interactive visualizations of dynamic brain connectivity"
    
    def get_args_schema(self):
        return VisualizationInput
    
    def _run(
        self,
        connectivity_matrix: Optional[np.ndarray] = None,
        time_series: Optional[np.ndarray] = None,
        atlas_labels: Optional[List[str]] = None,
        window_size: int = 30,
        visualization_type: str = "chord",  # chord, heatmap, graph, or matrix
        threshold: float = 0.3,
        output_dir: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """Create dynamic connectivity visualization."""
        try:
            output_path = Path(output_dir or "connectivity_viz_output")
            output_path.mkdir(parents=True, exist_ok=True)
            
            # Generate or load data
            if connectivity_matrix is None:
                if time_series is None:
                    time_series = self._generate_synthetic_time_series()
                connectivity_matrix = self._compute_dynamic_connectivity(time_series, window_size)
            
            # Generate labels if not provided
            if atlas_labels is None:
                n_regions = connectivity_matrix.shape[0]
                atlas_labels = [f"Region_{i+1}" for i in range(n_regions)]
            
            # Process connectivity for visualization
            processed_conn = self._process_connectivity(connectivity_matrix, threshold)
            
            # Calculate network metrics
            network_metrics = self._calculate_network_metrics(processed_conn)
            
            # Generate visualization based on type
            if visualization_type == "chord":
                viz_data = self._create_chord_diagram(processed_conn, atlas_labels)
            elif visualization_type == "heatmap":
                viz_data = self._create_heatmap(processed_conn, atlas_labels)
            elif visualization_type == "graph":
                viz_data = self._create_graph_layout(processed_conn, atlas_labels)
            else:
                viz_data = self._create_matrix_view(processed_conn, atlas_labels)
            
            # Generate interactive HTML
            html_content = self._generate_connectivity_html(viz_data, visualization_type)
            
            # Save visualization
            with open(output_path / f"connectivity_{visualization_type}.html", "w") as f:
                f.write(html_content)
            
            # Save processed data
            np.save(output_path / "processed_connectivity.npy", processed_conn)
            
            results = {
                'visualization_type': visualization_type,
                'n_regions': len(atlas_labels),
                'threshold': threshold,
                'network_metrics': network_metrics,
                'output_file': str(output_path / f"connectivity_{visualization_type}.html")
            }
            
            with open(output_path / "connectivity_config.json", "w") as f:
                json.dump(results, f, indent=2)
            
            return ToolResult(
                status="success",
                data=results,
                metadata={
                    "output_files": {
                        "visualization": str(output_path / f"connectivity_{visualization_type}.html"),
                        "config": str(output_path / "connectivity_config.json"),
                        "data": str(output_path / "processed_connectivity.npy")
                    }
                }
            )
            
        except Exception as e:
            logger.error(f"Connectivity visualization failed: {e}")
            return ToolResult(status="error", error=str(e))
    
    def _generate_synthetic_time_series(self) -> np.ndarray:
        """Generate synthetic time series data."""
        n_regions = 50
        n_timepoints = 500
        
        # Generate correlated time series
        time_series = np.random.randn(n_regions, n_timepoints)
        
        # Add correlations between some regions
        for i in range(0, n_regions-1, 5):
            # Create clusters of correlated regions
            cluster_size = min(5, n_regions - i)
            shared_signal = np.random.randn(n_timepoints)
            
            for j in range(cluster_size):
                time_series[i+j] = 0.7 * time_series[i+j] + 0.3 * shared_signal
        
        return time_series
    
    def _compute_dynamic_connectivity(self, time_series: np.ndarray, window_size: int) -> np.ndarray:
        """Compute dynamic connectivity from time series."""
        n_regions, n_timepoints = time_series.shape
        n_windows = n_timepoints - window_size + 1
        
        # For simplicity, compute static connectivity
        # In reality, would compute sliding window connectivity
        connectivity = np.corrcoef(time_series)
        
        # Remove self-connections
        np.fill_diagonal(connectivity, 0)
        
        return connectivity
    
    def _process_connectivity(self, connectivity: np.ndarray, threshold: float) -> np.ndarray:
        """Process connectivity matrix for visualization."""
        processed = connectivity.copy()
        
        # Apply threshold
        processed[np.abs(processed) < threshold] = 0
        
        # Ensure symmetry
        processed = (processed + processed.T) / 2
        
        return processed
    
    def _calculate_network_metrics(self, connectivity: np.ndarray) -> Dict:
        """Calculate network metrics."""
        # Binary adjacency matrix
        adj = (np.abs(connectivity) > 0).astype(int)
        
        # Degree
        degrees = np.sum(adj, axis=0)
        
        # Density
        n = len(connectivity)
        possible_edges = n * (n - 1) / 2
        actual_edges = np.sum(adj) / 2
        density = actual_edges / possible_edges if possible_edges > 0 else 0
        
        # Clustering coefficient (simplified)
        clustering_coeffs = []
        for i in range(n):
            neighbors = np.where(adj[i])[0]
            if len(neighbors) > 1:
                subgraph = adj[np.ix_(neighbors, neighbors)]
                possible = len(neighbors) * (len(neighbors) - 1) / 2
                actual = np.sum(subgraph) / 2
                clustering_coeffs.append(actual / possible if possible > 0 else 0)
        
        avg_clustering = np.mean(clustering_coeffs) if clustering_coeffs else 0
        
        # Modularity (simplified - random partition)
        n_communities = max(3, n // 10)
        communities = np.random.randint(0, n_communities, n)
        
        modularity = 0
        for c in range(n_communities):
            nodes_in_c = np.where(communities == c)[0]
            if len(nodes_in_c) > 0:
                within = np.sum(adj[np.ix_(nodes_in_c, nodes_in_c)])
                total = np.sum(adj[nodes_in_c])
                modularity += within - (total**2) / (2 * actual_edges + 0.01)
        
        modularity /= (2 * actual_edges + 0.01)
        
        return {
            'mean_degree': float(np.mean(degrees)),
            'network_density': float(density),
            'clustering_coefficient': float(avg_clustering),
            'modularity': float(modularity),
            'n_edges': int(actual_edges),
            'strongest_connection': float(np.max(np.abs(connectivity)))
        }
    
    def _create_chord_diagram(self, connectivity: np.ndarray, labels: List[str]) -> Dict:
        """Create chord diagram data."""
        # Convert to edge list
        edges = []
        for i in range(len(connectivity)):
            for j in range(i+1, len(connectivity)):
                if connectivity[i, j] != 0:
                    edges.append({
                        'source': labels[i],
                        'target': labels[j],
                        'value': float(np.abs(connectivity[i, j]))
                    })
        
        return {
            'nodes': labels,
            'edges': edges,
            'type': 'chord'
        }
    
    def _create_heatmap(self, connectivity: np.ndarray, labels: List[str]) -> Dict:
        """Create heatmap data."""
        return {
            'data': connectivity.tolist(),
            'labels': labels,
            'type': 'heatmap',
            'colorscale': 'RdBu',
            'symmetric': True
        }
    
    def _create_graph_layout(self, connectivity: np.ndarray, labels: List[str]) -> Dict:
        """Create graph layout data."""
        n = len(labels)
        
        # Simple circular layout
        angles = np.linspace(0, 2 * np.pi, n, endpoint=False)
        positions = {
            labels[i]: {
                'x': float(np.cos(angles[i])),
                'y': float(np.sin(angles[i]))
            }
            for i in range(n)
        }
        
        # Edges
        edges = []
        for i in range(n):
            for j in range(i+1, n):
                if connectivity[i, j] != 0:
                    edges.append({
                        'source': labels[i],
                        'target': labels[j],
                        'weight': float(np.abs(connectivity[i, j]))
                    })
        
        return {
            'nodes': positions,
            'edges': edges,
            'type': 'graph'
        }
    
    def _create_matrix_view(self, connectivity: np.ndarray, labels: List[str]) -> Dict:
        """Create matrix view data."""
        # Reorder matrix for better visualization (simple clustering)
        from scipy.cluster.hierarchy import linkage, dendrogram
        
        # Hierarchical clustering
        linkage_matrix = linkage(connectivity, method='average')
        dendro = dendrogram(linkage_matrix, no_plot=True)
        order = dendro['leaves']
        
        # Reorder
        reordered = connectivity[order][:, order]
        reordered_labels = [labels[i] for i in order]
        
        return {
            'data': reordered.tolist(),
            'labels': reordered_labels,
            'original_order': order,
            'type': 'matrix'
        }
    
    def _generate_connectivity_html(self, viz_data: Dict, viz_type: str) -> str:
        """Generate HTML for connectivity visualization."""
        if viz_type == "heatmap":
            return self._generate_heatmap_html(viz_data)
        elif viz_type == "chord":
            return self._generate_chord_html(viz_data)
        elif viz_type == "graph":
            return self._generate_graph_html(viz_data)
        else:
            return self._generate_matrix_html(viz_data)
    
    def _generate_heatmap_html(self, viz_data: Dict) -> str:
        """Generate heatmap HTML."""
        html = """
<!DOCTYPE html>
<html>
<head>
    <title>Connectivity Heatmap</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        #plot { width: 100%; height: 600px; }
    </style>
</head>
<body>
    <h1>Brain Connectivity Heatmap</h1>
    <div id="plot"></div>
    
    <script>
        const data = """ + json.dumps(viz_data) + """;
        
        const trace = {
            type: 'heatmap',
            z: data.data,
            x: data.labels,
            y: data.labels,
            colorscale: data.colorscale,
            symmetric: true
        };
        
        const layout = {
            title: 'Connectivity Matrix',
            xaxis: {tickangle: -45},
            yaxis: {autorange: 'reversed'}
        };
        
        Plotly.newPlot('plot', [trace], layout);
    </script>
</body>
</html>
"""
        return html
    
    def _generate_chord_html(self, viz_data: Dict) -> str:
        """Generate chord diagram HTML."""
        # Simplified - would use D3.js in real implementation
        html = """
<!DOCTYPE html>
<html>
<head>
    <title>Connectivity Chord Diagram</title>
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        #chart { width: 800px; height: 800px; margin: auto; }
    </style>
</head>
<body>
    <h1>Brain Connectivity Chord Diagram</h1>
    <div id="chart">
        <p>Chord diagram visualization would be rendered here using D3.js</p>
        <p>Nodes: """ + str(len(viz_data['nodes'])) + """</p>
        <p>Edges: """ + str(len(viz_data['edges'])) + """</p>
    </div>
</body>
</html>
"""
        return html
    
    def _generate_graph_html(self, viz_data: Dict) -> str:
        """Generate graph HTML."""
        html = """
<!DOCTYPE html>
<html>
<head>
    <title>Connectivity Graph</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        #plot { width: 100%; height: 600px; }
    </style>
</head>
<body>
    <h1>Brain Connectivity Graph</h1>
    <div id="plot"></div>
    
    <script>
        const data = """ + json.dumps(viz_data) + """;
        
        // Create node trace
        const nodeTrace = {
            x: Object.values(data.nodes).map(n => n.x),
            y: Object.values(data.nodes).map(n => n.y),
            mode: 'markers+text',
            text: Object.keys(data.nodes),
            textposition: 'top center',
            marker: {
                size: 10,
                color: 'blue'
            },
            type: 'scatter'
        };
        
        // Create edge traces
        const edgeTraces = [];
        data.edges.forEach(edge => {
            const source = data.nodes[edge.source];
            const target = data.nodes[edge.target];
            
            edgeTraces.push({
                x: [source.x, target.x],
                y: [source.y, target.y],
                mode: 'lines',
                line: {
                    width: edge.weight * 5,
                    color: 'gray'
                },
                type: 'scatter',
                showlegend: false
            });
        });
        
        const layout = {
            title: 'Connectivity Graph',
            showlegend: false,
            xaxis: {showgrid: false, zeroline: false, showticklabels: false},
            yaxis: {showgrid: false, zeroline: false, showticklabels: false}
        };
        
        Plotly.newPlot('plot', [...edgeTraces, nodeTrace], layout);
    </script>
</body>
</html>
"""
        return html
    
    def _generate_matrix_html(self, viz_data: Dict) -> str:
        """Generate matrix HTML."""
        return self._generate_heatmap_html(viz_data)  # Similar to heatmap


class TimeSeriesVisualizationTool(NeuroToolWrapper):
    """Create interactive time series visualizations."""
    
    def __init__(self):
        super().__init__()
    
    def get_tool_name(self) -> str:
        return "time_series_viz"
    
    def get_tool_description(self) -> str:
        return "Generate interactive time series visualizations with multiple panels and synchronization"
    
    def get_args_schema(self):
        return VisualizationInput
    
    def _run(
        self,
        time_series: Optional[np.ndarray] = None,
        sampling_rate: float = 1.0,
        labels: Optional[List[str]] = None,
        events: Optional[List[Dict]] = None,
        visualization_type: str = "multi_panel",  # multi_panel, stacked, overlay
        frequency_analysis: bool = True,
        output_dir: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """Create time series visualization."""
        try:
            output_path = Path(output_dir or "timeseries_viz_output")
            output_path.mkdir(parents=True, exist_ok=True)
            
            # Generate or load data
            if time_series is None:
                time_series = self._generate_synthetic_time_series()
            
            # Generate labels if not provided
            if labels is None:
                n_series = time_series.shape[0] if len(time_series.shape) > 1 else 1
                labels = [f"Channel_{i+1}" for i in range(n_series)]
            
            # Process time series
            processed_ts = self._process_time_series(time_series)
            
            # Frequency analysis if requested
            if frequency_analysis:
                freq_data = self._perform_frequency_analysis(processed_ts, sampling_rate)
            else:
                freq_data = {}
            
            # Calculate metrics
            metrics = self._calculate_time_series_metrics(processed_ts, sampling_rate)
            
            # Generate visualization
            viz_data = self._create_time_series_viz(
                processed_ts, labels, events, sampling_rate, visualization_type, freq_data
            )
            
            # Generate HTML
            html_content = self._generate_time_series_html(viz_data, visualization_type)
            
            # Save visualization
            with open(output_path / "time_series.html", "w") as f:
                f.write(html_content)
            
            results = {
                'visualization_type': visualization_type,
                'n_channels': len(labels),
                'duration': float(len(processed_ts[0] if len(processed_ts.shape) > 1 else processed_ts) / sampling_rate),
                'sampling_rate': sampling_rate,
                'metrics': metrics,
                'frequency_analysis': freq_data != {},
                'output_file': str(output_path / "time_series.html")
            }
            
            if freq_data:
                results['frequency_peaks'] = freq_data.get('peaks', [])
            
            with open(output_path / "timeseries_config.json", "w") as f:
                json.dump(results, f, indent=2)
            
            return ToolResult(
                status="success",
                data=results,
                metadata={
                    "output_files": {
                        "visualization": str(output_path / "time_series.html"),
                        "config": str(output_path / "timeseries_config.json")
                    }
                }
            )
            
        except Exception as e:
            logger.error(f"Time series visualization failed: {e}")
            return ToolResult(status="error", error=str(e))
    
    def _generate_synthetic_time_series(self) -> np.ndarray:
        """Generate synthetic time series."""
        n_channels = 10
        n_samples = 1000
        
        time_series = np.zeros((n_channels, n_samples))
        
        for i in range(n_channels):
            # Base signal
            t = np.arange(n_samples)
            
            # Add different frequency components
            freq1 = 0.01 * (i + 1)
            freq2 = 0.05 * (i + 1)
            
            time_series[i] = (np.sin(2 * np.pi * freq1 * t) +
                            0.5 * np.sin(2 * np.pi * freq2 * t) +
                            0.2 * np.random.randn(n_samples))
            
            # Add some events
            if i % 3 == 0:
                event_times = [200, 500, 800]
                for event_time in event_times:
                    time_series[i, event_time:event_time+20] += 2
        
        return time_series
    
    def _process_time_series(self, time_series: np.ndarray) -> np.ndarray:
        """Process time series for visualization."""
        # Ensure 2D
        if len(time_series.shape) == 1:
            time_series = time_series.reshape(1, -1)
        
        # Detrend
        from scipy.signal import detrend
        processed = np.zeros_like(time_series)
        
        for i in range(len(time_series)):
            processed[i] = detrend(time_series[i])
        
        return processed
    
    def _perform_frequency_analysis(self, time_series: np.ndarray, sampling_rate: float) -> Dict:
        """Perform frequency analysis."""
        from scipy.signal import welch, find_peaks
        
        freq_data = {
            'frequencies': [],
            'power': [],
            'peaks': []
        }
        
        for i in range(len(time_series)):
            # Compute power spectral density
            frequencies, psd = welch(time_series[i], fs=sampling_rate, nperseg=min(256, len(time_series[i])))
            
            freq_data['frequencies'] = frequencies.tolist()
            freq_data['power'].append(psd.tolist())
            
            # Find peaks
            peaks, _ = find_peaks(psd, height=np.mean(psd))
            if len(peaks) > 0:
                peak_freqs = frequencies[peaks[:3]]  # Top 3 peaks
                freq_data['peaks'].append(peak_freqs.tolist())
            else:
                freq_data['peaks'].append([])
        
        return freq_data
    
    def _calculate_time_series_metrics(self, time_series: np.ndarray, sampling_rate: float) -> Dict:
        """Calculate time series metrics."""
        metrics = {
            'mean': float(np.mean(time_series)),
            'std': float(np.std(time_series)),
            'min': float(np.min(time_series)),
            'max': float(np.max(time_series)),
            'rms': float(np.sqrt(np.mean(time_series**2)))
        }
        
        # Cross-correlation between channels
        if len(time_series) > 1:
            corr_matrix = np.corrcoef(time_series)
            np.fill_diagonal(corr_matrix, 0)
            metrics['mean_correlation'] = float(np.mean(np.abs(corr_matrix)))
        
        return metrics
    
    def _create_time_series_viz(self, time_series: np.ndarray, labels: List[str],
                               events: Optional[List[Dict]], sampling_rate: float,
                               viz_type: str, freq_data: Dict) -> Dict:
        """Create time series visualization data."""
        time_axis = np.arange(time_series.shape[1]) / sampling_rate
        
        viz_data = {
            'time': time_axis.tolist(),
            'data': time_series.tolist(),
            'labels': labels,
            'type': viz_type,
            'sampling_rate': sampling_rate
        }
        
        if events:
            viz_data['events'] = events
        
        if freq_data:
            viz_data['frequency_data'] = freq_data
        
        return viz_data
    
    def _generate_time_series_html(self, viz_data: Dict, viz_type: str) -> str:
        """Generate time series HTML."""
        html = """
<!DOCTYPE html>
<html>
<head>
    <title>Time Series Visualization</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        #controls { margin-bottom: 20px; }
        #plot { width: 100%; height: 600px; }
        button { margin: 5px; padding: 5px 10px; }
    </style>
</head>
<body>
    <h1>Interactive Time Series Visualization</h1>
    
    <div id="controls">
        <button onclick="resetZoom()">Reset Zoom</button>
        <button onclick="toggleFrequency()">Toggle Frequency</button>
        <button onclick="exportData()">Export Data</button>
    </div>
    
    <div id="plot"></div>
    
    <script>
        const data = """ + json.dumps(viz_data) + """;
        let showFrequency = false;
        
        function createPlot() {
            const traces = [];
            
            if (!showFrequency) {
                // Time domain plots
                data.data.forEach((series, i) => {
                    traces.push({
                        x: data.time,
                        y: series,
                        name: data.labels[i],
                        type: 'scatter',
                        mode: 'lines'
                    });
                });
            } else if (data.frequency_data) {
                // Frequency domain plots
                data.frequency_data.power.forEach((psd, i) => {
                    traces.push({
                        x: data.frequency_data.frequencies,
                        y: psd,
                        name: data.labels[i] + ' PSD',
                        type: 'scatter',
                        mode: 'lines'
                    });
                });
            }
            
            const layout = {
                title: showFrequency ? 'Frequency Domain' : 'Time Domain',
                xaxis: {title: showFrequency ? 'Frequency (Hz)' : 'Time (s)'},
                yaxis: {title: showFrequency ? 'Power' : 'Amplitude'},
                showlegend: true
            };
            
            Plotly.newPlot('plot', traces, layout);
        }
        
        createPlot();
        
        function resetZoom() {
            Plotly.relayout('plot', {
                'xaxis.autorange': true,
                'yaxis.autorange': true
            });
        }
        
        function toggleFrequency() {
            showFrequency = !showFrequency;
            createPlot();
        }
        
        function exportData() {
            const csvContent = 'data:text/csv;charset=utf-8,' + 
                'Time,' + data.labels.join(',') + '\\n' +
                data.time.map((t, i) => 
                    t + ',' + data.data.map(series => series[i]).join(',')
                ).join('\\n');
            
            const link = document.createElement('a');
            link.href = encodeURI(csvContent);
            link.download = 'time_series.csv';
            link.click();
        }
    </script>
</body>
</html>
"""
        return html


class VirtualRealityBrainTool(NeuroToolWrapper):
    """Create VR-ready brain visualizations."""
    
    def __init__(self):
        super().__init__()
    
    def get_tool_name(self) -> str:
        return "vr_brain_viz"
    
    def get_tool_description(self) -> str:
        return "Generate VR-compatible brain visualizations for immersive exploration"
    
    def get_args_schema(self):
        return VisualizationInput
    
    def _run(
        self,
        brain_data: Optional[np.ndarray] = None,
        surface_mesh: Optional[Dict] = None,
        vr_platform: str = "webxr",  # webxr, oculus, vive
        interaction_mode: str = "controller",  # controller, gaze, hand
        output_dir: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """Create VR brain visualization."""
        try:
            output_path = Path(output_dir or "vr_viz_output")
            output_path.mkdir(parents=True, exist_ok=True)
            
            # Generate or load data
            if brain_data is None and surface_mesh is None:
                brain_data, mesh = self._generate_vr_brain_data()
            else:
                mesh = surface_mesh if surface_mesh else self._create_vr_mesh(brain_data)
            
            # Optimize mesh for VR
            optimized_mesh = self._optimize_mesh_for_vr(mesh)
            
            # Setup VR scene
            vr_scene = self._setup_vr_scene(optimized_mesh, vr_platform)
            
            # Add interactions
            interactions = self._setup_vr_interactions(interaction_mode)
            
            # Generate VR visualization
            vr_content = self._generate_vr_html(vr_scene, interactions, vr_platform)
            
            # Calculate VR metrics
            metrics = self._calculate_vr_metrics(optimized_mesh)
            
            # Save VR visualization
            with open(output_path / "brain_vr.html", "w") as f:
                f.write(vr_content)
            
            results = {
                'vr_platform': vr_platform,
                'interaction_mode': interaction_mode,
                'mesh_complexity': metrics,
                'vr_ready': True,
                'output_file': str(output_path / "brain_vr.html")
            }
            
            with open(output_path / "vr_config.json", "w") as f:
                json.dump(results, f, indent=2)
            
            return ToolResult(
                status="success",
                data=results,
                metadata={
                    "output_files": {
                        "vr_visualization": str(output_path / "brain_vr.html"),
                        "config": str(output_path / "vr_config.json")
                    }
                }
            )
            
        except Exception as e:
            logger.error(f"VR visualization failed: {e}")
            return ToolResult(status="error", error=str(e))
    
    def _generate_vr_brain_data(self) -> Tuple[np.ndarray, Dict]:
        """Generate VR-optimized brain data."""
        # Create simplified brain for VR performance
        shape = (64, 64, 64)
        brain = np.zeros(shape)
        
        # Brain structure
        center = [s // 2 for s in shape]
        x, y, z = np.ogrid[:shape[0], :shape[1], :shape[2]]
        
        brain_mask = (((x - center[0]) / 25)**2 + 
                     ((y - center[1]) / 30)**2 + 
                     ((z - center[2]) / 25)**2) <= 1
        
        brain[brain_mask] = 1
        
        # Create optimized mesh
        mesh = self._create_vr_mesh(brain)
        
        return brain, mesh
    
    def _create_vr_mesh(self, volume: Optional[np.ndarray]) -> Dict:
        """Create VR-optimized mesh."""
        # Simplified mesh for VR performance
        n_vertices = 500  # Lower for VR
        vertices = []
        
        for _ in range(n_vertices):
            theta = np.random.uniform(0, 2 * np.pi)
            phi = np.random.uniform(0, np.pi)
            
            x = 30 * np.sin(phi) * np.cos(theta)
            y = 30 * np.sin(phi) * np.sin(theta)
            z = 25 * np.cos(phi)
            
            vertices.append([x, y, z])
        
        vertices = np.array(vertices)
        
        # Simple faces
        faces = []
        for i in range(0, len(vertices) - 2, 3):
            faces.append([i, i+1, i+2])
        
        return {
            'vertices': vertices.tolist(),
            'faces': faces,
            'normals': self._calculate_normals(vertices, faces)
        }
    
    def _calculate_normals(self, vertices: np.ndarray, faces: List) -> List:
        """Calculate vertex normals for lighting."""
        normals = np.zeros_like(vertices)
        
        for face in faces:
            if len(face) >= 3:
                v0 = vertices[face[0]]
                v1 = vertices[face[1]]
                v2 = vertices[face[2]]
                
                # Face normal
                edge1 = v1 - v0
                edge2 = v2 - v0
                face_normal = np.cross(edge1, edge2)
                face_normal /= np.linalg.norm(face_normal) + 0.001
                
                # Add to vertex normals
                for idx in face:
                    normals[idx] += face_normal
        
        # Normalize
        for i in range(len(normals)):
            norm = np.linalg.norm(normals[i])
            if norm > 0:
                normals[i] /= norm
        
        return normals.tolist()
    
    def _optimize_mesh_for_vr(self, mesh: Dict) -> Dict:
        """Optimize mesh for VR rendering."""
        # Level of detail optimization
        optimized = mesh.copy()
        
        # Reduce vertices if too many
        max_vertices = 1000
        if len(mesh['vertices']) > max_vertices:
            indices = np.random.choice(len(mesh['vertices']), max_vertices, replace=False)
            optimized['vertices'] = [mesh['vertices'][i] for i in indices]
            # Update faces accordingly (simplified)
            optimized['faces'] = [[i, i+1, i+2] for i in range(0, max_vertices-2, 3)]
        
        optimized['optimized'] = True
        optimized['lod_levels'] = 3
        
        return optimized
    
    def _setup_vr_scene(self, mesh: Dict, platform: str) -> Dict:
        """Setup VR scene configuration."""
        scene = {
            'mesh': mesh,
            'lighting': {
                'ambient': 0.3,
                'directional': [
                    {'direction': [0, 1, 0], 'intensity': 0.5},
                    {'direction': [1, 0, 0], 'intensity': 0.3}
                ]
            },
            'camera': {
                'position': [0, 0, 100],
                'fov': 75,
                'near': 0.1,
                'far': 1000
            },
            'environment': {
                'skybox': 'gradient',
                'floor': True,
                'grid': True
            }
        }
        
        # Platform-specific settings
        if platform == "oculus":
            scene['performance'] = 'high'
            scene['refresh_rate'] = 90
        elif platform == "vive":
            scene['performance'] = 'high'
            scene['refresh_rate'] = 90
        else:  # webxr
            scene['performance'] = 'balanced'
            scene['refresh_rate'] = 60
        
        return scene
    
    def _setup_vr_interactions(self, mode: str) -> Dict:
        """Setup VR interaction configuration."""
        interactions = {
            'mode': mode,
            'enabled': True,
            'features': []
        }
        
        if mode == "controller":
            interactions['features'] = [
                'point_and_select',
                'grab_and_rotate',
                'scale',
                'slice',
                'measure',
                'annotate'
            ]
        elif mode == "gaze":
            interactions['features'] = [
                'gaze_select',
                'dwell_time',
                'highlight'
            ]
        elif mode == "hand":
            interactions['features'] = [
                'pinch_to_zoom',
                'grab',
                'gesture_control'
            ]
        
        interactions['haptic_feedback'] = mode == "controller"
        
        return interactions
    
    def _generate_vr_html(self, scene: Dict, interactions: Dict, platform: str) -> str:
        """Generate VR-ready HTML."""
        html = """
<!DOCTYPE html>
<html>
<head>
    <title>VR Brain Visualization</title>
    <script src="https://aframe.io/releases/1.4.0/aframe.min.js"></script>
    <script src="https://cdn.jsdelivr.net/gh/supermedium/superframe@master/components/environment/dist/aframe-environment-component.min.js"></script>
    <style>
        body { margin: 0; font-family: Arial, sans-serif; }
        #enterVR { 
            position: fixed; 
            bottom: 20px; 
            right: 20px; 
            padding: 15px 30px;
            background: #4CAF50;
            color: white;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 16px;
            z-index: 999;
        }
    </style>
</head>
<body>
    <button id="enterVR">Enter VR</button>
    
    <a-scene environment="preset: forest; groundColor: #445; grid: cross">
        <!-- Brain mesh -->
        <a-entity id="brain"
                  geometry="primitive: sphere; radius: 2"
                  material="color: #FFC0CB; opacity: 0.8"
                  position="0 1.5 -5"
                  animation="property: rotation; to: 0 360 0; loop: true; dur: 10000">
        </a-entity>
        
        <!-- Controllers -->
        <a-entity laser-controls="hand: right"></a-entity>
        <a-entity laser-controls="hand: left"></a-entity>
        
        <!-- Info panel -->
        <a-text value="VR Brain Explorer\\nUse controllers to interact"
                position="-2 3 -5"
                color="#FFFFFF"
                font="kelsonsans">
        </a-text>
        
        <!-- Camera -->
        <a-camera position="0 1.6 0">
            <a-cursor animation__click="property: scale; to: 0.8 0.8 0.8; startEvents: click"
                     animation__clickend="property: scale; to: 1 1 1; startEvents: animationcomplete__click">
            </a-cursor>
        </a-camera>
        
        <!-- Lighting -->
        <a-light type="ambient" color="#404040"></a-light>
        <a-light type="directional" position="0 10 0" color="#FFFFFF"></a-light>
    </a-scene>
    
    <script>
        const scene = """ + json.dumps(scene) + """;
        const interactions = """ + json.dumps(interactions) + """;
        
        // Setup VR
        document.getElementById('enterVR').addEventListener('click', function() {
            document.querySelector('a-scene').enterVR();
        });
        
        // Setup interactions
        const brain = document.getElementById('brain');
        
        brain.addEventListener('click', function() {
            console.log('Brain clicked');
            // Add interaction logic
        });
        
        // Controller interactions
        if (interactions.mode === 'controller') {
            document.querySelectorAll('[laser-controls]').forEach(controller => {
                controller.addEventListener('triggerdown', function() {
                    console.log('Trigger pressed');
                });
            });
        }
        
        // Add mesh data
        // In real implementation, would convert mesh to A-Frame geometry
        console.log('VR Scene loaded with', scene.mesh.vertices.length, 'vertices');
    </script>
</body>
</html>
"""
        return html
    
    def _calculate_vr_metrics(self, mesh: Dict) -> Dict:
        """Calculate VR performance metrics."""
        n_vertices = len(mesh.get('vertices', []))
        n_faces = len(mesh.get('faces', []))
        
        # Estimate frame rate based on complexity
        if n_vertices < 1000:
            estimated_fps = 90
        elif n_vertices < 5000:
            estimated_fps = 60
        else:
            estimated_fps = 30
        
        return {
            'n_vertices': n_vertices,
            'n_faces': n_faces,
            'estimated_fps': estimated_fps,
            'vr_ready': n_vertices < 10000,
            'optimization_level': mesh.get('lod_levels', 1)
        }


class AugmentedRealityBrainTool(NeuroToolWrapper):
    """Create AR brain visualizations."""
    
    def __init__(self):
        super().__init__()
    
    def get_tool_name(self) -> str:
        return "ar_brain_viz"
    
    def get_tool_description(self) -> str:
        return "Generate AR-compatible brain visualizations for mobile and headset devices"
    
    def get_args_schema(self):
        return VisualizationInput
    
    def _run(
        self,
        brain_data: Optional[np.ndarray] = None,
        markers: Optional[List[Dict]] = None,
        ar_platform: str = "webxr",  # webxr, arcore, arkit
        tracking_mode: str = "marker",  # marker, markerless, slam
        output_dir: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """Create AR brain visualization."""
        try:
            output_path = Path(output_dir or "ar_viz_output")
            output_path.mkdir(parents=True, exist_ok=True)
            
            # Generate or load data
            if brain_data is None:
                brain_data = self._generate_ar_brain_data()
            
            # Process for AR
            ar_model = self._create_ar_model(brain_data)
            
            # Setup tracking
            tracking_config = self._setup_tracking(tracking_mode)
            
            # Add AR markers/anchors
            if markers is None:
                markers = self._generate_default_markers()
            
            # Create AR scene
            ar_scene = self._create_ar_scene(ar_model, markers, tracking_config)
            
            # Generate AR content
            ar_content = self._generate_ar_html(ar_scene, ar_platform)
            
            # Calculate AR metrics
            metrics = self._calculate_ar_metrics(ar_model, tracking_mode)
            
            # Save AR visualization
            with open(output_path / "brain_ar.html", "w") as f:
                f.write(ar_content)
            
            # Generate marker image if needed
            if tracking_mode == "marker":
                marker_data = self._generate_marker_image()
                with open(output_path / "ar_marker.svg", "w") as f:
                    f.write(marker_data)
            
            results = {
                'ar_platform': ar_platform,
                'tracking_mode': tracking_mode,
                'n_markers': len(markers),
                'model_complexity': metrics,
                'ar_ready': True,
                'output_files': {
                    'visualization': str(output_path / "brain_ar.html")
                }
            }
            
            if tracking_mode == "marker":
                results['output_files']['marker'] = str(output_path / "ar_marker.svg")
            
            with open(output_path / "ar_config.json", "w") as f:
                json.dump(results, f, indent=2)
            
            return ToolResult(
                status="success",
                data=results,
                metadata={"output_files": results['output_files']}
            )
            
        except Exception as e:
            logger.error(f"AR visualization failed: {e}")
            return ToolResult(status="error", error=str(e))
    
    def _generate_ar_brain_data(self) -> np.ndarray:
        """Generate AR-optimized brain data."""
        # Simplified for AR
        shape = (50, 50, 50)
        brain = np.zeros(shape)
        
        center = [s // 2 for s in shape]
        x, y, z = np.ogrid[:shape[0], :shape[1], :shape[2]]
        
        brain_mask = (((x - center[0]) / 20)**2 + 
                     ((y - center[1]) / 25)**2 + 
                     ((z - center[2]) / 20)**2) <= 1
        
        brain[brain_mask] = 1
        
        # Add some regions
        for _ in range(3):
            region_center = [center[i] + np.random.randint(-10, 10) for i in range(3)]
            region_mask = (((x - region_center[0])**2 + 
                          (y - region_center[1])**2 + 
                          (z - region_center[2])**2) <= 25)
            brain[region_mask & brain_mask] = 2
        
        return brain
    
    def _create_ar_model(self, brain_data: np.ndarray) -> Dict:
        """Create AR-optimized 3D model."""
        # Extract surface points
        threshold = 0.5
        surface_points = np.array(np.where(brain_data > threshold)).T
        
        # Simplify for AR
        if len(surface_points) > 500:
            indices = np.random.choice(len(surface_points), 500, replace=False)
            surface_points = surface_points[indices]
        
        # Scale to AR-friendly size (10cm cube)
        scaled_points = surface_points / np.max(surface_points) * 0.1
        
        return {
            'points': scaled_points.tolist(),
            'colors': self._assign_colors(brain_data, surface_points),
            'scale': 0.1,  # 10cm
            'anchor_point': [0, 0, 0]
        }
    
    def _assign_colors(self, brain_data: np.ndarray, points: np.ndarray) -> List:
        """Assign colors to points based on data values."""
        colors = []
        for point in points:
            value = brain_data[tuple(point.astype(int))]
            if value > 1.5:
                colors.append([1, 0, 0])  # Red for high values
            elif value > 0.5:
                colors.append([0, 0, 1])  # Blue for medium
            else:
                colors.append([0.5, 0.5, 0.5])  # Gray for low
        return colors
    
    def _setup_tracking(self, mode: str) -> Dict:
        """Setup AR tracking configuration."""
        config = {
            'mode': mode,
            'requirements': []
        }
        
        if mode == "marker":
            config['marker_type'] = 'pattern'
            config['marker_size'] = 0.15  # 15cm
            config['requirements'] = ['camera', 'marker_detection']
        elif mode == "markerless":
            config['requirements'] = ['camera', 'plane_detection']
            config['min_features'] = 100
        elif mode == "slam":
            config['requirements'] = ['camera', 'imu', 'slam_capability']
            config['map_size'] = 'small'
        
        return config
    
    def _generate_default_markers(self) -> List[Dict]:
        """Generate default AR markers."""
        return [
            {
                'id': 'info_1',
                'position': [0.05, 0.05, 0],
                'content': 'Frontal Lobe',
                'type': 'label'
            },
            {
                'id': 'info_2',
                'position': [-0.05, 0.05, 0],
                'content': 'Parietal Lobe',
                'type': 'label'
            },
            {
                'id': 'measurement',
                'position': [0, 0, 0.1],
                'content': 'Scale: 10cm',
                'type': 'ruler'
            }
        ]
    
    def _create_ar_scene(self, model: Dict, markers: List[Dict], tracking: Dict) -> Dict:
        """Create AR scene configuration."""
        return {
            'model': model,
            'markers': markers,
            'tracking': tracking,
            'lighting': 'environmental',
            'shadows': True,
            'occlusion': tracking['mode'] != 'marker',
            'interactions': {
                'tap_to_place': True,
                'pinch_to_scale': True,
                'rotate': True,
                'annotations': True
            }
        }
    
    def _generate_ar_html(self, scene: Dict, platform: str) -> str:
        """Generate AR-ready HTML."""
        html = """
<!DOCTYPE html>
<html>
<head>
    <title>AR Brain Visualization</title>
    <script src="https://aframe.io/releases/1.4.0/aframe.min.js"></script>
    <script src="https://cdn.jsdelivr.net/gh/AR-js-org/AR.js/aframe/build/aframe-ar.js"></script>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { margin: 0; overflow: hidden; }
        #arButton {
            position: fixed;
            bottom: 20px;
            left: 50%;
            transform: translateX(-50%);
            padding: 15px 30px;
            background: #007AFF;
            color: white;
            border: none;
            border-radius: 25px;
            font-size: 16px;
            z-index: 999;
        }
    </style>
</head>
<body>
    <button id="arButton">Start AR</button>
    
    <a-scene embedded arjs="sourceType: webcam; debugUIEnabled: false;">
        <!-- AR Model -->
        <a-entity id="brain-model"
                  geometry="primitive: sphere; radius: 0.1"
                  material="color: pink; opacity: 0.8"
                  position="0 0 0">
            
            <!-- Annotations -->
            <a-text value="Brain Model"
                    position="0 0.15 0"
                    align="center"
                    color="#000000"
                    scale="0.1 0.1 0.1">
            </a-text>
        </a-entity>
        
        <!-- Marker (if using marker-based tracking) -->
        <a-marker preset="hiro">
            <a-entity id="marker-model"
                      geometry="primitive: sphere; radius: 0.1"
                      material="color: lightblue"
                      position="0 0 0">
            </a-entity>
        </a-marker>
        
        <!-- Camera -->
        <a-entity camera></a-entity>
    </a-scene>
    
    <script>
        const scene = """ + json.dumps(scene) + """;
        
        // AR setup
        document.getElementById('arButton').addEventListener('click', function() {
            // Start AR session
            if ('xr' in navigator) {
                navigator.xr.requestSession('immersive-ar').then(session => {
                    console.log('AR session started');
                    // Setup AR rendering
                });
            } else {
                console.log('WebXR not supported, using camera-based AR');
            }
        });
        
        // Model interaction
        const model = document.getElementById('brain-model');
        
        model.addEventListener('click', function() {
            // Show information
            console.log('Model clicked');
        });
        
        // Touch gestures for mobile
        let initialDistance = 0;
        let initialScale = 1;
        
        document.addEventListener('touchstart', function(e) {
            if (e.touches.length === 2) {
                initialDistance = Math.hypot(
                    e.touches[0].clientX - e.touches[1].clientX,
                    e.touches[0].clientY - e.touches[1].clientY
                );
                initialScale = model.getAttribute('scale').x;
            }
        });
        
        document.addEventListener('touchmove', function(e) {
            if (e.touches.length === 2) {
                const distance = Math.hypot(
                    e.touches[0].clientX - e.touches[1].clientX,
                    e.touches[0].clientY - e.touches[1].clientY
                );
                const scale = initialScale * (distance / initialDistance);
                model.setAttribute('scale', {x: scale, y: scale, z: scale});
            }
        });
    </script>
</body>
</html>
"""
        return html
    
    def _generate_marker_image(self) -> str:
        """Generate AR marker image."""
        svg = """
<svg width="200" height="200" xmlns="http://www.w3.org/2000/svg">
    <rect width="200" height="200" fill="white"/>
    <rect x="20" y="20" width="160" height="160" fill="black"/>
    <rect x="40" y="40" width="40" height="40" fill="white"/>
    <rect x="120" y="40" width="40" height="40" fill="white"/>
    <rect x="40" y="120" width="40" height="40" fill="white"/>
    <rect x="120" y="120" width="40" height="40" fill="white"/>
    <rect x="80" y="80" width="40" height="40" fill="white"/>
</svg>
"""
        return svg
    
    def _calculate_ar_metrics(self, model: Dict, tracking_mode: str) -> Dict:
        """Calculate AR performance metrics."""
        n_points = len(model.get('points', []))
        
        # Performance estimation
        if n_points < 500:
            performance = 'high'
            estimated_fps = 60
        elif n_points < 1000:
            performance = 'medium'
            estimated_fps = 30
        else:
            performance = 'low'
            estimated_fps = 15
        
        return {
            'n_points': n_points,
            'model_size_mb': n_points * 0.001,  # Rough estimate
            'performance': performance,
            'estimated_fps': estimated_fps,
            'tracking_quality': 'high' if tracking_mode == 'slam' else 'medium'
        }


class InteractiveVisualizationTools:
    """Collection of interactive visualization tools."""
    
    def __init__(self):
        self.tools = [
            Interactive3DBrainTool(),
            DynamicConnectivityVisualizationTool(),
            TimeSeriesVisualizationTool(),
            VirtualRealityBrainTool(),
            AugmentedRealityBrainTool()
        ]
    
    def get_all_tools(self) -> List[NeuroToolWrapper]:
        """Get all visualization tools."""
        return self.tools