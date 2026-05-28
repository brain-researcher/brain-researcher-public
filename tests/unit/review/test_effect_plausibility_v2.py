"""Tests for the B3.5 multi-source effect-size prior dispatcher and threshold modulation."""

from __future__ import annotations

import pytest

from brain_researcher.core.contracts.code_review import CodeReviewBundle


def _bundle(
    stats_metrics: dict | None = None,
    kg_context: dict | None = None,
) -> CodeReviewBundle:
    return CodeReviewBundle(
        plan_steps=[],
        declared_modalities=[],
        declared_spaces=[],
        stats_metrics=stats_metrics or {},
        kg_context=kg_context or {},
    )


# ---------------------------------------------------------------------------
# Multi-source prior dispatcher
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMultiSourcePriorDispatcher:
    def test_kg_records_are_summarized_without_service_imports(self):
        from brain_researcher.core.literature import literature_priors as lp

        result = lp.infer_effect_size_priors_from_kg(
            task="nback",
            region="dlpfc",
            effect_size_records=[
                {
                    "task": "nback",
                    "region": "dlpfc",
                    "effect_size": 0.2,
                    "p_value": 0.04,
                    "sample_size": 30,
                },
                {
                    "task": "nback",
                    "region": "dlpfc",
                    "cohens_d": 0.4,
                    "p_value": 0.03,
                    "sample_size": 40,
                },
                {
                    "task": "nback",
                    "region": "dlpfc",
                    "statistic_value": 0.6,
                    "p_value": 0.02,
                    "sample_size": 50,
                },
                {
                    "task": "stroop",
                    "region": "acc",
                    "effect_size": 1.4,
                    "p_value": 0.001,
                    "sample_size": 60,
                },
            ],
        )

        assert result["status"] == "ok"
        assert result["source"] == "kg_meta_analysis"
        assert result["support"]["n_studies"] == 3
        assert result["priors"]["cohens_d"]["median_abs_d"] == 0.4
        assert result["priors"]["cohens_d"]["max_abs_d"] == 0.6

    def test_literature_fallback(self, monkeypatch):
        from brain_researcher.core.literature import literature_priors as lp

        monkeypatch.setattr(
            lp, "infer_effect_size_priors_from_kg",
            lambda **kw: {"status": "unavailable", "source": "kg_meta_analysis", "priors": {}, "support": {}},
        )
        monkeypatch.setattr(
            lp, "infer_effect_size_priors_from_enigma",
            lambda **kw: {"status": "unavailable", "source": "enigma_meta_analysis", "priors": {}, "support": {}},
        )
        monkeypatch.setattr(
            lp, "infer_effect_size_priors",
            lambda **kw: {
                "status": "ok", "source": "literature",
                "priors": {"cohens_d": {"median_abs_d": 0.5, "p90_abs_d": 0.8, "max_abs_d": 1.2, "n_mentions": 5}},
                "support": {},
            },
        )
        result = lp.infer_effect_size_priors_multi(task="test")
        assert result["confidence_tier"] == "literature_text_mining"
        assert result["status"] == "ok"

    def test_kg_takes_priority(self, monkeypatch):
        from brain_researcher.core.literature import literature_priors as lp

        monkeypatch.setattr(
            lp, "infer_effect_size_priors_from_kg",
            lambda **kw: {
                "status": "ok", "source": "kg_meta_analysis",
                "priors": {"cohens_d": {"median_abs_d": 0.3, "p90_abs_d": 0.6, "max_abs_d": 0.9, "n_mentions": 50}},
                "support": {},
            },
        )
        result = lp.infer_effect_size_priors_multi(task="test")
        assert result["confidence_tier"] == "kg_meta"
        assert result["source"] == "kg_meta_analysis"

    def test_enigma_takes_priority_over_literature(self, monkeypatch):
        from brain_researcher.core.literature import literature_priors as lp

        monkeypatch.setattr(
            lp, "infer_effect_size_priors_from_kg",
            lambda **kw: {"status": "no_data", "source": "kg_meta_analysis", "priors": {}, "support": {}},
        )
        monkeypatch.setattr(
            lp, "infer_effect_size_priors_from_enigma",
            lambda **kw: {
                "status": "ok", "source": "enigma_meta_analysis",
                "priors": {"cohens_d": {"median_abs_d": 0.2, "p90_abs_d": 0.4, "max_abs_d": 0.6, "n_mentions": 15}},
                "support": {},
            },
        )
        result = lp.infer_effect_size_priors_multi(task="test", region="hippocampus")
        assert result["confidence_tier"] == "enigma_meta"
        assert result["source"] == "enigma_meta_analysis"


