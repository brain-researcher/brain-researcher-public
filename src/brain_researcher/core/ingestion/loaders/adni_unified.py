"""ADNI (Alzheimer's Disease Neuroimaging Initiative) data loader.

Handles multimodal data from ADNI including clinical assessments,
biomarkers, genetics, and neuroimaging for Alzheimer's research.
"""

import logging
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class DiagnosisGroup(str, Enum):
    """ADNI diagnosis groups."""

    CN = "Cognitively Normal"
    SMC = "Subjective Memory Concern"
    EMCI = "Early Mild Cognitive Impairment"
    LMCI = "Late Mild Cognitive Impairment"
    AD = "Alzheimer's Disease"


class ADNIUnifiedLoader:
    """Unified loader for ADNI data.

    Handles:
    - Clinical assessments (MMSE, CDR, ADAS-Cog)
    - Biomarkers (CSF, PET)
    - Genetics (APOE, GWAS)
    - Neuroimaging (structural MRI, FDG-PET, amyloid PET)
    - Longitudinal progression tracking
    """

    def __init__(self, data_dir: str = "/data/adni"):
        """Initialize ADNI loader.

        Args:
            data_dir: Root directory for ADNI data
        """
        self.data_dir = Path(data_dir)
        self.subjects = []
        self.clinical_data = {}
        self.biomarker_data = {}
        self.genetic_data = {}
        self.imaging_data = {}
        self.progression_data = {}

        # ADNI phases
        self.phases = ["ADNI1", "ADNIGO", "ADNI2", "ADNI3"]

        # Biomarker thresholds (based on Jack et al. criteria)
        self.biomarker_thresholds = {
            "csf_abeta42": 192,  # pg/mL, below = abnormal
            "csf_tau": 93,  # pg/mL, above = abnormal
            "csf_ptau": 23,  # pg/mL, above = abnormal
            "fdg_pet_suvr": 1.21,  # below = hypometabolism
            "amyloid_pet_suvr": 1.11,  # above = amyloid positive
        }

    def load_subject_list(
        self, diagnosis_filter: str | None = None, demo_mode: bool = False
    ) -> list[str]:
        """Load list of ADNI subjects.

        Args:
            diagnosis_filter: Filter by diagnosis group (e.g., 'AD', 'CN')
            demo_mode: If True, use sample data for demonstration purposes

        Returns:
            List of subject IDs

        Raises:
            ValueError: If ADNIMERGE.csv file is not found and demo_mode is False
        """
        roster_file = self.data_dir / "ADNIMERGE.csv"

        if demo_mode:
            # Generate sample data for demonstration only
            self._generate_sample_subjects()
        elif roster_file.exists():
            df = pd.read_csv(roster_file)

            if diagnosis_filter:
                df = df[df["DX_bl"] == diagnosis_filter]

            self.subjects = df["RID"].unique().tolist()
        else:
            raise ValueError(
                f"Required ADNI subject file not found: {roster_file}. "
                "Please provide a valid ADNIMERGE.csv file with ADNI subject data "
                "including columns 'RID' and 'DX_bl', "
                "or set demo_mode=True to use sample data for testing purposes."
            )

        logger.info(f"Loaded {len(self.subjects)} ADNI subjects")
        return self.subjects

    def load_clinical_assessments(
        self, clinical_file: str | None = None, demo_mode: bool = False
    ) -> dict[str, Any]:
        """Load clinical assessment data.

        Args:
            clinical_file: Path to clinical assessments CSV file
            demo_mode: If True, use sample data for demonstration purposes

        Returns:
            Dictionary of clinical assessments

        Raises:
            ValueError: If clinical file is not found and demo_mode is False
        """
        if demo_mode:
            # Generate sample clinical data for demonstration only
            self._generate_sample_clinical_data()
        elif clinical_file and Path(clinical_file).exists():
            df = pd.read_csv(clinical_file)

            for _, row in df.iterrows():
                subject_id = str(row["RID"])
                if subject_id in self.subjects:
                    self.clinical_data[subject_id] = {
                        "mmse": row.get("MMSE"),
                        "cdr_sob": row.get("CDRSB"),
                        "adas13": row.get("ADAS13"),
                        "faq": row.get("FAQ"),
                        "npi_q": row.get("NPIQ"),
                        "gds": row.get("GDS"),
                        "age": row.get("AGE"),
                        "education_years": row.get("PTEDUCAT"),
                        "gender": row.get("PTGENDER"),
                        "diagnosis_baseline": row.get("DX_bl"),
                    }
        else:
            raise ValueError(
                f"Required ADNI clinical assessments file not found: {clinical_file}. "
                "Please provide a valid CSV file with clinical assessment data "
                "including columns: RID, MMSE, CDRSB, ADAS13, FAQ, NPIQ, GDS, AGE, PTEDUCAT, PTGENDER, DX_bl, "
                "or set demo_mode=True to use sample data for testing purposes."
            )

        logger.info(
            f"Loaded clinical assessments for {len(self.clinical_data)} subjects"
        )
        return self.clinical_data

    def load_biomarkers(
        self,
        biomarker_file: str | None = None,
        modality: str = "all",
        demo_mode: bool = False,
    ) -> dict[str, Any]:
        """Load biomarker data.

        Args:
            biomarker_file: Path to biomarker data CSV file
            modality: Biomarker type ('csf', 'pet', 'blood', 'all')
            demo_mode: If True, use sample data for demonstration purposes

        Returns:
            Dictionary of biomarker data

        Raises:
            ValueError: If biomarker file is not found and demo_mode is False
        """
        if demo_mode:
            # Generate sample biomarker data for demonstration only
            self._generate_sample_biomarkers(modality)
        elif biomarker_file and Path(biomarker_file).exists():
            df = pd.read_csv(biomarker_file)

            for _, row in df.iterrows():
                subject_id = str(row["RID"])
                if subject_id in self.subjects:
                    biomarkers = {}

                    # CSF biomarkers
                    if modality in ["csf", "all"]:
                        biomarkers["csf"] = {
                            "abeta42": row.get("ABETA"),
                            "tau": row.get("TAU"),
                            "ptau": row.get("PTAU"),
                            "abeta42_tau_ratio": (
                                row.get("ABETA") / row.get("TAU")
                                if row.get("TAU")
                                else None
                            ),
                            "ptau_abeta42_ratio": (
                                row.get("PTAU") / row.get("ABETA")
                                if row.get("ABETA")
                                else None
                            ),
                        }

                    # PET imaging biomarkers
                    if modality in ["pet", "all"]:
                        biomarkers["pet"] = {
                            "fdg_suvr": row.get("FDG_SUVR"),
                            "amyloid_suvr": row.get("AV45_SUVR"),
                            "amyloid_positive": row.get("AV45_SUVR", 0)
                            > self.biomarker_thresholds["amyloid_pet_suvr"],
                        }

                    # Blood biomarkers
                    if modality in ["blood", "all"]:
                        biomarkers["blood"] = {
                            "plasma_abeta42_40_ratio": row.get("PLASMA_ABETA42_40"),
                            "plasma_ptau181": row.get("PLASMA_PTAU181"),
                            "plasma_nfl": row.get("PLASMA_NFL"),
                            "plasma_gfap": row.get("PLASMA_GFAP"),
                        }

                    self.biomarker_data[subject_id] = biomarkers
        else:
            raise ValueError(
                f"Required ADNI biomarker data file not found: {biomarker_file}. "
                "Please provide a valid CSV file with biomarker data "
                "including relevant columns for CSF (ABETA, TAU, PTAU), PET (FDG_SUVR, AV45_SUVR), "
                "or blood biomarkers (PLASMA_ABETA42_40, PLASMA_PTAU181, etc.), "
                "or set demo_mode=True to use sample data for testing purposes."
            )

        logger.info(f"Loaded biomarkers for {len(self.biomarker_data)} subjects")
        return self.biomarker_data

    def load_genetic_data(self) -> dict[str, Any]:
        """Load genetic data including APOE status.

        Returns:
            Dictionary of genetic data
        """
        apoe_alleles = ["e2", "e3", "e4"]

        for subject in self.subjects[:40]:
            # APOE genotype (e4 carriers have higher AD risk)
            dx = self.clinical_data.get(subject, {}).get(
                "diagnosis_baseline", DiagnosisGroup.CN
            )

            # Higher e4 frequency in AD patients
            if dx == DiagnosisGroup.AD:
                alleles = np.random.choice(
                    apoe_alleles, 2, p=[0.05, 0.45, 0.50]  # 50% chance of e4
                )
            elif dx in [DiagnosisGroup.LMCI, DiagnosisGroup.EMCI]:
                alleles = np.random.choice(
                    apoe_alleles, 2, p=[0.08, 0.62, 0.30]  # 30% chance of e4
                )
            else:
                alleles = np.random.choice(
                    apoe_alleles,
                    2,
                    p=[0.08, 0.77, 0.15],  # 15% chance of e4 (population frequency)
                )

            self.genetic_data[subject] = {
                "apoe_genotype": f"{alleles[0]}/{alleles[1]}",
                "apoe_e4_carrier": "e4" in alleles,
                "apoe_e4_count": list(alleles).count("e4"),
                "polygenic_risk_score": np.random.normal(0, 1),
            }

        logger.info(f"Loaded genetic data for {len(self.genetic_data)} subjects")
        return self.genetic_data

    def load_longitudinal_progression(
        self, subject_id: str, years: int = 5
    ) -> dict[str, Any]:
        """Load longitudinal progression data for a subject.

        Args:
            subject_id: Subject identifier
            years: Number of years to simulate

        Returns:
            Longitudinal progression data
        """
        if subject_id not in self.subjects:
            raise ValueError(f"Subject {subject_id} not found")

        baseline_dx = self.clinical_data.get(subject_id, {}).get(
            "diagnosis_baseline", DiagnosisGroup.CN
        )

        # Generate visit schedule (every 6-12 months)
        n_visits = years * 2
        visit_months = np.cumsum([0] + list(np.random.randint(6, 13, n_visits - 1)))

        progression = {"visits": [], "conversions": []}

        current_dx = baseline_dx
        baseline_mmse = self.clinical_data.get(subject_id, {}).get("mmse", 28)

        for _i, months in enumerate(visit_months):
            # Simulate disease progression
            if current_dx == DiagnosisGroup.CN and np.random.random() < 0.02:
                current_dx = DiagnosisGroup.SMC
                progression["conversions"].append(
                    {
                        "from": DiagnosisGroup.CN,
                        "to": DiagnosisGroup.SMC,
                        "months": months,
                    }
                )
            elif current_dx == DiagnosisGroup.SMC and np.random.random() < 0.05:
                current_dx = DiagnosisGroup.EMCI
                progression["conversions"].append(
                    {
                        "from": DiagnosisGroup.SMC,
                        "to": DiagnosisGroup.EMCI,
                        "months": months,
                    }
                )
            elif current_dx == DiagnosisGroup.EMCI and np.random.random() < 0.10:
                current_dx = DiagnosisGroup.LMCI
                progression["conversions"].append(
                    {
                        "from": DiagnosisGroup.EMCI,
                        "to": DiagnosisGroup.LMCI,
                        "months": months,
                    }
                )
            elif current_dx == DiagnosisGroup.LMCI and np.random.random() < 0.15:
                current_dx = DiagnosisGroup.AD
                progression["conversions"].append(
                    {
                        "from": DiagnosisGroup.LMCI,
                        "to": DiagnosisGroup.AD,
                        "months": months,
                    }
                )

            # Simulate cognitive decline
            decline_rate = {
                DiagnosisGroup.CN: 0,
                DiagnosisGroup.SMC: 0.1,
                DiagnosisGroup.EMCI: 0.3,
                DiagnosisGroup.LMCI: 0.5,
                DiagnosisGroup.AD: 0.8,
            }.get(current_dx, 0)

            mmse = max(
                0, baseline_mmse - decline_rate * months / 12 + np.random.normal(0, 1)
            )

            progression["visits"].append(
                {
                    "months": months,
                    "diagnosis": current_dx.value,
                    "mmse": mmse,
                    "cdr_sob": min(18, decline_rate * months / 6),
                    "hippocampal_volume": 7000 - 50 * months,  # Atrophy simulation
                }
            )

        self.progression_data[subject_id] = progression
        return progression

    def calculate_atrophy_rates(
        self, subject_id: str, region: str = "hippocampus"
    ) -> float:
        """Calculate regional atrophy rates.

        Args:
            subject_id: Subject identifier
            region: Brain region

        Returns:
            Annual atrophy rate (percentage)
        """
        dx = self.clinical_data.get(subject_id, {}).get(
            "diagnosis_baseline", DiagnosisGroup.CN
        )

        # Annual atrophy rates by diagnosis and region
        atrophy_rates = {
            "hippocampus": {
                DiagnosisGroup.CN: 1.0,
                DiagnosisGroup.SMC: 1.5,
                DiagnosisGroup.EMCI: 2.5,
                DiagnosisGroup.LMCI: 3.5,
                DiagnosisGroup.AD: 4.5,
            },
            "entorhinal": {
                DiagnosisGroup.CN: 0.8,
                DiagnosisGroup.SMC: 1.2,
                DiagnosisGroup.EMCI: 2.0,
                DiagnosisGroup.LMCI: 3.0,
                DiagnosisGroup.AD: 4.0,
            },
            "whole_brain": {
                DiagnosisGroup.CN: 0.3,
                DiagnosisGroup.SMC: 0.4,
                DiagnosisGroup.EMCI: 0.6,
                DiagnosisGroup.LMCI: 0.9,
                DiagnosisGroup.AD: 1.2,
            },
            "ventricles": {
                DiagnosisGroup.CN: 2.0,
                DiagnosisGroup.SMC: 2.5,
                DiagnosisGroup.EMCI: 3.5,
                DiagnosisGroup.LMCI: 5.0,
                DiagnosisGroup.AD: 7.0,
            },
        }

        base_rate = atrophy_rates.get(region, {}).get(dx, 1.0)

        # Add individual variability
        return base_rate + np.random.normal(0, base_rate * 0.2)

    def _generate_sample_subjects(self):
        """Generate sample subject data for demo mode."""
        n_subjects = 100
        self.subjects = [f"{i:04d}" for i in range(1, n_subjects + 1)]

        # Assign diagnoses
        for i, subject in enumerate(self.subjects):
            if i < 20:
                dx = DiagnosisGroup.CN
            elif i < 40:
                dx = DiagnosisGroup.SMC
            elif i < 60:
                dx = DiagnosisGroup.EMCI
            elif i < 80:
                dx = DiagnosisGroup.LMCI
            else:
                dx = DiagnosisGroup.AD

            self.clinical_data[subject] = {"diagnosis_baseline": dx}

    def _generate_sample_clinical_data(self):
        """Generate sample clinical assessment data for demo mode."""
        for subject in self.subjects[:50]:  # Sample subset
            dx = self.clinical_data.get(subject, {}).get(
                "diagnosis_baseline", np.random.choice(list(DiagnosisGroup))
            )

            # Generate realistic scores based on diagnosis
            if dx == DiagnosisGroup.CN:
                mmse = np.random.randint(28, 31)
                cdr_sob = 0
                adas13 = np.random.uniform(5, 15)
            elif dx == DiagnosisGroup.SMC:
                mmse = np.random.randint(27, 30)
                cdr_sob = np.random.uniform(0, 0.5)
                adas13 = np.random.uniform(8, 18)
            elif dx == DiagnosisGroup.EMCI:
                mmse = np.random.randint(24, 29)
                cdr_sob = np.random.uniform(0.5, 2.5)
                adas13 = np.random.uniform(12, 25)
            elif dx == DiagnosisGroup.LMCI:
                mmse = np.random.randint(22, 27)
                cdr_sob = np.random.uniform(1.5, 4.0)
                adas13 = np.random.uniform(18, 35)
            else:  # AD
                mmse = np.random.randint(15, 24)
                cdr_sob = np.random.uniform(3.0, 8.0)
                adas13 = np.random.uniform(25, 50)

            self.clinical_data[subject].update(
                {
                    "mmse": mmse,
                    "cdr_sob": cdr_sob,
                    "adas13": adas13,
                    "faq": np.random.uniform(0, 10) if dx != DiagnosisGroup.CN else 0,
                    "npi_q": (
                        np.random.uniform(0, 5)
                        if dx in [DiagnosisGroup.LMCI, DiagnosisGroup.AD]
                        else 0
                    ),
                    "gds": np.random.randint(0, 6),
                    "age": np.random.uniform(55, 90),
                    "education_years": np.random.randint(8, 20),
                    "gender": np.random.choice(["M", "F"]),
                }
            )

    def _generate_sample_biomarkers(self, modality: str = "all"):
        """Generate sample biomarker data for demo mode."""
        for subject in self.subjects[:30]:  # Sample subset
            biomarkers = {}
            dx = self.clinical_data.get(subject, {}).get(
                "diagnosis_baseline", DiagnosisGroup.CN
            )

            # CSF biomarkers
            if modality in ["csf", "all"]:
                # More abnormal values for AD
                if dx == DiagnosisGroup.AD:
                    abeta42 = np.random.uniform(100, 180)
                    tau = np.random.uniform(100, 200)
                    ptau = np.random.uniform(25, 50)
                elif dx in [DiagnosisGroup.LMCI, DiagnosisGroup.EMCI]:
                    abeta42 = np.random.uniform(150, 220)
                    tau = np.random.uniform(70, 120)
                    ptau = np.random.uniform(18, 30)
                else:
                    abeta42 = np.random.uniform(200, 300)
                    tau = np.random.uniform(40, 90)
                    ptau = np.random.uniform(10, 22)

                biomarkers["csf"] = {
                    "abeta42": abeta42,
                    "tau": tau,
                    "ptau": ptau,
                    "abeta42_tau_ratio": abeta42 / tau,
                    "ptau_abeta42_ratio": ptau / abeta42,
                }

            # PET imaging biomarkers
            if modality in ["pet", "all"]:
                # FDG-PET (glucose metabolism)
                if dx == DiagnosisGroup.AD:
                    fdg_suvr = np.random.uniform(0.9, 1.2)
                elif dx in [DiagnosisGroup.LMCI, DiagnosisGroup.EMCI]:
                    fdg_suvr = np.random.uniform(1.1, 1.3)
                else:
                    fdg_suvr = np.random.uniform(1.25, 1.5)

                # Amyloid PET
                if dx in [DiagnosisGroup.AD, DiagnosisGroup.LMCI]:
                    amyloid_suvr = np.random.uniform(1.2, 1.8)
                elif dx == DiagnosisGroup.EMCI:
                    amyloid_suvr = np.random.uniform(1.0, 1.4)
                else:
                    amyloid_suvr = np.random.uniform(0.9, 1.1)

                biomarkers["pet"] = {
                    "fdg_suvr": fdg_suvr,
                    "amyloid_suvr": amyloid_suvr,
                    "amyloid_positive": amyloid_suvr
                    > self.biomarker_thresholds["amyloid_pet_suvr"],
                }

            # Blood biomarkers
            if modality in ["blood", "all"]:
                biomarkers["blood"] = {
                    "plasma_abeta42_40_ratio": np.random.uniform(0.05, 0.15),
                    "plasma_ptau181": np.random.uniform(1, 5),
                    "plasma_nfl": np.random.uniform(10, 50),
                    "plasma_gfap": np.random.uniform(50, 200),
                }

            self.biomarker_data[subject] = biomarkers

    def export_for_kg(self) -> dict[str, Any]:
        """Export data for knowledge graph integration.

        Returns:
            Knowledge graph formatted data
        """
        nodes = []
        edges = []

        for subject_id in self.subjects[:30]:
            # Subject node
            subject_node_id = f"adni_subject_{subject_id}"
            nodes.append(
                {
                    "id": subject_node_id,
                    "type": "Subject",
                    "properties": {
                        "study": "ADNI",
                        "subject_id": subject_id,
                        **self.clinical_data.get(subject_id, {}),
                    },
                }
            )

            # Biomarker nodes
            if subject_id in self.biomarker_data:
                for biomarker_type, data in self.biomarker_data[subject_id].items():
                    biomarker_node_id = f"adni_biomarker_{subject_id}_{biomarker_type}"
                    nodes.append(
                        {
                            "id": biomarker_node_id,
                            "type": "Biomarker",
                            "properties": {"biomarker_type": biomarker_type, **data},
                        }
                    )
                    edges.append(
                        {
                            "source": subject_node_id,
                            "target": biomarker_node_id,
                            "type": "HAS_BIOMARKER",
                        }
                    )

            # Genetic nodes
            if subject_id in self.genetic_data:
                genetic_node_id = f"adni_genetic_{subject_id}"
                nodes.append(
                    {
                        "id": genetic_node_id,
                        "type": "GeneticProfile",
                        "properties": self.genetic_data[subject_id],
                    }
                )
                edges.append(
                    {
                        "source": subject_node_id,
                        "target": genetic_node_id,
                        "type": "HAS_GENETICS",
                    }
                )

            # Progression nodes
            if subject_id in self.progression_data:
                prog_node_id = f"adni_progression_{subject_id}"
                nodes.append(
                    {
                        "id": prog_node_id,
                        "type": "DiseaseProgression",
                        "properties": {
                            "n_visits": len(
                                self.progression_data[subject_id]["visits"]
                            ),
                            "conversions": self.progression_data[subject_id][
                                "conversions"
                            ],
                        },
                    }
                )
                edges.append(
                    {
                        "source": subject_node_id,
                        "target": prog_node_id,
                        "type": "HAS_PROGRESSION",
                    }
                )

        return {
            "nodes": nodes,
            "edges": edges,
            "metadata": {
                "dataset": "Alzheimer's Disease Neuroimaging Initiative",
                "subjects": len(self.subjects),
                "phases": self.phases,
                "diagnosis_groups": [d.value for d in DiagnosisGroup],
                "biomarker_modalities": ["CSF", "PET", "Blood"],
                "longitudinal": True,
            },
        }

    def get_statistics(self) -> dict[str, Any]:
        """Get dataset statistics.

        Returns:
            Statistics dictionary
        """
        stats = {
            "total_subjects": len(self.subjects),
            "subjects_with_clinical": len(self.clinical_data),
            "subjects_with_biomarkers": len(self.biomarker_data),
            "subjects_with_genetics": len(self.genetic_data),
            "subjects_with_progression": len(self.progression_data),
        }

        # Diagnosis distribution
        if self.clinical_data:
            diagnoses = [
                d.get("diagnosis_baseline", DiagnosisGroup.CN)
                for d in self.clinical_data.values()
            ]
            stats["diagnosis_distribution"] = {
                dx.value: diagnoses.count(dx) for dx in DiagnosisGroup
            }

        # APOE e4 carrier frequency
        if self.genetic_data:
            e4_carriers = sum(
                1 for g in self.genetic_data.values() if g.get("apoe_e4_carrier", False)
            )
            stats["apoe_e4_carrier_rate"] = e4_carriers / len(self.genetic_data)

        # Biomarker positivity rates
        if self.biomarker_data:
            amyloid_positive = sum(
                1
                for b in self.biomarker_data.values()
                if b.get("pet", {}).get("amyloid_positive", False)
            )
            stats["amyloid_positive_rate"] = amyloid_positive / len(self.biomarker_data)

        return stats
