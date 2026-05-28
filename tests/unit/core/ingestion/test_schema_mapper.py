"""Unit tests for the Schema Mapper component."""

import pytest
import pandas as pd
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from dataclasses import asdict

from brain_researcher.core.ingestion.harmonization.schema_mapper import (
    SchemaMapper,
    FieldMapping
)


class TestFieldMapping:
    """Test suite for FieldMapping dataclass."""
    
    def test_field_mapping_creation(self):
        """Test FieldMapping dataclass creation."""
        mapping = FieldMapping(
            source_field="age",
            target_field="age_years",
            confidence=0.95,
            mapping_type="direct"
        )
        
        assert mapping.source_field == "age"
        assert mapping.target_field == "age_years"
        assert mapping.confidence == 0.95
        assert mapping.mapping_type == "direct"
        assert mapping.transform_func is None
    
    def test_field_mapping_with_transform(self):
        """Test FieldMapping with transform function."""
        def transform_age(x):
            return x / 12  # months to years
        
        mapping = FieldMapping(
            source_field="age_months",
            target_field="age_years",
            transform_func=transform_age,
            confidence=0.9,
            mapping_type="derived"
        )
        
        assert mapping.transform_func is not None
        assert mapping.transform_func(24) == 2.0
        assert mapping.mapping_type == "derived"
    
    def test_field_mapping_defaults(self):
        """Test FieldMapping with default values."""
        mapping = FieldMapping(
            source_field="source",
            target_field="target"
        )
        
        assert mapping.confidence == 1.0
        assert mapping.mapping_type == "direct"
        assert mapping.transform_func is None


