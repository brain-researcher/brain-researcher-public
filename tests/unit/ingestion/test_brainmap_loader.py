"""Unit tests for BrainMap loader."""

import pytest
import json
import tempfile
from pathlib import Path
from brain_researcher.core.ingestion.loaders.brainmap_unified import (
    BrainMapUnifiedLoader, CoordinateValidator
)
from brain_researcher.core.ingestion.parsers.brainmap_parser import BrainMapParser


class TestBrainMapParser:
    """Test suite for BrainMapParser."""
    
    @pytest.fixture
    def parser(self):
        """Create parser instance."""
        return BrainMapParser()
    
    def test_parse_coordinate_string(self, parser):
        """Test parsing coordinate strings."""
        # Test format: "(x, y, z) space"
        coord = parser._parse_coordinate_string("(-45, 20, 8) MNI")
        assert coord == {'x': -45, 'y': 20, 'z': 8, 'space': 'MNI'}
        
        # Test format: "x=X y=Y z=Z space=SPACE"
        coord = parser._parse_coordinate_string("x=-45 y=20 z=8 space=TAL")
        assert coord == {'x': -45, 'y': 20, 'z': 8, 'space': 'TAL'}
        
        # Test invalid format
        coord = parser._parse_coordinate_string("invalid")
        assert coord is None
    
    def test_validate_coordinate(self, parser):
        """Test coordinate validation."""
        # Valid MNI coordinate
        assert parser._validate_coordinate(-45, 20, 8, 'MNI') is True
        
        # Out of bounds MNI
        assert parser._validate_coordinate(-100, 20, 8, 'MNI') is False
        
        # Valid Talairach
        assert parser._validate_coordinate(-40, 20, 8, 'TAL') is True
        
        # Invalid space
        assert parser._validate_coordinate(0, 0, 0, 'INVALID') is False
    
    def test_convert_coordinate_space(self, parser):
        """Test coordinate space conversion."""
        # TAL to MNI
        coord = {'x': -40, 'y': 20, 'z': 8, 'space': 'TAL'}
        mni = parser.convert_coordinate_space(coord, 'MNI')
        
        assert mni['space'] == 'MNI'
        assert abs(mni['x'] - (-40 * 1.08)) < 0.01
        
        # MNI to TAL
        coord = {'x': -45, 'y': 20, 'z': 8, 'space': 'MNI'}
        tal = parser.convert_coordinate_space(coord, 'TAL')
        
        assert tal['space'] == 'TAL'
        assert abs(tal['x'] - (-45 / 1.08)) < 0.01
        
        # Same space (no conversion)
        coord = {'x': -45, 'y': 20, 'z': 8, 'space': 'MNI'}
        same = parser.convert_coordinate_space(coord, 'MNI')
        assert same == coord


class TestCoordinateValidator:
    """Test suite for CoordinateValidator."""
    
    @pytest.fixture
    def validator(self):
        """Create validator instance."""
        return CoordinateValidator()
    
    def test_validate_batch(self, validator):
        """Test batch coordinate validation."""
        coordinates = [
            {'x': -45, 'y': 20, 'z': 8, 'space': 'MNI'},  # Valid
            {'x': -100, 'y': 20, 'z': 8, 'space': 'MNI'},  # Out of bounds
            {'x': -40, 'y': 20, 'z': 8, 'space': 'TAL'},  # Valid TAL
            {'x': 0, 'y': 0, 'z': 0, 'space': 'INVALID'}  # Invalid space
        ]
        
        valid = validator.validate_batch(coordinates)
        
        assert len(valid) == 2  # Only 2 valid coordinates
        assert len(validator.invalid_coords) == 2
        assert len(validator.valid_coords) == 2
    
    def test_validation_report(self, validator):
        """Test validation report generation."""
        coordinates = [
            {'x': -45, 'y': 20, 'z': 8, 'space': 'MNI'},
            {'x': -100, 'y': 20, 'z': 8, 'space': 'MNI'}
        ]
        
        validator.validate_batch(coordinates)
        report = validator.get_report()
        
        assert report['total_validated'] == 2
        assert report['valid'] == 1
        assert report['invalid'] == 1
        assert len(report['invalid_samples']) <= 10


