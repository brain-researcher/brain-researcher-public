"""Experiment configuration contract (v1) for reproducible R5 runs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ExperimentRunSpecV1(BaseModel):
    """Single run definition inside an experiment config."""

    run_key: str = Field(description="Stable run identifier within the experiment.")
    mode: str = Field(description="Experiment mode (e.g., integrated, isolated).")
    dataset_id: str = Field(description="Dataset identifier.")
    workflow_id: str = Field(description="Workflow or pipeline identifier.")
    parameters: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class ExperimentConfigV1(BaseModel):
    """Top-level experiment manifest used by R5 reproducibility scripts."""

    schema_version: Literal["experiment-config-v1"] = "experiment-config-v1"
    experiment_id: str
    comparison_type: str = Field(description="Comparison label, e.g. integrated_vs_isolated.")
    commit_sha: str | None = None
    seeds: dict[str, int] = Field(default_factory=dict)
    environment: dict[str, Any] = Field(default_factory=dict)
    runs: list[ExperimentRunSpecV1] = Field(default_factory=list)


__all__ = ["ExperimentConfigV1", "ExperimentRunSpecV1"]
