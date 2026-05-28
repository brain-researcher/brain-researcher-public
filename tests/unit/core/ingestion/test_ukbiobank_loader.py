"""Unit tests for UK Biobank Unified Loader."""

import json
import os
import pytest
import numpy as np
import pandas as pd
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from brain_researcher.core.ingestion.loaders.ukbiobank_unified import UKBiobankUnifiedLoader


class TestUKBiobankUnifiedLoader:
    """Test UKBiobankUnifiedLoader class."""
    
    def test_init_default(self):
        """Test loader initialization with default parameters."""
        loader = UKBiobankUnifiedLoader()
        
        assert loader.data_dir is None
        assert loader.phenotype_file is None
        assert loader.imaging_dir is None
        assert loader.genetic_dir is None
        assert loader.cache_dir.is_dir()
        assert loader.cache_dir.name.startswith('ukbiobank_cache')
        assert os.access(loader.cache_dir, os.W_OK)
        assert len(loader.subjects) == 0
        assert len(loader.phenotype_data) == 0
        assert len(loader.imaging_metrics) == 0
        assert len(loader.genetic_markers) == 0
        assert len(loader.quality_scores) == 0
    
    def test_init_with_params(self, tmp_path):
        """Test loader initialization with custom parameters."""
        data_dir = tmp_path / "ukb_data"
        data_dir.mkdir()
        
        phenotype_file = data_dir / "phenotype.csv"
        phenotype_file.write_text("eid,age\n1000001,45\n")
        
        imaging_dir = data_dir / "imaging"
        imaging_dir.mkdir()
        
        genetic_dir = data_dir / "genetic"
        genetic_dir.mkdir()
        
        cache_dir = tmp_path / "cache"
        
        loader = UKBiobankUnifiedLoader(
            data_dir=str(data_dir),
            phenotype_file=str(phenotype_file),
            imaging_dir=str(imaging_dir),
            genetic_dir=str(genetic_dir),
            cache_dir=str(cache_dir)
        )
        
        assert loader.data_dir == data_dir
        assert loader.phenotype_file == phenotype_file
        assert loader.imaging_dir == imaging_dir
        assert loader.genetic_dir == genetic_dir
        assert loader.cache_dir == cache_dir
        assert cache_dir.exists()
    
    def test_load_subjects_demo_mode(self):
        """Test loading subjects in demo mode."""
        loader = UKBiobankUnifiedLoader()
        
        subjects = loader.load_subjects(n_subjects=50, demo_mode=True)
        
        assert len(subjects) == 50
        assert all(isinstance(s, str) for s in subjects)
        assert all(s.startswith('100') for s in subjects)
        assert loader.subjects == subjects
    
    def test_load_subjects_from_file(self, tmp_path):
        """Test loading subjects from file."""
        subject_file = tmp_path / "subjects.csv"
        subjects_data = "\n".join(["1000001", "1000002", "1000003", "1000004", "1000005"])
        subject_file.write_text(subjects_data)
        
        loader = UKBiobankUnifiedLoader()
        subjects = loader.load_subjects(subject_file=str(subject_file), n_subjects=3)
        
        assert len(subjects) == 3
        assert subjects == ["1000001", "1000002", "1000003"]
        assert loader.subjects == subjects
    
    def test_load_subjects_from_phenotype_file(self, tmp_path):
        """Test loading subjects from phenotype file."""
        phenotype_file = tmp_path / "phenotype.csv"
        phenotype_data = "eid,age,sex\n1000001,45,1\n1000002,50,0\n1000003,35,1\n"
        phenotype_file.write_text(phenotype_data)
        
        loader = UKBiobankUnifiedLoader(phenotype_file=str(phenotype_file))
        subjects = loader.load_subjects()
        
        assert len(subjects) == 3
        assert subjects == ["1000001", "1000002", "1000003"]
        assert loader.subjects == subjects
    
    def test_load_subjects_no_source_error(self):
        """Test error when no data source is provided."""
        loader = UKBiobankUnifiedLoader()
        
        with pytest.raises(ValueError, match="No UK Biobank data source specified"):
            loader.load_subjects()
    
    def test_load_phenotype_data_demo_mode(self):
        """Test loading phenotype data in demo mode."""
        loader = UKBiobankUnifiedLoader()
        loader.load_subjects(n_subjects=20, demo_mode=True)
        
        phenotype_data = loader.load_phenotype_data(demo_mode=True)
        
        assert 'demographics' in phenotype_data
        assert 'cognitive' in phenotype_data
        assert 'health' in phenotype_data
        assert 'lifestyle' in phenotype_data
        
        # Check demographics data structure
        demo_df = phenotype_data['demographics']
        assert isinstance(demo_df, pd.DataFrame)
        assert len(demo_df) == 20
        assert 'eid' in demo_df.columns
        assert 'age' in demo_df.columns
        assert 'sex' in demo_df.columns
        
        # Check cognitive data
        cog_df = phenotype_data['cognitive']
        assert isinstance(cog_df, pd.DataFrame)
        assert 'fluid_intelligence' in cog_df.columns
        assert 'reaction_time' in cog_df.columns
    
    def test_load_phenotype_data_from_file(self, tmp_path):
        """Test loading phenotype data from file."""
        phenotype_file = tmp_path / "phenotype.csv"
        phenotype_data = "eid,f.31.0.0,f.21003.0.0,f.20016.0.0\n1000001,1,45,8\n1000002,0,50,7\n"
        phenotype_file.write_text(phenotype_data)
        
        loader = UKBiobankUnifiedLoader(phenotype_file=str(phenotype_file))
        loader.load_subjects()
        
        phenotype_data = loader.load_phenotype_data()
        
        assert 'demographics' in phenotype_data
        assert 'cognitive' in phenotype_data
        
        demo_df = phenotype_data['demographics']
        assert len(demo_df) == 2
        assert 'f.31.0.0' in demo_df.columns  # sex field
        assert 'f.21003.0.0' in demo_df.columns  # age field
    
    def test_load_phenotype_data_specific_fields(self, tmp_path):
        """Test loading specific phenotype fields."""
        phenotype_file = tmp_path / "phenotype.csv"
        phenotype_data = "eid,f.31.0.0,f.21003.0.0,f.20016.0.0,f.25781.0.0\n1000001,1,45,8,600000\n"
        phenotype_file.write_text(phenotype_data)
        
        loader = UKBiobankUnifiedLoader(phenotype_file=str(phenotype_file))
        loader.load_subjects()
        
        phenotype_data = loader.load_phenotype_data(fields=['31', '21003'])
        
        # Should only load specified fields plus eid
        demo_df = phenotype_data['demographics']
        expected_cols = ['eid', 'f.31.0.0', 'f.21003.0.0']
        assert all(col in demo_df.columns for col in expected_cols)
        assert 'f.20016.0.0' not in demo_df.columns
        assert 'f.25781.0.0' not in demo_df.columns
    
    def test_load_imaging_metrics_demo_mode(self):
        """Test loading imaging metrics in demo mode."""
        loader = UKBiobankUnifiedLoader()
        loader.load_subjects(n_subjects=30, demo_mode=True)
        
        imaging_metrics = loader.load_imaging_metrics(demo_mode=True)
        
        assert 'T1_structural' in imaging_metrics
        assert 'resting_fMRI' in imaging_metrics
        assert 'diffusion_MRI' in imaging_metrics
        
        # Check T1 structural data
        t1_data = imaging_metrics['T1_structural']
        assert 'subjects' in t1_data
        assert 'grey_matter_volume' in t1_data
        assert 'white_matter_volume' in t1_data
        assert 'hippocampus_left' in t1_data
        
        # Check data consistency
        assert len(t1_data['subjects']) <= 30  # Limited by demo mode
        assert len(t1_data['grey_matter_volume']) == len(t1_data['subjects'])
    
    def test_load_imaging_metrics_specific_modalities(self):
        """Test loading specific imaging modalities."""
        loader = UKBiobankUnifiedLoader()
        loader.load_subjects(n_subjects=20, demo_mode=True)
        
        imaging_metrics = loader.load_imaging_metrics(
            modalities=['T1_structural', 'resting_fMRI'],
            demo_mode=True
        )
        
        assert 'T1_structural' in imaging_metrics
        assert 'resting_fMRI' in imaging_metrics
        assert 'diffusion_MRI' not in imaging_metrics
    
    def test_load_genetic_markers_demo_mode(self):
        """Test loading genetic markers in demo mode."""
        loader = UKBiobankUnifiedLoader()
        loader.load_subjects(n_subjects=15, demo_mode=True)
        
        genetic_markers = loader.load_genetic_markers(demo_mode=True)
        
        assert 'snps' in genetic_markers
        assert 'polygenic_scores' in genetic_markers
        assert 'ancestry' in genetic_markers
        
        # Check SNP data
        snp_data = genetic_markers['snps']
        assert 'subjects' in snp_data
        assert 'markers' in snp_data
        assert 'allele_frequencies' in snp_data
        
        # Check PRS data
        prs_data = genetic_markers['polygenic_scores']
        assert 'alzheimers_prs' in prs_data
        assert 'parkinsons_prs' in prs_data
        
        # Check ancestry data
        ancestry_data = genetic_markers['ancestry']
        assert 'pc1' in ancestry_data
        assert 'ancestry_group' in ancestry_data
    
    def test_load_genetic_markers_specific_types(self):
        """Test loading specific genetic marker types."""
        loader = UKBiobankUnifiedLoader()
        loader.load_subjects(n_subjects=15, demo_mode=True)
        
        genetic_markers = loader.load_genetic_markers(
            marker_types=['polygenic_scores'],
            demo_mode=True
        )
        
        assert 'polygenic_scores' in genetic_markers
        assert 'snps' not in genetic_markers
        assert 'ancestry' not in genetic_markers
    
    def test_calculate_quality_scores(self):
        """Test quality score calculation."""
        loader = UKBiobankUnifiedLoader()
        loader.load_subjects(n_subjects=100, demo_mode=True)
        loader.load_phenotype_data(demo_mode=True)
        loader.load_imaging_metrics(demo_mode=True)
        loader.load_genetic_markers(demo_mode=True)
        
        quality_scores = loader.calculate_quality_scores()
        
        assert 'data_completeness' in quality_scores
        assert 'phenotype_coverage' in quality_scores
        assert 'imaging_quality' in quality_scores
        assert 'genetic_coverage' in quality_scores
        assert 'overall_quality' in quality_scores
        
        # Check score ranges
        for score_name, score in quality_scores.items():
            assert 0.0 <= score <= 1.0, f"Score {score_name} out of range: {score}"
        
        # Overall should be weighted average
        expected_overall = 0.25 * (
            quality_scores['data_completeness'] +
            quality_scores['phenotype_coverage'] +
            quality_scores['imaging_quality'] +
            quality_scores['genetic_coverage']
        )
        assert abs(quality_scores['overall_quality'] - expected_overall) < 1e-6
    
    def test_export_to_knowledge_graph(self):
        """Test knowledge graph export."""
        loader = UKBiobankUnifiedLoader()
        loader.load_subjects(n_subjects=50, demo_mode=True)
        loader.load_phenotype_data(demo_mode=True)
        loader.load_imaging_metrics(demo_mode=True)
        loader.load_genetic_markers(demo_mode=True)
        
        kg_data = loader.export_to_knowledge_graph()
        
        assert 'nodes' in kg_data
        assert 'edges' in kg_data
        assert 'metadata' in kg_data
        
        # Check metadata
        metadata = kg_data['metadata']
        assert metadata['source'] == 'UK_Biobank'
        assert metadata['version'] == '2024.1'
        assert metadata['n_subjects'] == 50
        assert 'timestamp' in metadata
        
        # Check nodes
        nodes = kg_data['nodes']
        assert len(nodes) > 0
        
        # Check subject nodes
        subject_nodes = [n for n in nodes if n['type'] == 'Subject']
        assert len(subject_nodes) <= 100  # Limited by export
        
        # Check phenotype nodes
        phenotype_nodes = [n for n in nodes if n['type'] == 'Phenotype']
        assert len(phenotype_nodes) > 0
        
        # Check node structure
        for node in nodes[:5]:  # Check first few nodes
            assert 'id' in node
            assert 'type' in node
            assert 'properties' in node
    
    def test_get_statistics(self):
        """Test statistics generation."""
        loader = UKBiobankUnifiedLoader()
        loader.load_subjects(n_subjects=75, demo_mode=True)
        loader.load_phenotype_data(demo_mode=True)
        loader.load_imaging_metrics(modalities=['T1_structural', 'resting_fMRI'], demo_mode=True)
        loader.load_genetic_markers(marker_types=['snps', 'ancestry'], demo_mode=True)
        loader.calculate_quality_scores()
        
        stats = loader.get_statistics()
        
        assert stats['n_subjects'] == 75
        assert stats['phenotype_fields'] > 0
        assert stats['imaging_modalities'] == 2
        assert stats['genetic_markers'] > 0
        assert 'quality_scores' in stats
        assert 'data_summary' in stats
        
        # Check data summary
        summary = stats['data_summary']
        assert summary['has_phenotypes'] is True
        assert summary['has_imaging'] is True
        assert summary['has_genetics'] is True
    
    def test_field_mappings_completeness(self):
        """Test that field mappings are complete."""
        loader = UKBiobankUnifiedLoader()
        
        # Check that essential field mappings exist
        essential_fields = ['sex', 'age_at_recruitment', 'fluid_intelligence']
        for field in essential_fields:
            assert field in loader.field_mappings.values()
        
        # Check field ID format
        for field_id in loader.field_mappings.keys():
            assert field_id.isdigit(), f"Field ID should be numeric: {field_id}"
    
    def test_imaging_modalities_list(self):
        """Test imaging modalities configuration."""
        loader = UKBiobankUnifiedLoader()
        
        expected_modalities = [
            'T1_structural',
            'T2_FLAIR', 
            'resting_fMRI',
            'task_fMRI',
            'diffusion_MRI',
            'susceptibility_weighted',
            'arterial_spin_labelling'
        ]
        
        assert loader.imaging_modalities == expected_modalities
    
    def test_qc_metrics_list(self):
        """Test quality control metrics configuration."""
        loader = UKBiobankUnifiedLoader()
        
        expected_metrics = [
            'motion_parameters',
            'signal_to_noise',
            'registration_quality',
            'segmentation_quality',
            'completeness_score'
        ]
        
        assert loader.qc_metrics == expected_metrics
    
    def test_error_handling_missing_phenotype_file(self):
        """Test error handling for missing phenotype file."""
        loader = UKBiobankUnifiedLoader()
        
        with pytest.raises(ValueError, match="Phenotype file not found"):
            loader.load_phenotype_data()
    
    def test_error_handling_missing_imaging_dir(self):
        """Test error handling for missing imaging directory."""
        loader = UKBiobankUnifiedLoader()
        loader.load_subjects(demo_mode=True)
        
        with pytest.raises(ValueError, match="Imaging directory not found"):
            loader.load_imaging_metrics()
    
    def test_error_handling_missing_genetic_dir(self):
        """Test error handling for missing genetic directory."""
        loader = UKBiobankUnifiedLoader()
        loader.load_subjects(demo_mode=True)
        
        with pytest.raises(ValueError, match="Genetic directory not found"):
            loader.load_genetic_markers()
    
    def test_demo_data_reproducibility(self):
        """Test that demo data generation is reproducible."""
        loader1 = UKBiobankUnifiedLoader()
        loader2 = UKBiobankUnifiedLoader()
        
        # Load same demo data
        subjects1 = loader1.load_subjects(n_subjects=50, demo_mode=True)
        subjects2 = loader2.load_subjects(n_subjects=50, demo_mode=True)
        
        assert subjects1 == subjects2
        
        # Load phenotype data
        phenotype1 = loader1.load_phenotype_data(demo_mode=True)
        phenotype2 = loader2.load_phenotype_data(demo_mode=True)
        
        # Compare demographics dataframes
        pd.testing.assert_frame_equal(
            phenotype1['demographics'], 
            phenotype2['demographics']
        )
    
    def test_cache_directory_creation(self, tmp_path):
        """Test that cache directory is created if it doesn't exist."""
        cache_dir = tmp_path / "test_cache"
        assert not cache_dir.exists()
        
        loader = UKBiobankUnifiedLoader(cache_dir=str(cache_dir))
        
        assert cache_dir.exists()
        assert cache_dir.is_dir()
    
    def test_private_methods_demo_generation(self):
        """Test private demo data generation methods."""
        loader = UKBiobankUnifiedLoader()
        
        # Test demo subjects generation
        demo_subjects = loader._generate_demo_subjects(25)
        assert len(demo_subjects) == 25
        assert all(isinstance(s, str) for s in demo_subjects)
        
        # Set subjects for other methods
        loader.subjects = demo_subjects
        
        # Test demo phenotypes generation
        demo_phenotypes = loader._generate_demo_phenotypes()
        assert len(demo_phenotypes) == 4  # demographics, cognitive, health, lifestyle
        for category, df in demo_phenotypes.items():
            assert isinstance(df, pd.DataFrame)
            assert len(df) == 25
        
        # Test demo imaging generation
        demo_imaging = loader._generate_demo_imaging()
        assert 'T1_structural' in demo_imaging
        assert 'resting_fMRI' in demo_imaging
        assert 'diffusion_MRI' in demo_imaging
        
        # Test demo genetics generation  
        demo_genetics = loader._generate_demo_genetics()
        assert 'snps' in demo_genetics
        assert 'polygenic_scores' in demo_genetics
        assert 'ancestry' in demo_genetics
    
    def test_extract_phenotype_categories(self, tmp_path):
        """Test phenotype data extraction by category."""
        loader = UKBiobankUnifiedLoader()
        
        # Create test dataframe with various field IDs
        test_df = pd.DataFrame({
            'eid': ['1000001', '1000002'],
            'f.31.0.0': [1, 0],  # sex
            'f.21003.0.0': [45, 50],  # age
            'f.20016.0.0': [8, 7],  # fluid intelligence
            'f.20002.0.0': ['diabetes', 'none']  # health conditions
        })
        
        # Test demographics extraction
        demographics = loader._extract_demographics(test_df)
        assert 'eid' in demographics.columns
        assert 'f.31.0.0' in demographics.columns
        assert 'f.21003.0.0' in demographics.columns
        
        # Test cognitive extraction  
        cognitive = loader._extract_cognitive(test_df)
        assert 'f.20016.0.0' in cognitive.columns
        
        # Test health extraction
        health = loader._extract_health(test_df)
        assert 'f.20002.0.0' in health.columns

    def test_quality_calculation_edge_cases(self):
        """Test quality calculation with edge cases."""
        loader = UKBiobankUnifiedLoader()
        
        # Empty data
        quality_scores = loader.calculate_quality_scores()
        assert all(0.0 <= score <= 1.0 for score in quality_scores.values())
        
        # Only subjects
        loader.load_subjects(n_subjects=10, demo_mode=True)
        quality_scores = loader.calculate_quality_scores()
        assert quality_scores['data_completeness'] > 0
        
        # With phenotype data
        loader.load_phenotype_data(demo_mode=True)
        quality_scores = loader.calculate_quality_scores()
        assert quality_scores['phenotype_coverage'] > 0

    @patch('pandas.read_csv')
    def test_load_with_file_io_error(self, mock_read_csv):
        """Test handling of file I/O errors."""
        mock_read_csv.side_effect = IOError("File not readable")
        
        loader = UKBiobankUnifiedLoader()
        
        with pytest.raises(IOError):
            loader.load_subjects(subject_file="/nonexistent/file.csv")

    def test_modality_data_loading_empty_dir(self, tmp_path):
        """Test modality data loading with empty directory."""
        loader = UKBiobankUnifiedLoader()
        
        # Create empty modality directory
        modality_dir = tmp_path / "T1_structural"
        modality_dir.mkdir()
        
        modality_data = loader._load_modality_data(modality_dir)
        
        assert 'subjects' in modality_data
        assert 'metrics' in modality_data
        assert len(modality_data['subjects']) == 0
        assert len(modality_data['metrics']) == 0

    def test_modality_data_loading_with_summary(self, tmp_path):
        """Test modality data loading with summary file."""
        loader = UKBiobankUnifiedLoader()
        
        # Create modality directory with summary
        modality_dir = tmp_path / "T1_structural"
        modality_dir.mkdir()
        
        summary_file = modality_dir / "summary.csv"
        summary_data = "eid,volume,thickness\n1000001,600000,2.5\n1000002,580000,2.3\n"
        summary_file.write_text(summary_data)
        
        modality_data = loader._load_modality_data(modality_dir)
        
        assert len(modality_data['subjects']) == 2
        assert modality_data['subjects'] == ['1000001', '1000002']
        assert 'volume' in modality_data['metrics']
        assert 'thickness' in modality_data['metrics']


