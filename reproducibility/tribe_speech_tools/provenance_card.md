# Provenance card: TRIBE speech–tools derived-data replay

## What is preserved

This package preserves the public-safe, frozen summary values that support the
TRIBE speech–tools trajectory shown in Figure 6:

1. the complete 15-pair open sound-category screen;
2. the two-contrast exploratory held-out-collection diagnostic;
3. all 12 cells and three means from the recurring new-item panels; and
4. all four cells and the frozen inference endpoint from the new-collection
   extension.

The tables were transcribed from frozen evaluation outputs and checked against
the manuscript numbers before release. The new-collection extension keeps its
H1 primary endpoint (`not_supported`) distinct from the reviewed trajectory
outcome (`inconclusive_or_conflicting`). `verify.py` encodes the expected values
and counts, then redraws the figure from these tables.

## Public boundary

The release intentionally excludes raw audio, item-level identifiers, acoustic
features, model checkpoints, internal representations, private file locations,
and execution identifiers. The tables are sufficient to inspect the reported
summary and redraw the figure, but they are not sufficient to rerun the
underlying acoustic matching, TRIBE forward passes, or permutation procedure.

## Claim boundary

The package supports an internal-representation result: speech and tools were
usually less separated in late TRIBE layers while retaining the prespecified
direction. It does not establish a biological mechanism, a universal property
of sound collections, source-population generalization, or an observed brain or
fMRI effect.

## Attestation vocabulary

- `inspectable`: attained. The inputs, rendered figure, documentation, and
  validation code are public and openable.
- `integrity_verified`: attained. The repository-level verifier checks every
  shipped artifact listed in `manifest.json`.
- `public_runnable`: partial. The derived-data replay runs publicly, but raw
  inputs and model inference are deliberately outside this package.
- `governed_rerun`: not claimed. The original governed data and execution
  environment are not redistributed.
- `fully_reproduced`: not claimed. A derived-data redraw is not a full
  scientific reproduction.
