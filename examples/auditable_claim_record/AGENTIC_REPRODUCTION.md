# Agentic reproduction — drive the auditable claim record from language with Claude Code / Codex + MCP

`README.md` regenerates the three JSON files by running the generator script.
This file describes reproducing the record the way the platform produces it: a
coding agent (Claude Code / Codex) driving a **sealed claim episode** through the
Brain Researcher MCP, from natural language.

Unlike the bounded-autoresearch A1 case (a multi-turn *search* loop), this is a
**single episode** with a fixed shape:

> **commit before observe** → graded evidence queries → adjudicate → emit card

The discipline is structural: the commitment card is sealed and hash-verified
*before* any evidence is queried, so a post-hoc change to the pre-registered plan
is detectable. The agent frames the claim and drives the tools; it cannot make
the record self-consistent after seeing the evidence.

## Connect the MCP

See [`../../docs/mcp.md`](../../docs/mcp.md). For Claude Code against a hosted
server, `.mcp.json`:

```jsonc
{ "mcpServers": { "brain-researcher": {
  "type": "http",
  "url": "https://<PUBLIC_HOSTNAME>/mcp",
  "headers": { "Authorization": "Bearer ${BR_MCP_TOKEN}",
               "Accept": "application/json, text/event-stream" } } } }
```

Or run locally: `scripts/mcp/start_http_local.sh`. Sanity-check with `server_info`.

## The episode, step by step (each step ↔ the MCP tool that makes it typed)

| Step | What the agent does, in language | MCP tool(s) |
|---|---|---|
| Frame the claim + scope | State the working-memory → dlPFC claim, its allowed rival (`attention`), scope (Neurosynth v7, fMRI, NeuroLang), and success/failure criteria | *(agent-side)* |
| Ground the terms | Resolve the two big neuroimaging mapping uncertainties — coordinate→region and task→ontology (the compiler's explicit "sorries") | `grounding_resolve`, `grounding_gate_evidence_basis` |
| Seal the commitment (commit-before-observe) | Freeze the claim text, rival, scope, criteria, and a `commitment_hash` **before** querying evidence | sealed by the episode engine; `claim_commit` adjudicates a committed claim over gathered evidence |
| Compile to a gated verdict | Compile the claim; a **mandatory sensitivity sweep** (lenient vs conservative evidence bar) flags it *threshold-fragile*; named uncertainty is never folded into association strength | `neuroclaim_compile` |
| Graded evidence queries | forward-default, forward-strict, dlPFC-IPS network-coactivation, specificity-not-attention | `neuroclaim_compile` (NimareBackend / NeuroLang); or `kg_verify_hypothesis` |
| Adjudicate → status | Default profile supports it; conservative profile makes it threshold-fragile ⇒ status **`weakened`** (a qualified claim) | verdict from `neuroclaim_compile` |
| Report / review gate | Gate the claim through the evidence kernel; escalate if needed | `report_claim_evidence_check`, `request_scientific_review` |

The one-shot realization of exactly this episode is the shipped generator,
`scripts/autoresearch/run_neurolang_vhrl_demo.py` (it seals via `lock_commitment`,
runs the graded queries, and emits `claim_card.json` / `evidence_verdicts.json` /
`demo_bundle.json`). The agentic path calls the same machinery through typed MCP
tools instead of one script.

## What "reproduce" means here (honest scope)

This episode is **more deterministic than the A1 search loop**: a fixed corpus
(public Neurosynth v7) and fixed queries. What reproduces is the **finding** —
status `weakened`, the same five surviving checks and the single failing
`strict-evidence-profile` check — and the **internal consistency** (the claim
card's `commitment_hash` equals the commitment card's). The `commitment_hash`
*value* is sealed per run (it covers a timestamp + the engine version), so a
fresh run differs from the frozen `4871ea43…` snapshot here — expected, not a
failure (same caveat as `README.md`).

Verified end to end: running the generator on the public corpus reproduces
`status=weakened` with matching intra-run hashes (see `README.md`).

**Cost note (honest):** `neuroclaim_compile` with `backend="nimare"` runs a real
CBMA over the full Neurosynth corpus and, doubled by the sensitivity sweep, is a
long-running call — it exceeded a ~2-minute interactive timeout in our check. For
an interactive MCP demo, pass `run_sensitivity=false` and/or a smaller
`$BR_NEUROCLAIM_CORPUS`; for the full record, use the generator.

## A starter prompt (paste into Claude Code with the MCP connected)

> You are producing an auditable claim record for the claim: "Working-memory-
> labeled Neurosynth studies show dlPFC activation and dlPFC-IPS coactivation
> within coordinate evidence," scoped to Neurosynth v7 / fMRI / a NeuroLang
> probabilistic-Datalog workflow, with `attention` as the allowed rival
> explanation. First call `server_info`, then `grounding_resolve` /
> `grounding_gate_evidence_basis` to ground the region and task terms. Seal the
> commitment (claim text, rival, scope, success/failure criteria) BEFORE querying
> any evidence. Then compile the claim with `neuroclaim_compile` (run the
> mandatory lenient-vs-conservative sensitivity sweep) and read off the graded
> evidence verdicts (forward-default, forward-strict, network-coactivation,
> specificity-not-attention). Report the final status and confirm the claim
> card's `commitment_hash` equals the sealed commitment card's. Do not weaken or
> restate the sealed claim after seeing the evidence; if the MCP requests
> clarification, ask me exactly one question.
