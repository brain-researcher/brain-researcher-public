import json
from pathlib import Path

from brain_researcher.services.orchestrator.reward import (
    compute_reward_breakdown_from_run_dir,
)


def test_reward_breakdown_counts_penalties(tmp_path: Path):
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()

    (run_dir / "trajectory.json").write_text(
        json.dumps(
            {
                "schema_version": "ATIF-v1.4",
                "session_id": "r1",
                "agent": {"name": "br", "version": "0", "model_name": "m"},
                "steps": [
                    {
                        "step_id": 1,
                        "timestamp": "2026-01-01T00:00:00Z",
                        "source": "agent",
                        "message": "Execute demo.tool",
                        "model_name": "m",
                        "tool_calls": [
                            {
                                "tool_call_id": "c1",
                                "function_name": "demo.tool",
                                "arguments": {},
                            }
                        ],
                        "observation": {
                            "results": [
                                {
                                    "source_call_id": "c1",
                                    "content": {
                                        "violations": [
                                            {"severity": "critical", "code": "X"}
                                        ]
                                    },
                                }
                            ]
                        },
                    }
                ],
                "final_metrics": {"total_steps": 1},
                "extra": {"mask_reasons": [{"code": "BUDGET"}]},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "trace.jsonl").write_text(
        (
            '{"schema_version":"analysis-stream-event-v1","ids":{"run_id":"r1"},'
            '"seq":1,"timestamp":"2026-01-01T00:00:01Z","event_type":"unknown",'
            '"payload":{"raw_event_type":"branch_succeeded","raw_payload":{}}}\n'
        ),
        encoding="utf-8",
    )

    breakdown = compute_reward_breakdown_from_run_dir(run_dir)
    assert breakdown["schema_version"] == "reward-v1"
    assert breakdown["components"]["violation_penalty"] > 0
    assert breakdown["components"]["mask_penalty"] > 0
    assert breakdown["components"]["recovery_bonus"] > 0
