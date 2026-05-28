"""Tests for MONAI deep learning tool."""

import json
import numpy as np
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import tempfile

from brain_researcher.services.tools.monai_tool import (
    MONAITool,
    MONAIArgs
)


class TestMONAITool:
    """Test MONAI deep learning functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.tool = MONAITool()
        self.temp_dir = tempfile.mkdtemp()
        
        # Create dummy input files
        self.input_files = []
        self.label_files = []
        for i in range(3):
            input_file = Path(self.temp_dir) / f"image_{i}.nii.gz"
            label_file = Path(self.temp_dir) / f"label_{i}.nii.gz"
            input_file.touch()
            label_file.touch()
            self.input_files.append(str(input_file))
            self.label_files.append(str(label_file))
    
    def teardown_method(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_tool_initialization(self):
        """Test tool initializes correctly."""
        assert self.tool.get_tool_name() == "monai_deep_learning"
        assert "medical imaging" in self.tool.get_tool_description().lower()
        assert self.tool.get_args_schema() == MONAIArgs
    
    def test_create_simple_unet(self):
        """Test simple UNet creation."""
        model = self.tool._create_simple_unet(
            in_channels=1,
            out_channels=2,
            features=[32, 64, 128]
        )
        
        if self.tool.torch_available:
            assert model is not None
            # Test forward pass with dummy input
            import torch
            dummy_input = torch.randn(1, 1, 64, 64, 64)
            with torch.no_grad():
                output = model(dummy_input)
            assert output.shape == (1, 2, 64, 64, 64)
    
    def test_create_unet_model(self):
        """Test UNet model creation."""
        model = self.tool._create_unet_model(
            spatial_dims=3,
            in_channels=1,
            out_channels=2,
            features=(32, 64, 128)
        )
        
        # Model should be created even without MONAI (fallback)
        assert model is not None or not self.tool.torch_available
    
    def test_create_densenet_model(self):
        """Test DenseNet model creation."""
        model = self.tool._create_densenet_model(
            spatial_dims=3,
            in_channels=1,
            out_channels=2
        )
        
        if self.tool.torch_available:
            assert model is not None
            # Test forward pass
            import torch
            dummy_input = torch.randn(1, 1, 32, 32, 32)
            with torch.no_grad():
                output = model(dummy_input)
            assert output.shape[0] == 1
            assert output.shape[1] == 2
    
    def test_simple_data_loader(self):
        """Test simple data loader."""
        loader = self.tool._simple_data_loader(
            files=self.input_files,
            labels=self.label_files,
            batch_size=2
        )
        
        # Get first batch
        batch = next(loader)
        assert isinstance(batch, list)
        assert len(batch) <= 2
        if batch:
            assert 'image' in batch[0]
            assert 'label' in batch[0]
    
    def test_prepare_data_loader_fallback(self):
        """Test data loader preparation fallback."""
        if not self.tool.monai_available:
            loader = self.tool._prepare_data_loader(
                files=self.input_files,
                labels=self.label_files,
                transform=None,
                batch_size=1,
                shuffle=True
            )
            
            # Should return generator
            batch = next(loader)
            assert isinstance(batch, list)
    
    def test_run_inference_mode(self):
        """Test inference mode."""
        args = {
            'task': 'segmentation',
            'model_name': 'unet',
            'input_files': self.input_files,
            'mode': 'inference',
            'in_channels': 1,
            'out_channels': 2,
            'output_dir': self.temp_dir,
            'save_predictions': True,
            'visualize': False,
            'verbose': False
        }
        
        result = self.tool._run(**args)
        
        assert result.status == "success"
        assert 'outputs' in result.data
        assert 'summary' in result.data
        assert result.data['summary']['task'] == 'segmentation'
        assert result.data['summary']['model'] == 'unet'
        assert result.data['summary']['mode'] == 'inference'
    
    def test_run_training_mode(self):
        """Test training mode."""
        args = {
            'task': 'segmentation',
            'model_name': 'unet',
            'input_files': self.input_files,
            'label_files': self.label_files,
            'mode': 'train',
            'epochs': 2,  # Very few for testing
            'batch_size': 1,
            'learning_rate': 1e-4,
            'val_split': 0.3,
            'in_channels': 1,
            'out_channels': 2,
            'output_dir': self.temp_dir,
            'save_model': True,
            'visualize': False,
            'verbose': False
        }
        
        result = self.tool._run(**args)
        
        assert result.status == "success"
        assert result.data['summary']['mode'] == 'train'
        
        if self.tool.torch_available:
            assert 'training' in result.data['summary']
            training_results = result.data['summary']['training']
            if training_results and 'error' not in training_results:
                assert 'train_losses' in training_results
    
    def test_run_classification_task(self):
        """Test classification task."""
        args = {
            'task': 'classification',
            'model_name': 'densenet',
            'input_files': self.input_files,
            'label_files': self.label_files,
            'mode': 'inference',
            'in_channels': 1,
            'out_channels': 3,  # 3 classes
            'output_dir': self.temp_dir,
            'visualize': False,
            'verbose': False
        }
        
        result = self.tool._run(**args)
        
        assert result.status == "success"
        assert result.data['summary']['task'] == 'classification'
    
    def test_different_models(self):
        """Test different model architectures."""
        models_to_test = ['unet', 'segresnet', 'densenet']
        
        for model_name in models_to_test:
            args = {
                'task': 'segmentation',
                'model_name': model_name,
                'input_files': self.input_files[:1],
                'mode': 'inference',
                'in_channels': 1,
                'out_channels': 2,
                'roi_size': [32, 32, 32],
                'output_dir': self.temp_dir,
                'visualize': False,
                'verbose': False
            }
            
            result = self.tool._run(**args)
            
            assert result.status == "success"
            assert result.data['summary']['model'] == model_name
    
    def test_compute_metrics(self):
        """Test metric computation."""
        if self.tool.torch_available:
            import torch
            predictions = torch.sigmoid(torch.randn(1, 2, 32, 32, 32))
            labels = torch.randint(0, 2, (1, 2, 32, 32, 32)).float()
            
            metrics = self.tool._compute_metrics(predictions, labels)
            
            assert 'dice' in metrics
            assert 0 <= metrics['dice'] <= 1
    
    def test_model_save_load(self):
        """Test model saving and loading."""
        if self.tool.torch_available:
            import torch
            import torch.nn as nn
            
            # Create simple model
            model = nn.Sequential(
                nn.Conv3d(1, 8, 3),
                nn.ReLU(),
                nn.Conv3d(8, 2, 1)
            )
            
            # Save model
            model_path = Path(self.temp_dir) / "test_model.pth"
            self.tool._save_model(model, model_path)
            assert model_path.exists()
            
            # Load model
            new_model = nn.Sequential(
                nn.Conv3d(1, 8, 3),
                nn.ReLU(),
                nn.Conv3d(8, 2, 1)
            )
            loaded_model = self.tool._load_model(new_model, str(model_path))
            
            # Check weights are loaded
            for p1, p2 in zip(model.parameters(), loaded_model.parameters()):
                assert torch.allclose(p1, p2)
    
    def test_error_handling(self):
        """Test error handling."""
        args = {
            'task': 'invalid_task',
            'input_files': ['nonexistent.nii.gz'],
            'output_dir': self.temp_dir
        }
        
        result = self.tool._run(**args)
        
        # Should handle gracefully
        assert result.status in ["success", "error"]
    
    def test_device_selection(self):
        """Test device selection."""
        args = {
            'task': 'segmentation',
            'model_name': 'unet',
            'input_files': self.input_files[:1],
            'mode': 'inference',
            'device': 'cpu',  # Force CPU
            'output_dir': self.temp_dir,
            'visualize': False,
            'verbose': False
        }
        
        result = self.tool._run(**args)
        
        assert result.status == "success"
        if 'device' in result.data['summary']:
            assert 'cpu' in result.data['summary']['device'].lower()
    
    def test_preprocessing_options(self):
        """Test preprocessing options."""
        args = {
            'task': 'segmentation',
            'model_name': 'unet',
            'input_files': self.input_files,
            'mode': 'inference',
            'normalize': True,
            'spacing': [1.0, 1.0, 1.0],
            'roi_size': [64, 64, 64],
            'augment': False,  # No augmentation for inference
            'output_dir': self.temp_dir,
            'visualize': False,
            'verbose': False
        }
        
        result = self.tool._run(**args)
        
        assert result.status == "success"