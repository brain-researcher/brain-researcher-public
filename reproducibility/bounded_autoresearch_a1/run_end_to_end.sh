#!/usr/bin/env bash
# End-to-end, from scratch, deterministic (no MCP):
#   a research question  ->  locked environment  ->  public FC features  ->
#   the manifest-pinned public evaluator port  ->  the recovered headline numbers.
#
# Light path: standard scientific-Python only, no HCP account, no full platform.
# Fails loudly if the numbers drift, so a green run means the chain held.
#
#   bash run_end_to_end.sh
#
# For the language-driven (agent + MCP) path, see drive_from_language.py.
set -euo pipefail

PACK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${PACK_ROOT}"
RESULT="${BR_A1_E2E_RESULT:-/tmp/a1_e2e_result.json}"
LOCK_FILE="${PACK_ROOT}/requirements-py311.lock"

echo "== [1/3] the question =="
echo "   Do resting-state FC (pyspi) features predict the Liu ICA cognition"
echo "   component, and does the shipped predictor recover the recorded number?"

echo "== [2/3] environment (light) + public FC features =="
python - <<'PY'
import sys

if sys.version_info[:2] != (3, 11):
    raise SystemExit(
        "bounded_autoresearch_a1 is locked and tested with Python 3.11; "
        f"active interpreter is {sys.version.split()[0]}"
    )
PY
python -m pip install --quiet --disable-pip-version-check \
  --requirement "${LOCK_FILE}"
TERMS_DIR="${PACK_ROOT}/inputs/liu_fc_pyspi_terms"
if [ "$(ls "${TERMS_DIR}"/term_*_iu.h5 2>/dev/null | wc -l)" = "76" ]; then
  echo "   (76 term files already present in inputs/ — skipping the ~834 MB download)"
else
  python scripts/fetch_fc_features.py
fi

echo "== [3/3] execute the manifest-pinned public evaluator port =="
python scripts/run_prediction.py > "${RESULT}"

echo "== verify the numbers reproduce exactly =="
python - "${RESULT}" <<'PY'
import json
import sys

d = json.load(open(sys.argv[1]))
assert d.get("status") == "ok", f"evaluator errored: {d.get('error')}"

by = {c["component"]: c for c in d["per_component"]}
r = by["ICA_Cognition"]["fold_mean_r"]
agg = d["aggregate_mean_r"]
n_terms = d.get("n_terms_available")

print(f"   n_terms_available     = {n_terms}")
print(f"   ICA_Cognition fold_r  = {r}   (recorded ~= 0.183158)")
print(f"   aggregate_mean_r      = {agg} (recorded ~= 0.150847)")

assert n_terms == 76, f"expected the 76-term public deposit, got {n_terms}"
assert abs(r - 0.183158) < 1e-4, f"ICA_Cognition r drifted: {r}"
assert abs(agg - 0.150847) < 1e-4, f"aggregate drifted: {agg}"
print("   OK: question -> public evaluator port -> recorded recovery number")
PY

echo "== done =="
echo "   result: ${RESULT}"
