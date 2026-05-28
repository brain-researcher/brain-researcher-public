"""Unit tests for Allen Brain Atlas loader."""

import os

import numpy as np
import pytest

from brain_researcher.core.ingestion.api.allen_client import AllenBrainClient
from brain_researcher.core.ingestion.loaders.allen_brain_unified import (
    AllenBrainUnifiedLoader,
)


def _run_allen_api_tests() -> bool:
    return os.getenv("BR_RUN_ALLEN_API_TESTS", "").lower() in {"1", "true", "yes"}


class TestAllenBrainClient:
    """Test suite for AllenBrainClient."""

    @pytest.fixture
    def client(self):
        """Create client instance."""
        return AllenBrainClient()

    def test_get_sample_donors(self, client):
        """Test sample donor data."""
        donors = client._get_sample_donors()

        assert len(donors) == 6  # Should have 6 donors

        for donor in donors:
            assert "id" in donor
            assert "age" in donor
            assert "sex" in donor

    def test_get_sample_structures(self, client):
        """Test sample brain structures."""
        structures = client._get_sample_structures()

        assert len(structures) >= 10

        # Check structure properties
        for struct in structures:
            assert "id" in struct
            assert "name" in struct
            assert "acronym" in struct

    def test_get_sample_expression(self, client):
        """Test sample expression data."""
        expression = client._get_sample_expression("H0351.2001", ["FOXP2", "BDNF"])

        assert expression["donor_id"] == "H0351.2001"
        assert expression["genes"] == ["FOXP2", "BDNF"]
        assert len(expression["expression"]) > 0

        # Check expression values
        for expr in expression["expression"]:
            assert "structure_id" in expr
            assert "gene" in expr
            assert "expression_level" in expr
            assert expr["expression_level"] >= 0


