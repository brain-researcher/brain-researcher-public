"""Vendor-neutral microscope callback adapter for realtime two-photon streaming."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .realtime_twophoton_publisher import (
    RawSocketPublisher,
    RawSocketPublisherConfig,
)

PayloadExtractor = Callable[[Any], Any]
PayloadFieldSpec = str | tuple[str, ...] | list[str] | PayloadExtractor


def _lookup_payload_path(payload: Any, path: str) -> Any:
    current = payload
    for part in path.split("."):
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(part)
            current = current[part]
            continue
        if not hasattr(current, part):
            raise AttributeError(part)
        current = getattr(current, part)
    return current


def resolve_payload_field(payload: Any, spec: PayloadFieldSpec) -> Any:
    """Resolve a value from a callback payload using a flexible field spec."""

    if callable(spec):
        return spec(payload)
    if isinstance(spec, str):
        return _lookup_payload_path(payload, spec)
    if isinstance(spec, tuple | list):
        last_error: Exception | None = None
        for candidate in spec:
            try:
                return _lookup_payload_path(payload, str(candidate))
            except (AttributeError, KeyError, TypeError, ValueError) as exc:
                last_error = exc
        raise KeyError(
            f"None of the payload field candidates were present: {list(spec)!r}"
        ) from last_error
    raise TypeError(f"Unsupported payload field spec: {type(spec)!r}")


@dataclass(frozen=True)
class MicroscopeCallbackMapping:
    """Declarative field mapping from a microscope SDK payload to a frame event."""

    frame: PayloadFieldSpec
    timestamp_s: PayloadFieldSpec | None = None
    frame_id: PayloadFieldSpec | None = None
    metadata_fields: dict[str, PayloadFieldSpec] = field(default_factory=dict)
    optional_metadata_fields: dict[str, PayloadFieldSpec] = field(default_factory=dict)


@dataclass(frozen=True)
class MicroscopeFrameAdapterConfig:
    """Configuration for adapting acquisition callbacks to raw_socket publishing."""

    publisher: RawSocketPublisherConfig = field(
        default_factory=RawSocketPublisherConfig
    )
    session_id: str | None = None
    source_name: str | None = None
    auto_start: bool = True
    auto_timestamp: bool = True
    start_metadata: dict[str, Any] = field(default_factory=dict)
    frame_metadata: dict[str, Any] = field(default_factory=dict)
    end_metadata: dict[str, Any] = field(default_factory=dict)


class MicroscopeFrameAdapter:
    """Adapt microscope acquisition callbacks to the raw_socket frame protocol."""

    def __init__(
        self,
        config: MicroscopeFrameAdapterConfig,
        publisher: RawSocketPublisher | None = None,
    ):
        self.config = config
        self.publisher = publisher or RawSocketPublisher(config.publisher)
        self._started = False
        self._frame_counter = 0

    def _base_start_metadata(self) -> dict[str, Any]:
        metadata = dict(self.config.start_metadata)
        if self.config.session_id is not None:
            metadata.setdefault("session_id", self.config.session_id)
        if self.config.source_name is not None:
            metadata.setdefault("source_name", self.config.source_name)
        return metadata

    def start_session(self, metadata: dict[str, Any] | None = None) -> None:
        if self._started:
            return
        payload = self._base_start_metadata()
        if metadata:
            payload.update(metadata)
        self.publisher.send_start(payload or None)
        self._started = True

    def _resolve_timestamp(self, timestamp_s: float | None) -> float | None:
        if timestamp_s is not None:
            return float(timestamp_s)
        if self.config.auto_timestamp:
            return float(time.perf_counter())
        return None

    def _resolve_frame_id(self, frame_id: int | None) -> int:
        resolved = self._frame_counter if frame_id is None else int(frame_id)
        self._frame_counter = max(self._frame_counter, resolved + 1)
        return resolved

    def publish_frame(
        self,
        frame: np.ndarray,
        *,
        frame_id: int | None = None,
        timestamp_s: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        if self.config.auto_start and not self._started:
            self.start_session()
        elif not self._started:
            raise RuntimeError(
                "Session has not been started. Call start_session() first."
            )

        payload = dict(self.config.frame_metadata)
        if metadata:
            payload.update(metadata)

        resolved_frame_id = self._resolve_frame_id(frame_id)
        resolved_timestamp = self._resolve_timestamp(timestamp_s)
        self.publisher.send_frame(
            np.asarray(frame),
            frame_id=resolved_frame_id,
            timestamp_s=resolved_timestamp,
            metadata=payload or None,
        )
        return resolved_frame_id

    def end_session(self, metadata: dict[str, Any] | None = None) -> None:
        if not self._started:
            return
        payload = dict(self.config.end_metadata)
        if metadata:
            payload.update(metadata)
        self.publisher.send_end(payload or None)
        self._started = False

    def close(self) -> None:
        self.publisher.close()
        self._started = False

    def make_payload_callback(
        self,
        *,
        frame_extractor: PayloadExtractor,
        timestamp_extractor: PayloadExtractor | None = None,
        frame_id_extractor: PayloadExtractor | None = None,
        metadata_extractor: PayloadExtractor | None = None,
    ) -> Callable[[Any], int]:
        """Build a generic callback for vendor SDK payload objects."""

        def _callback(payload: Any) -> int:
            frame = np.asarray(frame_extractor(payload))
            timestamp_s = (
                None if timestamp_extractor is None else timestamp_extractor(payload)
            )
            frame_id = (
                None if frame_id_extractor is None else frame_id_extractor(payload)
            )
            metadata = (
                None if metadata_extractor is None else metadata_extractor(payload)
            )
            if metadata is not None and not isinstance(metadata, dict):
                raise ValueError("metadata_extractor must return a dict or None")
            return self.publish_frame(
                frame,
                frame_id=None if frame_id is None else int(frame_id),
                timestamp_s=None if timestamp_s is None else float(timestamp_s),
                metadata=metadata,
            )

        return _callback

    def make_field_callback(
        self,
        *,
        frame_field: PayloadFieldSpec,
        timestamp_field: PayloadFieldSpec | None = None,
        frame_id_field: PayloadFieldSpec | None = None,
        metadata_fields: dict[str, PayloadFieldSpec] | None = None,
        optional_metadata_fields: dict[str, PayloadFieldSpec] | None = None,
    ) -> Callable[[Any], int]:
        """Build a callback from dict/object field mappings.

        Field specs can be:
        - a dotted path string like ``"frame.data"``
        - a tuple/list of fallback paths like ``("frame", "image")``
        - a callable that receives the raw payload
        """

        mapping = MicroscopeCallbackMapping(
            frame=frame_field,
            timestamp_s=timestamp_field,
            frame_id=frame_id_field,
            metadata_fields=metadata_fields or {},
            optional_metadata_fields=optional_metadata_fields or {},
        )
        return self.make_mapped_callback(mapping)

    def make_mapped_callback(
        self,
        mapping: MicroscopeCallbackMapping,
    ) -> Callable[[Any], int]:
        """Build a callback from a declarative payload mapping."""

        def _frame_extractor(payload: Any) -> Any:
            return resolve_payload_field(payload, mapping.frame)

        def _timestamp_extractor(payload: Any) -> Any:
            if mapping.timestamp_s is None:
                return None
            return resolve_payload_field(payload, mapping.timestamp_s)

        def _frame_id_extractor(payload: Any) -> Any:
            if mapping.frame_id is None:
                return None
            return resolve_payload_field(payload, mapping.frame_id)

        def _metadata_extractor(payload: Any) -> dict[str, Any] | None:
            metadata: dict[str, Any] = {}
            for key, field_spec in mapping.metadata_fields.items():
                metadata[key] = resolve_payload_field(payload, field_spec)
            for key, field_spec in mapping.optional_metadata_fields.items():
                try:
                    metadata[key] = resolve_payload_field(payload, field_spec)
                except (AttributeError, KeyError, TypeError, ValueError):
                    continue
            return metadata or None

        return self.make_payload_callback(
            frame_extractor=_frame_extractor,
            timestamp_extractor=(
                None if mapping.timestamp_s is None else _timestamp_extractor
            ),
            frame_id_extractor=(
                None if mapping.frame_id is None else _frame_id_extractor
            ),
            metadata_extractor=_metadata_extractor,
        )

    def __enter__(self) -> MicroscopeFrameAdapter:
        return self

    def __exit__(self, exc_type, exc, exc_tb) -> None:
        self.close()
