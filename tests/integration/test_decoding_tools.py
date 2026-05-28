#!/usr/bin/env python3
"""
Integration tests for decoding and analysis tools.
Tests MVPA, encoding models, feature selection, and temporal decoding tools.
"""

import sys
import json
import numpy as np
import tempfile
from pathlib import Path
from datetime import datetime
import pytest

# Add project to path

from brain_researcher.services.tools.tool_registry import ToolRegistry


class TestDecodingTools:
    """Integration tests for decoding and analysis tools."""
    
    @classmethod
    def setup_class(cls):
        """Setup test environment."""
        cls.registry = ToolRegistry(auto_discover=True)
        cls.test_dir = Path(tempfile.mkdtemp(prefix="brain_decoding_test_"))
        cls.results = {}
    
    @classmethod
    def teardown_class(cls):
        """Cleanup test environment."""
        import shutil
        if cls.test_dir.exists():
            shutil.rmtree(cls.test_dir)
    
    def create_test_data(self):
        """Create test data for decoding analyses."""
        # Create classification data (samples x features)
        n_samples = 100
        n_features = 500
        n_classes = 2
        
        # Generate data with signal
        np.random.seed(42)
        X = np.random.randn(n_samples, n_features)
        
        # Add signal to first 50 features
        y = np.random.randint(0, n_classes, n_samples)
        for i in range(n_samples):
            if y[i] == 1:
                X[i, :50] += 0.5
        
        # Create temporal data (time x features x trials)
        n_timepoints = 50
        n_trials = 20
        temporal_data = np.random.randn(n_timepoints, n_features, n_trials)
        
        # Add temporal signal
        for t in range(20, 30):
            temporal_data[t, :50, :] += 1.0
        
        # Create groups for cross-validation
        groups = np.repeat(np.arange(5), n_samples // 5)
        
        # Create events
        events = np.array([5, 15, 25, 35])
        
        # Save data
        data_file = self.test_dir / "test_data.npy"
        labels_file = self.test_dir / "test_labels.npy"
        groups_file = self.test_dir / "test_groups.npy"
        temporal_file = self.test_dir / "test_temporal.npy"
        events_file = self.test_dir / "test_events.npy"
        
        np.save(data_file, X)
        np.save(labels_file, y)
        np.save(groups_file, groups)
        np.save(temporal_file, temporal_data)
        np.save(events_file, events)
        
        # Create stimulus for encoding models
        stimulus = np.random.randn(n_samples, 100)
        stimulus_file = self.test_dir / "test_stimulus.npy"
        np.save(stimulus_file, stimulus)
        
        # Create brain data for encoding (time x voxels)
        brain_data = np.random.randn(n_samples, 200)
        # Add encoding relationship
        brain_data[:, :20] = stimulus[:, :20] * 0.5 + np.random.randn(n_samples, 20) * 0.1
        brain_file = self.test_dir / "test_brain.npy"
        np.save(brain_file, brain_data)
        
        return {
            'data': str(data_file),
            'labels': str(labels_file),
            'groups': str(groups_file),
            'temporal': str(temporal_file),
            'events': str(events_file),
            'stimulus': str(stimulus_file),
            'brain': str(brain_file)
        }
    
    def test_mvpa_tool(self):
        """Test MVPA tool."""
        tool = self.registry.get_tool("mvpa")
        assert tool is not None, "MVPA tool not found in registry"
        
        # Create test data
        data_files = self.create_test_data()
        output_dir = self.test_dir / "mvpa_output"
        output_dir.mkdir(exist_ok=True)
        
        # Test MVPA
        result = tool._run(
            data_file=data_files['data'],
            labels_file=data_files['labels'],
            groups_file=data_files['groups'],
            classifier="svm",
            svm_kernel="linear",
            cv_type="stratified",
            n_folds=5,
            standardize=True,
            permutation_test=True,
            n_permutations=10,  # Reduced for speed
            output_dir=str(output_dir),
            save_predictions=True,
            save_confusion=True,
            visualize=True,
            verbose=False
        )
        
        assert result.status == "success"
        
        self.results['mvpa'] = {
            'status': 'PASSED',
            'accuracy': result.data['summary'].get('accuracy', 0),
            'p_value': result.data['summary'].get('p_value')
        }
    
    def test_encoding_models(self):
        """Test encoding models tool."""
        tool = self.registry.get_tool("encoding_models")
        assert tool is not None, "Encoding models tool not found in registry"
        
        # Create test data
        data_files = self.create_test_data()
        output_dir = self.test_dir / "encoding_output"
        output_dir.mkdir(exist_ok=True)
        
        # Test ridge encoding
        result = tool._run(
            brain_data_file=data_files['brain'],
            stimulus_file=data_files['stimulus'],
            model_type="ridge",
            n_folds=3,
            standardize=True,
            output_dir=str(output_dir),
            save_predictions=True,
            save_weights=True,
            visualize=True,
            verbose=False
        )
        
        assert result.status == "success"
        
        self.results['encoding_models'] = {
            'status': 'PASSED',
            'mean_r2': result.data['summary'].get('mean_r2', 0),
            'n_significant': result.data['summary'].get('n_significant', 0)
        }
    
    def test_feature_selection(self):
        """Test feature selection tool."""
        tool = self.registry.get_tool("feature_selection")
        assert tool is not None, "Feature selection tool not found in registry"
        
        # Create test data
        data_files = self.create_test_data()
        output_dir = self.test_dir / "feature_selection_output"
        output_dir.mkdir(exist_ok=True)
        
        # Test univariate selection
        result = tool._run(
            data_file=data_files['data'],
            labels_file=data_files['labels'],
            method="univariate",
            n_features=50,
            univariate_test="f_classif",
            validate_selection=True,
            cv_folds=3,
            output_dir=str(output_dir),
            save_indices=True,
            save_scores=True,
            visualize=True,
            verbose=False
        )
        
        assert result.status == "success"
        
        self.results['feature_selection'] = {
            'status': 'PASSED',
            'n_selected': result.data['summary'].get('n_features_selected', 0),
            'reduction_ratio': result.data['summary'].get('reduction_ratio', 0)
        }
    
    def test_temporal_decoding(self):
        """Test temporal decoding tool."""
        tool = self.registry.get_tool("temporal_decoding")
        assert tool is not None, "Temporal decoding tool not found in registry"
        
        # Create test data
        data_files = self.create_test_data()
        output_dir = self.test_dir / "temporal_output"
        output_dir.mkdir(exist_ok=True)
        
        # Create temporal labels
        temporal_labels = np.random.randint(0, 2, 20)  # For 20 trials
        temporal_labels_file = self.test_dir / "temporal_labels.npy"
        np.save(temporal_labels_file, temporal_labels)
        
        # Test sliding window decoding
        result = tool._run(
            data_file=data_files['temporal'],
            labels_file=str(temporal_labels_file),
            method="sliding_window",
            classifier="lda",
            window_size=5,
            window_step=1,
            cv_folds=3,
            permutation_test=False,  # Skip for speed
            output_dir=str(output_dir),
            save_accuracies=True,
            visualize=True,
            verbose=False
        )
        
        assert result.status == "success"
        
        self.results['temporal_decoding'] = {
            'status': 'PASSED',
            'peak_accuracy': result.data['summary'].get('sliding_window', {}).get('peak_accuracy', 0),
            'peak_time': result.data['summary'].get('sliding_window', {}).get('peak_time', 0)
        }
    
    def test_realtime_fmri(self):
        """Test real-time fMRI tool."""
        tool = self.registry.get_tool("realtime_fmri")
        assert tool is not None, "Real-time fMRI tool not found in registry"
        
        output_dir = self.test_dir / "realtime_output"
        output_dir.mkdir(exist_ok=True)
        
        # Test with simulator
        result = tool._run(
            data_source="simulator",
            mode="neurofeedback",
            feedback_type="continuous",
            baseline_scans=5,
            buffer_size=10,
            simulation_tr=2.0,
            simulation_noise=0.1,
            output_dir=str(output_dir),
            save_feedback=True,
            save_qc_metrics=True,
            visualize=False,  # Skip for speed
            verbose=False
        )
        
        assert result.status == "success"
        
        self.results['realtime_fmri'] = {
            'status': 'PASSED',
            'n_volumes': result.data['summary'].get('n_volumes_processed', 0),
            'mean_snr': result.data['summary'].get('qc_summary', {}).get('mean_snr', 0)
        }
    
    def test_stability_selection(self):
        """Test stability selection method."""
        tool = self.registry.get_tool("feature_selection")
        assert tool is not None
        
        # Create test data
        data_files = self.create_test_data()
        output_dir = self.test_dir / "stability_output"
        output_dir.mkdir(exist_ok=True)
        
        # Test stability selection
        result = tool._run(
            data_file=data_files['data'],
            labels_file=data_files['labels'],
            method="stability",
            n_features=30,
            stability_threshold=0.6,
            n_bootstrap=20,  # Reduced for speed
            sample_fraction=0.5,
            output_dir=str(output_dir),
            verbose=False
        )
        
        assert result.status == "success"
        
        self.results['stability_selection'] = {
            'status': 'PASSED',
            'n_selected': result.data['summary'].get('n_features_selected', 0)
        }
    
    def test_temporal_generalization(self):
        """Test temporal generalization method."""
        tool = self.registry.get_tool("temporal_decoding")
        assert tool is not None
        
        # Create test data
        data_files = self.create_test_data()
        output_dir = self.test_dir / "temporal_gen_output"
        output_dir.mkdir(exist_ok=True)
        
        # Create temporal labels
        temporal_labels = np.random.randint(0, 2, 20)
        temporal_labels_file = self.test_dir / "temporal_labels.npy"
        np.save(temporal_labels_file, temporal_labels)
        
        # Test temporal generalization
        result = tool._run(
            data_file=data_files['temporal'],
            labels_file=str(temporal_labels_file),
            method="temporal_generalization",
            classifier="lda",
            train_times=list(range(0, 50, 10)),
            test_times=list(range(0, 50, 10)),
            output_dir=str(output_dir),
            visualize=True,
            verbose=False
        )
        
        assert result.status == "success"
        
        self.results['temporal_generalization'] = {
            'status': 'PASSED',
            'diagonal_accuracy': result.data['summary'].get('diagonal_accuracy', 0)
        }
    
    def test_generate_report(self):
        """Generate comprehensive test report."""
        report = {
            "timestamp": datetime.now().isoformat(),
            "test_type": "Decoding and Analysis Tools Test",
            "test_location": str(self.test_dir),
            "tools_tested": [
                "mvpa",
                "encoding_models",
                "feature_selection",
                "temporal_decoding",
                "realtime_fmri",
                "stability_selection",
                "temporal_generalization"
            ],
            "results": self.results,
            "summary": {
                "total_tests": len(self.results),
                "passed": sum(1 for r in self.results.values() if r['status'] == 'PASSED'),
                "failed": sum(1 for r in self.results.values() if r['status'] == 'FAILED')
            }
        }
        
        # Save report
        report_file = Path(__file__).parent / "decoding_tools_test_report.json"
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"\n{'='*60}")
        print("DECODING TOOLS TEST SUMMARY")
        print(f"{'='*60}")
        print(f"Total tests: {report['summary']['total_tests']}")
        print(f"Passed: {report['summary']['passed']}")
        print(f"Failed: {report['summary']['failed']}")
        print(f"\nTest report saved to: {report_file}")
        
        # Assert all tests passed
        assert report['summary']['failed'] == 0


