"""Smoke tests for the UI API Blueprint."""

import json
import os
import pytest
import uuid
from unittest.mock import patch, MagicMock
from pathlib import Path


@pytest.fixture(autouse=True)
def enable_dev_mode(monkeypatch):
    """Enable dev mode for all tests (autouse)."""
    monkeypatch.setenv("DISABLE_AUTH_FOR_DEV", "1")


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset singleton instances between tests."""
    yield
    # Reset thread store singleton
    try:
        import brain_researcher.services.agent.thread_store as ts

        ts._thread_store = None
    except (ImportError, AttributeError):
        pass
    # Reset job service singleton
    try:
        import brain_researcher.services.agent.job_service as js

        js._job_service = None
    except (ImportError, AttributeError):
        pass
    # Reset file upload singletons
    try:
        import brain_researcher.services.agent.ui_api as ui_api

        ui_api._file_storage = None
        ui_api._resumable_storage = None
    except (ImportError, AttributeError):
        pass


@pytest.fixture
def app():
    """Create a Flask app with the ui_api blueprint."""
    from flask import Flask
    from brain_researcher.services.agent.ui_api import ui_api

    app = Flask(__name__)
    app.register_blueprint(ui_api, url_prefix="/api")
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    """Create a test client."""
    return app.test_client()


class TestCodingEscapeHatch:
    """Tests for the explicit remote code-agent escape hatch helper."""

    def test_requires_force_flag_and_env_opt_in(self, monkeypatch):
        from brain_researcher.services.agent.ui_api import _should_use_remote_code_agent

        monkeypatch.delenv("BR_ENABLE_CODE_AGENT_TOOL", raising=False)
        assert _should_use_remote_code_agent({}) is False
        assert _should_use_remote_code_agent({"force_code_agent": True}) is False

        monkeypatch.setenv("BR_ENABLE_CODE_AGENT_TOOL", "1")
        assert _should_use_remote_code_agent({"force_code_agent": False}) is False
        assert _should_use_remote_code_agent({"force_code_agent": True}) is True

    def test_explain_only_disables_escape_hatch(self, monkeypatch):
        from brain_researcher.services.agent.ui_api import _should_use_remote_code_agent

        monkeypatch.setenv("BR_ENABLE_CODE_AGENT_TOOL", "1")
        assert (
            _should_use_remote_code_agent(
                {"force_code_agent": True, "explain_only": True}
            )
            is False
        )


class TestHealthEndpoint:
    """Tests for /api/health endpoint."""

    def test_health_returns_ok(self, client):
        """GET /api/health should return status ok."""
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "ok"


class TestConfigEndpoint:
    """Tests for /api/config/ui endpoint."""

    def test_config_ui_returns_modes(self, client):
        """GET /api/config/ui should return available modes."""
        response = client.get("/api/config/ui")
        assert response.status_code == 200
        data = response.get_json()
        assert "modes" in data
        assert "default" in data["modes"]
        assert "tool_mode_default" in data


class TestChatEndpoint:
    """Tests for /api/chat endpoint."""

    def test_chat_missing_messages_returns_400(self, client):
        """POST /api/chat with empty messages should return 400."""
        response = client.post(
            "/api/chat",
            json={"messages": []},
            content_type="application/json",
        )
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data
        assert "empty" in data["error"].lower()

    def test_chat_missing_user_content_returns_400(self, client):
        """POST /api/chat with no user message should return 400."""
        response = client.post(
            "/api/chat",
            json={"messages": [{"role": "assistant", "content": "hello"}]},
            content_type="application/json",
        )
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data

    @patch("brain_researcher.services.agent.agent_core.simple_chat_core")
    def test_chat_tool_mode_off_uses_simple_chat(self, mock_simple_chat, client):
        """POST /api/chat with tool_mode=off should use simple_chat_core."""
        mock_simple_chat.return_value = {
            "text": "Hello, I'm an AI assistant.",
            "metadata": {"provider": "test", "model": "test-model"},
        }

        response = client.post(
            "/api/chat",
            json={
                "messages": [{"role": "user", "content": "Hello"}],
                "tool_mode": "off",
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        mock_simple_chat.assert_called_once()
        # Verify the call args
        call_args = mock_simple_chat.call_args
        assert call_args[0][0] == "Hello"  # First positional arg is the message

    @patch("brain_researcher.services.agent.agent_core.simple_chat_core")
    def test_chat_merges_resume_checkpoint_id_into_ctx(self, mock_simple_chat, client):
        """POST /api/chat should normalize resume checkpoint ids into ctx."""
        mock_simple_chat.return_value = {
            "text": "Resumed from checkpoint.",
            "metadata": {"checkpoint_id": "ck-final-123"},
        }

        response = client.post(
            "/api/chat",
            json={
                "messages": [{"role": "user", "content": "continue"}],
                "tool_mode": "off",
                "resume_checkpoint_id": "ck-resume-456",
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        call_args = mock_simple_chat.call_args
        assert call_args.kwargs["ctx"]["resume_checkpoint_id"] == "ck-resume-456"
        assert "checkpoint_id" not in call_args.kwargs["ctx"]
        data = response.get_json()
        assert data["metadata"]["checkpoint_id"] == "ck-final-123"
        assert "last_checkpoint_id" not in data["metadata"]

    @patch("brain_researcher.services.agent.agent_core.agent_act_core")
    def test_chat_tool_mode_auto_uses_agent_act(self, mock_agent_act, client):
        """POST /api/chat with tool_mode=auto should use agent_act_core."""
        mock_agent_act.return_value = {
            "message": {"role": "assistant", "content": "I'll help with that."},
            "tool_calls": [],
            "artifacts": [],
            "runCard": {"run_id": "test-123"},
            "session_id": "default",
        }

        response = client.post(
            "/api/chat",
            json={
                "messages": [{"role": "user", "content": "Run fMRI analysis"}],
                "tool_mode": "auto",
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        mock_agent_act.assert_called_once()
        # Verify the payload structure
        call_args = mock_agent_act.call_args
        payload = call_args[0][0]
        assert payload["query"] == "Run fMRI analysis"
        assert payload["tool_mode"] == "auto"

    @patch("brain_researcher.services.agent.agent_core.simple_chat_core")
    def test_chat_reuses_thread_history_from_store(self, mock_simple_chat, client):
        """POST /api/chat should hydrate history from thread store when payload only has latest turn."""
        mock_simple_chat.return_value = {
            "text": "Hello, I'm an AI assistant.",
            "metadata": {"provider": "test", "model": "test-model"},
        }
        thread_id = f"thread-history-{uuid.uuid4().hex}"

        response_1 = client.post(
            "/api/chat",
            json={
                "thread_id": thread_id,
                "messages": [{"role": "user", "content": "First turn"}],
                "tool_mode": "off",
            },
            content_type="application/json",
        )
        assert response_1.status_code == 200

        response_2 = client.post(
            "/api/chat",
            json={
                "thread_id": thread_id,
                "messages": [{"role": "user", "content": "Second turn"}],
                "tool_mode": "off",
            },
            content_type="application/json",
        )
        assert response_2.status_code == 200

        assert mock_simple_chat.call_count == 2
        second_call_kwargs = mock_simple_chat.call_args_list[1].kwargs
        assert len(second_call_kwargs["history"]) >= 2
        assert second_call_kwargs["history"][0]["role"] == "user"
        assert second_call_kwargs["history"][0]["content"] == "First turn"
        assert second_call_kwargs["history"][1]["role"] == "assistant"
        assert "AI assistant" in second_call_kwargs["history"][1]["content"]

    @patch("brain_researcher.services.agent.agent_core.agent_act_core")
    def test_chat_auto_injects_plan_context_into_query(self, mock_agent_act, client):
        """POST /api/chat auto mode should include plan context for grounded answers."""
        mock_agent_act.return_value = {
            "message": {"role": "assistant", "content": "Use Schaefer atlas first."},
            "tool_calls": [],
            "artifacts": [],
            "runCard": {"run_id": "test-ctx-1"},
            "session_id": "thread-ctx-1",
        }

        response = client.post(
            "/api/chat",
            json={
                "thread_id": "thread-ctx-1",
                "tool_mode": "auto",
                "messages": [
                    {
                        "role": "user",
                        "content": "What atlas should I use for this analysis?",
                    }
                ],
                "ctx": {
                    "plan_context": {
                        "dataset_id": "ds:manual:hcp_ya",
                        "pipeline_id": "nilearn_connectivity",
                        "parameters": {
                            "atlas": "schaefer-200",
                            "connectivity_metric": "correlation",
                        },
                    }
                },
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        mock_agent_act.assert_called_once()
        payload = mock_agent_act.call_args[0][0]
        assert "Studio plan context" in payload["query"]
        assert "Dataset: ds:manual:hcp_ya" in payload["query"]
        assert "Pipeline: nilearn_connectivity" in payload["query"]

    @patch("brain_researcher.services.agent.agent_core.agent_act_core")
    def test_chat_auto_returns_info_gap_clarification_before_agent_act(
        self, mock_agent_act, client
    ):
        """POST /api/chat should ask one clarification before legacy auto mode proceeds."""
        thread_id = f"thread-clarify-{uuid.uuid4().hex}"

        response = client.post(
            "/api/chat",
            json={
                "thread_id": thread_id,
                "tool_mode": "auto",
                "messages": [
                    {
                        "role": "user",
                        "content": "Can you analyze my brain imaging dataset?",
                    }
                ],
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["metadata"]["type"] == "clarification"
        assert data["metadata"]["questions"] == [
            "What dataset or subject should I operate on?"
        ]
        assert (
            data["message"]["content"] == "What dataset or subject should I operate on?"
        )
        mock_agent_act.assert_not_called()

    @patch("brain_researcher.services.agent.agent_core.agent_act_core")
    def test_chat_auto_uses_original_request_after_clarification_answer(
        self, mock_agent_act, client
    ):
        """POST /api/chat should merge the original request with clarification answers."""
        mock_agent_act.return_value = {
            "message": {"role": "assistant", "content": "I'll analyze ds000224."},
            "tool_calls": [],
            "artifacts": [],
            "runCard": {"run_id": "test-clarified-auto"},
            "session_id": "thread-clarified-auto",
        }
        thread_id = f"thread-clarified-auto-{uuid.uuid4().hex}"

        first_response = client.post(
            "/api/chat",
            json={
                "thread_id": thread_id,
                "tool_mode": "auto",
                "messages": [
                    {
                        "role": "user",
                        "content": "Can you analyze my brain imaging dataset?",
                    }
                ],
            },
            content_type="application/json",
        )
        assert first_response.status_code == 200
        assert first_response.get_json()["metadata"]["type"] == "clarification"

        second_response = client.post(
            "/api/chat",
            json={
                "thread_id": thread_id,
                "tool_mode": "auto",
                "messages": [{"role": "user", "content": "ds000224"}],
            },
            content_type="application/json",
        )

        assert second_response.status_code == 200
        mock_agent_act.assert_called_once()
        payload = mock_agent_act.call_args[0][0]
        assert "Can you analyze my brain imaging dataset?" in payload["query"]
        assert "What dataset or subject should I operate on?" in payload["query"]
        assert "ds000224" in payload["query"]

    @patch("brain_researcher.services.agent.agent_core.simple_chat_core")
    def test_chat_consumes_preseeded_generic_clarifications_one_at_a_time(
        self, mock_simple_chat, client
    ):
        """POST /api/chat should expose resolution-memory clarifications sequentially."""
        from brain_researcher.services.agent.resolution_memory import (
            add_pending_decision,
            export_resolution_state,
        )

        thread_id = f"thread-preseeded-clarify-{uuid.uuid4().hex}"
        seed_ctx = {"thread_id": thread_id}
        add_pending_decision(
            seed_ctx,
            {
                "kind": "generic_clarification",
                "source": "query_understanding",
                "clarification_key": "query_understanding:Which dataset id?",
                "question": "Which dataset id?",
            },
        )
        add_pending_decision(
            seed_ctx,
            {
                "kind": "generic_clarification",
                "source": "query_understanding",
                "clarification_key": "query_understanding:Which contrast?",
                "question": "Which contrast?",
            },
        )

        response = client.post(
            "/api/chat",
            json={
                "thread_id": thread_id,
                "tool_mode": "off",
                "messages": [{"role": "user", "content": "ds000224"}],
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["metadata"]["type"] == "clarification"
        assert data["metadata"]["questions"] == ["Which contrast?"]
        mock_simple_chat.assert_not_called()

        state = export_resolution_state({"thread_id": thread_id})
        assert state["generic_clarifications"]["answers"][0]["answer"] == "ds000224"
        assert [item["question"] for item in state["pending_decisions"]] == [
            "Which contrast?"
        ]

    def test_augment_query_with_context_adds_neuroimaging_atlas_hint(self):
        """Context augmentation should disambiguate atlas terminology for neuroimaging prompts."""
        from brain_researcher.services.agent.ui_api import _augment_query_with_context

        query = _augment_query_with_context(
            "What atlas should I use for this analysis?",
            ctx={
                "plan_context": {
                    "dataset_id": "ds:manual:hcp_ya",
                    "pipeline_id": "nilearn_connectivity",
                    "parameters": {"atlas": "schaefer-200"},
                }
            },
        )

        assert "Studio plan context" in query
        assert "Dataset: ds:manual:hcp_ya" in query
        assert "Pipeline: nilearn_connectivity" in query
        assert "neuroimaging brain atlas/parcellation" in query

    def test_augment_query_with_context_adds_repair_context(self):
        """Repair context should be injected so Studio repair loops are grounded."""
        from brain_researcher.services.agent.ui_api import _augment_query_with_context

        query = _augment_query_with_context(
            "Repair this failed validation run.",
            ctx={
                "repair_context": {
                    "run_id": "run-123",
                    "analysis_id": "analysis-123",
                    "tool_name": "fitlins",
                    "error_type": "workflow_error",
                    "error_message": "Missing confounds.tsv for subject 01",
                    "repair_attempt_count": 1,
                    "failing_step": {
                        "name": "Model fit",
                        "tool": "fitlins",
                        "status": "failed",
                        "error": "Missing confounds.tsv for subject 01",
                    },
                    "diagnosis": {
                        "title": "Diagnosis: Workflow error",
                        "message": "fitlins failed while building design matrices.",
                        "what_happened": ["Missing confounds.tsv for subject 01"],
                        "suggested_actions": [
                            "Reduce the subject subset and re-validate."
                        ],
                    },
                    "primary_violation": {
                        "code": "missing_confounds",
                        "message": "Missing confounds.tsv for subject 01",
                        "severity": "error",
                        "blocking": True,
                        "suggested_fix": "Restrict validation to a subject with confounds available.",
                        "where": {
                            "step_id": "step-model-fit",
                            "stage": "model_fit",
                            "component": "fitlins",
                        },
                    },
                    "diagnostics_codes": [
                        "taxonomy:data:missing_input",
                        "violation:missing_confounds",
                    ],
                    "sample_errors": [
                        "step: missing_confounds: Missing confounds.tsv for subject 01"
                    ],
                    "plan_snapshot": {
                        "dataset_id": "ds:manual:hcp_ya",
                        "dataset_version": "1.0.0",
                        "pipeline_id": "nilearn_glm",
                        "parameter_values": {
                            "subject_subset": ["sub-01"],
                            "smoothing_fwhm": 6,
                        },
                    },
                    "input_artifacts": [
                        {
                            "name": "design.tsv",
                            "type": "table",
                            "uri": "/artifacts/design.tsv",
                        }
                    ],
                    "log_tail": [
                        "fitlins: reading confounds",
                        "FileNotFoundError: confounds.tsv",
                    ],
                }
            },
        )

        assert "Studio repair context" in query
        assert "Run/job ID: run-123" in query
        assert "Tool: fitlins" in query
        assert "Primary violation: missing_confounds" in query
        assert "Top diagnostic code: taxonomy:data:missing_input" in query
        assert "Current Studio plan snapshot" in query
        assert "Dataset: ds:manual:hcp_ya" in query
        assert "Pipeline: nilearn_glm" in query
        assert "Repair objective" in query
        assert (
            "plan_patch, recipe_patch_preview, validation_intent, and handoff" in query
        )
        assert "Example Studio-side fix" in query
        assert "Example external handoff" in query

    def test_chat_stream_injects_plan_context_into_query(
        self, client, monkeypatch, tmp_path
    ):
        """/api/chat/stream should pass context-augmented query into streaming handler."""
        from brain_researcher.config.run_artifacts import reset_recorder_config
        from brain_researcher.services.agent.streaming import StreamEvent

        monkeypatch.setenv("BR_RUN_STORE_ROOT", str(tmp_path / "runs"))
        reset_recorder_config()

        captured: dict[str, str] = {}
        mock_user = MagicMock(id="user-stream-context", tenant_id="default")

        class FakeStreamingChatHandler:
            def __init__(self, model_hint=None, thread_id=None):
                self._accumulated = ""

            def stream_chat(self, query, history=None):
                captured["query"] = query
                self._accumulated = "ok"
                yield StreamEvent(
                    event="metadata", data={"provider": "test", "model": "test-model"}
                )
                yield StreamEvent(event="token", data={"content": "ok"})
                yield StreamEvent(
                    event="done",
                    data={"thread_id": "thread-stream-context", "total_length": 2},
                )

            def get_accumulated_text(self):
                return self._accumulated

        with (
            patch(
                "brain_researcher.services.agent.agent_auth.get_current_user",
                return_value=mock_user,
            ),
            patch(
                "brain_researcher.services.agent.ui_api._check_thread_access",
                return_value=True,
            ),
            patch(
                "brain_researcher.services.agent.ui_api._add_message",
                return_value=None,
            ),
            patch(
                "brain_researcher.services.agent.streaming.StreamingChatHandler",
                FakeStreamingChatHandler,
            ),
        ):
            response = client.post(
                "/api/chat/stream",
                json={
                    "messages": [
                        {
                            "role": "user",
                            "content": "What atlas should I use for this analysis?",
                        }
                    ],
                    "thread_id": "thread-stream-context",
                    "ctx": {
                        "plan_context": {
                            "dataset_id": "ds:manual:hcp_ya",
                            "pipeline_id": "nilearn_connectivity",
                            "parameters": {"atlas": "schaefer-200"},
                        }
                    },
                },
                content_type="application/json",
                buffered=True,
            )

        assert response.status_code == 200
        assert "Studio plan context" in captured["query"]
        assert "Dataset: ds:manual:hcp_ya" in captured["query"]
        assert "Pipeline: nilearn_connectivity" in captured["query"]
        assert "neuroimaging brain atlas/parcellation" in captured["query"]

    def test_chat_stream_merges_resume_checkpoint_id_into_ctx(
        self, client, monkeypatch, tmp_path
    ):
        """/api/chat/stream should pass normalized resume checkpoint ids to orchestrator."""
        from brain_researcher.config.run_artifacts import reset_recorder_config

        monkeypatch.setenv("BR_RUN_STORE_ROOT", str(tmp_path / "runs"))
        monkeypatch.setenv("BR_CHAT_ORCHESTRATOR_ENABLED", "1")
        reset_recorder_config()

        captured: dict[str, object] = {}
        mock_user = MagicMock(id="user-stream-resume", tenant_id="default")

        def fake_simple_chat_internal(*args, **kwargs):
            captured["ctx"] = kwargs.get("ctx")
            return MagicMock(
                status_code=200,
                get_json=lambda: {
                    "text": "resume ok",
                    "metadata": {"checkpoint_id": "ck-stream-final"},
                    "tool_calls": [],
                },
            )

        with (
            patch(
                "brain_researcher.services.agent.agent_auth.get_current_user",
                return_value=mock_user,
            ),
            patch(
                "brain_researcher.services.agent.ui_api._check_thread_access",
                return_value=True,
            ),
            patch(
                "brain_researcher.services.agent.ui_api._add_message",
                return_value=None,
            ),
            patch(
                "brain_researcher.services.agent.web_service.simple_chat_internal",
                side_effect=fake_simple_chat_internal,
            ),
        ):
            response = client.post(
                "/api/chat/stream",
                json={
                    "messages": [{"role": "user", "content": "continue"}],
                    "thread_id": "thread-stream-resume",
                    "resume_checkpoint_id": "ck-stream-resume",
                },
                content_type="application/json",
                buffered=True,
            )

        assert response.status_code == 200
        assert captured["ctx"]["resume_checkpoint_id"] == "ck-stream-resume"

    def test_chat_stream_injects_repair_context_into_query(
        self, client, monkeypatch, tmp_path
    ):
        """/api/chat/stream should pass repair-context protocol and facts into the streaming handler."""
        from brain_researcher.config.run_artifacts import reset_recorder_config
        from brain_researcher.services.agent.streaming import StreamEvent

        monkeypatch.setenv("BR_RUN_STORE_ROOT", str(tmp_path / "runs"))
        reset_recorder_config()

        captured: dict[str, str] = {}
        mock_user = MagicMock(id="user-stream-repair", tenant_id="default")

        class FakeStreamingChatHandler:
            def __init__(self, model_hint=None, thread_id=None):
                self._accumulated = ""

            def stream_chat(self, query, history=None):
                captured["query"] = query
                self._accumulated = "ok"
                yield StreamEvent(
                    event="metadata", data={"provider": "test", "model": "test-model"}
                )
                yield StreamEvent(
                    event="done",
                    data={"thread_id": "thread-stream-repair", "total_length": 2},
                )

            def get_accumulated_text(self):
                return self._accumulated

        with (
            patch(
                "brain_researcher.services.agent.agent_auth.get_current_user",
                return_value=mock_user,
            ),
            patch(
                "brain_researcher.services.agent.ui_api._check_thread_access",
                return_value=True,
            ),
            patch(
                "brain_researcher.services.agent.ui_api._add_message",
                return_value=None,
            ),
            patch(
                "brain_researcher.services.agent.streaming.StreamingChatHandler",
                FakeStreamingChatHandler,
            ),
        ):
            response = client.post(
                "/api/chat/stream",
                json={
                    "messages": [
                        {
                            "role": "user",
                            "content": "Repair this failed Studio validation run.",
                        }
                    ],
                    "thread_id": "thread-stream-repair",
                    "ctx": {
                        "repair_context": {
                            "run_id": "run-stream-123",
                            "tool_name": "fitlins",
                            "error_type": "missing_input",
                            "error_message": "Missing confounds.tsv for subject 01",
                            "repair_attempt_count": 1,
                            "failing_step": {
                                "name": "Model fit",
                                "tool": "fitlins",
                                "status": "failed",
                                "error": "Missing confounds.tsv for subject 01",
                            },
                            "primary_violation": {
                                "code": "missing_confounds",
                                "message": "Missing confounds.tsv for subject 01",
                                "severity": "error",
                                "blocking": True,
                                "where": {
                                    "step_id": "step-model-fit",
                                    "stage": "model_fit",
                                    "component": "fitlins",
                                },
                            },
                            "diagnostics_codes": [
                                "taxonomy:data:missing_input",
                                "violation:missing_confounds",
                            ],
                            "sample_errors": [
                                "step: missing_confounds: Missing confounds.tsv for subject 01"
                            ],
                            "plan_snapshot": {
                                "dataset_id": "ds:manual:hcp_ya",
                                "dataset_version": "1.0.0",
                                "pipeline_id": "nilearn_glm",
                                "parameter_values": {
                                    "subject_subset": ["sub-01"],
                                    "smoothing_fwhm": 6,
                                },
                            },
                            "log_tail": [
                                "fitlins: reading confounds",
                                "FileNotFoundError: confounds.tsv",
                            ],
                        }
                    },
                },
                content_type="application/json",
                buffered=True,
            )

        assert response.status_code == 200
        assert "Studio repair context" in captured["query"]
        assert "Run/job ID: run-stream-123" in captured["query"]
        assert "Current Studio plan snapshot" in captured["query"]
        assert "Pipeline: nilearn_glm" in captured["query"]
        assert "Example Studio-side fix" in captured["query"]
        assert "Example external handoff" in captured["query"]

    def test_chat_stream_reuses_thread_history_from_store(
        self, client, monkeypatch, tmp_path
    ):
        """/api/chat/stream should hydrate history from thread store when payload only has latest turn."""
        from brain_researcher.config.run_artifacts import reset_recorder_config
        from brain_researcher.services.agent.streaming import StreamEvent
        from brain_researcher.services.agent.ui_api import _add_message

        monkeypatch.setenv("BR_RUN_STORE_ROOT", str(tmp_path / "runs"))
        reset_recorder_config()

        thread_id = f"thread-stream-history-{uuid.uuid4().hex}"
        user_id = "user-stream-history"
        captured: dict[str, list[dict[str, str]]] = {}
        mock_user = MagicMock(id=user_id, tenant_id="default")

        _add_message(
            thread_id,
            "user",
            "First turn",
            user_id=user_id,
            tenant_id="default",
        )
        _add_message(
            thread_id,
            "assistant",
            "First response",
            user_id=user_id,
            tenant_id="default",
        )

        class FakeStreamingChatHandler:
            def __init__(self, model_hint=None, thread_id=None):
                self._accumulated = ""

            def stream_chat(self, query, history=None):
                captured["history"] = history or []
                self._accumulated = "ok"
                yield StreamEvent(
                    event="metadata", data={"provider": "test", "model": "test-model"}
                )
                yield StreamEvent(
                    event="done",
                    data={"thread_id": thread_id, "total_length": 2},
                )

            def get_accumulated_text(self):
                return self._accumulated

        with (
            patch(
                "brain_researcher.services.agent.agent_auth.get_current_user",
                return_value=mock_user,
            ),
            patch(
                "brain_researcher.services.agent.ui_api._check_thread_access",
                return_value=True,
            ),
            patch(
                "brain_researcher.services.agent.streaming.StreamingChatHandler",
                FakeStreamingChatHandler,
            ),
        ):
            response = client.post(
                "/api/chat/stream",
                json={
                    "messages": [{"role": "user", "content": "Second turn"}],
                    "thread_id": thread_id,
                },
                content_type="application/json",
                buffered=True,
            )

        assert response.status_code == 200
        history = captured.get("history") or []
        assert len(history) >= 2
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "First turn"
        assert history[1]["role"] == "assistant"
        assert history[1]["content"] == "First response"

    @patch("brain_researcher.services.agent.agent_core.agent_act_core")
    def test_chat_attaches_multihop_preview(self, mock_agent_act, client):
        """POST /api/chat should attach result_preview for kg_multihop_qa calls."""
        mock_agent_act.return_value = {
            "message": {"role": "assistant", "content": "Done."},
            "tool_calls": [
                {
                    "name": "kg_multihop_qa",
                    "arguments": {
                        "question": "How is working memory linked to cognitive control?",
                        "max_hops": 2,
                        "mode": "breadth_first",
                        "max_results": 25,
                        "allowed_edge_types": ["RELATED_TO"],
                    },
                    "status": "ok",
                    "result": {
                        "answer": "Found 2 paths within 2 hops.",
                        "paths": [
                            {
                                "nodes": [
                                    {"label": "Working Memory"},
                                    {"label": "DLPFC"},
                                    {"label": "Cognitive Control"},
                                ]
                            },
                            {
                                "nodes": [
                                    {"label": "Working Memory"},
                                    {"label": "Anterior Cingulate"},
                                ]
                            },
                        ],
                        "subgraph": {
                            "nodes": [{"kg_id": "concept:working_memory"}],
                            "edges": [
                                {
                                    "source": "concept:working_memory",
                                    "target": "region:dlpfc",
                                    "type": "RELATED_TO",
                                }
                            ],
                        },
                        "warnings": ["top-level warning"],
                        "summary": {
                            "question": "How is working memory linked to cognitive control?",
                            "max_hops": 2,
                            "mode": "breadth_first",
                        },
                        "outputs": {
                            "answer": "legacy answer should be ignored",
                            "paths": [
                                {"nodes": [{"label": "Legacy"}, {"label": "Path"}]}
                            ],
                            "warnings": ["legacy warning should be ignored"],
                        },
                    },
                }
            ],
            "artifacts": [],
            "runCard": {"run_id": "test-kg-preview"},
            "session_id": "default",
        }

        response = client.post(
            "/api/chat",
            json={
                "messages": [
                    {
                        "role": "user",
                        "content": "How is working memory linked to cognitive control?",
                    }
                ],
                "tool_mode": "auto",
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.get_json()
        tool_calls = data.get("tool_calls", [])
        assert tool_calls
        preview = tool_calls[0].get("result_preview")
        assert preview
        assert preview["kind"] == "kg_multihop_qa"
        assert preview["has_subgraph"] is True
        assert preview["top_paths"][0] == "Working Memory -> DLPFC -> Cognitive Control"
        assert preview["expand_args"]["question"] == (
            "How is working memory linked to cognitive control?"
        )
        assert preview["expand_args"]["return_subgraph"] is True
        assert "top-level warning" in preview["warnings"]
        assert "deprecation:kg_multihop_qa:data.outputs" not in preview["warnings"]

    @patch("brain_researcher.services.agent.agent_core.agent_act_core")
    def test_chat_stores_messages_in_thread(self, mock_agent_act, client):
        """POST /api/chat should store messages in thread."""
        mock_agent_act.return_value = {
            "message": {"role": "assistant", "content": "Response text"},
            "tool_calls": [],
            "artifacts": [],
            "runCard": {"run_id": "test-123"},
            "session_id": "test-thread",
        }

        # Send a chat message
        client.post(
            "/api/chat",
            json={
                "messages": [{"role": "user", "content": "Test message"}],
                "thread_id": "test-thread",
            },
            content_type="application/json",
        )

        # Verify messages are stored
        response = client.get("/api/threads/test-thread/messages")
        assert response.status_code == 200
        data = response.get_json()
        assert data["thread_id"] == "test-thread"
        assert len(data["messages"]) >= 1
        # First message should be the user message
        user_msgs = [m for m in data["messages"] if m["role"] == "user"]
        assert any(m["content"] == "Test message" for m in user_msgs)

    def test_chat_stream_orchestrator_attaches_multihop_preview(
        self, client, monkeypatch, tmp_path
    ):
        """/api/chat/stream should attach result_preview before tool_call events."""
        from flask import Response

        from brain_researcher.config.run_artifacts import reset_recorder_config

        monkeypatch.setenv("BR_CHAT_ORCHESTRATOR_ENABLED", "1")
        monkeypatch.setenv("BR_RUN_STORE_ROOT", str(tmp_path / "runs"))
        reset_recorder_config()

        mock_user = MagicMock(id="user-stream", tenant_id="default")

        with (
            patch(
                "brain_researcher.services.agent.agent_auth.get_current_user",
                return_value=mock_user,
            ),
            patch(
                "brain_researcher.services.agent.ui_api._check_thread_access",
                return_value=True,
            ),
            patch(
                "brain_researcher.services.agent.ui_api._add_message",
                return_value=None,
            ),
            patch(
                "brain_researcher.services.agent.web_service.simple_chat_internal"
            ) as mocked_simple_chat_internal,
        ):
            mocked_simple_chat_internal.return_value = Response(
                json.dumps(
                    {
                        "text": "stream answer",
                        "metadata": {"provider": "test", "model": "test-model"},
                        "tool_calls": [
                            {
                                "plan": {
                                    "tool": "kg_multihop_qa",
                                    "params": {
                                        "question": "What links memory and attention?",
                                        "max_hops": 3,
                                        "mode": "breadth_first",
                                        "max_results": 10,
                                        "allowed_edge_types": ["RELATED_TO"],
                                    },
                                },
                                "result": {
                                    "status": "success",
                                    "result": {
                                        "status": "success",
                                        "data": {
                                            "outputs": {
                                                "answer": "Found a plausible bridge.",
                                                "paths": [
                                                    {
                                                        "nodes": [
                                                            {"label": "Memory"},
                                                            {
                                                                "label": "Frontoparietal Network"
                                                            },
                                                            {"label": "Attention"},
                                                        ]
                                                    }
                                                ],
                                                "subgraph": {
                                                    "nodes": [
                                                        {"kg_id": "concept:memory"}
                                                    ],
                                                    "edges": [
                                                        {
                                                            "source": "concept:memory",
                                                            "target": "concept:attention",
                                                            "type": "RELATED_TO",
                                                        }
                                                    ],
                                                },
                                                "warnings": ["legacy stream warning"],
                                            },
                                            "summary": {
                                                "question": "What links memory and attention?",
                                                "max_hops": 3,
                                                "mode": "breadth_first",
                                            },
                                        },
                                    },
                                },
                            }
                        ],
                    }
                ),
                status=200,
                mimetype="application/json",
            )

            response = client.post(
                "/api/chat/stream",
                json={
                    "messages": [
                        {"role": "user", "content": "memory attention bridge"}
                    ],
                    "thread_id": "thread-stream-preview",
                    "ctx": {},
                },
                content_type="application/json",
                buffered=True,
            )

        assert response.status_code == 200
        body = b"".join(response.response).decode("utf-8")
        event_name = None
        tool_call_payloads: list[dict] = []
        for line in body.splitlines():
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
                continue
            if event_name == "tool_call" and line.startswith("data:"):
                tool_call_payloads.append(json.loads(line.split(":", 1)[1].strip()))
                event_name = None

        assert tool_call_payloads, "expected at least one tool_call event"
        preview = tool_call_payloads[0].get("result_preview")
        assert preview
        assert preview["kind"] == "kg_multihop_qa"
        assert (
            preview["top_paths"][0] == "Memory -> Frontoparietal Network -> Attention"
        )
        assert preview["expand_args"]["question"] == "What links memory and attention?"
        assert preview["expand_args"]["return_subgraph"] is True
        assert "legacy stream warning" in preview["warnings"]
        assert "deprecation:kg_multihop_qa:data.outputs" in preview["warnings"]


@patch.dict(os.environ, {"BR_CHAT_ORCHESTRATOR_ENABLED": "1"})
class TestChatPipelineIntegration:
    """Integration test for pipeline-first branch via /api/chat."""

    @pytest.fixture(autouse=True)
    def reset_chat_singletons(self):
        """Reset orchestrator singletons so each test is isolated."""
        import brain_researcher.services.agent.web_service as ws

        ws._CHAT_ORCHESTRATOR = None
        ws._CHAT_TOOL_EXECUTOR = None
        ws._CHAT_TOOL_REGISTRY = None
        ws._CHAT_TOOL_ROUTER = None
        yield
        try:
            if ws._CHAT_TOOL_EXECUTOR is not None:
                ws._CHAT_TOOL_EXECUTOR.shutdown()
        except Exception:
            pass
        ws._CHAT_ORCHESTRATOR = None
        ws._CHAT_TOOL_EXECUTOR = None
        ws._CHAT_TOOL_REGISTRY = None
        ws._CHAT_TOOL_ROUTER = None
        ws._LLM_ROUTER = None

    def test_chat_pipeline_preview(self, monkeypatch, client):
        """/api/chat with use_planning_engine should return pipeline preview."""
        # Dummy workflow steps returned by planner
        from brain_researcher.services.agent.planning import WorkflowStep

        steps = [
            WorkflowStep(
                step_id="s1",
                step_number=1,
                description="Skull strip",
                tool_name="fsl.bet",
                tool_args={"input_file": "/tmp/sub-01_T1w.nii.gz", "frac": 0.5},
            ),
            WorkflowStep(
                step_id="s2",
                step_number=2,
                description="Register to MNI",
                tool_name="fsl.fnirt",
                tool_args={"in_file": "/tmp/sub-01_T1w_brain.nii.gz"},
                dependencies=["s1"],
            ),
        ]

        class DummyPlanner:
            def __init__(self, *args, **kwargs):
                pass

            def _should_use_pipeline(self, intent, query):
                return True

            async def _generate_steps(self, query, intent, context=None):
                return steps

            async def generate_plan(self, query, intent=None, context=None):
                # ChatOrchestrator expects an object with .steps
                return type("Plan", (), {"steps": steps})()

        # Patch PlanningEngine used inside ChatOrchestrator
        monkeypatch.setattr(
            "brain_researcher.services.agent.chat_orchestrator.PlanningEngine",
            DummyPlanner,
        )

        # Patch execute_tool so we don't invoke real tools
        from brain_researcher.services.tools.result import ToolResult

        def fake_execute_tool(tool_id, params, **kwargs):
            return ToolResult(
                status="success", data={"tool_id": tool_id, "params": params}
            )

        monkeypatch.setattr(
            "brain_researcher.services.tools.executor.execute_tool", fake_execute_tool
        )

        # Avoid hitting real LLM for pipeline summary by replacing LLMRouter with a dummy
        from types import SimpleNamespace

        class DummyRouter:
            def __init__(self, *args, **kwargs):
                pass

            def route_chat(self, *args, **kwargs):
                return SimpleNamespace(text="pipeline summary", metadata=None)

        # Ensure the orchestrator built inside the endpoint uses DummyRouter
        import brain_researcher.services.agent.web_service as ws

        ws._LLM_ROUTER = DummyRouter()

        payload = {
            "messages": [{"role": "user", "content": "preprocess my T1 to MNI space"}],
            "ctx": {
                "use_planning_engine": True,
                "t1w_image": "/tmp/sub-01_T1w.nii.gz",
                "work_dir": "/tmp/work",
                "output_dir": "/tmp/out",
            },
        }

        response = client.post(
            "/api/chat", json=payload, content_type="application/json"
        )

        assert response.status_code == 200
        data = response.get_json()

        # metadata should indicate pipeline branch in preview mode
        metadata = data.get("metadata", {})
        assert metadata.get("type") == "pipeline"
        assert metadata.get("mode") == "preview"

        # tool_calls should include the planned steps with args
        tool_calls = data.get("tool_calls", [])
        assert tool_calls, "expected tool_calls with pipeline steps"
        pipeline_steps = tool_calls[0].get("pipeline_steps", [])
        step_tools = [
            s.get("tool_name") or s.get("tool") or s.get("tool_id")
            for s in pipeline_steps
        ]
        assert "fsl.bet" in step_tools
        assert "fsl.fnirt" in step_tools

        # Check that the first step carried our params through
        bet_step = pipeline_steps[0]
        assert (
            bet_step.get("tool_args", {}).get("input_file") == "/tmp/sub-01_T1w.nii.gz"
        )


class TestThreadsEndpoint:
    """Tests for /api/threads/* endpoints."""

    def test_get_thread_messages_returns_empty_for_new_thread(self, client):
        """GET /api/threads/{id}/messages for new thread should return empty."""
        response = client.get("/api/threads/nonexistent-thread/messages")
        assert response.status_code == 200
        data = response.get_json()
        assert data["messages"] == []
        assert data["count"] == 0

    def test_thread_stream_returns_sse(self, client):
        """GET /api/threads/{id}/stream should return SSE format."""
        response = client.get("/api/threads/test-stream/stream")
        assert response.status_code == 200
        assert response.content_type.startswith("text/event-stream")


class TestToolsEndpoint:
    """Tests for /api/tools endpoints."""

    def test_get_tools_returns_list(self, client):
        """GET /api/tools should return tool list."""
        response = client.get("/api/tools")
        assert response.status_code == 200
        data = response.get_json()
        assert "tools" in data
        assert isinstance(data["tools"], list)


class TestRunsEndpoint:
    """Tests for /api/runs endpoints."""

    def test_create_run_returns_run_id(self, client):
        """POST /api/runs should create a new run."""
        response = client.post(
            "/api/runs",
            json={"plan": {"steps": []}},
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.get_json()
        assert "run_id" in data
        assert data["run_id"].startswith("job_")
        assert len(data["run_id"]) > 8
        assert data["status"] == "queued"

    def test_get_run_status(self, client):
        """GET /api/runs/{id} should return run status."""
        # Create a run first
        create_response = client.post(
            "/api/runs",
            json={"plan": {}},
            content_type="application/json",
        )
        run_id = create_response.get_json()["run_id"]

        # Get status
        response = client.get(f"/api/runs/{run_id}")
        assert response.status_code == 200
        data = response.get_json()
        assert data["run_id"] == run_id

    def test_get_nonexistent_run_returns_404(self, client):
        """GET /api/runs/{id} for nonexistent run should return 404."""
        response = client.get("/api/runs/nonexistent-run-12345")
        assert response.status_code == 404

    def test_run_stream_returns_sse(self, client):
        """GET /api/runs/{id}/stream should return SSE format."""
        # Create a run first
        create_response = client.post(
            "/api/runs",
            json={"plan": {}},
            content_type="application/json",
        )
        run_id = create_response.get_json()["run_id"]

        response = client.get(f"/api/runs/{run_id}/stream")
        assert response.status_code == 200
        assert response.content_type.startswith("text/event-stream")


class TestDemoProxyEndpoint:
    """Tests for /api/demo/* proxy endpoints."""

    @patch("brain_researcher.services.agent.ui_api.req_lib")
    def test_demo_proxy_get_json(self, mock_requests, client):
        """GET /api/demo/* should proxy to Orchestrator and return JSON."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.content = b'{"demo_id": "test-123", "results": []}'
        mock_requests.request.return_value = mock_response

        response = client.get("/api/demo/real-results/test-123")

        assert response.status_code == 200
        mock_requests.request.assert_called_once()
        # Verify it called with GET method
        call_args = mock_requests.request.call_args
        assert call_args[0][0] == "GET"
        assert "real-results/test-123" in call_args[0][1]

    @patch("brain_researcher.services.agent.ui_api.req_lib")
    def test_demo_proxy_post(self, mock_requests, client):
        """POST /api/demo/* should proxy with JSON body."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.content = b'{"status": "shared"}'
        mock_requests.request.return_value = mock_response

        response = client.post(
            "/api/demo/share",
            json={"demo_id": "test-456"},
            content_type="application/json",
        )

        assert response.status_code == 200
        mock_requests.request.assert_called_once()
        call_args = mock_requests.request.call_args
        assert call_args[0][0] == "POST"
        assert call_args[1]["json"] == {"demo_id": "test-456"}

    @patch("brain_researcher.services.agent.ui_api.req_lib")
    def test_demo_proxy_timeout(self, mock_requests, client):
        """Demo proxy should return 504 on timeout."""
        import requests

        mock_requests.request.side_effect = requests.exceptions.Timeout()
        mock_requests.exceptions = requests.exceptions

        response = client.get("/api/demo/slow-endpoint")

        assert response.status_code == 504
        data = response.get_json()
        assert "timeout" in data["error"]

    @patch("brain_researcher.services.agent.ui_api.req_lib")
    def test_demo_proxy_connection_error(self, mock_requests, client):
        """Demo proxy should return 503 on connection error."""
        import requests

        mock_requests.request.side_effect = requests.exceptions.ConnectionError()
        mock_requests.exceptions = requests.exceptions

        response = client.get("/api/demo/unavailable")

        assert response.status_code == 503
        data = response.get_json()
        assert "unavailable" in data["error"]

    @patch("brain_researcher.services.agent.ui_api.req_lib")
    def test_demo_proxy_binary_stream(self, mock_requests, client):
        """Demo proxy should stream binary content."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {
            "Content-Type": "application/octet-stream",
            "Content-Disposition": "attachment; filename=data.nii.gz",
        }
        mock_response.iter_content.return_value = [b"chunk1", b"chunk2"]
        mock_requests.request.return_value = mock_response

        response = client.get("/api/demo/render/test/artifact.nii.gz")

        assert response.status_code == 200
        assert response.content_type == "application/octet-stream"

    @patch("brain_researcher.services.agent.ui_api.req_lib")
    def test_demo_proxy_preserves_query_params(self, mock_requests, client):
        """Demo proxy should forward query parameters."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.content = b'{"results": []}'
        mock_requests.request.return_value = mock_response

        client.get("/api/demo/search?limit=10&offset=5")

        call_args = mock_requests.request.call_args
        url = call_args[0][1]
        assert "limit=10" in url
        assert "offset=5" in url


class TestFilesEndpoint:
    """Tests for /api/files/* endpoints."""

    def test_upload_no_file_returns_400(self, client):
        """POST /api/files/upload without file should return 400."""
        response = client.post("/api/files/upload")
        assert response.status_code == 400
        data = response.get_json()
        assert data["error"] == "no_file"

    def test_upload_invalid_extension_returns_400(self, client):
        """POST /api/files/upload with invalid extension should return 400."""
        from io import BytesIO

        data = {"file": (BytesIO(b"test content"), "test.exe")}
        response = client.post(
            "/api/files/upload",
            data=data,
            content_type="multipart/form-data",
        )
        assert response.status_code == 400
        result = response.get_json()
        assert result["error"] == "invalid_extension"

    def test_upload_valid_file_returns_201(self, client):
        """POST /api/files/upload with valid file should return 201."""
        from io import BytesIO

        data = {"file": (BytesIO(b"test content"), "test.csv")}
        response = client.post(
            "/api/files/upload",
            data=data,
            content_type="multipart/form-data",
        )
        assert response.status_code == 201
        result = response.get_json()
        assert "file_id" in result
        assert result["filename"] == "test.csv"
        assert result["size"] == len(b"test content")

    def test_upload_nifti_file(self, client):
        """POST /api/files/upload should accept .nii.gz files."""
        from io import BytesIO

        data = {"file": (BytesIO(b"\x1f\x8b" + b"fake nifti"), "brain.nii.gz")}
        response = client.post(
            "/api/files/upload",
            data=data,
            content_type="multipart/form-data",
        )
        assert response.status_code == 201
        result = response.get_json()
        assert result["filename"] == "brain.nii.gz"

    def test_list_files_empty(self, client):
        """GET /api/files should return empty list initially."""
        # Reset the file storage for this test
        import brain_researcher.services.agent.ui_api as ui_api

        ui_api._file_storage = None

        response = client.get("/api/files")
        assert response.status_code == 200
        data = response.get_json()
        assert data["files"] == []
        assert data["count"] == 0

    def test_delete_nonexistent_file(self, client):
        """DELETE /api/files/{id} for nonexistent file should return 404."""
        response = client.delete("/api/files/nonexistent-file-id")
        assert response.status_code == 404

    def test_resumable_upload_roundtrip(self, client):
        """Resumable upload init/put/complete should register as a normal file."""
        data = b"hello resumable"
        resp = client.post(
            "/api/files/resumable/init",
            json={
                "filename": "big.zip",
                "content_type": "application/zip",
                "total_size": len(data),
            },
            content_type="application/json",
        )
        assert resp.status_code == 201
        meta = resp.get_json()
        upload_id = meta["upload_id"]

        put = client.put(
            f"/api/files/resumable/{upload_id}",
            data=data,
            headers={"Content-Range": f"bytes 0-{len(data) - 1}/{len(data)}"},
        )
        assert put.status_code == 200
        put_meta = put.get_json()
        assert put_meta["received"] == len(data)
        assert put_meta["status"] in {"uploaded", "completed"}

        complete = client.post(f"/api/files/resumable/{upload_id}/complete")
        assert complete.status_code == 201
        file_meta = complete.get_json()
        assert file_meta["file_id"] == upload_id

        download = client.get(f"/api/files/{upload_id}")
        assert download.status_code == 200
        assert download.data == data


class TestDatasetsEndpoint:
    """Tests for /api/datasets/* endpoints."""

    def test_search_returns_results_structure(self, client):
        """POST /api/datasets/search should return proper structure."""
        response = client.post(
            "/api/datasets/search",
            json={},
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.get_json()
        assert "results" in data
        assert "total" in data
        assert "limit" in data
        assert "offset" in data

    def test_search_with_query(self, client):
        """POST /api/datasets/search with query should filter results."""
        response = client.post(
            "/api/datasets/search",
            json={"query": "fmri", "limit": 10},
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data["results"], list)
        assert data["limit"] == 10

    def test_search_with_modality_filter(self, client):
        """POST /api/datasets/search with modality filter should work."""
        response = client.post(
            "/api/datasets/search",
            json={"modalities": ["fMRI", "EEG"]},
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data["results"], list)

    def test_get_nonexistent_dataset(self, client):
        """GET /api/datasets/{id} for nonexistent dataset should return 404."""
        response = client.get("/api/datasets/nonexistent-dataset-id")
        assert response.status_code == 404
        data = response.get_json()
        assert data["error"] == "not_found"

    def test_import_bids_zip_from_uploaded_file(self, client, tmp_path, monkeypatch):
        """Upload a zip then import it into the local BIDS store."""
        monkeypatch.setenv("BR_DATA_ROOT", str(tmp_path / "data" / "bids"))

        # Build a minimal BIDS dataset and zip it
        ds_root = tmp_path / "src"
        (ds_root / "dataset_description.json").parent.mkdir(parents=True, exist_ok=True)
        (ds_root / "dataset_description.json").write_text(
            '{"Name":"Example","BIDSVersion":"1.9.0"}',
            encoding="utf-8",
        )
        (ds_root / "sub-01" / "anat").mkdir(parents=True, exist_ok=True)
        (ds_root / "sub-01" / "anat" / "sub-01_T1w.nii.gz").write_bytes(b"fake")

        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for p in ds_root.rglob("*"):
                if p.is_dir():
                    continue
                zf.write(p, p.relative_to(ds_root).as_posix())
        buf.seek(0)

        upload = client.post(
            "/api/files/upload",
            data={"file": (buf, "ds.zip")},
            content_type="multipart/form-data",
        )
        assert upload.status_code == 201
        file_id = upload.get_json()["file_id"]

        imported = client.post(
            "/api/datasets/import",
            json={
                "file_id": file_id,
                "dataset_id": "bids-test",
                "validate": False,
                "delete_uploaded": False,
            },
            content_type="application/json",
        )
        assert imported.status_code == 201
        out = imported.get_json()
        assert out["dataset_id"] == "bids-test"

        bids_root = Path(out["bids_root"])
        assert (bids_root / "dataset_manifest.json").is_file()

        # Search should include local-only dataset_id when queried
        search = client.post(
            "/api/datasets/search",
            json={"query": "bids-test"},
            content_type="application/json",
        )
        assert search.status_code == 200
        ids = [r.get("dataset_id") for r in search.get_json()["results"]]
        assert "bids-test" in ids
