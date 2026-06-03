"""Gemini CLI wrappers exposed as agent tools.

These wrappers shell out to the local `gemini` CLI binary. They are intentionally
thin and marked dangerous in the catalog where appropriate. Chat whitelist should
only include the read/list/search/web_fetch/google_search variants.
"""

from __future__ import annotations

import json
import subprocess

from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


def _run_cli(
    args: list[str], stdin: str | None = None, timeout: int = 20
) -> ToolResult:
    proc = subprocess.run(
        args,
        input=stdin.encode("utf-8") if stdin is not None else None,
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    if proc.returncode != 0:
        return ToolResult(status="error", error=proc.stderr.decode("utf-8", "replace"))
    try:
        data = json.loads(proc.stdout.decode("utf-8"))
    except Exception:
        data = proc.stdout.decode("utf-8", "replace")
    return ToolResult(status="success", data=data)


class GeminiListDirectory(NeuroToolWrapper):
    DANGEROUS = False
    TAGS = ["fs", "coding", "read_only"]
    COST_HINT = "cheap"

    class Args(BaseModel):
        path: str = Field(default=".", description="Directory to list")
        recursive: bool = Field(
            default=False, description="Recurse into subdirectories"
        )

    def get_tool_name(self) -> str:
        return "gemini.list_directory"

    def get_tool_description(self) -> str:
        return "List files in a directory via Gemini CLI."

    def get_args_schema(self):
        return self.Args

    def _run(self, path: str = ".", recursive: bool = False) -> ToolResult:
        args = ["gemini", "list", path]
        if recursive:
            args.append("--recursive")
        return _run_cli(args)


class GeminiReadFile(NeuroToolWrapper):
    DANGEROUS = False
    TAGS = ["fs", "coding", "read_only"]
    COST_HINT = "cheap"

    class Args(BaseModel):
        path: str = Field(description="Path to file")
        max_bytes: int = Field(default=8000, description="Maximum bytes to read")
        offset: int = Field(default=0, description="Byte offset")

    def get_tool_name(self) -> str:
        return "gemini.read_file"

    def get_tool_description(self) -> str:
        return "Read a file (first few KB) via Gemini CLI."

    def get_args_schema(self):
        return self.Args

    def _run(self, path: str, max_bytes: int = 8000, offset: int = 0) -> ToolResult:
        args = [
            "gemini",
            "read",
            path,
            "--max-bytes",
            str(max_bytes),
            "--offset",
            str(offset),
        ]
        return _run_cli(args)


class GeminiSearchText(NeuroToolWrapper):
    DANGEROUS = False
    TAGS = ["fs", "coding", "read_only"]
    COST_HINT = "cheap"

    class Args(BaseModel):
        query: str = Field(description="Search pattern")
        root: str = Field(default=".", description="Root directory")
        max_results: int = Field(default=200, description="Maximum results")

    def get_tool_name(self) -> str:
        return "gemini.search_text"

    def get_tool_description(self) -> str:
        return "Search text in files (Gemini CLI grep)."

    def get_args_schema(self):
        return self.Args

    def _run(self, query: str, root: str = ".", max_results: int = 200) -> ToolResult:
        args = ["gemini", "search", query, "--root", root, "--limit", str(max_results)]
        return _run_cli(args)


class GeminiWebFetch(NeuroToolWrapper):
    DANGEROUS = False
    TAGS = ["net", "http"]
    COST_HINT = "normal"

    class Args(BaseModel):
        url: str = Field(description="URL to fetch")
        timeout: int = Field(default=20, description="Timeout seconds")

    def get_tool_name(self) -> str:
        return "gemini.web_fetch"

    def get_tool_description(self) -> str:
        return "Fetch a URL via Gemini CLI."

    def get_args_schema(self):
        return self.Args

    def _run(self, url: str, timeout: int = 20) -> ToolResult:
        args = ["gemini", "web-fetch", url, "--timeout", str(timeout)]
        return _run_cli(args, timeout=timeout)


class GeminiGoogleSearch(NeuroToolWrapper):
    DANGEROUS = False
    TAGS = ["net", "search"]
    COST_HINT = "normal"

    class Args(BaseModel):
        query: str = Field(description="Search query")
        num_results: int = Field(default=5, description="Number of results")

    def get_tool_name(self) -> str:
        return "gemini.google_search"

    def get_tool_description(self) -> str:
        return "Google search via Gemini CLI."

    def get_args_schema(self):
        return self.Args

    def _run(self, query: str, num_results: int = 5) -> ToolResult:
        args = ["gemini", "google-search", query, "--limit", str(num_results)]
        return _run_cli(args)


class GeminiWriteFile(NeuroToolWrapper):
    DANGEROUS = True
    TAGS = ["fs", "coding", "write"]
    COST_HINT = "normal"

    class Args(BaseModel):
        path: str = Field(description="Path to write")
        content: str = Field(description="Content to write")

    def get_tool_name(self) -> str:
        return "gemini.write_file"

    def get_tool_description(self) -> str:
        return "Write text to a file (dangerous; not chat-safe)."

    def get_args_schema(self):
        return self.Args

    def _run(self, path: str, content: str) -> ToolResult:
        args = ["gemini", "write", path]
        return _run_cli(args, stdin=content)


class GeminiReplace(NeuroToolWrapper):
    DANGEROUS = True
    TAGS = ["fs", "coding", "write"]
    COST_HINT = "normal"

    class Args(BaseModel):
        patch: str = Field(description="Patch text")

    def get_tool_name(self) -> str:
        return "gemini.replace"

    def get_tool_description(self) -> str:
        return "Apply a replace/patch operation (dangerous; not chat-safe)."

    def get_args_schema(self):
        return self.Args

    def _run(self, patch: str) -> ToolResult:
        args = ["gemini", "replace"]
        return _run_cli(args, stdin=patch)


class GeminiRunShell(NeuroToolWrapper):
    DANGEROUS = True
    TAGS = ["shell", "coding", "dangerous"]
    COST_HINT = "expensive"

    class Args(BaseModel):
        command: str = Field(description="Command to run")
        timeout: int = Field(default=20, description="Timeout seconds")

    def get_tool_name(self) -> str:
        return "gemini.run_shell"

    def get_tool_description(self) -> str:
        return "Run a shell command via Gemini CLI (dangerous)."

    def get_args_schema(self):
        return self.Args

    def _run(self, command: str, timeout: int = 20) -> ToolResult:
        args = ["gemini", "shell", command, "--timeout", str(timeout)]
        return _run_cli(args, timeout=timeout)


class GeminiWriteTodos(NeuroToolWrapper):
    DANGEROUS = True
    TAGS = ["planning", "write"]
    COST_HINT = "normal"

    class Args(BaseModel):
        context: str = Field(description="Context for TODO generation")

    def get_tool_name(self) -> str:
        return "gemini.write_todos"

    def get_tool_description(self) -> str:
        return "Generate todos via Gemini CLI (writes)."

    def get_args_schema(self):
        return self.Args

    def _run(self, context: str) -> ToolResult:
        args = ["gemini", "write-todos"]
        return _run_cli(args, stdin=context)


class GeminiSaveMemory(NeuroToolWrapper):
    DANGEROUS = True
    TAGS = ["memory", "write"]
    COST_HINT = "normal"

    class Args(BaseModel):
        content: str = Field(description="Content to save")

    def get_tool_name(self) -> str:
        return "gemini.save_memory"

    def get_tool_description(self) -> str:
        return "Persist context via Gemini CLI (writes)."

    def get_args_schema(self):
        return self.Args

    def _run(self, content: str) -> ToolResult:
        args = ["gemini", "save-memory"]
        return _run_cli(args, stdin=content)


class GeminiCodebaseInvestigator(NeuroToolWrapper):
    DANGEROUS = True
    TAGS = ["analysis", "coding", "expensive"]
    COST_HINT = "expensive"

    class Args(BaseModel):
        query: str = Field(description="Investigation prompt")
        root: str = Field(default=".", description="Repo root")

    def get_tool_name(self) -> str:
        return "gemini.codebase_investigator"

    def get_tool_description(self) -> str:
        return "Run Gemini codebase investigator (slow/expensive)."

    def get_args_schema(self):
        return self.Args

    def _run(self, query: str, root: str = ".") -> ToolResult:
        args = ["gemini", "codebase-investigator", query, "--root", root]
        return _run_cli(args)


def get_all_tools():
    return [
        GeminiListDirectory(),
        GeminiReadFile(),
        GeminiSearchText(),
        GeminiWebFetch(),
        GeminiGoogleSearch(),
        GeminiWriteFile(),
        GeminiReplace(),
        GeminiRunShell(),
        GeminiWriteTodos(),
        GeminiSaveMemory(),
        GeminiCodebaseInvestigator(),
    ]
