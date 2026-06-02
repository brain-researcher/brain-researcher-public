"""Python sandbox tool for code execution."""

from __future__ import annotations

import io
import json
import logging
import subprocess
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from multiprocessing import Process, Queue
from typing import Any, Dict

from brain_researcher.services.agent.code_tool_registry import CodeTool

logger = logging.getLogger(__name__)

# Maximum output size
MAX_OUTPUT_SIZE = 50000


def _truncate(text: str, limit: int) -> str:
    if text is None:
        return ""
    return (
        text
        if len(text) <= limit
        else text[:limit] + f"\n... (truncated at {limit} chars)"
    )


def _run_code_in_subprocess(code: str, capture_output: bool) -> Dict[str, Any]:
    """Execute code in a child process and return a serializable result dict."""

    def _worker(code_str: str, capture: bool, queue: Queue) -> None:
        try:
            namespace = {"__builtins__": __builtins__, "__name__": "__sandbox__"}
            SandboxRunTool._add_safe_imports(namespace)

            if capture:
                stdout_capture = io.StringIO()
                stderr_capture = io.StringIO()
                with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                    try:
                        exec(compile(code_str, "<sandbox>", "exec"), namespace)
                        result_value = None
                    except SyntaxError:
                        result_value = eval(
                            compile(code_str, "<sandbox>", "eval"), namespace
                        )
                stdout = stdout_capture.getvalue()
                stderr = stderr_capture.getvalue()
            else:
                exec(compile(code_str, "<sandbox>", "exec"), namespace)
                result_value = None
                stdout = ""
                stderr = ""

            result_str = None
            if result_value is not None:
                try:
                    result_str = repr(result_value)
                except Exception:
                    result_str = f"<unprintable: {type(result_value).__name__}>"

            queue.put(
                {
                    "status": "success",
                    "stdout": stdout,
                    "stderr": stderr,
                    "result": result_str,
                }
            )
        except Exception as exc:  # pragma: no cover - captured for parent
            tb = traceback.format_exc()
            queue.put({"status": "error", "error": str(exc), "traceback": tb})

    queue: Queue = Queue()
    proc = Process(target=_worker, args=(code, capture_output, queue))
    proc.start()
    return queue, proc


def _build_runner_script(code: str, capture_output: bool) -> str:
    capture_flag = "True" if capture_output else "False"
    code_literal = json.dumps(code)
    return f"""
import json as _json
import io
import traceback
from contextlib import redirect_stdout, redirect_stderr

namespace = {{"__builtins__": __builtins__, "__name__": "__sandbox__"}}

try:
    import math, re, datetime, collections, itertools, functools, operator, statistics, random, hashlib, base64
    namespace.update({{
        "math": math,
        "json": _json,
        "re": re,
        "datetime": datetime,
        "collections": collections,
        "itertools": itertools,
        "functools": functools,
        "operator": operator,
        "statistics": statistics,
        "random": random,
        "hashlib": hashlib,
        "base64": base64,
    }})
except Exception:
    pass

try:
    import numpy as np
    namespace["np"] = np
    namespace["numpy"] = np
except Exception:
    pass

try:
    import pandas as pd
    namespace["pd"] = pd
    namespace["pandas"] = pd
except Exception:
    pass

capture_output = {capture_flag}
code = {code_literal}
stdout_capture = io.StringIO()
stderr_capture = io.StringIO()
result_value = None

try:
    with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
        try:
            exec(compile(code, "<sandbox>", "exec"), namespace)
            result_value = None
        except SyntaxError:
            result_value = eval(compile(code, "<sandbox>", "eval"), namespace)

    stdout = stdout_capture.getvalue()
    stderr = stderr_capture.getvalue()

    result_str = None
    if result_value is not None:
        try:
            result_str = repr(result_value)
        except Exception:
            result_str = f"<unprintable: {{type(result_value).__name__}}>"

    payload = {{
        "status": "success",
        "stdout": stdout if capture_output else "",
        "stderr": stderr if capture_output else "",
        "result": result_str,
    }}
except Exception as exc:
    payload = {{
        "status": "error",
        "error": str(exc),
        "traceback": traceback.format_exc(),
        "stdout": "",
        "stderr": "",
        "result": None,
    }}

print(_json.dumps(payload))
"""


def _run_code_via_subprocess(
    code: str,
    timeout: int,
    capture_output: bool,
) -> Dict[str, Any]:
    script = _build_runner_script(code, capture_output)
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return {
            "status": "timeout",
            "error": f"Execution timed out after {timeout} seconds",
        }

    if not stdout:
        return {
            "status": "error",
            "error": stderr.strip() or "No result returned from sandbox",
        }

    response_line = ""
    for line in reversed(stdout.splitlines()):
        if line.strip():
            response_line = line
            break

    try:
        payload = json.loads(response_line)
    except Exception:
        return {
            "status": "error",
            "error": "Invalid sandbox response",
            "stdout": stdout,
            "stderr": stderr,
        }

    if not capture_output:
        payload["stdout"] = ""
        payload["stderr"] = ""
    return payload


class SandboxRunTool(CodeTool):
    """Execute Python code in an isolated sandbox."""

    name = "code.sandbox.run"
    description = "Execute Python code in an isolated sandbox for validation, calculation, or quick experiments."

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Maximum execution time in seconds (default: 30)",
                    "default": 30,
                },
                "capture_output": {
                    "type": "boolean",
                    "description": "Whether to capture stdout/stderr (default: true)",
                    "default": True,
                },
            },
            "required": ["code"],
        }

    def run(
        self,
        code: str,
        timeout: int = 30,
        capture_output: bool = True,
        **kwargs,
    ) -> Dict[str, Any]:
        # Prefer a dedicated subprocess instead of multiprocessing.
        #
        # Forking a Python process after libraries that use native thread pools (e.g.,
        # HuggingFace tokenizers) have been imported can hang; subprocess avoids that
        # class of deadlock and is more stable in CI-like environments.
        result = _run_code_via_subprocess(code, timeout, capture_output)
        result["stdout"] = _truncate(result.get("stdout", ""), MAX_OUTPUT_SIZE)
        result["stderr"] = _truncate(result.get("stderr", ""), MAX_OUTPUT_SIZE)
        if result.get("result"):
            result["result"] = _truncate(str(result["result"]), MAX_OUTPUT_SIZE)
        return result

    @staticmethod
    def _add_safe_imports(namespace: Dict[str, Any]) -> None:
        """Add commonly used safe imports to namespace."""
        try:
            import base64
            import collections
            import datetime
            import functools
            import hashlib
            import itertools
            import json
            import math
            import operator
            import random
            import re
            import statistics

            namespace.update(
                {
                    "math": math,
                    "json": json,
                    "re": re,
                    "datetime": datetime,
                    "collections": collections,
                    "itertools": itertools,
                    "functools": functools,
                    "operator": operator,
                    "statistics": statistics,
                    "random": random,
                    "hashlib": hashlib,
                    "base64": base64,
                }
            )
        except ImportError:
            pass

        # Try to add numpy/pandas if available (common for data work)
        try:
            import numpy as np

            namespace["np"] = np
            namespace["numpy"] = np
        except ImportError:
            pass

        try:
            import pandas as pd

            namespace["pd"] = pd
            namespace["pandas"] = pd
        except ImportError:
            pass


__all__ = ["SandboxRunTool", "MAX_OUTPUT_SIZE"]
