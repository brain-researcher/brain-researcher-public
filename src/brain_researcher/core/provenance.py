"""
Provenance recording utilities for reproducible GLM/multiverse runs.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def _sha256_file(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _git_commit(repo_path: Path) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return None


def _env_snapshot() -> Dict[str, Any]:
    return {
        "python_version": sys.version,
        "platform": platform.platform(),
        "executable": sys.executable,
        "cwd": os.getcwd(),
    }


def _default_package_versions() -> Dict[str, str]:
    try:
        from importlib import metadata
    except Exception:
        return {}

    packages = ["numpy", "pandas", "nibabel", "nilearn", "statsmodels", "scipy"]
    versions: Dict[str, str] = {}
    for pkg in packages:
        try:
            versions[pkg] = metadata.version(pkg)
        except Exception:
            continue
    return versions


def write_provenance(
    output_dir: Path,
    spec_paths: Iterable[Path],
    command: List[str],
    config_snapshot: Optional[Dict[str, Any]] = None,
    seeds: Optional[Dict[str, Any]] = None,
    images: Optional[Dict[str, str]] = None,
    pkg_versions: Optional[Dict[str, str]] = None,
    extra: Optional[Dict[str, Any]] = None,
    references: Optional[List[Dict[str, Any]]] = None,
) -> Path:
    """
    Write a provenance.json file capturing enough information to reproduce a run.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    repo_root = Path(__file__).resolve().parents[3]
    glmrepo_root = repo_root / "external" / "openneuro_glmfitlins"

    # references hash (canonicalized) for traceability
    ref_hash = None
    ref_sources = None
    if references:
        try:
            canon = json.dumps(references, sort_keys=True)
            ref_hash = hashlib.sha256(canon.encode("utf-8")).hexdigest()
            ref_sources = sorted(
                {
                    r.get("source")
                    for r in references
                    if isinstance(r, dict) and r.get("source")
                }
            )
        except Exception:
            ref_hash = None

    packages = pkg_versions or _default_package_versions()
    provenance: Dict[str, Any] = {
        "brain_researcher_commit": _git_commit(repo_root),
        "openneuro_glmfitlins_commit": _git_commit(glmrepo_root),
        "command": command,
        "cwd": os.getcwd(),
        "environment": _env_snapshot(),
        "specs": [],
        "config_snapshot": config_snapshot,
        "seeds": seeds,
        "images": images,
        "packages": packages,
        "extra": extra,
        "references": references,
        "references_sha256": ref_hash,
        "reference_sources": ref_sources,
    }

    for path in spec_paths:
        p = Path(path)
        provenance["specs"].append(
            {
                "path": str(p),
                "sha256": _sha256_file(p),
            }
        )

    prov_path = output_dir / "provenance.json"
    prov_path.write_text(json.dumps(provenance, indent=2))
    return prov_path
