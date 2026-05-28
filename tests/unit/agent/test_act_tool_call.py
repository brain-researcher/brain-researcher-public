from brain_researcher.cli.agent.act import act_in_process
from brain_researcher.services.agent import telemetry
from brain_researcher.services.agent.router import LLMRouteMetadata, LLMChatResult
from pydantic import BaseModel


def test_act_preview_records_run_metadata(monkeypatch):
    events = []

    def fake_record_event(payload, event_type="act"):
        events.append((event_type, payload))

    monkeypatch.setattr(telemetry, "record_event", fake_record_event)

    result = act_in_process(
        "Run fmriprep on ds000001",
        preview=True,
        tools_whitelist=["fmriprep"],
    )

    assert "run_id" in result
    assert result["selection"]["tool"]
    assert events, "telemetry events should be recorded"

    event_type, payload = events[0]
    assert event_type == "act"
    assert payload["run_id"] == result["run_id"]
    assert payload["tooling"]["selected_tool"] == result["selection"]["tool"]
    assert payload["tooling"]["result_status"] == "skipped"


def test_act_executes_tool_and_records_event(monkeypatch):
    events = []

    def fake_record_event(payload, event_type="act"):
        events.append((event_type, payload))

    monkeypatch.setattr(telemetry, "record_event", fake_record_event)

    class DemoArgs(BaseModel):
        value: str

    class DemoTool:
        EXAMPLES = []

        def get_tool_name(self):
            return "demo.tool"

        def get_tool_description(self):
            return "Demo tool"

        def get_args_schema(self):
            return DemoArgs

        def run(self, **kwargs):
            return {"status": "success", "data": kwargs}

    class DemoRegistry:
        def __init__(self):
            self.tool = DemoTool()

        def get_all_tools(self):
            return [self.tool]

        def get_tool(self, name):
            if name == "demo.tool":
                return self.tool
            return None

    class DemoAgent:
        def __init__(self, tool_registry=None):
            self.tool_registry = DemoRegistry()

    import brain_researcher.cli.agent.act as act_module
    import brain_researcher.services.agent.agents.neuro_agent as neuro_agent_module
    import brain_researcher.services.agent.tool_executor as tool_executor_module

    monkeypatch.setattr(neuro_agent_module, "NeuroAgent", DemoAgent, raising=False)

    metadata = LLMRouteMetadata(
        provider="google",
        model="gemini-2.5-pro",
        route="primary",
        transport="cli",
        usage={"total_tokens": 5},
    )
    metadata.latency_ms = 10

    monkeypatch.setattr(
        act_module._ROUTER,
        "route_chat",
        lambda prompt, model_hint=None: LLMChatResult(
            text='{"tool": "demo.tool", "params": {"value": "hello"}, "reasoning": "test"}',
            metadata=metadata,
        ),
    )

    class DummyExecutor:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute_with_timeout(self, tool, args, timeout_ms=None, trace_id=None):
            class Result:
                status = "success"
                data = args
                error = None
                metadata = {}

            return Result()

    # Patch both the act module reference and the underlying tool_executor reference
    # to avoid hitting real registries/redis during the test.
    monkeypatch.setattr(act_module, "BudgetedToolExecutor", DummyExecutor, raising=False)
    monkeypatch.setattr(tool_executor_module, "BudgetedToolExecutor", DummyExecutor, raising=False)

    result = act_in_process(
        "Please run the demo",
        preview=False,
        tools_whitelist=["demo.tool"],
        budget_ms=1000,
    )

    assert result["selection"]["tool"] == "demo.tool"
    assert result["tool_result"]["status"] == "success"
    assert result["tool_result"]["data"]["value"] == "hello"
    assert "run_id" in result
    assert events
    event_payload = events[0][1]
    assert event_payload["run_id"] == result["run_id"]
    assert event_payload["tooling"]["selected_tool"] == "demo.tool"
    assert event_payload["tooling"]["result_status"] == "success"
