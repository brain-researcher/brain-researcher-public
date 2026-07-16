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

## Working directory and prerequisites

Every shell command below runs from the **repository root** unless stated
otherwise. From anywhere inside the clone:

```bash
cd "$(git rev-parse --show-toplevel)"
```

This agentic path requires a reachable Brain Researcher MCP. It is separate from
the no-MCP light path in `README.md`. The driver makes a call sequence, not one
remote call: it checks `server_info`, then calls `neuroclaim_compile`; the async
path additionally starts and polls a background compile.

## Run the language step

[`drive_from_language.py`](drive_from_language.py) is the scripted realization of
the compile step below: it takes the claim as natural language, calls
`server_info` then `neuroclaim_compile` through the MCP, and prints the gated
verdict with its named-uncertainty vector and re-runnable query.

```bash
# needs a reachable MCP (hosted BR_MCP_HTTP_URL + BR_MCP_TOKEN, or a local server)
python reproducibility/auditable_claim_record/drive_from_language.py --full --async
```

That is the recommended full sensitivity run. For a faster connectivity and
compile smoke without the sensitivity sweep, omit `--full --async`; the returned
verdict then carries a robustness-unknown caveat. To report the conservative bar:

```bash
python reproducibility/auditable_claim_record/drive_from_language.py \
  --strictness conservative --full --async
```

`--full` adds the mandatory lenient-vs-conservative sweep (a second, conservative
verify pass). Because that pass is a whole extra evidence query, `--async` routes
it through `neuroclaim_compile_start` + polling so it never blocks on an
interactive MCP timeout — the driver prints one status line per poll.
`--strictness` selects the *reported* bar. The sweep measures a stricter bar when
one exists; `conservative` is already the strictest profile, so its additional
sweep is a no-op.

A coding agent would drive the same tools conversationally from the starter
prompt at the bottom of this file. The steps below are what that call sequence is.

## Connect the MCP

See [`../../docs/mcp.md`](../../docs/mcp.md). For Claude Code against a hosted
server, export the runtime variables in your shell:

```bash
export BR_MCP_HTTP_URL=https://your-host.example/mcp
export BR_MCP_TOKEN=your-token-from-the-service
```

For Claude Code's persistent configuration, the equivalent `.mcp.json` is:

```jsonc
{ "mcpServers": { "brain-researcher": {
  "type": "http",
  "url": "https://<PUBLIC_HOSTNAME>/mcp",
  "headers": { "Authorization": "Bearer ${BR_MCP_TOKEN}",
               "Accept": "application/json, text/event-stream" } } } }
```

For a local MCP using the NiMARE backend, install the current clone and NiMARE,
stage the public corpus, bind that corpus in the server environment, and then
start the server in terminal A:

```bash
python -m pip install \
  -c reproducibility/auditable_claim_record/constraints-py311.txt \
  -e ".[mcp]" nimare nilearn
python scripts/data/download_neurosynth_data.py
python scripts/data/convert_neurosynth.py
export BR_NEUROCLAIM_CORPUS="$PWD/data/neurosynth_nimare/neurosynth_dataset_v7.pkl"
export BR_NEUROCLAIM_SOURCE_DIR="$PWD/data/neurosynth_nimare/neurosynth_v7"
bash scripts/mcp/start_http_local.sh
```

The conversion creates
`neurosynth_dataset_v7.pkl.provenance.json`. Local loaders verify that sidecar,
the pickle checksum, and the pinned raw `source_manifest.json` before accepting
the corpus. There is no `~/.nimare` fallback and an arbitrary pickle plus an
unrelated valid source directory is rejected.

Open terminal B anywhere inside the same clone, activate the same environment,
return to the repository root, and run the driver. Its default URL is
`http://127.0.0.1:7000/mcp`:

```bash
cd "$(git rev-parse --show-toplevel)"
python reproducibility/auditable_claim_record/drive_from_language.py --full --async
```

Sanity-check the connection with `server_info`. Never commit a bearer token.

## The episode, step by step (each step ↔ the MCP tool that makes it typed)

