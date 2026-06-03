"""Compatibility checks for TaskBeacon helper relocation."""

from brain_researcher.services.orchestrator import (
    taskbeacon_handoff as old_handoff,
)
from brain_researcher.services.orchestrator import (
    taskbeacon_mcp_adapter as old_adapter,
)
from brain_researcher.services.tools import taskbeacon_handoff as new_handoff
from brain_researcher.services.tools import taskbeacon_mcp_adapter as new_adapter


def test_orchestrator_taskbeacon_handoff_reexports_tools_helpers() -> None:
    assert old_handoff is new_handoff
    assert old_handoff.normalize_taskbeacon_repo is new_handoff.normalize_taskbeacon_repo
    assert old_handoff.materialize_taskbeacon_repo is new_handoff.materialize_taskbeacon_repo


def test_orchestrator_taskbeacon_adapter_reexports_tools_helpers() -> None:
    assert old_adapter is new_adapter
    assert old_adapter.TaskBeaconMCPCallResult is new_adapter.TaskBeaconMCPCallResult
    assert old_adapter.list_taskbeacon_tasks is new_adapter.list_taskbeacon_tasks
    assert old_adapter.download_taskbeacon_task is new_adapter.download_taskbeacon_task
