# Reproducibility Packs

This repository includes public-safe reproducibility packs under
[`reproducibility/`](https://github.com/brain-researcher/brain-researcher-public/tree/main/reproducibility). They are meant for reviewers and users
who want to inspect the audit record behind a Brain Researcher result without
access to private runtime logs or governed datasets.

The same reproducibility directory also contains
[`reproducibility/auditable_claim_record/`](https://github.com/brain-researcher/brain-researcher-public/tree/main/reproducibility/auditable_claim_record).
That runnable tutorial emits claim-card JSON; it has no pack manifest and is not
accepted by `reproducibility/verify.py`. The similar
`run_end_to_end.sh` and `AGENTIC_REPRODUCTION.md` filenames describe parallel
user journeys, not the same artifact contract.

## Working Directory

Commands in this page run from the **repository root**. From anywhere inside the
clone:

```bash
cd "$(git rev-parse --show-toplevel)"
```

## What A Pack Proves

Each pack has:

- `manifest.json` with sha256 checksums for shipped artifacts
- `provenance_card.md` describing the execution envelope
- `README.md` with the result boundary and rerun instructions
- optional `run/`, `source/`, `artifacts/`, and `reproduction/` files

Run:

```bash
python reproducibility/verify.py reproducibility/bounded_autoresearch_a1
python reproducibility/verify.py reproducibility/fitlins_multiverse_yeo17
```

Exit code `0` means the shipped bytes match the manifest. It does not by itself
prove that an LLM rerun will be byte-identical.

## Current Packs

| Pack | Status | Boundary |
|---|---|---|
| `bounded_autoresearch_a1` | Real recorded result | Checksum-verifiable artifacts plus a public-data headline rerun. Deeper reconstruction is governed-data-gated: HCP-YA rows, the exact 326-subject FC/behavior binding, and its subject-keyed derived component table are not redistributed. The pack includes a redacted Liu/Tian source-provenance summary with OSF node `75je2`, key checksums, component-reconstruction caveats, and the `reconstructed_not_paper_exact` boundary. |
| `fitlins_multiverse_yeo17` | Synthetic schema exemplar | Shows the run-bundle and multiverse layout. It is a format template, not a real-data result; statmap entries are `schema_only`, and its historical params do not form a current end-to-end rerun contract. |

## Reproduce From Language (Claude Code / Codex + MCP)

The real A1 pack and the auditable-claim tutorial each include an
agentic guide. These describe how a coding agent drives typed MCP steps from
natural language. They are not both packs, and recipe/validation calls do not by
themselves prove that an analysis executed. Each guide states which part is a
runnable driver and which part remains a multi-step handoff:

| Case | Shape | Agentic guide |
|---|---|---|
| Bounded autoresearch A1 | Multi-turn feature/pipeline **search** loop (edit `predict.py` → frozen evaluator → score/compare → cheap-check → freeze → confirmatory null) | [A1 agentic guide](https://github.com/brain-researcher/brain-researcher-public/blob/main/reproducibility/bounded_autoresearch_a1/AGENTIC_REPRODUCTION.md) |
| Auditable claim record | Single sealed **claim episode** (commit-before-observe → graded evidence → adjudicate → emit card) | [Claim-record agentic guide](https://github.com/brain-researcher/brain-researcher-public/blob/main/reproducibility/auditable_claim_record/AGENTIC_REPRODUCTION.md) |

Honest scope: an agent's *search path* is non-deterministic, so a rerun
reproduces the **discipline** (commit-before-observe, frozen evaluator,
cheap-check-before-expensive-compute, literature-vetoed hypotheses) and — once the
same predictor/claim is frozen — the **confirmatory numbers / verdict**, not the
exact trajectory. Connect the MCP per [`mcp.md`](mcp.md); start each loop by
calling `loop_profile_get`.

## Audit Protocol Boundary

Brain Researcher can emit richer audit bundles when work runs through the
governed engine path that creates commitment cards, claim cards, run bundles,
review verdicts, and manifests. A post-hoc or local laptop recipe can still be
auditable, but it should be described as a partial or post-hoc record unless the
commit-before-observe artifacts actually exist.

For LLM-mediated workflows, reproducibility should be judged by the recorded
tool contract, prompt/model provenance, artifact checksums, and scientific
equivalence tolerances. Do not promise byte-identical LLM traces.

## Privacy Boundary

Public packs should not contain user session logs, bearer tokens, private MCP
tool names, or machine-local absolute paths. Session access in a deployed MCP
service should remain scoped to the requesting user; public artifacts are
separate, redacted exports.

For governed datasets such as HCP-YA, a public pack should expose the source
route and checksums without shipping restricted rows. The A1 pack follows that
pattern: `artifacts/liu_source_provenance_summary.json` records the Liu FC-pyspi
OSF route, reconstruction provenance, and redaction rules while omitting raw HCP
rows, subject identifiers, raw FC files, credentials, and local absolute paths.
The shipped A1 residualised-target CSV is also row-indexed; the governed output
checksum is retained in provenance, but HCP `Subject` identifiers are not shipped.
