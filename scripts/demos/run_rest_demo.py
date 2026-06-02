"""Run a minimal rest-connectivity demo using the worktree tools.

This script avoids interference from any editable/pip-installed brain_researcher
by purging the editable path hook and prepending the current worktree.
Outputs are written to /tmp/OpenNeuro/out/rest.
"""

from __future__ import annotations

import os
import sys
import importlib
import logging
from pathlib import Path


def _prime_sys_path(repo_root: str):
    """Force imports to resolve to the current repo (not old editable installs)."""
    sys.path = [p for p in sys.path if "__editable__.brain_researcher" not in p]
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    for mod in list(sys.modules):
        if mod.startswith("brain_researcher"):
            sys.modules.pop(mod, None)
    importlib.invalidate_caches()


def main():
    try:
        _run()
    except Exception as exc:  # pragma: no cover
        import traceback

        print("FATAL:", exc, flush=True)
        traceback.print_exc()
        raise


def _run():
    repo_root = str(Path(__file__).resolve().parent.parent)
    _prime_sys_path(repo_root)
    os.environ.setdefault("BRAIN_RESEARCHER_ENV", "dev")

    logging.basicConfig(level=logging.ERROR, force=True)
    for name in ["brain_researcher", "brain_researcher.services.tools"]:
        logging.getLogger(name).setLevel(logging.ERROR)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    from brain_researcher.services.tools.runner import execute_tool
    from brain_researcher.services.tools.atlas_utils import default_atlas_output_root

    print("[rest_demo] start")

    bold = "/tmp/OpenNeuro/ds000005-fmriprep/sub-01/func/sub-01_task-mixedgamblestask_run-1_desc-preproc_bold.nii.gz"
    conf = "/tmp/OpenNeuro/ds000005-fmriprep/sub-01/func/sub-01_task-mixedgamblestask_run-1_desc-confounds_timeseries.tsv"
    mask = "/tmp/OpenNeuro/ds000005-fmriprep/sub-01/func/sub-01_task-mixedgamblestask_run-1_desc-brain_mask.nii.gz"
    atlas_candidates = [
        default_atlas_output_root() / "aal" / "AAL.nii.gz",
        default_atlas_output_root() / "aal" / "AAL.nii",
        Path(repo_root)
        / "data"
        / "br_kg"
        / "raw"
        / "nilearn_atlases"
        / "aal_SPM12"
        / "aal"
        / "atlas"
        / "AAL.nii",
        Path(repo_root)
        / "data"
        / "br_kg"
        / "raw"
        / "nilearn_atlases"
        / "aal_SPM12"
        / "aal"
        / "ROI_MNI_V4.nii",
    ]
    atlas = next(
        (str(path) for path in atlas_candidates if path.exists()),
        str(atlas_candidates[0]),
    )
    outdir = Path("/tmp/OpenNeuro/out/rest")

    outdir.mkdir(parents=True, exist_ok=True)

    print("[rest_demo] TS step")

    res_ts = execute_tool(
        "extract_timeseries",
        {
            "img": bold,
            "atlas": atlas,
            "confounds": conf,
            "mask_img": mask,
            "output_dir": str(outdir / "ts"),
            "standardize": True,
        },
    )
    print("TS", res_ts.status, res_ts.error, flush=True)
    if res_ts.data and "traceback" in res_ts.data:
        print(res_ts.data["traceback"])
    else:
        print("TS outputs", res_ts.data.get("outputs") if res_ts.data else None)

    print("[rest_demo] CONN step")
    res_conn = execute_tool(
        "connectivity_matrix",
        {
            "timeseries": res_ts.data.get("outputs", {}).get(
                "timeseries", str(outdir / "ts" / "timeseries.npy")
            ),
            "kind": "correlation",
            "output_file": str(outdir / "conn" / "conn.npy"),
        },
    )
    print("CONN", res_conn.status, res_conn.error, flush=True)
    if res_conn.data and "traceback" in res_conn.data:
        print(res_conn.data["traceback"])
    else:
        print("CONN outputs", res_conn.data.get("outputs") if res_conn.data else None)

    print("[rest_demo] SEED step")
    res_seed = execute_tool(
        "seed_based_fc",
        {
            "img": bold,
            "seed": [0, -52, 18],
            "confounds": conf,
            "mask_img": mask,
            "output_file": str(outdir / "seed" / "pcc_fc.nii.gz"),
        },
    )
    print("SEED", res_seed.status, res_seed.error, flush=True)
    if res_seed.data and "traceback" in res_seed.data:
        print(res_seed.data["traceback"])
    else:
        print("SEED outputs", res_seed.data.get("outputs") if res_seed.data else None)

    print("END. Outputs under", outdir, flush=True)


if __name__ == "__main__":
    main()
