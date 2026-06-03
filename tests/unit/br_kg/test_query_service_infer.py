from brain_researcher.services.br_kg import query_service as qs


def test_infer_dataset_id():
    hints = qs._infer_query_hints("ds000030")
    assert hints["exact_id"] == "ds000030"
    assert "Dataset" in (hints["node_types"] or [])


def test_infer_pmid_identifier():
    hints = qs._infer_query_hints("pmid:19778619")
    assert hints["exact_id"] == "pmid:19778619"
    assert "Publication" in (hints["node_types"] or [])


def test_infer_doi_identifier():
    hints = qs._infer_query_hints("10.1016/j.neuroimage.2009.09.011")
    assert hints["exact_id"] == "doi:10.1016/j.neuroimage.2009.09.011"
    assert "Publication" in (hints["node_types"] or [])


def test_infer_ontology_id():
    hints = qs._infer_query_hints("ONVOC_0000438")
    assert hints["exact_id"] == "ONVOC_0000438"
    assert "Concept" in (hints["node_types"] or [])


def test_infer_curie():
    hints = qs._infer_query_hints("CogPO:00001")
    assert hints["exact_id"] == "CogPO:00001"
    assert "Concept" in (hints["node_types"] or [])


def test_infer_keyword_task():
    hints = qs._infer_query_hints("task working memory")
    assert hints["exact_id"] is None
    assert "Task" in (hints["node_types"] or [])


def test_infer_region_keyword():
    hints = qs._infer_query_hints("motor cortex")
    assert hints["exact_id"] is None
    assert "BrainRegion" in (hints["node_types"] or [])


def test_resolve_fulltext_index_prefers_candidates(monkeypatch):
    class FakeDB:
        def _run(self, _cypher, _params=None):
            return [
                {"name": "ft_Task_Concept"},
                {"name": "kgFulltext"},
                {"name": "kgNodeFulltext"},
            ]

    qs._FULLTEXT_INDEX_CACHE.clear()
    monkeypatch.delenv("NEO4J_FULLTEXT_NODE_INDEX", raising=False)
    monkeypatch.delenv("NEO4J_FULLTEXT_INDEX", raising=False)
    monkeypatch.delenv("NEO4J_FULLTEXT_DISABLE", raising=False)
    assert qs._resolve_fulltext_index(FakeDB()) == "kgNodeFulltext"


def test_build_fulltext_query_multiterm():
    query = qs._build_fulltext_query("motor cortex")
    assert '"motor cortex"' in query
    assert "motor AND cortex" in query
    assert "motor OR cortex" in query


def test_build_fulltext_query_single_term():
    assert qs._build_fulltext_query("amygdala") == "amygdala"


def test_build_lookup_terms_includes_publication_variants():
    terms = qs._build_lookup_terms("pmid:19778619")
    assert "pmid:19778619" in terms
    assert "19778619" in terms

    terms_doi = qs._build_lookup_terms("doi:10.1016/j.neuroimage.2009.09.011")
    assert "doi:10.1016/j.neuroimage.2009.09.011" in terms_doi
    assert "10.1016/j.neuroimage.2009.09.011" in terms_doi
