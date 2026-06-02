"""Code search tool using ripgrep-style matching."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from brain_researcher.services.agent.code_tool_registry import CodeTool
from brain_researcher.services.agent.code_tools.utils import (
    validate_path as _validate_path,
)

logger = logging.getLogger(__name__)


class CodeSearchTool(CodeTool):
    """Search code with ripgrep-style matching."""

    name = "code.search"
    description = "Search code files for a pattern using ripgrep-style matching. Returns matching lines with context."

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search pattern (regex supported)",
                },
                "glob_pattern": {
                    "type": "string",
                    "description": "Glob pattern to filter files (e.g., '*.py', '**/*.ts')",
                    "default": "**/*",
                },
                "max_matches": {
                    "type": "integer",
                    "description": "Maximum number of matches to return (default: 50)",
                    "default": 50,
                },
                "context_lines": {
                    "type": "integer",
                    "description": "Number of context lines before/after match (default: 2)",
                    "default": 2,
                },
                "case_sensitive": {
                    "type": "boolean",
                    "description": "Whether search is case-sensitive (default: false)",
                    "default": False,
                },
            },
            "required": ["query"],
        }

    def run(
        self,
        query: str,
        glob_pattern: str = "**/*",
        max_matches: int = 50,
        context_lines: int = 2,
        case_sensitive: bool = False,
        repo_root: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        try:
            cwd = Path(repo_root) if repo_root else Path.cwd()

            # Security: reject glob patterns that attempt path escape
            if glob_pattern.startswith("/") or ".." in glob_pattern:
                return {
                    "status": "error",
                    "error": f"Path escape rejected: glob pattern '{glob_pattern}' not allowed",
                }

            # Try ripgrep first, fall back to grep
            try:
                return self._search_with_rg(
                    query, glob_pattern, max_matches, context_lines, case_sensitive, cwd
                )
            except FileNotFoundError:
                logger.debug("ripgrep not found, falling back to grep")
                return self._search_with_grep(
                    query, glob_pattern, max_matches, context_lines, case_sensitive, cwd
                )

        except Exception as exc:
            logger.exception("CodeSearchTool failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    def _search_with_rg(
        self,
        query: str,
        glob_pattern: str,
        max_matches: int,
        context_lines: int,
        case_sensitive: bool,
        cwd: Path,
    ) -> Dict[str, Any]:
        """Search using ripgrep."""
        cmd = ["rg", "--json"]

        if not case_sensitive:
            cmd.append("-i")

        if context_lines > 0:
            cmd.extend(["-C", str(context_lines)])

        cmd.extend(["-m", str(max_matches)])

        if glob_pattern != "**/*":
            cmd.extend(["-g", glob_pattern])

        cmd.append(query)

        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=60,
        )

        # Parse ripgrep JSON output
        matches = []
        import json

        for line in result.stdout.splitlines():
            try:
                data = json.loads(line)
                if data.get("type") == "match":
                    match_data = data["data"]
                    matches.append(
                        {
                            "path": match_data["path"]["text"],
                            "line_number": match_data["line_number"],
                            "line": match_data["lines"]["text"].rstrip(),
                        }
                    )
            except (json.JSONDecodeError, KeyError):
                continue

        return {
            "status": "success",
            "query": query,
            "pattern": glob_pattern,
            "matches": matches[:max_matches],
            "count": len(matches),
            "truncated": len(matches) > max_matches,
        }

    def _search_with_grep(
        self,
        query: str,
        glob_pattern: str,
        max_matches: int,
        context_lines: int,
        case_sensitive: bool,
        cwd: Path,
    ) -> Dict[str, Any]:
        """Fallback search using grep."""
        cmd = ["grep", "-r", "-n"]

        if not case_sensitive:
            cmd.append("-i")

        if context_lines > 0:
            cmd.extend(["-C", str(context_lines)])

        cmd.extend(["-m", str(max_matches)])

        if glob_pattern != "**/*":
            cmd.extend(["--include", glob_pattern])

        cmd.append(query)
        cmd.append(".")

        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=60,
        )

        # Parse grep output
        matches = []
        for line in result.stdout.splitlines()[:max_matches]:
            parts = line.split(":", 2)
            if len(parts) >= 3:
                matches.append(
                    {
                        "path": parts[0],
                        "line_number": int(parts[1]) if parts[1].isdigit() else 0,
                        "line": parts[2],
                    }
                )

        return {
            "status": "success",
            "query": query,
            "pattern": glob_pattern,
            "matches": matches,
            "count": len(matches),
            "truncated": len(matches) >= max_matches,
        }


__all__ = ["CodeSearchTool"]
