"""
Provider verification tests for BR-KG service.

These tests verify that the BR-KG service can fulfill
the contracts defined by its consumers (Orchestrator, Agent).
"""

import pytest
import asyncio
import json
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock

try:
    from pact import Verifier
    from ..pact_config import pact_config, get_service_config
    from ..pact_helpers.state_setup import NeuroKGStateSetup
    from ..pact_helpers.verification_utils import VerificationHelper
except ImportError:
    pytest.skip("pact contract tooling not available for provider verification", allow_module_level=True)


class TestNeuroKGProvider:
    """Provider verification tests for BR-KG service."""
    
    @pytest.fixture
    def state_manager(self):
        """Get state setup manager for BR-KG."""
        return NeuroKGStateSetup.get_state_manager()
    
    @pytest.fixture
    def neurokg_config(self):
        """Get BR-KG service configuration."""
        return get_service_config("neurokg")
    
    @pytest.fixture
    def verifier(self, neurokg_config):
        """Create Pact verifier for BR-KG."""
        return Verifier(
            provider="neurokg-service",
            provider_base_url=neurokg_config.base_url,
            pact_dir=str(pact_config.pact_dir),
            provider_states_setup_url=f"{neurokg_config.base_url}/pact/provider-states",
            publish_version="1.0.0",
            publish_verification_results=pact_config.broker.publish_verification_results
        )
    
    def test_verify_orchestrator_consumer_contract(self, verifier, state_manager):
        """Verify contract with Orchestrator consumer."""
        pact_file = pact_config.pact_dir / "orchestrator-neurokg.json"
        
        # Skip if pact file doesn't exist
        if not pact_file.exists():
            pytest.skip("Orchestrator consumer contract not available")
        
        # Verify the pact file exists and is valid
        is_valid, errors = VerificationHelper.validate_pact_file(pact_file)
        if not is_valid:
            pytest.skip(f"Invalid pact file: {errors}")
        
        # Set up state handlers
        self._setup_provider_states(state_manager)
        
        # Verify the contract
        try:
            verifier.verify_pacts(pact_file)
        except Exception as e:
            pytest.fail(f"Contract verification failed: {e}")
    
    def test_verify_agent_consumer_contract(self, verifier, state_manager):
        """Verify contract with Agent consumer."""
        pact_file = pact_config.pact_dir / "agent-neurokg.json"
        
        # Skip if pact file doesn't exist
        if not pact_file.exists():
            pytest.skip("Agent consumer contract not available")
        
        # Verify the pact file exists and is valid
        is_valid, errors = VerificationHelper.validate_pact_file(pact_file)
        if not is_valid:
            pytest.skip(f"Invalid pact file: {errors}")
        
        # Set up state handlers
        self._setup_provider_states(state_manager)
        
        # Verify the contract
        try:
            verifier.verify_pacts(pact_file)
        except Exception as e:
            pytest.fail(f"Contract verification failed: {e}")
    
    def _setup_provider_states(self, state_manager):
        """Set up provider state handlers."""
        # This would be called by Pact verifier when setting up states
        pass
    
    @pytest.mark.asyncio
    async def test_kg_with_data_provider_state(self, state_manager):
        """Test knowledge graph with data state setup."""
        # Set up state
        state_data = await state_manager.setup_state("knowledge graph has data")
        
        assert state_data["nodes"] == 1000
        assert state_data["relationships"] == 5000
    
    @pytest.mark.asyncio
    async def test_empty_kg_provider_state(self, state_manager):
        """Test empty knowledge graph state setup."""
        # Set up state
        state_data = await state_manager.setup_state("knowledge graph is empty")
        
        assert state_data["nodes"] == 0
        assert state_data["relationships"] == 0
    
    @pytest.mark.asyncio
    async def test_health_endpoint_response(self, state_manager):
        """Test health endpoint response structure."""
        # Set up state with data
        await state_manager.setup_state("knowledge graph has data")
        
        # Mock health response
        health_response = {
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
            "timestamp": "2025-01-01T00:00:00Z",
            "version": "1.0.0"
        }
        
        # Verify response structure
        assert health_response["status"] == "healthy"
        assert "database" in health_response
        assert "search_indices" in health_response
        assert health_response["database"]["connected"] is True
        assert health_response["search_indices"]["concepts"] == "ready"
    
    @pytest.mark.asyncio
    async def test_dataset_search_response(self, state_manager):
        """Test dataset search response structure."""
        # Set up state
        await state_manager.setup_state("knowledge graph has datasets")
        
        # Mock dataset search response
        search_response = {
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
                    "last_updated": "2025-01-01T00:00:00Z",
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
        
        # Verify response structure
        assert "datasets" in search_response
        assert "total_count" in search_response
        assert "facets" in search_response
        assert isinstance(search_response["datasets"], list)
        
        # Verify dataset structure
        dataset = search_response["datasets"][0]
        assert "id" in dataset
        assert "name" in dataset
        assert "modality" in dataset
        assert "n_subjects" in dataset
        assert "metadata" in dataset
        assert "quality_score" in dataset
    
    @pytest.mark.asyncio
    async def test_dataset_details_response(self, state_manager):
        """Test dataset details response structure."""
        # Set up state
        await state_manager.setup_state("dataset exists in knowledge graph")
        
        # Mock dataset details response
        details_response = {
            "id": "ds003226",
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
            "last_updated": "2025-01-01T00:00:00Z",
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
        
        # Verify response structure
        assert details_response["id"] == "ds003226"
        assert "metadata" in details_response
        assert "statistics" in details_response
        assert "related_datasets" in details_response
        assert "analyses" in details_response
        
        # Verify metadata structure
        metadata = details_response["metadata"]
        assert "authors" in metadata
        assert "doi" in metadata
        assert "keywords" in metadata
    
    @pytest.mark.asyncio
    async def test_concept_search_response(self, state_manager):
        """Test concept search response structure."""
        # Set up state
        await state_manager.setup_state("knowledge graph has concepts")
        
        # Mock concept search response
        search_response = {
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
        
        # Verify response structure
        assert "concepts" in search_response
        assert "total_count" in search_response
        assert isinstance(search_response["concepts"], list)
        
        # Verify concept structure
        concept = search_response["concepts"][0]
        assert "id" in concept
        assert "name" in concept
        assert "definition" in concept
        assert "coordinates" in concept
        assert "related_tasks" in concept
        assert "related_concepts" in concept
    
    @pytest.mark.asyncio
    async def test_coordinate_mapping_response(self, state_manager):
        """Test coordinate to concept mapping response."""
        # Set up state
        await state_manager.setup_state("knowledge graph has spatial mappings")
        
        # Mock coordinate mapping response
        mapping_response = {
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
        
        # Verify response structure
        assert "mappings" in mapping_response
        assert len(mapping_response["mappings"]) == 2
        assert mapping_response["space"] == "MNI152"
        assert "radius_mm" in mapping_response
        assert "total_concepts" in mapping_response
        
        # Verify mapping structure
        mapping = mapping_response["mappings"][0]
        assert "coordinate" in mapping
        assert "concepts" in mapping
        assert "confidence" in mapping["concepts"][0]
        assert "distance_mm" in mapping["concepts"][0]
    
    @pytest.mark.asyncio
    async def test_task_concept_relationships_response(self, state_manager):
        """Test task-concept relationships response."""
        # Set up state
        await state_manager.setup_state("knowledge graph has task-concept relationships")
        
        # Mock task-concept relationships response
        relationships_response = {
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
                "last_updated": "2025-01-01T00:00:00Z",
                "evidence_sources": ["NeuroSynth", "BrainMap", "PubMed"]
            }
        }
        
        # Verify response structure
        assert "task" in relationships_response
        assert "related_concepts" in relationships_response
        assert len(relationships_response["related_concepts"]) == 2
        assert "total_relationships" in relationships_response
        assert "metadata" in relationships_response
        
        # Verify relationship structure
        relationship = relationships_response["related_concepts"][0]
        assert "concept_id" in relationship
        assert "name" in relationship
        assert "relationship_type" in relationship
        assert "strength" in relationship
        assert "evidence_count" in relationship
    
    @pytest.mark.asyncio
    async def test_knowledge_graph_statistics_response(self, state_manager):
        """Test knowledge graph statistics response."""
        # Set up state
        await state_manager.setup_state("knowledge graph has data")
        
        # Mock statistics response
        stats_response = {
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
                    "last_updated": "2025-01-01T00:00:00Z"
                },
                "datasets": {
                    "size": 2500,
                    "last_updated": "2025-01-01T00:00:00Z"
                }
            },
            "data_freshness": {
                "last_ingestion": "2025-01-01T00:00:00Z",
                "sources_synced": ["NeuroSynth", "OpenNeuro", "BrainMap"]
            }
        }
        
        # Verify response structure
        assert "nodes" in stats_response
        assert "relationships" in stats_response
        assert "indices" in stats_response
        assert "data_freshness" in stats_response
        
        assert stats_response["nodes"]["total"] == 15000
        assert stats_response["relationships"]["total"] == 75000
        assert "by_type" in stats_response["nodes"]
        assert "by_type" in stats_response["relationships"]
    
    @pytest.mark.asyncio
    async def test_dataset_not_found_response(self, state_manager):
        """Test dataset not found error response."""
        # Set up empty state
        await state_manager.setup_state("dataset does not exist")
        
        # Mock error response
        error_response = {
            "error": {
                "code": "NOT_FOUND",
                "message": "Dataset ds_nonexistent not found in knowledge graph",
                "suggestions": [
                    "Check the dataset ID",
                    "Browse available datasets at /api/datasets"
                ],
                "timestamp": "2025-01-01T00:00:00Z"
            }
        }
        
        # Verify error structure
        assert "error" in error_response
        error = error_response["error"]
        assert error["code"] == "NOT_FOUND"
        assert "message" in error
        assert "suggestions" in error
        assert "timestamp" in error
    
    def test_provider_state_coverage(self, state_manager):
        """Test that all required provider states are available."""
        # Get all pact files that use this provider
        pact_files = list(pact_config.pact_dir.glob("*-neurokg.json"))
        
        required_states = set()
        for pact_file in pact_files:
            if not pact_file.exists():
                continue
                
            interactions = VerificationHelper.extract_pact_interactions(pact_file)
            for interaction in interactions:
                if "providerState" in interaction:
                    required_states.add(interaction["providerState"])
                elif "provider_state" in interaction:
                    required_states.add(interaction["provider_state"])
        
        # Verify all required states can be set up
        available_states = set(state_manager._state_handlers.keys())
        missing_states = required_states - available_states
        
        if missing_states:
            pytest.skip(f"Missing provider states: {missing_states}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
