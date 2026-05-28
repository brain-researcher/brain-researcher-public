#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence

import nibabel as nib
import numpy as np
import pandas as pd
from nilearn.connectome import ConnectivityMeasure
from nilearn.maskers import NiftiLabelsMasker

from brain_researcher.core.analysis.connectivity_contracts import (
    FeatureContract,
    compute_estimator_diagnostics,
    safe_fisher_z,
    write_feature_contract,
)
from brain_researcher.services.tools.atlas_utils import (
    default_atlas_output_root,
    repo_data_dir,
)


DEFAULT_RESOLUTIONS = (100, 200, 400, 1000)
CONF_RESERVE_PREFIXES = ("a_comp_cor_",)


@dataclass(frozen=True)
class RestRun:
    subject: str
    session: str | None
    run_label: str
    bold_path: Path
    confounds_path: Path | None
    tr: float
    n_volumes: int
    minutes: float


def default_schaefer_root() -> Path:
    candidates = [
        default_atlas_output_root() / "schaefer_2018",
        repo_data_dir() / "neurokg" / "raw" / "nilearn_atlases" / "schaefer_2018",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract subject-level Schaefer connectivity matrices from resting-state "
            "fMRIPrep derivatives."
        )
    )
    parser.add_argument(
        "--fmriprep-root",
        required=True,
        type=Path,
        help="Path to the fMRIPrep derivatives root, e.g. ds000224-fmriprep.",
    )
    parser.add_argument(
        "--output-root",
        required=True,
        type=Path,
        help="Directory where manifests, timeseries, and matrices will be written.",
    )
    parser.add_argument(
        "--atlas-root",
        type=Path,
        default=default_schaefer_root(),
        help=(
            "Directory containing local Schaefer atlas NIfTI files. Defaults to "
            "/app/data/atlases/schaefer_2018 when available."
        ),
    )
    parser.add_argument(
        "--task",
        default="rest",
        help="Task label to match in derivative filenames. Default: rest.",
    )
    parser.add_argument(
        "--subjects",
        nargs="*",
        default=None,
        help="Optional list of subject labels such as sub-MSC01 or MSC01.",
    )
    parser.add_argument(
        "--sessions",
        nargs="*",
        default=None,
        help="Optional list of session labels such as ses-func01 or func01.",
    )
    parser.add_argument(
        "--resolutions",
        nargs="+",
        type=int,
        default=list(DEFAULT_RESOLUTIONS),
        help="Schaefer parcel counts to extract. Default: 100 200 400 1000.",
    )
    parser.add_argument(
        "--min-total-minutes",
        type=float,
        default=30.0,
        help="Skip subjects with less than this much total resting data. Default: 30.",
    )
    parser.add_argument(
        "--high-pass",
        type=float,
        default=0.01,
        help="High-pass filter cutoff in Hz. Default: 0.01.",
    )
    parser.add_argument(
        "--low-pass",
        type=float,
        default=0.1,
        help="Low-pass filter cutoff in Hz. Default: 0.1.",
    )
    parser.add_argument(
        "--kind",
        default="correlation",
        help="ConnectivityMeasure kind. Default: correlation.",
    )
    parser.add_argument(
        "--no-fisher-z",
        action="store_true",
        help="Disable Fisher z-transform for correlation-like matrices.",
    )
    parser.add_argument(
        "--no-standardize",
        action="store_true",
        help="Disable standardization inside NiftiLabelsMasker.",
    )
    parser.add_argument(
        "--no-detrend",
        action="store_true",
        help="Disable detrending inside NiftiLabelsMasker.",
    )
    parser.add_argument(
        "--acompcor-components",
        type=int,
        default=6,
        help="Number of aCompCor components to include when available. Default: 6.",
    )
    parser.add_argument(
        "--write-run-timeseries",
        action="store_true",
        help="Also persist per-run ROI timeseries arrays.",
    )
    return parser.parse_args()


