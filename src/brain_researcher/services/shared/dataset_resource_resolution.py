"""Dataset reference and resource resolution helpers.

This lower-layer module owns dataset catalog/mount/resource discovery so BR-KG
can resolve dataset resources without importing the agent layer. The agent
``kg_resolution`` module re-exports these APIs for backward compatibility.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Iterable
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from brain_researcher.core.datasets.catalog import (
    DEFAULT_CATALOG_PATH,
    DatasetRecord,
    load_catalog,
)
from brain_researcher.services.shared.dataset_mounts import dataset_mount_candidates
from brain_researcher.services.shared.r2brkg_query_understanding_types import (
    DatasetResolution,
    DatasetResources,
    DerivativeHit,
)

UTC = timezone.utc
logger = logging.getLogger(__name__)

OPENNEURO_GRAPHQL_ENDPOINT = "https://openneuro.org/crn/graphql"
DEFAULT_SOURCE_ACCESS_TTL_SECONDS = int(
    os.getenv("BR_DATASET_SOURCE_ACCESS_TTL_SECONDS", "600")
)

_SOURCE_ACCESS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_SOURCE_ACCESS_CACHE_LOCK = threading.Lock()

# ----------------------------
# Dataset resolution
# ----------------------------


@lru_cache(maxsize=8)
def _load_local_mounts_cached(path_str: str) -> dict[str, Any]:
    path = Path(path_str)
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text()) or {}
    except Exception as exc:  # pragma: no cover - I/O fallback
        logger.warning("Failed to load local mounts yaml: %s", exc)
        return {}


def _load_local_mounts(path: Path) -> dict[str, Any]:
    return _load_local_mounts_cached(str(path.resolve()))


def _path_from_mounts(dataset_id: str, mounts: dict[str, Any]) -> Path | None:
    # oak_mount datasets
    oak = mounts.get("oak_mount", {}).get("datasets", {}) if mounts else {}
    simple_id = dataset_id.split(":")[-1]
    candidates = [dataset_id, simple_id]

    # First try exact key matches.
    for candidate in candidates:
        if candidate in oak:
            return Path(oak[candidate])

    # Fall back to case-insensitive lookup so HCP_YA and hcp_ya resolve equally.
    normalized_oak: dict[str, Any] = {}
    for key, value in oak.items():
        if isinstance(key, str):
            normalized_oak[key.strip().lower()] = value
    for candidate in candidates:
        match = normalized_oak.get(candidate.strip().lower())
        if match:
            return Path(match)

    # generic local BIDS root
    local_root = mounts.get("local", {}).get("bids") if mounts else None
    if local_root:
        for candidate_id in (dataset_id, simple_id):
            candidate = Path(local_root) / candidate_id
            if candidate.exists():
                return candidate
    return None


PUBLIC_S3_CATALOG_TARGETS = {
    "ds:manual:fcp_1000": "fcp_1000",
    "ds:manual:nki_rs": "nki_rs",
    "ds:manual:hbn": "hbn",
    "ds:manual:hcp_ya": "hcp-openaccess",
    "ds:manual:hcp_a": "hcp-openaccess",
    "ds:manual:hcp_d": "hcp-openaccess",
    "ds:manual:nsd": "natural-scenes-dataset",
    "ds:manual:dandi": "dandiarchive",
    "ds:manual:mimic": "mimic-iii-physionet",
    "ds:manual:bluebrain": "openbluebrain",
    "ds:manual:ibl_brainwide": "ibl-brain-wide-map-public",
    "ds:manual:brainminds_marmoset": "brainminds-marmoset-connectivity",
    "ds:manual:allen_aba": "allen-mouse-brain-atlas",
    "ds:manual:allen_mouse_conn": "allen-mouse-brain-atlas",
}

PUBLIC_S3_ALIAS_MAP = {
    "fcp": "fcp_1000",
    "fcp-1000": "fcp_1000",
    "fcp_1000": "fcp_1000",
    "nki": "nki_rs",
    "nki-rs": "nki_rs",
    "nki_rs": "nki_rs",
    "hbn": "hbn",
    "healthy-brain-network": "hbn",
    "nsd": "natural-scenes-dataset",
    "natural-scenes": "natural-scenes-dataset",
    "natural-scenes-dataset": "natural-scenes-dataset",
    "ibl": "ibl-brain-wide-map-public",
    "ibl-bwm": "ibl-brain-wide-map-public",
    "ibl-brain-wide-map": "ibl-brain-wide-map-public",
    "ibl-brain-wide-map-public": "ibl-brain-wide-map-public",
    "allen": "allen-mouse-brain-atlas",
    "allen-mouse": "allen-mouse-brain-atlas",
    "allen-brain-atlas": "allen-mouse-brain-atlas",
    "allen-mouse-brain-atlas": "allen-mouse-brain-atlas",
    "bluebrain": "openbluebrain",
    "blue-brain": "openbluebrain",
    "openbluebrain": "openbluebrain",
    "brainminds": "brainminds-marmoset-connectivity",
    "brain-minds": "brainminds-marmoset-connectivity",
    "brainminds-marmoset": "brainminds-marmoset-connectivity",
    "brainminds-marmoset-connectivity": "brainminds-marmoset-connectivity",
    "hcp": "hcp-openaccess",
    "hcp-ya": "hcp-openaccess",
    "hcp_ya": "hcp-openaccess",
    "hcp-openaccess": "hcp-openaccess",
    "mimic": "mimic-iii-physionet",
    "mimic-iii": "mimic-iii-physionet",
    "mimic_iii": "mimic-iii-physionet",
    "mimic-iii-physionet": "mimic-iii-physionet",
    "mimic-iv-demo": "physionet-open-mimic-iv-demo",
    "physionet-open-mimic-iv-demo": "physionet-open-mimic-iv-demo",
    "mimic-iv-ecg": "physionet-open-mimic-iv-ecg",
    "physionet-open-mimic-iv-ecg": "physionet-open-mimic-iv-ecg",
}


def _normalize_mount_alias(value: str) -> str:
    token = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return token


def _public_s3_mount_roots(mounts: dict[str, Any]) -> list[Path]:
    local_cfg = mounts.get("local", {}) if mounts else {}
    return _unique_existing_first(
        dataset_mount_candidates(local_cfg)["public_s3_mount"]
    )


def _public_s3_alias_candidates(candidate: DatasetRecord) -> list[str]:
    values: list[str] = []
    mapped = PUBLIC_S3_CATALOG_TARGETS.get(candidate.dataset_id.strip().lower())
    if mapped:
        values.append(mapped)

    for raw in (
        candidate.dataset_id,
        candidate.source_repo_id or "",
        candidate.short_name or "",
        candidate.name or "",
        *list(candidate.alias or []),
    ):
        token = _normalize_mount_alias(raw)
        if not token:
            continue
        values.append(PUBLIC_S3_ALIAS_MAP.get(token, token))

    values.append(
        PUBLIC_S3_ALIAS_MAP.get(
            _normalize_dataset_id(candidate.dataset_id),
            _normalize_dataset_id(candidate.dataset_id),
        )
    )

    deduped: list[str] = []
    seen: set[str] = set()
    for item in values:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item.strip())
    return deduped


def _resolve_public_s3_path(
    candidate: DatasetRecord,
    mounts: dict[str, Any],
) -> tuple[Path | None, list[dict[str, Any]], dict[str, Any]]:
    roots = _public_s3_mount_roots(mounts)
    aliases = _public_s3_alias_candidates(candidate)
    trace: list[dict[str, Any]] = []
    searched: list[str] = []

    for root in roots:
        for alias in aliases:
            direct = root / alias
            searched.append(str(direct))
            hit = direct.exists()
            trace.append(
                {
                    "stage": "mount",
                    "kind": "public_s3",
                    "candidate": str(direct),
                    "hit": hit,
                    "mount_root": str(root),
                    "alias": alias,
                }
            )
            if hit:
                return (
                    direct,
                    trace,
                    {
                        "mounted": True,
                        "mount_kind": "public_s3",
                        "local_path": str(direct),
                        "mount_root": str(root),
                        "matched_alias": alias,
                        "searched_candidates": searched,
                    },
                )

    return (
        None,
        trace,
        {
            "mounted": False,
            "mount_kind": "public_s3",
            "local_path": None,
            "mount_root": None,
            "matched_alias": None,
            "searched_candidates": searched,
        },
    )


def _looks_like_bids_root(path: Path | None) -> bool:
    if not path or not path.exists() or not path.is_dir():
        return False
    if (path / "dataset_description.json").exists():
        return True
    try:
        return any(child.name.startswith("sub-") for child in path.iterdir())
    except Exception:
        return False


def _resolve_non_openneuro_local_path(
    candidate: DatasetRecord,
    mounts: dict[str, Any],
) -> tuple[Path | None, list[dict[str, Any]], dict[str, Any]]:
    direct = _path_from_mounts(candidate.dataset_id, mounts)
    if direct:
        return (
            direct,
            [
                {
                    "stage": "mount",
                    "kind": "raw",
                    "candidate": str(direct),
                    "hit": bool(direct.exists()),
                }
            ],
            {
                "mounted": bool(direct.exists()),
                "mount_kind": "local_or_oak",
                "local_path": str(direct),
                "mount_root": str(direct.parent),
                "matched_alias": None,
                "searched_candidates": [str(direct)],
            },
        )

    public_s3_path, public_s3_trace, public_s3_status = _resolve_public_s3_path(
        candidate, mounts
    )
    if public_s3_path:
        return public_s3_path, public_s3_trace, public_s3_status

    return None, public_s3_trace, public_s3_status


OPENNEURO_DERIV_BUCKETS = ("fmriprep", "mriqc", "fitlins", "xcpd")
DEFAULT_OPENNEURO_CACHE_ROOT = Path(
    os.getenv("BR_DATA_CACHE_ROOT", "tmp/dataset_cache")
)

# Required groups: each group must satisfy min_matches over listed glob patterns.
ANALYSIS_GOAL_REQUIRED_GROUPS: dict[str, list[dict[str, Any]]] = {
    "generic": [
        {
            "name": "dataset_description",
            "patterns": ["dataset_description.json"],
            "min_matches": 1,
            "optional": False,
        },
    ],
    "fmri-glm": [
        {
            "name": "dataset_description",
            "patterns": ["dataset_description.json"],
            "min_matches": 1,
            "optional": False,
        },
        {
            "name": "bold_nifti",
            "patterns": ["sub-*/**/*_bold.nii.gz"],
            "min_matches": 1,
            "optional": False,
        },
        {
            "name": "bold_sidecar_json",
            "patterns": ["sub-*/**/*_bold.json"],
            "min_matches": 1,
            "optional": False,
        },
    ],
    "lnm": [
        {
            "name": "dataset_description",
            "patterns": ["dataset_description.json"],
            "min_matches": 1,
            "optional": False,
        },
        {
            "name": "lesion_maps",
            "patterns": [
                "sub-*/**/*label-lesion*_roi.nii.gz",
                "sub-*/**/*lesion*mask*.nii.gz",
                "sub-*/**/*lesion*.nii.gz",
            ],
            "min_matches": 1,
            "optional": False,
        },
    ],
    "bold-layer1": [
        {
            "name": "dataset_description",
            "patterns": ["dataset_description.json"],
            "min_matches": 1,
            "optional": False,
        },
        {
            "name": "bold_nifti",
            "patterns": ["sub-*/**/*_bold.nii.gz"],
            "min_matches": 1,
            "optional": False,
        },
        {
            "name": "bold_sidecar_json",
            "patterns": ["sub-*/**/*_bold.json"],
            "min_matches": 1,
            "optional": False,
        },
        {
            "name": "calibrated_signals",
            "patterns": ["**/*cmro2*", "**/*oef*", "**/*cbf*", "**/*cbv*"],
            "min_matches": 1,
            "optional": False,
        },
    ],
}


def _normalize_dataset_id(dataset_id: str) -> str:
    return dataset_id.split(":")[-1].lower().strip()


def _normalize_analysis_goal(goal: str) -> str:
    token = (goal or "generic").strip().lower()
    aliases = {
        "glm": "fmri-glm",
        "task-fmri": "fmri-glm",
        "task": "fmri-glm",
        "layer1": "bold-layer1",
    }
    return aliases.get(token, token)


def _is_openneuro_dataset(candidate: DatasetRecord) -> bool:
    simple_id = _normalize_dataset_id(candidate.dataset_id)
    source_text = " ".join(
        [
            simple_id,
            candidate.source_repo.lower(),
            (candidate.source_repo_id or "").lower(),
            str(candidate.primary_url).lower(),
        ]
    )
    return simple_id.startswith("ds") or "openneuro" in source_text


def _openneuro_mount_roots(mounts: dict[str, Any]) -> list[Path]:
    local_cfg = mounts.get("local", {}) if mounts else {}
    return _unique_existing_first(
        dataset_mount_candidates(local_cfg)["openneuro_mount"]
    )


def _openneuro_deriv_roots(mounts: dict[str, Any]) -> list[Path]:
    local_cfg = mounts.get("local", {}) if mounts else {}
    return _unique_existing_first(
        dataset_mount_candidates(local_cfg)["openneuro_derivatives_mount"]
    )


def _unique_existing_first(paths: list[str]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for raw in paths:
        if not raw:
            continue
        p = Path(str(raw)).expanduser()
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _normalize_version_token(value: str | None) -> str | None:
    if not value:
        return None
    token = value.strip()
    return token or None


def _source_access_cache_key(dataset_id: str, requested_version: str | None) -> str:
    version = _normalize_version_token(requested_version) or ""
    return f"{dataset_id.lower().strip()}::{version.lower()}"


def _cache_get_source_access(key: str) -> dict[str, Any] | None:
    now = time.time()
    with _SOURCE_ACCESS_CACHE_LOCK:
        cached = _SOURCE_ACCESS_CACHE.get(key)
        if not cached:
            return None
        expires_at, payload = cached
        if now > expires_at:
            _SOURCE_ACCESS_CACHE.pop(key, None)
            return None
        cloned = json.loads(json.dumps(payload))
    bucket_check = cloned.get("bucket_check")
    if isinstance(bucket_check, dict):
        bucket_check["cache_hit"] = True
    return cloned


def _cache_set_source_access(key: str, payload: dict[str, Any]) -> None:
    ttl = max(5, DEFAULT_SOURCE_ACCESS_TTL_SECONDS)
    with _SOURCE_ACCESS_CACHE_LOCK:
        _SOURCE_ACCESS_CACHE[key] = (
            time.time() + ttl,
            json.loads(json.dumps(payload)),
        )


def _base_source_access(
    *,
    provider: str,
    bucket_uri: str | None,
    requested_version: str | None,
) -> dict[str, Any]:
    return {
        "provider": provider,
        "bucket_uri": bucket_uri,
        "bucket_check": {
            "state": "unknown",
            "method": "none",
            "checked_at": None,
            "message": None,
            "latency_ms": None,
        },
        "version_check": {
            "mode": "metadata_only",
            "requested": _normalize_version_token(requested_version),
            "resolved": None,
        },
        "available_versions": [],
    }


def _extract_s3_uri_from_url(raw: str) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None

    parsed = urlparse(text)
    if parsed.scheme == "s3":
        bucket = parsed.netloc.strip()
        prefix = parsed.path.lstrip("/")
        if not bucket:
            return None
        return f"s3://{bucket}/{prefix}" if prefix else f"s3://{bucket}"

    if parsed.scheme not in {"http", "https"}:
        return None

    host = parsed.netloc.lower().strip()
    path = parsed.path.lstrip("/")

    if host.endswith(".s3.amazonaws.com"):
        bucket = host[: -len(".s3.amazonaws.com")]
        if bucket:
            return f"s3://{bucket}/{path}" if path else f"s3://{bucket}"

    if host == "s3.amazonaws.com" or (
        host.startswith("s3.") and host.endswith(".amazonaws.com")
    ):
        if not path:
            return None
        parts = path.split("/", 1)
        bucket = parts[0].strip()
        prefix = parts[1].strip() if len(parts) > 1 else ""
        if not bucket:
            return None
        return f"s3://{bucket}/{prefix}" if prefix else f"s3://{bucket}"

    return None


def _split_s3_uri(uri: str) -> tuple[str, str]:
    body = uri.removeprefix("s3://").strip("/")
    if not body:
        return "", ""
    parts = body.split("/", 1)
    bucket = parts[0].strip()
    prefix = parts[1].strip() if len(parts) > 1 else ""
    return bucket, prefix


def _probe_s3_bucket(
    *,
    bucket: str,
    prefix: str,
    timeout_seconds: int = 20,
) -> dict[str, Any]:
    started = time.perf_counter()
    check = {
        "state": "unknown",
        "method": "s3_list_objects",
        "checked_at": _utc_now_iso(),
        "message": None,
        "latency_ms": None,
    }

    if not bucket:
        check["state"] = "not_applicable"
        check["method"] = "none"
        check["message"] = "missing bucket name"
        return check

    if shutil.which("aws") is None:
        check["state"] = "unknown"
        check["message"] = "aws cli not available"
        return check

    cmd = [
        "aws",
        "s3api",
        "list-objects-v2",
        "--bucket",
        bucket,
        "--max-items",
        "1",
        "--no-sign-request",
        "--output",
        "json",
    ]
    if prefix:
        cmd.extend(["--prefix", prefix])

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except Exception as exc:
        check["state"] = "unreachable"
        check["message"] = str(exc)
        check["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return check

    stderr = (proc.stderr or "").strip()
    stdout = (proc.stdout or "").strip()
    check["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)

    if proc.returncode == 0:
        payload: dict[str, Any] = {}
        try:
            payload = json.loads(stdout) if stdout else {}
        except Exception:
            payload = {}
        key_count = int(payload.get("KeyCount", 0) or 0)
        contents = payload.get("Contents", [])
        has_contents = isinstance(contents, list) and len(contents) > 0
        check["state"] = (
            "verified_present" if has_contents or key_count > 0 else "verified_absent"
        )
        return check

    lowered = stderr.lower()
    if "accessdenied" in lowered or "access denied" in lowered:
        check["state"] = "permission_denied"
        check["message"] = stderr or "access denied"
        return check
    if "nosuchbucket" in lowered or "not exist" in lowered:
        check["state"] = "verified_absent"
        check["message"] = stderr or "bucket not found"
        return check

    check["state"] = "unreachable"
    check["message"] = stderr or f"aws s3api failed with code {proc.returncode}"
    return check


def _resolve_openneuro_source_access(
    *,
    dataset_simple_id: str,
    requested_version: str | None,
) -> dict[str, Any]:
    source_access = _base_source_access(
        provider="openneuro",
        bucket_uri=f"s3://openneuro.org/{dataset_simple_id}",
        requested_version=requested_version,
    )

    started = time.perf_counter()
    query = """
    query GetDatasetSnapshots($datasetId: ID!) {
      dataset(id: $datasetId) {
        id
        snapshots {
          id
          tag
          created
        }
      }
    }
    """
    payload = {"query": query, "variables": {"datasetId": dataset_simple_id}}
    try:
        import requests

        response = requests.post(
            OPENNEURO_GRAPHQL_ENDPOINT,
            json=payload,
            timeout=8,
        )
    except Exception as exc:
        source_access["bucket_check"].update(
            {
                "state": "unreachable",
                "method": "openneuro_api",
                "checked_at": _utc_now_iso(),
                "message": str(exc),
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            }
        )
        return source_access

    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    if response.status_code != 200:
        source_access["bucket_check"].update(
            {
                "state": "unreachable",
                "method": "openneuro_api",
                "checked_at": _utc_now_iso(),
                "message": f"OpenNeuro API status {response.status_code}",
                "latency_ms": latency_ms,
            }
        )
        return source_access

    try:
        body = response.json()
    except Exception as exc:
        source_access["bucket_check"].update(
            {
                "state": "unreachable",
                "method": "openneuro_api",
                "checked_at": _utc_now_iso(),
                "message": f"invalid OpenNeuro JSON payload: {exc}",
                "latency_ms": latency_ms,
            }
        )
        return source_access

    errors = body.get("errors")
    if isinstance(errors, list) and errors:
        source_access["bucket_check"].update(
            {
                "state": "unreachable",
                "method": "openneuro_api",
                "checked_at": _utc_now_iso(),
                "message": str(errors[0]),
                "latency_ms": latency_ms,
            }
        )
        return source_access

    dataset = (
        ((body.get("data") or {}).get("dataset") or {})
        if isinstance(body, dict)
        else {}
    )
    if not dataset:
        source_access["bucket_check"].update(
            {
                "state": "verified_absent",
                "method": "openneuro_api",
                "checked_at": _utc_now_iso(),
                "message": "dataset not found on OpenNeuro",
                "latency_ms": latency_ms,
            }
        )
        return source_access

    snapshots_raw = dataset.get("snapshots") or []
    snapshots: list[dict[str, Any]] = []
    if isinstance(snapshots_raw, list):
        for snapshot in snapshots_raw:
            if not isinstance(snapshot, dict):
                continue
            tag = str(snapshot.get("tag") or "").strip()
            sid = str(snapshot.get("id") or "").strip()
            label = tag or sid
            if not label:
                continue
            snapshots.append(
                {
                    "id": tag or sid,
                    "label": label,
                    "source": "openneuro_snapshot",
                    "state": "verified",
                    "created_at": str(snapshot.get("created") or "").strip() or None,
                }
            )

    snapshots.sort(
        key=lambda item: str(item.get("created_at") or ""),
        reverse=True,
    )
    for idx, snapshot in enumerate(snapshots):
        snapshot["recommended"] = idx == 0

    requested = _normalize_version_token(requested_version)
    requested_lower = requested.lower() if requested else None
    resolved = None
    if requested_lower in {"latest", "current", "mounted-current"}:
        resolved = snapshots[0]["id"] if snapshots else None
    elif requested:
        for snapshot in snapshots:
            sid = str(snapshot.get("id", ""))
            label = str(snapshot.get("label", ""))
            if requested.lower() in {sid.lower(), label.lower()}:
                resolved = sid
                break
    if resolved is None and snapshots:
        resolved = str(snapshots[0]["id"])

    source_access["bucket_check"].update(
        {
            "state": "verified_present",
            "method": "openneuro_api",
            "checked_at": _utc_now_iso(),
            "message": None,
            "latency_ms": latency_ms,
        }
    )
    source_access["version_check"].update(
        {
            "mode": "verified" if snapshots else "metadata_only",
            "resolved": resolved,
        }
    )
    source_access["available_versions"] = snapshots
    return source_access


def _resolve_generic_source_access(
    *,
    candidate: DatasetRecord,
    requested_version: str | None,
    remote_urls: dict[str, str],
) -> dict[str, Any]:
    source_url_candidates = [
        str(remote_urls.get("s3") or ""),
        str(remote_urls.get("primary") or ""),
        str(candidate.primary_url or ""),
    ]
    s3_uri = None
    for value in source_url_candidates:
        s3_uri = _extract_s3_uri_from_url(value)
        if s3_uri:
            break

    provider = "s3" if s3_uri else "http" if candidate.primary_url else "other"
    source_access = _base_source_access(
        provider=provider,
        bucket_uri=s3_uri,
        requested_version=requested_version,
    )

    if not s3_uri:
        source_access["bucket_check"].update(
            {
                "state": "not_applicable",
                "method": "none",
                "checked_at": _utc_now_iso(),
                "message": "no S3 bucket URI detected for this source",
            }
        )
        return source_access

    bucket, prefix = _split_s3_uri(s3_uri)
    source_access["bucket_check"] = _probe_s3_bucket(bucket=bucket, prefix=prefix)
    return source_access


def _collect_source_access(
    *,
    candidate: DatasetRecord,
    simple_id: str,
    requested_version: str | None,
    remote_urls: dict[str, str],
) -> dict[str, Any]:
    cache_key = _source_access_cache_key(candidate.dataset_id, requested_version)
    cached = _cache_get_source_access(cache_key)
    if cached:
        return cached

    if _is_openneuro_dataset(candidate):
        payload = _resolve_openneuro_source_access(
            dataset_simple_id=simple_id,
            requested_version=requested_version,
        )
    else:
        payload = _resolve_generic_source_access(
            candidate=candidate,
            requested_version=requested_version,
            remote_urls=remote_urls,
        )

    _cache_set_source_access(cache_key, payload)
    return payload


def _skipped_source_access(
    *,
    candidate: DatasetRecord,
    simple_id: str,
    requested_version: str | None,
    remote_urls: dict[str, str],
) -> dict[str, Any]:
    if _is_openneuro_dataset(candidate):
        payload = _base_source_access(
            provider="openneuro",
            bucket_uri=f"s3://openneuro.org/{simple_id}",
            requested_version=requested_version,
        )
    else:
        source_url_candidates = [
            str(remote_urls.get("s3") or ""),
            str(remote_urls.get("primary") or ""),
            str(candidate.primary_url or ""),
        ]
        s3_uri = None
        for value in source_url_candidates:
            s3_uri = _extract_s3_uri_from_url(value)
            if s3_uri:
                break
        provider = "s3" if s3_uri else "http" if candidate.primary_url else "other"
        payload = _base_source_access(
            provider=provider,
            bucket_uri=s3_uri,
            requested_version=requested_version,
        )

    payload["bucket_check"].update(
        {
            "state": "skipped",
            "method": "none",
            "checked_at": _utc_now_iso(),
            "message": "skipped for local-fast dataset asset resolution",
        }
    )
    payload["version_check"]["mode"] = "skipped"
    return payload


def _resolve_openneuro_bids_path(
    simple_id: str, mounts: dict[str, Any]
) -> tuple[Path | None, list[dict[str, Any]]]:
    trace: list[dict[str, Any]] = []
    for root in _openneuro_mount_roots(mounts):
        candidates = [root / simple_id, root / simple_id / simple_id]
        for candidate in candidates:
            exists = candidate.exists()
            trace.append(
                {
                    "stage": "mount",
                    "kind": "raw",
                    "root": str(root),
                    "candidate": str(candidate),
                    "hit": exists,
                }
            )
            if exists:
                return candidate, trace
    return None, trace


def _discover_openneuro_derivatives(
    simple_id: str, mounts: dict[str, Any]
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    derivs: dict[str, str] = {}
    trace: list[dict[str, Any]] = []
    for root in _openneuro_deriv_roots(mounts):
        for kind in OPENNEURO_DERIV_BUCKETS:
            for suffix in (simple_id, f"{simple_id}-{kind}"):
                candidate = root / kind / suffix
                exists = candidate.exists()
                trace.append(
                    {
                        "stage": "mount",
                        "kind": kind,
                        "root": str(root),
                        "candidate": str(candidate),
                        "hit": exists,
                    }
                )
                if exists and kind not in derivs:
                    derivs[kind] = str(candidate)
                    break
    return derivs, trace


def _count_matches(base: Path, pattern: str) -> int:
    try:
        return sum(1 for _ in base.glob(pattern))
    except Exception:
        return 0


def _collect_required_file_status(
    bids_path: Path | None, analysis_goal: str
) -> dict[str, Any]:
    goal = _normalize_analysis_goal(analysis_goal)
    groups = (
        ANALYSIS_GOAL_REQUIRED_GROUPS.get(goal)
        or ANALYSIS_GOAL_REQUIRED_GROUPS["generic"]
    )
    status_groups: list[dict[str, Any]] = []
    missing_patterns: list[str] = []
    total_required = 0
    passed_required = 0

    for group in groups:
        patterns = list(group.get("patterns") or [])
        counts = {p: _count_matches(bids_path, p) if bids_path else 0 for p in patterns}
        matches = sum(counts.values())
        min_matches = int(group.get("min_matches", 1))
        optional = bool(group.get("optional", False))
        passed = matches >= min_matches
        if not optional:
            total_required += 1
            if passed:
                passed_required += 1
        if not passed:
            missing_patterns.extend(patterns)
        status_groups.append(
            {
                "name": group.get("name"),
                "patterns": patterns,
                "counts": counts,
                "min_matches": min_matches,
                "optional": optional,
                "passed": passed,
            }
        )

    return {
        "analysis_goal": goal,
        "groups": status_groups,
        "missing_patterns": sorted(set(missing_patterns)),
        "required_total": total_required,
        "required_passed": passed_required,
        "all_required_passed": passed_required == total_required,
    }


def _build_skipped_required_file_status(
    analysis_goal: str, *, note: str
) -> dict[str, Any]:
    goal = _normalize_analysis_goal(analysis_goal)
    return {
        "analysis_goal": goal,
        "groups": [],
        "missing_patterns": [],
        "required_total": 0,
        "required_passed": 0,
        "all_required_passed": False,
        "skipped": True,
        "note": note,
    }


def _run_bids_validator(bids_path: Path | None) -> dict[str, Any]:
    if not bids_path or not bids_path.exists():
        return {
            "ran": False,
            "errors": 0,
            "warnings": 0,
            "error_codes": [],
            "warning_codes": [],
        }
    if shutil.which("bids-validator") is None:
        return {
            "ran": False,
            "errors": 0,
            "warnings": 0,
            "error_codes": [],
            "warning_codes": [],
            "note": "bids-validator not installed",
        }
    try:
        proc = subprocess.run(
            ["bids-validator", str(bids_path), "--json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except Exception as exc:
        return {
            "ran": False,
            "errors": 0,
            "warnings": 0,
            "error_codes": [],
            "warning_codes": [],
            "note": f"bids-validator failed: {exc}",
        }
    payload = {}
    try:
        payload = json.loads(proc.stdout or "{}")
    except Exception:
        payload = {}
    issues = payload.get("issues", {})
    errors = issues.get("errors", []) or []
    warnings = issues.get("warnings", []) or []
    return {
        "ran": True,
        "errors": len(errors),
        "warnings": len(warnings),
        "error_codes": sorted(
            {int(e.get("code")) for e in errors if e.get("code") is not None}
        ),
        "warning_codes": sorted(
            {int(w.get("code")) for w in warnings if w.get("code") is not None}
        ),
    }


def _is_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        return os.access(path, os.W_OK)
    except Exception:
        return False


def _attempt_openneuro_auto_heal(
    dataset_simple_id: str,
    current_bids_path: Path | None,
    missing_patterns: list[str],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "attempted": False,
        "actions": [],
        "post_check": "not_run",
        "target_path": str(current_bids_path) if current_bids_path else None,
    }
    if not missing_patterns:
        result["post_check"] = "skipped"
        return result

    if shutil.which("aws") is None:
        result["attempted"] = True
        result["post_check"] = "failed"
        result["actions"].append(
            {"command": "aws s3 sync ...", "error": "aws cli not available"}
        )
        return result

    if current_bids_path and _is_writable_dir(current_bids_path):
        target = current_bids_path
    else:
        target = DEFAULT_OPENNEURO_CACHE_ROOT / "openneuro" / dataset_simple_id / "raw"
        target.mkdir(parents=True, exist_ok=True)
    result["target_path"] = str(target)

    include_patterns = sorted(set(missing_patterns))
    cmd = [
        "aws",
        "s3",
        "sync",
        f"s3://openneuro.org/{dataset_simple_id}",
        str(target),
        "--no-sign-request",
        "--exclude",
        "*",
    ]
    for pattern in include_patterns:
        cmd.extend(["--include", pattern])

    result["attempted"] = True
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=900,
        )
    except Exception as exc:
        result["post_check"] = "failed"
        result["actions"].append({"command": " ".join(cmd), "error": str(exc)})
        return result

    action = {
        "command": " ".join(cmd),
        "returncode": proc.returncode,
        "stdout_tail": (proc.stdout or "")[-1200:],
        "stderr_tail": (proc.stderr or "")[-1200:],
    }
    result["actions"].append(action)
    result["post_check"] = "passed" if proc.returncode == 0 else "failed"
    return result


def _participants_columns(bids_path: Path | None) -> list[str]:
    if not bids_path:
        return []
    participants = bids_path / "participants.tsv"
    if not participants.exists():
        return []
    try:
        header = participants.read_text(encoding="utf-8").splitlines()[0]
        return [h.strip().lower() for h in header.split("\t") if h.strip()]
    except Exception:
        return []


def _semantic_requirements(
    analysis_goal: str, semantic_intent: str | None
) -> list[str]:
    tokens = set((semantic_intent or "").lower().split())
    goal = _normalize_analysis_goal(analysis_goal)
    required: list[str] = []
    if goal == "lnm":
        required.append("lesion")
    if {"depression", "hamd", "bdi", "phq", "mood"} & tokens:
        required.append("depression_signal")
    return required


def _evaluate_semantic_match(
    candidate: DatasetRecord,
    bids_path: Path | None,
    analysis_goal: str,
    semantic_intent: str | None,
    *,
    catalog_path: Path,
) -> dict[str, Any]:
    required = _semantic_requirements(analysis_goal, semantic_intent)
    if not required:
        return {
            "matched": True,
            "required_signals": [],
            "found_signals": [],
            "block_reason": None,
            "suggestions": [],
        }

    search_text = " ".join(
        [
            candidate.name.lower(),
            (candidate.description or "").lower(),
            " ".join([t.lower() for t in candidate.tasks or []]),
            " ".join([d.lower() for d in candidate.disease_flags or []]),
            " ".join(_participants_columns(bids_path)),
        ]
    )
    found: list[str] = []
    if "lesion" in required and any(
        tok in search_text
        for tok in ("lesion", "stroke", "aphasia", "broca", "wernike")
    ):
        found.append("lesion")
    if "depression_signal" in required and any(
        tok in search_text for tok in ("depress", "hamd", "bdi", "phq", "mood")
    ):
        found.append("depression_signal")

    matched = set(required).issubset(set(found))
    suggestions: list[str] = []
    if not matched:
        intent_tokens = [
            t for t in (semantic_intent or "").lower().split() if len(t) > 2
        ]
        if intent_tokens:
            for rec in load_catalog(catalog_path):
                blob = rec.search_blob.lower()
                score = sum(1 for t in intent_tokens if t in blob)
                if score > 0:
                    suggestions.append(rec.dataset_id)
            suggestions = suggestions[:5]

    reason = None
    if not matched:
        reason = (
            f"Dataset '{candidate.dataset_id}' does not satisfy semantic intent "
            f"requirements: missing {sorted(set(required) - set(found))}"
        )
    return {
        "matched": matched,
        "required_signals": required,
        "found_signals": found,
        "block_reason": reason,
        "suggestions": suggestions,
    }


def _build_resource_readiness(
    *,
    local_path: Path | None,
    is_bids_available: bool,
    is_openneuro: bool,
    required_status: dict[str, Any],
    validator: dict[str, Any],
    healed: bool,
    semantic_match: dict[str, Any],
    enforce_semantic_gate: bool,
    analysis_goal: str,
) -> dict[str, Any]:
    local_path_exists = bool(local_path and Path(local_path).exists())
    notes: list[str] = []
    skipped_required_checks = bool(required_status.get("skipped"))
    skipped_note = str(required_status.get("note") or "").strip()

    if local_path_exists and skipped_note:
        notes.append(skipped_note)
    elif local_path_exists and not is_bids_available:
        notes.append(
            "Mounted dataset is readable but does not expose a BIDS root; "
            "returning generic resources without BIDS-only blocking."
        )
    if (
        local_path_exists
        and not skipped_required_checks
        and not required_status.get("all_required_passed", False)
    ):
        missing = required_status.get("missing_patterns") or []
        notes.append(
            f"Analysis goal '{analysis_goal}' is not fully satisfied by discovered "
            f"files; missing patterns: {missing}."
        )
    if local_path_exists and validator.get("errors", 0) > 0:
        notes.append(
            "BIDS validator reported errors; returning dataset resources with a "
            "note instead of blocking access."
        )

    if enforce_semantic_gate and not semantic_match.get("matched", True):
        readiness_status = "blocked"
        readiness_reason = semantic_match.get("block_reason") or "semantic mismatch"
    elif not local_path_exists:
        readiness_status = "blocked"
        readiness_reason = "Dataset path not available on mounts/cache"
    elif healed:
        readiness_status = "healed"
        readiness_reason = "Missing files were recovered by selective auto-heal"
    elif (
        is_bids_available
        and required_status.get("all_required_passed", False)
        and validator.get("errors", 0) == 0
    ):
        readiness_status = "ready"
        readiness_reason = "All preflight checks passed"
    else:
        readiness_status = "partial"
        readiness_reason = "Resources available with non-blocking dataset notes"

    return {
        "status": readiness_status,
        "reason": readiness_reason,
        "notes": notes,
        "note": notes[0] if notes else None,
        "is_openneuro": is_openneuro,
        "local_path_available": local_path_exists,
        "bids_validator": validator,
    }


# ----------------------------
# Dataset resource discovery
# ----------------------------


DEFAULT_MOUNTS_PATH = Path("configs/datasets/local_mounts.yaml")
DEFAULT_MANUAL_CATALOG = Path("configs/datasets/catalog_manual.jsonl")


def _resolve_catalog_candidate(
    catalog: list[DatasetRecord],
    dataset_ref: str,
) -> tuple[DatasetRecord | None, str, list[str]]:
    target = (dataset_ref or "").strip().lower()
    if not target:
        return None, "none", []

    ranked: list[tuple[int, str, DatasetRecord]] = []
    for rec in catalog:
        rid = rec.dataset_id.lower()
        rid_simple = rid.split(":")[-1]
        repo_id = (rec.source_repo_id or "").strip().lower()
        aliases = [a.strip().lower() for a in rec.alias or [] if str(a).strip()]
        name = rec.name.strip().lower()
        blob = rec.search_blob.lower()

        if target == rid:
            ranked.append((120, "exact_dataset_id", rec))
            continue
        if target == rid_simple:
            ranked.append((115, "exact_simple_id", rec))
            continue
        if repo_id and target == repo_id:
            ranked.append((110, "exact_source_repo_id", rec))
            continue
        if target in aliases:
            ranked.append((108, "exact_alias", rec))
            continue
        if target == name:
            ranked.append((100, "exact_name", rec))
            continue
        if target in name:
            ranked.append((70, "fuzzy_name", rec))
            continue
        if target in blob:
            ranked.append((45, "fuzzy_search_blob", rec))

    if not ranked:
        return None, "none", []

    ranked.sort(key=lambda item: (-item[0], item[2].dataset_id))
    best_score, best_mode, best_rec = ranked[0]
    tied = [item for item in ranked if item[0] == best_score and item[2] != best_rec]

    warnings: list[str] = []
    if tied:
        tied_ids = [best_rec.dataset_id, *[item[2].dataset_id for item in tied[:4]]]
        warnings.append(
            "ambiguous_dataset_ref: multiple catalog matches "
            f"with score {best_score}: {tied_ids}"
        )

    return best_rec, best_mode, warnings


def collect_dataset_resources(
    dataset_id_or_alias: str,
    *,
    catalog_path: Path | str = DEFAULT_CATALOG_PATH,
    mounts_path: Path | str = DEFAULT_MOUNTS_PATH,
    manual_catalog_path: Path | str = DEFAULT_MANUAL_CATALOG,
    dataset_version: str | None = None,
    analysis_goal: str = "generic",
    semantic_intent: str | None = None,
    auto_heal: bool = False,
    run_bids_validation: bool = True,
    enforce_semantic_gate: bool = True,
    check_source_access: bool = True,
) -> DatasetResources | None:
    """Return available local/remote resources for a dataset.

    Stability behavior:
      1) mount-first resource resolution
      2) readiness gate against goal-specific required files
      3) optional one-shot auto-heal for OpenNeuro missing patterns
      4) optional semantic gate to block intent/dataset mismatches
    """

    text = dataset_id_or_alias.strip()
    if not text:
        return None

    catalog_path = Path(catalog_path)
    mounts_path = Path(mounts_path)
    manual_catalog = Path(manual_catalog_path)
    goal = _normalize_analysis_goal(analysis_goal)

    catalog = load_catalog(catalog_path)
    mounts = _load_local_mounts(mounts_path)
    source_trace: list[dict[str, Any]] = []

    # Locate catalog record
    candidate, resolution_mode, resolver_warnings = _resolve_catalog_candidate(
        catalog, text
    )
    if not candidate:
        return None

    simple_id = _normalize_dataset_id(candidate.dataset_id)
    is_openneuro = _is_openneuro_dataset(candidate)

    # Paths (mount-first)
    if is_openneuro:
        bids_path, raw_trace = _resolve_openneuro_bids_path(simple_id, mounts)
        source_trace.extend(raw_trace)
        local_path = bids_path
        mount_status = {
            "mounted": bool(bids_path and Path(bids_path).exists()),
            "mount_kind": "openneuro_bids",
            "local_path": str(bids_path) if bids_path else None,
            "mount_root": str(Path(bids_path).parent) if bids_path else None,
            "matched_alias": simple_id,
            "searched_candidates": [
                t["candidate"]
                for t in raw_trace
                if isinstance(t, dict) and t.get("candidate")
            ],
        }
    else:
        local_path, raw_trace, mount_status = _resolve_non_openneuro_local_path(
            candidate, mounts
        )
        source_trace.extend(raw_trace)
        bids_path = local_path if _looks_like_bids_root(local_path) else None

    local_path_exists = bool(local_path and Path(local_path).exists())
    non_bids_local_note = None
    if local_path_exists and not (bids_path and Path(bids_path).exists()):
        non_bids_local_note = (
            "Mounted dataset is readable but does not expose a BIDS root. "
            "Returning local resources and skipping BIDS-specific required-file checks."
        )
    is_bids_available = bool(bids_path and Path(bids_path).exists())

    # Derivatives from mount discovery + manual catalog fallback
    discovered_derivatives: dict[str, str] = {}
    if is_openneuro:
        discovered_derivatives, deriv_trace = _discover_openneuro_derivatives(
            simple_id, mounts
        )
        source_trace.extend(deriv_trace)

    derivative_hits = find_existing_derivatives(
        candidate.dataset_id, manual_catalog=manual_catalog
    )
    derivatives: dict[str, str] = dict(discovered_derivatives)
    for hit in derivative_hits:
        derivatives.setdefault(hit.kind, str(hit.path))

    # Remote URLs
    remote_urls: dict[str, str] = {}
    if candidate.primary_url:
        remote_urls["primary"] = str(candidate.primary_url)
    # OpenNeuro convenience link when id looks like ds*
    if simple_id.startswith("ds"):
        remote_urls.setdefault(
            "openneuro", f"https://openneuro.org/datasets/{simple_id}"
        )
        remote_urls.setdefault("s3", f"s3://openneuro.org/{simple_id}")

    source_access = (
        _collect_source_access(
            candidate=candidate,
            simple_id=simple_id,
            requested_version=dataset_version,
            remote_urls=remote_urls,
        )
        if check_source_access
        else _skipped_source_access(
            candidate=candidate,
            simple_id=simple_id,
            requested_version=dataset_version,
            remote_urls=remote_urls,
        )
    )

    # Preflight required files / readiness
    if non_bids_local_note:
        required_status = _build_skipped_required_file_status(
            goal,
            note=non_bids_local_note,
        )
    else:
        required_status = _collect_required_file_status(bids_path, goal)
    validator = (
        _run_bids_validator(bids_path)
        if run_bids_validation
        else {
            "ran": False,
            "errors": 0,
            "warnings": 0,
            "error_codes": [],
            "warning_codes": [],
        }
    )

    auto_heal_result: dict[str, Any] = {
        "attempted": False,
        "actions": [],
        "post_check": "not_needed",
        "target_path": str(bids_path) if bids_path else None,
    }
    healed = False

    if auto_heal and is_openneuro and required_status["missing_patterns"]:
        auto_heal_result = _attempt_openneuro_auto_heal(
            simple_id,
            bids_path,
            list(required_status["missing_patterns"]),
        )
        if auto_heal_result.get("post_check") == "passed":
            healed = True
            healed_path = Path(str(auto_heal_result.get("target_path", "")))
            if healed_path.exists():
                bids_path = healed_path
                is_bids_available = True
            # Re-run gate after healing
            required_status = _collect_required_file_status(bids_path, goal)
            validator = (
                _run_bids_validator(bids_path) if run_bids_validation else validator
            )

    if enforce_semantic_gate or str(semantic_intent or "").strip():
        semantic_match = _evaluate_semantic_match(
            candidate,
            bids_path,
            goal,
            semantic_intent,
            catalog_path=catalog_path,
        )
    else:
        semantic_match = {
            "matched": True,
            "required_signals": [],
            "found_signals": [],
            "block_reason": None,
            "suggestions": [],
            "mode": "skipped",
        }

    readiness = _build_resource_readiness(
        local_path=local_path,
        is_bids_available=is_bids_available,
        is_openneuro=is_openneuro,
        required_status=required_status,
        validator=validator,
        healed=healed,
        semantic_match=semantic_match,
        enforce_semantic_gate=enforce_semantic_gate,
        analysis_goal=goal,
    )

    size_bytes = (
        candidate.approx_size_bytes if hasattr(candidate, "approx_size_bytes") else None
    )

    return DatasetResources(
        local_path=local_path,
        resolved_dataset_id=candidate.dataset_id,
        resolution_mode=resolution_mode,
        resolver_warnings=resolver_warnings,
        bids_path=bids_path,
        derivatives=derivatives,
        remote_urls=remote_urls,
        size_bytes=size_bytes,
        is_bids_available=is_bids_available,
        available_derivatives=sorted(derivatives.keys()),
        analysis_goal=goal,
        source_trace=source_trace,
        required_files=required_status,
        readiness=readiness,
        auto_heal=auto_heal_result,
        semantic_match=semantic_match,
        source_access=source_access,
        dataset_name=candidate.name,
        display_name=candidate.short_name or candidate.name,
        source_repo=candidate.source_repo,
        dataset_metadata={
            "tasks": list(candidate.tasks or []),
            "modalities": list(candidate.modalities or []),
            "license": candidate.license.value
            if hasattr(candidate.license, "value")
            else str(candidate.license or ""),
        },
        mount_status=mount_status,
    )


def resolve_dataset_reference(
    user_text: str,
    catalog_path: Path = DEFAULT_CATALOG_PATH,
    mounts_path: Path = DEFAULT_MOUNTS_PATH,
    manual_catalog_path: Path = DEFAULT_MANUAL_CATALOG,
) -> DatasetResolution | None:
    """Resolve a free-text dataset reference to a catalog entry and local path."""

    text = user_text.strip()
    if not text:
        return None

    catalog = load_catalog(catalog_path)
    mounts = _load_local_mounts(mounts_path)

    # Heuristic: ds000123 style IDs
    ds_pattern = re.compile(r"ds0*\d+", re.IGNORECASE)
    match_id = None
    m = ds_pattern.search(text)
    if m:
        match_id = m.group(0).lower()

    candidate: DatasetRecord | None
    if match_id:
        candidate, _mode, _warnings = _resolve_catalog_candidate(catalog, match_id)
    else:
        candidate, _mode, _warnings = _resolve_catalog_candidate(catalog, text)

    if not candidate:
        return None

    kg_node = f"dataset:{candidate.dataset_id}"

    resources = collect_dataset_resources(
        candidate.dataset_id,
        catalog_path=catalog_path,
        mounts_path=mounts_path,
        manual_catalog_path=manual_catalog_path,
    )

    return DatasetResolution(
        dataset_id=candidate.dataset_id,
        name=candidate.name,
        display_name=candidate.short_name or candidate.name,
        source_repo=candidate.source_repo,
        primary_url=str(candidate.primary_url) if candidate.primary_url else None,
        local_path=resources.local_path
        if resources
        else _path_from_mounts(candidate.dataset_id, mounts),
        kg_node_id=kg_node,
        bids_path=resources.bids_path if resources else None,
        remote_url=str(candidate.primary_url) if candidate.primary_url else None,
        aliases=candidate.alias or [],
        resources=resources,
        metadata={
            "modalities": candidate.modalities,
            "tasks": candidate.tasks,
            "license": candidate.license,
        },
    )


# ----------------------------
# Derivative reuse discovery
# ----------------------------


def _iter_manual_catalog(path: Path) -> Iterable[dict[str, Any]]:
    yield from _load_manual_catalog_rows(str(path.resolve()))


@lru_cache(maxsize=8)
def _load_manual_catalog_rows(path_str: str) -> tuple[dict[str, Any], ...]:
    path = Path(path_str)
    if not path.exists():
        return ()
    rows: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return tuple(rows)


def find_existing_derivatives(
    dataset_id: str,
    pipeline_signature: str | None = None,
    manual_catalog: Path = Path("configs/datasets/catalog_manual.jsonl"),
) -> list[DerivativeHit]:
    """Return locally-known derivatives for a dataset (if any).

    Looks for derivative paths recorded in the manual catalog. Filters by
    pipeline_signature when provided (simple substring match).
    """

    hits: list[DerivativeHit] = []
    keys = {
        "path_fmriprep": "fmriprep",
        "path_mriqc": "mriqc",
        "path_glmfitlins": "glmfitlins",
    }
    target_ids = {dataset_id.lower(), dataset_id.lower().split(":")[-1]}

    for row in _iter_manual_catalog(manual_catalog):
        row_ids: set[str] = set()
        for raw in (row.get("dataset_id"), row.get("source_repo_id")):
            if not raw:
                continue
            norm = str(raw).lower()
            row_ids.add(norm)
            row_ids.add(norm.split(":")[-1])

        if target_ids.isdisjoint(row_ids):
            continue
        for key, kind in keys.items():
            p = row.get(key)
            if not p:
                continue
            if pipeline_signature and pipeline_signature.lower() not in kind.lower():
                # skip if signature provided and doesn't match this derivative type
                continue
            path_obj = Path(p)
            hits.append(
                DerivativeHit(
                    dataset_id=dataset_id,
                    kind=kind,
                    path=path_obj,
                    description=f"Existing {kind} derivative",
                    pipeline_signature=pipeline_signature,
                )
            )
    return hits


__all__ = [
    "DatasetResolution",
    "DatasetResources",
    "DerivativeHit",
    "collect_dataset_resources",
    "find_existing_derivatives",
    "resolve_dataset_reference",
]
