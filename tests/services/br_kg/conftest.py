import os

import pytest

try:
    from neo4j import GraphDatabase
except Exception:  # pragma: no cover - optional dependency in some envs
    GraphDatabase = None  # type: ignore

from brain_researcher.services.br_kg.db.schema import setup_schema
from brain_researcher.services.br_kg.graph.neo4j_utils import require_neo4j_db


def _neo4j_env_ready() -> bool:
    return bool(os.getenv("NEO4J_URI") and os.getenv("NEO4J_PASSWORD"))


def _ensure_database(driver, db_name: str) -> bool:
    try:
        with driver.session(database="system") as session:
            record = session.run(
                "SHOW DATABASES YIELD name WHERE name = $name RETURN name",
                {"name": db_name},
            ).single()
            if record:
                return True
            session.run(f"CREATE DATABASE `{db_name}` IF NOT EXISTS")
        return True
    except Exception:
        return False


def _wipe_database(driver, db_name: str) -> None:
    with driver.session(database=db_name) as session:
        session.run("MATCH (n) DETACH DELETE n")


@pytest.fixture(scope="session", autouse=True)
def _br_kg_test_database():
    if not _neo4j_env_ready() or GraphDatabase is None:
        pytest.skip(
            "NEO4J_URI/NEO4J_PASSWORD required for Neo4j-only tests",
            allow_module_level=True,
        )

    os.environ["NEO4J_PRELOAD_CACHE"] = "false"

    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")
    target_db = os.getenv("NEO4J_DATABASE") or "br_kg_test"
    if not os.getenv("NEO4J_DATABASE"):
        os.environ["NEO4J_DATABASE"] = target_db

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        if target_db != "neo4j":
            if not _ensure_database(driver, target_db):
                if os.getenv("BR_KG_TEST_ALLOW_DEFAULT_DB") == "1":
                    target_db = "neo4j"
                    os.environ["NEO4J_DATABASE"] = target_db
                else:
                    pytest.skip(
                        "Neo4j does not allow creating test DB. "
                        "Set NEO4J_DATABASE=neo4j and BR_KG_TEST_ALLOW_DEFAULT_DB=1 "
                        "to run tests against the default database.",
                        allow_module_level=True,
                    )

        _wipe_database(driver, target_db)

        db = require_neo4j_db(database=target_db, preload_cache=False)
        setup_schema(db)

        yield
    finally:
        try:
            _wipe_database(driver, target_db)
        except Exception:
            pass
        driver.close()
