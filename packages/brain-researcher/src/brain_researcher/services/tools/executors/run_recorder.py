"""RunRecorder context manager for tracking tool execution provenance.

This module provides the core RunRecorder class that captures execution metadata,
streams logs to disk, and manages state transitions with atomic writes.

Moved from: services/toolhub/common/run_recorder.py
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from brain_researcher.config.run_artifacts import (
    RecorderConfig,
    build_run_dir,
    get_recorder_config,
    run_date_str,
)
from brain_researcher.core.artifact_checksums import (
    compute_file_sha256,
    fill_artifact_checksums,
)
from brain_researcher.services.tools.executors.provenance_helpers import (
    PROVENANCE_SCHEMA_VERSION,
    get_container_fingerprint,
    get_file_fingerprint,
    get_git_metadata,
    get_inputs_fingerprints,
)
from brain_researcher.services.tools.executors.provenance_helpers import (
    get_host_metadata as get_host_metadata_helper,
)

# Schema version for provenance JSON
SCHEMA_VERSION = PROVENANCE_SCHEMA_VERSION

# Valid state transitions
VALID_TRANSITIONS = {
    "scheduled": {"running", "cancelled"},
    "running": {"succeeded", "failed", "partial", "timeout", "cancelled"},
    "succeeded": set(),
    "failed": set(),
    "partial": set(),
    "timeout": set(),
    "cancelled": set(),
}


@dataclass
class StateTransition:
    """Record of a state transition."""

    from_state: str
    to_state: str
    timestamp: float


def _atomic_write(path: Path, content: str) -> None:
    """Write content atomically using tmp file + replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def _atomic_write_json(path: Path, obj: dict[str, Any]) -> None:
    """Write JSON atomically."""
    _atomic_write(path, json.dumps(obj, ensure_ascii=False, indent=2))


def compute_container_fingerprint(path: Path) -> str:
    """Compute container fingerprint (CVMFS-safe for directories).

    For files: SHA256 hash (first 16 chars)
    For directories: Light fingerprint of top-level files (name + size)
    """
    if not path.exists():
        return "missing"

    if path.is_dir():
        # CVMFS unpacked container - light fingerprint
        try:
            files = sorted(
                (f.name, f.stat().st_size) for f in path.iterdir() if f.is_file()
            )
            fingerprint_str = str(files)
            return hashlib.sha256(fingerprint_str.encode()).hexdigest()[:16]
        except (OSError, PermissionError):
            return "error-reading-dir"
    else:
        # Regular file - compute hash
        try:
            hasher = hashlib.sha256()
            with path.open("rb") as f:
                # Read in chunks to avoid memory issues
                for chunk in iter(lambda: f.read(65536), b""):
                    hasher.update(chunk)
            return hasher.hexdigest()[:16]
        except (OSError, PermissionError):
            return "error-reading-file"


