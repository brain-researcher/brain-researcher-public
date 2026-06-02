"""Canonical predictive loop-controller wrapper around the live FC meta-controller."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from brain_researcher.autoresearch.quality_protocol import GateVerdict
from brain_researcher.core.contracts import (
    AnalysisBundleFiles,
    AnalysisBundleV1,
    ExecutionEntrypointsV1,
    ExecutionIORefV1,
    ExecutionManifestV1,
    ExecutionModeV1,
    ExecutionReproV1,
    ExecutionRuntimeV1,
    ObservationFiles,
    ObservationSpecV1,
)
from brain_researcher.core.contracts.native_review_contract import (
    build_native_review_context,
)
from brain_researcher.research._legacy_project_loader import (
    legacy_project_script_path,
    load_legacy_project_module,
    run_legacy_main,
)
from brain_researcher.research.predictive.gates.common import term_index_of

LEGACY_SCRIPT = Path("scripts/analysis/fc_benchmarking/meta_controller.py")
WEAK_TARGET_PHASE = "phase9_weak_target_term_discovery"
NATIVE_BUNDLE_HELPER_NAMES = (
    "emit_native_bundle",
    "write_native_bundle",
    "persist_native_bundle",
)


def _load_ledger_rows(ledger_path: Path) -> list[dict[str, Any]]:
    if not ledger_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in ledger_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _path_or_none(value: Any) -> Path | None:
    text = _text(value)
    if text is None:
        return None
    return Path(text).expanduser().resolve()


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_none=True)
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(payload, "model_dump_json"):
        path.write_text(
            payload.model_dump_json(indent=2, exclude_none=True),
            encoding="utf-8",
        )
        return
    path.write_text(
        json.dumps(payload, indent=2, default=_json_default, ensure_ascii=False),
        encoding="utf-8",
    )


def _resolve_native_bundle_run_dir(payload: dict[str, Any]) -> Path | None:
    for key in ("run_dir", "artifact_root", "output_dir", "bundle_root"):
        if path := _path_or_none(payload.get(key)):
            return path
    return None


def _build_execution_manifest(
    payload: dict[str, Any],
    *,
    registry_path: Path,
    ledger_path: Path,
    run_dir: Path | None,
) -> ExecutionManifestV1:
    existing = payload.get("execution_manifest")
    if isinstance(existing, ExecutionManifestV1):
        return existing
    if isinstance(existing, dict):
        try:
            return ExecutionManifestV1.model_validate(existing)
        except Exception:
            pass

    script_path = loop_controller_script_path()
    return ExecutionManifestV1(
        execution_mode=ExecutionModeV1.python_script,
        summary=_text(payload.get("summary"))
        or "Predictive FC native bundle emitted by the loop controller",
        entrypoints=ExecutionEntrypointsV1(python_script=str(script_path)),
        runtime=ExecutionRuntimeV1(
            python_version=sys.version.split()[0],
            docker_supported=False,
            neurodesk_supported=False,
        ),
        inputs=[
            ExecutionIORefV1(
                name="registry_path",
                required=True,
                description="Predictive registry input",
                path=str(registry_path),
            ),
            ExecutionIORefV1(
                name="ledger_path",
                required=True,
                description="Predictive experiments ledger input",
                path=str(ledger_path),
            ),
        ],
        outputs=[
            ExecutionIORefV1(
                name="observation",
                required=True,
                description="Canonical observation document",
                path="observation.json",
            ),
            ExecutionIORefV1(
                name="analysis_bundle",
                required=True,
                description="Canonical analysis bundle document",
                path="analysis_bundle.json",
            ),
        ],
        parameters={
            **dict(payload.get("parameters") or {}),
            "registry_path": str(registry_path),
            "ledger_path": str(ledger_path),
        },
        repro=ExecutionReproV1(
            working_directory=str(run_dir or registry_path.parent),
            command=(
                f"{sys.executable} {script_path} "
                f"--registry {registry_path} --ledger {ledger_path}"
            ),
        ),
    )


def _build_observation_spec(
    payload: dict[str, Any],
    *,
    registry_path: Path,
    ledger_path: Path,
    run_dir: Path | None,
) -> ObservationSpecV1:
    existing = payload.get("observation")
    if isinstance(existing, ObservationSpecV1):
        return existing
    if isinstance(existing, dict):
        try:
            return ObservationSpecV1.model_validate(existing)
        except Exception:
            pass

    job_id = (
        _text(payload.get("job_id"))
        or _text(payload.get("run_id"))
        or registry_path.stem
        or ledger_path.stem
        or "predictive"
    )
    run_id = _text(payload.get("run_id")) or job_id
    state = _text(payload.get("state")) or _text(payload.get("status")) or "succeeded"
    provenance = _dict(payload.get("provenance")) or None
    diagnostics_summary = _dict(payload.get("diagnostics_summary")) or None

    return ObservationSpecV1(
        job_id=job_id,
        run_id=run_id,
        state=state,
        run_dir=str(run_dir) if run_dir is not None else None,
        files=ObservationFiles(
            observation_json="observation.json",
            provenance_json="provenance.json" if provenance is not None else None,
            trace_jsonl=_text(payload.get("trace_jsonl")),
            reward_breakdown_json=_text(payload.get("reward_breakdown_json")),
            research_episode_json=_text(payload.get("research_episode_json")),
            option_set_json=_text(payload.get("option_set_json")),
            evidence_gate_json=_text(payload.get("evidence_gate_json")),
            commitment_json=_text(payload.get("commitment_json")),
            claim_report_json=_text(payload.get("claim_report_json")),
            claim_update_json=_text(payload.get("claim_update_json")),
            rm_pairwise_redacted_json=_text(payload.get("rm_pairwise_redacted_json")),
            rm_pairwise_raw_json=_text(payload.get("rm_pairwise_raw_json")),
            rm_process_redacted_json=_text(payload.get("rm_process_redacted_json")),
            rm_process_raw_json=_text(payload.get("rm_process_raw_json")),
        ),
        run_card=_dict(payload.get("run_card")) or payload.get("run_card"),
        provenance=provenance,
        artifacts=list(payload.get("artifacts") or []),
        steps=list(payload.get("steps") or []),
        diagnostics_summary=diagnostics_summary,
    )


def _build_analysis_bundle(
    payload: dict[str, Any],
    *,
    registry_path: Path,
    ledger_path: Path,
    run_dir: Path | None,
    observation: ObservationSpecV1,
    execution_manifest: ExecutionManifestV1,
) -> AnalysisBundleV1:
    existing = payload.get("analysis_bundle")
    if isinstance(existing, AnalysisBundleV1):
        return existing
    if isinstance(existing, dict):
        try:
            return AnalysisBundleV1.model_validate(existing)
        except Exception:
            pass

    generated_at = _text(payload.get("generated_at")) or _utc_now()
    analysis_manifest = payload.get("analysis_manifest")
    if analysis_manifest is None:
        analysis_manifest = payload.get("next_campaign")

    bundle = AnalysisBundleV1(
        job_id=observation.job_id,
        run_id=observation.run_id,
        state=observation.state,
        run_dir=str(run_dir) if run_dir is not None else observation.run_dir,
        generated_at=generated_at,
        files=AnalysisBundleFiles(
            observation_json="observation.json",
            execution_manifest_json="execution_manifest.json",
            provenance_json=(
                "provenance.json" if payload.get("provenance") is not None else None
            ),
        ),
        observation=observation.model_dump(exclude_none=True),
        execution_manifest=execution_manifest,
        analysis_manifest=_dict(analysis_manifest) if analysis_manifest else None,
        run_card=_dict(payload.get("run_card")) or payload.get("run_card"),
        provenance=_dict(payload.get("provenance")) or None,
        artifacts=list(payload.get("artifacts") or []),
        policy_snapshot={
            "source": "predictive_loop_controller",
            "registry_path": str(registry_path),
            "ledger_path": str(ledger_path),
        },
    )
    review_context = build_native_review_context(
        bundle.model_dump(exclude_none=True),
        observation=observation.model_dump(exclude_none=True),
        execution_manifest=execution_manifest.model_dump(exclude_none=True),
    )
    if review_context:
        bundle.review_context = review_context
        if isinstance(bundle.run_card, dict):
            bundle.run_card["review_context"] = dict(review_context)
        if isinstance(observation.run_card, dict):
            observation.run_card["review_context"] = dict(review_context)
            bundle.observation = observation.model_dump(exclude_none=True)
    return bundle


def _emit_native_bundle(
    module: Any,
    payload: dict[str, Any],
    *,
    registry_path: Path,
    ledger_path: Path,
) -> list[Path]:
    for helper_name in NATIVE_BUNDLE_HELPER_NAMES:
        helper = getattr(module, helper_name, None)
        if callable(helper):
            result = helper(
                payload,
                registry_path=registry_path,
                ledger_path=ledger_path,
            )
            if isinstance(result, list):
                return [Path(item) for item in result if item]
            return []

    run_dir = _resolve_native_bundle_run_dir(payload)
    if run_dir is None:
        return []

    observation = _build_observation_spec(
        payload,
        registry_path=registry_path,
        ledger_path=ledger_path,
        run_dir=run_dir,
    )
    execution_manifest = _build_execution_manifest(
        payload,
        registry_path=registry_path,
        ledger_path=ledger_path,
        run_dir=run_dir,
    )
    analysis_bundle = _build_analysis_bundle(
        payload,
        registry_path=registry_path,
        ledger_path=ledger_path,
        run_dir=run_dir,
        observation=observation,
        execution_manifest=execution_manifest,
    )

    run_dir.mkdir(parents=True, exist_ok=True)
    emitted_paths = [
        run_dir / "execution_manifest.json",
        run_dir / "observation.json",
        run_dir / "analysis_bundle.json",
    ]
    _write_json(emitted_paths[0], execution_manifest)
    _write_json(emitted_paths[1], observation)
    _write_json(emitted_paths[2], analysis_bundle)
    return emitted_paths


def _apply_needs_exploration_gate(
    payload: dict[str, Any],
    ledger_path: Path,
) -> dict[str, Any]:
    next_campaign = dict(payload.get("next_campaign") or {})
    if next_campaign.get("campaign_type") != "lane_b_weak_target_term_discovery":
        return payload

    target_plans = dict(next_campaign.get("target_plans") or {})
    if not target_plans:
        return payload

    checkpoint = dict(next_campaign.get("self_critique_checkpoint") or {})
    gates = dict(checkpoint.get("gates") or {})
    exploratory_requirements: dict[str, dict[str, Any]] = {}
    rows = _load_ledger_rows(ledger_path)
    needs_exploration_targets: list[str] = []

    for target, plan in target_plans.items():
        leader_term = plan.get("leader_term_index")
        comparator_term = plan.get("comparator_term_index")
        exploratory_terms: set[int] = set()
        for row in rows:
            if row.get("phase") != WEAK_TARGET_PHASE:
                continue
            if row.get("config", {}).get("target") != target:
                continue
            term_index = term_index_of(row)
            if term_index is None:
                continue
            if term_index in {leader_term, comparator_term}:
                continue
            exploratory_terms.add(term_index)
        exploratory_requirements[target] = {
            "pass": len(exploratory_terms) >= 1,
            "exploratory_terms": sorted(exploratory_terms),
            "required_next_step": (
                "run_exploratory_follow_up"
                if len(exploratory_terms) < 1
                else "exploration_satisfied"
            ),
        }
        if len(exploratory_terms) < 1:
            needs_exploration_targets.append(target)

    gates["exploration_follow_up"] = {
        "target_requirements": exploratory_requirements,
        "failing_targets": needs_exploration_targets,
        "pass": not needs_exploration_targets,
    }
    checkpoint["gates"] = gates
    next_campaign["self_critique_checkpoint"] = checkpoint

    if needs_exploration_targets:
        reasoning = list(next_campaign.get("reasoning") or [])
        reasoning.append(
            "At least one weak target still lacks a formal exploratory follow-up arm, "
            "so the controller must open a needs_exploration campaign before report generation."
        )
        for target in needs_exploration_targets:
            requirement = exploratory_requirements[target]
            reasoning.append(
                f"{target}: exploratory_terms={requirement['exploratory_terms']}; "
                "required_next_step=run_exploratory_follow_up."
            )
        next_campaign["campaign_type"] = GateVerdict.NEEDS_EXPLORATION.value
        next_campaign["campaign_name"] = "lane_b_weak_target_needs_exploration"
        next_campaign["reasoning"] = reasoning
        next_campaign["batch_size_recommended"] = 0
        next_campaign["recommended_first_batch"] = []
        payload = dict(payload)
        payload["next_campaign"] = next_campaign
    return payload


def loop_controller_script_path(
    *,
    project_root: Path | str | None = None,
    implementation_path: Path | str | None = None,
) -> Path:
    return legacy_project_script_path(
        "predictive",
        LEGACY_SCRIPT,
        project_root=project_root,
        implementation_path=implementation_path,
    )


def legacy_script_path(*, project_root: Path | str | None = None) -> Path:
    return loop_controller_script_path(project_root=project_root)


def load_implementation(
    *,
    project_root: Path | str | None = None,
    implementation_path: Path | str | None = None,
):
    return load_legacy_project_module(
        "predictive",
        "brain_researcher_predictive_loop_controller_legacy",
        LEGACY_SCRIPT,
        project_root=project_root,
        implementation_path=implementation_path,
    )


def load_legacy_module(*, project_root: Path | str | None = None):
    return load_implementation(project_root=project_root)


def build_payload(
    registry_path: Path,
    ledger_path: Path,
    *,
    project_root: Path | str | None = None,
    implementation_path: Path | str | None = None,
) -> dict[str, Any]:
    module = load_implementation(
        project_root=project_root,
        implementation_path=implementation_path,
    )
    payload = module.build_payload(registry_path, ledger_path)
    payload = _apply_needs_exploration_gate(
        payload,
        Path(ledger_path).expanduser().resolve(),
    )
    _emit_native_bundle(
        module,
        payload,
        registry_path=Path(registry_path).expanduser().resolve(),
        ledger_path=Path(ledger_path).expanduser().resolve(),
    )
    return payload


def render_markdown(
    payload: dict[str, Any],
    *,
    project_root: Path | str | None = None,
    implementation_path: Path | str | None = None,
) -> str:
    module = load_implementation(
        project_root=project_root,
        implementation_path=implementation_path,
    )
    return module.render_markdown(payload)


def main(
    argv: Sequence[str] | None = None,
    *,
    project_root: Path | str | None = None,
    implementation_path: Path | str | None = None,
) -> int:
    module = load_implementation(
        project_root=project_root,
        implementation_path=implementation_path,
    )
    result = run_legacy_main(
        module,
        script_path=loop_controller_script_path(
            project_root=project_root,
            implementation_path=implementation_path,
        ),
        argv=argv,
    )
    return 0 if result is None else int(result)


__all__ = [
    "build_payload",
    "legacy_script_path",
    "load_implementation",
    "load_legacy_module",
    "loop_controller_script_path",
    "main",
    "render_markdown",
]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
