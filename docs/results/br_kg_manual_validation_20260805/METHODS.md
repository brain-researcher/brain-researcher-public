# Methods and reporting boundary

## Sampling

Two independent simple-random-without-replacement samples were captured from
the observed BR-KG instance frames during a live read-committed, non-frozen
query window from 2026-08-05 11:21:12 to 11:23:42 UTC. Algorithm R was applied
with a fixed seed to each frame:

| Unit | Frame size | Sample size | Seed | Inclusion probability | Sampling weight |
|---|---:|---:|---:|---:|---:|
| Node instance | 748,771 | 200 | 2026080501 | 0.00026710436168067407 | 3743.855 |
| Directed-edge instance | 1,386,496 | 200 | 2026080502 | 0.00014424852289512556 | 6932.48 |

The query window was not a transactionally frozen database snapshot. The
captured export was fixed after extraction and served as the immutable review
frame. The reported seed and frame metadata reproduce the selection contract,
but a current production graph may have drifted and cannot be assumed to yield
the same rows.

The samples were not balanced by node label or relationship type. The edge
sample observed 22 of the 98 relationship types present in the contemporaneous
frame. It is therefore accurate to say that edges were randomly sampled from
the all-edge frame, but inaccurate to say that every relationship type was
covered.

## Adjudication

Each row received one of three final verdicts:

- `pass`: no material defect was found within the row's stated evidence scope;
- `fail`: a material schema, source-fidelity, semantic, or provenance defect was
  found;
- `unassessable`: the retained evidence was insufficient for a defensible pass
  or fail.

An `unassessable` row is completed, not pending. A pass is also scoped: for
example, bibliographic source fidelity does not validate a paper's scientific
claims, and a source-derived TF-IDF relation does not establish that a term is
the paper's principal conclusion.

Ninety rows retained prior completed human adjudications. For the remaining 310
rows, agent-assisted candidate verdicts and reasons were reviewed and
authorized by the project author. Final review changed 13 candidate passes to
fail and resolved three narrow rubric boundaries as pass. The public ledger's
`decision_provenance` column distinguishes these routes.

No second independent human annotator reviewed the full sample. Inter-rater
reliability and Cohen's kappa are therefore not estimated.

## Estimation

Within each simple-random sample, the reported estimand is the proportion of
records adjudicated `fail` under the retained evidence and stated rubric. Nodes
and directed edges are reported separately because they have different frames
and sampling weights. This estimand is not the latent material-defect prevalence
because the defect status of `unassessable` records remains unresolved.

- Nodes: 70/200 failed, 35.0%, Wilson 95% CI 28.7% to 41.8%.
- Directed edges: 29/200 failed, 14.5%, Wilson 95% CI 10.3% to 20.0%.

The Wilson intervals treat `fail` versus all other completed verdicts as the
binary outcome. As a sensitivity bound, if every unassessable record were later
confirmed defective, the node and directed-edge fractions would instead be
82/200 (41.0%) and 38/200 (19.0%), respectively.

The arithmetic 99/400 value, 24.75%, is retained only as a descriptive summary
of the equal-sized audit set. It is not a population-weighted KG-wide defect
estimate.

## Semantic boundaries

`IN_ONVOC` was adjudicated as a task-family or contextual classification. In
particular, an `rt` regressor does not itself establish inhibition, and a
crosswalk label does not establish that an untrained control contrast measured
a trained condition. These rows remain pass only under the coarse
classification semantics recorded in the rubric-boundary ledger.

Coordinate and spatial judgments distinguish record correctness from scientific
validity. A row can fail because a required template space was not materialized
without implying that the underlying statistical map or publication is
scientifically invalid.

## Scope and non-claims

This audit does not estimate:

- missing-node or missing-edge recall;
- quality within every node label or relationship type;
- correctness of every upstream source;
- full-KG validity;
- post-repair or post-reingestion quality.

The audit artifact did not execute an ETL repair, reingestion, deletion, or
production KG mutation. After any systemic ETL repair, the appropriate
confirmatory check is a newly drawn, unseen post-reingestion holdout using the
same node/edge stratification and a prespecified rubric.

## Suggested paper wording

> We audited two independent simple-random-without-replacement samples of 200
> observed node instances and 200 observed directed-edge instances from a live
> read-committed BR-KG query window. Final adjudication classified 70/200 nodes
> as fail (35.0%, Wilson 95% CI 28.7%-41.8%; 12 unassessable) and 29/200 directed
> edges as fail (14.5%, Wilson 95% CI 10.3%-20.0%; 9 unassessable). These
> adjudicated-fail estimates characterize the sampled observed-instance frames;
> they do not resolve latent defect status for unassessable rows or measure
> missing-edge recall, all-type coverage, full-KG validity, or post-repair
> quality.
