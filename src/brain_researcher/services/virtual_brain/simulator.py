"""Core simulation logic for the Virtual Brain platform."""

from __future__ import annotations

import json
import logging
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import numpy as np

from brain_researcher.core.ingestion.graph_factory import GraphDatabaseProtocol

from .config import VirtualBrainConfig
from .models import (
    FitRequest,
    FitResponse,
    RegionPrior,
    SimulationArtifact,
    SimulationMetrics,
    SimulationReport,
    SimulateRequest,
    SimulateResponse,
    SuggestParamsRequest,
    SuggestParamsResponse,
    WhatIfRequest,
    WhatIfResponse,
    WilsonCowanParameters,
)

UTC = timezone.utc

logger = logging.getLogger(__name__)

_EPS = 1e-9


@dataclass(slots=True)
class SCMatrices:
    """Container for structural connectivity and delay matrices."""

    id: str
    weights: np.ndarray
    delays: np.ndarray
    regions: List[str]
    metadata: Dict[str, str]

    def size(self) -> int:
        return int(self.weights.shape[0])


class VirtualBrainSimulator:
    """High-level orchestration layer for VB ingest + simulation."""

    def __init__(
        self,
        db: GraphDatabaseProtocol,
        config: VirtualBrainConfig,
        *,
        repository_root: Optional[Path] = None,
    ) -> None:
        self.db = db
        self.config = config
        self.repo_root = repository_root or Path(__file__).resolve().parents[4]
        self.config.cache_dir.mkdir(parents=True, exist_ok=True)

        self._sc_cache: Dict[str, SCMatrices] = {}
        self._target_cache: Dict[str, np.ndarray] = {}
        self._sc_meta_cache: Dict[str, dict] = {}
        self._target_meta_cache: Dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def close(self) -> None:
        """Close underlying DB connection if available."""
        close_fn = getattr(self.db, "close", None)
        if callable(close_fn):
            try:
                close_fn()
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Failed to close VB simulator DB connection: %s", exc)

    def suggest_params(self, request: SuggestParamsRequest) -> SuggestParamsResponse:
        """Produce priors for a given task by inspecting ACTIVATE edges."""
        task_node_id, task_props = self._resolve_task(request.task_id)

        sc = self._load_sc_matrix(
            parcellation=request.parcellation, sc_matrix_id=self.config.sc_matrix_id
        )

        priors_raw = self._collect_task_priors(task_node_id, request, sc.regions)
        if not priors_raw:
            message = f"No ACTIVATE edges available for task {request.task_id}"
            raise ValueError(message)

        priors = self._normalise_priors(
            priors_raw,
            alpha=request.alpha,
            top_k=request.top_k,
            region_filter=request.region_filter,
            region_order=sc.regions,
        )

        summary = {
            "n_regions": float(len(priors)),
            "alpha": float(request.alpha),
            "source_strength_sum": float(sum(p.strength for p in priors)),
        }

        return SuggestParamsResponse(
            parcellation=request.parcellation,
            priors=priors,
            summary=summary,
            source_task_id=task_props.get("id", request.task_id),
            sc_matrix_id=sc.id,
        )

    def simulate(self, request: SimulateRequest) -> SimulateResponse:
        """Run a forward simulation with provided parameters."""
        sc_matrix = self._load_sc_matrix(
            parcellation=request.parcellation,
            sc_matrix_id=request.sc_matrix_id or self.config.sc_matrix_id,
        )

        canonical_task_id: Optional[str] = None
        priors_response: Optional[SuggestParamsResponse] = None

        if not request.priors and request.task_id:
            priors_response = self.suggest_params(
                SuggestParamsRequest(
                    task_id=request.task_id,
                    parcellation=request.parcellation,
                    top_k=None,
                    alpha=1.0,
                    include_aliases=True,
                )
            )
            priors = priors_response.priors
            canonical_task_id = priors_response.source_task_id
        else:
            priors = list(request.priors or [])
            if request.task_id:
                try:
                    canonical_task_id, _ = self._resolve_task(request.task_id)
                except ValueError:
                    canonical_task_id = request.task_id

        i_ext = self._build_external_drive(priors, sc_matrix)
        params = (
            request.parameters
            if request.parameters.i_ext is not None
            else request.parameters.model_copy(update={"i_ext": i_ext.tolist() if i_ext is not None else None})
        )

        sim_id = f"sim:{request.parcellation}:{uuid.uuid4().hex[:12]}"
        duration = float(request.duration)
        dt = float(request.dt)
        seed = request.seed

        sim_samples, bold_samples = self._run_wilson_cowan(
            sc_matrix, params, duration=duration, dt=dt, seed=seed
        )

        metrics = SimulationMetrics()
        target_fc = None
        if request.include_metrics:
            metrics = self._compute_metrics(
                bold_samples,
                sc_matrix,
                target_fc_id=self.config.target_fc_id,
            )
            target_fc = metrics.fc_pearson

        artifacts: List[SimulationArtifact] = []
        sim_dir: Optional[Path] = None
        region_activity: List[dict[str, float]] = []
        if request.persist:
            artifacts, sim_dir, region_activity = self._persist_artifacts(
                sim_id, bold_samples, sim_samples, metrics, sc_matrix
            )

        response = SimulateResponse(
            simulation_id=sim_id if request.persist else None,
            parcellation=request.parcellation,
            metrics=metrics,
            priors=priors,
            parameters=params,
            artifacts=artifacts,
            persisted=False,
        )

        if request.persist:
            self._persist_simulation(
                sim_id,
                request,
                params,
                priors,
                metrics,
                artifacts,
                sc_matrix,
                target_fc,
                task_node_id=canonical_task_id,
                sim_dir=sim_dir or (self.config.cache_dir / sim_id.replace(":", "_")),
                region_activity=region_activity,
            )
            response.persisted = True

        return response

    def fit(self, request: FitRequest) -> FitResponse:
        """Run a coarse parameter search to match an empirical target."""
        priors = list(request.priors or [])
        if not priors and request.task_id:
            priors = self.suggest_params(
                SuggestParamsRequest(
                    task_id=request.task_id,
                    parcellation=request.parcellation,
                    top_k=None,
                    alpha=1.0,
                    include_aliases=True,
                )
            ).priors

        rng = np.random.default_rng(request.seed)
        evaluations: List[Dict[str, float]] = []
        best_score = -math.inf
        best_params = request.parameters
        best_response: Optional[SimulateResponse] = None

        for _ in range(request.max_evals):
            candidate_params = request.parameters.model_copy()
            for field, bounds in request.search_space.items():
                low, high = bounds
                sample = float(rng.uniform(low, high))
                candidate_params = candidate_params.model_copy(update={field: sample})

            eval_response = self.simulate(
                SimulateRequest(
                    model=request.model,
                    parcellation=request.parcellation,
                    sc_matrix_id=request.sc_matrix_id,
                    duration=request.duration,
                    dt=request.dt,
                    parameters=candidate_params,
                    task_id=request.task_id,
                    priors=priors,
                    persist=False,
                    seed=request.seed,
                    include_metrics=True,
                )
            )
            score = eval_response.metrics.fc_pearson or float("-inf")
            evaluations.append(
                {
                    "score": float(score),
                    "g": float(candidate_params.g),
                    "sigma": float(candidate_params.sigma),
                }
            )
            if score > best_score:
                best_score = score
                best_params = candidate_params
                best_response = eval_response

        if request.persist:
            best_response = self.simulate(
                SimulateRequest(
                    model=request.model,
                    parcellation=request.parcellation,
                    sc_matrix_id=request.sc_matrix_id,
                    duration=request.duration,
                    dt=request.dt,
                    parameters=best_params,
                    task_id=request.task_id,
                    priors=priors,
                    persist=True,
                    seed=request.seed,
                    include_metrics=True,
                )
            )

        if best_response is None:
            best_response = self.simulate(
                SimulateRequest(
                    model=request.model,
                    parcellation=request.parcellation,
                    sc_matrix_id=request.sc_matrix_id,
                    duration=request.duration,
                    dt=request.dt,
                    parameters=best_params,
                    task_id=request.task_id,
                    priors=priors,
                    persist=False,
                    seed=request.seed,
                    include_metrics=True,
                )
            )

        return FitResponse(simulation=best_response, evaluations=evaluations, best_score=best_score)

    def report(self, simulation_id: str) -> SimulationReport:
        node = self.db.get_node(simulation_id)  # type: ignore[attr-defined]
        if not node:
            return SimulationReport(
                simulation_id=simulation_id,
                status="missing",
                model="wilson_cowan",
                parcellation=self.config.parcellation,
                sc_matrix_id=self.config.sc_matrix_id,
                parameters=WilsonCowanParameters(),
                priors=[],
            )

        props = dict(node)
        status = props.get("status", "completed")
        parcellation = props.get("parcellation", self.config.parcellation)
        sc_id = props.get("sc_matrix_id") or self.config.sc_matrix_id
        parameters = self._decode_json_field(props.get("parameters"), WilsonCowanParameters) or WilsonCowanParameters()
        priors = self._decode_json_field(props.get("priors"), list) or []
        priors_models = [RegionPrior.model_validate(p) for p in priors]
        metrics = self._decode_json_field(props.get("metrics"), SimulationMetrics) or SimulationMetrics()
        artifacts = self._decode_json_field(props.get("artifacts"), list) or []
        artifact_models = [SimulationArtifact.model_validate(a) for a in artifacts]

        created_at = props.get("created_at")
        if isinstance(created_at, str):
            try:
                created_at_dt = datetime.fromisoformat(created_at)
            except ValueError:
                created_at_dt = None
        else:
            created_at_dt = None

        provenance = self._decode_json_field(props.get("provenance"), dict) or {}

        return SimulationReport(
            simulation_id=simulation_id,
            status=status,
            model=props.get("model", "wilson_cowan"),
            parcellation=parcellation,
            sc_matrix_id=sc_id,
            parameters=parameters,
            priors=priors_models,
            metrics=metrics,
            created_at=created_at_dt,
            artifacts=artifact_models,
            provenance=provenance,
        )

    def whatif(self, request: WhatIfRequest) -> WhatIfResponse:
        baseline = self.report(request.simulation_id)
        if baseline.status == "missing":
            raise ValueError(f"Simulation {request.simulation_id} not found")

        if not hasattr(baseline.parameters, request.parameter):
            raise ValueError(f"Parameter {request.parameter} not recognised")

        base_value = getattr(baseline.parameters, request.parameter)
        deltas = [-request.delta_pct, request.delta_pct]
        perturbed_reports: List[SimulationReport] = []

        for delta in deltas:
            factor = 1.0 + delta / 100.0
            updated_params = baseline.parameters.model_copy(
                update={request.parameter: max(_EPS, base_value * factor)}
            )
            response = self.simulate(
                SimulateRequest(
                    model=baseline.model,
                    parcellation=baseline.parcellation,
                    sc_matrix_id=baseline.sc_matrix_id,
                    duration=120.0,
                    dt=0.001,
                    parameters=updated_params,
                    priors=baseline.priors,
                    persist=False,
                    include_metrics=True,
                )
            )
            perturbed_reports.append(
                SimulationReport(
                    simulation_id=response.simulation_id or f"whatif:{uuid.uuid4().hex[:8]}",
                    status="completed",
                    model=baseline.model,
                    parcellation=baseline.parcellation,
                    sc_matrix_id=baseline.sc_matrix_id,
                    parameters=response.parameters,
                    priors=response.priors,
                    metrics=response.metrics,
                    created_at=response.created_at,
                    artifacts=response.artifacts,
                    provenance={"baseline": baseline.simulation_id, "delta_pct": str(delta)},
                )
            )

        return WhatIfResponse(baseline=baseline, perturbed=perturbed_reports)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _normalize_path(self, uri: str) -> Path:
        path = Path(uri)
        if not path.is_absolute():
            path = self.repo_root / path
        return path

    def _load_array_from_uri(self, uri: str) -> np.ndarray:
        path = self._normalize_path(uri)
        if not path.exists():
            raise FileNotFoundError(f"Matrix file not found: {path}")

        if path.suffix in {".npy", ".npz"}:
            arr = np.load(path, allow_pickle=True)
            return arr["arr_0"] if isinstance(arr, np.lib.npyio.NpzFile) else arr
        if path.suffix in {".csv", ".tsv"}:
            delimiter = "," if path.suffix == ".csv" else "\t"
            return np.loadtxt(path, delimiter=delimiter)
        raise ValueError(f"Unsupported matrix format: {path}")

    def _load_sc_matrix(self, parcellation: str, sc_matrix_id: Optional[str]) -> SCMatrices:
        sc_id = sc_matrix_id or self.config.sc_matrix_id
        if not sc_id:
            raise ValueError("SC matrix id must be provided in config or request")
        cache_key = f"{sc_id}:{parcellation}"
        if cache_key in self._sc_cache:
            return self._sc_cache[cache_key]

        node = self._get_node_by_id(sc_id)
        if not node:
            raise ValueError(f"SCMatrix node {sc_id} not found")

        weights_uri = (
            node.get("weights_uri")
            or node.get("matrix_uri")
            or node.get("uri")
            or node.get("weights_path")
        )
        if not weights_uri:
            raise ValueError(f"SCMatrix node {sc_id} missing weights_uri")
        delays_uri = node.get("delays_uri") or node.get("lengths_uri") or node.get("distance_uri")
        regions = node.get("regions") or node.get("region_ids") or []
        if isinstance(regions, str):
            try:
                regions = json.loads(regions)
            except json.JSONDecodeError:
                regions = regions.split(",")

        weights = self._load_array_from_uri(weights_uri)
        delays = np.zeros_like(weights)
        if delays_uri:
            delays = self._load_array_from_uri(delays_uri)

        sc_metadata = {
            "parcellation": node.get("parcellation", parcellation),
            "source": node.get("source", "unknown"),
        }
        if weights_uri:
            sc_metadata["weights_uri"] = weights_uri
        if delays_uri:
            sc_metadata["delays_uri"] = delays_uri
        if node.get("license"):
            sc_metadata["license"] = node.get("license")

        sc = SCMatrices(
            id=node.get("id", sc_id),
            weights=np.asarray(weights, dtype=float),
            delays=np.asarray(delays, dtype=float),
            regions=list(regions),
            metadata=sc_metadata,
        )
        self._sc_cache[cache_key] = sc
        self._sc_meta_cache[sc.id] = dict(node)
        return sc

    def _load_target_fc(self, fc_id: Optional[str]) -> Optional[np.ndarray]:
        if not fc_id:
            return None
        if fc_id in self._target_cache:
            return self._target_cache[fc_id]

        node = self._get_node_by_id(fc_id)
        if not node:
            logger.warning("Target FC node %s not found", fc_id)
            return None

        fc_uri = node.get("uri") or node.get("matrix_uri") or node.get("path")
        if not fc_uri:
            logger.warning("Target FC node %s missing uri", fc_id)
            return None

        fc = self._load_array_from_uri(fc_uri)
        arr = np.asarray(fc, dtype=float)
        self._target_cache[fc_id] = arr
        self._target_meta_cache[fc_id] = dict(node)
        return arr

    def _resolve_task(self, task_id: str) -> Tuple[str, dict]:
        candidates = [
            {"id": task_id},
            {"label": task_id},
            {"name": task_id},
        ]
        for criterion in candidates:
            matches = self.db.find_nodes("Task", criterion)  # type: ignore[attr-defined]
            if matches:
                node_id, props = matches[0]
                props.setdefault("id", node_id)
                return node_id, props
        raise ValueError(f"Task node {task_id!r} not found")

    def _collect_task_priors(
        self,
        task_node_id: str,
        request: SuggestParamsRequest,
        sc_regions: Sequence[str],
    ) -> List[Tuple[str, float, MutableMapping[str, float]]]:
        priors: List[Tuple[str, float, MutableMapping[str, float]]] = []
        rels = self.db.find_relationships(start_node=task_node_id, rel_type="ACTIVATES")  # type: ignore[attr-defined]
        for _, region_id, rel_props in rels:
            strength = rel_props.get("strength")
            if strength is None:
                strength = rel_props.get("weight")
            if strength is None:
                continue
            try:
                strength_val = float(strength)
            except (TypeError, ValueError):
                continue
            region_props = self._get_node_by_id(region_id) or {}
            region_parcellation = region_props.get("parcellation") or region_props.get("atlas")
            if region_parcellation and region_parcellation.lower() != request.parcellation.lower():
                continue
            if sc_regions and region_id not in sc_regions:
                continue
            priors.append((region_id, strength_val, rel_props))
        return priors

    def _normalise_priors(
        self,
        priors: Iterable[Tuple[str, float, Mapping[str, float]]],
        *,
        alpha: float,
        top_k: Optional[int],
        region_filter: Optional[Sequence[str]],
        region_order: Sequence[str],
    ) -> List[RegionPrior]:
        sorted_priors = sorted(priors, key=lambda row: row[1], reverse=True)
        if top_k:
            sorted_priors = sorted_priors[:top_k]
        if region_filter:
            region_filter_set = {rid for rid in region_filter}
            sorted_priors = [row for row in sorted_priors if row[0] in region_filter_set]

        strengths = np.array([row[1] for row in sorted_priors], dtype=float)
        if strengths.size == 0:
            return []
        denom = float(strengths.max()) or 1.0
        weights = strengths / denom

        priors_model: List[RegionPrior] = []
        for (region_id, strength, rel_props), weight in zip(sorted_priors, weights):
            priors_model.append(
                RegionPrior(
                    region_id=region_id,
                    strength=float(strength),
                    weight=float(weight * alpha),
                    source=str(rel_props.get("source", "ACTIVATES")),
                )
            )

        region_index = {rid: idx for idx, rid in enumerate(region_order)}
        priors_model.sort(key=lambda prior: region_index.get(prior.region_id, 10**6))
        return priors_model

    def _build_external_drive(
        self,
        priors: Sequence[RegionPrior],
        sc_matrix: SCMatrices,
    ) -> Optional[np.ndarray]:
        if not priors:
            return None
        ext = np.zeros(sc_matrix.size(), dtype=float)
        region_index = {rid: idx for idx, rid in enumerate(sc_matrix.regions)}
        for prior in priors:
            idx = region_index.get(prior.region_id)
            if idx is None:
                continue
            ext[idx] = prior.weight if prior.weight is not None else float(prior.strength)
        return ext

    def _run_wilson_cowan(
        self,
        sc: SCMatrices,
        params: WilsonCowanParameters,
        *,
        duration: float,
        dt: float,
        seed: Optional[int],
    ) -> Tuple[np.ndarray, np.ndarray]:
        n_regions = sc.size()
        steps = int(duration / dt)
        sample_stride = max(1, int(round(0.01 / dt)))  # sample every 10ms
        sample_count = (steps // sample_stride) + 1

        rng = np.random.default_rng(seed)
        e_state = rng.uniform(0, 0.2, size=n_regions)
        i_state = rng.uniform(0, 0.2, size=n_regions)
        ext = np.asarray(params.i_ext or np.zeros(n_regions), dtype=float)
        weights = np.asarray(sc.weights, dtype=float)

        samples = np.zeros((sample_count, n_regions), dtype=float)
        bold = np.zeros_like(samples)

        def sigmoid(x: np.ndarray) -> np.ndarray:
            return 1.0 / (1.0 + np.exp(-x))

        sample_idx = 0
        for step in range(steps):
            coupled_e = params.g * weights.dot(e_state)
            coupled_i = params.g * weights.dot(i_state)
            noise_e = rng.normal(0.0, params.sigma, size=n_regions)
            noise_i = rng.normal(0.0, params.sigma, size=n_regions)

            drive_e = params.w_ee * e_state - params.w_ei * i_state + coupled_e + ext + noise_e
            drive_i = params.w_ie * e_state - params.w_ii * i_state + coupled_i + noise_i

            dE = (-e_state + sigmoid(drive_e)) / params.tau_e
            dI = (-i_state + sigmoid(drive_i)) / params.tau_i

            e_state = np.clip(e_state + dt * dE, 0.0, 1.0)
            i_state = np.clip(i_state + dt * dI, 0.0, 1.0)

            if step % sample_stride == 0:
                samples[sample_idx] = e_state
                bold[sample_idx] = self._balloon_windkessel(e_state, sample_idx, dt * sample_stride)
                sample_idx += 1

        return samples[:sample_idx], bold[:sample_idx]

    @staticmethod
    def _balloon_windkessel(activity: np.ndarray, index: int, dt: float) -> np.ndarray:
        """Simple low-pass filter placeholder for BOLD mapping."""
        alpha = 0.9
        if index == 0:
            return np.copy(activity)
        return alpha * activity + (1 - alpha) * activity.mean()

    def _compute_metrics(
        self,
        bold_samples: np.ndarray,
        sc: SCMatrices,
        target_fc_id: Optional[str],
    ) -> SimulationMetrics:
        metrics = SimulationMetrics()
        if bold_samples.size == 0:
            return metrics

        metrics.bold_mean = float(bold_samples.mean())
        metrics.bold_std = float(bold_samples.std())

        centered = bold_samples - bold_samples.mean(axis=0, keepdims=True)
        if centered.shape[0] > 1:
            sim_fc = np.corrcoef(centered.T)
        else:
            sim_fc = np.zeros((centered.shape[1], centered.shape[1]))

        target_fc = self._load_target_fc(target_fc_id)
        if target_fc is not None and sim_fc.shape == target_fc.shape:
            triu = np.triu_indices(sim_fc.shape[0], k=1)
            sim_vec = sim_fc[triu]
            target_vec = target_fc[triu]
            if sim_vec.std() > 0 and target_vec.std() > 0:
                metrics.fc_pearson = float(np.corrcoef(sim_vec, target_vec)[0, 1])

        diff = np.diff(bold_samples, axis=0)
        broadband = float(np.mean(diff**2)) if diff.size else 0.0
        half = max(1, sc.size() // 2)
        slow_slice = bold_samples[:, :half]
        slow_power = float(np.mean(slow_slice**2)) if slow_slice.size else None
        metrics.power_band = {"broadband": broadband}
        if slow_power is not None and math.isfinite(slow_power):
            metrics.power_band["slow"] = slow_power

        return metrics

    def _persist_artifacts(
        self,
        sim_id: str,
        bold_samples: np.ndarray,
        e_samples: np.ndarray,
        metrics: SimulationMetrics,
        sc_matrix: SCMatrices,
    ) -> tuple[List[SimulationArtifact], Path, List[dict[str, float]]]:
        sim_dir = self.config.cache_dir / sim_id.replace(":", "_")
        sim_dir.mkdir(parents=True, exist_ok=True)

        bold_path = sim_dir / "bold_samples.npy"
        np.save(bold_path, bold_samples)

        act_path = sim_dir / "activity_samples.npy"
        np.save(act_path, e_samples)

        metrics_path = sim_dir / "metrics.json"
        with metrics_path.open("w", encoding="utf-8") as handle:
            json.dump(metrics.model_dump(), handle, indent=2, sort_keys=True)

        region_activity: List[dict[str, float]] = []
        if e_samples.size and sc_matrix.regions:
            means = e_samples.mean(axis=0)
            region_activity = [
                {
                    "region_id": sc_matrix.regions[idx],
                    "mean_activity": float(means[idx]),
                }
                for idx in range(min(len(sc_matrix.regions), means.shape[0]))
            ]
        region_path = sim_dir / "region_activity.json"
        with region_path.open("w", encoding="utf-8") as handle:
            json.dump(region_activity, handle, indent=2, sort_keys=True)

        artifacts = [
            SimulationArtifact(uri=str(bold_path), media_type="application/x-npy", description="BOLD samples"),
            SimulationArtifact(uri=str(act_path), media_type="application/x-npy", description="Excitatory activity"),
            SimulationArtifact(uri=str(metrics_path), media_type="application/json", description="Simulation metrics"),
            SimulationArtifact(uri=str(region_path), media_type="application/json", description="Region mean activity"),
        ]
        return artifacts, sim_dir, region_activity

    def _persist_simulation(
        self,
        sim_id: str,
        request: SimulateRequest,
        params: WilsonCowanParameters,
        priors: List[RegionPrior],
        metrics: SimulationMetrics,
        artifacts: List[SimulationArtifact],
        sc_matrix: SCMatrices,
        target_fc: Optional[float],
        *,
        task_node_id: Optional[str],
        sim_dir: Path,
        region_activity: List[dict[str, float]],
    ) -> None:
        sc_meta = dict(self._sc_meta_cache.get(sc_matrix.id, {}))
        sc_meta.setdefault("id", sc_matrix.id)
        sc_meta.setdefault("parcellation", sc_matrix.metadata.get("parcellation"))
        if sc_matrix.metadata.get("weights_uri"):
            sc_meta.setdefault("weights_uri", sc_matrix.metadata.get("weights_uri"))
        if sc_matrix.metadata.get("delays_uri"):
            sc_meta.setdefault("delays_uri", sc_matrix.metadata.get("delays_uri"))

        target_meta: Optional[dict] = None
        if self.config.target_fc_id:
            raw = self._target_meta_cache.get(self.config.target_fc_id)
            if raw:
                target_meta = dict(raw)

        preview = sorted(
            region_activity,
            key=lambda item: item.get("mean_activity", 0.0),
            reverse=True,
        )[:10]

        properties = {
            "id": sim_id,
            "model": request.model,
            "parcellation": request.parcellation,
            "duration": float(request.duration),
            "dt": float(request.dt),
            "seed": request.seed,
            "status": "completed",
            "sc_matrix_id": sc_matrix.id,
            "seeded_task_id": task_node_id,
            "created_at": datetime.now(UTC).isoformat(),
            "parameters": params.model_dump(),
            "priors": [prior.model_dump() for prior in priors],
            "metrics": metrics.model_dump(),
            "artifacts": [artifact.model_dump() for artifact in artifacts],
            "target_fc": target_fc,
            "provenance": {
                "service": "virtual_brain",
                "cache_dir": str(self.config.cache_dir),
            },
            "report_uri": str(sim_dir / "report.json"),
            "region_activity_preview": preview,
        }
        self.db.create_node("Simulation", properties, node_id=sim_id)  # type: ignore[attr-defined]
        if task_node_id:
            self.db.create_relationship(sim_id, task_node_id, "SEEDED_BY", {"source": "virtual_brain"})  # type: ignore[attr-defined]
        self.db.create_relationship(sim_id, sc_matrix.id, "USES_NETWORK", {"source": "virtual_brain"})  # type: ignore[attr-defined]
        if self.config.target_fc_id:
            target_id = self.config.target_fc_id
            if target_id and target_meta:
                self.db.create_relationship(
                    sim_id, target_id, "FIT_TO", {"source": "virtual_brain"}
                )  # type: ignore[attr-defined]

        report_payload = {
            "simulation": properties,
            "sc_matrix": sc_meta,
            "target_fc": target_meta,
            "region_activity": region_activity,
            "task_id": task_node_id,
        }
        report_path = sim_dir / "report.json"
        with report_path.open("w", encoding="utf-8") as handle:
            json.dump(report_payload, handle, indent=2, sort_keys=True)

    def _decode_json_field(self, value: object, model_cls):
        if value is None:
            return None
        if isinstance(value, model_cls):
            return value
        if isinstance(value, (str, bytes)):
            try:
                data = json.loads(value)
            except json.JSONDecodeError:
                return None
        else:
            data = value
        if hasattr(model_cls, "model_validate"):
            return model_cls.model_validate(data)  # type: ignore[attr-defined]
        return data

    def _get_node_by_id(self, node_id: str) -> Optional[dict]:
        if hasattr(self.db, "get_node"):
            node = self.db.get_node(node_id)  # type: ignore[attr-defined]
            if node:
                return dict(node)
        matches = self.db.find_nodes(None, {"id": node_id})  # type: ignore[attr-defined]
        if matches:
            _, props = matches[0]
            props.setdefault("id", node_id)
            return props
        return None
