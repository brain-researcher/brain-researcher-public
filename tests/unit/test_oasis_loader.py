"""Unit tests for OASIS data loader."""

import pytest
import numpy as np
from brain_researcher.core.ingestion.loaders.oasis_unified import OASISUnifiedLoader


class TestOASISUnifiedLoader:
    """Test suite for OASIS loader."""
    
    @pytest.fixture
    def loader(self):
        """Create loader instance."""
        return OASISUnifiedLoader()
    
    def test_load_oasis1_cross_sectional(self, loader):
        """Test loading OASIS-1 cross-sectional data."""
        data = loader.load_oasis1_cross_sectional()
        
        assert 'subjects' in data
        assert 'demographics' in data
        assert 'clinical' in data
        assert 'imaging' in data
        
        # Check expected number of subjects
        assert len(data['subjects']) == 416
        
        # Check data structure
        for subject_id in data['subjects'][:10]:
            assert subject_id in data['demographics']
            assert subject_id in data['clinical']
            assert subject_id in data['imaging']
            
            # Check demographics
            demo = data['demographics'][subject_id]
            assert 'age' in demo
            assert 'gender' in demo
            assert 'education' in demo
            
            # Check clinical
            clinical = data['clinical'][subject_id]
            assert 'mmse' in clinical
            assert 'cdr' in clinical
            assert 'diagnosis' in clinical
            
            # Check imaging
            imaging = data['imaging'][subject_id]
            assert 'etiv' in imaging
            assert 'nwbv' in imaging
            assert 'asf' in imaging
    
    def test_cdr_scale(self, loader):
        """Test CDR scale mapping."""
        assert loader.cdr_scale[0] == 'Normal'
        assert loader.cdr_scale[0.5] == 'Very Mild Dementia'
        assert loader.cdr_scale[1] == 'Mild Dementia'
        assert loader.cdr_scale[2] == 'Moderate Dementia'
        assert loader.cdr_scale[3] == 'Severe Dementia'
    
    def test_load_oasis2_longitudinal(self, loader):
        """Test loading OASIS-2 longitudinal data."""
        data = loader.load_oasis2_longitudinal()
        
        assert 'subjects' in data
        assert 'longitudinal' in data
        
        # Check expected number of subjects
        assert len(data['subjects']) == 150
        
        # Check longitudinal data structure
        for subject_id in data['subjects'][:10]:
            assert subject_id in data['longitudinal']
            
            long_data = data['longitudinal'][subject_id]
            assert 'visits' in long_data
            assert 'n_visits' in long_data
            assert 'follow_up_years' in long_data
            
            # Check visits
            visits = long_data['visits']
            assert len(visits) >= 2  # At least 2 visits
            assert len(visits) <= 5  # At most 5 visits
            
            for visit in visits:
                assert 'visit' in visit
                assert 'age' in visit
                assert 'mmse' in visit
                assert 'cdr' in visit
                assert 'days_from_baseline' in visit
            
            # Check visits are chronological
            days = [v['days_from_baseline'] for v in visits]
            assert days == sorted(days)
    
    def test_load_oasis3_multimodal(self, loader):
        """Test loading OASIS-3 multimodal data."""
        data = loader.load_oasis3_multimodal()
        
        assert 'subjects' in data
        assert 'multimodal' in data
        
        # Check data structure
        for subject_id in data['subjects'][:10]:
            assert subject_id in data['multimodal']
            
            mm_data = data['multimodal'][subject_id]
            
            # Check all modalities present
            assert 'demographics' in mm_data
            assert 'clinical' in mm_data
            assert 'imaging' in mm_data
            assert 'pet' in mm_data
            assert 'biomarkers' in mm_data
            assert 'cognitive_battery' in mm_data
            
            # Check demographics
            demo = mm_data['demographics']
            assert 'age' in demo
            assert 'gender' in demo
            assert 'race' in demo
            assert 'apoe_genotype' in demo
            
            # Check clinical
            clinical = mm_data['clinical']
            assert 'diagnosis' in clinical
            assert clinical['diagnosis'] in ['AD', 'CN']
            assert 'mmse' in clinical
            assert 'moca' in clinical
            
            # Check imaging flags
            imaging = mm_data['imaging']
            assert 'has_t1' in imaging
            assert imaging['has_t1'] is True  # T1 always present
            assert 'has_rest_fmri' in imaging
            assert 'has_task_fmri' in imaging
            
            # Check PET
            pet = mm_data['pet']
            assert 'has_fdg' in pet
            assert 'has_pib' in pet
            assert 'amyloid_positive' in pet
            assert isinstance(pet['amyloid_positive'], bool)
    
    def test_calculate_brain_age_delta(self, loader):
        """Test brain age delta calculation."""
        # Load some data first
        loader.load_oasis1_cross_sectional()
        
        if loader.subjects:
            subject_id = loader.subjects[0]
            delta = loader.calculate_brain_age_delta(subject_id)
            
            # Delta should be a reasonable value
            assert isinstance(delta, float)
            assert -30 <= delta <= 30  # Reasonable range
    
    def test_identify_converters(self, loader):
        """Test identifying converters."""
        # Load longitudinal data
        loader.load_oasis2_longitudinal()
        
        converters = loader.identify_converters()
        
        assert isinstance(converters, list)
        
        # Check that converters actually converted
        for converter_id in converters:
            if converter_id in loader.longitudinal_data:
                visits = loader.longitudinal_data[converter_id]['visits']
                first_cdr = visits[0].get('cdr', 0)
                last_cdr = visits[-1].get('cdr', 0)
                assert first_cdr == 0
                assert last_cdr > 0
    
    def test_export_for_kg(self, loader):
        """Test knowledge graph export."""
        # Load multiple datasets
        loader.load_oasis1_cross_sectional()
        loader.load_oasis2_longitudinal()
        
        kg_data = loader.export_for_kg()
        
        assert 'nodes' in kg_data
        assert 'edges' in kg_data
        assert 'metadata' in kg_data
        
        # Check node types
        node_types = set(n['type'] for n in kg_data['nodes'])
        assert 'Subject' in node_types
        assert 'ClinicalAssessment' in node_types or 'ImagingData' in node_types
        
        # Check edges
        edge_types = set(e['type'] for e in kg_data['edges'])
        assert 'HAS_ASSESSMENT' in edge_types or 'HAS_IMAGING' in edge_types
        
        # Check metadata
        metadata = kg_data['metadata']
        assert metadata['dataset'] == 'Open Access Series of Imaging Studies'
        assert 'OASIS-1' in metadata['datasets']
        assert metadata['focus'] == "Aging and Alzheimer's Disease"
    
    def test_get_statistics(self, loader):
        """Test statistics generation."""
        # Load data
        loader.load_oasis1_cross_sectional()
        loader.load_oasis2_longitudinal()
        
        stats = loader.get_statistics()
        
        assert 'total_subjects' in stats
        assert 'cross_sectional_subjects' in stats
        assert 'longitudinal_subjects' in stats
        assert 'age_range' in stats
        assert 'mean_age' in stats
        assert 'cdr_distribution' in stats
        assert 'gender_distribution' in stats
        assert 'n_converters' in stats
        assert 'conversion_rate' in stats
        
        # Check values
        assert stats['total_subjects'] > 0
        assert stats['cross_sectional_subjects'] == 416
        assert stats['longitudinal_subjects'] == 150
        
        # Check age range
        age_min, age_max = stats['age_range']
        assert 18 <= age_min <= 96
        assert 18 <= age_max <= 96
        assert age_min < age_max
        
        # Check CDR distribution
        cdr_dist = stats['cdr_distribution']
        assert 'Normal' in cdr_dist
        total_cdr = sum(cdr_dist.values())
        assert total_cdr > 0
        
        # Check conversion rate
        assert 0 <= stats['conversion_rate'] <= 1
    
    def test_data_consistency(self, loader):
        """Test data consistency across datasets."""
        # Load all datasets
        oasis1 = loader.load_oasis1_cross_sectional()
        oasis2 = loader.load_oasis2_longitudinal()
        oasis3 = loader.load_oasis3_multimodal()
        
        # Check that subject IDs are unique within each dataset
        assert len(oasis1['subjects']) == len(set(oasis1['subjects']))
        assert len(oasis2['subjects']) == len(set(oasis2['subjects']))
        assert len(oasis3['subjects']) == len(set(oasis3['subjects']))
        
        # Check that all subjects have required data
        for subject_id in oasis1['subjects'][:10]:
            assert subject_id in oasis1['demographics']
            assert subject_id in oasis1['clinical']
            assert subject_id in oasis1['imaging']
        
        for subject_id in oasis2['subjects'][:10]:
            assert subject_id in oasis2['longitudinal']
            long_data = oasis2['longitudinal'][subject_id]
            assert long_data['n_visits'] == len(long_data['visits'])
        
        for subject_id in oasis3['subjects'][:10]:
            assert subject_id in oasis3['multimodal']
            mm_data = oasis3['multimodal'][subject_id]
            # Check required fields are present
            assert all(key in mm_data for key in [
                'demographics', 'clinical', 'imaging', 'pet', 'biomarkers'
            ])