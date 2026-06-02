import os

import pytest

if not os.getenv("NEO4J_URI") or not os.getenv("NEO4J_PASSWORD"):
    pytest.skip(
        "NEO4J_URI/NEO4J_PASSWORD required for Neo4j-only tests",
        allow_module_level=True,
    )


def have_strawberry():
    try:
        import strawberry  # noqa: F401

        return True
    except Exception:
        return False


@pytest.mark.skipif(not have_strawberry(), reason="strawberry-graphql not installed")
def test_build_schema_and_basic_query(tmp_path, monkeypatch):
    # Seed minimal graph
    from brain_researcher.services.br_kg.db.bootstrap import get_db, seed

    db = get_db()
    seed(db)

    # Build schema and run a simple query
    from brain_researcher.services.br_kg.gql_schema.schema_simple import build_schema

    schema = build_schema()
    query = """
    query {
      concepts { id name }
      tasks { id name }
    }
    """
    result = schema.execute_sync(query)
    assert result.errors is None
    data = result.data
    assert any(c["name"] == "working memory" for c in data["concepts"])  # type: ignore[index]
    assert any(t["name"] == "n-back" for t in data["tasks"])  # type: ignore[index]
