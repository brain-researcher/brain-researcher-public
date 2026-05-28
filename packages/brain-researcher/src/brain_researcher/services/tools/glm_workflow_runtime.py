from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Sequence

import nibabel as nib
import pandas as pd


_MNI_SPACE_PREFERENCE = [
    "MNI152NLin2009cAsym",
    "MNI152NLin6Asym",
    "MNI152NLin6Sym",
]
_EVENT_ENTITY_PREFIXES = (
    "sub-",
    "ses-",
    "task-",
    "run-",
    "acq-",
    "ce-",
    "rec-",
    "dir-",
)
_EVENT_DROP_PREFIXES = ("space-", "res-", "desc-", "den-", "echo-", "part-")


def normalize_participant_labels(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple, set)):
        items = raw
    else:
        items = [raw]
    labels: list[str] = []
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        labels.append(text[4:] if text.startswith("sub-") else text)
    return labels


def canonical_subject_label(raw: str) -> str:
    text = str(raw).strip()
    if not text:
        raise ValueError("empty participant label")
    return text if text.startswith("sub-") else f"sub-{text}"


def canonical_fmriprep_root(raw: str | Path) -> Path:
    root = Path(raw).expanduser().resolve()
    nested = root / "fmriprep"
    if nested.is_dir() and any(nested.glob("sub-*")):
        return nested
    return root


def _strip_nii_suffix(name: str) -> str:
    if name.endswith(".nii.gz"):
        return name[: -len(".nii.gz")]
    if name.endswith(".nii"):
        return name[: -len(".nii")]
    return name


def _event_stem_from_bold_name(name: str) -> str:
    stem = _strip_nii_suffix(name)
    kept: list[str] = []
    for token in stem.split("_"):
        if token == "bold":
            continue
        if token.startswith(_EVENT_DROP_PREFIXES):
            continue
        if token.startswith(_EVENT_ENTITY_PREFIXES):
            kept.append(token)
    return "_".join(kept)


def _subject_from_path(path: Path, fallback: int) -> str:
    match = re.search(r"(sub-[A-Za-z0-9]+)", path.name)
    if match:
        return match.group(1)
    return f"sub-{fallback:02d}"


def _resolve_tr(img_path: Path) -> float | None:
    try:
        img = nib.load(str(img_path))
        zooms = img.header.get_zooms()
        if len(zooms) >= 4:
            return float(zooms[3])
    except Exception:
        return None
    return None


def _normalize_events_argument(
    events: str | Sequence[str] | None,
    n_imgs: int,
) -> list[str | None]:
    if events is None:
        return [None] * n_imgs
    if isinstance(events, str):
        return [events] * n_imgs
    resolved = [str(item) if item is not None else None for item in events]
    if len(resolved) != n_imgs:
        raise ValueError("events list must match img list length")
    return resolved


def _trial_types_for_events(path: Path) -> set[str]:
    sep = "\t" if path.suffix.lower() == ".tsv" else ","
    df = pd.read_csv(path, sep=sep)
    if "trial_type" not in df.columns:
        return set()
    return {
        str(value).strip()
        for value in df["trial_type"].dropna().tolist()
        if str(value).strip()
    }


def infer_common_contrast_name(events_paths: Sequence[str | None]) -> str | None:
    shared: set[str] | None = None
    for raw in events_paths:
        if not raw:
            return None
        path = Path(str(raw)).expanduser().resolve()
        if not path.exists():
            return None
        trial_types = _trial_types_for_events(path)
        if not trial_types:
            return None
        shared = trial_types if shared is None else (shared & trial_types)
        if not shared:
            return None
    if not shared:
        return None
    if "Correct_Task" in shared:
        return "Correct_Task"
    return sorted(shared)[0]


def _list_subject_dirs(root: Path) -> list[Path]:
    return sorted(path for path in root.glob("sub-*") if path.is_dir())


def _preferred_bold_key(path: Path, *, requested_space: str | None) -> tuple[int, int, str]:
    name = path.name
    if requested_space and f"space-{requested_space}" in name:
        space_rank = 0
    else:
        space_rank = len(_MNI_SPACE_PREFERENCE) + 1
        for idx, token in enumerate(_MNI_SPACE_PREFERENCE, start=1):
            if f"space-{token}" in name:
                space_rank = idx
                break
    desc_rank = 0 if "desc-preproc_bold" in name else 1
    return (space_rank, desc_rank, name)


def _match_event_for_img(
    bids_root: Path,
    img_path: Path,
    *,
    task: str,
    session: str | None,
) -> Path | None:
    stem = _event_stem_from_bold_name(img_path.name)
    direct_candidates = sorted(bids_root.glob(f"**/func/{stem}*_events.tsv"))
    if session:
        direct_candidates = [
            path for path in direct_candidates if f"ses-{session}" in path.name
        ]
    if direct_candidates:
        return direct_candidates[0]

    subject = _subject_from_path(img_path, 0)
    subject_root = bids_root / subject
    if not subject_root.exists():
        return None
    pattern = f"**/func/*task-{task}*_events.tsv"
    candidates = sorted(subject_root.glob(pattern))
    if session:
        candidates = [path for path in candidates if f"ses-{session}" in path.name]
    if not candidates:
        return None

    run_match = re.search(r"(run-[A-Za-z0-9]+)", img_path.name)
    if run_match:
        run_token = run_match.group(1)
        run_candidates = [path for path in candidates if run_token in path.name]
        if run_candidates:
            return run_candidates[0]
    return candidates[0]


