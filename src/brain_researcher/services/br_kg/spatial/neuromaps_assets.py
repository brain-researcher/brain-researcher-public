"""Utilities for locating Yeo-17 reference assets.

By default we look for Neuromaps-formatted caches under the shared atlas home
(``/app/data/atlases/neuromaps`` when mounted) and fall back to the legacy raw
repo cache under ``data/br-kg/raw/neuromaps``. When no files are present we
fall back to ``nilearn.datasets.fetch_atlas_yeo_2011`` and stage its output
under the flat atlas family directory (``/app/data/atlases/yeo_2011`` by
default). This keeps ingestion scripts simple while aligning runtime behavior
with the seeded atlas layout.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import nibabel as nib
from nilearn import datasets

from brain_researcher.core.ingestion import neuromaps_paths
from brain_researcher.services.shared.atlas_utils import (
    existing_search_roots,
    resolve_local_volume_atlas,
)

LEGACY_NEUROMAPS_DIR = neuromaps_paths.LEGACY_NEUROMAPS_DIR
LEGACY_NILEARN_DIR = neuromaps_paths.LEGACY_NILEARN_DIR
DEFAULT_LABEL_GLOBS = (
    "**/yeo*17*2mm*.nii*",
    "**/Yeo*2011*17*2mm*.nii*",
)
DEFAULT_TEMPLATE_GLOBS = (
    "**/tpl-MNI152NLin2009cAsym_res-02_desc-brain_T1w.nii*",
    "**/*MNI152NLin2009cAsym*2mm*T1w.nii*",
)


def preferred_neuromaps_root() -> Path:
    return neuromaps_paths.preferred_neuromaps_root()


def preferred_yeo_fallback_root() -> Path:
    return neuromaps_paths.preferred_yeo_fallback_root()


DEFAULT_NEUROMAPS_DIR = preferred_neuromaps_root()
DEFAULT_NILEARN_DIR = preferred_yeo_fallback_root()


@dataclass(frozen=True)
class NeuromapsAssets:
    """Resolved file paths for the Yeo-17 pipeline."""

    label_img: Path
    template_img: Path

    def load_label(self) -> nib.Nifti1Image:
        return nib.load(str(self.label_img))

    def load_template(self) -> nib.Nifti1Image:
        return nib.load(str(self.template_img))


def _pick_first(match_lists: Iterable[Iterable[Path]]) -> Path:
    for matches in match_lists:
        for entry in matches:
            return entry
    raise FileNotFoundError


def _load_from_dir(
    root: Path, label_patterns: Iterable[str], template_patterns: Iterable[str]
) -> NeuromapsAssets:
    label_matches = [root.glob(pattern) for pattern in label_patterns]
    template_matches = [root.glob(pattern) for pattern in template_patterns]
    label_path = _pick_first(label_matches)
    template_path = _pick_first(template_matches)
    return NeuromapsAssets(label_img=label_path, template_img=template_path)


def _pick_template_from_roots(
    roots: Iterable[Path],
    template_patterns: Iterable[str],
) -> Path:
    template_matches = []
    for root in roots:
        template_matches.extend(root.glob(pattern) for pattern in template_patterns)
    return _pick_first(template_matches)


def _load_from_flat_yeo_family(
    *,
    atlas_root: Path,
    template_roots: Iterable[Path],
    template_patterns: Iterable[str],
) -> NeuromapsAssets:
    search_roots = existing_search_roots(None, atlas_root)
    label_path, _, _ = resolve_local_volume_atlas("yeo17", search_roots)
    template_path = _pick_template_from_roots(template_roots, template_patterns)
    return NeuromapsAssets(label_img=label_path, template_img=template_path)


def _fetch_nilearn_assets(target_dir: Path) -> NeuromapsAssets:
    target_dir.mkdir(parents=True, exist_ok=True)
    dataset = datasets.fetch_atlas_yeo_2011(n_networks=17, data_dir=str(target_dir))
    label_path = Path(dataset.maps)
    template_path = Path(dataset.template)
    logging.info(
        "Fetched Yeo 2011 atlas via nilearn (label=%s, template=%s)",
        label_path,
        template_path,
    )
    return NeuromapsAssets(label_img=label_path, template_img=template_path)


def resolve_neuromaps_assets(
    base_dir: Path | None = None,
    *,
    label_globs: Iterable[str] | None = None,
    template_globs: Iterable[str] | None = None,
) -> NeuromapsAssets:
    """Resolve template + label files, falling back to nilearn if needed."""

    label_patterns = tuple(label_globs or DEFAULT_LABEL_GLOBS)
    template_patterns = tuple(template_globs or DEFAULT_TEMPLATE_GLOBS)
    default_neuromaps = preferred_neuromaps_root().expanduser().resolve()
    fallback_yeo_root = preferred_yeo_fallback_root().expanduser().resolve()

    search_paths: list[Path] = []
    if base_dir is not None:
        search_paths.append(Path(base_dir).expanduser().resolve())
    if default_neuromaps not in search_paths:
        search_paths.append(default_neuromaps)
    legacy_neuromaps = neuromaps_paths.LEGACY_NEUROMAPS_DIR.expanduser().resolve()
    if legacy_neuromaps not in search_paths:
        search_paths.append(legacy_neuromaps)

    for candidate in search_paths:
        if not candidate.exists():
            logging.debug("Skipping non-existent atlas directory %s", candidate)
            continue
        try:
            return _load_from_dir(candidate, label_patterns, template_patterns)
        except FileNotFoundError:
            logging.debug("No Yeo-17 assets found in %s", candidate)

    try:
        return _load_from_flat_yeo_family(
            atlas_root=fallback_yeo_root,
            template_roots=search_paths,
            template_patterns=template_patterns,
        )
    except FileNotFoundError:
        logging.debug(
            "No flat Yeo-17 family assets found under %s",
            fallback_yeo_root,
        )

    logging.info(
        "Falling back to nilearn.fetch_atlas_yeo_2011 (data_dir=%s)",
        fallback_yeo_root,
    )
    return _fetch_nilearn_assets(fallback_yeo_root)


__all__ = [
    "NeuromapsAssets",
    "preferred_neuromaps_root",
    "preferred_yeo_fallback_root",
    "resolve_neuromaps_assets",
]
