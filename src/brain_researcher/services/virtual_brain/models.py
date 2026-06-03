"""Pydantic models shared by the Virtual Brain service."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator

UTC = timezone.utc


class RegionPrior(BaseModel):
    """Prior weight injected into a region's external drive."""

    region_id: str = Field(..., description="Canonical Region.id in BR-KG.")
    strength: float = Field(
        ..., description="Evidence strength (e.g., ACT" "IVATES.strength)."
    )
    weight: float | None = Field(
        None, description="Normalized weight applied to the simulation input vector."
    )
    source: str | None = Field(
        None, description="Source node identifier or citation for the prior."
    )


class SuggestParamsRequest(BaseModel):
    """Request payload for deriving virtual brain priors from BR-KG."""

    task_id: str = Field(..., description="Task node id or alias used to seed priors.")
    parcellation: str = Field(
        "schaefer100",
        description="Parcellation label (must match SCMatrix.parcellation).",
    )
    top_k: int | None = Field(
        25,
        ge=1,
        description="Optional cut-off of strongest regions to include. None keeps all.",
    )
    alpha: float = Field(
        1.0,
        ge=0.0,
        description="Linear gain used when mapping prior strength to I_ext.",
    )
    include_aliases: bool = Field(
        True,
        description="Expand task_id via NodeLabelLinker aliases before lookup.",
    )
    region_filter: Sequence[str] | None = Field(
        None,
        description="Explicit subset of Region ids to keep (applied after top_k).",
    )


class SuggestParamsResponse(BaseModel):
    model: Literal["wilson_cowan"] = "wilson_cowan"
    parcellation: str
    priors: list[RegionPrior]
    summary: dict[str, float] = Field(default_factory=dict)
    source_task_id: str
    sc_matrix_id: str | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WilsonCowanParameters(BaseModel):
    """Parameter payload consumed by the simulator."""

    g: float = Field(2.5, description="Global coupling strength.")
    w_ee: float = Field(10.0, description="Excitatory-to-excitatory weight.")
    w_ei: float = Field(10.0, description="Inhibitory-to-excitatory weight.")
    w_ie: float = Field(10.0, description="Excitatory-to-inhibitory weight.")
    w_ii: float = Field(10.0, description="Inhibitory-to-inhibitory weight.")
    tau_e: float = Field(0.02, gt=0, description="Excitatory time constant (s).")
    tau_i: float = Field(0.01, gt=0, description="Inhibitory time constant (s).")
    sigma: float = Field(0.01, ge=0, description="Additive noise scale.")
    v: float = Field(10.0, gt=0, description="Conduction velocity (m/s).")
    i_ext: list[float] | None = Field(
        None, description="Optional explicit external drive vector (per region)."
    )

    def as_vector(self) -> tuple[float, float, float, float, float, float, float]:
        return (
            self.g,
            self.w_ee,
            self.w_ei,
            self.w_ie,
            self.w_ii,
            self.tau_e,
            self.tau_i,
        )


class SimulationMetrics(BaseModel):
    """Canonical set of simulation quality metrics."""

    fc_pearson: float | None = Field(
        None, description="Pearson r between simulated FC and target FC."
    )
    bold_mean: float | None = None
    bold_std: float | None = None
    power_band: dict[str, float] = Field(default_factory=dict)


class SimulationArtifact(BaseModel):
    """Lightweight pointer to persisted artefacts."""

    uri: str
    etag: str | None = None
    media_type: str | None = None
    description: str | None = None


class SimulateRequest(BaseModel):
    """Request to run a forward simulation."""

    model: Literal["wilson_cowan"] = "wilson_cowan"
    parcellation: str = "schaefer100"
    sc_matrix_id: str | None = Field(
        None, description="Optional explicit SCMatrix.id to use; defaults to config."
    )
    duration: float = Field(120.0, gt=0, description="Simulation duration (seconds).")
    dt: float = Field(0.001, gt=0, description="Integrator step (seconds).")
    parameters: WilsonCowanParameters = Field(default_factory=WilsonCowanParameters)
    task_id: str | None = Field(
        None, description="Optional task id; reused to register priors/edges."
    )
    priors: list[RegionPrior] | None = Field(
        None, description="Explicit priors (bypass suggest_params)."
    )
    persist: bool = Field(
        True, description="Store Simulation node and artefact metadata."
    )
    seed: int | None = Field(None, description="Random seed for reproducibility.")
    include_metrics: bool = Field(
        True, description="Compute quick QC metrics (FC correlation, PSD)."
    )

    @field_validator("duration")
    @classmethod
    def _validate_duration(cls, value: float) -> float:
        if value <= 0:
            msg = "duration must be > 0"
            raise ValueError(msg)
        return value


class SimulateResponse(BaseModel):
    simulation_id: str | None = None
    mode: Literal["wilson_cowan"] = "wilson_cowan"
    parcellation: str
    metrics: SimulationMetrics = Field(default_factory=SimulationMetrics)
    priors: list[RegionPrior] = Field(default_factory=list)
    parameters: WilsonCowanParameters
    artifacts: list[SimulationArtifact] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    persisted: bool = False


class FitRequest(SimulateRequest):
    """Parameter fitting run based on empirical targets."""

    objective: Literal["fc", "psd", "multi"] = "fc"
    max_evals: int = Field(50, gt=0, description="Evaluation budget for optimizer.")
    search_space: dict[str, tuple[float, float]] = Field(
        default_factory=lambda: {
            "g": (0.5, 4.0),
            "sigma": (0.001, 0.02),
        },
        description="Parameter bounds used during optimization.",
    )
    retain_trace: bool = Field(
        True, description="Keep optimizer trace as artefact if persist=True."
    )


class FitResponse(BaseModel):
    simulation: SimulateResponse
    evaluations: list[dict[str, float]] = Field(default_factory=list)
    best_score: float | None = None


class SimulationReport(BaseModel):
    simulation_id: str
    status: Literal["completed", "pending", "missing", "failed"]
    model: Literal["wilson_cowan"] = "wilson_cowan"
    parcellation: str = "schaefer100"
    sc_matrix_id: str | None = None
    parameters: WilsonCowanParameters
    priors: list[RegionPrior] = Field(default_factory=list)
    metrics: SimulationMetrics = Field(default_factory=SimulationMetrics)
    created_at: datetime | None = None
    artifacts: list[SimulationArtifact] = Field(default_factory=list)
    provenance: dict[str, str] = Field(default_factory=dict)


class WhatIfRequest(BaseModel):
    simulation_id: str
    parameter: str = Field(..., pattern=r"^[A-Za-z0-9_]+$")
    delta_pct: float = Field(5.0, description="+/- percentage perturbation to apply")


class WhatIfResponse(BaseModel):
    baseline: SimulationReport
    perturbed: list[SimulationReport]
