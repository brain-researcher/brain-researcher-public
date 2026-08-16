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

- `manifest.json` using `br.reproducibility_pack_manifest.v2`, with sha256
  checksums plus source, tool, input, seed, tolerance, and attestation metadata
- `environment.lock.json` recording either the runnable environment binding or
  an explicit `unresolved_historical` boundary
- `provenance_card.md` describing the execution envelope
- `README.md` with the result boundary and rerun instructions
- optional `run/`, `source/`, `artifacts/`, and `reproduction/` files

The manifest's `maturity` is a repository lifecycle label (`stable` or
`historical`), separate from its reproduction attestation. Source metadata also
keeps three commits distinct: `contract_authored_against_commit` is the snapshot
used to write the v2 contract; `artifact_authoring_commit` is `null` when the
historical producing commit is unavailable; and the release gate records the
containing release commit externally because a manifest cannot checksum-bind
the commit that contains itself.

Run:

```bash
python reproducibility/verify.py reproducibility/bounded_autoresearch_a1
python reproducibility/verify.py reproducibility/fitlins_multiverse_yeo17
python reproducibility/verify.py reproducibility/hcp_workflow_search
python reproducibility/verify.py reproducibility/tribe_speech_tools
```

For a v2 manifest, the verifier first checks the required metadata and
attestation shape. A malformed v2 contract fails closed with exit code `1`
before artifact hashing. Exit code `0` means the shipped bytes match the
manifest. It does not by itself prove that an LLM rerun will be byte-identical.

## Reproduction Status Vocabulary

The five levels are cumulative. `partial` records useful evidence above the
current attained level without promoting the pack to that level.

| Level | Meaning |
|---|---|
| `inspectable` | The public files, provenance, and stated boundary can be read. No checksum or execution claim is implied. |
| `integrity_verified` | Every required shipped artifact is present and matches its recorded sha256. This verifies bytes, not execution. |
| `public_runnable` | A public user can execute the documented path from the public inputs and compare its output against recorded tolerances. |
| `governed_rerun` | The governed-data or governed-runtime path has been rerun under its recorded contract. A seed subset or incomplete governed path is `partial`. |
| `fully_reproduced` | The complete declared analysis, including all required governed work and scientific comparison criteria, has been reproduced. |

`attained`, `partial`, and `not_claimed` are evidence states. The manifest's
`attestation.current_level` is always the highest cumulative `attained` level;
it must not skip a lower level.

## Current Packs

| Pack | Maturity | Current level | Higher-level evidence | Boundary |
|---|---|---|---|---|
| `bounded_autoresearch_a1` | `stable` | `public_runnable` | `governed_rerun: partial`; `fully_reproduced: not_claimed` | Checksum-verifiable artifacts plus a public-data headline rerun. Deeper reconstruction is governed-data-gated: HCP-YA rows, the exact 326-subject FC/behavior binding, and its subject-keyed derived component table are not redistributed. The pack includes a redacted Liu/Tian source-provenance summary with OSF node `75je2`, key checksums, component-reconstruction caveats, and the `reconstructed_not_paper_exact` boundary. |
| `fitlins_multiverse_yeo17` | `historical` | `inspectable` | `integrity_verified: partial`; all execution levels `not_claimed` | Shows the run-bundle and multiverse layout. It is a format template, not a real-data result; statmap entries are `schema_only`, and its historical params do not form a current end-to-end rerun contract. |
| `hcp_workflow_search` | `stable` | `integrity_verified` | `public_runnable: partial`; governed and full reruns `not_claimed` | Preserves the 116-candidate ledger, frozen matched summaries, aggregate cohort counts, and a Figure 5 renderer. It excludes restricted HCP inputs, participant/family identifiers, out-of-fold predictions, and private run artifacts. |
| `tribe_speech_tools` | `stable` | `integrity_verified` | `public_runnable: partial`; governed and full reruns `not_claimed` | Preserves the full 15-pair screen and all plotted recurring/new-collection geometry cells, with a Figure 6 renderer. It excludes audio, item-level metadata, representations, checkpoints, and the original permutation execution. |

The HCP and TRIBE rows above describe the immutable replay packs, not every
source file elsewhere in the repository. Canonical HCP MVE100/recovery/R2/R3
drivers are now shipped under `src/brain_researcher/research/predictive/`, and
the TRIBE speech--tools feature-to-result evaluators are shipped under
`src/brain_researcher/research/discovery/programs/`. HCP execution still
requires governed inputs and explicit authorization. TRIBE raw-audio
acquisition, checkpoint access, and representation extraction remain external.
Accordingly, neither pack is promoted to `governed_rerun` or
`fully_reproduced` by the code release alone.

## Reproduce From Language (Claude Code / Codex + MCP)

The real A1 pack and the auditable-claim tutorial each include an
agentic guide. These describe how a coding agent drives typed MCP steps from
natural language. They are not both packs, and recipe/validation calls do not by
themselves prove that an analysis executed. Each guide states which part is a
runnable driver and which part remains a multi-step handoff:

| Case | Status | Shape | Agentic guide |
|---|---|---|---|
| Bounded autoresearch A1 | `public_runnable` | Multi-turn feature/pipeline **search** loop (edit `predict.py` → frozen evaluator → score/compare → cheap-check → freeze → confirmatory null) | [A1 agentic guide](https://github.com/brain-researcher/brain-researcher-public/blob/main/reproducibility/bounded_autoresearch_a1/AGENTIC_REPRODUCTION.md) |
| Auditable claim record, NiMARE light path | `public_runnable` tutorial path, not a manifest-backed pack | Single sealed **claim episode** (commit-before-observe → graded evidence → adjudicate → emit card) | [Claim-record agentic guide](https://github.com/brain-researcher/brain-researcher-public/blob/main/reproducibility/auditable_claim_record/AGENTIC_REPRODUCTION.md) |
| Auditable claim record, historical NeuroLang snapshot | `inspectable` only | The committed JSON records an older NeuroLang result, but the historical environment is not currently installable from this repository | [Claim-record README](https://github.com/brain-researcher/brain-researcher-public/blob/main/reproducibility/auditable_claim_record/README.md#reference-path-neurolang-engine-behind-the-committed-card) |

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

The HCP workflow-search pack follows the same privacy boundary at an aggregate
level: it ships candidate scores and repeat-level score differences, but no HCP
row binding or prediction vector. The TRIBE speech--tools pack ships only
collection-level geometry summaries and open-screen aggregates, not audio,
features, checkpoints, or item identifiers.
