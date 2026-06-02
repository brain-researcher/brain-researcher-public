"""Temporary workspace management for the coding agent loop."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path

from brain_researcher.services.llm_gateway.codegen.context import (
    ExecutionResult,
    FileSnippet,
)
from brain_researcher.services.llm_gateway.codegen.execution_gate import (
    build_verification_plan,
)


class Workspace:
    """Manages a temp working directory for patch/apply/run flow."""

    def __init__(self, repo_root: Path, workdir: Path | None = None):
        self.repo_root = repo_root
        if workdir is not None:
            self.workdir_obj = Path(workdir)
        else:
            # tempfile.gettempdir() is cached and may point to a path that was
            # deleted mid-process (e.g., when pytest wipes --basetemp). Ensure
            # it exists before using it, and fall back to a repo-local temp dir
            # if it's not writable.
            temp_root = Path(tempfile.gettempdir())
            try:
                temp_root.mkdir(parents=True, exist_ok=True)
                self.workdir_obj = Path(
                    tempfile.mkdtemp(prefix="codegen_ws_", dir=str(temp_root))
                )
            except Exception:
                fallback_root = self.repo_root / ".tmp"
                fallback_root.mkdir(parents=True, exist_ok=True)
                self.workdir_obj = Path(
                    tempfile.mkdtemp(prefix="codegen_ws_", dir=str(fallback_root))
                )
        self.workdir_obj.mkdir(parents=True, exist_ok=True)
        self._materialized: list[Path] = []
        self._touched: set[str] = set()

    @property
    def path(self) -> Path:
        return self.workdir_obj

    def materialize_files(self, files: Sequence[FileSnippet] | Sequence[str]) -> None:
        """Copy referenced files from repo_root into the workspace."""

        for item in files:
            if isinstance(item, FileSnippet):
                src_rel = Path(item.path)
            else:
                src_rel = Path(item)
            src = (self.repo_root / src_rel).resolve()
            if not src.exists() or not src.is_file():
                continue
            dest = self.workdir_obj / src_rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            self._materialized.append(src_rel)

    def apply_patch(self, patch_text: str) -> None:
        """Apply a unified diff patch inside the workspace."""

        if not patch_text.strip():
            return

        self._record_touched_files(patch_text)
        env = os.environ.copy()
        # Ensure patch uses a writable tmp directory (important in sandboxed/CI).
        env.setdefault("TMPDIR", str(self.workdir_obj))
        proc = subprocess.run(
            ["patch", "-p0", "-s"],
            input=patch_text.encode("utf-8"),
            capture_output=True,
            cwd=str(self.workdir_obj),
            env=env,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                proc.stderr.decode("utf-8", "replace")
                or proc.stdout.decode("utf-8", "replace")
            )

    def run_checks(self, test_command: str | None = None) -> ExecutionResult:
        """Run tests or py_compile within the workspace."""

        plan = build_verification_plan(
            workdir=self.workdir_obj,
            materialized=self._materialized,
            touched=self._touched,
            test_command=test_command,
        )
        if plan.mode == "none":
            return ExecutionResult(
                success=False,
                stdout="",
                stderr=plan.reason or "Verification gate rejected execution",
                exit_code=1,
            )

        if test_command:
            if not _is_allowed_command(test_command):
                return ExecutionResult(
                    success=False,
                    stdout="",
                    stderr=f"Command not allowed: {test_command}",
                    exit_code=1,
                )
            proc = subprocess.run(
                test_command,
                shell=True,
                cwd=str(self.workdir_obj),
                capture_output=True,
                text=True,
                check=False,
            )
            return ExecutionResult(
                success=proc.returncode == 0,
                stdout=proc.stdout,
                stderr=proc.stderr,
                exit_code=proc.returncode,
            )

        errors = []
        for full in plan.candidate_paths:
            proc = subprocess.run(
                ["python", "-m", "py_compile", str(full)],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                rel = full.relative_to(self.workdir_obj)
                errors.append(
                    proc.stderr or proc.stdout or f"py_compile failed for {rel}"
                )

        if errors:
            return ExecutionResult(
                success=False, stdout="", stderr="\n".join(errors), exit_code=1
            )
        return ExecutionResult(success=True, stdout="", stderr="", exit_code=0)

    def files_touched(self) -> list[str]:
        return (
            sorted(self._touched)
            if self._touched
            else [str(p) for p in self._materialized]
        )

    def _record_touched_files(self, patch_text: str) -> None:
        for line in patch_text.splitlines():
            if line.startswith("+++ "):
                path = line[4:].strip()
                # strip a/ or b/ prefixes if present
                if path.startswith("a/") or path.startswith("b/"):
                    path = path[2:]
                self._touched.add(path)
            elif line.startswith("--- "):
                path = line[4:].strip()
                if path.startswith("a/") or path.startswith("b/"):
                    path = path[2:]
                self._touched.add(path)


__all__ = ["Workspace"]


def apply_patches_to_repo(patches: list[str], repo_root: Path) -> list[str]:
    """Apply patches directly to the repo_root, returning patch command logs."""

    logs: list[str] = []
    if not patches:
        return logs

    for patch_text in patches:
        if not patch_text.strip():
            continue
        proc = subprocess.run(
            ["patch", "-p0", "-s"],
            input=patch_text.encode("utf-8"),
            capture_output=True,
            cwd=str(repo_root),
            check=False,
        )
        out = proc.stdout.decode("utf-8", "replace")
        err = proc.stderr.decode("utf-8", "replace")
        logs.append(out or err)
        if proc.returncode != 0:
            raise RuntimeError(err or out or "patch failed")
    return logs


def _is_allowed_command(cmd: str) -> bool:
    cmd_strip = cmd.strip()
    allowed_prefixes = ("pytest", "python -m ", "python ")
    return cmd_strip.startswith(allowed_prefixes)
