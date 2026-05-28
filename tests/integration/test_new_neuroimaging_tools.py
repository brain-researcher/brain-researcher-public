"""Test suite for new neuroimaging analysis tools."""

import pytest
import numpy as np
import tempfile
from pathlib import Path

from brain_researcher.services.tools.statistical_inference_tool import StatisticalInferenceTool
from brain_researcher.services.tools.advanced_visualization_tool import AdvancedVisualizationTool
from brain_researcher.services.tools.cross_validation_tool import CrossValidationTool


class TestStatisticalInferenceTool:
    """Test statistical inference tool."""
    
    def test_bootstrap_inference(self):
        """Test bootstrap confidence intervals."""
        tool = StatisticalInferenceTool()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test data
            np.random.seed(42)
            data = np.random.randn(100, 10)
            labels = np.random.randint(0, 2, 100)
            
            data_file = Path(tmpdir) / "data.npy"
            labels_file = Path(tmpdir) / "labels.npy"
            np.save(data_file, data)
            np.save(labels_file, labels)
            
            # Run tool
            result = tool._run(
                data_file=str(data_file),
                labels_file=str(labels_file),
                method="bootstrap",
                n_bootstrap=100,
                bootstrap_method="percentile",
                output_dir=tmpdir,
                visualize=False,
                verbose=False
            )
            
            assert result.status == "success"
            assert "outputs" in result.data
            assert "summary" in result.data
            assert "statistic" in result.data["summary"]
    
    def test_bayesian_inference(self):
        """Test Bayesian inference."""
        tool = StatisticalInferenceTool()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test data
            np.random.seed(42)
            data = np.random.randn(50)
            
            data_file = Path(tmpdir) / "data.npy"
            np.save(data_file, data)
            
            # Run tool
            result = tool._run(
                data_file=str(data_file),
                method="bayesian",
                n_mcmc=500,
                burn_in=100,
                output_dir=tmpdir,
                visualize=False,
                verbose=False
            )
            
            assert result.status == "success"
            assert "outputs" in result.data
            assert "summary" in result.data
            assert "posterior_mean" in result.data["summary"]
    
    def test_robust_statistics(self):
        """Test robust statistics."""
        tool = StatisticalInferenceTool()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test data with outliers
            np.random.seed(42)
            data = np.concatenate([np.random.randn(90), np.array([10, -10, 15, -15, 20, -20, 25, -25, 30, -30])])
            
            data_file = Path(tmpdir) / "data.npy"
            np.save(data_file, data)
            
            # Run tool
            result = tool._run(
                data_file=str(data_file),
                method="robust",
                robust_method="trimmed_mean",
                trim_proportion=0.1,
                output_dir=tmpdir,
                visualize=False,
                verbose=False
            )
            
            assert result.status == "success"
            assert "robust_estimate" in result.data["summary"]


class TestAdvancedVisualizationTool:
    """Test advanced visualization tool."""
    
    def test_matrix_visualization(self):
        """Test matrix visualization."""
        tool = AdvancedVisualizationTool()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test connectivity matrix
            np.random.seed(42)
            matrix = np.random.randn(20, 20)
            matrix = (matrix + matrix.T) / 2  # Make symmetric
            
            data_file = Path(tmpdir) / "matrix.npy"
            np.save(data_file, matrix)
            
            # Run tool
            result = tool._run(
                data_file=str(data_file),
                data_type="connectivity",
                plot_type="matrix",
                output_dir=tmpdir,
                figure_format="png",
                verbose=False
            )
            
            assert result.status == "success"
            assert "outputs" in result.data
            assert "visualization" in result.data["outputs"]
    
    def test_carpet_plot(self):
        """Test carpet plot for timeseries."""
        tool = AdvancedVisualizationTool()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test timeseries
            np.random.seed(42)
            timeseries = np.random.randn(100, 50)
            
            data_file = Path(tmpdir) / "timeseries.npy"
            np.save(data_file, timeseries)
            
            # Run tool
            result = tool._run(
                data_file=str(data_file),
                data_type="timeseries",
                plot_type="carpet",
                carpet_detrend=True,
                carpet_standardize=True,
                output_dir=tmpdir,
                figure_format="png",
                verbose=False
            )
            
            assert result.status == "success"
            assert "outputs" in result.data
    
    def test_interactive_plot(self):
        """Test interactive visualization."""
        tool = AdvancedVisualizationTool()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test data
            np.random.seed(42)
            data = np.random.randn(10, 10)
            
            data_file = Path(tmpdir) / "data.npy"
            np.save(data_file, data)
            
            # Run tool
            result = tool._run(
                data_file=str(data_file),
                plot_type="interactive",
                interactive_backend="plotly",
                output_dir=tmpdir,
                figure_format="html",
                verbose=False
            )
            
            # Note: Will fall back to matplotlib if plotly not available
            assert result.status == "success"