class TestUKBiobankLoaderIntegration:
    """Integration tests for UKBiobankUnifiedLoader."""
    
    def test_full_pipeline_demo_mode(self):
        """Test complete pipeline in demo mode."""
        loader = UKBiobankUnifiedLoader()
        
        # Full pipeline
        subjects = loader.load_subjects(n_subjects=20, demo_mode=True)
        phenotype_data = loader.load_phenotype_data(demo_mode=True)
        imaging_metrics = loader.load_imaging_metrics(demo_mode=True)
        genetic_markers = loader.load_genetic_markers(demo_mode=True)
        quality_scores = loader.calculate_quality_scores()
        kg_data = loader.export_to_knowledge_graph()
        stats = loader.get_statistics()
        
        # Verify pipeline completion
        assert len(subjects) == 20
        assert len(phenotype_data) == 4
        assert len(imaging_metrics) >= 3
        assert len(genetic_markers) >= 3
        assert len(quality_scores) == 5
        assert len(kg_data['nodes']) > 0
        assert stats['n_subjects'] == 20
    
    def test_incremental_loading(self):
        """Test incremental data loading."""
        loader = UKBiobankUnifiedLoader()
        
        # Load subjects first
        subjects = loader.load_subjects(n_subjects=30, demo_mode=True)
        stats1 = loader.get_statistics()
        
        # Add phenotype data
        loader.load_phenotype_data(demo_mode=True)
        stats2 = loader.get_statistics()
        
        # Add imaging data
        loader.load_imaging_metrics(demo_mode=True)
        stats3 = loader.get_statistics()
        
        # Verify incremental increases
        assert stats1['n_subjects'] == 30
        assert stats2['phenotype_fields'] > stats1['phenotype_fields']
        assert stats3['imaging_modalities'] > stats2['imaging_modalities']
    
    @pytest.mark.slow
    def test_performance_large_dataset(self):
        """Test performance with larger demo dataset."""
        loader = UKBiobankUnifiedLoader()
        
        import time
        start_time = time.time()
        
        # Load larger demo dataset
        loader.load_subjects(n_subjects=1000, demo_mode=True)
        loader.load_phenotype_data(demo_mode=True)
        
        end_time = time.time()
        execution_time = end_time - start_time
        
        # Should complete within reasonable time (adjust threshold as needed)
        assert execution_time < 30.0  # 30 seconds max
        assert len(loader.subjects) == 1000
    
    def test_data_consistency_across_modalities(self):
        """Test data consistency across different modalities."""
        loader = UKBiobankUnifiedLoader()
        
        # Load all data types
        subjects = loader.load_subjects(n_subjects=50, demo_mode=True)
        phenotype_data = loader.load_phenotype_data(demo_mode=True)
        imaging_metrics = loader.load_imaging_metrics(demo_mode=True)
        genetic_markers = loader.load_genetic_markers(demo_mode=True)
        
        # Check subject consistency in phenotype data
        for category, df in phenotype_data.items():
            if isinstance(df, pd.DataFrame) and len(df) > 0:
                phenotype_subjects = set(df['eid'].astype(str))
                assert phenotype_subjects.issubset(set(subjects))
        
        # Check subject consistency in imaging data
        for modality, data in imaging_metrics.items():
            if 'subjects' in data and len(data['subjects']) > 0:
                imaging_subjects = set(data['subjects'])
                assert imaging_subjects.issubset(set(subjects))
        
        # Check subject consistency in genetic data
        for marker_type, data in genetic_markers.items():
            if 'subjects' in data and len(data['subjects']) > 0:
                genetic_subjects = set(data['subjects'])
                assert genetic_subjects.issubset(set(subjects))
