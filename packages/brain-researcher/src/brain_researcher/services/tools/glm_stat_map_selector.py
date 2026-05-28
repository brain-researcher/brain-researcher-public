"""Shared selectors for local GLM statistical maps."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from brain_researcher.services.tools.reference_asset_registry import (
    load_reference_assets,
)

_DATASET_ID_RE = re.compile(r"(ds\d{3,})", re.IGNORECASE)
_ENTITY_RE = re.compile(r"^(?P<key>[a-zA-Z0-9]+)-(?P<value>.+)$")
_STATMAP_SUFFIXES = (".nii.gz", ".nii", ".dscalar.nii", ".dlabel.nii")
_STATISTIC_PREFERENCE = {"z": 0, "t": 1, "effect": 2, "variance": 3, "p": 4}


@dataclass(frozen=True)
class GLMStatMapQuery:
    dataset_ref: str | None = None
    query_text: str | None = None
    task: str | None = None
    node: str | None = None
    subject_id: str | None = None
    session_id: str | None = None
    run: str | None = None
    contrast: str | None = None
    statistic: str | None = None
    space: str | None = None


def _normalize_token(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _normalize_dataset_id(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = _DATASET_ID_RE.search(text)
    return (match.group(1) if match else text).lower()


def _normalize_subject_id(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text if text.startswith("sub-") else f"sub-{text}"


def _normalize_session_id(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text if text.startswith("ses-") else f"ses-{text}"


def _strip_statmap_suffix(name: str) -> str:
    for suffix in _STATMAP_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _parse_entities(name: str) -> dict[str, str]:
    entities: dict[str, str] = {}
    for token in _strip_statmap_suffix(name).split("_"):
        if token in {"statmap", "bold", "cope"}:
            continue
        match = _ENTITY_RE.match(token)
        if match is None:
            continue
        key = match.group("key").lower()
        value = match.group("value").strip()
        if value:
            entities[key] = value
    return entities


def _path_format(path: Path) -> str:
    name = path.name
    for suffix in _STATMAP_SUFFIXES:
        if name.endswith(suffix):
            return suffix
    return path.suffix


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _normalize_space_candidates(value: str | None) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []

    candidates = [text]
    lowered = text.lower()
    if lowered.startswith("mni152nlin2009casym"):
        candidates.extend(["MNI152NLin2009cAsym", "MNI152"])
    elif lowered.startswith("mni152nlin6asym"):
        candidates.extend(["MNI152NLin6Asym", "MNI152"])
    elif lowered.startswith("mni152"):
        candidates.extend(["MNI152", "MNI152NLin2009cAsym"])
    return list(dict.fromkeys(candidate for candidate in candidates if candidate))


def _space_matches(candidate: str | None, requested: str | None) -> bool:
    if not requested:
        return True
    candidate_tokens = {
        _normalize_token(value) for value in _normalize_space_candidates(candidate)
    }
    requested_tokens = {
        _normalize_token(value) for value in _normalize_space_candidates(requested)
    }
    candidate_tokens.discard("")
    requested_tokens.discard("")
    if not requested_tokens:
        return True
    if not candidate_tokens:
        return False
    return not requested_tokens.isdisjoint(candidate_tokens)


def _load_openneuro_dataset_description(path: Path) -> dict[str, Any]:
    current = path if path.is_dir() else path.parent
    current = current.resolve()
    for parent in [current, *current.parents]:
        candidate = parent / "dataset_description.json"
        if candidate.exists():
            return _read_json(candidate)
    return {}


@lru_cache(maxsize=1)
def _load_openneuro_glm_manifest() -> dict[str, dict[str, Any]]:
    manifest_path = (
        Path(__file__).resolve().parents[4]
        / "data"
        / "openneuro_glmfitlins"
        / "manifest"
        / "openneuro_glm_statsmaps.json"
    )
    if not manifest_path.exists():
        return {}

    payload = _read_json(manifest_path)
    if not isinstance(payload, list):
        return {}

    by_path: dict[str, dict[str, Any]] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        for key in (
            str(row.get("path") or "").strip(),
            str(row.get("relative_path") or "").strip(),
        ):
            if key:
                by_path[key] = row
    return by_path


def clear_glm_stat_map_selector_cache() -> None:
    _load_openneuro_glm_manifest.cache_clear()


def _manifest_row_for_path(path: Path) -> dict[str, Any]:
    manifest = _load_openneuro_glm_manifest()
    absolute = str(path.resolve())
    if absolute in manifest:
        return manifest[absolute]

    parts = path.parts
    dataset_id = ""
    for part in parts:
        dataset_id = _normalize_dataset_id(part)
        if dataset_id:
            break
    if not dataset_id:
        return {}

    rel_candidates: list[str] = []
    for idx, part in enumerate(parts):
        if _normalize_dataset_id(part) == dataset_id:
            rel_candidates.append("/".join(parts[idx + 1 :]))
            rel_candidates.append("/".join(parts[idx:]))
    for key in rel_candidates:
        if key and key in manifest:
            return manifest[key]
    return {}


def _dataset_id_from_parts(parts: tuple[str, ...]) -> str:
    for part in parts:
        match = _DATASET_ID_RE.search(part)
        if match:
            return match.group(1).lower()
    return ""


def _first_parent_entity(path: Path, prefix: str) -> str:
    needle = f"{prefix}-"
    for parent in path.parents:
        name = parent.name
        if name.startswith(needle):
            return name[len(needle) :]
    return ""


def _node_from_path(path: Path) -> str:
    return _first_parent_entity(path, "node")


def _level_from_node(node: str | None) -> str:
    token = _normalize_token(node)
    if token in {"subjectlevel"}:
        return "subject"
    if token in {"runlevel"}:
        return "run"
    if token in {"sessionlevel"}:
        return "session"
    if token in {"datalevel", "datasetlevel"}:
        return "dataset"
    if token:
        return "group"
    return ""


def _text_score(names: list[str], query_text: str | None) -> int:
    needle_norm = _normalize_token(query_text)
    if not needle_norm:
        return 0

    best = -1
    for name in names:
        candidate_norm = _normalize_token(name)
        if not candidate_norm:
            continue
        if candidate_norm == needle_norm:
            best = max(best, 100)
        elif needle_norm in candidate_norm:
            best = max(best, 60)
        elif candidate_norm in needle_norm:
            best = max(best, 45)
    return best


def _match_value(candidate: str | None, requested: str | None) -> bool:
    if not requested:
        return True
    return _normalize_token(candidate) == _normalize_token(requested)


def _explicit_filter_coverage(query: GLMStatMapQuery, match: dict[str, Any]) -> int:
    coverage = 0
    dataset_id = _normalize_dataset_id(match.get("dataset_id"))
    if query.dataset_ref and dataset_id == _normalize_dataset_id(query.dataset_ref):
        coverage += 1
    if query.task and _match_value(match.get("task"), query.task):
        coverage += 1
    if query.node and _match_value(match.get("node"), query.node):
        coverage += 1
    if query.subject_id and _match_value(
        match.get("subject_id"), _normalize_subject_id(query.subject_id)
    ):
        coverage += 1
    if query.session_id and _match_value(
        match.get("session_id"), _normalize_session_id(query.session_id)
    ):
        coverage += 1
    if query.run and _match_value(match.get("run"), query.run):
        coverage += 1
    if query.contrast and _match_value(match.get("contrast"), query.contrast):
        coverage += 1
    if query.statistic and _match_value(match.get("statistic"), query.statistic):
        coverage += 1
    if query.space and _space_matches(match.get("space"), query.space):
        coverage += 1
    return coverage


def _matches_structured_filters(query: GLMStatMapQuery, match: dict[str, Any]) -> bool:
    if query.dataset_ref and _normalize_dataset_id(
        match.get("dataset_id")
    ) != _normalize_dataset_id(query.dataset_ref):
        return False
    if query.task and not _match_value(match.get("task"), query.task):
        return False
    if query.node and not _match_value(match.get("node"), query.node):
        return False
    if query.subject_id and not _match_value(
        match.get("subject_id"), _normalize_subject_id(query.subject_id)
    ):
        return False
    if query.session_id and not _match_value(
        match.get("session_id"), _normalize_session_id(query.session_id)
    ):
        return False
    if query.run and not _match_value(match.get("run"), query.run):
        return False
    if query.contrast and not _match_value(match.get("contrast"), query.contrast):
        return False
    if query.statistic and not _match_value(match.get("statistic"), query.statistic):
        return False
    if query.space:
        candidate_space = str(match.get("space") or "").strip()
        if candidate_space and not _space_matches(candidate_space, query.space):
            return False
    return True


def _match_names(match: dict[str, Any]) -> list[str]:
    names = [
        str(match.get("path") or ""),
        str(match.get("asset_id") or ""),
        str(match.get("canonical_runtime_name") or ""),
        str(match.get("dataset_id") or ""),
        str(match.get("task") or ""),
        str(match.get("node") or ""),
        str(match.get("contrast") or ""),
        str(match.get("statistic") or ""),
        str(match.get("subject_id") or ""),
    ]
    if match.get("task") and match.get("contrast") and match.get("statistic"):
        names.append(f"{match['task']}_{match['contrast']}_{match['statistic']}")
    if match.get("dataset_id") and match.get("contrast") and match.get("statistic"):
        names.append(f"{match['dataset_id']}_{match['contrast']}_{match['statistic']}")
    if match.get("aliases"):
        names.extend([str(value) for value in match.get("aliases") or []])
    return names


def _rank_match(
    query: GLMStatMapQuery, match: dict[str, Any]
) -> tuple[int, int, int, str]:
    coverage = _explicit_filter_coverage(query, match)
    source_priority = 0 if match.get("source") == "openneuro_registry" else 1
    text_score = _text_score(_match_names(match), query.query_text)
    statistic = str(match.get("statistic") or "").lower()
    stat_priority = _STATISTIC_PREFERENCE.get(statistic, 99)
    if query.statistic:
        stat_priority = -1
    return (
        -coverage,
        source_priority,
        -text_score,
        stat_priority,
        str(match.get("path") or ""),
    )


def _registry_glm_matches(query: GLMStatMapQuery) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for asset in load_reference_assets():
        if asset.get("kind") != "reference_map":
            continue
        if asset.get("family") != "openneuro_glmfitlins_stat_map":
            continue
        metadata = asset.get("metadata") or {}
        local_paths = [
            Path(path).resolve()
            for path in asset.get("local_paths") or []
            if Path(path).exists()
        ]
        if not local_paths:
            continue
        path = local_paths[0]
        contrast = metadata.get("contrast") or metadata.get("description_key") or ""
        match = {
            "path": str(path),
            "source_path": str(path),
            "source": "openneuro_registry",
            "derivative_kind": "glmfitlins",
            "dataset_id": metadata.get("dataset_id") or "",
            "task": metadata.get("task") or "",
            "node": metadata.get("node") or "",
            "level": metadata.get("level") or _level_from_node(metadata.get("node")),
            "subject_id": metadata.get("subject_id") or "",
            "session_id": metadata.get("session_id") or "",
            "run": metadata.get("run") or "",
            "contrast": contrast,
            "statistic": metadata.get("statistic") or "",
            "space": metadata.get("space") or "",
            "space_inferred": bool(metadata.get("space_inferred")),
            "format": asset.get("formats", [""])[0] if asset.get("formats") else "",
            "asset_id": asset.get("id") or "",
            "canonical_runtime_name": asset.get("canonical_runtime_name") or "",
            "aliases": list(asset.get("aliases") or []),
        }
        if not _matches_structured_filters(query, match):
            continue
        if query.query_text and _text_score(_match_names(match), query.query_text) < 0:
            continue
        matches.append(match)
    return matches


def _statmap_paths(root: Path) -> list[Path]:
    matches: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        name = path.name
        if "statmap" not in name:
            continue
        if not any(name.endswith(suffix) for suffix in _STATMAP_SUFFIXES):
            continue
        matches.append(path.resolve())
    return matches


def _generic_glm_match(
    path: Path, derivative_kind: str, root: Path
) -> dict[str, Any] | None:
    entities = _parse_entities(path.name)
    statistic = entities.get("stat") or ""
    contrast = entities.get("contrast") or entities.get("desc") or ""
    if not statistic or not contrast:
        return None

    node = _node_from_path(path)
    dataset_id = _dataset_id_from_parts(path.parts)
    task = entities.get("task") or _first_parent_entity(path, "task")
    subject_id = entities.get("sub") or _first_parent_entity(path, "sub")
    if subject_id:
        subject_id = _normalize_subject_id(subject_id)
    session_id = entities.get("ses") or _first_parent_entity(path, "ses")
    if session_id:
        session_id = _normalize_session_id(session_id)
    run = entities.get("run") or ""
    space = entities.get("space") or ""
    description = _load_openneuro_dataset_description(path)
    pipeline = description.get("PipelineDescription") or {}
    parameters = pipeline.get("Parameters") or {}
    if not space:
        space = str(parameters.get("space") or "").strip()

    manifest_row = _manifest_row_for_path(path)
    if manifest_row:
        dataset_id = _normalize_dataset_id(manifest_row.get("dataset_id")) or dataset_id
        task = str(manifest_row.get("task") or task).strip()
        node = str(manifest_row.get("node_name") or node).strip()
        subject_id = _normalize_subject_id(manifest_row.get("subject") or subject_id)
        session_id = _normalize_session_id(manifest_row.get("session") or session_id)
        run = str(manifest_row.get("run") or run).strip()
        contrast = str(manifest_row.get("contrast") or contrast).strip()
        statistic = str(manifest_row.get("stat") or statistic).strip()
        space = str(manifest_row.get("space") or space).strip()

    return {
        "path": str(path),
        "source_path": str(path),
        "source": "generic_derivative_scan",
        "derivative_kind": derivative_kind,
        "dataset_id": dataset_id,
        "task": task,
        "node": node,
        "level": str(manifest_row.get("level") or _level_from_node(node)),
        "subject_id": subject_id,
        "session_id": session_id,
        "run": run,
        "contrast": contrast,
        "statistic": statistic,
        "space": space,
        "space_inferred": not bool(entities.get("space")) and bool(space),
        "format": str(manifest_row.get("format") or _path_format(path)),
        "asset_id": str(manifest_row.get("id") or ""),
        "canonical_runtime_name": "",
        "aliases": [
            path.name,
            contrast,
            f"{contrast}_{statistic}",
            f"{task}_{contrast}_{statistic}" if task else "",
            f"{dataset_id}_{contrast}_{statistic}" if dataset_id else "",
        ],
        "root": str(root.resolve()),
    }


def _generic_glm_matches(
    query: GLMStatMapQuery,
    derivative_roots: dict[str, str | Path],
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    preferred = ["glmfitlins"]
    ordered_items = []
    seen_kinds: set[str] = set()
    for derivative_kind in preferred:
        if derivative_kind in derivative_roots:
            ordered_items.append((derivative_kind, derivative_roots[derivative_kind]))
            seen_kinds.add(derivative_kind)
    for derivative_kind, root in derivative_roots.items():
        if derivative_kind in seen_kinds:
            continue
        ordered_items.append((derivative_kind, root))

    for derivative_kind, root in ordered_items:
        root_path = Path(root).expanduser().resolve()
        if not root_path.exists():
            continue
        for path in _statmap_paths(root_path):
            match = _generic_glm_match(path, derivative_kind, root_path)
            if match is None:
                continue
            if not _matches_structured_filters(query, match):
                continue
            if (
                query.query_text
                and _text_score(_match_names(match), query.query_text) < 0
            ):
                continue
            matches.append(match)
    return matches


def select_glm_stat_map_matches(
    *,
    query: GLMStatMapQuery,
    derivative_roots: dict[str, str | Path] | None = None,
    include_registry: bool = True,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    if include_registry:
        matches.extend(_registry_glm_matches(query))
    if derivative_roots:
        matches.extend(_generic_glm_matches(query, derivative_roots))

    deduped: dict[str, dict[str, Any]] = {}
    for match in matches:
        key = str(Path(match["path"]).resolve())
        current = deduped.get(key)
        if current is None or _rank_match(query, match) < _rank_match(query, current):
            deduped[key] = match

    ordered = list(deduped.values())
    ordered.sort(key=lambda match: _rank_match(query, match))
    return ordered


__all__ = [
    "GLMStatMapQuery",
    "clear_glm_stat_map_selector_cache",
    "select_glm_stat_map_matches",
]
