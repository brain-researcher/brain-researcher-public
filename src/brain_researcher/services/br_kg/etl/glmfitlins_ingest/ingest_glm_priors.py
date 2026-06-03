#!/usr/bin/env python3
"""Ingest GLM design priors into BR-KG from statsmodel_specs.

This script aggregates design choices (HRF basis, confounds, high-pass filter)
from BIDS Stats Models and writes them as GLMDesignPrior nodes in the KG.

Defaults mirror the GLMPriorsTool fallback roots:
  - data/openneuro_glmfitlins
  - external/openneuro_glmfitlins

Example:
  python ingest_glm_priors.py --scope all
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from brain_researcher.core.multiverse.confounds import (
    CONF_FAMILY_AXES,
    extract_confounds_family_flags,
)
from brain_researcher.services.br_kg.graph.neo4j_utils import require_neo4j_db

logger = logging.getLogger(__name__)


def _slug(text: str) -> str:
    clean = re.sub(r"[^a-z0-9_-]+", "_", (text or "").strip().lower())
    return re.sub(r"_+", "_", clean).strip("_") or "unknown"


def _extract_tasks(model: dict) -> list[str]:
    task_field = model.get("Input", {}).get("task", [])
    if isinstance(task_field, str):
        tasks = [task_field]
    elif isinstance(task_field, list):
        tasks = [str(t) for t in task_field if t]
    else:
        tasks = []
    return [t.strip() for t in tasks if isinstance(t, str) and t.strip()]


def _infer_tasks_from_path(path: Path) -> list[str]:
    match = re.search(r"task-([A-Za-z0-9_-]+)", path.name)
    if match:
        return [match.group(1)]
    return []


def _find_run_node(model: dict) -> dict | None:
    nodes = model.get("Nodes") or model.get("Steps") or []
    for node in nodes:
        level = str(node.get("Level", "")).lower()
        if level == "run":
            return node
    return None


def _extract_design_choices(model: dict) -> tuple[str, str, str | None]:
    run_node = _find_run_node(model)
    if not run_node:
        return "canonical", "6mot", None

    # HRF basis
    convolve = None
    for inst in run_node.get("Transformations", {}).get("Instructions", []):
        if str(inst.get("Name", "")).lower() == "convolve":
            convolve = inst
            break
    hrf = "canonical"
    if convolve:
        model_name = str(convolve.get("Model", "")).lower()
        deriv = bool(convolve.get("Derivative", False))
        if model_name == "fir" or model_name.startswith("fir"):
            hrf = "fir"
        elif deriv:
            hrf = "derivs"

    # Confounds
    x = run_node.get("Model", {}).get("X", [])
    conf_mode = "6mot"
    x_str = " ".join(map(str, x))
    if "derivative1" in x_str or "power2" in x_str:
        conf_mode = "24mot"
    if "a_comp_cor" in x_str:
        conf_mode = conf_mode + "_acompcor"

    # High-pass
    hp = run_node.get("Model", {}).get("Options", {}).get("HighPassFilterCutoff")
    hp_str = str(hp) if hp is not None else None

    return hrf, conf_mode, hp_str


def _extract_model_x_terms(model: dict) -> list[str]:
    run_node = _find_run_node(model)
    if not run_node:
        return []
    model_node = run_node.get("Model", {})
    x_terms = model_node.get("X", [])
    out: list[str] = []
    for term in x_terms:
        if isinstance(term, str):
            out.append(term.strip())
    return out


def _update_presence_counts(
    counts: dict[str, dict[str, int]], axis: str, present: bool
) -> None:
    bucket = counts.setdefault(axis, {})
    key = "present" if present else "absent"
    bucket[key] = bucket.get(key, 0) + 1


def _init_counts() -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {
        "hrf_basis": {},
        "confounds": {},
        "high_pass": {},
        "_scanned": {"n": 0},
        "_coverage": {},
    }
    for axis in ("hrf_basis", "confounds", "high_pass", *CONF_FAMILY_AXES):
        counts["_coverage"][axis] = 0
    for axis in CONF_FAMILY_AXES:
        counts[axis] = {}
    return counts


def _increment_coverage(counts: dict[str, dict[str, int]], axis: str) -> None:
    coverage = counts.setdefault("_coverage", {})
    coverage[axis] = coverage.get(axis, 0) + 1


def _compute_coverage(counts: dict[str, dict[str, int]]) -> dict[str, float]:
    scanned = counts.get("_scanned", {}).get("n", 0)
    if scanned <= 0:
        return {}
    coverage = counts.get("_coverage", {})
    return {axis: (observed / scanned) for axis, observed in coverage.items()}


def _update_counts_from_model(
    counts: dict[str, dict[str, int]],
    *,
    hrf: str,
    conf: str,
    hp: str | None,
    family_flags: dict[str, bool],
    observed_hrf: bool,
    observed_confounds: bool,
    observed_high_pass: bool,
) -> None:
    if observed_hrf:
        counts["hrf_basis"][hrf] = counts["hrf_basis"].get(hrf, 0) + 1
        _increment_coverage(counts, "hrf_basis")
    if observed_confounds:
        counts["confounds"][conf] = counts["confounds"].get(conf, 0) + 1
        _increment_coverage(counts, "confounds")
        for axis in CONF_FAMILY_AXES:
            _increment_coverage(counts, axis)
        for axis, present in family_flags.items():
            _update_presence_counts(counts, axis, present)
    if observed_high_pass and hp:
        counts["high_pass"][hp] = counts["high_pass"].get(hp, 0) + 1
        _increment_coverage(counts, "high_pass")


def _default_roots(repo_root: Path) -> list[Path]:
    return [
        repo_root / "data" / "openneuro_glmfitlins",
        repo_root / "external" / "openneuro_glmfitlins",
    ]


def _statsmodel_dirs(roots: Iterable[Path]) -> list[Path]:
    dirs: list[Path] = []
    for root in roots:
        stats_dir = root / "statsmodel_specs"
        if stats_dir.exists():
            dirs.append(stats_dir)
        elif root.exists():
            dirs.append(root)
    return dirs


def _iter_specs(
    roots: Iterable[Path],
    *,
    study_id: str | None,
    task_filter: str | None,
    max_results: int,
):
    scanned = 0
    task_filter_l = task_filter.lower() if task_filter else None
    for stats_dir in _statsmodel_dirs(roots):
        if not stats_dir.exists():
            continue
        glob = "*_specs.json" if not study_id else f"{study_id}/*_specs.json"
        for path in stats_dir.rglob(glob):
            if scanned >= max_results:
                return
            try:
                model = json.loads(path.read_text())
            except Exception:
                continue
            tasks = _extract_tasks(model)
            if not tasks:
                tasks = _infer_tasks_from_path(path)
            if task_filter_l:
                tasks = [t for t in tasks if t.lower() == task_filter_l]
                if not tasks:
                    continue
            dataset_id = path.parent.name if path.parent else ""
            yield dataset_id, tasks, model
            scanned += 1


def _normalize_counts(counts: dict[str, int]) -> dict[str, float]:
    total = sum(counts.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in counts.items()}


def _get_db() -> Any:
    return require_neo4j_db(preload_cache=False)


def _write_prior_node(
    db: Any,
    *,
    node_id: str,
    task: str,
    dataset_id: str | None,
    priors: dict[str, dict[str, float]],
    scanned: int,
    source: str,
    support: dict[str, int],
    coverage: dict[str, float],
) -> str:
    props: dict[str, Any] = {
        "id": node_id,
        "task": task,
        "dataset_id": dataset_id,
        "hrf_basis": priors.get("hrf_basis", {}),
        "confounds": priors.get("confounds", {}),
        "high_pass": priors.get("high_pass", {}),
        "axes": priors,
        "n_specs": scanned,
        "support": support,
        "coverage": coverage,
        "source": source,
    }
    return db.create_node(labels=["GLMDesignPrior"], properties=props, node_id=node_id)


def _find_dataset_node(db: Any, dataset_id: str) -> str | None:
    if not dataset_id:
        return None
    for key in ("dataset_id", "id", "name"):
        try:
            hits = db.find_nodes(labels="Dataset", properties={key: dataset_id})
        except Exception:
            hits = []
        if hits:
            return str(hits[0][0])
    return None


def _find_task_nodes(db: Any, task: str, dataset_id: str | None) -> list[str]:
    if not task:
        return []
    hits: list[str] = []
    if dataset_id:
        for label in ("TaskSpec", "Task"):
            try:
                rows = db.find_nodes(
                    labels=label, properties={"name": task, "dataset": dataset_id}
                )
            except Exception:
                rows = []
            hits.extend([str(r[0]) for r in rows])
    for label in ("TaskSpec", "Task"):
        try:
            rows = db.find_nodes(labels=label, properties={"name": task})
        except Exception:
            rows = []
        hits.extend([str(r[0]) for r in rows])
    # De-duplicate while preserving order
    seen = set()
    ordered = []
    for node_id in hits:
        if node_id in seen:
            continue
        seen.add(node_id)
        ordered.append(node_id)
    return ordered


def _link_prior(
    db: Any,
    *,
    prior_id: str,
    dataset_id: str | None,
    task: str,
) -> None:
    if dataset_id:
        dataset_node = _find_dataset_node(db, dataset_id)
        if dataset_node:
            db.create_relationship(
                start_node=dataset_node,
                end_node=prior_id,
                rel_type="HAS_GLM_PRIOR",
                properties={"scope": "dataset"},
            )
    for task_node in _find_task_nodes(db, task, dataset_id):
        db.create_relationship(
            start_node=task_node,
            end_node=prior_id,
            rel_type="HAS_GLM_PRIOR",
            properties={"scope": "task", "dataset_id": dataset_id},
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest GLM design priors into BR-KG")
    parser.add_argument(
        "--root", action="append", help="OpenNeuro GLM root (contains statsmodel_specs)"
    )
    parser.add_argument("--study-id", help="Dataset ID to filter (e.g., ds000114)")
    parser.add_argument("--task", help="Task label to filter (e.g., fingerfootlips)")
    parser.add_argument(
        "--scope",
        choices=["dataset", "task", "global", "all"],
        default="dataset",
        help="Aggregation scope (default: dataset)",
    )
    parser.add_argument(
        "--max-results", type=int, default=20000, help="Max specs to scan"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Compute priors without writing to KG"
    )

    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[6]
    roots = [Path(r) for r in (args.root or [])]
    if not roots:
        roots = _default_roots(repo_root)

    dataset_counts: dict[tuple[str, str], dict[str, dict[str, int]]] = {}
    task_counts: dict[str, dict[str, dict[str, int]]] = {}
    task_support_datasets: dict[str, set[str]] = {}
    global_counts: dict[str, dict[str, int]] = _init_counts()
    all_datasets: set[str] = set()
    all_tasks: set[str] = set()
    scanned_total = 0

    for dataset_id, tasks, model in _iter_specs(
        roots,
        study_id=args.study_id,
        task_filter=args.task,
        max_results=args.max_results,
    ):
        hrf, conf, hp = _extract_design_choices(model)
        run_node = _find_run_node(model)
        observed_hrf = False
        observed_confounds = False
        observed_high_pass = False
        if run_node:
            observed_confounds = "X" in (run_node.get("Model") or {})
            for inst in run_node.get("Transformations", {}).get("Instructions", []):
                if str(inst.get("Name", "")).lower() == "convolve":
                    observed_hrf = True
                    break
            observed_high_pass = (
                run_node.get("Model", {}).get("Options", {}).get("HighPassFilterCutoff")
                is not None
            )

        x_terms = _extract_model_x_terms(model) if observed_confounds else []
        family_flags = (
            extract_confounds_family_flags(x_terms)
            if observed_confounds
            else dict.fromkeys(CONF_FAMILY_AXES, False)
        )

        all_datasets.add(dataset_id)
        for task in tasks:
            all_tasks.add(task)
            task_support_datasets.setdefault(task, set()).add(dataset_id)

            key = (dataset_id, task)
            bucket = dataset_counts.setdefault(key, _init_counts())
            _update_counts_from_model(
                bucket,
                hrf=hrf,
                conf=conf,
                hp=hp,
                family_flags=family_flags,
                observed_hrf=observed_hrf,
                observed_confounds=observed_confounds,
                observed_high_pass=observed_high_pass,
            )
            bucket["_scanned"]["n"] += 1

            task_bucket = task_counts.setdefault(task, _init_counts())
            _update_counts_from_model(
                task_bucket,
                hrf=hrf,
                conf=conf,
                hp=hp,
                family_flags=family_flags,
                observed_hrf=observed_hrf,
                observed_confounds=observed_confounds,
                observed_high_pass=observed_high_pass,
            )
            task_bucket["_scanned"]["n"] += 1

        _update_counts_from_model(
            global_counts,
            hrf=hrf,
            conf=conf,
            hp=hp,
            family_flags=family_flags,
            observed_hrf=observed_hrf,
            observed_confounds=observed_confounds,
            observed_high_pass=observed_high_pass,
        )
        global_counts["_scanned"]["n"] += 1
        scanned_total += 1

    logger.info("Scanned %d statsmodel specs", scanned_total)
    if args.dry_run:
        logger.info("Dry run enabled; skipping write")
        return

    db = _get_db()
    source = "openneuro_glmfitlins"

    if args.scope in {"dataset", "all"}:
        for (dataset_id, task), counts in dataset_counts.items():
            priors = {
                "hrf_basis": _normalize_counts(counts["hrf_basis"]),
                "confounds": _normalize_counts(counts["confounds"]),
                "high_pass": _normalize_counts(counts["high_pass"]),
            }
            for axis in sorted(CONF_FAMILY_AXES):
                axis_prior = _normalize_counts(counts.get(axis, {}))
                if axis_prior:
                    priors[axis] = axis_prior
            support = {
                "n_specs": counts["_scanned"]["n"],
                "n_datasets": 1,
                "n_tasks": 1,
            }
            coverage = _compute_coverage(counts)
            node_id = f"glm_prior:{_slug(dataset_id)}:{_slug(task)}"
            prior_id = _write_prior_node(
                db,
                node_id=node_id,
                task=task,
                dataset_id=dataset_id,
                priors=priors,
                scanned=counts["_scanned"]["n"],
                support=support,
                coverage=coverage,
                source=source,
            )
            _link_prior(db, prior_id=prior_id, dataset_id=dataset_id, task=task)

    if args.scope in {"task", "all"}:
        for task, counts in task_counts.items():
            priors = {
                "hrf_basis": _normalize_counts(counts["hrf_basis"]),
                "confounds": _normalize_counts(counts["confounds"]),
                "high_pass": _normalize_counts(counts["high_pass"]),
            }
            for axis in sorted(CONF_FAMILY_AXES):
                axis_prior = _normalize_counts(counts.get(axis, {}))
                if axis_prior:
                    priors[axis] = axis_prior
            support = {
                "n_specs": counts["_scanned"]["n"],
                "n_datasets": len(task_support_datasets.get(task, set())),
                "n_tasks": 1,
            }
            coverage = _compute_coverage(counts)
            node_id = f"glm_prior:task:{_slug(task)}"
            prior_id = _write_prior_node(
                db,
                node_id=node_id,
                task=task,
                dataset_id=None,
                priors=priors,
                scanned=counts["_scanned"]["n"],
                support=support,
                coverage=coverage,
                source=source,
            )
            _link_prior(db, prior_id=prior_id, dataset_id=None, task=task)

    if args.scope in {"global", "all"}:
        priors = {
            "hrf_basis": _normalize_counts(global_counts["hrf_basis"]),
            "confounds": _normalize_counts(global_counts["confounds"]),
            "high_pass": _normalize_counts(global_counts["high_pass"]),
        }
        for axis in sorted(CONF_FAMILY_AXES):
            axis_prior = _normalize_counts(global_counts.get(axis, {}))
            if axis_prior:
                priors[axis] = axis_prior
        support = {
            "n_specs": global_counts["_scanned"]["n"],
            "n_datasets": len(all_datasets),
            "n_tasks": len(all_tasks),
        }
        coverage = _compute_coverage(global_counts)
        node_id = "glm_prior:global"
        prior_id = _write_prior_node(
            db,
            node_id=node_id,
            task="__all__",
            dataset_id=None,
            priors=priors,
            scanned=scanned_total,
            support=support,
            coverage=coverage,
            source=source,
        )
        _link_prior(db, prior_id=prior_id, dataset_id=None, task="__all__")

    logger.info("GLM priors ingestion complete")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
