#!/usr/bin/env python
"""
Integration tests for BR-KG Finder API
Tests the actual API endpoints with a running server
"""

import pytest
import requests
import json
from typing import Dict, List, Any

# Base URL for testing - can be overridden by environment variable
import os
BASE_URL = os.getenv("NEUROKG_URL", "http://localhost:5000")


class TestFinderAPIIntegration:
    """Integration tests for Finder API endpoints"""
    
    @classmethod
    def setup_class(cls):
        """Check if server is running before tests"""
        try:
            response = requests.get(f"{BASE_URL}/health", timeout=5)
            if response.status_code != 200:
                pytest.skip("BR-KG server not running")
        except requests.exceptions.RequestException:
            pytest.skip("Cannot connect to BR-KG server")
    
    def test_suggest_filters_basic(self):
        """Test basic NL to filters conversion"""
        response = requests.post(
            f"{BASE_URL}/kg/suggestFilters",
            json={"text": "task fMRI motor studies"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "filters" in data
        filters = data["filters"]
        
        # Check that we extracted modality and task
        facets = [f["facet"] for f in filters]
        assert "modality" in facets
        assert "task" in facets
        
        # Check values
        modality_filter = next(f for f in filters if f["facet"] == "modality")
        assert modality_filter["value"] == "fmri"
        
        task_filter = next(f for f in filters if f["facet"] == "task")
        assert task_filter["value"] == "motor"
    
    def test_suggest_filters_complex(self):
        """Test complex query parsing"""
        queries = [
            {
                "text": "older adults over 60 with n >= 100",
                "expected_facets": ["population", "age", "n"],
                "expected_ops": {"age": ">=", "n": ">="}
            },
            {
                "text": "BIDS datasets from 2020-2023",
                "expected_facets": ["bids", "year"],
                "expected_values": {"bids": True}
            },
            {
                "text": "resting state fMRI from OpenNeuro",
                "expected_facets": ["task", "modality", "source"],
                "expected_values": {"task": "rest", "source": "openneuro"}
            }
        ]
        
        for query_test in queries:
            response = requests.post(
                f"{BASE_URL}/kg/suggestFilters",
                json={"text": query_test["text"]}
            )
            assert response.status_code == 200
            filters = response.json()["filters"]
            facets = [f["facet"] for f in filters]
            
            # Check expected facets
            for expected_facet in query_test["expected_facets"]:
                assert expected_facet in facets, f"Missing {expected_facet} in query: {query_test['text']}"
            
            # Check operators if specified
            if "expected_ops" in query_test:
                for facet, op in query_test["expected_ops"].items():
                    filter_item = next((f for f in filters if f["facet"] == facet), None)
                    assert filter_item is not None
                    assert filter_item["op"] == op
            
            # Check values if specified
            if "expected_values" in query_test:
                for facet, value in query_test["expected_values"].items():
                    filter_item = next((f for f in filters if f["facet"] == facet), None)
                    assert filter_item is not None
                    assert filter_item["value"] == value
    
    @pytest.mark.skipif(
        not os.getenv("NEO4J_URI"),
        reason="Neo4j not configured"
    )
    def test_facets_endpoint(self):
        """Test facet counting endpoint (requires Neo4j)"""
        response = requests.post(
            f"{BASE_URL}/kg/facets",
            json={"filters": []}
        )
        
        if response.status_code == 500:
            pytest.skip("Neo4j not available")
        
        assert response.status_code == 200
        data = response.json()
        
        # Should return facet categories
        expected_facets = ["modality", "task", "population", "source"]
        for facet in expected_facets:
            assert facet in data
            assert isinstance(data[facet], list)
    
    @pytest.mark.skipif(
        not os.getenv("NEO4J_URI"),
        reason="Neo4j not configured"
    )
    def test_search_datasets_endpoint(self):
        """Test dataset search endpoint (requires Neo4j)"""
        response = requests.post(
            f"{BASE_URL}/kg/searchDatasets",
            json={
                "filters": [{"facet": "modality", "value": "fmri"}],
                "page": 1,
                "pageSize": 10
            }
        )
        
        if response.status_code == 500:
            pytest.skip("Neo4j not available")
        
        assert response.status_code == 200
        data = response.json()
        
        # Check response structure
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert data["page"] == 1
        assert "pageSize" in data
        assert data["pageSize"] == 10
        
        # Check item structure if any results
        if data["items"]:
            item = data["items"][0]
            assert "id" in item
            assert "readiness" in item
            assert item["readiness"] in ["green", "yellow", "red"]
            assert "why" in item
    
    def test_empty_query(self):
        """Test handling of empty query"""
        response = requests.post(
            f"{BASE_URL}/kg/suggestFilters",
            json={"text": ""}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["filters"] == []
    
    def test_invalid_request(self):
        """Test handling of invalid request"""
        response = requests.post(
            f"{BASE_URL}/kg/suggestFilters",
            json={}  # Missing 'text' field
        )
        assert response.status_code == 200  # Still returns 200 but with empty filters
        data = response.json()
        assert data["filters"] == []


def run_integration_tests():
    """Run integration tests programmatically"""
    import subprocess
    result = subprocess.run(
        ["pytest", __file__, "-v", "--tb=short"],
        capture_output=True,
        text=True
    )
    print(result.stdout)
    if result.stderr:
        print("Errors:", result.stderr)
    return result.returncode == 0


if __name__ == "__main__":
    # Can be run directly for quick testing
    print("=" * 60)
    print("FINDER API INTEGRATION TESTS")
    print("=" * 60)
    print(f"Testing against: {BASE_URL}")
    print()
    
    success = run_integration_tests()
    
    if success:
        print("\n✅ All integration tests passed!")
    else:
        print("\n❌ Some tests failed. Check output above.")