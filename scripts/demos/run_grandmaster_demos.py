#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path
from typing import Iterable

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    # Ensure we import this checkout (not an installed brain_researcher).
    sys.path.insert(0, str(_REPO_ROOT))

from brain_researcher.services.tools.executor import execute_tool  # noqa: E402


def _write_min_dataset_description(path: Path, name: str) -> None:
    path.write_text(
        json.dumps({"Name": name, "BIDSVersion": "1.6.0"}, indent=2) + "\n",
        encoding="utf-8",
    )


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _read_participants_labels(participants_tsv: Path) -> dict[str, str]:
    with participants_tsv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        labels: dict[str, str] = {}
        for row in reader:
            pid = row.get("participant_id")
            if not pid:
                continue
            labels[pid] = row.get("diagnosis", "")
        return labels


def _make_qc_tsv(subjects: Iterable[str], out_tsv: Path) -> None:
    out_tsv.parent.mkdir(parents=True, exist_ok=True)
    with out_tsv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["participant_id", "fd_mean", "dvars_mean"], delimiter="\t"
        )
        writer.writeheader()
        for i, sub in enumerate(subjects):
            # Toy values to exercise the QC pipeline end-to-end.
            writer.writerow(
                {
                    "participant_id": sub,
                    "fd_mean": round(0.05 + 0.02 * i, 4),
                    "dvars_mean": round(1.0 + 0.1 * i, 4),
                }
            )


def _connectome_features(mat_path: Path) -> np.ndarray:
    mat = np.load(mat_path)
    mat = np.squeeze(mat)
    if mat.ndim != 2:
        raise ValueError(f"Expected 2D connectome; got {mat.ndim}D at {mat_path}")
    iu = np.triu_indices_from(mat, k=1)
    return mat[iu]


def _label_to_binary(label: str) -> int:
    # Demo mapping for ds000030 subset.
    if label.upper() == "CONTROL":
        return 0
    if label.upper() == "ADHD":
        return 1
    raise ValueError(f"Unsupported diagnosis label for demo ML: {label!r}")


def _resolve_derivative_dir(
    *,
    derivatives_root: Path,
    pipeline: str,
    dataset: str,
    explicit_dir: str | None,
    allow_scan: bool,
    scan_limit: int,
) -> Path | None:
    if explicit_dir:
        p = Path(explicit_dir)
        if not p.exists():
            raise SystemExit(f"{pipeline} dir not found: {p}")
        return p

    base = derivatives_root / pipeline
    if not base.exists():
        return None

    # Common layouts:
    # - <derivatives_root>/<pipeline>/<dataset>/...
    # - <derivatives_root>/<pipeline>/<dataset>-<pipeline>/...
    for direct in (base / dataset, base / f"{dataset}-{pipeline}"):
        if direct.exists():
            return direct

    if not allow_scan:
        return None

    # Best-effort heuristic: some stores place datasets under an intermediate prefix.
    try:
        scanned = 0
        for entry in base.iterdir():
            scanned += 1
            if scanned > max(1, scan_limit):
                break
            if not entry.is_dir():
                continue
            for name in (dataset, f"{dataset}-{pipeline}"):
                candidate = entry / name
                if candidate.exists():
                    return candidate
    except OSError:
        return None

    return None


def _pick_first_existing(globs: Iterable[Path]) -> Path | None:
    for p in globs:
        if p.exists():
            return p
    return None


