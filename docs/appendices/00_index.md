# Appendix Order Index and File Map

This index defines the canonical A–P sequence for the paper's appendices and points to the fillable card templates for A–J. User-case reports K–P are placeholders here; they are written separately and are not card-style.

## Sequence and files

| Order | Appendix | Title | File |
|------|---------|-------|------|
| A | Appendix A | Episode and control-plane card | `01_appendix_A_episode_control_plane.md` |
| B | Appendix B | Evidence bundle / BR-KG card | `02_appendix_B_evidence_bundle.md` |
| C | Appendix C | Dataset / resource card | `03_appendix_C_dataset_resource.md` |
| D | Appendix D | Tool registry and specification ledger card | `04_appendix_D_tool_registry.md` |
| E | Appendix E | Constraint and commitment card | `05_appendix_E_constraint_commitment.md` |
| F | Appendix F | Run bundle and provenance card | `06_appendix_F_run_bundle_provenance.md` |
| G | Appendix G | Review card | `07_appendix_G_review.md` |
| H | Appendix H | Memory card | `08_appendix_H_memory.md` |
| I | Appendix I | Operational-mode card | `09_appendix_I_operational_mode.md` |
| J | Appendix J | Evaluation card | `10_appendix_J_evaluation.md` |
| K | Appendix K | User case 1 report | (report; not card) |
| L | Appendix L | User case 2 report | (report; not card) |
| M | Appendix M | User case 3 report | (report; not card) |
| N | Appendix N | User case 4 report | (report; not card) |
| O | Appendix O | Self-evolving research case 1 report | (report; not card) |
| P | Appendix P | Self-evolving research case 2 report | (report; not card) |

## Conventions

- One card per episode. Card ID format: `<APPENDIX>-<EPISODE-ID>-<NNN>`.
- Snapshot fields (BR-KG snapshot, registry snapshot, model version, prompt-template version) must be filled before the episode is considered reviewable.
- Every "accepted" claim or artifact must trace back to (a) a run bundle in Appendix F and (b) an evidence row in Appendix B.
- Tier vocabulary used across cards:
  - Tier 1: accepted graph evidence (curated / promoted).
  - Tier 2: batch-extracted evidence (not yet promoted).
  - Tier 3: candidate evidence (needs review).
  - Tier 4: real-time retrieval evidence (live tool / connector output).
- Verdict vocabulary: `accept`, `revise`, `block`, `defer`.
- Severity vocabulary (review layer): `BLOCK`, `WARN`, `INFO`.

## Renaming checklist

| Step | Check | Done |
|------|-------|------|
| 1 | All appendix files present in A–J order | [ ] |
| 2 | First heading inside each file matches assigned label | [ ] |
| 3 | Required fields present in each card | [ ] |
| 4 | Snapshot identifiers filled (BR-KG, registry, model, prompts) | [ ] |
| 5 | Cross-references between cards resolve (Appendix F ↔ B, G ↔ E, H ↔ G) | [ ] |
| 6 | Spelling: "Self-evolving" (not "Self-evloving") | [ ] |
