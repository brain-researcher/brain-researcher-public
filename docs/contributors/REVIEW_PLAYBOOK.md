# Brain Researcher Review Playbook

Use this playbook for product and scientific review contributions.

## Purpose

This playbook turns community review into reproducible bug reports and scientific feedback that maintainers can act on quickly.

## Project Context

Brain Researcher is in a hardening phase:

1. Core product surfaces are live.
2. Main work now is reliability, scientific rigor, and clearer UX.
3. High-quality issue reports are the fastest path to improvement.

## Scope

Use this document for:

- Studio, MCP, NeuroKG, Hypothesis, Datasets, and docs review.
- Structured issue submission through `.github/ISSUE_TEMPLATE/*`.

## Tool vs Workflow (Issue Routing)

Use this decision rule before opening an issue:

1. Tool behavior, schema, parameters, execution failure, duplicate tool names -> open a `tool` issue.
2. Node order/default parameters/compatibility inside Library pipelines -> open a `workflow` issue.
3. Not sure -> open a `tool` issue first; maintainers relabel.

## Universal Reporting Format

Use this order in every report:

1. Entry surface
2. Page URL(s)
3. Click path or reproduction steps
4. IDs and context (workflow/tool/task/node/sessionId/runId)
5. Expected behavior
6. Actual behavior
7. Suggested fix
8. Evidence (screenshots, logs, payload snippets, exact UI text)

## Reviewer Rules

1. Default to read-only review.
2. Do not click `Save governance` on Benchmark unless authorized.
3. Do not submit PHI, secrets, or private credentials.
4. Keep reports specific and ID-based.

## Good Issue Example

Use this pattern:

- Title: `Studio Validation: Data validated passes when dataset is not accessible`
- Entry surface: `Studio -> Plan -> Verify`
- IDs: `dataset=<id>`, `workflow=<name>`
- Expected: `Data validated` should stay blocked until dataset access is ready.
- Actual: `Data validated` shows passed, but run fails due to missing mount/readiness.
- Suggested fix: include dataset readiness signal in verify check and error copy.

## Review Tracks

### 1) Missing tool/workflow gaps

- Entry: `Advanced -> Tools`, then `Library`
- URL: `https://brain-researcher.com`
- Click path:
1. Search tools via `Search tools...`
2. Inspect metadata fields and duplicates
3. Search workflows via `Search workflows...`
4. Identify missing items or broken taxonomy
- Review standard:
1. Coverage gaps are concrete and high-value
2. Naming/grouping is consistent
3. Metadata is complete and sensible
- Issue form: `01-gap-tool-workflow.yml`

### 2) Existing workflow review

- Entry: `Library -> Add to Plan -> Studio -> Plan -> Review pipeline`
- URL: `https://brain-researcher.com`
- Click path:
1. Pick a workflow in Library
2. Add to Studio plan
3. Inspect Verify statuses
4. Open `Review pipeline` and inspect node order/defaults
- Review standard:
1. Node chain follows best practices
2. Defaults are scientifically defensible
3. Verify guidance is actionable when blocked
- Issue form: `02-workflow-review.yml`

### 3) Benchmark task rigor review

- Entry: `Benchmark`
- URL: `https://brain-researcher.com/benchmark`
- Click path:
1. Select benchmark dataset
2. Search task by ID/keyword
3. Inspect Scope/Goal/Input/Outputs/Pass Criteria/Expected Results
- Review standard:
1. Scope and goal alignment
2. Measurable outputs and pass criteria
3. Scientifically realistic expected results
- Issue form: `03-benchmark-review.yml`

### 4) NeuroKG definition/edge review

- Entry: `NeuroKG`
- URL: `https://brain-researcher.com/neurokg`
- Click path:
1. Find a known node
2. Inspect definition + nearby edges
3. Run `Run multihop reasoning`
4. Inspect `Open deep-research prompt`
- Review standard:
1. Definitions are accurate and complete
2. Edges avoid overclaiming
3. Multihop paths are semantically coherent
- Issue form: `04-neurokg-edge-review.yml`

### 5) Hypothesis review

- Entry: `Hypothesis`
- URLs:
- `https://brain-researcher.com/hypothesis?sessionId=session-mm88g4ch-9ojsx0&runId=hrun-mm88h8nq-weo6jx`
- `https://brain-researcher.com/hypothesis?sessionId=session-mm87c8o8-x27ht9&runId=hrun-mm87ciol-cp3r9x`
- Click path:
1. Identify stage (`clarifying`, `analysis ready`, `evidence ready`, `completed`)
2. Inspect Research Canvas consistency
3. Inspect Candidates/Evidence/Plan/Validation
- Review standard:
1. Novelty is real, not rephrasing
2. Evidence supports claims
3. No factual hallucinations
4. Plan includes leakage/confound/reproducibility logic
- Issue form: `05-hypothesis-review.yml`

### 6) MCP integration review

- Entry: Cursor / Claude Code / Codex with Brain Researcher MCP
- Click path:
1. Trigger tool search (`use brain_researcher_mcp to ...`)
2. Check schema and payload filling
3. Execute tools
4. Test boundary safety behavior
- Review standard:
1. Retrieval relevance
2. Schema/payload correctness
3. Execution reliability
4. Safety boundary enforcement
- Issue form: `06-mcp-integration.yml`

### 7) Studio blocked run review

- Entry: `Studio -> Plan -> Verify`
- URL: `https://brain-researcher.com`
- Click path:
1. New Chat
2. Set Intent/Data/Concepts/Pipeline
3. Observe blocked Verify line
4. Use `Review pipeline` and optionally `Ask Agent to fix`
- Review standard:
1. Block reason clarity
2. Unblock path clarity
3. Useful and actionable copy
- Issue form: `07-studio-blocked.yml`

### 8) Studio to MCP handoff review

- Entry: Studio plan configuration + MCP execution in IDE
- Click path:
1. Configure Studio state
2. Trigger equivalent run through MCP
3. Compare expected vs actual payload/requirements
- Review standard:
1. State transfer consistency
2. Default parity between Studio and MCP
3. No hidden required parameter drift
- Issue form: `08-studio-mcp-handoff.yml`

### 9) Dataset coverage/metadata review

- Entry: `Datasets`
- URL: `https://brain-researcher.com`
- Click path:
1. Search by dataset name/portal/keyword
2. Apply filters
3. Inspect metadata card
4. Test `View dataset` and `Add to Plan`
- Review standard:
1. Coverage quality
2. Metadata completeness/accuracy
3. Search/filter quality
4. Add-to-Plan reliability
- Issue form: `09-dataset-coverage.yml`

### 10) Docs/demo reproducibility review

- Entry: any official docs/demo trace
- Click path:
1. Follow docs exactly with zero hidden assumptions
2. Stop at first blocker
3. Capture failing step and message
- Review standard:
1. New user can complete documented flow
2. Prereqs are explicit
3. Failure guidance exists
- Issue form: `10-docs-demo-repro.yml`

### 11) Open questions

- Entry: architecture or product decision threads
- Click path:
1. State decision question
2. Capture current state
3. Propose one concrete direction
4. List tradeoffs and next steps
- Review standard:
1. Scope clarity
2. Actionable proposal
3. Explicit risks/costs
- Issue form: `11-open-question.yml`

## Labels

- `area/*` for subsystem ownership
- `type/*` for issue intent
- `status/*` for maintainer lifecycle

## Where To Start

If you are new, start with:

1. Studio blocked review (`07-studio-blocked.yml`)

Then continue with:

1. Workflow review (`02-workflow-review.yml`)
2. MCP integration review (`06-mcp-integration.yml`)
