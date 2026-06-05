# Benchmark Scope

The tool-routing benchmark corpus is not shipped in this public repository.
It includes manually curated task labels, audit notes, and internal validation
fixtures that are maintained in the private Brain Researcher repository.

Public code in this repository can run the evaluation harnesses, but not the
private 440-row task corpus itself.

## Current Label-Curation Status

As of private Brain Researcher commit
`07a3a50a86c5ab7c50966aea7ba9bca53ebd7b32` (`chore(eval): accept task27
routing label backfill (#273)`), the internal `microtooling_exact_labels`
benchmark has completed the obvious label hygiene pass and the six
human-approved Task #27 runtime-label accepts.

That private change is a benchmark-label update only:

- no production routing code changed;
- no runtime, deployment, or MCP contract changed;
- invalid catalog-backed labels are at 0 in the curated internal corpus;
- Task #27 accepted labels are reported as `labels_corrected`, not
  `retrieval_improved`;
- the cleanup is reported separately from routing-model improvements.

## Internal Validation Snapshot

The post-curation internal A/B snapshot used the same 440-row corpus, `limit=5`,
and `k=1,3,5`.

| Mode | R@1 | R@3 | R@5 |
|---|---:|---:|---:|
| legacy | 0.6136 | 0.7023 | 0.7364 |
| family cards | 0.8386 | 0.8477 | 0.8523 |

The family-card routing delta remains the routing result to track. Label
curation is treated as denominator hygiene, not as production behavior.
In this snapshot, the same-run family-cards-vs-legacy routing delta is
`+0.2250` R@1 on the cleaned internal labels. The six Task #27 label accepts
account for `labels_corrected` movement of `+0.0068` legacy R@1 and `+0.0136`
family-cards R@1 relative to the previous cleaned-label snapshot.

## Reproducibility Boundary

External users can inspect and run the public harness code under
`scripts/eval/` and `tests/eval/`, but the exact table above is not
reproducible from this repository alone because the benchmark corpus is not
published here.
