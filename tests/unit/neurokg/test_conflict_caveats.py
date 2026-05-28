from brain_researcher.services.neurokg.search.hybrid_v1 import _detect_evidence_conflicts
from brain_researcher.services.neurokg.evidence import caveats as caveats_module


def test_conflict_detection_semantic():
    evidence = [
        {
            "evidence_id": "ev1",
            "snippet": "ICA-AROMA is deprecated and will be removed.",
            "doc_role": "tooling_spec",
            "polarity": "negative",
        },
        {
            "evidence_id": "ev2",
            "snippet": "We recommend ICA-AROMA as a standard option.",
            "doc_role": "guideline",
            "polarity": "positive",
        },
    ]
    flags = _detect_evidence_conflicts(evidence)
    assert flags
    assert flags[0]["type"] == "evidence_semantic_conflict"
    assert flags[0]["severity"] == "high"


def test_caveat_trigger_by_query(tmp_path, monkeypatch):
    # Use repo caveats file by default; ensure cache refresh
    monkeypatch.setenv("NEUROKG_CAVEATS_PATH", "data/neuro_methods_kb.yaml")
    caveats_module.load_caveats(force=True)
    hits = caveats_module.match_caveats(
        query="motion confounds and FD", node_type="TaskSpec", node_label=None
    )
    assert any(c.get("id") == "motion_confounds" for c in hits)
