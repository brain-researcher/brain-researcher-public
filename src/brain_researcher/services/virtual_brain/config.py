"""Configuration helpers for the Virtual Brain service."""

from __future__ import annotations

import json
import os
from dataclasses import MISSING, dataclass
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Optional


@dataclass(slots=True)
class VirtualBrainConfig:
    """Runtime configuration for the VB platform service."""

    parcellation: str = "schaefer100"
    sc_matrix_id: Optional[str] = None
    target_fc_id: Optional[str] = None
    cache_dir: Path = Path("data/virtual_brain/cache")
    default_model: str = "wilson_cowan"
    fetch_chunk_seconds: float = 30.0
    manifest_path: Optional[Path] = None

    @classmethod
    def from_mapping(cls, config: Mapping[str, Any] | None) -> "VirtualBrainConfig":
        data = dict(config or {})

        def _default(name: str) -> Any:
            field_def = cls.__dataclass_fields__[name]  # type: ignore[attr-defined]
            if field_def.default is not MISSING:
                return field_def.default
            if field_def.default_factory is not MISSING:  # type: ignore[attr-defined]
                return field_def.default_factory()  # type: ignore[attr-defined]
            raise AttributeError(f"No default value for {name}")

        cache_dir = Path(data.get("cache_dir", _default("cache_dir")))
        manifest_path = data.get("manifest_path")
        if manifest_path is not None:
            manifest_path = Path(manifest_path)
        return cls(
            parcellation=data.get("parcellation", _default("parcellation")),
            sc_matrix_id=data.get("sc_matrix_id"),
            target_fc_id=data.get("target_fc_id"),
            cache_dir=cache_dir,
            default_model=data.get("default_model", _default("default_model")),
            fetch_chunk_seconds=float(
                data.get("fetch_chunk_seconds", _default("fetch_chunk_seconds"))
            ),
            manifest_path=manifest_path,
        )

    @classmethod
    def from_env(cls, prefix: str = "VB_") -> "VirtualBrainConfig":
        payload: MutableMapping[str, Any] = {}
        for key, value in os.environ.items():
            if not key.startswith(prefix):
                continue
            payload[key.removeprefix(prefix).lower()] = value
        # Allow JSON override via VB_CONFIG
        if "config" in payload:
            try:
                payload.update(json.loads(payload["config"]))
            except json.JSONDecodeError:
                pass
        return cls.from_mapping(payload)
