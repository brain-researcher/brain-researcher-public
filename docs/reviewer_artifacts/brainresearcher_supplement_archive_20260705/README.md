# Brain Researcher Reviewer Artifact Package

Snapshot date: 2026-07-05

This package contains full audit artifacts that support the BrainResearcher
manuscript but are too long for the reviewer-facing Supplementary Information.
The Supplementary Information retains the methods, denominators, summary tables,
claim states, and reviewer-facing contracts needed to assess the paper. This
package carries the full ledgers, per-case reports, item-level sheets, and code
excerpts.

## Contents

- [`extended_data.pdf`](extended_data.pdf): the appendix ledgers below compiled into a single
  human-readable PDF (110 pages), so the moved tables can be read directly
  without recompiling. This prebuilt PDF is the shipped reviewer artifact.
- [`extended_data.tex`](extended_data.tex), [`sn-jnl.cls`](sn-jnl.cls): the
  public source for `extended_data.pdf`. From the repository root, rebuild with:

  ```bash
  cd docs/reviewer_artifacts/brainresearcher_supplement_archive_20260705
  latexmk -pdf extended_data.tex
  ```

  The standalone build succeeds, but the package does not ship the manuscript
  `main_2500.aux` or Supplementary Information `supplementary.aux`. Without
  those external label files, three cross-document figure references render as
  `??`. Use the prebuilt PDF when reviewing the frozen package.
- [`appendix_ledgers/`](appendix_ledgers/): full appendix/data-card source files moved out of the
  lean supplement, including the full BR-KG atlas/inventories (Appendix B), the
  tool-registry ledger (Appendix D), constraint, execution/provenance, and
  memory ledgers (Appendices A, C, E, F, H), the per-rule review registry
  (Appendix G9.1--G9.4, G9.6), and the benchmark item/example/bundle manifests
  (Appendix J). The lean supplement retains a one-paragraph data card for each,
  plus Appendices G (review card + G9.5 calibration library), I, J, and K.
- [`case_reports/`](case_reports/): full automatically generated reports for the collaborator
  and bounded self-evolving cases summarized in the manuscript.
- [`benchmark_records/human_audit_20pct/`](benchmark_records/human_audit_20pct/): full graded human-audit sheet for the
  20 percent benchmark audit.
- [`claim_records/case1_neuromark_schizophrenia_multiverse/`](claim_records/case1_neuromark_schizophrenia_multiverse/): public claim-card
  and evidence-verdict records for the NeuroMark schizophrenia multiverse audit.
- [`supplement_crosswalk.md`](supplement_crosswalk.md): mapping from Supplementary Information locations
  to archived files in this package.
- [`MANIFEST.json`](MANIFEST.json): file sizes and SHA-256 checksums for the package.

## Archive status

This package was first frozen in GitHub release
[`br-reproducibility-20260709.1`](https://github.com/brain-researcher/brain-researcher-public/releases/tag/br-reproducibility-20260709.1)
and Zenodo version DOI [`10.5281/zenodo.21282320`](https://doi.org/10.5281/zenodo.21282320).
That release is immutable. It contains a stale size/checksum row for
`supplement_crosswalk.md`; the content file itself is intact, and current `main`
corrects the manifest row. Cite the release or later corrected version whose
bytes you actually inspected.

## Boundary

The operative manuscript-level claims remain the claim states, statistics,
denominators, and caveats reported in the main text, Supplementary Methods S11,
and reviewer-facing Appendices B, C, F, G, I, and J. Full reports in this package
are audit artifacts; if an archived report headline differs from the current
manuscript claim state, the manuscript and Supplementary Methods version paired
with this archive is the authoritative reporting layer. This public package does
not include those manuscript files; use
[`supplement_crosswalk.md`](supplement_crosswalk.md) to map their labels to the
shipped audit artifacts.
