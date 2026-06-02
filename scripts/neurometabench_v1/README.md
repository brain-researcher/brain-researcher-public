# NeurometaBench v1 Harness

This harness evaluates Track 1 study-set reconstruction:

`topic/search/inclusion/year_cutoff -> predicted PMID set`

Gold PMIDs come from `external/neurometabench/data/included_studies.csv`.

## Layered Evaluation

The v1 harness now treats NeuroMetaBench as a workflow-capability suite rather
than a pure screening-recall benchmark:

- **Layer A — Screening with justification**: non-NiMADS cases with ground-truth
  included studies. BR outputs per-paper `decision`, `criterion_ids`,
  `evidence_spans`, `reason`, and `confidence`. Only two local cases currently
  have curated closed-world `all_studies.csv` pools; the remaining Layer A cases
  require PubMed/PMC/union retrieval or the synthetic `mixed_pool` stress-test
  source.
- **Layer B — End-to-end reproduction**: NiMADS/BrainMap-backed cases where the
  target workflow is study set -> coordinates -> NiMARE/ALE map -> report.
- **Layer C — Diagnostic/audit layer**: non-headline checks that make Layer A
  and Layer B interpretable. Layer C records retrieval ceilings, public-map
  substrate coverage, and NiMADS coordinate asset readiness. It is not a model
  capability score.

## Commands

Export normalized cases:

```bash
python -m scripts.neurometabench_v1.export_cases \
  --output benchmarks/neurometabench/cases.v1.jsonl
```

Run the frozen Neurosynth v7 term-ranking baseline:

```bash
python -m scripts.neurometabench_v1.neurosynth_baseline \
  --cases benchmarks/neurometabench/cases.v1.jsonl \
  --output /tmp/neurometabench_v1/neurosynth_predictions.jsonl
```

Convert existing BR screening outputs, when available:

```bash
python -m scripts.neurometabench_v1.br_screening_adapter \
  --cases benchmarks/neurometabench/cases.v1.jsonl \
  --br-output-dir /tmp/neurometabench_batch_pmc_fulltext \
  --candidate-source union \
  --output /tmp/neurometabench_v1/br_predictions.jsonl
```

Run retrieval-only diagnostics before paying for LLM screening:

```bash
python -m scripts.neurometabench_v1.retrieval_only \
  --cases benchmarks/neurometabench/cases.v1.jsonl \
  --max-cases 5 \
  --max-candidates 500 \
  --output /tmp/neurometabench_v1/retrieval_diagnostics.jsonl
```

The retrieval diagnostic compares `official_query`, BR's high-recall
primary-study reformulation (`br_llm_query`), `broad_query`, and their
`union_query`. It reports `n_hits`, `n_candidates`, `candidate_recall`, and
`gt_missing_from_candidates`. Treat cases below `candidate_recall >= 0.6` as
retrieval/query failures before running expensive screening.

For cases without curated closed-world pools, use `mixed_pool` to test screening
under a controlled base rate before spending on open-world retrieval:

```bash
python -m scripts.neurometabench_v1.retrieval_only \
  --cases benchmarks/neurometabench/cases.v1.jsonl \
  --retriever mixed_pool \
  --max-cases 5 \
  --output /tmp/neurometabench_v1/retrieval_mixed_pool.jsonl
```

`mixed_pool` builds a deterministic pool of all GT PMIDs plus random non-GT
PMIDs from the local NeuroMetaBench universe. The default runner ratio is 1 GT
to 5 noise PMIDs, which avoids the inflated recall interpretation that occurs
when a curated closed-world candidate list has high inclusion prevalence.

Run the formal Layer C diagnostic/audit bundle:

```bash
python -m scripts.neurometabench_v1.run_layer_c_diagnostics \
  --cases benchmarks/neurometabench/cases.v1.jsonl \
  --output-root benchmarks/neurometabench/experiments/layer_c_diagnostics \
  --retrievers closed_world,mixed_pool \
  --max-candidates 500
```

