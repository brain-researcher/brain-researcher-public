"""Unit tests for scripts/mcp/call_http_tool.py."""

from __future__ import annotations

import io
import json
from pathlib import Path

from scripts.mcp import call_http_tool as mod


class FakeHTTPResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        body: str = "",
    ) -> None:
        self.status = status
        self.headers = headers or {}
        self._body = body.encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def getcode(self) -> int:
        return self.status

    def __enter__(self) -> FakeHTTPResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_load_json_object_supports_inline_file_and_stdin(
    tmp_path: Path,
    monkeypatch,
) -> None:
    args_file = tmp_path / "args.json"
    args_file.write_text('{"from_file": true}', encoding="utf-8")

    assert mod.load_json_object('{"inline": 1}') == {"inline": 1}
    assert mod.load_json_object(f"@{args_file}") == {"from_file": True}

    monkeypatch.setattr("sys.stdin", io.StringIO('{"from_stdin": "ok"}'))
    assert mod.load_json_object("-") == {"from_stdin": "ok"}


def test_http_client_parses_sse_and_captures_session_headers() -> None:
    requests: list[dict[str, object]] = []
    responses = [
        FakeHTTPResponse(
            status=204,
            headers={"mcp-session-id": "sess-123"},
            body="",
        ),
        FakeHTTPResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "mcp-session-id": "sess-123",
            },
            body=(
                'event: message\n'
                'data: {"jsonrpc":"2.0","id":"http-call-1","result":{"serverInfo":{"name":"br"}}}\n\n'
            ),
        ),
        FakeHTTPResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "mcp-session-id": "sess-123",
            },
            body=(
                'data: {"jsonrpc":"2.0","id":"http-call-2","result":{"content":[{"type":"text","text":"{\\"ok\\": true, \\"tool\\": \\"server_info\\"}"}]}}\n\n'
            ),
        ),
    ]

    def opener(request, timeout):
        requests.append(
            {
                "method": request.get_method(),
                "headers": {k.lower(): v for k, v in request.header_items()},
                "body": (
                    json.loads(request.data.decode("utf-8"))
                    if request.data is not None
                    else None
                ),
                "timeout": timeout,
            }
        )
        return responses.pop(0)

    client = mod.HttpMCPClient(
        url="http://example.test/mcp",
        token="token-123",
        timeout_s=5.0,
        opener=opener,
    )

    result = client.call_tool("server_info", {}, prime=True, initialize=True)

    assert result["ok"] is True
    assert result["payload"] == {"ok": True, "tool": "server_info"}
    assert client.session_id == "sess-123"
    assert result["initialized"]["ok"] is True
    assert requests[0]["method"] == "GET"
    assert requests[1]["body"]["method"] == "initialize"
    assert requests[2]["body"]["method"] == "tools/call"
    assert requests[2]["body"]["params"]["name"] == "server_info"
    assert requests[0]["headers"]["user-agent"] == mod.DEFAULT_USER_AGENT
    assert requests[1]["headers"]["mcp-session-id"] == "sess-123"
    assert requests[2]["headers"]["mcp-session-id"] == "sess-123"


def test_poll_run_get_retries_until_terminal_status() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object], bool, bool]] = []

        def call_tool(
            self,
            tool_name: str,
            arguments: dict[str, object] | None = None,
            *,
            prime: bool = True,
            initialize: bool = True,
        ) -> dict[str, object]:
            self.calls.append((tool_name, arguments or {}, prime, initialize))
            status = "running" if len(self.calls) == 1 else "succeeded"
            return {
                "ok": True,
                "payload": {
                    "ok": True,
                    "run": {
                        "status": status,
                        "steps": [],
                    },
                },
            }

    client = FakeClient()

    result = mod.poll_run_get(
        client,  # type: ignore[arg-type]
        "run-123",
        timeout_s=1.0,
        interval_s=0.0,
        heartbeat_s=0.0,
        quiet=True,
    )

    assert result["ok"] is True
    assert result["status"] == "succeeded"
    assert result["attempts"] == 2
    assert client.calls == [
        ("run_get", {"run_id": "run-123"}, True, True),
        ("run_get", {"run_id": "run-123"}, False, True),
    ]


