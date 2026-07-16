# Appendix F — Run Bundle & Provenance: fitlins_multiverse_yeo17 (synthetic)

## F.2 Execution envelope
- Recorded step tool: `fitlins.run_multiverse`
- Multiverse spec: `source/specs/multiverse_manifest.json`
- Environment status: `unresolved_historical`; see `environment.lock.json`.

## F.8 Expected vs produced artifacts
| Artifact | Path | Checksum | Note |
|---|---|---|---|
| run.json | `run/run.json` | `sha256:b91e1fd50739a44f…` | verifiable |
| analysis_bundle.json | `run/analysis_bundle.json` | `sha256:5bb50b63dea743db…` | verifiable |
| mv01_specs.json | `source/specs/mv01_specs.json` | `sha256:bc277a55a3536596…` | verifiable |
| multiverse_manifest.json | `source/specs/multiverse_manifest.json` | `sha256:547fd743372949ad…` | verifiable |
| yeo17_summary.csv | `source/fitlins/yeo17_summary.csv` | `sha256:bafec1ed462cfaf6…` | verifiable |
| sub-01_contrast-incongruentMinusCongruent_stat-z_statmap.nii.gz | `artifacts/statmaps/sub-01_contrast-incongruentMinusCongruent_stat-z_statmap.nii.gz` | — | schema_only (bytes not shipped) |
| sub-01_contrast-responseConflict_stat-z_statmap.nii.gz | `artifacts/statmaps/sub-01_contrast-responseConflict_stat-z_statmap.nii.gz` | — | schema_only (bytes not shipped) |

## F.10 Provenance
- Attestation current level: `inspectable`. Integrity is `partial`; public,
  governed, and full reproduction are not claimed.
- SYNTHETIC schema exemplar. Shipped specs/summary are checksum-verifiable; statmap
  NIfTIs are provenance keys only. Not a real-data result.
