"""
Lightweight, reproducible references for GLM decision points.

This module avoids live web calls. It stitches together:
1) Static method citations for common GLM choices (HRF, confounds, HPF).
2) Dataset citation (DOI) if available in dataset_description.json.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class Reference:
    source: str  # e.g., "static", "dataset"
    kind: str  # e.g., "method", "dataset"
    title: str
    year: Optional[int] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    note: str = ""
    supports: Optional[List[Dict[str, str]]] = None
    evidence: Optional[Dict[str, int]] = None

    def to_dict(self) -> Dict:
        return asdict(self)


# Static method references (minimal, extendable)
STATIC_METHOD_REFS: Dict[tuple, Reference] = {
    ("confounds", "24mot_acompcor"): Reference(
        source="static",
        kind="method",
        title="A component based noise correction method (CompCor)",
        year=2007,
        doi="10.1016/j.neuroimage.2007.04.042",
        url="https://pubmed.ncbi.nlm.nih.gov/17560126/",
        note="Supports inclusion of aCompCor components with motion regressors.",
    ),
    ("confounds", "24mot"): Reference(
        source="static",
        kind="method",
        title="Movement-related effects in fMRI time-series (Friston motion model)",
        year=1996,
        doi="10.1006/nimg.1996.0046",
        url="https://pubmed.ncbi.nlm.nih.gov/8677012/",
        note="Supports 24-parameter motion regression.",
    ),
    ("confounds", "6mot"): Reference(
        source="static",
        kind="method",
        title="Standard 6-parameter motion regression",
        year=1996,
        note="Widely used baseline motion model (translation/rotation).",
    ),
    ("hrf", "canonical"): Reference(
        source="static",
        kind="method",
        title="SPM canonical HRF",
        url="https://www.fil.ion.ucl.ac.uk/spm/doc/manual.pdf",
        note="Canonical HRF as implemented in SPM/pybids transforms.",
    ),
    ("hrf", "derivs"): Reference(
        source="static",
        kind="method",
        title="Canonical HRF with temporal derivatives",
        note="Derivative basis to capture latency shifts.",
    ),
    ("hrf", "fir"): Reference(
        source="static",
        kind="method",
        title="Finite impulse response (FIR) HRF",
        note="Non-parametric HRF estimation.",
    ),
    ("high_pass", "128"): Reference(
        source="static",
        kind="method",
        title="SPM default high-pass filter 128s",
        url="https://www.fil.ion.ucl.ac.uk/spm/docs/manual/fmri_spec/",
        note="Common default high-pass cutoff.",
    ),
}


def _dataset_reference(dataset_description: Path, dataset_id: str) -> Optional[Reference]:
    if not dataset_description.exists():
        return None
    try:
        desc = json.loads(dataset_description.read_text())
        doi = desc.get("DatasetDOI") or desc.get("DOI")
        title = desc.get("Name") or dataset_id
        url = desc.get("ReferencesAndLinks", [None])[0] if desc.get("ReferencesAndLinks") else None
        return Reference(
            source="dataset",
            kind="dataset",
            title=title,
            doi=doi,
            url=url,
            note=f"Citation for dataset {dataset_id}",
            supports=[{"decision": "dataset", "option": dataset_id}],
        )
    except Exception:
        return None


def gather_references(
    dataset_id: str,
    task: str,
    decisions: Dict[str, str],
    datasets_folder: Optional[Path] = None,
) -> List[Dict]:
    refs: List[Reference] = []

    # Static method refs
    for dec_name, option in decisions.items():
        key = (dec_name, str(option))
        ref = STATIC_METHOD_REFS.get(key)
        if ref:
            r = Reference(**ref.to_dict())  # copy
            r.supports = [{"decision": dec_name, "option": str(option)}]
            refs.append(r)

    # Dataset DOI
    dataset_desc = None
    search_roots: List[Path] = []
    if datasets_folder:
        search_roots.append(datasets_folder)
    # Common dataset roots (override with BR_DATASET_SEARCH_ROOTS, colon-separated)
    extra_roots = os.environ.get("BR_DATASET_SEARCH_ROOTS", "").strip()
    if extra_roots:
        search_roots.extend(Path(p) for p in extra_roots.split(":") if p.strip())
    else:
        search_roots.extend([Path("/app/data"), Path("/data")])

    candidates: List[Path] = []
    for root in search_roots:
        candidates.extend(
            [
                root / "openneuro" / dataset_id / "dataset_description.json",
                root / "input" / dataset_id / "dataset_description.json",
                root / "openneuro_mount" / dataset_id / "dataset_description.json",
                root / "OpenNeuroDerivatives" / "fmriprep" / f"{dataset_id}-fmriprep" / "sourcedata" / "dataset_description.json",
                root / "openneuro_metadata" / "openneuro" / dataset_id / "dataset_description.json",
                root / "openneuro_metadata" / dataset_id / "dataset_description.json",
            ]
        )
    for c in candidates:
        if c.exists():
            dataset_desc = c
            break
    if dataset_desc:
        dref = _dataset_reference(dataset_desc, dataset_id)
        if dref:
            refs.append(dref)

    return [r.to_dict() for r in refs]
