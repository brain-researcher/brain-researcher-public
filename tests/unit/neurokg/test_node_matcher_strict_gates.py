"""Strict gate coverage for UnifiedNodeMatcher SAME_AS acceptance."""

from __future__ import annotations

import pytest

from brain_researcher.services.neurokg.matching.node_matcher import (
    MatchResult,
    UnifiedNodeMatcher,
)


@pytest.fixture
def matcher(monkeypatch: pytest.MonkeyPatch) -> UnifiedNodeMatcher:
    """Create matcher without loading external task/phenotype matcher assets."""

    def _stub_init_matchers(self: UnifiedNodeMatcher) -> None:
        self.task_matcher = None
        self.phenotype_matcher = None

    monkeypatch.setattr(UnifiedNodeMatcher, "_init_matchers", _stub_init_matchers)
    return UnifiedNodeMatcher(config_dir="configs/neurokg")


def test_rejects_fuzzy_only_evidence(
    matcher: UnifiedNodeMatcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = {"id": "candidate:1", "label": "N back task"}
    existing = [{"id": "target:1", "label": "n-back task"}]

    monkeypatch.setattr(matcher, "_exact_match", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        matcher,
        "_fuzzy_match",
        lambda *_args, **_kwargs: [
            MatchResult(
                target_node_id="target:1",
                confidence=0.99,
                method="fuzzy",
                matched_fields=["label"],
                metadata={},
            )
        ],
    )
    monkeypatch.setattr(matcher, "_embedding_match", lambda *_args, **_kwargs: [])

    assert matcher.match_node(candidate, "Task", existing) == []


def test_rejects_embedding_only_evidence(
    matcher: UnifiedNodeMatcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = {"id": "candidate:1", "label": "N back task"}
    existing = [{"id": "target:1", "label": "n-back task"}]

    monkeypatch.setattr(matcher, "_exact_match", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(matcher, "_fuzzy_match", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        matcher,
        "_embedding_match",
        lambda *_args, **_kwargs: [
            MatchResult(
                target_node_id="target:1",
                confidence=0.99,
                method="embedding_niclip",
                matched_fields=["label"],
                metadata={"engine": "niclip"},
            )
        ],
    )

    assert matcher.match_node(candidate, "Task", existing) == []


def test_accepts_stronger_multi_family_evidence(
    matcher: UnifiedNodeMatcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = {"id": "candidate:1", "label": "N back task"}
    existing = [{"id": "target:1", "label": "n-back task"}]

    monkeypatch.setattr(matcher, "_exact_match", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        matcher,
        "_fuzzy_match",
        lambda *_args, **_kwargs: [
            MatchResult(
                target_node_id="target:1",
                confidence=0.92,
                method="fuzzy",
                matched_fields=["label"],
                metadata={},
            )
        ],
    )
    monkeypatch.setattr(
        matcher,
        "_embedding_match",
        lambda *_args, **_kwargs: [
            MatchResult(
                target_node_id="target:1",
                confidence=0.96,
                method="embedding_niclip",
                matched_fields=["label"],
                metadata={"engine": "niclip"},
            )
        ],
    )

    matches = matcher.match_node(candidate, "Task", existing)

    assert len(matches) == 1
    assert matches[0].target_node_id == "target:1"
    assert matches[0].method == "embedding_niclip"
    assert matches[0].metadata["evidence_methods"] == ["embedding_niclip", "fuzzy"]
    assert matches[0].metadata["evidence_families"] == ["semantic", "string"]
    assert matches[0].metadata["evidence_count"] == 2


def test_applies_updated_same_as_threshold(
    matcher: UnifiedNodeMatcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = {"id": "candidate:1", "label": "N back task"}
    existing = [{"id": "target:1", "label": "n-back task"}]

    monkeypatch.setattr(
        matcher,
        "_exact_match",
        lambda *_args, **_kwargs: [
            MatchResult(
                target_node_id="target:1",
                confidence=0.92,
                method="exact",
                matched_fields=["label"],
                metadata={},
            )
        ],
    )
    monkeypatch.setattr(matcher, "_fuzzy_match", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(matcher, "_embedding_match", lambda *_args, **_kwargs: [])

    matcher.thresholds.setdefault("same_as_thresholds", {})["Task"] = 0.95
    assert matcher.match_node(candidate, "Task", existing) == []

    matcher.thresholds["same_as_thresholds"]["Task"] = 0.90
    matches = matcher.match_node(candidate, "Task", existing)
    assert len(matches) == 1
    assert matches[0].confidence == pytest.approx(0.92)


def test_create_same_as_edges_rejects_weak_evidence_for_strict_node_type(
    matcher: UnifiedNodeMatcher,
) -> None:
    class _GraphDbStub:
        def __init__(self) -> None:
            self.calls = 0

        def create_relationship(self, *_args, **_kwargs) -> str:
            self.calls += 1
            return f"edge:{self.calls}"

    graph_db = _GraphDbStub()
    weak_match = MatchResult(
        target_node_id="target:1",
        confidence=0.95,
        method="fuzzy",
        matched_fields=["label"],
        metadata={"node_type": "Task", "evidence_methods": ["fuzzy"]},
    )

    edge_ids = matcher.create_same_as_edges("source:1", [weak_match], graph_db)
    assert edge_ids == []
    assert graph_db.calls == 0


def test_create_same_as_edges_allows_non_strict_single_method(
    matcher: UnifiedNodeMatcher,
) -> None:
    class _GraphDbStub:
        def __init__(self) -> None:
            self.calls = 0

        def create_relationship(self, *_args, **_kwargs) -> str:
            self.calls += 1
            return f"edge:{self.calls}"

    graph_db = _GraphDbStub()
    spatial_match = MatchResult(
        target_node_id="coord:1",
        confidence=0.95,
        method="spatial",
        matched_fields=["x", "y", "z"],
        metadata={"node_type": "Coordinate", "evidence_methods": ["spatial"]},
    )

    edge_ids = matcher.create_same_as_edges("coord:source", [spatial_match], graph_db)
    assert edge_ids == ["edge:1"]
    assert graph_db.calls == 1
