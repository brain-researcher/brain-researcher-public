# BrainResearcher Reviewer Artifact Package

Date: 2026-07-05

This package contains full audit artifacts that support the BrainResearcher
manuscript but are too long for the reviewer-facing Supplementary Information.
The Supplementary Information retains the methods, denominators, summary tables,
claim states, and reviewer-facing contracts needed to assess the paper. This
package carries the full ledgers, per-case reports, item-level sheets, and code
excerpts.

## Contents

- `extended_data.pdf`: the appendix ledgers below compiled into a single
  human-readable PDF (110 pages), so the moved tables can be read directly
  without recompiling. Built from `extended_data.tex` + `appendix_ledgers/` +
  `sn-jnl.cls` (the same document class and preamble as the Supplementary
  Information); cross-references to reviewer-facing appendices and figures
  resolve against the compiled supplement.
- `extended_data.tex`, `sn-jnl.cls`: the build recipe for `extended_data.pdf`
  (recompile with `latexmk -pdf extended_data.tex`).
- `appendix_ledgers/`: full appendix/data-card source files moved out of the
  lean supplement, including the full BR-KG atlas/inventories (Appendix B), the
  tool-registry ledger (Appendix D), constraint, execution/provenance, and
  memory ledgers (Appendices A, C, E, F, H), the per-rule review registry
  (Appendix G9.1--G9.4, G9.6), and the benchmark item/example/bundle manifests
  (Appendix J). The lean supplement retains a one-paragraph data card for each,
  plus Appendices G (review card + G9.5 calibration library), I, J, and K.
- `case_reports/`: full automatically generated reports for the collaborator
  and bounded self-evolving cases summarized in the manuscript.
- `benchmark_records/human_audit_20pct/`: full graded human-audit sheet for the
  20 percent benchmark audit.
- `claim_records/case1_neuromark_schizophrenia_multiverse/`: public claim-card
  and evidence-verdict records for the NeuroMark schizophrenia multiverse audit.
- `supplement_crosswalk.md`: mapping from Supplementary Information locations
  to archived files in this package.
- `MANIFEST.json`: file sizes and SHA-256 checksums for the package.

## Archive status

This directory is intended to be fixed by a GitHub release and then archived on
Zenodo or OSF before review. Until a release DOI is minted, paths in the
manuscript and supplement refer to this repository package location.

## Boundary

The operative manuscript-level claims remain the claim states, statistics,
denominators, and caveats reported in the main text, Supplementary Methods S11,
and reviewer-facing Appendices B, C, F, G, I, and J. Full reports in this package
are audit artifacts; if an archived report headline differs from the current
manuscript claim state, the manuscript and Supplementary Methods are the
authoritative reporting layer.
