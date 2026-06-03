# Cognitive Atlas → ONVOC Coverage (Nov 13, 2025)

## Completed Work
- Expanded  with the remaining CA task families (WM/naming/perception/decision/health/etc.) and regenerated .
- Re-ran  (CA-only) after each seed batch (final runs applied 41 + 4 proposals).  is now empty.
- Backfilled parent Level-2 edges for every task that only had Level-3 mappings via  (method ).
- Calibrated Gemini matcher runs:
  - 
  -  (wide sweep) plus a focused  pass.
- Manually seeded the anonymous CA task  to ONVOC Attention.

## Current Coverage Snapshot
| Metric | Count |
| --- | --- |
| Cognitive Atlas tasks | 965 |
| Tasks mapped to ONVOC (any level) | 965 (100%) |
| Tasks with  | 915 |
| Tasks with  | 141 |
| Tasks lacking ONVOC edges | 0 |
| Level-2 conflicts | 0 |

## Edge Provenance Keys
Every  includes:
-  (, , , , , ...)
-  (, , , )
-  and  (channels fired: slug/keywords/regex or LLM payload + votes)
-  and  (hierarchy metadata)
- , , , , 

Sample inspection queries:




## Remaining Notes
-  holds the final deterministic batch details.
-  captures any malformed Gemini responses.
- To target new Level-3 refinements, run  after identifying the parent(s) of interest.
- Keep  in sync whenever  changes (Wrote 21 generated anchors to configs/mapping_rules.generated.yaml using crosswalk families__to__onvoc.v1.yaml).
EOF}

## Manual overrides (Nov 13 – update)
Meditation → Emotion Regulation; Enumeration/Lateral Facilitation/Gating → Executive Function. Psychophysics task left unmapped.

## Crosswalk sync (Nov 13 – follow up)
- Added a dedicated tf_executive_control family (→ ONVOC_0000430) carrying the enumeration/gating/lateral-facilitation slugs so the deterministic mapper now owns those assignments.
- Removed the same slugs plus psychophysics from the perception/attention families to avoid future false positives.
- Added a plain meditation slug under the emotion/preference family to mirror the manual override and keep both naming variants covered.
- Expanded the working-memory seeds with additional delayed/one-back/serial-reaction variants so CA slug aliases like object-one-back-task resolve without relying on overrides.
- Regenerated configs/mapping_rules.generated.yaml via scripts/tools/etl/sync_taxonomy_to_mapping.py and re-ran onvoc_mapper.py propose (CA-only) to confirm no new proposals were needed (0 emitted, review deck unchanged).
