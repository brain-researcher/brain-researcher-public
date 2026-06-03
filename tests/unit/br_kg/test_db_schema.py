from __future__ import annotations

from brain_researcher.services.br_kg.db.schema import setup_schema


class _RecordingDB:
    def __init__(self) -> None:
        self.constraints: list[tuple[str, str, str]] = []
        self.indexes: list[tuple[str, str, str]] = []

    def create_constraint(self, label: str, prop: str, constraint_type: str = "UNIQUE") -> None:
        self.constraints.append((label, prop, constraint_type))

    def create_index(self, label: str, prop: str, index_type: str = "BTREE") -> None:
        self.indexes.append((label, prop, index_type))


def test_setup_schema_registers_gwas_runtime_indexes() -> None:
    db = _RecordingDB()

    setup_schema(db)

    assert ("Study", "id", "UNIQUE") in db.constraints
    assert ("DiseaseTrait", "id", "UNIQUE") in db.constraints
    assert ("Population", "id", "UNIQUE") in db.constraints
    assert ("Gene", "id", "UNIQUE") in db.constraints
    assert ("RiskLocus", "id", "UNIQUE") in db.constraints

    assert ("Study", "name", "BTREE") in db.indexes
    assert ("Study", "pmid", "BTREE") in db.indexes
    assert ("DiseaseTrait", "name", "BTREE") in db.indexes
    assert ("Population", "name", "BTREE") in db.indexes
    assert ("Population", "ancestry_code", "BTREE") in db.indexes
    assert ("Gene", "symbol", "BTREE") in db.indexes
    assert ("RiskLocus", "name", "BTREE") in db.indexes


def test_setup_schema_registers_agent_session_indexes() -> None:
    db = _RecordingDB()

    setup_schema(db)

    for label in (
        "AgentSession",
        "TaskSurface",
        "ValidationEvidence",
        "OpenRisk",
        "Outcome",
        "Lesson",
        "NextAction",
    ):
        assert (label, "id", "UNIQUE") in db.constraints

    assert ("AgentSession", "session_id", "BTREE") in db.indexes
    assert ("AgentSession", "source_client", "BTREE") in db.indexes
    assert ("AgentSession", "status", "BTREE") in db.indexes
    assert ("AgentSession", "last_event_at", "BTREE") in db.indexes
    assert ("TaskSurface", "name", "BTREE") in db.indexes
    assert ("ValidationEvidence", "evidence_type", "BTREE") in db.indexes
    assert ("OpenRisk", "label", "BTREE") in db.indexes
    assert ("Lesson", "issue_code", "BTREE") in db.indexes
    assert ("Lesson", "status", "BTREE") in db.indexes
    assert ("NextAction", "action_type", "BTREE") in db.indexes
