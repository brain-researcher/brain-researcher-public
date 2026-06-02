"""Shared trace/request header helpers."""

from __future__ import annotations

from typing import Mapping, MutableMapping, Optional

TRACE_ID_HEADER = "X-Trace-Id"
REQUEST_ID_HEADER = "X-Request-Id"

_TRACE_CANDIDATES = (TRACE_ID_HEADER, "X-Trace-ID", "x-trace-id")
_REQUEST_CANDIDATES = (REQUEST_ID_HEADER, "X-Request-ID", "x-request-id")


def _first_header(headers: Mapping[str, str], names: tuple[str, ...]) -> Optional[str]:
    for name in names:
        value = headers.get(name)
        if value:
            return value
    return None


def get_request_id(headers: Mapping[str, str]) -> Optional[str]:
    """Return request id from known header variants."""
    return _first_header(headers, _REQUEST_CANDIDATES)


def get_trace_id(headers: Mapping[str, str]) -> Optional[str]:
    """Return trace id from known header variants (fallback to request id)."""
    return _first_header(headers, _TRACE_CANDIDATES) or get_request_id(headers)


def set_trace_headers(
    headers: MutableMapping[str, str],
    trace_id: Optional[str],
    request_id: Optional[str] = None,
) -> None:
    """Set canonical trace/request headers on a response/outbound request."""
    if trace_id:
        headers[TRACE_ID_HEADER] = trace_id
    if request_id:
        headers[REQUEST_ID_HEADER] = request_id


__all__ = [
    "TRACE_ID_HEADER",
    "REQUEST_ID_HEADER",
    "get_trace_id",
    "get_request_id",
    "set_trace_headers",
]
