import importlib.util
import json
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "eval"
    / "analyze_nik_leak_free_sanity.py"
)
SPEC = importlib.util.spec_from_file_location("analyze_nik_leak_free_sanity", SCRIPT_PATH)
analyzer = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(analyzer)


def test_analyze_episode_parses_direct_task_model_mode_dir(tmp_path: Path):
    ep_dir = tmp_path / "NIK-BP-E-004__codex_gpt55__with_br_mcp"
    ep_dir.mkdir()
    (ep_dir / "record.json").write_text(
        json.dumps({"status": "succeeded"}), encoding="utf-8"
    )
    (ep_dir / "last_message.txt").write_text(
        json.dumps(
            {
                "evidence_basis": [
                    {
                        "basis_type": "specific_citation",
                        "reference": "10.1234/example.doi",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (ep_dir / "parsed_actions.jsonl").write_text(
        json.dumps({"action_type": "mcp_tool", "target": "memory_search"}) + "\n",
        encoding="utf-8",
    )

    row = analyzer.analyze_episode(ep_dir)

    assert row["task_id"] == "NIK-BP-E-004"
    assert row["model_id"] == "codex_gpt55"
    assert row["condition_id"] == "with_br_mcp"
    assert row["mode"] == "with_br_mcp"
    assert row["mcp_action_count"] == 1
    assert row["structural_grounded_rate"] == 1.0


def test_analyze_episode_counts_codex_mcp_tool_call_events(tmp_path: Path):
    ep_dir = tmp_path / "NIK-BP-E-004__codex_gpt55__with_br_fast_gated"
    ep_dir.mkdir()
    (ep_dir / "record.json").write_text(
        json.dumps({"returncode": 0}), encoding="utf-8"
    )
    (ep_dir / "last_message.txt").write_text(
        json.dumps({"evidence_basis": []}), encoding="utf-8"
    )
    event = {
        "type": "item.completed",
        "item": {
            "id": "item_0",
            "type": "mcp_tool_call",
            "server": "brain-researcher",
            "tool": "google_file_search",
            "status": "completed",
        },
    }
    (ep_dir / "events.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")

    row = analyzer.analyze_episode(ep_dir)

    assert row["action_count"] == 1
    assert row["mcp_action_count"] == 1
    assert row["concrete_action_count"] == 1
    assert row["mentions_mcp"] is True
    assert row["status"] == "succeeded"
    assert row["succeeded"] is True


def test_infer_episode_identity_parses_model_with_mode_suffix(tmp_path: Path):
    ep_dir = tmp_path / "NIK-ST-E-003__opencode_qwen36_plus_without_br"
    identity = analyzer.infer_episode_identity(ep_dir, {})

    assert identity == {
        "condition_id": "without_br",
        "task_id": "NIK-ST-E-003",
        "model_id": "opencode_qwen36_plus",
        "mode": "without_br",
    }


def test_infer_episode_identity_normalizes_record_br_mode(tmp_path: Path):
    ep_dir = tmp_path / "codex_gpt55__without_br" / "NIK-ST-E-003"
    identity = analyzer.infer_episode_identity(
        ep_dir,
        {
            "condition_id": "codex_gpt55__without_br",
            "br_mode": "codex_gpt55__without_br",
        },
    )

    assert identity["condition_id"] == "codex_gpt55__without_br"
    assert identity["mode"] == "without_br"


def test_normalize_mode_preserves_with_br_variant():
    assert (
        analyzer.normalize_mode(
            "codex_gpt55__with_br_fast_gated",
            "codex_gpt55__with_br_fast_gated",
        )
        == "with_br_fast_gated"
    )
    assert (
        analyzer.normalize_mode(
            "opencode_qwen36_plus_with_br_fast_gated",
            "opencode_qwen36_plus_with_br_fast_gated",
        )
        == "with_br_fast_gated"
    )
