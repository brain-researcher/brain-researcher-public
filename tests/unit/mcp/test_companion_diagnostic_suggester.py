"""Tests for the companion_diagnostic_suggester MCP tool.

The tool maps a neuroimaging/ML metric name to companion diagnostics that
guard against known failure modes. It is a pure lookup (no state, no LLM),
so tests focus on:

- input validation,
- alias normalization,
- context-based ``applies_if_context_matches`` gating that surfaces entries
  rather than hiding them,
- stable rigor_guards and coverage metadata,
- unknown metrics return matched=False + coverage-gap note, not an error.
"""

from __future__ import annotations

from pathlib import Path

from brain_researcher.services.mcp import runstore


def _configure_run_root(monkeypatch, tmp_path: Path):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(runstore, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    monkeypatch.setattr(srv, "_run_roots_for_read", lambda: [tmp_path])
    srv._ensure_dirs()
    return srv


def test_known_metric_reliability_ratio_returns_companions(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    resp = srv.companion_diagnostic_suggester(
        metric_name="reliability_ratio",
        observed_value=0.98,
    )

    assert resp["ok"] is True
    assert resp["matched_known_metric"] is True
    assert resp["normalized_metric_key"] == "reliability_ratio"
    assert resp["observed_value"] == 0.98
    names = [c["name"] for c in resp["companions"]]
    assert "within_class_variance_ratio" in names
    # Each companion carries the narrative fields we depend on.
    for companion in resp["companions"]:
        assert companion["name"]
        assert companion["rationale"]
        assert companion["failure_mode_guarded_against"]


def test_unknown_metric_returns_coverage_gap(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    resp = srv.companion_diagnostic_suggester(metric_name="never_heard_of_this")

    assert resp["ok"] is True
    assert resp["matched_known_metric"] is False
    assert resp["companions"] == []
    assert "coverage gap" in resp["note"]
    # Rigor guards must be present even for unknown metrics.
    assert resp["rigor_guards"]
    assert resp["coverage"]["table_version"]


def test_alias_normalization_maps_to_canonical_metric(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    resp = srv.companion_diagnostic_suggester(metric_name="Edge-Corr")
    assert resp["ok"] is True
    assert resp["matched_known_metric"] is True
    assert resp["normalized_metric_key"] == "edge_correlation"
    names = {c["name"] for c in resp["companions"]}
    assert "nearest_neighbor_overlap" in names


def test_context_matching_surfaces_but_flags_when_mismatched(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    # The kNN-specific hubness companions for balanced_accuracy require
    # classifier_family="kNN". When the caller says "linear_svm", we still
    # SURFACE the entries but mark applies_if_context_matches=False so the
    # agent sees them without being misled.
    resp = srv.companion_diagnostic_suggester(
        metric_name="balanced_accuracy",
        context={"classifier_family": "linear_svm"},
    )
    assert resp["ok"] is True
    assert resp["matched_known_metric"] is True

    hubness_entries = [c for c in resp["companions"] if c["name"] == "hubness_skewness"]
    assert hubness_entries, "expected hubness_skewness to be surfaced"
    assert hubness_entries[0]["applies_if_context_matches"] is False

    # When context matches, the same entry should apply.
    resp_knn = srv.companion_diagnostic_suggester(
        metric_name="balanced_accuracy",
        context={"classifier_family": "kNN"},
    )
    hubness_knn = [c for c in resp_knn["companions"] if c["name"] == "hubness_skewness"]
    assert hubness_knn[0]["applies_if_context_matches"] is True


def test_missing_context_does_not_hide_context_gated_entries(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    resp = srv.companion_diagnostic_suggester(metric_name="balanced_accuracy")
    assert resp["ok"] is True
    names = {c["name"] for c in resp["companions"]}
    # Context-gated entries must still be visible when no context is given.
    assert "hubness_skewness" in names
    assert "non_knn_linear_baseline" in names


def test_top_k_cap_is_respected(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    resp = srv.companion_diagnostic_suggester(
        metric_name="balanced_accuracy",
        top_k=1,
    )
    assert resp["ok"] is True
    assert len(resp["companions"]) == 1


def test_missing_metric_name_rejected(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    resp = srv.companion_diagnostic_suggester(metric_name="")
    assert resp["ok"] is False
    assert resp["error"] == "invalid_arguments"


def test_value_band_hint_is_echoed_not_evaluated(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    # Even when observed_value is far from the band, the hint is still
    # echoed — applicability is the caller's decision, not ours.
    resp = srv.companion_diagnostic_suggester(
        metric_name="reliability_ratio",
        observed_value=0.01,
    )
    assert resp["observed_value"] == 0.01
    wcv = next(
        c for c in resp["companions"] if c["name"] == "within_class_variance_ratio"
    )
    assert wcv["value_band_hint"] == "near 1.0"


def test_rigor_guards_and_coverage_are_stable(tmp_path, monkeypatch):
    srv = _configure_run_root(monkeypatch, tmp_path)

    r1 = srv.companion_diagnostic_suggester(metric_name="reliability_ratio")
    r2 = srv.companion_diagnostic_suggester(metric_name="edge_correlation")
    assert r1["rigor_guards"] == r2["rigor_guards"]
    assert r1["coverage"] == r2["coverage"]
    assert r1["coverage"]["known_metrics_count"] >= 5