Layer C writes `layer_c_manifest.jsonl`,
`layer_c_diagnostic_summary.json`, and `layer_c_diagnostic_summary.md`, plus
retrieval, NeuroVault, and NiMADS audit artifacts. Use `--retrievers pubmed`
only when network/API use is intended. Layer C outputs explain benchmark
coverage and substrate limits; do not aggregate them as BR-vs-baseline scores.

The legacy screening runner also exposes the same control knobs for actual
screening:

```bash
python scripts/neurometabench_screening_pipeline.py \
  --meta-pmid 36100907 \
  --candidate-source mixed_pool \
  --mixed-pool-noise-ratio 5 \
  --min-candidate-recall-to-screen 0.6 \
  --max-candidates 500
```

Evaluate one or more prediction files:

```bash
python -m scripts.neurometabench_v1.evaluate_study_set \
  --cases benchmarks/neurometabench/cases.v1.jsonl \
  --predictions /tmp/neurometabench_v1/neurosynth_predictions.jsonl \
  --add-closed-world-baselines \
  --output-dir /tmp/neurometabench_v1/eval
```

The evaluator reports absolute metrics plus corpus-aware metrics when a prediction
file provides `corpus_pmids` or `corpus_pmids_file`. When prediction rows include
per-candidate `decision_records`, it also reports `eligibility_F1`, include-only
metrics, predicted-to-gold ratios, over-conservatism signals, and citation
hallucination rates split into non-retrievable, retrievable-unsupported, and
wrong-source categories.

For closed-world cases, `--add-closed-world-baselines` adds include-all,
random, and keyword/BM25-style title baselines. Report BR screening against
these controls whenever closed-world prevalence is high; otherwise BR precision
and recall are not interpretable.

Generate Layer A deterministic controls:

```bash
python -m scripts.neurometabench_v1.layer_a_baselines \
  --cases benchmarks/neurometabench/cases.v1.jsonl \
  --candidate-source mixed_pool \
  --mixed-noise-ratio 5 \
  --mixed-max-total 150 \
  --output /tmp/neurometabench_v1/layer_a_baseline_predictions.jsonl
```

This writes two dependency-free controls in the standard prediction JSONL
schema: `layer_a_rule_lexical` and
`layer_a_asreview_style_specialist`. The ASReview-style row models an
active-learning screening loop with specialist feedback revealed only after
candidate selection; it does not require the external `asreview` package. Use
`--asreview-mode auto` to record external-package detection and style fallback
metadata when the package is absent. Use `--asreview-mode external` only after
the external ASReview wrapper is implemented and verified; the current harness
fails clearly rather than claiming an unverified external ASReview run.

Build the Layer B reproduction manifest:

```bash
python -m scripts.neurometabench_v1.build_nimads_reproduction_manifest \
  --cases benchmarks/neurometabench/cases.v1.jsonl \
  --output benchmarks/neurometabench/nimads_reproduction_manifest.jsonl
```

Audit the Layer B NiMADS assets before implementing ALE/map reproduction:

```bash
python -m scripts.neurometabench_v1.audit_nimads_assets
```

The audit writes `benchmarks/neurometabench/experiments/nimads_asset_audit.json`
and `.md`. It separates screening/study-set GT from `cases.v1.jsonl`
(`gt_pmids`) from coordinate-level GT in the merged NiMADS studysets. In the
current local snapshot, all 6 Layer B cases have coordinate-level NiMADS assets,
but only 2/6 have case-level PMID GT. Treat `map_ready_but_not_study_level`
cases as map-reproduction candidates, not study-set-F1 candidates, unless a
separate PMID mapping layer is added.

Run one Path B NiMADS -> NiMARE/ALE map reproduction:

```bash
python -m scripts.neurometabench_v1.run_path_b_reproduction \
  --meta-pmid 30793072 \
  --output-root benchmarks/neurometabench/experiments/path_b_reproduction
```