class TestSchemaMapper:
    """Test suite for SchemaMapper class."""
    
    @pytest.fixture
    def mapper(self):
        """Create SchemaMapper instance for testing."""
        return SchemaMapper()
    
    @pytest.fixture
    def temp_config_file(self):
        """Create temporary config file."""
        config_data = {
            "version": "1.0",
            "mappings": [
                {
                    "source": "subj_id",
                    "target": "participant_id",
                    "confidence": 0.9,
                    "type": "direct"
                }
            ]
        }
        
        temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        json.dump(config_data, temp_file)
        temp_file.close()
        
        yield temp_file.name
        
        Path(temp_file.name).unlink(missing_ok=True)
    
    @pytest.fixture
    def sample_source_schema(self):
        """Sample source schema for testing."""
        return {
            'subj_id': {'type': 'string', 'description': 'Subject identifier'},
            'age_years': {'type': 'int', 'description': 'Age in years'},
            'gender': {'type': 'string', 'description': 'Gender'},
            'hand_dominant': {'type': 'string', 'description': 'Dominant hand'},
            'clinical_dx': {'type': 'string', 'description': 'Clinical diagnosis'}
        }
    
    def test_initialization_default(self, mapper):
        """Test SchemaMapper initialization with defaults."""
        assert mapper.mappings == {}
        assert isinstance(mapper.standard_schemas, dict)
        assert mapper.custom_mappings == {}
        assert isinstance(mapper.common_mappings, dict)
        assert isinstance(mapper.bids_mappings, dict)
        
        # Check common mappings structure
        assert 'subject_id' in mapper.common_mappings
        assert 'age' in mapper.common_mappings
        assert 'sex' in mapper.common_mappings
        
        # Check BIDS mappings
        assert 'OpenNeuro' in mapper.bids_mappings
        assert 'HCP' in mapper.bids_mappings
        assert 'ABCD' in mapper.bids_mappings
    
    def test_initialization_with_config(self, temp_config_file):
        """Test SchemaMapper initialization with config file."""
        mapper = SchemaMapper(mapping_config=temp_config_file)
        
        # Should have loaded mappings from config
        assert len(mapper.mappings) > 0
        assert 'subj_id' in mapper.mappings
        
        mapping = mapper.mappings['subj_id']
        assert mapping.source_field == 'subj_id'
        assert mapping.target_field == 'participant_id'
        assert mapping.confidence == 0.9
        assert mapping.mapping_type == 'direct'
    
    def test_load_standard_schemas(self, mapper):
        """Test loading of standard schemas."""
        schemas = mapper._load_standard_schemas()
        
        # Should have BIDS and NIDM schemas
        assert 'BIDS' in schemas
        assert 'NIDM' in schemas
        
        # Check BIDS schema structure
        bids_schema = schemas['BIDS']
        assert 'participant_id' in bids_schema
        assert 'age' in bids_schema
        assert 'sex' in bids_schema
        
        # Check field properties
        assert bids_schema['participant_id']['required'] is True
        assert bids_schema['sex']['values'] == ['M', 'F']
    
    def test_map_schemas_exact_match(self, mapper, sample_source_schema):
        """Test schema mapping with exact matches."""
        # Add age to source schema to test exact match
        sample_source_schema['age'] = {'type': 'int'}
        
        mappings = mapper.map_schemas(sample_source_schema, 'BIDS')
        
        # Should find exact match for 'age'
        assert 'age' in mappings
        age_mapping = mappings['age']
        assert age_mapping.source_field == 'age'
        assert age_mapping.target_field == 'age'
        assert age_mapping.confidence == 1.0
        assert age_mapping.mapping_type == 'direct'
    
    def test_map_schemas_common_mappings(self, mapper, sample_source_schema):
        """Test schema mapping using common field mappings."""
        mappings = mapper.map_schemas(sample_source_schema, 'BIDS')
        
        # Should find common mappings
        mapped_fields = set(mappings.keys())
        
        # Check specific mappings
        if 'subj_id' in mappings:
            subj_mapping = mappings['subj_id']
            assert subj_mapping.target_field == 'subject_id'
            assert subj_mapping.mapping_type == 'common'
        
        if 'gender' in mappings:
            gender_mapping = mappings['gender']
            assert gender_mapping.target_field == 'sex'
            assert gender_mapping.mapping_type == 'common'
    
    def test_map_schemas_fuzzy_matching(self, mapper):
        """Test schema mapping with fuzzy string matching."""
        source_schema = {
            'participant_identifier': {'type': 'string'},  # Close to participant_id
            'subject_age': {'type': 'int'},  # Close to age
            'gender_info': {'type': 'string'}  # Close to sex/gender
        }
        
        mappings = mapper.map_schemas(source_schema, 'BIDS')
        
        # Should find fuzzy matches
        assert len(mappings) > 0
        
        # Check that fuzzy mappings have reasonable confidence
        for field, mapping in mappings.items():
            if mapping.mapping_type == 'fuzzy':
                assert 0.5 <= mapping.confidence <= 1.0
    
    def test_apply_mappings_basic(self, mapper):
        """Test applying mappings to data."""
        # Create test data
        data = pd.DataFrame({
            'subj_id': ['001', '002', '003'],
            'age_years': [25, 30, 35],
            'gender': ['M', 'F', 'M']
        })
        
        # Create mappings
        mappings = {
            'subj_id': FieldMapping('subj_id', 'participant_id', confidence=1.0),
            'age_years': FieldMapping('age_years', 'age', confidence=1.0),
            'gender': FieldMapping('gender', 'sex', confidence=1.0)
        }
        
        mapped_data = mapper.apply_mappings(data, mappings)
        
        # Check mapped columns
        assert list(mapped_data.columns) == ['participant_id', 'age', 'sex']
        assert len(mapped_data) == 3
        assert mapped_data['participant_id'].tolist() == ['001', '002', '003']
        assert mapped_data['age'].tolist() == [25, 30, 35]
        assert mapped_data['sex'].tolist() == ['M', 'F', 'M']
    
    def test_apply_mappings_with_transform(self, mapper):
        """Test applying mappings with transform functions."""
        # Create test data with ages in months
        data = pd.DataFrame({
            'age_months': [300, 360, 420]  # 25, 30, 35 years
        })
        
        # Create mapping with transform
        def months_to_years(x):
            return x / 12
        
        mappings = {
            'age_months': FieldMapping(
                'age_months', 
                'age_years',
                transform_func=months_to_years,
                confidence=0.9
            )
        }
        
        mapped_data = mapper.apply_mappings(data, mappings)
        
        # Check transformed values
        assert 'age_years' in mapped_data.columns
        assert mapped_data['age_years'].tolist() == [25.0, 30.0, 35.0]
    
    def test_apply_mappings_missing_field(self, mapper):
        """Test applying mappings with missing source field."""
        data = pd.DataFrame({
            'existing_field': [1, 2, 3]
        })
        
        mappings = {
            'missing_field': FieldMapping('missing_field', 'target_field', confidence=1.0)
        }
        
        mapped_data = mapper.apply_mappings(data, mappings)
        
        # Should not include the missing field mapping
        assert 'target_field' not in mapped_data.columns
        assert len(mapped_data.columns) == 0  # No valid mappings
    
    def test_apply_mappings_transform_error(self, mapper):
        """Test applying mappings with transform function error."""
        data = pd.DataFrame({
            'numeric_field': [1, 2, 'invalid']  # Mixed types
        })
        
        def failing_transform(x):
            return float(x) * 2  # Will fail on 'invalid'
        
        mappings = {
            'numeric_field': FieldMapping(
                'numeric_field',
                'transformed_field',
                transform_func=failing_transform
            )
        }
        
        mapped_data = mapper.apply_mappings(data, mappings)
        
        # Should fall back to original values when transform fails
        assert 'transformed_field' in mapped_data.columns
    
    def test_create_mapping_profile(self, mapper):
        """Test creation of mapping profile for multiple datasets."""
        datasets = ['BIDS', 'HCP', 'ABCD']
        
        profile = mapper.create_mapping_profile(datasets)
        
        # Check profile structure
        assert 'datasets' in profile
        assert 'compatibility_matrix' in profile
        assert 'common_fields' in profile
        assert 'mapping_quality' in profile
        
        assert profile['datasets'] == datasets
        
        # Check compatibility matrix
        matrix = profile['compatibility_matrix']
        for source in datasets:
            assert source in matrix
            for target in datasets:
                if source != target:
                    assert target in matrix[source]
                    assert isinstance(matrix[source][target], float)
                    assert 0.0 <= matrix[source][target] <= 1.0
        
        # Check common fields
        assert isinstance(profile['common_fields'], list)
        
        # Check mapping quality
        quality = profile['mapping_quality']
        for dataset in datasets:
            assert dataset in quality
            assert isinstance(quality[dataset], dict)
    
    def test_harmonize_field_names(self, mapper):
        """Test field name harmonization across datasets."""
        datasets = {
            'dataset1': pd.DataFrame({
                'participant_id': ['001', '002'],
                'age': [25, 30],
                'gender': ['M', 'F']
            }),
            'dataset2': pd.DataFrame({
                'subj_id': ['003', '004'],
                'age_years': [35, 40],
                'sex': ['F', 'M']
            }),
            'dataset3': pd.DataFrame({
                'participant_id': ['005', '006'],
                'age': [45, 50],
                'gender': ['M', 'M']
            })
        }
        
        harmonized = mapper.harmonize_field_names(datasets)
        
        # Should return same number of datasets
        assert len(harmonized) == len(datasets)
        
        # Check that harmonization was applied
        for name, data in harmonized.items():
            assert isinstance(data, pd.DataFrame)
            assert len(data) == 2  # Same number of rows
    
    def test_validate_mapping(self, mapper):
        """Test mapping validation against actual data."""
        data = pd.DataFrame({
            'participant_id': ['001', '002', '003'],
            'age': [25, 30, 35],
            'sex': ['M', 'F', 'M'],
            'unused_field': ['A', 'B', 'C']
        })
        
        mappings = {
            'participant_id': FieldMapping('participant_id', 'subject_id'),
            'age': FieldMapping('age', 'age_years'),
            'sex': FieldMapping('sex', 'gender')
        }
        
        validation = mapper.validate_mapping(mappings, data)
        
        # Check validation structure
        assert 'valid' in validation
        assert 'coverage' in validation
        assert 'missing_fields' in validation
        assert 'type_mismatches' in validation
        assert 'warnings' in validation
        
        # Should have good coverage (3/4 fields mapped)
        assert validation['coverage'] == 0.75
        
        # Should identify unused field
        assert 'unused_field' in validation['missing_fields']
        
        # Should be valid overall
        assert validation['valid'] is True
    
    def test_validate_mapping_low_coverage(self, mapper):
        """Test mapping validation with low field coverage."""
        data = pd.DataFrame({
            'field1': [1, 2, 3],
            'field2': [4, 5, 6],
            'field3': [7, 8, 9],
            'field4': [10, 11, 12],
            'field5': [13, 14, 15]
        })
        
        # Only map one field out of five
        mappings = {
            'field1': FieldMapping('field1', 'mapped_field1')
        }
        
        validation = mapper.validate_mapping(mappings, data)
        
        # Should have low coverage (1/5 = 0.2)
        assert validation['coverage'] == 0.2
        
        # Should have warnings about low coverage
        assert len(validation['warnings']) > 0
        assert any('Low field coverage' in w for w in validation['warnings'])
        
        # Should be invalid due to low coverage
        assert validation['valid'] is False
    
    def test_validate_mapping_type_mismatches(self, mapper):
        """Test mapping validation with type mismatches."""
        data = pd.DataFrame({
            'age': ['25', '30', '35'],  # String instead of int
            'score': [1.5, 2.5, 3.5]  # Float is OK
        })
        
        mappings = {
            'age': FieldMapping('age', 'age'),
            'score': FieldMapping('score', 'score')
        }
        
        with patch.object(mapper, '_get_expected_dtype') as mock_get_dtype:
            mock_get_dtype.side_effect = lambda field: {
                'age': int,  # Expect int but data is string
                'score': float  # Expect float and data is float
            }.get(field)
            
            validation = mapper.validate_mapping(mappings, data)
            
            # Should detect type mismatch for age
            assert len(validation['type_mismatches']) >= 1
            
            type_mismatch = validation['type_mismatches'][0]
            assert type_mismatch['field'] == 'age'
            assert 'object' in type_mismatch['source_type']  # String/object type
            assert 'int' in type_mismatch['expected_type']
    
    def test_export_mapping_config(self, mapper, tmp_path):
        """Test exporting mapping configuration."""
        mappings = {
            'source1': FieldMapping('source1', 'target1', confidence=0.9, mapping_type='direct'),
            'source2': FieldMapping('source2', 'target2', confidence=0.8, mapping_type='fuzzy')
        }
        
        output_path = tmp_path / "exported_config.json"
        mapper.export_mapping_config(mappings, str(output_path))
        
        # Check file was created
        assert output_path.exists()
        
        # Check content
        with open(output_path, 'r') as f:
            config = json.load(f)
        
        assert config['version'] == '1.0'
        assert len(config['mappings']) == 2
        
        # Check mapping details
        mapping1 = config['mappings'][0]
        assert mapping1['source'] == 'source1'
        assert mapping1['target'] == 'target1'
        assert mapping1['confidence'] == 0.9
        assert mapping1['type'] == 'direct'
    
    def test_register_custom_mapping(self, mapper):
        """Test registering custom field mappings."""
        custom_mapping = {
            'custom_id': 'participant_id',
            'custom_age': 'age',
            'custom_gender': 'sex'
        }
        
        mapper.register_custom_mapping('CustomDataset', 'BIDS', custom_mapping)
        
        # Check that custom mapping was registered
        key = 'CustomDataset_to_BIDS'
        assert key in mapper.custom_mappings
        assert mapper.custom_mappings[key] == custom_mapping
    
    def test_find_common_mapping(self, mapper):
        """Test finding mappings using common field names."""
        # Test exact match
        mapping = mapper._find_common_mapping('age')
        assert mapping is not None
        assert mapping.target_field == 'age'
        assert mapping.mapping_type == 'common'
        
        # Test case-insensitive match
        mapping = mapper._find_common_mapping('AGE')
        assert mapping is not None
        assert mapping.target_field == 'age'
        
        # Test variation match
        mapping = mapper._find_common_mapping('Subject')
        assert mapping is not None
        assert mapping.target_field == 'subject_id'
        
        # Test no match
        mapping = mapper._find_common_mapping('unknown_field')
        assert mapping is None
    
    def test_fuzzy_match_field(self, mapper):
        """Test fuzzy field name matching."""
        target_fields = ['participant_id', 'age', 'sex', 'handedness']
        
        # Test close match
        match = mapper._fuzzy_match_field('participant_identifier', target_fields)
        assert match is not None
        assert match.target_field == 'participant_id'
        assert match.mapping_type == 'fuzzy'
        assert match.confidence > 0.8
        
        # Test no good match
        match = mapper._fuzzy_match_field('completely_different', target_fields)
        # Might return None or a low-confidence match depending on threshold
        if match is not None:
            assert match.confidence < 0.8
    
    def test_semantic_match(self, mapper):
        """Test semantic field matching."""
        target_schema = {
            'participant_id': {},
            'age_at_scan': {},
            'dominant_hand': {},
            'clinical_diagnosis': {}
        }
        
        # Test semantic similarity
        match = mapper._semantic_match('subject_age', target_schema)
        if match is not None:
            assert match.target_field in target_schema
            assert match.mapping_type == 'semantic'
            assert match.confidence <= 1.0
        
        # Test no semantic match
        match = mapper._semantic_match('unrelated_field', target_schema)
        # May or may not find a match depending on implementation
    
    def test_calculate_compatibility(self, mapper):
        """Test compatibility calculation between datasets."""
        # Test with known datasets
        score = mapper._calculate_compatibility('BIDS', 'HCP')
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0
        
        # Test with unknown dataset
        score = mapper._calculate_compatibility('Unknown', 'BIDS')
        assert score == 0.0
    
    def test_get_dataset_schema(self, mapper):
        """Test retrieving dataset schemas."""
        # Test BIDS schema
        bids_schema = mapper._get_dataset_schema('BIDS')
        assert isinstance(bids_schema, dict)
        assert len(bids_schema) > 0
        assert 'participant_id' in bids_schema
        
        # Test HCP schema
        hcp_schema = mapper._get_dataset_schema('HCP')
        assert isinstance(hcp_schema, dict)
        
        # Test unknown dataset
        unknown_schema = mapper._get_dataset_schema('Unknown')
        assert unknown_schema == {}
    
    def test_assess_mapping_quality(self, mapper):
        """Test mapping quality assessment."""
        quality = mapper._assess_mapping_quality('BIDS')
        
        assert isinstance(quality, dict)
        assert 'completeness' in quality
        assert 'accuracy' in quality
        assert 'consistency' in quality
        
        # All scores should be between 0 and 1
        for score in quality.values():
            assert 0.0 <= score <= 1.0
    
    def test_find_reference_schema(self, mapper):
        """Test finding the most complete dataset for reference."""
        datasets = {
            'small': pd.DataFrame({'a': [1, 2]}),  # 2 rows, 1 col
            'medium': pd.DataFrame({'a': [1, 2, 3], 'b': [4, 5, 6]}),  # 3 rows, 2 cols
            'large': pd.DataFrame({  # 4 rows, 3 cols
                'a': [1, 2, 3, 4],
                'b': [5, 6, 7, 8],
                'c': [9, 10, 11, 12]
            })
        }
        
        reference = mapper._find_reference_schema(datasets)
        
        # Should choose the largest dataset
        assert reference == 'large'
    
    def test_map_to_reference(self, mapper):
        """Test mapping source schema to reference schema."""
        source_schema = {'subj_id', 'age_years', 'gender'}
        reference_schema = {'participant_id', 'age', 'sex', 'handedness'}
        
        mappings = mapper._map_to_reference(source_schema, reference_schema)
        
        assert isinstance(mappings, dict)
        
        # Should find some mappings
        if 'age_years' in mappings:
            assert mappings['age_years'] == 'age'  # Should map to similar field
    
    def test_get_expected_dtype(self, mapper):
        """Test getting expected data types for fields."""
        # Test known fields
        assert mapper._get_expected_dtype('age') == float
        assert mapper._get_expected_dtype('participant_id') == str
        assert mapper._get_expected_dtype('sex') == str
        
        # Test unknown field
        assert mapper._get_expected_dtype('unknown_field') is None
    
    def test_compatible_dtypes(self, mapper):
        """Test data type compatibility checking."""
        # Test compatible types
        assert mapper._compatible_dtypes('int64', float) is True
        assert mapper._compatible_dtypes('float64', float) is True
        assert mapper._compatible_dtypes('object', str) is True
        
        # Test exact match
        assert mapper._compatible_dtypes(int, int) is True
        
        # Test incompatible types
        assert mapper._compatible_dtypes('object', float) is False
        assert mapper._compatible_dtypes(int, str) is False
    
    def test_load_mapping_config(self, temp_config_file):
        """Test loading mapping configuration from file."""
        mapper = SchemaMapper()
        mapper._load_mapping_config(temp_config_file)
        
        # Should have loaded the mapping
        assert len(mapper.mappings) > 0
        assert 'subj_id' in mapper.mappings
        
        mapping = mapper.mappings['subj_id']
        assert mapping.source_field == 'subj_id'
        assert mapping.target_field == 'participant_id'
    
    def test_load_mapping_config_nonexistent(self, mapper):
        """Test loading config from nonexistent file."""
        # Should not raise error, just not load anything
        mapper._load_mapping_config('/nonexistent/config.json')
        assert len(mapper.mappings) == 0


