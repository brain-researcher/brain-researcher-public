"""BR-owned adapter around the upstream TaskBeacon MCP server.

The upstream ``taskbeacon-mcp`` server is useful for TaskBeacon catalog,
download, build, and localization operations. BR still owns workspace path
safety, hosted runtime patches, provenance, and QA/sim execution.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anyio
import httpx

from brain_researcher.services.orchestrator.taskbeacon_handoff import (
    apply_taskbeacon_runtime_patches,
    materialize_taskbeacon_repo,
    normalize_taskbeacon_ref,
    normalize_taskbeacon_repo,
    resolve_taskbeacon_target_path,
    taskbeacon_repo_name,
)

_DEFAULT_TASKBEACON_MCP_COMMAND = "taskbeacon-mcp"
_REPO_RE = re.compile(r"\bTaskBeacon/[A-Za-z0-9][A-Za-z0-9._-]{0,199}\b")
_TASK_REPO_NAME_RE = re.compile(r"^[HT]\d{6}-[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
_PATH_KEYS = ("template_path", "task_path", "local_path", "path", "repo_path")
_REPO_ROOT = Path(__file__).resolve().parents[4]
_TASKBEACON_GITHUB_ORG = (
    (os.getenv("BR_TASKBEACON_GITHUB_ORG") or "TaskBeacon").strip() or "TaskBeacon"
)
_TASKBEACON_GITHUB_REPOS_URL = (
    f"https://github.com/orgs/{_TASKBEACON_GITHUB_ORG}/repositories?type=all"
)
_TASKBEACON_GITHUB_TIMEOUT_SECONDS = float(
    os.getenv("BR_TASKBEACON_GITHUB_TIMEOUT_SECONDS", "20")
)
_TASKBEACON_GITHUB_CACHE_TTL_SECONDS = float(
    os.getenv("BR_TASKBEACON_GITHUB_CACHE_TTL_SECONDS", "600")
)
_taskbeacon_github_repo_cache: tuple[float, list[dict[str, Any]]] | None = None
_TASKBEACON_REPO_HREF_RE = re.compile(
    rf'href="/{re.escape(_TASKBEACON_GITHUB_ORG)}/([A-Za-z0-9][A-Za-z0-9._-]{{0,199}})"'
)


class TaskBeaconMCPError(RuntimeError):
    """Raised when the upstream TaskBeacon MCP server cannot satisfy a call."""


def _taskbeacon_mcp_command_parts() -> list[str]:
    raw = (os.getenv("BR_TASKBEACON_MCP_COMMAND") or _DEFAULT_TASKBEACON_MCP_COMMAND).strip()
    return shlex.split(raw) or [_DEFAULT_TASKBEACON_MCP_COMMAND]


@dataclass(frozen=True)
class TaskBeaconMCPConfig:
    """Runtime configuration for the upstream TaskBeacon MCP stdio server."""

    command: str = field(
        default_factory=lambda: _taskbeacon_mcp_command_parts()[0]
    )
    args: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            shlex.split(os.getenv("BR_TASKBEACON_MCP_ARGS") or "")
            or _taskbeacon_mcp_command_parts()[1:]
        )
    )
    cwd: str | None = None
    timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv("BR_TASKBEACON_MCP_TIMEOUT_SECONDS", "90"))
    )

    def command_vector(self) -> list[str]:
        return [self.command, *self.args]


@dataclass(frozen=True)
class TaskBeaconMCPCallResult:
    """Normalized result from one upstream TaskBeacon MCP tool call."""

    tool: str
    ok: bool
    structured: Any
    text: str
    raw: dict[str, Any]
    error: str | None = None


def _json_from_text(text: str) -> Any:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


def _result_content_text(raw: dict[str, Any]) -> str:
    chunks: list[str] = []
    for item in raw.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "\n".join(chunks).strip()


def _structured_payload(raw: dict[str, Any], text: str) -> Any:
    for key in ("structuredContent", "structured_content"):
        if key in raw:
            return raw[key]
    parsed = _json_from_text(text)
    return parsed if parsed is not None else None


async def _call_taskbeacon_mcp_tool_async(
    tool: str,
    arguments: dict[str, Any] | None,
    *,
    config: TaskBeaconMCPConfig,
) -> TaskBeaconMCPCallResult:
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except Exception as exc:  # pragma: no cover - import exercised by env
        raise TaskBeaconMCPError(
            "The Python 'mcp' package is required for TaskBeacon MCP calls. "
            "Install BR with 'pip install -e .[behavior-task]'."
        ) from exc

    params = StdioServerParameters(
        command=config.command,
        args=list(config.args),
        cwd=config.cwd,
    )
    try:
        with anyio.fail_after(config.timeout_seconds):
            async with stdio_client(params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(tool, arguments or {})
    except FileNotFoundError as exc:
        raise TaskBeaconMCPError(
            f"TaskBeacon MCP command not found: {config.command!r}. "
            "Install the behavior-task extra or set BR_TASKBEACON_MCP_COMMAND."
        ) from exc
    except TimeoutError as exc:
        raise TaskBeaconMCPError(
            f"TaskBeacon MCP tool {tool!r} timed out after {config.timeout_seconds}s."
        ) from exc
    except Exception as exc:
        raise TaskBeaconMCPError(f"TaskBeacon MCP tool {tool!r} failed: {exc}") from exc

    raw = result.model_dump(mode="json") if hasattr(result, "model_dump") else {}
    text = _result_content_text(raw)
    structured = _structured_payload(raw, text)
    is_error = bool(raw.get("isError"))
    return TaskBeaconMCPCallResult(
        tool=tool,
        ok=not is_error,
        structured=structured,
        text=text,
        raw=raw,
        error=text if is_error else None,
    )


def call_taskbeacon_mcp_tool(
    tool: str,
    arguments: dict[str, Any] | None = None,
    *,
    config: TaskBeaconMCPConfig | None = None,
) -> TaskBeaconMCPCallResult:
    """Call one upstream TaskBeacon MCP tool over stdio."""

    async def _runner() -> TaskBeaconMCPCallResult:
        return await _call_taskbeacon_mcp_tool_async(
            tool,
            arguments or {},
            config=config or TaskBeaconMCPConfig(),
        )

    return anyio.run(_runner)


async def async_call_taskbeacon_mcp_tool(
    tool: str,
    arguments: dict[str, Any] | None = None,
    *,
    config: TaskBeaconMCPConfig | None = None,
) -> TaskBeaconMCPCallResult:
    """Async variant for FastAPI routes already running inside an event loop."""

    return await _call_taskbeacon_mcp_tool_async(
        tool,
        arguments or {},
        config=config or TaskBeaconMCPConfig(),
    )


def _coerce_task_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        for key in ("tasks", "items", "data", "result"):
            rows = _coerce_task_rows(payload.get(key))
            if rows:
                return rows
        repo = payload.get("repo")
        return [payload] if isinstance(repo, str) else []
    if isinstance(payload, list):
        rows: list[dict[str, Any]] = []
        for item in payload:
            if isinstance(item, dict):
                repo = item.get("repo") or item.get("name")
                if isinstance(repo, str) and repo.strip():
                    rows.append(item)
            elif isinstance(item, str) and item.strip():
                rows.append({"repo": item.strip()})
        return rows
    return []


def _repos_from_text(text: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for match in _REPO_RE.finditer(text):
        repo = normalize_taskbeacon_repo(match.group(0))
        if repo and repo not in seen:
            rows.append({"repo": repo})
            seen.add(repo)
    return rows


def _filter_task_rows(
    rows: list[dict[str, Any]],
    *,
    query: str | None,
    limit: int | None,
) -> list[dict[str, Any]]:
    normalized_query = (query or "").strip().lower()
    if normalized_query:
        rows = [
            row
            for row in rows
            if normalized_query
            in " ".join(str(v) for v in row.values() if v is not None).lower()
        ]
    if limit is not None:
        rows = rows[: max(0, int(limit))]
    return rows


def _taskbeacon_github_headers() -> dict[str, str]:
    headers = {
        "Accept": "text/html,application/xhtml+xml",
        "User-Agent": "brain-researcher-taskbeacon-adapter",
    }
    token = (os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _clone_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _get_cached_taskbeacon_repo_rows() -> list[dict[str, Any]] | None:
    global _taskbeacon_github_repo_cache
    cached = _taskbeacon_github_repo_cache
    if cached is None:
        return None
    cached_at, rows = cached
    if time.time() - cached_at > _TASKBEACON_GITHUB_CACHE_TTL_SECONDS:
        _taskbeacon_github_repo_cache = None
        return None
    return _clone_rows(rows)


def _set_cached_taskbeacon_repo_rows(rows: list[dict[str, Any]]) -> None:
    global _taskbeacon_github_repo_cache
    _taskbeacon_github_repo_cache = (time.time(), _clone_rows(rows))


def _normalize_taskbeacon_repo_name(name: str) -> dict[str, Any] | None:
    repo = normalize_taskbeacon_repo(f"{_TASKBEACON_GITHUB_ORG}/{name}")
    if repo is None:
        return None
    repo_name = taskbeacon_repo_name(repo)
    if not _TASK_REPO_NAME_RE.match(repo_name):
        return None
    return {"repo": repo}


def _list_taskbeacon_tasks_via_github_sync() -> list[dict[str, Any]]:
    cached = _get_cached_taskbeacon_repo_rows()
    if cached is not None:
        return cached

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    with httpx.Client(
        timeout=_TASKBEACON_GITHUB_TIMEOUT_SECONDS,
        headers=_taskbeacon_github_headers(),
    ) as client:
        for page in range(1, 11):
            response = client.get(
                _TASKBEACON_GITHUB_REPOS_URL,
                params={"page": page},
            )
            response.raise_for_status()
            html = response.text
            page_rows: list[dict[str, Any]] = []
            for match in _TASKBEACON_REPO_HREF_RE.finditer(html):
                row = _normalize_taskbeacon_repo_name(match.group(1))
                if row is None:
                    continue
                repo = str(row["repo"])
                if repo in seen:
                    continue
                rows.append(row)
                page_rows.append(row)
                seen.add(repo)
            if not page_rows:
                break

    _set_cached_taskbeacon_repo_rows(rows)
    return _clone_rows(rows)


def list_taskbeacon_tasks(
    *,
    query: str | None = None,
    limit: int | None = None,
    config: TaskBeaconMCPConfig | None = None,
    caller=call_taskbeacon_mcp_tool,
) -> dict[str, Any]:
    """List TaskBeacon tasks via GitHub HTML, falling back to upstream MCP."""

    github_error: str | None = None
    try:
        rows = _filter_task_rows(
            _list_taskbeacon_tasks_via_github_sync(),
            query=query,
            limit=limit,
        )
    except Exception as exc:
        github_error = str(exc)
    else:
        return {
            "status": "success",
            "source": "taskbeacon_github_html",
            "count": len(rows),
            "tasks": rows,
            "raw": None,
        }

    result = caller("list_tasks", {}, config=config or TaskBeaconMCPConfig())
    if not result.ok:
        detail = result.error or "TaskBeacon MCP list_tasks failed"
        if github_error:
            detail = f"GitHub HTML listing failed: {github_error}; {detail}"
        raise TaskBeaconMCPError(detail)

    rows = _coerce_task_rows(result.structured) or _repos_from_text(result.text)
    rows = _filter_task_rows(rows, query=query, limit=limit)
    payload = {
        "status": "success",
        "source": "taskbeacon_mcp",
        "count": len(rows),
        "tasks": rows,
        "raw": result.raw,
    }
    if github_error:
        payload["github_error"] = github_error
    return payload


async def async_list_taskbeacon_tasks(
    *,
    query: str | None = None,
    limit: int | None = None,
    config: TaskBeaconMCPConfig | None = None,
) -> dict[str, Any]:
    """Async TaskBeacon task listing for FastAPI routes."""

    github_error: str | None = None
    try:
        rows = _filter_task_rows(
            await anyio.to_thread.run_sync(_list_taskbeacon_tasks_via_github_sync),
            query=query,
            limit=limit,
        )
    except Exception as exc:
        github_error = str(exc)
    else:
        return {
            "status": "success",
            "source": "taskbeacon_github_html",
            "count": len(rows),
            "tasks": rows,
            "raw": None,
        }

    result = await async_call_taskbeacon_mcp_tool(
        "list_tasks",
        {},
        config=config or TaskBeaconMCPConfig(),
    )
    if not result.ok:
        detail = result.error or "TaskBeacon MCP list_tasks failed"
        if github_error:
            detail = f"GitHub HTML listing failed: {github_error}; {detail}"
        raise TaskBeaconMCPError(detail)

    rows = _coerce_task_rows(result.structured) or _repos_from_text(result.text)
    rows = _filter_task_rows(rows, query=query, limit=limit)
    payload = {
        "status": "success",
        "source": "taskbeacon_mcp",
        "count": len(rows),
        "tasks": rows,
        "raw": result.raw,
    }
    if github_error:
        payload["github_error"] = github_error
    return payload


def _extract_download_path(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in _PATH_KEYS:
            raw = value.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
        for child in value.values():
            found = _extract_download_path(child)
            if found:
                return found
    if isinstance(value, list):
        for child in value:
            found = _extract_download_path(child)
            if found:
                return found
    if isinstance(value, str):
        for line in value.splitlines():
            text = line.strip()
            if text and ("/" in text or "\\" in text):
                return text
    return None


def _find_downloaded_repo(tmp_dir: Path, repo: str) -> Path | None:
    repo_name = taskbeacon_repo_name(repo)
    candidates = [
        tmp_dir / repo_name,
        tmp_dir / "tasks" / repo_name,
        tmp_dir / "TaskBeacon" / repo_name,
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate
    for candidate in tmp_dir.rglob(repo_name):
        if candidate.is_dir():
            return candidate
    return None


def _copy_downloaded_repo(source_dir: Path, target_dir: Path) -> None:
    if target_dir.exists():
        if target_dir.is_file():
            raise ValueError(f"TaskBeacon target path points to a file: {target_dir}")
        if any(target_dir.iterdir()):
            return
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, target_dir, dirs_exist_ok=True)


def _is_under_root(path: Path, root: Path) -> bool:
    try:
        resolved = path.resolve()
        resolved_root = root.resolve()
        return resolved == resolved_root or resolved.is_relative_to(resolved_root)
    except Exception:
        return False


def download_taskbeacon_task(
    *,
    workspace_root: str | Path,
    repo: str,
    target_path: str,
    ref: str | None = None,
    prefer_mcp: bool = True,
    config: TaskBeaconMCPConfig | None = None,
    caller=call_taskbeacon_mcp_tool,
) -> dict[str, Any]:
    """Download a TaskBeacon task into a BR workspace.

    The preferred path asks upstream ``taskbeacon-mcp`` to download the repo into
    a temporary directory, then BR copies it into the requested workspace path
    and applies hosted runtime overlays. If MCP is unavailable, BR falls back to
    the existing direct GitHub materializer.
    """

    normalized_repo = normalize_taskbeacon_repo(repo)
    if normalized_repo is None:
        raise ValueError("TaskBeacon repo is required")
    normalized_ref = normalize_taskbeacon_ref(ref)
    target_dir = resolve_taskbeacon_target_path(workspace_root, target_path)

    if target_dir.exists() and target_dir.is_dir() and any(target_dir.iterdir()):
        patch = apply_taskbeacon_runtime_patches(target_dir)
        return {
            "status": "skipped_existing",
            "source": "existing_workspace",
            "repo": normalized_repo,
            "ref": normalized_ref,
            "target_dir": str(target_dir),
            "runtime_patch": patch,
        }

    mcp_error: str | None = None
    mcp_skipped_reason: str | None = None
    if prefer_mcp and normalized_ref:
        mcp_skipped_reason = (
            "taskbeacon-mcp download_task does not accept refs; using direct Git fallback"
        )
    elif prefer_mcp:
        with tempfile.TemporaryDirectory(prefix="br_taskbeacon_mcp_") as tmp:
            tmp_dir = Path(tmp)
            mcp_config = config or TaskBeaconMCPConfig(cwd=str(tmp_dir))
            if config is not None and config.cwd is None:
                mcp_config = TaskBeaconMCPConfig(
                    command=config.command,
                    args=config.args,
                    cwd=str(tmp_dir),
                    timeout_seconds=config.timeout_seconds,
                )
            try:
                result = caller(
                    "download_task",
                    {"repo": normalized_repo},
                    config=mcp_config,
                )
                if not result.ok:
                    raise TaskBeaconMCPError(result.error or "download_task failed")
                source_text = _extract_download_path(result.structured) or _extract_download_path(
                    result.text
                )
                source_dir = Path(source_text).expanduser() if source_text else None
                if source_dir is not None and not source_dir.is_absolute():
                    source_dir = (tmp_dir / source_dir).resolve()
                if source_dir is not None and not _is_under_root(source_dir, tmp_dir):
                    raise TaskBeaconMCPError(
                        "download_task returned a path outside the temporary MCP root"
                    )
                if source_dir is None or not source_dir.exists():
                    source_dir = _find_downloaded_repo(tmp_dir, normalized_repo)
                if source_dir is None or not source_dir.exists():
                    raise TaskBeaconMCPError(
                        "download_task returned no materialized repo path"
                    )
                _copy_downloaded_repo(source_dir, target_dir)
                patch = apply_taskbeacon_runtime_patches(target_dir)
                return {
                    "status": "success",
                    "source": "taskbeacon_mcp",
                    "repo": normalized_repo,
                    "ref": normalized_ref,
                    "target_dir": str(target_dir),
                    "runtime_patch": patch,
                    "mcp": result.raw,
                }
            except Exception as exc:
                mcp_error = str(exc)

    fallback = materialize_taskbeacon_repo(
        workspace_root=workspace_root,
        repo=normalized_repo,
        target_path=target_path,
        ref=normalized_ref,
    )
    fallback["source"] = "direct_git_fallback"
    if mcp_error:
        fallback["mcp_error"] = mcp_error
    if mcp_skipped_reason:
        fallback["mcp_skipped_reason"] = mcp_skipped_reason
    return fallback


async def async_download_taskbeacon_task(
    *,
    workspace_root: str | Path,
    repo: str,
    target_path: str,
    ref: str | None = None,
    prefer_mcp: bool = True,
    config: TaskBeaconMCPConfig | None = None,
) -> dict[str, Any]:
    """Async TaskBeacon download for FastAPI routes.

    File copying and git fallback are still local blocking work, but upstream MCP
    I/O stays on the current async event loop instead of nesting ``anyio.run``.
    """

    normalized_repo = normalize_taskbeacon_repo(repo)
    if normalized_repo is None:
        raise ValueError("TaskBeacon repo is required")
    normalized_ref = normalize_taskbeacon_ref(ref)
    target_dir = resolve_taskbeacon_target_path(workspace_root, target_path)

    if target_dir.exists() and target_dir.is_dir() and any(target_dir.iterdir()):
        patch = apply_taskbeacon_runtime_patches(target_dir)
        return {
            "status": "skipped_existing",
            "source": "existing_workspace",
            "repo": normalized_repo,
            "ref": normalized_ref,
            "target_dir": str(target_dir),
            "runtime_patch": patch,
        }

    mcp_error: str | None = None
    mcp_skipped_reason: str | None = None
    if prefer_mcp and normalized_ref:
        mcp_skipped_reason = (
            "taskbeacon-mcp download_task does not accept refs; using direct Git fallback"
        )
    elif prefer_mcp:
        with tempfile.TemporaryDirectory(prefix="br_taskbeacon_mcp_") as tmp:
            tmp_dir = Path(tmp)
            mcp_config = config or TaskBeaconMCPConfig(cwd=str(tmp_dir))
            if config is not None and config.cwd is None:
                mcp_config = TaskBeaconMCPConfig(
                    command=config.command,
                    args=config.args,
                    cwd=str(tmp_dir),
                    timeout_seconds=config.timeout_seconds,
                )
            try:
                result = await async_call_taskbeacon_mcp_tool(
                    "download_task",
                    {"repo": normalized_repo},
                    config=mcp_config,
                )
                if not result.ok:
                    raise TaskBeaconMCPError(result.error or "download_task failed")
                source_text = _extract_download_path(result.structured) or _extract_download_path(
                    result.text
                )
                source_dir = Path(source_text).expanduser() if source_text else None
                if source_dir is not None and not source_dir.is_absolute():
                    source_dir = (tmp_dir / source_dir).resolve()
                if source_dir is not None and not _is_under_root(source_dir, tmp_dir):
                    raise TaskBeaconMCPError(
                        "download_task returned a path outside the temporary MCP root"
                    )
                if source_dir is None or not source_dir.exists():
                    source_dir = _find_downloaded_repo(tmp_dir, normalized_repo)
                if source_dir is None or not source_dir.exists():
                    raise TaskBeaconMCPError(
                        "download_task returned no materialized repo path"
                    )
                _copy_downloaded_repo(source_dir, target_dir)
                patch = apply_taskbeacon_runtime_patches(target_dir)
                return {
                    "status": "success",
                    "source": "taskbeacon_mcp",
                    "repo": normalized_repo,
                    "ref": normalized_ref,
                    "target_dir": str(target_dir),
                    "runtime_patch": patch,
                    "mcp": result.raw,
                }
            except Exception as exc:
                mcp_error = str(exc)

    fallback = materialize_taskbeacon_repo(
        workspace_root=workspace_root,
        repo=normalized_repo,
        target_path=target_path,
        ref=normalized_ref,
    )
    fallback["source"] = "direct_git_fallback"
    if mcp_error:
        fallback["mcp_error"] = mcp_error
    if mcp_skipped_reason:
        fallback["mcp_skipped_reason"] = mcp_skipped_reason
    return fallback


def _taskbeacon_runner_path() -> Path:
    raw = (os.getenv("BR_TASKBEACON_RUNNER") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    repo_runner = _REPO_ROOT / "scripts" / "runtime" / "run_taskbeacon_task.sh"
    if repo_runner.exists():
        return repo_runner
    return Path("/app/scripts/runtime/run_taskbeacon_task.sh")


def _taskbeacon_artifacts(resolved_task: Path) -> list[str]:
    outputs_dir = resolved_task / "outputs"
    if not outputs_dir.exists():
        return []
    return [
        str(path.relative_to(resolved_task))
        for path in sorted(outputs_dir.rglob("*"))
        if path.is_file()
    ]


def localize_taskbeacon_task(
    *,
    workspace_root: str | Path,
    task_path: str,
    target_language: str,
    voice: str | None = None,
    config: TaskBeaconMCPConfig | None = None,
    caller=call_taskbeacon_mcp_tool,
) -> dict[str, Any]:
    """Request TaskBeacon localization prompt messages for a workspace task."""

    resolved = resolve_taskbeacon_target_path(workspace_root, task_path)
    if not resolved.exists() or not resolved.is_dir():
        raise ValueError(f"TaskBeacon task path does not exist: {task_path!r}")
    language = (target_language or "").strip()
    if not language:
        raise ValueError("target_language is required")
    arguments: dict[str, Any] = {
        "task_path": str(resolved),
        "target_language": language,
    }
    if voice and voice.strip():
        arguments["voice"] = voice.strip()
    result = caller("localize", arguments, config=config or TaskBeaconMCPConfig())
    if not result.ok:
        raise TaskBeaconMCPError(result.error or "TaskBeacon MCP localize failed")
    return {
        "status": "success",
        "source": "taskbeacon_mcp",
        "task_path": str(resolved),
        "target_language": language,
        "prompt_messages": result.structured,
        "text": result.text,
        "raw": result.raw,
    }


async def async_localize_taskbeacon_task(
    *,
    workspace_root: str | Path,
    task_path: str,
    target_language: str,
    voice: str | None = None,
    config: TaskBeaconMCPConfig | None = None,
) -> dict[str, Any]:
    """Async TaskBeacon localization for FastAPI routes."""

    resolved = resolve_taskbeacon_target_path(workspace_root, task_path)
    if not resolved.exists() or not resolved.is_dir():
        raise ValueError(f"TaskBeacon task path does not exist: {task_path!r}")
    language = (target_language or "").strip()
    if not language:
        raise ValueError("target_language is required")
    arguments: dict[str, Any] = {
        "task_path": str(resolved),
        "target_language": language,
    }
    if voice and voice.strip():
        arguments["voice"] = voice.strip()
    result = await async_call_taskbeacon_mcp_tool(
        "localize",
        arguments,
        config=config or TaskBeaconMCPConfig(),
    )
    if not result.ok:
        raise TaskBeaconMCPError(result.error or "TaskBeacon MCP localize failed")
    return {
        "status": "success",
        "source": "taskbeacon_mcp",
        "task_path": str(resolved),
        "target_language": language,
        "prompt_messages": result.structured,
        "text": result.text,
        "raw": result.raw,
    }


def run_taskbeacon_qa_sim(
    *,
    workspace_root: str | Path,
    task_path: str,
    mode: str = "qa",
    config_path: str | None = None,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    """Run a TaskBeacon task through BR's hosted QA/sim shell boundary."""

    normalized_mode = (mode or "qa").strip().lower()
    if normalized_mode not in {"qa", "sim"}:
        raise ValueError("mode must be 'qa' or 'sim'")
    resolved_task = resolve_taskbeacon_target_path(workspace_root, task_path)
    if not (resolved_task / "main.py").exists():
        raise ValueError(f"TaskBeacon task directory does not contain main.py: {task_path!r}")

    command = [
        "bash",
        str(_taskbeacon_runner_path()),
        normalized_mode,
        "--task-dir",
        str(resolved_task),
    ]
    if config_path:
        resolved_config = resolve_taskbeacon_target_path(workspace_root, config_path)
        command.extend(["--config", str(resolved_config)])

    proc = subprocess.run(
        command,
        cwd=str(resolved_task),
        capture_output=True,
        text=True,
        timeout=max(1, int(timeout_seconds)),
        check=False,
    )
    return {
        "status": "success" if proc.returncode == 0 else "error",
        "mode": normalized_mode,
        "task_path": str(resolved_task),
        "returncode": proc.returncode,
        "stdout": proc.stdout[-8000:],
        "stderr": proc.stderr[-8000:],
        "artifacts": _taskbeacon_artifacts(resolved_task),
    }


