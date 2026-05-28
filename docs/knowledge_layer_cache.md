# Knowledge Layer Caching & Memory

This note summarizes how Track K+ knowledge caching works after the latest updates.

## Cache layers

- **L1 in-process cache** (EvidenceAggregator)
  - TTL: 300s (configurable), max 100 entries, simple oldest-first eviction.
  - Keyed by: `account_id | query | sources | limit | source_timeout`.

- **Shared Redis cache** (QueryCacheManager)
  - Reused existing agent Redis cache manager for cross-instance sharing.
  - Enabled when `use_shared_cache=True`; keyed the same as L1.
  - Tags with `account_id` for future invalidation.

- **Env/account id resolution**
  - From request ctx: `ctx['user_id']` or `ctx['account_id']` (preferred).
  - Else env: `ACCOUNT_ID` / `BRAIN_ACCOUNT_ID` / `USER_ID`.
  - Fallback: `test-account` (isolated sandbox bucket).

## Knowledge memory (per account)

- New `KnowledgeMemoryStore` (Redis if available, else in-process) keeps the most recent bundles per account (default 100).
- Automatically writes every EvidenceBundle gathered via `EvidenceAggregator` when a valid `account_id` is available.

## How to use

```python
from brain_researcher.services.agent.knowledge import EvidenceAggregator

agg = EvidenceAggregator(use_shared_cache=True, account_id="acct123")
bundle = await agg.gather_evidence("motor cortex connectivity", limit=10)
```

In chat, `ChatOrchestrator` now forwards `ctx['user_id']`/`ctx['account_id']` into the aggregator; no code change needed.

## Disable or tune

- Disable shared cache: `EvidenceAggregator(use_shared_cache=False)`.
- Disable all caching: `enable_cache=False`.
- Tune TTL/size: `cache_ttl_seconds`, `max_cache_size` parameters.

## Notes

- Shared cache uses Redis via `QueryCacheManager`; if Redis is unavailable, the system logs and falls back to L1 only.
- KnowledgeMemoryStore is best-effort; failures are logged and do not fail the request path.
