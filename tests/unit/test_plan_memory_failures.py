from brain_researcher.services.agent.plan_memory import PlanMemory


def test_record_failure_with_plan(tmp_path):
    db_path = tmp_path / "plan_memory.db"
    pm = PlanMemory(db_path=str(db_path))

    plan = {
        "plan_id": "plan_test_001",
        "query": "run glm analysis",
        "steps": [{"id": "001", "tool": "glm_tool", "params": {}}],
    }
    plan_id = pm.record_plan(plan=plan, user_id="u1", workspace_id="w1", query="run glm analysis")

    failure_id = pm.record_failure(
        plan_id=plan_id,
        step_id="001",
        tool_id="glm_tool",
        error_category="infra",
        recovery_action="retry_backoff",
        is_retryable=True,
        error_message="timeout",
        attempt=1,
        max_attempts=3,
        recovered=False,
    )

    failures = pm.list_failures(plan_id=plan_id)
    assert failures, "Failure records should be stored"
    assert failures[0].failure_id == failure_id
    assert failures[0].tool_id == "glm_tool"


def test_ensure_plan_record_allows_failure(tmp_path):
    db_path = tmp_path / "plan_memory.db"
    pm = PlanMemory(db_path=str(db_path))

    ok = pm.ensure_plan_record(
        plan_id="plan_missing",
        plan={"plan_id": "plan_missing", "steps": []},
        query="missing plan",
        user_id="u2",
        workspace_id="w2",
    )
    assert ok is True

    failure_id = pm.record_failure(
        plan_id="plan_missing",
        tool_id="tool_x",
        error_category="tool",
        error_message="tool failed",
    )

    failures = pm.list_failures(plan_id="plan_missing")
    assert any(f.failure_id == failure_id for f in failures)


def test_principle_session_round_trip(tmp_path):
    db_path = tmp_path / "plan_memory.db"
    pm = PlanMemory(db_path=str(db_path))

    session_state = {
        "session_key": "pcs_demo",
        "controller_mode": "principle_v0",
        "active_principle_id": "balanced",
        "posterior": {"balanced": 0.7, "novelty_first": 0.3},
    }
    pm.upsert_principle_session(
        session_key="pcs_demo",
        query_text="fmri based image decoding",
        query_hash="query_hash_demo",
        seed_signature=["node:seed"],
        relation_signature=["ASSOCIATED_WITH"],
        taste_mode="balanced",
        controller_mode="principle_v0",
        active_principle_id="balanced",
        posterior={"balanced": 0.7, "novelty_first": 0.3},
        principles=[
            {"principle_id": "balanced", "label": "Balanced search", "kind": "base"}
        ],
        anomaly_state={"counts": {"contradiction": 1}, "latest_flags": ["contradiction"]},
        session_state=session_state,
        last_run_id="run_123",
    )

    record = pm.get_principle_session("pcs_demo")
    assert record is not None
    assert record.query_text == "fmri based image decoding"
    assert record.seed_signature == ["node:seed"]
    assert record.relation_signature == ["ASSOCIATED_WITH"]
    assert record.active_principle_id == "balanced"
    assert record.posterior == {"balanced": 0.7, "novelty_first": 0.3}
    assert record.session_state["controller_mode"] == "principle_v0"
    assert record.last_run_id == "run_123"


def test_principle_event_round_trip(tmp_path):
    db_path = tmp_path / "plan_memory.db"
    pm = PlanMemory(db_path=str(db_path))

    pm.upsert_principle_session(
        session_key="pcs_demo",
        query_text="fmri based image decoding",
        query_hash="query_hash_demo",
        seed_signature=["node:seed"],
        relation_signature=[],
        taste_mode="novelty_first",
        controller_mode="principle_v0",
        active_principle_id="novelty_first",
        posterior={"novelty_first": 1.0},
        principles=[
            {
                "principle_id": "novelty_first",
                "label": "Novelty-first search",
                "kind": "base",
            }
        ],
        anomaly_state={"counts": {}, "latest_flags": []},
        session_state={"session_key": "pcs_demo"},
    )

    event_id = pm.append_principle_event(
        session_key="pcs_demo",
        event_type="selection",
        run_id="run_123",
        step_id="principle_state_init",
        active_principle_id="novelty_first",
        payload={"selection_reason": "cold_start_taste_mode"},
    )

    events = pm.list_principle_events("pcs_demo")
    assert events
    assert events[0].event_id == event_id
    assert events[0].event_type == "selection"
    assert events[0].active_principle_id == "novelty_first"
    assert events[0].payload == {"selection_reason": "cold_start_taste_mode"}
