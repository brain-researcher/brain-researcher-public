"""Executor-level sandbox enforcement (P0/M3).

This module implements best-effort runtime enforcement for ToolSpec
`execution_capabilities`, focusing on:

- Filesystem access: `allowed_paths` (parameter-based allowlisting)
- Filesystem access (runtime): thread-local open/os.open guard
- Network access: `needs_network` + `allowed_domains` (thread-local socket guard)

Limitations:
- Python tools can still access arbitrary files not referenced in parameters.
- Network guard only affects in-process networking (not subprocess/CLI calls).
"""

from __future__ import annotations

import builtins
import io
import ipaddress
import os
import socket
import sys
import threading
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from brain_researcher.services.tools.spec import ToolSpec


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _is_test_env() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules


def enforcement_enabled() -> bool:
    """Return whether enforcement is enabled for this process."""
    raw = os.getenv("BR_ENFORCE_EXECUTION_POLICY")
    if raw is not None:
        return _truthy(raw)
    if _is_test_env():
        return False
    return os.getenv("BR_SANDBOX_ENABLED", "true").strip().lower() == "true"


# ---------------------------------------------------------------------------
# Filesystem policy (allowed_paths)
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[4]

_DEFAULT_ALLOWED_ROOTS = [
    (REPO_ROOT / "artifacts").resolve(),
    (REPO_ROOT / "data").resolve(),
    (REPO_ROOT / "tmp").resolve(),
    Path("/data").resolve(),
    Path("/tmp").resolve(),
    Path("/var/tmp").resolve(),
]

_URI_PREFIXES = ("http://", "https://", "s3://", "gs://", "hf://")

_KEY_HINTS = {
    "img",
    "image",
    "mask",
    "mask_img",
    "atlas",
    "events",
    "confounds",
    "bids_dir",
    "bids_root",
    "output_dir",
    "work_dir",
    "infile",
    "outfile",
    "script",
    "input_file",
    "output_file",
}

_PATH_SUFFIXES = ("_path", "_file", "_dir")

_PATH_EXTENSIONS = (
    ".nii",
    ".nii.gz",
    ".json",
    ".tsv",
    ".csv",
    ".txt",
    ".py",
    ".sh",
    ".png",
    ".jpg",
    ".jpeg",
    ".gz",
    ".zip",
)


_DEFAULT_PATH_ALIAS_PAIRS = ((REPO_ROOT / "data", Path("/app/data")),)


def _safe_resolve(path: Path) -> Path:
    try:
        return path.resolve()
    except Exception:
        return path


def _parse_path_alias_map(raw: str | None) -> list[tuple[Path, Path]]:
    """Parse BR_PATH_ALIAS_MAP: "host=container,host2=container2"."""
    if not raw:
        return []

    aliases: list[tuple[Path, Path]] = []
    for part in raw.split(","):
        token = part.strip()
        if not token or "=" not in token:
            continue
        left, right = token.split("=", 1)
        src_raw = left.strip()
        dst_raw = right.strip()
        if not src_raw or not dst_raw:
            continue

        src = Path(src_raw).expanduser()
        dst = Path(dst_raw).expanduser()
        if not src.is_absolute() or not dst.is_absolute():
            continue
        aliases.append((_safe_resolve(src), _safe_resolve(dst)))

    return aliases


def _path_alias_pairs() -> list[tuple[Path, Path]]:
    """Return conservative default aliases merged with env overrides."""
    aliases: list[tuple[Path, Path]] = []
    for src, dst in _DEFAULT_PATH_ALIAS_PAIRS:
        aliases.append((_safe_resolve(src), _safe_resolve(dst)))

    aliases.extend(_parse_path_alias_map(os.getenv("BR_PATH_ALIAS_MAP")))

    dedup: list[tuple[Path, Path]] = []
    seen: set[tuple[str, str]] = set()
    for src, dst in aliases:
        key = (str(src), str(dst))
        if key in seen:
            continue
        seen.add(key)
        dedup.append((src, dst))
    return dedup


