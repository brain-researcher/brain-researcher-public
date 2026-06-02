"""
Lightweight telemetry helpers for the Brain Researcher agent.

The goal is to give all entrypoints (/chat, /act, MCP, CLI) a shared place to:
  - generate stable identifiers (run_id, prompt_hash)
  - capture span-style timing metadata
  - persist structured events to NDJSON for downstream analytics
  - (optionally) fan those events out to an OTLP-compatible exporter later
"""

from __future__ import annotations

import contextlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from brain_researcher.config.paths import get_data_root

_OTEL_TRACER = None
_OTEL_STATUS = None


def _init_otlp_tracer():
    endpoint_grpc = os.getenv("BRAIN_RESEARCHER_OTLP_GRPC")
    endpoint_http = os.getenv("BRAIN_RESEARCHER_OTLP_HTTP")
    if not endpoint_grpc and not endpoint_http:
        return None, None
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import (  # type: ignore
            Status,
            StatusCode,
            TracerProvider,
        )
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        if endpoint_grpc:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,  # type: ignore
            )

            insecure = (
                os.getenv("BRAIN_RESEARCHER_OTLP_INSECURE", "true").lower() == "true"
            )
            exporter = OTLPSpanExporter(endpoint=endpoint_grpc, insecure=insecure)
        else:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,  # type: ignore
            )

            exporter = OTLPSpanExporter(endpoint=endpoint_http)

        service_name = os.getenv("BRAIN_RESEARCHER_SERVICE_NAME", "brain-researcher")
        provider = TracerProvider(
            resource=Resource.create({"service.name": service_name})
        )
        processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)
        tracer = trace.get_tracer("brain_researcher.telemetry")
        return tracer, (Status, StatusCode)
    except Exception:
        return None, None


_OTEL_TRACER, _OTEL_STATUS = _init_otlp_tracer()

ISO_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def utc_now() -> str:
    """Return current UTC timestamp in ISO-8601 format with milliseconds."""
    return datetime.now(timezone.utc).strftime(ISO_FORMAT)


def new_run_id() -> str:
    """Generate a random hexadecimal run identifier."""
    return uuid.uuid4().hex


def prompt_hash(text: Optional[str]) -> str:
    """Hash user-visible prompts so raw content never leaves the process."""
    if not text:
        return ""
    return sha256(text.encode("utf-8")).hexdigest()


def _base_dir() -> Path:
    """Resolve the base directory for telemetry event storage."""
    env_path = os.getenv("BRAIN_RESEARCHER_TELEMETRY_DIR")
    if env_path:
        return Path(env_path).expanduser()
    return get_data_root() / "agent_outputs" / "sessions"


def _ensure_day_dir() -> Path:
    """Ensure the YYYY-MM-DD directory exists beneath the base path."""
    day_dir = _base_dir() / datetime.utcnow().strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    return day_dir


def _prune(obj: Any) -> Any:
    """Recursively drop None values from dictionaries/lists."""
    if isinstance(obj, dict):
        return {k: _prune(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_prune(v) for v in obj if v is not None]
    return obj


def record_event(payload: Dict[str, Any], *, event_type: str = "agent") -> Path:
    """
    Persist a telemetry event as a single NDJSON line.

    Returns the path that was written so callers can surface it in logs/tests.
    """
    event = {
        "event_type": event_type,
        "event_ts": utc_now(),
        **_prune(payload),
    }
    output_path = _ensure_day_dir() / f"{event_type}.ndjson"
    with output_path.open("a", encoding="utf-8") as handle:
        json.dump(event, handle, ensure_ascii=False)
        handle.write("\n")
    return output_path


@dataclass
class TelemetrySpan:
    """Simple span capture for measuring elapsed time and attaching attributes."""

    name: str
    start_ns: int
    attributes: Dict[str, Any] = field(default_factory=dict)
    _otel_cm: Optional[Any] = field(default=None, repr=False)
    _otel_span: Optional[Any] = field(default=None, repr=False)
    _closed: bool = field(default=False, repr=False)

    def finish(self, **extra: Any) -> Dict[str, Any]:
        """Return a dictionary representing the completed span."""
        if self._closed:
            return {
                "name": self.name,
                "duration_ms": 0.0,
                "attributes": _prune({**self.attributes, **extra}),
            }
        duration_ms = (time.perf_counter_ns() - self.start_ns) / 1_000_000
        attributes = {**self.attributes, **extra}
        if self._otel_span:
            for key, value in attributes.items():
                if value is not None:
                    self._otel_span.set_attribute(key, value)
            if _OTEL_STATUS:
                status_cls, status_code_cls = _OTEL_STATUS
                if status_cls and status_code_cls:
                    status_val = (
                        status_code_cls.ERROR
                        if extra.get("status") == "error" or extra.get("error")
                        else status_code_cls.OK
                    )
                    self._otel_span.set_status(status_cls(status_val))
        if self._otel_cm:
            try:
                self._otel_cm.__exit__(None, None, None)
            except Exception:
                pass
            self._otel_cm = None
            self._otel_span = None
        self._closed = True
        return {
            "name": self.name,
            "duration_ms": round(duration_ms, 3),
            "attributes": _prune(attributes),
        }


def start_span(name: str, attributes: Optional[Dict[str, Any]] = None) -> TelemetrySpan:
    """Create a span capture that callers can finish() when work completes."""
    attributes = attributes or {}
    otel_cm = None
    otel_span = None
    if _OTEL_TRACER:
        try:
            otel_cm = _OTEL_TRACER.start_as_current_span(name, attributes=attributes)
            otel_span = otel_cm.__enter__()
        except Exception:
            otel_cm = None
            otel_span = None
    return TelemetrySpan(
        name=name,
        start_ns=time.perf_counter_ns(),
        attributes=attributes,
        _otel_cm=otel_cm,
        _otel_span=otel_span,
    )


@contextlib.contextmanager
def span_context(
    name: str, attributes: Optional[Dict[str, Any]] = None
) -> Iterator[TelemetrySpan]:
    """
    Context-manager wrapper over start_span for convenience.

    Usage:
        with span_context("agent.chat", {"run_id": run_id}) as span:
            ...
        completed = span.finish(status="ok")
    """
    span = start_span(name, attributes)
    try:
        yield span
    except Exception as exc:
        if not span._closed:
            span.finish(status="error", error=str(exc))
        raise
    finally:
        if not span._closed:
            span.finish(status="ok")
