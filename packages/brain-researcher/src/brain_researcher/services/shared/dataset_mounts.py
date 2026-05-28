"""Shared dataset mount candidates and snapshot helpers.

This is the single source of truth for dataset-related local/container mount
roots that need to be visible across agent resolution and MCP health/status
surfaces.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping


def _clean_candidates(*candidates: object) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in candidates:
        text = str(raw or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


def dataset_mount_candidates(
    local_cfg: Mapping[str, Any] | None = None,
) -> dict[str, list[str]]:
    local_cfg = local_cfg or {}
    return {
        "openneuro_mount": _clean_candidates(
            os.getenv("OPENNEURO_MOUNT_ROOT", ""),
            os.getenv("OPENNEURO_ROOT", ""),
            local_cfg.get("openneuro_local", ""),
            "/app/data/openneuro",
        ),
        "openneuro_derivatives_mount": _clean_candidates(
            os.getenv("OPENNEURO_DERIV_ROOT", ""),
            local_cfg.get("openneuro_derivatives", ""),
            local_cfg.get("openneuro_deriv", ""),
            local_cfg.get("openneuro_derivatives_local", ""),
            "/app/data/OpenNeuroDerivatives",
        ),
        "openneuro_metadata_mount": _clean_candidates(
            os.getenv("OPENNEURO_METADATA_ROOT", ""),
            "/app/data/openneuro_metadata",
        ),
        "public_s3_mount": _clean_candidates(
            os.getenv("PUBLIC_S3_ROOT", ""),
            os.getenv("PUBLIC_BUCKETS_ROOT", ""),
            local_cfg.get("public_s3_root", ""),
            local_cfg.get("public_buckets_root", ""),
            "/app/data/public-s3",
            "/data/public_s3_mount",
            os.getenv("INDI_ROOT", ""),
            "/app/data/indi",
        ),
        "niclip_data_mount": _clean_candidates(
            os.getenv("NICLIP_DATA_PATH", ""),
            "/app/data/niclip",
        ),
        "niclip_model_mount": _clean_candidates(
            os.getenv("NICLIP_MODEL_DIR", ""),
            "/app/models/niclip",
        ),
        "niclip_faiss_mount": _clean_candidates(
            os.getenv("NICLIP_FAISS_INDEX_PATH", ""),
            "/app/data/niclip_faiss",
        ),
        "atlases_mount": _clean_candidates(
            os.getenv("BR_ATLAS_OUTPUT_ROOT", ""),
            "/app/data/atlases",
            "/srv/datasets/atlases",
        ),
        "neurosynth_nimare_mount": _clean_candidates("/app/data/neurosynth_nimare"),
        "scholarly_metadata_mount": _clean_candidates("/app/data/scholarly_metadata"),
        "datasets_root_mount": _clean_candidates("/data"),
    }


def mount_snapshot(candidates: list[str]) -> dict[str, Any]:
    configured = [candidate for candidate in candidates if candidate]
    detected = [candidate for candidate in configured if Path(candidate).exists()]
    return {
        "configured_candidates": configured,
        "detected_paths": detected,
        "exists": bool(detected),
    }


def dataset_mount_snapshots(
    local_cfg: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    return {
        name: mount_snapshot(candidates)
        for name, candidates in dataset_mount_candidates(local_cfg).items()
    }
