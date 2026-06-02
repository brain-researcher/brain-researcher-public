"""
Consumer contract tests: Agent -> BR-KG Service.

These tests define the contract expectations that the Agent has
when communicating with the BR-KG service for neuroimaging analysis tasks.
"""

import asyncio
from pathlib import Path

import pytest

try:
    from pact import Consumer, Provider
except ImportError:
    pytest.skip(
        "pact Consumer/Provider not available (pact-python v3?); skipping contract tests",
        allow_module_level=True,
    )

from ..pact_config import get_service_config, pact_config
from ..pact_helpers.mock_data import MockDataGenerator
from ..pact_helpers.pact_client import PactClient, PactMatchers


class TestAgentToBRKGContract:
    """Contract tests from Agent consumer perspective to BR-KG provider."""

    @pytest.fixture
    def pact_client(self):
        """Create Pact client for Agent -> BR-KG contract."""
        agent_config = get_service_config("agent")
        br_kg_config = get_service_config("br_kg")
        return PactClient(agent_config, br_kg_config)

    @pytest.mark.asyncio
    async def test_concept_lookup_contract(self, pact_client):
        """Test concept lookup for analysis context."""
        async with pact_client as pact:
            search_request = {
                "query": "motor cortex",
                "context": "analysis",
                "limit": 5,
            }

            (
                pact.given("knowledge graph has concepts")
                .upon_receiving("a concept lookup request from agent")
                .with_request(
                    method="POST",
                    path="/api/concepts/search",
                    headers={"Content-Type": "application/json"},
                    body=search_request,
                )
                .will_respond_with(
                    status=200,
                    headers={"Content-Type": "application/json"},
                    body={
                        "concepts": [
                            {
                                "id": PactMatchers.uuid(),
                                "name": "Motor Cortex",
                                "definition": "Primary motor cortex",
                                "coordinates": {
                                    "mni": [-42, -24, 58],
                                    "atlas": "MNI152",
                                },
                                "confidence": 0.95,
                            }
                        ],
                        "total_count": 1,
                        "processing_time_ms": 25,
                    },
                )
            )

            # Execute the request
            response = await pact.execute_request(
                "POST",
                "/api/concepts/search",
                headers={"Content-Type": "application/json"},
                json_data=search_request,
            )

            assert response.status_code == 200
            data = response.json()
            assert "concepts" in data
            assert len(data["concepts"]) > 0
            assert "coordinates" in data["concepts"][0]

    @pytest.mark.asyncio
    async def test_spatial_query_contract(self, pact_client):
        """Test spatial coordinate queries for brain region analysis."""
        async with pact_client as pact:
            spatial_request = {
                "coordinates": [
                    {"x": -42, "y": -24, "z": 58},
                    {"x": 42, "y": -24, "z": 58},
                ],
                "space": "MNI152",
                "radius_mm": 6,
            }

            (
                pact.given("knowledge graph has spatial mappings")
                .upon_receiving("a spatial coordinate query from agent")
                .with_request(
                    method="POST",
                    path="/api/coordinates/to-concepts",
                    headers={"Content-Type": "application/json"},
                    body=spatial_request,
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
                                        "concept_id": PactMatchers.uuid(),
                                        "name": "Left Motor Cortex",
                                        "confidence": 0.95,
                                        "distance_mm": 2.1,
                                    }
                                ],
                            }
                        ],
                        "space": "MNI152",
                        "total_concepts": 2,
                    },
                )
            )

            # Execute the request
            response = await pact.execute_request(
                "POST",
                "/api/coordinates/to-concepts",
                headers={"Content-Type": "application/json"},
                json_data=spatial_request,
            )

            assert response.status_code == 200
            data = response.json()
            assert "mappings" in data
            assert data["space"] == "MNI152"

    @pytest.mark.asyncio
    async def test_dataset_recommendation_contract(self, pact_client):
        """Test dataset recommendation for analysis tasks."""
        async with pact_client as pact:
            recommendation_request = {
                "task_type": "GLM",
                "brain_regions": ["motor cortex"],
                "modality": "fMRI",
                "min_subjects": 10,
            }

            (
                pact.given("knowledge graph has datasets")
                .upon_receiving("a dataset recommendation request from agent")
                .with_request(
                    method="POST",
                    path="/api/datasets/recommend",
                    headers={"Content-Type": "application/json"},
                    body=recommendation_request,
                )
                .will_respond_with(
                    status=200,
                    headers={"Content-Type": "application/json"},
                    body={
                        "recommended_datasets": [
                            {
                                "id": PactMatchers.dataset_id(),
                                "name": "Motor Task Dataset",
                                "relevance_score": 0.92,
                                "n_subjects": 24,
                                "tasks": ["motor"],
                                "modality": ["fMRI"],
                                "reason": "High relevance to motor cortex analysis",
                            }
                        ],
                        "total_count": 1,
                        "recommendation_metadata": {
                            "algorithm": "semantic_similarity",
                            "confidence": 0.85,
                        },
                    },
                )
            )

            # Execute the request
            response = await pact.execute_request(
                "POST",
                "/api/datasets/recommend",
                headers={"Content-Type": "application/json"},
                json_data=recommendation_request,
            )

            assert response.status_code == 200
            data = response.json()
            assert "recommended_datasets" in data
            assert data["recommended_datasets"][0]["relevance_score"] > 0.8

    @pytest.mark.asyncio
    async def test_analysis_context_contract(self, pact_client):
        """Test retrieving analysis context for tool selection."""
        async with pact_client as pact:
            context_request = {
                "dataset_id": "motor-task-001",
                "analysis_type": "GLM",
                "brain_regions": ["motor cortex", "visual cortex"],
            }

            (
                pact.given("dataset exists with analysis context")
                .upon_receiving("an analysis context request from agent")
                .with_request(
                    method="POST",
                    path="/api/analysis/context",
                    headers={"Content-Type": "application/json"},
                    body=context_request,
                )
                .will_respond_with(
                    status=200,
                    headers={"Content-Type": "application/json"},
                    body={
                        "dataset": {
                            "id": "motor-task-001",
                            "name": "Motor Task Dataset",
                            "n_subjects": 24,
                            "tasks": ["motor"],
                            "preprocessing_level": "fmriprep",
                        },
                        "analysis_recommendations": {
                            "suggested_tools": ["fsl_glm", "nilearn_glm"],
                            "contrasts": [
                                {
                                    "name": "motor > rest",
                                    "description": "Motor activation vs rest",
                                }
                            ],
                            "atlases": ["AAL", "Harvard-Oxford"],
                            "statistical_thresholds": {
                                "cluster_threshold": 0.001,
                                "extent_threshold": 10,
                            },
                        },
                        "related_studies": [
                            {
                                "study_id": "study_123",
                                "title": "Motor cortex activation patterns",
                                "similarity": 0.87,
                            }
                        ],
                    },
                )
            )

            # Execute the request
            response = await pact.execute_request(
                "POST",
                "/api/analysis/context",
                headers={"Content-Type": "application/json"},
                json_data=context_request,
            )

            assert response.status_code == 200
            data = response.json()
            assert "dataset" in data
            assert "analysis_recommendations" in data
            assert "suggested_tools" in data["analysis_recommendations"]

    @pytest.mark.asyncio
    async def test_literature_lookup_contract(self, pact_client):
        """Test literature lookup for analysis validation."""
        async with pact_client as pact:
            literature_request = {
                "concepts": ["motor cortex", "fMRI"],
                "analysis_type": "GLM",
                "limit": 5,
            }

            (
                pact.given("knowledge graph has literature")
                .upon_receiving("a literature lookup request from agent")
                .with_request(
                    method="POST",
                    path="/api/literature/search",
                    headers={"Content-Type": "application/json"},
                    body=literature_request,
                )
                .will_respond_with(
                    status=200,
                    headers={"Content-Type": "application/json"},
                    body={
                        "papers": [
                            {
                                "pmid": "12345678",
                                "title": "Motor cortex activation during finger tapping",
                                "authors": ["Smith, J.", "Jones, M."],
                                "journal": "NeuroImage",
                                "year": 2022,
                                "doi": "10.1016/j.neuroimage.2022.12345",
                                "relevance_score": 0.89,
                                "coordinates": [
                                    {"x": -42, "y": -24, "z": 58, "region": "Left M1"}
                                ],
                                "contrasts": ["motor > rest"],
                                "sample_size": 20,
                            }
                        ],
                        "total_count": 1,
                        "search_metadata": {
                            "query_expansion": True,
                            "semantic_similarity": 0.85,
                        },
                    },
                )
            )

            # Execute the request
            response = await pact.execute_request(
                "POST",
                "/api/literature/search",
                headers={"Content-Type": "application/json"},
                json_data=literature_request,
            )

            assert response.status_code == 200
            data = response.json()
            assert "papers" in data
            assert data["papers"][0]["relevance_score"] > 0.8

    @pytest.mark.asyncio
    async def test_prior_analysis_lookup_contract(self, pact_client):
        """Test lookup of prior analyses for comparison."""
        dataset_id = "motor-task-001"

        async with pact_client as pact:
            (
                pact.given("dataset has prior analyses")
                .upon_receiving("a prior analysis lookup from agent")
                .with_request(
                    method="GET",
                    path=f"/api/datasets/{dataset_id}/analyses",
                    query={"analysis_type": "GLM", "limit": "10"},
                )
                .will_respond_with(
                    status=200,
                    headers={"Content-Type": "application/json"},
                    body={
                        "analyses": [
                            {
                                "id": "analysis_001",
                                "type": "GLM",
                                "description": "First-level GLM analysis",
                                "tool": "FSL",
                                "parameters": {"smoothing": 6, "threshold": 0.001},
                                "results": {
                                    "significant_clusters": 5,
                                    "peak_coordinates": [
                                        {"x": -42, "y": -24, "z": 58, "t_value": 8.45}
                                    ],
                                },
                                "created_at": PactMatchers.iso_datetime(),
                                "quality_score": 0.92,
                            }
                        ],
                        "total_count": 1,
                        "similar_analyses": [
                            {
                                "dataset_id": "motor-task-002",
                                "analysis_id": "analysis_002",
                                "similarity_score": 0.78,
                            }
                        ],
                    },
                )
            )

            # Execute the request
            response = await pact.execute_request(
                "GET",
                f"/api/datasets/{dataset_id}/analyses",
                params={"analysis_type": "GLM", "limit": 10},
            )

            assert response.status_code == 200
            data = response.json()
            assert "analyses" in data
            assert "similar_analyses" in data

    @pytest.mark.asyncio
    async def test_knowledge_graph_unavailable_contract(self, pact_client):
        """Test graceful handling when knowledge graph is unavailable."""
        async with pact_client as pact:
            search_request = {"query": "motor cortex", "context": "analysis"}

            (
                pact.given("knowledge graph is temporarily unavailable")
                .upon_receiving("a concept search when KG is unavailable")
                .with_request(
                    method="POST",
                    path="/api/concepts/search",
                    headers={"Content-Type": "application/json"},
                    body=search_request,
                )
                .will_respond_with(
                    status=503,
                    headers={"Content-Type": "application/json"},
                    body={
                        "error": {
                            "code": "SERVICE_UNAVAILABLE",
                            "message": "Knowledge graph is temporarily unavailable",
                            "retry_after": 30,
                            "fallback_available": True,
                            "timestamp": PactMatchers.iso_datetime(),
                        }
                    },
                )
            )

            # Execute the request
            response = await pact.execute_request(
                "POST",
                "/api/concepts/search",
                headers={"Content-Type": "application/json"},
                json_data=search_request,
            )

            assert response.status_code == 503
            data = response.json()
            assert "error" in data
            assert data["error"]["code"] == "SERVICE_UNAVAILABLE"
            assert "retry_after" in data["error"]

    @pytest.mark.asyncio
    async def test_bulk_concept_lookup_contract(self, pact_client):
        """Test bulk concept lookup for batch processing."""
        async with pact_client as pact:
            bulk_request = {
                "coordinates": [
                    {"x": -42, "y": -24, "z": 58},
                    {"x": 42, "y": -24, "z": 58},
                    {"x": 0, "y": -52, "z": -8},
                ],
                "space": "MNI152",
                "radius_mm": 8,
                "return_all_matches": True,
            }

            (
                pact.given("knowledge graph has spatial mappings")
                .upon_receiving("a bulk concept lookup from agent")
                .with_request(
                    method="POST",
                    path="/api/coordinates/bulk-lookup",
                    headers={"Content-Type": "application/json"},
                    body=bulk_request,
                )
                .will_respond_with(
                    status=200,
                    headers={"Content-Type": "application/json"},
                    body={
                        "results": [
                            {
                                "coordinate": {"x": -42, "y": -24, "z": 58},
                                "concepts": [
                                    {
                                        "concept_id": PactMatchers.uuid(),
                                        "name": "Left Primary Motor Cortex",
                                        "confidence": 0.95,
                                    }
                                ],
                            },
                            {
                                "coordinate": {"x": 42, "y": -24, "z": 58},
                                "concepts": [
                                    {
                                        "concept_id": PactMatchers.uuid(),
                                        "name": "Right Primary Motor Cortex",
                                        "confidence": 0.93,
                                    }
                                ],
                            },
                        ],
                        "processing_stats": {
                            "total_coordinates": 3,
                            "successful_lookups": 2,
                            "failed_lookups": 1,
                            "processing_time_ms": 150,
                        },
                    },
                )
            )

            # Execute the request
            response = await pact.execute_request(
                "POST",
                "/api/coordinates/bulk-lookup",
                headers={"Content-Type": "application/json"},
                json_data=bulk_request,
            )

            assert response.status_code == 200
            data = response.json()
            assert "results" in data
            assert "processing_stats" in data
            assert data["processing_stats"]["total_coordinates"] == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
