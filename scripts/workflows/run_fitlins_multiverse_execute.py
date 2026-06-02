#!/usr/bin/env python3
"""Run a GLM multiverse execution loop and emit a run_manifest.json.

This script stitches together:
  1) seed spec discovery
  2) multiverse spec generation (priors-aware)
  3) optional FitLins execution
  4) run_manifest.json with decision points + outputs
  5) optional Yeo17 robustness summaries
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from brain_researcher.core.provenance import write_provenance
from brain_researcher.services.br_kg import query_service
from brain_researcher.services.tools.fitlins_tool import (
    FitLinsCreateSeedSpecTool,
    FitLinsGenerateMultiverseSpecsTool,
    FitLinsRunMultiverseTool,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fitlins_multiverse_execute")

def _ensure_bold_repetition_time(
    bids_root: Path,
    *,
    task: str,
    participant_labels: Optional[List[str]],
) -> None:
    """Ensure BOLD sidecar JSON files contain RepetitionTime.

    Some OpenNeuro datasets ship NIfTI files without JSON sidecars. FitLins
    (via pybids) requires `RepetitionTime` metadata to be present. We extract
    TR from the NIfTI header and write minimal sidecars when missing.
    """

    try:
        import nibabel as nib  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"nibabel required to infer RepetitionTime: {exc}") from exc

    glob_pat = f"**/func/*task-{task}*_bold.nii.gz"
    bold_files = sorted(bids_root.glob(glob_pat))
    if participant_labels:
        allowed = {f"sub-{lab}" if not lab.startswith("sub-") else lab for lab in participant_labels}
        bold_files = [p for p in bold_files if any(part in p.parts for part in allowed)]

    for bold in bold_files:
        json_path = bold.with_name(bold.name.replace("_bold.nii.gz", "_bold.json"))
        meta: Dict[str, Any] = {}
        if json_path.exists():
            try:
                meta = json.loads(json_path.read_text())
            except Exception:
                meta = {}
        if "RepetitionTime" in meta:
            continue
        img = nib.load(str(bold))
        zooms = img.header.get_zooms()
        if len(zooms) < 4 or not zooms[3]:
            raise RuntimeError(f"Unable to infer TR for {bold} from NIfTI header.")
        meta["RepetitionTime"] = float(zooms[3])
        meta.setdefault("TaskName", task)
        try:
            json_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            logger.info("Wrote missing RepetitionTime sidecar: %s", json_path)
        except OSError as exc:
            raise RuntimeError(
                f"Failed to write {json_path} ({exc}). Copy dataset to a writable location and retry."
            ) from exc


def _load_path_config(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        raise RuntimeError(f"Failed to read path_config at {path}: {exc}") from exc


def _resolve_bids_dir(dataset_id: str, data_root: Path, override: Optional[str]) -> Path:
    if override:
        candidate = Path(override).expanduser().resolve()
        if not candidate.exists():
            raise FileNotFoundError(f"bids_root not found: {candidate}")
        return candidate
    candidates = [
        data_root / "openneuro" / dataset_id,
        data_root / "openneuro_mount" / dataset_id,
        data_root / "input" / dataset_id,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(
        "BIDS root not found; checked: " + ", ".join(str(c) for c in candidates)
    )


def _resolve_derivatives_dir(dataset_id: str, data_root: Path, override: Optional[str]) -> Path:
    if override:
        candidate = Path(override).expanduser().resolve()
        if not candidate.exists():
            raise FileNotFoundError(f"derivatives_root not found: {candidate}")
        return candidate
    candidates = [
        data_root / "fmriprep" / dataset_id / "derivatives_alt",
        data_root / "fmriprep" / dataset_id / "derivatives",
        data_root / "openneuro" / dataset_id / "derivatives" / "fmriprep",
        data_root / "OpenNeuroDerivatives" / "fmriprep" / f"{dataset_id}-fmriprep",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(
        "fMRIPrep derivatives not found; checked: " + ", ".join(str(c) for c in candidates)
    )


def _parse_list_arg(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    items = [v.strip() for v in value.split(",") if v.strip()]
    return items or None


def _collect_axis_overrides(args: argparse.Namespace) -> Optional[Dict[str, List[str]]]:
    axis_overrides: Dict[str, List[str]] = {}
    hrf_levels = _parse_list_arg(args.axis_hrf)
    if hrf_levels:
        axis_overrides["hrf_basis"] = hrf_levels

    confound_levels = _parse_list_arg(args.axis_confounds)
    if confound_levels:
        axis_overrides["confounds"] = confound_levels

    high_pass_levels = _parse_list_arg(args.axis_high_pass)
    if high_pass_levels:
        axis_overrides["high_pass"] = high_pass_levels

    return axis_overrides or None


def _find_run_node(model: dict) -> Optional[dict]:
    for node in model.get("Nodes", []):
        if not isinstance(node, dict):
            continue
        level = str(node.get("Level", "")).lower()
        if level == "run":
            return node
    return None


def _extract_model_x_terms(model: dict) -> List[str]:
    run_node = _find_run_node(model)
    if not run_node:
        return []
    model_node = run_node.get("Model", {})
    x_terms = model_node.get("X", [])
    return [str(t) for t in x_terms if isinstance(t, (str, int, float))]


def _derive_model_id(spec_path: Path) -> str:
    stem = spec_path.stem.replace("_specs", "")
    if "-mv" in stem:
        suffix = stem.split("-mv")[-1]
        return f"mv{suffix}"
    return stem


def _read_variant_metadata(spec_path: Path) -> dict:
    try:
        data = json.loads(spec_path.read_text())
    except Exception:
        return {}
    meta = data.get("Metadata", {}).get("multiverse_variant", {})
    return meta if isinstance(meta, dict) else {}


def _scan_artifacts(output_dir: Path) -> List[Dict[str, Any]]:
    if not output_dir.exists():
        return []
    artifacts: List[Dict[str, Any]] = []
    for path in output_dir.rglob("*_stat-*_statmap.nii*"):
        name = path.name
        kind = "stat_map"
        if "_stat-z_" in name:
            kind = "stat_z_map"
        elif "_stat-effect_" in name:
            kind = "stat_effect_map"
        artifacts.append({"kind": kind, "path": str(path)})
    return artifacts


def _ensure_mv_aliases(
    fitlins_dir: Path,
    specs: List[str],
    plans: List[Dict[str, Any]],
) -> None:
    plans_map = {p.get("spec"): p for p in plans if p.get("spec")}
    for spec in specs:
        spec_path = Path(spec)
        model_id = _derive_model_id(spec_path)
        plan = plans_map.get(spec, {})
        output_dir = Path(plan.get("output", "")) if plan.get("output") else None
        if not output_dir or not output_dir.exists():
            continue
        alias = fitlins_dir / model_id
        if alias.exists():
            continue
        try:
            os.symlink(output_dir, alias, target_is_directory=True)
        except Exception as exc:
            logger.warning("Failed to symlink %s -> %s: %s", alias, output_dir, exc)


def _run_yeo17_summary(
    *,
    repo_root: Path,
    run_base: Path,
    manifest_path: Path,
    dataset_id: str,
    task: str,
    write_neo4j: bool,
) -> Dict[str, Any]:
    script = repo_root / "scripts" / "ingest_fitlins_multiverse_runonly_yeo17.py"
    cmd = [
        sys.executable,
        str(script),
        "--run-base",
        str(run_base),
        "--manifest",
        str(manifest_path),
        "--dataset-id",
        dataset_id,
        "--task",
        task,
    ]
    if not write_neo4j:
        cmd.append("--skip-neo4j")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    status = "success" if proc.returncode == 0 else "error"
    result: Dict[str, Any] = {
        "status": status,
        "returncode": proc.returncode,
        "command": cmd,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
    return result


def _build_run_manifest(
    *,
    run_id: str,
    dataset_id: str,
    task: str,
    seed: int,
    runtime: str,
    analysis_level: str,
    bids_root: Path,
    derivatives_root: Path,
    execute: bool,
    specs: List[str],
    plans: List[Dict[str, Any]],
    results: List[Dict[str, Any]],
    run_dir: Path,
    priors_payload: Optional[Dict[str, Any]],
    yeo17_payload: Optional[Dict[str, Any]],
    print_model_x: bool,
    axis_overrides: Optional[Dict[str, List[str]]],
) -> dict:
    plans_map = {p.get("spec"): p for p in plans if p.get("spec")}
    results_map = {r.get("spec"): r for r in results if r.get("spec")}

    variants: List[Dict[str, Any]] = []
    for spec in specs:
        spec_path = Path(spec)
        model_id = _derive_model_id(spec_path)
        meta = _read_variant_metadata(spec_path)
        decision_points = {}
        for key in ("hrf", "hrf_basis", "confounds", "high_pass", "confounds_families"):
            if key in meta:
                decision_points[key] = meta.get(key)

        model_x = []
        try:
            model_x = _extract_model_x_terms(json.loads(spec_path.read_text()))
        except Exception:
            model_x = []

        plan = plans_map.get(spec, {})
        output_dir = Path(plan.get("output", "")) if plan.get("output") else None
        result = results_map.get(spec, {})
        exit_code = result.get("exit_code")
        status = "planned"
        if execute:
            status = "success" if exit_code == 0 else "failed"
        artifacts = _scan_artifacts(output_dir) if output_dir else []

        variant = {
            "model_id": model_id,
            "variant_id": meta.get("variant_id"),
            "selection_reason": meta.get("selection_reason"),
            "decision_points": decision_points,
            "spec_path": str(spec_path),
            "output_dir": str(output_dir) if output_dir else None,
            "command": plan.get("cmd"),
            "status": status,
            "exit_code": exit_code,
            "artifacts": artifacts,
        }
        if print_model_x:
            variant["model_x"] = model_x
        variants.append(variant)

    payload: Dict[str, Any] = {
        "run_id": run_id,
        "dataset_id": dataset_id,
        "task": task,
        "seed": seed,
        "k": len(specs),
        "runtime": runtime,
        "analysis_level": analysis_level,
        "execute": execute,
        "bids_root": str(bids_root),
        "derivatives_root": str(derivatives_root),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "variants": variants,
    }
    if priors_payload:
        payload["priors_source"] = priors_payload.get("source")
        payload["priors_scope"] = priors_payload.get("scope")
        payload["support"] = priors_payload.get("support")
        payload["coverage"] = priors_payload.get("coverage")
    if axis_overrides:
        payload["axis_overrides"] = axis_overrides
    if yeo17_payload:
        payload["yeo17"] = yeo17_payload
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--k", type=int, default=6)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--axis-hrf",
        default=None,
        help=(
            "Comma-separated HRF axis levels, e.g. "
            "'canonical,derivs,glover,fir'."
        ),
    )
    parser.add_argument(
        "--axis-confounds",
        default=None,
        help="Comma-separated confounds axis levels, e.g. '24mot'.",
    )
    parser.add_argument(
        "--axis-high-pass",
        default=None,
        help="Comma-separated high-pass axis levels, e.g. '100,128'.",
    )
    parser.add_argument("--analysis-level", default="run")
    parser.add_argument("--runtime", default="wrapper")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--bids-root", default=None)
    parser.add_argument("--derivatives-root", default=None)
    parser.add_argument(
        "--path-config",
        default=None,
        help="Optional path_config.json (defaults to external/openneuro_glmfitlins/path_config.json)",
    )
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--seed-spec", default=None)
    parser.add_argument("--allow-stub", action="store_true")
    parser.add_argument("--require-priors", action="store_true")
    parser.add_argument("--no-priors", action="store_true")
    parser.add_argument("--include-seed", action="store_true")
    parser.add_argument("--participant-label", default=None)
    parser.add_argument("--exclude-participant", default=None)
    parser.add_argument("--print-model-x", action="store_true")
    parser.add_argument("--skip-yeo17", action="store_true")
    parser.add_argument(
        "--yeo17-write-neo4j",
        action="store_true",
        help="Write Yeo17 edges into Neo4j (default: skip Neo4j writes).",
    )
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    default_config = repo_root / "external" / "openneuro_glmfitlins" / "path_config.json"
    config_path = Path(args.path_config) if args.path_config else default_config
    config = _load_path_config(config_path) if config_path.exists() else None

    if not config and (not args.bids_root or not args.derivatives_root):
        logger.error("path_config.json not found and --bids-root/--derivatives-root not provided.")
        return 2

    data_root = None
    if config:
        data_root_value = config.get("datasets_folder")
        if not data_root_value:
            logger.error("path_config.json missing datasets_folder")
            return 2
        data_root = Path(data_root_value).expanduser().resolve()

    try:
        if data_root:
            bids_root = _resolve_bids_dir(args.dataset_id, data_root, args.bids_root)
            derivatives_root = _resolve_derivatives_dir(
                args.dataset_id, data_root, args.derivatives_root
            )
        else:
            bids_root = Path(args.bids_root).expanduser().resolve()
            derivatives_root = Path(args.derivatives_root).expanduser().resolve()
            if not bids_root.exists() or not derivatives_root.exists():
                raise FileNotFoundError("bids_root/derivatives_root do not exist")
    except Exception as exc:
        logger.error("Path resolution failed: %s", exc)
        return 2

    try:
        _ensure_bold_repetition_time(
            bids_root,
            task=args.task,
            participant_labels=_parse_list_arg(args.participant_label),
        )
    except Exception as exc:
        logger.error("BIDS metadata fixup failed: %s", exc)
        return 2

    run_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"glmrun:{args.dataset_id}:{args.task}:{run_ts}"
    default_run_root = repo_root / "outputs" / f"_a4_{args.dataset_id}_{args.task}" / f"run_{run_ts}"
    run_dir = Path(args.output_root).expanduser().resolve() if args.output_root else default_run_root
    spec_dir = run_dir / "specs"
    fitlins_dir = run_dir / "fitlins"
    spec_dir.mkdir(parents=True, exist_ok=True)
    fitlins_dir.mkdir(parents=True, exist_ok=True)

    # Seed spec
    seed_tool = FitLinsCreateSeedSpecTool()
    seed_result = seed_tool._run(
        study_id=args.dataset_id,
        task=args.task,
        seed_spec=args.seed_spec,
        allow_stub=args.allow_stub,
    )
    if seed_result.status != "success":
        logger.error("Seed spec error: %s", seed_result.error)
        return 2
    seed_spec = seed_result.data["outputs"]["seed_spec"]

    # Priors (Neo4j-only via query_service)
    priors_payload = None
    priors = None
    axis_overrides = _collect_axis_overrides(args)
    if not args.no_priors:
        priors_payload = query_service.get_glm_priors(
            task=args.task,
            study_id=args.dataset_id,
            db=query_service.get_default_db(),
        )
        if priors_payload and priors_payload.get("priors"):
            priors = priors_payload.get("priors")
        elif args.require_priors:
            logger.error("No priors returned from Neo4j (require-priors enabled).")
            return 2
        else:
            logger.warning("No priors returned from Neo4j; proceeding with uniform variants.")

    # Generate specs
    gen_tool = FitLinsGenerateMultiverseSpecsTool()
    gen_result = gen_tool._run(
        study_id=args.dataset_id,
        task=args.task,
        seed_spec=seed_spec,
        output_dir=str(spec_dir),
        max_models=args.k,
        include_seed=args.include_seed,
        priors=priors,
        use_priors=not args.no_priors,
        seed=args.seed,
        axis_overrides=axis_overrides,
    )
    if gen_result.status != "success":
        logger.error("Spec generation failed: %s", gen_result.error)
        return 2
    spec_paths = gen_result.data.get("outputs", {}).get("multiverse_specs", [])
    if not spec_paths:
        logger.error("No spec paths produced.")
        return 2

    # Run FitLins
    run_tool = FitLinsRunMultiverseTool()
    run_result = run_tool._run(
        study_id=args.dataset_id,
        task=args.task,
        bids_root=str(bids_root),
        derivatives_root=str(derivatives_root),
        multiverse_specs=spec_paths,
        analysis_level=args.analysis_level,
        participant_label=_parse_list_arg(args.participant_label),
        exclude_participant=_parse_list_arg(args.exclude_participant),
        execute=args.execute,
        output_root=str(fitlins_dir),
        runtime=args.runtime,
    )
    exit_code = 0
    if args.execute and run_result.status != "success":
        logger.error("FitLins run completed with status=%s", run_result.status)
        exit_code = 1

    outputs = run_result.data.get("outputs", {})
    plans = outputs.get("plans", [])
    results = outputs.get("multiverse_results", [])

    yeo17_payload = None
    if args.execute and not args.skip_yeo17:
        manifest_for_yeo17 = spec_dir / "multiverse_manifest.json"
        if not manifest_for_yeo17.exists():
            yeo17_payload = {
                "status": "skipped",
                "error": f"manifest not found: {manifest_for_yeo17}",
            }
        else:
            _ensure_mv_aliases(fitlins_dir, spec_paths, plans)
            yeo17_payload = _run_yeo17_summary(
                repo_root=repo_root,
                run_base=fitlins_dir,
                manifest_path=manifest_for_yeo17,
                dataset_id=args.dataset_id,
                task=args.task,
                write_neo4j=args.yeo17_write_neo4j,
            )
            summary_path = fitlins_dir / "yeo17_summary.csv"
            edges_path = fitlins_dir / "yeo17_edges.csv"
            robustness_json = fitlins_dir / "robustness_yeo17.json"
            robustness_md = fitlins_dir / "robustness_yeo17.md"
            yeo17_payload["summary_path"] = (
                str(summary_path) if summary_path.exists() else None
            )
            yeo17_payload["edges_path"] = str(edges_path) if edges_path.exists() else None
            yeo17_payload["robustness_json"] = (
                str(robustness_json) if robustness_json.exists() else None
            )
            yeo17_payload["robustness_md"] = (
                str(robustness_md) if robustness_md.exists() else None
            )

    run_manifest = _build_run_manifest(
        run_id=run_id,
        dataset_id=args.dataset_id,
        task=args.task,
        seed=args.seed,
        runtime=args.runtime,
        analysis_level=args.analysis_level,
        bids_root=bids_root,
        derivatives_root=derivatives_root,
        execute=args.execute,
        specs=spec_paths,
        plans=plans,
        results=results,
        run_dir=run_dir,
        priors_payload=priors_payload,
        yeo17_payload=yeo17_payload,
        print_model_x=args.print_model_x,
        axis_overrides=axis_overrides,
    )

    prov_path = write_provenance(
        run_dir,
        [Path(p) for p in spec_paths],
        command=[sys.executable, *sys.argv],
        seeds={"variant_seed": args.seed},
        extra={"run_id": run_id},
    )
    run_manifest["provenance_path"] = str(prov_path)

    manifest_path = run_dir / "run_manifest.json"
    manifest_path.write_text(json.dumps(run_manifest, indent=2))
    logger.info("Run manifest written: %s", manifest_path)
    if args.print_model_x:
        for variant in run_manifest.get("variants", []):
            logger.info("Variant %s Model.X: %s", variant.get("model_id"), variant.get("model_x"))

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
