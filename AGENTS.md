# Repository Guidelines

`AGENTS.md` is the canonical instruction file for this repository. If repository-level guidance changes, update this file instead of `CLAUDE.md`.

## Priority Rules
- Think before coding. State assumptions explicitly when they affect correctness.
- Prefer the simplest change that solves the requested problem. Avoid speculative abstractions, configurability, or error handling that is not required.
- Make surgical edits. Touch only code that is needed for the request. Do not refactor or clean up unrelated areas.
- Work from verifiable goals. Tie implementation to a concrete check: a focused test, a reproduction, a lint/typecheck run, or another clear validation step.
- Do not overclaim implementation status. When asked whether a protocol, architecture, or feature exists, distinguish clearly between `implemented`, `partial`, and `spec-only`.
- Keep planning and execution separate. When a surface is preview-only, validation-only, or handoff-only, say so explicitly instead of implying execution authority.

## Current Direction
- Preserve clear boundaries between explanation, planning, validation, and execution. Do not describe a surface as doing more than it actually does.
- Prefer explicit contracts and verifiable behavior over implicit assumptions about system capabilities.
- Favor lightweight guardrails, simple routing, and incremental extensions before introducing heavier orchestration or new architectural layers.
- Avoid speculative capabilities. If a tool, protocol, route, or integration is not verified in the current surface, say that directly instead of inferring it.
- When importing external instruction styles or agent patterns, adapt them to this repository and consolidate lasting rules into `AGENTS.md`.

## Repo Shape
- `src/brain_researcher/`: canonical Python package
  - `cli/`: Typer-based CLI (`brain-researcher` / `br`). Service entrypoints follow the shape `br serve agent|kg|web [-p PORT]` for the public web stack, with the orchestrator and MCP server reachable via the longer `br serve agent|kg|web|orchestrator|mcp [-p PORT]` form. See `docs/OPERATIONS.md` for per-service defaults.
  - `services/`: runtime surfaces such as `agent`, `mcp`, `br-kg`, `orchestrator`, `tools`, `review`, `memory`, and shared service helpers
  - `core/`: core analysis, datasets, contracts, literature, memory, multiverse, and utility logic
  - `autoresearch/`, `research/`: bounded research loops, line controllers, and research workflows
  - `integrations/`, `semantics/`, `config/`, `llmcore/`, `neurocore/`: integration layers, semantic layers, and supporting infrastructure
