# API Fee Credit Debit Integration

This repository now has a bounded helper for platform API-fee accounting:

- `brain_researcher.services.agent.api_fee_debit.record_usage_and_debit_platform_api_fee`
- input: `LLMRouteMetadata`, authenticated `workspace_id`/`user_id`, and a stable idempotency key or router `allocation_id`
- output: a typed result that reports `debited` or a precise skip reason

The helper records usage through `UsageTracker` when supplied and debits the isolated API-fee USD bucket (`api_fee_usd` / `usd`) through `CreditsStore.debit_bucket`. It only debits provider calls whose route metadata indicates platform-managed billing (`bill_to="managed"` / `managed:*` or a managed credential). BYOK and local OAuth usage is recorded but not debited.

## Integration Point

The safe integration point is the authenticated service layer immediately after an LLM call returns provider usage metadata:

```python
from brain_researcher.services.agent.api_fee_debit import (
    ApiFeeDebitIdentity,
    record_usage_and_debit_platform_api_fee,
)
from brain_researcher.services.agent.usage_aggregator import UsageTracker

result = record_usage_and_debit_platform_api_fee(
    router_result.metadata,
    identity=ApiFeeDebitIdentity(workspace_id=workspace_id, user_id=user_id),
    idempotency_key=f"llm-api-fee:{run_id}:{step_id}",
    usage_tracker=UsageTracker(),
)
```

Do not call it directly from `LLMRouter.route_chat` until the router contract carries authenticated wallet identity. The web `/chat` and `/act` service wrappers extract identity from authenticated request context and record API-fee debits against the same `api_fee_usd` bucket.

Hosted MCP uses the same account wallet when `BR_MCP_PLATFORM_API_FEE_REQUIRED=1` and `BR_CREDITS_DB` points at the shared credits SQLite database. MCP request auth sets a per-request wallet context from the API token or JWT subject, using JWT `tenant_id` / `workspace_id` when available and `default` otherwise. MCP LLM helpers route managed calls with a `mcp-api-usd:<workspace>:<user>` budget id, reserve before platform provider calls, and debit the isolated API-fee USD bucket. Local/BYOK MCP usage remains outside platform billing unless the hosted MCP billing gate is explicitly enabled.

Credit conversion defaults to `1 API-fee credit = 1 USD` and can be adjusted with `BR_PLATFORM_API_FEE_CREDITS_PER_USD`. Do not debit the legacy workflow-runtime credit balance for provider API fees.

API-fee mutation HTTP routes in the orchestrator are disabled by default with `BR_ENABLE_API_USD_MUTATION_API=0`. The web monthly top-up proxy is also disabled unless `BR_ENABLE_API_USD_MONTHLY_TOP_UP_PROXY=1` is set. The expected operational path for monthly allowance is the billing script/cron below; the web Settings surface reads `/api/credits/api-usd/balance` and the workflow credit ledger, and does not expose arbitrary credit mutations.

The legacy workflow credit grant proxy is disabled by default unless `BR_ENABLE_CREDITS_GRANT_PROXY=1` is set. Public credit proxy routes must derive `workspace_id` and `user_id` from verified authenticated claims when they are present; request query parameters, bodies, or headers are fallback-only for non-claim development paths.

Workflow-runtime credits are account scoped separately from API-fee USD credits. New credential and OAuth accounts receive idempotent initial grants in the `default` workspace for both workflow-runtime credits and API-fee USD credits. Set `BR_INITIAL_WORKFLOW_CREDITS=0` or `BR_INITIAL_API_USD_CREDITS=0` to disable either initial grant. Existing accounts can be backfilled with `scripts/billing/monthly_workflow_credit_allowance.py` and `scripts/billing/monthly_api_credit_allowance.py`, which top up active accounts to monthly caps without mixing buckets.

## Monthly Allowance Smoke Checks

Monthly API-fee allowance grants are handled by `scripts/billing/monthly_api_credit_allowance.py`. The script defaults to dry-run mode and only writes ledger entries when `--apply` is passed.

Local verification, without prod rollout or ledger writes:

```bash
pytest tests/unit/scripts/test_monthly_api_credit_allowance.py \
  tests/unit/scripts/test_monthly_workflow_credit_allowance.py \
  tests/unit/orchestrator/test_credits_account_scoping.py \
  tests/unit/orchestrator/test_credits_api_usd_buckets.py

cd apps/web-ui
npm test -- tests/unit/api/credits.routes.spec.ts src/lib/server/__tests__/credits.test.ts
```

Operational dry-run preview:

```bash
python scripts/billing/monthly_api_credit_allowance.py --month 2026-05
python scripts/billing/monthly_workflow_credit_allowance.py --month 2026-05
```

Use `--apply` only after reviewing the dry-run JSON. The dry-run summary should list each active account separately, report `dry_run: true`, and leave bucket balances unchanged.