class TestBrainMapUnifiedLoader:
    """Test suite for BrainMapUnifiedLoader."""
    
    @pytest.fixture
    def loader(self):
        """Create loader instance."""
        return BrainMapUnifiedLoader(use_api=False)
    
    @pytest.fixture
    def sample_workspace(self):
        """Create sample workspace file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("EXPERIMENT: BM_TEST_001\n")
            f.write("PMID: 12345678\n")
            f.write("CONTRAST: motor > rest\n")
            f.write("COORDINATE: (-45, 20, 8) MNI\n")
            f.write("COORDINATE: (42, 18, 10) MNI\n")
            f.write("DOMAIN: action.execution\n")
            f.write("EXPERIMENT: BM_TEST_002\n")
            f.write("PMID: 87654321\n")
            f.write("CONTRAST: language > baseline\n")
            f.write("COORDINATE: (-50, 15, -10) MNI\n")
            f.write("DOMAIN: cognition.language\n")
            return Path(f.name)
    
    def test_load_experiments_from_file(self, sample_workspace):
        """Test loading experiments from workspace file."""
        loader = BrainMapUnifiedLoader(workspace_path=str(sample_workspace))
        experiments = loader.load_experiments()
        
        assert len(experiments) == 2
        
        # Check first experiment
        exp1 = experiments[0]
        assert exp1['experiment_id'] == 'BM_TEST_001'
        assert exp1['paper']['pmid'] == '12345678'
        assert len(exp1['coordinates']) == 2
        assert exp1['behavioral_domains'] == ['action.execution']
        
        # Cleanup
        sample_workspace.unlink()
    
    def test_generate_sample_data(self, loader):
        """Test sample data generation."""
        experiments = loader.load_experiments()
        
        assert len(experiments) > 0
        
        for exp in experiments:
            assert 'experiment_id' in exp
            assert 'coordinates' in exp
            assert all(c['space'] == 'MNI' for c in exp['coordinates'])
    
    def test_behavioral_domain_mapping(self, loader):
        """Test behavioral domain hierarchy mapping."""
        loader.load_experiments()
        domain_map = loader.map_behavioral_domains()
        
        # Check hierarchy is built
        assert 'action' in domain_map
        assert 'execution' in domain_map['action']
    
    def test_export_for_kg(self, loader):
        """Test export to knowledge graph format."""
        loader.load_experiments()
        kg_data = loader.export_for_kg()
        
        assert 'nodes' in kg_data
        assert 'edges' in kg_data
        assert 'metadata' in kg_data
        
        # Check node types
        node_types = set(n['type'] for n in kg_data['nodes'])
        assert 'Experiment' in node_types
        assert 'Coordinate' in node_types
        
        # Check edge types
        edge_types = set(e['type'] for e in kg_data['edges'])
        assert 'HAS_COORDINATE' in edge_types
    
    def test_statistics(self, loader):
        """Test statistics generation."""
        loader.load_experiments()
        stats = loader.get_statistics()
        
        assert 'total_experiments' in stats
        assert 'total_coordinates' in stats
        assert 'behavioral_domains' in stats
        assert 'validation_report' in stats
        
        assert stats['total_experiments'] > 0
        assert stats['total_coordinates'] > 0


class TestBrainMapEnhancements:
    """Test suite for enhanced BrainMap functionality."""
    
    @pytest.fixture
    def enhanced_loader(self):
        """Create enhanced loader instance."""
        return BrainMapUnifiedLoader(use_api=False)
    
    def test_parse_experiments_full(self, enhanced_loader):
        """Test full experiment parsing with metadata."""
        experiments = enhanced_loader.parse_experiments()
        
        assert len(experiments) > 0
        
        for exp in experiments:
            # Check enhanced fields
            assert 'experiment_id' in exp
            if 'contrasts' in exp:
                for contrast in exp['contrasts']:
                    # Should have parsed contrast details
                    assert isinstance(contrast, dict)
            
            if 'behavioral_domain_hierarchy' in exp:
                for domain in exp['behavioral_domain_hierarchy']:
                    assert 'full_path' in domain
                    assert 'levels' in domain
                    assert 'depth' in domain
    
    def test_extract_contrasts(self, enhanced_loader):
        """Test contrast extraction with statistics."""
        enhanced_loader.load_experiments()
        contrasts = enhanced_loader.extract_contrasts()
        
        assert isinstance(contrasts, list)
        
        for contrast in contrasts:
            assert 'name' in contrast
            assert 'experiment_id' in contrast
            assert 'statistical_threshold' in contrast
            assert 'correction_method' in contrast
    
    def test_map_domains_to_cognitive_atlas(self, enhanced_loader):
        """Test behavioral domain to CA concept mapping."""
        enhanced_loader.load_experiments()
        
        try:
            mappings = enhanced_loader.map_domains_to_cognitive_atlas()
            
            assert isinstance(mappings, dict)
            
            for domain, mapping in mappings.items():
                assert 'domain_info' in mapping
                assert 'ca_concepts' in mapping or 'best_match' in mapping
                
                if mapping.get('best_match'):
                    assert 'confidence' in mapping['best_match']
                    assert 'match_type' in mapping['best_match']
        except ImportError:
            # CA loader not available, check fallback
            mappings = enhanced_loader.map_domains_to_cognitive_atlas()
            assert isinstance(mappings, dict)
    
    def test_import_coordinates_with_metadata(self, enhanced_loader):
        """Test coordinate import with clustering."""
        enhanced_loader.load_experiments()
        coord_data = enhanced_loader.import_coordinates_with_metadata()
        
        assert 'coordinates' in coord_data
        assert 'n_clusters' in coord_data
        assert 'validation_report' in coord_data
        
        for coord in coord_data['coordinates']:
            assert 'experiment_id' in coord
            assert 'cluster_id' in coord
            assert 'x' in coord and 'y' in coord and 'z' in coord
    
    def test_coordinate_clustering(self, enhanced_loader):
        """Test DBSCAN coordinate clustering."""
        test_coords = [
            {'x': -45, 'y': 20, 'z': 8},
            {'x': -44, 'y': 21, 'z': 7},  # Close to first
            {'x': 40, 'y': -20, 'z': 50},  # Far from others
            {'x': 41, 'y': -19, 'z': 49}   # Close to third
        ]
        
        clusters = enhanced_loader._cluster_coordinates(test_coords, eps=5.0, min_samples=2)
        
        assert len(clusters) == len(test_coords)
        # Should have at least 2 clusters
        assert len(set(clusters)) >= 2
    
    def test_link_papers_to_pubmed(self, enhanced_loader):
        """Test PubMed paper linking."""
        enhanced_loader.load_experiments()
        
        try:
            paper_links = enhanced_loader.link_papers_to_pubmed()
            
            assert 'linked_papers' in paper_links
            assert 'missing_papers' in paper_links
            assert 'link_rate' in paper_links
            
            assert isinstance(paper_links['link_rate'], (int, float))
            assert 0 <= paper_links['link_rate'] <= 1
        except ImportError:
            # PubMed loader not available
            paper_links = enhanced_loader.link_papers_to_pubmed()
            assert paper_links['link_rate'] == 0
    
    def test_enhanced_kg_export(self, enhanced_loader):
        """Test enhanced knowledge graph export."""
        kg_data = enhanced_loader.export_for_kg()
        
        assert 'nodes' in kg_data
        assert 'edges' in kg_data
        assert 'metadata' in kg_data
        
        # Check enhanced metadata
        metadata = kg_data['metadata']
        assert 'n_clusters' in metadata
        assert 'paper_link_rate' in metadata
        assert 'n_domain_mappings' in metadata
        
        # Check node types
        node_types = set(n['type'] for n in kg_data['nodes'])
        assert 'Experiment' in node_types
        
        # Check for CA concept nodes if mapping worked
        if metadata['n_domain_mappings'] > 0:
            assert any(n['type'] == 'CognitiveAtlasConcept' for n in kg_data['nodes'])
        
        # Check edge types
        edge_types = set(e['type'] for e in kg_data['edges'])
        assert 'HAS_COORDINATE' in edge_types


class TestBrainMapParser:
    """Extended tests for enhanced parser functionality."""
    
    @pytest.fixture
    def parser(self):
        """Create parser instance."""
        return BrainMapParser()
    
    def test_parse_contrast_details(self, parser):
        """Test detailed contrast parsing."""
        # Test dict input
        contrast_dict = {
            'name': 'task > rest',
            'description': 'Task versus rest contrast',
            'statistical_threshold': 0.001,
            'correction_method': 'FWE'
        }
        
        parsed = parser.parse_contrast_details(contrast_dict)
        assert parsed['name'] == 'task > rest'
        assert parsed['statistical_threshold'] == 0.001
        assert parsed['correction_method'] == 'FWE'
        
        # Test string input
        contrast_str = "language > baseline (p<0.05, FDR)"
        parsed = parser.parse_contrast_details(contrast_str)
        assert parsed['name'] == contrast_str
        assert parsed['statistical_threshold'] == 0.05
        assert parsed['correction_method'] == 'FDR'
    
    def test_parse_behavioral_domain_hierarchy(self, parser):
        """Test behavioral domain hierarchy parsing."""
        domain = "cognition.language.speech"
        hierarchy = parser.parse_behavioral_domain_hierarchy(domain)
        
        assert hierarchy['full_path'] == domain
        assert hierarchy['levels'] == ['cognition', 'language', 'speech']
        assert hierarchy['depth'] == 3
        assert hierarchy['parent_domains'] == ['cognition', 'cognition.language']
        assert hierarchy['base_category'] == 'cognition'
        
        # Test single-level domain
        domain = "action"
        hierarchy = parser.parse_behavioral_domain_hierarchy(domain)
        assert hierarchy['depth'] == 1
        assert len(hierarchy['child_domains']) > 0
    
    def test_parse_study_metadata(self, parser):
        """Test study metadata parsing."""
        study_dict = {
            'study_design': 'event-related',
            'imaging_modality': 'PET',
            'field_strength': 7.0,
            'analysis_software': ['SPM12', 'FSL'],
            'demographic_info': {
                'n_subjects': 20,
                'mean_age': 25.5
            }
        }
        
        metadata = parser.parse_study_metadata(study_dict)
        assert metadata['study_design'] == 'event-related'
        assert metadata['imaging_modality'] == 'PET'
        assert metadata['field_strength'] == 7.0
        assert 'SPM12' in metadata['analysis_software']
    
    def test_parse_experiment_full(self, parser):
        """Test full experiment parsing."""
        exp_data = {
            'experiment_id': 'TEST_001',
            'contrasts': ['task > rest', 'rest > task'],
            'behavioral_domains': ['cognition.memory', 'action.execution'],
            'study_info': {
                'study_design': 'block',
                'imaging_modality': 'fMRI'
            }
        }
        
        parsed = parser.parse_experiment_full(exp_data)
        
        # Check contrast parsing
        assert all(isinstance(c, dict) for c in parsed['contrasts'])
        
        # Check domain hierarchy
        assert 'behavioral_domain_hierarchy' in parsed
        assert len(parsed['behavioral_domain_hierarchy']) == 2
        
        # Check study metadata
        assert 'study_metadata' in parsed
        assert parsed['study_metadata']['study_design'] == 'block'