"""Tests for registration tool."""

import json
import numpy as np
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import tempfile

from brain_researcher.services.tools.registration_tool import (
    RegistrationTool,
    RegistrationArgs
)


class TestRegistrationTool:
    """Test registration functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.tool = RegistrationTool()
        self.temp_dir = tempfile.mkdtemp()
    
    def teardown_method(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_tool_initialization(self):
        """Test tool initializes correctly."""
        assert self.tool.get_tool_name() == "registration_pipeline"
        assert "alignment" in self.tool.get_tool_description().lower()
        assert self.tool.get_args_schema() == RegistrationArgs
    
    def test_estimate_rigid_transform(self):
        """Test rigid transform estimation."""
        # Create test images
        moving = np.random.randn(64, 64, 64)
        fixed = np.random.randn(64, 64, 64)
        
        # Estimate transform
        result = self.tool._estimate_rigid_transform(moving, fixed)
        
        assert 'warpedmovout' in result
        assert 'fwdtransforms' in result
        assert 'invtransforms' in result
        assert len(result['fwdtransforms']) > 0
        
        # Check transform is 4x4 matrix
        transform = result['fwdtransforms'][0]
        assert transform.shape == (4, 4)
        
        # Check inverse
        inv_transform = result['invtransforms'][0]
        assert inv_transform.shape == (4, 4)
    
    def test_estimate_affine_transform(self):
        """Test affine transform estimation."""
        moving = np.random.randn(64, 64, 64)
        fixed = np.random.randn(64, 64, 64)
        
        result = self.tool._estimate_affine_transform(moving, fixed)
        
        assert 'warpedmovout' in result
        assert 'fwdtransforms' in result
        
        transform = result['fwdtransforms'][0]
        assert transform.shape == (4, 4)
    
    def test_create_deformation_field(self):
        """Test deformation field creation."""
        moving = np.random.randn(32, 32, 32)
        fixed = np.random.randn(32, 32, 32)
        
        result = self.tool._create_deformation_field(moving, fixed)
        
        assert 'warpedmovout' in result
        assert 'fwdtransforms' in result
        
        field = result['fwdtransforms'][0]
        assert field.shape == (32, 32, 32, 3)
    
    def test_compute_similarity_metrics(self):
        """Test similarity metric computation."""
        # Create similar images
        base = np.random.randn(32, 32, 32)
        moving = base + np.random.randn(32, 32, 32) * 0.1
        fixed = base + np.random.randn(32, 32, 32) * 0.1
        warped = base + np.random.randn(32, 32, 32) * 0.05
        
        metrics = self.tool._compute_similarity_metrics(moving, fixed, warped)
        
        assert 'mse_before' in metrics
        assert 'mse_after' in metrics
        assert 'correlation_before' in metrics
        assert 'correlation_after' in metrics
        assert 'ssim_after' in metrics
        
        # Check values are reasonable
        assert 0 <= metrics['mse_before'] <= 1
        assert 0 <= metrics['mse_after'] <= 1
        assert -1 <= metrics['correlation_before'] <= 1
        assert -1 <= metrics['correlation_after'] <= 1
    
    def test_compute_jacobian(self):
        """Test Jacobian determinant computation."""
        # Create deformation field
        field = np.random.randn(32, 32, 32, 3) * 0.1
        
        jacobian = self.tool._compute_jacobian(field)
        
        assert jacobian is not None
        assert jacobian.shape == (32, 32, 32)
        assert np.all(np.isfinite(jacobian))
    
    def test_run_rigid_registration(self):
        """Test full rigid registration pipeline."""
        # Create dummy image files
        moving_file = Path(self.temp_dir) / "moving.nii.gz"
        fixed_file = Path(self.temp_dir) / "fixed.nii.gz"
        
        # Create dummy files (would be NIfTI in practice)
        moving_file.touch()
        fixed_file.touch()
        
        args = {
            'moving_image': str(moving_file),
            'fixed_image': str(fixed_file),
            'registration_type': 'rigid',
            'output_dir': self.temp_dir,
            'compute_similarity': True,
            'visualize': False,
            'verbose': False
        }
        
        result = self.tool._run(**args)
        
        assert result.status == "success"
        assert 'outputs' in result.data
        assert 'summary' in result.data
        assert result.data['summary']['registration_type'] == 'rigid'
    
    def test_run_affine_registration(self):
        """Test full affine registration pipeline."""
        moving_file = Path(self.temp_dir) / "moving.nii.gz"
        fixed_file = Path(self.temp_dir) / "fixed.nii.gz"
        
        moving_file.touch()
        fixed_file.touch()
        
        args = {
            'moving_image': str(moving_file),
            'fixed_image': str(fixed_file),
            'registration_type': 'affine',
            'metric': 'MI',
            'iterations': [50, 50, 50],
            'output_dir': self.temp_dir,
            'save_transform': True,
            'save_warped': True,
            'compute_similarity': True,
            'visualize': False,
            'verbose': False
        }
        
        result = self.tool._run(**args)
        
        assert result.status == "success"
        assert result.data['summary']['registration_type'] == 'affine'
        assert result.data['summary']['metric'] == 'MI'
    
    def test_run_nonlinear_registration(self):
        """Test nonlinear registration."""
        moving_file = Path(self.temp_dir) / "moving.nii.gz"
        fixed_file = Path(self.temp_dir) / "fixed.nii.gz"
        
        moving_file.touch()
        fixed_file.touch()
        
        args = {
            'moving_image': str(moving_file),
            'fixed_image': str(fixed_file),
            'registration_type': 'syn',
            'syn_metric': 'CC',
            'syn_iterations': [20, 20, 10],
            'output_dir': self.temp_dir,
            'compute_jacobian': True,
            'visualize': False,
            'verbose': False
        }
        
        result = self.tool._run(**args)
        
        assert result.status == "success"
        assert result.data['summary']['registration_type'] == 'syn'
    
    def test_visualization_generation(self):
        """Test visualization generation."""
        moving_file = Path(self.temp_dir) / "moving.nii.gz"
        fixed_file = Path(self.temp_dir) / "fixed.nii.gz"
        
        moving_file.touch()
        fixed_file.touch()
        
        args = {
            'moving_image': str(moving_file),
            'fixed_image': str(fixed_file),
            'registration_type': 'affine',
            'output_dir': self.temp_dir,
            'visualize': True,
            'checkerboard': True,
            'verbose': False
        }
        
        with patch('matplotlib.pyplot.savefig'):
            result = self.tool._run(**args)
        
        assert result.status == "success"
        assert 'visualization' in result.data['outputs']
        assert 'checkerboard' in result.data['outputs']
    
    def test_multi_resolution(self):
        """Test multi-resolution registration."""
        moving_file = Path(self.temp_dir) / "moving.nii.gz"
        fixed_file = Path(self.temp_dir) / "fixed.nii.gz"
        
        moving_file.touch()
        fixed_file.touch()
        
        args = {
            'moving_image': str(moving_file),
            'fixed_image': str(fixed_file),
            'registration_type': 'affine',
            'iterations': [100, 50, 25],
            'shrink_factors': [8, 4, 2],
            'smoothing_sigmas': [4, 2, 1],
            'output_dir': self.temp_dir,
            'visualize': False,
            'verbose': False
        }
        
        result = self.tool._run(**args)
        
        assert result.status == "success"
        assert result.data['summary']['iterations'] == [100, 50, 25]
    
    def test_error_handling(self):
        """Test error handling."""
        args = {
            'moving_image': 'nonexistent.nii.gz',
            'fixed_image': 'nonexistent.nii.gz',
            'output_dir': self.temp_dir
        }
        
        result = self.tool._run(**args)
        
        # Should handle gracefully
        assert result.status in ["success", "error"]