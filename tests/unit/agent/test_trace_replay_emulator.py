from pathlib import Path
import json

from brain_researcher.services.agent.emulator.trace_replay import TraceReplayEnv


def test_trace_replay_env_from_records():
    recs = [
        {
            "schema_version": "ATIF-v1.4",
            "session_id": "r1",
            "step_id": 1,
            "tool_calls": [{"tool_call_id": "c1", "function_name": "demo.tool", "arguments": {}}],
            "observation": {"results": [{"source_call_id": "c1", "content": {"violations": [{"code": "X"}]}}]},
        },
        {
            "schema_version": "ATIF-v1.4",
            "session_id": "r1",
            "step_id": 2,
            "mask_reasons": [{"code": "budget"}],
        },
    ]
    env = TraceReplayEnv(records=recs)
    obs0 = env.reset()
    assert obs0["step_id"] == 1
    obs1, _, done, info = env.step()
    assert obs1["step_id"] == 2
    assert info["mask_reasons"][0]["code"] == "budget"
    assert done is False
    obs2, _, done, _ = env.step()
    assert done is True
    assert obs2["step_id"] == 2  # stays at last frame when done


def test_trace_replay_env_from_file(tmp_path: Path):
    traj = tmp_path / "trajectory.json"
    traj.write_text(
        json.dumps(
            {
                "schema_version": "ATIF-v1.4",
                "session_id": "r2",
                "agent": {"name": "br", "version": "0", "model_name": "m"},
                "steps": [
                    {
                        "step_id": 1,
                        "timestamp": "2026-01-01T00:00:00Z",
                        "source": "agent",
                        "message": "Execute demo.tool",
                        "model_name": "m",
                        "tool_calls": [
                            {"tool_call_id": "c1", "function_name": "demo.tool", "arguments": {}}
                        ],
                        "observation": {"results": [{"source_call_id": "c1", "content": {"ok": True}}]},
                    }
                ],
                "final_metrics": {"total_steps": 1},
            }
        ),
        encoding="utf-8",
    )
    env = TraceReplayEnv(trajectory_path=traj)
    obs = env.reset()
    assert obs["step_id"] == 1
