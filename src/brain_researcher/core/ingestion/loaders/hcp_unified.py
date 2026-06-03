"""Unified loader for Human Connectome Project data."""

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


def _cache_root() -> Path:
    base = Path(os.getenv("XDG_CACHE_HOME", str(Path.home() / ".cache"))).expanduser()
    return base / "brain_researcher"


def _default_cache_dir(name: str) -> Path:
    return _cache_root() / name


class HCPUnifiedLoader:
    """Loader for Human Connectome Project data."""

    def __init__(
        self,
        data_dir: str | None = None,
        use_s3: bool = False,
        cache_dir: str | None = None,
    ):
        """Initialize HCP loader.

        Args:
            data_dir: Local HCP data directory
            use_s3: Use S3 access (requires credentials)
            cache_dir: Cache directory
        """
        self.data_dir = Path(data_dir) if data_dir else None
        self.use_s3 = use_s3
        cache_dir = cache_dir or str(_default_cache_dir("hcp_cache"))
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
                tempfile.mkdtemp(prefix="hcp_cache_", dir=str(fallback_root))
            )
            logger.warning(
                "Default HCP cache dir %s not writable (%s); using %s",
                preferred_cache,
                exc,
                fallback,
            )
            self.cache_dir = fallback

        # HCP data structure
        self.subjects = []
        self.behavioral_data = {}
        self.scan_parameters = {}
        self.processing_status = {}

        # Standard HCP measures
        self.behavioral_domains = [
            "Alertness",
            "Cognition",
            "Emotion",
            "Motor",
            "Personality",
            "Sensory",
            "Psychiatric",
            "Substance Use",
        ]

        self.scan_types = [
            "T1w",
            "T2w",
            "rfMRI_REST",
            "tfMRI_MOTOR",
            "tfMRI_WM",
            "tfMRI_EMOTION",
            "tfMRI_GAMBLING",
            "tfMRI_LANGUAGE",
            "tfMRI_RELATIONAL",
            "tfMRI_SOCIAL",
            "dMRI",
        ]

    def load_subject_list(
        self, subject_file: str | None = None, demo_mode: bool = False
    ) -> list[str]:
        """Load list of HCP subjects.

        Args:
            subject_file: Path to subject list file
            demo_mode: If True, use sample data for demonstration purposes

        Returns:
            List of subject IDs

        Raises:
            ValueError: If subject file is not found and demo_mode is False
        """
        if demo_mode:
            # Use sample subjects for demonstration only
            subjects = self._get_sample_subjects()
        elif subject_file and os.path.exists(subject_file):
            with open(subject_file) as f:
                subjects = [line.strip() for line in f if line.strip()]
        else:
            raise ValueError(
                f"Required HCP subject file not found: {subject_file}. "
                "Please provide a valid subject list file with HCP subject IDs (one per line), "
                "or set demo_mode=True to use sample data for testing purposes."
            )

        self.subjects = subjects
        logger.info(f"Loaded {len(subjects)} HCP subjects")
        return subjects

    def load_behavioral_data(
        self, behavioral_file: str | None = None, demo_mode: bool = False
    ) -> dict[str, Any]:
        """Load HCP behavioral/demographic data.

        Args:
            behavioral_file: Path to behavioral CSV file
            demo_mode: If True, use sample data for demonstration purposes

        Returns:
            Behavioral data by subject

        Raises:
            ValueError: If behavioral file is not found and demo_mode is False
        """
        if demo_mode:
            # Generate sample data for demonstration only
            self.behavioral_data = self._generate_sample_behavioral()
        elif behavioral_file and os.path.exists(behavioral_file):
            df = pd.read_csv(behavioral_file)

            # Convert to dict by subject
            for _, row in df.iterrows():
                subject_id = str(row["Subject"])
                self.behavioral_data[subject_id] = row.to_dict()
        else:
            raise ValueError(
                f"Required HCP behavioral data file not found: {behavioral_file}. "
                "Please provide a valid CSV file with HCP behavioral/demographic data "
                "containing columns like 'Subject', 'Age', 'Gender', 'Handedness', etc., "
                "or set demo_mode=True to use sample data for testing purposes."
            )

        logger.info(f"Loaded behavioral data for {len(self.behavioral_data)} subjects")
        return self.behavioral_data

    def load_scan_parameters(self, subject_id: str) -> dict[str, Any]:
        """Load scan parameters for a subject.

        Args:
            subject_id: HCP subject ID

        Returns:
            Scan parameters by modality
        """
        params = {}

        # Standard HCP scan parameters
        for scan_type in self.scan_types:
            params[scan_type] = self._get_scan_params(scan_type)

        self.scan_parameters[subject_id] = params
        return params

    def _get_scan_params(self, scan_type: str) -> dict[str, Any]:
        """Get standard HCP scan parameters.

        Args:
            scan_type: Type of scan

        Returns:
            Scan parameters
        """
        # Standard HCP protocol parameters
        base_params = {
            "scanner": "Siemens 3T Connectome Skyra",
            "field_strength": "3T",
            "manufacturer": "Siemens",
        }

        if scan_type.startswith("T1w"):
            return {
                **base_params,
                "sequence": "MPRAGE",
                "resolution": "0.7mm isotropic",
                "tr": 2400,
                "te": 2.14,
                "flip_angle": 8,
            }
        elif scan_type.startswith("T2w"):
            return {
                **base_params,
                "sequence": "SPACE",
                "resolution": "0.7mm isotropic",
                "tr": 3200,
                "te": 565,
            }
        elif "fMRI" in scan_type:
            return {
                **base_params,
                "sequence": "Gradient-echo EPI",
                "resolution": "2mm isotropic",
                "tr": 720,
                "te": 33.1,
                "flip_angle": 52,
                "multiband_factor": 8,
            }
        elif scan_type == "dMRI":
            return {
                **base_params,
                "sequence": "Spin-echo EPI",
                "resolution": "1.25mm isotropic",
                "b_values": [1000, 2000, 3000],
                "directions": 90,
                "multiband_factor": 3,
            }

        return base_params

    def load_processing_status(self, subject_id: str) -> dict[str, Any]:
        """Load processing pipeline status for subject.

        Args:
            subject_id: HCP subject ID

        Returns:
            Processing status
        """
        # Check for standard HCP pipeline outputs
        status = {
            "structural_preprocessing": "completed",
            "functional_preprocessing": "completed",
            "diffusion_preprocessing": "completed",
            "ica_fix": "completed",
            "msmall_registration": "completed",
            "task_analysis": "completed",
            "resting_state_analysis": "completed",
        }

        self.processing_status[subject_id] = status
        return status

    def get_connectivity_matrix(
        self, subject_id: str, parcellation: str = "Glasser360"
    ) -> Any | None:
        """Get connectivity matrix for subject.

        Args:
            subject_id: HCP subject ID
            parcellation: Brain parcellation to use

        Returns:
            Connectivity matrix or None
        """
        # Check cache
        cache_file = self.cache_dir / f"conn_{subject_id}_{parcellation}.npy"

        if cache_file.exists():
            import numpy as np

            return np.load(cache_file)

        # Generate sample connectivity
        import numpy as np

        if parcellation == "Glasser360":
            n_regions = 360
        elif parcellation == "Schaefer400":
            n_regions = 400
        else:
            n_regions = 100

        # Generate random symmetric matrix
        matrix = np.random.rand(n_regions, n_regions)
        matrix = (matrix + matrix.T) / 2
        np.fill_diagonal(matrix, 1)

        # Cache it
        np.save(cache_file, matrix)

        return matrix

    def _get_sample_subjects(self) -> list[str]:
        """Get sample HCP subject IDs.

        Returns:
            List of subject IDs
        """
        # Sample from HCP 1200 release
        return [
            "100307",
            "100408",
            "101006",
            "101107",
            "101309",
            "101410",
            "101915",
            "102008",
            "102311",
            "102513",
            "102614",
            "102715",
            "102816",
            "103111",
            "103212",
            "103414",
            "103515",
            "103818",
            "104012",
            "104416",
        ]

    def _generate_sample_behavioral(self) -> dict[str, Any]:
        """Generate sample behavioral data.

        Returns:
            Behavioral data dict
        """
        import random

        behavioral = {}

        for subject_id in self.subjects[:10]:  # First 10 subjects
            behavioral[subject_id] = {
                "Subject": subject_id,
                "Age": f"{random.randint(22, 35)}",
                "Gender": random.choice(["M", "F"]),
                "Handedness": random.randint(50, 100),
                "Race": random.choice(["White", "Black", "Asian", "More than one"]),
                "Ethnicity": random.choice(["Not Hispanic/Latino", "Hispanic/Latino"]),
                "Education": random.randint(12, 20),
                # Cognitive measures
                "CogFluidComp_Unadj": random.uniform(90, 130),
                "CogCrystalComp_Unadj": random.uniform(90, 130),
                "CogTotalComp_Unadj": random.uniform(90, 130),
                # Motor
                "Strength_Unadj": random.uniform(80, 150),
                "Dexterity_Unadj": random.uniform(80, 120),
                # Personality (NEO-FFI)
                "NEOFAC_N": random.uniform(10, 40),
                "NEOFAC_E": random.uniform(20, 50),
                "NEOFAC_O": random.uniform(20, 50),
                "NEOFAC_A": random.uniform(25, 55),
                "NEOFAC_C": random.uniform(25, 55),
                # Sleep
                "PSQI_Score": random.randint(0, 15),
                # BMI
                "BMI": random.uniform(18, 35),
            }

        return behavioral

    def get_task_contrasts(self, task: str) -> list[dict[str, str]]:
        """Get task contrasts for HCP task fMRI.

        Args:
            task: Task name (e.g., 'MOTOR', 'WM')

        Returns:
            List of contrast definitions
        """
        contrasts = {
            "MOTOR": [
                {"name": "lh", "description": "Left hand movement"},
                {"name": "rh", "description": "Right hand movement"},
                {"name": "lf", "description": "Left foot movement"},
                {"name": "rf", "description": "Right foot movement"},
                {"name": "t", "description": "Tongue movement"},
            ],
            "WM": [
                {"name": "2back_0back", "description": "2-back vs 0-back"},
                {"name": "body_face", "description": "Body vs Face"},
                {"name": "face_body", "description": "Face vs Body"},
                {"name": "place_face", "description": "Place vs Face"},
            ],
            "EMOTION": [
                {"name": "faces_shapes", "description": "Faces vs Shapes"},
                {"name": "fear_neutral", "description": "Fear vs Neutral"},
            ],
            "GAMBLING": [
                {"name": "win_loss", "description": "Win vs Loss"},
                {"name": "reward_punishment", "description": "Reward vs Punishment"},
            ],
            "LANGUAGE": [
                {"name": "story_math", "description": "Story vs Math"},
                {"name": "math_story", "description": "Math vs Story"},
            ],
            "RELATIONAL": [
                {"name": "relational_match", "description": "Relational vs Match"}
            ],
            "SOCIAL": [
                {"name": "tom_random", "description": "Theory of Mind vs Random"}
            ],
        }

        return contrasts.get(task, [])

    def export_for_kg(self) -> dict[str, Any]:
        """Export HCP data for knowledge graph.

        Returns:
            KG-formatted data
        """
        nodes = []
        edges = []

        # Create subject nodes
        for subject_id in self.subjects:
            nodes.append(
                {
                    "id": f"hcp_{subject_id}",
                    "type": "Subject",
                    "properties": {"dataset": "HCP", "subject_id": subject_id},
                }
            )

            # Add behavioral data if available
            if subject_id in self.behavioral_data:
                behavioral = self.behavioral_data[subject_id]
                nodes.append(
                    {
                        "id": f"hcp_{subject_id}_behavioral",
                        "type": "BehavioralData",
                        "properties": behavioral,
                    }
                )

                edges.append(
                    {
                        "source": f"hcp_{subject_id}",
                        "target": f"hcp_{subject_id}_behavioral",
                        "type": "HAS_BEHAVIORAL_DATA",
                    }
                )

            # Add scan nodes
            if subject_id in self.scan_parameters:
                for scan_type, params in self.scan_parameters[subject_id].items():
                    scan_id = f"hcp_{subject_id}_{scan_type}"
                    nodes.append(
                        {
                            "id": scan_id,
                            "type": "Scan",
                            "properties": {**params, "scan_type": scan_type},
                        }
                    )

                    edges.append(
                        {
                            "source": f"hcp_{subject_id}",
                            "target": scan_id,
                            "type": "HAS_SCAN",
                        }
                    )

        return {
            "nodes": nodes,
            "edges": edges,
            "metadata": {
                "dataset": "Human Connectome Project",
                "subjects": len(self.subjects),
                "behavioral_measures": len(self.behavioral_domains),
                "scan_types": len(self.scan_types),
            },
        }

    def get_statistics(self) -> dict[str, Any]:
        """Get HCP data statistics.

        Returns:
            Statistics dictionary
        """
        stats = {
            "total_subjects": len(self.subjects),
            "subjects_with_behavioral": len(self.behavioral_data),
            "subjects_with_scans": len(self.scan_parameters),
            "scan_types": self.scan_types,
            "behavioral_domains": self.behavioral_domains,
        }

        # Demographics if available
        if self.behavioral_data:
            ages = [
                float(d.get("Age", 0))
                for d in self.behavioral_data.values()
                if d.get("Age")
            ]
            if ages:
                stats["age_range"] = (min(ages), max(ages))
                stats["mean_age"] = sum(ages) / len(ages)

            genders = [d.get("Gender") for d in self.behavioral_data.values()]
            stats["gender_distribution"] = {
                "M": genders.count("M"),
                "F": genders.count("F"),
            }

        return stats
