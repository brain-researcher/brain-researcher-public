#!/usr/bin/env python3
"""Run a Liu-component max-over-pipelines permutation smoke/correction.

This script is intentionally project-specific. It reuses the frozen
confirmatory workspace's ``run.py`` and ``predict.py`` but applies candidate
configs from the autoresearch ledgers by mutating the predict-module globals
before each evaluation.

The resulting null is for post-selection inference: for each permutation seed,
evaluate each replayable candidate pipeline and keep the maximum statistic
across candidates. Small ``n_perm`` runs are smoke tests; publication-facing
runs should use a pre-specified candidate family and ``n_perm >= 1000``.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import time
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

import numpy as np


DEFAULT_PROJECT = Path("/data/brain_researcher/research/predictive/project")
DEFAULT_WORKSPACE = (
    DEFAULT_PROJECT / "autoresearch_confirmatory_permutation_line_20260425_shared_null"
)
DEFAULT_INVENTORY = DEFAULT_PROJECT / "post_selection_candidate_inventory.json"
DEFAULT_OUT_DIR = DEFAULT_WORKSPACE / "outputs/post_selection_max_over_pipelines"
DEFAULT_EXCHANGEABILITY = DEFAULT_PROJECT / "manifests/hcp_exchangeability_manifest.json"
SELECTED_FINAL_CONFIG_HASH = "bfdbd2e7c675fa56"
POSITIVE_COMPONENTS = [
    "ICA_Cognition",
    "ICA_TobaccoUse",
    "ICA_PersonalityEmotion",
]


ACCEPTED_BRANCH_LEDGER_PREFIXES = (
    "autoresearch/experiments.jsonl",
    "autoresearch_representation_scaling_line_kg_grounded_prior_20260422_120650/experiments.jsonl",
    "autoresearch_validation_line_wpli_illicit_permutation_validation_20260422_163139/experiments.jsonl",
    "autoresearch_sensitivity_line_sensitivity_gsr_altparc_altfolds_20260422_180853/experiments.jsonl",
)


SUPPORTED_HEADS = {"ridge", "kernel_ridge_rbf", "mlp", "random_forest", None}


def _json_default(obj: Any) -> Any:
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return str(obj)


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _config_hash(config: Any) -> str:
    payload = json.dumps(config or {}, sort_keys=True, default=_json_default)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _as_int_key_dict(value: Any, *, list_values: bool = False) -> dict[int, Any] | None:
    if not isinstance(value, dict):
        return None
    converted: dict[int, Any] = {}
    for key, item in value.items():
        converted[int(key)] = list(item) if list_values and item is not None else item
    return converted


def _is_numeric_sequence(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    return all(isinstance(item, (int, float)) for item in value)


def _is_int_mapping(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, dict):
        return False
    try:
        for key, item in value.items():
            int(key)
            int(item)
    except (TypeError, ValueError):
        return False
    return True


def _load_inventory_candidates(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text())
    if "candidates" in payload:
        return list(payload["candidates"])
    if "accepted_candidates" in payload:
        candidates: list[dict[str, Any]] = []
        for item in payload["accepted_candidates"]:
            cand = dict(item)
            if "first_seen" not in cand and "first_accepted_row" in cand:
                cand["first_seen"] = cand["first_accepted_row"]
            candidates.append(cand)
        return candidates
    candidates: list[dict[str, Any]] = []
    for cfg in payload.get("unique_configs", []):
        candidates.append(
            {
                "config_hash": cfg["config_hash"],
                "config": cfg.get("config") or {},
                "n_rows": cfg.get("n_rows"),
                "first_seen": cfg.get("first_seen") or {},
                "max_aggregate_mean_r": cfg.get("max_aggregate_mean_r"),
            }
        )
    return candidates


def _select_accepted_branch(
    candidates: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for cand in candidates:
        ledger = str((cand.get("first_seen") or {}).get("ledger") or "")
        if ledger in ACCEPTED_BRANCH_LEDGER_PREFIXES:
            selected.append(dict(cand))
    return selected


def _candidate_replayability(
    candidate: dict[str, Any],
    *,
    available_terms: set[str],
) -> tuple[bool, str]:
    config = candidate.get("config") or {}
    if str(config.get("path")) != "B":
        return False, "only_path_b_configs_supported_by_replayer"
    if not _is_numeric_sequence(config.get("alpha_grid")):
        return False, "alpha_grid_not_numeric_sequence"
    terms = config.get("terms")
    if not isinstance(terms, list) or not terms:
        return False, "missing_terms"
    missing_terms = [term for term in terms if str(term) not in available_terms]
    if missing_terms:
        return False, "terms_not_available:" + ",".join(map(str, missing_terms))
    model_head = config.get("model_head")
    if model_head not in SUPPORTED_HEADS:
        return False, f"unsupported_model_head:{model_head}"
    per_component_model_head = config.get("per_component_model_head")
    if isinstance(per_component_model_head, dict):
        unsupported = sorted(
            {
                str(head)
                for head in per_component_model_head.values()
                if head not in SUPPORTED_HEADS
            }
        )
        if unsupported:
            return False, "unsupported_per_component_head:" + ",".join(unsupported)
    if not _is_int_mapping(config.get("per_component_topk_by_component")):
        return False, "per_component_topk_by_component_not_int_mapping"
    if not _is_int_mapping(config.get("per_component_per_term_topk")):
        return False, "per_component_per_term_topk_not_int_mapping"
    return True, "replayable"


def _filter_candidates(
    candidates: list[dict[str, Any]],
    *,
    available_terms: set[str],
    candidate_hashes: set[str] | None,
    max_candidates: int | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    annotated: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for cand in candidates:
        cand = dict(cand)
        cand_hash = str(cand.get("config_hash") or _config_hash(cand.get("config")))
        cand["config_hash"] = cand_hash
        if candidate_hashes and cand_hash not in candidate_hashes:
            continue
        ok, reason = _candidate_replayability(cand, available_terms=available_terms)
        cand["replayability"] = reason
        if ok:
            annotated.append(cand)
        else:
            skipped.append(cand)
    annotated.sort(
        key=lambda cand: (
            cand.get("max_aggregate_mean_r")
            if isinstance(cand.get("max_aggregate_mean_r"), (int, float))
            else -999
        ),
        reverse=True,
    )
    if max_candidates is not None:
        annotated = annotated[: int(max_candidates)]
    return annotated, skipped


def _apply_config(
    predict_module: Any,
    config: dict[str, Any],
    *,
    inner_cv_n_jobs_override: int | None = None,
) -> None:
    predict_module.TERMS = list(config["terms"])
    predict_module.RIDGE_ALPHA_GRID = list(
        config.get("alpha_grid") or [0.1, 1.0, 10.0, 100.0]
    )
    predict_module.INNER_CV_SPLITS = int(config.get("inner_cv_splits") or 10)
    predict_module.INNER_CV_RANDOM_STATE = int(
        config.get("inner_cv_random_state") or 42
    )
    predict_module.INNER_CV_N_JOBS = int(config.get("inner_cv_n_jobs") or -1)
    if inner_cv_n_jobs_override is not None:
        predict_module.INNER_CV_N_JOBS = int(inner_cv_n_jobs_override)
    predict_module.PCA_COMPONENTS = config.get("pca_components")
    predict_module.PER_TERM_PCA = config.get("per_term_pca")
    predict_module.PER_COMPONENT_TOPK = int(config.get("per_component_topk") or 40)
    predict_module.PER_COMPONENT_TOPK_BY_COMPONENT = _as_int_key_dict(
        config.get("per_component_topk_by_component")
    )
    predict_module.PER_COMPONENT_TERMS = _as_int_key_dict(
        config.get("per_component_terms"), list_values=True
    )
    predict_module.PER_COMPONENT_PER_TERM_TOPK = _as_int_key_dict(
        config.get("per_component_per_term_topk")
    )
    predict_module.PROBE_ALPHA = float(config.get("probe_alpha") or 100.0)
    predict_module.PROBE_MODE = str(config.get("probe_mode") or "topk")
    if config.get("random_probe_seed") is not None:
        predict_module.RANDOM_PROBE_SEED = int(config["random_probe_seed"])
    predict_module.MODEL_HEAD = config.get("model_head") or "ridge"
    predict_module.PER_COMPONENT_MODEL_HEAD = _as_int_key_dict(
        config.get("per_component_model_head")
    )
    if config.get("kernel_ridge_gamma_grid"):
        predict_module.KERNEL_RIDGE_GAMMA_GRID = list(
            config["kernel_ridge_gamma_grid"]
        )
    for attr in ("_PER_TERM_PCA_CACHE", "_QCOD_MASK_CACHE"):
        cache = getattr(predict_module, attr, None)
        if hasattr(cache, "clear"):
            cache.clear()


@contextmanager
def _permutation_env(seed: int | None, exchangeability_manifest: Path):
    old_family = os.environ.get("LIU_FAMILY_BLOCK_PERMUTE_Y")
    old_shared = os.environ.get("LIU_SHARED_PERMUTE_Y")
    old_manifest = os.environ.get("LIU_EXCHANGEABILITY_MANIFEST")
    try:
        os.environ.pop("LIU_SHARED_PERMUTE_Y", None)
        if seed is None:
            os.environ.pop("LIU_FAMILY_BLOCK_PERMUTE_Y", None)
        else:
            os.environ["LIU_FAMILY_BLOCK_PERMUTE_Y"] = str(int(seed))
        os.environ["LIU_EXCHANGEABILITY_MANIFEST"] = str(exchangeability_manifest)
        yield
    finally:
        if old_family is None:
            os.environ.pop("LIU_FAMILY_BLOCK_PERMUTE_Y", None)
        else:
            os.environ["LIU_FAMILY_BLOCK_PERMUTE_Y"] = old_family
        if old_shared is None:
            os.environ.pop("LIU_SHARED_PERMUTE_Y", None)
        else:
            os.environ["LIU_SHARED_PERMUTE_Y"] = old_shared
        if old_manifest is None:
            os.environ.pop("LIU_EXCHANGEABILITY_MANIFEST", None)
        else:
            os.environ["LIU_EXCHANGEABILITY_MANIFEST"] = old_manifest


def _component_vector(result: dict[str, Any], component_order: list[str]) -> np.ndarray:
    by_name = {
        str(row["component"]): row.get("fold_mean_r")
        for row in result.get("per_component", [])
    }
    return np.asarray([float(by_name[name]) for name in component_order], dtype=float)


def _candidate_stats(vector: np.ndarray, component_order: list[str]) -> dict[str, Any]:
    positive_idx = [component_order.index(name) for name in POSITIVE_COMPONENTS]
    return {
        "aggregate_all_five": float(np.mean(vector)),
        "aggregate_positive_three": float(np.mean(vector[positive_idx])),
        "component_fold_mean_r": {
            name: float(vector[idx]) for idx, name in enumerate(component_order)
        },
        "max_component_fold_mean_r": float(np.max(vector)),
    }


def _run_candidate(
    *,
    run_module: Any,
    predict_module: Any,
    loader: Any,
    folds: Any,
    y: np.ndarray,
    candidate: dict[str, Any],
    component_order: list[str],
    inner_cv_n_jobs_override: int | None = None,
) -> dict[str, Any]:
    t0 = time.time()
    _apply_config(
        predict_module,
        candidate["config"],
        inner_cv_n_jobs_override=inner_cv_n_jobs_override,
    )
    result = run_module._run_path_b(predict_module, loader, folds, y)
    vector = _component_vector(result, component_order)
    payload = {
        "config_hash": candidate["config_hash"],
        "first_seen": candidate.get("first_seen"),
        "max_aggregate_mean_r_from_inventory": candidate.get("max_aggregate_mean_r"),
        "status": "ok",
        "wall_time_sec": round(time.time() - t0, 3),
        "stats": _candidate_stats(vector, component_order),
    }
    return payload


def _plus_one_p(null_values: list[float], observed: float) -> dict[str, Any]:
    arr = np.asarray(null_values, dtype=float)
    n_ge = int(np.sum(arr >= float(observed)))
    return {
        "observed": float(observed),
        "n_perm": int(arr.size),
        "n_perm_ge_observed": n_ge,
        "plus_one_p": float((n_ge + 1) / (arr.size + 1)),
        "null_mean": float(np.mean(arr)) if arr.size else None,
        "null_max": float(np.max(arr)) if arr.size else None,
    }


def _load_existing_perm_seeds(path: Path) -> set[int]:
    seeds: set[int] = set()
    if not path.exists():
        return seeds
    with path.open() as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("status") == "ok":
                seeds.add(int(row["seed"]))
    return seeds


def _load_perm_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open() as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("status") == "ok":
                rows.append(row)
    return sorted(rows, key=lambda row: int(row["seed"]))


def _summarize(
    *,
    out_dir: Path,
    n_perm_requested: int,
    selected_config_hash: str,
    candidates: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    observed: list[dict[str, Any]],
    perm_rows: list[dict[str, Any]],
    component_order: list[str],
) -> dict[str, Any]:
    observed_by_hash = {row["config_hash"]: row for row in observed if row["status"] == "ok"}
    selected = observed_by_hash.get(selected_config_hash)
    observed_family_max_agg = max(
        row["stats"]["aggregate_all_five"] for row in observed_by_hash.values()
    )
    observed_family_max_positive = max(
        row["stats"]["aggregate_positive_three"] for row in observed_by_hash.values()
    )
    null_max_agg = [row["max_aggregate_all_five"] for row in perm_rows]
    null_max_positive = [row["max_aggregate_positive_three"] for row in perm_rows]
    null_max_any_component = [row["max_any_component"] for row in perm_rows]

    selected_stats = selected["stats"] if selected else None
    selected_tests = {}
    if selected_stats:
        selected_tests["aggregate_all_five_vs_max_pipeline_null"] = _plus_one_p(
            null_max_agg, selected_stats["aggregate_all_five"]
        )
        selected_tests["positive_three_vs_max_pipeline_null"] = _plus_one_p(
            null_max_positive, selected_stats["aggregate_positive_three"]
        )
        selected_tests["components_vs_max_pipeline_same_endpoint_null"] = {}
        selected_tests["components_vs_max_pipeline_max_t_null"] = {}
        for name in component_order:
            observed_value = selected_stats["component_fold_mean_r"][name]
            same_endpoint_null = [
                row["max_component_by_name"][name] for row in perm_rows
            ]
            selected_tests["components_vs_max_pipeline_same_endpoint_null"][name] = (
                _plus_one_p(same_endpoint_null, observed_value)
            )
            selected_tests["components_vs_max_pipeline_max_t_null"][name] = (
                _plus_one_p(null_max_any_component, observed_value)
            )

    summary = {
        "schema_version": "liu_max_over_pipelines_permutation_v1",
        "out_dir": str(out_dir),
        "n_perm_requested": int(n_perm_requested),
        "n_perm_completed": len(perm_rows),
        "candidate_family": {
            "selection_rule": "accepted_branch_default_or_user_filtered",
            "n_candidates_requested": len(candidates) + len(skipped),
            "n_replayable_candidates_used": len(candidates),
            "n_skipped_candidates": len(skipped),
            "selected_config_hash": selected_config_hash,
            "candidate_hashes": [cand["config_hash"] for cand in candidates],
            "skipped": [
                {
                    "config_hash": cand.get("config_hash"),
                    "first_seen": cand.get("first_seen"),
                    "reason": cand.get("replayability"),
                }
                for cand in skipped[:100]
            ],
        },
        "observed": {
            "selected_config": selected,
            "family_max_aggregate_all_five": observed_family_max_agg,
            "family_max_aggregate_positive_three": observed_family_max_positive,
            "all_candidates": observed,
        },
        "post_selection_tests": {
            "observed_family_max_aggregate_all_five_vs_max_pipeline_null": _plus_one_p(
                null_max_agg, observed_family_max_agg
            )
            if perm_rows
            else None,
            "observed_family_max_positive_three_vs_max_pipeline_null": _plus_one_p(
                null_max_positive, observed_family_max_positive
            )
            if perm_rows
            else None,
            "selected_final_config": selected_tests if perm_rows else None,
        },
        "artifact_paths": {
            "observed_json": str(out_dir / "observed_candidates.json"),
            "permutations_jsonl": str(out_dir / "max_over_pipelines_perm.jsonl"),
            "summary_json": str(out_dir / "max_over_pipelines_summary.json"),
            "summary_md": str(out_dir / "max_over_pipelines_report.md"),
        },
        "interpretation_boundary": (
            "Small n_perm runs are smoke tests only. Treat as publication-facing "
            "post-selection inference only after the candidate family is "
            "pre-specified, all material candidates are replayable, and "
            "n_perm >= 1000."
        ),
    }
    return summary


def _write_markdown(summary: dict[str, Any], path: Path) -> None:
    fam = summary["candidate_family"]
    tests = summary["post_selection_tests"]
    lines = [
        "# Max-Over-Pipelines Post-Selection Permutation",
        "",
        "## Status",
        "",
        f"- Completed permutations: {summary['n_perm_completed']} / {summary['n_perm_requested']}.",
        f"- Replayable candidates used: {fam['n_replayable_candidates_used']}.",
        f"- Skipped candidates: {fam['n_skipped_candidates']}.",
        f"- Selected final config hash: `{fam['selected_config_hash']}`.",
        "",
        "This corrects for candidate-pipeline selection only for the candidate family actually replayed here.",
        "Small runs are smoke tests, not publication-grade p-values.",
        "",
        "## Candidate Hashes",
        "",
    ]
    for cand_hash in fam["candidate_hashes"]:
        lines.append(f"- `{cand_hash}`")
    lines.extend(["", "## Post-Selection Tests", ""])
    if tests and tests.get("observed_family_max_aggregate_all_five_vs_max_pipeline_null"):
        row = tests["observed_family_max_aggregate_all_five_vs_max_pipeline_null"]
        lines.append(
            f"- Family observed max aggregate: observed = {row['observed']:.6f}; "
            f"plus-one p = {row['plus_one_p']:.6g}; null max = {row['null_max']:.6f}."
        )
        row = tests["observed_family_max_positive_three_vs_max_pipeline_null"]
        lines.append(
            f"- Family observed max positive-three aggregate: observed = {row['observed']:.6f}; "
            f"plus-one p = {row['plus_one_p']:.6g}; null max = {row['null_max']:.6f}."
        )
        selected = tests.get("selected_final_config") or {}
        if selected:
            row = selected["aggregate_all_five_vs_max_pipeline_null"]
            lines.append(
                f"- Selected final aggregate vs max-pipeline null: observed = {row['observed']:.6f}; "
                f"plus-one p = {row['plus_one_p']:.6g}; null max = {row['null_max']:.6f}."
            )
    else:
        lines.append("- No permutation rows completed yet.")
    lines.extend(
        [
            "",
            "## Interpretation Boundary",
            "",
            summary["interpretation_boundary"],
            "",
        ]
    )
    path.write_text("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--inventory-json", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--candidate-family-json", type=Path)
    parser.add_argument("--exchangeability-manifest", type=Path, default=DEFAULT_EXCHANGEABILITY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--n-perm", type=int, default=0)
    parser.add_argument("--seed-start", type=int, default=1)
    parser.add_argument("--seed-end", type=int)
    parser.add_argument("--max-candidates", type=int)
    parser.add_argument("--candidate-hash", action="append", default=[])
    parser.add_argument("--selected-config-hash", default=SELECTED_FINAL_CONFIG_HASH)
    parser.add_argument("--inner-cv-n-jobs-override", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    seed_end = int(args.seed_end) if args.seed_end is not None else int(args.n_perm)
    if int(args.seed_start) < 1:
        raise ValueError("--seed-start must be >= 1")
    if seed_end < int(args.seed_start) - 1:
        raise ValueError("--seed-end must be >= --seed-start - 1")
    if int(args.n_perm) and seed_end > int(args.n_perm):
        raise ValueError("--seed-end cannot exceed --n-perm")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    run_module = _load_module(args.workspace / "run.py", "liu_postsel_run")
    predict_module = _load_module(args.workspace / "predict.py", "liu_postsel_predict")
    loader = run_module.TermLoader(run_module.TERMS_DIR)
    y = run_module._load_y()
    folds = run_module._load_folds()
    component_order = list(run_module.COMPONENT_ORDER)

    source_json = args.candidate_family_json or args.inventory_json
    raw_candidates = _load_inventory_candidates(source_json)
    if args.candidate_family_json:
        candidates = raw_candidates
    else:
        candidates = _select_accepted_branch(raw_candidates)
    candidate_hashes = set(args.candidate_hash) if args.candidate_hash else None
    candidates, skipped = _filter_candidates(
        candidates,
        available_terms=set(loader.available_names),
        candidate_hashes=candidate_hashes,
        max_candidates=args.max_candidates,
    )
    if not candidates:
        raise RuntimeError("no replayable candidates selected")

    dry_payload = {
        "source_json": str(source_json),
        "n_replayable_candidates": len(candidates),
        "n_skipped_candidates": len(skipped),
        "candidate_hashes": [cand["config_hash"] for cand in candidates],
        "skipped": [
            {
                "config_hash": cand.get("config_hash"),
                "first_seen": cand.get("first_seen"),
                "reason": cand.get("replayability"),
            }
            for cand in skipped[:25]
        ],
    }
    (args.out_dir / "candidate_selection_preview.json").write_text(
        json.dumps(dry_payload, indent=2, default=_json_default) + "\n"
    )
    if args.dry_run:
        print(json.dumps(dry_payload, indent=2, default=_json_default))
        return 0

    observed: list[dict[str, Any]] = []
    with _permutation_env(None, args.exchangeability_manifest):
        for cand in candidates:
            try:
                observed.append(
                    _run_candidate(
                        run_module=run_module,
                        predict_module=predict_module,
                        loader=loader,
                        folds=folds,
                        y=y,
                        candidate=cand,
                        component_order=component_order,
                        inner_cv_n_jobs_override=args.inner_cv_n_jobs_override,
                    )
                )
            except Exception as exc:
                observed.append(
                    {
                        "config_hash": cand["config_hash"],
                        "status": "error",
                        "error": repr(exc),
                        "traceback": traceback.format_exc(),
                    }
                )
    observed_path = args.out_dir / "observed_candidates.json"
    observed_path.write_text(json.dumps(observed, indent=2, default=_json_default) + "\n")

    perm_path = args.out_dir / "max_over_pipelines_perm.jsonl"
    completed = _load_existing_perm_seeds(perm_path)
    with perm_path.open("a") as handle:
        for seed in range(int(args.seed_start), seed_end + 1):
            if seed in completed:
                continue
            t0 = time.time()
            candidate_rows: list[dict[str, Any]] = []
            with _permutation_env(seed, args.exchangeability_manifest):
                for cand in candidates:
                    try:
                        candidate_rows.append(
                            _run_candidate(
                                run_module=run_module,
                                predict_module=predict_module,
                                loader=loader,
                                folds=folds,
                                y=y,
                                candidate=cand,
                                component_order=component_order,
                                inner_cv_n_jobs_override=args.inner_cv_n_jobs_override,
                            )
                        )
                    except Exception as exc:
                        candidate_rows.append(
                            {
                                "config_hash": cand["config_hash"],
                                "status": "error",
                                "error": repr(exc),
                                "traceback": traceback.format_exc(),
                            }
                        )
            ok_rows = [row for row in candidate_rows if row.get("status") == "ok"]
            if not ok_rows:
                row = {
                    "seed": seed,
                    "status": "error",
                    "error": "all candidate evaluations failed",
                    "candidate_results": candidate_rows,
                    "wall_time_sec": round(time.time() - t0, 3),
                }
            else:
                max_component_by_name = {
                    name: max(
                        row["stats"]["component_fold_mean_r"][name] for row in ok_rows
                    )
                    for name in component_order
                }
                row = {
                    "seed": seed,
                    "status": "ok",
                    "max_aggregate_all_five": max(
                        row["stats"]["aggregate_all_five"] for row in ok_rows
                    ),
                    "max_aggregate_positive_three": max(
                        row["stats"]["aggregate_positive_three"] for row in ok_rows
                    ),
                    "max_component_by_name": max_component_by_name,
                    "max_any_component": max(max_component_by_name.values()),
                    "candidate_results": candidate_rows,
                    "wall_time_sec": round(time.time() - t0, 3),
                }
            handle.write(json.dumps(row, default=_json_default) + "\n")
            handle.flush()

    perm_rows = _load_perm_rows(perm_path)
    summary = _summarize(
        out_dir=args.out_dir,
        n_perm_requested=args.n_perm,
        selected_config_hash=args.selected_config_hash,
        candidates=candidates,
        skipped=skipped,
        observed=observed,
        perm_rows=perm_rows,
        component_order=component_order,
    )
    summary_path = args.out_dir / "max_over_pipelines_summary.json"
    report_path = args.out_dir / "max_over_pipelines_report.md"
    summary_path.write_text(json.dumps(summary, indent=2, default=_json_default) + "\n")
    _write_markdown(summary, report_path)
    print(
        json.dumps(
            {
                "n_replayable_candidates": len(candidates),
                "n_perm_completed": len(perm_rows),
                "summary_json": str(summary_path),
                "summary_md": str(report_path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
