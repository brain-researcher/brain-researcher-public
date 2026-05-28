from types import SimpleNamespace

from brain_researcher.sdk.chat import (
    _coerce_marimo_codegen_result,
    _extract_notebook_code,
    _preferred_credential_name,
)


def test_extract_notebook_code_strips_language_marker_from_patch_snippet():
    code = _extract_notebook_code(
        [
            "python\nimport marimo\napp = marimo.App()\n\n@app.cell\ndef _():\n    return\n"
        ]
    )
    assert code is not None
    assert code.startswith("import marimo")
    assert not code.startswith("python")


def test_extract_notebook_code_strips_fence_and_language_marker():
    code = _extract_notebook_code(
        [
            "```python\nimport marimo\napp = marimo.App()\n\n@app.cell\ndef _():\n    return\n```"
        ]
    )
    assert code is not None
    assert code.startswith("import marimo")
    assert "@app.cell" in code


def test_preferred_credential_name_prefers_env_gemini_for_gemini_models(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    assert _preferred_credential_name("gemini-2.0-flash", None) == "env_gemini"


def test_preferred_credential_name_keeps_explicit_override(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    assert _preferred_credential_name("gemini-2.0-flash", "local_oauth") == "local_oauth"


def test_coerce_marimo_codegen_result_normalizes_preview(tmp_path):
    result = SimpleNamespace(
        patches=[
            "python\nimport marimo\napp = marimo.App()\n\n@app.cell\ndef _():\n    return\n"
        ],
        status="failed",
        answer="patch -p0 says only garbage was found in the patch input",
        files_touched=["ignored.py"],
    )

    changed = _coerce_marimo_codegen_result(result, str(tmp_path / "preview.py"), apply=False)

    assert changed is True
    assert result.status == "success"
    assert result.files_touched == []
    assert "Generated Marimo notebook preview" in result.answer


def test_coerce_marimo_codegen_result_writes_file_when_apply_true(tmp_path):
    out = tmp_path / "notebook.py"
    result = SimpleNamespace(
        patches=[
            "python\nimport marimo\napp = marimo.App()\n\n@app.cell\ndef _():\n    return\n"
        ],
        status="failed",
        answer="patch -p0 says only garbage was found in the patch input",
        files_touched=[],
    )

    changed = _coerce_marimo_codegen_result(result, str(out), apply=True)

    assert changed is True
    assert result.status == "success"
    assert result.files_touched == [str(out)]
    assert out.exists()
    assert out.read_text().startswith("import marimo")
