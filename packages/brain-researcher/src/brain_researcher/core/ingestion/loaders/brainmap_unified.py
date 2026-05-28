"""Unified loader for BrainMap database."""

import os
import json
import logging
import tempfile
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import requests
from collections import defaultdict
import numpy as np
from sklearn.cluster import DBSCAN

from ..parsers.brainmap_parser import BrainMapParser

logger = logging.getLogger(__name__)


def _cache_root() -> Path:
    base = Path(os.getenv("XDG_CACHE_HOME", str(Path.home() / ".cache"))).expanduser()
    return base / "brain_researcher"


def _default_cache_dir(name: str) -> Path:
    return _cache_root() / name


class CoordinateValidator:
    """Validator for brain coordinates."""
    
    def __init__(self):
        self.invalid_coords = []
        self.valid_coords = []
    
    def validate_batch(self, coordinates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Validate a batch of coordinates.
        
        Args:
            coordinates: List of coordinate dicts
            
        Returns:
            List of valid coordinates
        """
        valid = []
        
        for coord in coordinates:
            if self._is_valid(coord):
                valid.append(coord)
                self.valid_coords.append(coord)
            else:
                self.invalid_coords.append(coord)
        
        return valid
    
    def _is_valid(self, coord: Dict[str, Any]) -> bool:
        """Check if coordinate is valid.
        
        Args:
            coord: Coordinate dict with x, y, z, space
            
        Returns:
            True if valid
        """
        # Basic bounds check
        bounds = {
            'MNI': {'x': (-90, 90), 'y': (-126, 91), 'z': (-72, 109)},
            'TAL': {'x': (-80, 80), 'y': (-110, 80), 'z': (-65, 85)}
        }
        
        space = coord.get('space', 'MNI')
        if space not in bounds:
            return False
        
        b = bounds[space]
        x, y, z = coord.get('x', 0), coord.get('y', 0), coord.get('z', 0)
        
        return (b['x'][0] <= x <= b['x'][1] and
                b['y'][0] <= y <= b['y'][1] and
                b['z'][0] <= z <= b['z'][1])
    
    def get_report(self) -> Dict[str, Any]:
        """Get validation report.
        
        Returns:
            Report with statistics
        """
        return {
            'total_validated': len(self.valid_coords) + len(self.invalid_coords),
            'valid': len(self.valid_coords),
            'invalid': len(self.invalid_coords),
            'invalid_samples': self.invalid_coords[:10]
        }


class BrainMapUnifiedLoader:
    """Unified loader for BrainMap experimental data."""
    
    def __init__(self, 
                workspace_path: Optional[str] = None,
                use_api: bool = False,
                cache_dir: Optional[str] = None):
        """Initialize loader.
        
        Args:
            workspace_path: Path to Sleuth workspace file
            use_api: Use BrainMap API instead of local file
            cache_dir: Directory for caching API responses
        """
        self.workspace_path = workspace_path
        self.use_api = use_api
        cache_dir = cache_dir or str(_default_cache_dir("brainmap_cache"))
        preferred_cache = Path(cache_dir).expanduser()
        try:
            preferred_cache.mkdir(parents=True, exist_ok=True)
            self.cache_dir = preferred_cache
        except Exception as exc:  # pragma: no cover
            fallback_root = _cache_root()
            try:
                fallback_root.mkdir(parents=True, exist_ok=True)
            except Exception:
                fallback_root = Path(tempfile.gettempdir()) / "brain_researcher"
                fallback_root.mkdir(parents=True, exist_ok=True)
            fallback = Path(
                tempfile.mkdtemp(prefix="brainmap_cache_", dir=str(fallback_root))
            )
            logger.warning(
                "BrainMap cache dir %s not writable (%s); using %s",
                preferred_cache,
                exc,
                fallback,
            )
            self.cache_dir = fallback
        
        self.parser = BrainMapParser()
        self.validator = CoordinateValidator()
        
        self.experiments = []
        self.behavioral_domain_map = {}
        self.paradigm_class_map = {}
    
    def load_experiments(self) -> List[Dict[str, Any]]:
        """Load experiments from workspace or API.
        
        Returns:
            List of experiment data
        """
        if self.use_api:
            experiments = self._load_from_api()
        else:
            if not self.workspace_path or not os.path.exists(self.workspace_path):
                logger.warning(f"Workspace path not found: {self.workspace_path}")
                # Use sample data for testing
                experiments = self._generate_sample_data()
            else:
                experiments = self.parser.parse_workspace(self.workspace_path)
        
        # Process experiments
        processed = []
        for exp in experiments:
            processed_exp = self._process_experiment(exp)
            if processed_exp:
                processed.append(processed_exp)
        
        self.experiments = processed
        logger.info(f"Loaded {len(processed)} experiments")
        
        return processed
    
    def _load_from_api(self) -> List[Dict[str, Any]]:
        """Load experiments from BrainMap API.
        
        Returns:
            List of experiments
        """
        # Check cache first
        cache_file = self.cache_dir / 'experiments.json'
        if cache_file.exists():
            with open(cache_file, 'r') as f:
                return json.load(f)
        
        # Note: Actual BrainMap API would require authentication
        # This is a placeholder for the API integration
        api_url = "https://brainmap.org/api/experiments"
        
        try:
            response = requests.get(api_url, timeout=30)
            if response.status_code == 200:
                experiments = response.json()
                
                # Cache the response
                with open(cache_file, 'w') as f:
                    json.dump(experiments, f)
                
                return experiments
        except Exception as e:
            logger.error(f"Failed to load from API: {e}")
        
        # Fallback to sample data
        return self._generate_sample_data()
    
    def _generate_sample_data(self) -> List[Dict[str, Any]]:
        """Generate sample BrainMap data for testing.
        
        Returns:
            Sample experiments
        """
        return [
            {
                'experiment_id': 'BM_001',
                'paper': {
                    'pmid': '12345678',
                    'title': 'Motor cortex activation during hand movements',
                    'authors': 'Smith et al.',
                    'year': '2020'
                },
                'contrasts': [
                    {'name': 'hand_movement > rest', 'description': 'Hand movement vs baseline'}
                ],
                'coordinates': [
                    {'x': -45, 'y': 20, 'z': 8, 'space': 'MNI'},
                    {'x': 42, 'y': 18, 'z': 10, 'space': 'MNI'},
                    {'x': -38, 'y': -25, 'z': 50, 'space': 'MNI'}
                ],
                'behavioral_domains': ['action.execution', 'action.imagination'],
                'paradigm_classes': ['finger_tapping', 'sequential_finger_tapping']
            },
            {
                'experiment_id': 'BM_002',
                'paper': {
                    'pmid': '87654321',
                    'title': 'Language processing in the brain',
                    'authors': 'Jones et al.',
                    'year': '2021'
                },
                'contrasts': [
                    {'name': 'words > nonwords', 'description': 'Word recognition'}
                ],
                'coordinates': [
                    {'x': -50, 'y': 15, 'z': -10, 'space': 'MNI'},
                    {'x': -45, 'y': 30, 'z': 5, 'space': 'MNI'}
                ],
                'behavioral_domains': ['cognition.language.speech'],
                'paradigm_classes': ['word_generation', 'naming']
            }
        ]
    
    def _process_experiment(self, exp: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Process single experiment.
        
        Args:
            exp: Raw experiment data
            
        Returns:
            Processed experiment or None if invalid
        """
        # Validate required fields
        if not exp.get('experiment_id'):
            logger.warning("Experiment missing ID, skipping")
            return None
        
        # Validate and convert coordinates
        coords = exp.get('coordinates', [])
        valid_coords = self.validator.validate_batch(coords)
        
        if not valid_coords:
            logger.warning(f"Experiment {exp['experiment_id']} has no valid coordinates")
            return None
        
        # Convert all to MNI
        mni_coords = []
        for coord in valid_coords:
            mni_coord = self.parser.convert_coordinate_space(coord, 'MNI')
            mni_coords.append(mni_coord)
        
        exp['coordinates'] = mni_coords
        
        # Process behavioral domains
        for domain in exp.get('behavioral_domains', []):
            self._update_domain_map(domain)
        
        # Process paradigm classes
        for paradigm in exp.get('paradigm_classes', []):
            self._update_paradigm_map(paradigm)
        
        return exp
    
    def _update_domain_map(self, domain: str):
        """Update behavioral domain mapping.
        
        Args:
            domain: Domain string like 'action.execution'
        """
        parts = domain.split('.')
        current = self.behavioral_domain_map
        
        for part in parts:
            if part not in current:
                current[part] = {}
            current = current[part]
    
    def _update_paradigm_map(self, paradigm: str):
        """Update paradigm class mapping.
        
        Args:
            paradigm: Paradigm class name
        """
        if paradigm not in self.paradigm_class_map:
            self.paradigm_class_map[paradigm] = 0
        self.paradigm_class_map[paradigm] += 1
    
    def map_behavioral_domains(self) -> Dict[str, Any]:
        """Map behavioral domains to Cognitive Atlas.
        
        Returns:
            Mapping of domains to concepts
        """
        # This would integrate with Cognitive Atlas
        # For now, return the domain hierarchy
        return self.behavioral_domain_map
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get loading statistics.
        
        Returns:
            Statistics dict
        """
        total_coords = sum(len(exp['coordinates']) for exp in self.experiments)
        unique_papers = len(set(exp.get('paper', {}).get('pmid', '') 
                               for exp in self.experiments if exp.get('paper')))
        
        return {
            'total_experiments': len(self.experiments),
            'total_coordinates': total_coords,
            'unique_papers': unique_papers,
            'behavioral_domains': len(self._flatten_domain_map()),
            'paradigm_classes': len(self.paradigm_class_map),
            'validation_report': self.validator.get_report()
        }
    
    def _flatten_domain_map(self, d: Optional[Dict] = None, prefix: str = '') -> List[str]:
        """Flatten domain hierarchy.
        
        Args:
            d: Domain dict
            prefix: Current prefix
            
        Returns:
            List of full domain paths
        """
        if d is None:
            d = self.behavioral_domain_map
        
        domains = []
        for key, value in d.items():
            full_key = f"{prefix}.{key}" if prefix else key
            domains.append(full_key)
            
            if isinstance(value, dict) and value:
                domains.extend(self._flatten_domain_map(value, full_key))
        
        return domains
    
    def parse_experiments(self) -> List[Dict[str, Any]]:
        """Parse BrainMap experiments with full metadata.
        
        Returns:
            List of fully parsed experiments
        """
        # Load raw experiments
        raw_experiments = self.load_experiments()
        
        # Parse each experiment with full details
        parsed_experiments = []
        for exp in raw_experiments:
            parsed_exp = self.parser.parse_experiment_full(exp)
            parsed_experiments.append(parsed_exp)
        
        logger.info(f"Parsed {len(parsed_experiments)} experiments with full details")
        return parsed_experiments
    
    def extract_contrasts(self, experiments: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """Extract all contrasts with statistical information.
        
        Args:
            experiments: List of experiments (uses self.experiments if None)
            
        Returns:
            List of all contrasts with metadata
        """
        if experiments is None:
            experiments = self.experiments
        
        all_contrasts = []
        for exp in experiments:
            exp_contrasts = exp.get('contrasts', [])
            
            for contrast in exp_contrasts:
                # Parse contrast details if not already parsed
                if isinstance(contrast, str):
                    contrast = self.parser.parse_contrast_details(contrast)
                elif isinstance(contrast, dict) and 'statistical_threshold' not in contrast:
                    contrast = self.parser.parse_contrast_details(contrast)
                
                # Add experiment reference
                contrast['experiment_id'] = exp.get('experiment_id')
                contrast['paper_pmid'] = exp.get('paper', {}).get('pmid')
                
                all_contrasts.append(contrast)
        
        logger.info(f"Extracted {len(all_contrasts)} contrasts from {len(experiments)} experiments")
        return all_contrasts
    
    def map_domains_to_cognitive_atlas(self) -> Dict[str, Any]:
        """Map BrainMap behavioral domains to Cognitive Atlas concepts.
        
        Returns:
            Mapping of domains to CA concepts with confidence scores
        """
        try:
            # Import CA loader
            from .cognitive_atlas_unified import CognitiveAtlasUnifiedLoader
            
            # Load Cognitive Atlas data
            ca_loader = CognitiveAtlasUnifiedLoader(use_niclip_data=True)
            ca_concepts = ca_loader.load_concepts()
            ca_mappings = ca_loader.load_mappings()
            
            # Build domain to concept mappings
            domain_mappings = {}
            
            for exp in self.experiments:
                for domain in exp.get('behavioral_domains', []):
                    if domain not in domain_mappings:
                        # Parse domain hierarchy
                        domain_info = self.parser.parse_behavioral_domain_hierarchy(domain)
                        
                        # Find matching CA concepts
                        matches = self._find_ca_concept_matches(
                            domain_info, ca_concepts, ca_mappings
                        )
                        
                        domain_mappings[domain] = {
                            'domain_info': domain_info,
                            'ca_concepts': matches,
                            'best_match': matches[0] if matches else None
                        }
            
            logger.info(f"Mapped {len(domain_mappings)} behavioral domains to Cognitive Atlas")
            return domain_mappings
            
        except ImportError:
            logger.warning("Cognitive Atlas loader not available, returning basic mapping")
            return self.behavioral_domain_map
    
    def _find_ca_concept_matches(self, domain_info: Dict[str, Any], 
                                 concepts: List[Dict[str, Any]], 
                                 mappings: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Find matching Cognitive Atlas concepts for a domain.
        
        Args:
            domain_info: Parsed domain hierarchy
            concepts: CA concepts list
            mappings: CA mappings
            
        Returns:
            List of matching concepts with confidence scores
        """
        matches = []
        domain_path = domain_info['full_path']
        domain_levels = domain_info['levels']
        
        # Try exact match first
        for concept in concepts:
            concept_name = concept.get('name', '').lower()
            
            # Exact match
            if domain_path.lower() == concept_name:
                matches.append({
                    'concept_id': concept.get('id'),
                    'concept_name': concept.get('name'),
                    'confidence': 1.0,
                    'match_type': 'exact'
                })
                continue
            
            # Partial match on any level
            for level in domain_levels:
                if level.lower() in concept_name:
                    confidence = 0.5 + (0.3 * (1 / (len(domain_levels))))
                    matches.append({
                        'concept_id': concept.get('id'),
                        'concept_name': concept.get('name'),
                        'confidence': confidence,
                        'match_type': 'partial'
                    })
                    break
        
        # Sort by confidence
        matches.sort(key=lambda x: x['confidence'], reverse=True)
        
        # Return top 5 matches
        return matches[:5]
    
    def import_coordinates_with_metadata(self) -> Dict[str, Any]:
        """Import coordinates with full metadata and clustering.
        
        Returns:
            Processed coordinates with clusters and anatomical labels
        """
        all_coordinates = []
        
        for exp in self.experiments:
            exp_coords = exp.get('coordinates', [])
            
            for i, coord in enumerate(exp_coords):
                # Validate coordinate
                if self.validator._is_valid(coord):
                    # Add metadata
                    coord_with_meta = coord.copy()
                    coord_with_meta.update({
                        'experiment_id': exp.get('experiment_id'),
                        'contrast_idx': i,
                        'paper_pmid': exp.get('paper', {}).get('pmid'),
                        'behavioral_domains': exp.get('behavioral_domains', [])
                    })
                    
                    all_coordinates.append(coord_with_meta)
        
        # Perform spatial clustering
        if all_coordinates:
            clusters = self._cluster_coordinates(all_coordinates)
            
            # Add cluster labels to coordinates
            for coord, cluster_id in zip(all_coordinates, clusters):
                coord['cluster_id'] = int(cluster_id)
        
        logger.info(f"Imported {len(all_coordinates)} coordinates with metadata")
        
        return {
            'coordinates': all_coordinates,
            'n_clusters': len(set(clusters)) if all_coordinates else 0,
            'validation_report': self.validator.get_report()
        }
    
    def _cluster_coordinates(self, coordinates: List[Dict[str, Any]], 
                            eps: float = 10.0, min_samples: int = 5) -> np.ndarray:
        """Cluster coordinates using DBSCAN.
        
        Args:
            coordinates: List of coordinate dictionaries
            eps: Maximum distance between samples in cluster (mm)
            min_samples: Minimum samples in cluster
            
        Returns:
            Array of cluster labels
        """
        # Extract coordinate values
        coord_array = np.array([[c['x'], c['y'], c['z']] for c in coordinates])
        
        # Perform clustering
        clustering = DBSCAN(eps=eps, min_samples=min_samples).fit(coord_array)
        
        return clustering.labels_
    
    def link_papers_to_pubmed(self) -> Dict[str, Any]:
        """Link BrainMap papers to PubMed database.
        
        Returns:
            Linking results with statistics
        """
        try:
            # Import PubMed loader
            from .pubmed_unified import PubMedUnifiedLoader
            
            pubmed_loader = PubMedUnifiedLoader(use_niclip=False)  # Direct API access
            
            linked_papers = []
            missing_papers = []
            
            # Get unique papers
            papers_to_link = {}
            for exp in self.experiments:
                if exp.get('paper'):
                    pmid = exp['paper'].get('pmid')
                    if pmid and pmid not in papers_to_link:
                        papers_to_link[pmid] = exp['paper']
            
            logger.info(f"Linking {len(papers_to_link)} unique papers to PubMed")
            
            # Link each paper
            for pmid, paper_info in papers_to_link.items():
                try:
                    # Fetch from PubMed
                    pubmed_data = pubmed_loader.fetch_papers_by_pmids([pmid])
                    
                    if pubmed_data:
                        paper_data = pubmed_data[0]
                        # Merge BrainMap and PubMed data
                        merged_paper = {**paper_info, **paper_data}
                        linked_papers.append(merged_paper)
                    else:
                        missing_papers.append(pmid)
                        
                except Exception as e:
                    logger.warning(f"Failed to link PMID {pmid}: {e}")
                    missing_papers.append(pmid)
            
            return {
                'linked_papers': linked_papers,
                'missing_papers': missing_papers,
                'link_rate': len(linked_papers) / len(papers_to_link) if papers_to_link else 0
            }
            
        except ImportError:
            logger.warning("PubMed loader not available, skipping paper linking")
            return {
                'linked_papers': [],
                'missing_papers': list(papers_to_link.keys()) if 'papers_to_link' in locals() else [],
                'link_rate': 0
            }
    
    def export_for_kg(self) -> Dict[str, Any]:
        """Export data formatted for knowledge graph.
        
        Returns:
            KG-ready data
        """
        nodes = []
        edges = []
        
        # Parse experiments if not already done
        if not self.experiments:
            self.parse_experiments()
        
        # Extract all components
        contrasts = self.extract_contrasts()
        domain_mappings = self.map_domains_to_cognitive_atlas()
        coord_data = self.import_coordinates_with_metadata()
        paper_links = self.link_papers_to_pubmed()
        
        for exp in self.experiments:
            # Create experiment node with full metadata
            exp_node = {
                'id': exp['experiment_id'],
                'type': 'Experiment',
                'properties': {
                    'contrasts': exp.get('contrasts', []),
                    'paradigm_classes': exp.get('paradigm_classes', []),
                    'behavioral_domains': exp.get('behavioral_domains', []),
                    'study_metadata': exp.get('study_metadata', {})
                }
            }
            nodes.append(exp_node)
            
            # Create paper node if exists
            if exp.get('paper'):
                paper_id = f"pmid_{exp['paper']['pmid']}"
                
                # Find linked paper data
                linked_paper = next((p for p in paper_links.get('linked_papers', []) 
                                    if p.get('pmid') == exp['paper']['pmid']), 
                                   exp['paper'])
                
                nodes.append({
                    'id': paper_id,
                    'type': 'Publication',
                    'properties': linked_paper
                })
                
                # Link experiment to paper
                edges.append({
                    'source': exp['experiment_id'],
                    'target': paper_id,
                    'type': 'DERIVED_FROM'
                })
            
            # Create coordinate nodes with cluster info
            exp_coords = [c for c in coord_data.get('coordinates', []) 
                         if c['experiment_id'] == exp['experiment_id']]
            
            for coord in exp_coords:
                coord_id = f"{exp['experiment_id']}_coord_{coord.get('contrast_idx', 0)}"
                nodes.append({
                    'id': coord_id,
                    'type': 'Coordinate',
                    'properties': coord
                })
                
                # Link experiment to coordinate
                edges.append({
                    'source': exp['experiment_id'],
                    'target': coord_id,
                    'type': 'HAS_COORDINATE'
                })
            
            # Create domain-concept links
            for domain in exp.get('behavioral_domains', []):
                if domain in domain_mappings:
                    mapping = domain_mappings[domain]
                    if mapping.get('best_match'):
                        # Create concept node if not exists
                        concept_id = f"ca_{mapping['best_match']['concept_id']}"
                        nodes.append({
                            'id': concept_id,
                            'type': 'CognitiveAtlasConcept',
                            'properties': mapping['best_match']
                        })
                        
                        # Link experiment to concept
                        edges.append({
                            'source': exp['experiment_id'],
                            'target': concept_id,
                            'type': 'MEASURES_CONCEPT',
                            'properties': {
                                'confidence': mapping['best_match']['confidence'],
                                'domain': domain
                            }
                        })
        
        return {
            'nodes': nodes,
            'edges': edges,
            'metadata': {
                **self.get_statistics(),
                'n_clusters': coord_data.get('n_clusters', 0),
                'paper_link_rate': paper_links.get('link_rate', 0),
                'n_domain_mappings': len(domain_mappings)
            }
        }
