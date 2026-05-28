"""Integration tests for the complete Data Integration Pipeline."""

import pytest
import pandas as pd
import numpy as np
import json
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from brain_researcher.core.ingestion.updates.conflict_resolver import (
    ConflictResolver, ConflictType, ResolutionStrategy
)
from brain_researcher.core.ingestion.quality.quality_scorer import (
    QualityScorer, QualityDimension
)
from brain_researcher.core.ingestion.export.pipeline import (
    DataExportPipeline, ExportFormat, CompressionType
)
from brain_researcher.core.ingestion.harmonization.schema_mapper import (
    SchemaMapper, FieldMapping
)
from brain_researcher.core.ingestion.archival.archiver import (
    DataArchiver, ArchiveStatus, CompressionLevel
)


@pytest.fixture
def temp_workspace():
    """Create temporary workspace for integration tests."""
    workspace = tempfile.mkdtemp()
    
    workspace_path = Path(workspace)
    
    # Create subdirectories
    dirs = {
        'data': workspace_path / 'data',
        'exports': workspace_path / 'exports', 
        'archives': workspace_path / 'archives',
        'staging': workspace_path / 'staging',
        'quality_reports': workspace_path / 'quality_reports'
    }
    
    for dir_path in dirs.values():
        dir_path.mkdir(parents=True, exist_ok=True)
    
    yield dirs
    
    # Cleanup
    shutil.rmtree(workspace, ignore_errors=True)


@pytest.fixture
def sample_datasets(temp_workspace):
    """Create sample datasets with different schemas for integration testing."""
    datasets = {}
    
    # HCP-style dataset
    hcp_data = pd.DataFrame({
        'Subject': ['100001', '100002', '100003', '100004'],
        'Age_in_Yrs': [22.5, 25.3, 28.1, 31.7],
        'Gender': ['M', 'F', 'M', 'F'],
        'Handedness': ['R', 'L', 'R', 'R'],
        'Total_Gray_Vol': [807245, 823456, 798123, 834567],
        'FS_IntraCranial_Vol': [1579289, 1634521, 1598432, 1687543]
    })
    
    hcp_path = temp_workspace['data'] / 'hcp_dataset.csv'
    hcp_data.to_csv(hcp_path, index=False)
    datasets['HCP'] = {
        'path': str(hcp_path),
        'data': hcp_data,
        'format': 'csv',
        'schema_type': 'HCP'
    }
    
    # ABCD-style dataset 
    abcd_data = pd.DataFrame({
        'subjectkey': ['NDAR_001', 'NDAR_002', 'NDAR_003', 'NDAR_004'],
        'interview_age': [264, 300, 336, 372],  # Age in months
        'sex': ['M', 'F', 'M', 'F'],
        'eventname': ['baseline_year_1_arm_1'] * 4,
        'mri_info_manufacturer': ['Siemens', 'GE', 'Siemens', 'Philips'],
        'smri_vol_cdk_total': [1205000, 1234000, 1198000, 1267000]
    })
    
    abcd_path = temp_workspace['data'] / 'abcd_dataset.csv'
    abcd_data.to_csv(abcd_path, index=False)
    datasets['ABCD'] = {
        'path': str(abcd_path),
        'data': abcd_data,
        'format': 'csv',
        'schema_type': 'ABCD'
    }
    
    # BIDS-style dataset
    bids_data = pd.DataFrame({
        'participant_id': ['sub-001', 'sub-002', 'sub-003', 'sub-004'],
        'age': [25, 30, 35, 28],
        'sex': ['M', 'F', 'M', 'F'],
        'handedness': ['right', 'left', 'right', 'right'],
        'group': ['control', 'patient', 'control', 'patient']
    })
    
    bids_path = temp_workspace['data'] / 'bids_dataset.csv'
    bids_data.to_csv(bids_path, index=False)
    datasets['BIDS'] = {
        'path': str(bids_path),
        'data': bids_data,
        'format': 'csv',
        'schema_type': 'BIDS'
    }
    
    return datasets


