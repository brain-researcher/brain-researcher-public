# Pack: bounded_autoresearch_a1 (recorded result)

This is a manifest-backed pack for the A1 bounded-autoresearch result. It
records an HCP-YA component-to-behavior residualised-cognition target, the
governed harness and predictor identities used for the recorded result, and a
family-block exchangeability null. The public headline command uses a
manifest-pinned **public evaluator port**, not the byte-identical historical
governed harness.

The public checkout can reproduce the headline predictor result. It cannot, by
itself, rebuild the subject-keyed target or rerun the full family-block null.

## Choose what you want to do

| Goal | Command or starting point | Boundary |
|---|---|---|
| Check the committed bytes | `python reproducibility/verify.py reproducibility/bounded_autoresearch_a1` | Standard-library checksum verification; runs no analysis |
| Reproduce the public headline | `bash reproducibility/bounded_autoresearch_a1/run_end_to_end.sh` | Installs the Python 3.11 lock, downloads public FC features, and runs the public evaluator port with the recorded predictor; no HCP account or MCP needed |
| Understand the governed rerun | [`REPRODUCTION.md`](REPRODUCTION.md) | Separates the public path from target rebuilding and family-block steps that need user-staged HCP inputs |
| Inspect the language-driven agent path | [`AGENTIC_REPRODUCTION.md`](AGENTIC_REPRODUCTION.md) | Optional MCP episode; not required for checksum verification or the public headline |

Run commands from the **repository root**, the directory containing
`pyproject.toml` and `reproducibility/`. From anywhere inside the clone:

```bash
cd "$(git rev-parse --show-toplevel)"
```

## 1. Verify the shipped snapshot

No Brain Researcher installation is required:

```bash
python reproducibility/verify.py reproducibility/bounded_autoresearch_a1
```

Exit code 0 means every manifest entry matches its recorded checksum. This
proves the integrity of the committed snapshot; it does not rerun the predictor
or the scientific analysis.

## 2. Reproduce the public headline

The first run downloads an approximately 835 MB release archive and uses about
1.0 GB after extraction. The feature files are written under the pack's
git-ignored `inputs/` directory. After staging, the prediction itself takes only
seconds on the reference machine.

For a new clone, use an isolated Python 3.11 environment:

```bash
git clone https://github.com/brain-researcher/brain-researcher-public.git
cd brain-researcher-public
python3.11 -m venv ~/.venvs/br-a1-repro
source ~/.venvs/br-a1-repro/bin/activate
bash reproducibility/bounded_autoresearch_a1/run_end_to_end.sh
```

The shell script:

1. requires Python 3.11 and installs the exact light-path packages recorded in
   `requirements-py311.lock` into the active environment;
2. downloads and checksum-verifies the public, de-identified FC feature archive
   unless all 76 term files are already present;
3. runs the manifest-pinned public evaluator port with the recorded predictor
   against the shipped row-indexed target; and
4. fails unless it recovers `ICA_Cognition` fold-mean r near `0.183158` and
   aggregate mean r near `0.150847`.

The default fresh result is `/tmp/a1_e2e_result.json`. Set
`BR_A1_E2E_RESULT=/another/path/result.json` before running to change it.

To run the download and prediction separately:

```bash
python -m pip install --requirement \
  reproducibility/bounded_autoresearch_a1/requirements-py311.lock
python reproducibility/bounded_autoresearch_a1/scripts/fetch_fc_features.py
python reproducibility/bounded_autoresearch_a1/scripts/run_prediction.py
```

This public path reproduces the redesign-to-recovery predictor headline. It
uses the shipped de-identified target and therefore does **not** independently
rebuild that target from subject-keyed HCP behavior.

## Evaluator source boundary

The recorded governed results bind the historical `run.py` harness to
`sha256:3fe2eea1…` and the predictor to `sha256:380cbb50…`. The shipped
`scripts/predict.py` is byte-identical to that recorded predictor. The shipped
`scripts/run_prediction.py` has a different checksum because it is a public
port with repo-relative/configurable paths, a CLI, and explicit public-source
provenance metadata.

The pack does **not** call the public port the original frozen harness and does
not claim a formal semantic-equivalence proof. A successful public headline run
is direct evidence that the port recovers the recorded output values on the
public inputs. It is not evidence that the two harness files are byte-identical.
The machine-readable binding is
`artifacts/evaluator_source_closure.json`.

## Data-access boundary

| Input | Public checkout status | Needed for |
|---|---|---|
| Liu FC-pyspi per-term features | Public release fetched by `scripts/fetch_fc_features.py`; not stored in Git | Public predictor rerun |
| Row-indexed residualised target | Shipped under `artifacts/`; HCP subject identifiers removed | Public predictor rerun |
| Subject-keyed `liu_component_behavior.csv` for the exact 326-subject intersection | Governed derived input; not shipped, and no public command recreates that exact binding | Rebuilding the target and the deeper predictive check |
| HCP-YA behavior export | User-staged under HCP Data Use Terms | Rebuilding the target and the deeper predictive check |
| HCP-YA `Family_ID` and derived exchangeability manifest | Restricted/governed; not shipped | Family-block confirmatory null |

HCP behavior alone is not enough for the deeper path. You also need an
equivalent subject-keyed component table for the exact FC/behavior intersection.
Use the command templates and output-location safeguards in
[`REPRODUCTION.md`](REPRODUCTION.md); the documented commands pass explicit
output paths outside the committed pack.

## What the 2026-07-08 rerun established

Against the original governed inputs:

- target reconstruction matched the recorded estimates to machine precision;
- the chained Path-B predictive check matched all 117 compared numeric fields
  exactly; and
- permutation seeds 1 through 30 matched all 1,830 checked fields exactly.

The remaining 970 of the recorded 1,000 permutations were **not** rerun. The
published full-null significance (`+1 p = 0.000999`, z = 5.744) therefore remains
a recorded result rather than a fully independently reproduced result. Detailed
commands, comparisons, and tolerances are in
[`REPRODUCTION.md`](REPRODUCTION.md); the seed-subset output is
`reproduction/rerun_20260708_null_seeds_1_30.jsonl`.

## What is in the pack

- `manifest.json`: checksum boundary for every manifest-listed artifact
- `provenance_card.md`: recorded execution and provenance envelope
- `requirements-py311.lock`: exact tested light-path Python environment
- `artifacts/`: public-safe target, summaries, rerun checks, and agentic examples
- `manifests/`: frozen fold and component-target manifests used by the predictor
- `scripts/fetch_fc_features.py`: public release download, checksum, and extract
- `scripts/run_prediction.py`: manifest-pinned public evaluator port
- `scripts/predict.py`: predictor byte-identical to the recorded governed copy
- `scripts/build_residualised_target.py` and
  `scripts/run_residualised_cheap_check.py`: deeper steps requiring governed
  inputs described above
- `run_end_to_end.sh`: one-command public headline rerun
- `REPRODUCTION.md`: full data boundary and governed rerun record

`artifacts/liu_source_provenance_summary.json` records that the original
governed authoring workflow used OSF node `75je2` and a private authoring script:

- **Not shipped:** `scripts/analysis/fc_benchmarking/setup_liu_fc_pyspi.py`

Public users should use this pack's `scripts/fetch_fc_features.py`; it fetches
the de-identified release and does not reconstruct the governed subject
intersection.

The broader source narrative remains available under
[`docs/use_cases/bounded_autoresearch_a1_2026-04-30/`](../../docs/use_cases/bounded_autoresearch_a1_2026-04-30/).
