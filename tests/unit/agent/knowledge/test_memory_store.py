import json

import pytest

from brain_researcher.services.agent.knowledge.evidence_models import EvidenceBundle, EvidenceItem, EvidenceSourceType
from brain_researcher.services.agent.knowledge.memory_store import KnowledgeMemoryStore


def _sample_bundle():
    b = EvidenceBundle(query="motor cortex")
    b.add_item(
        EvidenceItem(
            source_type=EvidenceSourceType.PUBMED,
            source_id="pmid:1",
            label="Paper 1",
            relevance_score=0.9,
        )
    )
    b.compute_confidence()
    return b


def test_memory_store_in_memory_fallback():
    store = KnowledgeMemoryStore(redis_client=None, max_per_account=2)
    bundle = _sample_bundle()

    store.add_bundle("user123", bundle)
    store.add_bundle("user123", bundle)
    store.add_bundle("user123", bundle)  # should trim to 2

    items = store.get_bundles("user123")
    assert len(items) == 2
    # Ensure payload serializes
    json.dumps(items[0])


@pytest.mark.skip(reason="requires redis if available; covered by fallback test")
def test_memory_store_with_redis(redis_client):
    store = KnowledgeMemoryStore(redis_client=redis_client, max_per_account=1)
    bundle = _sample_bundle()
    store.add_bundle("user123", bundle)
    items = store.get_bundles("user123")
    assert len(items) == 1