The runner writes per-case `coordinate_table.csv`, `included_studies.csv`,
`ale_maps/*.nii.gz`, `metrics.json`, `spatial_report.md`, and
`provenance_manifest.json`. When no external published/reference NIfTI is
available, it validates the spatial metric path with an internal split-half ALE
check. If a reference map exists, pass `--reference-map /path/to/reference.nii.gz`
to compute direct z-map correlation and top-5% Dice.

After validating one case, scale to every Layer B case:

```bash
python -m scripts.neurometabench_v1.run_path_b_reproduction \
  --all \
  --output-root benchmarks/neurometabench/experiments/path_b_reproduction
```

If individual cases were run separately, rebuild the aggregate summary without
rerunning ALE:

```bash
python -m scripts.neurometabench_v1.run_path_b_reproduction \
  --summarize-existing \
  --output-root benchmarks/neurometabench/experiments/path_b_reproduction
```

Compare existing Layer B condition artifacts without rerunning ALE or invoking
agents:

```bash
python -m scripts.neurometabench_v1.run_layer_b_comparison \
  --condition pure_nimare=benchmarks/neurometabench/experiments/path_b_reproduction \
  --condition coding_agent_only=/path/to/coding_agent_layer_b_outputs \
  --condition br_assisted=/path/to/br_assisted_layer_b_outputs \
  --normalize-artifacts \
  --trace-br-anchors \
  --output-dir benchmarks/neurometabench/experiments/layer_b_comparison
```

The comparison runner reads existing `metrics.json`/summary artifacts and
classifies each case as `evaluable`, `degraded`, or `failed` based on required
artifact presence, coordinate rows, included studies, map outputs, and
provenance availability.

It reports Layer B in two metric layers. The deterministic artifact layer covers
map generation, study-set F1 when PMID-level gold is available, coordinate
agreement against the pure NiMARE control, spatial correlation, Dice top 5%,
coordinate/study rows, and exact matches to the pure NiMARE control. The
BR-relevant audit layer covers public PMID/DOI coverage, local study-id
coverage, source-provenance coverage, sample-size coverage, provenance
completeness, claim consistency, and failure-diagnosis quality. The comparison
JSON includes every metric in `metric_layers.metric_contract`; unavailable
metrics use `null` values with explicit `reason` fields. Treat map generation as
an execution metric, not the headline BR-benefit metric.

Print the current Layer B artifact/evaluator contract:

```bash
python -m scripts.neurometabench_v1.run_layer_b_comparison --print-contract
```

Run the v2 harness-fix pilot before another full matrix:

```bash
python -m scripts.neurometabench_v1.run_agent_condition_matrix \
  --layer layer_b \
  --condition opencode_gemini_pro_without_br \
  --condition opencode_gemini_pro_with_br_required \
  --condition codex_cli_gpt55_with_br_required \
  --condition opencode_glm51_with_br_required \
  --episode-scope case \
  --run-name layer_b_v2_harness_fix_small_matrix \
  --output-root benchmarks/neurometabench/experiments/agent_condition_matrix \
  --execute \
  --timeout-s 1800 \
  --soft-deadline-s 1500 \
  --layer-b-harness-finalizer \
  --require-br-effective-use
```

The v2 flags make the harness write required provenance fields, create a missing
report template or harness contract addendum, run per-case
`artifact_preflight.json`, write `br_anchor_trace.json`, pass explicit
`METABENCH_*` evaluator/output variables to agent CLIs, and fail BR-required rows
that do not produce an effective BR anchor. Existing agent-authored reports are
preserved as `spatial_report.agent_raw.md` when the harness appends a contract
addendum. Layer B case-scoped episodes write into isolated per-case producer
roots under each condition directory so one case episode cannot overwrite a
different case bundle from the same condition. This tests the benchmark contract
before spending a full 84-run budget.