def normalize_subjects(subjects: Sequence[str] | None) -> set[str] | None:
    if not subjects:
        return None
    normalized = set()
    for subject in subjects:
        subject = subject.strip()
        if not subject:
            continue
        normalized.add(subject if subject.startswith("sub-") else f"sub-{subject}")
    return normalized


def normalize_sessions(sessions: Sequence[str] | None) -> set[str] | None:
    if not sessions:
        return None
    normalized = set()
    for session in sessions:
        session = session.strip()
        if not session:
            continue
        normalized.add(session if session.startswith("ses-") else f"ses-{session}")
    return normalized


def atlas_path(atlas_root: Path, resolution: int) -> Path:
    atlas = (
        atlas_root
        / f"Schaefer2018_{resolution}Parcels_7Networks_order_FSLMNI152_2mm.nii.gz"
    )
    if not atlas.exists():
        raise FileNotFoundError(f"Atlas not found for {resolution} parcels: {atlas}")
    return atlas


def find_rest_bold_files(fmriprep_root: Path, task: str) -> list[Path]:
    patterns = [
        f"sub-*/ses-*/func/*task-{task}_space-MNI152NLin2009cAsym*_desc-preproc_bold.nii.gz",
        f"sub-*/func/*task-{task}_space-MNI152NLin2009cAsym*_desc-preproc_bold.nii.gz",
        f"sub-*/ses-*/func/*task-{task}_desc-preproc_bold.nii.gz",
        f"sub-*/func/*task-{task}_desc-preproc_bold.nii.gz",
    ]
    seen: set[Path] = set()
    matches: list[Path] = []
    for pattern in patterns:
        for path in sorted(fmriprep_root.glob(pattern)):
            if path in seen:
                continue
            seen.add(path)
            matches.append(path)
    return matches


def derive_confound_path(bold_path: Path) -> Path | None:
    name = bold_path.name
    patterns = [
        r"(_space-[^_]+)?(_res-[^_]+)?_desc-preproc_bold\.nii\.gz$",
        r"_desc-preproc_bold\.nii\.gz$",
    ]
    for pattern in patterns:
        prefix = re.sub(pattern, "", name)
        if prefix == name:
            continue
        candidate = bold_path.with_name(f"{prefix}_desc-confounds_timeseries.tsv")
        if candidate.exists():
            return candidate
    return None


def parse_run_metadata(bold_path: Path) -> RestRun:
    parts = bold_path.parts
    subject = next(part for part in parts if part.startswith("sub-"))
    session = next((part for part in parts if part.startswith("ses-")), None)

    img = nib.load(str(bold_path))
    n_volumes = int(img.shape[3])
    zooms = img.header.get_zooms()
    if len(zooms) < 4:
        raise ValueError(f"Could not read TR from image header: {bold_path}")
    tr = float(zooms[3])

    run_match = re.search(r"(_run-[^_]+)?_desc-preproc_bold\.nii\.gz$", bold_path.name)
    run_label = run_match.group(1)[1:] if run_match and run_match.group(1) else "run-01"

    return RestRun(
        subject=subject,
        session=session,
        run_label=run_label,
        bold_path=bold_path,
        confounds_path=derive_confound_path(bold_path),
        tr=tr,
        n_volumes=n_volumes,
        minutes=(n_volumes * tr) / 60.0,
    )


def enumerate_runs(
    fmriprep_root: Path,
    task: str,
    subjects_filter: set[str] | None,
    sessions_filter: set[str] | None,
) -> list[RestRun]:
    runs: list[RestRun] = []
    for bold_path in find_rest_bold_files(fmriprep_root, task):
        run = parse_run_metadata(bold_path)
        if subjects_filter and run.subject not in subjects_filter:
            continue
        if sessions_filter and run.session not in sessions_filter:
            continue
        runs.append(run)
    return runs


