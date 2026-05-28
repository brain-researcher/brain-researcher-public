from __future__ import annotations

from types import SimpleNamespace

from brain_researcher.services.agent import kg_resolution, preflight
from brain_researcher.services.agent.chat_orchestrator import ChatOrchestrator, ToolPlan
from brain_researcher.services.agent.memory import ConversationMemory
from brain_researcher.services.agent.resolution_memory import (
    add_pending_decision,
    export_resolution_state,
    get_override,
    get_pending_decisions,
    get_platform_knowledge_store,
)
from brain_researcher.services.agent.tool_catalog_loader import clear_tool_index_cache
from brain_researcher.services.agent.tool_router import RoutingToolView


class _StubParser:
    def parse(self, query, context=None):
        return preflight._minimal_parsed_query(query)


class _EmptyRetriever:
    def __init__(self):
        self.calls = 0

    def retrieve_tools(self, **kwargs):
        self.calls += 1
        return []


class _StubRouter:
    def __init__(
        self,
        selection_json='{"tool":"foo","params":{},"reasoning":"stub"}',
        summary_text="done",
    ):
        self.selection_json = selection_json
        self.summary_text = summary_text

    def route_chat(self, prompt):
        if "Respond ONLY with JSON" in prompt:
            return SimpleNamespace(
                text=self.selection_json,
                metadata=None,
            )
        return SimpleNamespace(text=self.summary_text, metadata=None)


class _SingleMatchRetriever:
    def __init__(self):
        self.calls = 0

    def retrieve_tools(self, **kwargs):
        self.calls += 1
        return [{"tool_id": "foo", "score": 0.9, "source": "unit_test"}]


class _StubToolRouter:
    def __init__(self):
        self.view = RoutingToolView(
            runtime_id="foo",
            name="foo",
            description="stub",
            tags=[],
        )

    def get_candidates(self, user_msg, history=None, ctx=None):
        return [self.view]


class _StubRegistry:
    def get_runtime_tool(self, tool_id):
        if tool_id == "foo":
            return object()
        return None

    def get_all_tools(self):
        class _Tool:
            def get_tool_name(self):
                return "foo"

            def get_tool_description(self):
                return "stub tool"

        return [_Tool()]


def test_ensure_query_understanding_reuses_session_cache(monkeypatch):
    calls = {"count": 0}

    def fake_build(_parsed):
        calls["count"] += 1
        dataset = kg_resolution.DatasetResolution(
            dataset_id="ds000224",
            name="MSC",
            source_repo="openneuro",
            primary_url=None,
            local_path=None,
            resources=kg_resolution.DatasetResources(
                bids_path=None,
                derivatives={"fmriprep": "/tmp/ds000224-fmriprep"},
                remote_urls={},
                size_bytes=None,
                is_bids_available=False,
                available_derivatives=["fmriprep"],
            ),
        )
        return kg_resolution.QueryUnderstandingResult(
            original_query="use ds000224 fmriprep",
            entities=[],
            resolved_datasets=[dataset],
            existing_derivatives=[],
        )

    monkeypatch.setattr(preflight, "build_query_understanding_result", fake_build)

    ctx1 = {"thread_id": "resolution-thread-query"}
    qur1 = preflight.ensure_query_understanding(
        "use ds000224 fmriprep",
        ctx1,
        parser=_StubParser(),
    )
    assert qur1 is not None
    assert calls["count"] == 1

    ctx2 = {"thread_id": "resolution-thread-query"}
    qur2 = preflight.ensure_query_understanding(
        "use ds000224 fmriprep",
        ctx2,
        parser=_StubParser(),
    )
    assert qur2 is not None
    assert calls["count"] == 1
    state = export_resolution_state(ctx2)
    assert state["step_statuses"]["query_understanding"]["source"] == "session_cache"


def test_ensure_tool_candidates_negative_cache_reuses_platform_knowledge():
    runtime_surface = "unit-capability-negative"
    store = get_platform_knowledge_store()
    store.invalidate_capability_entries(runtime_surface)

    retriever = _EmptyRetriever()
    query = "masker labels time series nilearn"

    ctx1 = {"thread_id": "resolution-thread-capability-1", "runtime_surface": runtime_surface}
    first = preflight.ensure_tool_candidates(query, ctx1, tool_retriever=retriever)
    assert first == []
    assert retriever.calls == 1
    state1 = export_resolution_state(ctx1)
    assert state1["pending_decisions"]
    assert state1["step_statuses"]["tool_candidates"]["status"] == "needs_verification"

    ctx2 = {"thread_id": "resolution-thread-capability-2", "runtime_surface": runtime_surface}
    second = preflight.ensure_tool_candidates(query, ctx2, tool_retriever=retriever)
    assert second == []
    assert retriever.calls == 1
    state2 = export_resolution_state(ctx2)
    assert state2["pending_decisions"]
    assert state2["step_statuses"]["tool_candidates"]["source"] == "platform_knowledge"