Re-score an existing full Layer B run with the v2 post-processors and export the
case-condition table consumed by diagnostic axes:

```bash
RUN_DIR=benchmarks/neurometabench/experiments/agent_condition_matrix/layer_b_full_model_matrix_20260504

python -m scripts.neurometabench_v1.run_layer_b_comparison \
  --condition pure_nimare=benchmarks/neurometabench/experiments/path_b_reproduction \
  --condition codex_cli_gpt55_without_br=$RUN_DIR/producer_outputs/codex_cli_gpt55_without_br \
  --condition codex_cli_gpt55_with_br=$RUN_DIR/producer_outputs/codex_cli_gpt55_with_br \
  --normalize-artifacts \
  --trace-br-anchors \
  --output-dir $RUN_DIR/evaluation_v2

python -m scripts.neurometabench_v1.export_layer_b_case_condition_rows \
  --run-dir $RUN_DIR \
  --comparison-summary $RUN_DIR/evaluation_v2/layer_b_comparison_summary.json \
  --output-csv $RUN_DIR/layer_b_full_model_matrix_case_condition_rows_v2.csv

python -m scripts.neurometabench_v1.derive_layer_b_diagnostics \
  $RUN_DIR/layer_b_full_model_matrix_case_condition_rows_v2.csv \
  --output-csv $RUN_DIR/layer_b_full_model_matrix_case_condition_rows_v2_diagnostic_axes.csv \
  --summary-json $RUN_DIR/LAYER_B_DIAGNOSTIC_AXES_SUMMARY_V2.json \
  --summary-md $RUN_DIR/LAYER_B_DIAGNOSTIC_AXES_SUMMARY_V2.md
```

For a full matrix, include every producer output directory as a `--condition`;
the short example above shows the required command shape without listing all
conditions.

Diagnostic outputs separate `harness_clean_pass` from `correct_strict`.
`harness_clean_pass` is the full-rerun readiness gate: completion, evaluator
discovery, artifact contract, ALE map generation, coordinate schema,
provenance, and claim consistency must all pass. `correct_strict` additionally
requires scientific similarity, local study-set F1, and coordinate canonical F1.
Report those stricter scientific axes as paper-table columns rather than hiding
them inside a single failure label.

The diagnostic axes also report BR-specific reconciliation fields:
`br_reconciliation_score`, `br_reconciliation_gain`,
`identifier_coverage_delta`, `provenance_enrichment_delta`, and
`normalized_vs_raw_recovery`. The gain/delta fields are paired
withBR-minus-withoutBR metrics when a matching `(system, case)` row exists. Use
them to separate BR identifier/provenance gains from strict artifact exactness.

`--normalize-artifacts` writes per-case normalized copies under
`normalized_artifacts/` without overwriting raw agent outputs:

- `coordinate_table.normalized.csv`
- `included_studies.normalized.csv`
- `normalization_manifest.json`

This separates raw contract compliance from recoverable scientific content. A
run can be scientifically recoverable after normalization while still failing
the raw artifact contract. The normalizer accepts common coordinate aliases,
including `x_mni`/`y_mni`/`z_mni` and `x_tal`/`y_tal`/`z_tal`; when both MNI
and TAL columns are present, the canonical `x`/`y`/`z` fields prefer MNI.
BR-required prompts ask agents to map useful BR results to evaluator-facing
fields (`study_id`, `study_pmid`, `doi`, `pmcid`, `source_asset`,
`source_file`, `sample_size`, `coordinate_space`, and `original_study_ids`) so
BR output is canonicalizable rather than free-form prose.

`--trace-br-anchors` writes per-case `br_anchor_trace.json` from
`provenance_manifest.json`, `trajectory.json`, and available episode stdout. It
reports anchor-level BR call counts, whether a retrieved/audited anchor exists,
and whether the artifact or report appears to consume that BR result. This is
the preferred evidence for BR actual-use/effective-use analyses; the diagnostic
CSV proxy should be treated as a fallback when traces are absent. Preflight-style
BR rows can use `details` and `impact` fields; those are treated as audit
purpose/result text when computing effective use.

