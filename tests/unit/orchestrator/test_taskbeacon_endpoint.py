from __future__ import annotations

from types import SimpleNamespace

import pytest

from brain_researcher.services.orchestrator.endpoints import taskbeacon


@pytest.mark.asyncio
async def test_list_taskbeacon_catalog_returns_normalized_envelope(monkeypatch) -> None:
    async def fake_require_user(_request) -> None:
        return None

    async def fake_list_taskbeacon_tasks(*, query, limit):
        assert query == "ant"
        assert limit == 7
        return {
            "source": "taskbeacon_mcp",
            "count": 1,
            "tasks": [{"repo": "TaskBeacon/T000015-ant"}],
        }

    monkeypatch.setattr(taskbeacon, "_require_user", fake_require_user)
    monkeypatch.setattr(
        taskbeacon,
        "async_list_taskbeacon_tasks",
        fake_list_taskbeacon_tasks,
    )

    response = await taskbeacon.list_taskbeacon_catalog(
        SimpleNamespace(),
        query="ant",
        limit=7,
    )

    assert response.model_dump() == {
        "source": "taskbeacon_mcp",
        "count": 1,
        "tasks": [{"repo": "TaskBeacon/T000015-ant"}],
    }


@pytest.mark.asyncio
async def test_download_taskbeacon_catalog_task_uses_configured_workspace(
    monkeypatch,
    tmp_path,
) -> None:
    async def fake_require_user(_request) -> None:
        return None

    calls: list[dict] = []

    async def fake_download_taskbeacon_task(**kwargs):
        calls.append(kwargs)
        return {"status": "success", "target_dir": "/workspace/task"}

    monkeypatch.setenv("BR_TASKBEACON_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(taskbeacon, "_require_user", fake_require_user)
    monkeypatch.setattr(
        taskbeacon,
        "async_download_taskbeacon_task",
        fake_download_taskbeacon_task,
    )

    response = await taskbeacon.download_taskbeacon_catalog_task(
        SimpleNamespace(),
        taskbeacon.TaskBeaconDownloadRequest(
            repo="TaskBeacon/T000015-ant",
            project_id="proj_demo",
        ),
    )

    assert response.result == {"status": "success", "target_dir": "/workspace/task"}
    assert calls[0]["workspace_root"] == tmp_path.resolve()
    assert calls[0]["target_path"] == "projects/proj_demo/taskbeacon/T000015-ant"


@pytest.mark.asyncio
async def test_download_taskbeacon_catalog_task_rejects_in_band_error(
    monkeypatch,
    tmp_path,
) -> None:
    async def fake_require_user(_request) -> None:
        return None

    async def fake_download_taskbeacon_task(**_kwargs):
        return {"status": "error", "stderr": "fatal: network blocked"}

    monkeypatch.setenv("BR_TASKBEACON_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(taskbeacon, "_require_user", fake_require_user)
    monkeypatch.setattr(
        taskbeacon,
        "async_download_taskbeacon_task",
        fake_download_taskbeacon_task,
    )

    with pytest.raises(taskbeacon.HTTPException) as excinfo:
        await taskbeacon.download_taskbeacon_catalog_task(
            SimpleNamespace(),
            taskbeacon.TaskBeaconDownloadRequest(repo="TaskBeacon/T000015-ant"),
        )

    assert excinfo.value.status_code == 502
    assert "fatal: network blocked" in str(excinfo.value.detail)


def test_workspace_root_requires_explicit_data_root(monkeypatch) -> None:
    monkeypatch.delenv("BR_TASKBEACON_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("BR_DATA_ROOT", raising=False)

    with pytest.raises(ValueError, match="BR_TASKBEACON_WORKSPACE_ROOT"):
        taskbeacon._workspace_root()


@pytest.mark.asyncio
async def test_run_taskbeacon_catalog_task_is_disabled_by_default(monkeypatch) -> None:
    async def fake_require_user(_request) -> None:
        return None

    monkeypatch.delenv("BR_TASKBEACON_ENABLE_ORCHESTRATOR_RUN", raising=False)
    monkeypatch.setattr(taskbeacon, "_require_user", fake_require_user)

    with pytest.raises(taskbeacon.HTTPException) as excinfo:
        await taskbeacon.run_taskbeacon_catalog_task(
            SimpleNamespace(),
            taskbeacon.TaskBeaconRunRequest(
                task_path="projects/proj/taskbeacon/T000015-ant",
            ),
        )

    assert excinfo.value.status_code == 503
    assert "disabled in the central orchestrator" in str(excinfo.value.detail)


@pytest.mark.asyncio
async def test_run_taskbeacon_catalog_task_can_be_enabled(monkeypatch, tmp_path) -> None:
    async def fake_require_user(_request) -> None:
        return None

    calls: list[dict] = []

    async def fake_run_taskbeacon_qa_sim(**kwargs):
        calls.append(kwargs)
        return {"status": "success", "returncode": 0}

    monkeypatch.setenv("BR_TASKBEACON_ENABLE_ORCHESTRATOR_RUN", "1")
    monkeypatch.setenv("BR_TASKBEACON_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(taskbeacon, "_require_user", fake_require_user)
    monkeypatch.setattr(
        taskbeacon,
        "async_run_taskbeacon_qa_sim",
        fake_run_taskbeacon_qa_sim,
    )

    response = await taskbeacon.run_taskbeacon_catalog_task(
        SimpleNamespace(),
        taskbeacon.TaskBeaconRunRequest(
            task_path="projects/proj/taskbeacon/T000015-ant",
            mode="sim",
            timeout_seconds=17,
        ),
    )

    assert response.result == {"status": "success", "returncode": 0}
    assert calls[0]["workspace_root"] == tmp_path.resolve()
    assert calls[0]["mode"] == "sim"
    assert calls[0]["timeout_seconds"] == 17
