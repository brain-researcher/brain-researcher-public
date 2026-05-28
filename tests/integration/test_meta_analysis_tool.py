"""Test suite for meta-analysis tool."""

import pytest
import numpy as np
import tempfile
from pathlib import Path

from brain_researcher.services.tools.meta_analysis_tool import MetaAnalysisTool


class TestMetaAnalysisTool:
    """Test meta-analysis tool."""
    
    def test_ale_analysis(self):
        """Test ALE coordinate-based meta-analysis."""
        tool = MetaAnalysisTool()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test coordinates (3 studies with multiple foci each)
            np.random.seed(42)
            coordinates = np.array([
                # Study 1 - frontal activation
                [[10, 50, 30], [15, 45, 35], [12, 48, 32]],
                # Study 2 - parietal activation  
                [[-30, -60, 40], [-35, -55, 45], [-32, -58, 42]],
                # Study 3 - temporal activation
                [[50, -20, -10], [55, -15, -5], [52, -18, -8]]
            ])
            
            sample_sizes = np.array([20, 25, 18])
            
            coords_file = Path(tmpdir) / "coordinates.npy"
            samples_file = Path(tmpdir) / "samples.npy"
            np.save(coords_file, coordinates)
            np.save(samples_file, sample_sizes)
            
            # Run ALE
            result = tool._run(
                input_type="coordinates",
                coordinates_file=str(coords_file),
                sample_sizes_file=str(samples_file),
                method="ALE",
                ale_fwhm=10.0,
                n_iterations=100,  # Small for testing
                output_dir=tmpdir,
                visualize=False,
                verbose=False
            )
            
            assert result.status == "success"
            assert "outputs" in result.data
            assert "summary" in result.data
            assert "n_studies" in result.data["summary"]
            assert result.data["summary"]["n_studies"] == 3
            assert "n_foci" in result.data["summary"]
            assert result.data["summary"]["n_foci"] == 9
    
    def test_mkda_analysis(self):
        """Test MKDA coordinate-based meta-analysis."""
        tool = MetaAnalysisTool()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test coordinates
            np.random.seed(42)
            coordinates = np.array([
                [[0, 0, 0], [10, 10, 10]],
                [[5, 5, 5], [15, 15, 15]],
                [[2, 2, 2], [12, 12, 12]]
            ])
            
            coords_file = Path(tmpdir) / "coordinates.npy"
            np.save(coords_file, coordinates)
            
            # Run MKDA
            result = tool._run(
                input_type="coordinates",
                coordinates_file=str(coords_file),
                method="MKDA",
                mkda_kernel_radius=10.0,
                mkda_threshold=0.3,
                output_dir=tmpdir,
                visualize=False,
                verbose=False
            )
            
            assert result.status == "success"
            assert "outputs" in result.data
            assert result.data["summary"]["method"] == "MKDA"
    
    def test_effect_size_meta_analysis(self):
        """Test effect size meta-analysis."""
        tool = MetaAnalysisTool()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test effect sizes
            np.random.seed(42)
            effect_sizes = np.array([0.3, 0.5, 0.2, 0.6, 0.4, 0.35, 0.45])
            standard_errors = np.array([0.1, 0.15, 0.12, 0.18, 0.11, 0.13, 0.14])
            
            es_file = Path(tmpdir) / "effect_sizes.npy"
            se_file = Path(tmpdir) / "standard_errors.npy"
            np.save(es_file, effect_sizes)
            np.save(se_file, standard_errors)
            
            # Run meta-analysis
            result = tool._run(
                input_type="effect_sizes",
                effect_sizes_file=str(es_file),
                standard_errors_file=str(se_file),
                es_model="random",
                heterogeneity_test=True,
                assess_bias=True,
                sensitivity_analysis=True,
                output_dir=tmpdir,
                visualize=True,
                verbose=False
            )
            
            assert result.status == "success"
            assert "combined_effect" in result.data["summary"]
            assert "ci_lower" in result.data["summary"]
            assert "ci_upper" in result.data["summary"]
            assert "I_squared" in result.data["summary"]
            assert "bias_assessment" in result.data["summary"]
            assert "sensitivity" in result.data["summary"]
    
    def test_ibma_fixed_effects(self):
        """Test image-based meta-analysis with fixed effects."""
        tool = MetaAnalysisTool()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test brain images
            np.random.seed(42)
            n_studies = 5
            brain_shape = (20, 20, 20)  # Small for testing
            
            contrast_files = []
            variance_files = []
            
            for i in range(n_studies):
                # Create random activation pattern
                contrast = np.random.randn(*brain_shape) * 2
                variance = np.abs(np.random.randn(*brain_shape)) * 0.5 + 0.1
                
                contrast_file = Path(tmpdir) / f"contrast_{i}.npy"
                variance_file = Path(tmpdir) / f"variance_{i}.npy"
                
                np.save(contrast_file, contrast)
                np.save(variance_file, variance)
                
                contrast_files.append(str(contrast_file))
                variance_files.append(str(variance_file))
            
            # Run IBMA
            result = tool._run(
                input_type="images",
                contrast_files=contrast_files,
                variance_files=variance_files,
                method="fixed_effects",
                output_dir=tmpdir,
                visualize=False,
                verbose=False
            )
            
            assert result.status == "success"
            assert "n_studies" in result.data["summary"]
            assert result.data["summary"]["n_studies"] == n_studies
    
    def test_cluster_detection(self):
        """Test cluster detection in stat maps."""
        tool = MetaAnalysisTool()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test stat map with known clusters
            np.random.seed(42)
            stat_map = np.random.randn(50, 50, 50) * 0.5
            
            # Add some significant clusters
            stat_map[10:20, 10:20, 10:20] = 4.0  # Cluster 1
            stat_map[30:38, 30:38, 30:38] = 3.5  # Cluster 2
            
            # Test cluster finding
            clusters = tool._find_clusters(stat_map, threshold=3.0, min_cluster_size=10)
            
            assert len(clusters) >= 2
            assert clusters[0]['size'] > 10
            assert clusters[0]['peak_value'] >= 3.0
    
    def test_publication_bias_assessment(self):
        """Test publication bias assessment."""
        tool = MetaAnalysisTool()
        
        # Create test data with potential bias
        np.random.seed(42)
        effect_sizes = np.array([0.1, 0.2, 0.3, 0.5, 0.7, 0.8, 0.9])  # Skewed
        standard_errors = np.array([0.3, 0.25, 0.2, 0.15, 0.1, 0.08, 0.05])  # Inverse relationship
        
        # Assess bias
        bias_results = tool._assess_publication_bias(
            effect_sizes, standard_errors, 
            methods=['egger', 'trim_fill']
        )
        
        assert 'egger' in bias_results
        assert 'intercept' in bias_results['egger']
        assert 'p_value' in bias_results['egger']
    
    def test_sensitivity_analysis(self):
        """Test leave-one-out sensitivity analysis."""
        tool = MetaAnalysisTool()
        
        # Create test data
        np.random.seed(42)
        effect_sizes = np.array([0.2, 0.3, 0.25, 0.35, 0.9])  # One outlier
        standard_errors = np.array([0.1, 0.1, 0.1, 0.1, 0.1])
        
        # Run sensitivity analysis
        sens_results = tool._sensitivity_analysis(effect_sizes, standard_errors, model='fixed')
        
        assert 'loo_effects' in sens_results
        assert len(sens_results['loo_effects']) == len(effect_sizes)
        assert 'range' in sens_results
        # Range should be substantial due to outlier
        assert sens_results['range'] > 0.1


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])