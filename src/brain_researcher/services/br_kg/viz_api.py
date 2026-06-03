"""Brain visualization endpoints for BR-KG.

This module intentionally avoids hard-coded host filesystem paths. Dataset, template,
and job roots are configured via environment variables so containerized deployments
can mount data to arbitrary locations.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlencode

from flask import Blueprint, jsonify, request, send_file

from brain_researcher.config.paths import get_data_root

viz_bp = Blueprint("viz", __name__)

_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_NIFTI_EXTENSIONS = (".nii", ".nii.gz")

_DATA_ROOT = get_data_root()

_DEFAULT_TEMPLATE_ROOTS = [
    _DATA_ROOT / "viz" / "templates",
    Path("/data/brain_researcher_data/viz/templates"),
    Path("/app/data/viz/templates"),
]
_DEFAULT_DATASET_ROOTS = [
    Path(os.getenv("BR_DATA_ROOT", "/data/brain_researcher_data")),
]
_DEFAULT_JOB_ROOTS = [
    _DATA_ROOT / "viz" / "jobs",
    Path("/data/brain_researcher_data/viz/jobs"),
]

DEFAULT_TEMPLATE = os.getenv("BR_KG_VIZ_DEFAULT_TEMPLATE", "mni152").strip() or "mni152"
DEFAULT_DATASET = os.getenv("BR_KG_VIZ_DEFAULT_DATASET", "openneuro/ds000114").strip()


def _parse_path_list(env_name: str, defaults: Sequence[Path]) -> List[Path]:
    raw = os.getenv(env_name, "").strip()
    if raw:
        candidates = [Path(item).expanduser() for item in raw.split(os.pathsep) if item.strip()]
    else:
        candidates = list(defaults)

    unique: List[Path] = []
    seen = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


TEMPLATE_ROOTS = _parse_path_list("BR_KG_VIZ_TEMPLATE_ROOTS", _DEFAULT_TEMPLATE_ROOTS)
DATASET_ROOTS = _parse_path_list("BR_KG_VIZ_DATASET_ROOTS", _DEFAULT_DATASET_ROOTS)
JOB_ROOTS = _parse_path_list("BR_KG_VIZ_JOB_ROOTS", _DEFAULT_JOB_ROOTS)


def _existing_dirs(paths: Sequence[Path]) -> Iterable[Path]:
    for path in paths:
        try:
            if path.exists() and path.is_dir():
                yield path.resolve()
        except OSError:
            continue


def _json_error(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


def _is_within_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _sanitize_segment(raw: str, *, label: str) -> str:
    value = (raw or "").strip()
    if not value:
        raise ValueError(f"Missing {label}")
    if not _SAFE_SEGMENT_RE.fullmatch(value):
        raise ValueError(f"Invalid {label}: {raw}")
    return value


def _sanitize_dataset_id(raw: str) -> str:
    parts = []
    for segment in (raw or "").replace("\\", "/").split("/"):
        token = segment.strip()
        if not token or token == ".":
            continue
        if token == ".." or not _SAFE_SEGMENT_RE.fullmatch(token):
            raise ValueError(f"Invalid dataset id: {raw}")
        parts.append(token)
    if not parts:
        raise ValueError("Missing dataset id")
    return "/".join(parts)


def _sanitize_relpath(raw: str) -> Path:
    cleaned = (raw or "").replace("\\", "/")
    if cleaned.startswith("/"):
        raise ValueError("Absolute paths are not allowed")

    parts = []
    for segment in cleaned.split("/"):
        token = segment.strip()
        if not token or token == ".":
            continue
        if token == ".." or not _SAFE_SEGMENT_RE.fullmatch(token):
            raise ValueError(f"Invalid relative path: {raw}")
        parts.append(token)

    if not parts:
        raise ValueError("Missing relative path")

    return Path(*parts)


def _is_nifti(path: Path) -> bool:
    return path.is_file() and path.name.endswith(_NIFTI_EXTENSIONS)


def _sorted_nifti_files(directory: Path) -> List[Path]:
    results = [p for p in directory.glob("*.nii*") if _is_nifti(p)]
    return sorted(results)


def _is_stat_like(path: Path) -> bool:
    name = path.name.lower()
    stat_tokens = ("stat", "zmap", "tmap", "cope", "contrast", "beta")
    return any(token in name for token in stat_tokens)


def _build_viz_url(endpoint: str, **params: str) -> str:
    qs = urlencode({k: v for k, v in params.items() if v is not None})
    return f"/api/viz/brain/{endpoint}{f'?{qs}' if qs else ''}"


def _resolve_template_file(template: Optional[str] = None) -> Optional[Path]:
    requested = (template or DEFAULT_TEMPLATE).strip()
    if not requested:
        requested = DEFAULT_TEMPLATE

    names: List[str]
    if requested.endswith(".nii") or requested.endswith(".nii.gz"):
        names = [requested]
    else:
        names = [f"{requested}.nii.gz", f"{requested}.nii"]

    for root in _existing_dirs(TEMPLATE_ROOTS):
        for name in names:
            candidate = (root / name).resolve()
            if candidate.exists() and _is_within_root(candidate, root) and candidate.is_file():
                return candidate
    return None


def _discover_dataset_dirs(limit: int = 64) -> List[Tuple[str, Path]]:
    discovered: List[Tuple[str, Path]] = []
    seen = set()

    for root in _existing_dirs(DATASET_ROOTS):
        candidates: List[Tuple[str, Path]] = []
        for ds_dir in sorted(root.glob("ds*")):
            if ds_dir.is_dir():
                candidates.append((ds_dir.name, ds_dir))

        openneuro_root = root / "openneuro"
        if openneuro_root.exists() and openneuro_root.is_dir():
            for ds_dir in sorted(openneuro_root.glob("ds*")):
                if ds_dir.is_dir():
                    candidates.append((f"openneuro/{ds_dir.name}", ds_dir))

        for dataset_id, path in candidates:
            key = (dataset_id, str(path.resolve()))
            if key in seen:
                continue
            seen.add(key)
            discovered.append((dataset_id, path.resolve()))
            if len(discovered) >= limit:
                return discovered

    return discovered


def _resolve_dataset_dir(dataset_id: Optional[str]) -> Tuple[str, Optional[Path]]:
    if dataset_id:
        normalized = _sanitize_dataset_id(dataset_id)
        for root in _existing_dirs(DATASET_ROOTS):
            candidate = (root / normalized).resolve()
            if candidate.exists() and candidate.is_dir() and _is_within_root(candidate, root):
                return normalized, candidate
        return normalized, None

    if DEFAULT_DATASET:
        try:
            resolved = _resolve_dataset_dir(DEFAULT_DATASET)
            if resolved[1] is not None:
                return resolved
        except ValueError:
            pass

    discovered = _discover_dataset_dirs(limit=1)
    if discovered:
        return discovered[0]

    return "", None


def _normalize_subject(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    value = _sanitize_segment(raw, label="subject")
    return value if value.startswith("sub-") else f"sub-{value}"


def _normalize_session(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    value = _sanitize_segment(raw, label="session")
    return value if value.startswith("ses-") else f"ses-{value}"


def _resolve_scope_dir(dataset_dir: Path, subject: Optional[str], session: Optional[str]) -> Optional[Path]:
    scope = dataset_dir

    if subject:
        subject_dir = dataset_dir / subject
        if not subject_dir.exists() or not subject_dir.is_dir():
            return None
        scope = subject_dir

    if session:
        session_dir = scope / session
        if not session_dir.exists() or not session_dir.is_dir():
            return None
        scope = session_dir

    return scope


def _find_first_matching(scope_dir: Path, patterns: Sequence[str]) -> Optional[Path]:
    for pattern in patterns:
        for candidate in scope_dir.rglob(pattern):
            if _is_nifti(candidate):
                return candidate.resolve()
    return None


def _select_dataset_files(
    dataset_dir: Path,
    *,
    subject: Optional[str],
    session: Optional[str],
    task: Optional[str],
) -> Tuple[Optional[Path], Optional[Path]]:
    scope_dir = _resolve_scope_dir(dataset_dir, subject, session)
    if scope_dir is None:
        return None, None

    anat_patterns = ["*T1w.nii.gz", "*T1w.nii", "*anat*.nii.gz", "*anat*.nii"]
    volume_file = _find_first_matching(scope_dir, anat_patterns)
    if volume_file is None:
        volume_file = _find_first_matching(scope_dir, ["*.nii.gz", "*.nii"])

    task_token = None
    if task:
        token = _sanitize_segment(task, label="task").lower()
        task_token = f"task-{token}"

    overlay_patterns: List[str] = []
    if task_token:
        overlay_patterns.extend(
            [
                f"*{task_token}*zmap*.nii.gz",
                f"*{task_token}*tmap*.nii.gz",
                f"*{task_token}*stat*.nii.gz",
                f"*{task_token}*_bold.nii.gz",
                f"*{task_token}*_bold.nii",
            ]
        )

    overlay_patterns.extend(["*zmap*.nii.gz", "*tmap*.nii.gz", "*stat*.nii.gz", "*_bold.nii.gz", "*_bold.nii"])
    overlay_file = _find_first_matching(scope_dir, overlay_patterns)

    if overlay_file is None and volume_file is not None:
        overlay_file = volume_file

    return volume_file, overlay_file


def _resolve_job_dir(job_id: str) -> Optional[Path]:
    safe_job_id = _sanitize_segment(job_id, label="job_id")
    for root in _existing_dirs(JOB_ROOTS):
        candidate = (root / safe_job_id).resolve()
        if candidate.exists() and candidate.is_dir() and _is_within_root(candidate, root):
            return candidate
    return None


def _safe_join(root: Path, relpath: str) -> Path:
    rel = _sanitize_relpath(relpath)
    candidate = (root / rel).resolve()
    if not _is_within_root(candidate, root.resolve()):
        raise ValueError("Path escapes configured root")
    return candidate


def _resolve_job_file(job_dir: Path, *, kind: str, overlay_name: Optional[str], relpath: Optional[str]) -> Optional[Path]:
    if relpath:
        candidate = _safe_join(job_dir, relpath)
        return candidate if _is_nifti(candidate) else None

    if overlay_name:
        safe_name = _sanitize_segment(overlay_name, label="overlay")
        candidate = _safe_join(job_dir, safe_name)
        return candidate if _is_nifti(candidate) else None

    files = _sorted_nifti_files(job_dir)
    if not files:
        return None

    if kind == "overlay":
        preferred = [file for file in files if _is_stat_like(file)] or files
    else:
        preferred = [file for file in files if not _is_stat_like(file)] or files
    return preferred[0]


def _resolve_dataset_file(
    *,
    dataset_id: str,
    subject: Optional[str],
    session: Optional[str],
    task: Optional[str],
    relpath: Optional[str],
    kind: str,
) -> Optional[Path]:
    normalized_dataset, dataset_dir = _resolve_dataset_dir(dataset_id)
    if not normalized_dataset or dataset_dir is None:
        return None

    if relpath:
        candidate = _safe_join(dataset_dir, relpath)
        return candidate if _is_nifti(candidate) else None

    volume_file, overlay_file = _select_dataset_files(
        dataset_dir,
        subject=subject,
        session=session,
        task=task,
    )
    return overlay_file if kind == "overlay" else volume_file


def _send_nifti(path: Path):
    return send_file(
        path,
        mimetype="application/octet-stream",
        as_attachment=False,
        download_name=path.name,
        conditional=True,
    )


@viz_bp.route("/api/viz/brain/config", methods=["GET"])
def get_brain_config():
    """Return Niivue-friendly config for demo/dataset/job visualization."""

    job_id = (request.args.get("job_id") or "demo").strip()
    dataset_query = request.args.get("dataset")
    subject = _normalize_subject(request.args.get("subject"))
    session = _normalize_session(request.args.get("session"))
    task = request.args.get("task")

    base_template_url = _build_viz_url("base", template=DEFAULT_TEMPLATE)
    config: Dict[str, object] = {
        "baseVolume": base_template_url,
        "baseVolumeFallback": base_template_url,
        "overlays": [],
        "surfaces": None,
        "atlas": {"name": "MNI152", "labelMap": None},
        "interaction": {"allowPick": True, "allowSlice": True, "allowDrag": True},
        "export": {"enableSnapshot": True},
        "metadata": {},
    }

    if job_id and job_id.lower() != "demo":
        try:
            job_dir = _resolve_job_dir(job_id)
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        if job_dir is None:
            return _json_error(f"Job {job_id} not found", status=404)

        job_files = _sorted_nifti_files(job_dir)
        overlays = []
        for file in job_files:
            overlays.append(
                {
                    "name": file.name,
                    "url": _build_viz_url("overlay", job_id=job_id, overlay=file.name),
                    "colormap": "hot" if _is_stat_like(file) else "gray",
                    "threshold": 2.3 if _is_stat_like(file) else 0.0,
                    "min": 0.0,
                    "max": 6.0 if _is_stat_like(file) else 1.0,
                    "opacity": 1.0 if _is_stat_like(file) else 0.75,
                }
            )

        if overlays:
            config["overlays"] = overlays

        config["metadata"] = {
            "job_id": job_id,
            "source": "job",
            "n_maps": len(overlays),
        }
        return jsonify(config)

    try:
        dataset_id, dataset_dir = _resolve_dataset_dir(dataset_query)
    except ValueError as exc:
        return _json_error(str(exc), status=400)

    if dataset_dir is not None:
        volume_file, overlay_file = _select_dataset_files(
            dataset_dir,
            subject=subject,
            session=session,
            task=task,
        )

        if volume_file is not None:
            rel = str(volume_file.relative_to(dataset_dir))
            config["baseVolume"] = _build_viz_url(
                "volume",
                dataset=dataset_id,
                relpath=rel,
                subject=subject,
                session=session,
            )

        if overlay_file is not None:
            rel = str(overlay_file.relative_to(dataset_dir))
            config["overlays"] = [
                {
                    "name": overlay_file.name,
                    "url": _build_viz_url(
                        "overlay",
                        dataset=dataset_id,
                        relpath=rel,
                        subject=subject,
                        session=session,
                        task=task,
                    ),
                    "colormap": "hot",
                    "threshold": 2.3,
                    "min": 0.0,
                    "max": 6.0,
                    "opacity": 1.0,
                }
            ]

        config["metadata"] = {
            "source": "dataset",
            "dataset": dataset_id,
            "subject": subject,
            "session": session,
            "task": task,
        }
    else:
        config["metadata"] = {
            "source": "template_only",
            "dataset": dataset_id or dataset_query,
            "note": "No configured dataset root contained the requested dataset",
        }

    return jsonify(config)


@viz_bp.route("/api/viz/brain/datasets", methods=["GET"])
def list_available_datasets():
    """List mounted datasets available for brain visualization."""

    requested_dataset = request.args.get("dataset")

    if requested_dataset:
        try:
            dataset_id, dataset_dir = _resolve_dataset_dir(requested_dataset)
        except ValueError as exc:
            return _json_error(str(exc), status=400)

        if dataset_dir is None:
            return jsonify(
                {
                    "datasets": [],
                    "total": 0,
                    "roots": [str(path) for path in DATASET_ROOTS],
                    "error": f"Dataset not found: {dataset_id}",
                }
            )

        subjects = sorted(
            path.name for path in dataset_dir.glob("sub-*") if path.exists() and path.is_dir()
        )
        return jsonify(
            {
                "datasets": [
                    {
                        "id": dataset_id,
                        "path": str(dataset_dir),
                        "n_subjects": len(subjects),
                        "subjects": subjects[:100],
                    }
                ],
                "total": 1,
                "roots": [str(path) for path in DATASET_ROOTS],
            }
        )

    discovered = _discover_dataset_dirs(limit=128)
    datasets = []
    for dataset_id, dataset_dir in discovered:
        subjects = [path.name for path in dataset_dir.glob("sub-*") if path.is_dir()]
        datasets.append(
            {
                "id": dataset_id,
                "path": str(dataset_dir),
                "n_subjects": len(subjects),
            }
        )

    return jsonify(
        {
            "datasets": datasets,
            "total": len(datasets),
            "roots": [str(path) for path in DATASET_ROOTS],
        }
    )


@viz_bp.route("/api/viz/brain/base", methods=["GET"])
def get_base_template_volume():
    """Serve a base anatomical template volume."""

    template = request.args.get("template", DEFAULT_TEMPLATE)
    template_path = _resolve_template_file(template)
    if template_path is None:
        return _json_error(f"Template not found: {template}", status=404)
    return _send_nifti(template_path)


@viz_bp.route("/api/viz/brain/volume", methods=["GET"])
def get_volume():
    """Serve a primary volume either from job outputs or mounted datasets."""

    try:
        job_id = request.args.get("job_id")
        relpath = request.args.get("relpath")
        dataset = request.args.get("dataset")
        subject = _normalize_subject(request.args.get("subject"))
        session = _normalize_session(request.args.get("session"))
        task = request.args.get("task")

        if job_id and job_id.lower() != "demo":
            job_dir = _resolve_job_dir(job_id)
            if job_dir is None:
                return _json_error(f"Job {job_id} not found", status=404)
            volume_file = _resolve_job_file(
                job_dir,
                kind="volume",
                overlay_name=None,
                relpath=relpath,
            )
        elif dataset or relpath or subject or session or task:
            volume_file = _resolve_dataset_file(
                dataset_id=dataset or DEFAULT_DATASET,
                subject=subject,
                session=session,
                task=task,
                relpath=relpath,
                kind="volume",
            )
        else:
            volume_file = _resolve_template_file(DEFAULT_TEMPLATE)

        if volume_file is None or not _is_nifti(volume_file):
            return _json_error("Volume not found", status=404)

        return _send_nifti(volume_file)
    except ValueError as exc:
        return _json_error(str(exc), status=400)


@viz_bp.route("/api/viz/brain/overlay", methods=["GET"])
def get_overlay():
    """Serve an overlay/stat map from job outputs or mounted datasets."""

    try:
        job_id = request.args.get("job_id")
        overlay_name = request.args.get("overlay")
        relpath = request.args.get("relpath")
        dataset = request.args.get("dataset")
        subject = _normalize_subject(request.args.get("subject"))
        session = _normalize_session(request.args.get("session"))
        task = request.args.get("task")

        if job_id and job_id.lower() != "demo":
            job_dir = _resolve_job_dir(job_id)
            if job_dir is None:
                return _json_error(f"Job {job_id} not found", status=404)
            overlay_file = _resolve_job_file(
                job_dir,
                kind="overlay",
                overlay_name=overlay_name,
                relpath=relpath,
            )
        else:
            overlay_file = _resolve_dataset_file(
                dataset_id=dataset or DEFAULT_DATASET,
                subject=subject,
                session=session,
                task=task,
                relpath=relpath,
                kind="overlay",
            )

        if overlay_file is None or not _is_nifti(overlay_file):
            return _json_error("Overlay not found", status=404)

        return _send_nifti(overlay_file)
    except ValueError as exc:
        return _json_error(str(exc), status=400)


@viz_bp.route("/api/viz/brain/snapshot", methods=["GET"])
def get_snapshot():
    """Placeholder endpoint for server-side snapshot generation."""

    job_id = request.args.get("job_id", "demo")
    view = request.args.get("view", "axial")

    return jsonify(
        {
            "ok": True,
            "message": "Server-side rendering not implemented",
            "job_id": job_id,
            "view": view,
            "hint": "Use client-side canvas capture for snapshots",
        }
    )


__all__ = ["viz_bp"]
