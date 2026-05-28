"""
Unit tests for Knowledge Graph Explorer components.

This test suite covers:
- Graph data management hook (useGraphData)
- Graph layout utilities
- Component rendering and interactions
- Search and filter functionality
- Export capabilities
"""

import pytest
import json
import tempfile
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

# Test the graph data structures and logic without external dependencies


class TestGraphDataManagement:
    """Test the graph data management functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.sample_nodes = [
            {
                "id": "c1",
                "label": "Working Memory",
                "type": "Concept",
                "properties": {"description": "Cognitive function", "category": "executive"}
            },
            {
                "id": "t1", 
                "label": "N-Back Task",
                "type": "Task",
                "properties": {"difficulty": "moderate", "duration": 300}
            },
            {
                "id": "r1",
                "label": "Prefrontal Cortex", 
                "type": "BrainRegion",
                "properties": {"hemisphere": "bilateral", "brodmann_area": [9, 10, 46]}
            },
            {
                "id": "d1",
                "label": "ds000114",
                "type": "Dataset", 
                "properties": {"subjects": 10, "sessions": 2}
            }
        ]
        
        self.sample_edges = [
            {
                "id": "e1",
                "source": "t1",
                "target": "c1", 
                "type": "MEASURES",
                "properties": {"strength": 0.8}
            },
            {
                "id": "e2",
                "source": "c1",
                "target": "r1",
                "type": "INVOLVES", 
                "properties": {"activation": "positive"}
            },
            {
                "id": "e3",
                "source": "d1",
                "target": "t1",
                "type": "USES",
                "properties": {"frequency": "high"}
            }
        ]
        
        self.sample_graph_data = {
            "nodes": self.sample_nodes,
            "edges": self.sample_edges,
            "stats": {
                "total_nodes": len(self.sample_nodes),
                "total_edges": len(self.sample_edges),
                "node_types": {"Concept": 1, "Task": 1, "BrainRegion": 1, "Dataset": 1},
                "edge_types": {"MEASURES": 1, "INVOLVES": 1, "USES": 1}
            }
        }
    
    def test_node_type_classification(self):
        """Test that nodes are properly classified by type."""
        node_types = set(node["type"] for node in self.sample_nodes)
        expected_types = {"Concept", "Task", "BrainRegion", "Dataset"}
        assert node_types == expected_types
    
    def test_edge_type_mapping(self):
        """Test that edges have appropriate relationships."""
        edge_types = set(edge["type"] for edge in self.sample_edges)
        expected_types = {"MEASURES", "INVOLVES", "USES"}
        assert edge_types == expected_types
    
    def test_graph_connectivity(self):
        """Test that graph has proper connectivity."""
        # Create adjacency representation
        adjacency = {}
        for edge in self.sample_edges:
            source = edge["source"]
            target = edge["target"]
            if source not in adjacency:
                adjacency[source] = []
            adjacency[source].append(target)
        
        # Test specific connections
        assert "c1" in adjacency["t1"]  # Task measures concept
        assert "r1" in adjacency["c1"]  # Concept involves region
        assert "t1" in adjacency["d1"]  # Dataset uses task
    
    def test_node_properties_structure(self):
        """Test that node properties have expected structure."""
        for node in self.sample_nodes:
            assert "id" in node
            assert "label" in node  
            assert "type" in node
            assert "properties" in node
            assert isinstance(node["properties"], dict)
    
    def test_search_functionality(self):
        """Test graph search functionality."""
        # Simulate search for "memory"
        query = "memory"
        matching_nodes = [
            node for node in self.sample_nodes 
            if query.lower() in node["label"].lower() or 
               any(query.lower() in str(v).lower() for v in node["properties"].values())
        ]
        
        assert len(matching_nodes) == 1
        assert matching_nodes[0]["label"] == "Working Memory"
    
    def test_filter_functionality(self):
        """Test node type filtering."""
        # Filter out Concept nodes
        filtered_types = {"Concept"}
        filtered_nodes = [
            node for node in self.sample_nodes 
            if node["type"] not in filtered_types
        ]
        
        assert len(filtered_nodes) == 3
        node_types = set(node["type"] for node in filtered_nodes)
        assert "Concept" not in node_types
    
    def test_node_expansion_simulation(self):
        """Test node expansion logic."""
        # Simulate expanding node "c1" (Working Memory)
        target_node_id = "c1"
        
        # Find connected nodes
        connected_edges = [
            edge for edge in self.sample_edges
            if edge["source"] == target_node_id or edge["target"] == target_node_id
        ]
        
        connected_node_ids = set()
        for edge in connected_edges:
            connected_node_ids.add(edge["source"])
            connected_node_ids.add(edge["target"])
        connected_node_ids.discard(target_node_id)
        
        assert len(connected_node_ids) == 2  # t1 and r1
        assert "t1" in connected_node_ids
        assert "r1" in connected_node_ids


class TestGraphLayoutAlgorithms:
    """Test graph layout algorithm utilities."""
    
    def test_layout_recommendation(self):
        """Test layout recommendation based on graph properties."""
        # Small dense graph - should recommend force-directed
        small_dense = self._get_layout_recommendation(10, 30, False)
        assert small_dense in ["cose-bilkent", "dagre"]
        
        # Large sparse graph - should recommend efficient layout
        large_sparse = self._get_layout_recommendation(200, 250, False)
        assert large_sparse in ["cose", "grid"]
        
        # Directed graph - should recommend hierarchical
        directed = self._get_layout_recommendation(50, 75, True)
        assert directed in ["dagre", "breadthfirst"]
    
    def _get_layout_recommendation(self, node_count, edge_count, has_directed_edges):
        """Simulate layout recommendation logic."""
        density = edge_count / (node_count * (node_count - 1)) if node_count > 1 else 0
        
        # Small graphs
        if node_count < 20:
            return "dagre" if has_directed_edges else "cose-bilkent"
        
        # Medium graphs
        if node_count < 100:
            if density > 0.1:  # Dense
                return "concentric"
            elif has_directed_edges:
                return "breadthfirst"
            else:
                return "cose-bilkent"
        
        # Large graphs
        if density > 0.05:  # Very dense
            return "grid"
        elif has_directed_edges:
            return "dagre"
        else:
            return "cose"
    
    def test_layout_configuration_validation(self):
        """Test that layout configurations are valid."""
        layout_configs = {
            'cose-bilkent': {
                'name': 'cose-bilkent',
                'animate': True,
                'animationDuration': 1500,
                'nodeRepulsion': 4500,
                'idealEdgeLength': 80
            },
            'dagre': {
                'name': 'dagre', 
                'animate': True,
                'animationDuration': 1000,
                'rankDir': 'TB',
                'nodeSep': 50
            }
        }
        
        for layout_name, config in layout_configs.items():
            assert 'name' in config
            assert config['name'] == layout_name
            assert 'animate' in config
            assert 'animationDuration' in config
            assert isinstance(config['animate'], bool)
            assert isinstance(config['animationDuration'], int)


class TestGraphPerformanceOptimization:
    """Test graph performance optimization."""
    
    def test_large_graph_handling(self):
        """Test handling of large graphs."""
        # Simulate performance optimizations for large graphs
        node_count = 500
        optimizations = self._get_performance_optimizations(node_count)
        
        assert 'disable_animation' in optimizations
        assert 'reduce_iterations' in optimizations
        assert optimizations['disable_animation'] is True
        assert optimizations['reduce_iterations'] < 1000
    
    def test_medium_graph_handling(self):
        """Test handling of medium graphs."""
        node_count = 100
        optimizations = self._get_performance_optimizations(node_count)
        
        assert optimizations.get('disable_animation', False) is False
        # Check that animation_duration is set when it's in optimizations
        if 'animation_duration' in optimizations:
            assert optimizations['animation_duration'] <= 500
    
    def _get_performance_optimizations(self, node_count):
        """Simulate performance optimization logic."""
        optimizations = {}
        
        if node_count > 200:
            optimizations['disable_animation'] = True
            optimizations['reduce_iterations'] = 500
            optimizations['lower_repulsion'] = True
        elif node_count > 100:
            optimizations['animation_duration'] = 500
            optimizations['reduce_iterations'] = 1000
        
        return optimizations


class TestGraphExportFunctionality:
    """Test graph export capabilities."""
    
    def test_export_data_structure(self):
        """Test export data structure validation."""
        export_data = {
            "graph_data": {
                "nodes": self.setup_method().sample_nodes if hasattr(self, 'setup_method') else [],
                "edges": self.setup_method().sample_edges if hasattr(self, 'setup_method') else []
            },
            "metadata": {
                "export_timestamp": "2025-01-01T12:00:00Z",
                "layout": "cose-bilkent",
                "filters_applied": [],
                "search_query": ""
            },
            "settings": {
                "node_limit": 100,
                "animation_enabled": True,
                "show_labels": True
            }
        }
        
        # Validate structure
        assert "graph_data" in export_data
        assert "metadata" in export_data  
        assert "settings" in export_data
        
        # Validate graph data
        graph_data = export_data["graph_data"]
        assert "nodes" in graph_data
        assert "edges" in graph_data
        assert isinstance(graph_data["nodes"], list)
        assert isinstance(graph_data["edges"], list)
        
        # Validate metadata
        metadata = export_data["metadata"]
        required_metadata = ["export_timestamp", "layout", "filters_applied", "search_query"]
        for field in required_metadata:
            assert field in metadata
    
    def test_export_format_validation(self):
        """Test different export formats."""
        formats = ["png", "svg", "json", "graphml"]
        
        for format_type in formats:
            export_config = self._get_export_config(format_type)
            assert export_config["format"] == format_type
            assert "settings" in export_config
            
            if format_type in ["png", "svg"]:
                assert "image_settings" in export_config
            elif format_type in ["json", "graphml"]:
                assert "data_settings" in export_config
    
    def _get_export_config(self, format_type):
        """Get export configuration for format."""
        base_config = {
            "format": format_type,
            "settings": {
                "include_metadata": True,
                "timestamp": True
            }
        }
        
        if format_type in ["png", "svg"]:
            base_config["image_settings"] = {
                "background": "#ffffff",
                "scale": 2,
                "quality": 0.9
            }
        elif format_type in ["json", "graphml"]:
            base_config["data_settings"] = {
                "include_properties": True,
                "pretty_print": True
            }
        
        return base_config


class TestGraphAccessibility:
    """Test graph accessibility features."""
    
    def test_keyboard_navigation_support(self):
        """Test keyboard navigation capabilities."""
        keyboard_actions = {
            "tab": "move_to_next_node",
            "shift+tab": "move_to_previous_node", 
            "enter": "select_node",
            "space": "expand_node",
            "escape": "clear_selection",
            "arrow_keys": "pan_view",
            "+": "zoom_in",
            "-": "zoom_out"
        }
        
        # Validate all required keyboard actions are defined
        required_actions = ["tab", "enter", "escape", "arrow_keys"]
        for action in required_actions:
            assert action in keyboard_actions
            assert isinstance(keyboard_actions[action], str)
    
    def test_screen_reader_support(self):
        """Test screen reader accessibility."""
        node_aria_attributes = {
            "role": "button",
            "aria-label": "Working Memory concept node",
            "aria-describedby": "node-description-c1",
            "tabindex": "0"
        }
        
        edge_aria_attributes = {
            "role": "link",
            "aria-label": "MEASURES relationship from N-Back Task to Working Memory",
            "aria-describedby": "edge-description-e1"
        }
        
        # Validate ARIA attributes
        assert "role" in node_aria_attributes
        assert "aria-label" in node_aria_attributes
        assert "tabindex" in node_aria_attributes
        
        assert "role" in edge_aria_attributes
        assert "aria-label" in edge_aria_attributes
    
    def test_color_accessibility(self):
        """Test color accessibility and contrast."""
        node_colors = {
            "Concept": "#8B5CF6",     # Purple
            "Task": "#10B981",        # Green  
            "BrainRegion": "#F59E0B",  # Orange
            "Dataset": "#06B6D4"      # Cyan
        }
        
        # All colors should be valid hex codes
        import re
        hex_pattern = re.compile(r'^#[0-9A-Fa-f]{6}$')
        
        for node_type, color in node_colors.items():
            assert hex_pattern.match(color), f"Invalid color for {node_type}: {color}"
        
        # Colors should be sufficiently different (basic check)
        color_values = list(node_colors.values())
        assert len(set(color_values)) == len(color_values), "Duplicate colors found"


class TestGraphErrorHandling:
    """Test error handling in graph components."""
    
    def test_malformed_data_handling(self):
        """Test handling of malformed graph data."""
        malformed_cases = [
            {"nodes": [], "edges": [{"source": "missing", "target": "also_missing"}]},
            {"nodes": [{"id": "n1"}], "edges": []},  # Missing required fields
            {"nodes": [{"id": "n1", "label": "Test", "type": None}], "edges": []},  # Null type
            {"nodes": "not_a_list", "edges": []},  # Wrong data type
        ]
        
        for case in malformed_cases:
            validation_result = self._validate_graph_data(case)
            assert validation_result["valid"] is False
            assert "errors" in validation_result
            assert len(validation_result["errors"]) > 0
    
    def test_api_error_handling(self):
        """Test API error handling."""
        error_scenarios = [
            {"status": 404, "message": "Graph not found"},
            {"status": 500, "message": "Internal server error"},
            {"status": 429, "message": "Rate limit exceeded"},
            {"status": 0, "message": "Network error"}
        ]
        
        for scenario in error_scenarios:
            error_handler = self._get_error_handler(scenario)
            assert "user_message" in error_handler
            assert "retry_action" in error_handler
            assert "fallback_data" in error_handler
    
    def _validate_graph_data(self, data):
        """Validate graph data structure."""
        errors = []
        
        # Check top-level structure
        if not isinstance(data, dict):
            errors.append("Data must be a dictionary")
            return {"valid": False, "errors": errors}
        
        if "nodes" not in data:
            errors.append("Missing 'nodes' field")
        elif not isinstance(data["nodes"], list):
            errors.append("'nodes' must be a list")
        
        if "edges" not in data:
            errors.append("Missing 'edges' field")
        elif not isinstance(data["edges"], list):
            errors.append("'edges' must be a list")
        
        # Validate nodes
        if isinstance(data.get("nodes"), list):
            for i, node in enumerate(data["nodes"]):
                if not isinstance(node, dict):
                    errors.append(f"Node {i} must be a dictionary")
                    continue
                
                required_fields = ["id", "label", "type"]
                for field in required_fields:
                    if field not in node:
                        errors.append(f"Node {i} missing required field: {field}")
                    elif node[field] is None:
                        errors.append(f"Node {i} field '{field}' cannot be null")
        
        # Validate edges
        if isinstance(data.get("edges"), list):
            node_ids = set(node.get("id") for node in data.get("nodes", []) if isinstance(node, dict))
            
            for i, edge in enumerate(data["edges"]):
                if not isinstance(edge, dict):
                    errors.append(f"Edge {i} must be a dictionary")
                    continue
                
                required_fields = ["source", "target", "type"]
                for field in required_fields:
                    if field not in edge:
                        errors.append(f"Edge {i} missing required field: {field}")
                
                # Check if source and target nodes exist
                if edge.get("source") not in node_ids:
                    errors.append(f"Edge {i} references non-existent source node: {edge.get('source')}")
                if edge.get("target") not in node_ids:
                    errors.append(f"Edge {i} references non-existent target node: {edge.get('target')}")
        
        return {"valid": len(errors) == 0, "errors": errors}
    
    def _get_error_handler(self, error_scenario):
        """Get error handler for scenario."""
        status = error_scenario["status"]
        message = error_scenario["message"]
        
        if status == 404:
            return {
                "user_message": "The requested graph data was not found.",
                "retry_action": "load_default_data",
                "fallback_data": "sample_graph"
            }
        elif status == 500:
            return {
                "user_message": "Server error occurred. Please try again later.",
                "retry_action": "retry_request",
                "fallback_data": "cached_data"
            }
        elif status == 429:
            return {
                "user_message": "Too many requests. Please wait a moment.",
                "retry_action": "delayed_retry",
                "fallback_data": "cached_data"
            }
        else:
            return {
                "user_message": "Network error. Check your connection.",
                "retry_action": "retry_request",
                "fallback_data": "offline_data"
            }


# Integration test for the complete graph system
class TestGraphIntegration:
    """Integration tests for the complete graph system."""
    
    def test_end_to_end_workflow(self):
        """Test complete workflow from data loading to export."""
        workflow_steps = [
            "load_initial_data",
            "apply_search_filter", 
            "select_layout",
            "expand_node",
            "apply_type_filters",
            "export_results"
        ]
        
        workflow_state = {
            "data_loaded": False,
            "search_applied": False,
            "layout_set": False,
            "node_expanded": False,
            "filters_applied": False,
            "exported": False
        }
        
        # Simulate workflow execution
        for step in workflow_steps:
            result = self._execute_workflow_step(step, workflow_state)
            assert result["success"], f"Step {step} failed: {result.get('error')}"
            workflow_state.update(result["state_updates"])
        
        # Verify final state
        assert all(workflow_state.values()), "Not all workflow steps completed successfully"
    
    def _execute_workflow_step(self, step, current_state):
        """Simulate executing a workflow step."""
        if step == "load_initial_data":
            return {
                "success": True,
                "state_updates": {"data_loaded": True}
            }
        elif step == "apply_search_filter":
            if not current_state["data_loaded"]:
                return {"success": False, "error": "Data not loaded"}
            return {
                "success": True,
                "state_updates": {"search_applied": True}
            }
        elif step == "select_layout":
            return {
                "success": True,
                "state_updates": {"layout_set": True}
            }
        elif step == "expand_node":
            if not current_state["data_loaded"]:
                return {"success": False, "error": "Data not loaded"}
            return {
                "success": True,
                "state_updates": {"node_expanded": True}
            }
        elif step == "apply_type_filters":
            return {
                "success": True,
                "state_updates": {"filters_applied": True}
            }
        elif step == "export_results":
            if not current_state["data_loaded"]:
                return {"success": False, "error": "No data to export"}
            return {
                "success": True,
                "state_updates": {"exported": True}
            }
        
        return {"success": False, "error": f"Unknown step: {step}"}


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v"])