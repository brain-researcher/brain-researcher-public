"""Unit tests for taxonomy-driven vocabulary enrichment in TaskMatcher."""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def noop_indices(monkeypatch):
    """Prevent embedding indices from building during tests."""

    monkeypatch.setattr(
        "brain_researcher.services.neurokg.utils.task_matcher.TaskMatcher._build_indices",
        lambda self: None,
    )


@pytest.fixture
def empty_neurokg(monkeypatch):
    """Provide a dummy BR-KG DB that returns no tasks."""

    class _EmptyDB:
        def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: D401 - stub
            self.args = args
            self.kwargs = kwargs

        def find_nodes(self, *_, **__) -> list[tuple[str, dict[str, Any]]]:
            return []

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "brain_researcher.services.neurokg.graph.graph_database.NeuroKGGraphDB",
        _EmptyDB,
    )


def test_taxonomy_aliases_available(noop_indices, empty_neurokg):
    """TaskMatcher should populate taxonomy aliases when DB/fallback are empty."""

    from brain_researcher.services.neurokg.utils.task_matcher import TaskMatcher

    matcher = TaskMatcher()

    # Canonical task label should be present in the vocabulary list.
    assert any(label.lower() == "go/no-go" for label in matcher.labels)

    # Taxonomy alias should resolve to the canonical form.
    assert matcher.label_lookup["gng"] == "go/no-go"
    assert matcher.label_lookup["go/no-go"] == "go/no-go"


def test_task_matcher_fuzzy_fallback_skips_semantic_model_when_disabled(
    monkeypatch, empty_neurokg
):
    """Lightweight mode should not try to initialize SentenceTransformer."""

    monkeypatch.setattr(
        "brain_researcher.services.neurokg.utils.task_matcher.get_cached_sentence_transformer",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("semantic model should not load in lightweight mode")
        ),
    )

    from brain_researcher.services.neurokg.utils.task_matcher import TaskMatcher

    matcher = TaskMatcher(enable_semantic=False, fuzzy_threshold=60)
    matches = matcher.match_candidates("go no go", top_k=1)

    assert matches
    assert matches[0]["label"].lower() == "go/no-go"
    assert matches[0]["engine"] in {"exact", "fuzzy"}
