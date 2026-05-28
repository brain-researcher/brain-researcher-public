"""Build a durable repo-repair context artifact for coding agents.

This module turns autoresearch state into an explicit, agent-readable snapshot of:
- recent recurring failure motifs
- absorbed-upstream repair patterns
- HARNESS task coverage
- golden repair principles
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # pragma: no cover - optional import exercised in tests
    import yaml
except Exception:  # pragma: no cover
    yaml = None

from brain_researcher.services.agent.autoresearch import (
    DEFAULT_BENCHMARK_ROOT,
    MOTIF_FAMILIES,
    get_autoresearch_root,
    load_canary_scaffold_task_ids,
    load_canary_task_ids,
    load_failure_motifs,
    load_motif_canary_task_ids,
    load_motif_scaffold_task_ids,
    load_motif_slice_task_ids,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_GOLDEN_PRINCIPLES_PATH = (
    REPO_ROOT / "configs" / "codegen" / "autoresearch_golden_principles.yaml"
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _write_text(path, json.dumps(payload, indent=2, ensure_ascii=False))


def _load_yaml(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to load repo repair context configs")
    if not path.exists():
        raise FileNotFoundError(path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Expected mapping at {path}")
    return payload


def load_golden_principles(
    *,
    path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Load the golden repair principles registry."""

    config_path = (
        Path(path).expanduser().resolve()
        if path is not None
        else DEFAULT_GOLDEN_PRINCIPLES_PATH
    )
    payload = _load_yaml(config_path)
    raw = payload.get("principles")
    if not isinstance(raw, list):
        raise ValueError(f"principles must be a list in {config_path}")
    principles: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        principle_id = str(item.get("id") or "").strip()
        title = str(item.get("title") or "").strip()
        if not principle_id or not title:
            continue
        principles.append(
            {
                "id": principle_id,
                "title": title,
                "rule": str(item.get("rule") or "").strip(),
                "why_it_exists": str(item.get("why_it_exists") or "").strip(),
                "failure_modes": [
                    str(value).strip()
                    for value in list(item.get("failure_modes") or [])
                    if str(value).strip()
                ],
                "applies_to": [
                    str(value).strip()
                    for value in list(item.get("applies_to") or [])
                    if str(value).strip()
                ],
            }
        )
    return principles


def _collect_absorbed_upstream_candidates(
    autoresearch_root: Path,
    *,
    top_n: int,
) -> list[dict[str, Any]]:
    candidate_root = autoresearch_root / "candidates"
    validation_root = autoresearch_root / "validations"
    rows: list[dict[str, Any]] = []
    if not candidate_root.exists():
        return rows
    for child in sorted(candidate_root.iterdir()):
        if not child.is_dir():
            continue
        candidate_payload = _read_json(child / "candidate_fix.json")
        if not isinstance(candidate_payload, dict):
            continue
        validation_payload = _read_json(validation_root / child.name / "validation_report.json") or {}
        status = str(candidate_payload.get("status") or "").strip()
        verdict = str(validation_payload.get("gate_verdict") or "").strip()
        if status != "absorbed_upstream" and verdict != "absorbed_upstream":
            continue
        patch_legibility = (
            validation_payload.get("patch_legibility")
            if isinstance(validation_payload.get("patch_legibility"), dict)
            else {}
        )
        rows.append(
            {
                "candidate_id": child.name,
                "motif_family": str(candidate_payload.get("motif_family") or "").strip(),
                "target_surface": str(candidate_payload.get("target_surface") or "").strip(),
                "allowed_paths": [
                    str(value).strip()
                    for value in list(candidate_payload.get("allowed_paths") or [])
                    if str(value).strip()
                ],
                "status_explanation": str(
                    validation_payload.get("status_explanation") or ""
                ).strip(),
                "recommended_action": str(
                    validation_payload.get("recommended_action") or ""
                ).strip(),
                "patch_legibility_score": float(
                    patch_legibility.get("score") or 0.0
                ),
                "patch_legibility_band": str(
                    patch_legibility.get("band") or "unknown"
                ),
                "touched_paths": [
                    str(value).strip()
                    for value in list(validation_payload.get("touched_paths") or [])
                    if str(value).strip()
                ],
                "created_at": str(candidate_payload.get("created_at") or "").strip(),
            }
        )
    rows.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return rows[:top_n]


