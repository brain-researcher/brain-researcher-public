#!/usr/bin/env python3
"""
Batch Schaefer connectivity matrix extraction — MSC dataset (ds000224).

Dataset:  Midnight Scan Club, 10 subjects × 10 resting sessions (~30 min/session)
Source:   /app/data/OpenNeuroDerivatives/fmriprep/ds000224-fmriprep  (pre-mounted)
Tool:     workflow_rest_connectome_e2e  (brain-researcher-prod MCP)

Output layout
--------------
OUT_ROOT/
  sub-MSC{01..10}/
    ses-func{01..10}/
      sub-MSC01_ses-func01_task-rest_run-01_space-MNI152NLin2009cAsym_res-2_atlas-Schaefer2018_desc-100Parcels7Networks_corrmat.npy
      sub-MSC01_ses-func01_task-rest_run-01_space-MNI152NLin2009cAsym_res-2_atlas-Schaefer2018_desc-100Parcels7Networks_timeseries.npy
      sub-MSC01_ses-func01_task-rest_run-01_space-MNI152NLin2009cAsym_res-2_atlas-Schaefer2018_desc-100Parcels7Networks_timeseries.csv
      sub-MSC01_ses-func01_task-rest_run-01_space-MNI152NLin2009cAsym_res-2_atlas-Schaefer2018_desc-100Parcels7Networks_provenance.json
    aggregate/
      Schaefer{100,...}_session_matrices.npy   # (n_valid_ses, n_rois, n_rois)
      Schaefer{100,...}_subject_mean.npy       # (n_rois, n_rois) mean across sessions
      Schaefer{100,...}_concat_timeseries.npy  # (total_tp, n_rois)
      Schaefer{100,...}_concat_matrix.npy      # single matrix from all concatenated data
  group/
    Schaefer{100,...}_subject_matrices.npy     # (n_subjects, n_rois, n_rois) subject means
    Schaefer{100,...}_group_mean.npy           # (n_rois, n_rois)

Usage
-----
  python msc_schaefer_connectomes.py [--resolutions 100 200 300 400] [--subjects all]
                                      [--sessions all] [--out-root /data/processed/...]
                                      [--n-jobs 4] [--force]

Requirements
------------
  pip install nibabel>=5.0.0 nilearn>=0.10.0 numpy>=1.24.0 pandas>=2.2.0 scikit-learn>=1.3.0

Confound strategy (24-motion + WM + CSF + motion outliers)
------------------------------------------------------------
  trans_{x,y,z}, rot_{x,y,z}                     6 params
  trans_{x,y,z}_derivative1, rot_{x,y,z}_deriv1  6 derivative params
  trans_{x,y,z}_power2, rot_{x,y,z}_power2       6 squared params (optional, set USE_36=True)
  white_matter, csf                               2 physiological
  motion_outlier*                                 variable spike regressors (FD>0.5mm)

  First-volume non-finite values in derivatives are filled with 0.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

import nibabel as nib
import numpy as np
import pandas as pd
from nilearn import datasets
from nilearn.connectome import ConnectivityMeasure
from nilearn.maskers import NiftiLabelsMasker

try:
    from brain_researcher.core.analysis.connectivity_contracts import (
        FeatureContract,
        compute_estimator_diagnostics,
        safe_fisher_z,
        write_feature_contract,
    )
    from brain_researcher.services.tools.atlas_utils import (
        existing_search_roots,
        fetch_templateflow_schaefer_atlas,
        find_local_schaefer_atlas,
    )
except ImportError:
    REPO_SRC = Path(__file__).resolve().parents[1] / "src"
    if str(REPO_SRC) not in sys.path:
        sys.path.insert(0, str(REPO_SRC))
    from brain_researcher.core.analysis.connectivity_contracts import (  # type: ignore[no-redef]
        FeatureContract,
        compute_estimator_diagnostics,
        safe_fisher_z,
        write_feature_contract,
    )
    from brain_researcher.services.tools.atlas_utils import (  # type: ignore[no-redef]
        existing_search_roots,
        fetch_templateflow_schaefer_atlas,
        find_local_schaefer_atlas,
    )

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
FMRIPREP_ROOT = Path("/app/data/OpenNeuroDerivatives/fmriprep/ds000224-fmriprep")
DEFAULT_OUT_ROOT = Path("/data/processed/msc_schaefer_connectomes")
ATLAS_CACHE = DEFAULT_OUT_ROOT / "_atlas_cache"

SUBJECTS = [f"MSC{i:02d}" for i in range(1, 11)]
SESSIONS = [f"func{s:02d}" for s in range(1, 11)]
RESOLUTIONS = [100, 200, 300, 400]

TR = 2.2          # seconds — MSC resting-state TR
LOW_PASS = 0.1    # Hz
HIGH_PASS = 0.01  # Hz
ATLAS_NAME = "Schaefer2018"
ATLAS_NETWORKS = 7
DERIVATIVE_TASK = "rest"
DERIVATIVE_RUN = "01"
DERIVATIVE_SPACE = "MNI152NLin2009cAsym"
DERIVATIVE_RESOLUTION = "2"

# Motion confound columns (24-parameter model by default; set True to use 36)
USE_36_PARAM = False

MOTION_COLS = [
    "trans_x", "trans_y", "trans_z",
    "rot_x", "rot_y", "rot_z",
    "trans_x_derivative1", "trans_y_derivative1", "trans_z_derivative1",
    "rot_x_derivative1", "rot_y_derivative1", "rot_z_derivative1",
]
MOTION_SQUARED_COLS = [
    "trans_x_power2", "trans_y_power2", "trans_z_power2",
    "rot_x_power2", "rot_y_power2", "rot_z_power2",
    "trans_x_derivative1_power2", "trans_y_derivative1_power2", "trans_z_derivative1_power2",
    "rot_x_derivative1_power2", "rot_y_derivative1_power2", "rot_z_derivative1_power2",
]
PHYSIO_COLS = ["white_matter", "csf"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Atlas helpers
# ---------------------------------------------------------------------------
def fetch_schaefer_atlas(n_rois: int, cache_dir: Path) -> Path:
    """Prefer a mounted TemplateFlow atlas and fall back to Nilearn."""
    search_roots = existing_search_roots(str(cache_dir), cache_dir)
    local_atlas = find_local_schaefer_atlas(
        n_rois=n_rois,
        roots=search_roots,
        yeo_networks=ATLAS_NETWORKS,
        space=DERIVATIVE_SPACE,
        resolution=DERIVATIVE_RESOLUTION,
        include_legacy=False,
    )
    if local_atlas is not None:
        return local_atlas

    fetched_templateflow_atlas = fetch_templateflow_schaefer_atlas(
        n_rois=n_rois,
        yeo_networks=ATLAS_NETWORKS,
        space=DERIVATIVE_SPACE,
        resolution=DERIVATIVE_RESOLUTION,
    )
    if fetched_templateflow_atlas is not None:
        return fetched_templateflow_atlas

    legacy_local_atlas = find_local_schaefer_atlas(
        n_rois=n_rois,
        roots=search_roots,
        yeo_networks=ATLAS_NETWORKS,
        space=DERIVATIVE_SPACE,
        resolution=DERIVATIVE_RESOLUTION,
    )
    if legacy_local_atlas is not None:
        return legacy_local_atlas

    cache_dir.mkdir(parents=True, exist_ok=True)
    atlas = datasets.fetch_atlas_schaefer_2018(
        n_rois=n_rois,
        resolution_mm=2,
        yeo_networks=ATLAS_NETWORKS,
        data_dir=str(cache_dir),
    )
    return Path(atlas.maps)


def schaefer_desc(n_rois: int) -> str:
    return f"{n_rois}Parcels{ATLAS_NETWORKS}Networks"


def session_artifact_prefix(subject: str, session: str, n_rois: int) -> str:
    return "_".join(
        [
            f"sub-{subject}",
            f"ses-{session}",
            f"task-{DERIVATIVE_TASK}",
            f"run-{DERIVATIVE_RUN}",
            f"space-{DERIVATIVE_SPACE}",
            f"res-{DERIVATIVE_RESOLUTION}",
            f"atlas-{ATLAS_NAME}",
            f"desc-{schaefer_desc(n_rois)}",
        ]
    )


def session_output_paths(subject: str, session: str, n_rois: int, out_root: Path) -> dict[str, Path]:
    session_dir = out_root / f"sub-{subject}" / f"ses-{session}"
    prefix = session_artifact_prefix(subject, session, n_rois)
    legacy_dir = session_dir / f"Schaefer{n_rois}"
    return {
        "session_dir": session_dir,
        "matrix": session_dir / f"{prefix}_corrmat.npy",
        "timeseries_npy": session_dir / f"{prefix}_timeseries.npy",
        "timeseries_csv": session_dir / f"{prefix}_timeseries.csv",
        "provenance": session_dir / f"{prefix}_provenance.json",
        "legacy_matrix": legacy_dir / "connectivity_matrix.npy",
        "legacy_timeseries": legacy_dir / "timeseries" / "timeseries.npy",
    }


def existing_session_artifacts(
    subject: str, session: str, n_rois: int, out_root: Path
) -> tuple[Path, Path] | None:
    paths = session_output_paths(subject, session, n_rois, out_root)
    if paths["matrix"].exists() and paths["timeseries_npy"].exists():
        return paths["matrix"], paths["timeseries_npy"]
    if paths["legacy_matrix"].exists() and paths["legacy_timeseries"].exists():
        return paths["legacy_matrix"], paths["legacy_timeseries"]
    return None


# ---------------------------------------------------------------------------
# Confound loading
# ---------------------------------------------------------------------------
def load_confounds(confounds_tsv: Path) -> np.ndarray | None:
    """Return (n_volumes, n_confounds) array, or None if file missing."""
    if not confounds_tsv.exists():
        log.warning("  confounds not found: %s", confounds_tsv)
        return None

    df = pd.read_csv(confounds_tsv, sep="\t")

    # Build confound column list
    wanted = list(MOTION_COLS) + list(PHYSIO_COLS)
    if USE_36_PARAM:
        wanted += list(MOTION_SQUARED_COLS)

    # Spike regressors (motion outliers): columns named motion_outlier*
    outlier_cols = [c for c in df.columns if c.startswith("motion_outlier")]

    present = [c for c in wanted if c in df.columns]
    missing = [c for c in wanted if c not in df.columns]
    if missing:
        log.debug("  confound columns absent (will skip): %s", missing)

    cols = present + outlier_cols
    if not cols:
        log.warning("  no usable confound columns found")
        return None

    conf = df[cols].to_numpy(dtype=float, copy=True)
    # Fill NaN in first row (derivative columns have NaN at t=0) with 0
    conf[~np.isfinite(conf)] = 0.0
    return conf


# ---------------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------------
@dataclass
class RunResult:
    subject: str
    session: str
    n_rois: int
    ok: bool
    n_timepoints: int = 0
    matrix_path: str = ""
    timeseries_path: str = ""
    error: str = ""


def extract_one(
    subject: str,
    session: str,
    n_rois: int,
    out_root: Path,
    atlas_path: Path,
    force: bool = False,
) -> RunResult:
    """Extract timeseries + connectivity matrix for one sub/ses/resolution."""
    func_dir = FMRIPREP_ROOT / f"sub-{subject}" / f"ses-{session}" / "func"
    bold_pattern = (
        f"sub-{subject}_ses-{session}_task-rest_"
        f"space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz"
    )
    bold_path = func_dir / bold_pattern
    confounds_path = func_dir / bold_pattern.replace(
        "preproc_bold.nii.gz", "confounds_timeseries.tsv"
    )

    output_paths = session_output_paths(subject, session, n_rois, out_root)
    out_dir = output_paths["session_dir"]
    matrix_file = output_paths["matrix"]
    ts_file = output_paths["timeseries_npy"]
    ts_csv_file = output_paths["timeseries_csv"]
    prov_file = output_paths["provenance"]

    # Resume: skip if already done
    if not force and matrix_file.exists() and ts_file.exists():
        log.info("  SKIP (exists): sub-%s ses-%s Schaefer%d", subject, session, n_rois)
        return RunResult(
            subject=subject, session=session, n_rois=n_rois, ok=True,
            matrix_path=str(matrix_file), timeseries_path=str(ts_file),
        )

    if not bold_path.exists():
        msg = f"BOLD not found: {bold_path}"
        log.warning("  %s", msg)
        return RunResult(subject=subject, session=session, n_rois=n_rois, ok=False, error=msg)

    log.info("  RUN: sub-%s ses-%s Schaefer%d", subject, session, n_rois)

    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        confounds = load_confounds(confounds_path)

        masker = NiftiLabelsMasker(
            labels_img=str(atlas_path),
            standardize=True,
            detrend=True,
            t_r=TR,
            low_pass=LOW_PASS,
            high_pass=HIGH_PASS,
            memory_level=0,
        )
        timeseries = masker.fit_transform(str(bold_path), confounds=confounds)
        # timeseries: (n_timepoints, n_rois)

        np.save(ts_file, timeseries)
        np.savetxt(ts_csv_file, timeseries, delimiter=",")

        measure = ConnectivityMeasure(kind="correlation")
        matrix = measure.fit_transform([timeseries])   # (1, n_rois, n_rois)
        # Fisher-z transform
        matrix, fisher_z_diagnostics = safe_fisher_z(
            matrix,
            f"msc_session_corrmat(sub-{subject},ses-{session},Schaefer{n_rois})",
            return_diagnostics=True,
        )
        np.save(matrix_file, matrix)

        prov = {
            "subject": subject, "session": session, "n_rois": n_rois,
            "bold": str(bold_path), "confounds": str(confounds_path),
            "n_timepoints": int(timeseries.shape[0]),
            "confound_columns": int(confounds.shape[1]) if confounds is not None else 0,
            "tr": TR, "low_pass": LOW_PASS, "high_pass": HIGH_PASS,
            "fisher_z": True,
            "fisher_z_diagnostics": fisher_z_diagnostics,
        }
        prov_file.write_text(json.dumps(prov, indent=2))

        try:
            estimator_diag = compute_estimator_diagnostics(np.asarray(matrix[0]))
            contract = FeatureContract(
                matrix_kind="correlation",
                source_level="roi_timeseries",
                n_rois=int(timeseries.shape[1]),
                n_timepoints=int(timeseries.shape[0]),
                effective_n_timepoints=int(timeseries.shape[0]),
                covariance_estimator="EmpiricalCovariance",
                covariance_rank=int(estimator_diag["rank"]),
                covariance_condition_number=float(estimator_diag["condition_number"]),
                min_eig=float(estimator_diag["min_eig"]),
                fisher_z_diagnostics=fisher_z_diagnostics,
                extras={
                    "subject": subject,
                    "session": session,
                    "atlas": f"Schaefer{n_rois}",
                    "tr": TR,
                    "low_pass": LOW_PASS,
                    "high_pass": HIGH_PASS,
                },
            )
            write_feature_contract(contract, out_dir)
        except Exception as exc:  # pragma: no cover - non-fatal
            log.warning("  feature_contract emit failed: %s", exc)

        log.info(
            "  DONE: sub-%s ses-%s Schaefer%d  (%d tp, %d rois)",
            subject, session, n_rois, timeseries.shape[0], timeseries.shape[1],
        )
        return RunResult(
            subject=subject, session=session, n_rois=n_rois, ok=True,
            n_timepoints=int(timeseries.shape[0]),
            matrix_path=str(matrix_file),
            timeseries_path=str(ts_file),
        )

    except Exception as exc:
        log.error("  ERROR sub-%s ses-%s Schaefer%d: %s", subject, session, n_rois, exc)
        return RunResult(subject=subject, session=session, n_rois=n_rois, ok=False, error=str(exc))


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------
def aggregate_subject(subject: str, n_rois: int, out_root: Path) -> None:
    """
    For a single subject:
      1. Stack all valid session matrices → (n_valid_ses, n_rois, n_rois)
      2. Compute subject-level mean matrix
      3. Concatenate timeseries across sessions → single (total_tp, n_rois) array
      4. Compute connectivity matrix on the concatenated timeseries
    """
    agg_dir = out_root / f"sub-{subject}" / "aggregate"
    agg_dir.mkdir(parents=True, exist_ok=True)

    session_matrices = []
    all_timeseries = []

    for session in SESSIONS:
        session_artifacts = existing_session_artifacts(subject, session, n_rois, out_root)
        if session_artifacts is not None:
            mat_path, ts_path = session_artifacts
            mat = np.load(mat_path)          # (1, n_rois, n_rois)
            session_matrices.append(mat[0])  # (n_rois, n_rois)
            all_timeseries.append(np.load(ts_path))

    if not session_matrices:
        log.warning("  aggregate: no sessions found for sub-%s Schaefer%d", subject, n_rois)
        return

    stacked = np.stack(session_matrices, axis=0)   # (n_ses, n_rois, n_rois)
    subj_mean = stacked.mean(axis=0)               # (n_rois, n_rois)

    np.save(agg_dir / f"Schaefer{n_rois}_session_matrices.npy", stacked)
    np.save(agg_dir / f"Schaefer{n_rois}_subject_mean.npy", subj_mean)
    log.info(
        "  AGG sub-%s Schaefer%d: %d sessions averaged", subject, n_rois, len(session_matrices)
    )

    concat_ts = np.concatenate(all_timeseries, axis=0)  # (total_tp, n_rois)
    np.save(agg_dir / f"Schaefer{n_rois}_concat_timeseries.npy", concat_ts)

    measure = ConnectivityMeasure(kind="correlation")
    concat_mat = measure.fit_transform([concat_ts])
    concat_mat = safe_fisher_z(
        concat_mat,
        f"msc_concat_corrmat(sub-{subject},Schaefer{n_rois})",
    )
    np.save(agg_dir / f"Schaefer{n_rois}_concat_matrix.npy", concat_mat)
    log.info(
        "  AGG sub-%s Schaefer%d: concat ts shape %s", subject, n_rois, concat_ts.shape
    )


def aggregate_group(subjects: list[str], n_rois: int, out_root: Path) -> None:
    """Stack subject-mean matrices into a group array."""
    group_dir = out_root / "group"
    group_dir.mkdir(parents=True, exist_ok=True)

    subject_matrices = []
    valid_subjects = []
    for subject in subjects:
        mean_path = (
            out_root / f"sub-{subject}" / "aggregate"
            / f"Schaefer{n_rois}_subject_mean.npy"
        )
        if mean_path.exists():
            subject_matrices.append(np.load(mean_path))
            valid_subjects.append(subject)

    if not subject_matrices:
        log.warning("  group: no subject means found for Schaefer%d", n_rois)
        return

    group_stack = np.stack(subject_matrices, axis=0)   # (n_subjects, n_rois, n_rois)
    group_mean = group_stack.mean(axis=0)

    np.save(group_dir / f"Schaefer{n_rois}_subject_matrices.npy", group_stack)
    np.save(group_dir / f"Schaefer{n_rois}_group_mean.npy", group_mean)

    # Save subject order
    (group_dir / f"Schaefer{n_rois}_subjects.json").write_text(
        json.dumps(valid_subjects, indent=2)
    )
    log.info(
        "  GROUP Schaefer%d: %d subjects → shape %s", n_rois, len(valid_subjects), group_stack.shape
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--resolutions", nargs="+", type=int, default=RESOLUTIONS,
                   metavar="N", help="Schaefer parcel counts (default: 100 200 300 400)")
    p.add_argument("--subjects", nargs="+", default=SUBJECTS,
                   help="Subject IDs without 'sub-' prefix (default: all MSC01..MSC10)")
    p.add_argument("--sessions", nargs="+", default=SESSIONS,
                   help="Session IDs without 'ses-' prefix (default: func01..func10)")
    p.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT,
                   help="Root output directory")
    p.add_argument("--n-jobs", type=int, default=1,
                   help="Parallel workers for session-level extraction (default: 1)")
    p.add_argument("--force", action="store_true",
                   help="Rerun even if outputs already exist")
    p.add_argument("--skip-aggregate", action="store_true",
                   help="Skip aggregation step (useful for partial runs)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    out_root: Path = args.out_root
    out_root.mkdir(parents=True, exist_ok=True)

    log.info("=== MSC Schaefer Connectivity Extraction ===")
    log.info("  FMRIPREP: %s", FMRIPREP_ROOT)
    log.info("  Output:   %s", out_root)
    log.info("  Subjects: %s", args.subjects)
    log.info("  Sessions: %s", args.sessions)
    log.info("  Resolutions: %s", args.resolutions)
    log.info("  Workers: %d", args.n_jobs)

    # Pre-fetch all atlases (serial, once)
    log.info("--- Fetching atlases ---")
    atlas_paths: dict[int, Path] = {}
    for n_rois in args.resolutions:
        atlas_paths[n_rois] = fetch_schaefer_atlas(n_rois, ATLAS_CACHE)
        log.info("  Schaefer%d → %s", n_rois, atlas_paths[n_rois])

    # Build job list: (subject, session, n_rois)
    jobs = [
        (sub, ses, n_rois)
        for sub in args.subjects
        for ses in args.sessions
        for n_rois in args.resolutions
    ]
    log.info("--- Extracting connectomes: %d jobs ---", len(jobs))

    results: list[RunResult] = []

    if args.n_jobs > 1:
        with ProcessPoolExecutor(max_workers=args.n_jobs) as pool:
            futures = {
                pool.submit(
                    extract_one, sub, ses, n_rois,
                    out_root, atlas_paths[n_rois], args.force
                ): (sub, ses, n_rois)
                for (sub, ses, n_rois) in jobs
            }
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as exc:
                    sub, ses, n_rois = futures[future]
                    log.error("Future error sub-%s ses-%s Schaefer%d: %s", sub, ses, n_rois, exc)
                    results.append(RunResult(subject=sub, session=ses, n_rois=n_rois, ok=False, error=str(exc)))
    else:
        for sub, ses, n_rois in jobs:
            results.append(
                extract_one(sub, ses, n_rois, out_root, atlas_paths[n_rois], args.force)
            )

    # Summary
    n_ok = sum(r.ok for r in results)
    n_fail = len(results) - n_ok
    log.info("--- Extraction complete: %d ok, %d failed ---", n_ok, n_fail)
    if n_fail:
        for r in results:
            if not r.ok:
                log.warning("  FAIL sub-%s ses-%s Schaefer%d: %s", r.subject, r.session, r.n_rois, r.error)

    # Write run manifest
    manifest_path = out_root / "run_manifest.json"
    manifest_path.write_text(
        json.dumps([asdict(r) for r in results], indent=2)
    )
    log.info("  Manifest: %s", manifest_path)

    if args.skip_aggregate:
        log.info("--- Skipping aggregation (--skip-aggregate) ---")
        return

    # Aggregation: per-subject across sessions
    log.info("--- Aggregating per-subject ---")
    for sub in args.subjects:
        for n_rois in args.resolutions:
            aggregate_subject(sub, n_rois, out_root)

    # Group-level
    log.info("--- Aggregating group ---")
    for n_rois in args.resolutions:
        aggregate_group(args.subjects, n_rois, out_root)

    log.info("=== Done. Outputs at %s ===", out_root)


if __name__ == "__main__":
    main()
