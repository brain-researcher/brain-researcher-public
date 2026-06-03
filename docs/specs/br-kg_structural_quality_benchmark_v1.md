# BR-KG Structural Quality Benchmark v1

Last updated: 2026-03-23

## 0. Summary

This benchmark evaluates **how good BR-KG is as a graph substrate**, not just
whether a particular graph model performs well.

Primary question:

> Does BR-KG exhibit coherent, learnable, internally consistent structure that
> supports typed link completion and bridge discovery beyond trivial controls?

In this framing, `Node2Vec`, `GraphSAGE`, and other graph models are **diagnostic
probes**, not the benchmark objective. The main output is a **graph diagnostic
report**; probe-model comparison is supporting evidence.

---

## 1. Objectives

### Primary objective

Evaluate whether BR-KG is:

- structurally coherent
- learnable at the relation level
- sufficiently complete for downstream reasoning
- more informative than degree/type priors or text-only similarity alone

### Secondary objective

Measure whether graph-aware representations provide additional lift over
text-only and trivial-structure controls.

---

## 2. Non-Goals

- declaring a permanent “best GNN”
- benchmarking arbitrary GNN architectures for their own sake
- replacing the existing `text_v1` node embedding product spec
- directly evaluating free-form hypothesis generation quality

---

## 3. Benchmark Outputs

Each run MUST emit both of the following:

### A. Graph Diagnostic Report

Primary artifact describing graph quality:

- total node / edge counts
- per-node-type coverage
- per-edge-type coverage
- orphan rates
- degree skew statistics
- per-edge-type learnability
- control-adjusted consistency buckets
- overall `structure_consistency_score`

### B. Probe Model Comparison

Supporting artifact comparing a fixed set of probes on the same split:

- `type_prior`
- `degree_only`
- `text_cosine`
- `node2vec`
- `graphsage_text_v1` when supported for the chosen slice

### C. Fairness Audit Report

Optional-but-stable subgroup diagnostic artifact:

- subgroup coverage on audited node properties
- per-group edge-type metrics on the evaluation split
- control-adjusted subgroup margins
- underpowered-group detection
- disparity summaries across adequately powered groups

---

## 4. Scope

### Node types in scope for v1

- `Task`
- `TaskDef`
- `TaskSpec`
- `Concept`
- `Construct`
- `Tool`
- `ToolFamily`

### Optional phase-2 node types

- `Dataset`
- `Claim`
- `EvidenceSpan`
- `Publication`

### Edge types in scope for v1

The benchmark is relation-type aware. Example edge families:

- `MEASURES`
- `USES_TOOL`
- `BELONGS_TO_FAMILY`
- `REPORTS_CLAIM`
- `SUPPORTS`
- `ASSUMES`

The benchmark MUST report metrics per edge type, not only aggregate metrics.

---

## 5. Canonical Evaluation Tasks

### 5.1 Typed link prediction

Hold out positive edges for a given relation type and evaluate whether probe
models rank true edges above matched negatives.

This is the **primary v1 task**.

### 5.2 Similar-node rerank

Given a seed node and a candidate pool, evaluate whether graph-aware probes
rerank structurally related nodes above text-only baselines.

This is **phase 2** and is not required for the initial implementation.

---

## 6. Controls and Probe Models

### Required controls

- `type_prior`
- `degree_only`
- `text_cosine` when node features are available

These controls are necessary because “learnable” does not automatically mean
“high-quality graph”. The benchmark must distinguish real structure from:

- node degree effects
- ontology leakage
- type priors
- text redundancy

### Required graph probe

- `node2vec`

### Optional graph probe

- `graphsage_text_v1`

`GraphSAGE` is useful when a slice is small enough to train quickly and
`text_v1` node features are available. It is not required for every v1 run.

---

## 7. Data Contract

The benchmark runner consumes a normalized graph slice with:

- `nodes`
- `edges`
- `node_types`
- `node_features` (preferred: `text_v1`)

### Node contract

Each node must expose:

- stable node id
- node type
- optional dense feature vector
- optional node properties used for subgroup audits

### Edge contract

Each edge must expose:

- source node id
- target node id
- edge type

---

## 8. Split Strategy

Splits are **edge-level** and **stratified by edge type**.

For each edge type:

- split positives into train / val / test
- construct matched negatives
- prefer typed negatives:
  - same source type
  - same target type
  - edge absent from the graph

### Negative families

v1 tracks:

- `random_typed`
- `hard_typed`

Hard negatives should be chosen from non-edges that are difficult under a
simple heuristic such as:

- high text cosine
- high degree product

---

## 9. Metrics

### Primary metrics

- `AUROC`
- `Average Precision`
- `MRR`
- `Recall@10`
- `Recall@50`

### Diagnostic breakdowns

- per-edge-type metrics
- per-node-type orphan and degree stats
- control margin versus `type_prior` and `degree_only`

---

## 10. Diagnostic Readout

The benchmark must classify each edge type into a diagnostic bucket such as:

- `strong`
- `marginal`
- `weak_or_noisy`
- `underpowered`

Suggested interpretation:

- `strong`: learnable above controls with adequate support
- `marginal`: signal exists but is unstable or small
- `weak_or_noisy`: little lift above controls
- `underpowered`: insufficient positive support for a meaningful judgment

---

## 11. Structure Consistency Score

The benchmark should summarize graph quality with an overall
`structure_consistency_score` in `[0, 1]`.

This score must combine:

- relation-level learnability
- margin over trivial controls
- coverage adequacy

The summary score is a dashboard convenience only. The **per-edge-type report is
the canonical diagnostic view**.

---

## 12. Required Artifacts

Each benchmark run must write:

- `benchmark_manifest.json`
- `split_manifest.json`
- `graph_diagnostic_report.json`
- `fairness_audit_report.json`
- `probe_model_comparison.json`

Optional:

- `error_cases.jsonl`
- `similar_node_rerank_report.json`

---

## 13. Minimum Acceptance (v1)

The benchmark is v1-complete if it can:

1. ingest a normalized graph slice
2. produce stratified typed link-prediction splits
3. run control probes and at least one graph probe
4. emit a graph diagnostic report with per-edge-type learnability
5. compute a stable overall `structure_consistency_score`

---

## 14. Recommended First Use

Use this benchmark to answer:

- which edge types are coherent versus noisy
- whether graph structure adds lift beyond text-only similarity
- whether a candidate graph slice is mature enough for downstream bridge
  discovery or hypothesis tooling

This benchmark should be the primary evaluation layer for BR-KG graph quality.
Model comparison is a secondary readout.
