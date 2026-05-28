# BR-KG Graph Substrate And Claim Spine Execution Plan

As of March 10, 2026.

This document operationalizes two linked workstreams:

- `Workstream A`: graph construction before graph learning
- `Workstream B`: claim-centric spine

The sequencing rule is strict:

- `Workstream A` gates any future graph-learning or relation-as-operator work.
- `Workstream B` runs in parallel because its schema and verifier path already exist.
- A later `relation-as-operator` phase starts only after both `graph_snapshot_v1` and `claim_snapshot_v1` are stable.

## Repo Anchors

- Graph state and gaps: `docs/standards/neurokg_graph_schema.md`
- Canonical node/edge status: `configs/neurokg/config.yml`
- Claim/provenance schemas: `src/brain_researcher/services/neurokg/schemas/node_schemas.py`
- Claim/provenance edge schemas: `src/brain_researcher/services/neurokg/schemas/edge_schemas.py`
- Bounded claim ingest path: `docs/neurokg/gabriel_sample_quickstart.md`
- Claim-first verifier contract: `docs/specs/kg_verify_hypothesis_spec.md`

## Owner Roles

- `PI`: direction owner and final go/no-go authority
- `GE`: graph ETL and schema engineer
- `GQ`: graph QA, metrics, and benchmark owner
- `CE`: claim extraction and provenance engineer
- `VE`: verification and evaluation owner
- `RA`: review and adjudication analyst

## Suggested Stream Staffing

### Workstream A: Graph Substrate

- 1 graph/ETL owner to run rebuild/resume flows and core integration scripts
- 1 ontology/atlas owner to maintain `BrainRegion` hierarchy and `Atlas` metadata
- 1 literature/semantic integration owner for `MEASURES`, study-concept links, and `CITES`
- 1 QA/reliability owner to own `--analyze` coverage checks, logs, and phase-gate signoff

### Workstream B: Claim Spine

- 1 schema/ingest owner for `Claim`, `EvidenceSpan`, and `MeasurementRun`
- 1 LLM extraction/provenance owner for `llm_extract` and `llm_codify`
- 1 query-service owner for `kg_verify_hypothesis`
- 1 curation/ops owner to run the low-confidence `review_queue.jsonl` loop

## 12-Week Execution Table

