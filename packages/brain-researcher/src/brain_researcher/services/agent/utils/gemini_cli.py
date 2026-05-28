"""
Secure local Gemini CLI executor used by the agent service.

Implements a thin wrapper around the user's installed `gemini` CLI to
leverage per-user OAuth free credits while enforcing strict security and
robust parsing. This module is intentionally minimal and self-contained.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


# Limits and defaults
MAX_INPUT_CHARS = 1_000_000
DEFAULT_TIMEOUT_SEC = 60


class GeminiCLIError(Exception):
    """Base exception for Gemini CLI wrapper."""


class GeminiNotInstalledError(GeminiCLIError):
    pass


class GeminiAuthError(GeminiCLIError):
    pass


class GeminiQuotaError(GeminiCLIError):
    pass


class GeminiTimeoutError(GeminiCLIError):
    pass


class GeminiProcessError(GeminiCLIError):
    pass


@dataclass
class GeminiResult:
    text: str
    usage: Dict[str, Any]
    raw: Optional[str] = None
    model: Optional[str] = None


def sanitize_input(text: str) -> str:
    """Sanitize user-provided prompt to avoid control chars and huge payloads."""
    if text is None:
        return ""
    # Remove null bytes
    cleaned = text.replace("\0", "")
    # Normalize line endings
    cleaned = cleaned.replace("\r\n", "\n")
    # Enforce length limit
    if len(cleaned) > MAX_INPUT_CHARS:
        cleaned = cleaned[:MAX_INPUT_CHARS]
    return cleaned


def get_gemini_executable() -> str:
    """Locate the `gemini` executable across platforms.

    Returns the absolute path or raises GeminiNotInstalledError.
    """
    # Prefer PATH
    which = shutil.which("gemini") or shutil.which("gemini.exe")
    if which:
        return which

    system = platform.system()
    search: list[Path | str]
    if system == "Windows":
        search = [
            r"C:\\Program Files\\Google\\Gemini CLI\\gemini.exe",
            r"C:\\Program Files (x86)\\Google\\Gemini CLI\\gemini.exe",
            Path.home() / "AppData" / "Local" / "Google" / "Gemini CLI" / "gemini.exe",
        ]
    elif system == "Darwin":
        search = [
            "/opt/homebrew/bin/gemini",
            "/usr/local/bin/gemini",
            Path.home() / ".local" / "bin" / "gemini",
        ]
    else:
        search = [
            "/usr/local/bin/gemini",
            "/usr/bin/gemini",
            Path.home() / ".local" / "bin" / "gemini",
        ]

    for p in search:
        pth = str(p)
        if os.path.isfile(pth):
            return pth

    raise GeminiNotInstalledError(
        "Gemini CLI not found. Install it and run `gemini login`."
    )


def check_gemini_version(timeout_sec: int = 5) -> Optional[str]:
    """Return the gemini CLI version string if available, else None."""
    try:
        exe = get_gemini_executable()
        result = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            shell=False,
        )
        out = (result.stdout or result.stderr or "").strip()
        # Typical: "gemini version 1.2.5"
        m = re.search(r"(\d+\.\d+\.\d+)", out)
        return m.group(1) if m else out or None
    except Exception:
        return None


def is_logged_in(timeout_sec: int = 5) -> bool:
    """Best-effort check that Gemini CLI is installed and user is authenticated.

    Attempts `gemini whoami` first (preferred). If unsupported or failing, falls back
    to `gemini --version` to confirm that the binary exists.
    """
    try:
        exe = get_gemini_executable()
    except Exception:
        return False

    commands = [
        ([exe, "whoami"], True),
        ([exe, "--version"], False),
    ]

    for args, requires_output in commands:
        try:
            result = subprocess.run(
                args, capture_output=True, text=True, timeout=timeout_sec, shell=False
            )
        except Exception:
            continue

        if result.returncode != 0:
            continue

        output = (result.stdout or result.stderr or "").strip()

        if requires_output:
            if not output:
                continue
            normalized = output.lower()
            if (
                "authorization code" in normalized
                or "please visit the following url" in normalized
            ):
                # Indicates login prompt rather than authenticated identity
                return False
            return True
        else:
            return True

    return False


def quick_health_check(timeout_sec: int = 3) -> bool:
    """Lightweight liveness check to confirm the CLI is runnable and logged in."""
    try:
        exe = get_gemini_executable()
    except Exception:
        return False

    try:
        # `models list` is fast and requires auth; suppress output
        result = subprocess.run(
            [exe, "models", "list", "--limit", "1"],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            shell=False,
        )
        if result.returncode != 0:
            return False
        return True
    except Exception:
        return False


def parse_gemini_response(output: str) -> Dict[str, Any]:
    """Parse Gemini CLI output into a normalized dict with fallbacks."""
    if not output:
        return {"text": "", "usage": {"total_tokens": 0}}

    # Strategy 1: Full JSON
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        pass

    # Strategy 2: line-by-line JSON
    for line in output.splitlines():
        l = line.strip()
        if l.startswith("{") and l.endswith("}"):
            try:
                return json.loads(l)
            except json.JSONDecodeError:
                continue

    # Strategy 3: extract "text" value roughly
    m = re.search(r'"text"\s*:\s*"(.*?)"', output, flags=re.DOTALL)
    if m:
        text_val = m.group(1)
        try:
            text_val = json.loads(f'"{text_val}"')
        except json.JSONDecodeError:
            pass
        return {"text": text_val, "usage": {"total_tokens": _estimate_tokens(text_val)}}

    # Strategy 4: plain text fallback
    cleaned = _clean_text(output)
    return {
        "text": cleaned,
        "usage": {"total_tokens": _estimate_tokens(cleaned)},
        "warning": "fallback_parse",
    }


def _clean_text(s: str) -> str:
    return s.replace("\0", "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _estimate_tokens(s: str) -> int:
    # Rough heuristic: ~4 chars per token
    return max(1, int(len(s) / 4))


def _map_error(exit_code: int, stderr: str) -> GeminiCLIError:
    s = (stderr or "").lower()
    if "quota" in s and ("exceeded" in s or "exhausted" in s or "limit" in s):
        return GeminiQuotaError(stderr)
    if "unauthorized" in s or "auth" in s or "token" in s:
        return GeminiAuthError(stderr)
    if "timeout" in s:
        return GeminiTimeoutError(stderr)
    if exit_code == 124:
        return GeminiTimeoutError(stderr)
    return GeminiProcessError(stderr or f"gemini exited with code {exit_code}")


def execute_chat(
    prompt: str,
    model: str = "gemini-3-flash-preview",
    *,
    max_output_tokens: Optional[int] = None,
    thinking_budget: Optional[int] = None,
    strict_json: Optional[bool] = None,
    task_type: Optional[str] = None,
    ctx_tokens: Optional[int] = None,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
) -> GeminiResult:
    """Execute a single-turn chat via local gemini CLI.

    Raises GeminiCLIError subclasses on failure.
    """
    # Unused parameters are accepted for interface compatibility with callers
    # that forward richer routing context (strict_json/task_type/etc.).
    sanitized = sanitize_input(prompt)
    exe = get_gemini_executable()

    # Build candidate argument variants for different CLI versions
    base = ["-m", model, "-p", sanitized]

    candidates: list[list[str]] = []
    # CLI v0.22+ exposes structured output via `-o json`; older legacy flag is `--json`.
    candidates.append(base + ["-o", "json"])  # preferred modern form
    candidates.append(base + ["--json"])  # legacy form for older CLI versions
    # Some versions don't support thinking budget; append if provided
    if isinstance(thinking_budget, int) and thinking_budget >= 0:
        candidates.insert(
            0, base + ["-o", "json", "--thinking-budget", str(thinking_budget)]
        )
        candidates.append(base + ["--thinking-budget", str(thinking_budget)])
    # Plain output fallback
    candidates.append(base)

    last_err: Exception | None = None
    stdout: str = ""

    for args in candidates:
        try:
            proc = subprocess.run(
                [exe] + args,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                shell=False,
            )
        except subprocess.TimeoutExpired as e:
            last_err = GeminiTimeoutError(str(e))
            continue
        except FileNotFoundError as e:
            last_err = GeminiNotInstalledError(str(e))
            break
        except Exception as e:
            last_err = GeminiProcessError(str(e))
            continue

        if proc.returncode == 0:
            stdout = proc.stdout
            break

        # If unknown arg errors, try next variant
        stderr_lower = (proc.stderr or "").lower()
        if "unknown argument" in stderr_lower or "unknown option" in stderr_lower:
            last_err = GeminiProcessError(proc.stderr)
            continue

        # Other non-zero: map and stop trying
        last_err = _map_error(proc.returncode, proc.stderr)
        break

    if not stdout:
        if last_err:
            raise last_err
        raise GeminiProcessError("Gemini CLI produced no output")

    lower_stdout = stdout.lower()
    if (
        "enter the authorization code" in lower_stdout
        or "please visit the following url" in lower_stdout
    ):
        raise GeminiAuthError(
            "Gemini CLI not authenticated. Run `gemini login` to continue."
        )

    parsed = parse_gemini_response(stdout)
    # CLI v0.22+ returns the model output under "response"; older/alt schemas
    # use "text" or "output". Check all three so both transport versions work.
    text = (
        parsed.get("response")
        or parsed.get("text")
        or parsed.get("output")
        or ""
    )
    usage = parsed.get("usage") or parsed.get("stats", {}).get("models", {}) or {}
    return GeminiResult(text=text, usage=usage, raw=proc.stdout, model=model)
