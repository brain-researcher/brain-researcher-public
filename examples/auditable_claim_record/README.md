# A worked auditable claim record

This directory is the concrete, openable example of an **auditable claim record**
referenced in the Brain Researcher manuscript (Supplementary Methods S8.5;
Appendix G). It is the record a single Brain Researcher study episode produces,
exported as plain JSON so anyone, not just the person who ran the analysis, can
open it and check what the analysis actually claimed and whether the evidence
supports it.

It is built entirely on **public Neurosynth coordinate evidence** (a
working-memory claim), so it can be redistributed here in full. Collaborator
episodes that run on controlled-access data (for example the schizophrenia
NeuroMark episode in the paper) produce the *same* record, but their cards
cannot be shipped alongside the restricted data; this public example is the
stand-in you can point to.

## What the claim was

> Working-memory-labeled Neurosynth studies show dlPFC activation and dlPFC-IPS
> coactivation within coordinate evidence.

Final card status: **`weakened`** — the association holds under the default
evidence profile but is threshold-fragile under the conservative one, so the
implementation records a lower-strength evidence status instead of reporting
clean support or dropping the claim. In the manuscript's six-state reporting
vocabulary, this rolls up to a **qualified** claim: support is present only with
an explicit conservative-profile caveat.

## The three files

| File | What it is |
|------|------------|
| `commitment_card.json` | Written **before** the analysis ran. Freezes the claim text, the allowed alternative explanation (`attention`), the scope boundary, and the explicit success and failure criteria, and stores a `commitment_hash`. |
| `claim_card.json` | Written **after** review. Records the final status, the checks the claim survived and the one it failed, its scope boundary, and what evidence is still required. It points back to the commitment card by hash. |
| `evidence_verdicts.json` | The graded evidence the claim card draws on: four verdicts (`forward_default`, `forward_strict`, `network_coactivation`, `specificity_excluding_rivals`), each with a reproducible query. |

## Where to look first

Open **`claim_card.json`**. Every field the manuscript paragraph names is right
there:

- `claim_text` — the exact claim under test
- `status` — `weakened`, an implementation-level evidence status: the default profile supports the association, but the conservative profile makes it threshold-fragile. This is not a seventh manuscript state; it rolls up to a qualified claim because the support survives only with a stated caveat.
- `commitment_hash` — `4871ea43…`; the same hash is stored in `commitment_card.json`, so any post-hoc change to the pre-registered plan is detectable
- `survived_checks` — the five checks that passed (structure, associational reasoning mode, default forward evidence, specificity-not-attention, dlPFC-IPS network coactivation)
- `failed_checks` — the one that failed: `strict-evidence-profile` (the same forward query under the conservative lift bar, which is why the status is *weakened*)
- `scope_boundary` — Neurosynth v7, fMRI, NeuroLang probabilistic-Datalog workflow family
- `next_required_evidence` — what would be needed to promote it (independent-dataset replication; no causal language from coordinate meta-analysis; a pipeline-level multiverse before binding a dataset-specific contrast)

That is the whole record — there is nothing hidden behind it. The appendix in
the paper only walks through the same schema field by field.

## Provenance

These files were emitted by the demo generator
`scripts/autoresearch/run_neurolang_vhrl_demo.py`; the generated run bundle lives
under `docs/results/neurolang_vhrl_working_memory_demo/`, and this directory is
the compact public-facing copy. The `commitment_hash` in `claim_card.json` and
`commitment_card.json` match, so the record is internally consistent.