BR-required case bundles should also write `br_reconciliation_anchors.json`.
The file is not required for without-BR runs. Its top level is an `anchors`
list; each anchor names `target_artifact`, `target_field`, `canonical_value`,
`evidence_source`, `evidence_summary`, `confidence`, and `changed_bundle`.
Allowed `target_field` values are `study_id`, `study_pmid`, `doi`, `pmcid`,
`source_asset`, `source_file`, `sample_size`, `coordinate_space`, and
`original_study_ids`. The tracer validates this file and reports
`br_reconciliation_anchor_pass`, counts for valid/consumed anchors, and an
anchor score in diagnostic exports. A changed anchor only passes when its
canonical value is consumed by the target artifact or report. Keep
`canonical_value` short and exact; put prose in `evidence_summary`. Audit-only
anchors should use `changed_bundle=false`. For changed anchors, repeat the exact
canonical value in the named artifact or in a compact `BR reconciliation
anchors` line/table in `spatial_report.md`. Do not rewrite
`coordinate_table.csv` or `included_studies.csv` only to satisfy anchor
consumption; prefer `spatial_report.md` or `provenance_manifest.json` for
BR audit anchors unless BR directly corrects or fills a missing table field.

Run the normalizer or tracer directly for one case:

```bash
python -m scripts.neurometabench_v1.layer_b_artifact_normalizer \
  --case-dir /path/to/layer_b_<meta_pmid>

python -m scripts.neurometabench_v1.layer_b_br_anchor_tracer \
  --case-dir /path/to/layer_b_<meta_pmid> \
  --episode-dir /path/to/episode
```

Refresh terminal Layer B episode records after changing the harness finalizer or
BR-anchor tracer:

```bash
python -m scripts.neurometabench_v1.refresh_layer_b_episode_records \
  --run-dir benchmarks/neurometabench/experiments/agent_condition_matrix/<run_name> \
  --require-br-effective-use
```

This command re-runs the harness finalizer over existing producer outputs,
updates each episode `record.json`, rewrites the aggregate
`episode_records.jsonl`, and creates an `episode_records.jsonl.pre_layer_b_refresh`
backup. It only repairs `failed_br_required_gate` to `succeeded` when the current
BR trace proves effective use; timed-out or otherwise failed rows remain failed.

Layer B staged prompts live under:

```text
benchmarks/neurometabench/prompts/layer_b_stages/
```

Use `b1_asset_audit.md`, `b3_coordinate_normalization.md`, and
`b5_reconciliation.md` as one-case, one-stage diagnostic tasks. They explain
asset discovery, coordinate schema, and PMID/study/source reconciliation failure
modes without making the end-to-end task easier.

Derive the Layer B strict-success and diagnostic failure ontology from an
existing case-condition CSV:

```bash
python -m scripts.neurometabench_v1.derive_layer_b_diagnostics \
  benchmarks/neurometabench/experiments/agent_condition_matrix/layer_b_full_model_matrix_20260504/layer_b_full_model_matrix_case_condition_rows.csv
```

This post-hoc pass does not rerun agents. It adds `correct_strict`,
`diagnostic_vector`, `recoverable_failure_type`, raw-vs-normalized score
proxies, and BR actual/effective-use proxies. Keep the original `correct` column
as the evaluator's permissive contract outcome; use `correct_strict` as the hard
endpoint and the vector columns to explain why a run failed.

Run the NeuroVault substrate-coverage diagnostic:

```bash
python -m scripts.neurometabench_v1.neurovault_substrate_diagnostic \
  --cases benchmarks/neurometabench/cases.v1.jsonl
```

