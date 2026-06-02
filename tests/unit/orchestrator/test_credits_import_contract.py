from __future__ import annotations


def test_orchestrator_credits_endpoint_reexports_shared_runtime_contract() -> None:
    from brain_researcher.services.orchestrator.endpoints import credits as endpoint
    from brain_researcher.services.shared import credits as shared

    for name in (
        "API_USD_BUCKET",
        "API_USD_CURRENCY",
        "WORKFLOW_RUNTIME_BUCKET",
        "WORKFLOW_RUNTIME_CURRENCY",
        "CreditsStore",
        "_from_milli_credits",
        "_get_store",
        "_to_milli_credits",
    ):
        assert getattr(endpoint, name) is getattr(shared, name)


def test_legacy_credits_endpoints_shim_keeps_public_runtime_exports() -> None:
    from brain_researcher.services.orchestrator import credits_endpoints as legacy
    from brain_researcher.services.orchestrator.endpoints import credits as endpoint

    for name in (
        "API_USD_BUCKET",
        "API_USD_CURRENCY",
        "WORKFLOW_RUNTIME_BUCKET",
        "WORKFLOW_RUNTIME_CURRENCY",
        "CreditsStore",
        "grant_initial_account_credits_for_account",
        "grant_initial_api_usd_credits_for_account",
        "grant_initial_workflow_credits_for_account",
        "router",
    ):
        assert getattr(legacy, name) is getattr(endpoint, name)
