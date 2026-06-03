"""Test execution tool for running test commands."""

from __future__ import annotations

import logging
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

from brain_researcher.services.agent.code_tool_registry import CodeTool
from brain_researcher.services.agent.code_tools.utils import validate_path

logger = logging.getLogger(__name__)


def _normalize_python_cmd(cmd: str) -> str:
    """Normalize python3/python3.x -> python for consistent prefix checking."""
    # Normalize various python3 versions to python
    return re.sub(r"\bpython3(?:\.\d+)?\s", "python ", cmd)


def _looks_like_path(value: str) -> bool:
    """Heuristic to decide if a token resembles a filesystem path."""
    if not value:
        return False
    if value.startswith("~"):
        return True
    if value.startswith(".."):
        return True
    if "/" in value or "\\" in value:
        return True
    # Windows drive pattern, e.g., C:\ or D:/
    if re.match(r"^[A-Za-z]:[\\/].*", value):
        return True
    return False


# Allowed test command prefixes for security
# Note: "python -c" is NOT allowed - blocks arbitrary code execution
ALLOWED_TEST_PREFIXES = [
    "pytest",
    "python -m pytest",
    "python -m unittest",
    "python -m py_compile",
    "python -m doctest",
    "make test",
    "npm test",
    "npm run test",
    "yarn test",
    "cargo test",
    "go test",
]

# Patterns that should never appear in commands (security blocklist)
DISALLOWED_PATTERNS = [
    " -c ",  # Block -c flag (arbitrary code execution)
    " -c'",  # Block -c with single quote
    ' -c"',  # Block -c with double quote
    " -c\t",  # Block -c with tab
    ">",  # Output redirection
    "<",  # Input redirection
    "`",  # Command substitution (backtick)
    "$(",  # Command substitution (dollar-paren)
    "cd /",  # Directory change to root
    "../",  # Parent directory traversal
    "..\\",  # Windows parent directory
    ";",  # Command chaining
    "&&",  # Command chaining (and)
    "||",  # Command chaining (or)
    "|",  # Pipe (command chaining)
]

# Flags that take path values - must validate paths for these
PATH_FLAGS = [
    "--rootdir",
    "--basetemp",
    "--confcutdir",
    "--junitxml",
    "--cov-report",
    "--htmlcov",
    "--cache-dir",
    "-o",
    "--override-ini",
]


def _validate_command_paths(cmd: str, repo_root: Path) -> str | None:
    """Check that any path-like arguments are under repo_root.

    Args:
        cmd: The command string to validate
        repo_root: The repository root that paths must stay within

    Returns:
        Error message if validation fails, None if valid
    """
    try:
        tokens = shlex.split(cmd)
    except ValueError as e:
        return f"Invalid command syntax: {e}"

    i = 0
    while i < len(tokens):
        token = tokens[i]

        # Check --flag=value format
        if token.startswith("-") and "=" in token:
            flag, value = token.split("=", 1)
            if any(flag == pf or flag.startswith(pf + "=") for pf in PATH_FLAGS):
                if _looks_like_path(value):
                    raw = os.path.expanduser(value)
                    path = Path(raw) if os.path.isabs(raw) else (repo_root / raw)
                    if not validate_path(path, repo_root):
                        return f"Flag '{flag}' path escapes repository: {value}"

        # Check --flag value format (flag followed by path)
        elif token in PATH_FLAGS and i + 1 < len(tokens):
            value = tokens[i + 1]
            if not value.startswith("-") and _looks_like_path(value):
                raw = os.path.expanduser(value)
                path = Path(raw) if os.path.isabs(raw) else (repo_root / raw)
                if not validate_path(path, repo_root):
                    return f"Flag '{token}' path escapes repository: {value}"
            i += 1  # Skip the value token

        # Check positional arguments that look like paths
        elif not token.startswith("-"):
            if _looks_like_path(token):
                raw = os.path.expanduser(token)
                path = Path(raw) if os.path.isabs(raw) else (repo_root / raw)
                if not validate_path(path, repo_root):
                    return f"Path '{token}' escapes repository root"

        i += 1

    return None


class RunTestsTool(CodeTool):
    """Run test commands in workspace."""

    name = "code.shell.run_tests"
    description = (
        "Run test commands in the workspace. Only allows safe test command patterns."
    )

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "cmd": {
                    "type": "string",
                    "description": "The test command to run (e.g., 'pytest tests/', 'python -m pytest -v')",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Maximum execution time in seconds (default: 300)",
                    "default": 300,
                },
            },
            "required": ["cmd"],
        }

    def run(
        self,
        cmd: str,
        timeout: int = 300,
        repo_root: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        try:
            cwd = Path(repo_root).resolve() if repo_root else Path.cwd().resolve()

            if repo_root:
                if not cwd.exists() or not cwd.is_dir():
                    return {
                        "status": "error",
                        "error": f"Invalid repo_root: {repo_root}",
                    }
                if not validate_path(cwd, cwd):
                    return {
                        "status": "error",
                        "error": f"Path escape rejected: repo_root '{repo_root}' is not allowed",
                    }

            # Normalize python3 -> python for consistent prefix checking
            cmd_normalized = _normalize_python_cmd(cmd)
            cmd_lower = cmd_normalized.lower().strip()

            # Security check: validate command prefix
            if not any(
                cmd_lower.startswith(prefix) for prefix in ALLOWED_TEST_PREFIXES
            ):
                return {
                    "status": "error",
                    "error": f"Command not allowed. Must start with one of: {ALLOWED_TEST_PREFIXES}",
                }

            # Security: reject commands with disallowed patterns (normalized)
            for pattern in DISALLOWED_PATTERNS:
                if pattern in cmd_normalized:
                    return {
                        "status": "error",
                        "error": f"Command contains disallowed pattern '{pattern}'",
                    }

            # Validate paths in command (both positional and flag values)
            path_error = _validate_command_paths(cmd, cwd)
            if path_error:
                return {"status": "error", "error": path_error}

            # Set up environment
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"

            # Run the test command
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )

            success = result.returncode == 0

            # Truncate output if too long
            max_output = 10000
            stdout = result.stdout
            stderr = result.stderr

            if len(stdout) > max_output:
                stdout = (
                    stdout[:max_output] + f"\n... (truncated at {max_output} chars)"
                )
            if len(stderr) > max_output:
                stderr = (
                    stderr[:max_output] + f"\n... (truncated at {max_output} chars)"
                )

            return {
                "status": "success" if success else "failed",
                "command": cmd,
                "exit_code": result.returncode,
                "success": success,
                "stdout": stdout,
                "stderr": stderr,
            }

        except subprocess.TimeoutExpired:
            return {
                "status": "timeout",
                "error": f"Test command timed out after {timeout} seconds",
                "command": cmd,
            }
        except Exception as exc:
            logger.exception("RunTestsTool failed: %s", exc)
            return {"status": "error", "error": str(exc)}


__all__ = ["RunTestsTool"]