class TestDataIntegrationPipeline:
    """Integration tests for the complete data integration pipeline."""
    
    def test_complete_data_integration_workflow(self, temp_workspace, sample_datasets):
        """Test complete workflow from ingestion to archival."""
        
        # Initialize all components
        conflict_resolver = ConflictResolver(
            default_strategy=ResolutionStrategy.USE_QUALITY_SCORE,
            quality_threshold=0.7
        )
        
        quality_scorer = QualityScorer()
        
        schema_mapper = SchemaMapper()
        
        export_pipeline = DataExportPipeline(
            output_dir=str(temp_workspace['exports']),
            compression=CompressionType.GZIP
        )
        
        archiver = DataArchiver(
            archive_dir=str(temp_workspace['archives']),
            staging_dir=str(temp_workspace['staging']),
            db_path=str(temp_workspace['archives'] / 'catalog.db')
        )
        
        # Step 1: Quality Assessment
        print("Step 1: Quality Assessment")
        quality_reports = {}
        
        for dataset_name, dataset_info in sample_datasets.items():
            report = quality_scorer.score_dataset(
                dataset_info['path'],
                dataset_type='neuroimaging',
                include_details=True
            )
            
            quality_reports[dataset_name] = report
            
            # Verify quality assessment
            assert report['overall_score'] > 0.0
            assert report['quality_level'] in ['excellent', 'good', 'acceptable', 'poor', 'unacceptable']
            assert len(report['dimension_scores']) == 8  # All quality dimensions
            
            print(f"  {dataset_name}: {report['overall_score']:.2f} ({report['quality_level']})")
        
        # Step 2: Schema Harmonization
        print("Step 2: Schema Harmonization")
        
        # Load datasets for harmonization
        loaded_datasets = {}
        for name, info in sample_datasets.items():
            loaded_datasets[name] = pd.read_csv(info['path'])
        
        # Harmonize field names
        harmonized_datasets = schema_mapper.harmonize_field_names(loaded_datasets)
        
        # Verify harmonization
        assert len(harmonized_datasets) == len(loaded_datasets)
        for name, data in harmonized_datasets.items():
            assert isinstance(data, pd.DataFrame)
            assert len(data) == len(loaded_datasets[name])  # Same number of rows
        
        # Map each dataset to BIDS format
        bids_mappings = {}
        for dataset_name, dataset_info in sample_datasets.items():
            if dataset_name != 'BIDS':  # Skip BIDS as it's already in BIDS format
                source_schema = {
                    col: {'type': str(loaded_datasets[dataset_name][col].dtype)}
                    for col in loaded_datasets[dataset_name].columns
                }
                
                mappings = schema_mapper.map_schemas(source_schema, 'BIDS')
                bids_mappings[dataset_name] = mappings
                
                print(f"  {dataset_name}: {len(mappings)} fields mapped to BIDS")
        
        # Step 3: Conflict Resolution (simulate incremental updates)
        print("Step 3: Conflict Resolution")
        
        # Simulate a scenario where we have local HCP data and receive updated HCP data
        local_hcp = loaded_datasets['HCP'].iloc[:3].copy()  # First 3 subjects
        updated_hcp = loaded_datasets['HCP'].iloc[1:4].copy()  # Subjects 2-4, overlapping with local
        
        # Modify some values to create conflicts
        updated_hcp.loc[updated_hcp.index[0], 'Age_in_Yrs'] = 25.5  # Changed age for subject 2
        updated_hcp.loc[updated_hcp.index[0], 'Total_Gray_Vol'] = 825000  # Changed volume
        
        # Convert to dictionaries for conflict resolution
        local_records = local_hcp.to_dict('records')
        updated_records = updated_hcp.to_dict('records')
        
        # Find overlapping subjects and resolve conflicts
        resolved_data = []
        for updated_record in updated_records:
            subject_id = updated_record['Subject']
            
            # Find matching local record
            local_record = None
            for lr in local_records:
                if lr['Subject'] == subject_id:
                    local_record = lr
                    break
            
            if local_record:
                # Resolve conflicts
                conflicts = conflict_resolver.detect_conflicts(local_record, updated_record)
                if conflicts:
                    resolution_results = conflict_resolver.resolve_conflicts(
                        conflicts, 
                        ResolutionStrategy.KEEP_NEWEST
                    )
                    merged_record = conflict_resolver.merge_data(
                        local_record,
                        updated_record, 
                        resolution_results
                    )
                    resolved_data.append(merged_record)
                    print(f"  Resolved {len(conflicts)} conflicts for subject {subject_id}")
                else:
                    resolved_data.append(updated_record)
            else:
                # New subject
                resolved_data.append(updated_record)
        
        # Add non-overlapping local subjects
        for local_record in local_records:
            if not any(ur['Subject'] == local_record['Subject'] for ur in updated_records):
                resolved_data.append(local_record)
        
        # Convert back to DataFrame
        resolved_df = pd.DataFrame(resolved_data)
        
        # Verify conflict resolution
        assert len(resolved_df) >= 3  # Should have at least 3 subjects
        print(f"  Final dataset has {len(resolved_df)} subjects after conflict resolution")
        
        # Step 4: Data Export
        print("Step 4: Data Export")
        
        # Save resolved data for export
        resolved_path = temp_workspace['data'] / 'resolved_hcp.csv'
        resolved_df.to_csv(resolved_path, index=False)
        
        # Export to multiple formats
        export_formats = [ExportFormat.JSON, ExportFormat.PARQUET, ExportFormat.BIDS]
        export_results = {}
        
        for format_type in export_formats:
            result = export_pipeline.export_dataset(
                str(resolved_path),
                format_type,
                output_name=f"integrated_data_{format_type}",
                compression=CompressionType.GZIP
            )
            
            export_results[format_type] = result
            
            # Verify export
            assert result['status'] == 'success'
            assert Path(result['output_path']).exists()
            
            # Validate export
            is_valid = export_pipeline.validate_export(
                result['output_path'],
                format_type
            )
            assert is_valid is True
            
            print(f"  Exported to {format_type}: {result['size_bytes']} bytes")
        
        # Step 5: Quality Re-assessment
        print("Step 5: Quality Re-assessment") 
        
        final_quality_report = quality_scorer.score_dataset(
            str(resolved_path),
            dataset_type='neuroimaging',
            include_details=True
        )
        
        # Verify final quality
        assert final_quality_report['overall_score'] > 0.0
        print(f"  Final quality score: {final_quality_report['overall_score']:.2f}")
        
        # Compare with original quality
        original_hcp_quality = quality_reports['HCP']['overall_score']
        quality_change = final_quality_report['overall_score'] - original_hcp_quality
        print(f"  Quality change: {quality_change:+.2f}")
        
        # Step 6: Archival
        print("Step 6: Archival")
        
        # Archive the final integrated dataset
        archive_result = archiver.archive_dataset(
            str(resolved_path),
            dataset_name="Integrated HCP Dataset",
            retention_days=365,
            compression=CompressionLevel.BALANCED,
            metadata={
                "integration_date": datetime.now().isoformat(),
                "source_datasets": ["HCP"],
                "conflicts_resolved": len(conflicts) if conflicts else 0,
                "final_quality_score": final_quality_report['overall_score']
            }
        )
        
        # Verify archival
        assert archive_result['status'] == ArchiveStatus.ARCHIVED.value
        assert Path(archive_result['archive_path']).exists()
        
        print(f"  Archived dataset: {archive_result['archive_id']}")
        print(f"  Archive size: {archive_result['size_bytes']} bytes")
        print(f"  Compression ratio: {archive_result['compression_ratio']:.2f}")
        
        # Step 7: Verification and Retrieval
        print("Step 7: Verification and Retrieval")
        
        # Verify archive in catalog
        all_archives = archiver.list_archives()
        our_archive = next(
            (a for a in all_archives if a['archive_id'] == archive_result['archive_id']),
            None
        )
        assert our_archive is not None
        assert our_archive['dataset_name'] == "Integrated HCP Dataset"
        
        # Test retrieval
        restore_path = temp_workspace['staging'] / 'retrieved_data'
        retrieval_result = archiver.retrieve_archive(
            archive_result['archive_id'],
            restore_path=str(restore_path),
            user="integration_test"
        )
        
        # Verify retrieval
        assert restore_path.exists()
        retrieved_files = list(restore_path.rglob('*'))
        assert len(retrieved_files) > 0
        
        print(f"  Retrieved {len(retrieved_files)} files/directories")
        
        # Get final statistics
        export_history = export_pipeline.get_export_history()
        storage_stats = archiver.get_storage_stats()
        conflict_stats = conflict_resolver.get_conflict_statistics()
        
        print("\nPipeline Summary:")
        print(f"  Datasets processed: {len(sample_datasets)}")
        print(f"  Exports created: {len(export_history)}")
        print(f"  Archives created: {storage_stats['total_archives']}")
        print(f"  Conflicts resolved: {conflict_stats['resolved_automatically']}")
        print(f"  Total storage used: {storage_stats['total_size_gb']:.2f} GB")
    
    def test_multi_dataset_harmonization_workflow(self, temp_workspace, sample_datasets):
        """Test harmonization workflow across multiple different datasets."""
        
        # Initialize components
        schema_mapper = SchemaMapper()
        quality_scorer = QualityScorer()
        export_pipeline = DataExportPipeline(output_dir=str(temp_workspace['exports']))
        
        # Load all datasets
        loaded_datasets = {}
        for name, info in sample_datasets.items():
            loaded_datasets[name] = pd.read_csv(info['path'])
        
        print(f"Loaded {len(loaded_datasets)} datasets for harmonization")
        
        # Step 1: Individual quality assessment
        individual_quality = {}
        for name, data in loaded_datasets.items():
            # Save temporarily for quality assessment
            temp_path = temp_workspace['data'] / f"temp_{name}.csv"
            data.to_csv(temp_path, index=False)
            
            quality_report = quality_scorer.score_dataset(str(temp_path))
            individual_quality[name] = quality_report['overall_score']
            
            temp_path.unlink()  # Cleanup
        
        print("Individual quality scores:", individual_quality)
        
        # Step 2: Schema mapping and compatibility analysis
        dataset_schemas = {}
        for name, data in loaded_datasets.items():
            schema = {col: {'type': str(data[col].dtype)} for col in data.columns}
            dataset_schemas[name] = schema
        
        # Create mapping profile
        dataset_names = list(loaded_datasets.keys())
        mapping_profile = schema_mapper.create_mapping_profile(dataset_names)
        
        # Verify compatibility analysis
        assert 'compatibility_matrix' in mapping_profile
        assert 'common_fields' in mapping_profile
        assert 'mapping_quality' in mapping_profile
        
        print(f"Common fields across all datasets: {mapping_profile['common_fields']}")
        
        # Step 3: Map all datasets to BIDS format
        bids_datasets = {}
        mapping_validations = {}
        
        for name, data in loaded_datasets.items():
            if name == 'BIDS':
                # Already in BIDS format
                bids_datasets[name] = data.copy()
                continue
            
            # Map schema to BIDS
            source_schema = dataset_schemas[name]
            mappings = schema_mapper.map_schemas(source_schema, 'BIDS')
            
            # Validate mappings
            validation = schema_mapper.validate_mapping(mappings, data)
            mapping_validations[name] = validation
            
            # Apply mappings
            if mappings:
                bids_data = schema_mapper.apply_mappings(data, mappings)
                bids_datasets[name] = bids_data
                
                print(f"{name}: {len(mappings)} mappings, {validation['coverage']:.1%} coverage")
        
        # Step 4: Harmonize field names across converted datasets
        harmonized_datasets = schema_mapper.harmonize_field_names(bids_datasets)
        
        # Verify harmonization improved compatibility
        harmonized_columns = set()
        for data in harmonized_datasets.values():
            harmonized_columns.update(data.columns)
        
        print(f"Total unique columns after harmonization: {len(harmonized_columns)}")
        
        # Step 5: Create merged dataset
        common_columns = None
        for name, data in harmonized_datasets.items():
            if common_columns is None:
                common_columns = set(data.columns)
            else:
                common_columns &= set(data.columns)
        
        if common_columns:
            print(f"Merging on {len(common_columns)} common columns: {common_columns}")
            
            merged_data = pd.DataFrame()
            for name, data in harmonized_datasets.items():
                # Add dataset source identifier
                data_subset = data[list(common_columns)].copy()
                data_subset['dataset_source'] = name
                
                merged_data = pd.concat([merged_data, data_subset], ignore_index=True)
            
            # Save merged dataset
            merged_path = temp_workspace['data'] / 'merged_harmonized.csv'
            merged_data.to_csv(merged_path, index=False)
            
            print(f"Created merged dataset with {len(merged_data)} total subjects")
            
            # Step 6: Quality assessment of merged dataset
            merged_quality = quality_scorer.score_dataset(str(merged_path))
            print(f"Merged dataset quality: {merged_quality['overall_score']:.2f}")
            
            # Step 7: Export harmonized data
            export_result = export_pipeline.export_dataset(
                str(merged_path),
                ExportFormat.PARQUET,
                output_name="harmonized_multi_dataset"
            )
            
            assert export_result['status'] == 'success'
            print(f"Exported harmonized dataset: {export_result['size_bytes']} bytes")
        
        # Verify workflow completed successfully
        assert len(harmonized_datasets) == len(loaded_datasets)
        assert all(isinstance(data, pd.DataFrame) for data in harmonized_datasets.values())
    
    def test_data_quality_improvement_pipeline(self, temp_workspace, sample_datasets):
        """Test pipeline for iterative data quality improvement."""
        
        # Initialize components
        quality_scorer = QualityScorer()
        conflict_resolver = ConflictResolver()
        
        # Create a dataset with various quality issues
        problematic_data = pd.DataFrame({
            'participant_id': ['sub-001', 'sub-002', 'sub-003', 'SUB004', ''],  # Inconsistent format
            'age': [25, 'thirty', -5, 300, None],  # Mixed types, invalid values
            'sex': ['M', 'Female', '1', 'Male', 'unknown'],  # Inconsistent coding
            'handedness': ['right', 'LEFT', 'R', 'ambidextrous', None],  # Mixed formats
            'score': [85.5, 92.0, None, 95.2, 78.3],  # Missing values
            'duplicate_id': [1, 1, 2, 3, 4]  # Duplicate values
        })
        
        problematic_path = temp_workspace['data'] / 'problematic_dataset.csv'
        problematic_data.to_csv(problematic_path, index=False)
        
        print("Starting data quality improvement pipeline")
        
        # Step 1: Initial quality assessment
        initial_quality = quality_scorer.score_dataset(str(problematic_path), include_details=True)
        
        print(f"Initial quality score: {initial_quality['overall_score']:.2f}")
        print(f"Initial quality level: {initial_quality['quality_level']}")
        print("Weaknesses:", initial_quality['details']['weaknesses'])
        print("Recommendations:", initial_quality['recommendations'])
        
        # Step 2: Data cleaning and standardization
        cleaned_data = problematic_data.copy()
        
        # Clean participant IDs
        cleaned_data['participant_id'] = cleaned_data['participant_id'].apply(
            lambda x: f"sub-{x.replace('SUB', '').replace('sub-', '').zfill(3)}" 
            if pd.notna(x) and x != '' else 'sub-000'
        )
        
        # Clean age data
        def clean_age(age_value):
            if pd.isna(age_value):
                return None
            if isinstance(age_value, str):
                if 'thirty' in age_value.lower():
                    return 30
                return None
            if age_value < 0 or age_value > 120:
                return None
            return age_value
        
        cleaned_data['age'] = cleaned_data['age'].apply(clean_age)
        
        # Standardize sex coding
        sex_mapping = {
            'M': 'M', 'Male': 'M', '1': 'M',
            'F': 'F', 'Female': 'F', '2': 'F',
            'unknown': None
        }
        cleaned_data['sex'] = cleaned_data['sex'].map(sex_mapping)
        
        # Standardize handedness
        def clean_handedness(hand_value):
            if pd.isna(hand_value):
                return None
            hand_lower = str(hand_value).lower()
            if hand_lower in ['right', 'r']:
                return 'right'
            elif hand_lower in ['left', 'l']:
                return 'left'
            elif hand_lower == 'ambidextrous':
                return 'ambidextrous'
            return None
        
        cleaned_data['handedness'] = cleaned_data['handedness'].apply(clean_handedness)
        
        # Handle duplicates
        cleaned_data = cleaned_data.drop_duplicates(subset=['duplicate_id'], keep='first')
        
        # Save cleaned data
        cleaned_path = temp_workspace['data'] / 'cleaned_dataset.csv'
        cleaned_data.to_csv(cleaned_path, index=False)
        
        # Step 3: Re-assess quality after cleaning
        cleaned_quality = quality_scorer.score_dataset(str(cleaned_path), include_details=True)
        
        quality_improvement = cleaned_quality['overall_score'] - initial_quality['overall_score']
        
        print(f"Cleaned quality score: {cleaned_quality['overall_score']:.2f}")
        print(f"Quality improvement: {quality_improvement:+.2f}")
        print(f"New quality level: {cleaned_quality['quality_level']}")
        
        # Step 4: Simulate data enrichment through conflict resolution
        # Create "enhanced" version with additional information
        enhanced_data = cleaned_data.copy()
        enhanced_data.loc[0, 'age'] = 26  # Updated age
        enhanced_data.loc[0, 'score'] = 87.0  # Updated score
        enhanced_data['study_site'] = ['Site_A', 'Site_B', 'Site_A', 'Site_C', 'Site_B']  # New field
        
        # Resolve conflicts between cleaned and enhanced versions
        records_to_resolve = []
        for idx in range(min(len(cleaned_data), len(enhanced_data))):
            if idx < len(cleaned_data) and idx < len(enhanced_data):
                local_record = cleaned_data.iloc[idx].to_dict()
                remote_record = enhanced_data.iloc[idx].to_dict()
                
                conflicts = conflict_resolver.detect_conflicts(local_record, remote_record)
                if conflicts:
                    resolution_results = conflict_resolver.resolve_conflicts(
                        conflicts, ResolutionStrategy.KEEP_NEWEST
                    )
                    merged_record = conflict_resolver.merge_data(
                        local_record, remote_record, resolution_results
                    )
                    records_to_resolve.append(merged_record)
                else:
                    records_to_resolve.append(remote_record)
        
        if records_to_resolve:
            final_data = pd.DataFrame(records_to_resolve)
        else:
            final_data = enhanced_data.copy()
        
        # Save final enhanced data
        final_path = temp_workspace['data'] / 'final_enhanced_dataset.csv'
        final_data.to_csv(final_path, index=False)
        
        # Step 5: Final quality assessment
        final_quality = quality_scorer.score_dataset(str(final_path), include_details=True)
        
        total_improvement = final_quality['overall_score'] - initial_quality['overall_score']
        
        print(f"Final quality score: {final_quality['overall_score']:.2f}")
        print(f"Total quality improvement: {total_improvement:+.2f}")
        print(f"Final quality level: {final_quality['quality_level']}")
        
        # Step 6: Generate improvement report
        improvement_report = {
            'initial_score': initial_quality['overall_score'],
            'cleaned_score': cleaned_quality['overall_score'],
            'final_score': final_quality['overall_score'],
            'total_improvement': total_improvement,
            'cleaning_improvement': quality_improvement,
            'enhancement_improvement': final_quality['overall_score'] - cleaned_quality['overall_score'],
            'initial_level': initial_quality['quality_level'],
            'final_level': final_quality['quality_level']
        }
        
        # Save improvement report
        report_path = temp_workspace['quality_reports'] / 'improvement_report.json'
        with open(report_path, 'w') as f:
            json.dump(improvement_report, f, indent=2)
        
        print("Quality improvement pipeline completed successfully")
        
        # Verify improvements
        assert final_quality['overall_score'] > initial_quality['overall_score']
        assert len(final_data) > 0
        assert report_path.exists()
    
    def test_large_scale_integration_pipeline(self, temp_workspace):
        """Test integration pipeline with larger datasets."""
        
        # Create larger synthetic datasets
        np.random.seed(42)  # For reproducible results
        
        large_datasets = {}
        dataset_sizes = {'small': 100, 'medium': 1000, 'large': 5000}
        
        for size_name, n_subjects in dataset_sizes.items():
            # Generate synthetic neuroimaging data
            data = pd.DataFrame({
                'participant_id': [f"sub-{i:05d}" for i in range(n_subjects)],
                'age': np.random.normal(30, 10, n_subjects).clip(18, 65),
                'sex': np.random.choice(['M', 'F'], n_subjects),
                'handedness': np.random.choice(['right', 'left'], n_subjects, p=[0.9, 0.1]),
                'education_years': np.random.normal(16, 3, n_subjects).clip(8, 25),
                'brain_volume': np.random.normal(1200000, 150000, n_subjects),
                'cortical_thickness': np.random.normal(2.4, 0.3, n_subjects),
                'quality_rating': np.random.uniform(0.5, 1.0, n_subjects),
                'scanner_type': np.random.choice(['Siemens', 'GE', 'Philips'], n_subjects),
                'site_id': np.random.choice([f'Site_{i}' for i in range(1, 6)], n_subjects)
            })
            
            data_path = temp_workspace['data'] / f'{size_name}_dataset.csv'
            data.to_csv(data_path, index=False)
            large_datasets[size_name] = {
                'path': str(data_path),
                'data': data,
                'size': n_subjects
            }
        
        print(f"Created {len(large_datasets)} synthetic datasets")
        
        # Initialize components
        quality_scorer = QualityScorer()
        export_pipeline = DataExportPipeline(
            output_dir=str(temp_workspace['exports']),
            parallel=True,
            n_workers=2
        )
        archiver = DataArchiver(
            archive_dir=str(temp_workspace['archives']),
            staging_dir=str(temp_workspace['staging']),
            db_path=str(temp_workspace['archives'] / 'catalog.db')
        )
        
        import time
        
        # Step 1: Parallel quality assessment
        print("Step 1: Parallel quality assessment")
        start_time = time.time()
        
        quality_results = {}
        for name, dataset_info in large_datasets.items():
            quality_report = quality_scorer.score_dataset(
                dataset_info['path'],
                include_details=False  # Skip details for speed
            )
            quality_results[name] = quality_report
            print(f"  {name} ({dataset_info['size']} subjects): {quality_report['overall_score']:.2f}")
        
        quality_time = time.time() - start_time
        print(f"Quality assessment completed in {quality_time:.2f} seconds")
        
        # Step 2: Batch export in different formats
        print("Step 2: Batch export")
        start_time = time.time()
        
        dataset_paths = [info['path'] for info in large_datasets.values()]
        
        # Export to different formats
        export_formats = [ExportFormat.JSON, ExportFormat.PARQUET]
        export_results = {}
        
        for format_type in export_formats:
            batch_results = export_pipeline.batch_export(
                dataset_paths,
                format_type,
                parallel=True
            )
            export_results[format_type] = batch_results
            
            successful_exports = [r for r in batch_results if r.get('status') == 'success']
            print(f"  {format_type}: {len(successful_exports)}/{len(batch_results)} successful")
        
        export_time = time.time() - start_time
        print(f"Batch export completed in {export_time:.2f} seconds")
        
        # Step 3: Selective archival based on quality
        print("Step 3: Selective archival")
        start_time = time.time()
        
        # Archive datasets with quality score above threshold
        quality_threshold = 0.7
        archive_results = {}
        
        for name, dataset_info in large_datasets.items():
            quality_score = quality_results[name]['overall_score']
            
            if quality_score >= quality_threshold:
                archive_result = archiver.archive_dataset(
                    dataset_info['path'],
                    dataset_name=f"Quality Dataset {name.title()}",
                    compression=CompressionLevel.BALANCED,
                    metadata={
                        'size': dataset_info['size'],
                        'quality_score': quality_score,
                        'archived_reason': 'quality_threshold_met'
                    }
                )
                archive_results[name] = archive_result
                print(f"  Archived {name}: {archive_result['compression_ratio']:.2f}x compression")
        
        archival_time = time.time() - start_time  
        print(f"Archival completed in {archival_time:.2f} seconds")
        
        # Step 4: Performance analysis and reporting
        print("Step 4: Performance analysis")
        
        # Get statistics
        export_history = export_pipeline.get_export_history()
        storage_stats = archiver.get_storage_stats()
        
        # Calculate performance metrics
        total_subjects = sum(info['size'] for info in large_datasets.values())
        total_time = quality_time + export_time + archival_time
        subjects_per_second = total_subjects / total_time if total_time > 0 else 0
        
        performance_report = {
            'datasets_processed': len(large_datasets),
            'total_subjects': total_subjects,
            'quality_assessment_time': quality_time,
            'export_time': export_time,  
            'archival_time': archival_time,
            'total_processing_time': total_time,
            'throughput_subjects_per_second': subjects_per_second,
            'exports_created': len(export_history),
            'archives_created': len(archive_results),
            'total_storage_gb': storage_stats['total_size_gb'],
            'average_compression_ratio': storage_stats.get('average_compression_ratio', 1.0)
        }
        
        # Save performance report
        perf_report_path = temp_workspace['quality_reports'] / 'performance_report.json'
        with open(perf_report_path, 'w') as f:
            json.dump(performance_report, f, indent=2)
        
        print("Performance Summary:")
        print(f"  Total subjects processed: {total_subjects}")
        print(f"  Processing throughput: {subjects_per_second:.1f} subjects/second")
        print(f"  Exports created: {len(export_history)}")
        print(f"  Archives created: {len(archive_results)}")
        print(f"  Storage used: {storage_stats['total_size_gb']:.2f} GB")
        print(f"  Average compression: {storage_stats.get('average_compression_ratio', 1.0):.2f}x")
        
        # Verify performance meets expectations
        assert subjects_per_second > 10  # Should process at least 10 subjects per second
        assert len(export_history) > 0
        assert storage_stats['total_size_gb'] > 0
        assert perf_report_path.exists()
        
        # Test retrieval of one archive to verify end-to-end functionality
        if archive_results:
            first_archive_id = list(archive_results.values())[0]['archive_id']
            restore_path = temp_workspace['staging'] / 'performance_test_restore'
            
            retrieval_result = archiver.retrieve_archive(
                first_archive_id,
                restore_path=str(restore_path)
            )
            
            assert restore_path.exists()
            print(f"  Successfully retrieved archive for verification")
        
        print("Large-scale integration pipeline completed successfully")


