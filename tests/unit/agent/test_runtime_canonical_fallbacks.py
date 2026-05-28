from brain_researcher.services.agent.error_taxonomy import (
    ErrorTaxonomyCategory,
    ErrorTaxonomyResult,
    RecoveryAction,
)
from brain_researcher.services.agent.recovery_policy import select_recovery_decision
from brain_researcher.services.agent.tool_qc import _apply_retry_rules
from brain_researcher.services.tools.spec import ToolQCSpec, ToolQCRetryRule


def test_qc_retry_rules_canonicalize_fallback_tool_ids():
    qc_spec = ToolQCSpec(
        enabled=True,
        retry_rules=[
            ToolQCRetryRule(
                match_any_failure_modes=["misalignment"],
                fallback_tool="fsl.bet.run",
            )
        ],
    )

    decision = _apply_retry_rules(
        qc_spec=qc_spec,
        parameters={},
        failure_modes=["misalignment"],
        attempt_index=0,
    )

    assert decision is not None
    assert decision.fallback_tool == "fsl_bet"


def test_recovery_policy_canonicalizes_metadata_fallback_tool_ids():
    taxonomy = ErrorTaxonomyResult(
        category=ErrorTaxonomyCategory.TOOL,
        is_retryable=False,
        recovery_action=RecoveryAction.TOOL_SUBSTITUTE,
    )

    decision = select_recovery_decision(
        taxonomy=taxonomy,
        tool_id="primary_tool",
        step_metadata={
            "fallback_tool": "python.searchlight_fmri.run",
            "fallback_tools": ["cat12"],
        },
        step_idx=1,
    )

    assert decision.fallback_tools == ["searchlight_analysis", "spm12_vbm"]
