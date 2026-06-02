"""Helpers for building reproducibility bundles from run artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from brain_researcher.core.reproducibility import compute_reproducibility_v1
from brain_researcher.services.memory.distill import _find_run_dir
from brain_researcher.services.review.bundle_builder import build_artifact_review_bundle
from brain_researcher.services.review.native_bundle_resolver import (
    load_json_artifact,
    native_analysis_bundle,
    native_execution_manifest,
    native_observation,
)


@dataclass(frozen=True)
class ReproducibilityBundleParameters:
    """Parameters for a reproducibility bundle request."""

    run_id: str
    run_dir: str | None = None


def reproducibility_bundle_from_payload(
    payload: dict[str, object],
) -> ReproducibilityBundleParameters:
    """Create typed parameters from a payload."""

    return ReproducibilityBundleParameters(
        run_id=str(payload["run_id"]),
        run_dir=str(payload["run_dir"]) if payload.get("run_dir") else None,
    )


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _build_component_status(
    *,
    analysis_bundle: dict[str, Any],
    observation: dict[str, Any],
    execution_manifest: dict[str, Any],
    inputs_manifest: dict[str, Any],
    artifact_manifest: dict[str, Any],
    review_bundle: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "analysis_bundle": bool(analysis_bundle),
        "observation": bool(observation),
        "execution_manifest": bool(execution_manifest),
        "inputs_manifest": bool(inputs_manifest),
        "artifact_manifest": bool(artifact_manifest),
        "review_bundle": bool(review_bundle),
    }


def build_reproducibility_bundle_payload(
    run_id: str,
    *,
    run_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Build a reproducibility bundle using the native analysis artifacts."""

    resolved_run_dir = _find_run_dir(run_id, run_dir=Path(run_dir) if run_dir else None)
    analysis_bundle = native_analysis_bundle(resolved_run_dir)
    observation = native_observation(resolved_run_dir, analysis_bundle)
    execution_manifest = native_execution_manifest(resolved_run_dir, analysis_bundle)
    inputs_manifest = load_json_artifact(resolved_run_dir / "inputs_manifest.json")
    artifact_manifest = load_json_artifact(resolved_run_dir / "artifact_manifest.json")

    review_bundle: dict[str, Any] | None = None
    review_bundle_error: str | None = None
    try:
        review_obj = build_artifact_review_bundle(run_id, run_dir=resolved_run_dir)
        review_bundle = review_obj.model_dump(mode="json", exclude_none=True)
    except Exception as exc:  # pragma: no cover - best-effort wrapper
        review_bundle_error = str(exc)

    datasets = _dict_items((inputs_manifest or {}).get("datasets"))
    datasets.extend(_dict_items((inputs_manifest or {}).get("inputs")))
    artifacts = _dict_items((artifact_manifest or {}).get("artifacts"))
    parameters = (
        dict((execution_manifest or {}).get("parameters") or {})
        if isinstance(execution_manifest, dict)
        else {}
    )

    reproducibility = compute_reproducibility_v1(
        run_dir=resolved_run_dir,
        datasets=datasets,
        artifacts=artifacts,
        parameters=parameters,
        versions=(analysis_bundle or {}).get("versions"),
        policy=(analysis_bundle or {}).get("policy"),
    )

    component_status = _build_component_status(
        analysis_bundle=analysis_bundle,
        observation=observation,
        execution_manifest=execution_manifest,
        inputs_manifest=inputs_manifest or {},
        artifact_manifest=artifact_manifest or {},
        review_bundle=review_bundle,
    )

    warnings = [
        key.replace("_", " ") + " missing"
        for key, present in component_status.items()
        if not present
    ]
    if review_bundle_error:
        warnings.append(f"review_bundle_error: {review_bundle_error}")

    return {
        "bundle_type": "engineering_reproducibility",
        "scope_note": (
            "This bundle summarizes engineering reproducibility artifacts and "
            "native manifests. It is not a substitute for peer review."
        ),
        "run_id": run_id,
        "run_dir": str(resolved_run_dir),
        "analysis_bundle": analysis_bundle,
        "observation": observation,
        "execution_manifest": execution_manifest,
        "inputs_manifest": inputs_manifest or {},
        "artifact_manifest": artifact_manifest or {},
        "review_bundle": review_bundle,
        "reproducibility": reproducibility,
        "reproducibility_score": reproducibility.get("score"),
        "component_status": component_status,
        "warnings": warnings,
    }


__all__ = [
    "ReproducibilityBundleParameters",
    "build_reproducibility_bundle_payload",
    "reproducibility_bundle_from_payload",
]