def _build_harness_coverage(
    *,
    benchmark_root: Path,
) -> dict[str, Any]:
    motif_entries: list[dict[str, Any]] = []
    all_harness_tasks: set[str] = set()
    all_scaffold_harness_tasks: set[str] = set()
    motifs_with_harness: list[str] = []
    motifs_without_harness: list[str] = []
    motifs_with_scaffold: list[str] = []

    for motif_family in MOTIF_FAMILIES:
        try:
            task_ids = load_motif_slice_task_ids(
                motif_family,
                benchmark_root=benchmark_root,
            )
        except Exception:
            task_ids = []
        try:
            canary_task_ids = load_motif_canary_task_ids(
                motif_family,
                benchmark_root=benchmark_root,
            )
        except Exception:
            canary_task_ids = []
        try:
            scaffold_task_ids = load_motif_scaffold_task_ids(
                motif_family,
                benchmark_root=benchmark_root,
            )
        except Exception:
            scaffold_task_ids = []
        harness_task_ids = sorted(
            {
                task_id
                for task_id in [*task_ids, *canary_task_ids]
                if str(task_id).strip().upper().startswith("HARNESS-")
            }
        )
        scaffold_harness_task_ids = sorted(
            {
                task_id
                for task_id in scaffold_task_ids
                if str(task_id).strip().upper().startswith("HARNESS-")
            }
        )
        if harness_task_ids:
            motifs_with_harness.append(motif_family)
            all_harness_tasks.update(harness_task_ids)
        else:
            motifs_without_harness.append(motif_family)
        if scaffold_harness_task_ids:
            motifs_with_scaffold.append(motif_family)
            all_scaffold_harness_tasks.update(scaffold_harness_task_ids)
        motif_entries.append(
            {
                "motif_family": motif_family,
                "task_ids": task_ids,
                "canary_task_ids": canary_task_ids,
                "scaffold_task_ids": scaffold_task_ids,
                "harness_task_ids": harness_task_ids,
                "scaffold_harness_task_ids": scaffold_harness_task_ids,
                "has_native_harness": bool(harness_task_ids),
                "has_draft_scaffold": bool(scaffold_harness_task_ids),
            }
        )

    try:
        global_canary = load_canary_task_ids(benchmark_root=benchmark_root)
    except Exception:
        global_canary = []
    try:
        global_scaffold = load_canary_scaffold_task_ids(benchmark_root=benchmark_root)
    except Exception:
        global_scaffold = []
    all_harness_tasks.update(
        task_id
        for task_id in global_canary
        if str(task_id).strip().upper().startswith("HARNESS-")
    )
    all_scaffold_harness_tasks.update(
        task_id
        for task_id in global_scaffold
        if str(task_id).strip().upper().startswith("HARNESS-")
    )
    return {
        "motif_entries": motif_entries,
        "all_harness_tasks": sorted(all_harness_tasks),
        "all_scaffold_harness_tasks": sorted(all_scaffold_harness_tasks),
        "global_canary_task_ids": global_canary,
        "global_scaffold_task_ids": global_scaffold,
        "motifs_with_native_harness": sorted(motifs_with_harness),
        "motifs_without_native_harness": sorted(motifs_without_harness),
        "motifs_with_draft_scaffold": sorted(motifs_with_scaffold),
    }


