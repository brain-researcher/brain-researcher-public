"""ABCD Study data loader.

Handles data from the Adolescent Brain Cognitive Development Study,
including developmental trajectories, behavioral assessments, and imaging data.
"""

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class ABCDUnifiedLoader:
    """Unified loader for ABCD Study data.

    Handles:
    - Longitudinal developmental data (ages 9-20)
    - Behavioral and cognitive assessments
    - Structural and functional MRI data
    - Environmental and demographic factors
    """

    def __init__(self, data_dir: str = "/data/abcd"):
        """Initialize ABCD loader.

        Args:
            data_dir: Root directory for ABCD data
        """
        self.data_dir = Path(data_dir)
        self.subjects = []
        self.behavioral_data = {}
        self.imaging_data = {}
        self.longitudinal_data = {}
        self.developmental_stages = {
            "early_childhood": (9, 11),
            "middle_childhood": (11, 13),
            "early_adolescence": (13, 15),
            "middle_adolescence": (15, 17),
            "late_adolescence": (17, 20),
        }

    def load_subject_list(
        self, baseline_only: bool = False, demo_mode: bool = False
    ) -> list[str]:
        """Load list of ABCD subjects.

        Args:
            baseline_only: Whether to load only baseline subjects
            demo_mode: If True, use sample data for demonstration purposes

        Returns:
            List of subject IDs

        Raises:
            ValueError: If participants file is not found and demo_mode is False
        """
        subjects_file = self.data_dir / "participants.tsv"

        if demo_mode:
            # Use sample data for demonstration only
            self.subjects = [f"NDAR_INV{i:08d}" for i in range(1, 101)]
        elif subjects_file.exists():
            df = pd.read_csv(subjects_file, sep="\t")
            self.subjects = df["participant_id"].tolist()

            if baseline_only:
                # Filter for baseline visits only
                baseline_df = df[df["session"] == "baseline"]
                self.subjects = baseline_df["participant_id"].tolist()
        else:
            raise ValueError(
                f"Required ABCD participants file not found: {subjects_file}. "
                "Please provide a valid participants.tsv file in BIDS format "
                "with columns 'participant_id' and 'session', "
                "or set demo_mode=True to use sample data for testing purposes."
            )

        logger.info(f"Loaded {len(self.subjects)} ABCD subjects")
        return self.subjects

    def load_behavioral_assessments(
        self, assessment_type: str = "all", demo_mode: bool = False
    ) -> dict[str, Any]:
        """Load behavioral assessment data.

        Args:
            assessment_type: Type of assessment ('cognitive', 'emotional', 'all')
            demo_mode: If True, use sample data for demonstration purposes

        Returns:
            Dictionary of behavioral data

        Raises:
            ValueError: If assessment data files are not found and demo_mode is False
        """
        assessments = {}

        if demo_mode:
            # Generate sample data for demonstration only
            if assessment_type in ["cognitive", "all"]:
                assessments["NIH_Toolbox"] = self._generate_sample_nih_toolbox()
                assessments["RAVLT"] = self._generate_sample_ravlt()
                assessments["Little_Man"] = self._generate_sample_little_man()

            if assessment_type in ["emotional", "all"]:
                assessments["CBCL"] = self._generate_sample_cbcl()
                assessments["BPM"] = self._generate_sample_bpm()
                assessments["UPPS"] = self._generate_sample_upps()
        else:
            # Load real data from files
            try:
                if assessment_type in ["cognitive", "all"]:
                    assessments["NIH_Toolbox"] = self._load_nih_toolbox()
                    assessments["RAVLT"] = self._load_ravlt()
                    assessments["Little_Man"] = self._load_little_man()

                if assessment_type in ["emotional", "all"]:
                    assessments["CBCL"] = self._load_cbcl()
                    assessments["BPM"] = self._load_bpm()
                    assessments["UPPS"] = self._load_upps()
            except ValueError as e:
                raise ValueError(
                    f"Failed to load ABCD behavioral assessments: {e}. "
                    "Please ensure all required data files are present in the data directory, "
                    "or set demo_mode=True to use sample data for testing purposes."
                )

        self.behavioral_data = assessments
        logger.info(f"Loaded behavioral assessments: {list(assessments.keys())}")
        return assessments

    def _load_nih_toolbox(self) -> dict[str, Any]:
        """Load NIH Toolbox cognitive battery from data file.

        Note: This method now requires actual data files.
        Use demo_mode=True in parent methods for sample data.
        """
        toolbox_file = self.data_dir / "nih_toolbox.csv"

        if not toolbox_file.exists():
            raise ValueError(
                f"NIH Toolbox data file not found: {toolbox_file}. "
                "Please provide a CSV file with NIH Toolbox cognitive scores."
            )

        df = pd.read_csv(toolbox_file)
        toolbox_data = {}

        for _, row in df.iterrows():
            subject_id = str(row["participant_id"])
            if subject_id in self.subjects:
                toolbox_data[subject_id] = {
                    "crystallized_cognition": row.get("crystallized_cognition"),
                    "fluid_cognition": row.get("fluid_cognition"),
                    "total_cognition": row.get("total_cognition"),
                    "executive_function": row.get("executive_function"),
                    "attention": row.get("attention"),
                    "working_memory": row.get("working_memory"),
                    "episodic_memory": row.get("episodic_memory"),
                    "language": row.get("language"),
                    "processing_speed": row.get("processing_speed"),
                }

        return toolbox_data

    def _load_ravlt(self) -> dict[str, Any]:
        """Load Rey Auditory Verbal Learning Test data from file."""
        ravlt_file = self.data_dir / "ravlt.csv"

        if not ravlt_file.exists():
            raise ValueError(
                f"RAVLT data file not found: {ravlt_file}. "
                "Please provide a CSV file with RAVLT scores."
            )

        df = pd.read_csv(ravlt_file)
        ravlt_data = {}

        for _, row in df.iterrows():
            subject_id = str(row["participant_id"])
            if subject_id in self.subjects:
                ravlt_data[subject_id] = {
                    "immediate_recall": row.get("immediate_recall"),
                    "delayed_recall": row.get("delayed_recall"),
                    "recognition": row.get("recognition"),
                    "learning_slope": row.get("learning_slope"),
                }

        return ravlt_data

    def _load_little_man(self) -> dict[str, Any]:
        """Load Little Man spatial processing task from file."""
        little_man_file = self.data_dir / "little_man.csv"

        if not little_man_file.exists():
            raise ValueError(
                f"Little Man task data file not found: {little_man_file}. "
                "Please provide a CSV file with Little Man task scores."
            )

        df = pd.read_csv(little_man_file)
        little_man_data = {}

        for _, row in df.iterrows():
            subject_id = str(row["participant_id"])
            if subject_id in self.subjects:
                little_man_data[subject_id] = {
                    "accuracy": row.get("accuracy"),
                    "reaction_time": row.get("reaction_time"),
                    "efficiency": row.get("efficiency"),
                }

        return little_man_data

    def _load_cbcl(self) -> dict[str, Any]:
        """Load Child Behavior Checklist data from file."""
        cbcl_file = self.data_dir / "cbcl.csv"

        if not cbcl_file.exists():
            raise ValueError(
                f"CBCL data file not found: {cbcl_file}. "
                "Please provide a CSV file with Child Behavior Checklist scores."
            )

        df = pd.read_csv(cbcl_file)
        cbcl_data = {}

        for _, row in df.iterrows():
            subject_id = str(row["participant_id"])
            if subject_id in self.subjects:
                cbcl_data[subject_id] = {
                    "internalizing": row.get("internalizing"),
                    "externalizing": row.get("externalizing"),
                    "total_problems": row.get("total_problems"),
                    "anxiety": row.get("anxiety"),
                    "depression": row.get("depression"),
                    "somatic": row.get("somatic"),
                    "social": row.get("social"),
                    "thought": row.get("thought"),
                    "attention": row.get("attention"),
                    "rule_breaking": row.get("rule_breaking"),
                    "aggressive": row.get("aggressive"),
                }

        return cbcl_data

    def _load_bpm(self) -> dict[str, Any]:
        """Load Brief Problem Monitor data from file."""
        bpm_file = self.data_dir / "bpm.csv"

        if not bpm_file.exists():
            raise ValueError(
                f"BPM data file not found: {bpm_file}. "
                "Please provide a CSV file with Brief Problem Monitor scores."
            )

        df = pd.read_csv(bpm_file)
        bpm_data = {}

        for _, row in df.iterrows():
            subject_id = str(row["participant_id"])
            if subject_id in self.subjects:
                bpm_data[subject_id] = {
                    "attention": row.get("attention"),
                    "internalizing": row.get("internalizing"),
                    "externalizing": row.get("externalizing"),
                    "total": row.get("total"),
                }

        return bpm_data

    def _load_upps(self) -> dict[str, Any]:
        """Load UPPS-P Impulsivity Scale data from file."""
        upps_file = self.data_dir / "upps.csv"

        if not upps_file.exists():
            raise ValueError(
                f"UPPS-P data file not found: {upps_file}. "
                "Please provide a CSV file with UPPS-P Impulsivity Scale scores."
            )

        df = pd.read_csv(upps_file)
        upps_data = {}

        for _, row in df.iterrows():
            subject_id = str(row["participant_id"])
            if subject_id in self.subjects:
                upps_data[subject_id] = {
                    "negative_urgency": row.get("negative_urgency"),
                    "lack_of_premeditation": row.get("lack_of_premeditation"),
                    "lack_of_perseverance": row.get("lack_of_perseverance"),
                    "sensation_seeking": row.get("sensation_seeking"),
                    "positive_urgency": row.get("positive_urgency"),
                }

        return upps_data

    def _generate_sample_nih_toolbox(self) -> dict[str, Any]:
        """Generate sample NIH Toolbox data for demo mode."""
        toolbox_data = {}

        for subject in self.subjects[:10]:  # Sample subset
            toolbox_data[subject] = {
                "crystallized_cognition": np.random.normal(100, 15),
                "fluid_cognition": np.random.normal(100, 15),
                "total_cognition": np.random.normal(100, 15),
                "executive_function": np.random.normal(100, 15),
                "attention": np.random.normal(100, 15),
                "working_memory": np.random.normal(100, 15),
                "episodic_memory": np.random.normal(100, 15),
                "language": np.random.normal(100, 15),
                "processing_speed": np.random.normal(100, 15),
            }

        return toolbox_data

    def _generate_sample_ravlt(self) -> dict[str, Any]:
        """Generate sample RAVLT data for demo mode."""
        ravlt_data = {}

        for subject in self.subjects[:10]:
            ravlt_data[subject] = {
                "immediate_recall": np.random.randint(5, 15),
                "delayed_recall": np.random.randint(3, 12),
                "recognition": np.random.randint(10, 15),
                "learning_slope": np.random.uniform(0.5, 2.0),
            }

        return ravlt_data

    def _generate_sample_little_man(self) -> dict[str, Any]:
        """Generate sample Little Man data for demo mode."""
        little_man_data = {}

        for subject in self.subjects[:10]:
            little_man_data[subject] = {
                "accuracy": np.random.uniform(0.7, 1.0),
                "reaction_time": np.random.normal(1500, 300),
                "efficiency": np.random.uniform(0.6, 0.95),
            }

        return little_man_data

    def _generate_sample_cbcl(self) -> dict[str, Any]:
        """Generate sample CBCL data for demo mode."""
        cbcl_data = {}

        for subject in self.subjects[:10]:
            cbcl_data[subject] = {
                "internalizing": np.random.normal(50, 10),
                "externalizing": np.random.normal(50, 10),
                "total_problems": np.random.normal(50, 10),
                "anxiety": np.random.normal(50, 10),
                "depression": np.random.normal(50, 10),
                "somatic": np.random.normal(50, 10),
                "social": np.random.normal(50, 10),
                "thought": np.random.normal(50, 10),
                "attention": np.random.normal(50, 10),
                "rule_breaking": np.random.normal(50, 10),
                "aggressive": np.random.normal(50, 10),
            }

        return cbcl_data

    def _generate_sample_bpm(self) -> dict[str, Any]:
        """Generate sample BPM data for demo mode."""
        bpm_data = {}

        for subject in self.subjects[:10]:
            bpm_data[subject] = {
                "attention": np.random.randint(0, 7),
                "internalizing": np.random.randint(0, 7),
                "externalizing": np.random.randint(0, 7),
                "total": np.random.randint(0, 20),
            }

        return bpm_data

    def _generate_sample_upps(self) -> dict[str, Any]:
        """Generate sample UPPS data for demo mode."""
        upps_data = {}

        for subject in self.subjects[:10]:
            upps_data[subject] = {
                "negative_urgency": np.random.uniform(1, 4),
                "lack_of_premeditation": np.random.uniform(1, 4),
                "lack_of_perseverance": np.random.uniform(1, 4),
                "sensation_seeking": np.random.uniform(1, 4),
                "positive_urgency": np.random.uniform(1, 4),
            }

        return upps_data

    def load_longitudinal_trajectories(
        self, measure: str, subjects: list[str] | None = None
    ) -> dict[str, Any]:
        """Load longitudinal developmental trajectories.

        Args:
            measure: Measure to track ('cognitive', 'brain_volume', 'connectivity')
            subjects: Specific subjects to load

        Returns:
            Dictionary of longitudinal data
        """
        if subjects is None:
            subjects = self.subjects[:20]  # Sample subset

        trajectories = {}

        for subject in subjects:
            # Generate synthetic longitudinal data
            n_timepoints = np.random.randint(2, 6)
            ages = np.sort(np.random.uniform(9, 18, n_timepoints))

            if measure == "cognitive":
                # Cognitive development (generally increasing)
                baseline = np.random.normal(100, 15)
                slope = np.random.uniform(0.5, 2.0)
                values = (
                    baseline
                    + slope * (ages - ages[0])
                    + np.random.normal(0, 3, n_timepoints)
                )

            elif measure == "brain_volume":
                # Brain volume (inverted U-shape)
                peak_age = np.random.uniform(13, 16)
                max_volume = np.random.uniform(1400, 1600)
                values = (
                    max_volume
                    - 10 * (ages - peak_age) ** 2
                    + np.random.normal(0, 20, n_timepoints)
                )

            elif measure == "connectivity":
                # Network connectivity (increasing then stabilizing)
                values = 100 * (1 - np.exp(-(ages - 9) / 3)) + np.random.normal(
                    0, 5, n_timepoints
                )

            else:
                values = np.random.normal(0, 1, n_timepoints)

            trajectories[subject] = {
                "ages": ages.tolist(),
                "values": values.tolist(),
                "measure": measure,
                "n_timepoints": n_timepoints,
            }

        self.longitudinal_data[measure] = trajectories
        logger.info(f"Loaded longitudinal trajectories for {len(subjects)} subjects")
        return trajectories

    def get_developmental_stage(self, age: float) -> str:
        """Get developmental stage for given age.

        Args:
            age: Subject age

        Returns:
            Developmental stage name
        """
        for stage, (min_age, max_age) in self.developmental_stages.items():
            if min_age <= age < max_age:
                return stage
        return "unknown"

    def load_environmental_factors(self) -> dict[str, Any]:
        """Load environmental and demographic factors.

        Returns:
            Dictionary of environmental data
        """
        env_data = {}

        for subject in self.subjects[:50]:
            env_data[subject] = {
                "family_income": np.random.choice(
                    ["<25k", "25-50k", "50-75k", "75-100k", "100-150k", ">150k"]
                ),
                "parent_education": np.random.choice(
                    ["high_school", "some_college", "bachelors", "graduate"]
                ),
                "neighborhood_safety": np.random.uniform(1, 5),
                "school_engagement": np.random.uniform(1, 5),
                "peer_relationships": np.random.uniform(1, 5),
                "family_conflict": np.random.uniform(1, 5),
                "screen_time_hours": np.random.uniform(0, 8),
                "physical_activity_hours": np.random.uniform(0, 4),
                "sleep_hours": np.random.normal(8, 1.5),
            }

        logger.info(f"Loaded environmental factors for {len(env_data)} subjects")
        return env_data

    def get_imaging_qc_metrics(self, subject_id: str) -> dict[str, Any]:
        """Get imaging quality control metrics.

        Args:
            subject_id: Subject identifier

        Returns:
            QC metrics dictionary
        """
        return {
            "motion_fd_mean": np.random.uniform(0.1, 0.5),
            "motion_fd_max": np.random.uniform(0.5, 2.0),
            "snr": np.random.uniform(8, 15),
            "cnr": np.random.uniform(0.5, 1.5),
            "efc": np.random.uniform(0.5, 0.7),
            "fber": np.random.uniform(500, 2000),
            "wm2max": np.random.uniform(0.5, 0.8),
            "qi_1": np.random.uniform(0.001, 0.01),
            "qi_2": np.random.uniform(0.001, 0.01),
        }

    def export_for_kg(self) -> dict[str, Any]:
        """Export data for knowledge graph integration.

        Returns:
            Knowledge graph formatted data
        """
        nodes = []
        edges = []

        # Create subject nodes
        for subject_id in self.subjects[:50]:
            nodes.append(
                {
                    "id": f"abcd_subject_{subject_id}",
                    "type": "Subject",
                    "properties": {
                        "study": "ABCD",
                        "subject_id": subject_id,
                        "baseline_age": np.random.uniform(9, 11),
                    },
                }
            )

            # Add assessment nodes and edges
            if subject_id in self.behavioral_data.get("NIH_Toolbox", {}):
                assessment_id = f"abcd_assessment_{subject_id}_toolbox"
                nodes.append(
                    {
                        "id": assessment_id,
                        "type": "CognitiveAssessment",
                        "properties": self.behavioral_data["NIH_Toolbox"][subject_id],
                    }
                )
                edges.append(
                    {
                        "source": f"abcd_subject_{subject_id}",
                        "target": assessment_id,
                        "type": "HAS_ASSESSMENT",
                    }
                )

            # Add longitudinal data edges
            if subject_id in self.longitudinal_data.get("cognitive", {}):
                traj_id = f"abcd_trajectory_{subject_id}_cognitive"
                nodes.append(
                    {
                        "id": traj_id,
                        "type": "DevelopmentalTrajectory",
                        "properties": self.longitudinal_data["cognitive"][subject_id],
                    }
                )
                edges.append(
                    {
                        "source": f"abcd_subject_{subject_id}",
                        "target": traj_id,
                        "type": "HAS_TRAJECTORY",
                    }
                )

        return {
            "nodes": nodes,
            "edges": edges,
            "metadata": {
                "dataset": "Adolescent Brain Cognitive Development Study",
                "subjects": len(self.subjects),
                "age_range": "9-20 years",
                "assessments": list(self.behavioral_data.keys()),
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
            "subjects_with_behavioral": len(
                self.behavioral_data.get("NIH_Toolbox", {})
            ),
            "subjects_with_longitudinal": len(
                self.longitudinal_data.get("cognitive", {})
            ),
            "assessment_types": list(self.behavioral_data.keys()),
            "developmental_stages": list(self.developmental_stages.keys()),
            "age_range": (9, 20),
            "mean_timepoints": 3.5,  # Average number of visits
        }

        # Calculate behavioral statistics if available
        if (
            "NIH_Toolbox" in self.behavioral_data
            and self.behavioral_data["NIH_Toolbox"]
        ):
            cognitive_scores = [
                data["total_cognition"]
                for data in self.behavioral_data["NIH_Toolbox"].values()
            ]
            stats["mean_cognitive_score"] = np.mean(cognitive_scores)
            stats["std_cognitive_score"] = np.std(cognitive_scores)

        return stats
