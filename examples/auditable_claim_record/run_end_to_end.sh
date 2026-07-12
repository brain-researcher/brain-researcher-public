#!/usr/bin/env bash
# End-to-end, from scratch, deterministic (no MCP):
#   a natural-language claim  ->  environment  ->  public corpus  ->  executed
#   evidence  ->  a sealed, auditable claim record.
#
# This is the light path: a handful of standard scientific-Python packages, not
# the full Brain Researcher platform. It fails loudly if the result drifts, so a
# green run means every link in the chain held.
#
#   bash run_end_to_end.sh [OUTPUT_DIR]
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
python -m pip install --quiet --disable-pip-version-check nimare nilearn

echo "== [3/4] public corpus: download -> convert =="
python scripts/data/download_neurosynth_data.py
python scripts/data/convert_neurosynth.py

echo "== [4/4] execute the claim -> sealed record (default NiMARE backend) =="
python scripts/autoresearch/run_auditable_claim_demo.py \
  --case working_memory \
  --corpus data/neurosynth_nimare/neurosynth_dataset_v7.pkl \
  --output-dir "${OUT}"

echo "== verify the chain actually fired =="
python - "${OUT}" "${EXPECT_STATUS}" <<'PY'
import json
import sys

out, expect = sys.argv[1], sys.argv[2]
card = json.load(open(f"{out}/claim_card.json"))
verdicts = json.load(open(f"{out}/evidence_verdicts.json"))

status = card.get("status")
fwd = verdicts.get("forward_default", {})
n_studies = (fwd.get("raw") or {}).get("n_studies")

print(f"   status = {status}")
print(f"   forward_default n_studies = {n_studies}")

assert status == expect, f"status drifted: got {status!r}, expected {expect!r}"
assert n_studies and n_studies > 0, "evidence did not run (no corpus studies scored)"
for key in ("forward_default", "forward_strict", "specificity_excluding_rivals",
            "network_coactivation"):
    assert key in verdicts, f"missing evidence verdict: {key}"
print("   OK: claim -> grounded evidence -> sealed claim record, end to end")
PY

echo "== done =="
echo "   record: ${OUT}/claim_card.json  (+ evidence_verdicts.json, demo_bundle.json)"
