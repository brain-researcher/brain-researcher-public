"""Unit tests for ENIGMA Consortium Unified Loader."""

import json
import os
import pytest
import numpy as np
import pandas as pd
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from brain_researcher.core.ingestion.loaders.enigma_unified import ENIGMAUnifiedLoader


class TestENIGMAUnifiedLoader:
    """Test ENIGMAUnifiedLoader class."""
    
    def test_init_default(self):
        """Test loader initialization with default parameters."""
        loader = ENIGMAUnifiedLoader()
        
        assert loader.data_dir is None
        assert loader.working_groups_dir is None
        assert loader.results_dir is None
        assert loader.cache_dir.is_dir()
        assert loader.cache_dir.name.startswith('enigma_cache')
        assert os.access(loader.cache_dir, os.W_OK)
        assert len(loader.working_groups) == 0
        assert len(loader.meta_analysis_results) == 0
        assert len(loader.brain_measures) == 0
        assert len(loader.quality_metrics) == 0
        assert len(loader.cohort_data) == 0
    
    def test_init_with_params(self, tmp_path):
        """Test loader initialization with custom parameters."""
        data_dir = tmp_path / "enigma_data"
        data_dir.mkdir()
        
        working_groups_dir = data_dir / "working_groups"
        working_groups_dir.mkdir()
        
        results_dir = data_dir / "results"
        results_dir.mkdir()
        
        cache_dir = tmp_path / "cache"
        
        loader = ENIGMAUnifiedLoader(
            data_dir=str(data_dir),
            working_groups_dir=str(working_groups_dir),
            results_dir=str(results_dir),
            cache_dir=str(cache_dir)
        )
        
        assert loader.data_dir == data_dir
        assert loader.working_groups_dir == working_groups_dir
        assert loader.results_dir == results_dir
        assert loader.cache_dir == cache_dir
        assert cache_dir.exists()
    
    def test_available_working_groups(self):
        """Test that available working groups are properly defined."""
        loader = ENIGMAUnifiedLoader()
        
        expected_groups = [
            'ENIGMA-Schizophrenia',
            'ENIGMA-Bipolar', 
            'ENIGMA-MDD',
            'ENIGMA-PTSD',
            'ENIGMA-OCD',
            'ENIGMA-ADHD',
            'ENIGMA-Autism',
            'ENIGMA-Addiction',
            'ENIGMA-Epilepsy',
            'ENIGMA-Parkinsons'
        ]
        
        assert loader.available_working_groups == expected_groups
    
    def test_brain_measures_config(self):
        """Test brain measures configuration."""
        loader = ENIGMAUnifiedLoader()
        
        # Check subcortical measures
        assert 'subcortical' in loader.brain_measures_config
        subcortical = loader.brain_measures_config['subcortical']
        assert 'thalamus' in subcortical
        assert 'hippocampus' in subcortical
        assert 'caudate' in subcortical
        
        # Check cortical measures
        assert 'cortical' in loader.brain_measures_config
        cortical = loader.brain_measures_config['cortical']
        assert 'thickness' in cortical
        assert 'surface_area' in cortical
        assert 'volume' in cortical
        
        # Check white matter measures
        assert 'white_matter' in loader.brain_measures_config
        white_matter = loader.brain_measures_config['white_matter']
        assert 'fractional_anisotropy' in white_matter
        assert 'mean_diffusivity' in white_matter
    
    def test_meta_analysis_metrics(self):
        """Test meta-analysis metrics configuration."""
        loader = ENIGMAUnifiedLoader()
        
        expected_metrics = [
            'cohens_d',
            'hedge_g',
            'standard_error',
            'confidence_interval',
            'p_value',
            'q_statistic',
            'i2_heterogeneity',
            'tau_squared'
        ]
        
        assert loader.meta_analysis_metrics == expected_metrics
    
    def test_load_working_groups_demo_mode(self):
        """Test loading working groups in demo mode."""
        loader = ENIGMAUnifiedLoader()
        
        working_groups = loader.load_working_groups(demo_mode=True)
        
        assert len(working_groups) == 5  # First 5 groups in demo
        
        # Check first working group structure
        first_group = list(working_groups.values())[0]
        assert 'disorder' in first_group
        assert 'cohorts' in first_group
        assert 'total_subjects' in first_group
        assert 'cases' in first_group
        assert 'controls' in first_group
        assert 'publications' in first_group
        
        # Check publications structure
        publications = first_group['publications']
        assert len(publications) > 0
        pub = publications[0]
        assert 'pmid' in pub
        assert 'title' in pub
        assert 'year' in pub
        assert 'journal' in pub
        assert 'citations' in pub
    
    def test_load_working_groups_specific_groups(self):
        """Test loading specific working groups."""
        loader = ENIGMAUnifiedLoader()
        
        specific_groups = ['ENIGMA-Schizophrenia', 'ENIGMA-Bipolar']
        working_groups = loader.load_working_groups(
            groups=specific_groups,
            demo_mode=True
        )
        
        assert len(working_groups) == 2
        assert 'ENIGMA-Schizophrenia' in working_groups
        assert 'ENIGMA-Bipolar' in working_groups
        assert 'ENIGMA-MDD' not in working_groups
    
    def test_load_working_groups_from_directory(self, tmp_path):
        """Test loading working groups from directory structure."""
        working_groups_dir = tmp_path / "working_groups"
        working_groups_dir.mkdir()
        
        # Create schizophrenia working group directory
        schizo_dir = working_groups_dir / "enigma_schizophrenia"
        schizo_dir.mkdir()
        
        # Create metadata file
        metadata = {
            "disorder": "Schizophrenia",
            "total_subjects": 5000,
            "data_freeze_date": "2025-01-01"
        }
        metadata_file = schizo_dir / "metadata.json"
        metadata_file.write_text(json.dumps(metadata))
        
        # Create cohorts file
        cohorts_df = pd.DataFrame({
            'cohort_name': ['COBRE', 'FBIRN', 'NUSDAST'],
            'n_subjects': [100, 200, 150],
            'site': ['UNM', 'UCI', 'NUS']
        })
        cohorts_file = schizo_dir / "cohorts.csv"
        cohorts_df.to_csv(cohorts_file, index=False)
        
        loader = ENIGMAUnifiedLoader(working_groups_dir=str(working_groups_dir))
        working_groups = loader.load_working_groups(groups=['ENIGMA-Schizophrenia'])
        
        assert 'ENIGMA-Schizophrenia' in working_groups
        group_data = working_groups['ENIGMA-Schizophrenia']
        assert group_data['disorder'] == 'Schizophrenia'
        assert group_data['total_subjects'] == 5000
        assert len(group_data['cohorts']) == 3
        assert 'COBRE' in group_data['cohorts']
    
    def test_load_meta_analysis_results_demo_mode(self):
        """Test loading meta-analysis results in demo mode."""
        loader = ENIGMAUnifiedLoader()
        loader.load_working_groups(demo_mode=True)
        
        meta_results = loader.load_meta_analysis_results(demo_mode=True)
        
        assert len(meta_results) >= 3  # First 3 working groups
        
        # Check result structure
        first_result_key = list(meta_results.keys())[0]
        first_result = meta_results[first_result_key]
        
        assert isinstance(first_result, pd.DataFrame)
        assert 'region' in first_result.columns
        assert 'cohens_d' in first_result.columns
        assert 'standard_error' in first_result.columns
        assert 'p_value' in first_result.columns
        assert 'ci_lower' in first_result.columns
        assert 'ci_upper' in first_result.columns
        
        # Check that confidence intervals are calculated
        for _, row in first_result.iterrows():
            expected_ci_lower = row['cohens_d'] - 1.96 * row['standard_error']
            expected_ci_upper = row['cohens_d'] + 1.96 * row['standard_error']
            assert abs(row['ci_lower'] - expected_ci_lower) < 1e-6
            assert abs(row['ci_upper'] - expected_ci_upper) < 1e-6
    
    def test_load_meta_analysis_results_from_files(self, tmp_path):
        """Test loading meta-analysis results from CSV files."""
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        
        # Create sample meta-analysis result file
        result_data = pd.DataFrame({
            'region': ['thalamus', 'hippocampus', 'caudate'],
            'cohens_d': [0.25, -0.15, 0.30],
            'standard_error': [0.05, 0.04, 0.06],
            'p_value': [0.001, 0.02, 0.005],
            'n_cases': [1500, 1500, 1500],
            'n_controls': [1200, 1200, 1200]
        })
        
        result_file = results_dir / "schizophrenia_subcortical.csv"
        result_data.to_csv(result_file, index=False)
        
        loader = ENIGMAUnifiedLoader(results_dir=str(results_dir))
        meta_results = loader.load_meta_analysis_results()
        
        assert 'schizophrenia_subcortical' in meta_results
        result_df = meta_results['schizophrenia_subcortical']
        
        # Check processed results
        assert 'significant' in result_df.columns
        assert 'ci_lower' in result_df.columns
        assert 'ci_upper' in result_df.columns
        
        # Check significance flags
        assert result_df.loc[result_df['region'] == 'thalamus', 'significant'].iloc[0] == True
        assert result_df.loc[result_df['region'] == 'hippocampus', 'significant'].iloc[0] == True
    
    def test_load_brain_measures_demo_mode(self):
        """Test loading brain measures in demo mode."""
        loader = ENIGMAUnifiedLoader()
        
        brain_measures = loader.load_brain_measures(demo_mode=True)
        
        assert 'subcortical' in brain_measures
        assert 'cortical' in brain_measures
        assert 'white_matter' in brain_measures
        
        # Check subcortical measures
        subcortical = brain_measures['subcortical']
        assert 'measures' in subcortical
        assert 'units' in subcortical
        assert 'normative_values' in subcortical
        
        # Check normative values structure
        normative = subcortical['normative_values']
        for measure in loader.brain_measures_config['subcortical']:
            assert measure in normative
            assert 'mean' in normative[measure]
            assert 'std' in normative[measure]
        
        # Check cortical measures
        cortical = brain_measures['cortical']
        assert 'parcellation' in cortical
        assert cortical['parcellation'] == 'Desikan-Killiany'
        
        # Check white matter measures
        white_matter = brain_measures['white_matter']
        assert 'tracts' in white_matter
        assert 'dti_parameters' in white_matter
        assert white_matter['dti_parameters']['b_value'] == 1000
    
    def test_load_brain_measures_specific_types(self):
        """Test loading specific brain measure types."""
        loader = ENIGMAUnifiedLoader()
        
        brain_measures = loader.load_brain_measures(
            measure_types=['subcortical', 'cortical'],
            demo_mode=True
        )
        
        assert 'subcortical' in brain_measures
        assert 'cortical' in brain_measures
        assert 'white_matter' not in brain_measures
    
    def test_calculate_quality_metrics(self):
        """Test quality metrics calculation."""
        loader = ENIGMAUnifiedLoader()
        loader.load_working_groups(demo_mode=True)
        loader.load_meta_analysis_results(demo_mode=True)
        
        quality_metrics = loader.calculate_quality_metrics()
        
        assert len(quality_metrics) >= 3  # At least 3 analyses
        
        # Check quality metric structure
        first_analysis = list(quality_metrics.keys())[0]
        first_metrics = quality_metrics[first_analysis]
        
        assert 'publication_bias' in first_metrics
        assert 'heterogeneity' in first_metrics
        assert 'statistical_power' in first_metrics
        assert 'data_quality' in first_metrics
        assert 'overall_quality' in first_metrics
        
        # Check score ranges
        for metric_name, score in first_metrics.items():
            assert 0.0 <= score <= 1.0, f"Metric {metric_name} out of range: {score}"
        
        # Check overall quality calculation
        expected_overall = np.mean([
            first_metrics['publication_bias'],
            first_metrics['heterogeneity'],
            first_metrics['statistical_power'],
            first_metrics['data_quality']
        ])
        assert abs(first_metrics['overall_quality'] - expected_overall) < 1e-6
    
    def test_harmonize_across_cohorts(self):
        """Test cohort harmonization."""
        loader = ENIGMAUnifiedLoader()
        loader.load_working_groups(demo_mode=True)
        
        harmonization_results = loader.harmonize_across_cohorts()
        
        assert 'cohort_mappings' in harmonization_results
        assert 'harmonized_measures' in harmonization_results
        assert 'conversion_factors' in harmonization_results
        assert 'quality_scores' in harmonization_results
        
        # Check that all working groups are processed
        working_groups = list(loader.working_groups.keys())
        for group_name in working_groups:
            assert group_name in harmonization_results['cohort_mappings']
            assert group_name in harmonization_results['harmonized_measures']
            assert group_name in harmonization_results['conversion_factors']
            assert group_name in harmonization_results['quality_scores']
        
        # Check harmonization structure
        first_group = working_groups[0]
        cohort_mapping = harmonization_results['cohort_mappings'][first_group]
        assert 'age' in cohort_mapping
        assert 'sex' in cohort_mapping
        assert 'diagnosis' in cohort_mapping
    
    def test_harmonize_specific_cohorts(self):
        """Test harmonization for specific cohorts."""
        loader = ENIGMAUnifiedLoader()
        loader.load_working_groups(demo_mode=True)
        
        # Get a cohort from the first working group
        first_group = list(loader.working_groups.values())[0]
        specific_cohorts = first_group['cohorts'][:2]  # First 2 cohorts
        
        harmonization_results = loader.harmonize_across_cohorts(cohorts=specific_cohorts)
        
        # Check that harmonization was applied
        assert len(harmonization_results['cohort_mappings']) > 0
    
    def test_link_publications(self):
        """Test publication linking."""
        loader = ENIGMAUnifiedLoader()
        loader.load_working_groups(demo_mode=True)
        
        publication_links = loader.link_publications()
        
        assert 'papers' in publication_links
        assert 'citations' in publication_links
        assert 'impact_metrics' in publication_links
        
        # Check papers structure
        papers = publication_links['papers']
        assert len(papers) > 0
        
        for paper in papers[:3]:  # Check first 3 papers
            assert 'working_group' in paper
            assert 'pmid' in paper
            assert 'title' in paper
            assert 'year' in paper
            assert 'journal' in paper
        
        # Check impact metrics
        impact = publication_links['impact_metrics']
        assert 'total_papers' in impact
        assert 'papers_per_group' in impact
        assert 'citation_count' in impact
        assert impact['total_papers'] == len(papers)
    
    def test_link_specific_publications(self):
        """Test linking specific publications by PubMed ID."""
        loader = ENIGMAUnifiedLoader()
        loader.load_working_groups(demo_mode=True)
        
        # Get a PMID from the loaded data
        first_group = list(loader.working_groups.values())[0]
        test_pmid = first_group['publications'][0]['pmid']
        
        publication_links = loader.link_publications(pubmed_ids=[test_pmid])
        
        # Should only return the specific publication
        papers = publication_links['papers']
        assert len(papers) == 1
        assert papers[0]['pmid'] == test_pmid
    
    def test_export_to_knowledge_graph(self):
        """Test knowledge graph export."""
        loader = ENIGMAUnifiedLoader()
        loader.load_working_groups(demo_mode=True)
        loader.load_brain_measures(demo_mode=True)
        
        kg_data = loader.export_to_knowledge_graph()
        
        assert 'nodes' in kg_data
        assert 'edges' in kg_data
        assert 'metadata' in kg_data
        
        # Check metadata
        metadata = kg_data['metadata']
        assert metadata['source'] == 'ENIGMA_Consortium'
        assert metadata['version'] == '2024.1'
        assert metadata['n_working_groups'] == len(loader.working_groups)
        assert 'timestamp' in metadata
        
        # Check nodes
        nodes = kg_data['nodes']
        assert len(nodes) > 0
        
        # Check working group nodes
        working_group_nodes = [n for n in nodes if n['type'] == 'WorkingGroup']
        assert len(working_group_nodes) == len(loader.working_groups)
        
        # Check cohort nodes
        cohort_nodes = [n for n in nodes if n['type'] == 'Cohort']
        assert len(cohort_nodes) > 0
        
        # Check brain measure nodes
        measure_nodes = [n for n in nodes if n['type'] == 'BrainMeasure']
        assert len(measure_nodes) > 0
        
        # Check edges
        edges = kg_data['edges']
        assert len(edges) > 0
        
        # Check edge structure
        for edge in edges[:3]:  # Check first 3 edges
            assert 'source' in edge
            assert 'target' in edge
            assert 'type' in edge
    
    def test_get_statistics(self):
        """Test statistics generation."""
        loader = ENIGMAUnifiedLoader()
        loader.load_working_groups(demo_mode=True)
        loader.load_meta_analysis_results(demo_mode=True)
        loader.load_brain_measures(demo_mode=True)
        loader.calculate_quality_metrics()
        
        stats = loader.get_statistics()
        
        assert 'n_working_groups' in stats
        assert 'n_cohorts' in stats
        assert 'n_subjects' in stats
        assert 'n_brain_measures' in stats
        assert 'n_meta_analyses' in stats
        assert 'disorders_studied' in stats
        assert 'quality_summary' in stats
        
        # Check values
        assert stats['n_working_groups'] == len(loader.working_groups)
        assert stats['n_meta_analyses'] == len(loader.meta_analysis_results)
        
        # Check disorders list
        disorders = stats['disorders_studied']
        assert len(disorders) > 0
        assert all(isinstance(d, str) for d in disorders)
        
        # Check quality summary
        quality_summary = stats['quality_summary']
        assert 'mean_quality' in quality_summary
        assert 'analyses_with_high_quality' in quality_summary
        assert 0.0 <= quality_summary['mean_quality'] <= 1.0
    
    def test_process_meta_analysis_missing_columns(self):
        """Test meta-analysis processing with missing required columns."""
        loader = ENIGMAUnifiedLoader()
        
        # Create dataframe missing required columns
        incomplete_df = pd.DataFrame({
            'region': ['thalamus', 'hippocampus'],
            'effect_size': [0.25, -0.15]  # Missing cohens_d, standard_error, p_value
        })
        
        # Should add missing columns with NaN
        processed_df = loader._process_meta_analysis(incomplete_df)
        
        assert 'cohens_d' in processed_df.columns
        assert 'standard_error' in processed_df.columns
        assert 'p_value' in processed_df.columns
        assert 'significant' in processed_df.columns
        
        # Missing columns should be NaN
        assert processed_df['cohens_d'].isna().all()
    
    def test_assess_publication_bias(self):
        """Test publication bias assessment."""
        loader = ENIGMAUnifiedLoader()
        
        # Create results with correlation between effect size and SE (bias indicator)
        biased_results = pd.DataFrame({
            'cohens_d': [0.1, 0.2, 0.3, 0.4, 0.5],
            'standard_error': [0.02, 0.04, 0.06, 0.08, 0.10]  # Correlated with effect size
        })
        
        bias_score = loader._assess_publication_bias(biased_results)
        assert 0.0 <= bias_score <= 1.0
        
        # Create results without correlation (less biased)
        unbiased_results = pd.DataFrame({
            'cohens_d': [0.1, 0.5, 0.2, 0.4, 0.3],
            'standard_error': [0.10, 0.02, 0.08, 0.04, 0.06]  # Random order
        })
        
        unbiased_score = loader._assess_publication_bias(unbiased_results)
        assert unbiased_score >= bias_score  # Should be less biased
    
    def test_assess_heterogeneity(self):
        """Test heterogeneity assessment."""
        loader = ENIGMAUnifiedLoader()
        
        # Low heterogeneity
        low_het_results = pd.DataFrame({
            'i2_heterogeneity': [10, 15, 20, 18, 12]
        })
        low_het_score = loader._assess_heterogeneity(low_het_results)
        assert low_het_score == 1.0
        
        # Moderate heterogeneity
        mod_het_results = pd.DataFrame({
            'i2_heterogeneity': [40, 50, 60, 45, 55]
        })
        mod_het_score = loader._assess_heterogeneity(mod_het_results)
        assert mod_het_score == 0.5
        
        # High heterogeneity
        high_het_results = pd.DataFrame({
            'i2_heterogeneity': [80, 85, 90, 88, 92]
        })
        high_het_score = loader._assess_heterogeneity(high_het_results)
        assert high_het_score == 0.2
    
    def test_calculate_statistical_power(self):
        """Test statistical power calculation."""
        loader = ENIGMAUnifiedLoader()
        
        # Large sample size (high power)
        large_sample = pd.DataFrame({
            'n_cases': [5000, 4000, 6000],
            'n_controls': [4000, 3000, 5000]
        })
        high_power = loader._calculate_statistical_power(large_sample)
        assert high_power == 0.95
        
        # Medium sample size
        medium_sample = pd.DataFrame({
            'n_cases': [1500, 1000, 2000],
            'n_controls': [1000, 800, 1200]
        })
        medium_power = loader._calculate_statistical_power(medium_sample)
        assert medium_power == 0.85
        
        # Small sample size (low power)
        small_sample = pd.DataFrame({
            'n_cases': [100, 200, 150],
            'n_controls': [80, 120, 100]
        })
        low_power = loader._calculate_statistical_power(small_sample)
        assert low_power == 0.50
    
    def test_assess_data_quality(self):
        """Test data quality assessment."""
        loader = ENIGMAUnifiedLoader()
        
        # High quality data (complete, no outliers)
        high_quality_data = pd.DataFrame({
            'cohens_d': [0.2, 0.25, 0.18, 0.22, 0.28],
            'standard_error': [0.05, 0.06, 0.04, 0.05, 0.07],
            'p_value': [0.01, 0.005, 0.02, 0.008, 0.003]
        })
        
        high_quality_score = loader._assess_data_quality(high_quality_data)
        assert high_quality_score > 0.7
        
        # Lower quality data (missing values, outliers)
        low_quality_data = pd.DataFrame({
            'cohens_d': [0.2, np.nan, 5.0, 0.22, np.nan],  # Missing values and outlier
            'standard_error': [0.05, 0.06, 0.04, np.nan, 0.07],
            'p_value': [0.01, 0.005, 0.02, 0.008, np.nan]
        })
        
        low_quality_score = loader._assess_data_quality(low_quality_data)
        assert low_quality_score < high_quality_score
    
    def test_get_modality_for_measure(self):
        """Test modality mapping for measure types."""
        loader = ENIGMAUnifiedLoader()
        
        assert loader._get_modality_for_measure('subcortical') == 'T1-weighted MRI'
        assert loader._get_modality_for_measure('cortical') == 'T1-weighted MRI'
        assert loader._get_modality_for_measure('white_matter') == 'Diffusion MRI'
        assert loader._get_modality_for_measure('unknown_measure') == 'Unknown'
    
    def test_error_handling_missing_working_groups_dir(self):
        """Test error handling for missing working groups directory."""
        loader = ENIGMAUnifiedLoader()
        
        with pytest.raises(ValueError, match="Working groups directory not found"):
            loader.load_working_groups()
    
    def test_error_handling_missing_results_dir(self):
        """Test error handling for missing results directory."""
        loader = ENIGMAUnifiedLoader()
        
        with pytest.raises(ValueError, match="Results directory not found"):
            loader.load_meta_analysis_results()
    
    def test_cache_directory_creation(self, tmp_path):
        """Test that cache directory is created if it doesn't exist."""
        cache_dir = tmp_path / "enigma_cache"
        assert not cache_dir.exists()
        
        loader = ENIGMAUnifiedLoader(cache_dir=str(cache_dir))
        
        assert cache_dir.exists()
        assert cache_dir.is_dir()
    
    def test_demo_data_reproducibility(self):
        """Test that demo data generation is reproducible."""
        loader1 = ENIGMAUnifiedLoader()
        loader2 = ENIGMAUnifiedLoader()
        
        # Load same demo data
        groups1 = loader1.load_working_groups(demo_mode=True)
        groups2 = loader2.load_working_groups(demo_mode=True)
        
        assert len(groups1) == len(groups2)
        
        # Check first working group data consistency
        first_group_name = list(groups1.keys())[0]
        group1_data = groups1[first_group_name]
        group2_data = groups2[first_group_name]
        
        assert group1_data['disorder'] == group2_data['disorder']
        assert group1_data['total_subjects'] == group2_data['total_subjects']
        assert len(group1_data['cohorts']) == len(group2_data['cohorts'])
    
    def test_load_working_group_data_empty_dir(self, tmp_path):
        """Test loading working group data from empty directory."""
        loader = ENIGMAUnifiedLoader()
        
        empty_dir = tmp_path / "empty_group"
        empty_dir.mkdir()
        
        group_data = loader._load_working_group_data(empty_dir)
        
        # Should return empty dict for empty directory
        assert isinstance(group_data, dict)
        assert len(group_data) == 0


