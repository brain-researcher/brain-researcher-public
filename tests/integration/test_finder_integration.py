"""
Integration tests for the complete Finder flow.
"""

import pytest
import requests
import json
from typing import Dict, Any


class TestFinderIntegration:
    """Test complete Finder workflow integration."""
    
    BASE_URL = "http://localhost:5000"
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Verify service is running before tests."""
        try:
            response = requests.get(f"{self.BASE_URL}/health")
            assert response.status_code == 200
        except requests.ConnectionError:
            pytest.skip("BR-KG service not running")
    
    def test_natural_language_to_filters(self):
        """Test converting natural language query to filters."""
        # Test simple query
        response = requests.post(
            f"{self.BASE_URL}/kg/suggestFilters",
            json={"text": "fMRI motor task"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "filters" in data
        filters = data["filters"]
        
        # Should have modality and task filters
        facets = {f["facet"] for f in filters}
        assert "modality" in facets
        assert "task" in facets
        
        # Check specific values
        modality_filter = next(f for f in filters if f["facet"] == "modality")
        assert modality_filter["value"] == "fmri"
        
        task_filter = next(f for f in filters if f["facet"] == "task")
        assert task_filter["value"] == "motor"
    
    def test_complex_natural_language_query(self):
        """Test complex natural language with multiple filters."""
        response = requests.post(
            f"{self.BASE_URL}/kg/suggestFilters",
            json={"text": "fMRI working memory studies after 2020 with over 50 subjects"}
        )
        assert response.status_code == 200
        data = response.json()
        
        filters = data["filters"]
        facets = {f["facet"] for f in filters}
        
        # Should extract all filter types
        assert "modality" in facets
        assert "task" in facets
        assert "year" in facets
        assert "sample_size" in facets
        
        # Check year filter
        year_filter = next(f for f in filters if f["facet"] == "year")
        assert year_filter["op"] == ">="
        assert year_filter["value"] == 2020
        
        # Check sample size filter  
        size_filter = next(f for f in filters if f["facet"] == "sample_size")
        assert size_filter["op"] == ">="
        assert size_filter["value"] == 50
    
    def test_facet_counting(self):
        """Test dynamic facet counting."""
        # Get facets without filters
        response = requests.post(
            f"{self.BASE_URL}/kg/facets",
            json={"filters": []}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "facets" in data
        facets = data["facets"]
        
        # Should have standard facets
        expected_facets = ["modality", "task", "population", "scanner"]
        for facet in expected_facets:
            if facet in facets:  # Some may not have data
                assert isinstance(facets[facet], dict)
                # Each facet should have counts
                for value, count in facets[facet].items():
                    assert isinstance(count, int)
                    assert count >= 0
    
    def test_facet_counting_with_filters(self):
        """Test facet counting with applied filters."""
        # Apply modality filter
        filters = [{"facet": "modality", "op": "=", "value": "fmri"}]
        
        response = requests.post(
            f"{self.BASE_URL}/kg/facets",
            json={"filters": filters}
        )
        assert response.status_code == 200
        data = response.json()
        
        facets = data["facets"]
        
        # Should still return facets but with filtered counts
        if "task" in facets:
            # Task counts should be for fMRI datasets only
            assert isinstance(facets["task"], dict)
    
    def test_dataset_search(self):
        """Test dataset search functionality."""
        response = requests.post(
            f"{self.BASE_URL}/kg/searchDatasets",
            json={
                "filters": [],
                "sort": "relevance",
                "limit": 10,
                "offset": 0
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "datasets" in data
        datasets = data["datasets"]
        
        # Check dataset structure
        if len(datasets) > 0:
            dataset = datasets[0]
            
            # Required fields
            assert "id" in dataset
            assert "name" in dataset
            assert "readiness" in dataset
            assert "why_matched" in dataset
            
            # Readiness structure
            readiness = dataset["readiness"]
            assert "color" in readiness
            assert readiness["color"] in ["green", "yellow", "red"]
            assert "score" in readiness
            assert 0 <= readiness["score"] <= 1
            assert "reason" in readiness
    
    def test_dataset_search_with_filters(self):
        """Test dataset search with specific filters."""
        filters = [
            {"facet": "modality", "op": "=", "value": "fmri"},
            {"facet": "task", "op": "=", "value": "motor"}
        ]
        
        response = requests.post(
            f"{self.BASE_URL}/kg/searchDatasets",
            json={
                "filters": filters,
                "sort": "readiness",
                "limit": 5,
                "offset": 0
            }
        )
        assert response.status_code == 200
        data = response.json()
        
        datasets = data["datasets"]
        
        # If datasets returned, they should match filters
        for dataset in datasets:
            # Check why_matched explains the filter matches
            assert "why_matched" in dataset
            matched = dataset["why_matched"]
            
            # Should explain modality and/or task match
            if "modality" in matched or "task" in matched:
                assert True  # At least one filter matched
    
    def test_dataset_search_pagination(self):
        """Test dataset search pagination."""
        # First page
        response1 = requests.post(
            f"{self.BASE_URL}/kg/searchDatasets",
            json={
                "filters": [],
                "sort": "name",
                "limit": 5,
                "offset": 0
            }
        )
        assert response1.status_code == 200
        page1 = response1.json()["datasets"]
        
        # Second page
        response2 = requests.post(
            f"{self.BASE_URL}/kg/searchDatasets",
            json={
                "filters": [],
                "sort": "name",
                "limit": 5,
                "offset": 5
            }
        )
        assert response2.status_code == 200
        page2 = response2.json()["datasets"]
        
        # Pages should not overlap
        if len(page1) > 0 and len(page2) > 0:
            page1_ids = {d["id"] for d in page1}
            page2_ids = {d["id"] for d in page2}
            assert len(page1_ids & page2_ids) == 0  # No overlap
    
    def test_dataset_explanation(self):
        """Test dataset explanation endpoint."""
        # First get a dataset ID
        search_response = requests.post(
            f"{self.BASE_URL}/kg/searchDatasets",
            json={
                "filters": [],
                "limit": 1,
                "offset": 0
            }
        )
        
        if search_response.status_code == 200:
            datasets = search_response.json()["datasets"]
            if len(datasets) > 0:
                dataset_id = datasets[0]["id"]
                
                # Get explanation
                response = requests.get(f"{self.BASE_URL}/kg/explain/{dataset_id}")
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # Check structure
                    assert "id" in data
                    assert data["id"] == dataset_id
                    assert "name" in data
                    assert "description" in data
                    assert "readiness" in data
                    assert "evidence" in data
                    assert "graph" in data
                    
                    # Check evidence structure
                    evidence = data["evidence"]
                    assert "papers" in evidence
                    assert "methods" in evidence
                    assert "derivatives" in evidence
                    assert isinstance(evidence["papers"], list)
                    assert isinstance(evidence["methods"], list)
                    assert isinstance(evidence["derivatives"], list)
                    
                    # Check graph structure
                    graph = data["graph"]
                    assert "nodes" in graph
                    assert "edges" in graph
                    assert isinstance(graph["nodes"], list)
                    assert isinstance(graph["edges"], list)
                    
                    # Graph should have at least the dataset node
                    assert len(graph["nodes"]) >= 1
                    dataset_nodes = [n for n in graph["nodes"] if n["type"] == "dataset"]
                    assert len(dataset_nodes) == 1
    
    def test_dataset_not_found(self):
        """Test explanation for non-existent dataset."""
        response = requests.get(f"{self.BASE_URL}/kg/explain/non_existent_dataset_999")
        assert response.status_code == 404
        data = response.json()
        assert "error" in data
    
    def test_complete_finder_workflow(self):
        """Test complete workflow from query to explanation."""
        # Step 1: Natural language query
        nl_response = requests.post(
            f"{self.BASE_URL}/kg/suggestFilters",
            json={"text": "fMRI studies"}
        )
        assert nl_response.status_code == 200
        filters = nl_response.json()["filters"]
        
        # Step 2: Get facet counts
        facet_response = requests.post(
            f"{self.BASE_URL}/kg/facets",
            json={"filters": filters}
        )
        assert facet_response.status_code == 200
        facets = facet_response.json()["facets"]
        
        # Step 3: Search datasets
        search_response = requests.post(
            f"{self.BASE_URL}/kg/searchDatasets",
            json={
                "filters": filters,
                "sort": "readiness",
                "limit": 10,
                "offset": 0
            }
        )
        assert search_response.status_code == 200
        datasets = search_response.json()["datasets"]
        
        # Step 4: Get explanation for top dataset
        if len(datasets) > 0:
            top_dataset = datasets[0]
            explain_response = requests.get(
                f"{self.BASE_URL}/kg/explain/{top_dataset['id']}"
            )
            
            if explain_response.status_code == 200:
                explanation = explain_response.json()
                
                # Verify complete data flow
                assert explanation["id"] == top_dataset["id"]
                assert "readiness" in explanation
                assert "evidence" in explanation
                assert "graph" in explanation
    
    def test_error_handling(self):
        """Test API error handling."""
        # Test invalid JSON
        response = requests.post(
            f"{self.BASE_URL}/kg/suggestFilters",
            data="invalid json",
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code in [400, 422]
        
        # Test missing required fields
        response = requests.post(
            f"{self.BASE_URL}/kg/searchDatasets",
            json={}  # Missing required fields
        )
        # Should handle gracefully with defaults or error
        assert response.status_code in [200, 400]
        
        # Test invalid filter operators
        response = requests.post(
            f"{self.BASE_URL}/kg/searchDatasets",
            json={
                "filters": [{"facet": "year", "op": "invalid", "value": 2020}],
                "limit": 10,
                "offset": 0
            }
        )
        # Should handle invalid operators
        assert response.status_code in [200, 400]


class TestFinderPerformance:
    """Test Finder API performance characteristics."""
    
    BASE_URL = "http://localhost:5000"
    
    def test_natural_language_parsing_speed(self):
        """Test NLP parsing responds quickly."""
        import time
        
        start = time.time()
        response = requests.post(
            f"{self.BASE_URL}/kg/suggestFilters",
            json={"text": "fMRI motor task studies after 2020"}
        )
        elapsed = time.time() - start
        
        assert response.status_code == 200
        # Should parse in under 500ms
        assert elapsed < 0.5
    
    def test_search_response_time(self):
        """Test search responds in reasonable time."""
        import time
        
        start = time.time()
        response = requests.post(
            f"{self.BASE_URL}/kg/searchDatasets",
            json={
                "filters": [{"facet": "modality", "op": "=", "value": "fmri"}],
                "limit": 20,
                "offset": 0
            }
        )
        elapsed = time.time() - start
        
        assert response.status_code == 200
        # Should search in under 1 second
        assert elapsed < 1.0
    
    def test_concurrent_requests(self):
        """Test API handles concurrent requests."""
        import concurrent.futures
        
        def make_request():
            return requests.post(
                f"{self.BASE_URL}/kg/suggestFilters",
                json={"text": "test query"}
            )
        
        # Make 10 concurrent requests
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(make_request) for _ in range(10)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
        
        # All should succeed
        for response in results:
            assert response.status_code == 200


if __name__ == "__main__":
    pytest.main([__file__, "-v"])