# ---------------------------------------------------------------------------
# Uncertainty modulation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUncertaintyModulation:
    def test_low_n_mentions_widens_threshold(self, monkeypatch):
        from brain_researcher.services.review.checks import effect_plausibility as ep

        _prior_few = {
            "status": "ok", "source": "literature", "confidence_tier": "literature_text_mining",
            "priors": {"cohens_d": {"median_abs_d": 0.5, "p90_abs_d": 0.8, "max_abs_d": 1.1, "n_mentions": 2}},
            "support": {},
        }
        monkeypatch.setattr(ep, "infer_effect_size_priors_multi", lambda **kw: _prior_few)
        monkeypatch.setattr(ep, "infer_effect_size_priors", lambda **kw: _prior_few)

        # n_mentions=2 → uncertainty_factor=1.5 → threshold=1.8*1.5=2.7
        bundle = _bundle(stats_metrics={"cohens_d_max": 2.5}, kg_context={"task": "t"})
        finding = ep.effect_size_plausibility_check(bundle)
        assert finding is None  # 2.5 < 2.7 → no flag

    def test_high_n_mentions_keeps_threshold(self, monkeypatch):
        from brain_researcher.services.review.checks import effect_plausibility as ep

        _prior_many = {
            "status": "ok", "source": "literature", "confidence_tier": "literature_text_mining",
            "priors": {"cohens_d": {"median_abs_d": 0.5, "p90_abs_d": 0.8, "max_abs_d": 1.1, "n_mentions": 50}},
            "support": {},
        }
        monkeypatch.setattr(ep, "infer_effect_size_priors_multi", lambda **kw: _prior_many)
        monkeypatch.setattr(ep, "infer_effect_size_priors", lambda **kw: _prior_many)

        # n_mentions=50 → uncertainty_factor=1.0 → threshold=1.8
        bundle = _bundle(stats_metrics={"cohens_d_max": 2.0}, kg_context={"task": "t"})
        finding = ep.effect_size_plausibility_check(bundle)
        assert finding is not None  # 2.0 > 1.8 → flag

    def test_high_heterogeneity_widens_threshold(self, monkeypatch):
        from brain_researcher.services.review.checks import effect_plausibility as ep

        _prior_hetero = {
            "status": "ok", "source": "kg_meta_analysis", "confidence_tier": "kg_meta",
            "priors": {"cohens_d": {"median_abs_d": 0.5, "p90_abs_d": 0.8, "max_abs_d": 1.1, "n_mentions": 30, "i_squared": 85}},
            "support": {},
        }
        monkeypatch.setattr(ep, "infer_effect_size_priors_multi", lambda **kw: _prior_hetero)
        monkeypatch.setattr(ep, "infer_effect_size_priors", lambda **kw: _prior_hetero)

        # i²=85 → 1.3x, kg source → 0.9x → 1.3*0.9=1.17
        # threshold = 1.8 * 1.17 = 2.106
        bundle = _bundle(stats_metrics={"cohens_d_max": 2.0}, kg_context={"task": "t"})
        finding = ep.effect_size_plausibility_check(bundle)
        assert finding is None  # 2.0 < 2.106 → no flag

    def test_kg_source_tightens_threshold(self, monkeypatch):
        from brain_researcher.services.review.checks import effect_plausibility as ep

        _prior_kg = {
            "status": "ok", "source": "kg_meta_analysis", "confidence_tier": "kg_meta",
            "priors": {"cohens_d": {"median_abs_d": 0.5, "p90_abs_d": 0.8, "max_abs_d": 1.1, "n_mentions": 30}},
            "support": {},
        }
        monkeypatch.setattr(ep, "infer_effect_size_priors_multi", lambda **kw: _prior_kg)
        monkeypatch.setattr(ep, "infer_effect_size_priors", lambda **kw: _prior_kg)

        # n=30 → 1.0, kg → 0.9 → threshold = 1.8 * 0.9 = 1.62
        bundle = _bundle(stats_metrics={"cohens_d_max": 1.7}, kg_context={"task": "t"})
        finding = ep.effect_size_plausibility_check(bundle)
        assert finding is not None  # 1.7 > 1.62 → flag


# ---------------------------------------------------------------------------
# Median observation preference
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestObservationPreference:
    def test_prefers_median_over_max(self, monkeypatch):
        from brain_researcher.services.review.checks import effect_plausibility as ep

        _prior = {
            "status": "ok", "source": "literature", "confidence_tier": "literature_text_mining",
            "priors": {"cohens_d": {"median_abs_d": 0.5, "p90_abs_d": 0.8, "max_abs_d": 1.1, "n_mentions": 20}},
            "support": {},
        }
        monkeypatch.setattr(ep, "infer_effect_size_priors_multi", lambda **kw: _prior)
        monkeypatch.setattr(ep, "infer_effect_size_priors", lambda **kw: _prior)

        # Both median and max present; median < threshold, max > threshold
        bundle = _bundle(
            stats_metrics={"cohens_d_median": 1.0, "cohens_d_max": 3.0},
            kg_context={"task": "t"},
        )
        finding = ep.effect_size_plausibility_check(bundle)
        # Median (1.0) is used → 1.0 < 1.8 → no flag
        assert finding is None


# ---------------------------------------------------------------------------
# Evidence includes source and uncertainty info
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_evidence_includes_source_and_uncertainty(monkeypatch):
    from brain_researcher.services.review.checks import effect_plausibility as ep

    _prior = {
        "status": "ok", "source": "enigma_meta_analysis", "confidence_tier": "enigma_meta",
        "priors": {"cohens_d": {"median_abs_d": 0.5, "p90_abs_d": 0.8, "max_abs_d": 1.1, "n_mentions": 20}},
        "support": {},
    }
    monkeypatch.setattr(ep, "infer_effect_size_priors_multi", lambda **kw: _prior)
    monkeypatch.setattr(ep, "infer_effect_size_priors", lambda **kw: _prior)

    bundle = _bundle(stats_metrics={"cohens_d_max": 2.5}, kg_context={"task": "t"})
    finding = ep.effect_size_plausibility_check(bundle)
    assert finding is not None
    evidence_text = " ".join(finding.kg_evidence)
    assert "enigma_meta_analysis" in evidence_text
    assert "uncertainty_factor" in evidence_text
