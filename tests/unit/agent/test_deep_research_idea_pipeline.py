from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from brain_researcher.services.agent import deep_research_idea_pipeline as pipeline


def test_resolve_kggen_python_prefers_env_override(tmp_path: Path, monkeypatch) -> None:
    override = tmp_path / "kggen-python"
    override.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("BR_DEEP_RESEARCH_IDEA_KGGEN_PYTHON", str(override))

    resolved = pipeline._resolve_kggen_python()

    assert resolved == override.resolve()


def test_resolve_kggen_python_falls_back_to_current_interpreter(
    monkeypatch,
) -> None:
    monkeypatch.delenv("BR_DEEP_RESEARCH_IDEA_KGGEN_PYTHON", raising=False)
    monkeypatch.setattr(
        pipeline,
        "_kggen_python_path",
        lambda: Path("/definitely/missing/kggen-python"),
    )
    monkeypatch.setattr(pipeline, "_current_python_has_kggen", lambda: True)

    resolved = pipeline._resolve_kggen_python()

    assert resolved == Path(sys.executable).resolve()


def test_resolve_kggen_python_raises_when_no_runtime(monkeypatch) -> None:
    missing = Path("/definitely/missing/kggen-python")
    monkeypatch.delenv("BR_DEEP_RESEARCH_IDEA_KGGEN_PYTHON", raising=False)
    monkeypatch.setattr(pipeline, "_kggen_python_path", lambda: missing)
    monkeypatch.setattr(pipeline, "_current_python_has_kggen", lambda: False)

    with pytest.raises(RuntimeError, match="KGGEN runtime not available"):
        pipeline._resolve_kggen_python()


def test_generate_deep_research_idea_cards_uses_partial_output_after_timeout(
    tmp_path: Path, monkeypatch
) -> None:
    bridge_dir = tmp_path / "bridge"
    bridge_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = bridge_dir / "manifest.json"
    manifest_path.write_text(json.dumps({"shards": []}), encoding="utf-8")
    kggen_python = tmp_path / "kggen-python"
    kggen_python.write_text("#!/bin/sh\n", encoding="utf-8")
    script_path = tmp_path / "kggen_generate_from_manifest.py"
    script_path.write_text("print('stub')\n", encoding="utf-8")

    monkeypatch.setattr(pipeline, "_resolve_kggen_python", lambda: kggen_python)
    monkeypatch.setattr(pipeline, "_kggen_script_path", lambda: script_path)
    monkeypatch.setattr(
        pipeline, "coerce_deep_research_result", lambda payload: dict(payload)
    )

    def fake_write_manifest(*args, **kwargs):
        del args, kwargs
        return {"sources_written": 1}

    monkeypatch.setattr(
        pipeline, "write_gabriel_manifest_from_deep_research", fake_write_manifest
    )

    def fake_build_cards(**kwargs):
        kggen_input = Path(kwargs["kggen_input"])
        assert kggen_input.exists()
        return {"candidate_cards": [{"card_id": "dr_partial"}], "summary": {"n": 1}}

    monkeypatch.setattr(pipeline, "build_deep_research_idea_cards", fake_build_cards)

    def fake_run(cmd, **kwargs):
        del kwargs
        output_path = Path(cmd[cmd.index("--output") + 1])
        output_path.write_text(
            json.dumps({"paper": {"id": "p1"}, "relations": [{"subject": "a"}]}) + "\n",
            encoding="utf-8",
        )
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=420.0)

    monkeypatch.setattr(pipeline.subprocess, "run", fake_run)

    payload = pipeline.generate_deep_research_idea_cards_from_result(
        deep_research_result={"documents": [{"url": "https://example.org"}]},
        query="mdd mitochondria",
        output_dir=tmp_path,
    )

    assert payload["candidate_cards"][0]["card_id"] == "dr_partial"
    assert "kggen_timeout_partial_output_used" in payload["warnings"]
    assert payload["kggen_summary"]["status"] == "partial_timeout"


def test_generate_deep_research_idea_cards_retries_reduced_config_after_timeout(
    tmp_path: Path, monkeypatch
) -> None:
    bridge_dir = tmp_path / "bridge"
    bridge_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = bridge_dir / "manifest.json"
    manifest_path.write_text(json.dumps({"shards": []}), encoding="utf-8")
    kggen_python = tmp_path / "kggen-python"
    kggen_python.write_text("#!/bin/sh\n", encoding="utf-8")
    script_path = tmp_path / "kggen_generate_from_manifest.py"
    script_path.write_text("print('stub')\n", encoding="utf-8")

    monkeypatch.setattr(pipeline, "_resolve_kggen_python", lambda: kggen_python)
    monkeypatch.setattr(pipeline, "_kggen_script_path", lambda: script_path)
    monkeypatch.setattr(
        pipeline, "coerce_deep_research_result", lambda payload: dict(payload)
    )

    def fake_write_manifest(*args, **kwargs):
        del args, kwargs
        return {"sources_written": 1}

    monkeypatch.setattr(
        pipeline, "write_gabriel_manifest_from_deep_research", fake_write_manifest
    )

    def fake_build_cards(**kwargs):
        return {"candidate_cards": [{"card_id": "dr_retry"}], "summary": {"n": 1}}

    monkeypatch.setattr(pipeline, "build_deep_research_idea_cards", fake_build_cards)

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        del kwargs
        calls.append(list(cmd))
        output_path = Path(cmd[cmd.index("--output") + 1])
        summary_path = Path(cmd[cmd.index("--summary-output") + 1])
        if len(calls) == 1:
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=420.0)
        output_path.write_text(
            json.dumps({"paper": {"id": "p2"}, "relations": [{"subject": "b"}]}) + "\n",
            encoding="utf-8",
        )
        summary_path.write_text(
            json.dumps({"status": "ok", "attempt": "retry"}),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(pipeline.subprocess, "run", fake_run)

    payload = pipeline.generate_deep_research_idea_cards_from_result(
        deep_research_result={"documents": [{"url": "https://example.org"}]},
        query="mdd mitochondria",
        output_dir=tmp_path,
    )

    assert payload["candidate_cards"][0]["card_id"] == "dr_retry"
    assert "kggen_timeout_retrying_reduced_config" in payload["warnings"]
    assert "kggen_retry_succeeded" in payload["warnings"]
    assert len(calls) == 2
    retry_cmd = calls[1]
    assert "--no-dspy" in retry_cmd
    assert retry_cmd[retry_cmd.index("--max-papers") + 1] == "2"
    assert retry_cmd[retry_cmd.index("--max-relations-per-paper") + 1] == "20"