| Step | What the agent does, in language | MCP tool(s) |
|---|---|---|
| Frame the claim + scope | State the working-memory → dlPFC claim, its allowed rival (`attention`), scope (Neurosynth v7, fMRI, NeuroLang), and success/failure criteria | *(agent-side)* |
| Ground the terms | Resolve the two big neuroimaging mapping uncertainties — coordinate→region and task→ontology (the compiler's explicit "sorries") | `grounding_resolve`, `grounding_gate_evidence_basis` |
| Seal the commitment (commit-before-observe) | Freeze the claim text, rival, scope, criteria, and a `commitment_hash` **before** querying evidence | sealed by the episode engine; `claim_commit` adjudicates a committed claim over gathered evidence |
| Compile to a gated verdict | Compile the claim; a **mandatory sensitivity sweep** (reported bar vs a strictly more conservative one) can flag it *threshold-fragile*; named uncertainty is never folded into association strength | `neuroclaim_compile` (or `neuroclaim_compile_start` + `neuroclaim_compile_get` to run the sweep off the interactive path) |
| Graded evidence queries | forward-default, forward-strict, dlPFC-IPS network-coactivation, specificity-not-attention | `neuroclaim_compile` (NimareBackend / NeuroLang); or `kg_verify_hypothesis` |
| Adjudicate → status | Default profile supports it; conservative profile makes it threshold-fragile ⇒ status **`weakened`** (a qualified claim) | verdict from `neuroclaim_compile` |
| Report / review gate | Gate the claim through the evidence kernel; escalate if needed | `report_claim_evidence_check`, `request_scientific_review` |

The one-shot realization of exactly this episode is the shipped generator,
`scripts/autoresearch/run_auditable_claim_demo.py` (it seals and persists
`commitment_card.json` before the first evidence query, then runs the graded
queries and emits `claim_card.json` / `evidence_verdicts.json` /
`demo_bundle.json`). The agentic path calls the same machinery through typed MCP
tools instead of one script.

## What "reproduce" means here (honest scope)

This episode is **more deterministic than the A1 search loop**: a fixed corpus
(public Neurosynth v7) and fixed queries. What reproduces is a **stable finding
per evidence model** — the NeuroLang reference path lands `weakened` (five
surviving checks + the single failing `strict-evidence-profile` check), the
nimare light default lands `supported_within_scope` — plus the **internal
consistency** that holds either way (the claim card's `commitment_hash` equals the
commitment card's). New cards hash the engine name/version/adapter and exact
rubric content hashes, but deliberately exclude `locked_at`; the timestamp says
when sealing occurred, not what was sealed. Clone location therefore does not
change the hash. The frozen `4871ea43…` reference predates the typed engine field,
so its NeuroLang version is inspectable in the evidence file but is not part of
that historical commitment hash (same boundary as `README.md`).

The committed authoring run recorded `status=weakened` with matching intra-run
hashes on the NeuroLang backend; the current public NiMARE path reproduces
`supported_within_scope`. This public checkout does not presently ship a pinned,
working NeuroLang installation recipe, so treat the first statement as recorded
authoring validation rather than a turnkey clean-checkout rerun (see
`README.md`).

**Backend ⇒ status (read this before comparing outputs).** The frozen record in
this folder (`4871ea43…`, status **`weakened`**) is the **NeuroLang reference
path**: its probabilistic-Datalog evidence bar, doubled by the conservative
sweep, flags the claim threshold-fragile. The **default light path**
(`backend="nimare"`) returns **`supported_within_scope`**. Its automatically
resolved forward term query uses NiMARE MKDAChi2; the specificity and network
contrasts use coordinate-set arithmetic rather than a single CBMA. Both are
honest verdicts of the
same claim under different evidence models; the point of the record is the
*machinery* (sealed commitment, named uncertainty kept as its own vector, a
mandatory sweep), not one magic status. `README.md` states this same split.

**Cost / timeout note (honest).** The sensitivity sweep is a second evidence
query, so a synchronous `--full` compile roughly doubles the call. With the
`kg_verify` backend (a live graph re-query per bar) the synchronous call exceeded
a ~2-minute interactive timeout in our check. The fix is the async path:
`neuroclaim_compile_start` runs the sweep as a background run and you poll
`neuroclaim_compile_get(run_id)` (driver: `--async`) — no interactive timeout.
`nimare` is fast enough to run `--full` synchronously; `--full --async` is the
safe default for any backend.

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
