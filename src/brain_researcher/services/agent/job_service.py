"""Agent-side job service with sync wrappers around async JobStore.

Provides a synchronous interface for Flask endpoints to interact with
the async JobStore backend. Uses thread pools to bridge sync/async.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from brain_researcher.core.contracts.version_ref import get_cached_version_ref_v1

logger = logging.getLogger(__name__)

_JOB_ID_ALLOWED = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
)
_TRUE_VALUES = {"1", "true", "yes", "on"}
_DEFAULT_PROJECT_ID = "default"
_DEFAULT_PROJECT_NAME = "Default"
_ANONYMOUS_PROJECT_SCOPE = "__anonymous__"
_PIPELINE_STEP_TOKEN_RE = re.compile(r"\$\{(steps\.[A-Za-z_][A-Za-z0-9_.-]*)\}")
_PIPELINE_STEP_SHORTHAND_RE = re.compile(
    r"\{([A-Za-z_][A-Za-z0-9_-]*)\.([A-Za-z0-9_.-]+)\}"
)


def _queue_backend() -> str:
    return (os.getenv("BR_QUEUE_BACKEND") or "memory").strip().lower()


def _is_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in _TRUE_VALUES


def _strict_queue_backend_required() -> bool:
    backend = _queue_backend()
    if backend not in {"sqlite", "dual"}:
        return False
    strict_env = os.getenv("BR_STRICT_SQLITE_BACKEND")
    if strict_env is not None:
        return _is_truthy(strict_env)
    runtime_env = (os.getenv("APP_ENV") or os.getenv("ENV") or "").strip().lower()
    return runtime_env in {"prod", "production"}


def _normalize_job_id(value: str) -> str:
    """Return a job id that satisfies orchestrator validation constraints.

    Orchestrator job identifiers are expected to match `^job_[a-zA-Z0-9_]+$`.
    """
    raw = value.strip()
    if not raw:
        return ""
    if raw.startswith("job_") and all(
        ch in _JOB_ID_ALLOWED for ch in raw[len("job_") :]
    ):
        return raw

    suffix = "".join(ch if ch in _JOB_ID_ALLOWED else "_" for ch in raw)
    suffix = suffix.strip("_")
    return f"job_{suffix}" if suffix else ""


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _epoch_ms() -> int:
    return int(time.time() * 1000)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _workflow_output_role(key: str, rel_path: str) -> str:
    normalized = f"{key} {rel_path}".lower()
    if "connectivity" in normalized or "matrix" in normalized:
        return "connectivity_matrix"
    if "timeseries" in normalized:
        return "timeseries"
    if "summary" in normalized:
        return "summary"
    if "atlas" in normalized:
        return "atlas"
    return "workflow_output"


def _artifact_relpath_for_output(value: Any, run_dir: Path) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", text):
        return None
    candidate = Path(text)
    if candidate.is_absolute():
        try:
            resolved = candidate.resolve()
            if not resolved.exists() or not resolved.is_file():
                return None
            return resolved.relative_to(run_dir.resolve()).as_posix()
        except Exception:
            return None
    local = run_dir / candidate
    if local.exists() and local.is_file():
        return candidate.as_posix()
    return None


def _workflow_output_artifacts(
    result_payload: dict[str, Any],
    run_dir: Path,
) -> list[dict[str, Any]]:
    data = (
        result_payload.get("data")
        if isinstance(result_payload.get("data"), dict)
        else {}
    )
    outputs = data.get("outputs") if isinstance(data.get("outputs"), dict) else {}
    artifacts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key, value in outputs.items():
        rel_path = _artifact_relpath_for_output(value, run_dir)
        if not rel_path or rel_path in seen:
            continue
        seen.add(rel_path)
        artifacts.append(
            {
                "path": rel_path,
                "name": Path(rel_path).name,
                "role": _workflow_output_role(str(key), rel_path),
                "metadata": {
                    "source": "workflow_result_outputs",
                    "output_key": str(key),
                },
            }
        )
    return artifacts


def _parse_payload_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _lookup_pipeline_value(root: dict[str, Any], dotted: str) -> Any:
    cur: Any = root
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
            continue
        raise KeyError(dotted)
    return cur


def _resolve_pipeline_shorthand(
    ctx: dict[str, Any], step_id: str, field_path: str
) -> Any:
    normalized = str(field_path or "").strip(".")
    candidates = [
        f"steps.{step_id}.data.outputs.{normalized}",
        f"steps.{step_id}.data.{normalized}",
        f"steps.{step_id}.{normalized}",
    ]
    if normalized.startswith("outputs."):
        candidates.insert(0, f"steps.{step_id}.data.{normalized}")
    if normalized.startswith(("data.", "metadata.")) or normalized in {
        "status",
        "error",
    }:
        candidates.insert(0, f"steps.{step_id}.{normalized}")

    last_error: KeyError | None = None
    for candidate in candidates:
        try:
            return _lookup_pipeline_value(ctx, candidate)
        except KeyError as exc:
            last_error = exc
    raise KeyError(f"steps.{step_id}.{normalized}") from last_error


def _interpolate_pipeline_step_params(value: Any, ctx: dict[str, Any]) -> Any:
    if isinstance(value, str):
        full_expr = re.fullmatch(r"\$\{([^}]+)\}", value)
        if full_expr and full_expr.group(1).startswith("steps."):
            return _lookup_pipeline_value(ctx, full_expr.group(1))

        full_shorthand = _PIPELINE_STEP_SHORTHAND_RE.fullmatch(value)
        if full_shorthand:
            return _resolve_pipeline_shorthand(
                ctx,
                step_id=full_shorthand.group(1),
                field_path=full_shorthand.group(2),
            )

        def _replace_step_expr(match: re.Match[str]) -> str:
            return str(_lookup_pipeline_value(ctx, match.group(1)))

        def _replace_step_shorthand(match: re.Match[str]) -> str:
            return str(
                _resolve_pipeline_shorthand(
                    ctx,
                    step_id=match.group(1),
                    field_path=match.group(2),
                )
            )

        if "${steps." in value:
            value = _PIPELINE_STEP_TOKEN_RE.sub(_replace_step_expr, value)
        if "{" in value and "}" in value:
            value = _PIPELINE_STEP_SHORTHAND_RE.sub(_replace_step_shorthand, value)
        return value
    if isinstance(value, dict):
        return {k: _interpolate_pipeline_step_params(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate_pipeline_step_params(v, ctx) for v in value]
    return value


def _extract_policy_issues_from_tool_payload(
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return out

    root_issues = payload.get("policy_issues")
    if isinstance(root_issues, list):
        out.extend([item for item in root_issues if isinstance(item, dict)])

    data = payload.get("data")
    if isinstance(data, dict):
        data_issues = data.get("policy_issues")
        if isinstance(data_issues, list):
            out.extend([item for item in data_issues if isinstance(item, dict)])

    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        metadata_issues = metadata.get("policy_issues")
        if isinstance(metadata_issues, list):
            out.extend([item for item in metadata_issues if isinstance(item, dict)])

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for issue in out:
        key = json.dumps(issue, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)
    return deduped


def _run_async(coro):
    """Run async coroutine from sync Flask context.

    Handles the case where we're in a sync context (Flask) but need
    to call async methods (JobStore).
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Already in async context - use thread pool
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        # No event loop - create new one
        return asyncio.run(coro)


