"""
Unit tests for enhanced meta-analysis tools.
"""

import pytest
import numpy as np
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from brain_researcher.services.tools.enhanced_meta_analysis import (
    CoordinateMetaAnalysisTool,
    ImageBasedMetaAnalysisTool,
    EffectSizeMetaAnalysisTool,
    LiteratureMiningTool,
    NetworkMetaAnalysisTool,
    NIMARE_AVAILABLE
)


class TestCoordinateMetaAnalysisTool:
    """Test coordinate-based meta-analysis tool."""
    
    @pytest.fixture
    def tool(self):
        """Create tool instance."""
        return CoordinateMetaAnalysisTool()
    
    def test_tool_metadata(self, tool):
        """Test tool name and description."""
        assert tool.get_tool_name() == "coordinate_meta_analysis"
        assert "coordinate-based meta-analysis" in tool.get_tool_description().lower()
    
    def test_generate_synthetic_coordinates(self, tool):
        """Test synthetic coordinate generation."""
        coords, study_ids = tool._generate_synthetic_coordinates()
        
        assert len(coords) > 0
        assert len(study_ids) == len(coords)
        assert all(len(c) == 3 for c in coords)  # Each coordinate has x, y, z
        assert all(isinstance(sid, str) for sid in study_ids)
    
    def test_mni_to_voxel_conversion(self, tool):
        """Test MNI to voxel coordinate conversion."""
        mni_coords = np.array([[0, 0, 0], [10, 20, 30], [-10, -20, -30]])
        voxel_coords = tool._mni_to_voxel(mni_coords)
        
        assert voxel_coords.shape == mni_coords.shape
        assert voxel_coords.dtype == np.int64 or voxel_coords.dtype == np.int32
    
    def test_run_kernel_ma(self, tool):
        """Test kernel-based meta-analysis fallback."""
        coords = [[0, 0, 0], [10, 10, 10], [-10, -10, -10]]
        study_ids = ["study_001", "study_002", "study_003"]
        
        results = tool._run_kernel_ma(coords, study_ids, kernel_size=10)
        
        assert "z_map" in results
        assert "p_map" in results
        assert "method" in results
        assert results["method"] == "Kernel"
        assert isinstance(results["z_map"], np.ndarray)
        assert isinstance(results["p_map"], np.ndarray)
    
    @pytest.mark.skipif(not NIMARE_AVAILABLE, reason="NiMARE not installed")
    def test_create_nimare_dataset(self, tool):
        """Test NiMARE dataset creation."""
        coords = [[0, 0, 0], [10, 10, 10], [-10, -10, -10]]
        study_ids = ["study_001", "study_001", "study_002"]
        
        dataset = tool._create_nimare_dataset(coords, study_ids)
        
        # Dataset might be None if NiMARE fails, which is okay
        # The tool will fall back to kernel method
        if dataset is not None:
            assert hasattr(dataset, 'coordinates')
    
    def test_apply_correction(self, tool):
        """Test multiple comparisons correction."""
        # Create fake results
        z_map = np.random.randn(50, 50, 50)
        z_map[20:30, 20:30, 20:30] = 3.0  # Add a cluster
        
        results = {
            "z_map": z_map,
            "p_map": 1 - np.abs(z_map) / 4  # Fake p-values
        }
        
        corrected = tool._apply_correction(results, voxel_thresh=0.05, cluster_thresh=0.05)
        
        assert "corrected_map" in corrected
        assert "uncorrected_map" in corrected
        assert "n_clusters" in corrected
        assert "peaks" in corrected
        assert "cluster_sizes" in corrected
    
    def test_run_with_synthetic_data(self, tool):
        """Test full run with synthetic data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = tool._run(
                coordinates=None,  # Will generate synthetic
                study_ids=None,
                method="ale",
                output_dir=tmpdir
            )
            
            assert result.status == "success"
            assert "n_studies" in result.data
            assert "n_foci" in result.data
            assert "output_files" in result.data
            
            # Check output files were created
            output_path = Path(tmpdir)
            assert (output_path / "report.json").exists()


class TestImageBasedMetaAnalysisTool:
    """Test image-based meta-analysis tool."""
    
    @pytest.fixture
    def tool(self):
        """Create tool instance."""
        return ImageBasedMetaAnalysisTool()
    
    def test_tool_metadata(self, tool):
        """Test tool name and description."""
        assert tool.get_tool_name() == "image_based_meta_analysis"
        assert "image-based meta-analysis" in tool.get_tool_description().lower()
    
    def test_generate_synthetic_images(self, tool):
        """Test synthetic image generation."""
        images, sample_sizes = tool._generate_synthetic_images()
        
        assert len(images) > 0
        assert len(sample_sizes) == len(images)
        assert all(isinstance(img, np.ndarray) for img in images)
        assert all(img.ndim == 3 for img in images)  # 3D images
        assert all(n > 0 for n in sample_sizes)
    
    def test_stouffers_z_method(self, tool):
        """Test Stouffer's Z-score method."""
        # Create fake z-score images
        images = [np.random.randn(10, 10, 10) for _ in range(5)]
        sample_sizes = [30, 40, 50, 60, 70]
        
        result = tool._stouffers_z(images, sample_sizes, weighted=True)
        
        assert "z_map" in result
        assert "p_map" in result
        assert "method" in result
        assert result["method"] == "Stouffer's Z"
        assert result["z_map"].shape == images[0].shape
    
    def test_fishers_method(self, tool):
        """Test Fisher's combined probability test."""
        images = [np.random.randn(10, 10, 10) for _ in range(3)]
        
        result = tool._fishers_method(images)
        
        assert "z_map" in result
        assert "p_map" in result
        assert result["method"] == "Fisher's method"
    
    def test_weighted_average(self, tool):
        """Test weighted average method."""
        images = [np.ones((5, 5, 5)) * i for i in range(3)]
        sample_sizes = [10, 20, 30]
        
        result = tool._weighted_average(images, sample_sizes)
        
        assert "z_map" in result
        assert "p_map" in result
        assert result["method"] == "Weighted average"
    
    def test_fixed_effects(self, tool):
        """Test fixed effects model."""
        images = [np.random.randn(5, 5, 5) for _ in range(4)]
        
        result = tool._fixed_effects(images)
        
        assert "z_map" in result
        assert "p_map" in result
        assert result["method"] == "Fixed effects"
    
    def test_run_with_synthetic_data(self, tool):
        """Test full run with synthetic data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = tool._run(
                image_files=None,  # Will generate synthetic
                method="stouffers",
                weighted=True,
                output_dir=tmpdir
            )
            
            assert result.status == "success"
            assert "n_studies" in result.data
            assert "method" in result.data
            assert "output_files" in result.data


class TestEffectSizeMetaAnalysisTool:
    """Test effect size meta-analysis tool."""
    
    @pytest.fixture
    def tool(self):
        """Create tool instance."""
        return EffectSizeMetaAnalysisTool()
    
    def test_tool_metadata(self, tool):
        """Test tool name and description."""
        assert tool.get_tool_name() == "effect_size_meta_analysis"
        assert "effect size" in tool.get_tool_description().lower()
    
    def test_generate_effect_sizes(self, tool):
        """Test synthetic effect size generation."""
        effects, ses, labels = tool._generate_effect_sizes()
        
        assert len(effects) > 0
        assert len(ses) == len(effects)
        assert len(labels) == len(effects)
        assert all(isinstance(e, float) for e in effects)
        assert all(se > 0 for se in ses)
    
    def test_fixed_effects_ma(self, tool):
        """Test fixed effects meta-analysis."""
        effects = [0.5, 0.3, 0.7, 0.4]
        ses = [0.1, 0.15, 0.12, 0.18]
        
        result = tool._fixed_effects_ma(effects, ses)
        
        assert "pooled_effect" in result
        assert "se" in result
        assert "ci" in result
        assert "z" in result
        assert "p_value" in result
        assert len(result["ci"]) == 2
        assert result["ci"][0] < result["pooled_effect"] < result["ci"][1]
    
    def test_random_effects_ma(self, tool):
        """Test random effects meta-analysis."""
        effects = [0.5, 0.3, 0.7, 0.4, 0.6]
        ses = [0.1, 0.15, 0.12, 0.18, 0.14]
        
        result = tool._random_effects_ma(effects, ses)
        
        assert "pooled_effect" in result
        assert "tau2" in result  # Between-study variance
        assert "ci" in result
        assert result["tau2"] >= 0
    
    def test_heterogeneity_test(self, tool):
        """Test heterogeneity testing."""
        effects = [0.5, 0.3, 0.7, 0.4]
        ses = [0.1, 0.15, 0.12, 0.18]
        
        heterogeneity = tool._test_heterogeneity(effects, ses)
        
        assert "Q" in heterogeneity
        assert "df" in heterogeneity
        assert "p_value" in heterogeneity
        assert "I2" in heterogeneity
        assert "interpretation" in heterogeneity
        assert 0 <= heterogeneity["I2"] <= 100
    
    def test_publication_bias(self, tool):
        """Test publication bias assessment."""
        effects = np.random.normal(0.5, 0.2, 10).tolist()
        ses = np.random.uniform(0.1, 0.3, 10).tolist()
        
        pub_bias = tool._test_publication_bias(effects, ses)
        
        assert "egger_test" in pub_bias
        assert "begg_test" in pub_bias
        assert "interpretation" in pub_bias
        assert "p_value" in pub_bias["egger_test"]
        assert "p_value" in pub_bias["begg_test"]
    
    def test_forest_plot_data(self, tool):
        """Test forest plot data creation."""
        effects = [0.5, 0.3, 0.7]
        ses = [0.1, 0.15, 0.12]
        labels = ["Study A", "Study B", "Study C"]
        results = {"pooled_effect": 0.5, "ci": [0.3, 0.7], "weights": [1, 0.8, 0.9]}
        
        forest_data = tool._create_forest_plot_data(effects, ses, labels, results)
        
        assert "studies" in forest_data
        assert "pooled" in forest_data
        assert len(forest_data["studies"]) == 3
        assert all("label" in s for s in forest_data["studies"])
        assert all("effect" in s for s in forest_data["studies"])
        assert all("ci_lower" in s for s in forest_data["studies"])
        assert all("ci_upper" in s for s in forest_data["studies"])
    
    def test_run_with_synthetic_data(self, tool):
        """Test full run with synthetic data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = tool._run(
                effect_sizes=None,  # Will generate synthetic
                model="random",
                output_dir=tmpdir
            )
            
            assert result.status == "success"
            assert "pooled_effect" in result.data
            assert "confidence_interval" in result.data
            assert "heterogeneity" in result.data
            assert "publication_bias" in result.data


