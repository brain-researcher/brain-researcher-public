from brain_researcher.services.agent.chat_orchestrator import ChatOrchestrator, ToolPlan
from brain_researcher.services.tools.tool_registry import ToolRegistry
from brain_researcher.services.agent.codegen.workspace import apply_patches_to_repo
import pytest
import os


class DummyRouter:
    """Router placeholder; not used in this test."""


class FakeFsClient:
    async def search_text(self, query: str, root: str, max_results: int = 200):
        return [{"path": "a.py", "line": 3}]

    async def read_file(self, path: str, max_bytes: int = 8000, offset: int = 0):
        return "print('hi')\n"


def test_orchestrator_prefetches_files_for_coding_tool():
    orch = ChatOrchestrator(
        router=DummyRouter(),
        tool_executor=None,
        tool_registry=ToolRegistry(),
        tool_router=None,
        memory=None,
        error_recovery=False,
        enable_knowledge_layer=False,
    )

    plan = ToolPlan(tool="code_agent", params={}, reasoning="", leaf_runtime_id="code_agent")
    ctx = {"fs_client": FakeFsClient()}

    enriched = orch._maybe_enrich_coding_plan(plan, "print hello", ctx)

    assert "prefetched_files" in enriched.params
    pf = enriched.params["prefetched_files"][0]
    assert pf["path"] == "a.py"
    assert enriched.params.get("auto_fs_context") is False


@pytest.fixture(autouse=True)
def _force_writable_tmp(monkeypatch, tmp_path):
    """Ensure patch utility uses a writable temp dir during tests."""
    work_tmp = tmp_path / "tmp"
    work_tmp.mkdir(parents=True, exist_ok=True)
    for var in ("TMPDIR", "TMP", "TEMP"):
        monkeypatch.setenv(var, str(work_tmp))


def test_orchestrator_apply_pending(monkeypatch, tmp_path):
    orch = ChatOrchestrator(
        router=DummyRouter(),
        tool_executor=None,
        tool_registry=ToolRegistry(),
        tool_router=None,
        memory=None,
        error_recovery=False,
        enable_knowledge_layer=False,
    )

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.txt").write_text("hi\n")

    # seed pending patches
    orch._pending_patches["default"] = {
        "patches": ["--- a.txt\n+++ a.txt\n@@ -1,1 +1,1 @@\n-hi\n+hello\n"],
        "repo_root": str(repo),
    }

    reply = orch.handle_chat("apply patches", ctx={"thread_id": "default"})
    assert "applied" in reply.answer.lower()
    assert (repo / "a.txt").read_text() == "hello\n"
