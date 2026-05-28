"""Unit tests for ABCD Study data loader."""

import pytest
import numpy as np
from brain_researcher.core.ingestion.loaders.abcd_unified import ABCDUnifiedLoader


class TestABCDUnifiedLoader:
    """Test suite for ABCD loader."""
    
    @pytest.fixture
    def loader(self):
        """Create loader instance."""
        return ABCDUnifiedLoader()
    
    def test_load_subject_list(self, loader):
        """Test loading subject list."""
        subjects = loader.load_subject_list()
        
        assert len(subjects) > 0
        assert all(isinstance(s, str) for s in subjects)
        assert all(s.startswith('NDAR_INV') for s in subjects)
        assert loader.subjects == subjects
    
    def test_load_subject_list_baseline_only(self, loader):
        """Test loading baseline subjects only."""
        subjects = loader.load_subject_list(baseline_only=True)
        
        assert len(subjects) > 0
        # In test mode, should return same subjects
        assert all(s.startswith('NDAR_INV') for s in subjects)
    
    def test_load_behavioral_assessments_cognitive(self, loader):
        """Test loading cognitive assessments."""
        loader.load_subject_list()
        assessments = loader.load_behavioral_assessments('cognitive')
        
        assert 'NIH_Toolbox' in assessments
        assert 'RAVLT' in assessments
        assert 'Little_Man' in assessments
        assert 'CBCL' not in assessments  # Emotional assessment
        
        # Check NIH Toolbox structure
        toolbox = assessments['NIH_Toolbox']
        assert len(toolbox) > 0
        
        for subject_data in toolbox.values():
            assert 'crystallized_cognition' in subject_data
            assert 'fluid_cognition' in subject_data
            assert 'executive_function' in subject_data
            assert 'working_memory' in subject_data
            assert 70 <= subject_data['total_cognition'] <= 130  # Normal range
    
    def test_load_behavioral_assessments_emotional(self, loader):
        """Test loading emotional/behavioral assessments."""
        loader.load_subject_list()
        assessments = loader.load_behavioral_assessments('emotional')
        
        assert 'CBCL' in assessments
        assert 'BPM' in assessments
        assert 'UPPS' in assessments
        assert 'NIH_Toolbox' not in assessments  # Cognitive assessment
        
        # Check CBCL structure
        cbcl = assessments['CBCL']
        for subject_data in cbcl.values():
            assert 'internalizing' in subject_data
            assert 'externalizing' in subject_data
            assert 'anxiety' in subject_data
            assert 'depression' in subject_data
            assert 30 <= subject_data['total_problems'] <= 70  # T-score range
    
    def test_load_longitudinal_trajectories_cognitive(self, loader):
        """Test loading cognitive developmental trajectories."""
        loader.load_subject_list()
        trajectories = loader.load_longitudinal_trajectories('cognitive')
        
        assert len(trajectories) > 0
        
        for subject_id, traj in trajectories.items():
            assert 'ages' in traj
            assert 'values' in traj
            assert 'measure' in traj
            assert 'n_timepoints' in traj
            
            assert traj['measure'] == 'cognitive'
            assert 2 <= traj['n_timepoints'] <= 6
            assert all(9 <= age <= 18 for age in traj['ages'])
            assert traj['ages'] == sorted(traj['ages'])  # Ages should be sorted
    
    def test_load_longitudinal_trajectories_brain_volume(self, loader):
        """Test loading brain volume trajectories."""
        loader.load_subject_list()
        trajectories = loader.load_longitudinal_trajectories('brain_volume')
        
        for subject_id, traj in trajectories.items():
            assert traj['measure'] == 'brain_volume'
            values = traj['values']
            assert all(1000 <= v <= 2000 for v in values)  # Realistic volume range
    
    def test_load_longitudinal_trajectories_connectivity(self, loader):
        """Test loading connectivity trajectories."""
        loader.load_subject_list()
        trajectories = loader.load_longitudinal_trajectories('connectivity')
        
        for subject_id, traj in trajectories.items():
            assert traj['measure'] == 'connectivity'
            values = traj['values']
            # Connectivity should generally increase with age
            assert all(0 <= v <= 120 for v in values)
    
    def test_get_developmental_stage(self, loader):
        """Test developmental stage classification."""
        assert loader.get_developmental_stage(9.5) == 'early_childhood'
        assert loader.get_developmental_stage(12) == 'middle_childhood'
        assert loader.get_developmental_stage(14) == 'early_adolescence'
        assert loader.get_developmental_stage(16) == 'middle_adolescence'
        assert loader.get_developmental_stage(18) == 'late_adolescence'
        assert loader.get_developmental_stage(25) == 'unknown'
    
    def test_load_environmental_factors(self, loader):
        """Test loading environmental and demographic factors."""
        loader.load_subject_list()
        env_data = loader.load_environmental_factors()
        
        assert len(env_data) > 0
        
        for subject_id, data in env_data.items():
            assert 'family_income' in data
            assert 'parent_education' in data
            assert 'neighborhood_safety' in data
            assert 'school_engagement' in data
            assert 'screen_time_hours' in data
            assert 'sleep_hours' in data
            
            assert 1 <= data['neighborhood_safety'] <= 5
            assert 0 <= data['screen_time_hours'] <= 8
            assert 4 <= data['sleep_hours'] <= 12  # Reasonable sleep range
    
    def test_get_imaging_qc_metrics(self, loader):
        """Test imaging quality control metrics."""
        loader.load_subject_list()
        subject_id = loader.subjects[0]
        
        qc = loader.get_imaging_qc_metrics(subject_id)
        
        assert 'motion_fd_mean' in qc
        assert 'motion_fd_max' in qc
        assert 'snr' in qc
        assert 'cnr' in qc
        assert 'efc' in qc
        
        assert 0 <= qc['motion_fd_mean'] <= 1
        assert qc['motion_fd_max'] >= qc['motion_fd_mean']
        assert qc['snr'] > 0
    
    def test_export_for_kg(self, loader):
        """Test knowledge graph export."""
        loader.load_subject_list()
        loader.load_behavioral_assessments()
        loader.load_longitudinal_trajectories('cognitive')
        
        kg_data = loader.export_for_kg()
        
        assert 'nodes' in kg_data
        assert 'edges' in kg_data
        assert 'metadata' in kg_data
        
        # Check node types
        node_types = set(n['type'] for n in kg_data['nodes'])
        assert 'Subject' in node_types
        assert 'CognitiveAssessment' in node_types or 'DevelopmentalTrajectory' in node_types
        
        # Check edges
        edge_types = set(e['type'] for e in kg_data['edges'])
        assert 'HAS_ASSESSMENT' in edge_types or 'HAS_TRAJECTORY' in edge_types
        
        # Check metadata
        assert kg_data['metadata']['dataset'] == 'Adolescent Brain Cognitive Development Study'
        assert kg_data['metadata']['age_range'] == '9-20 years'
        assert kg_data['metadata']['longitudinal'] is True
    
    def test_get_statistics(self, loader):
        """Test statistics generation."""
        loader.load_subject_list()
        loader.load_behavioral_assessments()
        loader.load_longitudinal_trajectories('cognitive')
        
        stats = loader.get_statistics()
        
        assert 'total_subjects' in stats
        assert 'subjects_with_behavioral' in stats
        assert 'subjects_with_longitudinal' in stats
        assert 'assessment_types' in stats
        assert 'developmental_stages' in stats
        assert 'age_range' in stats
        assert 'mean_timepoints' in stats
        
        assert stats['total_subjects'] > 0
        assert stats['age_range'] == (9, 20)
        assert stats['mean_timepoints'] == 3.5
        assert len(stats['developmental_stages']) == 5
        
        # Check cognitive statistics if available
        if 'mean_cognitive_score' in stats:
            assert 70 <= stats['mean_cognitive_score'] <= 130
            assert stats['std_cognitive_score'] > 0