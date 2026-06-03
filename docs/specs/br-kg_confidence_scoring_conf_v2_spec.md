# BR-KG Confidence Scoring (`conf_v2_conflict_uncertainty`) — Spec v1.1

Last updated: 2026-03-03

## 0. Summary

`conf_v2` extends query-time confidence scoring with explicit conflict and
uncertainty penalties. It is used in:

- `SearchOrchestrator` (orchestrated `/api/search`)
- `verify_hypothesis` (`kg_verify_hypothesis` MCP and service call)

`conf_v1` remains the writeback model for edge-level confidence governance.

## 1. Inputs

Per evidence item:

- `direction`: `support | conflict | uncertain | neutral`
- `strength`: scalar in `[0, 1]`
- `quality`: scalar in `[0, 1]`
- `source_reliability`: scalar in `[0, 1]`

Derived aggregates:

- `S`: support strength sum
- `C`: conflict strength sum
- `U`: uncertain strength sum
- `N`: number of evidence items

## 2. Features

```
contradiction_density = 2*min(S,C)/max(S+C, 1e-6)
uncertainty_density   = U/max(S+C+U, 1e-6)
quality_spread_norm   = min(1.0, pstdev(Q)/0.35)
source_var_norm       = min(1.0, pvariance(R)/0.08)
n_eff                 = n_support + n_conflict + 0.2*n_uncertain
coverage              = 1 - exp(-n_eff/6)
dominance             = abs(S-C)/max(S+C+0.75*U, 1e-6)
certainty_factor      = 1 - uncertainty_density
q_mean                = mean(Q)
```

## 3. Confidence Function

```
base    = (0.42*coverage + 0.28*dominance + 0.30*q_mean) * certainty_factor
penalty = clip01(1 - (0.72*contradiction_density
                      +0.72*uncertainty_density
                      +0.10*quality_spread_norm
                      +0.10*source_var_norm
                      +0.22*contradiction_density*uncertainty_density))
confidence_v2 = clip01(base * penalty^1.8)
```

## 4. Runtime Integration

### 4.1 Search Orchestrator

For each candidate:

```
final_score = base_score + alpha * evidence_norm * confidence_v2
```

When `include_score_breakdown=true`, return:

- `scoring_version`
- `confidence_multiplier`
- `contradiction_density`
- `uncertainty_density`
- `quality_spread_norm`
- `source_reliability_variance_norm`
- `penalty`

### 4.2 Hypothesis Verification

Top-level response includes:

- `confidence` (v2 unless explicitly set to `v1`)
- `confidence_signals` (full v2 components)
- `uncertain_evidence` bucket
- `summary.n_uncertain`

## 5. Compatibility

- API parameter: `confidence_scoring_version` with values `v1 | v2` (default `v2`)
- `v1` preserves legacy behavior for A/B comparison and rollback.
- No response schema changes are required for callers already consuming `v2`.

## 6. Issue #10 Benchmark Protocol and Gates

The benchmark script (`scripts/br-kg/issue10_confidence_benchmark.py`) now
reports both full-population and stratified-sample summaries and enforces gates
when `--enforce-thresholds` is enabled (default).

Coverage gates:

- `selected_conflict_cases >= 90% * target_conflict_cases`
- `selected_uncertainty_cases >= 90% * target_uncertainty_cases`
- `selected_baseline_cases >= 90% * target_baseline_cases`

Effectiveness gates:

- `median_delta_sampled_conflict_bucket <= -0.02`
- `median_delta_sampled_uncertainty_bucket <= 0.00`
- `median_confidence_v2_uncertain_only <= 0.02` (applies only when uncertain-only denominator > 0)
- `median_delta_sampled_baseline_bucket >= +0.05`

Stability gates:

- If high-confidence denominators are non-zero:
  `high_conf_precision_v2 >= high_conf_precision_v1 - 0.02`
- If top-decile denominator is non-zero:
  `top_decile_precision_v2 >= top_decile_precision_v1 - 0.02`

Independent eval gates (from frozen fixture slice):

- `independent_accuracy_v2 >= independent_accuracy_v1 - 0.02`
- `independent_non_supported_high_conf_rate_v2 <= max(0, independent_non_supported_high_conf_rate_v1 - 0.05)`
