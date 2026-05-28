from __future__ import annotations

import base64

from scripts.billing import authenticated_act_api_usd_smoke as smoke


def _config(**overrides):
    values = {
        "base_url": "https://brain-researcher.com/",
        "email": "smoke@example.org",
        "password": "secret",
        "username": "smoke_user",
        "signup": True,
        "workspace_id": "ws-1",
        "month": "2026-05",
        "allowance_milli": 10_000,
        "cap_milli": 10_000,
        "session_id": "sess-1",
        "budget_id": "budget-1",
        "query": "hello",
        "top_up_mode": "kubectl",
        "ledger_mode": "kubectl",
        "gcp_project": "project-1",
        "gcp_zone": "us-west1-b",
        "gcp_vm": "vm-1",
        "namespace": "brain-researcher-core",
        "orchestrator_target": "deployment/brain-researcher-orchestrator",
        "timeout_seconds": 180,
    }
    values.update(overrides)
    return smoke.SmokeConfig(**values)


def test_act_payload_uses_tool_mode_off_and_budget_id():
    payload = smoke.act_payload(_config(query="plain chat"))

    assert payload["query"] == "plain chat"
    assert payload["tool_mode"] == "off"
    assert payload["budget_id"] == "budget-1"
    assert payload["llm_budget_id"] == "budget-1"


def test_build_remote_python_command_uses_gcloud_kubectl_and_base64_code():
    cmd = smoke.build_remote_python_command(
        project="project-1",
        zone="us-west1-b",
        vm="vm-1",
        namespace="brain-researcher-core",
        target="deployment/brain-researcher-orchestrator",
        python_code="print('ok')",
    )

    assert cmd[:4] == ["gcloud", "compute", "ssh", "vm-1"]
    assert "--zone" in cmd
    assert "--project" in cmd
    command = cmd[cmd.index("--command") + 1]
    assert "sudo k3s kubectl -n brain-researcher-core exec" in command
    assert "deployment/brain-researcher-orchestrator" in command
    assert "print('ok')" not in command
    encoded = command.split("base64.b64decode('", 1)[1].split("')", 1)[0]
    assert base64.b64decode(encoded).decode() == "print('ok')"


def test_validate_smoke_accepts_managed_debit_and_committed_ledger():
    errors = smoke.validate_smoke(
        execution={
            "credential": "managed_gemini",
            "bill_to": "managed:budget-1",
        },
        api_fee_debit={"status": "debited", "amount_milli": 1},
        ledger={
            "account": {"balance_milli": 9999},
            "ledger": [
                {"event_type": "monthly_top_up", "amount_milli": 10000},
                {"event_type": "reserve", "amount_milli": -2},
                {"event_type": "commit", "amount_milli": 1},
            ],
            "reservations": [{"status": "committed"}],
        },
        allowance_milli=10_000,
    )

    assert errors == []


def test_validate_smoke_reports_missing_commit_and_response_debit():
    errors = smoke.validate_smoke(
        execution={"credential": "managed_gemini", "bill_to": "managed:budget-1"},
        api_fee_debit=None,
        ledger={
            "account": {"balance_milli": 10000},
            "ledger": [{"event_type": "reserve", "amount_milli": -2}],
            "reservations": [{"status": "reserved"}],
        },
        allowance_milli=10_000,
    )

    assert "response missing api_fee_debit" in errors
    assert "ledger missing commit event" in errors
    assert "ledger missing committed reservation" in errors
    assert "API-USD balance was not debited below allowance" in errors


def test_config_from_args_generates_workspace_and_normalizes_base_url():
    args = smoke.parse_args(
        [
            "--base-url",
            "https://example.org///",
            "--email",
            "smoke@example.org",
            "--password",
            "pw",
            "--username",
            "smoke_user",
            "--top-up-mode",
            "skip",
            "--ledger-mode",
            "skip",
        ]
    )
    config = smoke.config_from_args(args)

    assert config.base_url == "https://example.org/"
    assert config.workspace_id
    assert config.session_id.startswith("api-usd-smoke-")
    assert config.budget_id.startswith("api-usd-budget-")
    assert config.top_up_mode == "skip"
    assert config.ledger_mode == "skip"
