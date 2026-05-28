# Line-Based Autoresearch Architecture

## Purpose

This document defines the generic Brain Researcher contract for line-based
autoresearch. A **line** is a bounded, review-gated research trajectory with its
own budget, lineage, append-only evidence trail, and explicit closeout or pivot
policy.

This layer is intentionally **not** tied to any one scientific domain,
benchmark, or prompt family. Domain-specific targets, metrics, hypotheses, and
module presets stay outside the core contract.

## Why Lines Are First-Class

A line-based workflow solves a different problem from one-off background jobs or
simple scheduled routines.

It makes these objects explicit:

- lineage: what this line inherited and why it exists
- budget: when the line should stop, synthesize, or request a grace turn
- review: what must be accepted before a report is final
- closeout: whether the right result is to advance, pivot, halt, or publish a
  null / blocker outcome

This prevents two common failure modes in autonomous research loops:

- silent drift into open-ended experimentation without a stopping contract
- silent failure where an infra blocker is treated like a transient experiment
  miss instead of a real scientific outcome

## Core Contracts

The generic contracts live in:

- `src/brain_researcher/core/contracts/autoresearch_line.py`
- `src/brain_researcher/services/review/autoresearch_line_workspace.py`
- `src/brain_researcher/services/review/autoresearch_report_preflight.py`
- `src/brain_researcher/services/review/autoresearch_line_controller.py`

The main top-level objects are:

- `AutoresearchLineStateV1`
  controller state for one line
- `AutoresearchWorkspaceLayoutV1`
  stable file-system layout for a line workspace

Supporting nested objects are:

- `LineBudgetEnvelopeV1`
- `LinePendingDirectiveV1`
- `LineTransitionRulesV1`
- `LineDecisionEventV1`
- `LineLatestSummaryV1`
- `LineCloseoutV1`
- `LinePivotOptionV1`
- `LineReportPreflightV1`
- `LineControllerDecisionV1`

## Workspace Layout

A line workspace is expected to have a stable, inspectable layout.

Required paths:

- `line_state.json`
- `experiments.jsonl`
- `loop_body_prompt.md`
- `outputs/`
- `runner_logs/`

Optional but common paths:

- `experiments.bootstrap.jsonl`
- `run.py`
- `predict.py`
- `reference*/`

The generic loader resolves these paths into `AutoresearchWorkspaceLayoutV1` so
review, import, and dashboard surfaces can read a workspace without hardcoding a
single project’s naming conventions.

## Line State

`AutoresearchLineStateV1` is the controller-facing state record for a line.

Recommended fields include:

- identity and lineage:
  `line_id`, `line_type`, `workspace`, `parent_workspace`,
  `reference_workspace`
- lifecycle:
  `status`, `created_utc`, `updated_utc`
- budget and control:
  `budget_envelope`, `runner_turns_completed`, `budget_extensions_used`,
  `pending_directive`, `transition_rules`, `consecutive_no_growth`
- execution profile:
  `loaded_modules`, `forbidden_modules`, `training_backend`,
  `success_criterion`
- evidence trace:
  `decision_trace`, `last_latest_summary`
- closeout:
  `closeout`

The generic loader supports both new BR-native line-state payloads and legacy
workspace payloads by coercing them into `AutoresearchLineStateV1` while
preserving the original on-disk schema tag in `source_schema_version`.


## Report Preflight

Before scientific review, a line report should pass a deterministic preflight.
This catches format and declaration errors before they become review-time
rejections.

The current generic preflight checks:

- report existence and readability
- presence of the pre-report self-critique checkpoint
- presence of the required self-critique sections
- parseable `claim_strength` declaration
- explicit `validation_missing` declaration
- explicit `final_stopping_condition` declaration
- explicit separation of `primary analysis` and `sensitivity analysis`

The result is represented by `LineReportPreflightV1`.

## Controller Skeleton

The controller skeleton translates preflight and scientific-review signals into
line-state transitions.

The current generic decision outcomes are:

- `repair_report_preflight`
- `continue_current_line`
- `accepted_closeout`
- `pivot`
- `dead_end`

`drive_autoresearch_line()` provides a minimal load -> preflight -> decide ->
apply -> optional persist path for line workspaces.

## Review Handshake

Line-based autoresearch should be review-gated, not chat-gated.

The expected loop is:

1. iterate while the line is `active`
2. write a synthesis or provisional report
3. run scientific review
4. either accept and halt, or reject and continue with an explicit directive

The existing scientific-review stack already supplies most of this machinery.
The current generic alignment point is:

- `build_autoresearch_review_bundle()` now reads the generic workspace-layout
  helper and coerced line-state contract
- the autoresearch review path consumes line metadata through `review_context`
  instead of depending only on predictive-project heuristics

## Closeout And Pivot Policy

A line should close with one of a small set of explicit outcomes:

- continue current line
- pivot to a sequel line
- halt with accepted report
- stop with blocker / dead-end rationale

`LineCloseoutV1` captures that decision in a structured way, including:

- `outcome`
- `reason`
- `review_decision`
- `report_action`
- `claim_strength`
- `next_line_type`
- `pivot_options`
- `unresolved_blockers`

This is the mechanism that turns a dead-end into a first-class scientific or
infrastructure result rather than an untracked failure.

## Mapping To Existing BR Surfaces

This architecture is meant to sit on top of existing BR capabilities rather than
replace them.

Already reusable today:

- `services/review/autoresearch_scientific_review.py`
- `services/review/autoresearch_judgment_critic.py`
- `services/review/external_run_import.py`
- `services/review/native_review_contract.py`
- `services/review/research_episode_artifacts.py`

Still intentionally domain-specific:

- exact `line_type` vocabularies
- model families, metrics, and thresholds
- prompt addenda and controller policy text
- project-specific module registries such as line presets

## Recommended Next Steps

The generic contract layer is only the first step. The next repo-native pieces
should be:

1. report preflight
   validate required report blocks before scientific review rejects on format
2. line controller helpers
   convert review outcomes into explicit `pending_directive` and `closeout`
   updates
3. workspace import / dashboard surfaces
   let BR inspect external line workspaces as first-class line runs
4. routine triggers
   schedule or API-trigger lines only after the contract and review handshake are
   stable
