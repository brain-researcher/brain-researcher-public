"""OASIS (Open Access Series of Imaging Studies) data loader.

Handles cross-sectional and longitudinal neuroimaging data focusing on
aging and Alzheimer's disease from the OASIS project.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class OASISUnifiedLoader:
    """Unified loader for OASIS datasets.

    Handles:
    - OASIS-1: Cross-sectional MRI (416 subjects, 18-96 years)
    - OASIS-2: Longitudinal MRI (150 subjects, 60-96 years)
    - OASIS-3: Longitudinal multimodal (1098 subjects)
    - OASIS-4: Clinical cohort data
    """

    def __init__(self, data_dir: str = "/data/oasis"):
        """Initialize OASIS loader.

        Args:
            data_dir: Root directory for OASIS data
        """
        self.data_dir = Path(data_dir)
        self.subjects = []
        self.demographics = {}
        self.clinical_data = {}
        self.imaging_data = {}
        self.longitudinal_data = {}

        # CDR (Clinical Dementia Rating) scale
        self.cdr_scale = {
            0: "Normal",
            0.5: "Very Mild Dementia",
            1: "Mild Dementia",
            2: "Moderate Dementia",
            3: "Severe Dementia",
        }

    def load_oasis1_cross_sectional(self, demo_mode: bool = False) -> Dict[str, Any]:
        """Load OASIS-1 cross-sectional data.

        Args:
            demo_mode: If True, use sample data for demonstration purposes

        Returns:
            Cross-sectional dataset

        Raises:
            ValueError: If OASIS-1 data file is not found and demo_mode is False
        """
        oasis1_file = self.data_dir / "oasis1" / "oasis_cross-sectional.csv"

        if demo_mode:
            # Generate sample data for demonstration only
            self._generate_oasis1_sample_data()
        elif oasis1_file.exists():
            df = pd.read_csv(oasis1_file)

            for _, row in df.iterrows():
                subject_id = row["ID"]
                self.subjects.append(subject_id)

                self.demographics[subject_id] = {
                    "age": row.get("Age"),
                    "gender": row.get("M/F"),
                    "education": row.get("Educ"),
                    "ses": row.get("SES"),  # Socioeconomic status
                    "handedness": row.get("Hand"),
                }

                self.clinical_data[subject_id] = {
                    "mmse": row.get("MMSE"),
                    "cdr": row.get("CDR"),
                    "diagnosis": self.cdr_scale.get(row.get("CDR", 0), "Unknown"),
                }

                self.imaging_data[subject_id] = {
                    "etiv": row.get("eTIV"),  # Estimated total intracranial volume
                    "nwbv": row.get("nWBV"),  # Normalized whole brain volume
                    "asf": row.get("ASF"),  # Atlas scaling factor
                }
        else:
            raise ValueError(
                f"Required OASIS-1 cross-sectional data file not found: {oasis1_file}. "
                "Please provide a valid CSV file with OASIS-1 data including columns: "
                "'ID', 'Age', 'M/F', 'Educ', 'SES', 'Hand', 'MMSE', 'CDR', 'eTIV', 'nWBV', 'ASF', "
                "or set demo_mode=True to use sample data for testing purposes."
            )

        logger.info(f"Loaded {len(self.subjects)} OASIS-1 cross-sectional subjects")

        return {
            "subjects": self.subjects,
            "demographics": self.demographics,
            "clinical": self.clinical_data,
            "imaging": self.imaging_data,
        }

    def load_oasis2_longitudinal(self, demo_mode: bool = False) -> Dict[str, Any]:
        """Load OASIS-2 longitudinal data.

        Args:
            demo_mode: If True, use sample data for demonstration purposes

        Returns:
            Longitudinal dataset

        Raises:
            ValueError: If OASIS-2 data file is not found and demo_mode is False
        """
        oasis2_file = self.data_dir / "oasis2" / "oasis_longitudinal.csv"

        longitudinal_subjects = []

        if demo_mode:
            # Generate sample longitudinal data for demonstration only
            self._generate_oasis2_sample_data()
            longitudinal_subjects = list(self.longitudinal_data.keys())
        elif oasis2_file.exists():
            df = pd.read_csv(oasis2_file)

            # Group by subject
            for subject_id, group in df.groupby("Subject ID"):
                visits = []
                for _, row in group.iterrows():
                    visits.append(
                        {
                            "visit": row["Visit"],
                            "age": row["Age"],
                            "mmse": row.get("MMSE"),
                            "cdr": row.get("CDR"),
                            "etiv": row.get("eTIV"),
                            "nwbv": row.get("nWBV"),
                            "days_from_baseline": row.get("Delay", 0),
                        }
                    )

                self.longitudinal_data[subject_id] = {
                    "visits": visits,
                    "n_visits": len(visits),
                    "follow_up_years": max(v["days_from_baseline"] for v in visits)
                    / 365,
                }
                longitudinal_subjects.append(subject_id)
        else:
            raise ValueError(
                f"Required OASIS-2 longitudinal data file not found: {oasis2_file}. "
                "Please provide a valid CSV file with OASIS-2 longitudinal data including columns: "
                "'Subject ID', 'Visit', 'Age', 'MMSE', 'CDR', 'eTIV', 'nWBV', 'Delay', "
                "or set demo_mode=True to use sample data for testing purposes."
            )

        logger.info(
            f"Loaded {len(longitudinal_subjects)} OASIS-2 longitudinal subjects"
        )

        return {
            "subjects": longitudinal_subjects,
            "longitudinal": self.longitudinal_data,
        }

    def load_oasis3_multimodal(
        self, oasis3_file: Optional[str] = None, demo_mode: bool = False
    ) -> Dict[str, Any]:
        """Load OASIS-3 multimodal data.

        Args:
            oasis3_file: Path to OASIS-3 data file
            demo_mode: If True, use sample data for demonstration purposes

        Returns:
            Multimodal dataset including PET, fMRI, clinical

        Raises:
            ValueError: If OASIS-3 data file is not found and demo_mode is False
        """
        oasis3_subjects = []
        multimodal_data = {}

        if demo_mode:
            # Generate sample OASIS-3 data for demonstration only
            multimodal_data = self._generate_oasis3_sample_data()
            oasis3_subjects = list(multimodal_data.keys())
        elif oasis3_file and os.path.exists(oasis3_file):
            # Load real OASIS-3 data from file
            df = pd.read_csv(oasis3_file)

            for _, row in df.iterrows():
                subject_id = str(row["subject_id"])
                oasis3_subjects.append(subject_id)

                multimodal_data[subject_id] = {
                    "demographics": {
                        "age": row.get("age"),
                        "gender": row.get("gender"),
                        "race": row.get("race"),
                        "education": row.get("education"),
                        "apoe_genotype": row.get("apoe_genotype"),
                    },
                    "clinical": {
                        "diagnosis": row.get("diagnosis"),
                        "cdr_global": row.get("cdr_global"),
                        "cdr_sob": row.get("cdr_sob"),
                        "mmse": row.get("mmse"),
                        "moca": row.get("moca"),
                        "gds": row.get("gds"),
                        "faq": row.get("faq"),
                    },
                    "imaging": {
                        "has_t1": row.get("has_t1", False),
                        "has_t2": row.get("has_t2", False),
                        "has_flair": row.get("has_flair", False),
                        "has_dwi": row.get("has_dwi", False),
                        "has_asl": row.get("has_asl", False),
                        "has_swi": row.get("has_swi", False),
                        "has_rest_fmri": row.get("has_rest_fmri", False),
                        "has_task_fmri": row.get("has_task_fmri", False),
                    },
                    "pet": {
                        "has_fdg": row.get("has_fdg", False),
                        "has_pib": row.get("has_pib", False),
                        "has_av45": row.get("has_av45", False),
                        "has_tau": row.get("has_tau", False),
                        "amyloid_positive": row.get("amyloid_positive", False),
                    },
                    "biomarkers": {
                        "csf_abeta42": row.get("csf_abeta42"),
                        "csf_tau": row.get("csf_tau"),
                        "csf_ptau": row.get("csf_ptau"),
                        "plasma_abeta42_40": row.get("plasma_abeta42_40"),
                    },
                    "cognitive_battery": {
                        "memory_composite": row.get("memory_composite"),
                        "executive_composite": row.get("executive_composite"),
                        "language_composite": row.get("language_composite"),
                        "visuospatial_composite": row.get("visuospatial_composite"),
                    },
                }
        else:
            raise ValueError(
                f"Required OASIS-3 multimodal data file not found: {oasis3_file}. "
                "Please provide a valid CSV file with OASIS-3 data including demographic, "
                "clinical, imaging, PET, biomarker, and cognitive battery information, "
                "or set demo_mode=True to use sample data for testing purposes."
            )

        logger.info(f"Loaded {len(oasis3_subjects)} OASIS-3 multimodal subjects")

        return {"subjects": oasis3_subjects, "multimodal": multimodal_data}

    def calculate_brain_age_delta(self, subject_id: str) -> float:
        """Calculate brain age delta (predicted - chronological age).

        Args:
            subject_id: Subject identifier

        Returns:
            Brain age delta in years
        """
        if subject_id not in self.imaging_data:
            return 0.0

        # Simple model based on brain volume
        nwbv = self.imaging_data[subject_id].get("nwbv", 0.75)
        chronological_age = self.demographics.get(subject_id, {}).get("age", 65)

        # Predicted brain age (simplified)
        predicted_age = 100 - (nwbv * 100)  # Very simplified

        return predicted_age - chronological_age

    def _generate_oasis1_sample_data(self):
        """Generate sample OASIS-1 data for demo mode."""
        n_subjects = 416
        for i in range(n_subjects):
            subject_id = f"OAS1_{i+1:04d}_MR1"
            self.subjects.append(subject_id)

            # Age distribution (18-96)
            if i < 100:
                age = np.random.randint(18, 40)
            elif i < 250:
                age = np.random.randint(40, 65)
            else:
                age = np.random.randint(65, 96)

            self.demographics[subject_id] = {
                "age": age,
                "gender": np.random.choice(["M", "F"]),
                "education": np.random.randint(8, 20),
                "ses": np.random.randint(1, 6),
                "handedness": np.random.choice(["R", "L", "A"], p=[0.9, 0.08, 0.02]),
            }

            # CDR based on age
            if age < 60:
                cdr = 0
            elif age < 75:
                cdr = np.random.choice([0, 0.5], p=[0.8, 0.2])
            else:
                cdr = np.random.choice([0, 0.5, 1, 2], p=[0.5, 0.3, 0.15, 0.05])

            self.clinical_data[subject_id] = {
                "mmse": max(10, 30 - int(cdr * 5) + np.random.randint(-2, 3)),
                "cdr": cdr,
                "diagnosis": self.cdr_scale[cdr],
            }

            self.imaging_data[subject_id] = {
                "etiv": np.random.normal(1500, 150),
                "nwbv": np.random.normal(0.75 - cdr * 0.05, 0.05),
                "asf": np.random.normal(1.0, 0.1),
            }

    def _generate_oasis2_sample_data(self):
        """Generate sample OASIS-2 longitudinal data for demo mode."""
        n_subjects = 150

        for i in range(n_subjects):
            subject_id = f"OAS2_{i+1:04d}"

            # Number of visits (2-5)
            n_visits = np.random.randint(2, 6)
            baseline_age = np.random.randint(60, 96)
            baseline_cdr = np.random.choice([0, 0.5, 1], p=[0.5, 0.35, 0.15])

            visits = []
            for v in range(n_visits):
                days_from_baseline = v * np.random.randint(
                    180, 730
                )  # 6 months to 2 years
                age = baseline_age + days_from_baseline / 365

                # Progression
                if baseline_cdr > 0:
                    cdr_progression = min(
                        3, baseline_cdr + v * 0.25 * np.random.random()
                    )
                else:
                    cdr_progression = 0 if np.random.random() > 0.1 else 0.5

                visits.append(
                    {
                        "visit": v + 1,
                        "age": age,
                        "mmse": max(10, 30 - int(cdr_progression * 5)),
                        "cdr": cdr_progression,
                        "etiv": np.random.normal(1500, 150),
                        "nwbv": np.random.normal(0.75 - cdr_progression * 0.05, 0.03),
                        "days_from_baseline": days_from_baseline,
                    }
                )

            self.longitudinal_data[subject_id] = {
                "visits": visits,
                "n_visits": n_visits,
                "follow_up_years": days_from_baseline / 365,
                "converted": visits[-1]["cdr"] > visits[0]["cdr"],
            }

    def _generate_oasis3_sample_data(self) -> Dict[str, Any]:
        """Generate sample OASIS-3 multimodal data for demo mode."""
        multimodal_data = {}
        n_subjects = 200  # Sample subset

        for i in range(n_subjects):
            subject_id = f"OAS3{i+1:04d}"

            age = np.random.randint(42, 95)
            has_ad = np.random.random() < (0.1 if age < 65 else 0.3)

            multimodal_data[subject_id] = {
                "demographics": {
                    "age": age,
                    "gender": np.random.choice(["M", "F"]),
                    "race": np.random.choice(
                        ["White", "Black", "Asian", "Other"], p=[0.7, 0.15, 0.1, 0.05]
                    ),
                    "education": np.random.randint(8, 20),
                    "apoe_genotype": np.random.choice(
                        ["e3/e3", "e3/e4", "e4/e4", "e2/e3"], p=[0.6, 0.25, 0.05, 0.1]
                    ),
                },
                "clinical": {
                    "diagnosis": "AD" if has_ad else "CN",
                    "cdr_global": np.random.choice([0, 0.5, 1]) if has_ad else 0,
                    "cdr_sob": np.random.uniform(0, 8) if has_ad else 0,
                    "mmse": (
                        np.random.randint(20, 26)
                        if has_ad
                        else np.random.randint(27, 31)
                    ),
                    "moca": (
                        np.random.randint(18, 24)
                        if has_ad
                        else np.random.randint(25, 30)
                    ),
                    "gds": np.random.randint(0, 10),  # Geriatric Depression Scale
                    "faq": (
                        np.random.uniform(0, 20) if has_ad else 0
                    ),  # Functional Activities
                },
                "imaging": {
                    "has_t1": True,
                    "has_t2": np.random.random() > 0.2,
                    "has_flair": np.random.random() > 0.3,
                    "has_dwi": np.random.random() > 0.5,
                    "has_asl": np.random.random() > 0.6,
                    "has_swi": np.random.random() > 0.7,
                    "has_rest_fmri": np.random.random() > 0.4,
                    "has_task_fmri": np.random.random() > 0.7,
                },
                "pet": {
                    "has_fdg": np.random.random() > 0.6,
                    "has_pib": np.random.random() > 0.5,
                    "has_av45": np.random.random() > 0.4,
                    "has_tau": np.random.random() > 0.7,
                    "amyloid_positive": has_ad or (np.random.random() < 0.2),
                },
                "biomarkers": {
                    "csf_abeta42": np.random.uniform(200, 600),
                    "csf_tau": np.random.uniform(100, 400),
                    "csf_ptau": np.random.uniform(20, 80),
                    "plasma_abeta42_40": np.random.uniform(0.05, 0.15),
                },
                "cognitive_battery": {
                    "memory_composite": np.random.normal(-1 if has_ad else 0, 0.5),
                    "executive_composite": np.random.normal(-0.8 if has_ad else 0, 0.5),
                    "language_composite": np.random.normal(-0.5 if has_ad else 0, 0.5),
                    "visuospatial_composite": np.random.normal(
                        -0.3 if has_ad else 0, 0.5
                    ),
                },
            }

        return multimodal_data

    def identify_converters(self) -> List[str]:
        """Identify subjects who converted from CN to MCI/AD.

        Returns:
            List of converter subject IDs
        """
        converters = []

        for subject_id, data in self.longitudinal_data.items():
            if "visits" in data and len(data["visits"]) > 1:
                first_cdr = data["visits"][0].get("cdr", 0)
                last_cdr = data["visits"][-1].get("cdr", 0)

                if first_cdr == 0 and last_cdr > 0:
                    converters.append(subject_id)

        logger.info(f"Identified {len(converters)} converters")
        return converters

    def export_for_kg(self) -> Dict[str, Any]:
        """Export data for knowledge graph integration.

        Returns:
            Knowledge graph formatted data
        """
        nodes = []
        edges = []

        # Combine all subjects
        all_subjects = list(set(self.subjects + list(self.longitudinal_data.keys())))

        for subject_id in all_subjects[:100]:  # Sample for KG
            # Subject node
            subject_node_id = f"oasis_{subject_id}"

            node_data = {
                "id": subject_node_id,
                "type": "Subject",
                "properties": {"study": "OASIS", "subject_id": subject_id},
            }

            # Add demographics if available
            if subject_id in self.demographics:
                node_data["properties"].update(self.demographics[subject_id])

            nodes.append(node_data)

            # Clinical assessment nodes
            if subject_id in self.clinical_data:
                assessment_id = f"oasis_clinical_{subject_id}"
                nodes.append(
                    {
                        "id": assessment_id,
                        "type": "ClinicalAssessment",
                        "properties": self.clinical_data[subject_id],
                    }
                )
                edges.append(
                    {
                        "source": subject_node_id,
                        "target": assessment_id,
                        "type": "HAS_ASSESSMENT",
                    }
                )

            # Imaging nodes
            if subject_id in self.imaging_data:
                imaging_id = f"oasis_imaging_{subject_id}"
                nodes.append(
                    {
                        "id": imaging_id,
                        "type": "ImagingData",
                        "properties": self.imaging_data[subject_id],
                    }
                )
                edges.append(
                    {
                        "source": subject_node_id,
                        "target": imaging_id,
                        "type": "HAS_IMAGING",
                    }
                )

            # Longitudinal trajectory
            if subject_id in self.longitudinal_data:
                trajectory_id = f"oasis_trajectory_{subject_id}"
                nodes.append(
                    {
                        "id": trajectory_id,
                        "type": "LongitudinalTrajectory",
                        "properties": {
                            "n_visits": self.longitudinal_data[subject_id]["n_visits"],
                            "follow_up_years": self.longitudinal_data[subject_id][
                                "follow_up_years"
                            ],
                            "converted": self.longitudinal_data[subject_id].get(
                                "converted", False
                            ),
                        },
                    }
                )
                edges.append(
                    {
                        "source": subject_node_id,
                        "target": trajectory_id,
                        "type": "HAS_TRAJECTORY",
                    }
                )

        return {
            "nodes": nodes,
            "edges": edges,
            "metadata": {
                "dataset": "Open Access Series of Imaging Studies",
                "total_subjects": len(all_subjects),
                "datasets": ["OASIS-1", "OASIS-2", "OASIS-3"],
                "focus": "Aging and Alzheimer's Disease",
                "modalities": ["T1", "T2", "FLAIR", "DTI", "fMRI", "PET"],
            },
        }

    def get_statistics(self) -> Dict[str, Any]:
        """Get dataset statistics.

        Returns:
            Statistics dictionary
        """
        all_subjects = list(set(self.subjects + list(self.longitudinal_data.keys())))

        # Age distribution
        ages = [
            self.demographics.get(s, {}).get("age", 0)
            for s in self.subjects
            if s in self.demographics
        ]

        # CDR distribution
        cdr_counts = {}
        for s in self.clinical_data.values():
            cdr = s.get("cdr", 0)
            cdr_label = self.cdr_scale.get(cdr, "Unknown")
            cdr_counts[cdr_label] = cdr_counts.get(cdr_label, 0) + 1

        converters = self.identify_converters()

        stats = {
            "total_subjects": len(all_subjects),
            "cross_sectional_subjects": len(self.subjects),
            "longitudinal_subjects": len(self.longitudinal_data),
            "age_range": (min(ages), max(ages)) if ages else (0, 0),
            "mean_age": np.mean(ages) if ages else 0,
            "cdr_distribution": cdr_counts,
            "n_converters": len(converters),
            "conversion_rate": len(converters) / max(1, len(self.longitudinal_data)),
        }

        # Gender distribution
        genders = [
            self.demographics.get(s, {}).get("gender", "U")
            for s in self.subjects
            if s in self.demographics
        ]
        stats["gender_distribution"] = {
            "M": genders.count("M"),
            "F": genders.count("F"),
        }

        return stats
