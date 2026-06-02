from brain_researcher.services.br_kg import query_service


def test_search_tools_structured_fallback_prefers_method_intent_matches():
    # Use catalog fallback so this unit test does not require Neo4j.
    out = query_service.search_tools_structured(
        query="glm first level",
        force_fallback=True,
        k_methods=8,
        k_candidates=20,
    )

    assert out["source"] == "catalog_fallback"
    assert out["methods"], "Expected at least one method candidate"
    assert out["methods"][0]["method"] == "glm_first_level_fmri"

    rec = out.get("recommendation")
    assert rec is not None, "Expected a recommended candidate tool"
    assert rec.get("method") == "glm_first_level_fmri"
    # Score is token-overlap based; should be non-zero for this query.
    assert int(rec.get("score") or 0) >= 1
