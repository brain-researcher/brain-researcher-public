"""ML / decoding thin-wrapper tools.

Extracted from grandmaster_tools.py — behavior-neutral refactor.

Contains the *cross-validation / decoding / searchlight / model-evaluation*
cluster (Layer 4/5 slice): four Tool+Args pairs that are pure thin wrappers
delegating via ``_call_wrapper`` to specialist implementations already in this
repository.  ``_call_wrapper`` is lazy-imported inside each ``_run`` body so
that the canonical monkeypatch target
``brain_researcher.services.tools.grandmaster_tools._call_wrapper`` is
unaffected.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

# ---------------------------------------------------------------------------
# ML Cross-Validation
# ---------------------------------------------------------------------------


class MLCrossValidationArgs(BaseModel):
    data_file: str = Field(description="Features array (n_samples x n_features)")
    labels_file: str = Field(description="Labels/targets file")
    groups_file: str | None = Field(
        default=None, description="Optional groups file (site/subject)"
    )
    cv_type: str = Field(default="kfold", description="CV splitter type")
    n_splits: int = Field(default=5, description="Number of folds")
    task_type: str = Field(
        default="classification", description="classification|regression"
    )
    metrics: list[str] = Field(
        default_factory=lambda: ["accuracy"], description="Metrics"
    )
    output_dir: str | None = Field(default=None, description="Output directory")


class MLCrossValidationTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "ml_cross_validation"

    def get_tool_description(self) -> str:
        return "Run cross-validation splits + metrics (wrapper over cross_validation)."

    def get_args_schema(self):
        return MLCrossValidationArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        from brain_researcher.services.tools.cross_validation_tool import (
            CrossValidationTool,
        )
        from brain_researcher.services.tools.grandmaster_tools import _call_wrapper

        return _call_wrapper(CrossValidationTool(), kwargs)


# ---------------------------------------------------------------------------
# Train Decoder
# ---------------------------------------------------------------------------


class TrainDecoderArgs(BaseModel):
    img: str = Field(description="Input data matrix (.npy) or nifti path")
    labels: str | list[float] = Field(
        description="Labels vector or path to labels file"
    )
    classifier: str = Field(default="svc", description="Classifier backend")
    cv_folds: int = Field(default=5, description="Cross-validation folds")
    permutations: int = Field(default=0, description="Permutation iterations")
    output_dir: str | None = Field(default=None, description="Output directory")


class TrainDecoderTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "train_decoder"

    def get_tool_description(self) -> str:
        return "Train/evaluate a decoder (wrapper over decoding_classifier)."

    def get_args_schema(self):
        return TrainDecoderArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        from brain_researcher.services.tools.grandmaster_tools import _call_wrapper
        from brain_researcher.services.tools.nilearn_mvpa import MVPADecodingTool

        return _call_wrapper(MVPADecodingTool(), kwargs)


# ---------------------------------------------------------------------------
# Run Searchlight
# ---------------------------------------------------------------------------


class RunSearchlightArgs(BaseModel):
    func_file: str = Field(description="4D fMRI nifti")
    output_dir: str = Field(description="Output directory")
    labels_file: str | None = Field(default=None, description="Labels file")
    radius: float = Field(default=6.0, description="Searchlight radius (mm)")
    analysis_type: str = Field(
        default="classification", description="classification|regression|rsa"
    )


class RunSearchlightTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "run_searchlight"

    def get_tool_description(self) -> str:
        return "Run searchlight MVPA (wrapper over searchlight_analysis)."

    def get_args_schema(self):
        return RunSearchlightArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        from brain_researcher.services.tools.grandmaster_tools import _call_wrapper
        from brain_researcher.services.tools.searchlight_tool import SearchlightTool

        return _call_wrapper(SearchlightTool(), kwargs)


# ---------------------------------------------------------------------------
# Evaluate Model
# ---------------------------------------------------------------------------


class EvaluateModelArgs(BaseModel):
    data_file: str = Field(description="Features array (n_samples x n_features)")
    labels_file: str = Field(description="Labels/targets file")
    cv_type: str = Field(default="kfold", description="CV splitter type")
    n_splits: int = Field(default=5, description="Number of folds")
    task_type: str = Field(
        default="classification", description="classification|regression"
    )
    metrics: list[str] = Field(
        default_factory=lambda: ["accuracy"], description="Metrics"
    )
    permutations: int = Field(default=0, description="Permutation iterations")
    output_dir: str | None = Field(default=None, description="Output directory")


class EvaluateModelTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "evaluate_model"

    def get_tool_description(self) -> str:
        return "Evaluate a model with CV + optional permutation testing (wrapper over cross_validation)."

    def get_args_schema(self):
        return EvaluateModelArgs

    def _run(self, **kwargs: Any) -> ToolResult:
        from brain_researcher.services.tools.cross_validation_tool import (
            CrossValidationTool,
        )
        from brain_researcher.services.tools.grandmaster_tools import _call_wrapper

        # Best-effort: CrossValidationTool supports permutations via downstream params;
        # keep wrapper stable and pass through extra fields.
        return _call_wrapper(CrossValidationTool(), kwargs)
