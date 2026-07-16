"""Neurosynth integration tools for the agent system."""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path

# Set matplotlib backend before importing plotting
import matplotlib
import nibabel as nib
from pydantic import BaseModel, Field

from brain_researcher.core.datasets.neurosynth_source import (
    DEFAULT_DATASET_PICKLE,
    DEFAULT_SOURCE_DIR,
    NeurosynthSourceError,
    verify_converted_dataset,
)

matplotlib.use("Agg")  # Use non-interactive backend for headless environments

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class NeuroSynthMetaAnalysisArgs(BaseModel):
    """Arguments for the legacy-named descriptive Neurosynth mapping tool."""

    keyword: str = Field(
        description="Term to query in the Neurosynth dataset (e.g., 'fear', 'memory', 'reward')"
    )


class NeuroSynthVisualizationArgs(BaseModel):
    """Arguments for descriptive Neurosynth map visualization."""

    activation_map_paths: list[str] = Field(
        description=(
            "List of NIfTI map paths. This legacy field name does not assign "
            "inferential or activation semantics to the inputs."
        )
    )
    threshold: float = Field(
        default=3.0,
        description=(
            "Absolute display threshold in the input map's native value units; "
            "this does not imply statistical significance"
        ),
    )
    output_dir: str | None = Field(
        default=None, description="Directory to save visualization outputs"
    )


class NeuroSynthTermSearchArgs(BaseModel):
    """Arguments for searching available Neurosynth terms."""

    search_query: str = Field(description="Term to search for in the dataset")
    fuzzy_match: bool = Field(
        default=True, description="Use fuzzy matching with similarity scores"
    )
    limit: int = Field(default=10, description="Maximum number of matches to return")
    score_cutoff: float = Field(
        default=60.0, description="Minimum similarity score (0-100) for fuzzy matches"
    )


def _get_dataset_path() -> str:
    """Get the explicit override or canonical Neurosynth dataset pickle path."""
    env_path = os.getenv("NEUROSYNTH_DATASET_PATH")
    if env_path:
        return str(Path(env_path).expanduser().resolve())
    return str(DEFAULT_DATASET_PICKLE)


def _source_dir_for_dataset() -> str:
    source_override = os.getenv("NEUROSYNTH_SOURCE_DIR")
    if os.getenv("NEUROSYNTH_DATASET_PATH") and not source_override:
        raise NeurosynthSourceError(
            "NEUROSYNTH_DATASET_PATH requires NEUROSYNTH_SOURCE_DIR so the "
            "dataset can be associated with a verified source manifest"
        )
    source_dir = source_override or str(DEFAULT_SOURCE_DIR)
    return source_dir


def _load_dataset():
    """Load the Neurosynth NiMARE dataset if present."""
    dataset_path = _get_dataset_path()
    verify_converted_dataset(dataset_path, _source_dir_for_dataset())

    if not os.path.exists(dataset_path):
        error_msg = (
            f"Neurosynth dataset not found at {dataset_path}\n"
            "Please run the canonical source step from the repository root: "
            "python scripts/data/download_neurosynth_data.py\n"
            "Then follow reproducibility/auditable_claim_record/README.md "
            "to build the NiMARE dataset pickle.\n"
            "An explicit NEUROSYNTH_DATASET_PATH must be paired with "
            "NEUROSYNTH_SOURCE_DIR."
        )
        raise FileNotFoundError(error_msg)

    try:
        from nimare import dataset as nimare_dataset

        logger.info(f"Loading Neurosynth dataset from {dataset_path}")
        return nimare_dataset.Dataset.load(dataset_path)
    except ImportError as exc:
        raise ImportError(
            "nimare is not installed. Please run: pip install nimare"
        ) from exc
    except Exception as e:
        logger.error(f"Failed to load dataset: {e}")
        raise


class BaseNeuroSynthTool(NeuroToolWrapper):
    """Base class for Neurosynth tools with common functionality."""

    def __init__(self):
        super().__init__()
        preferred_dir = os.getenv("BR_KG_OUTPUT_DIR") or os.path.join(
            tempfile.gettempdir(), "br_kg"
        )
        try:
            os.makedirs(preferred_dir, exist_ok=True)
            self.output_dir = preferred_dir
        except Exception as exc:  # pragma: no cover - fallback path for locked tmp
            fallback_dir = tempfile.mkdtemp(prefix="br_kg_", dir=os.getcwd())
            logger.warning(
                "NeuroSynth output dir %s not writable (%s); falling back to %s",
                preferred_dir,
                exc,
                fallback_dir,
            )
            self.output_dir = fallback_dir

    def _get_timestamp(self) -> str:
        """Get timestamp string for file naming."""
        return datetime.now().strftime("%Y%m%d_%H%M%S")


