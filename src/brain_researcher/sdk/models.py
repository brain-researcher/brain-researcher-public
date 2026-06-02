"""Lightweight user-facing models for the Brain Researcher SDK.

These are simplified projections of the internal ``ToolSpec`` / MCP response
dicts.  They deliberately omit heavy internal fields (``json_schema``,
``qc_spec``, ``execution_capabilities``, …) so that notebook users see a
clean, stable surface.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from pydantic import BaseModel, Field


class ToolCard(BaseModel):
    """A discoverable tool card returned by ``br.search()``."""

    name: str = Field(description="Canonical tool identifier, e.g. 'fsl.bet'")
    description: str = Field(default="", description="Human-readable description")
    backend: str = Field(
        default="python",
        description="Execution backend: niwrap | python | external_api",
    )
    modalities: list[str] = Field(
        default_factory=list, description="Supported modalities"
    )
    kind: str | None = Field(default=None, description="Category: imaging, kg, viz, …")
    category: str | None = Field(default=None, description="Sub-category")
    tags: list[str] = Field(default_factory=list)
    cost_hint: str | None = Field(
        default=None, description="cheap | normal | expensive"
    )
    requires_runtime: str | None = Field(
        default=None, description="python | container | network | none"
    )
    implementation_level: str = Field(default="production")

    @classmethod
    def from_mcp_card(cls, data: dict[str, Any]) -> ToolCard:
        """Build a ``ToolCard`` from a raw MCP ``tool_search`` card dict."""
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            backend=data.get("backend", "python"),
            modalities=data.get("modalities") or [],
            kind=data.get("kind"),
            category=data.get("category"),
            tags=data.get("tags") or [],
            cost_hint=data.get("cost_hint"),
            requires_runtime=data.get("requires_runtime"),
            implementation_level=data.get("implementation_level", "production"),
        )


class ToolResult(BaseModel):
    """Result of a completed tool execution."""

    ok: bool = Field(description="Whether execution succeeded")
    tool_id: str = Field(default="", description="Resolved tool identifier")
    output: dict[str, Any] = Field(
        default_factory=dict, description="Raw result payload"
    )
    run_id: str | None = Field(default=None)
    warnings: list[str] = Field(default_factory=list)

    @property
    def output_path(self) -> str | None:
        """Convenience accessor for the primary output file path."""
        return (
            self.output.get("output_path")
            or self.output.get("output_file")
            or self.output.get("output")
        )

    @classmethod
    def from_mcp_response(cls, data: dict[str, Any]) -> ToolResult:
        """Build from a raw MCP ``tool_execute`` response dict."""
        return cls(
            ok=bool(data.get("ok", False)),
            tool_id=data.get("resolved_tool_id") or data.get("requested_tool_id", ""),
            output=data.get("result") or data.get("output") or data,
            run_id=data.get("run_id"),
            warnings=data.get("warnings") or [],
        )


class JobHandle(BaseModel):
    """Handle for a long-running tool execution.

    The handle is keyed by a deterministic content hash so that re-execution
    of the same ``(tool_id, params)`` pair returns the cached handle instead
    of re-submitting the job.
    """

    job_id: str = Field(description="Unique job identifier")
    tool_id: str = Field(default="")
    status: str = Field(
        default="pending", description="pending | running | succeeded | failed"
    )
    run_id: str | None = Field(default=None)
    content_hash: str = Field(default="", description="SHA-256 of (tool_id, params)")
    _client: Any = None  # back-reference, set by BRClient

    model_config = {"arbitrary_types_allowed": True}

    @staticmethod
    def compute_content_hash(tool_id: str, params: dict[str, Any]) -> str:
        """Deterministic hash for ``(tool_id, params)``."""
        blob = json.dumps({"tool_id": tool_id, "params": params}, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()


_RUN_TERMINAL_STATUSES = frozenset(
    {
        "completed",
        "succeeded",
        "failed",
        "cancelled",
        "timeout",
        "skipped",
    }
)


class RunHandle(BaseModel):
    """Handle for a run created elsewhere (by Studio, an external agent, …).

    Returned by :func:`brain_researcher.sdk.attach_run`. Carries enough fields
    to introspect a run from inside a notebook without re-fetching every time:

    - ``run_id`` — the run identifier
    - ``status`` — current status string (``pending``/``running``/``completed``/…)
    - ``artifacts`` — list of artifact entries returned by ``run_bundle_get``
    - ``logs`` — list of log entries returned by ``run_logs``
    - ``workflow`` — workflow metadata associated with the run, if any
    - ``dataset`` — dataset metadata associated with the run, if any

    Use :meth:`refresh` to re-fetch status and :meth:`wait` to block until
    a terminal status is reached.
    """

    run_id: str
    status: str = "unknown"
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    logs: list[dict[str, Any]] = Field(default_factory=list)
    workflow: dict[str, Any] | None = None
    dataset: dict[str, Any] | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
    _client: Any = None

    model_config = {"arbitrary_types_allowed": True}

    @classmethod
    def from_mcp_response(
        cls, run_id: str, payload: dict[str, Any], *, client: Any | None = None
    ) -> RunHandle:
        bundle = payload.get("bundle") if isinstance(payload, dict) else None
        artifacts: list[dict[str, Any]] = []
        if isinstance(bundle, dict):
            raw_artifacts = bundle.get("artifacts") or bundle.get("outputs") or []
            if isinstance(raw_artifacts, list):
                artifacts = [
                    item if isinstance(item, dict) else {"value": item}
                    for item in raw_artifacts
                ]
        record = payload.get("record") if isinstance(payload, dict) else None
        status = ""
        workflow: dict[str, Any] | None = None
        dataset: dict[str, Any] | None = None
        if isinstance(record, dict):
            status = str(record.get("status") or "")
            wf = record.get("workflow") or record.get("plan", {}).get("workflow")
            if isinstance(wf, dict):
                workflow = wf
            ds = record.get("dataset") or record.get("plan", {}).get("dataset")
            if isinstance(ds, dict):
                dataset = ds
        if not status:
            status = str(payload.get("status") or "unknown")
        handle = cls(
            run_id=run_id,
            status=status or "unknown",
            artifacts=artifacts,
            workflow=workflow,
            dataset=dataset,
            raw=payload if isinstance(payload, dict) else {},
        )
        handle._client = client
        return handle

    def refresh(self) -> RunHandle:
        """Re-fetch this run's status and mutate this handle in place."""
        if self._client is None:
            raise RuntimeError(
                "RunHandle has no bound client; call br.attach_run() to obtain one"
            )
        payload = self._client.call("run_bundle_get", {"run_id": self.run_id})
        refreshed = RunHandle.from_mcp_response(
            self.run_id, payload, client=self._client
        )
        self.status = refreshed.status
        self.artifacts = refreshed.artifacts
        if refreshed.workflow is not None:
            self.workflow = refreshed.workflow
        if refreshed.dataset is not None:
            self.dataset = refreshed.dataset
        self.raw = refreshed.raw
        try:
            logs_resp = self._client.call("run_logs", {"run_id": self.run_id})
            items = logs_resp.get("items") if isinstance(logs_resp, dict) else None
            if isinstance(items, list):
                self.logs = [item for item in items if isinstance(item, dict)]
        except Exception:
            pass
        return self

    def wait(self, timeout: int = 300, poll_interval: float = 5.0) -> RunHandle:
        """Block until the run reaches a terminal status or ``timeout`` elapses.

        Synchronous polling loop — fine for notebook use, not for async code.
        """
        deadline = time.monotonic() + max(1, int(timeout))
        while True:
            self.refresh()
            if self.status.lower() in _RUN_TERMINAL_STATUSES:
                return self
            if time.monotonic() >= deadline:
                return self
            time.sleep(max(0.1, poll_interval))
