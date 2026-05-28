from pathlib import Path

import pytest

from brain_researcher.services.agent.codegen.constitution import (
    format_codegen_constitution_for_prompt,
    load_codegen_constitution,
)


def test_load_codegen_constitution_reads_default_file():
    payload = load_codegen_constitution()
    assert payload["title"] == "Brain Researcher Codegen Constitution"
    assert isinstance(payload["sections"], list)
    assert payload["sections"]


def test_format_codegen_constitution_for_prompt_includes_key_rules():
    text = format_codegen_constitution_for_prompt()
    assert "Silent failure is unacceptable" in text
    assert "Fail loud" in text
    assert "Failed Cases Matter More" in text
    assert "Benchmark Design" in text


def test_load_codegen_constitution_fails_for_missing_file(tmp_path: Path):
    missing = tmp_path / "missing.yaml"
    with pytest.raises(FileNotFoundError):
        load_codegen_constitution(missing)
