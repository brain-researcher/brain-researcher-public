import pytest

from brain_researcher.services.br_kg.bulk_loader import EntityValidator


GWAS_NODE_TYPES = {"Study", "DiseaseTrait", "Population", "Gene", "RiskLocus"}
GWAS_RELATIONSHIP_TYPES = {
    "STUDIES",
    "HAS_POPULATION",
    "HAS_LEAD_LOCUS",
    "IMPLICATES_GENE",
    "ASSOCIATED_WITH",
}
GWAS_NODES_SUPPORTED = GWAS_NODE_TYPES.issubset(EntityValidator.VALID_NODE_TYPES)
GWAS_RELATIONSHIPS_SUPPORTED = GWAS_RELATIONSHIP_TYPES.issubset(
    EntityValidator.VALID_RELATIONSHIP_TYPES
)
SESSION_NODE_TYPES = {
    "AgentSession",
    "TaskSurface",
    "ValidationEvidence",
    "OpenRisk",
    "Outcome",
    "Lesson",
    "NextAction",
}
SESSION_RELATIONSHIP_TYPES = {
    "WORKED_ON_SURFACE",
    "VALIDATED_BY",
    "LEFT_OPEN_RISK",
    "PRODUCED_ARTIFACT",
    "EXPOSED_FAILURE_MODE",
    "HAS_REMEDIATION",
    "SHOULD_UPDATE_AGENT_POLICY",
}


def test_entity_validator_accepts_claim_spine_nodes() -> None:
    valid, error = EntityValidator.validate_node(
        {
            "type": "Assumption",
            "id": "assumption:test",
            "text": "Tasks are stable",
        }
    )

    assert valid
    assert error is None


def test_entity_validator_accepts_richer_claim_relations() -> None:
    valid, error = EntityValidator.validate_relationship(
        {
            "type": "CHALLENGES_ASSUMPTION",
            "source_id": "claim:1",
            "target_id": "assumption:1",
            "confidence": 0.76,
        }
    )

    assert valid
    assert error is None


def test_entity_validator_registers_session_lesson_types() -> None:
    assert SESSION_NODE_TYPES <= EntityValidator.VALID_NODE_TYPES
    assert SESSION_RELATIONSHIP_TYPES <= EntityValidator.VALID_RELATIONSHIP_TYPES


@pytest.mark.parametrize(
    "node",
    [
        {
            "type": "AgentSession",
            "id": "agent_session:s1",
            "session_id": "s1",
        },
        {"type": "TaskSurface", "id": "task_surface:prod-runtime", "name": "prod-runtime"},
        {
            "type": "ValidationEvidence",
            "id": "validation_evidence:1",
            "evidence_type": "pytest",
            "text": "pytest passed",
        },
        {
            "type": "OpenRisk",
            "id": "open_risk:1",
            "label": "partial-validation",
            "text": "No browser smoke was run.",
        },
        {"type": "Outcome", "id": "outcome:1", "text": "Committed changes."},
        {
            "type": "Lesson",
            "id": "lesson:1",
            "issue_code": "missing_source_client",
            "text": "Pass source_client.",
        },
        {"type": "NextAction", "id": "next_action:1", "command": "pytest -q"},
    ],
)
def test_entity_validator_accepts_session_lesson_nodes(
    node: dict[str, object],
) -> None:
    valid, error = EntityValidator.validate_node(node)

    assert valid
    assert error is None


def test_entity_validator_rejects_noncanonical_open_risk_label() -> None:
    valid, error = EntityValidator.validate_node(
        {
            "type": "OpenRisk",
            "id": "open_risk:bad",
            "label": "unknown",
            "text": "Something vague.",
        }
    )

    assert not valid
    assert error and "OpenRisk label" in error


