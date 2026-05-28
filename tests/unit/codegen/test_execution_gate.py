from pathlib import Path

from brain_researcher.services.agent.codegen.execution_gate import (
    build_verification_plan,
)


def test_build_verification_plan_prefers_test_command(tmp_path: Path):
    plan = build_verification_plan(
        workdir=tmp_path,
        test_command="pytest tests/unit/codegen/test_loop.py -q",
    )

    assert plan.mode == "test_command"
    assert not plan.candidate_paths


def test_build_verification_plan_uses_touched_python_files(tmp_path: Path):
    mod = tmp_path / "pkg" / "mod.py"
    mod.parent.mkdir(parents=True, exist_ok=True)
    mod.write_text("x = 1\n", encoding="utf-8")

    plan = build_verification_plan(
        workdir=tmp_path,
        touched=["pkg/mod.py", "README.md"],
    )

    assert plan.mode == "py_compile"
    assert plan.candidate_paths == (mod,)


def test_build_verification_plan_fails_loud_without_verification_evidence(tmp_path: Path):
    readme = tmp_path / "README.md"
    readme.write_text("# notes\n", encoding="utf-8")

    plan = build_verification_plan(
        workdir=tmp_path,
        touched=["README.md"],
    )

    assert plan.mode == "none"
    assert "Silent success is forbidden" in (plan.reason or "")
