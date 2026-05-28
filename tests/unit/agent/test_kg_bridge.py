import os
import pytest

from brain_researcher.services.agent.planner.kg_bridge import (
    get_preferred_families_for_pipeline,
    get_family_stats_for_operation,
)


@pytest.mark.skipif(
    not os.environ.get("NEO4J_PASSWORD"),
    reason="NEO4J_PASSWORD not set; KG not reachable in CI by default",
)
def test_kg_bridge_getters_run():
    fams = get_family_stats_for_operation("dmri_tractography")
    assert isinstance(fams, list)
    # should return tuples when data present
    if fams:
        assert isinstance(fams[0], tuple)

    prefs = get_preferred_families_for_pipeline("pipeline.tractography")
    assert isinstance(prefs, list)