def _build_hot_surfaces(
    motifs: list[Any],
    absorbed_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for card in motifs:
        surface = str(getattr(card, "suspected_surface", "") or "").strip()
        if surface:
            counter[surface] += int(getattr(card, "frequency", 0) or 0)
    for row in absorbed_candidates:
        surface = str(row.get("target_surface") or "").strip()
        if surface:
            counter[surface] += 1
    return [
        {"surface": surface, "weight": weight}
        for surface, weight in counter.most_common(8)
    ]


def _render_repo_repair_context_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    motifs = payload.get("recent_failure_motifs") or []
    absorbed = payload.get("absorbed_upstream_candidates") or []
    harness = payload.get("harness_coverage") or {}
    principles = payload.get("golden_principles") or []
    hot_surfaces = payload.get("hot_surfaces") or []

    lines = [
        "# Repo Repair Context",
        "",
        f"- Generated at: `{payload.get('generated_at')}`",
        f"- Failure motifs loaded: `{summary.get('failure_motif_count', 0)}`",
        f"- Absorbed-upstream candidates: `{summary.get('absorbed_upstream_candidate_count', 0)}`",
        f"- HARNESS tasks known: `{summary.get('harness_task_count', 0)}`",
        f"- Golden principles: `{summary.get('golden_principle_count', 0)}`",
        "",
        "## Hot Surfaces",
    ]
    if hot_surfaces:
        for row in hot_surfaces:
            lines.append(f"- `{row.get('surface')}` (weight `{row.get('weight')}`)")
    else:
        lines.append("- none")

    lines.extend(["", "## Recent Failure Motifs"])
    if motifs:
        for row in motifs:
            lines.append(
                f"- `{row.get('motif_family')}` freq=`{row.get('frequency')}` "
                f"surface=`{row.get('suspected_surface')}`"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Absorbed-Upstream Patterns"])
    if absorbed:
        for row in absorbed:
            lines.append(
                f"- `{row.get('candidate_id')}` motif=`{row.get('motif_family')}` "
                f"surface=`{row.get('target_surface')}` "
                f"legibility=`{row.get('patch_legibility_band')}`"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## HARNESS Coverage"])
    motifs_without = harness.get("motifs_without_native_harness") or []
    draft_scaffolds = harness.get("all_scaffold_harness_tasks") or []
    lines.append(
        f"- Native HARNESS motifs: `{len(harness.get('motifs_with_native_harness') or [])}`"
    )
    lines.append(f"- Native HARNESS tasks: `{', '.join(harness.get('all_harness_tasks') or []) or 'none'}`")
    lines.append(
        f"- Draft scaffold HARNESS tasks: "
        f"`{', '.join(draft_scaffolds) or 'none'}`"
    )
    lines.append(
        f"- Motifs still without native HARNESS: "
        f"`{', '.join(motifs_without) or 'none'}`"
    )

    lines.extend(["", "## Golden Principles"])
    for row in principles:
        lines.append(f"- `{row.get('id')}`: {row.get('title')}")

    return "\n".join(lines).strip() + "\n"


def generate_repo_repair_context(
    *,
    top_n: int = 8,
    persist: bool = True,
    autoresearch_root: Path | str | None = None,
    benchmark_root: Path | str | None = None,
    golden_principles_path: Path | str | None = None,
) -> dict[str, Any]:
    """Build a repo repair context artifact from autoresearch state."""

    state_root = get_autoresearch_root(autoresearch_root)
    benchmark_root_path = (
        Path(benchmark_root).expanduser().resolve()
        if benchmark_root is not None
        else DEFAULT_BENCHMARK_ROOT
    )
    golden_path = (
        Path(golden_principles_path).expanduser().resolve()
        if golden_principles_path is not None
        else DEFAULT_GOLDEN_PRINCIPLES_PATH
    )
    warnings: list[str] = []

    try:
        motifs = load_failure_motifs(autoresearch_root=state_root)
    except Exception as exc:
        warnings.append(f"failure_motifs_unavailable: {exc}")
        motifs = []

    absorbed_candidates = _collect_absorbed_upstream_candidates(
        state_root,
        top_n=top_n,
    )

    try:
        harness_coverage = _build_harness_coverage(benchmark_root=benchmark_root_path)
    except Exception as exc:
        warnings.append(f"harness_coverage_unavailable: {exc}")
        harness_coverage = {
            "motif_entries": [],
            "all_harness_tasks": [],
            "global_canary_task_ids": [],
            "motifs_with_native_harness": [],
            "motifs_without_native_harness": list(MOTIF_FAMILIES),
        }

    try:
        golden_principles = load_golden_principles(path=golden_path)
    except Exception as exc:
        warnings.append(f"golden_principles_unavailable: {exc}")
        golden_principles = []

    recent_failure_motifs = [
        {
            "motif_family": str(card.motif_family),
            "severity": str(card.severity),
            "frequency": int(card.frequency),
            "suspected_surface": str(card.suspected_surface),
            "affected_tools_workflows": list(card.affected_tools_workflows),
            "representative_runs": list(card.representative_runs),
            "recommended_benchmark_slice_id": str(card.recommended_benchmark_slice_id),
        }
        for card in motifs[:top_n]
    ]

    payload = {
        "generated_at": _utc_iso(),
        "top_n": int(top_n),
        "source_paths": {
            "autoresearch_root": str(state_root),
            "benchmark_root": str(benchmark_root_path),
            "golden_principles_path": str(golden_path),
            "failure_motifs_latest": str(
                state_root / "failure_motifs" / "failure_motifs_latest.jsonl"
            ),
        },
        "summary": {
            "failure_motif_count": len(motifs),
            "absorbed_upstream_candidate_count": len(absorbed_candidates),
            "harness_task_count": len(harness_coverage.get("all_harness_tasks") or []),
            "golden_principle_count": len(golden_principles),
        },
        "recent_failure_motifs": recent_failure_motifs,
        "absorbed_upstream_candidates": absorbed_candidates,
        "harness_coverage": harness_coverage,
        "golden_principles": golden_principles,
        "hot_surfaces": _build_hot_surfaces(motifs, absorbed_candidates),
        "warnings": sorted({str(item) for item in warnings if str(item).strip()}),
    }

    markdown = _render_repo_repair_context_markdown(payload)
    persisted_files: list[str] = []
    if persist:
        output_root = state_root / "repo_repair_context"
        latest_json = output_root / "repo_repair_context_latest.json"
        latest_md = output_root / "repo_repair_context_latest.md"
        _write_json(latest_json, payload)
        _write_text(latest_md, markdown)
        persisted_files = [str(latest_json), str(latest_md)]

    return {
        "ok": True,
        "repo_repair_context": payload,
        "markdown": markdown,
        "persisted_files": persisted_files,
        "warnings": payload["warnings"],
    }


__all__ = [
    "DEFAULT_GOLDEN_PRINCIPLES_PATH",
    "generate_repo_repair_context",
    "load_golden_principles",
]