class NeuroSynthMetaAnalysisTool(BaseNeuroSynthTool):
    """Compatibility-named tool for descriptive Neurosynth density maps."""

    def get_tool_name(self) -> str:
        return "neurosynth_meta_analysis"

    def get_tool_description(self) -> str:
        return (
            "Build a descriptive Neurosynth coordinate-density map for a term. "
            "The compatibility tool id contains 'meta_analysis', but this operation "
            "selects high positive TF-IDF study weights and counts overlapping "
            "coordinate spheres. It returns no z-scores, significance test, effect "
            "estimate, or cognitive interpretation."
        )

    def get_args_schema(self):
        return NeuroSynthMetaAnalysisArgs

    def _run(self, keyword: str) -> ToolResult:
        try:
            from brain_researcher.core.analysis.neurosynth_integration import (
                get_neurosynth_mapping,
            )

            logger.info("Building descriptive coordinate-density map for %s", keyword)
            result = get_neurosynth_mapping(keyword)

            if "error" in result:
                return ToolResult(status="error", error=result["error"])

            # Save descriptive coordinate-density maps and return paths.
            density_maps = result.get("coordinate_density_maps") or result.get(
                "activation_maps"
            )
            if density_maps:
                map_paths = []
                timestamp = self._get_timestamp()

                for i, density_map in enumerate(density_maps):
                    try:
                        filename = (
                            f"neurosynth_{keyword}_{timestamp}_coordinate_density{i}.nii.gz"
                        )
                        filepath = os.path.join(self.output_dir, filename)
                        nib.save(density_map, filepath)
                        map_paths.append(filepath)
                        logger.info("Saved coordinate-density map to %s", filepath)
                    except Exception as e:
                        logger.error("Failed to save density map %s: %s", i, e)

                result["coordinate_density_map_paths"] = map_paths
                # Compatibility alias; metadata states the authoritative semantics.
                result["activation_map_paths"] = map_paths
                result.pop("coordinate_density_maps", None)
                result.pop("activation_maps", None)

            return ToolResult(
                status="success",
                data=result,
                metadata={
                    "n_studies": len(result.get("studies", [])),
                    "n_coordinates": len(result.get("coordinates", [])),
                    "keyword_used": result.get("keyword", keyword),
                    "analysis_semantics": result.get(
                        "analysis_semantics", "descriptive_coordinate_density"
                    ),
                    "map_value_semantics": result.get(
                        "map_value_semantics",
                        "overlapping_coordinate_sphere_hit_count",
                    ),
                    "inferential_statistics": False,
                    "multiple_comparisons_correction": None,
                },
            )

        except Exception as e:
            logger.error("Descriptive Neurosynth mapping failed: %s", e)
            return ToolResult(status="error", error=str(e))


class NeuroSynthVisualizationTool(BaseNeuroSynthTool):
    """Tool for rendering supplied NIfTI maps without statistical inference."""

    def get_tool_name(self) -> str:
        return "neurosynth_visualize"

    def get_tool_description(self) -> str:
        return (
            "Render descriptive axial-slice PNGs from supplied Neurosynth NIfTI maps. "
            "The display threshold uses the map's native units and does not establish "
            "statistical significance or functional interpretation."
        )

    def get_args_schema(self):
        return NeuroSynthVisualizationArgs

    def _run(
        self,
        activation_map_paths: list[str],
        threshold: float = 3.0,
        output_dir: str | None = None,
    ) -> ToolResult:
        try:
            # Load supplied map values without inferring their statistic.
            activation_maps = []
            for path in activation_map_paths:
                if not os.path.exists(path):
                    return ToolResult(
                        status="error", error=f"NIfTI map not found: {path}"
                    )
                activation_maps.append(nib.load(path))

            from brain_researcher.core.analysis.neurosynth_integration import (
                visualize_activation_maps,
            )

            # Use provided output_dir or default
            viz_output_dir = output_dir or self.output_dir
            os.makedirs(viz_output_dir, exist_ok=True)

            # Generate visualizations
            vis_results = visualize_activation_maps(
                activation_maps,
                threshold=threshold,
                output_dir=viz_output_dir,
            )

            saved_files = {
                f"map_{index}": path
                for index, path in enumerate(vis_results.get("plots", []), start=1)
            }

            return ToolResult(
                status="success",
                data={
                    "visualizations": vis_results,
                    "saved_files": saved_files,
                    "threshold": threshold,
                    "threshold_semantics": (
                        "absolute_display_threshold_in_map_native_units"
                    ),
                    "inferential_statistics": False,
                },
                metadata={
                    "n_maps": len(activation_maps),
                    "n_visualizations": len(saved_files),
                },
            )

        except Exception as e:
            logger.error(f"Visualization failed: {e}")
            return ToolResult(status="error", error=str(e))