def select_confounds(
    confounds_path: Path | None, acompcor_components: int
) -> np.ndarray | None:
    if confounds_path is None or not confounds_path.exists():
        return None
    frame = (
        pd.read_csv(confounds_path, sep="\t").select_dtypes(include=[np.number]).copy()
    )
    if frame.empty:
        return None

    preferred: list[str] = []

    motion_regex = re.compile(
        r"^(trans|rot)_[xyz](?:_derivative1|_power2|_derivative1_power2)?$"
    )
    preferred.extend([col for col in frame.columns if motion_regex.match(col)])

    for col in ("white_matter", "csf"):
        if col in frame.columns:
            preferred.append(col)

    acompcor = sorted(
        col
        for col in frame.columns
        if any(col.startswith(prefix) for prefix in CONF_RESERVE_PREFIXES)
    )
    preferred.extend(acompcor[:acompcor_components])

    for col in ("framewise_displacement", "dvars", "std_dvars"):
        if col in frame.columns:
            preferred.append(col)

    ordered = [col for col in preferred if col in frame.columns]
    if not ordered:
        return frame.fillna(0.0).to_numpy()
    return frame.loc[:, ordered].fillna(0.0).to_numpy()


def fisher_z_transform(
    matrix: np.ndarray,
    kind: str,
) -> tuple[np.ndarray, dict | None]:
    kind = kind.lower()
    if "correlation" not in kind:
        return matrix, None
    transformed, diagnostics = safe_fisher_z(
        matrix,
        f"connectivity_matrix(kind={kind})",
        return_diagnostics=True,
    )
    return transformed, diagnostics


def subject_total_minutes(runs: Iterable[RestRun]) -> float:
    return float(sum(run.minutes for run in runs))


def relative_run_id(run: RestRun) -> str:
    pieces = [run.subject]
    if run.session:
        pieces.append(run.session)
    pieces.append(run.run_label)
    return "_".join(pieces)