| Week | Workstream A: Graph Substrate | Workstream B: Claim Spine | Owners | Artifacts | Go / No-Go Check |
|---|---|---|---|---|---|
| 1 | Reconcile `config`, docs, and current DB state. Publish one node/edge truth table. | Define the bounded GABRIEL benchmark scope, hypothesis set, and review queue policy. | `PI, GE, GQ, CE, VE` | `graph_contract_v1.md`, `claim_benchmark_charter.md`, source-of-truth matrix | `Go` only if all status conflicts are explicit and assigned. |
| 2 | Freeze graph coverage scoreboard and baseline path metrics; mark `HAS_COORDINATE` as live literature backbone; freeze `A1` vs `A2` gate split. | Freeze claim coverage scoreboard and baseline verifier outputs on the sample path; confirm low-confidence records route to the review queue rather than entering the graph. | `GQ, VE, GE, CE` | `graph_baseline_report.md`, `claim_baseline_report.md`, frozen eval seeds, `resume_rebuild_runbook.md` | `No-Go` if either baseline is not reproducible from a clean run. |
| 3 | Lock `BrainRegion` as canonical public spatial/anatomy node; validate `Atlas` metadata needed for hierarchy work. | Wire high-confidence GABRIEL ingest into `Claim`, `EvidenceSpan`, and `MeasurementRun`. | `GE, GQ, CE` | integrity report, contract diff memo, ingest logs | `Go` only if canonical node/edge labels are explicit and claim nodes are materialized. |
| 4 | Freeze `StatsMap -> IN_REGION -> BrainRegion` as canonical spatial substrate and measure orphan publication/coordinate rates. | Materialize `MENTIONS`, `MENTIONS_REGION`, `REPORTS_CLAIM`, `SUPPORTS`, and `GENERATED` for the bounded sample. | `GE, CE, GQ` | edge count report, orphan analysis, claim-edge report | `No-Go` if the canonical spatial substrate still cannot be measured cleanly. |
| 5 | Materialize canonical `BrainRegion -> PART_OF -> BrainRegion`; validate `A1` and `A2` typed paths separately. | Run claim-first vs mention-fallback verification on a small held-out slice. | `GE, GQ, VE` | spatial path audit, verifier comparison report | `Go` only if `A1` is queryable and claim-first is operational. |
| 6 | Materialize `MEASURES` and first-pass `CITES`; keep `ACTIVATES` as tracked nonblocking enrichment; freeze `graph_snapshot_v1`. | Calibrate provenance completeness, evidence quality, and verdict auditability; freeze `claim_snapshot_alpha`. | `GE, GQ, CE, VE, PI` | `graph_snapshot_v1`, typed edge report, `claim_snapshot_alpha`, auditability memo | `Gate A`: graph can continue only if `A1` passes and `A2` is either passed or isolated as the only remaining blocker; `Workstream B` can continue only if the auditable claim-first path is live. |
| 7 | Backfill residual blocked graph components, document unresolved waivers, and rerun typed path QA. | Expand held-out hypothesis set and collect reviewed positives/negatives. | `GE, GQ, RA, VE` | waiver list, typed path regression report, reviewed eval set | `No-Go` if unresolved graph gaps still block core paths or the eval set is too noisy. |
| 8 | Stabilize graph coverage dashboards and freeze post-backfill counts. | Run the formal `claim-first` benchmark against mention fallback. | `GQ, VE, PI` | coverage dashboard, verdict metrics, evidence retrieval metrics | `Gate B`: claim-first must beat or materially out-audit mention fallback on the bounded benchmark. |
| 9 | Define graph-readiness probes for later operator modeling. | Design cross-paper claim canonicalization or clustering strategy. | `GQ, CE, VE` | readiness probe spec, claim canonicalization ADR | `Go` only if claim aggregation strategy is explicit and testable. |
| 10 | Run joint stress tests on graph traversal, typed connectivity, and snapshot reproducibility. | Prototype cross-paper claim clustering and adjudicate failure modes. | `GQ, CE, VE, RA` | stress-test report, clustering eval, failure taxonomy | `No-Go` if claim support/conflict aggregation is still dominated by paper-local fragmentation. |
| 11 | Freeze `graph_snapshot_v1_1` and define downstream operator-learning tasks. | Freeze `claim_snapshot_v1` and define downstream claim-centric reasoning tasks. | `PI, GQ, VE` | task charter, train/dev/test split proposal, snapshot manifests | `Go` only if both snapshots are versioned and benchmark-ready. |
| 12 | Hold the joint readiness review for graph learning and typed operator work. | Hold the joint readiness review for claim-centric reasoning and later idea-mining use. | `PI, GE, GQ, CE, VE, RA` | `readiness_review.md`, `go_no_go_memo.md`, next-quarter roadmap | `Final Gate`: relation-as-operator work starts only if both workstreams pass. |

## RACI Matrix

| Deliverable | PI | GE | GQ | CE | VE | RA |
|---|---|---|---|---|---|---|
| Graph contract and status matrix | A | R | R | C | C | I |
| Graph coverage scoreboard | C | R | A | I | C | I |
| BrainRegion/Atlas hierarchy | I | A | R | I | I | I |
| Backbone edge materialization | I | A | R | C | I | I |
| Graph snapshots and typed path QA | C | R | A | I | C | I |
| GABRIEL claim ingest | I | I | I | A | R | I |
| Claim-edge materialization | I | I | I | A | R | I |
| Claim-first verifier benchmark | C | I | I | R | A | C |
| Provenance and auditability review | I | I | I | R | A | C |
| Claim adjudication set | I | I | I | C | R | A |
| Joint readiness review | A | R | R | R | R | C |

Legend:

- `R`: responsible
- `A`: accountable
- `C`: consulted
- `I`: informed

## Artifact Checklist

