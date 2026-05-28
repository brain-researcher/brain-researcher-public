from __future__ import annotations

from brain_researcher.services.neurokg.graph import graph_factory


class DummyDB:
    def close(self) -> None:
        pass

    def get_stats(self) -> dict:
        return {"ok": True}


def test_create_graph_client_accepts_legacy_kwargs(monkeypatch) -> None:
    calls = []
    dummy = DummyDB()

    def fake_require_neo4j_db():
        calls.append(True)
        return dummy

    monkeypatch.setattr(graph_factory, "require_neo4j_db", fake_require_neo4j_db)

    db = graph_factory.create_graph_client(
        db_path="legacy.sqlite",
        allow_sqlite_mock=False,
    )

    assert db is dummy
    assert calls == [True]
