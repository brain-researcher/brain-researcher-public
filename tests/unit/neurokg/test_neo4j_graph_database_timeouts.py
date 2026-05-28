from __future__ import annotations

from brain_researcher.services.neurokg.graph import neo4j_graph_database as neo_db


class _FakeResult:
    def __iter__(self):
        yield {"value": 1}


class _FakeSession:
    def __init__(self):
        self.calls: list[dict[str, object]] = []
        self.closed = False

    def run(self, cypher, params=None, **kwargs):
        self.calls.append(
            {
                "cypher": cypher,
                "params": params,
                "kwargs": kwargs,
            }
        )
        return _FakeResult()

    def close(self):
        self.closed = True


class _FakeDriver:
    def __init__(self):
        self.session_obj = _FakeSession()
        self.closed = False

    def verify_connectivity(self):
        return None

    def session(self, database=None):
        return self.session_obj

    def close(self):
        self.closed = True


def test_driver_uses_env_timeout_kwargs(monkeypatch):
    captured: dict[str, object] = {}
    fake_driver = _FakeDriver()

    class _FakeGraphDatabase:
        @staticmethod
        def driver(uri, *, auth=None, **config):
            captured["uri"] = uri
            captured["auth"] = auth
            captured["config"] = dict(config)
            return fake_driver

    monkeypatch.setattr(neo_db, "GraphDatabase", _FakeGraphDatabase)
    monkeypatch.setenv("NEO4J_CONNECTION_TIMEOUT_S", "3")
    monkeypatch.setenv("NEO4J_CONNECTION_ACQUISITION_TIMEOUT_S", "7")
    monkeypatch.setenv("NEO4J_MAX_TRANSACTION_RETRY_TIME_S", "2")

    db = neo_db.Neo4jGraphDB(
        "bolt://example:7687",
        "neo4j",
        "secret",
        preload_cache=False,
    )

    config = captured["config"]
    assert config["connection_timeout"] == 3.0
    assert config["connection_acquisition_timeout"] == 7.0
    assert config["max_transaction_retry_time"] == 2.0
    db.close()


def test_run_falls_back_when_timeout_kw_not_supported(monkeypatch):
    class _NoTimeoutSession(_FakeSession):
        def run(self, cypher, params=None, **kwargs):
            self.calls.append(
                {
                    "cypher": cypher,
                    "params": params,
                    "kwargs": kwargs,
                }
            )
            if "timeout" in kwargs:
                raise TypeError("unexpected keyword argument 'timeout'")
            return _FakeResult()

    class _NoTimeoutDriver(_FakeDriver):
        def __init__(self):
            super().__init__()
            self.session_obj = _NoTimeoutSession()

    fake_driver = _NoTimeoutDriver()

    class _FakeGraphDatabase:
        @staticmethod
        def driver(uri, *, auth=None, **config):
            return fake_driver

    monkeypatch.setattr(neo_db, "GraphDatabase", _FakeGraphDatabase)
    monkeypatch.setenv("NEO4J_QUERY_TIMEOUT_S", "1")

    db = neo_db.Neo4jGraphDB(
        "bolt://example:7687",
        "neo4j",
        "secret",
        preload_cache=False,
    )

    # Consume to trigger _ManagedResult session close path.
    _ = list(db._run("RETURN 1", {}))

    calls = fake_driver.session_obj.calls
    assert len(calls) == 2
    assert calls[0]["kwargs"] == {"timeout": 1.0}
    assert calls[1]["kwargs"] == {}
    assert fake_driver.session_obj.closed is True
    db.close()


def test_run_uses_per_call_timeout_override(monkeypatch):
    fake_driver = _FakeDriver()

    class _FakeGraphDatabase:
        @staticmethod
        def driver(uri, *, auth=None, **config):
            del uri, auth, config
            return fake_driver

    monkeypatch.setattr(neo_db, "GraphDatabase", _FakeGraphDatabase)
    monkeypatch.setenv("NEO4J_QUERY_TIMEOUT_S", "30")

    db = neo_db.Neo4jGraphDB(
        "bolt://example:7687",
        "neo4j",
        "secret",
        preload_cache=False,
    )

    _ = list(db._run("RETURN 1", {}, timeout_s=1.25))

    calls = fake_driver.session_obj.calls
    assert len(calls) == 1
    assert calls[0]["kwargs"] == {"timeout": 1.25}
    db.close()
