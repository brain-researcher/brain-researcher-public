from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_script_module(relative_path: str, module_name: str):
    script_path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec is not None and spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    fake_sentence_transformers = types.ModuleType("sentence_transformers")
    fake_sentence_transformers.SentenceTransformer = object
    fake_sentence_transformers.util = types.SimpleNamespace()

    previous = sys.modules.get("sentence_transformers")
    sys.modules["sentence_transformers"] = fake_sentence_transformers
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            sys.modules.pop("sentence_transformers", None)
        else:
            sys.modules["sentence_transformers"] = previous

    return module


@pytest.mark.parametrize(
    ("relative_path", "module_name"),
    [
        ("scripts/eval/semantic_screening_baseline.py", "semantic_screening_baseline_for_test"),
        ("scripts/eval/hybrid_screening_baseline.py", "hybrid_screening_baseline_for_test"),
    ],
)
def test_resolve_graphql_url_defaults_to_localhost(
    monkeypatch: pytest.MonkeyPatch,
    relative_path: str,
    module_name: str,
) -> None:
    for key in [
        "NEUROKG_GRAPHQL_URL",
        "BR_NEUROKG_URL",
        "NEUROKG_BASE_URL",
        "NEUROKG_URL",
        "NEUROKG_API_URL",
    ]:
        monkeypatch.delenv(key, raising=False)

    module = _load_script_module(relative_path, module_name)

    assert module.resolve_graphql_url() == "http://localhost:5000/graphql"


@pytest.mark.parametrize(
    ("relative_path", "module_name"),
    [
        ("scripts/eval/semantic_screening_baseline.py", "semantic_screening_baseline_env_test"),
        ("scripts/eval/hybrid_screening_baseline.py", "hybrid_screening_baseline_env_test"),
    ],
)
def test_resolve_graphql_url_appends_suffix_for_base_url(
    monkeypatch: pytest.MonkeyPatch,
    relative_path: str,
    module_name: str,
) -> None:
    monkeypatch.setenv("NEUROKG_URL", "http://kg.internal:5000")

    module = _load_script_module(relative_path, module_name)

    assert module.resolve_graphql_url() == "http://kg.internal:5000/graphql"


@pytest.mark.parametrize(
    ("relative_path", "module_name"),
    [
        ("scripts/eval/semantic_screening_baseline.py", "semantic_screening_baseline_arg_test"),
        ("scripts/eval/hybrid_screening_baseline.py", "hybrid_screening_baseline_arg_test"),
    ],
)
def test_resolve_graphql_url_preserves_explicit_graphql_endpoint(
    relative_path: str,
    module_name: str,
) -> None:
    module = _load_script_module(relative_path, module_name)

    assert (
        module.resolve_graphql_url("https://kg.example.com/graphql")
        == "https://kg.example.com/graphql"
    )
