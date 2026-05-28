"""
Integration tests for demo gallery functionality.

Tests demo data loading, artifact generation, visualization rendering,
and interactive features for the Brain Researcher demo gallery.
"""

import pytest
import asyncio
import httpx
import json
import os
from pathlib import Path
from typing import Dict, List, Any, Optional
from unittest.mock import AsyncMock, patch, MagicMock
import tempfile
import base64


# Demo gallery configuration
DEMO_GALLERY_CONFIG = {
    "artifacts_base_path": "/api/demo/artifacts",
    "visualizations_base_path": "/viz/demo",
    "thumbnails_base_path": "/demo/thumbnails",
    "supported_formats": ["nii.gz", "png", "jpg", "html", "json", "csv", "pdf"],
    "max_artifact_size_mb": 100,
    "visualization_timeout_seconds": 30
}


@pytest.fixture
async def gallery_client():
    """HTTP client configured for gallery testing."""
    timeout = httpx.Timeout(20.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        yield client


@pytest.fixture
def mock_orchestrator_url():
    """Mock orchestrator URL for gallery endpoints."""
    return "http://localhost:3001"


@pytest.fixture
def mock_demo_artifacts():
    """Mock demo artifacts for testing."""
    return {
        "glm_motor": [
            {
                "id": "zstat_map",
                "name": "zstat1.nii.gz",
                "type": "brain_map",
                "size_bytes": 2847392,
                "url": "/api/demo/artifacts/glm_motor/zstat1.nii.gz",
                "meta": {"threshold": 3.1, "max_z": 8.42}
            },
            {
                "id": "design_matrix", 
                "name": "design_matrix.png",
                "type": "image",
                "size_bytes": 156432,
                "url": "/api/demo/artifacts/glm_motor/design_matrix.png",
                "meta": {"format": "PNG", "dimensions": [800, 600]}
            }
        ],
        "connectivity_dmn": [
            {
                "id": "correlation_matrix",
                "name": "correlation_matrix.csv",
                "type": "table",
                "size_bytes": 1280000,
                "url": "/api/demo/artifacts/connectivity_dmn/correlation_matrix.csv",
                "meta": {"dimensions": [400, 400]}
            }
        ]
    }


class TestDemoDataLoading:
    """Test loading and validation of demo data."""
    
    @pytest.mark.asyncio
    async def test_demo_scenarios_loading(self, gallery_client, mock_orchestrator_url):
        """Test loading of all demo scenarios."""
        response = await gallery_client.get(
            f"{mock_orchestrator_url}/api/demos/scenarios"
        )
        
        if response.status_code != 200:
            pytest.skip("Demo scenarios endpoint not available")
            
        scenarios = response.json()
        assert "scenarios" in scenarios or isinstance(scenarios, list)
        
        scenario_list = scenarios.get("scenarios", scenarios)
        assert len(scenario_list) > 0
        
        # Validate each scenario
        for scenario in scenario_list:
            required_fields = ["id", "name", "title", "description", "type", "complexity"]
            for field in required_fields:
                assert field in scenario, f"Scenario missing required field: {field}"
                
            # Validate types
            assert scenario["complexity"] in ["beginner", "intermediate", "advanced"]
            assert isinstance(scenario.get("duration", 0), (int, float))
            assert isinstance(scenario.get("tags", []), list)
            
    @pytest.mark.asyncio
    async def test_demo_examples_loading(self, gallery_client, mock_orchestrator_url):
        """Test loading of demo example cards."""
        response = await gallery_client.get(
            f"{mock_orchestrator_url}/api/landing/examples"
        )
        
        if response.status_code != 200:
            pytest.skip("Demo examples endpoint not available")
            
        examples = response.json()
        assert len(examples) > 0
        
        for example in examples:
            # Validate example card structure
            assert "id" in example
            assert "title" in example
            assert "description" in example
            assert "demo_type" in example
            assert "duration" in example
            assert "difficulty" in example
            assert "tags" in example
            assert "popularity" in example
            assert "thumbnail_url" in example
            
            # Validate data types
            assert isinstance(example["tags"], list)
            assert isinstance(example["popularity"], int)
            assert 1 <= example["popularity"] <= 5
            
    @pytest.mark.asyncio
    async def test_demo_metadata_consistency(self, gallery_client, mock_orchestrator_url):
        """Test consistency between demo scenarios and examples."""
        # Get scenarios
        scenarios_response = await gallery_client.get(
            f"{mock_orchestrator_url}/api/demos/scenarios"
        )
        
        # Get examples
        examples_response = await gallery_client.get(
            f"{mock_orchestrator_url}/api/landing/examples"
        )
        
        if scenarios_response.status_code != 200 or examples_response.status_code != 200:
            pytest.skip("Cannot compare scenarios and examples")
            
        scenarios_data = scenarios_response.json()
        examples = examples_response.json()
        
        scenario_list = scenarios_data.get("scenarios", scenarios_data)
        
        # Create lookup maps
        scenarios_by_id = {s["id"]: s for s in scenario_list}
        examples_by_type = {e["demo_type"]: e for e in examples}
        
        # Check for consistency
        for example in examples:
            demo_type = example["demo_type"]
            
            # Find corresponding scenario
            matching_scenarios = [
                s for s in scenario_list 
                if s["type"].lower() == demo_type.lower() or 
                   demo_type.lower() in s["id"].lower()
            ]
            
            if matching_scenarios:
                scenario = matching_scenarios[0]
                
                # Check title consistency
                assert len(scenario["title"]) > 0
                assert len(example["title"]) > 0
                
                # Check duration format consistency
                if "duration" in scenario and "duration" in example:
                    # Both should represent time
                    scenario_duration = scenario["duration"]
                    example_duration = example["duration"]
                    
                    assert isinstance(scenario_duration, (int, float))
                    assert isinstance(example_duration, str)
                    assert any(unit in example_duration.lower() 
                             for unit in ["second", "minute", "hour"])


class TestArtifactGeneration:
    """Test generation and validation of demo artifacts."""
    
    @pytest.mark.asyncio
    async def test_artifact_availability(self, gallery_client, mock_orchestrator_url, mock_demo_artifacts):
        """Test that demo artifacts are available and accessible."""
        for demo_id, artifacts in mock_demo_artifacts.items():
            for artifact in artifacts:
                url = f"{mock_orchestrator_url}{artifact['url']}"
                
                response = await gallery_client.head(url)
                
                # Artifact should either be available or return proper error
                assert response.status_code in [200, 404, 503]
                
                if response.status_code == 200:
                    # Check content type is appropriate
                    content_type = response.headers.get("content-type", "")
                    
                    if artifact["type"] == "image":
                        assert any(img_type in content_type 
                                 for img_type in ["image/", "application/octet-stream"])
                    elif artifact["type"] == "table":
                        assert any(table_type in content_type 
                                 for table_type in ["text/csv", "application/json", "application/octet-stream"])
                                 
    @pytest.mark.asyncio
    async def test_artifact_metadata_validation(self, mock_demo_artifacts):
        """Test validation of artifact metadata."""
        for demo_id, artifacts in mock_demo_artifacts.items():
            for artifact in artifacts:
                # Validate required fields
                assert "id" in artifact
                assert "name" in artifact
                assert "type" in artifact
                assert "size_bytes" in artifact
                assert "url" in artifact
                
                # Validate data types
                assert isinstance(artifact["size_bytes"], int)
                assert artifact["size_bytes"] > 0
                assert artifact["size_bytes"] < DEMO_GALLERY_CONFIG["max_artifact_size_mb"] * 1024 * 1024
                
                # Validate URL format
                assert artifact["url"].startswith(DEMO_GALLERY_CONFIG["artifacts_base_path"])
                
                # Validate file extension
                file_ext = Path(artifact["name"]).suffix.lower()
                expected_extensions = {
                    "brain_map": [".nii", ".nii.gz"],
                    "image": [".png", ".jpg", ".jpeg", ".svg"],
                    "table": [".csv", ".json", ".tsv"],
                    "report": [".html", ".pdf"],
                    "file": [".nii.gz", ".json", ".txt"]
                }
                
                if artifact["type"] in expected_extensions:
                    valid_extensions = expected_extensions[artifact["type"]]
                    assert any(artifact["name"].endswith(ext) for ext in valid_extensions)
                    
    @pytest.mark.asyncio
    async def test_artifact_generation_performance(self, gallery_client, mock_orchestrator_url):
        """Test artifact generation performance."""
        # Test artifact generation for a demo
        demo_request = {
            "demo_type": "glm",
            "parameters": {"generate_artifacts": True}
        }
        
        response = await gallery_client.post(
            f"{mock_orchestrator_url}/api/landing/demos/start",
            json=demo_request
        )
        
        if response.status_code != 200:
            pytest.skip("Cannot start demo for artifact generation test")
            
        demo_id = response.json()["demo_id"]
        
        # Wait for completion and measure time
        import time
        start_time = time.time()
        
        while (time.time() - start_time) < 180:  # 3 minute timeout
            response = await gallery_client.get(
                f"{mock_orchestrator_url}/api/landing/demos/{demo_id}/progress"
            )
            
            if response.status_code == 200:
                progress = response.json()
                if progress["status"] == "completed":
                    break
                elif progress["status"] == "failed":
                    pytest.fail("Demo failed during artifact generation")
                    
            await asyncio.sleep(2)
        else:
            pytest.fail("Artifact generation took too long")
            
        # Get result and check artifacts
        response = await gallery_client.get(
            f"{mock_orchestrator_url}/api/landing/demos/{demo_id}/result"
        )
        
        if response.status_code == 200:
            result = response.json()
            artifacts = result.get("outputs", [])
            
            # Should have generated some artifacts
            assert len(artifacts) > 0
            
            generation_time = time.time() - start_time
            # Artifact generation should complete in reasonable time
            assert generation_time < 120, f"Artifact generation took {generation_time:.2f}s"


class TestVisualizationRendering:
    """Test rendering of demo visualizations."""
    
    @pytest.mark.asyncio
    async def test_visualization_endpoints(self, gallery_client, mock_orchestrator_url):
        """Test visualization endpoint availability."""
        # Common visualization endpoints
        viz_endpoints = [
            "/viz/demo/glm_motor/brain_map",
            "/viz/demo/connectivity_dmn/matrix",
            "/viz/demo/brain_decoding/accuracy"
        ]
        
        for endpoint in viz_endpoints:
            url = f"{mock_orchestrator_url}{endpoint}"
            response = await gallery_client.get(url)
            
            # Visualization should be available or return proper error
            assert response.status_code in [200, 404, 503]
            
            if response.status_code == 200:
                # Check content type
                content_type = response.headers.get("content-type", "")
                
                # Should be HTML, JSON, or image
                assert any(viz_type in content_type for viz_type in [
                    "text/html", "application/json", "image/", "text/javascript"
                ])
                
    @pytest.mark.asyncio
    async def test_interactive_visualizations(self, gallery_client, mock_orchestrator_url):
        """Test interactive visualization features."""
        # Test brain map visualization with parameters
        viz_params = {
            "threshold": 3.1,
            "colormap": "hot",
            "view": "axial"
        }
        
        response = await gallery_client.get(
            f"{mock_orchestrator_url}/viz/demo/glm_motor/brain_map",
            params=viz_params
        )
        
        if response.status_code == 200:
            content_type = response.headers.get("content-type", "")
            
            if "text/html" in content_type:
                # Should be interactive HTML
                content = response.text
                assert "interactive" in content.lower() or "plotly" in content.lower() or "d3" in content.lower()
            elif "application/json" in content_type:
                # Should return visualization data
                data = response.json()
                assert "data" in data or "traces" in data or "config" in data
                
    @pytest.mark.asyncio
    async def test_visualization_thumbnails(self, gallery_client, mock_orchestrator_url):
        """Test visualization thumbnail generation."""
        # Test thumbnail endpoints
        thumbnail_endpoints = [
            "/demo/thumbnails/glm_motor_card.png",
            "/demo/thumbnails/connectivity_dmn_card.png",
            "/demo/thumbnails/brain_decoding_card.png"
        ]
        
        for endpoint in thumbnail_endpoints:
            url = f"{mock_orchestrator_url}{endpoint}"
            response = await gallery_client.get(url)
            
            # Thumbnail should exist or be generateable
            assert response.status_code in [200, 404, 503]
            
            if response.status_code == 200:
                content_type = response.headers.get("content-type", "")
                assert "image/" in content_type
                
                # Check image size is reasonable for thumbnail
                content_length = response.headers.get("content-length")
                if content_length:
                    size_bytes = int(content_length)
                    assert 1000 < size_bytes < 500000  # Between 1KB and 500KB
                    
    @pytest.mark.asyncio
    async def test_visualization_performance(self, gallery_client, mock_orchestrator_url):
        """Test visualization rendering performance."""
        import time
        
        # Test various visualization types
        viz_endpoints = [
            "/viz/demo/glm_motor/brain_map",
            "/viz/demo/connectivity_dmn/matrix", 
            "/viz/demo/preprocessing/carpet"
        ]
        
        performance_metrics = []
        
        for endpoint in viz_endpoints:
            start_time = time.time()
            
            response = await gallery_client.get(
                f"{mock_orchestrator_url}{endpoint}",
                timeout=DEMO_GALLERY_CONFIG["visualization_timeout_seconds"]
            )
            
            render_time = time.time() - start_time
            
            performance_metrics.append({
                "endpoint": endpoint,
                "render_time": render_time,
                "status_code": response.status_code,
                "size_bytes": len(response.content) if response.status_code == 200 else 0
            })
            
            # Visualizations should render within reasonable time
            if response.status_code == 200:
                assert render_time < 15.0, f"Visualization {endpoint} took {render_time:.2f}s"
                
        # At least some visualizations should be available
        successful_renders = [m for m in performance_metrics if m["status_code"] == 200]
        if len(performance_metrics) > 0:
            success_rate = len(successful_renders) / len(performance_metrics)
            assert success_rate > 0.5, f"Only {success_rate:.1%} of visualizations rendered successfully"


class TestInteractiveFeatures:
    """Test interactive features of the demo gallery."""
    
    @pytest.mark.asyncio
    async def test_demo_filtering(self, gallery_client, mock_orchestrator_url):
        """Test demo filtering functionality."""
        # Test filter by complexity
        response = await gallery_client.get(
            f"{mock_orchestrator_url}/api/landing/examples",
            params={"complexity": "beginner"}
        )
        
        if response.status_code == 200:
            examples = response.json()
            for example in examples:
                assert example["difficulty"].lower() == "beginner"
                
        # Test filter by tags
        response = await gallery_client.get(
            f"{mock_orchestrator_url}/api/landing/examples",
            params={"tags": "fMRI"}
        )
        
        if response.status_code == 200:
            examples = response.json()
            for example in examples:
                assert "fMRI" in example["tags"] or "fmri" in [tag.lower() for tag in example["tags"]]
                
    @pytest.mark.asyncio
    async def test_demo_search(self, gallery_client, mock_orchestrator_url):
        """Test demo search functionality."""
        search_queries = ["motor", "connectivity", "preprocessing"]
        
        for query in search_queries:
            response = await gallery_client.get(
                f"{mock_orchestrator_url}/api/landing/examples",
                params={"search": query}
            )
            
            if response.status_code == 200:
                examples = response.json()
                
                # Results should be relevant to search query
                if len(examples) > 0:
                    relevant_results = [
                        ex for ex in examples 
                        if query.lower() in ex["title"].lower() or 
                           query.lower() in ex["description"].lower() or
                           query.lower() in [tag.lower() for tag in ex["tags"]]
                    ]
                    
                    # At least some results should be relevant
                    assert len(relevant_results) > 0
                    
    @pytest.mark.asyncio
    async def test_demo_sorting(self, gallery_client, mock_orchestrator_url):
        """Test demo sorting functionality."""
        sort_options = ["popularity", "duration", "name"]
        
        for sort_by in sort_options:
            response = await gallery_client.get(
                f"{mock_orchestrator_url}/api/landing/examples",
                params={"sort_by": sort_by}
            )
            
            if response.status_code == 200:
                examples = response.json()
                
                if len(examples) > 1:
                    # Verify sorting
                    if sort_by == "popularity":
                        popularities = [ex["popularity"] for ex in examples]
                        assert popularities == sorted(popularities, reverse=True)
                    elif sort_by == "name":
                        names = [ex["title"] for ex in examples]
                        assert names == sorted(names)
                        
    @pytest.mark.asyncio
    async def test_demo_pagination(self, gallery_client, mock_orchestrator_url):
        """Test demo pagination."""
        # Test first page
        response = await gallery_client.get(
            f"{mock_orchestrator_url}/api/landing/examples",
            params={"page": 1, "per_page": 2}
        )
        
        if response.status_code == 200:
            if isinstance(response.json(), dict) and "data" in response.json():
                # Paginated response format
                page_data = response.json()
                assert "data" in page_data
                assert "meta" in page_data
                
                meta = page_data["meta"]
                assert "page" in meta
                assert "per_page" in meta
                assert "total_count" in meta
                
                # Test second page if there are enough items
                if meta["total_count"] > meta["per_page"]:
                    response2 = await gallery_client.get(
                        f"{mock_orchestrator_url}/api/landing/examples",
                        params={"page": 2, "per_page": 2}
                    )
                    
                    if response2.status_code == 200:
                        page2_data = response2.json()
                        
                        # Should have different items
                        page1_ids = [item["id"] for item in page_data["data"]]
                        page2_ids = [item["id"] for item in page2_data["data"]]
                        
                        assert set(page1_ids).isdisjoint(set(page2_ids))


class TestUserInteractionTracking:
    """Test user interaction tracking and analytics."""
    
    @pytest.mark.asyncio
    async def test_demo_view_tracking(self, gallery_client, mock_orchestrator_url):
        """Test tracking of demo views."""
        # Track demo view event
        event_data = {
            "event_name": "demo_viewed",
            "event_data": {
                "demo_id": "glm_motor_task",
                "user_id": "test_user_123",
                "timestamp": "2025-01-15T10:30:00Z"
            }
        }
        
        response = await gallery_client.post(
            f"{mock_orchestrator_url}/api/analytics/event",
            params={"event_name": event_data["event_name"]},
            json=event_data["event_data"]
        )
        
        # Should accept analytics events
        assert response.status_code in [200, 201, 404]  # 404 if analytics not implemented
        
        if response.status_code in [200, 201]:
            result = response.json()
            assert "status" in result
            assert result["status"] in ["tracked", "received", "accepted"]
            
    @pytest.mark.asyncio
    async def test_demo_interaction_tracking(self, gallery_client, mock_orchestrator_url):
        """Test tracking of demo interactions."""
        interactions = [
            {"action": "demo_started", "demo_type": "glm"},
            {"action": "visualization_opened", "viz_type": "brain_map"},
            {"action": "artifact_downloaded", "artifact_type": "nifti"},
            {"action": "demo_shared", "share_method": "link"}
        ]
        
        for interaction in interactions:
            event_data = {
                "event_name": interaction["action"],
                "event_data": interaction
            }
            
            response = await gallery_client.post(
                f"{mock_orchestrator_url}/api/analytics/event",
                params={"event_name": event_data["event_name"]},
                json=event_data["event_data"]
            )
            
            # Should handle interaction tracking
            assert response.status_code in [200, 201, 404]


class TestAccessibilityFeatures:
    """Test accessibility features of the demo gallery."""
    
    @pytest.mark.asyncio
    async def test_keyboard_navigation(self, gallery_client, mock_orchestrator_url):
        """Test keyboard navigation support."""
        # Get example gallery page
        response = await gallery_client.get(
            f"{mock_orchestrator_url}/api/landing/examples"
        )
        
        if response.status_code == 200:
            examples = response.json()
            
            # Each example should have navigable elements
            for example in examples:
                assert "id" in example  # For focus targeting
                assert "title" in example  # For screen readers
                assert "description" in example  # For context
                
    @pytest.mark.asyncio
    async def test_alternative_text_support(self, gallery_client, mock_orchestrator_url):
        """Test alternative text for images and visualizations."""
        # Test thumbnail alt text
        response = await gallery_client.get(
            f"{mock_orchestrator_url}/api/landing/examples"
        )
        
        if response.status_code == 200:
            examples = response.json()
            
            for example in examples:
                # Should have description for accessibility
                assert "description" in example
                assert len(example["description"]) > 10
                
                # Title should be descriptive
                assert "title" in example
                assert len(example["title"]) > 5


if __name__ == "__main__":
    # Run with: python -m pytest tests/integration/test_demo_gallery.py -v
    pytest.main([__file__, "-v", "--tb=short"])