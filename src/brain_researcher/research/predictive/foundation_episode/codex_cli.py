"""Fail-closed Codex CLI transport for the foundation controller.

The controller is an agentic CLI surface, not an OpenAI Responses request.  This
module deliberately keeps the invocation fixed, sends the prompt only on stdin,
and validates the complete JSONL event stream before returning its final JSON.
Raw event streams, stderr, prompts, and reasoning are intentionally transient.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from brain_researcher.research.predictive.foundation_episode.contracts import (
    FoundationEpisodeError,
)

CODEX_CLI_BINARY = os.environ.get("BR_HCP_CODEX_BINARY", "codex")
CODEX_CLI_VERSION = os.environ.get("BR_HCP_CODEX_VERSION", "0.146.1")
CODEX_CLI_MODEL = os.environ.get("BR_HCP_CODEX_MODEL", "gpt-5.6-sol")
CODEX_CLI_REASONING_EFFORT = os.environ.get("BR_HCP_CODEX_REASONING", "max")
CODEX_CLI_TIMEOUT_SECONDS = float(os.environ.get("BR_HCP_CODEX_TIMEOUT_SECONDS", "120"))
CODEX_CLI_VERSION_TIMEOUT_SECONDS = float(os.environ.get("BR_HCP_CODEX_VERSION_TIMEOUT_SECONDS", "10"))

_EVENT_TYPES = frozenset(
    {
        "thread.started",
        "turn.started",
        "item.started",
        "item.updated",
        "item.completed",
        "turn.completed",
        "turn.failed",
        "error",
    }
)
_ITEM_TYPES = frozenset(
    {
        "agent_message",
        "reasoning",
        "command_execution",
        "file_change",
        "mcp_tool_call",
        "collab_tool_call",
        "web_search",
        "todo_list",
        "error",
    }
)
_FORBIDDEN_ITEM_TYPES = frozenset(
    {
        "command_execution",
        "file_change",
        "mcp_tool_call",
        "collab_tool_call",
        "web_search",
        "todo_list",
        "error",
    }
)
# Codex 0.146.1 emits these response-only items directly as completed events.
# Every other recognized item kind is forbidden on this controller surface.
_COMPLETION_ONLY_ITEM_TYPES = frozenset({"agent_message", "reasoning"})
_VERSION_PATTERN = re.compile(r"\b(\d+\.\d+\.\d+)\b")


class CodexCLIError(FoundationEpisodeError):
    """The fixed Codex CLI transport failed closed."""


class CodexCLIExecutionError(CodexCLIError):
    """The process or event stream was unsafe or incomplete."""


class CodexCLIValidationError(CodexCLIError):
    """The final controller JSON did not validate as JSON."""


class CodexCLIUnsafeEventError(CodexCLIExecutionError):
    """The agentic CLI emitted an event that the controller forbids."""

    def __init__(self, message: str, *, item_type: str, tool_event_count: int) -> None:
        super().__init__(message)
        self.item_type = item_type
        self.tool_event_count = tool_event_count


@dataclass(frozen=True, slots=True)
class CodexCLIResult:
    """The only controller-call data suitable for persistence."""

    final_json: str
    sanitized_argv: tuple[str, ...]
    cli_version: str
    validation_result: Mapping[str, object]
    tool_event_count: int

    def persistence_record(self) -> dict[str, object]:
        """Return public-safe invocation metadata without process transcripts."""

        return {
            "final_json": self.final_json,
            "sanitized_argv": list(self.sanitized_argv),
            "cli_version": self.cli_version,
            "validation_result": dict(self.validation_result),
            "tool_event_count": self.tool_event_count,
        }


def configure_codex_runtime(
    *,
    binary: str | None = None,
    version: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    timeout_seconds: float | None = None,
) -> None:
    """Set explicit public CLI runtime overrides for this process only."""

    global CODEX_CLI_BINARY, CODEX_CLI_VERSION, CODEX_CLI_MODEL, CODEX_CLI_REASONING_EFFORT, CODEX_CLI_TIMEOUT_SECONDS
    if binary is not None:
        CODEX_CLI_BINARY = binary
    if version is not None:
        CODEX_CLI_VERSION = version
    if model is not None:
        CODEX_CLI_MODEL = model
    if reasoning_effort is not None:
        CODEX_CLI_REASONING_EFFORT = reasoning_effort
    if timeout_seconds is not None:
        CODEX_CLI_TIMEOUT_SECONDS = timeout_seconds


def _regular_file(path: Path | str, *, label: str) -> Path:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise CodexCLIError(f"{label} must be a regular file")
    return candidate


def _validate_strict_schema(path: Path | str) -> tuple[Path, dict[str, object]]:
    schema_path = _regular_file(path, label="Codex CLI output schema")
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CodexCLIError("Codex CLI output schema is not valid JSON") from exc
    if (
        not isinstance(schema, Mapping)
        or schema.get("type") != "object"
        or schema.get("additionalProperties") is not False
        or not isinstance(schema.get("required"), list)
        or not isinstance(schema.get("properties"), Mapping)
    ):
        raise CodexCLIError("Codex CLI output schema is not strict")
    strict_schema = dict(schema)
    try:
        Draft202012Validator.check_schema(strict_schema)
    except SchemaError as exc:
        raise CodexCLIError("Codex CLI output schema is invalid") from exc
    return schema_path, strict_schema


def build_codex_cli_argv(
    *,
    output_schema_path: Path | str,
    output_last_message_path: Path | str,
    scratch_dir: Path | str,
) -> list[str]:
    """Build the one frozen controller invocation without a shell."""

    return [
        CODEX_CLI_BINARY,
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--disable",
        "skill_search",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--model",
        CODEX_CLI_MODEL,
        "--config",
        f'model_reasoning_effort="{CODEX_CLI_REASONING_EFFORT}"',
        "--config",
        "skills.include_instructions=false",
        "--output-schema",
        str(output_schema_path),
        "--output-last-message",
        str(output_last_message_path),
        "--json",
        "-C",
        str(scratch_dir),
        "-",
    ]


def _sanitized_argv(
    argv: list[str],
    *,
    output_schema_path: Path,
    output_last_message_path: Path,
    scratch_dir: Path,
) -> tuple[str, ...]:
    replacements = {
        CODEX_CLI_BINARY: "<CODEX_CLI_BINARY>",
        str(output_schema_path): "<FROZEN_OUTPUT_SCHEMA>",
        str(output_last_message_path): "<PRIVATE_FINAL_OUTPUT>",
        str(scratch_dir): "<EMPTY_READ_ONLY_SCRATCH>",
    }
    return tuple(replacements.get(value, value) for value in argv)


def _command_runner(
    run_command: Callable[..., object] | None,
) -> Callable[..., object]:
    return subprocess.run if run_command is None else run_command


def _completed_stdout(completed: object, *, label: str) -> str:
    value = getattr(completed, "stdout", None)
    if not isinstance(value, str):
        raise CodexCLIExecutionError(f"{label} did not return text stdout")
    return value


def _completed_returncode(completed: object, *, label: str) -> int:
    value = getattr(completed, "returncode", None)
    if isinstance(value, bool) or not isinstance(value, int):
        raise CodexCLIExecutionError(f"{label} did not return an integer exit code")
    return value


def verify_codex_cli_version(
    *,
    timeout_seconds: float | None = None,
    run_command: Callable[..., object] | None = None,
) -> str:
    """Return the required CLI version or refuse this controller transport."""

    if timeout_seconds is None:
        timeout_seconds = CODEX_CLI_VERSION_TIMEOUT_SECONDS
    if timeout_seconds <= 0:
        raise CodexCLIError("Codex CLI version timeout must be positive")
    runner = _command_runner(run_command)
    try:
        completed = runner(
            [CODEX_CLI_BINARY, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise CodexCLIExecutionError("Codex CLI version probe timed out") from exc
    except OSError as exc:
        raise CodexCLIExecutionError("Codex CLI version probe could not start") from exc
    if _completed_returncode(completed, label="Codex CLI version probe") != 0:
        raise CodexCLIExecutionError("Codex CLI version probe exited nonzero")
    versions = _VERSION_PATTERN.findall(
        _completed_stdout(completed, label="Codex CLI version probe")
    )
    if versions != [CODEX_CLI_VERSION]:
        raise CodexCLIExecutionError(
            f"Codex CLI version must be exactly {CODEX_CLI_VERSION}"
        )
    return CODEX_CLI_VERSION


def _validate_event_stream(stdout: str) -> int:
    """Validate every official 0.146.1 JSONL event without retaining it."""

    lines = stdout.splitlines()
    if not lines:
        raise CodexCLIExecutionError("Codex CLI emitted no JSONL events")
    lifecycle = "awaiting_thread"
    tool_event_count = 0
    started_items: dict[str, str] = {}
    completed_item_ids: set[str] = set()
    saw_completed_agent_message = False
    for line in lines:
        if not line.strip():
            raise CodexCLIExecutionError("Codex CLI emitted a malformed JSONL event")
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CodexCLIExecutionError(
                "Codex CLI emitted a malformed JSONL event"
            ) from exc
        if not isinstance(event, Mapping):
            raise CodexCLIExecutionError("Codex CLI event must be a JSON object")
        event_type = event.get("type")
        if event_type not in _EVENT_TYPES:
            raise CodexCLIExecutionError("Codex CLI emitted an unknown event type")
        if lifecycle == "completed":
            raise CodexCLIExecutionError(
                "Codex CLI emitted an event after turn completion"
            )
        if event_type in {"turn.failed", "error"}:
            raise CodexCLIExecutionError("Codex CLI emitted an error event")
        if lifecycle == "awaiting_thread":
            if event_type != "thread.started":
                raise CodexCLIExecutionError(
                    "Codex CLI event stream must start with one thread.started event"
                )
            lifecycle = "awaiting_turn"
            continue
        if lifecycle == "awaiting_turn":
            if event_type != "turn.started":
                raise CodexCLIExecutionError(
                    "Codex CLI turn.started must follow thread.started"
                )
            lifecycle = "running"
            continue
        if event_type == "turn.completed":
            if started_items:
                raise CodexCLIExecutionError(
                    "Codex CLI turn completed with unfinished items"
                )
            if not saw_completed_agent_message:
                raise CodexCLIExecutionError(
                    "Codex CLI turn lacks a completed agent_message"
                )
            lifecycle = "completed"
            continue
        if event_type in {"thread.started", "turn.started"}:
            raise CodexCLIExecutionError(
                "Codex CLI emitted a duplicate lifecycle event"
            )
        if event_type not in {"item.started", "item.updated", "item.completed"}:
            raise CodexCLIExecutionError("Codex CLI event is out of lifecycle order")
        item = event.get("item")
        if not isinstance(item, Mapping):
            raise CodexCLIExecutionError("Codex CLI item event has no item object")
        item_id = item.get("id")
        if (
            not isinstance(item_id, str)
            or not item_id.strip()
            or item_id != item_id.strip()
        ):
            raise CodexCLIExecutionError("Codex CLI item has no valid id")
        item_type = item.get("type")
        if item_type not in _ITEM_TYPES:
            raise CodexCLIExecutionError("Codex CLI emitted an unknown item type")
        if item_type in _FORBIDDEN_ITEM_TYPES:
            tool_event_count += 1
            item_fields = ",".join(sorted(str(key) for key in item))
            raise CodexCLIUnsafeEventError(
                "Codex CLI controller emitted forbidden tool or error item type "
                f"{item_type} with fields {item_fields}",
                item_type=str(item_type),
                tool_event_count=tool_event_count,
            )
        if item_type in _COMPLETION_ONLY_ITEM_TYPES and event_type != "item.completed":
            raise CodexCLIExecutionError(
                "Codex CLI response-only item emitted a non-completion event"
            )
        if item_type == "agent_message" and (
            not isinstance(item.get("text"), str) or not item["text"].strip()
        ):
            raise CodexCLIExecutionError(
                "Codex CLI completed agent_message has no response text"
            )
        if event_type == "item.started":
            if item_id in started_items or item_id in completed_item_ids:
                raise CodexCLIExecutionError("Codex CLI emitted a duplicate item start")
            started_items[item_id] = str(item_type)
        elif event_type == "item.updated":
            if item_id in completed_item_ids:
                raise CodexCLIExecutionError(
                    "Codex CLI item update followed its completion"
                )
            started_type = started_items.get(item_id)
            if started_type is None:
                raise CodexCLIExecutionError("Codex CLI emitted an orphan item update")
            if started_type != item_type:
                raise CodexCLIExecutionError(
                    "Codex CLI item type changed during its lifecycle"
                )
        else:
            if item_id in completed_item_ids:
                raise CodexCLIExecutionError(
                    "Codex CLI emitted a duplicate item completion"
                )
            started_type = started_items.pop(item_id, None)
            if started_type is None and item_type not in _COMPLETION_ONLY_ITEM_TYPES:
                raise CodexCLIExecutionError(
                    "Codex CLI emitted an orphan item completion"
                )
            if started_type is not None and started_type != item_type:
                raise CodexCLIExecutionError(
                    "Codex CLI item type changed during its lifecycle"
                )
            completed_item_ids.add(item_id)
            if item_type == "agent_message":
                saw_completed_agent_message = True
    if lifecycle != "completed":
        raise CodexCLIExecutionError("Codex CLI event stream lacks turn completion")
    return tool_event_count


def _canonical_final_json(path: Path, *, schema: Mapping[str, object]) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise CodexCLIExecutionError("Codex CLI did not write a final message") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CodexCLIValidationError(
            "Codex CLI final message is not valid JSON"
        ) from exc
    if not isinstance(payload, Mapping):
        raise CodexCLIValidationError("Codex CLI final JSON must be an object")
    try:
        Draft202012Validator(schema).validate(payload)
    except ValidationError:
        raise CodexCLIValidationError(
            "Codex CLI final JSON does not match the frozen output schema"
        ) from None
    return json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )


def invoke_codex_cli(
    *,
    prompt: str,
    output_schema_path: Path | str,
    timeout_seconds: float | None = None,
    run_command: Callable[..., object] | None = None,
) -> CodexCLIResult:
    """Run the fixed controller transport once and fail closed on unsafe output."""

    if not isinstance(prompt, str) or not prompt.strip():
        raise CodexCLIError("Codex CLI prompt must be non-empty text")
    if timeout_seconds is None:
        timeout_seconds = CODEX_CLI_TIMEOUT_SECONDS
    if timeout_seconds <= 0:
        raise CodexCLIError("Codex CLI timeout must be positive")
    schema_path, output_schema = _validate_strict_schema(output_schema_path)
    runner = _command_runner(run_command)
    cli_version = verify_codex_cli_version(run_command=runner)
    with tempfile.TemporaryDirectory(prefix="br-foundation-mve24-codex-cli-") as root:
        root_path = Path(root)
        scratch_dir = root_path / "controller"
        scratch_dir.mkdir(mode=0o700)
        scratch_dir.chmod(0o500)
        output_last_message_path = root_path / "final.json"
        argv = build_codex_cli_argv(
            output_schema_path=schema_path,
            output_last_message_path=output_last_message_path,
            scratch_dir=scratch_dir,
        )
        try:
            completed = runner(
                argv,
                input=prompt,
                cwd=str(scratch_dir),
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise CodexCLIExecutionError("Codex CLI controller timed out") from exc
        except OSError as exc:
            raise CodexCLIExecutionError(
                "Codex CLI controller could not start"
            ) from exc
        if _completed_returncode(completed, label="Codex CLI controller") != 0:
            raise CodexCLIExecutionError("Codex CLI controller exited nonzero")
        tool_event_count = _validate_event_stream(
            _completed_stdout(completed, label="Codex CLI controller")
        )
        final_json = _canonical_final_json(
            output_last_message_path, schema=output_schema
        )
        sanitized_argv = _sanitized_argv(
            argv,
            output_schema_path=schema_path,
            output_last_message_path=output_last_message_path,
            scratch_dir=scratch_dir,
        )
    return CodexCLIResult(
        final_json=final_json,
        sanitized_argv=sanitized_argv,
        cli_version=cli_version,
        validation_result={
            "event_stream": "valid",
            "final_json": "valid_json_object",
            "strict_output_schema": True,
        },
        tool_event_count=tool_event_count,
    )


_LIVENESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["liveness"],
    "properties": {"liveness": {"type": "string", "enum": ["SYNTHETIC_OK"]}},
}
_LIVENESS_PROMPT = (
    'Return exactly the JSON object {"liveness":"SYNTHETIC_OK"}. '
    "This is a score-blind synthetic controller liveness probe."
)


def run_score_blind_liveness_probe(
    *,
    timeout_seconds: float | None = None,
    run_command: Callable[..., object] | None = None,
) -> CodexCLIResult:
    """Exercise the real CLI seam without a target, bundle, or score input."""

    with tempfile.TemporaryDirectory(
        prefix="br-foundation-mve24-codex-liveness-"
    ) as root:
        schema_path = Path(root) / "liveness.schema.json"
        schema_path.write_text(
            json.dumps(_LIVENESS_SCHEMA, separators=(",", ":")), encoding="utf-8"
        )
        result = invoke_codex_cli(
            prompt=_LIVENESS_PROMPT,
            output_schema_path=schema_path,
            timeout_seconds=timeout_seconds,
            run_command=run_command,
        )
    if json.loads(result.final_json) != {"liveness": "SYNTHETIC_OK"}:
        raise CodexCLIValidationError("Codex CLI liveness response is invalid")
    return result


__all__ = [
    "CODEX_CLI_BINARY",
    "CODEX_CLI_MODEL",
    "CODEX_CLI_REASONING_EFFORT",
    "CODEX_CLI_TIMEOUT_SECONDS",
    "CODEX_CLI_VERSION",
    "CODEX_CLI_VERSION_TIMEOUT_SECONDS",
    "CodexCLIError",
    "CodexCLIExecutionError",
    "CodexCLIResult",
    "CodexCLIUnsafeEventError",
    "CodexCLIValidationError",
    "build_codex_cli_argv",
    "configure_codex_runtime",
    "invoke_codex_cli",
    "run_score_blind_liveness_probe",
    "verify_codex_cli_version",
]
