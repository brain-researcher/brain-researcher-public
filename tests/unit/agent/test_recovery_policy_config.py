from pathlib import Path

from brain_researcher.services.agent.error_taxonomy import (
    ErrorTaxonomyCategory,
    ErrorTaxonomyResult,
    RecoveryAction,
)
from brain_researcher.services.agent import recovery_policy


def test_recovery_policy_config_override(monkeypatch, tmp_path):
    cfg = tmp_path / "recovery_map.yaml"
    cfg.write_text(
        "\n".join(
            [
                "version: 1",
                "rules:",
                "  - category: infra",
                "    tool_family: container",
                "    allow_param_adjustment: false",
                "    allow_tool_substitute: true",
            ]
        )
    )
    monkeypatch.setenv("BR_RECOVERY_MAP_PATH", str(cfg))

    taxonomy = ErrorTaxonomyResult(
        category=ErrorTaxonomyCategory.INFRA,
        is_retryable=True,
        recovery_action=RecoveryAction.RETRY_BACKOFF,
    )
    policy = recovery_policy.policy_for_taxonomy(
        taxonomy, step_metadata={"tool_family": "container"}
    )

    assert policy.allow_param_adjustment is False
    assert policy.allow_tool_substitute is True