class TestAllenBrainUnifiedLoader:
    """Test suite for AllenBrainUnifiedLoader."""

    @pytest.fixture
    def loader(self):
        """Create loader instance."""
        return AllenBrainUnifiedLoader()

    @pytest.mark.skipif(
        not _run_allen_api_tests(),
        reason="Allen API data not available; set BR_RUN_ALLEN_API_TESTS=1 to enable.",
    )
    def test_load_gene_expression(self, loader):
        """Test gene expression loading."""
        result = loader.load_gene_expression(
            gene_symbols=["FOXP2", "BDNF"],
            donors=None,  # Use all available
        )

        assert "donors" in result
        assert "genes" in result
        assert "expression" in result
        assert "statistics" in result

        assert result["donors"] > 0
        assert result["genes"] == ["FOXP2", "BDNF"]

    def test_process_expression(self, loader):
        """Test expression data processing."""
        raw_expression = {
            "expression": [
                {
                    "structure_id": 1,
                    "structure_name": "Frontal",
                    "gene": "FOXP2",
                    "expression_level": 5.0,
                },
                {
                    "structure_id": 1,
                    "structure_name": "Frontal",
                    "gene": "BDNF",
                    "expression_level": 3.0,
                },
                {
                    "structure_id": 2,
                    "structure_name": "Parietal",
                    "gene": "FOXP2",
                    "expression_level": 4.0,
                },
            ]
        }

        processed = loader._process_expression(raw_expression)

        assert "by_structure" in processed
        assert 1 in processed["by_structure"]
        assert 2 in processed["by_structure"]

        # Check normalization occurred
        struct1 = processed["by_structure"][1]
        assert "FOXP2" in struct1["genes"]
        assert "BDNF" in struct1["genes"]

    def test_calculate_expression_stats(self, loader):
        """Test expression statistics calculation."""
        expression_data = {
            "donor1": {
                "by_structure": {
                    1: {"genes": {"FOXP2": 0.5, "BDNF": -0.3}},
                    2: {"genes": {"FOXP2": 0.8, "BDNF": 0.2}},
                }
            },
            "donor2": {
                "by_structure": {
                    1: {"genes": {"FOXP2": 0.3, "BDNF": -0.1}},
                    2: {"genes": {"FOXP2": 0.6, "BDNF": 0.4}},
                }
            },
        }

        stats = loader._calculate_expression_stats(expression_data)

        assert "gene_stats" in stats
        assert "structure_stats" in stats
        assert "total_measurements" in stats

        # Check gene statistics
        assert "FOXP2" in stats["gene_stats"]
        assert "mean" in stats["gene_stats"]["FOXP2"]
        assert "std" in stats["gene_stats"]["FOXP2"]

    def test_build_connectivity_matrix(self, loader):
        """Test connectivity matrix construction."""
        connectivity_data = {
            1: {"connections": {2: 0.5, 3: 0.3}},
            2: {"connections": {1: 0.4, 3: 0.6}},
            3: {"connections": {1: 0.2, 2: 0.7}},
        }

        matrix = loader._build_connectivity_matrix(connectivity_data)

        assert matrix.shape == (3, 3)

        # Check symmetry
        assert np.allclose(matrix, matrix.T)

        # Check values
        assert matrix[0, 1] > 0  # Connection between 1 and 2
        assert matrix[1, 2] > 0  # Connection between 2 and 3

    def test_map_allen_to_mni(self, loader):
        """Test coordinate space mapping."""
        allen_coords = [5000, 6000, 7000]  # in micrometers
        mni_coords = loader.map_allen_to_mni(allen_coords)

        assert len(mni_coords) == 3

        # Check conversion (micrometers to mm)
        assert mni_coords[0] < allen_coords[0]  # Should be smaller after conversion

    def test_load_atlas_hierarchy(self, loader, monkeypatch):
        """Test atlas-only hierarchy loading."""
        structures = [
            {"id": 1, "name": "Root", "acronym": "ROOT"},
            {
                "id": 2,
                "name": "Visual cortex",
                "acronym": "VIS",
                "parent_structure_id": 1,
            },
        ]
        monkeypatch.setattr(loader.client, "get_structures", lambda: structures)

        result = loader.load_atlas_hierarchy(structure_ids=[2])

        assert result["atlas"] == "AllenCCFv3"
        assert result["structures_count"] == 1
        assert result["structure_ids"] == [2]
        assert loader.structures == [structures[1]]

    def test_export_for_kg(self, loader):
        """Test knowledge graph export."""
        # Load some data first
        loader.structures = [
            {
                "id": 1,
                "name": "Cerebrum",
                "acronym": "CH",
                "graph_order": 1,
                "depth": 1,
            },
            {
                "id": 2,
                "name": "Parietal cortex",
                "acronym": "PTLp",
                "parent_structure_id": 1,
                "graph_order": 2,
                "depth": 2,
            },
        ]

        loader.expression_data = {
            "donor1": {"by_structure": {1: {"genes": {"FOXP2": 0.5}}}}
        }

        loader.connectivity_data = {1: {"connections": {2: 0.8}}}

        kg_data = loader.export_for_kg()

        assert "nodes" in kg_data
        assert "edges" in kg_data
        assert "metadata" in kg_data
        assert kg_data["metadata"]["atlas"] == "AllenCCFv3"

        # Check node types
        node_types = {n["type"] for n in kg_data["nodes"]}
        assert "Atlas" in node_types
        assert "TemplateSpace" in node_types
        assert "BrainRegion" in node_types
        assert "GeneExpression" in node_types

        atlas_nodes = {
            node["id"]: node["properties"]
            for node in kg_data["nodes"]
            if node["type"] == "Atlas"
        }
        template_spaces = {
            node["id"]: node["properties"]
            for node in kg_data["nodes"]
            if node["type"] == "TemplateSpace"
        }
        brain_regions = {
            node["id"]: node["properties"]
            for node in kg_data["nodes"]
            if node["type"] == "BrainRegion"
        }
        assert "atlas:allenccfv3" in atlas_nodes
        assert atlas_nodes["atlas:allenccfv3"]["name"] == "Allen Common Coordinate Framework v3"
        assert atlas_nodes["atlas:allenccfv3"]["atlas"] == "AllenCCFv3"
        assert "space:allenccfv3" in template_spaces
        assert template_spaces["space:allenccfv3"]["name"] == "Allen CCFv3"
        assert template_spaces["space:allenccfv3"]["source"] == "Allen Brain Atlas"
        assert "ccfv3:1" in brain_regions
        assert "ccfv3:2" in brain_regions
        assert brain_regions["ccfv3:2"]["atlas"] == "AllenCCFv3"
        assert brain_regions["ccfv3:2"]["abbreviation"] == "PTLp"

        # Check edge types
        edge_types = {e["type"] for e in kg_data["edges"]}
        assert "IN_SPACE" in edge_types
        assert "HAS_REGION" in edge_types
        assert "PART_OF" in edge_types
        assert "EXPRESSED_IN" in edge_types

        assert any(
            edge["type"] == "IN_SPACE"
            and edge["source"] == "atlas:allenccfv3"
            and edge["target"] == "space:allenccfv3"
            for edge in kg_data["edges"]
        )
        assert any(
            edge["type"] == "HAS_REGION"
            and edge["source"] == "atlas:allenccfv3"
            and edge["target"] == "ccfv3:2"
            for edge in kg_data["edges"]
        )
        assert any(
            edge["type"] == "PART_OF"
            and edge["source"] == "ccfv3:2"
            and edge["target"] == "ccfv3:1"
            for edge in kg_data["edges"]
        )


class TestIntegration:
    """Integration tests for Allen Brain data pipeline."""

    @pytest.mark.skipif(
        not _run_allen_api_tests(),
        reason="Allen API data not available; set BR_RUN_ALLEN_API_TESTS=1 to enable.",
    )
    def test_full_pipeline(self):
        """Test complete data loading pipeline."""
        loader = AllenBrainUnifiedLoader()

        # Load minimal data
        gene_result = loader.load_gene_expression(gene_symbols=["FOXP2"], donors=None)

        # Export to KG
        kg_data = loader.export_for_kg()

        # Verify complete pipeline
        assert gene_result["donors"] > 0
        assert len(kg_data["nodes"]) > 0
        assert "metadata" in kg_data
        assert kg_data["metadata"]["donors"] > 0
