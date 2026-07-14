# Agentic reproduction — drive A1 from language with Claude Code / Codex + MCP

`REPRODUCTION.md` reproduces the A1 **numbers** by running the frozen scripts.
This file reproduces A1 the way it was actually produced: a coding agent
(Claude Code, occasionally Codex) driving the loop **one turn at a time from
natural language**, through the Brain Researcher MCP. This is the M1 claim of the
case report — the discipline is an architectural property of the loop, not of the
agent's good intentions.

The shipped `drive_from_language.py` reproduces only the **KG-as-prior
precondition** as a typed MCP call. The complete multi-turn search loop is an
agent-driven procedure described below; it is not packaged as one deterministic
command and it requires additional run persistence before `run_bundle_get`,
`run_scorecard`, or `run_compare` can inspect a `run_id`.

## Working directory and scratch copy

Commands in this guide run from the **repository root** unless a block says
otherwise. From anywhere inside the clone:

```bash
export BR_PUBLIC_ROOT="$(git rev-parse --show-toplevel)"
cd "$BR_PUBLIC_ROOT"
```

The published pack is manifest-pinned. Do not edit its `scripts/predict.py` in
place and then expect `verify.py` to pass. For a search experiment, copy the pack
to an untracked scratch directory and let the agent work there:

```bash
export A1_WORK_DIR="$(mktemp -d /tmp/bounded-autoresearch-a1.XXXXXX)"
cp -a reproducibility/packs/bounded_autoresearch_a1/. "$A1_WORK_DIR/"
cd "$A1_WORK_DIR"
```

The driver commands below use the immutable published copy, so return to the
repository root first.

## The division of labour (what the MCP does vs what the agent does)

The deployed MCP hands external agents a machine-readable loop profile; fetch it
first with `loop_profile_get` (`profile_id="external_coding_v1"`). In short:

- **The agent owns code mutation.** It edits only `scripts/predict.py` (the
  editable predictor). The MCP **never writes code into the repo**.
- **The MCP owns discovery, recipes, observation, comparison, KG, and review.**
  `scripts/run_prediction.py` is the SHA-pinnable *immutable evaluator* — the
  agent cannot edit it, mock the folds, or peek at fold assignments before
  scoring.

Recommended call order (from the profile):
`loop_profile_get → tool_search → tool_get → get_execution_recipe →
pipeline_plan_validate → run_bundle_get → run_scorecard → run_compare`.

## Run the KG-as-prior step as one command

[`drive_from_language.py`](drive_from_language.py) runs the loop's language-driven
precondition — the KG hypothesis step — as a single MCP call: from a
natural-language query it surfaces falsifiable connectivity→behavior leads and
prints what the literature check let survive versus vetoed / downranked.

```bash
cd "$BR_PUBLIC_ROOT"
# needs a reachable MCP (hosted BR_MCP_HTTP_URL + BR_MCP_TOKEN, or a local server)
python reproducibility/packs/bounded_autoresearch_a1/drive_from_language.py
# offline, against the captured demo call:
python reproducibility/packs/bounded_autoresearch_a1/drive_from_language.py \
  --from-file reproducibility/packs/bounded_autoresearch_a1/artifacts/agentic_kg_hypothesis_demo.json
```

Sampling + verification are budget-bounded and non-deterministic; what is
invariant is the machinery (falsifier-carrying leads, duplicate collapse,
same-family downrank, literature veto). The full loop is the starter prompt below.

## Connect the MCP

See [`docs/mcp.md`](../../../docs/mcp.md) for the full connection guide. In brief,
for Claude Code against a hosted server:

```bash
export BR_MCP_HTTP_URL=https://your-host.example/mcp
export BR_MCP_TOKEN=your-token-from-the-service
```

```jsonc
// .mcp.json
{ "mcpServers": { "brain-researcher": {
  "type": "http",
  "url": "https://<PUBLIC_HOSTNAME>/mcp",
  "headers": { "Authorization": "Bearer ${BR_MCP_TOKEN}",
               "Accept": "application/json, text/event-stream" } } } }
```

The live KG step needs a populated BR-KG plus its literature-verification
backend. A bare public clone does not contain that graph. Prefer the hosted MCP;
otherwise use a local deployment whose KG has already been populated. Merely
starting an empty local server is a transport smoke, not an A1 KG reproduction.

For an already configured local deployment, use its full project environment,
not the A1 light environment. From the repository root, start the server in
terminal A:

```bash
python -m pip install -e .
bash scripts/mcp/start_http_local.sh
```

Open terminal B anywhere inside the same clone, activate the same environment,
recompute the root for that shell, and run the driver. It defaults to
`http://127.0.0.1:7000/mcp` and uses the repository token resolver when
available:

```bash
export BR_PUBLIC_ROOT="$(git rev-parse --show-toplevel)"
cd "$BR_PUBLIC_ROOT"
python reproducibility/packs/bounded_autoresearch_a1/drive_from_language.py
```

Sanity-check the connected MCP with `server_info` before relying on any other
tool. Without populated KG data, use the shipped `--from-file` command above to
inspect and validate the captured public demo instead. Never paste a token into
a committed file.

## The loop, step by step (each A1 step ↔ the MCP tool that makes it a typed action)

