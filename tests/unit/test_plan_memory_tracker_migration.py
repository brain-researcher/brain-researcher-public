import sqlite3

from brain_researcher.services.agent.plan_memory import PlanMemory


def _create_legacy_plan_memory_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE plan_records (
                plan_id           TEXT PRIMARY KEY,
                created_at        INTEGER NOT NULL,
                finished_at       INTEGER,
                user_id           TEXT NOT NULL,
                workspace_id      TEXT,
                shared_level      TEXT NOT NULL DEFAULT 'user',
                query_text        TEXT NOT NULL,
                query_hash        TEXT NOT NULL,
                complexity_level  TEXT,
                complexity_reason TEXT,
                plan_json         TEXT NOT NULL,
                step_count        INTEGER NOT NULL,
                tools_used        TEXT,
                outcome           TEXT DEFAULT 'pending',
                execution_time_ms INTEGER,
                error_message     TEXT,
                source_plan_id    TEXT,
                markdown_path     TEXT,
                linear_issue_id   TEXT
            );
            """
        )
        conn.execute(
            """
            INSERT INTO plan_records (
                plan_id, created_at, user_id, query_text, query_hash, plan_json,
                step_count, outcome, linear_issue_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "plan_legacy_1",
                1700000000,
                "u1",
                "legacy query",
                "hash1",
                '{"plan_id":"plan_legacy_1","steps":[]}',
                0,
                "pending",
                "lin_issue_123",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_plan_memory_migrates_tracker_columns_and_backfills(tmp_path):
    db_path = tmp_path / "legacy_plan_memory.db"
    _create_legacy_plan_memory_db(str(db_path))

    pm = PlanMemory(db_path=str(db_path))

    tracker_ref = pm.get_tracker_issue("plan_legacy_1")
    assert tracker_ref == {"provider": "linear", "issue_id": "lin_issue_123"}

    plan = pm.get_plan("plan_legacy_1")
    assert plan is not None
    assert plan.tracker_provider == "linear"
    assert plan.tracker_issue_id == "lin_issue_123"
    assert plan.linear_issue_id == "lin_issue_123"


def test_update_tracker_issue_and_legacy_wrapper(tmp_path):
    db_path = tmp_path / "plan_memory.db"
    pm = PlanMemory(db_path=str(db_path))

    plan = {
        "plan_id": "plan_tracker_1",
        "query": "test query",
        "steps": [],
    }
    plan_id = pm.record_plan(plan=plan, user_id="u1", query="test query")

    pm.update_tracker_issue(plan_id=plan_id, provider="linear", issue_id="lin_001")
    assert pm.get_tracker_issue(plan_id) == {
        "provider": "linear",
        "issue_id": "lin_001",
    }
    assert pm.get_linear_issue_id(plan_id) == "lin_001"

    pm.update_tracker_issue(plan_id=plan_id, provider="jira", issue_id="jira_777")
    assert pm.get_tracker_issue(plan_id) == {
        "provider": "jira",
        "issue_id": "jira_777",
    }
    assert pm.get_linear_issue_id(plan_id) is None
