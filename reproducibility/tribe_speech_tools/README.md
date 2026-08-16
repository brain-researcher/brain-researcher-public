# TRIBE speech–tools geometry: public derived-data replay

This pack makes the Figure 6 TRIBE trajectory inspectable and redrawable from
the frozen **derived summary tables** used by the manuscript. It follows the
research path from an open screen of sound-category pairs, through the
speech–tools choice, to three new-item panels and a first extension to new
collections.

The main result represented here is a direction-preserving contraction of
speech–tools geometry within TRIBE: in most evaluated collections, late layers
retain the reference direction while the normalized separation is smaller.

## What this package does and does not reproduce

The command below validates every public number used in the figure and redraws
the PDF, SVG, and PNG from the shipped tables. It is a **derived-data replay**.
It does not rerun audio collection, acoustic matching, feature extraction,
TRIBE inference, or the balanced-label permutation procedure.

No audio recordings, item-level metadata, internal representations, model
checkpoints, or restricted source artifacts are included. The scientific scope
is internal TRIBE sound representations, not observed brain or fMRI responses.

## One command: validate and redraw

From the repository root, create a Python 3.11 environment with Matplotlib
3.9.4, then run:

```bash
python reproducibility/tribe_speech_tools/verify.py \
  --output-dir /tmp/tribe_speech_tools_replay
```

The command checks the complete public tables and writes:

```text
/tmp/tribe_speech_tools_replay/
├── figure6_tribe_speech_tools.pdf
├── figure6_tribe_speech_tools.png
└── figure6_tribe_speech_tools.svg
```

For the recorded Python 3.11 rendering environment:

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -r reproducibility/tribe_speech_tools/requirements-py311.lock
python reproducibility/tribe_speech_tools/verify.py
```

To inspect table integrity separately, use the repository-level verifier:

```bash
python reproducibility/verify.py reproducibility/tribe_speech_tools
```

## Shipped public tables

| File | Contents |
|---|---|
| `source/discovery_pairs.csv` | All 15 open-screen sound-category pairs, their early and late decoding AUCs, and ranks by absolute change. |
| `source/selection_diagnostic.csv` | Four held-out-collection geometry cells each for tools–voice and speech–tools. |
| `source/recurring_cells.csv` | The 12 collection-by-panel cells from the three new-item panels. |
| `source/recurring_panel_summary.csv` | The three frozen panel means and terminal panel statuses. |
| `source/new_collection_cells.csv` | The four previously unused collection cells. |
| `source/new_collection_summary.json` | The aggregate ΔS, permutation endpoint, correction, primary-endpoint status, and reviewed trajectory outcome. |
| `source/frozen_protocol.json` | The public-safe study and replay boundary. |

## Numerical landmarks

- The open screen contains all 15 pairwise contrasts from six sound categories.
  Tools–voice ranked first by absolute source-held-out ΔAUC (`-0.375`);
  speech–tools ranked third (`-0.33333333333333326`).
- In the exploratory held-out-collection diagnostic, speech–tools had lower
  separation in 4/4 collections and retained direction in 3/4. Tools–voice
  did so in 2/4 and 1/4, respectively. Speech–tools was then selected for the
  follow-up, whose prediction and analysis were frozen before new-item
  evaluation.
- Across three non-overlapping 48-item panels (144 new stimuli), all three
  panel means were negative: `-0.6937409133858539`,
  `-0.44671967745113533`, and `-0.5471175107075629`. Eleven of the 12
  collection-by-panel cells had ΔS < 0 and C > 0.
- In four previously unused collections, three cells had the same target
  geometry. The aggregate was `ΔS = -0.19802239326408583`; the frozen
  balanced-label permutation endpoint had raw `p = 0.13212` and
  Holm-adjusted `p = 0.39635999999999993`. The H1 primary endpoint was
  `not_supported`; the reviewed trajectory outcome was
  `inconclusive_or_conflicting`.

Here, ΔS is the late-minus-early change in normalized separation, and C is
late directional alignment with the reference axis. The public figure uses the
same ΔS/C coordinate system for its exploratory and follow-up geometry plots.

## Attestation

`integrity_verified` is the current level for this pack: its checked-in tables,
renderer, figure files, and documentation can be inspected and verified. The
figure replay is publicly runnable from the derived tables, but that is only
partial evidence for a public rerun. Governed raw-data rerun and full scientific
reproduction are not claimed.

See [`provenance_card.md`](provenance_card.md) for the boundary and
[`figure/CAPTION.md`](figure/CAPTION.md) for the Figure 6 legend.
