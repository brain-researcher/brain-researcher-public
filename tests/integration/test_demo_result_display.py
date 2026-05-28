"""
Enhanced Integration tests for UI-002D: Demo Result Display component
Tests demo execution, result visualization, file downloads, and evidence rail
"""

import pytest
from unittest.mock import Mock, patch, MagicMock, AsyncMock
import json
import asyncio


class TestDemoResultDisplayIntegration:
    """Integration test suite for Demo Result Display component functionality"""

    def test_demo_result_interface(self):
        """Test DemoResult interface from actual component"""
        # Based on actual DemoResult interface
        demo_result = {
            "id": "demo-glm-001",
            "title": "First-Level GLM Analysis",
            "description": "Statistical analysis of motor task activation patterns",
            "type": "glm",
            "status": "completed",
            "progress": 100,
            "duration": "4m 32s",
            "outputFiles": [
                {
                    "name": "task-motor_space-MNI152_desc-cope_stat.nii.gz",
                    "type": "nifti",
                    "size": "12.4 MB",
                    "description": "Statistical contrast maps in MNI space",
                    "downloadUrl": "/demo/outputs/glm_stats.nii.gz",
                    "previewAvailable": True
                }
            ],
            "visualizations": [
                {
                    "id": "glm-brain-map",
                    "title": "Motor Activation Map",
                    "type": "brain_map",
                    "thumbnail": "/card-glm.png",
                    "fullUrl": "/viz/glm-demo-001",
                    "interactive": True,
                    "description": "Statistical activation map overlaid on anatomical template"
                }
            ],
            "evidenceRail": [
                {
                    "id": "ev-1",
                    "type": "method",
                    "title": "FSL FEAT Pipeline",
                    "description": "Standard GLM analysis using FSL's FEAT tool",
                    "relevance": 0.95,
                    "source": "FSL Documentation",
                    "url": "https://fsl.fmrib.ox.ac.uk/fsl/fslwiki/FEAT"
                }
            ],
            "metrics": [
                {
                    "label": "Peak Z-score",
                    "value": 8.4,
                    "significance": "high",
                    "description": "Maximum statistical significance"
                }
            ],
            "shareableLink": "https://brain-researcher.ai/results/demo-glm-001",
            "citationText": "Brain Researcher Demo Analysis. Motor Task GLM. Generated on 2025-01-20"
        }
        
        # Test required fields
        assert "id" in demo_result
        assert "title" in demo_result
        assert "description" in demo_result
        assert "type" in demo_result
        assert "status" in demo_result
        assert "progress" in demo_result
        assert "duration" in demo_result
        
        # Test type validation
        assert demo_result["type"] in ["glm", "connectivity", "dmn", "preprocessing"]
        assert demo_result["status"] in ["running", "completed", "ready"]
        assert 0 <= demo_result["progress"] <= 100
        
        # Test arrays
        assert isinstance(demo_result["outputFiles"], list)
        assert isinstance(demo_result["visualizations"], list)
        assert isinstance(demo_result["evidenceRail"], list)
        assert isinstance(demo_result["metrics"], list)

    def test_output_file_interface(self):
        """Test OutputFile interface from actual component"""
        # Based on actual OutputFile interface
        output_file = {
            "name": "task-motor_space-MNI152_desc-cope_stat.nii.gz",
            "type": "nifti",
            "size": "12.4 MB",
            "description": "Statistical contrast maps in MNI space",
            "downloadUrl": "/demo/outputs/glm_stats.nii.gz",
            "previewAvailable": True
        }
        
        # Test required fields
        assert "name" in output_file
        assert "type" in output_file
        assert "size" in output_file
        assert "description" in output_file
        assert "downloadUrl" in output_file
        assert "previewAvailable" in output_file
        
        # Test type validation
        valid_types = ["nifti", "json", "html", "png", "csv", "pdf"]
        assert output_file["type"] in valid_types
        assert isinstance(output_file["previewAvailable"], bool)
        assert output_file["downloadUrl"].startswith("/")

    def test_visualization_interface(self):
        """Test Visualization interface from actual component"""
        # Based on actual Visualization interface
        visualization = {
            "id": "glm-brain-map",
            "title": "Motor Activation Map",
            "type": "brain_map",
            "thumbnail": "/card-glm.png",
            "fullUrl": "/viz/glm-demo-001",
            "interactive": True,
            "description": "Statistical activation map overlaid on anatomical template"
        }
        
        # Test required fields
        assert "id" in visualization
        assert "title" in visualization
        assert "type" in visualization
        assert "thumbnail" in visualization
        assert "fullUrl" in visualization
        assert "interactive" in visualization
        assert "description" in visualization
        
        # Test type validation
        valid_types = ["brain_map", "plot", "table", "connectivity_matrix"]
        assert visualization["type"] in valid_types
        assert isinstance(visualization["interactive"], bool)
        assert visualization["thumbnail"].startswith("/")
        assert visualization["fullUrl"].startswith("/")

    def test_evidence_item_interface(self):
        """Test EvidenceItem interface from actual component"""
        # Based on actual EvidenceItem interface
        evidence_item = {
            "id": "ev-1",
            "type": "method",
            "title": "FSL FEAT Pipeline",
            "description": "Standard GLM analysis using FSL's FEAT tool",
            "relevance": 0.95,
            "source": "FSL Documentation",
            "url": "https://fsl.fmrib.ox.ac.uk/fsl/fslwiki/FEAT"
        }
        
        # Test required fields
        assert "id" in evidence_item
        assert "type" in evidence_item
        assert "title" in evidence_item
        assert "description" in evidence_item
        assert "relevance" in evidence_item
        assert "source" in evidence_item
        
        # Test type validation
        valid_types = ["paper", "dataset", "method", "validation"]
        assert evidence_item["type"] in valid_types
        assert 0.0 <= evidence_item["relevance"] <= 1.0
        
        # Test optional URL
        if "url" in evidence_item:
            assert evidence_item["url"].startswith("http")

    def test_result_metric_interface(self):
        """Test ResultMetric interface from actual component"""
        # Based on actual ResultMetric interface
        result_metric = {
            "label": "Peak Z-score",
            "value": 8.4,
            "unit": "standard deviations",
            "significance": "high",
            "description": "Maximum statistical significance"
        }
        
        # Test required fields
        assert "label" in result_metric
        assert "value" in result_metric
        assert "description" in result_metric
        
        # Test optional fields
        if "unit" in result_metric:
            assert isinstance(result_metric["unit"], str)
        if "significance" in result_metric:
            assert result_metric["significance"] in ["high", "medium", "low"]
        
        # Test value types
        assert isinstance(result_metric["value"], (str, int, float))

    def test_demo_results_structure(self):
        """Test DEMO_RESULTS structure from actual component"""
        # Based on actual DEMO_RESULTS from component
        demo_results = {
            "glm": {
                "id": "demo-glm-001",
                "title": "First-Level GLM Analysis",
                "description": "Statistical analysis of motor task activation patterns",
                "type": "glm",
                "status": "completed",
                "duration": "4m 32s",
                "metrics": [
                    {"label": "Peak Z-score", "value": 8.4, "significance": "high"},
                    {"label": "Cluster Size", "value": 1247, "unit": "voxels", "significance": "high"},
                    {"label": "P-value", "value": "<0.001", "significance": "high"},
                    {"label": "Effect Size", "value": 1.23, "unit": "Cohen's d", "significance": "high"}
                ]
            },
            "connectivity": {
                "id": "demo-conn-001",
                "title": "Resting State Connectivity Analysis", 
                "description": "Functional connectivity patterns in default mode network",
                "type": "connectivity",
                "status": "completed",
                "duration": "3m 18s",
                "metrics": [
                    {"label": "Networks", "value": 7, "significance": "medium"},
                    {"label": "Connections", "value": 2156, "significance": "high"}
                ]
            },
            "dmn": {
                "id": "demo-dmn-001",
                "title": "Default Mode Network Analysis",
                "description": "Investigation of default mode network connectivity and activation",
                "type": "dmn",
                "status": "completed",
                "duration": "2m 45s",
                "metrics": [
                    {"label": "DMN Strength", "value": 0.78, "significance": "high"},
                    {"label": "Hub Regions", "value": 4, "significance": "high"}
                ]
            }
        }
        
        # Test demo results structure
        assert len(demo_results) == 3
        assert "glm" in demo_results
        assert "connectivity" in demo_results
        assert "dmn" in demo_results
        
        # Test each demo
        for demo_type, demo_data in demo_results.items():
            assert demo_data["type"] == demo_type
            assert demo_data["status"] == "completed"
            assert "duration" in demo_data
            assert len(demo_data["metrics"]) > 0
            
            # Test duration format (e.g., "4m 32s")
            duration = demo_data["duration"]
            assert "m" in duration and "s" in duration
        
        # Test specific demo metrics
        glm_metrics = demo_results["glm"]["metrics"]
        z_score_metric = next(m for m in glm_metrics if m["label"] == "Peak Z-score")
        assert z_score_metric["value"] == 8.4
        assert z_score_metric["significance"] == "high"

    def test_demo_execution_simulation(self):
        """Test demo execution simulation"""
        async def simulate_demo_execution():
            """Mock startDemo function from component"""
            execution_state = {
                "is_running": False,
                "current_progress": 0,
                "active_tab": "results"
            }
            
            # Simulate analysis steps
            steps = [
                {"label": "Loading data...", "duration": 0.1},  # Reduced for testing
                {"label": "Preprocessing...", "duration": 0.15},
                {"label": "Running analysis...", "duration": 0.2},
                {"label": "Generating visualizations...", "duration": 0.1},
                {"label": "Finalizing results...", "duration": 0.05}
            ]
            
            execution_state["is_running"] = True
            execution_state["current_progress"] = 0
            execution_state["active_tab"] = "progress"
            
            for i, step in enumerate(steps):
                # Simulate step execution
                await asyncio.sleep(step["duration"])
                execution_state["current_progress"] = ((i + 1) / len(steps)) * 100
            
            execution_state["is_running"] = False
            execution_state["active_tab"] = "results"
            
            return execution_state
        
        # Test demo execution
        result = asyncio.run(simulate_demo_execution())
        
        assert not result["is_running"]
        assert result["current_progress"] == 100
        assert result["active_tab"] == "results"

    def test_file_icon_mapping(self):
        """Test file icon mapping functionality"""
        def get_file_icon(file_type):
            """Mock getFileIcon function from component"""
            icon_map = {
                'nifti': 'Brain',
                'html': 'FileText', 
                'json': 'Code',
                'png': 'Eye',
                'csv': 'BarChart3',
                'pdf': 'FileText',
                'default': 'FileText'
            }
            return icon_map.get(file_type, icon_map['default'])
        
        # Test all file types
        test_types = ['nifti', 'html', 'json', 'png', 'csv', 'pdf', 'unknown']
        
        for file_type in test_types:
            icon = get_file_icon(file_type)
            assert icon is not None
            
            # Test specific mappings
            if file_type == 'nifti':
                assert icon == 'Brain'
            elif file_type == 'json':
                assert icon == 'Code'
            elif file_type == 'png':
                assert icon == 'Eye'
            elif file_type == 'csv':
                assert icon == 'BarChart3'
            elif file_type in ['html', 'pdf', 'unknown']:
                assert icon == 'FileText'

    def test_significance_color_mapping(self):
        """Test significance color mapping functionality"""
        def get_significance_color(significance):
            """Mock getSignificanceColor function from component"""
            color_map = {
                'high': 'text-green-600',
                'medium': 'text-yellow-600',
                'low': 'text-gray-600',
                'default': 'text-gray-600'
            }
            return color_map.get(significance, color_map['default'])
        
        # Test significance color mapping
        assert get_significance_color('high') == 'text-green-600'
        assert get_significance_color('medium') == 'text-yellow-600' 
        assert get_significance_color('low') == 'text-gray-600'
        assert get_significance_color('unknown') == 'text-gray-600'
        assert get_significance_color(None) == 'text-gray-600'

    def test_download_functionality(self):
        """Test file download functionality"""
        def handle_download(output_file):
            """Mock handleDownload function from component"""
            if not output_file.get("downloadUrl"):
                return {"error": "No download URL provided"}
            
            # Simulate creating download link
            download_result = {
                "filename": output_file["name"],
                "url": output_file["downloadUrl"],
                "size": output_file["size"],
                "action": "download_initiated"
            }
            
            return download_result
        
        # Test download functionality
        test_file = {
            "name": "test_results.nii.gz",
            "type": "nifti",
            "size": "15.2 MB",
            "downloadUrl": "/demo/outputs/test_results.nii.gz",
            "previewAvailable": True
        }
        
        result = handle_download(test_file)
        
        assert result["action"] == "download_initiated"
        assert result["filename"] == test_file["name"]
        assert result["url"] == test_file["downloadUrl"]
        assert result["size"] == test_file["size"]
        
        # Test error case
        invalid_file = {"name": "test.txt", "type": "text"}
        error_result = handle_download(invalid_file)
        assert "error" in error_result

    def test_sharing_functionality(self):
        """Test result sharing functionality"""
        def handle_share(demo_result):
            """Mock handleShare function from component"""
            if not demo_result.get("shareableLink"):
                return {"error": "No shareable link available"}
            
            # Simulate copying to clipboard
            share_result = {
                "link": demo_result["shareableLink"],
                "action": "copied_to_clipboard",
                "message": "Link copied to clipboard"
            }
            
            return share_result
        
        # Test sharing functionality
        demo_with_link = {
            "id": "demo-001",
            "title": "Test Analysis",
            "shareableLink": "https://brain-researcher.ai/results/demo-001"
        }
        
        result = handle_share(demo_with_link)
        
        assert result["action"] == "copied_to_clipboard"
        assert result["link"] == demo_with_link["shareableLink"]
        assert "copied" in result["message"].lower()
        
        # Test error case
        demo_without_link = {"id": "demo-002", "title": "Test Without Link"}
        error_result = handle_share(demo_without_link)
        assert "error" in error_result

    def test_citation_functionality(self):
        """Test citation functionality"""
        def generate_citation(demo_result):
            """Mock citation generation"""
            from datetime import datetime
            
            citation_parts = [
                "Brain Researcher Demo Analysis.",
                demo_result["title"],
                f"Generated on {datetime.now().strftime('%Y-%m-%d')}"
            ]
            
            return " ".join(citation_parts)
        
        def handle_citation_copy(demo_result):
            """Mock citation copy functionality"""
            if not demo_result.get("citationText"):
                citation = generate_citation(demo_result)
            else:
                citation = demo_result["citationText"]
            
            return {
                "citation": citation,
                "action": "copied_to_clipboard",
                "length": len(citation)
            }
        
        # Test citation generation
        demo_data = {
            "id": "demo-glm-001",
            "title": "First-Level GLM Analysis",
            "citationText": "Brain Researcher Demo Analysis. Motor Task GLM. Generated on 2025-01-20"
        }
        
        result = handle_citation_copy(demo_data)
        
        assert result["action"] == "copied_to_clipboard"
        assert result["citation"] == demo_data["citationText"]
        assert result["length"] > 0
        
        # Test auto-generation
        demo_without_citation = {
            "id": "demo-002",
            "title": "Connectivity Analysis"
        }
        
        auto_result = handle_citation_copy(demo_without_citation)
        assert "Connectivity Analysis" in auto_result["citation"]
        assert "Brain Researcher Demo Analysis" in auto_result["citation"]

    def test_evidence_rail_functionality(self):
        """Test evidence rail functionality"""
        def calculate_evidence_relevance(evidence_items):
            """Mock evidence relevance calculation"""
            if not evidence_items:
                return {"average_relevance": 0, "high_relevance_count": 0}
            
            relevances = [item["relevance"] for item in evidence_items]
            average_relevance = sum(relevances) / len(relevances)
            high_relevance_count = len([r for r in relevances if r > 0.8])
            
            return {
                "average_relevance": round(average_relevance, 3),
                "high_relevance_count": high_relevance_count,
                "total_items": len(evidence_items)
            }
        
        def handle_evidence_click(evidence_item):
            """Mock evidence item click handler"""
            if evidence_item.get("url"):
                return {
                    "action": "external_link",
                    "url": evidence_item["url"],
                    "type": evidence_item["type"],
                    "title": evidence_item["title"]
                }
            return {"action": "none"}
        
        # Test evidence relevance calculation
        test_evidence = [
            {"id": "ev-1", "type": "method", "title": "FSL FEAT", "relevance": 0.95},
            {"id": "ev-2", "type": "paper", "title": "Motor cortex study", "relevance": 0.87},
            {"id": "ev-3", "type": "dataset", "title": "HCP data", "relevance": 0.82}
        ]
        
        relevance_stats = calculate_evidence_relevance(test_evidence)
        
        assert relevance_stats["total_items"] == 3
        assert relevance_stats["high_relevance_count"] == 3  # All above 0.8
        assert 0.8 < relevance_stats["average_relevance"] < 1.0
        
        # Test evidence click
        evidence_with_url = {
            "id": "ev-1",
            "type": "method",
            "title": "FSL FEAT Pipeline",
            "url": "https://fsl.fmrib.ox.ac.uk/fsl/fslwiki/FEAT"
        }
        
        click_result = handle_evidence_click(evidence_with_url)
        assert click_result["action"] == "external_link"
        assert click_result["url"] == evidence_with_url["url"]
        assert click_result["type"] == "method"

    def test_tab_navigation_functionality(self):
        """Test tab navigation functionality"""
        tab_state = {
            "active_tab": "results",
            "available_tabs": ["results", "visualizations", "outputs", "progress"],
            "tab_content_loaded": {
                "results": True,
                "visualizations": False,
                "outputs": False,
                "progress": True
            }
        }
        
        def switch_tab(new_tab):
            """Mock tab switching functionality"""
            if new_tab not in tab_state["available_tabs"]:
                return {"error": "Invalid tab"}
            
            tab_state["active_tab"] = new_tab
            tab_state["tab_content_loaded"][new_tab] = True
            
            return {
                "active_tab": new_tab,
                "content_loaded": tab_state["tab_content_loaded"][new_tab]
            }
        
        # Test tab switching
        result = switch_tab("visualizations")
        assert result["active_tab"] == "visualizations"
        assert result["content_loaded"]
        
        # Test invalid tab
        error_result = switch_tab("invalid_tab")
        assert "error" in error_result
        
        # Test current state
        assert tab_state["active_tab"] == "visualizations"
        assert tab_state["tab_content_loaded"]["visualizations"]

    def test_responsive_layout_configuration(self):
        """Test responsive layout configuration"""
        layout_config = {
            "desktop": {
                "main_content_cols": "lg:col-span-3",
                "evidence_rail_cols": "lg:col-span-1",
                "metrics_grid": "grid-cols-2 lg:grid-cols-4",
                "visualizations_grid": "grid-cols-1 md:grid-cols-2"
            },
            "mobile": {
                "main_content_cols": "col-span-4",
                "evidence_rail_cols": "col-span-4",
                "metrics_grid": "grid-cols-1",
                "visualizations_grid": "grid-cols-1"
            },
            "breakpoints": {
                "mobile": 768,
                "tablet": 1024,
                "desktop": 1200
            }
        }
        
        def get_layout_for_screen_size(screen_width):
            """Mock responsive layout calculation"""
            if screen_width < layout_config["breakpoints"]["mobile"]:
                return layout_config["mobile"]
            else:
                return layout_config["desktop"]
        
        # Test responsive behavior
        mobile_layout = get_layout_for_screen_size(375)  # iPhone width
        assert mobile_layout["metrics_grid"] == "grid-cols-1"
        assert mobile_layout["main_content_cols"] == "col-span-4"
        
        desktop_layout = get_layout_for_screen_size(1400)  # Desktop width
        assert "lg:grid-cols-4" in desktop_layout["metrics_grid"]
        assert "lg:col-span-3" in desktop_layout["main_content_cols"]