This reports the substrate ceiling BR can build on top of: which meta-analysis
papers and ground-truth included studies have local NeuroVault collection/image
links in the PubGet extraction. It is not a BR score.

Run or summarize one durable Layer A mixed-pool experiment:

```bash
python -m scripts.neurometabench_v1.run_layer_a_experiment \
  --meta-pmid 36100907 \
  --candidate-source mixed_pool \
  --mixed-pool-noise-ratio 5 \
  --max-candidates 150 \
  --screening-output-dir /tmp/neurometabench_results/layer_a_36100907_mixed_pool_flash_canonical_v2 \
  --judge-json /tmp/neurometabench_v1/criterion_alignment_36100907_mixed_pool_canonical_v2_gemini.json
```

To execute screening rather than reuse an existing output directory, load Gemini
credentials into the environment and add `--run-screening`. The runner writes an
`experiment_summary.json` and `experiment_summary.md` containing study-set
metrics, rationale coverage, semantic-judge summary, and the confusion matrix.

Scale Layer A runs with bounded concurrency, retry/backoff, resume, aggregate
prediction export, and aggregate evaluation:

```bash
python -m scripts.neurometabench_v1.run_layer_a_batch \
  --cases benchmarks/neurometabench/cases.v1.jsonl \
  --output-root benchmarks/neurometabench/experiments/layer_a_batch \
  --candidate-source mixed_pool \
  --max-candidates 150 \
  --concurrency 4 \
  --retries 2 \
  --run-screening \
  --generate-baselines \
  --baseline-asreview-mode style
```

Without `--run-screening`, the batch runner resumes from each case's existing
`screening/screening_decisions.jsonl`. Use `--dry-run` to inspect selected cases
and planned baseline generation without running screening or evaluation. Use
`--baseline-only --generate-baselines` to evaluate just the deterministic rule
and ASReview-style specialist controls.

Normalize existing coding-agent artifacts before including them in the aggregate
evaluator:

```bash
python -m scripts.neurometabench_v1.layer_a_model_adapters \
  --input /path/to/run_bundle_or_decisions \
  --input-format run_bundle \
  --system codex_coding_agent \
  --execution-mode coding_agent \
  --candidate-source mixed_pool \
  --output /tmp/neurometabench_v1/codex_predictions.jsonl
```

The adapter is intentionally offline: it reads artifacts that already exist and
writes standard Layer A prediction JSONL with adapter provenance. It does not
call Codex, Claude Code, OpenCode, Gemini, or any model API.

Main model-family comparisons should be coding-agent runs:

- Codex conditions use the local Codex CLI subscription through `codex exec`.
- Claude conditions use the local Claude Code subscription through `claude -p`.
- Gemini, GLM, Kimi, Qwen, and DeepSeek conditions use OpenCode through
  `opencode run --model ...`.

OpenCode provider IDs are model IDs, not prose labels: local `opencode models`
currently exposes `google/...` for BYOK Gemini API credentials, `opencode/...`
for the Zen endpoint, `opencode-go/...` for the Zen Go endpoint, and
`deepseek/...` for the DeepSeek API. There is no `opencode-zen/...` provider ID.
Use `google/gemini-3.1-pro-preview` for Gemini so the run consumes
`GEMINI_API_KEY` or `GOOGLE_API_KEY` from `.env`/environment, use
`zai-coding-plan/glm-5.1` for GLM, use direct OpenCode Zen `opencode/...` IDs
for Kimi and Qwen, and use `deepseek/deepseek-v4-pro` for DeepSeek.

The canonical condition matrix is:

```text
benchmarks/neurometabench/agent_conditions.v1.jsonl
```

The shared Layer A producer prompt is:

```text
benchmarks/neurometabench/prompts/layer_a_coding_agent_producer.md
```

The shared Layer B producer prompt is:

```text
benchmarks/neurometabench/prompts/layer_b_coding_agent_producer.md
```

Direct provider API smokes are diagnostic-only and should not be reported as
Codex/Claude Code/OpenCode coding-agent comparisons.