class AgentJobService:
    """Sync wrapper around async JobStore for Flask endpoints.

    Provides methods to create, query, and manage runs/jobs through
    the underlying JobStore backend. All methods are synchronous to
    work with Flask's request handling.
    """

    def __init__(self):
        from brain_researcher.services.shared.job_store_factory import get_job_store
        from brain_researcher.services.shared.job_store_registry import (
            get_initialized_job_store,
            register_autoinit,
        )

        # In single-process compatibility deployments the orchestrator sets the
        # global JobStore instance during startup so the agent and orchestrator
        # share a single queue.
        register_autoinit(get_job_store)
        self._store = get_initialized_job_store()
        if (
            _queue_backend() in {"sqlite", "dual"}
            and type(self._store).__name__ == "MemoryJobStore"
        ):
            message = (
                "BR_QUEUE_BACKEND requests sqlite/dual, but AgentJobService is using "
                "MemoryJobStore (queue persistence mismatch)."
            )
            if _strict_queue_backend_required():
                logger.error("%s Refusing startup in strict mode.", message)
                raise RuntimeError(message)
            logger.warning("%s", message)
        if hasattr(self._store, "initialize"):
            try:
                _run_async(self._store.initialize())
            except Exception as exc:  # pragma: no cover - best effort for dev startup
                if _strict_queue_backend_required():
                    logger.error(
                        "JobStore.initialize failed under strict sqlite mode (backend=%s): %s",
                        _queue_backend(),
                        exc,
                    )
                    raise RuntimeError(
                        f"JobStore.initialize failed for backend={_queue_backend()}: {exc}"
                    ) from exc
                logger.warning("JobStore.initialize failed: %s", exc)
        self._lock = threading.Lock()
        self._projects_by_scope: dict[str, dict[str, dict[str, Any]]] = {}
        self._log_offsets: dict[tuple[str, str], int] = {}
        self._async_threads: dict[str, threading.Thread] = {}
        logger.info(f"AgentJobService initialized with {type(self._store).__name__}")

    @staticmethod
    def _normalize_project_id(project_id: str | None) -> str:
        return (
            str(project_id).strip()
            if isinstance(project_id, str) and project_id.strip()
            else _DEFAULT_PROJECT_ID
        )

    @staticmethod
    def _normalize_project_scope(user_id: str | None) -> str:
        if isinstance(user_id, str) and user_id.strip():
            return user_id.strip()
        return _ANONYMOUS_PROJECT_SCOPE

    @staticmethod
    def _coerce_project_description(description: str | None) -> str:
        if description is None:
            return ""
        if isinstance(description, str):
            return description
        return str(description)

    @staticmethod
    def _coerce_timestamp(value: Any, fallback: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _is_async_store_method(candidate: Any) -> bool:
        return callable(candidate) and inspect.iscoroutinefunction(candidate)

    def _default_project(
        self, user_id: str | None, now: int | None = None
    ) -> dict[str, Any]:
        timestamp = int(time.time()) if now is None else int(now)
        return {
            "project_id": _DEFAULT_PROJECT_ID,
            "name": _DEFAULT_PROJECT_NAME,
            "description": "",
            "user_id": user_id,
            "created_at": timestamp,
            "updated_at": timestamp,
        }

    def _ensure_local_default_project(
        self, user_id: str | None
    ) -> dict[str, dict[str, Any]]:
        scope = self._normalize_project_scope(user_id)
        bucket = self._projects_by_scope.setdefault(scope, {})
        if _DEFAULT_PROJECT_ID not in bucket:
            bucket[_DEFAULT_PROJECT_ID] = self._default_project(user_id)
        return bucket

    def _project_to_api_format(
        self, project: Any, user_id: str | None
    ) -> dict[str, Any]:
        if isinstance(project, dict):
            raw = dict(project)
        else:
            raw = {}
            for key in (
                "project_id",
                "name",
                "description",
                "user_id",
                "created_at",
                "updated_at",
            ):
                value = getattr(project, key, None)
                if value is not None:
                    raw[key] = value

        project_id = self._normalize_project_id(raw.get("project_id"))
        resolved_user_id = raw.get("user_id")
        if not isinstance(resolved_user_id, str) or not resolved_user_id.strip():
            resolved_user_id = user_id

        now = int(time.time())
        created_at = self._coerce_timestamp(raw.get("created_at"), now)
        updated_at = self._coerce_timestamp(raw.get("updated_at"), created_at)

        raw_name = raw.get("name")
        if isinstance(raw_name, str) and raw_name.strip():
            name = raw_name.strip()
        else:
            name = (
                _DEFAULT_PROJECT_NAME
                if project_id == _DEFAULT_PROJECT_ID
                else project_id
            )

        return {
            "project_id": project_id,
            "name": name,
            "description": self._coerce_project_description(raw.get("description")),
            "user_id": resolved_user_id,
            "created_at": created_at,
            "updated_at": updated_at,
        }

    def list_projects(self, user_id: str | None) -> list[dict[str, Any]]:
        """List projects visible to a user."""
        list_projects = getattr(self._store, "list_projects", None)
        if self._is_async_store_method(list_projects):
            records = _run_async(list_projects(user_id=user_id)) or []
            projects = [
                self._project_to_api_format(record, user_id) for record in records
            ]
            if not any(p["project_id"] == _DEFAULT_PROJECT_ID for p in projects):
                projects.insert(0, self._default_project(user_id))
            return projects

        with self._lock:
            bucket = self._ensure_local_default_project(user_id)
            projects = [
                dict(project)
                for project in sorted(
                    bucket.values(),
                    key=lambda p: (
                        p.get("project_id") != _DEFAULT_PROJECT_ID,
                        p.get("created_at", 0),
                    ),
                )
            ]
        return projects

    def get_project(
        self, user_id: str | None, project_id: str | None
    ) -> dict[str, Any] | None:
        """Return a project by id."""
        normalized_project_id = self._normalize_project_id(project_id)

        get_project = getattr(self._store, "get_project", None)
        if self._is_async_store_method(get_project):
            record = _run_async(
                get_project(project_id=normalized_project_id, user_id=user_id)
            )
            if record:
                return self._project_to_api_format(record, user_id)
            if normalized_project_id == _DEFAULT_PROJECT_ID:
                return self._default_project(user_id)
            return None

        with self._lock:
            bucket = self._ensure_local_default_project(user_id)
            project = bucket.get(normalized_project_id)
            return dict(project) if project else None

    def project_exists(self, project_id: str | None, user_id: str | None) -> bool:
        """Return True if a project exists for the given user context."""
        normalized_project_id = self._normalize_project_id(project_id)
        if normalized_project_id == _DEFAULT_PROJECT_ID:
            return True

        project_exists = getattr(self._store, "project_exists", None)
        if self._is_async_store_method(project_exists):
            return bool(
                _run_async(
                    project_exists(project_id=normalized_project_id, user_id=user_id)
                )
            )

        return (
            self.get_project(user_id=user_id, project_id=normalized_project_id)
            is not None
        )

    def create_project(
        self,
        user_id: str | None,
        project_id: str,
        name: str,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Create a new project for a user."""
        normalized_project_id = self._normalize_project_id(project_id)
        if normalized_project_id == _DEFAULT_PROJECT_ID:
            raise ValueError("project_id 'default' is reserved")

        if not isinstance(name, str) or not name.strip():
            raise ValueError("name is required")
        normalized_name = name.strip()
        normalized_description = self._coerce_project_description(description)

        create_project = getattr(self._store, "create_project", None)
        if self._is_async_store_method(create_project):
            record = _run_async(
                create_project(
                    user_id=user_id,
                    project_id=normalized_project_id,
                    name=normalized_name,
                    description=normalized_description,
                )
            )
            return self._project_to_api_format(record, user_id)

        with self._lock:
            bucket = self._ensure_local_default_project(user_id)
            if normalized_project_id in bucket:
                raise ValueError(f"Project '{normalized_project_id}' already exists")
            now = int(time.time())
            record = {
                "project_id": normalized_project_id,
                "name": normalized_name,
                "description": normalized_description,
                "user_id": user_id,
                "created_at": now,
                "updated_at": now,
            }
            bucket[normalized_project_id] = record
            return dict(record)

    def update_project(
        self,
        user_id: str | None,
        project_id: str,
        name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any] | None:
        """Update project attributes."""
        normalized_project_id = self._normalize_project_id(project_id)

        normalized_name: str | None = None
        if name is not None:
            if not isinstance(name, str) or not name.strip():
                raise ValueError("name must be a non-empty string")
            normalized_name = name.strip()

        normalized_description: str | None = None
        if description is not None:
            normalized_description = self._coerce_project_description(description)

        if normalized_name is None and normalized_description is None:
            raise ValueError("at least one field must be provided")

        update_project = getattr(self._store, "update_project", None)
        if self._is_async_store_method(update_project):
            record = _run_async(
                update_project(
                    user_id=user_id,
                    project_id=normalized_project_id,
                    name=normalized_name,
                    description=normalized_description,
                )
            )
            if not record:
                return None
            return self._project_to_api_format(record, user_id)

        with self._lock:
            bucket = self._ensure_local_default_project(user_id)
            record = bucket.get(normalized_project_id)
            if not record:
                return None
            if normalized_name is not None:
                record["name"] = normalized_name
            if normalized_description is not None:
                record["description"] = normalized_description
            record["updated_at"] = int(time.time())
            return dict(record)

    def delete_project(self, user_id: str | None, project_id: str) -> None:
        """Delete a project for a user."""
        normalized_project_id = self._normalize_project_id(project_id)
        if normalized_project_id == _DEFAULT_PROJECT_ID:
            raise ValueError("Default project cannot be deleted")

        existing_runs = self.list_runs(
            user_id=str(user_id) if isinstance(user_id, str) else "",
            limit=1,
            project_id=normalized_project_id,
        )
        if existing_runs:
            raise ValueError(
                f"Project '{normalized_project_id}' cannot be deleted because it has runs"
            )

        delete_project = getattr(self._store, "delete_project", None)
        if self._is_async_store_method(delete_project):
            deleted = _run_async(
                delete_project(user_id=user_id, project_id=normalized_project_id)
            )
            if not deleted:
                raise KeyError(normalized_project_id)
            return

        with self._lock:
            bucket = self._ensure_local_default_project(user_id)
            if normalized_project_id not in bucket:
                raise KeyError(normalized_project_id)
            del bucket[normalized_project_id]

    def create_run(
        self,
        plan: dict[str, Any],
        user_id: str,
        thread_id: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new run/job from a plan.

        Args:
            plan: The plan/workflow specification
            user_id: ID of the user creating the run
            thread_id: Optional thread/session ID for context

        Returns:
            API-formatted run dict with run_id, status, etc.
        """
        from brain_researcher.services.shared.job_models import JobRecord, JobState

        allow_override = os.getenv("BR_ALLOW_RUN_ID_OVERRIDE", "0").lower() in {
            "1",
            "true",
            "yes",
        }

        requested_id = ""
        if allow_override and isinstance(plan, dict):
            # Only allow explicit IDs for demo/test plans to avoid user-controlled
            # run_id collisions in production deployments.
            if plan.get("demo") is True or plan.get("demo_seed") is True:
                candidate = (
                    plan.get("run_id") or plan.get("analysis_id") or plan.get("job_id")
                )
                if isinstance(candidate, str) and candidate.strip():
                    requested_id = candidate.strip()

        job_id = _normalize_job_id(requested_id) if requested_id else ""
        if not job_id:
            job_id = f"job_{uuid.uuid4().hex[:12]}"

        if requested_id:
            existing = _run_async(self._store.get(job_id))
            if existing:
                logger.info(f"Run {job_id} already exists; returning existing record")
                return self._to_api_format(existing)

        effective_user_id = user_id
        if isinstance(plan, dict) and plan.get("demo_seed") is True:
            effective_user_id = None
        now = int(time.time())

        normalized_project_id = self._normalize_project_id(project_id)
        if not self.project_exists(normalized_project_id, user_id):
            raise ValueError(f"Project '{normalized_project_id}' does not exist")

        record = JobRecord(
            job_id=job_id,
            kind="plan",
            payload_json=json.dumps(plan),
            state=JobState.QUEUED,
            user_id=effective_user_id,
            session_id=thread_id,
            project_id=normalized_project_id,
            created_at=now,
            queued_at=now,
        )

        with self._lock:
            _run_async(self._store.enqueue(record))

        # If the caller explicitly asks for a forced failure (used by e2e/smoke tests),
        # mark the run as failed immediately so the UI can render the failure state
        # without requiring a background worker to pick up the job.
        force_failure = (
            isinstance(plan, dict)
            and isinstance(plan.get("parameters"), dict)
            and plan["parameters"].get("force_failure") is True
        )
        if force_failure:
            now_ts = int(time.time())
            _run_async(
                self._store.update_state(
                    job_id,
                    JobState.FAILED,
                    started_at=record.started_at or now_ts,
                    finished_at=now_ts,
                    error_message="Forced failure for test run",
                    exit_code=1,
                )
            )
            # Refresh record to return updated fields
            record = _run_async(self._store.get(job_id)) or record

        logger.info(f"Created run {job_id} for user {user_id}")
        return self._to_api_format(record)

    def create_async_tool_run(
        self,
        *,
        tool_id: str,
        params: dict[str, Any],
        user_id: str | None = None,
        thread_id: str | None = None,
        project_id: str | None = None,
        work_dir: str | None = None,
        output_dir: str | None = None,
        origin: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        from brain_researcher.services.shared.job_models import JobRecord, JobState

        normalized_project_id = self._normalize_project_id(project_id)
        if not self.project_exists(normalized_project_id, user_id):
            raise ValueError(f"Project '{normalized_project_id}' does not exist")

        job_id = (
            str(run_id).strip() if isinstance(run_id, str) and run_id.strip() else ""
        )
        if not job_id:
            job_id = f"job_{uuid.uuid4().hex[:12]}"

        existing = _run_async(self._store.get(job_id))
        if existing:
            logger.info(
                "Async tool run %s already exists; returning existing record", job_id
            )
            return self._to_api_format(existing)

        payload = {
            "execution_type": "tool",
            "tool_id": tool_id,
            "params": params,
            "work_dir": work_dir,
            "output_dir": output_dir,
            "origin": origin or "direct",
        }
        now = int(time.time())
        run_dir = self._build_execution_run_dir(job_id)
        record = JobRecord(
            job_id=job_id,
            kind="tool_execution",
            payload_json=json.dumps(payload),
            state=JobState.QUEUED,
            user_id=user_id,
            session_id=thread_id,
            project_id=normalized_project_id,
            created_at=now,
            queued_at=now,
            run_id=job_id,
            run_dir=str(run_dir),
        )

        with self._lock:
            _run_async(self._store.enqueue(record))
            self._bootstrap_execution_run_files(job_id, run_dir, payload)
            self._start_async_execution_thread(job_id)

        logger.info("Queued async tool run %s for %s", job_id, tool_id)
        return self._to_api_format(record)

    def create_async_plan_run(
        self,
        *,
        plan: dict[str, Any],
        user_id: str | None = None,
        thread_id: str | None = None,
        project_id: str | None = None,
        origin: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        from brain_researcher.services.shared.job_models import JobRecord, JobState

        normalized_project_id = self._normalize_project_id(project_id)
        if not self.project_exists(normalized_project_id, user_id):
            raise ValueError(f"Project '{normalized_project_id}' does not exist")

        job_id = (
            str(run_id).strip() if isinstance(run_id, str) and run_id.strip() else ""
        )
        if not job_id:
            job_id = f"job_{uuid.uuid4().hex[:12]}"

        existing = _run_async(self._store.get(job_id))
        if existing:
            logger.info(
                "Async plan run %s already exists; returning existing record", job_id
            )
            return self._to_api_format(existing)

        payload = {
            "execution_type": "plan",
            "plan": plan,
            "origin": origin or "direct",
        }
        now = int(time.time())
        run_dir = self._build_execution_run_dir(job_id)
        record = JobRecord(
            job_id=job_id,
            kind="plan_execution",
            payload_json=json.dumps(payload),
            state=JobState.QUEUED,
            user_id=user_id,
            session_id=thread_id,
            project_id=normalized_project_id,
            created_at=now,
            queued_at=now,
            run_id=job_id,
            run_dir=str(run_dir),
        )

        with self._lock:
            _run_async(self._store.enqueue(record))
            self._bootstrap_execution_run_files(job_id, run_dir, payload)
            self._start_async_execution_thread(job_id)

        logger.info("Queued async plan run %s", job_id)
        return self._to_api_format(record)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Get run status by ID.

        Args:
            run_id: The job/run identifier

        Returns:
            API-formatted run dict, or None if not found
        """
        record = _run_async(self._store.get(run_id))
        if not record:
            return None
        return self._to_api_format(record)

    def get_run_metrics(self, run_id: str) -> dict[str, Any] | None:
        run_record, run_dir = self._load_execution_run_record(run_id)
        if run_record is None or run_dir is None:
            return None
        return self._build_execution_metrics(run_record, run_dir)

    def get_run_bundle(self, run_id: str) -> dict[str, Any] | None:
        run_record, run_dir = self._load_execution_run_record(run_id)
        if run_record is None or run_dir is None:
            return None

        from brain_researcher.services.shared.loop_primitives import (
            build_run_bundle_payload,
        )

        bundle_payload, warnings = build_run_bundle_payload(
            run_id,
            record=run_record,
            run_dir=run_dir,
        )
        return {
            "ok": True,
            "run_id": run_id,
            "run_dir": str(run_dir),
            "bundle": bundle_payload,
            "warnings": warnings,
        }

    def get_run_scorecard(
        self,
        run_id: str,
        profile_id: str = "external_coding_v1",
    ) -> dict[str, Any] | None:
        run_record, run_dir = self._load_execution_run_record(run_id)
        if run_record is None or run_dir is None:
            return None

        from brain_researcher.services.shared.loop_primitives import (
            build_run_bundle_payload,
            build_run_scorecard,
            get_loop_profile,
        )

        _ = get_loop_profile(profile_id)
        metrics = self._build_execution_metrics(run_record, run_dir)
        bundle_payload, warnings = build_run_bundle_payload(
            run_id,
            record=run_record,
            run_dir=run_dir,
        )
        scorecard = build_run_scorecard(
            run_id,
            profile_id=profile_id,
            record=run_record,
            run_dir=run_dir,
            metrics=metrics,
            bundle_payload=bundle_payload,
            bundle_warnings=warnings,
        )
        return {
            "ok": True,
            "run_id": run_id,
            "run_dir": str(run_dir),
            "profile_id": profile_id,
            "scorecard": scorecard,
            "warnings": warnings,
        }

    def get_async_tool_status(self, run_id: str) -> dict[str, Any] | None:
        """Return legacy async tool status payload for compatibility routes."""
        record = _run_async(self._store.get(run_id))
        if record is None:
            return None

        api_record = self._to_api_format(record)
        payload = (
            api_record.get("plan") if isinstance(api_record.get("plan"), dict) else {}
        )
        run_dir = self._resolve_run_dir(run_id)
        run_record = self._load_run_record(run_dir) if run_dir is not None else {}
        steps = (
            run_record.get("steps") if isinstance(run_record.get("steps"), list) else []
        )
        first_step = steps[0] if steps and isinstance(steps[0], dict) else {}

        result_payload = (
            payload.get("result") if isinstance(payload.get("result"), dict) else None
        )
        if result_payload is None and run_dir is not None:
            result_relpath = first_step.get("result_path")
            if isinstance(result_relpath, str) and result_relpath.strip():
                try:
                    parsed = json.loads(
                        (run_dir / result_relpath).read_text(encoding="utf-8")
                    )
                except Exception:
                    parsed = None
                if isinstance(parsed, dict):
                    result_payload = parsed

        provenance_path = None
        if run_dir is not None:
            candidate = run_dir / "provenance.json"
            if candidate.exists():
                provenance_path = str(candidate)

        status = str(api_record.get("status") or "unknown")
        body: dict[str, Any] = {
            "ok": True,
            "run_id": record.job_id,
            "status": status,
            "done": status
            in {"completed", "failed", "cancelled", "timeout", "skipped"},
            "tool_id": payload.get("tool_id"),
            "params": (
                payload.get("params") if isinstance(payload.get("params"), dict) else {}
            ),
            "work_dir": first_step.get("work_dir") or payload.get("work_dir"),
            "output_dir": first_step.get("output_dir") or payload.get("output_dir"),
            "preview": bool(payload.get("preview", False)),
            "origin": payload.get("origin"),
            "created_at": record.created_at,
            "started_at": record.started_at,
            "finished_at": record.finished_at,
            "error_message": record.error_message,
            "run_dir": str(run_dir) if run_dir is not None else record.run_dir,
            "provenance_path": provenance_path,
        }
        if isinstance(result_payload, dict):
            body["result"] = result_payload
        return body

    def get_record(self, run_id: str):
        """Return the raw JobRecord for internal service use."""
        return _run_async(self._store.get(run_id))

    def list_runs(
        self,
        user_id: str,
        limit: int = 50,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List runs for a user.

        Args:
            user_id: User ID to filter by
            limit: Maximum number of runs to return

        Returns:
            List of API-formatted run dicts
        """
        normalized_project_id = (
            str(project_id).strip()
            if isinstance(project_id, str) and project_id.strip()
            else None
        )
        records = _run_async(
            self._store.list_all(
                user_id=user_id,
                limit=limit,
                project_id=normalized_project_id,
            )
        )
        return [self._to_api_format(r) for r in records]

    def cancel_run(self, run_id: str, reason: str = "User requested") -> bool:
        """Cancel a run.

        Args:
            run_id: The job/run identifier
            reason: Cancellation reason

        Returns:
            True if cancellation was requested, False otherwise
        """
        return _run_async(self._store.cancel(run_id, reason))

    def update_run_state(
        self,
        run_id: str,
        state: Any = None,
        **fields: Any,
    ) -> bool:
        """Update a JobStore-backed run record."""
        return _run_async(self._store.update_state(run_id, state, **fields))

    def append_run_log(self, run_id: str, stream: str, data: str) -> bool:
        """Best-effort append a log chunk when supported by the store."""
        append_log = getattr(self._store, "append_log", None)
        if not callable(append_log):
            return False
        payload = data.encode("utf-8", errors="replace")
        offset = 0
        iter_logs = getattr(self._store, "iter_logs", None)
        if callable(iter_logs):
            try:
                chunks = _run_async(iter_logs(run_id, 0))
                if chunks:
                    last = chunks[-1]
                    offset = int(getattr(last, "offset", 0)) + len(
                        getattr(last, "data", b"")
                    )
            except Exception:
                offset = 0
        _run_async(append_log(run_id, stream=stream, data=payload, offset=offset))
        return True

    def get_logs(self, run_id: str, start_offset: int = 0) -> list[dict[str, Any]]:
        """Get log chunks for a run.

        Args:
            run_id: The job/run identifier
            start_offset: Byte offset to start from

        Returns:
            List of log chunk dicts with stream, offset, data, created_at
        """
        chunks = _run_async(self._store.iter_logs(run_id, start_offset))
        return [
            {
                "stream": c.stream,
                "offset": c.offset,
                "data": c.data.decode("utf-8", errors="replace"),
                "created_at": c.created_at,
            }
            for c in chunks
        ]

    def _build_execution_run_dir(self, run_id: str) -> Path:
        from brain_researcher.config.run_artifacts import (
            build_run_dir,
            get_recorder_config,
        )

        return build_run_dir(get_recorder_config().root, run_id)

    def _run_record_path(self, run_dir: Path) -> Path:
        return run_dir / "run.json"

    def _initial_steps_for_payload(
        self, payload: dict[str, Any]
    ) -> list[dict[str, Any]]:
        execution_type = str(payload.get("execution_type") or "tool")
        if execution_type == "plan":
            plan = payload.get("plan")
            steps = plan.get("steps") if isinstance(plan, dict) else None
            out: list[dict[str, Any]] = []
            if isinstance(steps, list):
                for idx, step in enumerate(steps, start=1):
                    if not isinstance(step, dict):
                        continue
                    step_id = str(step.get("step_id") or f"s{idx}")
                    out.append(
                        {
                            "step_id": step_id,
                            "tool_id": step.get("tool"),
                            "params": (
                                step.get("params")
                                if isinstance(step.get("params"), dict)
                                else {}
                            ),
                            "status": "queued",
                            "work_dir": step.get("work_dir"),
                            "output_dir": step.get("output_dir"),
                            "started_at": None,
                            "finished_at": None,
                            "result_path": None,
                            "stdout_path": None,
                            "stderr_path": None,
                            "error": None,
                            "policy_issues": [],
                        }
                    )
            return out

        return [
            {
                "step_id": "s1",
                "tool_id": payload.get("tool_id"),
                "params": (
                    payload.get("params")
                    if isinstance(payload.get("params"), dict)
                    else {}
                ),
                "status": "queued",
                "work_dir": payload.get("work_dir"),
                "output_dir": payload.get("output_dir"),
                "started_at": None,
                "finished_at": None,
                "result_path": None,
                "stdout_path": None,
                "stderr_path": None,
                "error": None,
                "policy_issues": [],
            }
        ]

    def _bootstrap_execution_run_files(
        self,
        run_id: str,
        run_dir: Path,
        payload: dict[str, Any],
    ) -> None:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "logs").mkdir(parents=True, exist_ok=True)
        (run_dir / "work").mkdir(parents=True, exist_ok=True)
        (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)

        provenance = {
            "run_id": run_id,
            "mode": "agent",
            "route": "execute_async",
            "transport": "http",
            "request": payload,
        }
        run_record = {
            "run_id": run_id,
            "created_at": _utc_iso(),
            "status": "queued",
            "dry_run": False,
            "finished_at": None,
            "started_at": None,
            "error": None,
            "steps": self._initial_steps_for_payload(payload),
        }
        _write_json(run_dir / "provenance.json", provenance)
        _write_json(self._run_record_path(run_dir), run_record)

        try:
            from brain_researcher.services.agent.run_bundle import log_trace_event

            log_trace_event(
                run_dir,
                run_id=run_id,
                event_type="agent.run.queued",
                payload={"route": "execute_async"},
            )
        except Exception:
            logger.debug("Unable to append queued trace event for %s", run_id)

    def _load_run_record(self, run_dir: Path) -> dict[str, Any]:
        path = self._run_record_path(run_dir)
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _save_run_record(self, run_dir: Path, record: dict[str, Any]) -> None:
        _write_json(self._run_record_path(run_dir), record)

    def _resolve_run_dir(self, run_id: str) -> Path | None:
        record = _run_async(self._store.get(run_id))
        if record and isinstance(record.run_dir, str) and record.run_dir.strip():
            return Path(record.run_dir)
        candidate = self._build_execution_run_dir(run_id)
        if candidate.exists():
            return candidate
        return None

    def _load_execution_run_record(
        self, run_id: str
    ) -> tuple[dict[str, Any] | None, Path | None]:
        run_dir = self._resolve_run_dir(run_id)
        if run_dir is None:
            return None, None
        run_record = self._load_run_record(run_dir)
        if not run_record:
            return None, None
        return run_record, run_dir

    def _append_log(self, job_id: str, message: str, *, stream: str = "stdout") -> None:
        append_log = getattr(self._store, "append_log", None)
        if not callable(append_log):
            return
        key = (job_id, stream)
        offset = self._log_offsets.get(key, 0)
        data = (message.rstrip("\n") + "\n").encode("utf-8")
        try:
            _run_async(append_log(job_id, stream, data, offset))
            self._log_offsets[key] = offset + len(data)
        except Exception:
            logger.debug("Failed to append %s log chunk for %s", stream, job_id)

    def _start_async_execution_thread(self, job_id: str) -> None:
        thread = threading.Thread(
            target=self._execute_async_run,
            args=(job_id,),
            name=f"agent-async-run-{job_id}",
            daemon=True,
        )
        self._async_threads[job_id] = thread
        thread.start()

    def _execute_async_run(self, job_id: str) -> None:
        from brain_researcher.services.agent.run_bundle import (
            log_trace_event,
            persist_agent_analysis_bundle,
            persist_agent_observation,
        )
        from brain_researcher.services.shared.job_models import JobState
        from brain_researcher.services.tools.executor import execute_tool

        record = _run_async(self._store.get(job_id))
        if not record:
            return
        payload = _parse_payload_json(record.payload_json)
        run_dir = Path(record.run_dir or self._build_execution_run_dir(job_id))
        run_record = self._load_run_record(run_dir)
        if not run_record:
            self._bootstrap_execution_run_files(job_id, run_dir, payload)
            run_record = self._load_run_record(run_dir)

        now = int(time.time())
        _run_async(
            self._store.update_state(
                job_id,
                JobState.RUNNING,
                started_at=now,
                run_id=job_id,
                run_dir=str(run_dir),
            )
        )
        run_record["status"] = "running"
        run_record["started_at"] = _utc_iso()
        self._save_run_record(run_dir, run_record)
        self._append_log(job_id, f"Starting async execution for {job_id}")
        log_trace_event(
            run_dir,
            run_id=job_id,
            event_type="agent.run.started",
            payload={"execution_type": payload.get("execution_type")},
        )

        provenance = {
            "run_id": job_id,
            "mode": "agent",
            "route": "execute_async",
            "transport": "http",
            "capture_mode": "best_effort",
            "request": payload,
            "versions": get_cached_version_ref_v1().model_dump(exclude_none=True),
        }

        final_error: str | None = None
        tool_calls: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []

        try:
            steps = (
                run_record.get("steps")
                if isinstance(run_record.get("steps"), list)
                else []
            )
            step_ctx: dict[str, Any] = {"steps": {}}
            for idx, step in enumerate(steps, start=1):
                if not isinstance(step, dict):
                    continue
                step_id = str(step.get("step_id") or f"s{idx}")
                tool_id = str(step.get("tool_id") or "").strip()
                raw_params = (
                    step.get("params") if isinstance(step.get("params"), dict) else {}
                )
                resolved_params = _interpolate_pipeline_step_params(
                    raw_params, step_ctx
                )
                work_dir = str(
                    step.get("work_dir")
                    or (run_dir / "work" / f"step-{idx:02d}-{step_id}")
                )
                output_dir = str(
                    step.get("output_dir")
                    or (run_dir / "artifacts" / f"step-{idx:02d}-{step_id}")
                )
                Path(work_dir).mkdir(parents=True, exist_ok=True)
                Path(output_dir).mkdir(parents=True, exist_ok=True)

                step["status"] = "running"
                step["started_at"] = _utc_iso()
                step["work_dir"] = work_dir
                step["output_dir"] = output_dir
                self._save_run_record(run_dir, run_record)
                self._append_log(job_id, f"[{step_id}] Executing {tool_id}")
                log_trace_event(
                    run_dir,
                    run_id=job_id,
                    event_type="agent.step.started",
                    payload={"step_id": step_id, "tool_id": tool_id},
                )

                result_payload = execute_tool(
                    tool_id,
                    resolved_params,
                    work_dir=work_dir,
                    output_dir=output_dir,
                    preview=False,
                ).model_dump()

                result_relpath = (
                    Path("artifacts") / f"step-{idx:02d}-{step_id}" / "result.json"
                )
                _write_json(run_dir / result_relpath, result_payload)
                policy_issues = _extract_policy_issues_from_tool_payload(result_payload)
                step["finished_at"] = _utc_iso()
                step["result_path"] = str(result_relpath)
                step["policy_issues"] = policy_issues

                if result_payload.get("status") == "success":
                    step["status"] = "succeeded"
                    self._append_log(job_id, f"[{step_id}] Completed {tool_id}")
                    data = (
                        result_payload.get("data")
                        if isinstance(result_payload.get("data"), dict)
                        else {}
                    )
                    workflow_provenance = (
                        data.get("provenance")
                        if isinstance(data.get("provenance"), dict)
                        else None
                    )
                    if workflow_provenance:
                        provenance.setdefault("workflow_provenance", []).append(
                            {
                                "step_id": step_id,
                                "tool_id": tool_id,
                                **workflow_provenance,
                            }
                        )
                else:
                    final_error = str(result_payload.get("error") or "tool_failed")
                    step["status"] = "failed"
                    step["error"] = final_error
                    run_record["status"] = "failed"
                    run_record["error"] = final_error
                    self._append_log(
                        job_id,
                        f"[{step_id}] Failed {tool_id}: {final_error}",
                        stream="stderr",
                    )

                step_ctx["steps"][step_id] = result_payload
                tool_calls.append(
                    {
                        "tool_call_id": step_id,
                        "name": tool_id,
                        "arguments": resolved_params,
                        "status": step["status"],
                        "result": (
                            result_payload
                            if result_payload.get("status") == "success"
                            else None
                        ),
                        "error": step.get("error"),
                        "work_dir": work_dir,
                        "output_dir": output_dir,
                        "started_at": step.get("started_at"),
                        "finished_at": step.get("finished_at"),
                    }
                )
                artifacts.append(
                    {
                        "path": str(result_relpath),
                        "name": str(result_relpath),
                        "role": "artifact",
                    }
                )
                artifacts.extend(_workflow_output_artifacts(result_payload, run_dir))
                self._save_run_record(run_dir, run_record)
                log_trace_event(
                    run_dir,
                    run_id=job_id,
                    event_type="agent.step.finished",
                    payload={
                        "step_id": step_id,
                        "tool_id": tool_id,
                        "status": step["status"],
                        "error": step.get("error"),
                    },
                )
                if final_error:
                    break

            if not final_error:
                run_record["status"] = "succeeded"
            run_record["finished_at"] = _utc_iso()
            self._save_run_record(run_dir, run_record)

            final_state = JobState.SUCCEEDED if not final_error else JobState.FAILED
            _run_async(
                self._store.update_state(
                    job_id,
                    final_state,
                    finished_at=int(time.time()),
                    error_message=final_error,
                    exit_code=0 if not final_error else 1,
                    run_id=job_id,
                    run_dir=str(run_dir),
                )
            )
            log_trace_event(
                run_dir,
                run_id=job_id,
                event_type="agent.run.finished",
                payload={"status": run_record["status"], "error": final_error},
            )
            _write_json(run_dir / "provenance.json", provenance)

            run_card = {
                "id": job_id,
                "run_id": job_id,
                "execution": {
                    "provider": "agent",
                    "tool_mode": "direct",
                    "route": "execute_async",
                    "transport": "http",
                    "selected_tool": (
                        tool_calls[0]["name"] if len(tool_calls) == 1 else None
                    ),
                },
                "provenance": {"run_dir": str(run_dir)},
            }
            persist_agent_observation(
                run_dir,
                job_id=job_id,
                run_id=job_id,
                state=run_record["status"],
                run_card=run_card,
                provenance=provenance,
                tool_calls=tool_calls,
                artifacts=artifacts,
                violations=[
                    issue
                    for step in run_record.get("steps", [])
                    if isinstance(step, dict)
                    for issue in (step.get("policy_issues") or [])
                    if isinstance(issue, dict)
                ],
                created_at_ms=_epoch_ms(),
                started_at_ms=_epoch_ms(),
                finished_at_ms=_epoch_ms(),
            )
            persist_agent_analysis_bundle(
                run_dir,
                job_id=job_id,
                run_id=job_id,
                state=run_record["status"],
                run_card=run_card,
                provenance=provenance,
                policy={"dry_run": False},
            )
        except Exception as exc:
            logger.exception("Async execution failed for %s", job_id)
            final_error = str(exc)
            run_record["status"] = "failed"
            run_record["error"] = final_error
            run_record["finished_at"] = _utc_iso()
            self._save_run_record(run_dir, run_record)
            self._append_log(
                job_id, f"Execution failed: {final_error}", stream="stderr"
            )
            _run_async(
                self._store.update_state(
                    job_id,
                    JobState.FAILED,
                    finished_at=int(time.time()),
                    error_message=final_error,
                    exit_code=1,
                    run_id=job_id,
                    run_dir=str(run_dir),
                )
            )
        finally:
            self._async_threads.pop(job_id, None)

    def _build_execution_metrics(
        self, record: dict[str, Any], run_dir: Path
    ) -> dict[str, Any]:
        totals: dict[str, Any] = {
            "steps": len(record.get("steps") or []),
            "succeeded": 0,
            "failed": 0,
            "skipped": 0,
            "execution_time_s_sum": 0.0,
            "tokens_sum": 0,
            "cost_usd_sum": 0.0,
        }
        steps_out: list[dict[str, Any]] = []

        for step in record.get("steps") or []:
            if not isinstance(step, dict):
                continue
            started_at = step.get("started_at")
            finished_at = step.get("finished_at")
            duration_s = None
            try:
                if isinstance(started_at, str) and isinstance(finished_at, str):
                    st = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                    ft = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
                    duration_s = (ft - st).total_seconds()
            except Exception:
                duration_s = None

            result_payload: dict[str, Any] = {}
            result_path = step.get("result_path")
            if isinstance(result_path, str) and result_path.strip():
                try:
                    result_payload = json.loads(
                        (run_dir / result_path).read_text(encoding="utf-8")
                    )
                except Exception:
                    result_payload = {}

            data = (
                result_payload.get("data")
                if isinstance(result_payload.get("data"), dict)
                else {}
            )
            metadata = (
                result_payload.get("metadata")
                if isinstance(result_payload.get("metadata"), dict)
                else {}
            )
            execution_time = (
                data.get("execution_time")
                or data.get("execution_time_s")
                or metadata.get("execution_time")
                or metadata.get("execution_time_s")
            )
            tokens = metadata.get("tokens") or metadata.get("total_tokens")
            cost_usd = metadata.get("cost_usd") or metadata.get("estimated_usd")

            status = str(step.get("status") or "")
            if status == "succeeded":
                totals["succeeded"] += 1
            elif status == "failed":
                totals["failed"] += 1
            elif status == "skipped":
                totals["skipped"] += 1
            if isinstance(execution_time, int | float):
                totals["execution_time_s_sum"] += float(execution_time)
            if isinstance(tokens, int | float):
                totals["tokens_sum"] += int(tokens)
            if isinstance(cost_usd, int | float):
                totals["cost_usd_sum"] += float(cost_usd)

            steps_out.append(
                {
                    "step_id": step.get("step_id"),
                    "tool_id": step.get("tool_id"),
                    "status": status or "unknown",
                    "duration_s": duration_s,
                    "execution_time_s": execution_time,
                    "tokens": tokens,
                    "cost_usd": cost_usd,
                    "error": step.get("error"),
                }
            )

        duration_s = None
        try:
            created = record.get("created_at")
            finished = record.get("finished_at")
            if isinstance(created, str) and isinstance(finished, str):
                st = datetime.fromisoformat(created.replace("Z", "+00:00"))
                ft = datetime.fromisoformat(finished.replace("Z", "+00:00"))
                duration_s = (ft - st).total_seconds()
        except Exception:
            duration_s = None

        return {
            "duration_s": duration_s,
            "totals": totals,
            "steps": steps_out,
        }

    def get_queue_stats(self) -> dict[str, Any]:
        """Return lightweight queue statistics for health/status endpoints.

        Falls back gracefully if the underlying JobStore does not implement
        ``get_queue_stats`` (should not happen for current stores).
        """
        if not hasattr(self._store, "get_queue_stats"):
            return {}
        try:
            return _run_async(self._store.get_queue_stats())
        except Exception as exc:  # pragma: no cover - best effort for health path
            logger.warning("JobStore.get_queue_stats failed: %s", exc)
            return {}

    @staticmethod
    def _derive_run_source(record) -> str:
        """Classify a run as ``internal`` (Studio) or ``external`` (outside agent).

        The Runs drawer renders a "Studio" badge for internal runs and an
        "External agent" badge for external ones.

        Product decision (2026-06-01): the runs shown in the Runs drawer are the
        user's OWN runs, so treat them as ``internal`` ("Studio") UNLESS they
        carry an explicit marker that they were submitted from OUTSIDE Studio (a
        headless agent / API / MCP pipeline). This deliberately covers BOTH the
        Studio workflow runs (kind ``plan``) AND the in-app plan-execute /
        agent-assisted runs (payload ``type``/``job_kind`` of ``agent_tool`` /
        ``plan_execution``) — all of which the user initiated inside Studio.

        Only the explicit external origins below map to ``external``. Note
        ``direct`` is the ``create_run`` default (Studio sync) and is NOT
        external. Anything without an external marker -> ``internal``.
        """
        external_origins = {
            "mcp_pipeline_execute",
            "api_tools_run",
            "tools_run_compat",
            "external",
        }
        origin = ""
        payload_json = getattr(record, "payload_json", None)
        if payload_json:
            try:
                payload = json.loads(payload_json)
            except (ValueError, TypeError):
                payload = None
            if isinstance(payload, dict):
                origin = str(payload.get("origin") or "").strip().lower()
                # plan-execute / agent runs may nest the origin under metadata.
                if not origin and isinstance(payload.get("metadata"), dict):
                    origin = (
                        str(payload["metadata"].get("origin") or "").strip().lower()
                    )
        if origin in external_origins:
            return "external"
        return "internal"

    def _to_api_format(self, record) -> dict[str, Any]:
        """Convert JobRecord to API response format.

        Args:
            record: JobRecord from JobStore

        Returns:
            Dict suitable for JSON API response
        """
        from brain_researcher.services.shared.job_models import JobState

        # Map JobState to simple status strings
        status_map = {
            JobState.PENDING: "pending",
            JobState.QUEUED: "queued",
            JobState.CLAIMED: "running",
            JobState.RUNNING: "running",
            JobState.SUCCEEDED: "completed",
            JobState.FAILED: "failed",
            JobState.CANCELLED: "cancelled",
            JobState.TIMEOUT: "timeout",
            JobState.CANCELLING: "cancelling",
            JobState.SKIPPED: "skipped",
            JobState.PAUSED: "paused",
            JobState.RETRYING: "retrying",
        }

        # Calculate progress (0.0-1.0) based on state
        progress_map = {
            "pending": 0.0,
            "queued": 0.0,
            "running": 0.5,
            "completed": 1.0,
            "failed": 1.0,
            "cancelled": 1.0,
            "timeout": 1.0,
            "skipped": 1.0,
        }

        status = status_map.get(record.state, "unknown")

        return {
            "run_id": record.job_id,
            "status": status,
            "source": self._derive_run_source(record),
            "progress": progress_map.get(status, 0.0),
            "plan": json.loads(record.payload_json) if record.payload_json else {},
            "run_dir": record.run_dir,
            "user_id": record.user_id,
            "thread_id": record.session_id,
            "project_id": record.project_id or "default",
            "created_at": record.created_at,
            "started_at": record.started_at,
            "finished_at": record.finished_at,
            "error_message": record.error_message,
        }


# Singleton instance
_job_service: AgentJobService | None = None
_job_service_lock = threading.Lock()


def get_job_service() -> AgentJobService:
    """Get singleton AgentJobService instance.

    Returns:
        The global AgentJobService instance
    """
    global _job_service
    if _job_service is None:
        with _job_service_lock:
            if _job_service is None:
                _job_service = AgentJobService()
    return _job_service


def _should_eager_initialize_job_service() -> bool:
    override = os.getenv("BR_AGENT_EAGER_JOB_SERVICE_INIT")
    if override is not None:
        return _is_truthy(override)
    return False


def maybe_initialize_job_service_for_startup() -> bool:
    """Eagerly initialize the singleton JobService when configured.

    This makes queue/backend issues visible during service startup instead of
    waiting for the first async run request.
    """

    if not _should_eager_initialize_job_service():
        logger.info(
            "Agent JobService eager startup init disabled (backend=%s)",
            _queue_backend(),
        )
        return False

    service = get_job_service()
    logger.info(
        "Agent JobService eager startup init complete: backend=%s store=%s",
        _queue_backend(),
        type(service._store).__name__,
    )
    return True
