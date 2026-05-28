"""Unified loader for UK Biobank brain imaging data."""

import os
import json
import logging
import tempfile
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
import hashlib

logger = logging.getLogger(__name__)


def _cache_root() -> Path:
    base = Path(os.getenv("XDG_CACHE_HOME", str(Path.home() / ".cache"))).expanduser()
    return base / "brain_researcher"


def _default_cache_dir(name: str) -> Path:
    return _cache_root() / name


class UKBiobankUnifiedLoader:
    """Loader for UK Biobank neuroimaging and phenotype data.
    
    Supports loading:
    - 40,000+ subjects with brain imaging
    - Phenotype data (demographics, lifestyle, health)
    - Imaging metrics (structural, functional, diffusion)
    - Genetic markers (SNPs, polygenic risk scores)
    - Quality assessment metrics
    """
    
    def __init__(self,
                 data_dir: Optional[str] = None,
                 phenotype_file: Optional[str] = None,
                 imaging_dir: Optional[str] = None,
                 genetic_dir: Optional[str] = None,
                 cache_dir: Optional[str] = None):
        """Initialize UK Biobank loader.
        
        Args:
            data_dir: Base UK Biobank data directory
            phenotype_file: Path to phenotype CSV file
            imaging_dir: Directory containing imaging data
            genetic_dir: Directory containing genetic data
            cache_dir: Cache directory for processed data
        """
        self.data_dir = Path(data_dir) if data_dir else None
        self.phenotype_file = Path(phenotype_file) if phenotype_file else None
        self.imaging_dir = Path(imaging_dir) if imaging_dir else None
        self.genetic_dir = Path(genetic_dir) if genetic_dir else None
        cache_dir = cache_dir or str(_default_cache_dir("ukbiobank_cache"))
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
                tempfile.mkdtemp(prefix="ukbiobank_cache_", dir=str(fallback_root))
            )
            logger.warning(
                "Default UKB cache dir %s not writable (%s); using %s",
                preferred_cache,
                exc,
                fallback,
            )
            self.cache_dir = fallback
        
        # UK Biobank data structure
        self.subjects = []
        self.phenotype_data = {}
        self.imaging_metrics = {}
        self.genetic_markers = {}
        self.quality_scores = {}
        
        # UK Biobank field IDs for key variables
        self.field_mappings = {
            # Demographics
            '31': 'sex',
            '21003': 'age_at_recruitment',
            '53': 'date_of_assessment',
            '54': 'assessment_centre',
            
            # Brain imaging
            '25781': 't1_volume_grey_matter',
            '25782': 't1_volume_white_matter',
            '25783': 't1_volume_csf',
            '25784': 't1_total_brain_volume',
            '25785': 'hippocampus_volume_left',
            '25786': 'hippocampus_volume_right',
            
            # Cognitive measures
            '20016': 'fluid_intelligence',
            '20023': 'reaction_time',
            '20127': 'neuroticism_score',
            '20128': 'depression_score',
            
            # Health conditions
            '20002': 'self_reported_conditions',
            '41270': 'icd10_diagnoses',
            '40001': 'death_date',
            '40000': 'death_cause',
            
            # Genetics
            '22009': 'genetic_principal_components',
            '22182': 'heterozygosity',
            '22027': 'genetic_sex',
        }
        
        # Imaging modalities available
        self.imaging_modalities = [
            'T1_structural',
            'T2_FLAIR',
            'resting_fMRI',
            'task_fMRI',
            'diffusion_MRI',
            'susceptibility_weighted',
            'arterial_spin_labelling'
        ]
        
        # Quality control metrics
        self.qc_metrics = [
            'motion_parameters',
            'signal_to_noise',
            'registration_quality',
            'segmentation_quality',
            'completeness_score'
        ]
    
    def load_subjects(self, 
                     subject_file: Optional[str] = None,
                     n_subjects: Optional[int] = None,
                     demo_mode: bool = False) -> List[str]:
        """Load UK Biobank subject IDs.
        
        Args:
            subject_file: Path to file with subject IDs
            n_subjects: Limit to first N subjects
            demo_mode: Use synthetic data for testing
            
        Returns:
            List of subject IDs
        """
        if demo_mode:
            # Generate synthetic subject IDs for testing
            subjects = self._generate_demo_subjects(n_subjects or 100)
        elif subject_file:
            subjects_df = pd.read_csv(subject_file, header=None, names=['eid'])
            subjects = subjects_df['eid'].astype(str).tolist()
            if n_subjects:
                subjects = subjects[:n_subjects]
        elif self.phenotype_file and self.phenotype_file.exists():
            # Extract from phenotype file
            phenotype_df = pd.read_csv(self.phenotype_file, nrows=1)
            if 'eid' in phenotype_df.columns:
                full_df = pd.read_csv(self.phenotype_file, usecols=['eid'])
                subjects = full_df['eid'].astype(str).tolist()
                if n_subjects:
                    subjects = subjects[:n_subjects]
            else:
                raise ValueError("No 'eid' column found in phenotype file")
        else:
            raise ValueError(
                "No UK Biobank data source specified. Please provide either:\n"
                "1. A subject file with participant IDs\n"
                "2. A phenotype file with 'eid' column\n"
                "3. Set demo_mode=True for synthetic test data"
            )
        
        self.subjects = subjects
        logger.info(f"Loaded {len(subjects)} UK Biobank subjects")
        return subjects
    
    def load_phenotype_data(self,
                           fields: Optional[List[str]] = None,
                           demo_mode: bool = False) -> Dict[str, pd.DataFrame]:
        """Load UK Biobank phenotype data.
        
        Args:
            fields: Specific field IDs to load (None = all)
            demo_mode: Use synthetic data for testing
            
        Returns:
            Dictionary with phenotype data by category
        """
        if demo_mode:
            phenotype_data = self._generate_demo_phenotypes()
        elif self.phenotype_file and self.phenotype_file.exists():
            # Load real phenotype data
            if fields:
                cols = ['eid'] + [f"f.{f}.0.0" for f in fields]
                phenotype_df = pd.read_csv(self.phenotype_file, usecols=cols)
            else:
                phenotype_df = pd.read_csv(self.phenotype_file)
            
            # Organize by category
            phenotype_data = {
                'demographics': self._extract_demographics(phenotype_df),
                'cognitive': self._extract_cognitive(phenotype_df),
                'health': self._extract_health(phenotype_df),
                'lifestyle': self._extract_lifestyle(phenotype_df)
            }
        else:
            raise ValueError(
                "Phenotype file not found. Please provide a valid UK Biobank "
                "phenotype CSV file or use demo_mode=True"
            )
        
        self.phenotype_data = phenotype_data
        logger.info(f"Loaded phenotype data for {len(self.subjects)} subjects")
        return phenotype_data
    
    def load_imaging_metrics(self,
                           modalities: Optional[List[str]] = None,
                           demo_mode: bool = False) -> Dict[str, Any]:
        """Load UK Biobank imaging metrics.
        
        Args:
            modalities: Specific imaging modalities to load
            demo_mode: Use synthetic data for testing
            
        Returns:
            Dictionary with imaging metrics by modality
        """
        if demo_mode:
            imaging_metrics = self._generate_demo_imaging()
            if modalities:
                imaging_metrics = {
                    key: value
                    for key, value in imaging_metrics.items()
                    if key in modalities
                }
            modalities = list(imaging_metrics.keys())
        elif self.imaging_dir and self.imaging_dir.exists():
            imaging_metrics = {}
            modalities = modalities or self.imaging_modalities
            
            for modality in modalities:
                modality_dir = self.imaging_dir / modality
                if modality_dir.exists():
                    imaging_metrics[modality] = self._load_modality_data(modality_dir)
                else:
                    logger.warning(f"Modality directory not found: {modality_dir}")
        else:
            raise ValueError(
                "Imaging directory not found. Please provide a valid UK Biobank "
                "imaging directory or use demo_mode=True"
            )
        
        self.imaging_metrics = imaging_metrics
        logger.info(f"Loaded imaging metrics for {len(imaging_metrics)} modalities")
        return imaging_metrics
    
    def load_genetic_markers(self,
                           marker_types: Optional[List[str]] = None,
                           demo_mode: bool = False) -> Dict[str, Any]:
        """Load UK Biobank genetic data.
        
        Args:
            marker_types: Types of genetic markers to load
            demo_mode: Use synthetic data for testing
            
        Returns:
            Dictionary with genetic marker data
        """
        if demo_mode:
            genetic_markers = self._generate_demo_genetics()
            if marker_types:
                genetic_markers = {
                    key: value
                    for key, value in genetic_markers.items()
                    if key in marker_types
                }
        elif self.genetic_dir and self.genetic_dir.exists():
            genetic_markers = {}
            marker_types = marker_types or ['snps', 'polygenic_scores', 'ancestry']
            
            for marker_type in marker_types:
                if marker_type == 'snps':
                    genetic_markers['snps'] = self._load_snp_data()
                elif marker_type == 'polygenic_scores':
                    genetic_markers['polygenic_scores'] = self._load_prs_data()
                elif marker_type == 'ancestry':
                    genetic_markers['ancestry'] = self._load_ancestry_data()
        else:
            raise ValueError(
                "Genetic directory not found. Please provide a valid UK Biobank "
                "genetic directory or use demo_mode=True"
            )
        
        self.genetic_markers = genetic_markers
        logger.info(f"Loaded genetic markers: {list(genetic_markers.keys())}")
        return genetic_markers
    
    def calculate_quality_scores(self) -> Dict[str, float]:
        """Calculate data quality scores.
        
        Returns:
            Dictionary with quality metrics
        """
        quality_scores = {
            'data_completeness': self._calculate_completeness(),
            'phenotype_coverage': self._calculate_phenotype_coverage(),
            'imaging_quality': self._calculate_imaging_quality(),
            'genetic_coverage': self._calculate_genetic_coverage(),
            'overall_quality': 0.0
        }
        
        # Calculate overall quality score
        weights = [0.25, 0.25, 0.25, 0.25]
        quality_scores['overall_quality'] = sum(
            w * quality_scores[k] for w, k in zip(
                weights, 
                ['data_completeness', 'phenotype_coverage', 
                 'imaging_quality', 'genetic_coverage']
            )
        )
        
        self.quality_scores = quality_scores
        logger.info(f"Overall quality score: {quality_scores['overall_quality']:.2f}")
        return quality_scores
    
    def export_to_knowledge_graph(self) -> Dict[str, Any]:
        """Export UK Biobank data for knowledge graph integration.
        
        Returns:
            Dictionary with graph-ready data
        """
        kg_data = {
            'nodes': [],
            'edges': [],
            'metadata': {
                'source': 'UK_Biobank',
                'version': '2024.1',
                'n_subjects': len(self.subjects),
                'timestamp': datetime.now().isoformat()
            }
        }
        
        # Create subject nodes
        for subject_id in self.subjects[:100]:  # Limit for demo
            kg_data['nodes'].append({
                'id': f"ukb_{subject_id}",
                'type': 'Subject',
                'properties': {
                    'cohort': 'UK_Biobank',
                    'has_imaging': subject_id in self.imaging_metrics.get('T1_structural', {}).get('subjects', []),
                    'has_genetics': subject_id in self.genetic_markers.get('snps', {}).get('subjects', [])
                }
            })
        
        # Create phenotype nodes and edges
        for category, data in self.phenotype_data.items():
            if isinstance(data, pd.DataFrame) and not data.empty:
                for col in data.columns:
                    if col != 'eid':
                        node_id = f"ukb_phenotype_{col}"
                        kg_data['nodes'].append({
                            'id': node_id,
                            'type': 'Phenotype',
                            'properties': {
                                'category': category,
                                'field_name': col,
                                'data_type': str(data[col].dtype)
                            }
                        })
        
        logger.info(f"Exported {len(kg_data['nodes'])} nodes to knowledge graph")
        return kg_data
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get summary statistics of loaded data.
        
        Returns:
            Dictionary with summary statistics
        """
        stats = {
            'n_subjects': len(self.subjects),
            'phenotype_fields': sum(
                len(df.columns) - 1 for df in self.phenotype_data.values() 
                if isinstance(df, pd.DataFrame)
            ),
            'imaging_modalities': len(self.imaging_metrics),
            'genetic_markers': sum(
                len(data.get('markers', [])) for data in self.genetic_markers.values()
            ),
            'quality_scores': self.quality_scores,
            'data_summary': {
                'has_phenotypes': bool(self.phenotype_data),
                'has_imaging': bool(self.imaging_metrics),
                'has_genetics': bool(self.genetic_markers)
            }
        }
        
        return stats
    
    # Private helper methods
    
    def _generate_demo_subjects(self, n: int = 100) -> List[str]:
        """Generate demo subject IDs."""
        np.random.seed(42)
        return [f"{1000000 + i}" for i in range(n)]
    
    def _generate_demo_phenotypes(self) -> Dict[str, pd.DataFrame]:
        """Generate demo phenotype data."""
        np.random.seed(42)
        n = len(self.subjects) if self.subjects else 100
        
        demographics = pd.DataFrame({
            'eid': self.subjects[:n] if self.subjects else self._generate_demo_subjects(n),
            'age': np.random.normal(60, 10, n),
            'sex': np.random.choice([0, 1], n),
            'bmi': np.random.normal(26, 4, n),
            'education_years': np.random.normal(14, 3, n)
        })
        
        cognitive = pd.DataFrame({
            'eid': demographics['eid'],
            'fluid_intelligence': np.random.normal(8, 2, n),
            'reaction_time': np.random.normal(550, 100, n),
            'memory_score': np.random.normal(10, 3, n)
        })
        
        health = pd.DataFrame({
            'eid': demographics['eid'],
            'systolic_bp': np.random.normal(130, 20, n),
            'diastolic_bp': np.random.normal(80, 10, n),
            'diabetes': np.random.choice([0, 1], n, p=[0.9, 0.1]),
            'hypertension': np.random.choice([0, 1], n, p=[0.7, 0.3])
        })
        
        lifestyle = pd.DataFrame({
            'eid': demographics['eid'],
            'smoking_status': np.random.choice([0, 1, 2], n),
            'alcohol_frequency': np.random.choice(range(6), n),
            'physical_activity': np.random.normal(2000, 500, n)
        })
        
        return {
            'demographics': demographics,
            'cognitive': cognitive,
            'health': health,
            'lifestyle': lifestyle
        }
    
    def _generate_demo_imaging(self) -> Dict[str, Any]:
        """Generate demo imaging metrics."""
        np.random.seed(42)
        n = min(len(self.subjects), 50) if self.subjects else 50
        
        imaging_metrics = {
            'T1_structural': {
                'subjects': self.subjects[:n] if self.subjects else self._generate_demo_subjects(n),
                'grey_matter_volume': np.random.normal(600000, 50000, n),
                'white_matter_volume': np.random.normal(500000, 40000, n),
                'csf_volume': np.random.normal(250000, 30000, n),
                'hippocampus_left': np.random.normal(3500, 400, n),
                'hippocampus_right': np.random.normal(3600, 400, n)
            },
            'resting_fMRI': {
                'subjects': self.subjects[:n] if self.subjects else self._generate_demo_subjects(n),
                'default_mode_connectivity': np.random.normal(0.3, 0.1, n),
                'executive_control_connectivity': np.random.normal(0.25, 0.08, n),
                'salience_network_connectivity': np.random.normal(0.28, 0.09, n)
            },
            'diffusion_MRI': {
                'subjects': self.subjects[:n] if self.subjects else self._generate_demo_subjects(n),
                'mean_fa': np.random.normal(0.45, 0.05, n),
                'mean_md': np.random.normal(0.0008, 0.0001, n),
                'tract_volumes': np.random.normal(150000, 20000, n)
            }
        }
        
        return imaging_metrics
    
    def _generate_demo_genetics(self) -> Dict[str, Any]:
        """Generate demo genetic data."""
        np.random.seed(42)
        n = min(len(self.subjects), 30) if self.subjects else 30
        
        genetic_markers = {
            'snps': {
                'subjects': self.subjects[:n] if self.subjects else self._generate_demo_subjects(n),
                'markers': ['rs' + str(i) for i in range(1000000, 1000100)],
                'allele_frequencies': np.random.uniform(0.01, 0.5, 100)
            },
            'polygenic_scores': {
                'subjects': self.subjects[:n] if self.subjects else self._generate_demo_subjects(n),
                'alzheimers_prs': np.random.normal(0, 1, n),
                'parkinsons_prs': np.random.normal(0, 1, n),
                'depression_prs': np.random.normal(0, 1, n),
                'schizophrenia_prs': np.random.normal(0, 1, n)
            },
            'ancestry': {
                'subjects': self.subjects[:n] if self.subjects else self._generate_demo_subjects(n),
                'pc1': np.random.normal(0, 1, n),
                'pc2': np.random.normal(0, 1, n),
                'pc3': np.random.normal(0, 1, n),
                'ancestry_group': np.random.choice(['EUR', 'AFR', 'EAS', 'SAS'], n, p=[0.85, 0.05, 0.05, 0.05])
            }
        }
        
        return genetic_markers
    
    def _extract_demographics(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extract demographic variables from phenotype data."""
        demo_cols = ['eid']
        for field_id, name in self.field_mappings.items():
            col = f"f.{field_id}.0.0"
            if col in df.columns:
                demo_cols.append(col)
        
        if len(demo_cols) > 1:
            return df[demo_cols].copy()
        return pd.DataFrame({'eid': df['eid'] if 'eid' in df.columns else []})
    
    def _extract_cognitive(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extract cognitive variables from phenotype data."""
        cognitive_fields = ['20016', '20023', '20127', '20128']
        cog_cols = ['eid']
        
        for field in cognitive_fields:
            col = f"f.{field}.0.0"
            if col in df.columns:
                cog_cols.append(col)
        
        if len(cog_cols) > 1:
            return df[cog_cols].copy()
        return pd.DataFrame({'eid': df['eid'] if 'eid' in df.columns else []})
    
    def _extract_health(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extract health variables from phenotype data."""
        health_fields = ['20002', '41270', '40001', '40000']
        health_cols = ['eid']
        
        for field in health_fields:
            col = f"f.{field}.0.0"
            if col in df.columns:
                health_cols.append(col)
        
        if len(health_cols) > 1:
            return df[health_cols].copy()
        return pd.DataFrame({'eid': df['eid'] if 'eid' in df.columns else []})
    
    def _extract_lifestyle(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extract lifestyle variables from phenotype data."""
        # These are example field IDs - actual UK Biobank field IDs would be needed
        lifestyle_fields = ['1239', '1558', '864', '874']  # smoking, alcohol, activity, diet
        lifestyle_cols = ['eid']
        
        for field in lifestyle_fields:
            col = f"f.{field}.0.0"
            if col in df.columns:
                lifestyle_cols.append(col)
        
        if len(lifestyle_cols) > 1:
            return df[lifestyle_cols].copy()
        return pd.DataFrame({'eid': df['eid'] if 'eid' in df.columns else []})
    
    def _load_modality_data(self, modality_dir: Path) -> Dict[str, Any]:
        """Load data for a specific imaging modality."""
        modality_data = {
            'subjects': [],
            'metrics': {}
        }
        
        # Look for summary files or individual subject files
        summary_file = modality_dir / 'summary.csv'
        if summary_file.exists():
            summary_df = pd.read_csv(summary_file)
            modality_data['subjects'] = summary_df['eid'].astype(str).tolist()
            modality_data['metrics'] = summary_df.to_dict()
        
        return modality_data
    
    def _load_snp_data(self) -> Dict[str, Any]:
        """Load SNP genotype data."""
        snp_data = {
            'subjects': [],
            'markers': [],
            'genotypes': {}
        }
        
        # This would load actual genetic data files
        # For now, return empty structure
        return snp_data
    
    def _load_prs_data(self) -> Dict[str, Any]:
        """Load polygenic risk scores."""
        prs_data = {
            'subjects': [],
            'scores': {}
        }
        
        prs_file = self.genetic_dir / 'polygenic_scores.csv'
        if prs_file.exists():
            prs_df = pd.read_csv(prs_file)
            prs_data['subjects'] = prs_df['eid'].astype(str).tolist()
            prs_data['scores'] = prs_df.drop('eid', axis=1).to_dict()
        
        return prs_data
    
    def _load_ancestry_data(self) -> Dict[str, Any]:
        """Load genetic ancestry data."""
        ancestry_data = {
            'subjects': [],
            'principal_components': {},
            'ancestry_groups': {}
        }
        
        ancestry_file = self.genetic_dir / 'ancestry.csv'
        if ancestry_file.exists():
            ancestry_df = pd.read_csv(ancestry_file)
            ancestry_data['subjects'] = ancestry_df['eid'].astype(str).tolist()
            
            pc_cols = [col for col in ancestry_df.columns if col.startswith('PC')]
            if pc_cols:
                ancestry_data['principal_components'] = ancestry_df[pc_cols].to_dict()
            
            if 'ancestry_group' in ancestry_df.columns:
                ancestry_data['ancestry_groups'] = ancestry_df['ancestry_group'].to_dict()
        
        return ancestry_data
    
    def _calculate_completeness(self) -> float:
        """Calculate overall data completeness score."""
        total_expected = len(self.subjects) * 4  # phenotype, imaging, genetics, QC
        total_available = 0
        
        if self.phenotype_data:
            total_available += len(self.subjects)
        if self.imaging_metrics:
            total_available += len(self.subjects)
        if self.genetic_markers:
            total_available += len(self.subjects)
        if self.quality_scores:
            total_available += len(self.subjects)
        
        return total_available / total_expected if total_expected > 0 else 0.0
    
    def _calculate_phenotype_coverage(self) -> float:
        """Calculate phenotype data coverage."""
        if not self.phenotype_data:
            return 0.0
        
        total_fields = sum(
            len(df.columns) - 1 for df in self.phenotype_data.values()
            if isinstance(df, pd.DataFrame)
        )
        
        expected_fields = len(self.field_mappings)
        return min(total_fields / expected_fields, 1.0) if expected_fields > 0 else 0.0
    
    def _calculate_imaging_quality(self) -> float:
        """Calculate imaging data quality score."""
        if not self.imaging_metrics:
            return 0.0
        
        available_modalities = len(self.imaging_metrics)
        expected_modalities = len(self.imaging_modalities)
        
        return available_modalities / expected_modalities if expected_modalities > 0 else 0.0
    
    def _calculate_genetic_coverage(self) -> float:
        """Calculate genetic data coverage."""
        if not self.genetic_markers:
            return 0.0
        
        coverage_scores = []
        
        if 'snps' in self.genetic_markers:
            n_snps = len(self.genetic_markers['snps'].get('markers', []))
            coverage_scores.append(min(n_snps / 1000, 1.0))  # Expect at least 1000 SNPs
        
        if 'polygenic_scores' in self.genetic_markers:
            n_prs = len(self.genetic_markers['polygenic_scores'].get('scores', {}))
            coverage_scores.append(min(n_prs / 5, 1.0))  # Expect at least 5 PRS
        
        if 'ancestry' in self.genetic_markers:
            has_pcs = bool(self.genetic_markers['ancestry'].get('principal_components'))
            coverage_scores.append(1.0 if has_pcs else 0.0)
        
        return sum(coverage_scores) / len(coverage_scores) if coverage_scores else 0.0
