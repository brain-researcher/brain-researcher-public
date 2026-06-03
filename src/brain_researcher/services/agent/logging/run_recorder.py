"""
Minimal Run Recorder for Agent Logging

This module provides a lightweight, production-ready logging system for
traceability, reproducibility, and auditability of agent executions.

Schema version: 0.0 (initial release)
"""

import hashlib
import json
import os
import pathlib
import random
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from brain_researcher.config.run_artifacts import get_metadata_root

# Timezone for local timestamps
LA = ZoneInfo("America/Los_Angeles")


def iso_utc() -> str:
    """Generate ISO-8601 UTC timestamp with microseconds."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def iso_local() -> str:
    """Generate ISO-8601 local timestamp with timezone offset."""
    return datetime.now(LA).isoformat(timespec="microseconds")


def file_fingerprint(path: str) -> dict[str, Any]:
    """
    Calculate SHA256 fingerprint and size for a file.

    Args:
        path: File path

    Returns:
        Dict with uri, sha256, and bytes
    """
    if not os.path.exists(path):
        return {
            "uri": f"file://{path}",
            "sha256": None,
            "bytes": 0,
            "error": "file not found",
        }

    h = hashlib.sha256()
    size = 0

    try:
        with open(path, "rb") as f:
            # Read in 1MB chunks
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
                size += len(chunk)

        return {
            "uri": f"file://{os.path.abspath(path)}",
            "sha256": h.hexdigest(),
            "bytes": size,
        }
    except Exception as e:
        return {"uri": f"file://{path}", "sha256": None, "bytes": 0, "error": str(e)}


def redacted_path(path: str) -> str:
    """
    Redact sensitive parts of file paths for privacy.

    Args:
        path: Original file path

    Returns:
        Redacted path with home directory and mount points obscured
    """
    # Replace home directory
    home = os.path.expanduser("~")
    redacted = path.replace(home, "~")

    # Common mount points to redact
    mount_patterns = ["/home/", "/Users/", "/scratch/", "/data/", "/mnt/"]

    for pattern in mount_patterns:
        if pattern in redacted:
            # Keep the mount point but redact user-specific parts
            parts = redacted.split(pattern)
            if len(parts) > 1:
                # Redact the first path component after mount point
                subparts = parts[1].split("/", 1)
                if len(subparts) > 1:
                    redacted = f"{parts[0]}{pattern}[REDACTED]/{subparts[1]}"

    return redacted


def get_package_version(package_name: str) -> str | None:
    """
    Get installed package version.

    Args:
        package_name: Name of the package

    Returns:
        Version string or None if not found
    """
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version(package_name)
    except (ImportError, PackageNotFoundError):
        # Fallback for older Python versions
        try:
            import pkg_resources

            return pkg_resources.get_distribution(package_name).version
        except:
            return None


def get_git_sha() -> str | None:
    """
    Get current git commit SHA.

    Returns:
        Short git SHA or None if not in git repo
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=1,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except:
        pass
    return None


def compute_tool_spec_digest(tool_spec: Any) -> str:
    """
    Compute SHA256 digest of tool specification.

    Args:
        tool_spec: Tool specification (dict or object)

    Returns:
        SHA256 hex digest
    """
    if hasattr(tool_spec, "model_dump_json"):
        # Pydantic model
        spec_str = tool_spec.model_dump_json(exclude_none=True)
    elif hasattr(tool_spec, "__dict__"):
        # Regular object
        spec_str = json.dumps(tool_spec.__dict__, sort_keys=True, default=str)
    else:
        # Dict or other
        spec_str = json.dumps(tool_spec, sort_keys=True, default=str)

    return f"sha256:{hashlib.sha256(spec_str.encode()).hexdigest()[:16]}"


def generate_trace_id() -> str:
    """
    Generate a W3C trace ID (32 hex chars).

    Returns:
        Trace ID string
    """
    return format(random.getrandbits(128), "032x")


def generate_span_id() -> str:
    """
    Generate a W3C span ID (16 hex chars).

    Returns:
        Span ID string
    """
    return format(random.getrandbits(64), "016x")


