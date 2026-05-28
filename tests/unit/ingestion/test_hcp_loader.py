"""Unit tests for HCP data loader."""

import os

import numpy as np
import pytest

from brain_researcher.core.ingestion.loaders.hcp_unified import HCPUnifiedLoader


def _run_hcp_tests() -> bool:
    return os.getenv("BR_RUN_HCP_TESTS", "").lower() in {"1", "true", "yes"}


@pytest.mark.skipif(
    not _run_hcp_tests(),
    reason="HCP source files not available; set BR_RUN_HCP_TESTS=1 to enable.",
)
class TestHCPUnifiedLoader:
    """Test suite for HCP loader."""
    
    @pytest.fixture
    def loader(self):
        """Create loader instance."""
        return HCPUnifiedLoader()
    
    def test_load_subject_list(self, loader):
        """Test loading subject list."""
        subjects = loader.load_subject_list()
        
        assert len(subjects) > 0
        assert all(isinstance(s, str) for s in subjects)
        assert loader.subjects == subjects
    
    def test_load_behavioral_data(self, loader):
        """Test loading behavioral data."""
        loader.load_subject_list()
        behavioral = loader.load_behavioral_data()
        
        assert len(behavioral) > 0
        
        # Check data structure
        for subject_id, data in behavioral.items():
            assert 'Age' in data
            assert 'Gender' in data
            assert 'Education' in data
            assert 'BMI' in data
    
    def test_load_scan_parameters(self, loader):
        """Test loading scan parameters."""
        loader.load_subject_list()
        subject_id = loader.subjects[0]
        
        params = loader.load_scan_parameters(subject_id)
        
        assert len(params) > 0
        assert 'T1w' in params
        assert 'rfMRI_REST' in params
        
        # Check T1w parameters
        t1_params = params['T1w']
        assert t1_params['scanner'] == 'Siemens 3T Connectome Skyra'
        assert t1_params['resolution'] == '0.7mm isotropic'
    
    def test_get_task_contrasts(self, loader):
        """Test getting task contrasts."""
        motor_contrasts = loader.get_task_contrasts('MOTOR')
        
        assert len(motor_contrasts) == 5
        contrast_names = [c['name'] for c in motor_contrasts]
        assert 'lh' in contrast_names
        assert 'rh' in contrast_names
        assert 'lf' in contrast_names
        
        wm_contrasts = loader.get_task_contrasts('WM')
        assert len(wm_contrasts) == 4
        assert any('2back_0back' in c['name'] for c in wm_contrasts)
    
    def test_get_connectivity_matrix(self, loader):
        """Test connectivity matrix generation."""
        loader.load_subject_list()
        subject_id = loader.subjects[0]
        
        # Test Glasser parcellation
        matrix = loader.get_connectivity_matrix(subject_id, 'Glasser360')
        assert matrix.shape == (360, 360)
        assert np.allclose(matrix, matrix.T)  # Should be symmetric
        assert np.all(np.diag(matrix) == 1)  # Diagonal should be 1
        
        # Test different parcellation
        matrix2 = loader.get_connectivity_matrix(subject_id, 'Schaefer400')
        assert matrix2.shape == (400, 400)
    
    def test_export_for_kg(self, loader):
        """Test knowledge graph export."""
        loader.load_subject_list()
        loader.load_behavioral_data()
        
        # Load scan params for first subject
        loader.load_scan_parameters(loader.subjects[0])
        
        kg_data = loader.export_for_kg()
        
        assert 'nodes' in kg_data
        assert 'edges' in kg_data
        assert 'metadata' in kg_data
        
        # Check node types
        node_types = set(n['type'] for n in kg_data['nodes'])
        assert 'Subject' in node_types
        assert 'BehavioralData' in node_types or 'Scan' in node_types
        
        # Check metadata
        assert kg_data['metadata']['dataset'] == 'Human Connectome Project'
        assert kg_data['metadata']['subjects'] > 0
    
    def test_statistics(self, loader):
        """Test statistics generation."""
        loader.load_subject_list()
        loader.load_behavioral_data()
        
        stats = loader.get_statistics()
        
        assert 'total_subjects' in stats
        assert 'subjects_with_behavioral' in stats
        assert 'scan_types' in stats
        assert 'behavioral_domains' in stats
        
        assert stats['total_subjects'] > 0
        assert len(stats['scan_types']) == 11  # HCP has 11 scan types
        assert len(stats['behavioral_domains']) == 8  # 8 domains
        
        # Check demographics if available
        if stats.get('mean_age'):
            assert 22 <= stats['mean_age'] <= 35  # HCP age range
