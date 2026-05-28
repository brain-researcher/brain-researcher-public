"""Helpers to gather file snippets for the coding agent via gemini.fs."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from typing import List, Optional, Protocol, Sequence

from brain_researcher.services.agent.codegen.context import FileSnippet


class GeminiFsClient(Protocol):
    """Minimal protocol for gemini.fs interaction."""

    async def search_text(self, query: str, root: str, max_results: int = 200) -> Sequence[dict]:
        ...

    async def read_file(self, path: str, max_bytes: int = 8000, offset: int = 0) -> str:
        ...


class GeminiCliFsClient:
    """Lightweight asyncio wrapper around the `gemini` CLI."""

    def __init__(self, timeout: int = 20):
        self.timeout = timeout

    async def search_text(self, query: str, root: str, max_results: int = 200) -> Sequence[dict]:
        args = ["gemini", "search", query, "--root", root, "--limit", str(max_results)]
        return await asyncio.to_thread(_run_cli_json, args, self.timeout)

    async def read_file(self, path: str, max_bytes: int = 8000, offset: int = 0) -> str:
        args = ["gemini", "read", path, "--max-bytes", str(max_bytes), "--offset", str(offset)]
        return await asyncio.to_thread(_run_cli_text, args, self.timeout)


def _run_cli_json(args: List[str], timeout: int) -> Sequence[dict]:
    proc = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace"))
    data = proc.stdout.decode("utf-8", "replace")
    try:
        loaded = json.loads(data)
        if isinstance(loaded, list):
            return loaded
        if isinstance(loaded, dict):
            return loaded.get("results", [])
        return []
    except json.JSONDecodeError:
        return []


def _run_cli_text(args: List[str], timeout: int) -> str:
    proc = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace"))
    return proc.stdout.decode("utf-8", "replace")


def _guess_language(path: str) -> Optional[str]:
    ext = os.path.splitext(path)[1].lower()
    return {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".jsx": "javascript",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".md": "markdown",
        ".sh": "bash",
    }.get(ext)


def _truncate_snippet(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 10] + "\n... (truncated)"


async def build_fs_context_for_task(
    query: str,
    repo_root: Optional[str],
    fs_client: GeminiFsClient,
    max_files: int = 5,
    max_chars_per_file: int = 4000,
) -> List[FileSnippet]:
    """Search and gather file snippets related to the query using gemini.fs."""

    if not query:
        return []

    root = repo_root or "."
    try:
        hits = await fs_client.search_text(query=query, root=root, max_results=max_files * 6)
    except Exception:
        return []

    seen = set()
    snippets: List[FileSnippet] = []

    for hit in hits:
        if len(snippets) >= max_files:
            break
        path = hit.get("path") or hit.get("file")
        if not path or path in seen:
            continue
        seen.add(path)

        start_line = hit.get("line") or hit.get("start_line")
        try:
            content = await fs_client.read_file(path=path, max_bytes=max_chars_per_file)
        except Exception:
            continue

        snippet = _truncate_snippet(content, max_chars_per_file)
        end_line: Optional[int] = None
        if start_line is not None:
            try:
                start_int = int(start_line)
                end_line = start_int + snippet.count("\n")
                start_line = start_int
            except Exception:
                start_line = None

        snippets.append(
            FileSnippet(
                path=path,
                snippet=snippet,
                language=_guess_language(path),
                start_line=start_line,
                end_line=end_line,
            )
        )

    return snippets


def build_fs_context_for_task_sync(
    query: str,
    repo_root: Optional[str],
    fs_client: GeminiFsClient,
    max_files: int = 5,
    max_chars_per_file: int = 4000,
) -> List[FileSnippet]:
    """Synchronous wrapper for environments without an event loop."""

    try:
        return asyncio.run(
            build_fs_context_for_task(
                query=query,
                repo_root=repo_root,
                fs_client=fs_client,
                max_files=max_files,
                max_chars_per_file=max_chars_per_file,
            )
        )
    except RuntimeError:
        # Fall back to existing loop if we're already inside one.
        loop = asyncio.get_event_loop()
        if loop.is_running():
            return []
        return loop.run_until_complete(
            build_fs_context_for_task(
                query=query,
                repo_root=repo_root,
                fs_client=fs_client,
                max_files=max_files,
                max_chars_per_file=max_chars_per_file,
            )
        )


__all__ = [
    "GeminiFsClient",
    "GeminiCliFsClient",
    "build_fs_context_for_task",
    "build_fs_context_for_task_sync",
]
