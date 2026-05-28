from __future__ import annotations

from unittest.mock import Mock

from brain_researcher.services.neurokg.nl_query import (
    NaturalLanguageQueryOrchestrator,
)
from brain_researcher.services.neurokg.nl_query.agents import QueryType


def _build_orchestrator(*, sparql_executor=None):
    parser = Mock()
    mapper = Mock()
    builder = Mock()
    formatter = Mock()
    orchestrator = NaturalLanguageQueryOrchestrator(
        parser_agent=parser,
        mapper_agent=mapper,
        builder_agent=builder,
        formatter_agent=formatter,
        sparql_executor=sparql_executor,
    )
    orchestrator.parser_agent.parse.return_value = Mock(
        intent="search",
        entities=[],
        constraints=[],
        modifiers={},
        confidence_score=0.8,
    )
    orchestrator.mapper_agent.map_to_schema.return_value = Mock(
        graph_patterns=[],
        node_filters={},
        relationship_filters={},
        constraints=[],
        projections=["*"],
        confidence_score=0.7,
    )
    orchestrator.builder_agent.build_query.return_value = Mock(
        query_type=QueryType.SPARQL,
        query_string="SELECT * WHERE { ?s ?p ?o }",
        parameters={},
        fallback_query=None,
        confidence_score=0.75,
    )
    return orchestrator


def test_nlq_sparql_without_executor_returns_explicit_not_supported():
    orchestrator = _build_orchestrator()

    result = orchestrator.process_query("Find concepts using SPARQL")

    assert result["success"] is False
    assert result["error_code"] == "not_supported"
    assert result["not_supported"]["query_type"] == "sparql"
    assert result["not_supported"]["supported_query_types"] == ["cypher"]
    assert result["phase_failed"] == "error"
    assert "query_type=sparql is not supported" in result["error"]


def test_nlq_sparql_with_executor_executes_successfully():
    sparql_executor = Mock(
        return_value={
            "results": {
                "bindings": [
                    {"s": {"type": "uri", "value": "https://neurokg.org/node/1"}}
                ]
            }
        }
    )
    orchestrator = _build_orchestrator(sparql_executor=sparql_executor)
    orchestrator.formatter_agent.format_results.return_value = Mock(
        summary="SPARQL results",
        data=[{"id": "n1"}],
        visualization_hints={},
        explanation="ok",
        confidence_score=0.9,
    )

    result = orchestrator.process_query("Find concepts using SPARQL")

    assert result["success"] is True
    assert result["result"]["summary"] == "SPARQL results"
    sparql_executor.assert_called_once_with("SELECT * WHERE { ?s ?p ?o }")


def test_factory_auto_wires_sparql_executor_when_neo4j_db_is_present(monkeypatch):
    from brain_researcher.services.neurokg.nl_query import nl_query_orchestrator as nqo

    fake_executor = Mock(return_value={"results": {"bindings": []}})
    spy_builder = Mock(return_value=fake_executor)
    monkeypatch.setattr(nqo, "_build_default_sparql_executor", spy_builder)

    db = object()
    orchestrator = nqo.create_nl_query_orchestrator(neo4j_db=db)

    spy_builder.assert_called_once_with(db)
    assert orchestrator.sparql_executor is fake_executor
