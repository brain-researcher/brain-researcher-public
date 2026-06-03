"""Unified loader for ENIGMA Consortium meta-analysis data."""

import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)


def _cache_root() -> Path:
    base = Path(os.getenv("XDG_CACHE_HOME", str(Path.home() / ".cache"))).expanduser()
    return base / "brain_researcher"


def _default_cache_dir(name: str) -> Path:
    return _cache_root() / name


class ENIGMAUnifiedLoader:
    """Loader for ENIGMA Consortium neuroimaging meta-analysis data.

    ENIGMA (Enhancing Neuro Imaging Genetics through Meta Analysis) is a
    global collaboration studying brain structure, function, and disease
    across multiple cohorts and working groups.

    Supports loading:
    - Working group data (e.g., Schizophrenia, Bipolar, PTSD, etc.)
    - Effect sizes and sample sizes from meta-analyses
    - Brain measures (subcortical volumes, cortical thickness, white matter)
    - Quality metrics and publication bias assessments
    - Cross-cohort harmonization data
    """

    def __init__(
        self,
        data_dir: str | None = None,
        working_groups_dir: str | None = None,
        results_dir: str | None = None,
        cache_dir: str | None = None,
    ):
        """Initialize ENIGMA loader.

        Args:
            data_dir: Base ENIGMA data directory
            working_groups_dir: Directory containing working group data
            results_dir: Directory containing meta-analysis results
            cache_dir: Cache directory for processed data
        """
        self.data_dir = Path(data_dir) if data_dir else None
        self.working_groups_dir = (
            Path(working_groups_dir) if working_groups_dir else None
        )
        self.results_dir = Path(results_dir) if results_dir else None
        cache_dir = cache_dir or str(_default_cache_dir("enigma_cache"))
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
                tempfile.mkdtemp(prefix="enigma_cache_", dir=str(fallback_root))
            )
            logger.warning(
                "Default ENIGMA cache dir %s not writable (%s); using %s",
                preferred_cache,
                exc,
                fallback,
            )
            self.cache_dir = fallback

        # ENIGMA data structure
        self.working_groups = {}
        self.meta_analysis_results = {}
        self.brain_measures = {}
        self.quality_metrics = {}
        self.cohort_data = {}

        # ENIGMA working groups
        self.available_working_groups = [
            "ENIGMA-Schizophrenia",
            "ENIGMA-Bipolar",
            "ENIGMA-MDD",  # Major Depressive Disorder
            "ENIGMA-PTSD",
            "ENIGMA-OCD",
            "ENIGMA-ADHD",
            "ENIGMA-Autism",
            "ENIGMA-Addiction",
            "ENIGMA-Epilepsy",
            "ENIGMA-Parkinsons",
        ]

        # Standard brain measures
        self.brain_measures_config = {
            "subcortical": [
                "lateral_ventricles",
                "thalamus",
                "caudate",
                "putamen",
                "pallidum",
                "hippocampus",
                "amygdala",
                "accumbens",
                "brain_stem",
            ],
            "cortical": ["thickness", "surface_area", "volume"],
            "white_matter": [
                "fractional_anisotropy",
                "mean_diffusivity",
                "radial_diffusivity",
                "axial_diffusivity",
            ],
        }

        # Meta-analysis metrics
        self.meta_analysis_metrics = [
            "cohens_d",
            "hedge_g",
            "standard_error",
            "confidence_interval",
            "p_value",
            "q_statistic",
            "i2_heterogeneity",
            "tau_squared",
        ]

    def load_working_groups(
        self, groups: list[str] | None = None, demo_mode: bool = False
    ) -> dict[str, Any]:
        """Load ENIGMA working group data.

        Args:
            groups: Specific working groups to load (None = all)
            demo_mode: Use synthetic data for testing

        Returns:
            Dictionary with working group data
        """
        if demo_mode:
            working_groups = self._generate_demo_working_groups(groups)
        elif self.working_groups_dir and self.working_groups_dir.exists():
            working_groups = {}
            groups = groups or self.available_working_groups

            for group_name in groups:
                group_dir = self.working_groups_dir / group_name.lower().replace(
                    "-", "_"
                )
                if group_dir.exists():
                    working_groups[group_name] = self._load_working_group_data(
                        group_dir
                    )
                else:
                    logger.warning(f"Working group directory not found: {group_dir}")
        else:
            raise ValueError(
                "Working groups directory not found. Please provide a valid ENIGMA "
                "working groups directory or use demo_mode=True"
            )

        self.working_groups = working_groups
        logger.info(f"Loaded {len(working_groups)} ENIGMA working groups")
        return working_groups

    def load_meta_analysis_results(
        self, analysis_types: list[str] | None = None, demo_mode: bool = False
    ) -> dict[str, Any]:
        """Load ENIGMA meta-analysis results.

        Args:
            analysis_types: Types of analyses to load
            demo_mode: Use synthetic data for testing

        Returns:
            Dictionary with meta-analysis results
        """
        if demo_mode:
            meta_analysis_results = self._generate_demo_meta_analysis()
        elif self.results_dir and self.results_dir.exists():
            meta_analysis_results = {}

            # Load different analysis types
            for result_file in self.results_dir.glob("*.csv"):
                analysis_name = result_file.stem
                if not analysis_types or analysis_name in analysis_types:
                    results_df = pd.read_csv(result_file)
                    meta_analysis_results[analysis_name] = self._process_meta_analysis(
                        results_df
                    )
        else:
            raise ValueError(
                "Results directory not found. Please provide a valid ENIGMA "
                "results directory or use demo_mode=True"
            )

        self.meta_analysis_results = meta_analysis_results
        logger.info(
            f"Loaded meta-analysis results for {len(meta_analysis_results)} analyses"
        )
        return meta_analysis_results

    def load_brain_measures(
        self, measure_types: list[str] | None = None, demo_mode: bool = False
    ) -> dict[str, Any]:
        """Load standardized brain measures across cohorts.

        Args:
            measure_types: Types of brain measures to load
            demo_mode: Use synthetic data for testing

        Returns:
            Dictionary with brain measure data
        """
        if demo_mode:
            brain_measures = self._generate_demo_brain_measures()
            if measure_types:
                brain_measures = {
                    key: value
                    for key, value in brain_measures.items()
                    if key in measure_types
                }
        else:
            brain_measures = {}
            measure_types = measure_types or list(self.brain_measures_config.keys())

            for measure_type in measure_types:
                if measure_type in self.brain_measures_config:
                    brain_measures[measure_type] = self._load_brain_measure_data(
                        measure_type
                    )

        self.brain_measures = brain_measures
        logger.info(f"Loaded brain measures: {list(brain_measures.keys())}")
        return brain_measures

    def calculate_quality_metrics(self) -> dict[str, Any]:
        """Calculate quality metrics for meta-analyses.

        Returns:
            Dictionary with quality assessment metrics
        """
        quality_metrics = {}

        for analysis_name, results in self.meta_analysis_results.items():
            metrics = {
                "publication_bias": self._assess_publication_bias(results),
                "heterogeneity": self._assess_heterogeneity(results),
                "statistical_power": self._calculate_statistical_power(results),
                "data_quality": self._assess_data_quality(results),
                "overall_quality": 0.0,
            }

            # Calculate overall quality score
            metrics["overall_quality"] = np.mean(
                [
                    metrics["publication_bias"],
                    metrics["heterogeneity"],
                    metrics["statistical_power"],
                    metrics["data_quality"],
                ]
            )

            quality_metrics[analysis_name] = metrics

        self.quality_metrics = quality_metrics
        logger.info(f"Calculated quality metrics for {len(quality_metrics)} analyses")
        return quality_metrics

    def harmonize_across_cohorts(
        self, cohorts: list[str] | None = None
    ) -> dict[str, Any]:
        """Harmonize data across different cohorts.

        Args:
            cohorts: Specific cohorts to harmonize

        Returns:
            Dictionary with harmonization results
        """
        harmonization_results = {
            "cohort_mappings": {},
            "harmonized_measures": {},
            "conversion_factors": {},
            "quality_scores": {},
        }

        # Perform harmonization for each working group
        for group_name, group_data in self.working_groups.items():
            if "cohorts" in group_data:
                group_cohorts = group_data["cohorts"]
                if cohorts:
                    group_cohorts = [c for c in group_cohorts if c in cohorts]

                harmonization_results["cohort_mappings"][group_name] = (
                    self._map_cohort_variables(group_cohorts)
                )
                harmonization_results["harmonized_measures"][group_name] = (
                    self._harmonize_measures(group_cohorts)
                )
                harmonization_results["conversion_factors"][group_name] = (
                    self._calculate_conversion_factors(group_cohorts)
                )
                harmonization_results["quality_scores"][group_name] = (
                    self._assess_harmonization_quality(group_cohorts)
                )

        logger.info(
            f"Harmonized data across {len(harmonization_results['cohort_mappings'])} working groups"
        )
        return harmonization_results

    def link_publications(self, pubmed_ids: list[str] | None = None) -> dict[str, Any]:
        """Link ENIGMA results to published literature.

        Args:
            pubmed_ids: Specific PubMed IDs to link

        Returns:
            Dictionary with publication linkage data
        """
        publication_links = {"papers": [], "citations": {}, "impact_metrics": {}}

        # Link each working group to its publications
        for group_name, group_data in self.working_groups.items():
            if "publications" in group_data:
                for pub in group_data["publications"]:
                    if not pubmed_ids or pub.get("pmid") in pubmed_ids:
                        publication_links["papers"].append(
                            {
                                "working_group": group_name,
                                "pmid": pub.get("pmid"),
                                "doi": pub.get("doi"),
                                "title": pub.get("title"),
                                "year": pub.get("year"),
                                "journal": pub.get("journal"),
                            }
                        )

        # Calculate impact metrics
        publication_links["impact_metrics"] = {
            "total_papers": len(publication_links["papers"]),
            "papers_per_group": (
                len(publication_links["papers"]) / len(self.working_groups)
                if self.working_groups
                else 0
            ),
            "citation_count": sum(
                pub.get("citations", 0) for pub in publication_links["papers"]
            ),
        }

        logger.info(f"Linked {len(publication_links['papers'])} publications")
        return publication_links

    def export_to_knowledge_graph(self) -> dict[str, Any]:
        """Export ENIGMA data for knowledge graph integration.

        Returns:
            Dictionary with graph-ready data
        """
        kg_data = {
            "nodes": [],
            "edges": [],
            "metadata": {
                "source": "ENIGMA_Consortium",
                "version": "2024.1",
                "n_working_groups": len(self.working_groups),
                "n_cohorts": sum(
                    len(g.get("cohorts", [])) for g in self.working_groups.values()
                ),
                "timestamp": datetime.now().isoformat(),
            },
        }

        # Create working group nodes
        for group_name, group_data in self.working_groups.items():
            node_id = f"enigma_{group_name.lower().replace('-', '_')}"
            kg_data["nodes"].append(
                {
                    "id": node_id,
                    "type": "WorkingGroup",
                    "properties": {
                        "name": group_name,
                        "disorder": group_data.get("disorder", ""),
                        "n_cohorts": len(group_data.get("cohorts", [])),
                        "n_subjects": group_data.get("total_subjects", 0),
                    },
                }
            )

            # Create cohort nodes and edges
            for cohort in group_data.get("cohorts", []):
                cohort_id = f"enigma_cohort_{cohort.lower().replace(' ', '_')}"
                kg_data["nodes"].append(
                    {
                        "id": cohort_id,
                        "type": "Cohort",
                        "properties": {"name": cohort, "working_group": group_name},
                    }
                )

                # Create edge from working group to cohort
                kg_data["edges"].append(
                    {"source": node_id, "target": cohort_id, "type": "includes_cohort"}
                )

        # Create brain measure nodes
        for measure_type, _measures in self.brain_measures.items():
            for measure_name in self.brain_measures_config.get(measure_type, []):
                measure_id = f"enigma_measure_{measure_type}_{measure_name}"
                kg_data["nodes"].append(
                    {
                        "id": measure_id,
                        "type": "BrainMeasure",
                        "properties": {
                            "category": measure_type,
                            "name": measure_name,
                            "modality": self._get_modality_for_measure(measure_type),
                        },
                    }
                )

        logger.info(
            f"Exported {len(kg_data['nodes'])} nodes and {len(kg_data['edges'])} edges to knowledge graph"
        )
        return kg_data

    def get_statistics(self) -> dict[str, Any]:
        """Get summary statistics of loaded data.

        Returns:
            Dictionary with summary statistics
        """
        stats = {
            "n_working_groups": len(self.working_groups),
            "n_cohorts": sum(
                len(g.get("cohorts", [])) for g in self.working_groups.values()
            ),
            "n_subjects": sum(
                g.get("total_subjects", 0) for g in self.working_groups.values()
            ),
            "n_brain_measures": (
                sum(
                    len(measures.get("measures", []))
                    for measures in self.brain_measures.values()
                )
                if self.brain_measures
                else 0
            ),
            "n_meta_analyses": len(self.meta_analysis_results),
            "disorders_studied": list(
                {
                    g.get("disorder", "")
                    for g in self.working_groups.values()
                    if g.get("disorder")
                }
            ),
            "quality_summary": {
                "mean_quality": (
                    np.mean(
                        [m["overall_quality"] for m in self.quality_metrics.values()]
                    )
                    if self.quality_metrics
                    else 0
                ),
                "analyses_with_high_quality": (
                    sum(
                        1
                        for m in self.quality_metrics.values()
                        if m["overall_quality"] > 0.7
                    )
                    if self.quality_metrics
                    else 0
                ),
            },
        }

        return stats

    # Private helper methods

    def _generate_demo_working_groups(
        self, groups: list[str] | None = None
    ) -> dict[str, Any]:
        """Generate demo working group data."""
        np.random.seed(42)
        working_groups = {}

        group_list = groups or self.available_working_groups[:5]

        for group_index, group_name in enumerate(group_list):
            disorder = group_name.split("-")[1]
            n_cohorts = np.random.randint(10, 30)

            working_groups[group_name] = {
                "disorder": disorder,
                "cohorts": [f"Cohort_{i}" for i in range(n_cohorts)],
                "total_subjects": np.random.randint(1000, 10000),
                "cases": np.random.randint(500, 5000),
                "controls": np.random.randint(500, 5000),
                "publications": [
                    {
                        "pmid": f"{30000000 + (group_index * 100) + i}",
                        "title": f"ENIGMA {disorder} Working Group Study {i+1}",
                        "year": 2020 + i,
                        "journal": np.random.choice(
                            [
                                "Nature",
                                "Science",
                                "JAMA Psychiatry",
                                "Molecular Psychiatry",
                            ]
                        ),
                        "citations": np.random.randint(10, 200),
                    }
                    for i in range(np.random.randint(1, 5))
                ],
                "data_freeze_date": "2024-01-01",
            }

        return working_groups

    def _generate_demo_meta_analysis(self) -> dict[str, Any]:
        """Generate demo meta-analysis results."""
        np.random.seed(42)
        meta_analysis_results = {}

        for group_name in list(self.working_groups.keys())[:3]:  # First 3 groups
            results = []

            # Generate results for each brain region
            for region in self.brain_measures_config["subcortical"][:5]:
                result = {
                    "region": region,
                    "cohens_d": np.random.normal(0.2, 0.1),
                    "standard_error": np.random.uniform(0.01, 0.05),
                    "p_value": np.random.uniform(0.0001, 0.1),
                    "n_cases": np.random.randint(500, 3000),
                    "n_controls": np.random.randint(500, 3000),
                    "q_statistic": np.random.uniform(10, 100),
                    "i2_heterogeneity": np.random.uniform(0, 80),
                    "tau_squared": np.random.uniform(0, 0.1),
                }

                # Calculate confidence intervals
                result["ci_lower"] = (
                    result["cohens_d"] - 1.96 * result["standard_error"]
                )
                result["ci_upper"] = (
                    result["cohens_d"] + 1.96 * result["standard_error"]
                )

                results.append(result)

            meta_analysis_results[f"{group_name}_subcortical"] = pd.DataFrame(results)

        return meta_analysis_results

    def _generate_demo_brain_measures(self) -> dict[str, Any]:
        """Generate demo brain measure data."""
        np.random.seed(42)
        brain_measures = {}

        # Subcortical volumes
        brain_measures["subcortical"] = {
            "measures": self.brain_measures_config["subcortical"],
            "units": "mm³",
            "normative_values": {
                measure: {
                    "mean": np.random.uniform(1000, 10000),
                    "std": np.random.uniform(100, 1000),
                }
                for measure in self.brain_measures_config["subcortical"]
            },
        }

        # Cortical measures
        brain_measures["cortical"] = {
            "measures": self.brain_measures_config["cortical"],
            "units": {"thickness": "mm", "surface_area": "mm²", "volume": "mm³"},
            "parcellation": "Desikan-Killiany",
        }

        # White matter measures
        brain_measures["white_matter"] = {
            "measures": self.brain_measures_config["white_matter"],
            "tracts": ["corpus_callosum", "cingulum", "uncinate", "arcuate"],
            "units": "dimensionless",
            "dti_parameters": {"b_value": 1000, "directions": 64},
        }

        return brain_measures

    def _load_working_group_data(self, group_dir: Path) -> dict[str, Any]:
        """Load data for a specific working group."""
        group_data = {}

        # Load metadata
        metadata_file = group_dir / "metadata.json"
        if metadata_file.exists():
            with open(metadata_file) as f:
                group_data = json.load(f)

        # Load cohort data
        cohort_file = group_dir / "cohorts.csv"
        if cohort_file.exists():
            cohort_df = pd.read_csv(cohort_file)
            group_data["cohorts"] = cohort_df["cohort_name"].tolist()
            group_data["cohort_details"] = cohort_df.to_dict("records")

        # Load results
        results_file = group_dir / "results.csv"
        if results_file.exists():
            results_df = pd.read_csv(results_file)
            group_data["results"] = results_df.to_dict("records")

        return group_data

    def _load_brain_measure_data(self, measure_type: str) -> dict[str, Any]:
        """Load brain measure data for a specific type."""
        measure_data = {
            "type": measure_type,
            "measures": self.brain_measures_config.get(measure_type, []),
            "data": {},
        }

        if self.data_dir:
            measure_file = self.data_dir / f"{measure_type}_measures.csv"
            if measure_file.exists():
                measure_df = pd.read_csv(measure_file)
                measure_data["data"] = measure_df.to_dict("records")

        return measure_data

    def _process_meta_analysis(self, results_df: pd.DataFrame) -> pd.DataFrame:
        """Process and validate meta-analysis results."""
        # Ensure required columns exist
        required_cols = ["cohens_d", "standard_error", "p_value"]
        for col in required_cols:
            if col not in results_df.columns:
                logger.warning(f"Missing required column: {col}")
                results_df[col] = np.nan

        # Calculate additional metrics if not present
        if "ci_lower" not in results_df.columns:
            results_df["ci_lower"] = (
                results_df["cohens_d"] - 1.96 * results_df["standard_error"]
            )
        if "ci_upper" not in results_df.columns:
            results_df["ci_upper"] = (
                results_df["cohens_d"] + 1.96 * results_df["standard_error"]
            )

        # Add significance flag
        results_df["significant"] = results_df["p_value"] < 0.05

        return results_df

    def _assess_publication_bias(self, results: Any) -> float:
        """Assess publication bias using funnel plot asymmetry."""
        if isinstance(results, pd.DataFrame) and len(results) > 0:
            if "cohens_d" in results.columns and "standard_error" in results.columns:
                # Simple assessment based on correlation between effect size and SE
                correlation = results["cohens_d"].corr(results["standard_error"])
                if pd.isna(correlation):
                    return 0.5
                # Treat positive correlation as bias indicator
                bias_score = 1 - max(0.0, correlation)
                return max(0, min(1, float(bias_score)))
        return 0.5  # Neutral score if cannot assess

    def _assess_heterogeneity(self, results: Any) -> float:
        """Assess heterogeneity of results."""
        if isinstance(results, pd.DataFrame) and "i2_heterogeneity" in results.columns:
            # I² statistic: 0-25% low, 25-75% moderate, >75% high
            mean_i2 = results["i2_heterogeneity"].mean()
            if mean_i2 < 25:
                return 1.0  # Low heterogeneity is good
            elif mean_i2 < 75:
                return 0.5  # Moderate
            else:
                return 0.2  # High heterogeneity is problematic
        return 0.5  # Neutral score if cannot assess

    def _calculate_statistical_power(self, results: Any) -> float:
        """Calculate statistical power of the meta-analysis."""
        if isinstance(results, pd.DataFrame):
            if "n_cases" in results.columns and "n_controls" in results.columns:
                total_n = results["n_cases"].sum() + results["n_controls"].sum()
                # Simple power calculation based on sample size
                # Assuming medium effect size (d=0.5), alpha=0.05
                if total_n > 10000:
                    return 0.95
                elif total_n > 5000:
                    return 0.85
                elif total_n > 1000:
                    return 0.70
                else:
                    return 0.50
        return 0.5  # Neutral score if cannot assess

    def _assess_data_quality(self, results: Any) -> float:
        """Assess overall data quality."""
        quality_score = 0.5

        if isinstance(results, pd.DataFrame):
            # Check for missing data
            missing_proportion = results.isnull().sum().sum() / results.size
            completeness_score = 1 - missing_proportion

            # Check for outliers
            if "cohens_d" in results.columns:
                z_scores = np.abs(stats.zscore(results["cohens_d"].dropna()))
                outlier_proportion = (
                    (z_scores > 3).sum() / len(z_scores) if len(z_scores) > 0 else 0
                )
                outlier_score = 1 - outlier_proportion
            else:
                outlier_score = 0.5

            quality_score = (completeness_score + outlier_score) / 2

        return quality_score

    def _map_cohort_variables(self, cohorts: list[str]) -> dict[str, Any]:
        """Map variables across different cohorts."""
        variable_mappings = {
            "age": ["age", "age_at_scan", "age_years"],
            "sex": ["sex", "gender", "biological_sex"],
            "diagnosis": ["diagnosis", "dx", "clinical_diagnosis"],
            "medication": ["medication", "meds", "current_medication"],
        }
        return variable_mappings.copy()

    def _harmonize_measures(self, cohorts: list[str]) -> dict[str, Any]:
        """Harmonize brain measures across cohorts."""
        harmonized_measures = {}

        for cohort in cohorts:
            harmonized_measures[cohort] = {
                "scaling_factor": np.random.uniform(0.95, 1.05),  # Demo scaling
                "offset": np.random.uniform(-0.1, 0.1),  # Demo offset
                "harmonization_method": "ComBat",
                "reference_cohort": cohorts[0] if cohorts else None,
            }

        return harmonized_measures

    def _calculate_conversion_factors(self, cohorts: list[str]) -> dict[str, float]:
        """Calculate conversion factors between cohorts."""
        conversion_factors = {}

        for cohort in cohorts:
            # Demo conversion factors (in reality, these would be calculated from data)
            conversion_factors[cohort] = np.random.uniform(0.95, 1.05)

        return conversion_factors

    def _assess_harmonization_quality(self, cohorts: list[str]) -> float:
        """Assess quality of harmonization across cohorts."""
        # In reality, this would check actual harmonization metrics
        # For demo, return a reasonable quality score
        if len(cohorts) > 10:
            return 0.85  # Good quality with many cohorts
        elif len(cohorts) > 5:
            return 0.75
        else:
            return 0.65

    def _get_modality_for_measure(self, measure_type: str) -> str:
        """Get imaging modality for a measure type."""
        modality_map = {
            "subcortical": "T1-weighted MRI",
            "cortical": "T1-weighted MRI",
            "white_matter": "Diffusion MRI",
        }
        return modality_map.get(measure_type, "Unknown")
