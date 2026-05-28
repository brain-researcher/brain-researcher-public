from brain_researcher.services.tools.kg_multihop_qa_tool import KGMultihopQATool


def test_extract_search_terms_includes_identifier_variants():
    terms = KGMultihopQATool._extract_search_terms(
        "Check DOI 10.1016/j.neuroimage.2009.09.011 and PMID:19778619 evidence."
    )
    lower_terms = {term.lower() for term in terms}

    assert "10.1016/j.neuroimage.2009.09.011" in lower_terms
    assert "doi:10.1016/j.neuroimage.2009.09.011" in lower_terms
    assert "19778619" in lower_terms
    assert "pmid:19778619" in lower_terms


def test_extract_search_terms_does_not_emit_pmid_from_doi_digits():
    terms = KGMultihopQATool._extract_search_terms(
        "Investigate DOI 10.1007/s10548-011-0190-1 evidence."
    )
    lower_terms = {term.lower() for term in terms}

    # Should not treat DOI-internal digits as standalone PMID seeds.
    assert "10548" not in lower_terms
    assert "pmid:10548" not in lower_terms
    assert "10.1007/s10548-011-0190-1" in lower_terms


def test_extract_search_terms_prioritizes_relation_mentions_and_bounds_size():
    terms = KGMultihopQATool._extract_search_terms(
        "What links working memory to prefrontal cortex in adults?"
    )
    lower_terms = [term.lower() for term in terms]

    assert "working memory" in lower_terms
    assert "prefrontal cortex" in lower_terms
    assert "what links working memory" not in lower_terms
    assert len(terms) <= 6


def test_extract_search_terms_avoids_compacted_full_question_tokens():
    terms = KGMultihopQATool._extract_search_terms(
        "What links working memory and prefrontal cortex?"
    )
    lower_terms = {term.lower() for term in terms}

    assert "whatlinksworkingmemoryandprefrontalcortex" not in lower_terms


def test_extract_search_terms_quotes_are_preserved_as_high_precision_mentions():
    terms = KGMultihopQATool._extract_search_terms(
        'Explain relationship between "n-back task" and dorsolateral prefrontal cortex.'
    )
    lower_terms = {term.lower() for term in terms}

    assert "n-back task" in lower_terms
    assert "dorsolateral prefrontal cortex" in lower_terms


def test_runtime_seed_mapping_fail_open_when_mapper_unavailable(monkeypatch):
    tool = KGMultihopQATool()
    monkeypatch.setattr(tool, "runtime_seed_mapper_mode", "on")
    monkeypatch.setattr(tool, "_resolve_runtime_mapper", lambda: None)

    terms, runtime_meta = tool._augment_seed_terms_with_runtime_mapping(
        search_terms=["working memory", "prefrontal cortex"]
    )

    assert terms == ["working memory", "prefrontal cortex"]
    assert isinstance(runtime_meta, dict)
    assert runtime_meta.get("available") is False


def test_runtime_seed_mapping_adds_mapped_terms_when_available(monkeypatch):
    class _FakeMapping:
        def __init__(self, status: str, label: str | None = None, onvoc_id: str | None = None):
            self.status = status
            self.onvoc_label = label
            self.onvoc_id = onvoc_id

    class _FakeMapper:
        def map_text(self, term, **_kwargs):
            if term == "working memory":
                return _FakeMapping("mapped", label="Working memory", onvoc_id="ONVOC:0001")
            return _FakeMapping("unmatched")

    tool = KGMultihopQATool()
    monkeypatch.setattr(tool, "runtime_seed_mapper_mode", "on")
    monkeypatch.setattr(tool, "_resolve_runtime_mapper", lambda: _FakeMapper())

    terms, runtime_meta = tool._augment_seed_terms_with_runtime_mapping(
        search_terms=["working memory", "prefrontal cortex"]
    )

    lower_terms = [term.lower() for term in terms]
    assert "working memory" in lower_terms
    assert "onvoc:0001" in lower_terms
    assert "prefrontal cortex" in lower_terms
    assert isinstance(runtime_meta, dict)
    assert runtime_meta.get("available") is True
    assert runtime_meta.get("mapped_terms") == 1
