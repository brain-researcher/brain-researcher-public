"""Tests for Neo4j connection resolution in pipeline catalog search."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from brain_researcher.services.agent.pipeline_catalog import search_pipelines


def _mock_driver_with_records(records):
    session = MagicMock()
    session.run.return_value.values.return_value = records

    session_ctx = MagicMock()
    session_ctx.__enter__.return_value = session
    session_ctx.__exit__.return_value = False

    driver = MagicMock()
    driver.session.return_value = session_ctx
    return driver


def test_search_pipelines_uses_env_connection_when_not_overridden(monkeypatch):
    monkeypatch.setenv("NEO4J_URI", "bolt://brain-researcher-neo4j:7687")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "pw")

    driver = _mock_driver_with_records([])
    with patch(
        "brain_researcher.services.agent.pipeline_catalog.GraphDatabase.driver",
        return_value=driver,
    ) as mock_driver:
        search_pipelines(task="test query", limit=1)

    mock_driver.assert_called_once_with(
        "bolt://brain-researcher-neo4j:7687", auth=("neo4j", "pw")
    )


def test_search_pipelines_explicit_connection_overrides_env(monkeypatch):
    monkeypatch.setenv("NEO4J_URI", "bolt://brain-researcher-neo4j:7687")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "pw")

    driver = _mock_driver_with_records([])
    with patch(
        "brain_researcher.services.agent.pipeline_catalog.GraphDatabase.driver",
        return_value=driver,
    ) as mock_driver:
        search_pipelines(
            task="test query",
            limit=1,
            uri="bolt://custom:7687",
            user="custom-user",
            password="custom-pass",
        )

    mock_driver.assert_called_once_with(
        "bolt://custom:7687", auth=("custom-user", "custom-pass")
    )


def test_search_pipelines_localhost_fallback_when_env_missing(monkeypatch):
    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.delenv("NEO4J_USER", raising=False)
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)

    driver = _mock_driver_with_records([])
    with patch(
        "brain_researcher.services.agent.pipeline_catalog.GraphDatabase.driver",
        return_value=driver,
    ) as mock_driver:
        search_pipelines(task="test query", limit=1)

    mock_driver.assert_called_once_with("bolt://localhost:7687", auth=("neo4j", None))