| A1 step | What the agent does, in language | MCP tool(s) |
|---|---|---|
| Surface a hypothesis | Ask the KG which connectivity statistic is linked to the target trait in the literature; keep only those that survive literature verification | `kg_search_nodes` → `kg_hypothesis_workflow` |
| Propose a pipeline edit | In the scratch copy, read the experiments ledger and edit `scripts/predict.py` (a pyspi statistic, a feature filter, a model family, a hyperparameter) | *(agent-side; MCP does not touch code)* |
| Evaluate under the frozen protocol | Get a recipe and run `run_prediction.py` over the shipped target + fetched FC features. A direct local invocation returns JSON but does not itself create a persisted MCP `run_id`. | `get_execution_recipe`; `run_bundle_get` only after a governed run is persisted |
| Score / compare vs baseline | Normalize the result; keep or discard | `run_scorecard`, `run_compare` |
| Cheap-check → kill / redesign | Apply the cheap-in-house check; if a branch fails its retention bar, convert it into a covariate-aware redesign | `run_scorecard` + `scientific_review` family |
| Freeze + confirmatory null | Freeze the predictor; run the family-block / max-T / max-over-pipelines nulls | `get_execution_recipe` + review (needs HCP Restricted `Family_ID`) |
| Review gate | Decide accept / spawn sequel thread / reject | `request_scientific_review`, `run_scientific_review` |

Data: in the scratch pack, the FC features come from
`scripts/fetch_fc_features.py` (public); the
headline redesign→recovery loop runs on public data. Rebuilding the target and
the confirmatory null need staged HCP data (see `REPRODUCTION.md`).

## What "reproduce" means here (honest scope)

The **search path is not deterministic** — a fresh agent re-derives its own
sequence of `predict.py` edits and may not retrace the exact same trajectory.
What reproduces is (a) the **discipline** (commit-before-observe, frozen
evaluator, cheap-check-before-expensive-compute, literature-vetoed hypotheses),
and (b) once you freeze the *same* predictor, the **confirmatory numbers**
(`ICA_Cognition` fold-mean r ≈ 0.183, aggregate ≈ 0.151). That the trajectory
varies while the discipline holds *is* the M1 claim.

The evaluator itself is **deterministic**, so "not identical" never comes from
drift: a captured loop turn
([`artifacts/agentic_loop_turn_demo.json`](artifacts/agentic_loop_turn_demo.json))
shows the shipped predictor scoring `ICA_Cognition` r = 0.183158 on two
back-to-back runs (identical `predict_sha256`, equal to the published number),
and a one-line predictor edit moving it to 0.194154 with a *changed*
`predict_sha256` — the score moves only because the predictor changed, and the
evaluator records which predictor produced it.

## Live example — the KG hypothesis step, run against the deployed MCP

Calling `kg_hypothesis_workflow` (seeded from a real weighted-phase-lag-index
resting-state connectivity publication, `pmid:27920976`) returns structured,
falsifiable hypotheses **and vetoes the ones the literature contradicts** — the
same surface-then-verify-then-veto machinery the case report's §3.3 wPLI /
IllicitDrugUse lead exercised:

- each returned hypothesis carries a `statement`, `mechanism`,
  `independent_variable` / `dependent_variable` / `control_condition`,
  `minimal_test`, and an explicit `falsifier`, plus novelty / coherence /
  feasibility / OOD scores;
- candidates are checked against a literature store, and at least one was
  returned with `verification_status: "vetoed"`, `verification_reason:
  "literature_contradiction"` (with the contradicting paper cited) — the loop
  rejecting a tempting-but-unsupported lead, not the agent choosing to.

This is the KG-as-prior step of the loop working end to end from a natural-language
query — the precondition for every downstream typed, verifiable action. The
captured call (params + the surviving hypothesis + the literature-vetoed
candidate + the deployed server's `contract_version` / `toolset_hash`) is saved
at [`artifacts/agentic_kg_hypothesis_demo.json`](artifacts/agentic_kg_hypothesis_demo.json).

## A starter prompt (paste into Claude Code with the MCP connected)

> You are driving the Brain Researcher external-coding loop to reproduce the
> bounded_autoresearch_a1 case. First call `loop_profile_get`
> (`external_coding_v1`) and follow its call order. Work only in the scratch copy
> of the pack, not the manifest-pinned published directory. Run
> `scripts/fetch_fc_features.py` once to stage the public FC features.
> Treat `scripts/run_prediction.py` as the immutable evaluator and
> `scripts/predict.py` as the only file you may edit. Loop: (1) use
> `kg_hypothesis_workflow` to surface a connectivity-statistic→behavior lead and
> keep only literature-survived ones; (2) edit `predict.py` to materialise one
> pipeline change; (3) get the execution recipe and run the evaluator; (4) use
> `run_scorecard` / `run_compare` against your baseline and append a ledger row
> with a self-critique; (5) apply the cheap-in-house check and, if a load-bearing
> branch fails its retention bar, convert it into a covariate-aware redesign.
> Keep going until the search converges, then freeze and report. Do not edit the
> evaluator, mock the folds, or claim significance before the frozen confirmatory
> step. Ask me exactly one question if the MCP requests clarification.