@pytest.mark.integration
@pytest.mark.slow
class TestDataIntegrationStressTests:
    """Stress tests for data integration components."""
    
    def test_high_conflict_resolution_scenario(self, temp_workspace):
        """Test conflict resolution under high conflict scenarios."""
        
        conflict_resolver = ConflictResolver()
        
        # Create datasets with many conflicts
        base_data = pd.DataFrame({
            'id': range(100),
            'value1': np.random.rand(100),
            'value2': np.random.randint(1, 100, 100),
            'category': np.random.choice(['A', 'B', 'C'], 100)
        })
        
        # Create modified version with conflicts in every field
        conflicted_data = base_data.copy()
        conflicted_data['value1'] = conflicted_data['value1'] + np.random.normal(0, 0.1, 100)  # Small changes
        conflicted_data['value2'] = conflicted_data['value2'] + np.random.randint(-5, 6, 100)  # Int changes
        conflicted_data['category'] = np.random.choice(['X', 'Y', 'Z'], 100)  # Complete category change
        
        # Convert to record format for conflict resolution
        base_records = base_data.to_dict('records')
        conflicted_records = conflicted_data.to_dict('records')
        
        print("Testing high-conflict resolution scenario")
        
        resolved_records = []
        total_conflicts = 0
        
        start_time = time.time()
        
        for i in range(len(base_records)):
            base_record = base_records[i]
            conflicted_record = conflicted_records[i]
            
            # Detect and resolve conflicts
            conflicts = conflict_resolver.detect_conflicts(base_record, conflicted_record)
            total_conflicts += len(conflicts)
            
            if conflicts:
                resolution_results = conflict_resolver.resolve_conflicts(
                    conflicts, 
                    ResolutionStrategy.USE_QUALITY_SCORE
                )
                resolved_record = conflict_resolver.merge_data(
                    base_record,
                    conflicted_record,
                    resolution_results
                )
            else:
                resolved_record = conflicted_record
            
            resolved_records.append(resolved_record)
        
        resolution_time = time.time() - start_time
        
        # Verify results
        assert len(resolved_records) == 100
        assert total_conflicts > 200  # Should have many conflicts
        
        # Get conflict statistics
        stats = conflict_resolver.get_conflict_statistics()
        
        print(f"Resolved {total_conflicts} conflicts across 100 records")
        print(f"Resolution time: {resolution_time:.2f} seconds")  
        print(f"Conflicts per second: {total_conflicts/resolution_time:.1f}")
        print(f"Success rate: {stats['success_rate']:.1%}")
        
        # Verify performance
        assert resolution_time < 30  # Should complete within 30 seconds
        assert stats['success_rate'] > 0.8  # At least 80% success rate
    
    def test_memory_efficiency_large_datasets(self, temp_workspace):
        """Test memory efficiency with large datasets."""
        
        # This test would require significant memory monitoring
        # For now, we'll create a moderately large dataset and ensure it processes without errors
        
        print("Testing memory efficiency with large dataset")
        
        # Create dataset that would use significant memory if not handled efficiently
        n_subjects = 10000
        n_features = 100
        
        large_data = pd.DataFrame({
            f'feature_{i}': np.random.rand(n_subjects)
            for i in range(n_features)
        })
        large_data['participant_id'] = [f"sub-{i:06d}" for i in range(n_subjects)]
        
        large_path = temp_workspace['data'] / 'large_memory_test.csv'
        large_data.to_csv(large_path, index=False)
        
        # Test quality scoring (should handle large datasets efficiently)
        quality_scorer = QualityScorer()
        
        start_time = time.time()
        quality_report = quality_scorer.score_dataset(str(large_path))
        quality_time = time.time() - start_time
        
        print(f"Quality assessment of {n_subjects} x {n_features} dataset: {quality_time:.2f}s")
        
        # Test export (should handle large datasets)
        export_pipeline = DataExportPipeline(
            output_dir=str(temp_workspace['exports'])
        )
        
        start_time = time.time()
        export_result = export_pipeline.export_dataset(
            str(large_path),
            ExportFormat.PARQUET,  # Efficient format for large data
            output_name="large_memory_test"
        )
        export_time = time.time() - start_time
        
        print(f"Export of large dataset: {export_time:.2f}s")
        print(f"Export size: {export_result['size_bytes'] / 1024 / 1024:.1f} MB")
        
        # Verify operations completed successfully
        assert quality_report['overall_score'] > 0
        assert export_result['status'] == 'success'
        assert quality_time < 60  # Should complete within 1 minute
        assert export_time < 120  # Should complete within 2 minutes
        
        print("Memory efficiency test completed successfully")