def _remap_with_path_alias(path: Path) -> Path:
    """Apply longest-prefix path alias remapping to a resolved path."""
    resolved = _safe_resolve(path)
    best: tuple[Path, Path] | None = None

    for src, dst in _path_alias_pairs():
        try:
            if resolved == src or resolved.is_relative_to(src):
                if best is None or len(str(src)) > len(str(best[0])):
                    best = (src, dst)
        except Exception:
            continue

    if best is None:
        return resolved

    src, dst = best
    try:
        rel = resolved.relative_to(src)
    except Exception:
        return resolved
    return _safe_resolve(dst / rel)


def _path_variants_for_policy(path: Path) -> list[Path]:
    """Return [original, aliased?] candidates used for allowlist checks."""
    original = _safe_resolve(path)
    remapped = _remap_with_path_alias(original)
    if remapped == original:
        return [original]
    return [original, remapped]


def _first_variant_under_roots(path: Path, roots: list[Path]) -> Path | None:
    for candidate in _path_variants_for_policy(path):
        if _is_under_any_root(candidate, roots):
            return candidate
    return None


def _parse_roots(raw: str | None) -> list[Path]:
    if not raw:
        return []
    roots: list[Path] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            roots.append(Path(part).expanduser().resolve())
        except Exception:
            continue
    return roots


def _global_allowed_roots() -> list[Path]:
    raw = os.getenv("BR_ALLOWED_ROOTS") or os.getenv("BR_MCP_ALLOWED_ROOTS")
    parsed = _parse_roots(raw)
    return parsed or list(_DEFAULT_ALLOWED_ROOTS)


def _is_under_root(path: Path, root: Path) -> bool:
    try:
        resolved = path.resolve()
        root_resolved = root.resolve()
        return resolved == root_resolved or resolved.is_relative_to(root_resolved)
    except Exception:
        return False


def _is_under_any_root(path: Path, roots: list[Path]) -> bool:
    return any(_is_under_root(path, root) for root in roots)


def _is_uri(value: str) -> bool:
    v = value.strip().lower()
    return any(v.startswith(p) for p in _URI_PREFIXES)


def _key_is_pathish(key: str) -> bool:
    k = key.lower()
    return k in _KEY_HINTS or k.endswith(_PATH_SUFFIXES)


def _looks_like_path(value: str) -> bool:
    v = value.strip()
    if not v or any(ch.isspace() for ch in v):
        return False
    if _is_uri(v):
        return False
    if v.startswith(("/", "~", "./", "../")):
        return True
    v_lower = v.lower()
    return any(v_lower.endswith(ext) for ext in _PATH_EXTENSIONS)


