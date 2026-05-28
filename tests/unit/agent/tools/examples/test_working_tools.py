#!/usr/bin/env python3
"""
Test cases for working tools in the Brain Researcher Agent.
These tests demonstrate actual working functionality.
"""

import json
import os
from typing import Any, Dict

import pytest
import requests

BASE_URL = "http://localhost:8000"

# These are "live" smoke tests that hit a running local agent service and depend on
# the current BR-KG / tool wiring. Keep them opt-in so normal unit runs stay hermetic.
pytestmark = pytest.mark.slow

_RUN_LIVE = os.getenv("BR_RUN_LIVE_TOOL_TESTS", "").lower() in {"1", "true", "yes", "on"}


def _is_service_available() -> bool:
    try:
        requests.get(BASE_URL, timeout=1)
    except requests.RequestException:
        return False
    return True


@pytest.fixture(scope="module", autouse=True)
def _require_local_service() -> None:
    if not _RUN_LIVE:
        pytest.skip("Set BR_RUN_LIVE_TOOL_TESTS=1 to run live tool smoke tests.")
    if not _is_service_available():
        pytest.skip("Local agent service not running on localhost:8000")


class TestWorkingTools:
    """Test cases for tools that are fully functional."""
    
    def test_task_to_concept_mapping_basic(self):
        """Test basic task to concept mapping."""
        response = requests.post(
            f"{BASE_URL}/debug/tool/task_to_concept_mapping",
            json={"args": {"task_name": "n-back"}}
        )
        
        assert response.status_code == 200
        result = response.json()
        
        assert result["success"] is True
        data = result["result"]["data"]
        
        # Check expected fields
        assert "task_name" in data
        assert "concepts" in data
        assert "matched_task" in data
        
        # Check concepts are returned
        assert len(data["concepts"]) > 0
        assert "working memory" in data["concepts"]
    
    def test_task_to_concept_mapping_variants(self):
        """Test different task name variants."""
        test_cases = [
            ("n-back", ["working memory", "updating"]),
            ("finger tapping", ["motor", "movement"]),
            ("stroop", ["cognitive control", "conflict"]),
            ("face viewing", ["face", "visual"]),
        ]
        
        for task_name, expected_concepts in test_cases:
            response = requests.post(
                f"{BASE_URL}/debug/tool/task_to_concept_mapping",
                json={"args": {"task_name": task_name}}
            )
            
            assert response.status_code == 200
            data = response.json()["result"]["data"]
            
            # Check at least one expected concept is found
            found_concepts = " ".join(data["concepts"]).lower()
            assert any(concept in found_concepts for concept in expected_concepts),\
                f"Expected concepts {expected_concepts} not found in {data['concepts']}"
    
    def test_coordinate_to_concept_single(self):
        """Test single coordinate mapping."""
        response = requests.post(
            f"{BASE_URL}/debug/tool/coordinate_to_concept",
            json={"args": {
                "coordinates": [[-42, -22, 54]],
                "radius": 10
            }}
        )
        
        assert response.status_code == 200
        result = response.json()
        
        assert result["success"] is True
        data = result["result"]["data"]
        
        # Check structure
        assert "coordinate_mappings" in data
        assert len(data["coordinate_mappings"]) == 1
        
        mapping = data["coordinate_mappings"][0]
        assert "coordinate" in mapping
        assert "concepts" in mapping
        assert len(mapping["concepts"]) > 0
        
        # Check concept structure
        concept = mapping["concepts"][0]
        assert "concept" in concept
        assert "score" in concept
    
    def test_coordinate_to_concept_multiple(self):
        """Test multiple coordinates in batch."""
        coordinates = [
            [-42, -22, 54],  # Left motor
            [38, -86, -8],   # Right visual
            [0, -2, 48]      # SMA
        ]
        
        response = requests.post(
            f"{BASE_URL}/debug/tool/coordinate_to_concept",
            json={"args": {
                "coordinates": coordinates,
                "radius": 10,
                "top_k": 3
            }}
        )
        
        assert response.status_code == 200
        data = response.json()["result"]["data"]
        
        # Check all coordinates processed
        assert len(data["coordinate_mappings"]) == 3
        
        # Check each has concepts
        for mapping in data["coordinate_mappings"]:
            assert len(mapping["concepts"]) <= 3  # Respects top_k
            assert mapping["concepts"][0]["score"] >= mapping["concepts"][-1]["score"]  # Sorted by score
    
    def test_coordinate_to_concept_parameters(self):
        """Test different parameter combinations."""
        base_coord = [[-30, -90, 0]]  # Visual cortex
        
        # Test different radius values
        for radius in [5, 10, 20]:
            response = requests.post(
                f"{BASE_URL}/debug/tool/coordinate_to_concept",
                json={"args": {
                    "coordinates": base_coord,
                    "radius": radius
                }}
            )
            
            assert response.status_code == 200
            data = response.json()["result"]["data"]
            assert data["radius_mm"] == radius
        
        # Test different top_k values
        for top_k in [1, 5, 10]:
            response = requests.post(
                f"{BASE_URL}/debug/tool/coordinate_to_concept",
                json={"args": {
                    "coordinates": base_coord,
                    "top_k": top_k
                }}
            )
            
            assert response.status_code == 200
            data = response.json()["result"]["data"]
            # May return fewer than top_k if not enough concepts
            assert len(data["coordinate_mappings"][0]["concepts"]) <= top_k


