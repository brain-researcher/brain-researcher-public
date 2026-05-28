from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from scripts.neurometabench_v1 import run_agent_condition_matrix as matrix


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_load_conditions_filters_diagnostic_rows(tmp_path: Path) -> None:
    conditions_path = tmp_path / "conditions.jsonl"
    _write_jsonl(
        conditions_path,
        [
            {
                "record_type": "condition",
                "condition_id": "codex_without",
                "runner": "codex_cli",
                "model_target": "gpt-5.5",
                "br_mode": "without_br",
                "layers": ["layer_a"],
            },
            {
                "record_type": "diagnostic_only",
                "condition_id": "direct_api",
                "runner": "python",
            },
        ],
    )

    conditions = matrix.load_conditions(conditions_path)

    assert [condition.condition_id for condition in conditions] == ["codex_without"]


def test_select_cases_uses_layer_and_limit(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.jsonl"
    _write_jsonl(
        cases_path,
        [
            {
                "case_id": "neurometabench:1",
                "meta_pmid": "1",
                "primary_task_layer": "layer_a_screening_with_justification",
                "task_layers": ["layer_a_screening_with_justification"],
            },
            {
                "case_id": "neurometabench:2",
                "meta_pmid": "2",
                "primary_task_layer": "layer_a_screening_with_justification",
                "task_layers": ["layer_a_screening_with_justification"],
            },
            {
                "case_id": "neurometabench:3",
                "meta_pmid": "3",
                "primary_task_layer": "layer_b_end_to_end_reproduction",
                "task_layers": ["layer_b_end_to_end_reproduction"],
            },
        ],
    )

    cases = matrix.select_cases(
        cases_path=cases_path,
        layer="layer_a",
        meta_pmids=set(),
        limit_cases=1,
    )

    assert [case["meta_pmid"] for case in cases] == ["1"]


def test_materialize_layer_a_inputs_hide_gold_labels(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _write_jsonl(data_dir / "unused.jsonl", [])
    (data_dir / "included_studies.csv").write_text(
        "meta_pmid,study_pmid\n1,10\n1,20\n",
        encoding="utf-8",
    )
    (data_dir / "all_studies.csv").write_text(
        "meta_pmid,study_pmid,title,status,final_status,SourceSheet,"
        "corrected_status,posthoc_status,posthoc_reason,reason\n"
        "1,10,GT A,YES,YES,Gold,YES,YES,answer,Included answer\n"
        "1,20,GT B,YES,YES,Gold,YES,YES,answer,Included answer\n"
        "9,30,Noise A,NO,NO,Noise,NO,NO,answer,Excluded answer\n"
        "9,40,Noise B,NO,NO,Noise,NO,NO,answer,Excluded answer\n",
        encoding="utf-8",
    )
    case = {
        "case_id": "neurometabench:1",
        "meta_pmid": "1",
        "topic": "Toy",
        "gt_pmids": ["10", "20"],
        "n_gt": 2,
        "selected_n": "2",
        "screening_criteria": [{"criterion_id": "inc_a", "text": "A"}],
    }

    outputs = matrix.materialize_layer_a_inputs(
        run_dir=tmp_path / "run",
        cases=[case],
        data_dir=data_dir,
        max_candidates=4,
        mixed_pool_noise_ratio=1,
        mixed_pool_seed=0,
    )
    case_json = json.loads((outputs["1"] / "case.json").read_text(encoding="utf-8"))
    candidate_text = (outputs["1"] / "candidates.jsonl").read_text(encoding="utf-8")

    assert "gt_pmids" not in case_json
    assert "n_gt" not in case_json
    assert "selected_n" not in case_json
    assert "YES" not in candidate_text
    assert "NO" not in candidate_text
    assert "SourceSheet" not in candidate_text
    assert "corrected_status" not in candidate_text
    assert "posthoc_status" not in candidate_text
    assert "posthoc_reason" not in candidate_text
    assert "reason" not in candidate_text
    assert "meta_pmid" not in candidate_text


def test_materialize_layer_a_inputs_records_budget_policy_when_gt_exceeds_cap(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    (data_dir / "included_studies.csv").parent.mkdir(parents=True, exist_ok=True)
    (data_dir / "included_studies.csv").write_text(
        "meta_pmid,study_pmid\n"
        "1,10\n"
        "1,20\n"
        "1,30\n",
        encoding="utf-8",
    )
    (data_dir / "all_studies.csv").write_text(
        "meta_pmid,study_pmid,title,status\n"
        "1,10,GT A,YES\n"
        "1,20,GT B,YES\n"
        "1,30,GT C,YES\n",
        encoding="utf-8",
    )
    case = {
        "case_id": "neurometabench:1",
        "meta_pmid": "1",
        "topic": "Toy",
        "gt_pmids": ["10", "20", "30"],
    }

    outputs = matrix.materialize_layer_a_inputs(
        run_dir=tmp_path / "run",
        cases=[case],
        data_dir=data_dir,
        max_candidates=2,
        mixed_pool_noise_ratio=1,
        mixed_pool_seed=0,
    )
    manifest = json.loads(
        (outputs["1"] / "input_manifest.json").read_text(encoding="utf-8")
    )

    assert manifest["requested_max_candidates"] == 2
    assert manifest["n_candidates"] == 3
    assert manifest["candidate_count_exceeds_requested_max"] is True
    assert (
        manifest["candidate_budget_policy"]
        == "preserve_all_gt_pmids_may_exceed_requested_max"
    )


def test_build_command_encodes_runner_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(matrix, "opencode_has_mcp", lambda: False)
    codex = matrix.Condition(
        condition_id="codex_with",
        runner="codex_cli",
        model_target="gpt-5.5",
        br_mode="with_br_mcp",
        layers=("layer_a",),
        raw={},
    )
    opencode = matrix.Condition(
        condition_id="opencode_with",
        runner="opencode",
        model_target="opencode/model",
        br_mode="with_br_mcp",
        layers=("layer_a",),
        raw={},
    )

    command, skip = matrix.build_command(
        condition=codex,
        prompt="prompt",
        run_dir=tmp_path,
        repo_root=tmp_path,
        codex_bin="python",
        claude_bin="python",
        opencode_bin="python",
        claude_br_mcp_config=tmp_path / "missing.json",
        allow_opencode_with_br=False,
    )
    assert skip is None
    assert "mcp_servers.brain-researcher-prod.enabled=true" in command

    command, skip = matrix.build_command(
        condition=opencode,
        prompt="prompt",
        run_dir=tmp_path,
        repo_root=tmp_path,
        codex_bin="python",
        claude_bin="python",
        opencode_bin="python",
        claude_br_mcp_config=tmp_path / "missing.json",
        allow_opencode_with_br=False,
    )
    assert command == []
    assert skip == "skipped_missing_opencode_br_mcp"


def test_build_command_treats_required_br_as_br_enabled(tmp_path: Path) -> None:
    condition = matrix.Condition(
        condition_id="codex_with_required",
        runner="codex_cli",
        model_target="gpt-5.5",
        br_mode="with_br_required",
        layers=("layer_b",),
        raw={},
    )

    command, skip = matrix.build_command(
        condition=condition,
        prompt="prompt",
        run_dir=tmp_path,
        repo_root=tmp_path,
        codex_bin="python",
        claude_bin="python",
        opencode_bin="python",
        claude_br_mcp_config=tmp_path / "missing.json",
        allow_opencode_with_br=False,
    )

    assert skip is None
    assert "mcp_servers.brain-researcher-prod.enabled=true" in command
    assert matrix.condition_br_required(condition)


def test_layer_b_prompt_injects_evaluator_path_soft_deadline_and_br_required(
    tmp_path: Path,
) -> None:
    condition = matrix.Condition(
        condition_id="codex_with_required",
        runner="codex_cli",
        model_target="gpt-5.5",
        br_mode="with_br_required",
        layers=("layer_b",),
        raw={},
    )
    case = {
        "case_id": "neurometabench:123",
        "meta_pmid": "123",
        "topic": "Reward",
    }

    prompt = matrix.build_prompt(
        base_prompt="BASE",
        layer="layer_b",
        condition=condition,
        cases=[case],
        input_dirs={"123": tmp_path / "inputs" / "layer_b_123"},
        producer_output_dir=tmp_path / "producer" / "cond",
        max_candidates=150,
        mixed_pool_noise_ratio=5,
        mixed_pool_seed=0,
        layer_b_soft_deadline_s=1500,
        require_br_effective_use=True,
    )

    assert "METABENCH_EVALUATOR_PATH" in prompt
    assert "--print-contract" in prompt
    assert "Soft deadline: `1500`" in prompt
    assert "Do not spend more than the first third" in prompt
    assert "BR-required condition" in prompt
    assert "BR table write policy: conservative" in prompt
    assert (
        "Treat `coordinate_table.csv` and `included_studies.csv` as reproduction artifacts"
        in prompt
    )
    assert "Do not split, merge, rename" in prompt
    assert "Make useful BR results canonicalizable for audit artifacts" in prompt
    assert "br_reconciliation_anchors.json" in prompt
    assert "`target_field`" in prompt
    assert "`study_pmid`" in prompt
    assert "`coordinate_space`" in prompt
    assert "canonical_value` entries short and exact" in prompt
    assert "Do not set `changed_bundle=true` for audit-only evidence" in prompt
    assert "BR reconciliation anchors" in prompt
    assert "Do not change scientific table values solely" in prompt
    assert "Preserve the canonical NiMADS/NiMARE values" in prompt
    assert "Fallback or synthetic maps must be marked degraded" in prompt


def test_claude_stream_json_command_uses_verbose(tmp_path: Path) -> None:
    config = tmp_path / "mcp.json"
    config.write_text('{"mcpServers": {}}', encoding="utf-8")
    condition = matrix.Condition(
        condition_id="claude_without",
        runner="claude_code",
        model_target="opus",
        br_mode="without_br",
        layers=("layer_a",),
        raw={},
    )

    command, skip = matrix.build_command(
        condition=condition,
        prompt="prompt",
        run_dir=tmp_path,
        repo_root=tmp_path,
        codex_bin="python",
        claude_bin="python",
        opencode_bin="python",
        claude_br_mcp_config=config,
        allow_opencode_with_br=False,
    )

    assert skip is None
    assert "--output-format" in command
    assert "stream-json" in command
    assert "--verbose" in command


def test_json_error_event_detection() -> None:
    assert matrix._has_json_error_event('{"type":"error","error":{"message":"bad"}}')
    assert not matrix._has_json_error_event('{"type":"step_finish"}')


def test_default_gemini_conditions_use_google_env_provider() -> None:
    conditions = {
        condition.condition_id: condition
        for condition in matrix.load_conditions(matrix.DEFAULT_CONDITIONS_PATH)
    }

    assert (
        conditions["opencode_gemini_pro_without_br"].model_target
        == "google/gemini-3.1-pro-preview"
    )
    assert (
        conditions["opencode_gemini_pro_with_br"].raw.get("provider_id")
        == "google"
    )
    assert conditions["opencode_glm51_with_br"].model_target == "zai-coding-plan/glm-5.1"
    assert conditions["opencode_kimi_k25_with_br"].model_target == "opencode/kimi-k2.5"
    assert conditions["opencode_qwen36_plus_with_br"].model_target == "opencode/qwen3.6-plus"
    assert (
        conditions["opencode_deepseek_v4_pro_with_br"].model_target
        == "deepseek/deepseek-v4-pro"
    )


def test_load_env_file_sets_missing_values_without_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GEMINI_API_KEY=from_file\n"
        "export GOOGLE_API_KEY='google_from_file'\n"
        "KEEP_EXISTING=from_file\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("KEEP_EXISTING", "already")

    loaded = matrix.load_env_file(env_file)

    assert "GEMINI_API_KEY" in loaded
    assert "GOOGLE_API_KEY" in loaded
    assert "KEEP_EXISTING" not in loaded
    assert matrix.os.environ["GEMINI_API_KEY"] == "from_file"
    assert matrix.os.environ["GOOGLE_API_KEY"] == "google_from_file"
    assert matrix.os.environ["KEEP_EXISTING"] == "already"


def test_layer_b_comparison_only_scores_succeeded_conditions(tmp_path: Path) -> None:
    conditions = [
        matrix.Condition(
            condition_id="ok",
            runner="opencode",
            model_target="google/gemini-3.1-pro-preview",
            br_mode="without_br",
            layers=("layer_b",),
            raw={},
        ),
        matrix.Condition(
            condition_id="timeout",
            runner="opencode",
            model_target="google/gemini-3.1-pro-preview",
            br_mode="without_br",
            layers=("layer_b",),
            raw={},
        ),
    ]

    comparison_conditions = matrix.collect_layer_b_comparison_conditions(
        run_dir=tmp_path,
        conditions=conditions,
        records=[
            {"condition_id": "ok", "status": "succeeded"},
            {"condition_id": "timeout", "status": "timed_out"},
        ],
    )

    names = [condition.name for condition in comparison_conditions]
    assert "ok" in names
    assert "timeout" not in names


def test_timeout_terminates_child_process_group(tmp_path: Path) -> None:
    marker = tmp_path / "late_marker.txt"
    script = tmp_path / "spawn_child.py"
    script.write_text(
        "import subprocess, sys, time\n"
        "marker = sys.argv[1]\n"
        "subprocess.Popen([sys.executable, '-c', "
        "\"import pathlib, sys, time; time.sleep(2.0); "
        "pathlib.Path(sys.argv[1]).write_text('late', encoding='utf-8')\", "
        "marker])\n"
        "time.sleep(10)\n",
        encoding="utf-8",
    )
    condition = matrix.Condition(
        condition_id="timeout",
        runner="opencode",
        model_target="google/gemini-3.1-pro-preview",
        br_mode="without_br",
        layers=("layer_b",),
        raw={},
    )
    episode = matrix.Episode(
        condition=condition,
        episode_dir=tmp_path / "episode",
        producer_output_dir=tmp_path / "producer",
        command=[sys.executable, str(script), str(marker)],
        prompt="",
        meta_pmids=("32659287",),
    )

    record = matrix.run_episode(episode=episode, timeout_s=1, dry_run=False)
    time.sleep(2.2)

    assert record["status"] == "timed_out"
    assert record["terminated_process_group"] is True
    assert not marker.exists()


def test_run_episodes_resume_reuses_terminal_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    condition = matrix.Condition(
        condition_id="codex_without",
        runner="codex_cli",
        model_target="gpt-5.5",
        br_mode="without_br",
        layers=("layer_a",),
        raw={},
    )
    episode = matrix.Episode(
        condition=condition,
        episode_dir=tmp_path / "episodes/codex_without/layer_a_1",
        producer_output_dir=tmp_path / "producer/codex_without",
        command=["python"],
        prompt="prompt",
        meta_pmids=("1",),
    )
    episode.episode_dir.mkdir(parents=True)
    record = {
        "condition_id": "codex_without",
        "status": "succeeded",
        "meta_pmids": ["1"],
    }
    (episode.episode_dir / "record.json").write_text(
        json.dumps(record), encoding="utf-8"
    )

    def fail_run_episode(**_: object) -> dict[str, object]:
        raise AssertionError("resume should not execute existing terminal episode")

    monkeypatch.setattr(matrix, "run_episode", fail_run_episode)

    records = matrix.run_episodes(
        episodes=[episode],
        timeout_s=1,
        dry_run=False,
        max_workers=2,
        resume=True,
        records_path=tmp_path / "episode_records.jsonl",
    )

    assert records == [record | {"resumed_from_record": True}]


def test_run_episodes_parallel_collects_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    condition = matrix.Condition(
        condition_id="codex_without",
        runner="codex_cli",
        model_target="gpt-5.5",
        br_mode="without_br",
        layers=("layer_a",),
        raw={},
    )
    episodes = [
        matrix.Episode(
            condition=condition,
            episode_dir=tmp_path / f"episodes/codex_without/layer_a_{meta_pmid}",
            producer_output_dir=tmp_path / "producer/codex_without",
            command=["python"],
            prompt="prompt",
            meta_pmids=(meta_pmid,),
        )
        for meta_pmid in ("1", "2")
    ]

    def fake_run_episode(*, episode: matrix.Episode, **_: object) -> dict[str, object]:
        return {
            "condition_id": episode.condition.condition_id,
            "meta_pmids": list(episode.meta_pmids),
            "status": "succeeded",
        }

    monkeypatch.setattr(matrix, "run_episode", fake_run_episode)

    records = matrix.run_episodes(
        episodes=episodes,
        timeout_s=1,
        dry_run=False,
        max_workers=2,
        resume=False,
        records_path=tmp_path / "episode_records.jsonl",
    )

    assert sorted(record["meta_pmids"][0] for record in records) == ["1", "2"]
    assert len((tmp_path / "episode_records.jsonl").read_text().splitlines()) == 2


def test_round_robin_by_condition_interleaves_conditions(tmp_path: Path) -> None:
    conditions = [
        matrix.Condition(
            condition_id=condition_id,
            runner="opencode",
            model_target="model",
            br_mode="without_br",
            layers=("layer_a",),
            raw={},
        )
        for condition_id in ("a", "b")
    ]
    episodes = [
        matrix.Episode(
            condition=condition,
            episode_dir=tmp_path / condition.condition_id / meta_pmid,
            producer_output_dir=tmp_path / condition.condition_id,
            command=["opencode"],
            prompt="prompt",
            meta_pmids=(meta_pmid,),
        )
        for condition in conditions
        for meta_pmid in ("1", "2")
    ]

    ordered = matrix._round_robin_by_condition(episodes)

    assert [(e.condition.condition_id, e.meta_pmids[0]) for e in ordered] == [
        ("a", "1"),
        ("b", "1"),
        ("a", "2"),
        ("b", "2"),
    ]


def test_episode_env_disables_opencode_project_config_for_without_br(
    tmp_path: Path,
) -> None:
    without = matrix.Condition(
        condition_id="opencode_without",
        runner="opencode",
        model_target="opencode/qwen3.6-plus",
        br_mode="without_br",
        layers=("layer_a",),
        raw={},
    )
    with_br = matrix.Condition(
        condition_id="opencode_with",
        runner="opencode",
        model_target="opencode/qwen3.6-plus",
        br_mode="with_br_mcp",
        layers=("layer_a",),
        raw={},
    )

    def episode(condition: matrix.Condition) -> matrix.Episode:
        return matrix.Episode(
            condition=condition,
            episode_dir=tmp_path / condition.condition_id,
            producer_output_dir=tmp_path / "producer" / condition.condition_id,
            command=["opencode"],
            prompt="prompt",
            meta_pmids=("1",),
        )

    assert matrix.episode_env(episode(without))["OPENCODE_DISABLE_PROJECT_CONFIG"] == "1"
    assert "OPENCODE_DISABLE_PROJECT_CONFIG" not in matrix.episode_env(
        episode(with_br)
    )


def test_build_prompt_uses_neutral_br_boundary_and_no_agent_eval(
    tmp_path: Path,
) -> None:
    condition = matrix.Condition(
        condition_id="opencode_with",
        runner="opencode",
        model_target="opencode/model",
        br_mode="with_br_mcp",
        layers=("layer_a",),
        raw={},
    )
    prompt = matrix.build_prompt(
        base_prompt="base",
        layer="layer_a",
        condition=condition,
        cases=[{"case_id": "neurometabench:1", "meta_pmid": "1", "topic": "Toy"}],
        input_dirs={"1": tmp_path / "case"},
        producer_output_dir=tmp_path / "producer",
        max_candidates=150,
        mixed_pool_noise_ratio=5,
        mixed_pool_seed=0,
    )

    assert "BR MCP/tools are available for this condition" in prompt
    assert "Use BR only where it adds" not in prompt
    assert "Do not run the benchmark evaluator" in prompt
    assert "pure NiMARE/control outputs" in prompt
    assert "harness will aggregate prediction rows across case episodes" in prompt
    assert "recall-oriented evidence recovery" in prompt
    assert "Do not use BR as a conservative exclusion filter" in prompt
    assert "br_screening_anchors.json" in prompt


def test_layer_a_br_required_prompt_adds_screening_anchor_contract(
    tmp_path: Path,
) -> None:
    condition = matrix.Condition(
        condition_id="opencode_with",
        runner="opencode",
        model_target="opencode/model",
        br_mode="with_br_mcp",
        layers=("layer_a",),
        raw={},
    )
    prompt = matrix.build_prompt(
        base_prompt="base",
        layer="layer_a",
        condition=condition,
        cases=[{"case_id": "neurometabench:1", "meta_pmid": "1", "topic": "Toy"}],
        input_dirs={"1": tmp_path / "case"},
        producer_output_dir=tmp_path / "producer",
        max_candidates=150,
        mixed_pool_noise_ratio=5,
        mixed_pool_seed=0,
        require_br_effective_use=True,
    )

    assert "BR-required Layer A condition" in prompt
    assert "non-empty `br_screening_anchors.json`" in prompt
    assert "inclusion-supporting" in prompt
    assert "`supports_inclusion`" in prompt
    assert "must appear in `screening_decisions.jsonl`" in prompt


def test_layer_b_base_prompt_does_not_expose_control_output_path() -> None:
    prompt = matrix.DEFAULT_LAYER_B_PROMPT.read_text(encoding="utf-8")

    assert "experiments/path_b_reproduction" not in prompt
    assert "Do not copy or inspect prior Layer B" in prompt
    assert "BR-assisted preflight and audit" in prompt
    assert "reconcile study identifiers to PMID/DOI" in prompt
    assert "canonicalizable in audit artifacts" in prompt
    assert "explicit evaluator fields" in prompt


def test_collect_layer_b_comparison_conditions_includes_control_and_attempted_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pure = tmp_path / "pure_nimare"
    pure.mkdir()
    monkeypatch.setattr(matrix, "DEFAULT_LAYER_B_PURE_NIMARE_OUTPUT", pure)
    conditions = [
        matrix.Condition(
            condition_id="codex_without",
            runner="codex_cli",
            model_target="gpt-5.5",
            br_mode="without_br",
            layers=("layer_b",),
            raw={},
        ),
        matrix.Condition(
            condition_id="opencode_with",
            runner="opencode",
            model_target="model",
            br_mode="with_br_mcp",
            layers=("layer_b",),
            raw={},
        ),
    ]
    records = [
        {"condition_id": "codex_without", "status": "succeeded"},
        {"condition_id": "opencode_with", "status": "skipped"},
    ]

    comparison_conditions = matrix.collect_layer_b_comparison_conditions(
        run_dir=tmp_path / "run",
        conditions=conditions,
        records=records,
    )

    assert [condition.name for condition in comparison_conditions] == [
        "pure_nimare",
        "codex_without",
    ]


def test_build_episodes_defaults_to_one_episode_per_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(matrix, "_command_exists", lambda _binary: True)
    condition = matrix.Condition(
        condition_id="codex_without",
        runner="codex_cli",
        model_target="gpt-5.5",
        br_mode="without_br",
        layers=("layer_a",),
        raw={},
    )
    cases = [
        {"case_id": "neurometabench:1", "meta_pmid": "1", "topic": "A"},
        {"case_id": "neurometabench:2", "meta_pmid": "2", "topic": "B"},
    ]

    episodes = matrix.build_episodes(
        run_dir=tmp_path / "run",
        layer="layer_a",
        base_prompt="base",
        cases=cases,
        input_dirs={"1": tmp_path / "1", "2": tmp_path / "2"},
        conditions=[condition],
        max_candidates=150,
        mixed_pool_noise_ratio=5,
        mixed_pool_seed=0,
        codex_bin="python",
        claude_bin="python",
        opencode_bin="python",
        claude_br_mcp_config=tmp_path / "missing.json",
        allow_opencode_with_br=False,
        episode_scope=matrix.EPISODE_SCOPE_CASE,
    )

    assert [episode.meta_pmids for episode in episodes] == [("1",), ("2",)]
    assert [episode.episode_dir.name for episode in episodes] == [
        "layer_a_1",
        "layer_a_2",
    ]


def test_layer_b_case_episodes_use_isolated_producer_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(matrix, "_command_exists", lambda _binary: True)
    condition = matrix.Condition(
        condition_id="codex_with",
        runner="codex_cli",
        model_target="gpt-5.5",
        br_mode="with_br_required",
        layers=("layer_b",),
        raw={},
    )
    cases = [
        {"case_id": "neurometabench:1", "meta_pmid": "1", "topic": "A"},
        {"case_id": "neurometabench:2", "meta_pmid": "2", "topic": "B"},
    ]

    episodes = matrix.build_episodes(
        run_dir=tmp_path / "run",
        layer="layer_b",
        base_prompt="base",
        cases=cases,
        input_dirs={"1": tmp_path / "1", "2": tmp_path / "2"},
        conditions=[condition],
        max_candidates=150,
        mixed_pool_noise_ratio=5,
        mixed_pool_seed=0,
        codex_bin="python",
        claude_bin="python",
        opencode_bin="python",
        claude_br_mcp_config=tmp_path / "missing.json",
        allow_opencode_with_br=False,
        episode_scope=matrix.EPISODE_SCOPE_CASE,
    )

    assert [episode.producer_output_dir.name for episode in episodes] == [
        "_episode_layer_b_1",
        "_episode_layer_b_2",
    ]
    assert all(
        episode.producer_output_dir.parent.name == "codex_with"
        for episode in episodes
    )


def test_validate_layer_a_outputs_requires_all_materialized_candidates(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    case_input = run_dir / "case_inputs/layer_a/layer_a_1_mixed_pool"
    _write_jsonl(
        case_input / "candidates.jsonl",
        [{"pmid": "10"}, {"pmid": "20"}, {"pmid": "30"}],
    )
    output_dir = run_dir / "producer_outputs/codex_without/layer_a_1_mixed_pool"
    _write_jsonl(
        output_dir / "predictions.jsonl",
        [
            {
                "case_id": "neurometabench:1",
                "meta_pmid": "1",
                "system": "codex_without",
                "predicted_pmids": ["10"],
                "ranked_pmids": ["10", "20"],
            }
        ],
    )
    _write_jsonl(
        output_dir / "screening_decisions.jsonl",
        [{"candidate_pmid": "10"}, {"candidate_pmid": "20"}],
    )
    condition = matrix.Condition(
        condition_id="codex_without",
        runner="codex_cli",
        model_target="gpt-5.5",
        br_mode="without_br",
        layers=("layer_a",),
        raw={},
    )

    result = matrix.validate_layer_a_outputs(
        run_dir=run_dir,
        cases=[{"case_id": "neurometabench:1", "meta_pmid": "1"}],
        conditions=[condition],
    )

    errors = result["codex_without"]["cases"]["1"]["errors"]
    assert result["codex_without"]["valid"] is False
    assert any(error.startswith("ranked_pmids_count_mismatch") for error in errors)
    assert any(
        error.startswith("screening_decisions_count_mismatch") for error in errors
    )


def test_layer_a_br_required_validation_requires_consumed_screening_anchors(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    case_input = run_dir / "case_inputs/layer_a/layer_a_1_mixed_pool"
    _write_jsonl(case_input / "candidates.jsonl", [{"pmid": "10"}, {"pmid": "20"}])
    output_dir = run_dir / "producer_outputs/codex_with/layer_a_1_mixed_pool"
    _write_jsonl(
        output_dir / "predictions.jsonl",
        [
            {
                "case_id": "neurometabench:1",
                "meta_pmid": "1",
                "system": "codex_with",
                "predicted_pmids": ["10"],
                "ranked_pmids": ["10", "20"],
            }
        ],
    )
    _write_jsonl(
        output_dir / "screening_decisions.jsonl",
        [
            {"pmid": "10", "decision": "include"},
            {"pmid": "20", "decision": "exclude"},
        ],
    )
    condition = matrix.Condition(
        condition_id="codex_with",
        runner="codex_cli",
        model_target="gpt-5.5",
        br_mode="with_br_mcp",
        layers=("layer_a",),
        raw={},
    )

    missing = matrix.validate_layer_a_outputs(
        run_dir=run_dir,
        cases=[{"case_id": "neurometabench:1", "meta_pmid": "1"}],
        conditions=[condition],
        require_br_effective_use=True,
    )
    assert "missing_br_screening_anchors_json" in missing["codex_with"]["cases"]["1"]["errors"]

    matrix.write_json(
        output_dir / "br_screening_anchors.json",
        {
            "anchors": [
                {
                    "candidate_pmid": "20",
                    "decision": "exclude",
                    "supports_inclusion": False,
                    "eligibility_criterion": "toy exclusion",
                    "evidence_source": "BR MCP",
                    "evidence_summary": "Recovered exclusion evidence.",
                    "confidence": "high",
                    "consumed_by": ["screening_decisions.jsonl"],
                }
            ]
        },
    )
    exclude_only = matrix.validate_layer_a_outputs(
        run_dir=run_dir,
        cases=[{"case_id": "neurometabench:1", "meta_pmid": "1"}],
        conditions=[condition],
        require_br_effective_use=True,
    )
    assert (
        "missing_consumed_inclusion_supporting_br_screening_anchor"
        in exclude_only["codex_with"]["cases"]["1"]["errors"]
    )

    matrix.write_json(
        output_dir / "br_screening_anchors.json",
        {
            "anchors": [
                {
                    "candidate_pmid": "10",
                    "decision": "include",
                    "supports_inclusion": True,
                    "eligibility_criterion": "toy inclusion",
                    "evidence_source": "BR MCP",
                    "evidence_summary": "Recovered inclusion evidence.",
                    "confidence": "high",
                    "consumed_by": ["screening_decisions.jsonl"],
                }
            ]
        },
    )

    valid = matrix.validate_layer_a_outputs(
        run_dir=run_dir,
        cases=[{"case_id": "neurometabench:1", "meta_pmid": "1"}],
        conditions=[condition],
        require_br_effective_use=True,
    )
    assert valid["codex_with"]["valid"] is True


def test_collect_layer_a_predictions_embeds_br_screening_anchors(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    output_dir = run_dir / "producer_outputs/codex_with/layer_a_1_mixed_pool"
    _write_jsonl(
        output_dir / "predictions.jsonl",
        [
            {
                "case_id": "neurometabench:1",
                "meta_pmid": "1",
                "ranked_pmids": ["10"],
                "predicted_pmids": ["10"],
            }
        ],
    )
    matrix.write_json(
        output_dir / "br_screening_anchors.json",
        {
            "anchors": [
                {
                    "candidate_pmid": "10",
                    "decision": "include",
                    "supports_inclusion": True,
                    "eligibility_criterion": "toy inclusion",
                    "evidence_source": "BR MCP",
                    "evidence_summary": "Recovered inclusion evidence.",
                    "confidence": "high",
                    "consumed_by": ["screening_decisions.jsonl"],
                }
            ]
        },
    )
    condition = matrix.Condition(
        condition_id="codex_with",
        runner="codex_cli",
        model_target="gpt-5.5",
        br_mode="with_br_mcp",
        layers=("layer_a",),
        raw={},
    )

    [aggregate] = matrix.collect_layer_a_predictions(run_dir, [condition])
    [row] = matrix.read_jsonl(aggregate)

    assert row["br_screening_anchors"][0]["candidate_pmid"] == "10"
    assert row["br_screening_anchors_file"].endswith("br_screening_anchors.json")