async def async_run_taskbeacon_qa_sim(
    *,
    workspace_root: str | Path,
    task_path: str,
    mode: str = "qa",
    config_path: str | None = None,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    """Run a TaskBeacon task through BR's shell boundary without blocking FastAPI."""

    normalized_mode = (mode or "qa").strip().lower()
    if normalized_mode not in {"qa", "sim"}:
        raise ValueError("mode must be 'qa' or 'sim'")
    resolved_task = resolve_taskbeacon_target_path(workspace_root, task_path)
    if not (resolved_task / "main.py").exists():
        raise ValueError(f"TaskBeacon task directory does not contain main.py: {task_path!r}")

    command = [
        "bash",
        str(_taskbeacon_runner_path()),
        normalized_mode,
        "--task-dir",
        str(resolved_task),
    ]
    if config_path:
        resolved_config = resolve_taskbeacon_target_path(workspace_root, config_path)
        command.extend(["--config", str(resolved_config)])

    proc = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(resolved_task),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(),
            timeout=max(1, int(timeout_seconds)),
        )
    except asyncio.TimeoutError:
        proc.kill()
        stdout_b, stderr_b = await proc.communicate()
        stderr = stderr_b.decode(errors="replace")
        return {
            "status": "error",
            "mode": normalized_mode,
            "task_path": str(resolved_task),
            "returncode": proc.returncode,
            "stdout": stdout_b.decode(errors="replace")[-8000:],
            "stderr": (stderr + "\nTaskBeacon QA/sim timed out.").strip()[-8000:],
            "artifacts": _taskbeacon_artifacts(resolved_task),
        }

    return {
        "status": "success" if proc.returncode == 0 else "error",
        "mode": normalized_mode,
        "task_path": str(resolved_task),
        "returncode": proc.returncode,
        "stdout": stdout_b.decode(errors="replace")[-8000:],
        "stderr": stderr_b.decode(errors="replace")[-8000:],
        "artifacts": _taskbeacon_artifacts(resolved_task),
    }
