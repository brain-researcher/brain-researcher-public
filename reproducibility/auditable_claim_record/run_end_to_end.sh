#!/usr/bin/env bash
# End-to-end, from scratch, pinned-input and version-constrained (no MCP):
#   a natural-language claim  ->  environment  ->  public corpus  ->  executed
#   evidence  ->  a sealed, auditable claim record.
#
# This is the light path: a handful of standard scientific-Python packages, not
# the full Brain Researcher platform. It fails loudly if the result drifts, so a
# green run means every link in the chain held.
#
#   bash reproducibility/auditable_claim_record/run_end_to_end.sh [OUTPUT_DIR]
#
# For the language-driven (agent + MCP) path, see drive_from_language.py.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
OUT="${1:-/tmp/auditable_claim_e2e}"
EXPECT_STATUS="${BR_E2E_EXPECT_STATUS:-supported_within_scope}"
CLAIM="Working-memory-labeled Neurosynth studies show dlPFC activation and dlPFC-IPS coactivation within coordinate evidence."

echo "== [1/4] the question (natural language) =="
echo "   claim: ${CLAIM}"
echo "   scope: Neurosynth v7 / fMRI / 'attention' as the allowed rival explanation"

echo "== [2/4] environment (light — not the full platform) =="
python - <<'PY'
import sys

if sys.version_info[:2] != (3, 11):
    raise SystemExit(
        "This locked light path requires Python 3.11; got "
        f"{sys.version_info.major}.{sys.version_info.minor}"
    )
PY
python -m pip install --quiet --disable-pip-version-check \
  -c reproducibility/auditable_claim_record/constraints-py311.txt \
  -e . nimare nilearn
python - "${REPO_ROOT}" <<'PY'
from pathlib import Path
import sys

import brain_researcher

repo_src = (Path(sys.argv[1]) / "src").resolve()
module_path = Path(brain_researcher.__file__).resolve()
if not module_path.is_relative_to(repo_src):
    raise SystemExit(
        "brain_researcher resolved outside this clone: "
        f"{module_path} (expected under {repo_src})"
    )
print(f"   brain_researcher import: {module_path}")
PY

echo "== [3/4] public corpus: download -> convert =="
python scripts/data/download_neurosynth_data.py
python scripts/data/convert_neurosynth.py

echo "== [4/4] execute the claim -> sealed record (default NiMARE backend) =="
python scripts/autoresearch/run_auditable_claim_demo.py \
  --case working_memory \
  --corpus data/neurosynth_nimare/neurosynth_dataset_v7.pkl \
  --source-dir data/neurosynth_nimare/neurosynth_v7 \
  --output-dir "${OUT}"

echo "== verify the chain actually fired =="
python - "${OUT}" "${EXPECT_STATUS}" <<'PY'
import json
import sys
from pathlib import Path

out, expect = sys.argv[1], sys.argv[2]
card = json.load(open(f"{out}/claim_card.json"))
commitment = json.load(open(f"{out}/commitment_card.json"))
verdicts = json.load(open(f"{out}/evidence_verdicts.json"))
bundle = json.load(open(f"{out}/demo_bundle.json"))
readme = open(f"{out}/README.md").read()

status = card.get("status")
fwd = verdicts.get("forward_default", {})
n_studies = (fwd.get("raw") or {}).get("n_studies")

print(f"   status = {status}")
print(f"   forward_default n_studies = {n_studies}")

assert status == expect, f"status drifted: got {status!r}, expected {expect!r}"
assert card["commitment_hash"] == commitment["commitment_hash"]
assert commitment["evidence_engine"]["name"] == "nimare"
assert commitment["evidence_engine"]["version"]
assert all(
    not ref["path"].startswith("/")
    for ref in commitment["rubric_refs"].values()
), "rubric paths must be clone-stable repository-relative references"
assert bundle["corpus_ref"]["sha256"], "corpus identity was not recorded"
verified_source = bundle["corpus_ref"].get("verified_source") or {}
assert verified_source.get("manifest_sha256"), "raw source manifest was not recorded"
assert verified_source.get("converted_provenance_sha256"), (
    "converted-dataset provenance sidecar was not recorded"
)
assert str(Path.cwd().resolve()) not in json.dumps(bundle), (
    "output bundle leaked the absolute clone path"
)
assert n_studies and n_studies > 0, "evidence did not run (no corpus studies scored)"
for key in ("forward_default", "forward_strict", "specificity_excluding_rivals",
            "network_coactivation"):
    assert key in verdicts, f"missing evidence verdict: {key}"
for snippet in (
    "Run every command from the public repository root",
    "cd brain-researcher-public",
    "constraints-py311.txt",
    "reproducibility/auditable_claim_record/drive_from_language.py",
):
    assert snippet in readme, f"generated README missing runnable instruction: {snippet}"
print("   OK: claim -> grounded evidence -> sealed claim record, end to end")
PY

echo "== done =="
echo "   record: ${OUT}/commitment_card.json  (+ claim_card.json, evidence_verdicts.json, demo_bundle.json)"
