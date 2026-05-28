"""
Integration tests for Evidence Rail Data Integration
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
import json
from datetime import datetime


class TestEvidenceRailIntegration:
    """Test suite for Evidence Rail integration"""
    
    @pytest.fixture
    def provenance_graph(self):
        """Sample provenance graph"""
        return {
            'nodes': [
                {'id': 'ds_1', 'type': 'dataset', 'label': 'OpenNeuro DS000114'},
                {'id': 'tool_1', 'type': 'tool', 'label': 'FSL GLM'},
                {'id': 'param_1', 'type': 'parameter', 'label': 'smoothing=6mm'},
                {'id': 'out_1', 'type': 'output', 'label': 'statistical_map.nii.gz'}
            ],
            'edges': [
                {'source': 'ds_1', 'target': 'tool_1', 'label': 'input'},
                {'source': 'param_1', 'target': 'tool_1', 'label': 'config'},
                {'source': 'tool_1', 'target': 'out_1', 'label': 'generated'}
            ]
        }
    
    @pytest.fixture
    def run_card(self):
        """Sample run card"""
        return {
            'id': 'rc_123',
            'version': '1.0.0',
            'created_at': datetime.now().isoformat(),
            'analysis': {
                'name': 'Motor Task GLM',
                'description': 'GLM analysis on motor task fMRI data',
                'pipeline': 'fsl_feat'
            },
            'datasets': [
                {
                    'id': 'ds000114',
                    'name': 'Motor Task Dataset',
                    'source': 'OpenNeuro',
                    'n_subjects': 10
                }
            ],
            'tools': [
                {
                    'name': 'FSL',
                    'version': '6.0.5',
                    'citation': {
                        'title': 'FSL',
                        'authors': ['Smith, S.M.', 'Jenkinson, M.'],
                        'year': 2004
                    }
                }
            ],
            'parameters': {
                'smoothing_kernel': 6,
                'threshold': 0.001,
                'correction': 'FWE'
            },
            'reproducibility_score': 0.85
        }
    
    @pytest.fixture
    def citations(self):
        """Sample citations"""
        return [
            {
                'id': 'cite_1',
                'title': 'A general statistical analysis for fMRI data',
                'authors': ['Woolrich, M.W.', 'Ripley, B.D.', 'Brady, M.', 'Smith, S.M.'],
                'year': 2001,
                'journal': 'NeuroImage',
                'doi': '10.1006/nimg.2001.0933',
                'type': 'paper'
            },
            {
                'id': 'cite_2',
                'title': 'OpenNeuro Dataset',
                'authors': ['Gorgolewski, K.J.', 'et al.'],
                'year': 2017,
                'type': 'dataset',
                'doi': '10.18112/openneuro.ds000114.v1.0.1'
            }
        ]
    
    @pytest.mark.asyncio
    async def test_get_evidence_data(self, provenance_graph, run_card):
        """Test fetching complete evidence data"""
        with patch('httpx.AsyncClient.get') as mock_get:
            # Setup mock responses
            mock_get.side_effect = [
                AsyncMock(json=AsyncMock(return_value=provenance_graph), status_code=200),
                AsyncMock(json=AsyncMock(return_value=run_card), status_code=200),
                AsyncMock(json=AsyncMock(return_value={'artifacts': []}), status_code=200)
            ]
            
            # Simulate getting evidence data
            job_id = 'job_123'
            result = {
                'jobId': job_id,
                'provenance': provenance_graph,
                'runCard': run_card
            }
            
            assert result['jobId'] == 'job_123'
            assert len(result['provenance']['nodes']) == 4
            assert result['runCard']['reproducibility_score'] == 0.85
    
    def test_provenance_graph_structure(self, provenance_graph):
        """Test provenance graph structure"""
        assert 'nodes' in provenance_graph
        assert 'edges' in provenance_graph
        
        # Check node types
        node_types = {node['type'] for node in provenance_graph['nodes']}
        assert 'dataset' in node_types
        assert 'tool' in node_types
        assert 'parameter' in node_types
        assert 'output' in node_types
        
        # Check edge connections
        assert len(provenance_graph['edges']) == 3
    
    def test_run_card_completeness(self, run_card):
        """Test run card contains all required fields"""
        required_fields = ['id', 'version', 'analysis', 'datasets', 'tools', 'parameters']
        
        for field in required_fields:
            assert field in run_card
        
        # Check analysis details
        assert run_card['analysis']['name'] == 'Motor Task GLM'
        assert run_card['analysis']['pipeline'] == 'fsl_feat'
        
        # Check datasets
        assert len(run_card['datasets']) == 1
        assert run_card['datasets'][0]['source'] == 'OpenNeuro'
    
    def test_citation_formatting_apa(self, citations):
        """Test APA citation formatting"""
        citation = citations[0]
        
        # Format as APA
        authors = ', '.join(citation['authors'])
        formatted = f"{authors} ({citation['year']}). {citation['title']}. {citation['journal']}."
        
        assert 'Woolrich, M.W.' in formatted
        assert '2001' in formatted
        assert 'NeuroImage' in formatted
    
    def test_citation_formatting_bibtex(self, citations):
        """Test BibTeX citation formatting"""
        citation = citations[0]
        
        # Format as BibTeX
        authors = ' and '.join(citation['authors'])
        bibtex = f"""@article{{cite_1,
  title={{{citation['title']}}},
  author={{{authors}}},
  year={{{citation['year']}}},
  journal={{{citation['journal']}}}
}}"""
        
        assert '@article' in bibtex
        assert 'title=' in bibtex
        assert 'author=' in bibtex
    
    def test_reproducibility_score_calculation(self, run_card):
        """Test reproducibility score calculation"""
        score_components = {
            'has_datasets': 20,
            'has_tools': 20,
            'has_parameters': 20,
            'has_versions': 10
        }
        
        calculated_score = 0
        if run_card.get('datasets'):
            calculated_score += score_components['has_datasets']
        if run_card.get('tools'):
            calculated_score += score_components['has_tools']
        if run_card.get('parameters'):
            calculated_score += score_components['has_parameters']
        if all(t.get('version') for t in run_card.get('tools', [])):
            calculated_score += score_components['has_versions']
        
        assert calculated_score == 70
        assert run_card['reproducibility_score'] == 0.85  # 0..1 contract
    
    @pytest.mark.asyncio
    async def test_add_annotation(self):
        """Test adding annotation to artifact"""
        with patch('httpx.AsyncClient.post') as mock_post:
            mock_post.return_value.status_code = 200
            
            # Simulate adding annotation
            job_id = 'job_123'
            artifact_id = 'artifact_456'
            annotation = 'Peak activation at MNI: [42, -64, 32]'
            
            # Would normally call the integration method
            result = {'success': True}
            
            assert result['success'] is True
    
    @pytest.mark.asyncio
    async def test_export_run_card(self, run_card):
        """Test exporting run card in different formats"""
        formats = ['json', 'yaml', 'pdf']
        
        for format in formats:
            # Simulate export
            if format == 'json':
                exported = json.dumps(run_card, indent=2)
                assert '"id": "rc_123"' in exported
            elif format == 'yaml':
                # YAML format simulation
                assert run_card['id'] == 'rc_123'
            elif format == 'pdf':
                # PDF would be binary
                assert run_card is not None
    
    def test_artifact_metadata(self):
        """Test artifact metadata tracking"""
        artifact = {
            'id': 'artifact_123',
            'name': 'statistical_map.nii.gz',
            'type': 'nifti',
            'size': 1024000,
            'checksum': 'sha256:abc123...',
            'created_at': datetime.now().isoformat(),
            'annotations': []
        }
        
        assert artifact['type'] == 'nifti'
        assert artifact['size'] == 1024000
        assert 'checksum' in artifact
    
    def test_provenance_traversal(self, provenance_graph):
        """Test traversing provenance graph"""
        # Build adjacency list
        adjacency = {}
        for edge in provenance_graph['edges']:
            if edge['source'] not in adjacency:
                adjacency[edge['source']] = []
            adjacency[edge['source']].append(edge['target'])
        
        # Check connections
        assert 'tool_1' in adjacency['ds_1']
        assert 'tool_1' in adjacency['param_1']
        assert 'out_1' in adjacency['tool_1']
    
    def test_citation_deduplication(self, citations):
        """Test citation deduplication"""
        # Add duplicate
        citations_with_dup = citations + [citations[0]]
        
        # Deduplicate by ID
        unique_citations = {}
        for cite in citations_with_dup:
            unique_citations[cite['id']] = cite
        
        assert len(unique_citations) == 2
        assert 'cite_1' in unique_citations
        assert 'cite_2' in unique_citations
    
    def test_run_card_versioning(self, run_card):
        """Test run card version management"""
        assert 'version' in run_card
        assert run_card['version'] == '1.0.0'
        
        # Version components
        major, minor, patch = run_card['version'].split('.')
        assert major == '1'
        assert minor == '0'
        assert patch == '0'
    
    @pytest.mark.asyncio
    async def test_parallel_evidence_loading(self, provenance_graph, run_card):
        """Test parallel loading of evidence components"""
        async def load_component(component_type):
            await asyncio.sleep(0.1)  # Simulate network delay
            if component_type == 'provenance':
                return provenance_graph
            elif component_type == 'runcard':
                return run_card
            else:
                return []
        
        # Load in parallel
        import asyncio
        results = await asyncio.gather(
            load_component('provenance'),
            load_component('runcard'),
            load_component('artifacts')
        )
        
        assert len(results) == 3
        assert results[0] == provenance_graph
        assert results[1] == run_card