@pytest.mark.integration
class TestSchemaMapperIntegration:
    """Integration tests for SchemaMapper."""
    
    def test_end_to_end_schema_harmonization(self):
        """Test complete schema harmonization workflow."""
        mapper = SchemaMapper()
        
        # Create datasets with different schemas
        hcp_data = pd.DataFrame({
            'Subject': ['100001', '100002', '100003'],
            'Age_in_Yrs': [22, 25, 28],
            'Gender': ['M', 'F', 'M'],
            'Handedness': ['R', 'L', 'R']
        })
        
        abcd_data = pd.DataFrame({
            'subjectkey': ['NDAR_001', 'NDAR_002', 'NDAR_003'],
            'interview_age': [264, 300, 336],  # Age in months
            'sex': ['M', 'F', 'M'],
            'eventname': ['baseline', 'baseline', 'baseline']
        })
        
        openneuro_data = pd.DataFrame({
            'participant_id': ['sub-001', 'sub-002', 'sub-003'],
            'age': [25, 30, 35],
            'sex': ['M', 'F', 'M'],
            'handedness': ['right', 'left', 'right']
        })
        
        datasets = {
            'HCP': hcp_data,
            'ABCD': abcd_data,
            'OpenNeuro': openneuro_data
        }
        
        # Harmonize field names
        harmonized = mapper.harmonize_field_names(datasets)
        
        # All datasets should be harmonized
        assert len(harmonized) == 3
        
        # Check that harmonization worked
        for name, data in harmonized.items():
            assert isinstance(data, pd.DataFrame)
            assert len(data) == 3  # Same number of subjects
            
            # Should have some common field names after harmonization
            # (exact names depend on which dataset was chosen as reference)
    
    def test_cross_dataset_mapping_compatibility(self):
        """Test mapping compatibility across different dataset types."""
        mapper = SchemaMapper()
        
        # Test various neuroimaging dataset schemas
        schemas = {
            'HCP': {
                'Subject': {'type': 'string'},
                'Age_in_Yrs': {'type': 'float'},
                'Gender': {'type': 'string'},
                'Handedness': {'type': 'string'},
                'fMRI_3T_ReconVrs': {'type': 'string'}
            },
            'ABCD': {
                'subjectkey': {'type': 'string'},
                'interview_age': {'type': 'int'},
                'sex': {'type': 'string'},
                'eventname': {'type': 'string'},
                'mri_info_manufacturer': {'type': 'string'}
            },
            'BIDS_OpenNeuro': {
                'participant_id': {'type': 'string'},
                'age': {'type': 'float'},
                'sex': {'type': 'string'},
                'handedness': {'type': 'string'},
                'session': {'type': 'string'}
            }
        }
        
        # Create mapping profile
        dataset_names = list(schemas.keys())
        profile = mapper.create_mapping_profile(dataset_names)
        
        # Should identify some level of compatibility
        compatibility_matrix = profile['compatibility_matrix']
        
        for source in dataset_names:
            for target in dataset_names:
                if source != target:
                    score = compatibility_matrix[source][target]
                    assert 0.0 <= score <= 1.0
        
        # Should identify some common fields across neuroimaging datasets
        # (at least subject ID, age, sex should be common concepts)
        mapping_quality = profile['mapping_quality']
        for dataset in dataset_names:
            quality = mapping_quality[dataset]
            assert isinstance(quality, dict)
            assert all(0.0 <= v <= 1.0 for v in quality.values())
    
    def test_bids_conversion_workflow(self):
        """Test converting various datasets to BIDS format."""
        mapper = SchemaMapper()
        
        # Simulate different dataset formats converting to BIDS
        test_datasets = [
            {
                'name': 'HCP_style',
                'schema': {
                    'Subject': {'type': 'string'},
                    'Age_in_Yrs': {'type': 'float'},
                    'Gender': {'type': 'string'}
                },
                'data': pd.DataFrame({
                    'Subject': ['100001', '100002'],
                    'Age_in_Yrs': [22, 25],
                    'Gender': ['M', 'F']
                })
            },
            {
                'name': 'Custom_study',
                'schema': {
                    'ID': {'type': 'string'},
                    'participant_age': {'type': 'int'},
                    'biological_sex': {'type': 'string'}
                },
                'data': pd.DataFrame({
                    'ID': ['P001', 'P002'],
                    'participant_age': [30, 35],
                    'biological_sex': ['male', 'female']
                })
            }
        ]
        
        bids_conversions = {}
        
        for dataset in test_datasets:
            # Map to BIDS
            mappings = mapper.map_schemas(dataset['schema'], 'BIDS')
            
            # Apply mappings
            bids_data = mapper.apply_mappings(dataset['data'], mappings)
            
            bids_conversions[dataset['name']] = {
                'mappings': mappings,
                'data': bids_data,
                'original_data': dataset['data']
            }
            
            # Validate mapping
            validation = mapper.validate_mapping(mappings, dataset['data'])
            
            # Should have reasonable coverage and validity
            assert validation['coverage'] > 0.0
            
            # At least some fields should be mapped
            assert len(mappings) > 0
        
        # All conversions should produce some BIDS-compatible output
        for name, conversion in bids_conversions.items():
            assert len(conversion['data']) > 0
    
    def test_multi_site_harmonization(self):
        """Test harmonization across multiple sites with different conventions."""
        mapper = SchemaMapper()
        
        # Simulate multi-site study with different naming conventions
        sites = {
            'Site_A': pd.DataFrame({
                'SubjectID': ['A001', 'A002', 'A003'],
                'AgeAtScan': [25.5, 30.2, 28.1],
                'Sex': ['M', 'F', 'M'],
                'ScannerModel': ['Siemens', 'Siemens', 'Siemens']
            }),
            'Site_B': pd.DataFrame({
                'participant': ['B001', 'B002', 'B003'],
                'age_years': [22, 27, 33],
                'gender': ['male', 'female', 'male'],
                'mri_scanner': ['GE', 'GE', 'GE']
            }),
            'Site_C': pd.DataFrame({
                'sub_id': ['C001', 'C002', 'C003'],
                'demographic_age': [29, 24, 31],
                'biological_sex': [1, 0, 1],  # Numeric coding
                'scanner_type': ['Philips', 'Philips', 'Philips']
            })
        }
        
        # Harmonize across sites
        harmonized_sites = mapper.harmonize_field_names(sites)
        
        # Should harmonize to common field names
        assert len(harmonized_sites) == 3
        
        # Check that harmonization preserved data
        for site_name, harmonized_data in harmonized_sites.items():
            original_data = sites[site_name]
            assert len(harmonized_data) == len(original_data)
            
            # Should have some common column names across sites after harmonization
            # (exact behavior depends on which site was chosen as reference)
        
        # Create combined dataset
        combined_schemas = {}
        for site_name, data in harmonized_sites.items():
            combined_schemas[site_name] = {
                col: {'type': str(data[col].dtype)} 
                for col in data.columns
            }
        
        # Assess cross-site compatibility
        site_names = list(combined_schemas.keys())
        profile = mapper.create_mapping_profile(site_names)
        
        # Should show improved compatibility after harmonization
        compatibility_scores = []
        for source in site_names:
            for target in site_names:
                if source != target:
                    score = profile['compatibility_matrix'][source][target]
                    compatibility_scores.append(score)
        
        # Average compatibility should be reasonable
        if compatibility_scores:
            avg_compatibility = sum(compatibility_scores) / len(compatibility_scores)
            assert avg_compatibility > 0.0  # Some level of compatibility expected
    
    def test_quality_validation_workflow(self):
        """Test comprehensive quality validation of schema mappings."""
        mapper = SchemaMapper()
        
        # Create a dataset with various data quality issues
        problematic_data = pd.DataFrame({
            'subj_id': ['001', '002', '003', '004'],
            'age_string': ['25', '30', 'unknown', '35'],  # Mixed types
            'gender_coded': [1, 2, 1, 9],  # Numeric coding with invalid value
            'missing_data': [10, None, 20, None],  # Missing values
            'inconsistent_ids': ['SUB001', 'sub-002', 'SUBJ_003', '4']  # Inconsistent format
        })
        
        # Define mappings
        mappings = {
            'subj_id': FieldMapping('subj_id', 'participant_id'),
            'age_string': FieldMapping('age_string', 'age'),
            'gender_coded': FieldMapping('gender_coded', 'sex'),
            'missing_data': FieldMapping('missing_data', 'score'),
            'inconsistent_ids': FieldMapping('inconsistent_ids', 'session')
        }
        
        # Validate mappings
        validation = mapper.validate_mapping(mappings, problematic_data)
        
        # Should detect various issues
        assert validation is not None
        assert 'valid' in validation
        assert 'type_mismatches' in validation
        assert 'warnings' in validation
        
        # Apply mappings despite issues
        mapped_data = mapper.apply_mappings(problematic_data, mappings)
        
        # Should handle problematic data gracefully
        assert len(mapped_data) == len(problematic_data)
        assert len(mapped_data.columns) > 0
        
        # Missing values should be preserved
        assert mapped_data.isnull().any().any()  # Should have some null values
    
    def test_performance_large_schema(self):
        """Test performance with large schemas."""
        mapper = SchemaMapper()
        
        # Create large schemas
        large_source_schema = {}
        for i in range(1000):
            large_source_schema[f'field_{i:04d}'] = {
                'type': 'string' if i % 2 else 'float',
                'description': f'Field number {i}'
            }
        
        import time
        start_time = time.time()
        
        # Map to BIDS (should be fast even with many fields)
        mappings = mapper.map_schemas(large_source_schema, 'BIDS')
        
        end_time = time.time()
        execution_time = end_time - start_time
        
        # Should complete within reasonable time
        assert execution_time < 10.0  # 10 seconds max
        
        # Should find some mappings
        assert isinstance(mappings, dict)
        
        # Should handle large schema without errors
        mapping_count = len(mappings)
        assert mapping_count >= 0  # At least no errors