"""Tests for hyperalignment tool."""

import json
import numpy as np
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import tempfile

from brain_researcher.services.tools.hyperalignment_tool import (
    HyperalignmentTool,
    HyperalignmentArgs
)


class TestHyperalignmentTool:
    """Test hyperalignment functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.tool = HyperalignmentTool()
        self.temp_dir = tempfile.mkdtemp()
        
        # Create synthetic multi-subject data
        np.random.seed(42)
        self.n_subjects = 4
        self.n_timepoints = 100
        self.n_voxels = 50
        
        # Generate correlated data across subjects
        self.subjects_data = []
        shared_signal = np.random.randn(self.n_timepoints, 10)
        
        for i in range(self.n_subjects):
            # Each subject has shared + unique components
            subject_data = shared_signal @ np.random.randn(10, self.n_voxels)
            subject_data += np.random.randn(self.n_timepoints, self.n_voxels) * 0.5
            self.subjects_data.append(subject_data)
    
    def teardown_method(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_tool_initialization(self):
        """Test tool initializes correctly."""
        assert self.tool.get_tool_name() == "hyperalignment"
        assert "multi-subject" in self.tool.get_tool_description().lower()
        assert self.tool.get_args_schema() == HyperalignmentArgs
    
    def test_load_subject_data(self):
        """Test loading subject data from files."""
        # Save test data
        data_files = []
        for i, data in enumerate(self.subjects_data):
            file_path = Path(self.temp_dir) / f"subject_{i}.npy"
            np.save(file_path, data)
            data_files.append(str(file_path))
        
        # Load data
        loaded_data = self.tool._load_subject_data(data_files)
        
        assert len(loaded_data) == self.n_subjects
        for i, data in enumerate(loaded_data):
            assert data.shape == (self.n_timepoints, self.n_voxels)
            np.testing.assert_array_almost_equal(data, self.subjects_data[i])
    
    def test_procrustes_alignment(self):
        """Test Procrustes hyperalignment."""
        aligned_data, transforms, reference = self.tool._procrustes_alignment(
            self.subjects_data,
            scaling=True,
            reflection=True
        )
        
        assert len(aligned_data) == self.n_subjects
        assert len(transforms) == self.n_subjects
        assert reference.shape == (self.n_timepoints, self.n_voxels)
        
        # Check aligned data properties
        for i, aligned in enumerate(aligned_data):
            assert aligned.shape == (self.n_timepoints, self.n_voxels)
            assert np.all(np.isfinite(aligned))
            
            # Check transform properties
            transform = transforms[i]
            assert 'rotation' in transform
            assert 'scale' in transform
            assert transform['rotation'].shape == (self.n_voxels, self.n_voxels)
            # Rotation matrix should be orthogonal
            R = transform['rotation']
            np.testing.assert_array_almost_equal(R @ R.T, np.eye(self.n_voxels), decimal=5)
    
    def test_cca_alignment(self):
        """Test CCA-based hyperalignment."""
        n_components = min(20, self.n_voxels)
        
        aligned_data, transforms, common_space = self.tool._cca_alignment(
            self.subjects_data,
            n_components=n_components,
            regularization=0.1
        )
        
        assert len(aligned_data) == self.n_subjects
        assert len(transforms) == self.n_subjects
        
        # Check aligned data
        for aligned in aligned_data:
            assert aligned.shape[0] == self.n_timepoints
            assert np.all(np.isfinite(aligned))
        
        # Check common space
        assert common_space.shape[0] == self.n_timepoints
        assert np.all(np.isfinite(common_space))
    
    def test_simple_srm_alignment(self):
        """Test simplified SRM alignment."""
        n_features = 20
        n_iterations = 5
        
        aligned_data, transforms, shared_response = self.tool._simple_srm(
            self.subjects_data,
            n_features=n_features,
            n_iterations=n_iterations
        )
        
        assert len(aligned_data) == self.n_subjects
        assert len(transforms) == self.n_subjects
        assert shared_response.shape == (self.n_timepoints, n_features)
        
        # Check aligned data
        for i, aligned in enumerate(aligned_data):
            assert aligned.shape == (self.n_timepoints, n_features)
            assert np.all(np.isfinite(aligned))
            
            # Check transform
            assert transforms[i].shape == (self.n_voxels, n_features)
    
    def test_searchlight_alignment(self):
        """Test searchlight hyperalignment."""
        aligned_data, _, _ = self.tool._searchlight_alignment(
            self.subjects_data,
            radius=10,
            stride=5
        )
        
        assert len(aligned_data) == self.n_subjects
        
        for aligned in aligned_data:
            assert aligned.shape == (self.n_timepoints, self.n_voxels)
            assert np.all(np.isfinite(aligned))
    
    def test_compute_isc(self):
        """Test inter-subject correlation computation."""
        # Create perfectly correlated data for testing
        perfect_data = [np.tile(np.random.randn(100, 1), (1, 10)) for _ in range(3)]
        
        isc_values = self.tool._compute_isc(perfect_data)
        
        assert len(isc_values) == 10
        assert np.all(isc_values >= -1) and np.all(isc_values <= 1)
        # Perfect correlation should give high ISC
        assert np.mean(isc_values) > 0.8
        
        # Test with uncorrelated data
        random_data = [np.random.randn(100, 10) for _ in range(3)]
        isc_random = self.tool._compute_isc(random_data)
        
        assert len(isc_random) == 10
        # Random data should give low ISC
        assert np.abs(np.mean(isc_random)) < 0.3
    
    def test_test_classification(self):
        """Test cross-subject classification."""
        # Create data with clear class structure
        n_samples = 50
        n_features = 20
        n_subjects = 3
        
        # Generate two classes
        class1_data = np.random.randn(n_samples//2, n_features) + 1
        class2_data = np.random.randn(n_samples//2, n_features) - 1
        
        aligned_data = []
        for _ in range(n_subjects):
            subject_data = np.vstack([class1_data, class2_data])
            subject_data += np.random.randn(*subject_data.shape) * 0.1
            aligned_data.append(subject_data)
        
        labels = np.array([0] * (n_samples//2) + [1] * (n_samples//2))
        
        scores = self.tool._test_classification(aligned_data, labels)
        
        assert len(scores) == n_subjects
        assert all(0 <= s <= 1 for s in scores)
        # With clear class separation, accuracy should be good
        assert np.mean(scores) > 0.7
    
    def test_run_procrustes_alignment(self):
        """Test full Procrustes alignment pipeline."""
        # Save test data
        data_files = []
        for i, data in enumerate(self.subjects_data):
            file_path = Path(self.temp_dir) / f"subject_{i}.npy"
            np.save(file_path, data)
            data_files.append(str(file_path))
        
        args = {
            'data_files': data_files,
            'method': 'procrustes',
            'procrustes_scaling': True,
            'procrustes_reflection': True,
            'compute_isc': True,
            'output_dir': self.temp_dir,
            'save_transforms': True,
            'save_aligned': True,
            'save_common_space': True,
            'visualize': False,
            'verbose': False
        }
        
        result = self.tool._run(**args)
        
        assert result.status == "success"
        assert 'outputs' in result.data
        assert 'summary' in result.data
        assert result.data['summary']['alignment_completed']
        assert 'mean_isc' in result.data['summary']
        
        # Check output files
        output_path = Path(self.temp_dir)
        assert (output_path / "alignment_transforms.npy").exists()
        assert (output_path / "common_space.npy").exists()
        for i in range(self.n_subjects):
            assert (output_path / f"aligned_subject_{i}.npy").exists()
    
    def test_run_cca_alignment(self):
        """Test full CCA alignment pipeline."""
        # Save test data
        data_files = []
        for i, data in enumerate(self.subjects_data):
            file_path = Path(self.temp_dir) / f"subject_{i}.npy"
            np.save(file_path, data)
            data_files.append(str(file_path))
        
        args = {
            'data_files': data_files,
            'method': 'cca',
            'n_components': 20,
            'regularization': 0.1,
            'compute_isc': True,
            'output_dir': self.temp_dir,
            'save_aligned': True,
            'visualize': False,
            'verbose': False
        }
        
        result = self.tool._run(**args)
        
        assert result.status == "success"
        assert result.data['summary']['method'] == 'cca'
        assert result.data['summary']['alignment_completed']
    
    def test_run_srm_alignment(self):
        """Test full SRM alignment pipeline."""
        # Save test data
        data_files = []
        for i, data in enumerate(self.subjects_data):
            file_path = Path(self.temp_dir) / f"subject_{i}.npy"
            np.save(file_path, data)
            data_files.append(str(file_path))
        
        args = {
            'data_files': data_files,
            'method': 'srm',
            'srm_features': 15,
            'srm_iterations': 5,
            'compute_isc': True,
            'output_dir': self.temp_dir,
            'save_aligned': False,
            'visualize': False,
            'verbose': False
        }
        
        result = self.tool._run(**args)
        
        assert result.status == "success"
        assert result.data['summary']['method'] == 'srm'
        assert result.data['summary']['alignment_completed']
    
    def test_dimensionality_reduction(self):
        """Test dimensionality reduction before alignment."""
        # Save test data
        data_files = []
        for i, data in enumerate(self.subjects_data):
            file_path = Path(self.temp_dir) / f"subject_{i}.npy"
            np.save(file_path, data)
            data_files.append(str(file_path))
        
        args = {
            'data_files': data_files,
            'method': 'procrustes',
            'reduce_dimensions': True,
            'target_dimensions': 20,
            'reduction_method': 'pca',
            'compute_isc': True,
            'output_dir': self.temp_dir,
            'save_aligned': True,
            'visualize': False,
            'verbose': False
        }
        
        result = self.tool._run(**args)
        
        assert result.status == "success"
        assert result.data['summary']['n_features'] == 20
        
        # Check reduced dimensionality in output
        aligned_file = Path(self.temp_dir) / "aligned_subject_0.npy"
        aligned_data = np.load(aligned_file)
        assert aligned_data.shape[1] == 20
    
    def test_roi_mask_application(self):
        """Test ROI mask application."""
        # Create and save ROI mask
        mask = np.zeros(self.n_voxels, dtype=bool)
        mask[10:30] = True  # Select 20 voxels
        mask_file = Path(self.temp_dir) / "roi_mask.npy"
        np.save(mask_file, mask)
        
        # Save test data
        data_files = []
        for i, data in enumerate(self.subjects_data):
            file_path = Path(self.temp_dir) / f"subject_{i}.npy"
            np.save(file_path, data)
            data_files.append(str(file_path))
        
        args = {
            'data_files': data_files,
            'roi_mask_file': str(mask_file),
            'method': 'procrustes',
            'compute_isc': True,
            'output_dir': self.temp_dir,
            'save_aligned': True,
            'visualize': False,
            'verbose': False
        }
        
        result = self.tool._run(**args)
        
        assert result.status == "success"
        assert result.data['summary']['n_features'] == 20  # Only masked voxels
    
    def test_classification_with_labels(self):
        """Test classification with provided labels."""
        # Save test data
        data_files = []
        for i, data in enumerate(self.subjects_data):
            file_path = Path(self.temp_dir) / f"subject_{i}.npy"
            np.save(file_path, data)
            data_files.append(str(file_path))
        
        # Create labels
        labels = np.array([0, 1] * (self.n_timepoints // 2))[:self.n_timepoints]
        labels_file = Path(self.temp_dir) / "labels.npy"
        np.save(labels_file, labels)
        
        args = {
            'data_files': data_files,
            'method': 'procrustes',
            'compute_isc': True,
            'compute_classification': True,
            'classification_labels_file': str(labels_file),
            'output_dir': self.temp_dir,
            'save_aligned': False,
            'visualize': False,
            'verbose': False
        }
        
        result = self.tool._run(**args)
        
        assert result.status == "success"
        assert 'classification_scores' in result.data['summary']
        assert 'mean_classification' in result.data['summary']
        assert len(result.data['summary']['classification_scores']) == self.n_subjects
    
    def test_error_handling(self):
        """Test error handling."""
        # Test with invalid file
        args = {
            'data_files': ['nonexistent_file.npy'],
            'output_dir': self.temp_dir
        }
        
        result = self.tool._run(**args)
        
        assert result.status == "error"
        assert "error" in result.data
    
    def test_visualization_generation(self):
        """Test visualization generation."""
        # Save small test data for speed
        small_data = [np.random.randn(50, 10) for _ in range(3)]
        data_files = []
        for i, data in enumerate(small_data):
            file_path = Path(self.temp_dir) / f"subject_{i}.npy"
            np.save(file_path, data)
            data_files.append(str(file_path))
        
        args = {
            'data_files': data_files,
            'method': 'procrustes',
            'compute_isc': True,
            'output_dir': self.temp_dir,
            'save_aligned': False,
            'visualize': True,
            'verbose': False
        }
        
        with patch('matplotlib.pyplot.savefig'):
            result = self.tool._run(**args)
        
        assert result.status == "success"
        assert 'visualization' in result.data['outputs']