@pytest.mark.parametrize(
    "relationship",
    [
        {
            "type": "WORKED_ON_SURFACE",
            "source_id": "agent_session:s1",
            "target_id": "task_surface:prod-runtime",
        },
        {
            "type": "VALIDATED_BY",
            "source_id": "agent_session:s1",
            "target_id": "validation_evidence:1",
        },
        {
            "type": "LEFT_OPEN_RISK",
            "source_id": "agent_session:s1",
            "target_id": "open_risk:1",
        },
        {
            "type": "PRODUCED_ARTIFACT",
            "source_id": "agent_session:s1",
            "target_id": "outcome:1",
        },
        {
            "type": "EXPOSED_FAILURE_MODE",
            "source_id": "task_surface:prod-runtime",
            "target_id": "open_risk:1",
        },
        {
            "type": "HAS_REMEDIATION",
            "source_id": "open_risk:1",
            "target_id": "next_action:1",
        },
        {
            "type": "SHOULD_UPDATE_AGENT_POLICY",
            "source_id": "lesson:1",
            "target_id": "next_action:1",
        },
    ],
)
def test_entity_validator_accepts_session_lesson_relationships(
    relationship: dict[str, object],
) -> None:
    valid, error = EntityValidator.validate_relationship(relationship)

    assert valid
    assert error is None


def test_entity_validator_accepts_statmap_alias_nodes() -> None:
    valid, error = EntityValidator.validate_node(
        {
            "type": "StatsMap",
            "id": "map:test",
            "name": "Working Memory Z map",
        }
    )

    assert valid
    assert error is None


@pytest.mark.xfail(
    not GWAS_NODES_SUPPORTED,
    reason="GWAS node types are not yet registered in EntityValidator",
    strict=False,
)
@pytest.mark.parametrize(
    "node",
    [
        {
            "type": "Study",
            "id": "study:pgc_mdd_001",
            "title": "PGC Major Depressive Disorder GWAS",
            "doi": "10.1234/pgc.mdd.001",
        },
        {
            "type": "DiseaseTrait",
            "id": "trait:mdd",
            "name": "Major depressive disorder",
            "phenotype_id": "MONDO:0001234",
            "category": "psychiatric",
        },
        {
            "type": "Population",
            "id": "population:eur",
            "name": "European ancestry",
            "ancestry": "EUR",
        },
        {
            "type": "Gene",
            "id": "gene:drd2",
            "symbol": "DRD2",
        },
        {
            "type": "RiskLocus",
            "id": "locus:rs123",
            "name": "Lead risk locus 1",
            "rsid": "rs123",
            "chromosome": "11",
            "position": 113000,
            "p_value": 1e-9,
        },
    ],
)
def test_entity_validator_accepts_gwas_metadata_nodes(node: dict[str, object]) -> None:
    valid, error = EntityValidator.validate_node(node)

    assert valid
    assert error is None


@pytest.mark.xfail(
    not GWAS_RELATIONSHIPS_SUPPORTED,
    reason="GWAS relationship types are not yet registered in EntityValidator",
    strict=False,
)
@pytest.mark.parametrize(
    "relationship",
    [
        {
            "type": "STUDIES",
            "source_id": "study:pgc_mdd_001",
            "target_id": "trait:mdd",
            "confidence": 0.97,
        },
        {
            "type": "HAS_POPULATION",
            "source_id": "study:pgc_mdd_001",
            "target_id": "population:eur",
            "confidence": 0.96,
        },
        {
            "type": "HAS_LEAD_LOCUS",
            "source_id": "study:pgc_mdd_001",
            "target_id": "locus:rs123",
            "confidence": 0.95,
        },
        {
            "type": "IMPLICATES_GENE",
            "source_id": "locus:rs123",
            "target_id": "gene:drd2",
            "confidence": 0.93,
        },
        {
            "type": "ASSOCIATED_WITH",
            "source_id": "locus:rs123",
            "target_id": "trait:mdd",
            "confidence": 0.94,
        },
    ],
)
def test_entity_validator_accepts_gwas_metadata_relationships(
    relationship: dict[str, object],
) -> None:
    valid, error = EntityValidator.validate_relationship(relationship)

    assert valid
    assert error is None
