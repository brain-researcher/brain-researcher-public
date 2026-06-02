"""Minimal local execution runner for the coding agent loop.

This runner favors safety and portability over completeness: it attempts a
lightweight syntax/test check when file paths are provided and fails loud when
no verification evidence exists.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from brain_researcher.services.llm_gateway.codegen.context import ExecutionResult
from brain_researcher.services.llm_gateway.codegen.execution_gate import (
    build_verification_plan,
)


def run_checks(
    file_paths: list[str] | None = None, test_command: str | None = None
) -> ExecutionResult:
    """Execute a lightweight validation step.

    - If test_command is provided, run it in a shell.
    - Else, if file_paths exist, run `python -m py_compile` on each.
    - Else, fail because the constitution forbids silent success.
    """

    start = time.time()

    if test_command:
        try:
            proc = subprocess.run(
                test_command,
                shell=True,
                capture_output=True,
                text=True,
                check=False,
            )
            return ExecutionResult(
                success=proc.returncode == 0,
                stdout=proc.stdout,
                stderr=proc.stderr,
                exit_code=proc.returncode,
                duration_ms=int((time.time() - start) * 1000),
            )
        except Exception as exc:  # pragma: no cover - defensive
            return ExecutionResult(
                success=False,
                stderr=str(exc),
                exit_code=None,
                duration_ms=int((time.time() - start) * 1000),
            )

    plan = build_verification_plan(
        workdir=Path.cwd(),
        materialized=[Path(path) for path in (file_paths or [])],
        touched=(),
        test_command=test_command,
    )
    if plan.mode == "none":
        return ExecutionResult(
            success=False,
            stdout="",
            stderr=plan.reason or "Verification gate rejected execution",
            exit_code=1,
            duration_ms=int((time.time() - start) * 1000),
        )

    if file_paths:
        errors = []
        for p in plan.candidate_paths:
            proc = subprocess.run(
                ["python", "-m", "py_compile", str(p)],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                errors.append(
                    proc.stderr or proc.stdout or f"py_compile failed for {p}"
                )

        duration = int((time.time() - start) * 1000)
        if errors:
            return ExecutionResult(
                success=False,
                stdout="",
                stderr="\n".join(errors),
                exit_code=1,
                duration_ms=duration,
            )
        return ExecutionResult(
            success=True, stdout="", stderr="", exit_code=0, duration_ms=duration
        )

    return ExecutionResult(
        success=False,
        stdout="",
        stderr=plan.reason or "Verification gate rejected execution",
        exit_code=1,
        duration_ms=int((time.time() - start) * 1000),
    )
