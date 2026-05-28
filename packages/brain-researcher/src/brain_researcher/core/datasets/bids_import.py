from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from brain_researcher.core.datasets.local_registry import (
    LocalDatasetRecord,
    LocalDatasetSource,
    upsert_local_dataset,
)
from brain_researcher.core.ingestion.bids_io import (
    validate_bids_dataset,
    write_bids_dataset_manifest,
)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sanitize_dataset_id(dataset_id: str) -> str:
    dataset_id = (dataset_id or "").strip()
    if not dataset_id:
        raise ValueError("dataset_id is required")
    if "/" in dataset_id or "\\" in dataset_id:
        raise ValueError("dataset_id must not contain path separators")
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$", dataset_id):
        raise ValueError("dataset_id must match ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    return dataset_id


def _default_bids_root() -> Path:
    return Path(os.getenv("BR_DATA_ROOT", "data/bids")).expanduser()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _is_zipinfo_symlink(info: zipfile.ZipInfo) -> bool:
    # Unix symlink is stored in the high 16 bits of external_attr (st_mode)
    # 0o120000 indicates a symlink.
    return (info.external_attr >> 16) & 0o170000 == 0o120000


def _safe_extract_zip(
    zip_path: Path,
    dest_dir: Path,
    *,
    max_files: int,
    max_total_bytes: int,
) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    total_bytes = 0
    extracted_files = 0

    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            extracted_files += 1
            if extracted_files > max_files:
                raise ValueError(f"Zip contains too many files (>{max_files})")

            if _is_zipinfo_symlink(info):
                raise ValueError(f"Zip contains symlink entry: {info.filename}")

            total_bytes += int(info.file_size or 0)
            if total_bytes > max_total_bytes:
                raise ValueError(
                    f"Zip expands to too many bytes (>{max_total_bytes} bytes)"
                )

            raw_name = info.filename.replace("\\\\", "/")
            if raw_name.startswith("/") or raw_name.startswith("../"):
                raise ValueError(f"Unsafe zip path: {info.filename}")

            out_path = (dest_dir / raw_name).resolve()
            try:
                out_path.relative_to(dest_dir.resolve())
            except ValueError:
                raise ValueError(
                    f"Zip path escapes destination: {info.filename}"
                ) from None

            out_path.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, out_path.open("wb") as dst:
                shutil.copyfileobj(src, dst)


def _find_bids_root(extracted_dir: Path) -> Path:
    candidates = list(extracted_dir.rglob("dataset_description.json"))
    if not candidates:
        raise ValueError("No dataset_description.json found; not a BIDS dataset zip")

    # Prefer the shallowest dataset_description.json (handles zips with top-level folder)
    candidates.sort(key=lambda p: len(p.relative_to(extracted_dir).parts))
    return candidates[0].parent


def _read_dataset_description(bids_root: Path) -> dict[str, Any] | None:
    path = bids_root / "dataset_description.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def register_bids_dataset(
    *,
    dataset_id: str,
    bids_root: Path,
    source: LocalDatasetSource,
    extra_meta: dict[str, Any] | None = None,
) -> LocalDatasetRecord:
    """Register (or update) a local BIDS dataset in the local registry."""
    bids_root = bids_root.expanduser().resolve()
    dataset_id = _sanitize_dataset_id(dataset_id)

    dataset_desc = _read_dataset_description(bids_root) or {}
    name = (
        dataset_desc.get("Name") if isinstance(dataset_desc.get("Name"), str) else None
    )
    description = (
        dataset_desc.get("HowToAcknowledge")
        if isinstance(dataset_desc.get("HowToAcknowledge"), str)
        else None
    )

    manifest_sha256: str | None = None
    manifest_path = bids_root / "dataset_manifest.json"
    if manifest_path.is_file():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                manifest_sha256 = data.get("manifest_sha256")
        except Exception:
            manifest_sha256 = None

    validation_path = bids_root / "bids_validation.json"
    validation: dict[str, Any] | None = None
    if validation_path.is_file():
        try:
            v = json.loads(validation_path.read_text(encoding="utf-8"))
            validation = v if isinstance(v, dict) else None
        except Exception:
            validation = None

    meta: dict[str, Any] = {}
    for k in ("BIDSVersion", "License", "Authors", "DatasetDOI", "ReferencesAndLinks"):
        if k in dataset_desc:
            meta[k] = dataset_desc.get(k)
    if extra_meta:
        meta.update(extra_meta)

    record = LocalDatasetRecord(
        dataset_id=dataset_id,
        bids_root=str(bids_root),
        source=source,
        name=name,
        description=description,
        manifest_sha256=manifest_sha256,
        validation=validation,
        meta=meta or None,
    )
    return upsert_local_dataset(record)


