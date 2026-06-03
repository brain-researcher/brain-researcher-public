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
from collections.abc import Iterable
from pathlib import Path
from typing import Any


def _sha256_file(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _git_commit(repo_path: Path) -> str | None:
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


def _env_snapshot() -> dict[str, Any]:
    return {
        "python_version": sys.version,
        "platform": platform.platform(),
        "executable": sys.executable,
        "cwd": os.getcwd(),
    }


def _default_package_versions() -> dict[str, str]:
    try:
        from importlib import metadata
    except Exception:
        return {}

    packages = ["numpy", "pandas", "nibabel", "nilearn", "statsmodels", "scipy"]
    versions: dict[str, str] = {}
    for pkg in packages:
        try:
            versions[pkg] = metadata.version(pkg)
        except Exception:
            continue
    return versions


def write_provenance(
    output_dir: Path,
    spec_paths: Iterable[Path],
    command: list[str],
    config_snapshot: dict[str, Any] | None = None,
    seeds: dict[str, Any] | None = None,
    images: dict[str, str] | None = None,
    pkg_versions: dict[str, str] | None = None,
    extra: dict[str, Any] | None = None,
    references: list[dict[str, Any]] | None = None,
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
    provenance: dict[str, Any] = {
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
