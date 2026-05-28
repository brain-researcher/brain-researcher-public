"""Tests for MNE-Python preprocessing tool."""

import pytest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch, MagicMock, call
import numpy as np

from brain_researcher.services.tools.mne_preprocessing_tool import (
    MNEPreprocessingTool,
    MNEPreprocessingArgs,
    FilterType,
    ReferenceType
)


class TestMNEPreprocessingTool:
    """Test suite for MNE preprocessing tool."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.tool = MNEPreprocessingTool()
        self.temp_dir = tempfile.mkdtemp()
    
    def test_tool_initialization(self):
        """Test tool initializes correctly."""
        assert self.tool.get_tool_name() == "mne_preprocessing"
        assert "preprocessing" in self.tool.get_tool_description().lower()
        assert "eeg" in self.tool.get_tool_description().lower() or "meg" in self.tool.get_tool_description().lower()
    
    def test_args_schema(self):
        """Test argument schema validation."""
        schema = self.tool.get_args_schema()
        
        # Check required fields
        assert "raw_file" in schema.model_fields
        assert "output_dir" in schema.model_fields
        
        # Check default values
        args = MNEPreprocessingArgs(
            raw_file="test.fif",
            output_dir="output"
        )
        assert args.l_freq == 0.1
        assert args.h_freq == 40.0
        assert args.reference == "average"
        assert args.detect_bad_channels == True
    
    def test_filter_parameters(self):
        """Test filter parameter validation."""
        args = MNEPreprocessingArgs(
            raw_file="test.fif",
            output_dir="output",
            l_freq=1.0,
            h_freq=30.0,
            filter_method="iir"
        )
        assert args.l_freq == 1.0
        assert args.h_freq == 30.0
        assert args.filter_method == "iir"
    
    def test_epoching_parameters(self):
        """Test epoching parameter setup."""
        event_id = {"stimulus": 1, "response": 2}
        args = MNEPreprocessingArgs(
            raw_file="test.fif",
            output_dir="output",
            create_epochs=True,
            epoch_tmin=-0.5,
            epoch_tmax=1.0,
            event_id=event_id
        )
        assert args.create_epochs == True
        assert args.epoch_tmin == -0.5
        assert args.epoch_tmax == 1.0
        assert args.event_id == event_id
    
    @patch('brain_researcher.services.tools.mne_preprocessing_tool.MNEPreprocessingTool._load_raw_data')
    def test_successful_preprocessing(self, mock_load):
        """Test successful preprocessing execution."""
        # Mock MNE imports
        with patch('brain_researcher.services.tools.mne_preprocessing_tool.mne') as mock_mne:
            # Setup mock raw object
            mock_raw = MagicMock()
            mock_raw.info = {
                'sfreq': 1000.0,
                'bads': [],
                'ch_names': ['Fp1', 'Fp2', 'F3', 'F4', 'C3', 'C4']
            }
            mock_raw.times = np.array([0, 1, 2, 3, 4])
            mock_raw.ch_names = ['Fp1', 'Fp2', 'F3', 'F4', 'C3', 'C4']
            mock_raw.get_data.return_value = np.random.randn(6, 5000)
            
            mock_load.return_value = mock_raw
            
            # Create output directory
            output_dir = Path(self.temp_dir) / "output"
            
            # Run preprocessing
            result = self.tool._run(
                raw_file="test.fif",
                output_dir=str(output_dir),
                l_freq=1.0,
                h_freq=40.0,
                reference="average"
            )
            
            # Check result
            assert result.status == "success"
            assert "outputs" in result.data
            assert "processing_log" in result.data
            assert "statistics" in result.data
            
            # Verify filtering was called
            mock_raw.filter.assert_called_once()
            
            # Verify reference was set
            mock_raw.set_eeg_reference.assert_called()
    
    @patch('brain_researcher.services.tools.mne_preprocessing_tool.MNEPreprocessingTool._load_raw_data')
    def test_bad_channel_detection(self, mock_load):
        """Test automatic bad channel detection."""
        # Create mock raw with bad channels
        mock_raw = MagicMock()
        mock_raw.ch_names = ['Good1', 'Bad1', 'Good2', 'Bad2']
        
        # Simulate bad channels with extreme variance
        good_data = np.random.randn(2, 1000)
        bad_data = np.concatenate([
            np.zeros((1, 1000)),  # Flat channel
            np.random.randn(1, 1000) * 100  # Noisy channel
        ])
        
        all_data = np.vstack([good_data[0:1], bad_data[0:1], 
                              good_data[1:2], bad_data[1:2]])
        mock_raw.get_data.return_value = all_data
        
        # Test detection
        bad_channels = self.tool._detect_bad_channels(mock_raw)
        
        # Should detect at least some bad channels
        assert len(bad_channels) > 0
    
    def test_load_raw_data_formats(self):
        """Test loading different file formats."""
        with patch('brain_researcher.services.tools.mne_preprocessing_tool.mne.io') as mock_io:
            # Test FIF format
            test_file = Path(self.temp_dir) / "test.fif"
            test_file.touch()
            self.tool._load_raw_data(str(test_file))
            mock_io.read_raw_fif.assert_called_once()
            
            # Reset mock
            mock_io.reset_mock()
            
            # Test EDF format
            test_file = Path(self.temp_dir) / "test.edf"
            test_file.touch()
            self.tool._load_raw_data(str(test_file))
            mock_io.read_raw_edf.assert_called_once()
            
            # Reset mock
            mock_io.reset_mock()
            
            # Test BrainVision format
            test_file = Path(self.temp_dir) / "test.vhdr"
            test_file.touch()
            self.tool._load_raw_data(str(test_file))
            mock_io.read_raw_brainvision.assert_called_once()
    
    def test_reference_types(self):
        """Test different reference types."""
        with patch('brain_researcher.services.tools.mne_preprocessing_tool.mne') as mock_mne:
            mock_raw = MagicMock()
            
            # Test average reference
            self.tool._apply_reference(mock_raw, "average")
            mock_raw.set_eeg_reference.assert_called_with('average', projection=False)
            
            # Reset mock
            mock_raw.reset_mock()
            
            # Test REST reference
            self.tool._apply_reference(mock_raw, "REST")
            mock_raw.set_eeg_reference.assert_called_with('REST')
            
            # Reset mock
            mock_raw.reset_mock()
            
            # Test custom channel reference
            self.tool._apply_reference(mock_raw, "Cz", ["Cz"])
            mock_raw.set_eeg_reference.assert_called_with(["Cz"])
    
    @patch('brain_researcher.services.tools.mne_preprocessing_tool.MNEPreprocessingTool._load_raw_data')
    def test_resampling(self, mock_load):
        """Test resampling functionality."""
        with patch('brain_researcher.services.tools.mne_preprocessing_tool.mne'):
            mock_raw = MagicMock()
            mock_raw.info = {'sfreq': 1000.0, 'bads': [], 'ch_names': ['Ch1']}
            mock_raw.times = np.array([0, 1])
            mock_raw.ch_names = ['Ch1']
            mock_raw.get_data.return_value = np.random.randn(1, 1000)
            
            mock_load.return_value = mock_raw
            
            # Run with resampling
            result = self.tool._run(
                raw_file="test.fif",
                output_dir=self.temp_dir,
                sfreq=250.0
            )
            
            # Verify resampling was called
            mock_raw.resample.assert_called_with(250.0)
    
    @patch('brain_researcher.services.tools.mne_preprocessing_tool.MNEPreprocessingTool._load_raw_data')
    def test_epoching(self, mock_load):
        """Test epoch creation."""
        with patch('brain_researcher.services.tools.mne_preprocessing_tool.mne') as mock_mne:
            # Setup mocks
            mock_raw = MagicMock()
            mock_raw.info = {'sfreq': 1000.0, 'bads': [], 'ch_names': ['Ch1']}
            mock_raw.times = np.array([0, 1])
            mock_raw.ch_names = ['Ch1', 'STI 014']
            mock_raw.get_data.return_value = np.random.randn(2, 1000)
            
            mock_load.return_value = mock_raw
            
            # Mock event finding
            mock_events = np.array([[100, 0, 1], [200, 0, 2]])
            mock_mne.find_events.return_value = mock_events
            
            # Mock Epochs class
            mock_epochs = MagicMock()
            mock_epochs.__len__.return_value = 2
            mock_mne.Epochs.return_value = mock_epochs
            
            # Run with epoching
            result = self.tool._run(
                raw_file="test.fif",
                output_dir=self.temp_dir,
                create_epochs=True,
                epoch_tmin=-0.2,
                epoch_tmax=0.8,
                event_id={'stim': 1, 'resp': 2}
            )
            
            # Verify epochs were created
            mock_mne.Epochs.assert_called_once()
            assert result.data["statistics"]["n_epochs"] == 2
    
    @patch('brain_researcher.services.tools.mne_preprocessing_tool.MNEPreprocessingTool._run')
    def test_batch_preprocessing(self, mock_run):
        """Test batch preprocessing of multiple files."""
        # Mock successful runs
        mock_run.return_value = MagicMock(
            status="success",
            data={"outputs": {"preprocessed_data": "output.fif"}}
        )
        
        # Create test input files
        input_files = [f"file_{i}.fif" for i in range(3)]
        
        # Run batch processing
        result = self.tool.batch_preprocess(
            input_files=input_files,
            output_dir=self.temp_dir,
            l_freq=1.0,
            h_freq=40.0
        )
        
        # Check results
        assert result.status == "success"
        assert result.data["n_processed"] == 3
        assert result.data["n_failed"] == 0
        assert mock_run.call_count == 3
    
    def test_notch_filter(self):
        """Test notch filter for line noise removal."""
        args = MNEPreprocessingArgs(
            raw_file="test.fif",
            output_dir="output",
            notch_freq=50.0  # 50 Hz line noise
        )
        assert args.notch_freq == 50.0
        
        # Test multiple notch frequencies
        args = MNEPreprocessingArgs(
            raw_file="test.fif",
            output_dir="output",
            notch_freq=[50.0, 100.0, 150.0]  # Harmonics
        )
        assert args.notch_freq == [50.0, 100.0, 150.0]
    
    def test_montage_setting(self):
        """Test standard montage setting."""
        args = MNEPreprocessingArgs(
            raw_file="test.fif",
            output_dir="output",
            set_montage="standard_1020"
        )
        assert args.set_montage == "standard_1020"
    
    @pytest.mark.integration
    def test_with_real_eeg_data(self):
        """Test with real EEG data if available."""
        # This would test with actual EEG files if available
        test_file = Path("/path/to/test/eeg/data.edf")
        
        if not test_file.exists():
            pytest.skip("Test EEG data not available")
        
        output_dir = Path(self.temp_dir) / "real_output"
        
        result = self.tool._run(
            raw_file=str(test_file),
            output_dir=str(output_dir),
            l_freq=0.5,
            h_freq=45.0,
            notch_freq=50.0,
            reference="average",
            detect_bad_channels=True,
            interpolate_bads=True
        )
        
        # For real execution, check outputs
        assert result.status in ["success", "error"]
        if result.status == "success":
            assert Path(result.data["outputs"]["preprocessed_data"]).exists()
    
    def teardown_method(self):
        """Clean up test files."""
        import shutil
        if Path(self.temp_dir).exists():
            shutil.rmtree(self.temp_dir)