- `apps/web-ui/`: Next.js frontend and Studio/chat UX
- `tests/`: unit, integration, and behavior/contract coverage
- `scripts/`: operational and reproducible helper scripts
- `docs/`: operations docs, MCP docs, appendices, release notes, and use cases
- `benchmarks/`: evaluation harness code and public-safe benchmark fixtures when present
- Agent skills, AGENTS templates, demos, and eval rubrics live in the companion [`brain-researcher-agent-kit`](https://github.com/zjc062/brain-researcher-agent-kit) repository, not in this public core repo.
- `data/`, `configs/`, `infrastructure/`: datasets, runtime config, and deployment assets

## Workflow
- Discovery before execution: inspect existing implementations in `src/`, `tests/`, `scripts/`, and `docs/` before introducing a new code path or service surface.
- Prefer extending existing entrypoints (`br`, current service modules, existing scripts, existing test fixtures) over adding parallel abstractions.
- Keep behavior changes, refactors, and migrations separable when practical.
- Avoid hardcoded machine-specific or temporary-session paths. Prefer repo-relative paths, config, env vars, or clearly named path variables.
- For new operational scripts, keep them under a topical `scripts/` subdirectory, make them rerunnable, and document inputs, outputs, env vars, and log locations. Avoid adding run-specific or one-off scripts directly under `scripts/`; use a benchmark run directory, `/tmp`, or a clearly named archive/legacy folder instead.
- If multiple technical options are viable, state trade-offs explicitly: correctness, speed, maintenance burden, operational cost, and infra/data requirements.

## Session-Derived Agent Rules
- Treat `succeeded` as "this agent turn completed," not as proof that the product feature, deployment, or scientific claim is fully complete. Preserve remaining blockers in `open` items and the final handoff.
- For prod/runtime work, record the commit or image tag, rollout target, rollout status, health checks, and any API/browser smoke that was actually run. Do not claim hosted execution if the result is only a recipe, handoff, dry run, or local verification.
- For web, Studio, demo, and artifact-viewer work, verify both the API payload and the rendered browser state when feasible. Distinguish curated/demo evidence, live analysis evidence, degraded backend health, and local environment failures.
- For repo cleanup or release-readiness work, inventory exact paths first, keep unrelated dirty work separate, preserve example/template files, and validate with focused checks such as `git diff --check`, `git status`, `git ls-files`, or `git check-ignore`.
- For code or contract changes, prefer focused tests that exercise the changed behavior and contract shape. If repo-wide lint or tests are blocked by pre-existing debt, name the narrow validation that passed and the unrelated blocker that remains.
- For scientific workflows, record the hypothesis, confirmatory test, exploratory follow-up, gate/outcome state, null-result diagnosis, and blocked assets. Clearly separate run completion, scientific validity, and manuscript/report readiness.
- When leaving work open, classify the risk before the details when practical: `uncommitted-local`, `unrelated-dirty-worktree`, `partial-validation`, `prod-auth-data-runtime`, `generated-artifact`, `pre-existing-debt`, `scientific-method-gap`, or `logging-metadata-gap`.
- A compact final handoff should include: `changed`, `verified`, `open`, `next_command`, and `BR session_id`. Example: `changed: added session risk labels to AGENTS.md; verified: git diff --check -- AGENTS.md; open: uncommitted-local AGENTS.md only; next_command: git diff -- AGENTS.md; BR session_id: codex-example-20260526`.

## Validation
- Validation is part of the task, not a follow-up.
- Backend logic changes should add or update focused unit tests when feasible.
- API, schema, protocol, or planning-surface changes should validate contract shape, not only happy-path behavior.
- Frontend and notebook-surface changes should run the narrowest meaningful lint/typecheck/test coverage available, plus a manual verification path when visual or routing behavior matters.
- For chat, Studio, marimo, or planner-routing changes, verify the intended mode boundaries directly. Example: plain chat should stay plain chat; grounded requests should use verified grounding; handoff-only surfaces should not be described as executable.
- If validation cannot run, say exactly what blocked it, what was not verified, and what risk remains.
- Final handoff should summarize what changed, what was verified, and what remains open.

## Security
- Provide secrets via env vars such as `OPENAI_API_KEY`.
- Never commit secrets.
- Prefer existing data download paths and scripts over ad hoc large-file placement.

## Required Brain Researcher Check
- For neuroimaging or research-related tasks, first check whether `brain_researcher_mcp` is active and which tools it exposes.
- If `brain_researcher_mcp` is active, use its available tools when they are relevant for prior context, memory lookup, research synthesis, analysis planning, plan validation, scientific self-critique, or final reporting.
- Inspect the actual exposed tool names before invoking them. Do not invent SDK-style function names unless the current MCP client actually exposes them.
- If the MCP server is inactive or unavailable, state that `brain_researcher_mcp` is unavailable and continue with the closest reasonable fallback.

## Brain Researcher MCP Functions
- Treat this as an inventory of Brain Researcher MCP functions to look for. The active client may expose only a subset, so inspect the current MCP tool list first and then choose from the functions that are actually available.
- Status, health, and inventory: use `server_info` to inspect server configuration and guardrails, `system_self_test` for health/dependency probes, and `loop_profile_get` for machine-readable loop policies. Use these before claiming that the MCP server can execute, validate, or access a resource.
- Tool and workflow discovery: use `tool_search` for capability search, `workflow_search` for workflow-level routes, `tool_search_structured` for method/software/version-style lookup, `tool_resolve` to map a method/software/op key to a concrete tool, and `tool_get` to inspect a known tool and its schema. Use `get_execution_recipe` when the next step should be a runnable local, container, Neurodesk, or cluster recipe.
- Planning and handoff surfaces: use `plan_preflight` to check dataset facts, missing inputs, blockers, and candidate tools before committing to a plan. Use `plan_create` to create a read-only plan contract with display and execution envelopes. Use `get_latest_plan` only to recover an existing validated handoff block.
- Plan validation and pre-execution critique: use `pipeline_plan_validate` for schema normalization, path/policy checks, and validation issues. Use `pipeline_plan_review` for domain critique of ordering, parameter ranges, modality/space compatibility, and plan completeness. Use `qsm_implementation_review` for QSM-specific code hazards such as direct inversion or incorrect local-field dataflow.
- Manual/admin execution surfaces: `tool_execute`, `pipeline_execute`, and `run_cancel` are not the default agent path. Prefer `get_execution_recipe` plus explicit local execution unless the user specifically asks for MCP execution, cancellation, or admin control. Never describe `plan_preflight`, `plan_create`, `pipeline_plan_validate`, or `get_execution_recipe` as having executed an analysis.
- Research memory: use `memory_search` for prior context, saved decisions, hypotheses, datasets, papers, or earlier results. Use `memory_get` after a specific memory card is identified. Use `memory_write` only when the user explicitly asks to persist a derived memory card or relation.
- Research logging and session summaries: use `log_research_event` for the start of real work and rare rationale notes, `write_session_snapshot` before final handoff, `research_session_digest` for one session, and `research_log_summary` for cross-session summaries.
- Session learning tools: when exposed, use `session_risk_classify` and `session_lesson_extract` to inspect one session, `session_open_risks_query` to find repeated blockers, `session_policy_cards_generate` to propose durable agent-policy candidates, `session_learning_report_generate` for periodic reports covering top task surfaces, repeated blockers, successful patterns, candidate `AGENTS.md` updates, KG lesson candidates, and stale/running sessions, and `session_signal_report_generate` to mine post-snapshot activity, trace-only invariant signals, validation-parser false negatives, and unresolved next-action chains before promoting silent-fail lessons into policy.
- Session KG backfill: `session_backfill_to_kg` is dry-run by default. Use `dry_run=false` only when Neo4j env vars are configured and the user explicitly wants KG writes; otherwise use its returned rows and query examples as a preview.
- Run inspection: use `run_list` to discover runs, `run_get` for status and step records, `run_bundle_get` for normalized observation bundles, `run_scorecard` for scorecards, `run_compare` for run-to-run comparisons, `run_metrics` for timing/cost/status metrics, `run_logs` for log payloads, `run_find_latest_reviewable` to locate review/report candidates, and `run_request_summary` for historical request-type summaries.
- Artifact inspection: use `artifact_list` to enumerate run artifacts, `artifact_read_text` for text artifacts, `artifact_get_metadata` for size/time/checksum metadata, and `artifact_read_bytes` for small binary artifacts. Do not assume the deployed MCP server can read arbitrary local workspace paths.
- Code and scientific review: use `run_code_review` for post-execution artifact/domain review. Use `run_scientific_review` for correctness, completeness, and judgment review of a persisted run. Use `run_autoresearch_scientific_review` for autoresearch workspaces. Use `request_scientific_review` when the right review path may be a run, autoresearch directory, or external-review directive.
- External review handoff: use `request_external_scientific_review_directive` when BR should provide review criteria/schema but cannot read the external artifacts itself. Use `submit_external_scientific_review_verdict` only after an external agent has actually inspected the evidence and produced a schema-valid verdict.
- Report generation and rendering: use `scientific_report_generate` when producing a research-facing report from reviewed evidence. Use `latex_report_render` only to render supplied structured sections; it does not perform scientific review by itself.
- KG and dataset lookup: use `kg_search_nodes`, `kg_get_node`, and `kg_neighbors` for KG node lookup and neighborhoods. Use `kg_search_datasets`, `kg_related_datasets`, `dataset_get_resources`, and `kg_list_dataset_onvoc_links` for dataset discovery/resources/ontology links. Use `kg_behavior_to_fmri_retrieval` for behavior-to-task-fMRI evidence and `kg_multihop_qa` for multi-hop KG questions; report degraded or timeout results explicitly.
- KG hypothesis verification and critique: use `kg_verify_hypothesis` or `verify_hypothesis_with_kg` to check a claim against KG evidence. Use `kg_probe` for structural leverage, contradiction motifs/frontiers, assumption cracks, or analogy transfers. Compatibility wrappers include `kg_find_structural_leverage`, `kg_detect_contradiction_motifs`, `kg_find_contradiction_frontiers`, `kg_mine_assumption_cracks`, `kg_find_analogy_transfers`, and `kg_detect_topology_shifts`.
- KG hypothesis generation and candidate workflows: use `kg_sample_ood_hypothesis` for OOD hypothesis sampling, `kg_hypothesis_workflow` for sample/verify workflows, `kg_verify_sampled_hypotheses` and `kg_sample_and_verify_hypotheses` for candidate verification loops, `kg_hypothesis_candidate_cards` for synchronous candidate cards, `kg_hypothesis_candidate_cards_start` and `kg_hypothesis_candidate_cards_get` for longer candidate-card runs, `hypothesis_hot_load_research` for the full hot-load path, and `hypothesis_run_start` / `hypothesis_run_get` for longer hypothesis runs.
- Literature, paper, file-search, and grounding tools: use `google_deep_research` for current web-grounded synthesis, or `google_deep_research_start` / `google_deep_research_get` for async deep research. Use `deepxiv` for arXiv/PMC paper search and reading. Use `google_file_search` only for configured Google File Search stores. Use `grounding_resolve` to resolve evidence anchors and `grounding_gate_evidence_basis` to downgrade weak or unresolved final evidence claims.
- Diagnostics and synthesis helpers: use `companion_diagnostic_suggester` for metric-specific companion checks, `refuted_landscape_summary` to summarize supported/refuted/inconclusive directions from structured findings, `generate_research_trajectory_and_insights` for durable trajectory summaries, `generate_bug_digest` for run/candidate failure summaries, and `generate_repo_repair_context` for repair-context synthesis.
- Environment-specific helpers: use `sherlock_guide` and `sherlock_slurm` only for Stanford Sherlock/Slurm workflow guidance and debugging.
- Direct lookup rule: there is no generic `br.lookup` MCP function unless a client exposes one. For known items, use the specific lookup surface: `memory_get`, `tool_get`, `run_get`, `artifact_read_text`, `kg_get_node`, `dataset_get_resources`, or the relevant review/report getter.

## Self-Critique Checkpoint
- After obtaining an initial research result, do not write the final report immediately. First run a self-critique pass, using Brain Researcher MCP review tools when they are active and relevant.
- Interest check: if a reviewer's first reaction would be "so what?" rather than "interesting," the analysis is not finished. Refine the framing, comparison, visualization, or follow-up analysis until the result has a clear scientific point.
- Null-result diagnosis: if the main effect is weak or non-significant, do not immediately report it as a final null. First check whether the null may be caused by methodological choices such as the wrong analysis granularity, uncontrolled confounders, weak labels, placeholder categories, insufficient filtering, or an overly broad outcome definition. After diagnosis, decide whether to report the null, adjust the approach, or run a more targeted analysis.
- Exploratory follow-up: run at least one reasonable post-hoc exploration before concluding. For example, check whether a weak overall effect hides signal in a subgroup, condition, feature family, brain network, network pair, task contrast, dataset split, or quality-controlled subset. Clearly label these findings as exploratory.
- Only proceed to the final report after this checkpoint is completed. The report should state what was tested, what was found, what was checked after the initial result, and which findings are confirmatory versus exploratory.

## Research Logging Harness (Codex / Claude Code)
- Treat research logging as `start + optional enrichment + final snapshot`, not as per-turn commentary.
- At the start of real work, call `log_research_event(kind="start", content=..., session_id=..., source="agent", source_client=...)`.
- Always pass `source_client` when the client is known: use `codex`, `codex_cli`, or `claude_code` rather than leaving it null. If the client exposes a native thread/chat/session id, pass it as `client_session_id`; otherwise use one stable descriptive `session_id` for the continuous task.
- Mid-session `kind="note"` is optional and should be used only for rationale that server-side telemetry cannot infer from traces.
- Before the final answer, call `write_session_snapshot(session_id=..., goal=..., done=[...], open=[...], next_command=..., source="agent", source_client=...)` exactly once for the continuous task.
- Prefer one `session_id` per continuous coding session. Reuse the same id across the session unless a tool directive says otherwise.
- If a BR tool response includes `_agent_directive.research_logging`, follow it and reuse the provided `session_id`.
- If a closeout directive includes `review_session_snapshot_hygiene`, treat it as advisory feedback for future sessions or follow-up policy work. Do not imply the persisted snapshot was rejected or amended.
- Do not paste the full raw JSON response from `log_research_event` or `write_session_snapshot` into the user-facing final answer unless the user asks for it. Summarize the logged `run_id` / `session_id`, what was captured, and any open follow-up instead.
- Treat lingering `status="running"` research-logging sessions as incomplete closeout unless the work is intentionally still in progress; close them with a snapshot when the task is done.
