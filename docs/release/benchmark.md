# Benchmark Scope

The tool-routing benchmark corpus is not shipped in this public repository.
It includes manually curated task labels, audit notes, and internal validation
fixtures that are maintained in the private Brain Researcher repository.

Public code in this repository can run the evaluation harnesses, but not the
private 440-row task corpus itself.

## Current Label-Curation Status

As of private Brain Researcher commit
`8f5611b5d5309e80ce92ad926c0d22586a9e2f77` (`test(eval): narrow obvious
tier-c routing labels (#188)`), the internal `microtooling_exact_labels`
benchmark has completed the obvious Tier C-A curation pass.

That private change is a benchmark-label update only:

- no production routing code changed;
- no runtime, deployment, or MCP contract changed;
- invalid catalog-backed labels are at 0 in the curated internal corpus;
- the cleanup is reported separately from routing-model improvements.

## Internal Validation Snapshot

The post-curation internal A/B snapshot used the same 440-row corpus, `limit=5`,
and `k=1,3,5`.

| Mode | R@1 | R@3 | R@5 |
|---|---:|---:|---:|
| legacy | 0.2432 | 0.3364 | 0.3705 |
| family cards | 0.3205 | 0.4227 | 0.4386 |

The family-card routing delta remains the routing result to track. Label
curation is treated as denominator hygiene, not as production behavior.

## Reproducibility Boundary

External users can inspect and run the public harness code under
`scripts/eval/` and `tests/eval/`, but the exact table above is not
reproducible from this repository alone because the benchmark corpus is not
published here.
