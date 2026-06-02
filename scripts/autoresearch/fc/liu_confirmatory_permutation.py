#!/usr/bin/env python3
"""Run a frozen Liu-component confirmatory permutation analysis.

This script is intentionally project-specific. It imports an existing frozen
autoresearch workspace containing ``run.py`` and ``predict.py``, evaluates the
real 10-fold result once, then runs a resumable permutation null.

Primary outputs:
- ``real_result.json``
- ``confirmatory_shared_perm.jsonl``
- ``confirmatory_permutation_summary.json``
- ``confirmatory_permutation_report.md``
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np


STRONG_POSITIVE_COMPONENTS = [
    "ICA_Cognition",
    "ICA_TobaccoUse",
    "ICA_PersonalityEmotion",
]

CAVEATED_COMPONENTS = ["ICA_MentalHealth"]
NONROBUST_COMPONENTS = ["ICA_IllicitDrugUse"]


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_default(obj: Any) -> Any:
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return str(obj)


def _load_existing_seeds(path: Path) -> set[int]:
    seeds: set[int] = set()
    if not path.exists():
        return seeds
    with path.open() as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("status") == "ok" and "seed" in row:
                seeds.add(int(row["seed"]))
    return seeds


def _load_perm_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open() as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("status") == "ok":
                rows.append(row)
    rows.sort(key=lambda row: int(row["seed"]))
    return rows


def _component_vector(result: dict[str, Any], component_order: list[str]) -> np.ndarray:
    by_name = {
        str(row["component"]): row.get("fold_mean_r")
        for row in result.get("per_component", [])
    }
    return np.asarray([float(by_name[name]) for name in component_order], dtype=float)


def _run_once(
    run_module: Any,
    predict_module: Any,
    loader: Any,
    folds: Any,
    y: np.ndarray,
) -> dict[str, Any]:
    if hasattr(predict_module, "predict_fold"):
        summary = run_module._run_path_b(predict_module, loader, folds, y)
    else:
        summary = run_module._run_path_a(predict_module, loader, folds, y)
    return dict(summary)


def _plus_one_p(null_values: np.ndarray, observed: float) -> tuple[int, float]:
    n_ge = int(np.sum(null_values >= observed))
    return n_ge, float((n_ge + 1) / (len(null_values) + 1))


def _bh_fdr(p_values: list[float]) -> list[float]:
    """Benjamini-Hochberg adjusted q-values, preserving input order."""
    n = len(p_values)
    order = sorted(range(n), key=lambda idx: p_values[idx])
    q_values = [1.0] * n
    running = 1.0
    for rank_from_end, idx in enumerate(reversed(order), start=1):
        rank = n - rank_from_end + 1
        q = min(running, p_values[idx] * n / rank)
        running = q
        q_values[idx] = float(min(q, 1.0))
    return q_values


def _null_stats(values: np.ndarray) -> dict[str, float]:
    return {
        "mean": float(np.mean(values)),
        "sd": float(np.std(values)),
        "min": float(np.min(values)),
        "max": float(np.max(values)),
        "p95": float(np.quantile(values, 0.95)),
        "p99": float(np.quantile(values, 0.99)),
    }


def _effect_vs_null(null_values: np.ndarray, observed: float) -> dict[str, float | None]:
    null_mean = float(np.mean(null_values))
    null_sd = float(np.std(null_values))
    return {
        "observed_minus_null_mean": float(observed - null_mean),
        "permutation_z": None if null_sd == 0 else float((observed - null_mean) / null_sd),
        "empirical_percentile": float(np.mean(null_values <= observed)),
    }


def summarize(
    *,
    workspace: Path,
    out_dir: Path,
    n_perm_requested: int,
    real_result: dict[str, Any],
    perm_path: Path,
    null_mode: str,
    exchangeability_manifest: Path | None = None,
) -> dict[str, Any]:
    component_order = [
        str(row["component"]) for row in real_result.get("per_component", [])
    ]
    real_vector = _component_vector(real_result, component_order)
    rows = _load_perm_rows(perm_path)
    null_matrix = np.asarray(
        [_component_vector(row, component_order) for row in rows],
        dtype=float,
    )
    if null_matrix.ndim != 2 or null_matrix.shape[1] != len(component_order):
        raise RuntimeError("permutation matrix has invalid shape")

    n_perm = int(null_matrix.shape[0])
    seeds = [int(row["seed"]) for row in rows]
    contiguous_from_one = seeds == list(range(1, n_perm + 1))
    real_agg = float(np.mean(real_vector))
    null_agg = np.mean(null_matrix, axis=1)
    agg_n_ge, agg_p = _plus_one_p(null_agg, real_agg)
    null_max_t = np.max(null_matrix, axis=1)

    real_by_name = {
        str(row["component"]): row for row in real_result.get("per_component", [])
    }
    per_component: dict[str, dict[str, Any]] = {}
    raw_p_values: list[float] = []
    for idx, name in enumerate(component_order):
        raw_n_ge, raw_p = _plus_one_p(null_matrix[:, idx], float(real_vector[idx]))
        max_t_n_ge, max_t_p = _plus_one_p(null_max_t, float(real_vector[idx]))
        raw_p_values.append(raw_p)
        real_row = real_by_name.get(name, {})
        per_component[name] = {
            "observed_fold_mean_r": float(real_vector[idx]),
            "observed_fold_std_r": real_row.get("fold_std_r"),
            "reference_mean_r": real_row.get("reference_mean_r"),
            "reference_best_r": real_row.get("reference_best_r"),
            "surplus_over_ref_mean": real_row.get("surplus_over_ref_mean"),
            "surplus_over_ref_best": real_row.get("surplus_over_ref_best"),
            "raw_plus_one_p": raw_p,
            "raw_n_perm_ge_observed": raw_n_ge,
            "max_t_fwer_plus_one_p": max_t_p,
            "max_t_n_perm_ge_observed": max_t_n_ge,
            "effect_vs_null": _effect_vs_null(
                null_matrix[:, idx], float(real_vector[idx])
            ),
            "null": _null_stats(null_matrix[:, idx]),
        }
    for name, q_value in zip(component_order, _bh_fdr(raw_p_values)):
        per_component[name]["bh_fdr_q"] = q_value

    subset_tests: dict[str, dict[str, Any]] = {}
    subsets = {
        "all_five_components": component_order,
        "pre_specified_positive_three": STRONG_POSITIVE_COMPONENTS,
        "positive_plus_caveated_four_excluding_illicit": (
            STRONG_POSITIVE_COMPONENTS + CAVEATED_COMPONENTS
        ),
    }
    for label, names in subsets.items():
        indices = [component_order.index(name) for name in names if name in component_order]
        observed = float(np.mean(real_vector[indices]))
        null_values = np.mean(null_matrix[:, indices], axis=1)
        n_ge, p_value = _plus_one_p(null_values, observed)
        subset_tests[label] = {
            "components": [component_order[i] for i in indices],
            "observed_mean_fold_r": observed,
            "plus_one_p": p_value,
            "n_perm_ge_observed": n_ge,
            "effect_vs_null": _effect_vs_null(null_values, observed),
            "null": _null_stats(null_values),
        }

    if null_mode == "family_block":
        null_design = {
            "label_shuffle": (
                "Family_ID block permutation of the 5-component target matrix "
                "within each training fold; blocks are shuffled among same-size "
                "within-fold family blocks"
            ),
            "env_var": "LIU_FAMILY_BLOCK_PERMUTE_Y",
            "exchangeability_manifest": str(exchangeability_manifest)
            if exchangeability_manifest
            else None,
            "permutation_seed_formula": (
                "numpy.default_rng(base_seed * 1_000_000 + fold_id); block "
                "permutation by Family_ID group size"
            ),
            "folds": "fixed 10-fold HCP split, seed=42",
            "test_labels": "never permuted",
            "model_selection": "frozen final autoresearch pipeline; inner ridge selection reruns inside each permuted training fold",
        }
    else:
        null_design = {
            "label_shuffle": "shared row permutation of the 5-component target matrix within each training fold",
            "env_var": "LIU_SHARED_PERMUTE_Y",
            "exchangeability_manifest": None,
            "permutation_seed_formula": "numpy.default_rng(base_seed * 1_000_000 + fold_id).permutation(n_train)",
            "folds": "fixed 10-fold HCP split, seed=42",
            "test_labels": "never permuted",
            "model_selection": "frozen final autoresearch pipeline; inner ridge selection reruns inside each permuted training fold",
        }

    summary = {
        "schema_version": "liu_confirmatory_permutation_v1",
        "workspace": str(workspace),
        "out_dir": str(out_dir),
        "n_perm_requested": int(n_perm_requested),
        "n_perm_completed": n_perm,
        "is_publication_grade_primary_complete": n_perm >= 1000,
        "null_mode": null_mode,
        "null_design": null_design,
        "permutation_seed_audit": {
            "requested_seed_range": [1, int(n_perm_requested)],
            "completed_seed_min": min(seeds) if seeds else None,
            "completed_seed_max": max(seeds) if seeds else None,
            "completed_seed_count": len(seeds),
            "completed_seeds_unique": len(set(seeds)) == len(seeds),
            "completed_seeds_contiguous_from_1": contiguous_from_one,
            "seed_record_location": str(perm_path),
        },
        "frozen_pipeline": {
            "run_py_sha256": _sha256(workspace / "run.py"),
            "predict_py_sha256": _sha256(workspace / "predict.py"),
            "predict_config": real_result.get("config"),
            "data_spec": real_result.get("data_spec"),
        },
        "pre_specified_claims": {
            "positive": STRONG_POSITIVE_COMPONENTS,
            "caveated": CAVEATED_COMPONENTS,
            "nonrobust_or_negative_control": NONROBUST_COMPONENTS,
        },
        "aggregate_all_five": {
            "observed_mean_fold_r": real_agg,
            "plus_one_p": agg_p,
            "n_perm_ge_observed": agg_n_ge,
            "effect_vs_null": _effect_vs_null(null_agg, real_agg),
            "null": _null_stats(null_agg),
        },
        "per_component": per_component,
        "subset_tests": subset_tests,
        "optional_model_selection_correction": {
            "max_over_pipelines_null": "not_executed",
            "reason": (
                "Primary analysis freezes the selected pipeline. A max-over-pipelines "
                "null would rerun the whole autoresearch selection policy per label "
                "shuffle and is much more expensive; it is recommended only if the "
                "claim is about the adaptive search procedure rather than the frozen "
                "final pipeline."
            ),
        },
        "artifact_paths": {
            "real_result": str(out_dir / "real_result.json"),
            "permutations_jsonl": str(perm_path),
            "summary_json": str(out_dir / "confirmatory_permutation_summary.json"),
            "summary_md": str(out_dir / "confirmatory_permutation_report.md"),
        },
    }
    return summary


def write_markdown(summary: dict[str, Any], path: Path) -> None:
    def fmt_optional(value: Any, digits: int = 3) -> str:
        if value is None:
            return "NA"
        return f"{float(value):.{digits}f}"

    title = (
        "Confirmatory Family-Block Permutation Analysis"
        if summary.get("null_mode") == "family_block"
        else "Confirmatory Shared-Null Permutation Analysis"
    )
    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append("## Protocol")
    lines.append("")
    lines.append(
        f"- Completed permutations: {summary['n_perm_completed']} / "
        f"{summary['n_perm_requested']}."
    )
    seed_audit = summary["permutation_seed_audit"]
    lines.append(
        f"- Seeds: requested {seed_audit['requested_seed_range'][0]}.."
        f"{seed_audit['requested_seed_range'][1]}; completed "
        f"{seed_audit['completed_seed_min']}..{seed_audit['completed_seed_max']}; "
        f"unique={seed_audit['completed_seeds_unique']}; "
        f"contiguous_from_1={seed_audit['completed_seeds_contiguous_from_1']}."
    )
    null_design = summary["null_design"]
    lines.append(
        f"- Null: {null_design['label_shuffle']}; test labels are never permuted."
    )
    lines.append(
        "- Pipeline: frozen final autoresearch predictor with the same folds, "
        "feature routing, top-K selection, and nested ridge fitting."
    )
    lines.append(
        "- P-values: one-sided plus-one permutation p-values; max-T controls "
        "family-wise error over the five component-level positive tests."
    )
    lines.append("")
    lines.append("## Pre-Specified Claims")
    lines.append("")
    claims = summary["pre_specified_claims"]
    lines.append(f"- Positive: {', '.join(claims['positive'])}.")
    lines.append(f"- Caveated: {', '.join(claims['caveated'])}.")
    lines.append(
        f"- Non-robust / negative-control target: "
        f"{', '.join(claims['nonrobust_or_negative_control'])}."
    )
    lines.append("")
    lines.append("## Aggregate And Subset Tests")
    lines.append("")
    agg = summary["aggregate_all_five"]
    lines.append(
        f"- All five aggregate mean fold-r = {agg['observed_mean_fold_r']:.6f}; "
        f"p = {agg['plus_one_p']:.6g}; "
        f"delta vs null mean = "
        f"{agg['effect_vs_null']['observed_minus_null_mean']:.6f}; "
        f"permutation z = "
        f"{fmt_optional(agg['effect_vs_null']['permutation_z'])}; "
        f"null max = {agg['null']['max']:.6f}."
    )
    for label, row in summary["subset_tests"].items():
        lines.append(
            f"- {label}: observed mean fold-r = "
            f"{row['observed_mean_fold_r']:.6f}; p = {row['plus_one_p']:.6g}; "
            f"delta = {row['effect_vs_null']['observed_minus_null_mean']:.6f}; "
            f"components = {', '.join(row['components'])}."
        )
    lines.append("")
    lines.append("## Component-Level Tests")
    lines.append("")
    lines.append(
        "| Component | Observed fold-r | Delta vs null | Perm z | Raw p | BH-FDR q | Max-T FWER p | Null max | Interpretation |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---|")
    for name, row in summary["per_component"].items():
        if name in claims["positive"]:
            interp = "pre-specified positive"
        elif name in claims["caveated"]:
            interp = "positive only with demographic/BMI caveat"
        else:
            interp = "pre-specified non-robust target"
        z_value = row["effect_vs_null"]["permutation_z"]
        z_text = "NA" if z_value is None else f"{z_value:.3f}"
        lines.append(
            f"| {name} | {row['observed_fold_mean_r']:.6f} | "
            f"{row['effect_vs_null']['observed_minus_null_mean']:.6f} | "
            f"{z_text} | "
            f"{row['raw_plus_one_p']:.6g} | "
            f"{row['bh_fdr_q']:.6g} | "
            f"{row['max_t_fwer_plus_one_p']:.6g} | "
            f"{row['null']['max']:.6f} | {interp} |"
        )
    lines.append("")
    lines.append("## Model-Selection Correction")
    lines.append("")
    opt = summary["optional_model_selection_correction"]
    lines.append(f"- max-over-pipelines null: {opt['max_over_pipelines_null']}.")
    lines.append(f"- Rationale: {opt['reason']}")
    lines.append("")
    lines.append("## Artifact Paths")
    lines.append("")
    for key, value in summary["artifact_paths"].items():
        lines.append(f"- {key}: `{value}`")
    lines.append("")
    path.write_text("\n".join(lines) + "\n")


def write_summary(summary: dict[str, Any], out_dir: Path) -> None:
    summary_path = out_dir / "confirmatory_permutation_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=_json_default) + "\n")
    write_markdown(summary, out_dir / "confirmatory_permutation_report.md")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument(
        "--null-mode",
        choices=["shared", "family_block"],
        default="shared",
    )
    parser.add_argument("--exchangeability-manifest", type=Path, default=None)
    parser.add_argument("--n-perm", type=int, default=1000)
    parser.add_argument("--start-seed", type=int, default=1)
    parser.add_argument("--summary-every", type=int, default=25)
    parser.add_argument("--max-new", type=int, default=None)
    args = parser.parse_args(argv)

    workspace = args.workspace.resolve()
    default_subdir = (
        "confirmatory_family_block_null"
        if args.null_mode == "family_block"
        else "confirmatory_shared_null"
    )
    out_dir = (args.out_dir or (workspace / "outputs" / default_subdir)).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    perm_path = out_dir / f"confirmatory_{args.null_mode}_perm.jsonl"
    real_path = out_dir / "real_result.json"

    if args.null_mode == "family_block":
        if args.exchangeability_manifest is None:
            raise ValueError("--exchangeability-manifest is required for family_block")
        os.environ["LIU_EXCHANGEABILITY_MANIFEST"] = str(
            args.exchangeability_manifest.resolve()
        )

    run_module = _load_module(workspace / "run.py", "liu_confirm_run")
    loader = run_module.TermLoader(run_module.TERMS_DIR)
    y = run_module._load_y()
    folds = run_module._load_folds()
    predict_module, path_kind = run_module._import_predict()

    os.environ.pop("LIU_PERMUTE_Y", None)
    os.environ.pop("LIU_SHARED_PERMUTE_Y", None)
    os.environ.pop("LIU_FAMILY_BLOCK_PERMUTE_Y", None)

    if real_path.exists():
        real_result = json.loads(real_path.read_text())
    else:
        t0 = time.time()
        real_result = _run_once(run_module, predict_module, loader, folds, y)
        real_result.update(
            {
                "status": "ok",
                "path_kind": path_kind,
                "wall_time_sec": round(time.time() - t0, 3),
                "config": dict(predict_module.get_config() or {})
                if hasattr(predict_module, "get_config")
                else {},
                "data_spec": {
                    "n_subjects": run_module.N_SUBJECTS,
                    "n_rois": run_module.N_ROIS,
                    "n_features_per_term": run_module.N_FEATURES_PER_TERM,
                    "parcellation": "schaefer100x7",
                    "components": run_module.COMPONENT_ORDER,
                    "cv": {
                        "n_folds": 10,
                        "seed": 42,
                        "source": str(run_module.FOLD_MANIFEST),
                    },
                    "confound_regression": False,
                },
            }
        )
        real_path.write_text(json.dumps(real_result, indent=2, default=_json_default) + "\n")

    done = _load_existing_seeds(perm_path)
    new_count = 0
    for seed in range(args.start_seed, args.n_perm + 1):
        if seed in done:
            continue
        if args.max_new is not None and new_count >= args.max_new:
            break
        t0 = time.time()
        if args.null_mode == "family_block":
            os.environ["LIU_FAMILY_BLOCK_PERMUTE_Y"] = str(seed)
            os.environ.pop("LIU_SHARED_PERMUTE_Y", None)
            env_var = "LIU_FAMILY_BLOCK_PERMUTE_Y"
            null_label = "family_block_label_shuffle"
        else:
            os.environ["LIU_SHARED_PERMUTE_Y"] = str(seed)
            os.environ.pop("LIU_FAMILY_BLOCK_PERMUTE_Y", None)
            env_var = "LIU_SHARED_PERMUTE_Y"
            null_label = "shared_label_shuffle"
        try:
            result = _run_once(run_module, predict_module, loader, folds, y)
            result.update(
                {
                    "seed": seed,
                    "status": "ok",
                    "null": null_label,
                    "env_var": env_var,
                    "wall_time_sec": round(time.time() - t0, 3),
                }
            )
        except Exception as exc:  # pragma: no cover - operational safety
            result = {
                "seed": seed,
                "status": "error",
                "error": repr(exc),
                "traceback": traceback.format_exc(),
                "wall_time_sec": round(time.time() - t0, 3),
            }
        with perm_path.open("a") as handle:
            handle.write(json.dumps(result, default=_json_default) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        done.add(seed)
        new_count += 1
        if seed % args.summary_every == 0 or seed == args.n_perm:
            summary = summarize(
                workspace=workspace,
                out_dir=out_dir,
                n_perm_requested=args.n_perm,
                real_result=real_result,
                perm_path=perm_path,
                null_mode=args.null_mode,
                exchangeability_manifest=args.exchangeability_manifest,
            )
            write_summary(summary, out_dir)
            print(
                json.dumps(
                    {
                        "completed": summary["n_perm_completed"],
                        "n_perm_requested": args.n_perm,
                        "aggregate_p": summary["aggregate_all_five"]["plus_one_p"],
                    },
                    default=_json_default,
                ),
                flush=True,
            )

    os.environ.pop("LIU_SHARED_PERMUTE_Y", None)
    os.environ.pop("LIU_FAMILY_BLOCK_PERMUTE_Y", None)
    summary = summarize(
        workspace=workspace,
        out_dir=out_dir,
        n_perm_requested=args.n_perm,
        real_result=real_result,
        perm_path=perm_path,
        null_mode=args.null_mode,
        exchangeability_manifest=args.exchangeability_manifest,
    )
    write_summary(summary, out_dir)
    print(json.dumps(summary, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