Run the coding-agent matrix launcher:

```bash
python -m scripts.neurometabench_v1.run_agent_condition_matrix \
  --layer layer_a \
  --limit-cases 2 \
  --max-candidates 150 \
  --episode-scope case \
  --run-name layer_a_agent_matrix_2case \
  --output-root benchmarks/neurometabench/experiments/agent_condition_matrix \
  --execute \
  --timeout-s 900
```

Use `--dry-run` to materialize prompts/commands without calling agent CLIs.
OpenCode `with_br_mcp` rows are skipped unless OpenCode MCP is configured, so
the run record does not mislabel OpenCode as BR-assisted.

Use `--episode-scope case` for benchmark runs. The launcher invokes one agent
episode per case, then aggregates and evaluates prediction files itself. Agents
write bundles only; they do not run `evaluate_study_set.py`.

For `mixed_pool`, `--max-candidates` is a requested cap, not always a hard cap:
the shared pool builder preserves all GT PMIDs, so cases with more GT PMIDs than
the requested cap can materialize larger `candidates.jsonl` files. The
per-case `input_manifest.json` records this budget policy and the actual
`n_candidates`; producers must screen every materialized row. The launcher
writes `output_validation.json` and marks rows `failed_output_validation` when a
producer ranks or screens fewer candidates than the materialized input.

Layer A summaries include row-level `case_partition` labels and system-level
`subsets`. Use `subsets.mixed_only` as the main screening comparison. Treat
`subsets.all_gt_saturated` as diagnostic because those cases contain no
effective negatives, so broad `uncertain` predictions can score well under the
legacy include-or-uncertain metric.

Do not use include-or-uncertain `f1` as the sole headline. Main result tables
must report include-only metrics (`include_only_precision`,
`include_only_recall`, `include_only_f1`), `eligibility_F1`,
`average_precision`, `candidate_recall`, predicted-to-gold ratios, and
`over_conservatism_penalty` alongside the legacy include-or-uncertain metrics.
The summary JSON records this under
`headline_metric_policy`, and `study_set_subset_summary.csv` writes a compact
system-by-subset reporting table. The current 14-case Layer A mixed-pool run
marks `22282036`, `32078973`, `34400176`, and `36436737` as saturated
diagnostics.

For BR-assisted Layer A runs, BR is framed as recall-oriented evidence recovery,
not as a conservative exclusion filter. A no-hit or incomplete BR result is not
itself exclusion evidence; plausible but incomplete cases should remain
`uncertain`. BR-assisted bundles may include `br_screening_anchors.json`; when
`--require-br-effective-use` is set for Layer A with-BR rows, the launcher
requires a non-empty `anchors` list consumed by `screening_decisions.jsonl`.

Run the first-pass Layer A rationale alignment triage:

```bash
python -m scripts.neurometabench_v1.criterion_alignment_judge \
  --cases benchmarks/neurometabench/cases.v1.jsonl \
  --predictions /tmp/neurometabench_v1/br_predictions.jsonl \
  --output /tmp/neurometabench_v1/criterion_alignment_judge.json
```

The criterion-alignment judge is heuristic first-pass triage only. Use human
adjudication, or a separately validated LLM judge plus human spot checks, for
paper-level claims.

Run semantic Gemini judging on a small sample before scaling:

```bash
python -m scripts.neurometabench_v1.criterion_alignment_judge \
  --cases benchmarks/neurometabench/cases.v1.jsonl \
  --predictions /tmp/neurometabench_v1/br_predictions.jsonl \
  --judge-mode gemini \
  --model gemini-2.5-flash \
  --repeat 2 \
  --limit 20 \
  --output /tmp/neurometabench_v1/criterion_alignment_gemini_sample.json
```

Report the Gemini/human-adjudicated criterion-alignment rate for paper claims;
keep the lexical heuristic as a sanity filter only.