@pytest.mark.parametrize("classifier", ["svm", "lda", "logistic"])
def test_mvpa_classifiers(classifier):
    """Test different MVPA classifiers."""
    registry = ToolRegistry(auto_discover=True)
    tool = registry.get_tool("mvpa")
    
    if tool is None:
        pytest.skip("MVPA tool not available")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test data
        X = np.random.randn(50, 100)
        y = np.random.randint(0, 2, 50)
        
        data_file = Path(tmpdir) / "data.npy"
        labels_file = Path(tmpdir) / "labels.npy"
        output_dir = Path(tmpdir) / "output"
        
        np.save(data_file, X)
        np.save(labels_file, y)
        
        result = tool._run(
            data_file=str(data_file),
            labels_file=str(labels_file),
            classifier=classifier,
            cv_folds=3,
            permutation_test=False,
            output_dir=str(output_dir),
            verbose=False
        )
        
        assert result.status == "success"


@pytest.mark.parametrize("method", ["univariate", "variance", "lasso"])
def test_feature_selection_methods(method):
    """Test different feature selection methods."""
    registry = ToolRegistry(auto_discover=True)
    tool = registry.get_tool("feature_selection")
    
    if tool is None:
        pytest.skip("Feature selection tool not available")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test data
        X = np.random.randn(50, 200)
        y = np.random.randint(0, 2, 50)
        
        data_file = Path(tmpdir) / "data.npy"
        labels_file = Path(tmpdir) / "labels.npy"
        output_dir = Path(tmpdir) / "output"
        
        np.save(data_file, X)
        np.save(labels_file, y)
        
        result = tool._run(
            data_file=str(data_file),
            labels_file=str(labels_file) if method != "variance" else None,
            method=method,
            n_features=20,
            output_dir=str(output_dir),
            verbose=False
        )
        
        assert result.status == "success"


if __name__ == "__main__":
    # Run tests
    test_suite = TestDecodingTools()
    test_suite.setup_class()
    
    try:
        test_suite.test_mvpa_tool()
        test_suite.test_encoding_models()
        test_suite.test_feature_selection()
        test_suite.test_temporal_decoding()
        test_suite.test_realtime_fmri()
        test_suite.test_stability_selection()
        test_suite.test_temporal_generalization()
        test_suite.test_generate_report()
    finally:
        test_suite.teardown_class()
