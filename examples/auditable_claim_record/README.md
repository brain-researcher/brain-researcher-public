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

## Reproduce it yourself

This example runs on public Neurosynth data — no account or data-use agreement —
and everything the generator needs is in this repository.

### Prerequisites

- A Python environment with `nimare`, `nilearn`, and `numpy` (the environment
  used elsewhere in this repo).
- A **separate NeuroLang interpreter** for the out-of-process probabilistic-
  Datalog backend. NeuroLang pins older dependencies, so it lives in its own
  virtualenv rather than the main environment:
  ```bash
  python3.12 -m venv ~/.venvs/neurolang-py312
  ~/.venvs/neurolang-py312/bin/pip install neurolang
  ```
  The generator looks for `~/.venvs/neurolang-py312/bin/python` by default;
  point `$BR_NEUROLANG_PYTHON` (or `--venv-python`) at any interpreter that has
  `neurolang` installed.

### Steps

1. Download and convert the public Neurosynth v7 corpus (run from the repo
   root):
   ```bash
   python scripts/data/download_neurosynth_data.py   # -> data/neurosynth_nimare/neurosynth_v7/
   python scripts/data/convert_neurosynth.py         # -> data/neurosynth_nimare/neurosynth_dataset_v7.pkl
   ```
2. Run the generator, pointing it at that corpus:
   ```bash
   python scripts/autoresearch/run_neurolang_vhrl_demo.py \
     --case working_memory \
     --corpus data/neurosynth_nimare/neurosynth_dataset_v7.pkl \
     --output-dir /tmp/wm_demo
   ```

The generator seals the commitment card, runs the graded NeuroLang evidence
queries, and writes `claim_card.json`, `evidence_verdicts.json`,
`demo_bundle.json`, and a `README.md` to the output directory. The standalone
`commitment_card.json` shipped in this folder is `demo_bundle.json`'s
`calibration.commitment_card`.

### What "reproduces" means here

A fresh run reproduces the **finding** and an **internally-consistent record**:
the claim ends `weakened`, the same five checks pass and the same
`strict-evidence-profile` check fails, and `claim_card.json`'s `commitment_hash`
equals the commitment card's — so no post-hoc edit to the sealed plan could go
undetected.

The `commitment_hash` value itself is sealed per run (it covers a `locked_at`
timestamp and the exact engine version), so a fresh run produces a *different*
hash from the frozen `4871ea43…` snapshot committed here. That is expected: the
committed files are one sealed instance. The reproducible invariants are the
status, the surviving/failing checks, and the intra-run hash match — not the
hash value.

## Data

Every source used here — the public Neurosynth corpus for this example, and the
data for the other manuscript cases (including the controlled-access HCP-YA data
and the Liu et al. 2025 benchmark) — is documented with download locations in
[`DATA_SOURCES.md`](DATA_SOURCES.md).
