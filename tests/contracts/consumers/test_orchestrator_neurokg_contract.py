"""
Consumer contract tests: Orchestrator -> BR-KG Service.

These tests define the contract expectations that the Orchestrator has
when communicating with the BR-KG service.
"""

import pytest
import asyncio
from pathlib import Path

import pytest
try:
    from pact import Consumer, Provider
except ImportError:
    pytest.skip("pact Consumer/Provider not available (pact-python v3?)", allow_module_level=True)

from ..pact_config import pact_config, get_service_config
from ..pact_helpers.pact_client import PactClient, PactMatchers
from ..pact_helpers.mock_data import MockDataGenerator


class TestOrchestratorToNeuroKGContract:
    """Contract tests from Orchestrator consumer perspective to BR-KG provider."""
    
    @pytest.fixture
    def pact_client(self):
        """Create Pact client for Orchestrator -> BR-KG contract."""
        orchestrator_config = get_service_config("orchestrator")
        neurokg_config = get_service_config("neurokg")
        return PactClient(orchestrator_config, neurokg_config)
    
    @pytest.mark.asyncio
    async def test_neurokg_health_check_contract(self, pact_client):
        """Test BR-KG health check endpoint contract."""
        async with pact_client as pact:
            (pact
             .given("neurokg service is running")
             .upon_receiving("a request for neurokg health status")
             .with_request(
                 method="GET",
                 path="/health"
             )
             .will_respond_with(
                 status=200,
                 headers={"Content-Type": "application/json"},
                 body={
                     "status": "healthy",
                     "database": {
                         "connected": True,
                         "nodes": 10000,
                         "relationships": 50000
                     },
                     "search_indices": {
                         "concepts": "ready",
                         "datasets": "ready", 
                         "tasks": "ready"
                     },
                     "timestamp": PactMatchers.iso_datetime(),
                     "version": "1.0.0"
                 }
             ))
            
            # Execute the request
            response = await pact.execute_request("GET", "/health")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert "database" in data
            assert "search_indices" in data
            assert data["database"]["connected"] is True
    
    @pytest.mark.asyncio
    async def test_search_datasets_contract(self, pact_client):
        """Test dataset search endpoint contract."""
        async with pact_client as pact:
            search_request = {
                "query": "motor cortex activation",
                "filters": {
                    "modality": ["fMRI"],
                    "n_subjects": {"min": 10, "max": 100},
                    "tasks": ["motor"]
                },
                "limit": 20,
                "offset": 0
            }
            
            (pact
             .given("knowledge graph has datasets")
             .upon_receiving("a dataset search request")
             .with_request(
                 method="POST",
                 path="/api/datasets/search",
                 headers={"Content-Type": "application/json"},
                 body=search_request
             )
             .will_respond_with(
                 status=200,
                 headers={"Content-Type": "application/json"},
                 body={
                     "datasets": [
                         {
                             "id": "ds003226",
                             "name": "Motor task fMRI dataset",
                             "description": "fMRI data during motor task performance",
                             "source": "OpenNeuro",
                             "url": "https://openneuro.org/datasets/ds003226",
                             "modality": ["fMRI"],
                             "n_subjects": 24,
                             "n_sessions": 1,
                             "tasks": ["motor", "rest"],
                             "size_gb": 12.5,
                             "has_derivatives": True,
                             "bids_version": "1.6.0",
                             "last_updated": PactMatchers.iso_datetime(),
                             "metadata": {
                                 "authors": ["Smith, J.", "Jones, M."],
                                 "publication_year": 2022,
                                 "doi": "10.18112/openneuro.ds003226.v1.0.0"
                             },
                             "quality_score": 0.92,
                             "preview_images": [
                                 "/api/datasets/ds003226/preview/brain_slice_001.png"
                             ]
                         }
                     ],
                     "total_count": 1,
                     "query_metadata": {
                         "processing_time_ms": 45,
                         "search_strategy": "hybrid_semantic_spatial"
                     },
                     "facets": {
                         "modality": [
                             {"value": "fMRI", "count": 1}
                         ],
                         "source": [
                             {"value": "OpenNeuro", "count": 1}
                         ],
                         "n_subjects_range": [
                             {"range": "10-50", "count": 1}
                         ]
                     }
                 }
             ))
            
            # Execute the request
            response = await pact.execute_request(
                "POST", "/api/datasets/search",
                headers={"Content-Type": "application/json"},
                json_data=search_request
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "datasets" in data
            assert "total_count" in data
            assert "facets" in data
            assert isinstance(data["datasets"], list)
            assert data["datasets"][0]["modality"] == ["fMRI"]
    
    @pytest.mark.asyncio
    async def test_get_dataset_details_contract(self, pact_client):
        """Test dataset details retrieval contract."""
        dataset_id = "ds003226"
        
        async with pact_client as pact:
            (pact
             .given("dataset exists in knowledge graph")
             .upon_receiving("a request for dataset details")
             .with_request(
                 method="GET",
                 path=f"/api/datasets/{dataset_id}"
             )
             .will_respond_with(
                 status=200,
                 headers={"Content-Type": "application/json"},
                 body={
                     "id": dataset_id,
                     "name": "Motor task fMRI dataset",
                     "description": "Detailed description of the motor task fMRI dataset",
                     "source": "OpenNeuro",
                     "url": "https://openneuro.org/datasets/ds003226",
                     "modality": ["fMRI"],
                     "n_subjects": 24,
                     "n_sessions": 1,
                     "tasks": ["motor", "rest"],
                     "size_gb": 12.5,
                     "has_derivatives": True,
                     "bids_version": "1.6.0",
                     "last_updated": PactMatchers.iso_datetime(),
                     "metadata": {
                         "authors": ["Smith, J.", "Jones, M."],
                         "publication_year": 2022,
                         "doi": "10.18112/openneuro.ds003226.v1.0.0",
                         "license": "CC0",
                         "acknowledgements": "Data collection supported by NIH grant...",
                         "references": ["Smith et al. (2022) Nature Neuroscience"],
                         "keywords": ["motor", "fMRI", "cortex"]
                     },
                     "statistics": {
                         "mean_age": 28.5,
                         "age_range": [18, 65],
                         "sex_distribution": {"M": 12, "F": 12},
                         "handedness": {"R": 22, "L": 2}
                     },
                     "related_datasets": [
                         {
                             "id": "ds003227",
                             "name": "Related visual task dataset",
                             "similarity_score": 0.75
                         }
                     ],
                     "analyses": [
                         {
                             "id": "analysis_001",
                             "type": "GLM",
                             "description": "First-level GLM analysis",
                             "results_available": True
                         }
                     ]
                 }
             ))
            
            # Execute the request
            response = await pact.execute_request("GET", f"/api/datasets/{dataset_id}")
            
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == dataset_id
            assert "metadata" in data
            assert "statistics" in data
            assert "related_datasets" in data
    
    @pytest.mark.asyncio
    async def test_search_concepts_contract(self, pact_client):
        """Test concept search endpoint contract."""
        async with pact_client as pact:
            search_request = {
                "query": "motor cortex",
                "context": "neuroimaging",
                "limit": 10
            }
            
            (pact
             .given("knowledge graph has concepts")
             .upon_receiving("a concept search request")
             .with_request(
                 method="POST",
                 path="/api/concepts/search",
                 headers={"Content-Type": "application/json"},
                 body=search_request
             )
             .will_respond_with(
                 status=200,
                 headers={"Content-Type": "application/json"},
                 body={
                     "concepts": [
                         {
                             "id": "concept_001",
                             "name": "Motor Cortex",
                             "definition": "Brain region responsible for voluntary motor control",
                             "aliases": ["M1", "Primary Motor Cortex"],
                             "category": "brain_region",
                             "coordinates": {
                                 "mni": [-42, -24, 58],
                                 "atlas": "MNI152"
                             },
                             "related_tasks": [
                                 {
                                     "task_id": "task_motor",
                                     "task_name": "motor execution",
                                     "association_strength": 0.95
                                 }
                             ],
                             "related_concepts": [
                                 {
                                     "concept_id": "concept_002",
                                     "name": "Premotor Cortex",
                                     "relationship": "adjacent_to"
                                 }
                             ]
                         }
                     ],
                     "total_count": 1,
                     "query_metadata": {
                         "processing_time_ms": 25,
                         "semantic_similarity": 0.92
                     }
                 }
             ))
            
            # Execute the request
            response = await pact.execute_request(
                "POST", "/api/concepts/search",
                headers={"Content-Type": "application/json"},
                json_data=search_request
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "concepts" in data
            assert "total_count" in data
            assert isinstance(data["concepts"], list)
            assert data["concepts"][0]["name"] == "Motor Cortex"
    
    @pytest.mark.asyncio
    async def test_coordinate_to_concept_mapping_contract(self, pact_client):
        """Test coordinate to concept mapping contract."""
        async with pact_client as pact:
            coordinate_request = {
                "coordinates": [
                    {"x": -42, "y": -24, "z": 58},
                    {"x": 42, "y": -24, "z": 58}
                ],
                "space": "MNI152",
                "radius_mm": 8
            }
            
            (pact
             .given("knowledge graph has spatial mappings")
             .upon_receiving("a coordinate to concept mapping request")
             .with_request(
                 method="POST",
                 path="/api/coordinates/to-concepts",
                 headers={"Content-Type": "application/json"},
                 body=coordinate_request
             )
             .will_respond_with(
                 status=200,
                 headers={"Content-Type": "application/json"},
                 body={
                     "mappings": [
                         {
                             "coordinate": {"x": -42, "y": -24, "z": 58},
                             "concepts": [
                                 {
                                     "concept_id": "concept_001",
                                     "name": "Left Motor Cortex",
                                     "confidence": 0.95,
                                     "distance_mm": 2.1
                                 }
                             ]
                         },
                         {
                             "coordinate": {"x": 42, "y": -24, "z": 58},
                             "concepts": [
                                 {
                                     "concept_id": "concept_002",
                                     "name": "Right Motor Cortex", 
                                     "confidence": 0.93,
                                     "distance_mm": 3.5
                                 }
                             ]
                         }
                     ],
                     "space": "MNI152",
                     "radius_mm": 8,
                     "total_concepts": 2
                 }
             ))
            
            # Execute the request
            response = await pact.execute_request(
                "POST", "/api/coordinates/to-concepts",
                headers={"Content-Type": "application/json"},
                json_data=coordinate_request
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "mappings" in data
            assert len(data["mappings"]) == 2
            assert data["space"] == "MNI152"
    
    @pytest.mark.asyncio
    async def test_get_task_concept_relationships_contract(self, pact_client):
        """Test task-concept relationship retrieval contract."""
        task_name = "motor execution"
        
        async with pact_client as pact:
            (pact
             .given("knowledge graph has task-concept relationships")
             .upon_receiving("a request for task-concept relationships")
             .with_request(
                 method="GET",
                 path="/api/tasks/motor%20execution/concepts"
             )
             .will_respond_with(
                 status=200,
                 headers={"Content-Type": "application/json"},
                 body={
                     "task": {
                         "name": "motor execution",
                         "description": "Voluntary motor movement execution",
                         "category": "motor"
                     },
                     "related_concepts": [
                         {
                             "concept_id": "concept_001",
                             "name": "Motor Cortex",
                             "relationship_type": "activates",
                             "strength": 0.95,
                             "evidence_count": 152
                         },
                         {
                             "concept_id": "concept_003",
                             "name": "Cerebellum",
                             "relationship_type": "modulates",
                             "strength": 0.87,
                             "evidence_count": 89
                         }
                     ],
                     "total_relationships": 2,
                     "metadata": {
                         "last_updated": PactMatchers.iso_datetime(),
                         "evidence_sources": ["NeuroSynth", "BrainMap", "PubMed"]
                     }
                 }
             ))
            
            # Execute the request
            response = await pact.execute_request("GET", "/api/tasks/motor%20execution/concepts")
            
            assert response.status_code == 200
            data = response.json()
            assert "task" in data
            assert "related_concepts" in data
            assert len(data["related_concepts"]) == 2
    
    @pytest.mark.asyncio
    async def test_dataset_not_found_contract(self, pact_client):
        """Test dataset not found error contract."""
        dataset_id = "ds_nonexistent"
        
        async with pact_client as pact:
            (pact
             .given("dataset does not exist")
             .upon_receiving("a request for non-existent dataset")
             .with_request(
                 method="GET",
                 path=f"/api/datasets/{dataset_id}"
             )
             .will_respond_with(
                 status=404,
                 headers={"Content-Type": "application/json"},
                 body={
                     "error": {
                         "code": "NOT_FOUND",
                         "message": f"Dataset {dataset_id} not found in knowledge graph",
                         "suggestions": [
                             "Check the dataset ID",
                             "Browse available datasets at /api/datasets"
                         ],
                         "timestamp": PactMatchers.iso_datetime()
                     }
                 }
             ))
            
            # Execute the request
            response = await pact.execute_request("GET", f"/api/datasets/{dataset_id}")
            
            assert response.status_code == 404
            data = response.json()
            assert "error" in data
            assert data["error"]["code"] == "NOT_FOUND"
    
    @pytest.mark.asyncio
    async def test_knowledge_graph_statistics_contract(self, pact_client):
        """Test knowledge graph statistics endpoint contract."""
        async with pact_client as pact:
            (pact
             .given("knowledge graph has data")
             .upon_receiving("a request for knowledge graph statistics")
             .with_request(
                 method="GET",
                 path="/api/stats"
             )
             .will_respond_with(
                 status=200,
                 headers={"Content-Type": "application/json"},
                 body={
                     "nodes": {
                         "total": 15000,
                         "by_type": {
                             "Dataset": 2500,
                             "Concept": 8000,
                             "Task": 1500,
                             "Study": 3000
                         }
                     },
                     "relationships": {
                         "total": 75000,
                         "by_type": {
                             "activates": 25000,
                             "belongs_to": 20000,
                             "relates_to": 30000
                         }
                     },
                     "indices": {
                         "concepts": {
                             "size": 8000,
                             "last_updated": PactMatchers.iso_datetime()
                         },
                         "datasets": {
                             "size": 2500,
                             "last_updated": PactMatchers.iso_datetime()
                         }
                     },
                     "data_freshness": {
                         "last_ingestion": PactMatchers.iso_datetime(),
                         "sources_synced": ["NeuroSynth", "OpenNeuro", "BrainMap"]
                     }
                 }
             ))
            
            # Execute the request
            response = await pact.execute_request("GET", "/api/stats")
            
            assert response.status_code == 200
            data = response.json()
            assert "nodes" in data
            assert "relationships" in data
            assert "indices" in data
            assert data["nodes"]["total"] == 15000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])