def _resolve_direct_subject_records(
    *,
    img: str | Sequence[str] | None,
    events: str | Sequence[str] | None,
    bids_dir: str | None,
    task: str | None,
    session: str | None,
) -> list[dict[str, Any]]:
    if img in (None, ""):
        return []
    imgs = [img] if isinstance(img, str) else list(img)
    if not imgs:
        raise ValueError("img is required")

    events_list = _normalize_events_argument(events, len(imgs))
    bids_root = Path(str(bids_dir)).expanduser().resolve() if bids_dir else None
    resolved: list[dict[str, Any]] = []
    for idx, (img_item, events_item) in enumerate(zip(imgs, events_list)):
        img_path = Path(str(img_item)).expanduser().resolve()
        if not img_path.exists():
            raise FileNotFoundError(f"img not found: {img_path}")
        resolved_events: Path | None = None
        if events_item and str(events_item).strip().lower() != "auto":
            candidate = Path(str(events_item)).expanduser().resolve()
            if not candidate.exists():
                raise FileNotFoundError(f"events not found: {candidate}")
            resolved_events = candidate
        elif bids_root is not None and task:
            resolved_events = _match_event_for_img(
                bids_root,
                img_path,
                task=str(task),
                session=session,
            )
        resolved.append(
            {
                "subject": _subject_from_path(img_path, idx),
                "img": str(img_path),
                "events": str(resolved_events) if resolved_events else None,
                "t_r": _resolve_tr(img_path),
                "source": "direct_inputs",
            }
        )
    return resolved


def _resolve_bids_fmriprep_subject_records(
    *,
    bids_dir: str,
    fmriprep_dir: str,
    task: str,
    participant_label: Sequence[str] | None,
    session: str | None,
    space: str | None,
) -> list[dict[str, Any]]:
    bids_root = Path(str(bids_dir)).expanduser().resolve()
    if not bids_root.exists():
        raise FileNotFoundError(f"BIDS directory not found: {bids_root}")

    fmriprep_root = canonical_fmriprep_root(fmriprep_dir)
    if not fmriprep_root.exists():
        raise FileNotFoundError(f"fMRIPrep directory not found: {fmriprep_root}")

    labels = [canonical_subject_label(label) for label in (participant_label or [])]
    if not labels:
        labels = [path.name for path in _list_subject_dirs(fmriprep_root)]
    if not labels:
        raise ValueError(f"No participant directories found under {fmriprep_root}")

    resolved: list[dict[str, Any]] = []
    missing: list[str] = []
    for label in labels:
        subject_root = fmriprep_root / label
        if not subject_root.exists():
            missing.append(label)
            continue
        candidates = sorted(subject_root.glob(f"**/func/*task-{task}*_bold.nii.gz"))
        if session:
            candidates = [path for path in candidates if f"ses-{session}" in path.name]
        if not candidates:
            missing.append(label)
            continue
        chosen_img = sorted(
            candidates,
            key=lambda path: _preferred_bold_key(path, requested_space=space),
        )[0]
        events_path = _match_event_for_img(
            bids_root,
            chosen_img,
            task=task,
            session=session,
        )
        resolved.append(
            {
                "subject": label,
                "img": str(chosen_img),
                "events": str(events_path) if events_path else None,
                "t_r": _resolve_tr(chosen_img),
                "source": "bids_fmriprep_derivatives",
            }
        )

    if not resolved:
        raise ValueError(
            "No matching preprocessed BOLD images were found for the requested task"
        )
    if missing:
        for record in resolved:
            record["missing_participants"] = list(missing)
    return resolved


def resolve_task_glm_group_inputs(
    *,
    img: str | Sequence[str] | None = None,
    events: str | Sequence[str] | None = None,
    bids_dir: str | None = None,
    fmriprep_dir: str | None = None,
    task: str | None = None,
    participant_label: Sequence[str] | None = None,
    session: str | None = None,
    space: str | None = None,
    contrast_name: str | None = None,
) -> dict[str, Any]:
    if bids_dir and fmriprep_dir and task:
        subject_records = _resolve_bids_fmriprep_subject_records(
            bids_dir=bids_dir,
            fmriprep_dir=fmriprep_dir,
            task=str(task),
            participant_label=participant_label,
            session=session,
            space=space,
        )
        route = "bids_fmriprep_derivatives"
    else:
        subject_records = _resolve_direct_subject_records(
            img=img,
            events=events,
            bids_dir=bids_dir,
            task=task,
            session=session,
        )
        route = "direct_inputs"

    if not subject_records:
        raise ValueError(
            "Provide img/events inputs or bids_dir + fmriprep_dir + task for task GLM"
        )

    resolved_contrast = contrast_name or infer_common_contrast_name(
        [record.get("events") for record in subject_records]
    )
    resolved_tr = next(
        (record.get("t_r") for record in subject_records if record.get("t_r") is not None),
        None,
    )
    return {
        "route": route,
        "subject_records": subject_records,
        "contrast_name": resolved_contrast,
        "n_subjects": len(subject_records),
        "participant_label": [record["subject"][4:] for record in subject_records],
        "task": task,
        "bids_dir": str(Path(str(bids_dir)).expanduser().resolve()) if bids_dir else None,
        "fmriprep_dir": (
            str(canonical_fmriprep_root(fmriprep_dir)) if fmriprep_dir else None
        ),
        "session": session,
        "space": space,
        "t_r": resolved_tr,
    }


def write_task_glm_resolution_manifest(
    output_dir: str | Path,
    payload: dict[str, Any],
) -> str:
    out_root = Path(output_dir).expanduser().resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    manifest_path = out_root / "resolved_inputs_manifest.json"
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(manifest_path)
