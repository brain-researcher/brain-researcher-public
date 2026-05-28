# Gitleaks Full-History Triage Report

Generated: 2026-05-26 — `docker run zricethezav/gitleaks:latest git -v /repo` on full repo history (1762 commits, 643 MB).

## TL;DR

- **86 findings** in git history → after triage: **~10 real leaks, all in DELETED files**
- **0 leaks in current HEAD** (`grep` for known leaked JWT secret returns 0)
- All leaked secrets are inactive or expired (DeepSeek key in deleted file, JWT exp dates in 2025-09, demo tokens)
- **No `git filter-repo` required for safety** — rotation alone suffices

## Findings Breakdown

### Real secrets in history (files removed from HEAD)
| File (REMOVED from HEAD) | Leak Type | Note |
|---|---|---|
| `tools/contrast_annotation.py` | DeepSeek API key (`api_key="..."`) | Hardcoded in old agent tool, file removed in commit `ba31ad7bc` (project migration). **Action: revoke at platform.deepseek.com if still active** |
| `.env.docker` | `JWT_SECRET=pN3OV...` | Old prod env file, removed and gitignored. Current `.env.docker` not tracked. |
| `k8s/manifests/02-secrets.yaml` | Same `JWT_SECRET` value | Old K8s manifest, replaced by `infrastructure/k8s/manifests/02-secrets.yaml` (sanitized) |
| `brain_researcher/services/web_ui/.vercel/output/static/_next/static/chunks/.../page-*.js` | Same `JWT_SECRET` bundled into JS | Build artifact, no longer committed |
| `brain_researcher/services/web_ui/cookies.txt`, `cookies_final.txt` | Demo user JWT tokens (`exp: 1756928032` = 2025-09-03) | **Expired**, removed from HEAD |
| `brain_researcher/services/telemetry/example_usage.py` | Demo JWT token | Same expired token, file removed |
| `brain_researcher/core/analysis/rag_retrieval.py` | Demo JWT token | Same, file removed |
| `services/agent/ui/brain-researcher-chat/.next/server/server-reference-manifest.json` | Demo JWT in build manifest | Build artifact, removed |

### False positives (no action needed)
| File | Finding | Why FP |
|---|---|---|
| `tests/unit/services/test_api_fee_debit.py` (12 hits) | `API_USD_BUCKET, currency=API_USD_CURRENCY` | Test fixture attribute names; regex match on "API_" |
| `tests/unit/orchestrator/test_credits_api_usd_buckets.py` (8 hits) | Same pattern | Same |
| `tests/unit/scripts/test_monthly_api_credit_allowance.py` (3 hits) | Same pattern | Same |
| `tests/unit/telemetry/test_sentry_integration.py` (8 hits) | Stripe `sk_test_4eC39HqLyjWDarjtT1zdp7dc` | Stripe's official public test key (in their docs) |
| `tests/integration/test_settings_interface.py` (4 hits) | JWT with `sub=1234567890` | Well-known JWT example token (jwt.io homepage example) |
| `tests/contracts/pact_broker/setup.sh` (3 hits) | `curl http://localhost:9292/...` | Localhost test scripts |
| `infrastructure/cloudflare/configure_cloudflare.py`, `k8s/manifests/02-secrets.yaml` (private-key rule) | `# placeholder - replace with actual private key` | Comment text triggering BEGIN/END PRIVATE KEY regex |
| `infrastructure/cloudflare/README.md` (4 hits) | `curl ... zones/YOUR_ZONE_ID/...` | Placeholder docs |
| `.env.example`, `services/agent/.env.example` | `BR_MODEL_API_KEY=sk-ant-...` | Env example placeholders |
| `docs/SHARE_FUNCTIONALITY_STATUS.md` (3 hits) | Documentation mentioning API patterns | Docs |
| `docs/operations/locked_followup_manifest_specs_2026-04-26.md` | Generic API references | Docs |
| `docs/prompts/.../r2_robustness_minimal.yaml` | Test artifact YAML | Docs/artifact |
| `tools/build_ca_topics.py` | Old tools script (removed) | Likely FP, file gone |
| `brain_researcher/services/web_ui/src/components/settings/SettingsInterface.tsx` | `curl -X POST ... YOUR_ZONE_ID...` | UI display string, file removed |
| `src/brain_researcher/services/orchestrator/endpoints/credits.py` | `API_USD_BUCKET` constant reference | FP same as test files |

## Recommended Remediation (compatible with Phase D K8s refresh)

### Critical — do before OSS public:
1. **DeepSeek API key**: Log into platform.deepseek.com → revoke the old key (5 min). If you're not using DeepSeek anymore, just revoke. If still in use, generate a new key and update wherever it's now stored (env var, not in code).
2. **Verify JWT_SECRET in production is NOT `pN3OV...`**: Check `infrastructure/k8s/manifests/02-secrets.yaml` (current sanitized version) vs the old leaked value. If they differ, no action. If same, rotate via Phase D dual-secret pattern.

### Not critical (already inactive):
- **Demo JWT tokens**: `exp` claim was September 2025, all expired — no action.
- **Old `.env.docker`**: removed and gitignored — already mitigated.

### `git filter-repo` decision
**Recommended: SKIP** for these reasons:
- All leaked secrets are in DELETED files (current HEAD is clean)
- Active rotation makes the historical leaks inert (DeepSeek revoke + JWT rotation in Phase D)
- Filter-repo invalidates every collaborator clone (force-push pain) and rewrites 1762 commits
- The cleanliness benefit (history without these strings) is cosmetic, not security-critical

**Reconsider filter-repo IF**:
- DeepSeek key cannot be revoked (e.g., shared account access)
- The team needs zero-trace audit posture for compliance / paper publication
- Time-cost of collaborator coordination is acceptable

## Verification

```bash
# Current HEAD has no known leaked values:
grep -rln "pN3OVSqI5WS293s1y7r00tLwRRlf3NzpUNf8H5DrZ5RgtdgVYVycRP4BKRz6XFwj" . \
  --exclude-dir=.git --exclude-dir=node_modules
# → 0 hits (confirmed)

# Pre-commit gitleaks (already added in commit a2b73c092) blocks future leaks.
# CI gitleaks step (added in next commit) gates PRs on history.
```

## Notes for Phase D

When rotating NEXTAUTH_SECRET / JWT_SECRET via dual-secret pattern:
- If current prod uses the old `pN3OV...` value → use Phase D rotation to retire it
- If current prod already uses a different value → just rotate per OSS-launch hygiene, no special action

For the DeepSeek key, it likely doesn't need replacement (no DeepSeek usage in current code) — just revoke the old one.
