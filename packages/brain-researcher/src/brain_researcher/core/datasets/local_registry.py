from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

LocalDatasetSource = Literal["upload", "openneuro_cache", "local"]


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _default_registry_path() -> Path:
    """Return the local dataset registry path.

    Defaults to `<BR_DATA_ROOT>/../datasets/local_registry.json`.
    With the default BR_DATA_ROOT=data/bids, this becomes `data/datasets/local_registry.json`.
    """
    env = os.getenv("BR_LOCAL_DATASET_REGISTRY")
    if env:
        return Path(env).expanduser()

    bids_root = Path(os.getenv("BR_DATA_ROOT", "data/bids")).expanduser()
    return bids_root.parent / "datasets" / "local_registry.json"


@contextmanager
def _locked(lock_path: Path):
    """Best-effort cross-process lock using fcntl (no-op on unsupported platforms)."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        try:  # pragma: no cover - platform dependent
            import fcntl  # type: ignore

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except Exception:
            pass
        yield
    finally:
        try:  # pragma: no cover - platform dependent
            import fcntl  # type: ignore

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        handle.close()


class LocalDatasetRecord(BaseModel):
    dataset_id: str = Field(description="Stable identifier for this dataset")
    bids_root: str = Field(description="Absolute path to the local BIDS dataset root")
    source: LocalDatasetSource = Field(
        description="How this dataset was imported (upload/openneuro_cache/local)"
    )

    created_at: str = Field(default_factory=_iso_now)
    updated_at: str = Field(default_factory=_iso_now)

    name: str | None = Field(default=None, description="Human-friendly dataset name")
    description: str | None = Field(default=None)

    manifest_sha256: str | None = Field(
        default=None,
        description="manifest_sha256 from dataset_manifest.json (if present)",
    )
    validation: dict[str, Any] | None = Field(
        default=None, description="BIDS validator summary (if available)"
    )
    meta: dict[str, Any] | None = Field(
        default=None,
        description="Extra metadata (e.g., dataset_description.json subset)",
    )


def _read_registry_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": "local-dataset-registry-v1", "datasets": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return {"schema_version": "local-dataset-registry-v1", "datasets": payload}
        if isinstance(payload, dict) and "datasets" in payload:
            return payload
    except Exception:
        pass
    return {"schema_version": "local-dataset-registry-v1", "datasets": []}


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def list_local_datasets(path: Path | str | None = None) -> list[LocalDatasetRecord]:
    registry_path = Path(path) if path else _default_registry_path()
    lock_path = registry_path.with_suffix(registry_path.suffix + ".lock")
    with _locked(lock_path):
        payload = _read_registry_payload(registry_path)
    datasets = payload.get("datasets", [])
    records: list[LocalDatasetRecord] = []
    if isinstance(datasets, list):
        for item in datasets:
            if not isinstance(item, dict):
                continue
            try:
                records.append(LocalDatasetRecord(**item))
            except Exception:
                continue
    return sorted(records, key=lambda r: r.dataset_id)


def get_local_dataset(
    dataset_id: str, path: Path | str | None = None
) -> LocalDatasetRecord | None:
    dataset_id = (dataset_id or "").strip()
    if not dataset_id:
        return None
    for rec in list_local_datasets(path=path):
        if rec.dataset_id == dataset_id:
            return rec
    return None


def upsert_local_dataset(
    record: LocalDatasetRecord, path: Path | str | None = None
) -> LocalDatasetRecord:
    registry_path = Path(path) if path else _default_registry_path()
    lock_path = registry_path.with_suffix(registry_path.suffix + ".lock")

    with _locked(lock_path):
        payload = _read_registry_payload(registry_path)
        items = payload.get("datasets", [])
        if not isinstance(items, list):
            items = []

        updated = False
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            if item.get("dataset_id") == record.dataset_id:
                merged = {**item, **record.model_dump(mode="json")}
                if isinstance(item.get("created_at"), str) and item.get("created_at"):
                    merged["created_at"] = item["created_at"]
                merged["updated_at"] = _iso_now()
                items[idx] = merged
                updated = True
                break

        if not updated:
            items.append(record.model_dump(mode="json"))

        payload_out = {
            "schema_version": "local-dataset-registry-v1",
            "generated_at": _iso_now(),
            "datasets": items,
        }
        _atomic_write_json(registry_path, payload_out)

    return record


def delete_local_dataset(dataset_id: str, path: Path | str | None = None) -> bool:
    registry_path = Path(path) if path else _default_registry_path()
    lock_path = registry_path.with_suffix(registry_path.suffix + ".lock")
    dataset_id = (dataset_id or "").strip()
    if not dataset_id:
        return False

    with _locked(lock_path):
        payload = _read_registry_payload(registry_path)
        items = payload.get("datasets", [])
        if not isinstance(items, list):
            return False

        kept: list[dict[str, Any]] = [
            item
            for item in items
            if isinstance(item, dict) and item.get("dataset_id") != dataset_id
        ]
        if len(kept) == len(items):
            return False

        payload_out = {
            "schema_version": "local-dataset-registry-v1",
            "generated_at": _iso_now(),
            "datasets": kept,
        }
        _atomic_write_json(registry_path, payload_out)
        return True


__all__ = [
    "LocalDatasetRecord",
    "LocalDatasetSource",
    "delete_local_dataset",
    "get_local_dataset",
    "list_local_datasets",
    "upsert_local_dataset",
]
