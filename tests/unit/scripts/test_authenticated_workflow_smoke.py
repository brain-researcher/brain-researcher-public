from __future__ import annotations

import pytest

from scripts.smoke import authenticated_workflow_smoke as smoke


def _clear_smoke_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "BR_WORKFLOW_SMOKE_ALLOW_CREDIT_GRANT",
        "BR_WORKFLOW_SMOKE_GRANT_CREDIT",
        "BR_WORKFLOW_SMOKE_LAUNCH",
        "BR_WORKFLOW_SMOKE_REQUIRED_OUTPUTS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_config_defaults_to_preflight_only(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_smoke_env(monkeypatch)
    args = smoke.parse_args(
        [
            "--base-url",
            "https://example.org///",
            "--email",
            "smoke@example.org",
            "--password",
            "pw",
            "--run-tag",
            "run-1",
        ]
    )

    config = smoke.config_from_args(args)

    assert config.base_url == "https://example.org/"
    assert config.launch is False
    assert config.grant_credit is False
    assert config.required_outputs == smoke.DEFAULT_REQUIRED_OUTPUTS
    assert config.workflow_id == "workflow_rest_connectome_e2e"
    assert config.dataset_id == "ds000114"


def test_launch_env_flag_enables_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_smoke_env(monkeypatch)
    monkeypatch.setenv("BR_WORKFLOW_SMOKE_LAUNCH", "1")

    config = smoke.config_from_args(
        smoke.parse_args(["--email", "smoke@example.org", "--password", "pw"])
    )

    assert config.launch is True


def test_credit_grant_requires_explicit_allow_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_smoke_env(monkeypatch)

    args = smoke.parse_args(
        [
            "--email",
            "smoke@example.org",
            "--password",
            "pw",
            "--launch",
            "--grant-credit",
        ]
    )
    with pytest.raises(ValueError, match="BR_WORKFLOW_SMOKE_ALLOW_CREDIT_GRANT"):
        smoke.config_from_args(args)

    monkeypatch.setenv("BR_WORKFLOW_SMOKE_ALLOW_CREDIT_GRANT", "1")
    config = smoke.config_from_args(args)
    assert config.credit_grant_requested is True
    assert config.grant_credit is True


def test_credit_grant_request_is_ineffective_without_launch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_smoke_env(monkeypatch)
    monkeypatch.setenv("BR_WORKFLOW_SMOKE_ALLOW_CREDIT_GRANT", "1")

    config = smoke.config_from_args(
        smoke.parse_args(
            ["--email", "smoke@example.org", "--password", "pw", "--grant-credit"]
        )
    )

    assert config.launch is False
    assert config.credit_grant_requested is True
    assert config.grant_credit is False


def test_build_preflight_and_launch_payloads_use_workflow_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_smoke_env(monkeypatch)
    config = smoke.config_from_args(
        smoke.parse_args(
            [
                "--email",
                "smoke@example.org",
                "--password",
                "pw",
                "--run-tag",
                "run-1",
                "--img",
                "/data/sub-01_bold.nii.gz",
                "--output-dir",
                "outputs/smoke",
                "--atlas-path",
                "",
            ]
        )
    )

    preflight = smoke.build_preflight_payload(config)
    launch = smoke.build_launch_payload(config)

    assert preflight["strict"] is True
    assert preflight["params"]["img"] == "/data/sub-01_bold.nii.gz"
    assert preflight["params"]["output_dir"] == "outputs/smoke"
    assert "atlas_path" not in preflight["params"]
    assert launch["analysis_id"] == "dynamic_workflow"
    assert launch["pipeline_id"] == "workflow_rest_connectome_e2e"
    assert launch["template_id"] == "dynamic_workflow/workflow_rest_connectome_e2e"
    assert launch["thread"] == {"mode": "none"}
    assert launch["parameters"] == preflight["params"]


def test_required_outputs_match_analysis_detail_artifact_suffixes() -> None:
    detail = {
        "artifacts": [
            {
                "path": "workflow_outputs/workflow_rest_connectome_e2e/timeseries/timeseries.npy",
            },
            {
                "path": "workflow_outputs/workflow_rest_connectome_e2e/timeseries/timeseries.csv",
            },
            {
                "path": "workflow_outputs/workflow_rest_connectome_e2e/connectivity_matrix.npy",
            },
        ]
    }

    payload = smoke.assert_required_outputs(detail, smoke.DEFAULT_REQUIRED_OUTPUTS)

    assert payload["ok"] is True
    assert payload["missing"] == []
    assert "connectivity_matrix.npy" in payload["matches"]


def test_required_outputs_report_missing_artifacts() -> None:
    detail = {"artifacts": [{"path": "workflow_outputs/only_one.txt"}]}

    with pytest.raises(RuntimeError, match="missing required outputs"):
        smoke.assert_required_outputs(detail, smoke.DEFAULT_REQUIRED_OUTPUTS)
