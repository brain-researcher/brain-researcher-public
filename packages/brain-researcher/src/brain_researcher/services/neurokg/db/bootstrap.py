"""Runtime helpers for obtaining and seeding the BR-KG Neo4j database."""

from __future__ import annotations

from typing import Any

from brain_researcher.services.neurokg.graph.neo4j_utils import require_neo4j_db


def get_db(*, require_neo4j: bool = True, preload_cache: bool = False):
    """Return the canonical BR-KG graph handle.

    The ``require_neo4j`` keyword is kept for backward compatibility with
    callers that still pass it from CLI/tests.
    """

    del require_neo4j
    return require_neo4j_db(preload_cache=preload_cache)


def seed(db: Any) -> None:
    """Seed a tiny demo graph used by smoke tests."""

    concept = db.create_node("Concept", {"id": "trm_working_memory", "name": "working memory"})
    task = db.create_node("Task", {"id": "tsk_nback", "name": "n-back"})
    pub = db.create_node(
        "Publication",
        {"pmid": "123456", "title": "Working memory networks"},
    )
    region = db.create_node(
        "Region",
        {"name": "dorsolateral prefrontal cortex", "abbreviation": "dlPFC"},
    )
    coord = db.create_node("Coordinate", {"x": -45, "y": 15, "z": 30, "space": "MNI"})

    db.create_relationship(concept, task, "MEASURED_BY", {"source": "seed"})
    db.create_relationship(pub, concept, "MENTIONS_CONCEPT", {"source": "seed"})
    db.create_relationship(pub, coord, "HAS_COORDINATE", {"source": "seed"})
    db.create_relationship(coord, region, "LOCATED_IN", {"source": "seed"})