class ImportBIDSZipResult(BaseModel):
    dataset_id: str
    bids_root: str
    source: Literal["upload"] = "upload"
    manifest_sha256: str | None = None
    validation: dict[str, Any] | None = None
    created_at: str = Field(default_factory=_iso_now)


def import_bids_zip(
    *,
    zip_path: Path | str,
    dataset_id: str | None = None,
    dest_root: Path | str | None = None,
    overwrite: bool = False,
    validate: bool = True,
    strict: bool = True,
    manifest_mode: Literal["fast", "secure", "paranoid"] = "secure",
    include_derivatives: bool = False,
    max_hash_mb: int | None = None,
    max_files: int | None = None,
    max_total_bytes: int | None = None,
) -> ImportBIDSZipResult:
    """Import an uploaded BIDS zip into the local `data/bids/<dataset_id>` tree."""
    zip_path = Path(zip_path).expanduser().resolve()
    if not zip_path.is_file():
        raise FileNotFoundError(str(zip_path))

    dest_root_path = (
        Path(dest_root).expanduser().resolve()
        if dest_root
        else _default_bids_root().resolve()
    )
    dest_root_path.mkdir(parents=True, exist_ok=True)

    max_files_val = int(os.getenv("BR_ZIP_IMPORT_MAX_FILES", "20000"))
    max_total_bytes_val = int(os.getenv("BR_ZIP_IMPORT_MAX_BYTES", str(25 * 1024**3)))
    if max_files is not None:
        max_files_val = int(max_files)
    if max_total_bytes is not None:
        max_total_bytes_val = int(max_total_bytes)

    with tempfile.TemporaryDirectory(prefix="br_bids_zip_") as tmp:
        tmp_dir = Path(tmp)
        _safe_extract_zip(
            zip_path,
            tmp_dir,
            max_files=max_files_val,
            max_total_bytes=max_total_bytes_val,
        )
        extracted_root = _find_bids_root(tmp_dir)

        final_dataset_id = dataset_id
        if final_dataset_id is None:
            final_dataset_id = f"bids-{uuid.uuid4().hex[:8]}"
        final_dataset_id = _sanitize_dataset_id(final_dataset_id)

        dest = (dest_root_path / final_dataset_id).resolve()
        try:
            dest.relative_to(dest_root_path)
        except ValueError:
            raise ValueError("Destination escapes dest_root") from None

        if dest.exists():
            if not overwrite:
                raise FileExistsError(f"Dataset already exists: {dest}")
            shutil.rmtree(dest)

        if extracted_root.is_dir() and extracted_root != tmp_dir:
            shutil.move(extracted_root.as_posix(), dest.as_posix())
        else:
            shutil.copytree(extracted_root, dest)

    # Post-import: best-effort validation + manifest
    validation: dict[str, Any] | None = None
    if validate:
        validation = validate_bids_dataset(dest.as_posix(), strict=strict)
        _atomic_write_json(dest / "bids_validation.json", validation)

    manifest = write_bids_dataset_manifest(
        dest,
        mode=manifest_mode,
        include_derivatives=include_derivatives,
        max_hash_mb=max_hash_mb,
    )
    manifest_sha256: str | None = None
    if isinstance(manifest, dict):
        manifest_sha256 = manifest.get("manifest_sha256")

    register_bids_dataset(
        dataset_id=final_dataset_id,
        bids_root=dest,
        source="upload",
        extra_meta={"imported_from": str(zip_path)},
    )

    return ImportBIDSZipResult(
        dataset_id=final_dataset_id,
        bids_root=str(dest),
        manifest_sha256=manifest_sha256,
        validation=validation,
    )


__all__ = [
    "ImportBIDSZipResult",
    "import_bids_zip",
    "register_bids_dataset",
]