def _copy_fmriprep_rest_subset(
    *,
    src_fmriprep_dir: Path,
    dst_fmriprep_dir: Path,
    subjects: Iterable[str],
) -> dict[str, Path]:
    """Copy a minimal set of fMRIPrep outputs needed by our demo workflows."""

    mapping: dict[str, Path] = {}

    if (src_fmriprep_dir / "dataset_description.json").exists():
        _copy_file(
            src_fmriprep_dir / "dataset_description.json",
            dst_fmriprep_dir / "dataset_description.json",
        )

    for sub in subjects:
        func_dir = src_fmriprep_dir / sub / "func"
        if not func_dir.exists():
            continue

        # Prefer preproc rest bolds.
        matches = sorted(func_dir.glob(f"{sub}_task-rest*desc-preproc_bold.nii.gz"))
        if not matches:
            matches = sorted(func_dir.glob(f"{sub}_*desc-preproc_bold.nii.gz"))
        if not matches:
            continue

        src_img = matches[0]
        rel = src_img.relative_to(src_fmriprep_dir)
        dst_img = dst_fmriprep_dir / rel
        _copy_file(src_img, dst_img)

        # Optional JSON sidecar.
        json_sidecar = src_img.with_suffix("").with_suffix(".json")
        if json_sidecar.exists():
            _copy_file(
                json_sidecar,
                dst_fmriprep_dir / json_sidecar.relative_to(src_fmriprep_dir),
            )

        mapping[sub] = dst_img

    return mapping


def _copy_mriqc_group_tsv(*, src_mriqc_dir: Path, dst_dir: Path) -> Path | None:
    candidates = [
        src_mriqc_dir / "group_bold.tsv",
        src_mriqc_dir / "group_T1w.tsv",
    ]
    found = _pick_first_existing(candidates)
    if not found:
        # Broader match at top-level.
        found = _pick_first_existing(
            sorted(src_mriqc_dir.glob("*group*bold*.tsv"))
            + sorted(src_mriqc_dir.glob("*group*bold*.tsv"))
        )
    if not found:
        return None

    out = dst_dir / found.name
    _copy_file(found, out)
    return out