def test_main_call_supports_poll_run_and_output_file(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.calls = 0

        def call_tool(
            self,
            tool_name: str,
            arguments: dict[str, object] | None = None,
            *,
            prime: bool = True,
            initialize: bool = True,
        ) -> dict[str, object]:
            self.calls += 1
            if tool_name == "pipeline_execute":
                return {
                    "ok": True,
                    "payload": {"ok": True, "run_id": "run-9"},
                    "tool_name": tool_name,
                }
            assert tool_name == "run_get"
            return {
                "ok": True,
                "payload": {
                    "ok": True,
                    "run": {
                        "status": "succeeded",
                        "steps": [],
                    },
                },
                "tool_name": tool_name,
            }

    fake_client = FakeClient()
    monkeypatch.setattr(mod, "build_client_from_args", lambda args: fake_client)

    output_path = tmp_path / "call_result.json"
    exit_code = mod.main(
        [
            "call",
            "pipeline_execute",
            "--args",
            '{"plan": {"steps": []}}',
            "--poll-run",
            "--quiet-poll",
            "--result-only",
            "--output",
            str(output_path),
            "--compact",
        ]
    )

    assert exit_code == 0
    stdout = capsys.readouterr().out.strip()
    payload = json.loads(stdout)
    assert payload["ok"] is True
    assert payload["run"]["status"] == "succeeded"
    assert json.loads(output_path.read_text(encoding="utf-8")) == payload


def test_research_logging_session_attaches_buffered_transcript_and_trace() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object], bool, bool]] = []

        def call_tool(
            self,
            tool_name: str,
            arguments: dict[str, object] | None = None,
            *,
            prime: bool = True,
            initialize: bool = True,
        ) -> dict[str, object]:
            args = arguments or {}
            self.calls.append((tool_name, args, prime, initialize))
            if tool_name == "log_research_event":
                return {
                    "payload": {
                        "ok": True,
                        "session_id": "codex:trace-chat",
                        "_agent_directive": {
                            "research_logging": {
                                "state": {
                                    "session_id": "codex:trace-chat",
                                    "preferred_transcript_context_key": "conversation_messages",
                                    "preferred_trace_context_key": "tool_trace_events",
                                }
                            }
                        },
                    }
                }
            assert tool_name == "write_session_snapshot"
            return {"payload": {"ok": True}}

    client = FakeClient()
    session = mod.ResearchLoggingSession(
        source_client="codex",
        client_session_id="trace-chat",
    )
    session.record_progress("Pre-start progress message", stage="setup")
    session.record_external_command(["docker", "push", "image:tag"], returncode=0)
    session.bind_client(client)

    start = session.start("Start session")
    close = session.close(
        goal="Close session",
        done=["captured transcript and trace"],
        open_items=["verify digest"],
        next_command="resume later",
    )

    assert start["ok"] is True
    assert close["ok"] is True
    assert client.calls[0][0] == "log_research_event"
    assert client.calls[1][0] == "write_session_snapshot"
    context = client.calls[1][1]["context"]
    assert context["conversation_messages"][0]["content"] == "Pre-start progress message"
    assert context["conversation_messages"][0]["metadata"] == {"stage": "setup"}
    assert [row["event_type"] for row in context["tool_trace_events"]] == [
        "tool.call.started",
        "tool.call.finished",
    ]
    assert context["tool_trace_events"][0]["tool_id"] == "docker"


def test_run_subprocess_with_trace_records_remote_kubectl_tool(monkeypatch) -> None:
    logger = mod.ResearchLoggingSession(source_client="codex")

    monkeypatch.setattr(
        mod.subprocess,
        "run",
        lambda *args, **kwargs: mod.subprocess.CompletedProcess(
            args[0], 0, stdout="pods", stderr=""
        ),
    )

    proc = mod.run_subprocess_with_trace(
        [
            "gcloud",
            "compute",
            "ssh",
            "brain-researcher-vm",
            "--command",
            "sudo k3s kubectl -n brain-researcher-core get pods",
        ],
        timeout_s=5.0,
        logger=logger,
    )

    assert proc.returncode == 0
    assert [row["event_type"] for row in logger.trace_rows] == [
        "tool.call.started",
        "tool.call.finished",
    ]
    assert logger.trace_rows[0]["tool_id"] == "kubectl"
    assert logger.trace_rows[1]["payload"]["status"] == "success"


def test_research_logging_session_close_surfaces_follow_up_question() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object], bool, bool]] = []

        def call_tool(
            self,
            tool_name: str,
            arguments: dict[str, object] | None = None,
            *,
            prime: bool = True,
            initialize: bool = True,
        ) -> dict[str, object]:
            args = arguments or {}
            self.calls.append((tool_name, args, prime, initialize))
            if tool_name == "log_research_event":
                return {
                    "payload": {
                        "ok": True,
                        "session_id": "codex:trace-chat",
                    }
                }
            assert tool_name == "write_session_snapshot"
            return {
                "payload": {
                    "ok": True,
                    "run_id": "run-123",
                    "_agent_directive": {
                        "research_logging": {
                            "actions": [
                                {
                                    "type": "prompt_post_session_actions",
                                    "payload": {
                                        "run_id": "run-123",
                                        "requires_user_initiation": True,
                                        "suggested_actions": [
                                            {
                                                "id": "generate_durable_session_summary",
                                                "label": "Generate Session Summary",
                                                "tool_name": (
                                                    "generate_research_trajectory_and_insights"
                                                ),
                                                "arguments": {
                                                    "run_id": "run-123",
                                                    "persist": True,
                                                },
                                            }
                                        ],
                                    },
                                }
                            ]
                        }
                    },
                }
            }

    client = FakeClient()
    session = mod.ResearchLoggingSession(
        source_client="codex",
        client_session_id="trace-chat",
    )
    session.bind_client(client)
    session.start("Start session")

    close = session.close(
        goal="Close session",
        done=["captured transcript and trace"],
        open_items=["verify digest"],
        next_command="resume later",
    )

    assert close["ok"] is True
    assert (
        close["follow_up_question"]
        == "Session closed. Do you want me to generate a durable session summary now?"
    )
    assert session.build_follow_up_question() == close["follow_up_question"]
    assert close["post_session_actions"][0]["tool_name"] == (
        "generate_research_trajectory_and_insights"
    )


