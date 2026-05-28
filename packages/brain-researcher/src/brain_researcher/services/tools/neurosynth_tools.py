"""Neurosynth integration tools for the agent system."""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime

# Set matplotlib backend before importing plotting
import matplotlib
import nibabel as nib
from pydantic import BaseModel, Field

matplotlib.use("Agg")  # Use non-interactive backend for headless environments

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class NeuroSynthMetaAnalysisArgs(BaseModel):
    """Arguments for Neurosynth meta-analysis."""

    keyword: str = Field(
        description="Term to query in the Neurosynth dataset (e.g., 'fear', 'memory', 'reward')"
    )


class NeuroSynthVisualizationArgs(BaseModel):
    """Arguments for Neurosynth activation map visualization."""

    activation_map_paths: list[str] = Field(
        description="List of paths to NiFTI activation map files"
    )
    threshold: float = Field(
        default=3.0, description="Statistical threshold for visualization (Z-score)"
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
    """Get the Neurosynth dataset path from environment or default location."""
    env_path = os.getenv("NEUROSYNTH_DATASET_PATH")
    if env_path and os.path.exists(env_path):
        return env_path

    # Use the actual dataset location
    # Try both .pkl and .pkl.gz formats
    base_dir = os.path.abspath(os.path.join(
        os.path.dirname(__file__),  # services/tools/
        "..",
        "..",
        "..",  # up to brain_researcher/
        "data",
        "neurosynth_nimare",
    ))

    # Check for .pkl.gz first (compressed), then .pkl
    pkl_gz_path = os.path.join(base_dir, "neurosynth_dataset_v7.pkl.gz")
    pkl_path = os.path.join(base_dir, "neurosynth_dataset_v7.pkl")

    if os.path.exists(pkl_gz_path):
        return pkl_gz_path
    elif os.path.exists(pkl_path):
        return pkl_path
    else:
        # Return default for error message
        return pkl_gz_path


def _load_dataset():
    """Load the Neurosynth NiMARE dataset if present."""
    dataset_path = _get_dataset_path()

    if not os.path.exists(dataset_path):
        error_msg = (
            f"Neurosynth dataset not found at {dataset_path}\n"
            "Please run: python cli/neurosynth_fetch.py\n"
            "Or set NEUROSYNTH_DATASET_PATH environment variable"
        )
        raise FileNotFoundError(error_msg)

    try:
        from nimare import dataset as nimare_dataset

        logger.info(f"Loading Neurosynth dataset from {dataset_path}")
        return nimare_dataset.Dataset.load(dataset_path)
    except ImportError:
        raise ImportError("nimare is not installed. Please run: pip install nimare")
    except Exception as e:
        logger.error(f"Failed to load dataset: {e}")
        raise


class BaseNeuroSynthTool(NeuroToolWrapper):
    """Base class for Neurosynth tools with common functionality."""

    def __init__(self):
        super().__init__()
        preferred_dir = os.getenv("NEUROKG_OUTPUT_DIR") or os.path.join(
            tempfile.gettempdir(), "neurokg"
        )
        try:
            os.makedirs(preferred_dir, exist_ok=True)
            self.output_dir = preferred_dir
        except Exception as exc:  # pragma: no cover - fallback path for locked tmp
            fallback_dir = tempfile.mkdtemp(prefix="neurokg_", dir=os.getcwd())
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
    """Tool performing meta-analysis queries using Neurosynth."""

    def get_tool_name(self) -> str:
        return "neurosynth_meta_analysis"

    def get_tool_description(self) -> str:
        return (
            "Perform a Neurosynth meta-analysis for cognitive/behavioral terms. "
            "Searches ~14,000 neuroimaging studies to find brain activation patterns "
            "associated with terms like 'fear', 'memory', 'attention', 'reward', etc. "
            "Returns activation maps, peak coordinates, and relevant studies."
        )

    def get_args_schema(self):
        return NeuroSynthMetaAnalysisArgs

    def _run(self, keyword: str) -> ToolResult:
        try:
            from brain_researcher.core.analysis.neurosynth_integration import (
                get_neurosynth_mapping,
            )

            logger.info(f"Running meta-analysis for keyword: {keyword}")
            result = get_neurosynth_mapping(keyword)

            if "error" in result:
                return ToolResult(status="error", error=result["error"])

            # Save activation maps to files and return paths
            if result.get("activation_maps"):
                map_paths = []
                timestamp = self._get_timestamp()

                for i, activation_map in enumerate(result["activation_maps"]):
                    try:
                        filename = f"neurosynth_{keyword}_{timestamp}_map{i}.nii.gz"
                        filepath = os.path.join(self.output_dir, filename)
                        nib.save(activation_map, filepath)
                        map_paths.append(filepath)
                        logger.info(f"Saved activation map to {filepath}")
                    except Exception as e:
                        logger.error(f"Failed to save activation map {i}: {e}")

                result["activation_map_paths"] = map_paths
                # Remove the non-serializable objects
                del result["activation_maps"]

            return ToolResult(
                status="success",
                data=result,
                metadata={
                    "n_studies": len(result.get("studies", [])),
                    "n_coordinates": len(result.get("coordinates", [])),
                    "keyword_used": result.get("keyword", keyword),
                },
            )

        except Exception as e:
            logger.error(f"Meta-analysis failed: {e}")
            return ToolResult(status="error", error=str(e))


class NeuroSynthVisualizationTool(BaseNeuroSynthTool):
    """Tool for creating visualizations from activation maps."""

    def get_tool_name(self) -> str:
        return "neurosynth_visualize"

    def get_tool_description(self) -> str:
        return (
            "Create publication-ready brain visualizations from Neurosynth activation maps. "
            "Generates multiple views including axial slices, glass brain, and 3D mosaic. "
            "Returns base64-encoded images and saves PNG files for different brain views."
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
            # Load activation maps from paths
            activation_maps = []
            for path in activation_map_paths:
                if not os.path.exists(path):
                    return ToolResult(
                        status="error", error=f"Activation map not found: {path}"
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
                activation_maps, threshold=threshold
            )

            # Save visualization files
            timestamp = self._get_timestamp()
            saved_files = {}

            for key, base64_data in vis_results.items():
                if not key.startswith("error"):
                    try:
                        # Decode base64 and save as PNG
                        import base64

                        img_data = base64.b64decode(base64_data)

                        filename = f"neurosynth_viz_{timestamp}_{key}.png"
                        filepath = os.path.join(viz_output_dir, filename)

                        with open(filepath, "wb") as f:
                            f.write(img_data)

                        saved_files[key] = filepath
                        logger.info(f"Saved visualization to {filepath}")
                    except Exception as e:
                        logger.error(f"Failed to save {key}: {e}")

            return ToolResult(
                status="success",
                data={
                    "visualizations": vis_results,
                    "saved_files": saved_files,
                    "threshold": threshold,
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
                                    "score": 100.0
                                    if clean.lower() == query_lower
                                    else 80.0,
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
