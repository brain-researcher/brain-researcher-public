import json
from pathlib import Path

from brain_researcher.core.contracts import ClaimV1, EvidenceItemV1
from brain_researcher.core.quote_grounded import (
    QUOTE_GROUNDED_CLAIMS_FILENAME,
    QUOTE_GROUNDED_EVIDENCE_ITEMS_FILENAME,
    write_quote_grounded_artifacts,
)


def test_write_quote_grounded_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_001"
    hits = [
        {
            "doc_id": "fileSearchStores/example/files/doc_001",
            "title": "Example Paper",
            "score": 0.9,
            "pmid": "123456",
            "pmcid": "PMC123456",
            "doi": "10.1000/example",
            "snippet": "First line.",
            "text": "First line.\nSecond line.\nThird line.",
        }
    ]

    result = write_quote_grounded_artifacts(
        run_dir=run_dir,
        query="example query",
        hits=hits,
    )
    assert result["status"] == "ok"

    evidence_path = run_dir / QUOTE_GROUNDED_EVIDENCE_ITEMS_FILENAME
    claims_path = run_dir / QUOTE_GROUNDED_CLAIMS_FILENAME
    assert evidence_path.exists()
    assert claims_path.exists()

    evidence_items = json.loads(evidence_path.read_text(encoding="utf-8"))
    claims = json.loads(claims_path.read_text(encoding="utf-8"))

    parsed_evidence = [EvidenceItemV1.model_validate(item) for item in evidence_items]
    parsed_claims = [ClaimV1.model_validate(item) for item in claims]

    assert parsed_evidence
    assert parsed_claims

    evidence_ids = {ev.evidence_id for ev in parsed_evidence}
    for ev in parsed_evidence:
        assert isinstance(ev.payload_ref, str) and ev.payload_ref
        assert "/" not in ev.payload_ref
        assert "\\" not in ev.payload_ref

        payload_text = (run_dir / ev.payload_ref).read_text(encoding="utf-8")

        span = ev.quote_span
        if isinstance(span, dict):
            start = int(span.get("start_char", 0))
            end = int(span.get("end_char", 0))
        else:
            start = int(span.start_char) if span else 0
            end = int(span.end_char) if span else 0

        assert 0 <= start <= end <= len(payload_text)

    for claim in parsed_claims:
        assert claim.verdict == "suggestive"
        assert claim.epistemic_confidence_tier == "low"
        assert claim.evidence_provenance == "cross_study_inference"
        assert claim.claim_scope == "cross_study"
        assert claim.raw_data_available is False
        assert claim.direct_statistical_test is False
        assert claim.evidence_ids
        for evidence_id in claim.evidence_ids:
            assert evidence_id in evidence_ids

    for evidence in parsed_evidence:
        assert evidence.evidence_provenance == "cross_study_inference"
        assert evidence.raw_data_available is False
        assert evidence.direct_statistical_test is False