def test_force_search_more_bypasses_negative_capability_cache_once():
    runtime_surface = "unit-capability-search-more"
    store = get_platform_knowledge_store()
    store.invalidate_capability_entries(runtime_surface)
    store.set_capability(
        "extract_timeseries",
        runtime_surface,
        status="negative",
        resolved_id_or_path=None,
        source_run_id="run-negative",
    )

    retriever = _SingleMatchRetriever()
    ctx = {
        "thread_id": "resolution-thread-search-more",
        "runtime_surface": runtime_surface,
        "_resolution_force_capability_lookup": "extract_timeseries",
    }
    candidates = preflight.ensure_tool_candidates(
        "masker labels time series nilearn",
        ctx,
        tool_retriever=retriever,
    )

    assert retriever.calls == 1
    assert candidates
    assert candidates[0]["tool_id"] == "foo"
    state = export_resolution_state(ctx)
    assert state["step_statuses"]["tool_candidates"]["status"] == "confirmed"
    assert not state["pending_decisions"]


def test_pending_decisions_persist_across_thread_contexts():
    ctx1 = {"thread_id": "resolution-thread-persist"}
    add_pending_decision(
        ctx1,
        {
            "capability_intent": "extract_timeseries",
            "question": "Use local Nilearn instead, or keep searching?",
            "recommended_choice": "local_nilearn",
            "options": ["local_nilearn", "search_more"],
        },
    )

    ctx2 = {"thread_id": "resolution-thread-persist"}
    pending = get_pending_decisions(ctx2)

    assert pending
    assert pending[0]["capability_intent"] == "extract_timeseries"


def test_clear_tool_index_cache_invalidates_capability_knowledge():
    runtime_surface = "unit-capability-invalidate"
    store = get_platform_knowledge_store()
    store.set_capability(
        "extract_timeseries",
        runtime_surface,
        status="negative",
        resolved_id_or_path=None,
        source_run_id="run-test",
    )
    assert store.get_capability("extract_timeseries", runtime_surface) is not None

    clear_tool_index_cache()

    assert store.get_capability("extract_timeseries", runtime_surface) is None


def test_chat_orchestrator_clarifies_from_resolution_pending_decision(tmp_path, monkeypatch):
    monkeypatch.setenv("BR_USE_TOOL_RETRIEVER", "0")
    orchestrator = ChatOrchestrator(
        router=_StubRouter(),
        tool_router=_StubToolRouter(),
        tool_registry=_StubRegistry(),
        memory=ConversationMemory(store_path=tmp_path / "mem.md"),
    )

    reply = orchestrator.handle_chat(
        "run connectivity",
        history=[],
        ctx={
            "thread_id": "resolution-thread-chat",
            "_resolution_pending_decisions": [
                {
                    "capability_intent": "extract_timeseries",
                    "question": "Use local Nilearn instead, or keep searching?",
                    "recommended_choice": "local_nilearn",
                    "options": ["local_nilearn", "search_more"],
                }
            ],
        },
    )

    assert reply.metadata["type"] == "clarification"
    assert reply.metadata["pending_decision"]["capability_intent"] == "extract_timeseries"
    assert "nilearn" in reply.answer.lower()


def test_chat_orchestrator_applies_resolution_choice_reply(tmp_path, monkeypatch):
    monkeypatch.setenv("BR_USE_TOOL_RETRIEVER", "0")
    orchestrator = ChatOrchestrator(
        router=_StubRouter(
            selection_json='{"tool":"no_tool","params":{},"reasoning":"use local backend"}',
            summary_text="fallback answer",
        ),
        tool_router=_StubToolRouter(),
        tool_registry=_StubRegistry(),
        memory=ConversationMemory(store_path=tmp_path / "mem.md"),
    )

    ctx = {
        "thread_id": "resolution-thread-choice",
        "_resolution_pending_decisions": [
            {
                "capability_intent": "extract_timeseries",
                "question": "Use local Nilearn instead, or keep searching?",
                "recommended_choice": "local_nilearn",
                "options": ["local_nilearn", "search_more"],
            }
        ],
    }

    reply = orchestrator.handle_chat("use local nilearn", history=[], ctx=ctx)

    assert reply.answer == "fallback answer"
    assert get_override(ctx, "extract_timeseries") == "local_nilearn"
    assert get_pending_decisions(ctx) == []


