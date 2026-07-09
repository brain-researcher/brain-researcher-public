# Appendix F — Run Bundle & Provenance: bounded_autoresearch_a1

## F.2 Execution envelope
- Target runtime: python (bounded-autoresearch A1)
- Method / provenance: see `artifacts/residualised_target_provenance.json`
  (source_files, residualisation method, exchangeability family-block design).

## F.8 Expected vs produced artifacts
| Artifact | Path | Checksum |
|---|---|---|
| liu_component_behavior_residualised_cognition.csv | `artifacts/liu_component_behavior_residualised_cognition.csv` | `sha256:f62365e25793b199…` |
| residualised_target_provenance.json | `artifacts/residualised_target_provenance.json` | `sha256:7f5e88ad46231541…` |
| family_block_null_summary.json | `artifacts/family_block_null_summary.json` | `sha256:83eabfb146f0ac28…` |
| residualised_cheap_check.json | `artifacts/residualised_cheap_check.json` | `sha256:5dc29332cd260466…` |
| residualised_target_summary.json | `artifacts/residualised_target_summary.json` | `sha256:b593730059c31e46…` |
| rerun_20260708_null_seeds_1_30.jsonl | `reproduction/rerun_20260708_null_seeds_1_30.jsonl` | `sha256:1495777bcf75ea12…` |

## F.10 Provenance
- Real recorded result; input data governed (not shipped). See the pack README
  for the data-gated re-run path. Checksums above are verifiable now via verify.py.