class TestPartiallyWorkingTools:
    """Test cases for tools that work but return mock data."""
    
    def test_glm_analysis_basic(self):
        """Test basic GLM analysis (mock)."""
        response = requests.post(
            f"{BASE_URL}/debug/tool/glm_analysis",
            json={"args": {
                "dataset_id": "ds000001",
                "contrasts": {"motor_vs_baseline": [1, -1]},
                "allow_mock": True,
            }}
        )
        
        assert response.status_code == 200
        result = response.json()
        
        assert result["success"] is True
        data = result["result"]["data"]
        
        # Check mock data structure
        assert data["dataset_id"] == "ds000001"
        assert "contrasts" in data
        assert "peak_coordinates" in data
        assert len(data["peak_coordinates"]) > 0
    
    def test_glm_analysis_multiple_contrasts(self):
        """Test GLM with multiple contrasts."""
        response = requests.post(
            f"{BASE_URL}/debug/tool/glm_analysis",
            json={"args": {
                "dataset_id": "ds000030",
                "contrasts": {
                    "faces_vs_houses": [1, -1, 0, 0],
                    "faces_vs_baseline": [1, 0, 0, -1],
                    "main_effect": [1, 1, 0, -2]
                },
                "threshold": 2.3,
                "allow_mock": True,
            }}
        )
        
        assert response.status_code == 200
        data = response.json()["result"]["data"]
        
        assert data["n_contrasts"] == 3
        assert len(data["contrasts"]) == 3
        
        # Check each contrast has results
        for contrast_name in ["faces_vs_houses", "faces_vs_baseline", "main_effect"]:
            assert contrast_name in data["contrasts"]
            assert "z_map" in data["contrasts"][contrast_name]
            assert data["contrasts"][contrast_name]["threshold"] == 2.3
    
    def test_encoding_model_basic(self):
        """Test encoding model (mock)."""
        response = requests.post(
            f"{BASE_URL}/debug/tool/encoding_model",
            json={"args": {
                "dataset_id": "ds000001",
                "feature_type": "visual",
                "model_type": "ridge"
            }}
        )
        
        assert response.status_code == 200
        result = response.json()
        
        assert result["success"] is True
        data = result["result"]["data"]
        
        # Check mock results
        assert "r2_scores" in data
        assert "mean" in data["r2_scores"]
        assert "by_region" in data["r2_scores"]
        assert data["r2_scores"]["mean"] > 0
    
    def test_encoding_model_parcellations(self):
        """Test different parcellations."""
        parcellations = ["schaefer_400", "glasser_360"]
        
        for parcellation in parcellations:
            response = requests.post(
                f"{BASE_URL}/debug/tool/encoding_model",
                json={"args": {
                    "dataset_id": "ds000001",
                    "feature_type": "visual",
                    "model_type": "ridge",
                    "parcellation": parcellation
                }}
            )
            
            assert response.status_code == 200
            data = response.json()["result"]["data"]
            
            # Check parcellation affects mock data
            if "400" in parcellation:
                assert data["n_parcels"] == 400
            elif "360" in parcellation:
                assert data["n_parcels"] == 360


def run_tests():
    """Run all tests and report results."""
    import sys
    
    # Create test instances
    working_tests = TestWorkingTools()
    partial_tests = TestPartiallyWorkingTools()
    
    # Run tests
    print("Testing Working Tools...")
    print("=" * 50)
    
    try:
        working_tests.test_task_to_concept_mapping_basic()
        print("✅ task_to_concept_mapping: Basic test passed")
    except Exception as e:
        print(f"❌ task_to_concept_mapping: Basic test failed - {e}")
    
    try:
        working_tests.test_coordinate_to_concept_single()
        print("✅ coordinate_to_concept: Single coordinate test passed")
    except Exception as e:
        print(f"❌ coordinate_to_concept: Single coordinate test failed - {e}")
    
    print("\nTesting Partially Working Tools (Mock Data)...")
    print("=" * 50)
    
    try:
        partial_tests.test_glm_analysis_basic()
        print("✅ glm_analysis: Basic test passed (mock)")
    except Exception as e:
        print(f"❌ glm_analysis: Basic test failed - {e}")
    
    try:
        partial_tests.test_encoding_model_basic()
        print("✅ encoding_model: Basic test passed (mock)")
    except Exception as e:
        print(f"❌ encoding_model: Basic test failed - {e}")


if __name__ == "__main__":
    run_tests()
