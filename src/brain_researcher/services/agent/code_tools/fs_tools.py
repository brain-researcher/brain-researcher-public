"""File system tools for code editing.

Provides:
- ReadFileTool: Read file content with optional line range
- ReadDirTool: List directory with content preview
- ApplyPatchTool: Apply unified diff patches
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
from glob import glob
from pathlib import Path
from typing import Any, Dict, List, Optional

from brain_researcher.services.agent.code_tool_registry import CodeTool
from brain_researcher.services.agent.code_tools.utils import validate_path as _validate_path

logger = logging.getLogger(__name__)


class ReadFileTool(CodeTool):
    """Read file content with optional line range."""

    name = "code.fs.read_file"
    description = "Read file content with optional line range. Returns the content as text."

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to read (absolute or relative to repo root)",
                },
                "max_bytes": {
                    "type": "integer",
                    "description": "Maximum bytes to read (default: 50000)",
                    "default": 50000,
                },
                "start_line": {
                    "type": "integer",
                    "description": "Start reading from this line (1-indexed)",
                },
                "end_line": {
                    "type": "integer",
                    "description": "Stop reading at this line (inclusive)",
                },
            },
            "required": ["path"],
        }

    def run(
        self,
        path: str,
        max_bytes: int = 50000,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        repo_root: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        try:
            # Resolve path
            file_path = Path(path)
            root_path = Path(repo_root) if repo_root else Path.cwd()
            if not file_path.is_absolute():
                file_path = root_path / file_path

            # Security: validate path stays within repo_root
            if not _validate_path(file_path, root_path):
                return {
                    "status": "error",
                    "error": f"Path escape rejected: {path} is outside repository root",
                }

            if not file_path.exists():
                return {"status": "error", "error": f"File not found: {file_path}"}

            if not file_path.is_file():
                return {"status": "error", "error": f"Not a file: {file_path}"}

            # Read file content
            content = file_path.read_text(encoding="utf-8", errors="replace")

            # Apply line range filter
            if start_line is not None or end_line is not None:
                lines = content.splitlines(keepends=True)
                start_idx = (start_line - 1) if start_line else 0
                end_idx = end_line if end_line else len(lines)
                content = "".join(lines[start_idx:end_idx])

            # Truncate if too long
            if len(content) > max_bytes:
                content = content[:max_bytes] + f"\n... (truncated at {max_bytes} bytes)"

            return {
                "status": "success",
                "path": str(file_path),
                "content": content,
                "size": len(content),
            }

        except Exception as exc:
            logger.exception("ReadFileTool failed: %s", exc)
            return {"status": "error", "error": str(exc)}


class ReadDirTool(CodeTool):
    """List directory with optional content preview."""

    name = "code.fs.read_dir"
    description = "List files matching a glob pattern with optional content preview."

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "glob_pattern": {
                    "type": "string",
                    "description": "Glob pattern to match files (e.g., '**/*.py', 'src/*.ts')",
                },
                "max_files": {
                    "type": "integer",
                    "description": "Maximum number of files to return (default: 20)",
                    "default": 20,
                },
                "max_bytes_per_file": {
                    "type": "integer",
                    "description": "Maximum bytes to preview per file (default: 2000)",
                    "default": 2000,
                },
                "include_content": {
                    "type": "boolean",
                    "description": "Whether to include file content preview (default: false)",
                    "default": False,
                },
            },
            "required": ["glob_pattern"],
        }

    def run(
        self,
        glob_pattern: str,
        max_files: int = 20,
        max_bytes_per_file: int = 2000,
        include_content: bool = False,
        repo_root: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        try:
            # Resolve base path
            base_path = Path(repo_root) if repo_root else Path.cwd()

            # Security: reject patterns that attempt path escape
            if glob_pattern.startswith("/") or ".." in glob_pattern:
                return {
                    "status": "error",
                    "error": f"Path escape rejected: pattern '{glob_pattern}' not allowed",
                }

            # Find matching files
            pattern = str(base_path / glob_pattern)
            matches = sorted(glob(pattern, recursive=True))[:max_files]

            files = []
            for match_path in matches:
                path = Path(match_path)
                if not path.is_file():
                    continue

                # Security: validate each matched file is within repo_root
                if not _validate_path(path, base_path):
                    continue

                file_info = {
                    "path": str(path),
                    "relative_path": str(path.relative_to(base_path)) if path.is_relative_to(base_path) else str(path),
                    "size": path.stat().st_size,
                }

                if include_content:
                    try:
                        content = path.read_text(encoding="utf-8", errors="replace")
                        if len(content) > max_bytes_per_file:
                            content = content[:max_bytes_per_file] + f"\n... (truncated)"
                        file_info["content"] = content
                    except Exception as exc:
                        file_info["content"] = f"(error reading: {exc})"

                files.append(file_info)

            return {
                "status": "success",
                "pattern": glob_pattern,
                "base_path": str(base_path),
                "files": files,
                "count": len(files),
            }

        except Exception as exc:
            logger.exception("ReadDirTool failed: %s", exc)
            return {"status": "error", "error": str(exc)}


def _extract_patch_targets(patch: str) -> List[str]:
    """Extract target file paths from a unified diff patch.

    Looks for lines starting with:
    - '--- ' (original file)
    - '+++ ' (new file)
    - 'diff --git a/... b/...' (git diff format)
    """
    targets = set()
    for line in patch.splitlines():
        # Match +++ b/path or +++ path (unified diff target)
        if line.startswith("+++ "):
            path = line[4:].strip()
            # Remove timestamps if present
            path = path.split("\t")[0]
            # Handle git diff format: +++ b/path
            if path.startswith("b/"):
                path = path[2:]
            if path and path != "/dev/null":
                targets.add(path)
        # Match diff --git a/path b/path
        elif line.startswith("diff --git "):
            match = re.search(r"diff --git a/(.+?) b/(.+)$", line)
            if match:
                targets.add(match.group(2))
    return list(targets)


class ApplyPatchTool(CodeTool):
    """Apply unified diff patch to files."""

    name = "code.fs.apply_patch"
    description = "Apply a unified diff patch to files. Supports dry-run mode to preview changes."

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "patch": {
                    "type": "string",
                    "description": "The unified diff patch content to apply",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "If true, only check if patch applies cleanly without modifying files (default: true)",
                    "default": True,
                },
            },
            "required": ["patch"],
        }

    def run(
        self,
        patch: str,
        dry_run: bool = True,
        repo_root: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        try:
            cwd = Path(repo_root) if repo_root else Path.cwd()

            # Security: validate all target paths in patch stay within repo_root
            target_paths = _extract_patch_targets(patch)
            for target in target_paths:
                target_path = cwd / target
                if not _validate_path(target_path, cwd):
                    return {
                        "status": "error",
                        "error": f"Path escape rejected: patch targets '{target}' outside repository root",
                    }

            # Write patch to temp file
            with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False) as f:
                f.write(patch)
                patch_file = f.name

            try:
                # Build patch command
                cmd = ["patch", "-p0", "-s"]
                if dry_run:
                    cmd.append("--dry-run")
                cmd.extend(["-i", patch_file])

                # Run patch command
                result = subprocess.run(
                    cmd,
                    cwd=str(cwd),
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

                if result.returncode == 0:
                    return {
                        "status": "success",
                        "dry_run": dry_run,
                        "message": "Patch applied successfully" if not dry_run else "Patch would apply cleanly",
                        "stdout": result.stdout,
                    }
                else:
                    return {
                        "status": "error",
                        "error": f"Patch failed: {result.stderr}",
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                    }

            finally:
                # Clean up temp file
                os.unlink(patch_file)

        except subprocess.TimeoutExpired:
            return {"status": "error", "error": "Patch command timed out"}
        except Exception as exc:
            logger.exception("ApplyPatchTool failed: %s", exc)
            return {"status": "error", "error": str(exc)}


__all__ = ["ReadFileTool", "ReadDirTool", "ApplyPatchTool"]