class TestENIGMALoaderIntegration:
    """Integration tests for ENIGMAUnifiedLoader."""
    
    def test_full_pipeline_demo_mode(self):
        """Test complete pipeline in demo mode."""
        loader = ENIGMAUnifiedLoader()
        
        # Full pipeline
        working_groups = loader.load_working_groups(demo_mode=True)
        meta_results = loader.load_meta_analysis_results(demo_mode=True)
        brain_measures = loader.load_brain_measures(demo_mode=True)
        quality_metrics = loader.calculate_quality_metrics()
        harmonization = loader.harmonize_across_cohorts()
        publications = loader.link_publications()
        kg_data = loader.export_to_knowledge_graph()
        stats = loader.get_statistics()
        
        # Verify pipeline completion
        assert len(working_groups) == 5
        assert len(meta_results) >= 3
        assert len(brain_measures) == 3
        assert len(quality_metrics) >= 3
        assert len(harmonization['cohort_mappings']) == len(working_groups)
        assert len(publications['papers']) > 0
        assert len(kg_data['nodes']) > 0
        assert stats['n_working_groups'] == 5
    
    def test_incremental_loading(self):
        """Test incremental data loading."""
        loader = ENIGMAUnifiedLoader()
        
        # Load working groups first
        working_groups = loader.load_working_groups(demo_mode=True)
        stats1 = loader.get_statistics()
        
        # Add meta-analysis results
        loader.load_meta_analysis_results(demo_mode=True)
        stats2 = loader.get_statistics()
        
        # Add brain measures
        loader.load_brain_measures(demo_mode=True)
        stats3 = loader.get_statistics()
        
        # Verify incremental increases
        assert stats1['n_working_groups'] == 5
        assert stats2['n_meta_analyses'] > stats1['n_meta_analyses']
        assert stats3['n_brain_measures'] > stats2['n_brain_measures']
    
    def test_data_consistency_across_components(self):
        """Test data consistency across different components."""
        loader = ENIGMAUnifiedLoader()
        
        # Load all data types
        working_groups = loader.load_working_groups(demo_mode=True)
        meta_results = loader.load_meta_analysis_results(demo_mode=True)
        brain_measures = loader.load_brain_measures(demo_mode=True)
        
        # Check consistency between working groups and meta-analysis results
        working_group_names = set(working_groups.keys())
        meta_result_groups = set()
        for result_name in meta_results.keys():
            # Extract working group name from result name (e.g., "ENIGMA-Schizophrenia_subcortical")
            group_part = result_name.split('_')[0]
            # Convert to match working group format
            if 'enigma' in group_part.lower():
                meta_result_groups.add(group_part.replace('enigma', 'ENIGMA'))
        
        # Meta-analysis results should be based on loaded working groups
        for result_group in meta_result_groups:
            if result_group in loader.available_working_groups:
                assert result_group in working_group_names
        
        # Check brain measures consistency
        for measure_type in brain_measures:
            assert measure_type in loader.brain_measures_config
    
    def test_quality_metrics_consistency(self):
        """Test consistency of quality metrics calculation."""
        loader = ENIGMAUnifiedLoader()
        loader.load_working_groups(demo_mode=True)
        loader.load_meta_analysis_results(demo_mode=True)
        
        quality_metrics = loader.calculate_quality_metrics()
        
        # All meta-analysis results should have quality metrics
        for result_name in loader.meta_analysis_results.keys():
            assert result_name in quality_metrics
            
            metrics = quality_metrics[result_name]
            # All individual metrics should contribute to overall quality
            assert 0.0 <= metrics['overall_quality'] <= 1.0
            
            # Overall quality should be reasonable given individual metrics
            individual_scores = [
                metrics['publication_bias'],
                metrics['heterogeneity'],
                metrics['statistical_power'],
                metrics['data_quality']
            ]
            expected_overall = np.mean(individual_scores)
            assert abs(metrics['overall_quality'] - expected_overall) < 1e-6
    
    @pytest.mark.slow
    def test_performance_large_dataset(self):
        """Test performance with larger demo dataset."""
        loader = ENIGMAUnifiedLoader()
        
        import time
        start_time = time.time()
        
        # Load all available working groups (not limited to 5)
        loader.available_working_groups = loader.available_working_groups  # All 10 groups
        working_groups = loader.load_working_groups(demo_mode=True)
        meta_results = loader.load_meta_analysis_results(demo_mode=True)
        
        end_time = time.time()
        execution_time = end_time - start_time
        
        # Should complete within reasonable time
        assert execution_time < 60.0  # 60 seconds max for all groups
        assert len(working_groups) >= 5
    
    def test_harmonization_consistency(self):
        """Test harmonization consistency across cohorts."""
        loader = ENIGMAUnifiedLoader()
        loader.load_working_groups(demo_mode=True)
        
        harmonization_results = loader.harmonize_across_cohorts()
        
        # Check that harmonization is applied consistently
        for group_name, cohort_measures in harmonization_results['harmonized_measures'].items():
            for cohort_name, measures in cohort_measures.items():
                assert 'scaling_factor' in measures
                assert 'offset' in measures
                assert 'harmonization_method' in measures
                
                # Scaling factor should be reasonable
                assert 0.5 <= measures['scaling_factor'] <= 1.5
                # Offset should be small
                assert -0.5 <= measures['offset'] <= 0.5