class TestLiteratureMiningTool:
    """Test literature mining tool."""
    
    @pytest.fixture
    def tool(self):
        """Create tool instance."""
        return LiteratureMiningTool()
    
    def test_tool_metadata(self, tool):
        """Test tool name and description."""
        assert tool.get_tool_name() == "literature_mining"
        assert "literature" in tool.get_tool_description().lower()
    
    def test_simulate_article_extraction(self, tool):
        """Test simulated article extraction."""
        articles = tool._simulate_article_extraction("working memory")
        
        assert len(articles) > 0
        assert all("pmid" in a for a in articles)
        assert all("title" in a for a in articles)
        assert all("year" in a for a in articles)
    
    def test_extract_coordinates(self, tool):
        """Test coordinate extraction from article."""
        article = {
            "pmid": "PM12345",
            "title": "Test article",
            "n_subjects": 30
        }
        
        coords = tool._extract_coordinates(article)
        
        assert isinstance(coords, list)
        if coords:  # May be empty due to randomness
            assert all("x" in c for c in coords)
            assert all("y" in c for c in coords)
            assert all("z" in c for c in coords)
            assert all(c["pmid"] == "PM12345" for c in coords)
    
    def test_extract_effect_sizes(self, tool):
        """Test effect size extraction from article."""
        article = {
            "pmid": "PM12345",
            "n_subjects": 30
        }
        
        effects = tool._extract_effect_sizes(article)
        
        assert isinstance(effects, list)
        assert len(effects) > 0
        assert all("effect_size" in e for e in effects)
        assert all("standard_error" in e for e in effects)
        assert all("n" in e for e in effects)
    
    def test_extract_metadata(self, tool):
        """Test metadata extraction."""
        article = {
            "pmid": "PM12345",
            "title": "Test study",
            "year": 2023,
            "journal": "NeuroImage",
            "n_subjects": 30,
            "task": "working memory"
        }
        
        metadata = tool._extract_metadata(article)
        
        assert metadata["pmid"] == "PM12345"
        assert metadata["title"] == "Test study"
        assert metadata["year"] == 2023
        assert "scanner" in metadata
        assert "software" in metadata
    
    def test_run_with_synthetic_data(self, tool):
        """Test full run with synthetic data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = tool._run(
                search_query="attention",
                extract_coordinates=True,
                extract_effects=True,
                output_dir=tmpdir
            )
            
            assert result.status == "success"
            assert "n_articles" in result.data
            assert "n_coordinates" in result.data
            assert "n_effect_sizes" in result.data


class TestNetworkMetaAnalysisTool:
    """Test network meta-analysis tool."""
    
    @pytest.fixture
    def tool(self):
        """Create tool instance."""
        return NetworkMetaAnalysisTool()
    
    def test_tool_metadata(self, tool):
        """Test tool name and description."""
        assert tool.get_tool_name() == "network_meta_analysis"
        assert "network meta-analysis" in tool.get_tool_description().lower()
    
    def test_generate_network_data(self, tool):
        """Test synthetic network data generation."""
        comparisons = tool._generate_network_data()
        
        assert len(comparisons) > 0
        assert all("treatment1" in c for c in comparisons)
        assert all("treatment2" in c for c in comparisons)
        assert all("effect_size" in c for c in comparisons)
        assert all("standard_error" in c for c in comparisons)
    
    def test_build_network(self, tool):
        """Test network building from comparisons."""
        comparisons = [
            {"treatment1": "A", "treatment2": "B", "effect_size": 0.5, "standard_error": 0.1},
            {"treatment1": "B", "treatment2": "C", "effect_size": 0.3, "standard_error": 0.15},
            {"treatment1": "A", "treatment2": "C", "effect_size": 0.8, "standard_error": 0.12},
        ]
        
        network = tool._build_network(comparisons)
        
        assert "nodes" in network
        assert "edges" in network
        assert len(network["nodes"]) == 3  # A, B, C
        assert len(network["edges"]) == 3
    
    def test_check_connectivity(self, tool):
        """Test network connectivity check."""
        network = {
            "nodes": ["A", "B", "C"],
            "edges": [
                {"from": "A", "to": "B"},
                {"from": "B", "to": "C"}
            ]
        }
        
        connectivity = tool._check_connectivity(network)
        
        assert "is_connected" in connectivity
        assert connectivity["is_connected"] == True
    
    def test_calculate_ranking(self, tool):
        """Test treatment ranking calculation."""
        results = {
            "network_effects": {
                "treatment_A": {"effect": 0.8, "se": 0.1},
                "treatment_B": {"effect": 0.5, "se": 0.15},
                "treatment_C": {"effect": 0.3, "se": 0.12},
            }
        }
        
        ranking = tool._calculate_ranking(results)
        
        assert "rank_order" in ranking
        assert "p_scores" in ranking
        assert "sucra" in ranking
        assert ranking["rank_order"][0] == "treatment_A"  # Highest effect
        assert ranking["rank_order"][-1] == "treatment_C"  # Lowest effect
    
    def test_consistency_test(self, tool):
        """Test consistency testing."""
        network = {"nodes": ["A", "B", "C"], "edges": []}
        results = {}
        
        consistency = tool._test_consistency(network, results)
        
        assert "global_inconsistency" in consistency
        assert "p_value" in consistency
        assert "consistent" in consistency
        assert "interpretation" in consistency
    
    def test_run_with_synthetic_data(self, tool):
        """Test full run with synthetic data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = tool._run(
                comparisons=None,  # Will generate synthetic
                reference="control",
                method="netmeta",
                output_dir=tmpdir
            )
            
            assert result.status == "success"
            assert "n_treatments" in result.data
            assert "n_comparisons" in result.data
            assert "ranking" in result.data
            assert "consistency" in result.data