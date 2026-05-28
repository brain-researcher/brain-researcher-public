import json
from types import SimpleNamespace

from brain_researcher.services.agent.chat_orchestrator import ChatOrchestrator
from brain_researcher.services.agent.tool_router import RoutingToolView, ToolFamily


class FakeLLMRouter:
    def __init__(self, selection_text: str, answer_text: str = "final answer"):
        self.selection_text = selection_text
        self.answer_text = answer_text
        self.selection_calls = []
        self.answer_calls = []

    def route_chat(self, prompt):
        if isinstance(prompt, str) and "Respond ONLY with JSON" in prompt:
            self.selection_calls.append(prompt)
            return SimpleNamespace(text=self.selection_text)
        self.answer_calls.append(prompt)
        return SimpleNamespace(text=self.answer_text)


class FakeRuntimeTool:
    def __init__(self, tool_id: str):
        self.id = tool_id
        self.spec = SimpleNamespace(name=tool_id, description="", tags=[])

    def get_tool_name(self):
        return self.id

    def get_tool_description(self):
        return ""

    def get_args_schema(self):
        return SimpleNamespace(model_json_schema=lambda: {})


class FakeRuntimeRegistry:
    def __init__(self, tools: dict[str, FakeRuntimeTool]):
        self._tools = tools

    def get_runtime_tool(self, tool_id: str):
        return self._tools.get(tool_id)

    # compatibility if router uses get_all_tools
    def get_all_tools(self):
        return list(self._tools.values())


class FakeToolExecutor:
    def __init__(self):
        self.calls = []

    def execute(self, request):
        self.calls.append(request)
        # mimic ToolExecutionResult fields accessed in orchestrator
        return SimpleNamespace(
            status="success", result={"ok": True}, error=None, metadata={}
        )


def test_orchestrator_no_tool_path():
    llm = FakeLLMRouter(
        selection_text=json.dumps(
            {"tool": "no_tool", "params": {}, "reasoning": "none"}
        ),
        answer_text="direct",
    )
    execu = FakeToolExecutor()
    reg = FakeRuntimeRegistry({})
    router = SimpleNamespace(get_candidates=lambda u, h, c: [])

    orch = ChatOrchestrator(
        router=llm, tool_executor=execu, tool_registry=reg, tool_router=router
    )
    reply = orch.handle_chat("Explain GLM", history=[], ctx={})

    assert execu.calls == []
    assert reply.tool_calls == []


def test_orchestrator_leaf_tool_exec():
    selection = json.dumps(
        {"tool": "leaf.tool", "params": {"x": 1}, "reasoning": "need leaf"}
    )
    llm = FakeLLMRouter(selection_text=selection, answer_text="summary")
    execu = FakeToolExecutor()
    reg = FakeRuntimeRegistry({"leaf.tool": FakeRuntimeTool("leaf.tool")})
    router = SimpleNamespace(
        get_candidates=lambda u, h, c: [
            RoutingToolView(
                runtime_id="leaf.tool",
                name="leaf.tool",
                description="leaf",
                tags=[],
                dangerous=False,
                family_id=None,
                family_ops=None,
            )
        ]
    )

    orch = ChatOrchestrator(
        router=llm, tool_executor=execu, tool_registry=reg, tool_router=router
    )
    plan_dict = {"tool": "leaf.tool", "params": {"x": 1}, "reasoning": "need leaf"}
    plan = orch._enrich_plan(plan_dict)
    orch._execute_tool(plan, ctx={})

    assert len(execu.calls) == 1
    req = execu.calls[0]
    assert req.tool_name == "leaf.tool"
    assert req.parameters == {"x": 1}


def test_orchestrator_family_tool_maps_to_leaf():
    fam = ToolFamily(
        id="jobs.client",
        description="jobs client",
        op_param="op",
        ops={"status": "jobs.get_job_status"},
    )
    selection = json.dumps(
        {
            "tool": "jobs.client",
            "params": {"op": "status", "job_id": "123"},
            "reasoning": "need status",
        }
    )
    llm = FakeLLMRouter(selection_text=selection, answer_text="status ok")
    execu = FakeToolExecutor()
    reg = FakeRuntimeRegistry(
        {"jobs.get_job_status": FakeRuntimeTool("jobs.get_job_status")}
    )
    router = SimpleNamespace(
        get_candidates=lambda u, h, c: [
            RoutingToolView(
                runtime_id="jobs.client",
                name="jobs.client",
                description="family",
                tags=[],
                dangerous=False,
                family_id="jobs.client",
                family_ops=["status"],
            )
        ]
    )
    orch = ChatOrchestrator(
        router=llm, tool_executor=execu, tool_registry=reg, tool_router=router
    )
    orch.families = {"jobs.client": fam}
    plan_dict = {
        "tool": "jobs.client",
        "params": {"op": "status", "job_id": "123"},
        "reasoning": "need status",
    }
    plan = orch._enrich_plan(plan_dict)
    orch._execute_tool(plan, ctx={})

    assert len(execu.calls) == 1
    req = execu.calls[0]
    assert req.tool_name == "jobs.get_job_status"
    assert req.parameters.get("job_id") == "123"


def test_orchestrator_uses_shared_tool_candidate_service(monkeypatch):
    calls = {"count": 0}

    def fake_generate_tool_candidates(query, *, ctx=None, **kwargs):
        calls["count"] += 1
        ctx = ctx or {}
        ctx["tool_candidate_diagnostics"] = {
            "candidate_count": 0,
            "candidate_generation_latency_ms": 1.0,
            "retrieval_path": "fake",
        }
        return SimpleNamespace(
            ctx=ctx,
            query_understanding=None,
            tool_candidates=[],
            tool_candidate_diagnostics=ctx["tool_candidate_diagnostics"],
            resolution_state={},
        )

    monkeypatch.setattr(
        "brain_researcher.services.agent.chat_orchestrator.generate_tool_candidates",
        fake_generate_tool_candidates,
    )

    llm = FakeLLMRouter(
        selection_text=json.dumps(
            {"tool": "no_tool", "params": {}, "reasoning": "none"}
        ),
        answer_text="direct",
    )
    execu = FakeToolExecutor()
    reg = FakeRuntimeRegistry({})
    router = SimpleNamespace(get_candidates=lambda u, h, c: [])

    orch = ChatOrchestrator(
        router=llm,
        tool_executor=execu,
        tool_registry=reg,
        tool_router=router,
        enable_knowledge_layer=False,
    )
    reply = orch.handle_chat("Explain GLM", history=[], ctx={})

    assert calls["count"] == 1
    assert reply.metadata["tool_routing"]["preflight"]["retrieval_path"] == "fake"
