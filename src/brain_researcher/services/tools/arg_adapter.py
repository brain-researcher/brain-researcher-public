"""
Tool argument adapter for converting generic LLM arguments to tool-specific formats.

Handles the conversion between what the LLM provides and what tools expect.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ToolArgumentAdapter:
    """
    Adapts generic LLM arguments to tool-specific requirements.

    Provides:
    - Argument name remapping
    - Default value injection for demo mode
    - Validation of required arguments
    - Type conversion where needed
    """

    @staticmethod
    def adapt(
        tool_name: str,
        llm_args: Dict[str, Any],
        demo: bool = False,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Adapt LLM arguments for specific tool.

        Args:
            tool_name: Name of the tool
            llm_args: Arguments provided by LLM
            demo: Whether in demo mode (adds defaults)
            trace_id: Trace ID for logging

        Returns:
            Adapted arguments ready for tool execution

        Raises:
            ValueError: If required arguments are missing in non-demo mode
        """
        logger.info(f"[{trace_id}] Adapting args for {tool_name}: {llm_args}")

        # Tool-specific adapters
        if tool_name == "glm_analysis":
            return ToolArgumentAdapter._adapt_glm_analysis(llm_args, demo, trace_id)
        elif tool_name == "find_related_concepts":
            return ToolArgumentAdapter._adapt_find_related_concepts(llm_args, trace_id)
        elif tool_name == "coordinate_to_concept":
            return ToolArgumentAdapter._adapt_coordinate_to_concept(llm_args, trace_id)
        elif tool_name == "pubmed_search" or tool_name == "concept_literature_search":
            return ToolArgumentAdapter._adapt_pubmed_search(llm_args, trace_id)
        elif tool_name == "task_to_concept_mapping":
            return ToolArgumentAdapter._adapt_task_mapping(llm_args, trace_id)
        elif tool_name == "contrast_to_activation_map":
            return ToolArgumentAdapter._adapt_contrast_to_activation_map(
                llm_args, trace_id
            )
        elif tool_name == "contrast_analysis":
            return ToolArgumentAdapter._adapt_contrast_analysis(
                llm_args, demo, trace_id
            )
        elif tool_name == "encoding_model":
            return ToolArgumentAdapter._adapt_encoding_model(llm_args, demo, trace_id)
        elif tool_name == "brain_similarity":
            return ToolArgumentAdapter._adapt_brain_similarity(llm_args, trace_id)
        else:
            # Default: pass through unchanged
            logger.info(f"[{trace_id}] No adapter for {tool_name}, passing through")
            return llm_args

    @staticmethod
    def _adapt_glm_analysis(
        llm_args: Dict[str, Any], demo: bool, trace_id: str
    ) -> Dict[str, Any]:
        """Adapt GLM analysis arguments."""
        adapted: Dict[str, Any] = {}

        dataset_id = llm_args.get("dataset_id") or llm_args.get("study_id")
        task = llm_args.get("task")
        contrasts = llm_args.get("contrasts")

        # If new-style args are present, prefer them
        if dataset_id or task or contrasts:
            if not dataset_id and demo:
                dataset_id = "ds000001"
            if contrasts is None:
                contrasts = {"task_vs_baseline": [1, -1]}
            if not dataset_id:
                raise ValueError("GLM analysis requires 'dataset_id' argument")
            adapted["dataset_id"] = dataset_id
            adapted["contrasts"] = contrasts
            if task:
                adapted["task"] = task
            elif demo:
                adapted["allow_mock"] = True
        else:
            # Legacy args path: opt into mock outputs in demo mode
            if demo:
                adapted["dataset_id"] = "ds000001"
                adapted["contrasts"] = {"task_vs_baseline": [1, -1]}
                adapted["allow_mock"] = True
                logger.info(f"[{trace_id}] Demo mode: using mock GLM outputs")
            else:
                raise ValueError(
                    "GLM analysis requires 'dataset_id' and 'task' (or allow_mock)"
                )

        if "threshold" in llm_args:
            adapted["threshold"] = llm_args["threshold"]

        return adapted

    @staticmethod
    def _adapt_find_related_concepts(
        llm_args: Dict[str, Any], trace_id: str
    ) -> Dict[str, Any]:
        """Adapt find_related_concepts arguments."""
        # Map various possible argument names to 'concept'
        concept = (
            llm_args.get("concept")
            or llm_args.get("target_concept")  # Added this
            or llm_args.get("query")
            or llm_args.get("search_query")
            or llm_args.get("search_term")
            or llm_args.get("term")
            or llm_args.get("keyword")
            or llm_args.get("input")
        )

        if not concept:
            raise ValueError("find_related_concepts requires a 'concept' argument")

        return {"concept": concept}

    @staticmethod
    def _adapt_coordinate_to_concept(
        llm_args: Dict[str, Any], trace_id: str
    ) -> Dict[str, Any]:
        """Adapt coordinate_to_concept arguments."""
        # Handle various input formats
        if "x" in llm_args and "y" in llm_args and "z" in llm_args:
            adapted = {"coordinates": [[llm_args["x"], llm_args["y"], llm_args["z"]]]}
            if "radius" in llm_args:
                adapted["radius"] = llm_args["radius"]
            if "top_k" in llm_args:
                adapted["top_k"] = llm_args["top_k"]
            return adapted

        # Try to parse from various formats
        coords = (
            llm_args.get("coordinates")
            or llm_args.get("coords")
            or llm_args.get("coordinate")
            or llm_args.get("mni")
            or llm_args.get("position")
        )

        if coords:
            # Parse from list of coordinates [[x, y, z], ...]
            if (
                isinstance(coords, list)
                and coords
                and all(
                    isinstance(item, (list, tuple)) and len(item) == 3
                    for item in coords
                )
            ):
                adapted = {"coordinates": [list(item) for item in coords]}
                if "radius" in llm_args:
                    adapted["radius"] = llm_args["radius"]
                if "top_k" in llm_args:
                    adapted["top_k"] = llm_args["top_k"]
                return adapted

            # Parse from list [x, y, z]
            if isinstance(coords, list) and len(coords) == 3:
                adapted = {"coordinates": [[coords[0], coords[1], coords[2]]]}
                if "radius" in llm_args:
                    adapted["radius"] = llm_args["radius"]
                if "top_k" in llm_args:
                    adapted["top_k"] = llm_args["top_k"]
                return adapted

            # Parse from string "x, y, z" or "x y z"
            if isinstance(coords, str):
                parts = coords.replace(",", " ").split()
                if len(parts) == 3:
                    try:
                        adapted = {
                            "coordinates": [
                                [float(parts[0]), float(parts[1]), float(parts[2])]
                            ]
                        }
                        if "radius" in llm_args:
                            adapted["radius"] = llm_args["radius"]
                        if "top_k" in llm_args:
                            adapted["top_k"] = llm_args["top_k"]
                        return adapted
                    except ValueError:
                        pass

        raise ValueError("coordinate_to_concept requires x, y, z coordinates")

    @staticmethod
    def _adapt_pubmed_search(llm_args: Dict[str, Any], trace_id: str) -> Dict[str, Any]:
        """Adapt PubMed/literature search arguments."""
        query = (
            llm_args.get("query")
            or llm_args.get("search_query")
            or llm_args.get("keywords")
            or llm_args.get("terms")
            or llm_args.get("search")
        )

        if not query:
            raise ValueError("Literature search requires a 'query' argument")

        adapted = {"query": query}

        # Add optional parameters
        if "max_results" in llm_args:
            adapted["max_results"] = llm_args["max_results"]
        elif "limit" in llm_args:
            adapted["max_results"] = llm_args["limit"]
        else:
            adapted["max_results"] = 10  # Default

        return adapted

    @staticmethod
    def _adapt_task_mapping(llm_args: Dict[str, Any], trace_id: str) -> Dict[str, Any]:
        """Adapt task_to_concept_mapping arguments."""
        task_name = (
            llm_args.get("task_name")
            or llm_args.get("task")
            or llm_args.get("paradigm")
            or llm_args.get("cognitive_task")
            or llm_args.get("experiment")
        )

        if not task_name:
            raise ValueError("task_to_concept_mapping requires a 'task_name' argument")

        return {"task_name": task_name}

    @staticmethod
    def _adapt_contrast_to_activation_map(
        llm_args: Dict[str, Any], trace_id: str
    ) -> Dict[str, Any]:
        """Adapt contrast_to_activation_map arguments."""
        contrast_text = (
            llm_args.get("contrast_text")
            or llm_args.get("contrast")
            or llm_args.get("contrast_description")
            or llm_args.get("description")
            or llm_args.get("query")
            or llm_args.get("input")
        )
        if not contrast_text:
            raise ValueError(
                "contrast_to_activation_map requires a 'contrast_text' argument"
            )

        adapted: Dict[str, Any] = {"contrast_text": contrast_text}

        task_name = (
            llm_args.get("task_name")
            or llm_args.get("task")
            or llm_args.get("paradigm")
        )
        if task_name:
            adapted["task_name"] = task_name

        optional_keys = [
            "top_k_tasks",
            "top_k_constructs",
            "top_k_map_terms",
            "map_threshold",
            "save_dir",
            "coord_top_n",
            "coord_radius_mm",
            "coord_top_k",
        ]
        for key in optional_keys:
            if key in llm_args:
                adapted[key] = llm_args[key]

        return adapted

    @staticmethod
    def _adapt_contrast_analysis(
        llm_args: Dict[str, Any], demo: bool, trace_id: str
    ) -> Dict[str, Any]:
        """Adapt contrast analysis arguments."""
        contrast_map = (
            llm_args.get("contrast_map")
            or llm_args.get("map")
            or llm_args.get("stat_map")
            or llm_args.get("input")
        )

        threshold = (
            llm_args.get("threshold")
            or llm_args.get("p_value")
            or llm_args.get("significance")
        )

        if demo:
            return {
                "contrast_map": contrast_map or "/demo/contrast.nii.gz",
                "threshold": threshold or 0.001,
            }
        else:
            if not contrast_map:
                raise ValueError("contrast_analysis requires a 'contrast_map' argument")
            return {"contrast_map": contrast_map, "threshold": threshold or 0.001}

    @staticmethod
    def _adapt_encoding_model(
        llm_args: Dict[str, Any], demo: bool, trace_id: str
    ) -> Dict[str, Any]:
        """Adapt encoding model arguments."""
        brain_data = (
            llm_args.get("brain_data")
            or llm_args.get("fmri")
            or llm_args.get("neural_data")
            or llm_args.get("data")
        )

        features = (
            llm_args.get("features")
            or llm_args.get("predictors")
            or llm_args.get("stimuli")
            or llm_args.get("regressors")
        )

        if demo:
            return {
                "brain_data": brain_data or "/demo/brain_data.nii.gz",
                "features": features or "/demo/features.csv",
            }
        else:
            if not brain_data:
                raise ValueError("encoding_model requires 'brain_data' argument")
            if not features:
                raise ValueError("encoding_model requires 'features' argument")
            return {"brain_data": brain_data, "features": features}

    @staticmethod
    def _adapt_brain_similarity(
        llm_args: Dict[str, Any], trace_id: str
    ) -> Dict[str, Any]:
        """Adapt brain similarity arguments."""
        pattern1 = (
            llm_args.get("pattern1")
            or llm_args.get("first_pattern")
            or llm_args.get("data1")
            or llm_args.get("pattern_a")
        )

        pattern2 = (
            llm_args.get("pattern2")
            or llm_args.get("second_pattern")
            or llm_args.get("data2")
            or llm_args.get("pattern_b")
        )

        if not pattern1:
            raise ValueError("brain_similarity requires 'pattern1' argument")
        if not pattern2:
            raise ValueError("brain_similarity requires 'pattern2' argument")

        return {"pattern1": pattern1, "pattern2": pattern2}
