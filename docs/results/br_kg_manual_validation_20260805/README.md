# BR-KG manual validation audit, 2026-08-05

This directory is the public-safe export of a completed post-hoc quality audit
of Brain Researcher KG records. It contains two independently sampled sets:
200 observed node instances and 200 observed directed-edge instances.

The export is **inspectable**, not a public rerun pack. It does not ship the
private KG, raw Neo4j identities, upstream payloads, internal run records, or
the original reviewer workspace. It also does not claim that an ETL repair,
reingestion, or production KG mutation occurred.

## Results

| Sampling unit | n | Pass | Fail | Unassessable | Adjudicated-fail fraction | Wilson 95% CI |
|---|---:|---:|---:|---:|---:|---:|
| Observed nodes | 200 | 118 | 70 | 12 | 35.0% | 28.7% to 41.8% |
| Observed directed edges | 200 | 162 | 29 | 9 | 14.5% | 10.3% to 20.0% |

Across the deliberately equal-sized 400-row audit set, 280 records passed, 99
failed, and 21 were unassessable. The resulting 24.75% descriptive
adjudicated-fail fraction is not a KG-wide overall defect rate because nodes
and edges were sampled as two separate strata with different population sizes.

`Unassessable` is a completed adjudication: the retained evidence was
insufficient for a defensible pass or fail. It does not mean pending review.
The reported fractions and Wilson intervals treat `fail` as the outcome and do
not resolve latent defect status for unassessable rows. As a sensitivity bound,
if every unassessable row were later confirmed defective, the corresponding
fractions would be 41.0% for nodes and 19.0% for directed edges.
The issue-class values `none` and `none_observed` are provenance-preserving
labels from two review stages and both mean that no material issue was recorded
within the stated scope.

## Descriptive failure concentration

As an exploratory diagnostic, failures were grouped by their final issue class.
Spatial metadata and coordinate handling account for 50 of the 70 node failures
and 10 of the 29 edge failures. Study-objective substitution for a publication
or collection title accounts for another 14 node failures and two edge
failures. The edge ledger also contains five dataset-level crosswalk
overpropagation failures and three config-text target mismatches. These are
sample-level concentrations useful for ETL prioritization; they are not
type-specific population prevalence estimates.

## Start here

- [`adjudication_public_400.csv`](adjudication_public_400.csv) is the
  authoritative public ledger with one row per sampled record and a persisted
  reason for every verdict.
- [`METHODS.md`](METHODS.md) gives the sampling, adjudication, estimation, and
  claim boundaries in paper-ready form.
- [`summary.json`](summary.json) provides machine-readable counts and scope.
- [`issue_class_summary.csv`](issue_class_summary.csv) aggregates verdicts by
  unit and issue class.
- [`candidate_pass_to_fail_corrections_13.csv`](candidate_pass_to_fail_corrections_13.csv)
  records the 13 candidate pass-to-fail corrections authorized during final
  review.
- [`rubric_boundary_decisions_3.csv`](rubric_boundary_decisions_3.csv) records
  three narrow semantic decisions that remained pass.
- [`source_attribution.md`](source_attribution.md) states the upstream content
  and redistribution boundary.

## What the sample does and does not cover

The extraction used Algorithm R with fixed seeds over a live read-committed,
non-frozen query window. The exported rows were fixed after capture for
adjudication. The node and edge samples are simple random samples without
replacement within their respective observed-instance frames; they are not
type-balanced and are not one joint 400-row sample.

The 200 sampled edges happened to contain 22 of the 98 relationship types in
the contemporaneous edge frame. Sampling from all observed directed edges is
therefore not equivalent to covering every relationship type.

The audit estimates observed-record quality within the sampled node and edge
frames. It does not estimate missing-edge recall, quality for every entity or
relationship type, full-KG validity, or post-repair quality. A repair claim
requires an unseen, newly sampled post-reingestion holdout.

`IN_ONVOC` passes in this ledger mean only task-family or contextual
classification. They are not contrast-specific `MEASURES` evidence.

## Adjudication and redaction

Ninety rows retained prior completed human adjudications. The remaining 310
rows received agent-assisted candidate review and were then authorized by the
project author, including 13 pass-to-fail corrections and three explicit rubric
boundary decisions. There was no second independent human annotator, so this
artifact does not report inter-rater reliability or Cohen's kappa.

The public ledger omits database and Neo4j element identities, raw properties,
property-key inventories, pseudonymous subject identifiers, generated claim or
evidence identifiers, internal run/session identifiers, agent/shard identities,
and private paths. Public URLs and public-repository code locators are retained
where available. Raw upstream abstracts, evidence quotes, and source payloads
are not redistributed.

## Validate

From the root of a Git checkout:

```bash
python docs/results/br_kg_manual_validation_20260805/validate_public_bundle.py
```

The validator checks the public schema, sampling constants, row uniqueness,
verdict totals, correction and rubric ledgers, Git-tracked release files,
public locator shape, and the redaction boundary. It requires `.git` metadata;
it does not connect to Neo4j or mutate any data.

When citing this audit, cite the repository path together with the Git commit or
release tag that contains it. Do not cite it as a validation of the entire KG or
as evidence of a completed repair.

## Relationship to the frozen supplement archive

This audit postdates the immutable 2026-07-05 reviewer artifact package under
`docs/reviewer_artifacts/`. It is intentionally published as a separate result
rather than inserted into that frozen archive or its file manifest. A future
supplement release can cite this directory or incorporate it as a newly
versioned artifact.