def write_dataframe(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".tsv":
        frame.to_csv(path, sep="\t", index=False)
    else:
        frame.to_csv(path, index=False)


def main() -> None:
    args = parse_args()

    fmriprep_root = args.fmriprep_root.expanduser().resolve()
    output_root = args.output_root.expanduser().resolve()
    atlas_root = args.atlas_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    subjects_filter = normalize_subjects(args.subjects)
    sessions_filter = normalize_sessions(args.sessions)

    runs = enumerate_runs(
        fmriprep_root=fmriprep_root,
        task=args.task,
        subjects_filter=subjects_filter,
        sessions_filter=sessions_filter,
    )
    if not runs:
        raise SystemExit("No matching rest BOLD files were found.")

    manifest_records = []
    runs_by_subject: dict[str, list[RestRun]] = {}
    for run in runs:
        runs_by_subject.setdefault(run.subject, []).append(run)
        manifest_records.append(
            {
                "subject": run.subject,
                "session": run.session,
                "run_label": run.run_label,
                "bold_path": str(run.bold_path),
                "confounds_path": str(run.confounds_path) if run.confounds_path else "",
                "tr_seconds": run.tr,
                "n_volumes": run.n_volumes,
                "minutes": run.minutes,
            }
        )

    write_dataframe(output_root / "run_manifest.tsv", pd.DataFrame(manifest_records))

    selected_subjects = {
        subject: sorted(
            subject_runs,
            key=lambda item: (
                item.session or "",
                item.run_label,
                item.bold_path.name,
            ),
        )
        for subject, subject_runs in runs_by_subject.items()
        if subject_total_minutes(subject_runs) >= args.min_total_minutes
    }
    if not selected_subjects:
        raise SystemExit(
            f"No subjects met the minimum rest threshold of {args.min_total_minutes} minutes."
        )

    subject_summary_rows = []
    for subject, subject_runs in selected_subjects.items():
        subject_summary_rows.append(
            {
                "subject": subject,
                "n_runs": len(subject_runs),
                "total_minutes": subject_total_minutes(subject_runs),
                "sessions": ",".join(
                    sorted(
                        {run.session for run in subject_runs if run.session is not None}
                    )
                ),
            }
        )
    write_dataframe(
        output_root / "selected_subjects.tsv", pd.DataFrame(subject_summary_rows)
    )

    summary: dict[str, object] = {
        "fmriprep_root": str(fmriprep_root),
        "task": args.task,
        "resolutions": list(args.resolutions),
        "min_total_minutes": args.min_total_minutes,
        "subjects": {},
    }

    for resolution in args.resolutions:
        atlas = atlas_path(atlas_root, resolution)
        for subject, subject_runs in selected_subjects.items():
            subject_dir = output_root / subject / f"schaefer_{resolution}"
            subject_dir.mkdir(parents=True, exist_ok=True)

            concatenated_runs: list[np.ndarray] = []
            run_rows = []

            for run in subject_runs:
                confounds = select_confounds(
                    run.confounds_path, args.acompcor_components
                )
                masker = NiftiLabelsMasker(
                    labels_img=str(atlas),
                    standardize=not args.no_standardize,
                    detrend=not args.no_detrend,
                    low_pass=args.low_pass,
                    high_pass=args.high_pass,
                    t_r=run.tr,
                )
                timeseries = np.asarray(
                    masker.fit_transform(str(run.bold_path), confounds=confounds),
                    dtype=np.float32,
                )
                concatenated_runs.append(timeseries)

                run_rows.append(
                    {
                        "run_id": relative_run_id(run),
                        "n_timepoints": int(timeseries.shape[0]),
                        "n_regions": int(timeseries.shape[1]),
                        "minutes": run.minutes,
                    }
                )
                if args.write_run_timeseries:
                    np.save(
                        subject_dir / f"{relative_run_id(run)}_timeseries.npy",
                        timeseries,
                    )

            concatenated = np.vstack(concatenated_runs)
            matrix = ConnectivityMeasure(kind=args.kind).fit_transform([concatenated])[
                0
            ]
            fisher_z_diagnostics: dict | None = None
            if not args.no_fisher_z:
                matrix, fisher_z_diagnostics = fisher_z_transform(matrix, args.kind)

            np.save(
                subject_dir / "timeseries_concat.npy", concatenated.astype(np.float32)
            )
            np.save(subject_dir / "connectivity_matrix.npy", matrix.astype(np.float32))
            pd.DataFrame(matrix).to_csv(
                subject_dir / "connectivity_matrix.csv", index=False
            )
            write_dataframe(
                subject_dir / "run_timeseries_summary.tsv", pd.DataFrame(run_rows)
            )

            try:
                estimator_diag = compute_estimator_diagnostics(matrix)
                contract = FeatureContract(
                    matrix_kind=args.kind,
                    source_level="roi_timeseries",
                    n_rois=int(concatenated.shape[1]),
                    n_timepoints=int(concatenated.shape[0]),
                    effective_n_timepoints=int(concatenated.shape[0]),
                    covariance_estimator="EmpiricalCovariance",
                    covariance_rank=int(estimator_diag["rank"]),
                    covariance_condition_number=float(
                        estimator_diag["condition_number"]
                    ),
                    min_eig=float(estimator_diag["min_eig"]),
                    fisher_z_diagnostics=fisher_z_diagnostics,
                    extras={
                        "subject": subject,
                        "n_runs": len(subject_runs),
                        "atlas": f"Schaefer{resolution}",
                        "concat_strategy": "vstack",
                    },
                )
                write_feature_contract(contract, subject_dir)
            except Exception:  # pragma: no cover - non-fatal
                pass

            subject_entry = summary["subjects"].setdefault(subject, {})  # type: ignore[assignment]
            subject_entry[str(resolution)] = {
                "atlas_path": str(atlas),
                "n_runs": len(subject_runs),
                "total_minutes": subject_total_minutes(subject_runs),
                "timeseries_shape": list(concatenated.shape),
                "matrix_shape": list(matrix.shape),
                "output_dir": str(subject_dir),
            }

    (output_root / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