class RunRecorder:
    """Context manager for recording tool execution with streaming logs.

    Usage:
        rec = RunRecorder(run_id="abc123", resolver_mode="best_effort")
        rec.set_command(["bet", "input.nii", "output.nii"])
        rec.set_env({"FSLDIR": "/opt/fsl"})

        with rec:
            # Execute tool
            result = subprocess.run(...)
            rec.capture_output(result.stdout, result.stderr)
            rec.set_outputs([Path("output.nii")])

    Automatically handles:
    - State transitions (scheduled → running → succeeded/failed)
    - Atomic writes to disk
    - Log truncation with tail preservation
    - Provenance metadata collection
    """

    def __init__(
        self,
        run_id: str,
        resolver_mode: str,
        cfg: RecorderConfig | None = None,
        parent_run_id: str | None = None,
        step_id: str | None = None,
        attempt: int = 1,
    ):
        """Initialize RunRecorder.

        Args:
            run_id: Unique run identifier
            resolver_mode: Container resolution mode (best_effort, pinned, etc.)
            cfg: Optional config override (uses global config if None)
            parent_run_id: Parent run ID for nested recorders (optional)
            step_id: Step identifier within parent workflow (optional)
            attempt: Attempt number for re-runs (default: 1)
        """
        self.cfg = cfg or get_recorder_config()
        self.run_id = run_id
        self.resolver_mode = resolver_mode
        self.parent_run_id = parent_run_id
        self.step_id = step_id
        self.attempt = attempt

        # Create run directory path via shared layout helpers so recorder and
        # cleanup logic agree on the same date-bucket semantics.
        date_str = run_date_str()
        root_for_day = self.cfg.root / date_str
        self.run_dir = build_run_dir(
            self.cfg.root,
            run_id,
            parent_run_id=parent_run_id,
            step_id=step_id,
            attempt=attempt,
        )
        self.run_dir_relative = str(self.run_dir.relative_to(root_for_day))

        # State tracking
        self.state = "scheduled"
        self.transitions: list[StateTransition] = []
        self.started_at: float | None = None
        self.finished_at: float | None = None

        # Metadata to collect
        self.command: list[str] = []
        self.env: dict[str, str] = {}
        self.inputs: dict[str, str] = {}
        self.outputs: list[Path] = []
        self.extra_metadata: dict[str, Any] = {}

        # Child workflow tracking (for parent recorders)
        self.child_summaries: list[dict[str, Any]] = []

        # Log capture state
        self.stdout_bytes = 0
        self.stderr_bytes = 0
        self.stdout_truncated = False
        self.stderr_truncated = False
        self.stdout_tail = b""
        self.stderr_tail = b""

        # Output collection state
        self.collected_output_bytes = 0

    def set_command(self, command_tokens: list[str]) -> None:
        """Set the command being executed."""
        self.command = command_tokens

    def set_env(self, env_vars: dict[str, str]) -> None:
        """Set environment variables (will be filtered by allowlist)."""
        self.env = self._filter_env(env_vars)

    def set_inputs(self, inputs: dict[str, str]) -> None:
        """Set input files/parameters."""
        self.inputs = inputs

    def set_outputs(self, outputs: list[Path] | list[str]) -> None:
        """Set output file paths."""
        self.outputs = [Path(p) for p in outputs]

    def add_extra(self, **kwargs: Any) -> None:
        """Add extra metadata fields."""
        self.extra_metadata.update(kwargs)

    def add_child_summary(
        self,
        step_id: str,
        state: str,
        run_dir: Path | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Add a child run summary (for parent/workflow recorders).

        Args:
            step_id: Step identifier
            state: Final state of child run (succeeded, failed, etc.)
            run_dir: Optional path to child run directory (omitted if None)
            extra: Optional extra metadata about the child run
        """
        summary = {
            "step_id": step_id,
            "state": state,
        }
        # Only include run_dir if it's not None
        if run_dir is not None:
            summary["run_dir"] = str(run_dir)
        if extra:
            summary.update(extra)
        self.child_summaries.append(summary)

    def __enter__(self) -> RunRecorder:
        """Enter context: create directory and transition to running."""
        if not self.cfg.enabled:
            return self

        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.started_at = time.time()
        self._update_status("running")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context: determine final state and write provenance."""
        if not self.cfg.enabled:
            return

        self.finished_at = time.time()

        # Determine final state
        if exc_type is None:
            final_state = "succeeded"
        elif isinstance(exc_val, subprocess.TimeoutExpired):
            final_state = "timeout"
        else:
            final_state = "failed"

        self._update_status(final_state)
        self._write_command()
        self._write_provenance()

        # Collect outputs if enabled
        if self.cfg.output_enabled:
            self._collect_outputs()

    def _update_status(self, new_state: str) -> None:
        """Update state with atomic write to status.json."""
        if not self.cfg.enabled:
            return

        # Validate transition
        if new_state not in VALID_TRANSITIONS.get(self.state, set()):
            raise ValueError(f"Invalid state transition: {self.state} → {new_state}")

        # Record transition
        transition = StateTransition(
            from_state=self.state, to_state=new_state, timestamp=time.time()
        )
        self.transitions.append(transition)
        self.state = new_state

        # Write status.json atomically
        status = {
            "state": self.state,
            "started_at": self.started_at,
            "updated_at": time.time(),
            "transitions": [
                {"from": t.from_state, "to": t.to_state, "at": t.timestamp}
                for t in self.transitions
            ],
        }
        _atomic_write_json(self.run_dir / "status.json", status)

    def capture_output(self, stdout: bytes | str, stderr: bytes | str) -> None:
        """Capture stdout/stderr with streaming to disk and tail preservation.

        Args:
            stdout: Standard output (bytes or str)
            stderr: Standard error (bytes or str)
        """
        if not self.cfg.enabled:
            return

        # Convert to bytes if needed
        stdout_bytes = stdout.encode("utf-8") if isinstance(stdout, str) else stdout
        stderr_bytes = stderr.encode("utf-8") if isinstance(stderr, str) else stderr

        # Write full output to disk atomically
        _atomic_write(
            self.run_dir / "stdout.txt", stdout_bytes.decode("utf-8", errors="replace")
        )
        _atomic_write(
            self.run_dir / "stderr.txt", stderr_bytes.decode("utf-8", errors="replace")
        )

        # Track sizes and truncation
        self.stdout_bytes = len(stdout_bytes)
        self.stderr_bytes = len(stderr_bytes)

        # Preserve tail for provenance
        tail_size = min(self.cfg.max_std_bytes, 1024)  # Keep at least 1KB tail
        self.stdout_tail = stdout_bytes[-tail_size:]
        self.stderr_tail = stderr_bytes[-tail_size:]

        self.stdout_truncated = self.stdout_bytes > self.cfg.max_std_bytes
        self.stderr_truncated = self.stderr_bytes > self.cfg.max_std_bytes

    def _infer_kind(self) -> str:
        """Infer recorder kind from resolver_mode and context.

        Returns:
            Kind label: pipeline, stage, workflow, step, or tool
        """
        if self.resolver_mode == "pipeline":
            return "pipeline"
        elif self.resolver_mode == "dag_workflow":
            # If this has a parent, it's a stage within a pipeline
            return "stage" if self.parent_run_id else "workflow"
        elif self.resolver_mode == "dag_step":
            return "step"
        else:
            # direct_execution, command_generation, niwrap_tool, etc.
            return "tool"

    def _write_command(self) -> None:
        """Write command.txt atomically."""
        if not self.cfg.enabled:
            return

        command_str = " ".join(self.command) if self.command else ""
        _atomic_write(self.run_dir / "command.txt", command_str)

    def _write_provenance(self) -> None:
        """Write provenance.json with full metadata."""
        if not self.cfg.enabled:
            return

        # Contract-first output (provenance-v1) with backward-compatible extras.
        from brain_researcher.core.contracts.artifact import ArtifactKindV1, ArtifactV1
        from brain_researcher.core.contracts.ids import IdsV1
        from brain_researcher.core.contracts.provenance import (
            ProvenanceKindV1,
            ProvenanceRuntimeV1,
            ProvenanceStatusV1,
            ProvenanceTimestampsV1,
            ProvenanceV1,
        )

        job_id = self.parent_run_id or self.run_id
        ids = IdsV1(job_id=job_id, analysis_id=job_id, run_id=self.run_id)

        # Ensure log files exist even for in-process Python tools that don't
        # naturally produce stdout/stderr capture.
        stdout_path = self.run_dir / "stdout.txt"
        stderr_path = self.run_dir / "stderr.txt"
        if not stdout_path.exists():
            _atomic_write(stdout_path, "")
        if not stderr_path.exists():
            _atomic_write(stderr_path, "")

        outputs: list[ArtifactV1] = []

        def _artifact_from_local_file(
            path: Path,
            *,
            kind: ArtifactKindV1,
            media_type: str,
            uri: str,
            tags: list[str],
        ) -> ArtifactV1:
            sha256 = None
            size_bytes = None
            try:
                size_bytes = path.stat().st_size
            except OSError:
                size_bytes = None
            hexdigest, status, _reason = compute_file_sha256(path)
            if hexdigest and status == "ok":
                sha256 = f"sha256:{hexdigest}"
            return ArtifactV1(
                ids=ids,
                job_id=job_id,
                kind=kind,
                media_type=media_type,
                uri=uri,
                sha256=sha256,
                bytes=size_bytes,
                tags=tags,
            )

        # Register the primary run artifacts as typed ArtifactV1 references.
        outputs.append(
            _artifact_from_local_file(
                stdout_path,
                kind=ArtifactKindV1.log,
                media_type="text/plain",
                uri="stdout.txt",
                tags=["stdout"],
            )
        )
        outputs.append(
            _artifact_from_local_file(
                stderr_path,
                kind=ArtifactKindV1.log,
                media_type="text/plain",
                uri="stderr.txt",
                tags=["stderr"],
            )
        )
        outputs.append(
            ArtifactV1(
                ids=ids,
                job_id=job_id,
                kind=ArtifactKindV1.json,
                media_type="application/json",
                uri="provenance.json",
                tags=["provenance"],
            )
        )
        outputs.append(
            ArtifactV1(
                ids=ids,
                job_id=job_id,
                kind=ArtifactKindV1.json,
                media_type="application/json",
                uri="hash.json",
                tags=["hash"],
            )
        )

        runtime = ProvenanceRuntimeV1(host=self._get_host_metadata())
        policy_snapshot = self.extra_metadata.get("execution_policy")
        if isinstance(policy_snapshot, dict):
            runtime.sandbox = policy_snapshot

        # Add git metadata (best-effort)
        git_metadata = get_git_metadata()
        if git_metadata:
            runtime.git = git_metadata

        # Add parent/child metadata if applicable
        metadata: dict[str, Any] = {}
        if self.parent_run_id:
            metadata["parent_run_id"] = self.parent_run_id
        if self.step_id:
            metadata["step_id"] = self.step_id
        if self.child_summaries:
            metadata["child_runs"] = self.child_summaries

        # Add attempt number if > 1 (for re-runs)
        if self.attempt > 1:
            metadata["attempt"] = self.attempt

        # Add container fingerprint if container info is available
        if "container" in self.extra_metadata:
            container_info = self.extra_metadata["container"]
            if isinstance(container_info, dict) and "image" in container_info:
                image_path = container_info["image"]
                metadata["container_fingerprint"] = get_container_fingerprint(
                    image_path
                )
                runtime.container = container_info

        # Add input fingerprints (best-effort; can be disabled)
        if self.cfg.inputs_fingerprints_enabled:
            max_hash_mb = max(1, int(self.cfg.inputs_fingerprints_max_hash_mb))
            metadata["inputs_fingerprints"] = get_inputs_fingerprints(
                self.inputs, max_hash_mb=max_hash_mb
            )

            input_dataset_manifests = self._collect_input_dataset_manifests(
                max_hash_mb=max_hash_mb
            )
            if input_dataset_manifests:
                metadata["input_dataset_manifests"] = input_dataset_manifests

        # Merge planner trace if present (for P1.3 tool discovery)
        if "planner_trace" in self.extra_metadata:
            metadata["plan"] = self.extra_metadata["planner_trace"]

        # Merge canonical op trace if present (for P1.4 LPM)
        if "canonical_op" in self.extra_metadata:
            metadata["canonical_op"] = self.extra_metadata["canonical_op"]

        # Merge cache metadata if present (P2.5)
        if "cache_key" in self.extra_metadata:
            metadata["cache"] = {
                "cache_key": self.extra_metadata["cache_key"],
                "cache_hit": self.extra_metadata.get("cache_hit", False),
                "cache_mode": os.getenv("BR_CACHE_MODE", "fast"),
            }

        # Build the ProvenanceV1 contract. For compatibility with existing producers,
        # keep legacy fields under metadata or as top-level extras below.
        duration_sec = None
        if self.started_at and self.finished_at:
            duration_sec = round(self.finished_at - self.started_at, 3)

        status_map = {
            "scheduled": ProvenanceStatusV1.scheduled,
            "running": ProvenanceStatusV1.running,
            "succeeded": ProvenanceStatusV1.succeeded,
            "failed": ProvenanceStatusV1.failed,
            "partial": ProvenanceStatusV1.partial,
            "timeout": ProvenanceStatusV1.timeout,
            "cancelled": ProvenanceStatusV1.cancelled,
        }
        status = status_map.get(self.state, ProvenanceStatusV1.failed)

        prov = ProvenanceV1(
            ids=ids,
            run_id=self.run_id,
            kind=ProvenanceKindV1(self._infer_kind()),
            status=status,
            timestamps=ProvenanceTimestampsV1(
                started_at=self.started_at,
                finished_at=self.finished_at,
                duration_sec=duration_sec,
            ),
            command=list(self.command or []),
            parameters=self.inputs if isinstance(self.inputs, dict) else {},
            outputs=outputs,
            runtime=runtime,
            logs={
                "stdout_bytes": self.stdout_bytes,
                "stderr_bytes": self.stderr_bytes,
                "stdout_truncated": self.stdout_truncated,
                "stderr_truncated": self.stderr_truncated,
                "tail_bytes": len(self.stdout_tail),
            },
            metadata={
                **metadata,
                "resolver_mode": self.resolver_mode,
                "environment": self.env,
                "legacy_schema_version": SCHEMA_VERSION,
                "extra_metadata": dict(self.extra_metadata),
            },
        )

        # Compute checksums for declared outputs (best-effort; ensures status present)
        artifacts = [{"name": p.name, "path": str(p)} for p in self.outputs]
        artifacts = fill_artifact_checksums(artifacts, run_dir=self.run_dir)
        metadata_extras = prov.model_dump(exclude_none=True)
        metadata_extras["artifacts"] = artifacts

        # Backward-compatible top-level extras for existing APIs/UI:
        # - plan and child_runs are used by /plan and /steps endpoints.
        # - state/environment/host/git are legacy fields referenced in some tools.
        legacy_extras: dict[str, Any] = {
            "state": self.state,
            "environment": self.env,
            "resolver_mode": self.resolver_mode,
            "host": self._get_host_metadata(),
        }
        if git_metadata:
            legacy_extras["git"] = git_metadata
        for key in (
            "parent_run_id",
            "step_id",
            "child_runs",
            "attempt",
            "cache",
            "plan",
            "canonical_op",
            "container_fingerprint",
            "inputs_fingerprints",
            "input_dataset_manifests",
        ):
            value = (metadata or {}).get(key)
            if value is not None:
                legacy_extras[key] = value

        metadata_extras.update(legacy_extras)

        provenance_path = self.run_dir / "provenance.json"
        _atomic_write_json(provenance_path, metadata_extras)

        # Also emit a small, self-contained hash sidecar for quick integrity checks.
        # Note: We intentionally do not include hash.json itself to keep this stable.
        hash_entries: list[dict[str, Any]] = []
        for uri, path in (
            ("provenance.json", provenance_path),
            ("stdout.txt", stdout_path),
            ("stderr.txt", stderr_path),
        ):
            hexdigest, status, reason = compute_file_sha256(path)
            entry: dict[str, Any] = {"path": uri, "checksum_status": status}
            if hexdigest:
                entry["checksum"] = f"sha256:{hexdigest}"
            if reason:
                entry["checksum_reason"] = reason
            try:
                entry["bytes"] = path.stat().st_size
            except OSError:
                pass
            hash_entries.append(entry)

        _atomic_write_json(
            self.run_dir / "hash.json",
            {
                "schema_version": "hash-v1",
                "run_id": self.run_id,
                "generated_at": time.time(),
                "artifacts": hash_entries,
            },
        )

    def _collect_input_dataset_manifests(
        self, max_hash_mb: int
    ) -> list[dict[str, Any]]:
        """Collect best-effort references to input BIDS dataset manifests.

        This scans input values for paths that belong to a BIDS dataset (identified by
        dataset_description.json in an ancestor directory), then records fingerprints for
        dataset_description.json and dataset_manifest.json (if present).
        """
        results: dict[Path, dict[str, Any]] = {}

        for value in (self.inputs or {}).values():
            try:
                candidate = Path(str(value)).expanduser()
            except Exception:
                continue

            if not candidate.exists():
                continue

            start_dir = candidate if candidate.is_dir() else candidate.parent
            bids_root = self._find_bids_root(start_dir)
            if bids_root is None:
                continue

            if bids_root in results:
                continue

            entry: dict[str, Any] = {"bids_root": str(bids_root)}

            dataset_desc = bids_root / "dataset_description.json"
            if dataset_desc.is_file():
                entry["dataset_description"] = get_file_fingerprint(
                    dataset_desc, max_hash_mb=max_hash_mb
                )

            manifest_path = bids_root / "dataset_manifest.json"
            if manifest_path.is_file():
                entry["dataset_manifest"] = get_file_fingerprint(
                    manifest_path, max_hash_mb=max_hash_mb
                )
                entry["dataset_manifest_meta"] = self._read_dataset_manifest_meta(
                    manifest_path
                )

            results[bids_root] = entry

        return list(results.values())

    @staticmethod
    def _find_bids_root(start_dir: Path, max_ascend: int = 20) -> Path | None:
        """Find the nearest ancestor that looks like a BIDS dataset root."""
        cur = start_dir
        for _ in range(max_ascend):
            if (cur / "dataset_description.json").is_file():
                return cur
            if cur.parent == cur:
                break
            cur = cur.parent
        return None

    @staticmethod
    def _read_dataset_manifest_meta(manifest_path: Path) -> dict[str, Any]:
        """Read lightweight metadata from dataset_manifest.json (best-effort)."""
        max_bytes = 10 * 1024 * 1024  # avoid loading huge manifests into memory
        try:
            stat = manifest_path.stat()
            if stat.st_size > max_bytes:
                return {"status": "skipped_too_large", "size": stat.st_size}

            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            return {
                "schema_version": data.get("schema_version"),
                "manifest_sha256": data.get("manifest_sha256"),
                "summary": data.get("summary"),
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _get_host_metadata(self) -> dict[str, Any]:
        """Collect host/runtime metadata using best-effort helpers."""
        # Use provenance helper for host metadata
        return get_host_metadata_helper()

    def _filter_env(self, env_vars: dict[str, str]) -> dict[str, str]:
        """Filter environment variables by allowlist and redact patterns."""
        filtered = {}

        for key, value in env_vars.items():
            # Check allowlist
            if key not in self.cfg.env_allowlist:
                continue

            # Check redaction patterns
            should_redact = any(
                pattern in key.upper() for pattern in self.cfg.env_redact_patterns
            )

            filtered[key] = "***REDACTED***" if should_redact else value

        return filtered

    def _collect_outputs(self) -> None:
        """Collect output files with hardlink→copy and size caps."""
        if not self.cfg.output_enabled or not self.outputs:
            return

        output_dir = self.run_dir / "outputs"
        output_dir.mkdir(exist_ok=True)

        for output_path in self.outputs:
            if not output_path.exists():
                continue

            # Check extension filter (handle multi-part extensions like .nii.gz)
            # Check both single suffix and combined suffixes
            matched = False
            if output_path.suffix in self.cfg.output_extensions:
                matched = True
            else:
                # Check for multi-part extensions like .nii.gz
                combined_suffix = "".join(output_path.suffixes)
                if combined_suffix in self.cfg.output_extensions:
                    matched = True

            if not matched:
                continue

            # Check file size
            file_size = output_path.stat().st_size
            if file_size > self.cfg.output_max_per_file:
                continue

            # Check per-run cap
            if self.collected_output_bytes + file_size > self.cfg.output_max_per_run:
                break

            # Try hardlink, fallback to copy
            dest = output_dir / output_path.name
            try:
                os.link(output_path, dest)
            except (OSError, AttributeError):
                # Hardlink failed (cross-device or not supported), try copy
                try:
                    shutil.copy2(output_path, dest)
                except (OSError, shutil.Error):
                    continue

            self.collected_output_bytes += file_size


def prepare_child_summary_extra(
    child_recorder: RunRecorder | None = None,
    max_attempts: int = 1,
    outputs: list[Any] | None = None,
    retry_reason: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Prepare extra metadata for child run summaries.

    Args:
        child_recorder: Child RunRecorder instance (optional)
        max_attempts: Maximum retry attempts allowed
        outputs: List of output artifacts (optional)
        retry_reason: Reason for retry if applicable (optional)
        error: Error message if failed (optional)

    Returns:
        Dict with extra metadata fields
    """
    extra: dict[str, Any] = {}

    if child_recorder:
        extra["attempt"] = child_recorder.attempt
        extra["max_attempts"] = max_attempts
        if child_recorder.started_at and child_recorder.finished_at:
            extra["duration_sec"] = round(
                child_recorder.finished_at - child_recorder.started_at, 3
            )
    else:
        extra["attempt"] = max_attempts
        extra["max_attempts"] = max_attempts

    if outputs:
        extra["outputs"] = [str(o) for o in outputs]

    if retry_reason:
        extra["retry_reason"] = retry_reason

    if error:
        extra["error"] = error

    return extra