class NeuroSynthTermSearchTool(BaseNeuroSynthTool):
    """Tool for searching available terms in the Neurosynth dataset."""

    def get_tool_name(self) -> str:
        return "neurosynth_search_terms"

    def get_tool_description(self) -> str:
        return (
            "Search for available cognitive/behavioral terms in the Neurosynth dataset. "
            "Supports fuzzy matching to find similar terms (e.g., 'mem' finds 'memory', "
            "'working memory', 'episodic memory'). Returns ranked matches with similarity scores."
        )

    def get_args_schema(self):
        return NeuroSynthTermSearchArgs

    def _run(
        self,
        search_query: str,
        fuzzy_match: bool = True,
        limit: int = 10,
        score_cutoff: float = 60.0,
    ) -> ToolResult:
        try:
            dataset = _load_dataset()
            all_labels = dataset.get_labels()

            # Clean labels for better matching (remove prefixes like "terms_abstract__")
            clean_labels = []
            label_map = {}
            for label in all_labels:
                if "__" in label:
                    clean = label.split("__")[-1]
                    clean_labels.append(clean)
                    label_map[clean] = label
                else:
                    clean_labels.append(label)
                    label_map[label] = label

            if fuzzy_match:
                try:
                    from rapidfuzz import process

                    # Find fuzzy matches
                    matches = process.extract(
                        search_query,
                        clean_labels,
                        limit=limit,
                        score_cutoff=score_cutoff,
                    )

                    # Format results with original labels
                    results = []
                    for match, score, _ in matches:
                        original_label = label_map.get(match, match)
                        results.append(
                            {
                                "term": match,
                                "full_label": original_label,
                                "score": round(score, 2),
                            }
                        )

                except ImportError:
                    logger.warning(
                        "rapidfuzz not available, falling back to substring matching"
                    )
                    # Fallback to substring matching
                    matches = []
                    query_lower = search_query.lower()
                    for clean, original in label_map.items():
                        if query_lower in clean.lower():
                            matches.append(
                                {
                                    "term": clean,
                                    "full_label": original,
                                    "score": (
                                        100.0 if clean.lower() == query_lower else 80.0
                                    ),
                                }
                            )
                    results = sorted(matches, key=lambda x: x["score"], reverse=True)[
                        :limit
                    ]

            else:
                # Exact matching
                results = []
                query_lower = search_query.lower()
                for clean, original in label_map.items():
                    if clean.lower() == query_lower:
                        results.append(
                            {"term": clean, "full_label": original, "score": 100.0}
                        )

            return ToolResult(
                status="success",
                data={
                    "query": search_query,
                    "matches": results,
                    "n_matches": len(results),
                    "total_terms": len(all_labels),
                },
                metadata={"fuzzy_match": fuzzy_match, "score_cutoff": score_cutoff},
            )

        except Exception as e:
            logger.error(f"Term search failed: {e}")
            return ToolResult(status="error", error=str(e))


class NeuroSynthTools:
    """Collection of Neurosynth-related tools."""

    def __init__(self):
        self.meta_analysis = NeuroSynthMetaAnalysisTool()
        self.visualize = NeuroSynthVisualizationTool()
        self.term_search = NeuroSynthTermSearchTool()

    def get_all_tools(self) -> list[NeuroToolWrapper]:
        return [self.meta_analysis, self.visualize, self.term_search]

    def get_tool_by_name(self, name: str) -> NeuroToolWrapper | None:
        tool_map = {
            "neurosynth_meta_analysis": self.meta_analysis,
            "neurosynth_visualize": self.visualize,
            "neurosynth_search_terms": self.term_search,
        }
        return tool_map.get(name)
