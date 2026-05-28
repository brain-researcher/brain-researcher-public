"""Regression tests for the tool-selection capability pilot."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

from brain_researcher.services.agent.planner.catalog_loader import get_capability_index
from brain_researcher.services.tools.catalog_loader import (
    load_exposed_tools,
    load_orchestration_workflows,
    load_workflow_catalog_ids,
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "eval" / "tool_selection_capability_pilot.py"
SPEC = importlib.util.spec_from_file_location("tool_selection_capability_pilot", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
pilot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pilot)

CAPABILITY_PILOT_DIR = ROOT / "benchmarks" / "tool_routing_validation" / "capability_pilot"
BASE_CAPABILITY_TASKS = CAPABILITY_PILOT_DIR / "microtooling_capability_pilot.v1.jsonl"
WORKFLOW_FAMILY_TASKS = CAPABILITY_PILOT_DIR / "microtooling_workflow_family_routing.v1.jsonl"
WORKFLOW_REMAINDER_TASKS = (
    CAPABILITY_PILOT_DIR / "microtooling_workflow_remainder_routing.v1.jsonl"
)
EXPOSED_ATOMIC_TASKS = CAPABILITY_PILOT_DIR / "microtooling_exposed_atomic_routing.v1.jsonl"
CAPABILITY_TASK_FILES = (
    BASE_CAPABILITY_TASKS,
    WORKFLOW_FAMILY_TASKS,
    WORKFLOW_REMAINDER_TASKS,
    EXPOSED_ATOMIC_TASKS,
)
WORKFLOW_TASK_FILES = (
    WORKFLOW_FAMILY_TASKS,
    WORKFLOW_REMAINDER_TASKS,
)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def _pilot_task(task_id: str) -> dict[str, Any]:
    tasks_path = BASE_CAPABILITY_TASKS
    for line in tasks_path.read_text(encoding="utf-8").splitlines():
        task = json.loads(line)
        if task["task_id"] == task_id:
            return task
    raise AssertionError(f"Missing pilot task {task_id}")


def _score(task_id: str, actions: list[dict[str, Any]]) -> dict[str, Any]:
    return pilot.score_task(
        _pilot_task(task_id),
        actions,
        condition="unit",
        max_actions=3,
    )


def test_scorer_repair_data_001_requires_validation_recipe_params() -> None:
    validation_recipe = {
        "index": 1,
        "action_type": "recipe_tool",
        "target": "list_dataset_assets",
        "confidence": 0.95,
        "raw": {
            "input": {
                "tool_id": "list_dataset_assets",
                "params": {"validate_bids": True},
            }
        },
    }
    discovery_only = {
        "index": 1,
        "action_type": "mcp_tool",
        "target": "dataset_get_resources",
        "confidence": 0.95,
    }

    positive = _score("DATA-001", [validation_recipe])
    negative = _score("DATA-001", [discovery_only])

    assert "bids_validation" in positive["capabilities_covered"]
    assert "dataset_access" in negative["capabilities_covered"]
    assert "bids_validation" in negative["missing_capabilities"]


def test_scorer_repair_stat_001_task_glm_workflow_covers_stack() -> None:
    row = _score(
        "STAT-001",
        [
            {
                "index": 1,
                "action_type": "recipe_tool",
                "target": "workflow_task_glm_group",
                "confidence": 0.95,
            }
        ],
    )

    assert row["capabilities_covered"] == [
        "contrast_estimation",
        "first_level_glm",
        "hrf_modeling",
    ]
    assert row["correct"] is True


def test_scorer_repair_statinf_001_permutation_correction_is_specific() -> None:
    corrected = _score(
        "STATINF-001",
        [
            {
                "index": 1,
                "action_type": "bash_cmd",
                "target": "randomise -i input_4d.nii.gz -o out -d design.mat -t design.con -n 10000 -T",
                "confidence": 0.85,
            }
        ],
    )
    uncorrected = _score(
        "STATINF-001",
        [
            {
                "index": 1,
                "action_type": "bash_cmd",
                "target": "randomise -i input_4d.nii.gz -o out -d design.mat -t design.con -n 10000",
                "confidence": 0.85,
            }
        ],
    )

    assert corrected["capabilities_covered"] == [
        "multiple_comparison_control",
        "permutation_inference",
    ]
    assert "permutation_inference" in uncorrected["capabilities_covered"]
    assert "multiple_comparison_control" in uncorrected["missing_capabilities"]


def test_scorer_repair_qc_001_reports_require_real_mriqc_route() -> None:
    report = _score(
        "QC-001",
        [
            {
                "index": 1,
                "action_type": "bash_cmd",
                "target": "mriqc /data/haxby_bids /out/mriqc group -m bold T1w",
                "confidence": 0.85,
            }
        ],
    )
    import_probe = _score(
        "QC-001",
        [
            {
                "index": 1,
                "action_type": "bash_cmd",
                "target": "python -c 'import mriqc'",
                "confidence": 0.85,
            },
            {
                "index": 2,
                "budget_group": 1,
                "action_type": "py_import",
                "target": "mriqc",
                "confidence": 0.9,
                "raw": {"command": "python -c 'import mriqc'"},
            },
        ],
    )

    assert report["capabilities_covered"] == [
        "image_quality_metrics",
        "qc_reporting",
    ]
    assert import_probe["capabilities_covered"] == []


def test_scorer_repair_prep_001_surface_credit_requires_surface_signal() -> None:
    surface = _score(
        "PREP-001",
        [
            {
                "index": 1,
                "action_type": "bash_cmd",
                "target": "fmriprep /data /out participant --fs-license-file /license.txt --output-spaces T1w fsaverage",
                "confidence": 0.85,
            }
        ],
    )
    preprocessing_only = _score(
        "PREP-001",
        [
            {
                "index": 1,
                "action_type": "bash_cmd",
                "target": "fmriprep /data /out participant --output-spaces T1w",
                "confidence": 0.85,
            }
        ],
    )

    assert surface["capabilities_covered"] == [
        "fmri_preprocessing",
        "surface_reconstruction",
    ]
    assert "fmri_preprocessing" in preprocessing_only["capabilities_covered"]
    assert "surface_reconstruction" in preprocessing_only["missing_capabilities"]


def test_scorer_repair_harm_001_does_not_credit_diagnostics_from_combat_only() -> None:
    row = _score(
        "HARM-001",
        [
            {
                "index": 1,
                "action_type": "py_call",
                "target": "harmonizationLearn",
                "confidence": 0.8,
            }
        ],
    )

    assert row["capabilities_covered"] == ["site_harmonization"]
    assert "site_effect_diagnostics" in row["missing_capabilities"]


def test_scorer_repair_conn_001_keeps_confound_cleaning_separate() -> None:
    with_confounds = _score(
        "CONN-001",
        [
            {
                "index": 1,
                "action_type": "bash_cmd",
                "target": "python - <<'PY'\nmasker = NiftiMapsMasker(atlas, standardize=True)\ntime_series = masker.fit_transform(img, confounds=confounds)\nConnectivityMeasure(kind='correlation').fit_transform([time_series])\nPY",
                "confidence": 0.85,
            },
            {
                "index": 2,
                "budget_group": 1,
                "action_type": "py_call",
                "target": "NiftiMapsMasker",
                "confidence": 0.8,
            },
            {
                "index": 3,
                "budget_group": 1,
                "action_type": "py_call",
                "target": "ConnectivityMeasure",
                "confidence": 0.8,
            },
        ],
    )
    without_confounds = _score(
        "CONN-001",
        [
            {
                "index": 1,
                "action_type": "py_call",
                "target": "NiftiMapsMasker",
                "confidence": 0.8,
            },
            {
                "index": 2,
                "action_type": "py_call",
                "target": "ConnectivityMeasure",
                "confidence": 0.8,
            },
        ],
    )

    assert with_confounds["capabilities_covered"] == [
        "atlas_timeseries_extraction",
        "confound_cleaning",
        "connectivity_extraction",
    ]
    assert "atlas_timeseries_extraction" in without_confounds["capabilities_covered"]
    assert "connectivity_extraction" in without_confounds["capabilities_covered"]
    assert "confound_cleaning" in without_confounds["missing_capabilities"]


def test_parse_plan_tools_and_python_actions() -> None:
    events = [
        {
            "type": "item.completed",
            "item": {
                "type": "agent_message",
                "text": json.dumps(
                    {
                        "predictions": [
                            {
                                "task_id": "DATA-001",
                                "top_tool_ids": [
                                    "openneuro.get_dataset",
                                    "validate_bids_structure",
                                ],
                            }
                        ]
                    }
                ),
            },
        },
        {
            "type": "tool_call",
            "task_id": "ML-001",
            "name": "shell",
            "arguments": {
                "cmd": (
                    "python - <<'PY'\n"
                    "from sklearn.model_selection import GroupKFold\n"
                    "GroupKFold(n_splits=5)\n"
                    "PY"
                )
            },
        },
    ]

    actions = pilot.parse_events(events)
    triples = {(a["action_type"], a["target"], a["task_id"]) for a in actions}

    assert ("plan_tool", "openneuro.get_dataset", "DATA-001") in triples
    assert ("plan_tool", "validate_bids_structure", "DATA-001") in triples
    assert ("bash_cmd", actions[2]["target"], "ML-001") in triples
    assert ("py_import", "sklearn.model_selection", "ML-001") in triples
    assert ("py_import", "sklearn.model_selection.GroupKFold", "ML-001") in triples
    assert ("py_call", "GroupKFold", "ML-001") in triples
    assert ("py_call", "sklearn.model_selection.GroupKFold", "ML-001") not in triples


def test_parse_provider_markdown_shell_code_fence_as_route_action() -> None:
    command = (
        "qsiprep data/bids-dataset data/derivatives participant \\\n"
        "  --participant-label 01 \\\n"
        "  --pepolar-method TOPUP \\\n"
        "  --eddy-config /path/to/eddy_params.json"
    )
    events = [
        {
            "type": "text",
            "part": {
                "type": "text",
                "text": (
                    "Use QSIPrep for this route.\n\n"
                    "```bash\n"
                    f"{command}\n"
                    "```"
                ),
            },
        }
    ]

    actions = pilot.parse_events(events)
    assert [
        {
            key: actions[0].get(key)
            for key in ("action_type", "target", "source", "confidence")
        }
    ] == [
        {
            "action_type": "bash_cmd",
            "target": command,
            "source": "agent_message.code_fence.shell",
            "confidence": 0.8,
        }
    ]


def test_parse_get_execution_recipe_emits_recipe_tool_action() -> None:
    events = [
        {
            "type": "mcp_tool_call",
            "tool": "get_execution_recipe",
            "arguments": {
                "tool_id": "mriqc",
                "params": {"dataset": "Haxby", "mode": "routing_only"},
            },
        }
    ]

    actions = pilot.parse_events(events)
    triples = {(a["action_type"], a["target"], a["source"]) for a in actions}

    assert ("mcp_tool", "get_execution_recipe", "mcp_tool_call") in triples
    assert (
        "recipe_tool",
        "mriqc",
        "mcp_tool_call.arguments.tool_id",
    ) in triples


def test_parse_br_cli_get_execution_recipe_emits_recipe_tool_action() -> None:
    command = "/bin/bash -lc 'br get_execution_recipe --tool-id workflow_qsiprep'"
    mention = "/bin/bash -lc \"printf '%s\\n' 'get_execution_recipe(tool_id=workflow_qsirecon)'\""
    events = [
        {"type": "command_execution", "command": command},
        {"type": "command_execution", "command": mention},
    ]

    actions = pilot.parse_events(events)
    triples = {(a["action_type"], a["target"], a["source"]) for a in actions}

    assert ("bash_cmd", command, "command_execution.command") in triples
    assert (
        "recipe_tool",
        "workflow_qsiprep",
        "shell_command.br_get_execution_recipe.tool_id",
    ) in triples
    assert (
        "recipe_tool",
        "workflow_qsirecon",
        "shell_command.br_get_execution_recipe.tool_id",
    ) not in triples


def test_parse_opencode_tool_use_events() -> None:
    events = [
        {
            "type": "tool_use",
            "part": {
                "type": "tool",
                "tool": "bash",
                "state": {
                    "input": {
                        "command": (
                            "python - <<'PY'\n"
                            "from nilearn.glm.first_level import FirstLevelModel\n"
                            "PY"
                        )
                    }
                },
            },
        },
        {
            "type": "tool_use",
            "part": {
                "type": "tool",
                "tool": "brain-researcher-local_get_execution_recipe",
                "state": {
                    "input": {
                        "tool_id": "mriqc",
                        "target_runtime": "neurodesk",
                    }
                },
            },
        },
    ]

    actions = pilot.parse_events(events)
    triples = {(a["action_type"], a["target"], a["source"]) for a in actions}

    assert ("bash_cmd", actions[0]["target"], "tool_use.command") in triples
    assert ("py_import", "nilearn.glm.first_level", "python_ast.import_from") in triples
    assert ("mcp_tool", "get_execution_recipe", "tool_use") in triples
    assert ("recipe_tool", "mriqc", "tool_use.arguments.tool_id") in triples


def test_parse_codex_bash_lc_escaped_heredoc_python_actions() -> None:
    command = (
        "/bin/bash -lc \"python - <<'PY'\n"
        "from nilearn import datasets\n"
        "from nilearn.maskers import NiftiMapsMasker\n"
        "from nilearn.connectome import ConnectivityMeasure\n"
        "route = {\\\"time_series_extractor\\\": NiftiMapsMasker.__name__}\n"
        "print(route)\n"
        "PY\""
    )
    events = [
        {
            "type": "command_execution",
            "command": command,
        }
    ]

    actions = pilot.parse_events(events)
    triples = {(a["action_type"], a["target"], a["source"]) for a in actions}

    assert ("bash_cmd", command, "command_execution.command") in triples
    assert ("py_import", "nilearn", "python_ast.import_from") in triples
    assert ("py_import", "nilearn.maskers.NiftiMapsMasker", "python_ast.import_from") in triples
    assert (
        "py_import",
        "nilearn.connectome.ConnectivityMeasure",
        "python_ast.import_from",
    ) in triples


def test_score_task_uses_capability_coverage_and_traps() -> None:
    task = {
        "task_id": "T1",
        "query": "demo",
        "required_capabilities": ["grouped_cv", "model_fit"],
        "canonical_br_tools": ["br_grouped_cv_tool"],
        "acceptable_patterns": [
            {
                "capability": "grouped_cv",
                "action_type": "py_import",
                "pattern": "sklearn.model_selection.GroupKFold",
                "match": "exact",
            },
            {
                "capability": "model_fit",
                "action_type": "py_import",
                "pattern": "sklearn.linear_model",
                "match": "contains",
            },
        ],
        "disqualifying_patterns": [
            {
                "trap_id": "non_grouped_cv",
                "action_type": "py_import",
                "pattern": "sklearn.model_selection.KFold",
                "match": "exact",
            }
        ],
    }
    correct_actions = [
        {
            "index": 1,
            "action_type": "py_import",
            "target": "sklearn.model_selection.GroupKFold",
            "task_id": None,
            "source": "test",
            "confidence": 0.9,
        },
        {
            "index": 2,
            "action_type": "py_import",
            "target": "sklearn.linear_model",
            "task_id": None,
            "source": "test",
            "confidence": 0.9,
        },
    ]
    trap_actions = [
        {
            "index": 1,
            "action_type": "py_import",
            "target": "sklearn.model_selection.KFold",
            "task_id": None,
            "source": "test",
            "confidence": 0.9,
        },
        correct_actions[1],
    ]

    correct = pilot.score_task(task, correct_actions, condition="without_br", max_actions=3)
    trapped = pilot.score_task(task, trap_actions, condition="without_br", max_actions=3)

    assert correct["correct"] is True
    assert correct["n_required_capabilities"] == 2
    assert correct["n_capabilities_covered"] == 2
    assert correct["capability_score"] == 1.0
    assert correct["capabilities_covered"] == ["grouped_cv", "model_fit"]
    assert trapped["correct"] is False
    assert trapped["n_capabilities_covered"] == 1
    assert trapped["capability_score"] == 0.5
    assert trapped["trap_fall"] is True
    assert trapped["trap_hits"][0]["trap_id"] == "non_grouped_cv"


def test_score_task_neutralizes_probe_and_keeps_partial_credit() -> None:
    task = {
        "task_id": "DATA-001",
        "query": "Fetch and validate BIDS structure",
        "required_capabilities": ["dataset_access", "bids_validation"],
        "canonical_br_tools": ["openneuro.get_dataset", "validate_bids_structure"],
        "acceptable_patterns": [
            {
                "capability": "dataset_access",
                "action_type": "mcp_tool",
                "pattern": "dataset_get_resources",
                "match": "exact",
            },
            {
                "capability": "bids_validation",
                "action_type": "bash_cmd",
                "pattern": "bids-validator",
                "match": "contains",
            },
        ],
        "disqualifying_patterns": [],
    }
    actions = [
        {
            "index": 1,
            "action_type": "mcp_tool",
            "target": "tool_search",
            "task_id": None,
            "source": "test",
            "confidence": 0.95,
        },
        {
            "index": 2,
            "action_type": "mcp_tool",
            "target": "dataset_get_resources",
            "task_id": None,
            "source": "test",
            "confidence": 0.95,
        },
        {
            "index": 3,
            "action_type": "bash_cmd",
            "target": (
                "python - <<'PY'\n"
                "import importlib.util, shutil\n"
                "print(importlib.util.find_spec('bids'))\n"
                "print(shutil.which('bids-validator'))\n"
                "PY"
            ),
            "task_id": None,
            "source": "test",
            "confidence": 0.85,
        },
    ]

    scored = pilot.score_task(task, actions, condition="with_br", max_actions=3)

    assert scored["correct"] is False
    assert scored["capabilities_covered"] == ["dataset_access"]
    assert scored["missing_capabilities"] == ["bids_validation"]
    assert scored["capability_score"] == 0.5
    assert [item["target"] for item in scored["neutral_actions"]] == [
        "tool_search",
        actions[2]["target"],
    ]


def test_score_task_credits_recipe_tool_without_charging_wrapper_budget() -> None:
    task = {
        "task_id": "QC-001",
        "query": "Run MRIQC and reports",
        "required_capabilities": ["image_quality_metrics", "qc_reporting"],
        "canonical_br_tools": ["mriqc"],
        "acceptable_patterns": [
            {
                "capability": "image_quality_metrics",
                "action_type": "recipe_tool",
                "pattern": "mriqc",
                "match": "exact",
            },
            {
                "capability": "qc_reporting",
                "action_type": "recipe_tool",
                "pattern": "mriqc",
                "match": "exact",
            },
        ],
        "disqualifying_patterns": [],
    }
    actions = [
        {
            "index": 1,
            "action_type": "mcp_tool",
            "target": "get_execution_recipe",
            "task_id": None,
            "source": "test",
            "confidence": 0.95,
        },
        {
            "index": 2,
            "action_type": "recipe_tool",
            "target": "mriqc",
            "task_id": None,
            "source": "test.arguments.tool_id",
            "confidence": 0.95,
        },
    ]

    scored = pilot.score_task(task, actions, condition="with_br", max_actions=1)

    assert scored["correct"] is True
    assert scored["ungated_capability_score"] == 1.0
    assert scored["capability_score"] == 1.0
    assert scored["canonical_tool_hit"] is True
    assert scored["n_selected_non_neutral_actions"] == 1
    assert [item["target"] for item in scored["neutral_actions"]] == [
        "get_execution_recipe",
    ]


def test_strict_codex_with_br_requires_direct_plan_and_route() -> None:
    task = {
        "task_id": "WF-X",
        "query": "Select QSIPrep workflow",
        "required_capabilities": ["dwi_preprocessing"],
        "canonical_br_tools": ["workflow_qsiprep"],
        "acceptable_patterns": [
            {
                "capability": "dwi_preprocessing",
                "action_type": "recipe_tool",
                "pattern": "workflow_qsiprep",
                "match": "exact",
            }
        ],
        "disqualifying_patterns": [],
    }
    direct_actions = [
        {
            "index": 1,
            "action_type": "mcp_tool",
            "target": "plan_preflight",
            "source": "function_call",
            "raw": {"arguments": {"query": "WF-X DWI preprocessing", "selection_mode": True}},
            "confidence": 0.95,
        },
        {
            "index": 2,
            "action_type": "mcp_tool",
            "target": "get_execution_recipe",
            "source": "function_call",
            "raw": {"arguments": {"tool_id": "workflow_qsiprep"}},
            "confidence": 0.95,
        },
        {
            "index": 3,
            "budget_group": 2,
            "action_type": "recipe_tool",
            "target": "workflow_qsiprep",
            "source": "function_call.arguments.tool_id",
            "raw": {"arguments": {"tool_id": "workflow_qsiprep"}},
            "confidence": 0.95,
        },
    ]

    scored = pilot.score_task(
        task,
        direct_actions,
        condition="codex_cli_gpt55_with_br",
        max_actions=1,
    )

    assert scored["correct"] is True
    assert scored["br_contract_mode"] == "strict_direct_br_v1"
    assert scored["br_usage_ok"] is True
    assert scored["br_usage_failures"] == []
    assert scored["canonical_tool_hit"] is True
    assert scored["used_canonical_routing_path"] is True


def test_strict_codex_with_br_rejects_local_recipe_wrapper() -> None:
    task = {
        "task_id": "WF-X",
        "query": "Select QSIPrep workflow",
        "required_capabilities": ["dwi_preprocessing"],
        "canonical_br_tools": ["workflow_qsiprep"],
        "acceptable_patterns": [
            {
                "capability": "dwi_preprocessing",
                "action_type": "recipe_tool",
                "pattern": "workflow_qsiprep",
                "match": "exact",
            }
        ],
        "disqualifying_patterns": [],
    }
    wrapper_actions = [
        {
            "index": 1,
            "action_type": "bash_cmd",
            "target": "python - <<'PY'\nget_execution_recipe(tool_id='workflow_qsiprep')\nPY",
            "source": "command_execution.command",
            "confidence": 0.85,
        },
        {
            "index": 2,
            "budget_group": 1,
            "action_type": "recipe_tool",
            "target": "workflow_qsiprep",
            "source": "python_ast.call.keyword.tool_id",
            "confidence": 0.95,
        },
    ]

    scored = pilot.score_task(
        task,
        wrapper_actions,
        condition="codex_cli_gpt55_with_br",
        max_actions=1,
    )

    assert scored["ungated_capability_score"] == 1.0
    assert scored["capability_score"] == 0.0
    assert scored["correct"] is False
    assert scored["br_usage_ok"] is False
    assert "missing_direct_plan_preflight" in scored["br_usage_failures"]
    assert "missing_direct_concrete_br_route_after_plan_preflight" in scored["br_usage_failures"]
    assert scored["canonical_tool_hit"] is False
    assert scored["used_canonical_routing_path"] is False


def test_strict_codex_with_br_requires_selection_mode_true() -> None:
    task = {
        "task_id": "WF-X",
        "query": "Select QSIPrep workflow",
        "required_capabilities": ["dwi_preprocessing"],
        "canonical_br_tools": ["workflow_qsiprep"],
        "acceptable_patterns": [
            {
                "capability": "dwi_preprocessing",
                "action_type": "recipe_tool",
                "pattern": "workflow_qsiprep",
                "match": "exact",
            }
        ],
        "disqualifying_patterns": [],
    }
    actions = [
        {
            "index": 1,
            "action_type": "mcp_tool",
            "target": "plan_preflight",
            "source": "function_call",
            "raw": {"arguments": {"query": "WF-X DWI preprocessing"}},
            "confidence": 0.95,
        },
        {
            "index": 2,
            "action_type": "mcp_tool",
            "target": "get_execution_recipe",
            "source": "function_call",
            "raw": {"arguments": {"tool_id": "workflow_qsiprep"}},
            "confidence": 0.95,
        },
        {
            "index": 3,
            "budget_group": 2,
            "action_type": "recipe_tool",
            "target": "workflow_qsiprep",
            "source": "function_call.arguments.tool_id",
            "confidence": 0.95,
        },
    ]

    scored = pilot.score_task(
        task,
        actions,
        condition="codex_cli_gpt55_with_br",
        max_actions=1,
    )

    assert scored["correct"] is False
    assert scored["br_usage_ok"] is False
    assert scored["br_usage_failures"] == ["plan_preflight_missing_selection_mode_true"]


def test_pilot_aliases_credit_br_workflow_recipe_ids() -> None:
    cases = [
        ("PREP-001", "workflow_fmriprep_preprocessing", 1.0),
        ("QC-001", "workflow_mriqc", 1.0),
        ("QC-001", "workflow_preprocessing_qc", 1.0),
        ("HARM-001", "workflow_data_harmonization", 1.0),
    ]

    for task_id, recipe_tool_id, expected_score in cases:
        scored = pilot.score_task(
            _pilot_task(task_id),
            [
                {
                    "index": 1,
                    "action_type": "mcp_tool",
                    "target": "get_execution_recipe",
                    "task_id": None,
                    "source": "test",
                    "confidence": 0.95,
                },
                {
                    "index": 2,
                    "action_type": "recipe_tool",
                    "target": recipe_tool_id,
                    "task_id": None,
                    "source": "test.arguments.tool_id",
                    "confidence": 0.95,
                },
            ],
            condition="with_br",
            max_actions=1,
        )

        assert scored["capability_score"] == expected_score
        assert scored["missing_capabilities"] == []


def test_score_task_requires_invocation_not_search_or_version_mention() -> None:
    task = {
        "task_id": "DATA-001",
        "query": "Fetch and validate BIDS structure",
        "required_capabilities": ["dataset_access", "bids_validation"],
        "canonical_br_tools": [],
        "acceptable_patterns": [
            {
                "capability": "dataset_access",
                "action_type": "bash_cmd",
                "pattern": r"nilearn\.datasets\.fetch_|fetch_haxby",
                "match": "regex",
            },
            {
                "capability": "bids_validation",
                "action_type": "bash_cmd",
                "pattern": "bids-validator",
                "match": "contains",
            },
        ],
        "disqualifying_patterns": [],
    }
    actions = [
        {
            "index": 1,
            "action_type": "bash_cmd",
            "target": "rg -n \"bids-validator|fetch_haxby\" src tests docs",
            "task_id": None,
            "source": "test",
            "confidence": 0.85,
        },
        {
            "index": 2,
            "action_type": "bash_cmd",
            "target": "bids-validator --version",
            "task_id": None,
            "source": "test",
            "confidence": 0.85,
        },
    ]

    scored = pilot.score_task(task, actions, condition="without_br", max_actions=3)

    assert scored["correct"] is False
    assert scored["capability_score"] == 0.0
    assert scored["capabilities_covered"] == []
    assert scored["n_selected_non_neutral_actions"] == 0
    assert [item["target"] for item in scored["neutral_actions"]] == [
        actions[0]["target"],
        actions[1]["target"],
    ]


def test_score_task_uses_non_neutral_budget_and_routing_paths() -> None:
    task = {
        "task_id": "DATA-001",
        "query": "Fetch and validate BIDS structure",
        "required_capabilities": ["dataset_access", "bids_validation"],
        "canonical_br_tools": ["validate_bids_structure"],
        "acceptable_patterns": [
            {
                "capability": "dataset_access",
                "action_type": "mcp_tool",
                "pattern": "dataset_get_resources",
                "match": "exact",
            },
            {
                "capability": "bids_validation",
                "action_type": "bash_cmd",
                "pattern": "bids-validator",
                "match": "contains",
            },
        ],
        "canonical_routing_paths": [
            {
                "path_id": "br_tool_search_to_dataset_resources",
                "patterns": [
                    {
                        "action_type": "mcp_tool",
                        "pattern": "tool_search",
                        "match": "exact",
                    },
                    {
                        "action_type": "mcp_tool",
                        "pattern": "dataset_get_resources",
                        "match": "exact",
                    },
                ],
            }
        ],
        "disqualifying_patterns": [],
    }
    actions = [
        {
            "index": 1,
            "action_type": "mcp_tool",
            "target": "tool_search",
            "task_id": None,
            "source": "test",
            "confidence": 0.95,
        },
        {
            "index": 2,
            "action_type": "mcp_tool",
            "target": "dataset_get_resources",
            "task_id": None,
            "source": "test",
            "confidence": 0.95,
        },
        {
            "index": 3,
            "action_type": "bash_cmd",
            "target": "python -c \"import shutil; print(shutil.which('bids-validator'))\"",
            "task_id": None,
            "source": "test",
            "confidence": 0.85,
        },
        {
            "index": 4,
            "action_type": "bash_cmd",
            "target": "bids-validator /tmp/haxby",
            "task_id": None,
            "source": "test",
            "confidence": 0.85,
        },
    ]

    scored = pilot.score_task(task, actions, condition="with_br", max_actions=2)

    assert scored["correct"] is True
    assert scored["capability_score"] == 1.0
    assert scored["action_budget_unit"] == "non_neutral_actions"
    assert scored["n_selected_non_neutral_actions"] == 2
    assert [action["target"] for action in scored["selected_actions"]] == [
        "tool_search",
        "dataset_get_resources",
        actions[2]["target"],
        "bids-validator /tmp/haxby",
    ]
    assert scored["first_task_relevant_action_index"] == 1
    assert scored["canonical_routing_path_applicable"] is True
    assert scored["used_canonical_routing_path"] is True
    assert scored["canonical_routing_path_hits"][0]["path_id"] == (
        "br_tool_search_to_dataset_resources"
    )


def test_execution_handoff_v1_passes_parameterized_dataset_handoff() -> None:
    scored = _score(
        "DATA-001",
        [
            {
                "index": 1,
                "action_type": "mcp_tool",
                "target": "dataset_get_resources",
                "confidence": 0.95,
                "raw": {"arguments": {"dataset_ref": "haxby"}},
            },
            {
                "index": 2,
                "action_type": "recipe_tool",
                "target": "list_dataset_assets",
                "confidence": 0.95,
                "raw": {
                    "input": {
                        "tool_id": "list_dataset_assets",
                        "params": {
                            "dataset_ref": "ds000105",
                            "validate_bids": True,
                            "use_pybids_layout": True,
                        },
                    }
                },
            },
        ],
    )

    assert scored["capability_score"] == 1.0
    assert scored["execution_handoff_contract"] == "execution_handoff_v1"
    assert scored["execution_handoff_ok"] is True
    assert scored["execution_handoff_score"] == 1.0
    assert scored["execution_handoff_failures"] == []


def test_execution_handoff_v1_rejects_routing_only_empty_recipe_params() -> None:
    scored = _score(
        "STAT-001",
        [
            {
                "index": 1,
                "action_type": "recipe_tool",
                "target": "workflow_task_glm_group",
                "confidence": 0.95,
                "raw": {
                    "input": {
                        "tool_id": "workflow_task_glm_group",
                        "params": {
                            "mode": "routing_only",
                            "task": "Fit first-level GLM on Haxby task data",
                            "no_download": True,
                            "no_heavy_execution": True,
                        },
                    }
                },
            }
        ],
    )

    assert scored["correct"] is True
    assert scored["execution_handoff_ok"] is False
    assert "recipe_params_populated" in scored["execution_handoff_failures"]
    assert "dataset_binding" in scored["execution_handoff_failures"]


def test_execution_handoff_v1_rejects_wrong_dataset_and_query_contradiction() -> None:
    scored = _score(
        "PREP-001",
        [
            {
                "index": 1,
                "action_type": "recipe_tool",
                "target": "workflow_fmriprep_preprocessing",
                "confidence": 0.95,
                "raw": {
                    "input": {
                        "tool_id": "workflow_fmriprep_preprocessing",
                        "params": {
                            "bids_dir": "/data/openneuro/ds000114/bids",
                            "output_dir": "/tmp/fmriprep",
                            "participant_label": "01",
                            "extra_args": "--fs-no-reconall",
                        },
                    }
                },
            }
        ],
    )

    assert scored["capability_score"] == 1.0
    assert scored["execution_handoff_ok"] is False
    assert "dataset_not_mismatched" in scored["execution_handoff_failures"]
    assert "no_query_contradiction" in scored["execution_handoff_failures"]


def test_trace_oracle_v1_labels_terminal_connectivity_without_upstream_calls() -> None:
    scored = _score(
        "CONN-001",
        [
            {
                "index": 1,
                "action_type": "recipe_tool",
                "target": "nilearn_connectivity_matrix",
                "confidence": 0.95,
                "raw": {
                    "input": {
                        "tool_id": "nilearn_connectivity_matrix",
                        "params": {
                            "mode": "routing_only",
                            "task": "Compute ADHD MSDL connectivity",
                        },
                    }
                },
            }
        ],
    )

    assert scored["trace_oracle_contract"] == "trace_oracle_v1"
    assert scored["trace_required_call_coverage"] < 1.0
    assert "dataset_resolution" in scored["trace_required_calls_missing"]
    assert "atlas_resolution" in scored["trace_required_calls_missing"]
    assert "CRITICAL_NEXT_CALL_SKIPPED" in scored["failure_mode_labels"]
    assert "DATASET_NOT_RESOLVED" in scored["failure_mode_labels"]
    assert "RECIPE_ONLY_NO_PARAMS" in scored["failure_mode_labels"]
    assert "TERMINAL_TOOL_BEFORE_UPSTREAM" in scored["failure_mode_labels"]


def test_trace_oracle_v1_labels_meta_analysis_before_study_search() -> None:
    scored = _score(
        "META-001",
        [
            {
                "index": 1,
                "action_type": "recipe_tool",
                "target": "coordinate_meta_analysis",
                "confidence": 0.95,
                "raw": {
                    "input": {
                        "tool_id": "coordinate_meta_analysis",
                        "params": {"coordinates": "coords.tsv", "output_dir": "/tmp/out"},
                    }
                },
            }
        ],
    )

    assert "study_search" in scored["trace_required_calls_missing"]
    assert "coordinate_meta_analysis" in scored["trace_required_calls_hit"]
    assert "CRITICAL_NEXT_CALL_SKIPPED" in scored["failure_mode_labels"]
    assert "TERMINAL_TOOL_BEFORE_UPSTREAM" in scored["failure_mode_labels"]


def test_trace_oracle_v1_labels_unknown_tool_without_fallback_and_duplicates() -> None:
    scored = _score(
        "ML-001",
        [
            {
                "index": 1,
                "action_type": "mcp_tool",
                "target": "get_execution_recipe",
                "confidence": 0.95,
                "raw": {
                    "arguments": {"tool_id": "nilearn_decoding"},
                    "error": "unknown_tool",
                },
            },
            {
                "index": 2,
                "action_type": "mcp_tool",
                "target": "get_execution_recipe",
                "confidence": 0.95,
                "raw": {
                    "arguments": {"tool_id": "nilearn_decoding"},
                    "error": "unknown_tool",
                },
            },
        ],
    )

    assert scored["duplicate_route_call_count"] == 1
    assert "UNKNOWN_TOOL_NO_FALLBACK" in scored["failure_mode_labels"]
    assert "DUPLICATE_TOOL_CALLS" in scored["failure_mode_labels"]


def test_parser_validation_fixture_passes() -> None:
    summary = pilot.validate_parser(CAPABILITY_PILOT_DIR / "parser_validation_traces.v1.jsonl")

    assert summary["fixture_count"] == 28
    assert summary["all_fixtures_passed"] is True
    assert summary["precision"] >= 0.95
    assert summary["recall"] >= 0.95


def test_pilot_plan_tool_ids_are_catalog_backed() -> None:
    catalog_tool_ids = set(get_capability_index().by_id)
    workflow_ids = set(load_orchestration_workflows()) | set(load_workflow_catalog_ids())
    exposed_tool_ids = set(load_exposed_tools(agent_visible_only=False))
    missing: list[tuple[str, str, str]] = []
    for tasks_path in CAPABILITY_TASK_FILES:
        for line in tasks_path.read_text(encoding="utf-8").splitlines():
            task = json.loads(line)
            task_id = task["task_id"]
            for tool_id in task.get("canonical_br_tools", []):
                if (
                    tool_id not in catalog_tool_ids
                    and tool_id not in workflow_ids
                    and tool_id not in exposed_tool_ids
                ):
                    missing.append((task_id, "canonical_br_tools", tool_id))
            patterns = task.get("acceptable_patterns", []) + task.get("disqualifying_patterns", [])
            for pattern in patterns:
                if pattern.get("action_type") != "plan_tool" or pattern.get("match") != "exact":
                    continue
                tool_id = pattern.get("pattern")
                if tool_id not in catalog_tool_ids and tool_id not in exposed_tool_ids:
                    missing.append((task_id, "plan_tool_pattern", tool_id))

    assert missing == []


def test_workflow_family_routing_tasks_cover_30_to_50_workflows() -> None:
    tasks = pilot.load_tasks(WORKFLOW_FAMILY_TASKS)
    workflow_ids = set(load_orchestration_workflows()) | set(load_workflow_catalog_ids())
    task_ids = {task["task_id"] for task in tasks}

    assert 30 <= len(tasks) <= 50
    assert len(task_ids) == len(tasks)
    for task in tasks:
        canonical_workflows = [
            tool_id
            for tool_id in task.get("canonical_br_tools", [])
            if str(tool_id).startswith("workflow_")
        ]
        assert canonical_workflows, task["task_id"]
        assert set(canonical_workflows) <= workflow_ids
        assert task.get("route_hints"), task["task_id"]


def test_workflow_remainder_routing_tasks_cover_remaining_15_workflows() -> None:
    tasks = pilot.load_tasks(WORKFLOW_REMAINDER_TASKS)
    workflow_ids = set(load_orchestration_workflows()) | set(load_workflow_catalog_ids())
    canonical = {
        tool_id
        for task in tasks
        for tool_id in task.get("canonical_br_tools", [])
        if str(tool_id).startswith("workflow_")
    }

    assert len(tasks) == 15
    assert len(canonical) == 15
    assert canonical <= workflow_ids
    assert all(task.get("route_hints") for task in tasks)


def test_workflow_routing_task_files_cover_all_declared_workflows() -> None:
    workflow_ids = set(load_orchestration_workflows()) | set(load_workflow_catalog_ids())
    covered: set[str] = set()
    for tasks_path in CAPABILITY_TASK_FILES:
        for task in pilot.load_tasks(tasks_path):
            covered.update(
                tool_id
                for tool_id in task.get("canonical_br_tools", [])
                if str(tool_id).startswith("workflow_")
            )
            for key in ("acceptable_patterns", "disqualifying_patterns"):
                for pattern in task.get(key, []):
                    if (
                        pattern.get("action_type") == "recipe_tool"
                        and pattern.get("match") == "exact"
                        and str(pattern.get("pattern", "")).startswith("workflow_")
                    ):
                        covered.add(str(pattern["pattern"]))

    assert workflow_ids - covered == set()


def test_workflow_family_recipe_routes_score_and_mark_canonical_path() -> None:
    for tasks_path in WORKFLOW_TASK_FILES:
        for task in pilot.load_tasks(tasks_path):
            workflow_id = next(
                tool_id
                for tool_id in task.get("canonical_br_tools", [])
                if str(tool_id).startswith("workflow_")
            )
            scored = pilot.score_task(
                task,
                [
                    {
                        "index": 1,
                        "action_type": "mcp_tool",
                        "target": "get_execution_recipe",
                        "task_id": None,
                        "source": "test",
                        "confidence": 0.95,
                    },
                    {
                        "index": 2,
                        "action_type": "recipe_tool",
                        "target": workflow_id,
                        "task_id": None,
                        "source": "test.arguments.tool_id",
                        "confidence": 0.95,
                    },
                ],
                condition="with_br",
                max_actions=1,
            )

            assert scored["correct"] is True, task["task_id"]
            assert scored["capability_score"] == 1.0, task["task_id"]
            assert scored["canonical_tool_hit"] is True, task["task_id"]
            assert scored["used_canonical_routing_path"] is True, task["task_id"]


def test_exposed_atomic_routing_tasks_cover_priority_families() -> None:
    tasks = pilot.load_tasks(EXPOSED_ATOMIC_TASKS)
    exposed_tool_ids = set(load_exposed_tools(agent_visible_only=False))
    categories = {task["category"] for task in tasks}

    assert 20 <= len(tasks) <= 30
    assert {
        "Exposed Atomic - Dataset",
        "Exposed Atomic - NiWrap/FSL",
        "Exposed Atomic - EEG/MEG",
        "Exposed Atomic - KG",
        "Exposed Atomic - MCP Utility",
        "Exposed Atomic - TaskBeacon",
    } <= categories
    for task in tasks:
        assert task.get("route_hints"), task["task_id"]
        assert set(task.get("canonical_br_tools", [])) <= exposed_tool_ids


def test_exposed_atomic_plan_routes_score() -> None:
    for task in pilot.load_tasks(EXPOSED_ATOMIC_TASKS):
        actions = [
            {
                "index": index,
                "action_type": "plan_tool",
                "target": tool_id,
                "task_id": None,
                "source": "test",
                "confidence": 1.0,
            }
            for index, tool_id in enumerate(task.get("canonical_br_tools", []), 1)
        ]

        scored = pilot.score_task(
            task,
            actions,
            condition="unit",
            max_actions=len(actions),
        )

        assert scored["correct"] is True, task["task_id"]
        assert scored["capability_score"] == 1.0, task["task_id"]


def test_exposed_atomic_bids_route_credits_br_service_import_selection() -> None:
    task = next(
        task
        for task in pilot.load_tasks(EXPOSED_ATOMIC_TASKS)
        if task["task_id"] == "ATOM-DATA-001"
    )
    actions = [
        {
            "index": 1,
            "budget_group": 1,
            "action_type": "bash_cmd",
            "target": (
                "python - <<'PY'\n"
                "from brain_researcher.services.tools.dataset import "
                "validate_bids, list_dataset_assets\n"
                "print(validate_bids.__name__, list_dataset_assets.__name__)\n"
                "PY"
            ),
            "task_id": None,
            "source": "test",
            "confidence": 0.85,
        },
        {
            "index": 2,
            "budget_group": 1,
            "action_type": "py_import",
            "target": "brain_researcher.services.tools.dataset.validate_bids",
            "task_id": None,
            "source": "python_ast.import_from",
            "confidence": 0.9,
        },
        {
            "index": 3,
            "budget_group": 1,
            "action_type": "py_import",
            "target": "brain_researcher.services.tools.dataset.list_dataset_assets",
            "task_id": None,
            "source": "python_ast.import_from",
            "confidence": 0.9,
        },
    ]

    scored = pilot.score_task(task, actions, condition="with_br", max_actions=1)

    assert scored["correct"] is True
    assert scored["capability_score"] == 1.0
    assert scored["capabilities_covered"] == [
        "bids_validation",
        "dataset_asset_listing",
    ]


def test_run_pilot_scores_condition_traces(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.jsonl"
    trace = tmp_path / "trace.jsonl"
    fixtures = (
        ROOT
        / "benchmarks"
        / "tool_routing_validation"
        / "capability_pilot"
        / "parser_validation_traces.v1.jsonl"
    )
    _write_jsonl(
        tasks,
        [
            {
                "task_id": "DATA-001",
                "query": "Fetch and validate BIDS structure",
                "required_capabilities": ["dataset_access", "bids_validation"],
                "canonical_br_tools": ["openneuro.get_dataset", "validate_bids_structure"],
                "acceptable_patterns": [
                    {
                        "capability": "dataset_access",
                        "action_type": "plan_tool",
                        "pattern": "openneuro.get_dataset",
                        "match": "exact",
                    },
                    {
                        "capability": "bids_validation",
                        "action_type": "plan_tool",
                        "pattern": "validate_bids_structure",
                        "match": "exact",
                    },
                ],
                "disqualifying_patterns": [],
            }
        ],
    )
    _write_jsonl(
        trace,
        [
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": json.dumps(
                        {
                            "predictions": [
                                {
                                    "task_id": "DATA-001",
                                    "top_tool_ids": [
                                        "openneuro.get_dataset",
                                        "validate_bids_structure",
                                    ],
                                }
                            ]
                        }
                    ),
                },
            }
        ],
    )

    payload = pilot.run_pilot(
        tasks_path=tasks,
        condition_traces=[("demo", trace)],
        parser_fixtures=fixtures,
        max_actions_values=[3],
    )

    summary = payload["summary_by_max_actions"]["3"]["demo"]
    assert summary["n_tasks"] == 1
    assert summary["tool_selection_accuracy"] == 1.0
    assert summary["mean_capability_score"] == 1.0
    assert summary["mean_capabilities_covered"] == 2.0
    assert summary["canonical_routing_path_applicable_count"] == 0
    assert summary["canonical_routing_path_rate"] is None
    assert summary["trap_fall_rate"] == 0.0
    assert payload["scale_readiness"]["parser_gate_passed"] is True