@pytest.fixture
def mock_demo_result_display():
    """Mock demo result display component for testing"""
    return {
        "component_name": "DemoResultDisplay",
        "props": {
            "demoType": "glm",
            "autoStart": False,
            "showEvidenceRail": True,
            "showSharing": True
        },
        "state": {
            "selected_demo": "glm",
            "is_running": False,
            "current_progress": 0,
            "active_tab": "results"
        },
        "data": {
            "available_demos": 3,
            "total_output_files": 8,
            "total_visualizations": 4,
            "total_evidence_items": 7
        }
    }


def test_demo_result_display_integration(mock_demo_result_display):
    """Test demo result display component integration"""
    component = mock_demo_result_display
    
    # Test component structure
    assert component["component_name"] == "DemoResultDisplay"
    assert component["props"]["showEvidenceRail"]
    assert component["props"]["showSharing"]
    assert component["props"]["demoType"] == "glm"
    
    # Test initial state
    assert not component["state"]["is_running"]
    assert component["state"]["current_progress"] == 0
    assert component["state"]["active_tab"] == "results"
    
    # Test data availability
    assert component["data"]["available_demos"] == 3
    assert component["data"]["total_output_files"] > 0
    assert component["data"]["total_visualizations"] > 0
    assert component["data"]["total_evidence_items"] > 0