class RunRecorder:
    """
    Minimal run recorder for agent execution logging.

    Features:
    - Unified run_id across planning/execution/review phases
    - Three-tier timestamps (UTC, local, performance)
    - Parameter tracing (raw -> resolved -> validated)
    - File fingerprinting with privacy-aware redaction
    - Environment and version capture
    - Tool selection decision recording
    """

    def __init__(
        self,
        base_path: str | pathlib.Path | None = None,
        enable_otel: bool = True,
    ):
        """
        Initialize recorder with base logging path.

        Args:
            base_path: Base directory for log files. Defaults to the shared
                metadata resolver root.
            enable_otel: Enable OpenTelemetry trace/span generation
        """
        self.base = (
            pathlib.Path(base_path) if base_path is not None else get_metadata_root()
        )
        self.run_id = None
        self.phase = None
        self.t0 = None
        self.ts_event_utc = None
        self.ts_event_local = None

        # OpenTelemetry support
        self.enable_otel = enable_otel
        self.trace_id = None
        self.span_id = None
        self.parent_span_id = None

        # Cache environment info
        self._env_cache = None

    def start(
        self,
        phase: str,
        run_id: str | None = None,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> str:
        """
        Start recording a new phase.

        Args:
            phase: Phase name (planning|execution|review)
            run_id: Optional run_id to continue existing run
            trace_id: Optional OpenTelemetry trace ID
            parent_span_id: Optional parent span ID for distributed tracing

        Returns:
            Run ID for this recording session
        """
        self.phase = phase
        self.run_id = run_id or str(uuid.uuid4())
        self.t0 = time.perf_counter_ns()
        self.ts_event_utc = iso_utc()
        self.ts_event_local = iso_local()

        # OpenTelemetry trace context
        if self.enable_otel:
            self.trace_id = trace_id or generate_trace_id()
            self.span_id = generate_span_id()
            self.parent_span_id = parent_span_id

        return self.run_id

    def get_environment(self) -> dict[str, Any]:
        """
        Get current environment information.

        Returns:
            Dict with git_sha, python version, and key package versions
        """
        if self._env_cache is None:
            self._env_cache = {
                "git_sha": get_git_sha(),
                "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
                "nilearn": get_package_version("nilearn"),
                "numpy": get_package_version("numpy"),
                "nibabel": get_package_version("nibabel"),
                "langchain": get_package_version("langchain"),
            }

            # Add container image if available
            container_image = os.environ.get("BR_IMAGE") or os.environ.get(
                "CONTAINER_IMAGE"
            )
            if container_image:
                self._env_cache["container_image"] = container_image

        return self._env_cache

    def finish(
        self, record: dict[str, Any], categories: list[str] | None = None
    ) -> dict[str, Any]:
        """
        Finish recording and write to log files.

        Args:
            record: Record data to log
            categories: Optional list of category subdirectories

        Returns:
            Complete payload that was logged
        """
        if not self.run_id:
            raise ValueError("Must call start() before finish()")

        t1 = time.perf_counter_ns()

        # Build complete payload
        payload = {
            "schema_version": "0.0",
            "run_id": self.run_id,
            "phase": self.phase,
            "timestamps": {
                "ts_event_utc": self.ts_event_utc,
                "ts_event_local": self.ts_event_local,
                "perf": {
                    "start_ns": self.t0,
                    "end_ns": t1,
                    "duration_ms": (t1 - self.t0) / 1e6,
                },
            },
        }

        # Add OpenTelemetry trace context if enabled
        if self.enable_otel and self.trace_id:
            payload["trace"] = {"trace_id": self.trace_id, "span_id": self.span_id}
            if self.parent_span_id:
                payload["trace"]["parent_span_id"] = self.parent_span_id

        # Merge provided record
        payload.update(record)

        # Ensure status field exists
        if "status" not in payload:
            payload["status"] = "SUCCESS" if not payload.get("errors") else "FAILED"

        # Write to session file (daily bucket)
        day = self.ts_event_local[:10]  # YYYY-MM-DD
        session_file = self.base / "sessions" / f"{day}.jsonl"
        session_file.parent.mkdir(parents=True, exist_ok=True)

        with session_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

        # Write to category files if specified
        if categories:
            for cat in categories:
                cat_file = self.base / cat / "executions.jsonl"
                cat_file.parent.mkdir(parents=True, exist_ok=True)

                with cat_file.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(payload, ensure_ascii=False) + "\n")

        return payload

    def record_planning(
        self,
        query: str,
        tool_candidates: list[dict[str, Any]],
        selected_tool: str,
        candidate_count: int | None = None,
        candidate_source_counts: dict[str, int] | None = None,
        selected_tool_rank: int | None = None,
        selected_tool_in_top_k: dict[str, bool] | None = None,
        family_selected: bool | None = None,
        family_expand_success: bool | None = None,
        routing_latency_ms: float | None = None,
        surface: str | None = None,
        tool_spec: Any = None,
        llm_provider: str = None,
        llm_model: str = None,
        llm_params: dict[str, Any] = None,
        **kwargs,
    ) -> dict[str, Any]:
        """
        Record planning phase with tool selection.

        Args:
            query: User query
            tool_candidates: List of candidate tools with scores
            selected_tool: Name of selected tool
            tool_spec: Tool specification object
            llm_provider: LLM provider name
            llm_model: Model identifier
            llm_params: LLM parameters (temperature, etc)
            **kwargs: Additional fields to include

        Returns:
            Complete logged payload
        """
        record = {
            "request": {
                "query": query,
                "tool_candidates": tool_candidates,
                "selected_tool": selected_tool,
            }
        }
        if candidate_count is not None:
            record["request"]["candidate_count"] = candidate_count
        if candidate_source_counts is not None:
            record["request"]["candidate_source_counts"] = candidate_source_counts
        if selected_tool_rank is not None:
            record["request"]["selected_tool_rank"] = selected_tool_rank
        if selected_tool_in_top_k is not None:
            record["request"]["selected_tool_in_top_k"] = selected_tool_in_top_k
        if family_selected is not None:
            record["request"]["family_selected"] = family_selected
        if family_expand_success is not None:
            record["request"]["family_expand_success"] = family_expand_success
        if routing_latency_ms is not None:
            record["request"]["routing_latency_ms"] = routing_latency_ms
        if surface is not None:
            record["request"]["surface"] = surface

        if tool_spec:
            record["request"]["tool_spec_digest"] = compute_tool_spec_digest(tool_spec)

        if llm_provider or llm_model or llm_params:
            record["llm_call"] = {}
            if llm_provider:
                record["llm_call"]["provider"] = llm_provider
            if llm_model:
                record["llm_call"]["model"] = llm_model
            if llm_params:
                record["llm_call"]["params"] = llm_params

        # Add any additional fields
        record.update(kwargs)

        return self.finish(record, ["agent", "planning"])

    def record_execution(
        self,
        query: str,
        selected_tool: str,
        args_raw: dict[str, Any],
        args_resolved: dict[str, Any],
        validation_ok: bool,
        validation_errors: list[str] = None,
        input_files: list[str] = None,
        output_files: list[str] = None,
        exit_code: int = 0,
        plan_cmd: str = None,
        **kwargs,
    ) -> dict[str, Any]:
        """
        Record execution phase with full parameter tracing.

        Args:
            query: User query
            selected_tool: Tool that was executed
            args_raw: Raw arguments from LLM
            args_resolved: Resolved arguments after processing
            validation_ok: Whether validation passed
            validation_errors: List of validation errors if any
            input_files: List of input file paths
            output_files: List of output file paths
            exit_code: Execution exit code
            plan_cmd: Command that was planned/executed
            **kwargs: Additional fields to include

        Returns:
            Complete logged payload
        """
        record = {
            "request": {
                "query": query,
                "selected_tool": selected_tool,
            },
            "args": {
                "args_raw": args_raw,
                "args_resolved": args_resolved,
                "validation": {"ok": validation_ok, "errors": validation_errors or []},
            },
            "execution": {
                "mode": "execute",
                "exit_code": exit_code,
                "env": self.get_environment(),
            },
        }

        # Add fingerprints for input files
        if input_files:
            input_fingerprints = []
            for path in input_files:
                fp = file_fingerprint(path)
                fp["path_redacted"] = redacted_path(path)
                input_fingerprints.append(fp)
            record["request"]["input_fingerprints"] = input_fingerprints

        # Add fingerprints for output files
        if output_files:
            artifacts = []
            for path in output_files:
                fp = file_fingerprint(path)
                # Determine type from extension
                ext = os.path.splitext(path)[1].lower()
                fp["type"] = ext[1:] if ext else "unknown"
                artifacts.append(fp)
            record["execution"]["artifacts"] = artifacts

        if plan_cmd:
            record["execution"]["plan_cmd"] = plan_cmd

        # Add any additional fields
        record.update(kwargs)

        return self.finish(record, ["agent", "execution"])

    def record_review(
        self,
        query: str,
        status: str,
        checks: list[dict[str, Any]] = None,
        notes: str = None,
        **kwargs,
    ) -> dict[str, Any]:
        """
        Record review phase results.

        Args:
            query: User query
            status: Review status (PASS|FAIL|CHANGES_REQUESTED)
            checks: List of checks performed
            notes: Review notes
            **kwargs: Additional fields to include

        Returns:
            Complete logged payload
        """
        record = {"request": {"query": query}, "review": {"status": status}}

        if checks:
            record["review"]["checks"] = checks

        if notes:
            record["review"]["notes"] = notes

        # Add any additional fields
        record.update(kwargs)

        return self.finish(record, ["agent", "review"])


# Singleton instance for convenience
_default_recorder = None


def get_recorder(base_path: str | pathlib.Path | None = None) -> RunRecorder:
    """
    Get or create default recorder instance.

    Args:
        base_path: Optional base path for logs

    Returns:
        RunRecorder instance
    """
    global _default_recorder
    if _default_recorder is None:
        _default_recorder = RunRecorder(base_path=base_path)
    return _default_recorder
