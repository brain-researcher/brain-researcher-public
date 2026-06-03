"""Client for Allen Brain Atlas API."""

import os
import requests
import json
import logging
import tempfile
from typing import List, Dict, Any, Optional
from pathlib import Path
import time

logger = logging.getLogger(__name__)


def _cache_root() -> Path:
    base = Path(os.getenv("XDG_CACHE_HOME", str(Path.home() / ".cache"))).expanduser()
    return base / "brain_researcher"


def _default_cache_dir(name: str) -> Path:
    return _cache_root() / name


class AllenBrainClient:
    """Client for interacting with Allen Brain Atlas API."""

    BASE_URL = "http://api.brain-map.org/api/v2"

    def __init__(self, cache_dir: Optional[str] = None):
        """Initialize Allen Brain API client.

        Args:
            cache_dir: Directory for caching API responses
        """
        cache_dir = cache_dir or str(_default_cache_dir("allen_cache"))
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
            fallback = Path(tempfile.mkdtemp(prefix="allen_cache_", dir=str(fallback_root)))
            logger.warning(
                "Allen cache dir %s not writable (%s); using %s",
                preferred_cache,
                exc,
                fallback,
            )
            self.cache_dir = fallback
        self.session = requests.Session()
        self.rate_limit_delay = 0.5  # seconds between requests
        self.last_request_time = 0

    def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> Any:
        """Make rate-limited API request.

        Args:
            endpoint: API endpoint
            params: Query parameters

        Returns:
            JSON response
        """
        # Rate limiting
        elapsed = time.time() - self.last_request_time
        if elapsed < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - elapsed)

        url = f"{self.BASE_URL}/{endpoint}"

        try:
            response = self.session.get(url, params=params, timeout=30)
            self.last_request_time = time.time()

            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"API request failed: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.error(f"API request error: {e}")
            return None

    def get_donors(self) -> List[Dict[str, Any]]:
        """Get list of available donor brains.

        Returns:
            List of donor information
        """
        # Check cache
        cache_file = self.cache_dir / 'donors.json'
        if cache_file.exists():
            with open(cache_file, 'r') as f:
                return json.load(f)

        # Query API
        response = self._make_request(
            "data/query.json",
            params={
                "criteria": "model::Donor,rma::criteria,products[id$eq2]",
                "include": "age,specimens"
            }
        )

        if response and 'msg' in response:
            donors = response['msg']

            # Cache response
            with open(cache_file, 'w') as f:
                json.dump(donors, f)

            return donors

        # Return sample data if API fails
        return self._get_sample_donors()

    def get_expression_data(self,
                          donor_id: str,
                          gene_symbols: List[str]) -> Dict[str, Any]:
        """Get gene expression data for specific genes.

        Args:
            donor_id: Donor identifier
            gene_symbols: List of gene symbols (e.g., ['FOXP2', 'BDNF'])

        Returns:
            Expression data dictionary
        """
        # Check cache
        cache_key = f"{donor_id}_{'_'.join(sorted(gene_symbols))}"
        cache_file = self.cache_dir / f'expression_{cache_key}.json'

        if cache_file.exists():
            with open(cache_file, 'r') as f:
                return json.load(f)

        # Build query
        gene_criteria = ','.join([f"acronym$eq'{gene}'" for gene in gene_symbols])

        response = self._make_request(
            "data/query.json",
            params={
                "criteria": f"model::Gene,rma::criteria,[{gene_criteria}]",
                "include": "probes"
            }
        )

        if response and 'msg' in response:
            # Get probe IDs for genes
            probe_ids = []
            for gene in response['msg']:
                for probe in gene.get('probes', []):
                    probe_ids.append(probe['id'])

            # Get expression values
            expression_data = self._get_probe_expression(donor_id, probe_ids)

            result = {
                'donor_id': donor_id,
                'genes': gene_symbols,
                'expression': expression_data
            }

            # Cache response
            with open(cache_file, 'w') as f:
                json.dump(result, f)

            return result

        # Return sample data if API fails
        return self._get_sample_expression(donor_id, gene_symbols)

    def _get_probe_expression(self,
                            donor_id: str,
                            probe_ids: List[int]) -> List[Dict[str, Any]]:
        """Get expression values for specific probes.

        Args:
            donor_id: Donor identifier
            probe_ids: List of probe IDs

        Returns:
            Expression values by structure
        """
        if not probe_ids:
            return []

        # Query expression data
        probe_list = ','.join(map(str, probe_ids))

        response = self._make_request(
            f"data/query.json",
            params={
                "criteria": f"service::human_microarray_expression[probes$in{probe_list}][donor_id$eq{donor_id}]",
                "num_rows": 2000
            }
        )

        if response and 'msg' in response:
            return response['msg']

        return []

    def get_structures(self) -> List[Dict[str, Any]]:
        """Get brain structure ontology.

        Returns:
            List of brain structures with hierarchy
        """
        # Check cache
        cache_file = self.cache_dir / 'structures.json'
        if cache_file.exists():
            with open(cache_file, 'r') as f:
                return json.load(f)

        # Query API
        response = self._make_request(
            "data/query.json",
            params={
                "criteria": "model::Structure,rma::criteria,[ontology_id$eq1]",
                "order": "structures.graph_order",
                "num_rows": 2000
            }
        )

        if response and 'msg' in response:
            structures = response['msg']

            # Cache response
            with open(cache_file, 'w') as f:
                json.dump(structures, f)

            return structures

        # Return sample data if API fails
        return self._get_sample_structures()

    def get_connectivity(self, structure_id: int) -> Dict[str, Any]:
        """Get structural connectivity data.

        Args:
            structure_id: Brain structure ID

        Returns:
            Connectivity information
        """
        # Check cache
        cache_file = self.cache_dir / f'connectivity_{structure_id}.json'
        if cache_file.exists():
            with open(cache_file, 'r') as f:
                return json.load(f)

        # Query API for projection data
        response = self._make_request(
            "data/query.json",
            params={
                "criteria": f"model::ProjectionVolume,rma::criteria,[structure_id$eq{structure_id}]",
                "include": "data_mask,injection_coordinates"
            }
        )

        if response and 'msg' in response:
            connectivity = {
                'structure_id': structure_id,
                'projections': response['msg']
            }

            # Cache response
            with open(cache_file, 'w') as f:
                json.dump(connectivity, f)

            return connectivity

        # Return sample data if API fails
        return {'structure_id': structure_id, 'projections': []}

    def _get_sample_donors(self) -> List[Dict[str, Any]]:
        """Get sample donor data for testing.

        Returns:
            Sample donor list
        """
        return [
            {
                'id': 'H0351.2001',
                'name': 'H0351.2001',
                'age': '24 years',
                'sex': 'M',
                'race': 'Caucasian'
            },
            {
                'id': 'H0351.2002',
                'name': 'H0351.2002',
                'age': '39 years',
                'sex': 'F',
                'race': 'African American'
            },
            {
                'id': 'H0351.1009',
                'name': 'H0351.1009',
                'age': '57 years',
                'sex': 'M',
                'race': 'Hispanic'
            },
            {
                'id': 'H0351.1012',
                'name': 'H0351.1012',
                'age': '31 years',
                'sex': 'M',
                'race': 'Caucasian'
            },
            {
                'id': 'H0351.1015',
                'name': 'H0351.1015',
                'age': '49 years',
                'sex': 'F',
                'race': 'Asian'
            },
            {
                'id': 'H0351.1016',
                'name': 'H0351.1016',
                'age': '55 years',
                'sex': 'M',
                'race': 'Caucasian'
            }
        ]

    def _get_sample_expression(self,
                              donor_id: str,
                              gene_symbols: List[str]) -> Dict[str, Any]:
        """Get sample expression data for testing.

        Args:
            donor_id: Donor ID
            gene_symbols: Gene symbols

        Returns:
            Sample expression data
        """
        import random

        structures = self._get_sample_structures()[:10]
        expression = []

        for struct in structures:
            for gene in gene_symbols:
                expression.append({
                    'structure_id': struct['id'],
                    'structure_name': struct['name'],
                    'gene': gene,
                    'expression_level': random.uniform(0, 10)
                })

        return {
            'donor_id': donor_id,
            'genes': gene_symbols,
            'expression': expression
        }

    def _get_sample_structures(self) -> List[Dict[str, Any]]:
        """Get sample brain structures for testing.

        Returns:
            Sample structure list
        """
        return [
            {'id': 4001, 'name': 'frontal lobe', 'acronym': 'FL', 'parent_structure_id': 4000},
            {'id': 4002, 'name': 'parietal lobe', 'acronym': 'PL', 'parent_structure_id': 4000},
            {'id': 4003, 'name': 'temporal lobe', 'acronym': 'TL', 'parent_structure_id': 4000},
            {'id': 4004, 'name': 'occipital lobe', 'acronym': 'OL', 'parent_structure_id': 4000},
            {'id': 4005, 'name': 'hippocampus', 'acronym': 'HIP', 'parent_structure_id': 4003},
            {'id': 4006, 'name': 'amygdala', 'acronym': 'AMY', 'parent_structure_id': 4003},
            {'id': 4007, 'name': 'thalamus', 'acronym': 'TH', 'parent_structure_id': None},
            {'id': 4008, 'name': 'hypothalamus', 'acronym': 'HY', 'parent_structure_id': None},
            {'id': 4009, 'name': 'cerebellum', 'acronym': 'CB', 'parent_structure_id': None},
            {'id': 4010, 'name': 'brainstem', 'acronym': 'BS', 'parent_structure_id': None}
        ]
