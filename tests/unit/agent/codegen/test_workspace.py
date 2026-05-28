from pathlib import Path
import os
import pytest

from brain_researcher.services.agent.codegen.workspace import Workspace


@pytest.fixture(autouse=True)
def _force_writable_tmp(monkeypatch, tmp_path):
    """Ensure patch/tmp operations use a writable temp dir during tests."""
    work_tmp = tmp_path / "tmp"
    work_tmp.mkdir(parents=True, exist_ok=True)
    for var in ("TMPDIR", "TMP", "TEMP"):
        monkeypatch.setenv(var, str(work_tmp))

def test_workspace_apply_patch_and_run_checks(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    file_path = repo / "hello.py"
    file_path.write_text("def add(a, b):\n    return a + b\n")

    ws = Workspace(repo_root=repo)
    ws.materialize_files(["hello.py"])

    patch = """--- hello.py
+++ hello.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a + b
+    return a - b
"""

    ws.apply_patch(patch)
    result = ws.run_checks()

    assert result.success
    assert "hello.py" in ws.files_touched()


def test_workspace_detects_py_compile_error(tmp_path: Path):
    repo = tmp_path / "repo2"
    repo.mkdir()
    file_path = repo / "bad.py"
    file_path.write_text("def oops(:\n    pass\n")

    ws = Workspace(repo_root=repo)
    ws.materialize_files(["bad.py"])

    result = ws.run_checks()

    assert not result.success
    assert "bad.py" in result.stderr


def test_workspace_rejects_disallowed_command(tmp_path: Path):
    repo = tmp_path / "repo3"
    repo.mkdir()
    (repo / "ok.py").write_text("print('hi')\n")
    ws = Workspace(repo_root=repo)
    ws.materialize_files(["ok.py"])

    result = ws.run_checks(test_command="rm -rf /")

    assert not result.success
    assert "not allowed" in result.stderr


def test_workspace_fails_loud_without_verification_evidence(tmp_path: Path):
    repo = tmp_path / "repo4"
    repo.mkdir()
    (repo / "README.md").write_text("# notes\n", encoding="utf-8")

    ws = Workspace(repo_root=repo)
    ws.materialize_files(["README.md"])

    result = ws.run_checks()

    assert not result.success
    assert "No verification evidence available" in result.stderr


def test_workspace_checks_touched_python_file_added_by_patch(tmp_path: Path):
    repo = tmp_path / "repo5"
    repo.mkdir()
    (repo / "seed.py").write_text("x = 1\n", encoding="utf-8")

    ws = Workspace(repo_root=repo)
    ws.materialize_files(["seed.py"])
    patch = """--- /dev/null
+++ added.py
@@ -0,0 +1 @@
+value = 1
"""

    ws.apply_patch(patch)
    result = ws.run_checks()

    assert result.success
    assert "added.py" in ws.files_touched()