def _walk_candidate_paths(obj: Any, *, prefix: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                continue
            key_path = f"{prefix}.{k}" if prefix else k

            if isinstance(v, str) and (_looks_like_path(v) or _key_is_pathish(k)):
                found.append((key_path, v))
            elif isinstance(v, list):
                for idx, item in enumerate(v):
                    if isinstance(item, str) and (
                        _looks_like_path(item) or _key_is_pathish(k)
                    ):
                        found.append((f"{key_path}[{idx}]", item))

            found.extend(_walk_candidate_paths(v, prefix=key_path))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            found.extend(_walk_candidate_paths(item, prefix=f"{prefix}[{idx}]"))
    return found


def _resolve_path(raw: str, *, bases: list[Path]) -> Path | None:
    p = Path(raw).expanduser()
    if p.is_absolute():
        try:
            return p.resolve()
        except Exception:
            return p

    for base in bases:
        try:
            return (base / p).resolve()
        except Exception:
            continue
    return None


class ExecutionPolicyError(RuntimeError):
    def __init__(self, issues: list[dict[str, Any]]):
        super().__init__("execution_policy_violation")
        self.issues = issues


def _python_runtime_read_roots() -> list[Path]:
    """Best-effort read allowlist for Python runtime/module loading.

    We allow reading under these roots to avoid breaking imports and standard
    library/package loading when a filesystem guard is active.
    """
    roots: list[Path] = []
    for raw in {sys.prefix, sys.base_prefix, sys.exec_prefix}:
        if not raw:
            continue
        try:
            roots.append(Path(raw).resolve())
        except Exception:
            continue

    # Allow reading package code within the repo checkout.
    try:
        roots.append(REPO_ROOT.resolve())
    except Exception:
        pass

    # De-duplicate while preserving order.
    deduped: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(root)
    return deduped


def _effective_allowed_roots(
    spec: ToolSpec | None,
    *,
    work_dir: str | None = None,
    output_dir: str | None = None,
) -> list[Path]:
    """Compute the effective filesystem allowlist roots for a tool run."""
    global_roots = _global_allowed_roots()

    bases: list[Path] = []
    if output_dir:
        out = Path(output_dir).expanduser()
        out_resolved = _safe_resolve(out)
        out_allowed = _first_variant_under_roots(out_resolved, global_roots)
        if out_allowed is None:
            raise ExecutionPolicyError(
                [
                    {
                        "level": "error",
                        "code": "output_dir_not_allowed",
                        "message": f"output_dir is outside allowed roots: {out_resolved}",
                    }
                ]
            )
        bases.append(out_allowed)

    if work_dir:
        wd = Path(work_dir).expanduser()
        wd_resolved = _safe_resolve(wd)
        wd_allowed = _first_variant_under_roots(wd_resolved, global_roots)
        if wd_allowed is None:
            raise ExecutionPolicyError(
                [
                    {
                        "level": "error",
                        "code": "work_dir_not_allowed",
                        "message": f"work_dir is outside allowed roots: {wd_resolved}",
                    }
                ]
            )
        bases.append(wd_allowed)

    caps = getattr(spec, "execution_capabilities", None) if spec is not None else None
    has_tool_allowlist = bool(caps and getattr(caps, "allowed_paths", None))

    if has_tool_allowlist:
        tool_roots: list[Path] = []
        for raw_root in caps.allowed_paths:
            if not isinstance(raw_root, str) or not raw_root.strip():
                continue
            root = Path(raw_root).expanduser()
            if not root.is_absolute():
                root = REPO_ROOT / root
            for root_variant in _path_variants_for_policy(root):
                if root_variant not in tool_roots:
                    tool_roots.append(root_variant)

        for base in bases:
            if base not in tool_roots:
                tool_roots.append(base)
        return tool_roots

    roots = list(global_roots)
    for base in bases:
        if base not in roots:
            roots.append(base)
    return roots


def enforce_allowed_paths(
    spec: ToolSpec,
    parameters: dict[str, Any],
    *,
    work_dir: str | None = None,
    output_dir: str | None = None,
) -> None:
    """Enforce filesystem allowlists for a tool execution (best-effort)."""
    if not enforcement_enabled():
        return

    global_roots = _global_allowed_roots()

    bases: list[Path] = []
    if output_dir:
        out = Path(output_dir).expanduser()
        out_resolved = _safe_resolve(out)
        out_allowed = _first_variant_under_roots(out_resolved, global_roots)
        if out_allowed is None:
            raise ExecutionPolicyError(
                [
                    {
                        "level": "error",
                        "code": "output_dir_not_allowed",
                        "message": f"output_dir is outside allowed roots: {out_resolved}",
                    }
                ]
            )
        bases.append(out_allowed)

    if work_dir:
        wd = Path(work_dir).expanduser()
        wd_resolved = _safe_resolve(wd)
        wd_allowed = _first_variant_under_roots(wd_resolved, global_roots)
        if wd_allowed is None:
            raise ExecutionPolicyError(
                [
                    {
                        "level": "error",
                        "code": "work_dir_not_allowed",
                        "message": f"work_dir is outside allowed roots: {wd_resolved}",
                    }
                ]
            )
        bases.append(wd_allowed)

    caps = getattr(spec, "execution_capabilities", None)
    has_tool_allowlist = bool(caps and getattr(caps, "allowed_paths", None))

    # resolve_bases is used ONLY for resolving relative paths
    resolve_bases = list(bases) if bases else [REPO_ROOT]

    tool_roots: list[Path] = []
    if has_tool_allowlist:
        # Tool declared specific allowed_paths - build tool-specific allowlist
        for raw_root in caps.allowed_paths:
            if not isinstance(raw_root, str) or not raw_root.strip():
                continue
            root = Path(raw_root).expanduser()
            if not root.is_absolute():
                root = REPO_ROOT / root
            for root_variant in _path_variants_for_policy(root):
                if root_variant not in tool_roots:
                    tool_roots.append(root_variant)

        # Also allow within step sandbox directories (output_dir/work_dir)
        for base in bases:
            if base not in tool_roots:
                tool_roots.append(base)

    candidates = _walk_candidate_paths(parameters, prefix="")
    if not candidates:
        return

    issues: list[dict[str, Any]] = []
    for key_path, raw_value in candidates:
        value = (raw_value or "").strip()
        if not value or _is_uri(value):
            continue

        resolved = _resolve_path(value, bases=resolve_bases)
        if resolved is None:
            issues.append(
                {
                    "level": "error",
                    "code": "relative_path_without_base",
                    "message": (
                        f"Relative path for '{key_path}' requires work_dir/output_dir: {value}"
                    ),
                    "key": key_path,
                    "value": value,
                }
            )
            continue

        variants = _path_variants_for_policy(resolved)

        if not any(_is_under_any_root(v, global_roots) for v in variants):
            issues.append(
                {
                    "level": "error",
                    "code": "path_outside_allowed_roots",
                    "message": f"Path is outside allowed roots: {resolved}",
                    "key": key_path,
                    "value": value,
                    "resolved_path": str(resolved),
                    "aliased_path": (str(variants[1]) if len(variants) > 1 else None),
                }
            )
            continue

        # Only enforce tool-specific allowlist if tool declared one
        if (
            has_tool_allowlist
            and tool_roots
            and not any(_is_under_any_root(v, tool_roots) for v in variants)
        ):
            issues.append(
                {
                    "level": "error",
                    "code": "path_not_in_tool_allowlist",
                    "message": (
                        "Path is not allowed by tool execution_capabilities: "
                        f"{resolved}"
                    ),
                    "key": key_path,
                    "value": value,
                    "resolved_path": str(resolved),
                }
            )

    if issues:
        raise ExecutionPolicyError(issues)


# ---------------------------------------------------------------------------
# Filesystem policy (runtime guard)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _FilesystemPolicy:
    allowed_roots: tuple[Path, ...]
    python_read_roots: tuple[Path, ...]


_ORIGINAL_OPEN = builtins.open
_ORIGINAL_IO_OPEN = io.open
_ORIGINAL_OS_OPEN = os.open
_FS_GUARD_INSTALLED = False
_fs_guard_lock = threading.Lock()


def _coerce_fspath(value: Any) -> str | None:
    if isinstance(value, int):
        return None
    try:
        raw = os.fspath(value)
    except TypeError:
        return None
    if isinstance(raw, bytes):
        try:
            return raw.decode("utf-8", "ignore")
        except Exception:
            return str(raw)
    return str(raw)


def _is_write_mode(mode: Any) -> bool:
    if not isinstance(mode, str):
        return False
    return any(ch in mode for ch in ("w", "a", "x", "+"))


def _allow_pyc_write(path: Path, roots: tuple[Path, ...]) -> bool:
    try:
        if path.suffix != ".pyc":
            return False
        if "__pycache__" not in path.parts:
            return False
        return _is_under_any_root(path, list(roots))
    except Exception:
        return False


def _enforce_filesystem_policy(pathish: Any, *, is_write: bool) -> None:
    policy: _FilesystemPolicy | None = getattr(_thread_local, "fs_policy", None)
    if policy is None:
        return

    raw = _coerce_fspath(pathish)
    if raw is None:
        return

    try:
        candidate = Path(raw).expanduser()
    except Exception:
        candidate = Path(str(raw))
    try:
        resolved = candidate.resolve()
    except Exception:
        resolved = candidate

    variants = _path_variants_for_policy(resolved)

    if any(_is_under_any_root(v, list(policy.allowed_roots)) for v in variants):
        return

    if not is_write and any(
        _is_under_any_root(v, list(policy.python_read_roots)) for v in variants
    ):
        return

    if is_write and any(
        _allow_pyc_write(v, policy.python_read_roots) for v in variants
    ):
        return

    raise ExecutionPolicyError(
        [
            {
                "level": "error",
                "code": "path_outside_allowed_roots",
                "message": f"Path is outside allowed roots: {resolved}",
                "resolved_path": str(resolved),
                "aliased_path": str(variants[1]) if len(variants) > 1 else None,
            }
        ]
    )


def _install_filesystem_guard_once() -> None:
    global _FS_GUARD_INSTALLED
    if _FS_GUARD_INSTALLED:
        return
    with _fs_guard_lock:
        if _FS_GUARD_INSTALLED:
            return

        def guarded_open(file, mode="r", *args, **kwargs):
            _enforce_filesystem_policy(file, is_write=_is_write_mode(mode))
            return _ORIGINAL_OPEN(file, mode, *args, **kwargs)

        def guarded_os_open(file, flags, *args, **kwargs):
            is_write = bool(
                int(flags)
                & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            )
            _enforce_filesystem_policy(file, is_write=is_write)
            return _ORIGINAL_OS_OPEN(file, flags, *args, **kwargs)

        guarded_open._br_policy_wrapped = True  # type: ignore[attr-defined]
        guarded_os_open._br_policy_wrapped = True  # type: ignore[attr-defined]
        builtins.open = guarded_open  # type: ignore[assignment]
        io.open = guarded_open  # type: ignore[assignment]
        os.open = guarded_os_open  # type: ignore[assignment]

        _FS_GUARD_INSTALLED = True


@contextmanager
def filesystem_guard(
    spec: ToolSpec | None,
    *,
    work_dir: str | None = None,
    output_dir: str | None = None,
):
    """Apply per-tool filesystem policy via a thread-local open/os.open guard."""
    if not enforcement_enabled():
        yield
        return

    allowed_roots = _effective_allowed_roots(
        spec, work_dir=work_dir, output_dir=output_dir
    )
    python_roots = _python_runtime_read_roots()

    _install_filesystem_guard_once()
    prev = getattr(_thread_local, "fs_policy", None)
    _thread_local.fs_policy = _FilesystemPolicy(
        allowed_roots=tuple(allowed_roots),
        python_read_roots=tuple(python_roots),
    )
    try:
        yield
    finally:
        _thread_local.fs_policy = prev


def build_execution_policy_snapshot(
    spec: ToolSpec | None,
    *,
    work_dir: str | None = None,
    output_dir: str | None = None,
    timeout_s: float | None = None,
) -> dict[str, Any]:
    """Return a best-effort snapshot of the effective execution policy."""
    global_roots = _global_allowed_roots()
    try:
        effective_roots = _effective_allowed_roots(
            spec, work_dir=work_dir, output_dir=output_dir
        )
    except ExecutionPolicyError:
        effective_roots = []

    caps = getattr(spec, "execution_capabilities", None) if spec is not None else None
    domains = getattr(caps, "allowed_domains", None) if caps is not None else None
    domains = domains or []
    cleaned_domains = [d.strip() for d in domains if isinstance(d, str) and d.strip()]

    return {
        "enforced": enforcement_enabled(),
        "timeout_s": timeout_s,
        "filesystem": {
            "global_allowed_roots": [str(p) for p in global_roots],
            "effective_allowed_roots": [str(p) for p in effective_roots],
            "work_dir": work_dir,
            "output_dir": output_dir,
            "declared_allowed_paths": (
                list(getattr(caps, "allowed_paths", None) or [])
                if caps is not None
                else []
            ),
        },
        "network": {
            "default_deny": True,
            "declared_needs_network": (
                getattr(caps, "needs_network", None) if caps is not None else None
            ),
            "allowed_domains": cleaned_domains,
        },
    }


# ---------------------------------------------------------------------------
# Network policy (allowed_domains)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _NetworkPolicy:
    allow_network: bool
    allowed_domains: tuple[str, ...] | None = None


_thread_local = threading.local()
_ORIGINAL_GETADDRINFO = socket.getaddrinfo
_SOCKET_GUARD_INSTALLED = False
_socket_guard_lock = threading.Lock()


def _normalize_host(host: Any) -> str | None:
    if host is None:
        return None
    if isinstance(host, bytes):
        try:
            host = host.decode("utf-8", "ignore")
        except Exception:
            host = str(host)
    if not isinstance(host, str):
        host = str(host)
    host = host.strip().lower()
    if host.endswith("."):
        host = host[:-1]
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    return host or None


def _host_allowed(host: str, patterns: Iterable[str]) -> bool:
    host = host.strip().lower()
    if not host:
        return False

    for pat in patterns:
        if not isinstance(pat, str):
            continue
        p = pat.strip().lower()
        if not p:
            continue
        if p == "*":
            return True

        # Allow exact IP matches.
        try:
            ipaddress.ip_address(host)
            if host == p:
                return True
            continue
        except ValueError:
            pass

        if p.startswith("*."):
            suffix = p[2:]
            if host == suffix or host.endswith("." + suffix):
                return True
            continue

        # Default: allow exact domain and subdomains.
        if host == p or host.endswith("." + p):
            return True

    return False


def _install_socket_guard_once() -> None:
    global _SOCKET_GUARD_INSTALLED
    if _SOCKET_GUARD_INSTALLED:
        return
    with _socket_guard_lock:
        if _SOCKET_GUARD_INSTALLED:
            return

        def guarded_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
            policy: _NetworkPolicy | None = getattr(_thread_local, "policy", None)
            if policy is None:
                return _ORIGINAL_GETADDRINFO(host, port, family, type, proto, flags)

            if not policy.allow_network:
                raise socket.gaierror(socket.EAI_NONAME, "network_blocked_by_policy")

            allowed = policy.allowed_domains
            if allowed:
                normalized = _normalize_host(host)
                if normalized is not None and not _host_allowed(normalized, allowed):
                    raise socket.gaierror(
                        socket.EAI_NONAME,
                        f"domain_not_allowed:{normalized}",
                    )

            return _ORIGINAL_GETADDRINFO(host, port, family, type, proto, flags)

        guarded_getaddrinfo._br_policy_wrapped = True  # type: ignore[attr-defined]
        socket.getaddrinfo = guarded_getaddrinfo  # type: ignore[assignment]
        _SOCKET_GUARD_INSTALLED = True


@contextmanager
def network_guard(spec: ToolSpec | None):
    """Apply per-tool network policy via thread-local socket guard."""
    if not enforcement_enabled():
        yield
        return

    caps = getattr(spec, "execution_capabilities", None) if spec is not None else None
    declared = getattr(caps, "needs_network", None) if caps is not None else None
    domains = getattr(caps, "allowed_domains", None) if caps is not None else None
    domains = domains or []
    cleaned = [d.strip() for d in domains if isinstance(d, str) and d.strip()]
    allowed_domains: tuple[str, ...] | None = tuple(cleaned) if cleaned else None

    # Default deny: if the tool has not declared network needs, block by default.
    allow_network = False
    if declared is True:
        allow_network = True
    elif declared is False:
        allow_network = False
    elif allowed_domains:
        # Allow only when an explicit allowlist exists.
        allow_network = True

    _install_socket_guard_once()
    prev = getattr(_thread_local, "policy", None)
    _thread_local.policy = _NetworkPolicy(
        allow_network=allow_network,
        allowed_domains=allowed_domains,
    )
    try:
        yield
    finally:
        _thread_local.policy = prev


__all__ = [
    "ExecutionPolicyError",
    "build_execution_policy_snapshot",
    "enforcement_enabled",
    "enforce_allowed_paths",
    "filesystem_guard",
    "network_guard",
]
