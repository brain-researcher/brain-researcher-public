from brain_researcher.services.agent.tool_metadata_bridge import (
    get_resource_hints,
    get_example_payload,
)
from brain_researcher.services.agent.resources.resource_limits import get_tool_profile
from brain_researcher.services.agent.resources.resource_manager import ResourceManager, Priority


def test_get_resource_hints_matches_alias():
    hints = get_resource_hints("fmriprep")
    assert hints
    assert hints["cpu"] >= 1
    assert hints["mem_gb"] >= 1


def test_get_example_payload_returns_dict():
    example = get_example_payload("fitlins")
    assert isinstance(example, dict)
    assert "bids_dir" in example or "bids_dir" in "".join(example.keys())


def test_get_tool_profile_respects_hints():
    profile = get_tool_profile("bidsapp.fmriprep.run")
    assert profile.cpu_cores >= 4
    assert profile.memory_gb >= 16


def test_resource_manager_priority_adjusts_with_profile(monkeypatch):
    captured = {}

    rm = ResourceManager(max_cpu_cores=0.5, max_memory_gb=0.5, enable_queueing=True)
    assert rm.queue_manager is not None

    original_enqueue = rm.queue_manager.enqueue

    def fake_enqueue(entry):
        captured["entry"] = entry
        return False

    rm.queue_manager.enqueue = fake_enqueue  # type: ignore[attr-defined]

    rm.request_resources(
        "bidsapp.fmriprep.run", "exec-test", priority=Priority.NORMAL, timeout=0.01
    )

    rm.queue_manager.enqueue = original_enqueue  # restore

    entry = captured.get("entry")
    assert entry is not None
    assert entry.priority == Priority.LOW