- `graph_contract_v1.md`
- `claim_benchmark_charter.md`
- `graph_baseline_report.md`
- `claim_baseline_report.md`
- `graph_snapshot_v1`
- `claim_snapshot_alpha`
- `coverage_dashboard.md`
- `typed_path_regression_report.md`
- `claim_first_vs_mention_report.md`
- `claim_canonicalization_adr.md`
- `graph_snapshot_v1_1`
- `claim_snapshot_v1`
- `readiness_review.md`
- `go_no_go_memo.md`

## Hard Gates

### Gate A1: Spatial Backbone

Pass only if all of the following are true:

- `HAS_COORDINATE` is materialized at meaningful scale.
- `StatsMap -> IN_REGION -> BrainRegion` produces stable canonical spatial paths.
- `MEASURES` and first-pass `CITES` are either live or explicitly waived with written rationale.
- Config, docs, and snapshot counts are aligned.
- Total edge count clears the minimum structural floor for a learnable substrate.

### Gate A2: Anatomy Hierarchy

Pass only if all of the following are true:

- `BrainRegion -> PART_OF -> BrainRegion` produces stable canonical anatomy hierarchy paths.
- the two-hop canonical path
  `StatsMap -> IN_REGION -> BrainRegion -> PART_OF -> BrainRegion` is queryable.

Operational gate shape:

- `A1 spatial backbone`: `HAS_COORDINATE`, canonical `IN_REGION`, `MEASURES`, `CITES`
- `A2 anatomy hierarchy`: canonical `PART_OF`
- `ACTIVATES` is tracked but nonblocking in this revision

### Gate B: Claim-First Verification Readiness

Pass only if all of the following are true:

- `Claim`, `EvidenceSpan`, and `MeasurementRun` are populated from the bounded GABRIEL path.
- `MENTIONS`, `MENTIONS_REGION`, `REPORTS_CLAIM`, `SUPPORTS`, and `GENERATED` are queryable.
- Claim-first verification is measurably better than mention fallback on auditability and at least non-inferior on verdict quality.
- Provenance completeness and evidence-quality diagnostics are visible in the evaluation output.
- The auditable path `Publication -> REPORTS_CLAIM -> Claim <- SUPPORTS <- EvidenceSpan` plus `MeasurementRun -> GENERATED -> artifact` is live end to end.

### Final Gate: Joint Modeling Readiness

Pass only if all of the following are true:

- `graph_snapshot_v1_1` is frozen and reproducible.
- `claim_snapshot_v1` is frozen and reproducible.
- Task definitions for later operator modeling and claim-centric reasoning are frozen.
- Remaining waivers are explicit enough that future model gains can be interpreted.

## Primary Risks

- `Schema/documentation drift`: if config, docs, and snapshots disagree, every later benchmark will be misleading.
- `Backbone incompleteness`: if graph paths remain sparse, graph-learning work will fit ingestion artifacts rather than neuroscience structure.
- `Claim fragmentation`: if semantically equivalent claims remain paper-local, support/conflict aggregation will be noisy.
- `Benchmark leakage`: if held-out hypotheses or reviewed examples are not frozen early, later comparisons will not be credible.
- `Operator prematurity`: if relation-as-operator work starts before both gates pass, it will mostly measure substrate defects.

## Explicit No-Go Triggers

- End of Week 2: if the graph remains effectively node-heavy and edge-sparse, with core edge creation still missing and total edges still near the current baseline regime, do not start graph learning.
- End of Week 6: if the graph still cannot support an auditable claim-first path `Publication -> REPORTS_CLAIM -> Claim <- SUPPORTS <- EvidenceSpan` plus `MeasurementRun -> GENERATED -> artifact`, stop rollout of `Workstream B` and treat the claim layer as incomplete.

## Exit Condition

This execution plan is done when:

- `Workstream A` produces a stable typed graph substrate with frozen counts and typed path probes.
- `Workstream B` produces a stable claim-first evidence layer with bounded benchmark evidence.
- The program can make a clean, auditable go/no-go call on whether to start relation-as-operator work.