def test_chat_orchestrator_consumes_generic_pending_clarification_one_at_a_time(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("BR_USE_TOOL_RETRIEVER", "0")
    orchestrator = ChatOrchestrator(
        router=_StubRouter(
            selection_json='{"tool":"no_tool","params":{},"reasoning":"fallback"}',
            summary_text="fallback answer",
        ),
        tool_router=_StubToolRouter(),
        tool_registry=_StubRegistry(),
        memory=ConversationMemory(store_path=tmp_path / "mem.md"),
    )

    ctx = {
        "thread_id": "resolution-thread-generic-clarify",
        "_resolution_pending_decisions": [
            {
                "kind": "generic_clarification",
                "source": "query_understanding",
                "clarification_key": "query_understanding:Which dataset id?",
                "question": "Which dataset id?",
            },
            {
                "kind": "generic_clarification",
                "source": "query_understanding",
                "clarification_key": "query_understanding:Which contrast?",
                "question": "Which contrast?",
            },
        ],
    }

    reply = orchestrator.handle_chat("ds000224", history=[], ctx=ctx)

    assert reply.metadata["type"] == "clarification"
    assert reply.metadata["questions"] == ["Which contrast?"]
    assert reply.answer == "Which contrast?"
    assert [item["question"] for item in get_pending_decisions(ctx)] == [
        "Which contrast?"
    ]
    state = export_resolution_state(ctx)
    assert state["generic_clarifications"]["answered_keys"] == [
        "query_understanding:Which dataset id?"
    ]
    assert state["generic_clarifications"]["answers"][0]["answer"] == "ds000224"


def test_resolution_state_survives_checkpoint_round_trip(tmp_path):
    orchestrator = ChatOrchestrator(
        router=_StubRouter(),
        tool_router=_StubToolRouter(),
        tool_registry=_StubRegistry(),
        memory=ConversationMemory(store_path=tmp_path / "mem.md"),
    )

    ctx = {"thread_id": "resolution-thread-checkpoint"}
    add_pending_decision(
        ctx,
        {
            "capability_intent": "extract_timeseries",
            "question": "Use local Nilearn instead, or keep searching?",
            "recommended_choice": "local_nilearn",
            "options": ["local_nilearn", "search_more"],
        },
    )
    ctx["_resolution_session_cache"] = {
        "query_understanding:test": {"status": "resolved", "value": {"ok": True}}
    }

    checkpoint_id = orchestrator._record_checkpoint(
        "resolution-thread-checkpoint",
        ToolPlan(tool="no_tool", params={}, reasoning="checkpoint test"),
        [],
        ctx,
    )

    restored = orchestrator.checkpoints.restore_from_checkpoint(checkpoint_id)
    restored_ctx = restored.variables["ctx"]
    assert (
        restored_ctx["_resolution_pending_decisions"][0]["capability_intent"]
        == "extract_timeseries"
    )
    assert "query_understanding:test" in restored_ctx["_resolution_session_cache"]


def test_chat_orchestrator_restores_pending_decision_from_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("BR_USE_TOOL_RETRIEVER", "0")
    orchestrator = ChatOrchestrator(
        router=_StubRouter(),
        tool_router=_StubToolRouter(),
        tool_registry=_StubRegistry(),
        memory=ConversationMemory(store_path=tmp_path / "mem.md"),
    )

    base_ctx = {
        "thread_id": "resolution-thread-restore-clarify",
        "_resolution_pending_decisions": [
            {
                "capability_intent": "extract_timeseries",
                "question": "Use local Nilearn instead, or keep searching?",
                "recommended_choice": "local_nilearn",
                "options": ["local_nilearn", "search_more"],
            }
        ],
    }
    checkpoint_id = orchestrator._record_checkpoint(
        "resolution-thread-restore-clarify",
        ToolPlan(tool="no_tool", params={}, reasoning="checkpoint restore"),
        [],
        base_ctx,
    )

    reply = orchestrator.handle_chat(
        "continue",
        history=[],
        ctx={
            "thread_id": "resolution-thread-restore-clarify",
            "checkpoint_id": checkpoint_id,
        },
    )

    assert reply.metadata["type"] == "clarification"
    assert reply.metadata["pending_decision"]["capability_intent"] == "extract_timeseries"


def test_chat_orchestrator_applies_resolution_choice_reply_from_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("BR_USE_TOOL_RETRIEVER", "0")
    orchestrator = ChatOrchestrator(
        router=_StubRouter(
            selection_json='{"tool":"no_tool","params":{},"reasoning":"use local backend"}',
            summary_text="fallback answer",
        ),
        tool_router=_StubToolRouter(),
        tool_registry=_StubRegistry(),
        memory=ConversationMemory(store_path=tmp_path / "mem.md"),
    )

    base_ctx = {
        "thread_id": "resolution-thread-restore-choice",
        "_resolution_pending_decisions": [
            {
                "capability_intent": "extract_timeseries",
                "question": "Use local Nilearn instead, or keep searching?",
                "recommended_choice": "local_nilearn",
                "options": ["local_nilearn", "search_more"],
            }
        ],
    }
    checkpoint_id = orchestrator._record_checkpoint(
        "resolution-thread-restore-choice",
        ToolPlan(tool="no_tool", params={}, reasoning="checkpoint restore choice"),
        [],
        base_ctx,
    )

    reply = orchestrator.handle_chat(
        "use local nilearn",
        history=[],
        ctx={
            "thread_id": "resolution-thread-restore-choice",
            "checkpoint_id": checkpoint_id,
        },
    )

    assert reply.answer == "fallback answer"
    assert get_override(
        {"thread_id": "resolution-thread-restore-choice"},
        "extract_timeseries",
    ) == "local_nilearn"