class TestCrossValidationTool:
    """Test cross-validation tool."""
    
    def test_kfold_cv(self):
        """Test k-fold cross-validation."""
        tool = CrossValidationTool()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test classification data
            np.random.seed(42)
            X = np.random.randn(100, 20)
            y = np.random.randint(0, 2, 100)
            
            data_file = Path(tmpdir) / "features.npy"
            labels_file = Path(tmpdir) / "labels.npy"
            np.save(data_file, X)
            np.save(labels_file, y)
            
            # Run tool
            result = tool._run(
                data_file=str(data_file),
                labels_file=str(labels_file),
                cv_type="kfold",
                n_splits=5,
                model_type="svm",
                task_type="classification",
                metrics=["accuracy"],
                permutation_test=False,
                output_dir=tmpdir,
                visualize=False,
                verbose=False
            )
            
            assert result.status == "success"
            assert "summary" in result.data
            assert "mean_metrics" in result.data["summary"]
            assert "accuracy" in result.data["summary"]["mean_metrics"]
    
    def test_leave_one_out_cv(self):
        """Test leave-one-out cross-validation."""
        tool = CrossValidationTool()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create small test data for LOO
            np.random.seed(42)
            X = np.random.randn(20, 10)
            y = np.random.randint(0, 2, 20)
            
            data_file = Path(tmpdir) / "features.npy"
            labels_file = Path(tmpdir) / "labels.npy"
            np.save(data_file, X)
            np.save(labels_file, y)
            
            # Run tool
            result = tool._run(
                data_file=str(data_file),
                labels_file=str(labels_file),
                cv_type="leave_one_out",
                model_type="ridge",
                task_type="classification",
                metrics=["accuracy"],
                permutation_test=False,
                compute_importance=False,
                output_dir=tmpdir,
                visualize=False,
                verbose=False
            )
            
            assert result.status == "success"
            assert "summary" in result.data
    
    def test_group_cv(self):
        """Test group cross-validation."""
        tool = CrossValidationTool()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test data with groups (subjects)
            np.random.seed(42)
            X = np.random.randn(100, 20)
            y = np.random.randint(0, 2, 100)
            groups = np.repeat(np.arange(10), 10)  # 10 subjects, 10 samples each
            
            data_file = Path(tmpdir) / "features.npy"
            labels_file = Path(tmpdir) / "labels.npy"
            groups_file = Path(tmpdir) / "groups.npy"
            np.save(data_file, X)
            np.save(labels_file, y)
            np.save(groups_file, groups)
            
            # Run tool
            result = tool._run(
                data_file=str(data_file),
                labels_file=str(labels_file),
                groups_file=str(groups_file),
                cv_type="group",
                n_splits=5,
                model_type="random_forest",
                task_type="classification",
                metrics=["accuracy"],
                permutation_test=False,
                output_dir=tmpdir,
                visualize=False,
                verbose=False
            )
            
            assert result.status == "success"
            assert "summary" in result.data
    
    def test_feature_importance(self):
        """Test feature importance computation."""
        tool = CrossValidationTool()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test data
            np.random.seed(42)
            X = np.random.randn(50, 10)
            y = np.random.randint(0, 2, 50)
            
            data_file = Path(tmpdir) / "features.npy"
            labels_file = Path(tmpdir) / "labels.npy"
            np.save(data_file, X)
            np.save(labels_file, y)
            
            # Run tool
            result = tool._run(
                data_file=str(data_file),
                labels_file=str(labels_file),
                cv_type="kfold",
                n_splits=3,
                model_type="random_forest",
                task_type="classification",
                compute_importance=True,
                importance_method="coefficients",
                output_dir=tmpdir,
                visualize=False,
                verbose=False
            )
            
            assert result.status == "success"
            assert Path(tmpdir, "feature_importance.npy").exists()


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])