def _copy_xcpd_qc_subset(
    *,
    src_xcpd_dir: Path,
    dst_xcpd_dir: Path,
    subjects: Iterable[str],
) -> list[Path]:
    """Copy only the QC files needed by xcpd_qc (keeps directory structure)."""

    copied: list[Path] = []

    # XCP-D outputs are often under <root>/xcp_d/.
    xcp_root = src_xcpd_dir / "xcp_d"
    if not xcp_root.exists():
        xcp_root = src_xcpd_dir

    for sub in subjects:
        sub_dir = xcp_root / sub
        if not sub_dir.exists():
            continue
        qc_matches = list(sub_dir.rglob("*_qc.json")) + list(sub_dir.rglob("*_qc.tsv"))
        if not qc_matches:
            continue

        # Copy the first qc file; it's enough for a smoke run.
        src_qc = sorted(qc_matches)[0]
        rel = src_qc.relative_to(src_xcpd_dir)
        dst_qc = dst_xcpd_dir / rel
        _copy_file(src_qc, dst_qc)
        copied.append(dst_qc)

    return copied


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the 5 Grandmaster workflows end-to-end on a tiny ds000030 subset.\n"
            "Always copies data out to a work dir before running tools."
        )
    )
    parser.add_argument(
        "--openneuro-root",
        default="/app/data/openneuro",
        help="Mounted OpenNeuro datasets root",
    )
    parser.add_argument(
        "--derivatives-root",
        default="/app/data/OpenNeuroDerivatives",
        help="OpenNeuro derivatives root (fmriprep/mriqc/xcpd)",
    )
    parser.add_argument("--dataset", default="ds000030", help="OpenNeuro dataset ID")
    parser.add_argument(
        "--work-dir",
        default=None,
        help="Work directory (default: /tmp/br_realdata_<dataset>)",
    )
    parser.add_argument(
        "--subjects",
        nargs="+",
        default=["sub-10159", "sub-10171", "sub-10189", "sub-70001", "sub-70004", "sub-70007"],
        help="Subjects to copy and run for rest connectome + QC + ML",
    )
    parser.add_argument(
        "--glm-subject",
        default="sub-10159",
        help="Subject to use for the task GLM demo",
    )
    parser.add_argument("--glm-task", default="bart", help="Task name for GLM demo")
    parser.add_argument(
        "--atlas-name",
        default="synthetic",
        help="Atlas name for rest connectome (default synthetic for speed/stability)",
    )
    parser.add_argument(
        "--n-splits", type=int, default=3, help="CV folds for ML decoding demo"
    )
    parser.add_argument(
        "--use-derivatives",
        action="store_true",
        help=(
            "Prefer real derivatives from --derivatives-root when available "
            "(still copies a minimal subset out to work-dir)."
        ),
    )
    parser.add_argument(
        "--derivatives-pipelines",
        default="mriqc,xcpd,fmriprep",
        help=(
            "Comma-separated pipelines to try under --derivatives-root "
            "(e.g. 'mriqc,xcpd,fmriprep'). If a mount is flaky/slow, exclude it."
        ),
    )
    parser.add_argument(
        "--derivatives-scan",
        action="store_true",
        help=(
            "Allow a bounded scan under --derivatives-root/<pipeline>/ to locate the "
            "dataset under an intermediate prefix. Useful for some object stores, but "
            "can be slow on large mounts."
        ),
    )
    parser.add_argument(
        "--derivatives-scan-limit",
        type=int,
        default=100,
        help="Max directory entries to scan per pipeline when --derivatives-scan is set",
    )
    parser.add_argument(
        "--fmriprep-dir",
        default=None,
        help="Explicit fMRIPrep derivatives dir (overrides auto-detection)",
    )
    parser.add_argument(
        "--mriqc-dir",
        default=None,
        help="Explicit MRIQC derivatives dir (overrides auto-detection)",
    )
    parser.add_argument(
        "--xcpd-dir",
        default=None,
        help="Explicit XCP-D derivatives dir (overrides auto-detection)",
    )
    parser.add_argument(
        "--skip-copy",
        action="store_true",
        help="Skip copying (assume work-dir already prepared)",
    )
    args = parser.parse_args(argv)

    openneuro_root = Path(args.openneuro_root)
    derivatives_root = Path(args.derivatives_root)
    ds_root = openneuro_root / args.dataset
    if not ds_root.exists():
        raise SystemExit(f"Dataset root not found: {ds_root}")

    work_dir = Path(args.work_dir) if args.work_dir else Path(f"/tmp/br_realdata_{args.dataset}")
    bids_dir = work_dir / "bids_min"
    fmriprep_dir = work_dir / "fmriprep_min"
    derivatives_min = work_dir / "derivatives_min"
    fmriprep_from_derivatives = derivatives_min / "fmriprep"
    mriqc_from_derivatives = derivatives_min / "mriqc"
    xcpd_from_derivatives = derivatives_min / "xcpd"
    out_dir = work_dir / "out"

    selected_rest_imgs: dict[str, Path] = {}
    mriqc_group_tsv: Path | None = None
    xcpd_qc_files: list[Path] = []

    if not args.skip_copy:
        print(f"Preparing work_dir: {work_dir}", flush=True)
        if work_dir.exists():
            shutil.rmtree(work_dir)
        bids_dir.mkdir(parents=True, exist_ok=True)
        fmriprep_dir.mkdir(parents=True, exist_ok=True)
        out_dir.mkdir(parents=True, exist_ok=True)

        _write_min_dataset_description(bids_dir / "dataset_description.json", f"{args.dataset}_min_sample")

        participants_src = ds_root / "participants.tsv"
        if not participants_src.exists():
            raise SystemExit(f"participants.tsv not found: {participants_src}")
        _copy_file(participants_src, bids_dir / "participants.tsv")

        # Copy one task for GLM.
        glm_sub = args.glm_subject
        glm_func = ds_root / glm_sub / "func"
        glm_bold = glm_func / f"{glm_sub}_task-{args.glm_task}_bold.nii.gz"
        glm_json = glm_func / f"{glm_sub}_task-{args.glm_task}_bold.json"
        glm_events = glm_func / f"{glm_sub}_task-{args.glm_task}_events.tsv"
        if not glm_bold.exists() or not glm_json.exists() or not glm_events.exists():
            raise SystemExit(
                f"Missing GLM demo files under {glm_func} for task={args.glm_task}"
            )
        _copy_file(glm_bold, bids_dir / glm_sub / "func" / glm_bold.name)
        _copy_file(glm_json, bids_dir / glm_sub / "func" / glm_json.name)
        _copy_file(glm_events, bids_dir / glm_sub / "func" / glm_events.name)

        if args.use_derivatives:
            print(
                "Attempting to use real derivatives (copying minimal subset out first)...",
                flush=True,
            )
            pipelines = {
                p.strip().lower()
                for p in str(args.derivatives_pipelines).split(",")
                if p.strip()
            }

            if "fmriprep" in pipelines:
                src_fmriprep = _resolve_derivative_dir(
                    derivatives_root=derivatives_root,
                    pipeline="fmriprep",
                    dataset=args.dataset,
                    explicit_dir=args.fmriprep_dir,
                    allow_scan=bool(args.derivatives_scan),
                    scan_limit=int(args.derivatives_scan_limit),
                )
            else:
                src_fmriprep = None
            if src_fmriprep:
                print(f"Found fmriprep dir: {src_fmriprep}", flush=True)
                selected_rest_imgs = _copy_fmriprep_rest_subset(
                    src_fmriprep_dir=src_fmriprep,
                    dst_fmriprep_dir=fmriprep_from_derivatives,
                    subjects=args.subjects,
                )
                print(
                    f"Copied {len(selected_rest_imgs)} rest preproc file(s) from fmriprep",
                    flush=True,
                )
            else:
                print(
                    f"[warn] No fmriprep derivatives found under {derivatives_root} "
                    f"for dataset={args.dataset}; using raw BIDS rest images.",
                    file=sys.stderr,
                )

            if "mriqc" in pipelines:
                src_mriqc = _resolve_derivative_dir(
                    derivatives_root=derivatives_root,
                    pipeline="mriqc",
                    dataset=args.dataset,
                    explicit_dir=args.mriqc_dir,
                    allow_scan=bool(args.derivatives_scan),
                    scan_limit=int(args.derivatives_scan_limit),
                )
            else:
                src_mriqc = None
            if src_mriqc:
                print(f"Found mriqc dir: {src_mriqc}", flush=True)
                mriqc_group_tsv = _copy_mriqc_group_tsv(
                    src_mriqc_dir=src_mriqc,
                    dst_dir=mriqc_from_derivatives,
                )
                if not mriqc_group_tsv:
                    print(
                        f"[warn] MRIQC dir found but no group TSV detected: {src_mriqc}",
                        file=sys.stderr,
                    )
                else:
                    print(f"Copied MRIQC group TSV: {mriqc_group_tsv}", flush=True)
            else:
                print(
                    f"[warn] No mriqc derivatives found under {derivatives_root} "
                    f"for dataset={args.dataset}; using toy QC TSV.",
                    file=sys.stderr,
                )

            if "xcpd" in pipelines:
                src_xcpd = _resolve_derivative_dir(
                    derivatives_root=derivatives_root,
                    pipeline="xcpd",
                    dataset=args.dataset,
                    explicit_dir=args.xcpd_dir,
                    allow_scan=bool(args.derivatives_scan),
                    scan_limit=int(args.derivatives_scan_limit),
                )
            else:
                src_xcpd = None
            if src_xcpd:
                print(f"Found xcpd dir: {src_xcpd}", flush=True)
                xcpd_qc_files = _copy_xcpd_qc_subset(
                    src_xcpd_dir=src_xcpd,
                    dst_xcpd_dir=xcpd_from_derivatives,
                    subjects=args.subjects,
                )
                if not xcpd_qc_files:
                    print(
                        f"[warn] XCP-D dir found but no per-subject QC files copied: {src_xcpd}",
                        file=sys.stderr,
                    )
                else:
                    print(f"Copied {len(xcpd_qc_files)} XCP-D QC file(s)", flush=True)
            else:
                print(
                    f"[warn] No xcpd derivatives found under {derivatives_root} "
                    f"for dataset={args.dataset}; XCP-D workflow will run in command-preview mode.",
                    file=sys.stderr,
                )

        subjects_needing_raw_rest = [s for s in args.subjects if s not in selected_rest_imgs]
        print(
            f"Copying raw BIDS rest data for {len(subjects_needing_raw_rest)} subject(s)...",
            flush=True,
        )
        for sub in subjects_needing_raw_rest:
            src_func = ds_root / sub / "func"
            rest_bold = src_func / f"{sub}_task-rest_bold.nii.gz"
            rest_json = src_func / f"{sub}_task-rest_bold.json"
            if not rest_bold.exists() or not rest_json.exists():
                raise SystemExit(f"Missing rest files for {sub} under {src_func}")
            _copy_file(rest_bold, bids_dir / sub / "func" / rest_bold.name)
            _copy_file(rest_json, bids_dir / sub / "func" / rest_json.name)

        # XCP-D workflow still needs a fMRIPrep directory (at minimum for command generation).
        if selected_rest_imgs:
            # Reuse the copied derivatives as the fmriprep_dir for XCP-D planning.
            fmriprep_dir = fmriprep_from_derivatives
        else:
            # Minimal fMRIPrep-like dir for XCP-D command generation.
            (fmriprep_dir / "dataset_description.json").write_text(
                json.dumps(
                    {
                        "Name": "fmriprep_min_sample",
                        "BIDSVersion": "1.6.0",
                        "GeneratedBy": [{"Name": "fMRIPrep", "Version": "0.0"}],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            (fmriprep_dir / glm_sub / "func").mkdir(parents=True, exist_ok=True)
            _copy_file(
                ds_root
                / glm_sub
                / "func"
                / f"{glm_sub}_task-rest_bold.nii.gz",
                fmriprep_dir
                / glm_sub
                / "func"
                / f"{glm_sub}_task-rest_desc-preproc_bold.nii.gz",
            )

    # 1) REST connectomes
    rest_out_root = out_dir / "rest_connectome"
    rest_out_root.mkdir(parents=True, exist_ok=True)
    for sub in args.subjects:
        img = selected_rest_imgs.get(sub) or (
            bids_dir / sub / "func" / f"{sub}_task-rest_bold.nii.gz"
        )
        res = execute_tool(
            "workflow_rest_connectome_e2e",
            {
                "img": str(img),
                "atlas_name": args.atlas_name,
                "connectivity_kind": "correlation",
                "output_dir": str(rest_out_root / sub),
            },
        )
        if res.status != "success":
            raise SystemExit(f"rest_connectome failed for {sub}: {res.error}")

    # 2) Build ML inputs from connectomes (CONTROL vs ADHD only)
    participants_labels = _read_participants_labels(bids_dir / "participants.tsv")
    subs_ml: list[str] = []
    X_rows: list[np.ndarray] = []
    y_rows: list[int] = []
    for sub in args.subjects:
        diag = participants_labels.get(sub, "")
        if diag.upper() not in {"CONTROL", "ADHD"}:
            continue
        feats = _connectome_features(rest_out_root / sub / "connectivity_matrix.npy")
        subs_ml.append(sub)
        X_rows.append(feats)
        y_rows.append(_label_to_binary(diag))

    if len(subs_ml) < 4:
        raise SystemExit(
            f"Not enough CONTROL/ADHD samples for ML demo (got {len(subs_ml)})."
        )

    X = np.asarray(X_rows)
    y = np.asarray(y_rows)
    groups = np.zeros(len(subs_ml), dtype=int)

    ml_inputs = out_dir / "ml_inputs"
    ml_inputs.mkdir(parents=True, exist_ok=True)
    np.save(ml_inputs / "X.npy", X)
    np.save(ml_inputs / "y.npy", y)
    np.save(ml_inputs / "groups.npy", groups)
    (ml_inputs / "participants.txt").write_text("\n".join(subs_ml) + "\n", encoding="utf-8")

    # 3) ML workflow
    n_splits = max(2, min(int(args.n_splits), len(subs_ml)))
    ml_out = out_dir / "ml_workflow"
    res = execute_tool(
        "workflow_ml_decoding_pipeline",
        {
            "data_file": str(ml_inputs / "X.npy"),
            "labels_file": str(ml_inputs / "y.npy"),
            "groups_file": str(ml_inputs / "groups.npy"),
            "cv_type": "kfold",
            "n_splits": n_splits,
            "task_type": "classification",
            "output_dir": str(ml_out),
        },
    )
    if res.status != "success":
        raise SystemExit(f"ml_decoding_pipeline failed: {res.error}")

    # 4) Task GLM workflow (single-subject demo)
    glm_sub = args.glm_subject
    glm_bold_json = bids_dir / glm_sub / "func" / f"{glm_sub}_task-{args.glm_task}_bold.json"
    meta = json.loads(glm_bold_json.read_text(encoding="utf-8"))
    tr = float(meta.get("RepetitionTime", 2.0))
    glm_out = out_dir / "task_glm"
    res = execute_tool(
        "workflow_task_glm_group",
        {
            "img": str(bids_dir / glm_sub / "func" / f"{glm_sub}_task-{args.glm_task}_bold.nii.gz"),
            "events": str(bids_dir / glm_sub / "func" / f"{glm_sub}_task-{args.glm_task}_events.tsv"),
            "t_r": tr,
            "smoothing_fwhm": 5.0,
            "output_dir": str(glm_out),
        },
    )
    if res.status != "success":
        raise SystemExit(f"task_glm_group failed: {res.error}")

    # 5) QC workflow (toy QC TSV)
    qc_inputs = out_dir / "qc_inputs"
    qc_tsv = qc_inputs / "qc.tsv"
    if mriqc_group_tsv and mriqc_group_tsv.exists():
        qc_tsv.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(mriqc_group_tsv, qc_tsv)
    else:
        _make_qc_tsv(args.subjects, qc_tsv)
    qc_out = out_dir / "qc_workflow"
    res = execute_tool(
        "workflow_preprocessing_qc",
        {
            "bids_dir": str(bids_dir),
            "qc_tsv": str(qc_tsv),
            "outlier_metric": "fd_mean",
            "outlier_z": 2.0,
            "output_dir": str(qc_out),
        },
    )
    if res.status != "success":
        raise SystemExit(f"preprocessing_qc failed: {res.error}")

    print("")
    print("Grandmaster demo complete")
    print(f"- work_dir: {work_dir}")
    print(f"- bids_dir: {bids_dir}")
    print(f"- outputs: {out_dir}")
    print(f"- rest_connectome: {rest_out_root}")
    if selected_rest_imgs:
        print(f"- fmriprep_derivatives: {fmriprep_from_derivatives}")
    print(f"- ml_inputs: {ml_inputs}")
    print(f"- ml_workflow: {ml_out}")
    print(f"- task_glm: {glm_out}")
    print(f"- qc_dashboard: {qc_out / 'qc' / 'index.html'}")
    print(f"- xcpd_qc_json: {xcpd_out / 'xcpd_qc.json'}")
    if xcpd_existing_qc_report:
        print(f"- xcpd_existing_qc_json: {xcpd_existing_qc_report}")
    if xcpd_cmd:
        print(f"- xcpd_command: {xcpd_cmd}")
    print("")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
