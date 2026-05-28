from pathlib import Path

from brain_researcher.services.agent.codegen.runner import run_checks


def test_runner_fails_loud_without_verification_evidence():
    result = run_checks()

    assert not result.success
    assert "No verification evidence available" in result.stderr


def test_runner_compiles_python_file(tmp_path: Path):
    mod = tmp_path / "ok.py"
    mod.write_text("value = 1\n", encoding="utf-8")

    result = run_checks(file_paths=[str(mod)])

    assert result.success
