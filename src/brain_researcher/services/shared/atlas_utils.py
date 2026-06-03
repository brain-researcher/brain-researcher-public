"""Shared atlas path helpers for Nilearn-based tools."""

from __future__ import annotations

import csv
import importlib
import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import nibabel as nib
import numpy as np
import yaml

from brain_researcher.config.paths import (
    get_data_root,
    get_default_atlas_output_root,
)

_DEFAULT_SCHAEFER_SEARCH_ROOTS = [
    "/app/data/atlases",
    "/app/data",
    "/srv/datasets/atlases",
    "/srv/datasets",
    "/data/atlases",
    "/data/brain_researcher_data",
    "/data",
]
_SCHAEFER_FILENAME_RE = re.compile(
    r"^Schaefer2018_(\d+)Parcels_(7|17)Networks_order_FSLMNI152_2mm\.nii(?:\.gz)?$"
)
_TEMPLATEFLOW_SCHAEFER_PATTERNS = (
    "tpl-*_atlas-Schaefer2018*_desc-*Parcels*Networks_dseg.nii*",
)
_TEMPLATEFLOW_IMAGE_EXTENSIONS = (".nii.gz", ".nii")
_TEMPLATEFLOW_DEFAULT_TEMPLATES = (
    "MNI152NLin2009cAsym",
    "MNI152NLin6Asym",
    "MNI152Lin",
)
_TEMPLATEFLOW_TEMPLATE_ALIASES = {
    "MNI152": _TEMPLATEFLOW_DEFAULT_TEMPLATES,
    "MNI152NLIN2009CASYM": ("MNI152NLin2009cAsym",),
    "MNI152NLIN6ASYM": ("MNI152NLin6Asym",),
    "MNI152LIN": ("MNI152Lin",),
    "FSLMNI152": ("MNI152NLin6Asym", "MNI152Lin"),
}
_DIFUMO_PATTERNS = (
    "tpl-*_atlas-DiFuMo_*_probseg.nii*",
    "atlas-DiFuMo_dimension-*_data-MNI152_*.nii*",
    "DiFuMo_*.nii*",
)
_BIDS_ENTITY_RE = re.compile(r"(?:^|_)(?P<key>[A-Za-z0-9]+)-(?P<value>[^_]+)")
_MAX_ATLAS_SEARCH_DIRS = 5000
_HARVARD_OXFORD_VARIANT_ALIASES = {
    "harvard_oxford": "cort-maxprob-thr25-2mm",
    "harvard-oxford": "cort-maxprob-thr25-2mm",
    "harvard_oxford_cort25": "cort-maxprob-thr25-2mm",
    "harvard-oxford-cort25": "cort-maxprob-thr25-2mm",
    "harvard_oxford_cort-maxprob-thr25-2mm": "cort-maxprob-thr25-2mm",
    "harvard-oxford-cort-maxprob-thr25-2mm": "cort-maxprob-thr25-2mm",
    "harvard_oxford_sub25": "sub-maxprob-thr25-2mm",
    "harvard-oxford-sub25": "sub-maxprob-thr25-2mm",
    "harvard_oxford_sub-maxprob-thr25-2mm": "sub-maxprob-thr25-2mm",
    "harvard-oxford-sub-maxprob-thr25-2mm": "sub-maxprob-thr25-2mm",
}
_YEO_VARIANT_ALIASES = {
    "yeo": 7,
    "yeo7": 7,
    "yeo_7": 7,
    "yeo_2011": 7,
    "yeo_2011_7": 7,
    "yeo17": 17,
    "yeo_17": 17,
    "yeo_2011_17": 17,
}
_ATLAS_FAMILY_DIRS = {
    "schaefer": "schaefer_2018",
    "aal": "aal",
    "harvard_oxford": "harvard_oxford",
    "yeo": "yeo_2011",
    "destrieux": "destrieux_2009",
    "basc": "basc_multiscale_2015",
    "msdl": "msdl_atlas",
    "difumo": "difumo",
}


def repo_data_dir() -> Path:
    return get_data_root()


