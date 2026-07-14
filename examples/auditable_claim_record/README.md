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

This directory is a **worked tutorial**, not a formal reproducibility pack. It
has no `manifest.json` or `provenance_card.md`, and
`reproducibility/verify.py` does not accept it. Manifest-backed result and schema
packs live under [`../../reproducibility/`](../../reproducibility/); the folder
split is intentional even though both surfaces include similarly named rerun
guides.

## Working directory

Unless a block explicitly says otherwise, run every command below from the
**repository root**, the directory containing `pyproject.toml`, `examples/`, and
`scripts/`. From anywhere inside the clone:

```bash
cd "$(git rev-parse --show-toplevel)"
```

In these commands, `python` and `python -m pip` refer to the same active conda
environment or virtual environment.

## What the claim was

> Working-memory-labeled Neurosynth studies show dlPFC activation and dlPFC-IPS
> coactivation within coordinate evidence.

Final card status: **`weakened`** — the association holds under the default
evidence profile but is threshold-fragile under the conservative one, so the
implementation records a lower-strength evidence status instead of reporting
clean support or dropping the claim. In the manuscript's six-state reporting
vocabulary, this rolls up to a **qualified** claim: support is present only with
an explicit conservative-profile caveat.

(This committed status is from the **NeuroLang** reference engine. Reproducing
the example on the default **NiMARE** backend lands `supported_within_scope`
instead, because that engine clears the strict bar; see
[Reproduce it yourself](#reproduce-it-yourself) for why both are faithful.)

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

This example runs on public Neurosynth data — no account or data-use agreement.
You do **not** need to start the Brain Researcher services or MCP. The run does
need the Python package from this clone; the script installs it in editable mode
along with the light NiMARE dependencies.

For a new clone, this is the complete light path tested with Python 3.11:

```bash
git clone https://github.com/brain-researcher/brain-researcher-public.git
cd brain-researcher-public
python3.11 -m venv ~/.venvs/br-claim-repro
source ~/.venvs/br-claim-repro/bin/activate
bash examples/auditable_claim_record/run_end_to_end.sh
```

The shell script does **not** create or activate an environment. It installs
`brain_researcher`, NiMARE, and Nilearn into the environment that is already
active; downloads and converts Neurosynth under
`data/neurosynth_nimare/`; writes the generated record to
`/tmp/auditable_claim_e2e` by default; and asserts the expected status and
evidence fields. Pass a different output directory as its first argument.

To reproduce it the way the platform produces it — a coding agent driving the
sealed claim episode **from language** through the MCP — run
[`drive_from_language.py`](drive_from_language.py) (a small MCP call sequence:
`server_info`, then compile or start-and-poll) or follow the full episode in
[`AGENTIC_REPRODUCTION.md`](AGENTIC_REPRODUCTION.md).

The rest of this section is the same chain, step by step. There are two evidence
backends. The **NiMARE backend is the default** and the
light path a reader should start with; the **NeuroLang backend** is the
reference engine that produced the exact sealed card committed in this folder.

### Light path (default: NiMARE)

Runs in-process against the public Neurosynth coordinate/term corpus. No second
interpreter, no pinned legacy dependencies.

1. Install this clone and the backend into an isolated Python 3.10+ environment
   (tested with Python 3.11), from the repository root:
   ```bash
   python -m pip install -e . nimare nilearn "numpy>=1.24"
   ```
2. Download and convert the public Neurosynth v7 corpus:
   ```bash
   python scripts/data/download_neurosynth_data.py   # -> data/neurosynth_nimare/neurosynth_v7/
   python scripts/data/convert_neurosynth.py         # -> data/neurosynth_nimare/neurosynth_dataset_v7.pkl
   ```
3. Run the generator (NiMARE is the default backend, so `--backend` is optional):
   ```bash
   python scripts/autoresearch/run_auditable_claim_demo.py \
     --case working_memory \
     --corpus data/neurosynth_nimare/neurosynth_dataset_v7.pkl \
     --output-dir /tmp/wm_demo
   ```
   A second case, `--case response_inhibition_boundary`, is also included; it is
   a deliberate boundary case that lands `unresolved` (the ACC / response-
   inhibition association does not clear the evidence bar), so you can see the
   record faithfully report a *non*-supported claim.

The generator seals the commitment card, runs the four graded evidence queries
(forward association under two profiles, specificity against the rival term, and
region co-activation), and writes `claim_card.json`, `evidence_verdicts.json`,
`demo_bundle.json`, and a `README.md` to the output directory. The standalone
`commitment_card.json` shipped in this folder is `demo_bundle.json`'s
`calibration.commitment_card`.

On the NiMARE backend the working-memory claim lands **`supported_within_scope`**:
the dlPFC association clears the bar under *both* the default and the strict
evidence profile, and the specificity and co-activation checks pass. Each verdict
in `evidence_verdicts.json` carries its real numbers — study counts, the reverse-
inference statistic, the specificity and co-activation lifts — and a
`reproducible_query` you can re-run. Forward inference uses NiMARE's MKDAChi2
estimator when the term resolves automatically. The specificity and network
queries use coordinate-set arithmetic over the corpus (each verdict identifies
its inference path), because those compositional contrasts are not expressible
as a single NiMARE CBMA.

### Reference path (NeuroLang) — reproduces the exact committed card

The committed `claim_card.json` / `commitment_card.json` / `evidence_verdicts.json`
(status **`weakened`**, hash `4871ea43…`) were produced by the out-of-process
NeuroLang probabilistic-Datalog engine. That engine finds the same dlPFC
association but rules it *threshold-fragile* under the strict profile, which is
why the reference card is `weakened` rather than `supported_within_scope`. If you
want to regenerate that exact card family, use the NeuroLang backend.

NeuroLang pins older dependencies, so it lives in its own virtualenv. The install
that works today (the released `neurolang` does not cap NumPy/SciPy, and its
current versions break the alpha) is:

```bash
python3.11 -m venv ~/.venvs/neurolang
~/.venvs/neurolang/bin/pip install "numpy<2" "scipy<1.13" neurolang
```

- The `"numpy<2" "scipy<1.13"` pins are required: a bare `pip install neurolang`
  pulls NumPy 2.x (removes `np.sctypes`) and SciPy ≥1.13 (removes
  `scipy.linalg.kron`), and NeuroLang's import fails on both.
- NeuroLang needs `pysdd`. On Linux it installs from a manylinux wheel; on macOS
  there is no wheel, so `pip` compiles it — you need a C toolchain (Xcode command
  line tools) for the NeuroLang path on a Mac. The NiMARE light path above has no
  such requirement.

Then point the generator at that interpreter and select the backend:

```bash
BR_NEUROLANG_PYTHON=~/.venvs/neurolang/bin/python \
python scripts/autoresearch/run_auditable_claim_demo.py \
  --case working_memory --backend neurolang \
  --corpus data/neurosynth_nimare/neurosynth_dataset_v7.pkl \
  --output-dir /tmp/wm_neurolang
```

### What "reproduces" means here

A fresh run reproduces the **finding** and an **internally-consistent record**,
not a byte-identical file. On the NeuroLang reference path the claim ends
`weakened`, the same five checks pass and the same `strict-evidence-profile`
check fails; on the NiMARE light path it ends `supported_within_scope` because
that engine clears the strict bar. Both are faithful records of what their engine
found — the point of the artifact is that the status, the surviving/failing
checks, and their evidence are all right there to inspect, whichever backend you
run.

The `commitment_hash` is sealed per run (it covers a `locked_at` timestamp and
the exact engine version), so any fresh run — even on the NeuroLang backend —
produces a *different* hash from the frozen `4871ea43…` snapshot committed here,
while still matching between its own commitment and claim cards. That is
expected: the committed files are one sealed instance. The reproducible
invariants are the finding, the surviving/failing checks, and the intra-run hash
match — not the hash value.

## Data

Every source used here — the public Neurosynth corpus for this example, and the
data for the other manuscript cases (including the controlled-access HCP-YA data
and the Liu et al. 2025 benchmark) — is documented with download locations in
[`DATA_SOURCES.md`](DATA_SOURCES.md).
