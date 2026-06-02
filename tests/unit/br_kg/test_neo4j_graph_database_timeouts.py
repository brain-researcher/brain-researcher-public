from __future__ import annotations

import pytest

from brain_researcher.services.br_kg.graph import neo4j_graph_database as neo_db


class _FakeResult:
    def __init__(self, records=None):
        self._records = records if records is not None else [{"value": 1}]

    def __iter__(self):
        yield from self._records


class _FakeTransaction:
    def __init__(self, owner, timeout):
        self._owner = owner
        self.timeout = timeout
        self.committed = False
        self.closed = False
        self.runs: list[dict[str, object]] = []

    def run(self, cypher, params=None, **kwargs):
        self.runs.append({"cypher": cypher, "params": params, "kwargs": kwargs})
        if self._owner.tx_run_error is not None:
            raise self._owner.tx_run_error
        return _FakeResult(self._owner.records)

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


class _FakeSession:
    def __init__(self, owner):
        self._owner = owner
        self.autocommit_calls: list[dict[str, object]] = []
        self.begin_calls: list[dict[str, object]] = []
        self.transactions: list[_FakeTransaction] = []
        self.closed = False

    def run(self, cypher, params=None, **kwargs):
        # Autocommit path (no per-query timeout).
        self.autocommit_calls.append(
            {"cypher": cypher, "params": params, "kwargs": kwargs}
        )
        return _FakeResult(self._owner.records)

    def begin_transaction(self, metadata=None, timeout=None):
        self.begin_calls.append({"metadata": metadata, "timeout": timeout})
        if self._owner.begin_error is not None:
            raise self._owner.begin_error
        tx = _FakeTransaction(self._owner, timeout)
        self.transactions.append(tx)
        return tx

    def close(self):
        self.closed = True


class _FakeDriver:
    def __init__(self):
        self.records = [{"value": 1}]
        self.tx_run_error: Exception | None = None
        self.begin_error: Exception | None = None
        self.sessions: list[_FakeSession] = []
        self.closed = False

    def verify_connectivity(self):
        return None

    def session(self, database=None):
        sess = _FakeSession(self)
        self.sessions.append(sess)
        return sess

    def close(self):
        self.closed = True


def _make_db(monkeypatch, fake_driver):
    class _FakeGraphDatabase:
        @staticmethod
        def driver(uri, *, auth=None, **config):
            del uri, auth, config
            return fake_driver

    monkeypatch.setattr(neo_db, "GraphDatabase", _FakeGraphDatabase)
    return neo_db.Neo4jGraphDB(
        "bolt://example:7687",
        "neo4j",
        "secret",
        preload_cache=False,
    )


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


def test_default_timeout_uses_begin_transaction_not_run_kwarg(monkeypatch):
    # The module default NEO4J_QUERY_TIMEOUT_S must be applied as a server-side
    # transaction timeout via begin_transaction(timeout=...), NOT as a run()
    # kwarg (which neo4j 6.1.0 would merge into the Cypher params as $timeout).
    fake_driver = _FakeDriver()
    monkeypatch.setenv("NEO4J_QUERY_TIMEOUT_S", "12")
    db = _make_db(monkeypatch, fake_driver)

    records = list(db._run("RETURN 1", {"foo": "bar"}))
    assert records == [{"value": 1}]

    session = fake_driver.sessions[-1]
    # No autocommit run(): the timed path goes through an explicit transaction.
    assert session.autocommit_calls == []
    assert len(session.begin_calls) == 1
    # Timeout forwarded as a float seconds value to begin_transaction.
    assert session.begin_calls[0]["timeout"] == 12.0
    assert isinstance(session.begin_calls[0]["timeout"], float)

    tx = session.transactions[-1]
    assert len(tx.runs) == 1
    # The query parameters must NOT carry a leaked $timeout key.
    assert tx.runs[0]["params"] == {"foo": "bar"}
    assert "timeout" not in (tx.runs[0]["params"] or {})
    # And run() itself must not receive a timeout kwarg.
    assert tx.runs[0]["kwargs"] == {}
    assert tx.committed is True
    assert session.closed is True
    db.close()


def test_per_call_timeout_overrides_default_via_begin_transaction(monkeypatch):
    fake_driver = _FakeDriver()
    monkeypatch.setenv("NEO4J_QUERY_TIMEOUT_S", "30")
    db = _make_db(monkeypatch, fake_driver)

    list(db._run("RETURN 1", {}, timeout_s=1.25))

    session = fake_driver.sessions[-1]
    assert session.autocommit_calls == []
    assert session.begin_calls[0]["timeout"] == 1.25
    tx = session.transactions[-1]
    assert tx.runs[0]["params"] == {}
    assert tx.runs[0]["kwargs"] == {}
    assert "timeout" not in (tx.runs[0]["params"] or {})
    db.close()


def test_no_timeout_uses_autocommit_run(monkeypatch):
    # Backward-compat: with no timeout configured, behave exactly as before --
    # a plain autocommit session.run(), no begin_transaction, no $timeout param.
    fake_driver = _FakeDriver()
    monkeypatch.setenv("NEO4J_QUERY_TIMEOUT_S", "0")  # disables default timeout
    db = _make_db(monkeypatch, fake_driver)

    records = list(db._run("RETURN 1", {"a": 1}))
    assert records == [{"value": 1}]

    session = fake_driver.sessions[-1]
    assert session.begin_calls == []
    assert len(session.autocommit_calls) == 1
    assert session.autocommit_calls[0]["params"] == {"a": 1}
    assert session.autocommit_calls[0]["kwargs"] == {}
    assert "timeout" not in (session.autocommit_calls[0]["params"] or {})
    db.close()


def test_fired_transaction_timeout_propagates(monkeypatch):
    # A server-side transaction timeout raises a Neo4j ClientError/TransientError
    # from tx.run(); _run must let it propagate (not swallow / not re-run untimed)
    # and must clean up the transaction and session.
    from neo4j.exceptions import ClientError

    fake_driver = _FakeDriver()
    fake_driver.tx_run_error = ClientError(
        "The transaction has been terminated. "
        "Neo4j.ClientError.Transaction.TransactionTimedOut"
    )
    monkeypatch.setenv("NEO4J_QUERY_TIMEOUT_S", "5")
    db = _make_db(monkeypatch, fake_driver)

    with pytest.raises(ClientError):
        list(db._run("RETURN 1", {}, timeout_s=2.0))

    session = fake_driver.sessions[-1]
    tx = session.transactions[-1]
    assert tx.committed is False
    assert tx.closed is True
    assert session.closed is True
    db.close()