def templateflow_root() -> Path | None:
    explicit = os.getenv("TEMPLATEFLOW_HOME", "").strip()
    if explicit:
        root = Path(explicit).expanduser().resolve()
        if root.exists() and root.is_dir():
            return root

    mounts_path = repo_data_dir().parent / "configs" / "datasets" / "local_mounts.yaml"
    if not mounts_path.exists():
        return None
    try:
        payload = yaml.safe_load(mounts_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    resources = (payload.get("oak_mount") or {}).get("resources") or {}
    raw = str(resources.get("templateflow") or "").strip()
    if not raw:
        return None
    root = Path(raw).expanduser().resolve()
    return root if root.exists() and root.is_dir() else None


def default_atlas_output_root() -> Path:
    return get_default_atlas_output_root()


def parse_schaefer_n_rois(atlas_name: str) -> int:
    for part in str(atlas_name or "").split("_"):
        if part.isdigit():
            return int(part)
    return 200


def parse_schaefer_yeo_networks(atlas_name: str) -> int:
    atlas_key = str(atlas_name or "").strip().lower()
    if "17network" in atlas_key or "_17n" in atlas_key or atlas_key.endswith("_17"):
        return 17
    if "7network" in atlas_key or "_7n" in atlas_key or atlas_key.endswith("_7"):
        return 7
    return 7


def schaefer_output_root(base_root: Path) -> Path:
    return base_root / "schaefer_2018"


def atlas_family_output_root(base_root: Path, family: str) -> Path:
    return base_root / family


def symbolic_atlas_family(atlas_name: str) -> str | None:
    atlas_key = str(atlas_name or "").strip().lower()
    if atlas_key.startswith("schaefer2018"):
        return _ATLAS_FAMILY_DIRS["schaefer"]
    if atlas_key in {"aal", "aal_2mm", "aal3"}:
        return _ATLAS_FAMILY_DIRS["aal"]
    if "harvard" in atlas_key:
        return _ATLAS_FAMILY_DIRS["harvard_oxford"]
    if "yeo" in atlas_key:
        return _ATLAS_FAMILY_DIRS["yeo"]
    if "destrieux" in atlas_key:
        return _ATLAS_FAMILY_DIRS["destrieux"]
    if "basc" in atlas_key:
        return _ATLAS_FAMILY_DIRS["basc"]
    if "msdl" in atlas_key:
        return _ATLAS_FAMILY_DIRS["msdl"]
    if "difumo" in atlas_key:
        return _ATLAS_FAMILY_DIRS["difumo"]
    return None


def is_path_like_atlas(atlas: str) -> bool:
    atlas = str(atlas or "").strip()
    if not atlas:
        return False
    path = Path(atlas)
    if path.is_absolute():
        return True
    if "/" in atlas or "\\" in atlas:
        return True
    if atlas.startswith("."):
        return True
    lower = atlas.lower()
    return lower.endswith(".nii") or lower.endswith(".nii.gz")


def atlas_labels_from_image(path: Path) -> list[str]:
    atlas_img = nib.load(path)
    data = atlas_img.get_fdata()
    if data.ndim >= 4:
        n_rois = int(data.shape[3])
        return ["background"] + [f"roi_{idx:03d}" for idx in range(1, n_rois + 1)]
    unique_labels = np.unique(data).astype(int)
    roi_labels = [val for val in unique_labels if val > 0]
    return ["background"] + [f"roi_{int(val):03d}" for val in roi_labels]


def atlas_artifact_stem(path: Path) -> str:
    if path.name.endswith(".nii.gz"):
        return path.name[: -len(".nii.gz")]
    return path.stem


def filename_entities(path_or_name: str | os.PathLike[str]) -> dict[str, str]:
    name = Path(path_or_name).name
    stem = name[: -len(".nii.gz")] if name.endswith(".nii.gz") else Path(name).stem
    entities: dict[str, str] = {}
    for match in _BIDS_ENTITY_RE.finditer(stem):
        entities[match.group("key")] = match.group("value")
    return entities


def atlas_reference_hints(
    reference_img: str | os.PathLike[str] | None,
) -> tuple[str | None, str | None]:
    if not reference_img:
        return None, None
    entities = filename_entities(reference_img)
    return entities.get("space") or entities.get("tpl"), entities.get("res")


def atlas_label_paths(
    atlas_path: Path, output_dir: Path | None = None
) -> tuple[Path, Path]:
    base_dir = output_dir or atlas_path.parent
    stem = atlas_artifact_stem(atlas_path)
    return (
        base_dir / f"{stem}_labels.tsv",
        base_dir / f"{stem}_labels.json",
    )


def read_labels_sidecar(atlas_path: Path) -> list[str] | None:
    tsv_path, json_path = atlas_label_paths(atlas_path)
    legacy_tsv = atlas_path.parent / f"{atlas_path.stem}_labels.tsv"
    legacy_json = atlas_path.parent / f"{atlas_path.stem}_labels.json"

    for candidate in (tsv_path, legacy_tsv):
        if candidate.exists():
            labels = [
                line.strip()
                for line in candidate.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            if labels:
                return labels

    for candidate in (json_path, legacy_json):
        if candidate.exists():
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                return [str(item) for item in payload]

    return None


def write_labels_sidecars(
    atlas_path: Path,
    labels: list[object],
    output_dir: Path | None = None,
) -> tuple[Path, Path]:
    normalized = [str(label) for label in labels]
    tsv_path, json_path = atlas_label_paths(atlas_path, output_dir=output_dir)
    tsv_path.write_text("\n".join(normalized), encoding="utf-8")
    json_path.write_text(json.dumps(normalized, indent=2), encoding="utf-8")
    return tsv_path, json_path


def existing_search_roots(data_dir: str | None, output_root: Path) -> list[Path]:
    env_roots_raw = os.getenv("BR_ATLAS_SEARCH_ROOTS", "").strip()
    env_roots = [item.strip() for item in env_roots_raw.split(",") if item.strip()]
    roots: list[Path] = []
    tf_root = templateflow_root()
    if tf_root is not None:
        roots.append(tf_root)
    roots.extend(Path(p) for p in (env_roots or _DEFAULT_SCHAEFER_SEARCH_ROOTS))
    roots.append(repo_data_dir())
    if data_dir:
        roots.append(Path(data_dir))
    roots.append(output_root)

    unique_roots: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        try:
            resolved = root.resolve()
        except Exception:
            resolved = root
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        if resolved.exists() and resolved.is_dir():
            unique_roots.append(resolved)
    return unique_roots


def walk_schaefer_files(root: Path, n_rois: int | None = None) -> list[Path]:
    matches: list[Path] = []
    scanned_dirs = 0
    for dirpath, _, filenames in os.walk(root):
        scanned_dirs += 1
        if scanned_dirs > _MAX_ATLAS_SEARCH_DIRS:
            break
        for filename in filenames:
            match = _SCHAEFER_FILENAME_RE.match(filename)
            if match is None:
                continue
            if n_rois is not None and int(match.group(1)) != int(n_rois):
                continue
            matches.append(Path(dirpath) / filename)
    matches.sort()
    return matches


def _normalize_resolution_entity(value: str | int | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if text.endswith("mm"):
        text = text[: -len("mm")]
    if text.isdigit():
        text = str(int(text))
    return text or None


def _normalize_templateflow_template(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[4:] if text.startswith("tpl-") else text


def _templateflow_template_candidates(space: str | None) -> list[str]:
    explicit = _normalize_templateflow_template(space)
    candidates: list[str] = []
    if explicit:
        alias_key = explicit.upper()
        candidates.extend(_TEMPLATEFLOW_TEMPLATE_ALIASES.get(alias_key, (explicit,)))
    candidates.extend(_TEMPLATEFLOW_DEFAULT_TEMPLATES)

    ordered: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = _normalize_templateflow_template(candidate)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _templateflow_resolution_candidates(
    resolution: str | int | None,
) -> list[int | None]:
    normalized = _normalize_resolution_entity(resolution)
    if normalized and normalized.isdigit():
        return [int(normalized), None]
    return [None]


def _templateflow_candidate_preference(
    path: Path,
    *,
    space: str | None = None,
    resolution: str | int | None = None,
) -> tuple[int, int]:
    entities = filename_entities(path)
    candidate_space = entities.get("tpl")
    candidate_res = _normalize_resolution_entity(entities.get("res"))
    wanted_res = _normalize_resolution_entity(resolution)
    return (
        int(not space or candidate_space == space),
        int(wanted_res is None or candidate_res == wanted_res),
    )


def _select_preferred_templateflow_candidate(
    candidates: list[Path],
    *,
    space: str | None = None,
    resolution: str | int | None = None,
) -> Path | None:
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda path: _templateflow_candidate_preference(
            path,
            space=space,
            resolution=resolution,
        ),
    )


def find_local_schaefer_atlas(
    n_rois: int,
    roots: list[Path],
    yeo_networks: int | None = None,
    *,
    space: str | None = None,
    resolution: str | int | None = None,
    include_legacy: bool = True,
) -> Path | None:
    network_order = [yeo_networks] if yeo_networks in {7, 17} else [7, 17]
    search_roots: list[Path] = []
    tf_root = templateflow_root()
    if tf_root is not None:
        search_roots.append(tf_root)
    search_roots.extend(roots)
    templateflow_candidates: list[Path] = []

    candidate_filenames: list[str] = []
    for n_networks in network_order:
        candidate_filenames.extend(
            [
                f"Schaefer2018_{n_rois}Parcels_{n_networks}Networks_order_FSLMNI152_2mm.nii.gz",
                f"Schaefer2018_{n_rois}Parcels_{n_networks}Networks_order_FSLMNI152_2mm.nii",
            ]
        )
    relative_candidates = [
        Path(""),
        Path("schaefer_2018"),
        Path("atlases/schaefer_2018"),
        Path("br-kg/raw/nilearn_atlases/schaefer_2018"),
    ]

    for tf_dir in _templateflow_search_dirs(search_roots, space=space):
        for path in sorted(tf_dir.glob("*.nii*")):
            if not _templateflow_schaefer_candidate(path) or not _is_nonempty_file(
                path
            ):
                continue
            match = re.search(
                r"desc-(?P<rois>\d+)Parcels(?P<networks>\d+)Networks", path.name
            )
            if match is None:
                continue
            if int(match.group("rois")) != int(n_rois):
                continue
            if yeo_networks in {7, 17} and int(match.group("networks")) != int(
                yeo_networks
            ):
                continue
            templateflow_candidates.append(path)

    preferred = _select_preferred_templateflow_candidate(
        templateflow_candidates,
        space=space,
        resolution=resolution,
    )
    if preferred is not None:
        return preferred
    if not include_legacy:
        return None

    for root in search_roots:
        for rel in relative_candidates:
            base = root / rel
            if not base.exists():
                continue
            for candidate in candidate_filenames:
                atlas_path = base / candidate
                if _is_nonempty_file(atlas_path):
                    return atlas_path

    for root in search_roots:
        deep_matches = walk_schaefer_files(root, n_rois=n_rois)
        if not deep_matches:
            continue
        for n_networks in network_order:
            for path in deep_matches:
                match = _SCHAEFER_FILENAME_RE.match(path.name)
                if match is None:
                    continue
                if int(match.group(2)) == int(n_networks):
                    return path
        return deep_matches[0]
    return None


def normalize_harvard_oxford_variant(atlas_name: str) -> str:
    atlas_key = str(atlas_name or "").strip().lower()
    return _HARVARD_OXFORD_VARIANT_ALIASES.get(
        atlas_key,
        "sub-maxprob-thr25-2mm" if "sub" in atlas_key else "cort-maxprob-thr25-2mm",
    )


def parse_yeo_networks(atlas_name: str) -> int:
    atlas_key = str(atlas_name or "").strip().lower()
    if atlas_key in _YEO_VARIANT_ALIASES:
        return _YEO_VARIANT_ALIASES[atlas_key]
    if "17" in atlas_key:
        return 17
    return 7


def parse_basc_scale(atlas_name: str) -> int:
    atlas_key = str(atlas_name or "").strip().lower()
    for pattern in (
        r"scale[_-]?(\d+)",
        r"basc[_-]?(\d+)",
        r"resolution[_-]?(\d+)",
    ):
        match = re.search(pattern, atlas_key)
        if match:
            return int(match.group(1))
    return 122


def _walk_named_files(root: Path, filenames: list[str]) -> list[Path]:
    matches: list[Path] = []
    scanned_dirs = 0
    normalized = {name.lower() for name in filenames}
    for dirpath, _, file_names in os.walk(root):
        scanned_dirs += 1
        if scanned_dirs > _MAX_ATLAS_SEARCH_DIRS:
            break
        for filename in file_names:
            if filename.lower() in normalized:
                matches.append(Path(dirpath) / filename)
    matches.sort()
    return matches


def _walk_pattern_files(root: Path, patterns: tuple[str, ...]) -> list[Path]:
    matches: list[Path] = []
    scanned_dirs = 0
    for dirpath, _, file_names in os.walk(root):
        scanned_dirs += 1
        if scanned_dirs > _MAX_ATLAS_SEARCH_DIRS:
            break
        for filename in file_names:
            if any(Path(filename).match(pattern) for pattern in patterns):
                matches.append(Path(dirpath) / filename)
    matches.sort()
    return matches


def _templateflow_search_dirs(
    roots: list[Path],
    *,
    space: str | None = None,
) -> list[Path]:
    matches: list[Path] = []
    seen: set[str] = set()

    for root in roots:
        if not root.exists() or not root.is_dir():
            continue

        candidates: list[Path] = []
        if root.name.startswith("tpl-"):
            candidates.append(root)
        else:
            if space:
                candidates.append(root / f"tpl-{space}")
            candidates.extend(
                sorted(path for path in root.glob("tpl-*") if path.is_dir())
            )

        for candidate in candidates:
            if not candidate.exists() or not candidate.is_dir():
                continue
            try:
                resolved = candidate.resolve()
            except Exception:
                resolved = candidate
            key = str(resolved)
            if key in seen:
                continue
            seen.add(key)
            matches.append(resolved)

    return matches


def _templateflow_schaefer_candidate(path: Path) -> bool:
    name = path.name
    return "atlas-Schaefer2018" in name and "desc-" in name and "dseg" in name


def _templateflow_difumo_candidate(path: Path) -> bool:
    name = path.name
    return (
        "atlas-DiFuMo" in name
        or ("DiFuMo" in name and name.endswith(".nii.gz"))
        or ("DiFuMo" in name and name.endswith(".nii"))
    )


def _import_templateflow_api():
    try:
        return importlib.import_module("templateflow.api")
    except ImportError:
        return None


def _as_path_list(paths: object) -> list[Path]:
    if isinstance(paths, str | os.PathLike):
        return [Path(paths)]
    if isinstance(paths, list | tuple | set):
        return [Path(item) for item in paths if isinstance(item, str | os.PathLike)]
    return []


def _templateflow_get_first_path(
    *,
    atlas: str,
    desc: str,
    suffix: str,
    space: str | None = None,
    resolution: str | int | None = None,
) -> Path | None:
    templateflow_api = _import_templateflow_api()
    if templateflow_api is None:
        return None

    base_query = {
        "atlas": atlas,
        "desc": desc,
        "suffix": suffix,
        "extension": list(_TEMPLATEFLOW_IMAGE_EXTENSIONS),
    }
    for template in _templateflow_template_candidates(space):
        for query_resolution in _templateflow_resolution_candidates(resolution):
            query = dict(base_query)
            if query_resolution is not None:
                query["resolution"] = query_resolution
            try:
                result = templateflow_api.get(
                    template,
                    raise_empty=True,
                    **query,
                )
            except Exception:
                continue
            for path in _as_path_list(result):
                if _is_nonempty_file(path):
                    _prefetch_templateflow_sidecar(
                        templateflow_api,
                        template=template,
                        atlas=atlas,
                        desc=desc,
                        suffix=suffix,
                        resolution=query_resolution,
                    )
                    return path
    return None


def _prefetch_templateflow_sidecar(
    templateflow_api,
    *,
    template: str,
    atlas: str,
    desc: str,
    suffix: str,
    resolution: int | None = None,
) -> None:
    query = {
        "atlas": atlas,
        "desc": desc,
        "suffix": suffix,
        "extension": ".tsv",
    }
    if resolution is not None:
        query["resolution"] = resolution
    try:
        templateflow_api.get(template, raise_empty=True, **query)
    except Exception:
        return


def _is_nonempty_file(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def find_local_aal_atlas(roots: list[Path]) -> Path | None:
    candidate_filenames = [
        "AAL.nii.gz",
        "AAL.nii",
        "ROI_MNI_V4.nii.gz",
        "ROI_MNI_V4.nii",
    ]
    relative_candidates = [
        Path(""),
        Path("aal"),
        Path("atlases/aal"),
        Path("br-kg/raw/nilearn_atlases/aal_SPM12/aal/atlas"),
        Path("br-kg/raw/nilearn_atlases/aal_SPM12/aal"),
    ]
    for root in roots:
        for rel in relative_candidates:
            base = root / rel
            if not base.exists():
                continue
            for candidate in candidate_filenames:
                atlas_path = base / candidate
                if atlas_path.exists():
                    return atlas_path
    for root in roots:
        deep_matches = _walk_named_files(root, candidate_filenames)
        if deep_matches:
            return deep_matches[0]
    return None


def find_local_harvard_oxford_atlas(
    variant: str,
    roots: list[Path],
) -> Path | None:
    candidate_filenames = [
        f"HarvardOxford-{variant}.nii.gz",
        f"HarvardOxford-{variant}.nii",
    ]
    relative_candidates = [
        Path(""),
        Path("harvard_oxford"),
        Path("atlases/harvard_oxford"),
        Path("br-kg/raw/nilearn_atlases/fsl/data/atlases/HarvardOxford"),
    ]
    for root in roots:
        for rel in relative_candidates:
            base = root / rel
            if not base.exists():
                continue
            for candidate in candidate_filenames:
                atlas_path = base / candidate
                if atlas_path.exists():
                    return atlas_path
    for root in roots:
        deep_matches = _walk_named_files(root, candidate_filenames)
        if deep_matches:
            return deep_matches[0]
    return None


def find_local_yeo_atlas(n_networks: int, roots: list[Path]) -> Path | None:
    candidate_filenames = [
        f"Yeo2011_{n_networks}Networks_MNI152_FreeSurferConformed1mm_LiberalMask.nii.gz",
        f"Yeo2011_{n_networks}Networks_MNI152_FreeSurferConformed1mm.nii.gz",
    ]
    relative_candidates = [
        Path(""),
        Path("yeo_2011"),
        Path("atlases/yeo_2011"),
        Path("br-kg/raw/nilearn_atlases/yeo_2011/Yeo_JNeurophysiol11_MNI152"),
    ]
    for root in roots:
        for rel in relative_candidates:
            base = root / rel
            if not base.exists():
                continue
            for candidate in candidate_filenames:
                atlas_path = base / candidate
                if atlas_path.exists():
                    return atlas_path
    for root in roots:
        deep_matches = _walk_named_files(root, candidate_filenames)
        if deep_matches:
            return deep_matches[0]
    return None


def find_local_destrieux_atlas(
    roots: list[Path],
    *,
    lateralized: bool = False,
) -> Path | None:
    candidate_filenames = [
        "destrieux2009_rois_lateralized.nii.gz"
        if lateralized
        else "destrieux2009_rois.nii.gz"
    ]
    relative_candidates = [
        Path(""),
        Path("destrieux_2009"),
        Path("atlases/destrieux_2009"),
        Path("br-kg/raw/nilearn_atlases/destrieux_2009"),
    ]
    for root in roots:
        for rel in relative_candidates:
            base = root / rel
            if not base.exists():
                continue
            for candidate in candidate_filenames:
                atlas_path = base / candidate
                if atlas_path.exists():
                    return atlas_path
    for root in roots:
        deep_matches = _walk_named_files(root, candidate_filenames)
        if deep_matches:
            return deep_matches[0]
    return None


def find_local_basc_atlas(scale: int, roots: list[Path]) -> Path | None:
    candidate = f"template_cambridge_basc_multiscale_sym_scale{int(scale):03d}.nii.gz"
    relative_candidates = [
        Path(""),
        Path("basc_multiscale_2015"),
        Path("atlases/basc_multiscale_2015"),
        Path(
            "br-kg/raw/nilearn_atlases/basc_multiscale_2015/"
            "template_cambridge_basc_multiscale_nii_sym"
        ),
    ]
    for root in roots:
        for rel in relative_candidates:
            base = root / rel
            if not base.exists():
                continue
            atlas_path = base / candidate
            if atlas_path.exists():
                return atlas_path
    for root in roots:
        deep_matches = _walk_named_files(root, [candidate])
        if deep_matches:
            return deep_matches[0]
    return None


def find_local_msdl_atlas(roots: list[Path]) -> Path | None:
    candidate_filenames = ["msdl_rois.nii", "msdl_rois.nii.gz"]
    relative_candidates = [
        Path(""),
        Path("msdl_atlas"),
        Path("atlases/msdl_atlas"),
        Path("br-kg/raw/nilearn_atlases/msdl_atlas/MSDL_rois"),
    ]
    for root in roots:
        for rel in relative_candidates:
            base = root / rel
            if not base.exists():
                continue
            for candidate in candidate_filenames:
                atlas_path = base / candidate
                if atlas_path.exists():
                    return atlas_path
    for root in roots:
        deep_matches = _walk_named_files(root, candidate_filenames)
        if deep_matches:
            return deep_matches[0]
    return None


def find_local_difumo_atlas(
    roots: list[Path],
    dimension: int | None = None,
    *,
    space: str | None = None,
    resolution: str | int | None = None,
) -> Path | None:
    dimension_text = str(int(dimension)) if dimension else ""
    search_roots: list[Path] = []
    tf_root = templateflow_root()
    if tf_root is not None:
        search_roots.append(tf_root)
    search_roots.extend(roots)
    templateflow_candidates: list[Path] = []
    legacy_candidates: list[Path] = []
    candidate_filenames = []
    if dimension_text:
        candidate_filenames.extend(
            [
                f"atlas-DiFuMo_dimension-{dimension_text}_data-MNI152_2mm.nii.gz",
                f"atlas-DiFuMo_dimension-{dimension_text}_data-MNI152_2mm.nii",
                f"DiFuMo_{dimension_text}.nii.gz",
                f"DiFuMo_{dimension_text}.nii",
            ]
        )
    relative_candidates = [
        Path(""),
        Path("difumo"),
        Path("atlases/difumo"),
        Path("br-kg/raw/nilearn_atlases/difumo"),
    ]
    for tf_dir in _templateflow_search_dirs(search_roots, space=space):
        for path in sorted(tf_dir.glob("*.nii*")):
            if not _templateflow_difumo_candidate(path) or not _is_nonempty_file(path):
                continue
            if dimension_text and dimension_text not in path.name:
                continue
            templateflow_candidates.append(path)

    preferred = _select_preferred_templateflow_candidate(
        templateflow_candidates,
        space=space,
        resolution=resolution,
    )
    if preferred is not None:
        return preferred

    for root in search_roots:
        for rel in relative_candidates:
            base = root / rel
            if not base.exists():
                continue
            if candidate_filenames:
                for candidate in candidate_filenames:
                    atlas_path = base / candidate
                    if _is_nonempty_file(atlas_path):
                        legacy_candidates.append(atlas_path)
            for path in _walk_pattern_files(base, _DIFUMO_PATTERNS):
                if not _templateflow_difumo_candidate(path) or not _is_nonempty_file(
                    path
                ):
                    continue
                if dimension_text and dimension_text not in path.name:
                    continue
                legacy_candidates.append(path)
    if legacy_candidates:
        return min(legacy_candidates, key=str)

    for root in search_roots:
        deep_matches = _walk_pattern_files(root, _DIFUMO_PATTERNS)
        deep_matches = [path for path in deep_matches if _is_nonempty_file(path)]
        if dimension_text:
            deep_matches = [
                path for path in deep_matches if dimension_text in path.name
            ]
        if deep_matches:
            return deep_matches[0]
    return None


def fetch_templateflow_schaefer_atlas(
    n_rois: int,
    *,
    yeo_networks: int = 7,
    space: str | None = None,
    resolution: str | int | None = None,
) -> Path | None:
    return _templateflow_get_first_path(
        atlas="Schaefer2018",
        desc=f"{int(n_rois)}Parcels{int(yeo_networks)}Networks",
        suffix="dseg",
        space=space,
        resolution=resolution,
    )


def fetch_templateflow_difumo_atlas(
    dimension: int,
    *,
    space: str | None = None,
    resolution: str | int | None = None,
) -> Path | None:
    return _templateflow_get_first_path(
        atlas="DiFuMo",
        desc=f"{int(dimension)}dimensions",
        suffix="probseg",
        space=space,
        resolution=resolution,
    )


def resolve_local_volume_atlas(
    atlas_name: str,
    roots: list[Path],
    *,
    space: str | None = None,
    resolution: str | int | None = None,
    include_legacy_schaefer: bool = True,
) -> tuple[Path, list[str], str]:
    atlas_key = str(atlas_name or "").strip().lower()
    atlas_path: Path | None
    family: str

    if atlas_key.startswith("schaefer2018"):
        family = _ATLAS_FAMILY_DIRS["schaefer"]
        atlas_path = find_local_schaefer_atlas(
            n_rois=parse_schaefer_n_rois(atlas_name),
            roots=roots,
            yeo_networks=parse_schaefer_yeo_networks(atlas_name),
            space=space,
            resolution=resolution,
            include_legacy=include_legacy_schaefer,
        )
    elif atlas_key in {"aal", "aal_2mm", "aal3"}:
        family = _ATLAS_FAMILY_DIRS["aal"]
        atlas_path = find_local_aal_atlas(roots)
    elif "harvard" in atlas_key:
        family = _ATLAS_FAMILY_DIRS["harvard_oxford"]
        atlas_path = find_local_harvard_oxford_atlas(
            normalize_harvard_oxford_variant(atlas_name),
            roots,
        )
    elif "yeo" in atlas_key:
        family = _ATLAS_FAMILY_DIRS["yeo"]
        atlas_path = find_local_yeo_atlas(parse_yeo_networks(atlas_name), roots)
    elif "destrieux" in atlas_key:
        family = _ATLAS_FAMILY_DIRS["destrieux"]
        atlas_path = find_local_destrieux_atlas(
            roots,
            lateralized="lateral" in atlas_key,
        )
    elif "basc" in atlas_key:
        family = _ATLAS_FAMILY_DIRS["basc"]
        atlas_path = find_local_basc_atlas(parse_basc_scale(atlas_name), roots)
    elif "msdl" in atlas_key:
        family = _ATLAS_FAMILY_DIRS["msdl"]
        atlas_path = find_local_msdl_atlas(roots)
    elif "difumo" in atlas_key:
        family = _ATLAS_FAMILY_DIRS["difumo"]
        match = re.search(r"(\d+)", atlas_key)
        atlas_path = find_local_difumo_atlas(
            roots,
            dimension=int(match.group(1)) if match else None,
            space=space,
            resolution=resolution,
        )
    else:
        raise ValueError(
            f"Unsupported atlas_name for volume atlas resolution: {atlas_name}"
        )

    if atlas_path is None:
        raise FileNotFoundError(
            f"Atlas '{atlas_name}' was not found under atlas roots: "
            f"{[str(root) for root in roots]}"
        )

    labels = derive_local_atlas_labels(
        atlas_path,
        atlas_name=atlas_name,
        family=family,
    )
    return atlas_path, labels, family


def discover_local_schaefer_resolutions(roots: list[Path]) -> list[int]:
    resolutions: set[int] = set()
    relative_candidates = [
        Path(""),
        Path("schaefer_2018"),
        Path("atlases/schaefer_2018"),
        Path("br-kg/raw/nilearn_atlases/schaefer_2018"),
    ]
    for root in roots:
        found_in_known_layout = False
        for rel in relative_candidates:
            base = root / rel
            if not base.exists():
                continue
            for atlas_path in base.glob(
                "Schaefer2018_*Parcels_*Networks_order_FSLMNI152_2mm.nii*"
            ):
                match = _SCHAEFER_FILENAME_RE.match(atlas_path.name)
                if match is None:
                    continue
                found_in_known_layout = True
                resolutions.add(int(match.group(1)))

        if found_in_known_layout:
            continue

        for atlas_path in _walk_pattern_files(root, _TEMPLATEFLOW_SCHAEFER_PATTERNS):
            match = re.search(r"desc-(\d+)Parcels(\d+)Networks", atlas_path.name)
            if match is None:
                continue
            resolutions.add(int(match.group(1)))

        for atlas_path in walk_schaefer_files(root):
            match = _SCHAEFER_FILENAME_RE.match(atlas_path.name)
            if match is None:
                continue
            resolutions.add(int(match.group(1)))
    return sorted(resolutions)


def _find_parent_candidate(path: Path, candidate_paths: list[Path]) -> Path | None:
    for parent in [path.parent, *path.parents]:
        for candidate in candidate_paths:
            candidate_path = parent / candidate
            if candidate_path.exists():
                return candidate_path
    return None


def aal_labels_from_xml(atlas_path: Path) -> list[str] | None:
    xml_path = _find_parent_candidate(
        atlas_path,
        [
            Path("AAL.xml"),
            Path("atlas/AAL.xml"),
        ],
    )
    if xml_path is None:
        return None
    try:
        root = ET.fromstring(xml_path.read_text(encoding="latin-1"))
    except Exception:
        return None
    labels = ["background"]
    for label_node in root.findall(".//label"):
        name = label_node.findtext("name")
        if name:
            labels.append(name)
    return labels or None


def harvard_oxford_labels_from_xml(atlas_path: Path, variant: str) -> list[str] | None:
    xml_name = (
        "HarvardOxford-Subcortical.xml"
        if variant.startswith("sub-")
        else "HarvardOxford-Cortical.xml"
    )
    xml_path = _find_parent_candidate(
        atlas_path,
        [
            Path(xml_name),
            Path("../") / xml_name,
        ],
    )
    if xml_path is None:
        return None
    try:
        root = ET.fromstring(xml_path.read_text(encoding="latin-1"))
    except Exception:
        return None
    labels = ["Background"]
    for label_node in root.findall(".//label"):
        text = (label_node.text or "").strip()
        if text:
            labels.append(text)
    return labels or None


def yeo_labels_from_lut(atlas_path: Path, n_networks: int) -> list[str] | None:
    lut_path = _find_parent_candidate(
        atlas_path,
        [Path(f"Yeo2011_{n_networks}Networks_ColorLUT.txt")],
    )
    if lut_path is None:
        return None
    labels: list[str] = []
    for line in lut_path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) < 2 or not parts[0].isdigit():
            continue
        labels.append(parts[1])
    return labels or None


def destrieux_labels_from_csv(
    atlas_path: Path,
    *,
    lateralized: bool = False,
) -> list[str] | None:
    csv_name = (
        "destrieux2009_rois_labels_lateralized.csv"
        if lateralized
        else "destrieux2009_rois_labels.csv"
    )
    csv_path = _find_parent_candidate(
        atlas_path,
        [Path(csv_name)],
    )
    if csv_path is None:
        return None
    labels: list[str] = []
    with csv_path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            name = str(row.get("name") or "").strip()
            if name:
                labels.append(name)
    return labels or None


def msdl_labels_from_csv(atlas_path: Path) -> list[str] | None:
    csv_path = _find_parent_candidate(
        atlas_path,
        [Path("msdl_rois_labels.csv")],
    )
    if csv_path is None:
        return None
    labels = ["background"]
    with csv_path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            name = str(row.get("name") or "").strip()
            if name:
                labels.append(name)
    return labels or None


def _templateflow_sidecar_tsv(atlas_path: Path) -> Path:
    name = atlas_path.name
    if name.endswith(".nii.gz"):
        return atlas_path.with_name(f"{name[:-7]}.tsv")
    if name.endswith(".nii"):
        return atlas_path.with_suffix(".tsv")
    return atlas_path.with_suffix(".tsv")


def templateflow_labels_from_tsv(
    atlas_path: Path,
    *,
    family: str | None = None,
) -> list[str] | None:
    tsv_path = _templateflow_sidecar_tsv(atlas_path)
    if not tsv_path.exists():
        return None

    with tsv_path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fieldnames = reader.fieldnames or []
        if not fieldnames:
            return None
        label_key = next(
            (
                candidate
                for candidate in ("name", "Difumo_names", "label", "labels")
                if candidate in fieldnames
            ),
            None,
        )
        if label_key is None:
            return None

        index_key = next(
            (
                candidate
                for candidate in ("index", "Component")
                if candidate in fieldnames
            ),
            None,
        )
        labels: list[str] = []
        numeric_indices: list[int] = []
        for row in reader:
            label = str(row.get(label_key) or "").strip()
            if not label:
                continue
            labels.append(label)
            if index_key is None:
                continue
            raw_index = str(row.get(index_key) or "").strip()
            if raw_index.isdigit():
                numeric_indices.append(int(raw_index))

    if not labels:
        return None
    if labels[0].lower() == "background":
        return labels
    if numeric_indices and min(numeric_indices) > 0:
        return ["background", *labels]
    if family == _ATLAS_FAMILY_DIRS["schaefer"]:
        return ["background", *labels]
    return labels


def derive_local_atlas_labels(
    atlas_path: Path,
    *,
    atlas_name: str | None = None,
    family: str | None = None,
) -> list[str]:
    sidecar_labels = read_labels_sidecar(atlas_path)
    if sidecar_labels:
        return sidecar_labels

    atlas_key = str(atlas_name or "").strip().lower()
    resolved_family = family or symbolic_atlas_family(atlas_key) or ""
    parsed = templateflow_labels_from_tsv(atlas_path, family=resolved_family)
    if parsed:
        return parsed
    if resolved_family == _ATLAS_FAMILY_DIRS["aal"]:
        parsed = aal_labels_from_xml(atlas_path)
        if parsed:
            return parsed
    if resolved_family == _ATLAS_FAMILY_DIRS["harvard_oxford"]:
        parsed = harvard_oxford_labels_from_xml(
            atlas_path,
            normalize_harvard_oxford_variant(atlas_key),
        )
        if parsed:
            return parsed
    if resolved_family == _ATLAS_FAMILY_DIRS["yeo"]:
        parsed = yeo_labels_from_lut(atlas_path, parse_yeo_networks(atlas_key))
        if parsed:
            return parsed
    if resolved_family == _ATLAS_FAMILY_DIRS["destrieux"]:
        parsed = destrieux_labels_from_csv(
            atlas_path,
            lateralized="lateral" in atlas_key,
        )
        if parsed:
            return parsed
    if resolved_family == _ATLAS_FAMILY_DIRS["msdl"]:
        parsed = msdl_labels_from_csv(atlas_path)
        if parsed:
            return parsed
    if resolved_family == _ATLAS_FAMILY_DIRS["difumo"]:
        if atlas_path.suffix in {".nii", ".gz"}:
            return atlas_labels_from_image(atlas_path)
    return atlas_labels_from_image(atlas_path)


def allow_network_atlas_fetch() -> bool:
    return os.getenv("BR_FETCH_ATLAS_ALLOW_NETWORK", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


__all__ = [
    "allow_network_atlas_fetch",
    "aal_labels_from_xml",
    "atlas_artifact_stem",
    "atlas_family_output_root",
    "atlas_label_paths",
    "atlas_labels_from_image",
    "atlas_reference_hints",
    "derive_local_atlas_labels",
    "default_atlas_output_root",
    "discover_local_schaefer_resolutions",
    "existing_search_roots",
    "fetch_templateflow_difumo_atlas",
    "fetch_templateflow_schaefer_atlas",
    "filename_entities",
    "find_local_aal_atlas",
    "find_local_basc_atlas",
    "find_local_difumo_atlas",
    "find_local_destrieux_atlas",
    "find_local_harvard_oxford_atlas",
    "find_local_msdl_atlas",
    "find_local_schaefer_atlas",
    "find_local_yeo_atlas",
    "harvard_oxford_labels_from_xml",
    "is_path_like_atlas",
    "msdl_labels_from_csv",
    "normalize_harvard_oxford_variant",
    "parse_basc_scale",
    "parse_schaefer_yeo_networks",
    "parse_yeo_networks",
    "parse_schaefer_n_rois",
    "read_labels_sidecar",
    "repo_data_dir",
    "resolve_local_volume_atlas",
    "schaefer_output_root",
    "templateflow_root",
    "templateflow_labels_from_tsv",
    "symbolic_atlas_family",
    "destrieux_labels_from_csv",
    "write_labels_sidecars",
    "yeo_labels_from_lut",
]
