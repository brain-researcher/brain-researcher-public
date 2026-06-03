"""Unified loader for CamCAN dataset."""

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


class CamCANUnifiedLoader:
    """Loader for Cambridge Centre for Ageing and Neuroscience (CamCAN) data."""

    def __init__(self, data_dir: str | None = None, cache_dir: str | None = None):
        """Initialize CamCAN loader.

        Args:
            data_dir: CamCAN data directory
            cache_dir: Cache directory
        """
        self.data_dir = Path(data_dir) if data_dir else None
        cache_dir = cache_dir or str(_default_cache_dir("camcan_cache"))
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
                tempfile.mkdtemp(prefix="camcan_cache_", dir=str(fallback_root))
            )
            logger.warning(
                "Default CamCAN cache dir %s not writable (%s); using %s",
                preferred_cache,
                exc,
                fallback,
            )
            self.cache_dir = fallback

        # CamCAN data structure
        self.subjects = []
        self.demographics = {}
        self.cognitive_data = {}
        self.imaging_data = {}
        self.lifestyle_data = {}

        # Age stratification (CamCAN age range: 18-88)
        self.age_bands = [
            (18, 27),
            (28, 37),
            (38, 47),
            (48, 57),
            (58, 67),
            (68, 77),
            (78, 88),
        ]

        # Cognitive domains assessed
        self.cognitive_domains = [
            "fluid_intelligence",
            "crystallized_intelligence",
            "memory",
            "executive_function",
            "processing_speed",
            "attention",
        ]

        # Imaging modalities
        self.imaging_modalities = [
            "T1w",
            "T2w",
            "DWI",
            "rfMRI",
            "tfMRI",
            "MEG_rest",
            "MEG_task",
        ]

    def load_participants(
        self, participants_file: str | None = None, demo_mode: bool = False
    ) -> dict[str, Any]:
        """Load CamCAN participants data.

        Args:
            participants_file: Path to participants TSV file
            demo_mode: If True, use sample data for demonstration purposes

        Returns:
            Participants data

        Raises:
            ValueError: If participants file is not found and demo_mode is False
        """
        if demo_mode:
            # Generate sample data for demonstration only
            self._generate_sample_participants()
        elif participants_file and os.path.exists(participants_file):
            df = pd.read_csv(participants_file, sep="\t")

            for _, row in df.iterrows():
                subject_id = row["participant_id"]
                self.subjects.append(subject_id)
                self.demographics[subject_id] = {
                    "age": row.get("age"),
                    "sex": row.get("sex"),
                    "handedness": row.get("handedness"),
                    "education_years": row.get("education"),
                }
        else:
            raise ValueError(
                f"Required CamCAN participants file not found: {participants_file}. "
                "Please provide a valid participants.tsv file in BIDS format "
                "with columns 'participant_id', 'age', 'sex', 'handedness', 'education', "
                "or set demo_mode=True to use sample data for testing purposes."
            )

        logger.info(f"Loaded {len(self.subjects)} CamCAN participants")
        return self.demographics

    def load_cognitive_measures(
        self, cognitive_file: str | None = None, demo_mode: bool = False
    ) -> dict[str, Any]:
        """Load cognitive assessment data.

        Args:
            cognitive_file: Path to cognitive data CSV file
            demo_mode: If True, use sample data for demonstration purposes

        Returns:
            Cognitive measures by subject

        Raises:
            ValueError: If cognitive file is not found and demo_mode is False
        """
        if demo_mode:
            # Generate sample cognitive data based on age
            for subject_id in self.subjects:
                self.cognitive_data[subject_id] = self._generate_cognitive_scores(
                    self.demographics[subject_id].get("age", 50)
                )
        elif cognitive_file and os.path.exists(cognitive_file):
            df = pd.read_csv(cognitive_file)

            for _, row in df.iterrows():
                subject_id = str(row["participant_id"])
                if subject_id in self.subjects:
                    self.cognitive_data[subject_id] = {
                        domain: row.get(domain) for domain in self.cognitive_domains
                    }
        else:
            raise ValueError(
                f"Required CamCAN cognitive data file not found: {cognitive_file}. "
                "Please provide a valid CSV file with cognitive assessment scores "
                f"including columns: {', '.join(self.cognitive_domains)}, "
                "or set demo_mode=True to use sample data for testing purposes."
            )

        logger.info(f"Loaded cognitive data for {len(self.cognitive_data)} subjects")
        return self.cognitive_data

    def load_imaging_metadata(self, subject_id: str) -> dict[str, Any]:
        """Load imaging metadata for subject.

        Args:
            subject_id: Subject identifier

        Returns:
            Imaging metadata
        """
        metadata = {}

        for modality in self.imaging_modalities:
            metadata[modality] = self._get_imaging_params(modality)

        self.imaging_data[subject_id] = metadata
        return metadata

    def load_lifestyle_factors(
        self, lifestyle_file: str | None = None, demo_mode: bool = False
    ) -> dict[str, Any]:
        """Load lifestyle and health factors.

        Args:
            lifestyle_file: Path to lifestyle data CSV file
            demo_mode: If True, use sample data for demonstration purposes

        Returns:
            Lifestyle data by subject

        Raises:
            ValueError: If lifestyle file is not found and demo_mode is False
        """
        if demo_mode:
            # Generate sample lifestyle data based on age
            for subject_id in self.subjects:
                age = self.demographics[subject_id].get("age", 50)
                self.lifestyle_data[subject_id] = self._generate_lifestyle_data(age)
        elif lifestyle_file and os.path.exists(lifestyle_file):
            df = pd.read_csv(lifestyle_file)

            for _, row in df.iterrows():
                subject_id = str(row["participant_id"])
                if subject_id in self.subjects:
                    self.lifestyle_data[subject_id] = {
                        "physical_activity": row.get("physical_activity"),
                        "sleep_quality": row.get("sleep_quality"),
                        "diet_quality": row.get("diet_quality"),
                        "smoking": row.get("smoking"),
                        "alcohol": row.get("alcohol"),
                        "social_engagement": row.get("social_engagement"),
                        "cognitive_activities": row.get("cognitive_activities"),
                        "bmi": row.get("bmi"),
                        "systolic_bp": row.get("systolic_bp"),
                        "diastolic_bp": row.get("diastolic_bp"),
                    }
        else:
            raise ValueError(
                f"Required CamCAN lifestyle data file not found: {lifestyle_file}. "
                "Please provide a valid CSV file with lifestyle and health factors "
                "including columns: physical_activity, sleep_quality, diet_quality, etc., "
                "or set demo_mode=True to use sample data for testing purposes."
            )

        logger.info(f"Loaded lifestyle data for {len(self.lifestyle_data)} subjects")
        return self.lifestyle_data

    def get_age_stratified_groups(self) -> dict[tuple[int, int], list[str]]:
        """Get subjects grouped by age bands.

        Returns:
            Dict mapping age bands to subject lists
        """
        age_groups = {band: [] for band in self.age_bands}

        for subject_id, demo in self.demographics.items():
            age = demo.get("age")
            if age:
                for band in self.age_bands:
                    if band[0] <= age <= band[1]:
                        age_groups[band].append(subject_id)
                        break

        return age_groups

    def _generate_sample_participants(self):
        """Generate sample participant data."""
        import random

        # Generate age-stratified sample
        n_per_band = 100
        subject_counter = 1

        for age_band in self.age_bands:
            for _ in range(n_per_band):
                subject_id = f"CC{subject_counter:06d}"
                age = random.randint(age_band[0], age_band[1])

                self.subjects.append(subject_id)
                self.demographics[subject_id] = {
                    "age": age,
                    "sex": random.choice(["M", "F"]),
                    "handedness": random.choice(["R", "L", "A"]),
                    "education_years": random.randint(10, 20),
                }

                subject_counter += 1

    def _generate_cognitive_scores(self, age: int) -> dict[str, float]:
        """Generate age-appropriate cognitive scores.

        Args:
            age: Subject age

        Returns:
            Cognitive scores
        """
        import random

        # Simulate age-related cognitive changes
        age_factor = 1.0 - (max(age - 30, 0) / 100)  # Decline after 30

        scores = {}
        for domain in self.cognitive_domains:
            base_score = random.uniform(85, 115)

            if domain in [
                "fluid_intelligence",
                "processing_speed",
                "executive_function",
            ]:
                # These decline with age
                scores[domain] = base_score * age_factor
            elif domain == "crystallized_intelligence":
                # This improves with age
                scores[domain] = base_score * (1 + (age - 30) / 200)
            else:
                # Memory and attention: moderate decline
                scores[domain] = base_score * (age_factor * 0.5 + 0.5)

        return scores

    def _generate_lifestyle_data(self, age: int) -> dict[str, Any]:
        """Generate lifestyle data.

        Args:
            age: Subject age

        Returns:
            Lifestyle factors
        """
        import random

        return {
            "physical_activity": random.choice(["low", "moderate", "high"]),
            "sleep_quality": random.randint(1, 10),
            "diet_quality": random.choice(["poor", "fair", "good", "excellent"]),
            "smoking": random.choice(["never", "former", "current"]),
            "alcohol": random.choice(["none", "light", "moderate", "heavy"]),
            "social_engagement": random.randint(1, 10),
            "cognitive_activities": random.randint(1, 10),
            "bmi": random.uniform(18, 35),
            "systolic_bp": random.randint(100, 160),
            "diastolic_bp": random.randint(60, 100),
        }

    def _get_imaging_params(self, modality: str) -> dict[str, Any]:
        """Get imaging parameters for modality.

        Args:
            modality: Imaging modality

        Returns:
            Imaging parameters
        """
        base_params = {"scanner": "Siemens 3T TIM Trio", "field_strength": "3T"}

        params_by_modality = {
            "T1w": {
                **base_params,
                "sequence": "MPRAGE",
                "resolution": "1mm isotropic",
                "tr": 2250,
                "te": 2.98,
            },
            "T2w": {
                **base_params,
                "sequence": "TSE",
                "resolution": "1mm isotropic",
                "tr": 2800,
                "te": 408,
            },
            "DWI": {
                **base_params,
                "sequence": "EPI",
                "resolution": "2mm isotropic",
                "b_values": [0, 1000, 2000],
                "directions": 60,
            },
            "rfMRI": {
                **base_params,
                "sequence": "EPI",
                "resolution": "3mm isotropic",
                "tr": 1970,
                "te": 30,
                "duration": "8min40s",
            },
            "tfMRI": {
                **base_params,
                "sequence": "EPI",
                "resolution": "3mm isotropic",
                "tr": 1970,
                "te": 30,
                "task": "sensorimotor",
            },
            "MEG_rest": {
                "system": "VectorView",
                "channels": 306,
                "sampling_rate": 1000,
                "duration": "8min40s",
            },
            "MEG_task": {
                "system": "VectorView",
                "channels": 306,
                "sampling_rate": 1000,
                "task": "sensorimotor",
            },
        }

        return params_by_modality.get(modality, base_params)

    def compute_brain_age_gap(self, subject_id: str) -> float | None:
        """Compute brain age gap (predicted - chronological age).

        Args:
            subject_id: Subject identifier

        Returns:
            Brain age gap or None
        """
        if subject_id not in self.demographics:
            return None

        chronological_age = self.demographics[subject_id].get("age")
        if not chronological_age:
            return None

        # Simplified brain age prediction
        # In reality, this would use imaging data
        import random

        predicted_age = chronological_age + random.uniform(-10, 10)

        return predicted_age - chronological_age

    def export_for_kg(self) -> dict[str, Any]:
        """Export CamCAN data for knowledge graph.

        Returns:
            KG-formatted data
        """
        nodes = []
        edges = []

        # Create subject nodes
        for subject_id in self.subjects:
            nodes.append(
                {
                    "id": f"camcan_{subject_id}",
                    "type": "Subject",
                    "properties": {
                        "dataset": "CamCAN",
                        "subject_id": subject_id,
                        **self.demographics.get(subject_id, {}),
                    },
                }
            )

            # Add cognitive data
            if subject_id in self.cognitive_data:
                cog_id = f"camcan_{subject_id}_cognitive"
                nodes.append(
                    {
                        "id": cog_id,
                        "type": "CognitiveAssessment",
                        "properties": self.cognitive_data[subject_id],
                    }
                )

                edges.append(
                    {
                        "source": f"camcan_{subject_id}",
                        "target": cog_id,
                        "type": "HAS_COGNITIVE_DATA",
                    }
                )

            # Add lifestyle data
            if subject_id in self.lifestyle_data:
                life_id = f"camcan_{subject_id}_lifestyle"
                nodes.append(
                    {
                        "id": life_id,
                        "type": "LifestyleFactors",
                        "properties": self.lifestyle_data[subject_id],
                    }
                )

                edges.append(
                    {
                        "source": f"camcan_{subject_id}",
                        "target": life_id,
                        "type": "HAS_LIFESTYLE_DATA",
                    }
                )

            # Add brain age gap if computed
            brain_age_gap = self.compute_brain_age_gap(subject_id)
            if brain_age_gap is not None:
                nodes[-1]["properties"]["brain_age_gap"] = brain_age_gap

        # Add age group relationships
        age_groups = self.get_age_stratified_groups()
        for age_band, subjects in age_groups.items():
            group_id = f"camcan_age_{age_band[0]}_{age_band[1]}"
            nodes.append(
                {
                    "id": group_id,
                    "type": "AgeGroup",
                    "properties": {
                        "min_age": age_band[0],
                        "max_age": age_band[1],
                        "n_subjects": len(subjects),
                    },
                }
            )

            for subj in subjects:
                edges.append(
                    {
                        "source": f"camcan_{subj}",
                        "target": group_id,
                        "type": "BELONGS_TO_GROUP",
                    }
                )

        return {
            "nodes": nodes,
            "edges": edges,
            "metadata": {
                "dataset": "CamCAN",
                "subjects": len(self.subjects),
                "age_range": (18, 88),
                "modalities": len(self.imaging_modalities),
                "cognitive_domains": len(self.cognitive_domains),
            },
        }

    def get_statistics(self) -> dict[str, Any]:
        """Get CamCAN data statistics.

        Returns:
            Statistics dictionary
        """
        stats = {
            "total_subjects": len(self.subjects),
            "age_bands": len(self.age_bands),
            "cognitive_domains": self.cognitive_domains,
            "imaging_modalities": self.imaging_modalities,
        }

        # Age distribution
        age_groups = self.get_age_stratified_groups()
        stats["age_distribution"] = {
            f"{band[0]}-{band[1]}": len(subjects)
            for band, subjects in age_groups.items()
        }

        # Sex distribution
        if self.demographics:
            sex_counts = {"M": 0, "F": 0}
            for demo in self.demographics.values():
                sex = demo.get("sex")
                if sex in sex_counts:
                    sex_counts[sex] += 1
            stats["sex_distribution"] = sex_counts

        return stats