def test_research_logging_session_confirm_post_session_actions_executes_tool() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object], bool, bool]] = []

        def call_tool(
            self,
            tool_name: str,
            arguments: dict[str, object] | None = None,
            *,
            prime: bool = True,
            initialize: bool = True,
        ) -> dict[str, object]:
            args = arguments or {}
            self.calls.append((tool_name, args, prime, initialize))
            if tool_name == "log_research_event":
                return {
                    "payload": {
                        "ok": True,
                        "session_id": "codex:trace-chat",
                    }
                }
            if tool_name == "write_session_snapshot":
                return {
                    "payload": {
                        "ok": True,
                        "_agent_directive": {
                            "research_logging": {
                                "actions": [
                                    {
                                        "type": "prompt_post_session_actions",
                                        "payload": {
                                            "run_id": "run-123",
                                            "suggested_actions": [
                                                {
                                                    "id": "generate_durable_session_summary",
                                                    "tool_name": (
                                                        "generate_research_trajectory_and_insights"
                                                    ),
                                                    "arguments": {
                                                        "run_id": "run-123",
                                                        "persist": True,
                                                    },
                                                }
                                            ],
                                        },
                                    }
                                ]
                            }
                        },
                    }
                }
            assert tool_name == "generate_research_trajectory_and_insights"
            return {
                "payload": {
                    "ok": True,
                    "anchor_type": "run",
                    "anchor_id": args["run_id"],
                }
            }

    client = FakeClient()
    session = mod.ResearchLoggingSession(
        source_client="codex",
        client_session_id="trace-chat",
    )
    session.bind_client(client)
    session.start("Start session")
    session.close(
        goal="Close session",
        done=["captured transcript and trace"],
        open_items=["verify digest"],
        next_command="resume later",
    )

    follow_up = session.confirm_post_session_actions(True)

    assert follow_up["ok"] is True
    assert follow_up["anchor_type"] == "run"
    assert follow_up["anchor_id"] == "run-123"
    assert client.calls[2] == (
        "generate_research_trajectory_and_insights",
        {"run_id": "run-123", "persist": True},
        True,
        True,
    )
    assert session.pending_post_session_actions() == []
    assert session.build_follow_up_question() is None


def test_research_logging_session_decline_post_session_actions_clears_pending() -> None:
    class FakeClient:
        def call_tool(
            self,
            tool_name: str,
            arguments: dict[str, object] | None = None,
            *,
            prime: bool = True,
            initialize: bool = True,
        ) -> dict[str, object]:
            if tool_name == "log_research_event":
                return {"payload": {"ok": True, "session_id": "codex:trace-chat"}}
            return {
                "payload": {
                    "ok": True,
                    "_agent_directive": {
                        "research_logging": {
                            "actions": [
                                {
                                    "type": "prompt_post_session_actions",
                                    "payload": {
                                        "suggested_actions": [
                                            {
                                                "id": "generate_durable_session_summary",
                                                "tool_name": (
                                                    "generate_research_trajectory_and_insights"
                                                ),
                                                "arguments": {
                                                    "run_id": "run-123",
                                                    "persist": True,
                                                },
                                            }
                                        ],
                                    },
                                }
                            ]
                        }
                    },
                }
            }

    session = mod.ResearchLoggingSession(
        source_client="codex",
        client_session_id="trace-chat",
    )
    session.bind_client(FakeClient())
    session.start("Start session")
    session.close(
        goal="Close session",
        done=["captured transcript and trace"],
        open_items=["verify digest"],
        next_command="resume later",
    )

    follow_up = session.confirm_post_session_actions("no")

    assert follow_up["ok"] is True
    assert follow_up["skipped"] is True
    assert follow_up["reason"] == "user_declined"
    assert session.pending_post_session_actions() == []
    assert session.build_follow_up_question() is None
