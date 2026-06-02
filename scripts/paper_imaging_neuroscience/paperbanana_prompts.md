# PaperBanana (Nano Banana) Figure Prompts

This file stores the **reader-facing** prompts (the `intent` strings) we feed to `paperbanana` for figure regeneration, plus the exact data payload paths.

Note: when these were first drafted, `paperbanana` MCP was temporarily broken, so we rendered the initial figures deterministically with matplotlib. These prompts are the **v0/v1** versions we use going forward now that MCP is healthy.

## Fig1 (Behavioral Anchor): Equifinality + Pairing Dependence

**Data JSON (pass as `data_json`)**

`/data/brain_researcher_data/runs/paper_figs_imag_paperbanana_20260305/prompts/Fig1_paperbanana_data.json`

### v0 intent (original)

Create a publication-ready multi-panel figure (PNG) for an Imaging Neuroscience paper with a clean, minimal style.

The JSON provides three panels:

Panel A (left): “Native weak-class deficit”.
- Bar chart over subjects S01, S02, S05
- y-axis: weak_minus_control
- Annotate each bar with the one-sided Mann-Whitney p-value (mw_p_less).

Panel B (center): “Weak-class gain vs native”.
- Grouped bars for each subject (S01, S02, S05)
- Four stages: Rescue, Continue-train, Sham-random, True sham (pair-breaking)
- y-axis: delta_weak_vs_native
- Include a legend with stage names.

Panel C (right): “Pairing dependence”.
- Bar chart over subjects S01, S02, S05
- y-axis: rescue_minus_true_sham
- Annotate each bar with the numeric value.

Do not invent any numbers; use the JSON values exactly. Use panel labels “A”, “B”, “C”.

### v1 intent (revised for clarity)

Create a **reviewer-proof** multi-panel figure (PNG) that communicates:
1) A native weak-class deficit exists in some subjects (H1),
2) Pair-preserving adaptation strategies are behaviorally near-equifinal,
3) Pair-breaking true sham is consistently lower, showing pairing dependence.

Styling constraints:
- White background, thin axes, consistent font sizes; colorblind-safe.
- Use reader-facing labels only (no internal stage IDs).

Panel A: “Native weak-class deficit (H1)”.
- Bars: weak_minus_control for S01/S02/S05.
- Color rule: use a highlight color for subjects with mw_p_less < 0.05; gray otherwise.
- Print p-values above bars (format as `p=...`).

Panel B: “Weak-class gain vs native”.
- Grouped bars per subject.
- Stage colors must be consistent across the paper:
  - Rescue (blue), Continue-train (green), Sham-random (orange), True sham (magenta).
- Keep y-axis label explicit: “Δ CLIP similarity (weak) vs native”.

Panel C: “Pairing dependence”.
- Plot Rescue − True sham per subject.
- Add `+` sign for positive values and format to 3 decimals.

Strict rule: do not infer anything from the data; just render the provided values.

### v2 intent (strict blueprint; Gemini-style)

```text
Generate a publication-ready, 3-panel scientific figure (PNG) laid out as 1 row x 3 columns. Use a pure white background.

Global typography:
- Use a single sans-serif font (Helvetica/Arial).
- Titles: bold, size 14.
- Axis labels: size 12.
- Tick labels: size 11.
- Panel labels: bold "A", "B", "C" at the top-left of each panel.

Global geometry:
- Overall figure aspect: wide (approximately 4:1).
- Equal panel heights; consistent margins and spacing.
- No background gridlines. Remove top/right spines.
- Axis lines thin and black.

Global colors (hex):
- Non-significant native bars (Panel A): Gray "#7F7F7F"
- Significant native bars (Panel A): Red "#D62728"
- Rescue: Navy "#174A7E"
- Continue-train: Green "#2CA02C"
- Sham-random: Orange "#D95319"
- True sham: Magenta "#9C27B0"

Panel A (left):
- Title text: "Native weak-class deficit (H1)"
- X-axis categories (exact): "S01", "S02", "S05"
- Y-axis label (exact): "weak_minus_control"
- Plot: bar chart using values from panelA_native_deficit[*].weak_minus_control
- Color rule: if mw_p_less < 0.05 use Red "#D62728", else Gray "#7F7F7F"
- Annotation: center text immediately above each bar: "p=[mw_p_less]" using the numeric value from JSON (no re-computation)

Panel B (center):
- Title text: "Weak-class gain vs native"
- X-axis categories (exact): "S01", "S02", "S05"
- Y-axis label (exact): "Δ CLIP similarity (weak) vs native"
- Plot: grouped bar chart with 4 bars per subject using panelB_weak_gain_vs_native.values
- Stage order is exactly panelB_weak_gain_vs_native.stages (do not reorder)
- Color mapping by stage name:
  - "Rescue" -> Navy "#174A7E"
  - "Continue-train" -> Green "#2CA02C"
  - "Sham-random" -> Orange "#D95319"
  - "True sham (pair-breaking)" -> Magenta "#9C27B0"
- Legend: place inside the panel, top-left, mapping colors to the four stage names exactly as above.

Panel C (right):
- Title text: "Pairing dependence"
- X-axis categories (exact): "S01", "S02", "S05"
- Y-axis label (exact): "Rescue − True sham"
- Plot: bar chart using values from panelC_pairing_dependence[*].rescue_minus_true_sham in Navy "#174A7E"
- Annotation: print the numeric value above each bar, prefixed with "+", formatted to 3 decimals (e.g., "+0.020")

Constraint: do not hallucinate data; use values exactly as provided in data_json.
```

## Fig2 (Mechanistic Core, Subject 05): Rescue vs Sham-random

**Data JSON (pass as `data_json`)**

`/data/brain_researcher_data/runs/paper_figs_imag_paperbanana_20260305/prompts/Fig2_paperbanana_data.json`

It contains:
- `panelA_metrics`: `map_corr_rescue_vs_sham_random`, `contrast_abs_mean`, `top5_roi_jaccard`
- `panelB_key_rois`: arrays for ROI names, mean deltas, contrasts, CIs, q-values, sample counts
- `panelC_relative_semantic_bias`: early/high ROI sets and aggregated contrasts

### v0 intent (original)

Create a publication-ready multi-panel statistical figure (PNG) for an Imaging Neuroscience paper. Use a clean, minimal journal style and a colorblind-safe palette.

The input JSON contains three panels worth of data:

Panel A (left): A text-only map-level summary for Subject 05 showing:
- map corr (Rescue vs Sham-random)
- contrast abs mean
- top-5 ROI Jaccard
Format each metric with a short label and a large numeric value.

Panel B (center): A grouped bar chart titled “Key ROIs: Rescue vs Sham-random (S05)”.
- x-axis: ROIs in this order: V1, V2, V3, LO1, V3B, PH, PHA1, PHA2, PHA3
- bars: mean delta for Rescue and mean delta for Sham-random
- overlay: a contrast series (Rescue − Sham-random) with 95% CI error bars on a secondary y-axis
- annotate: FDR-adjusted Wilcoxon q-value significance as stars above each ROI (*** for q<0.001, ** for q<0.01, * for q<0.05)
- include a compact legend

Panel C (right): A bar chart titled “Relative semantic bias”.
- two bars: Early vs High
- y-axis: mean contrast
- show the ratio (High/Early) as a large label inside the plot.

Do not invent any numbers; use the provided JSON values exactly. Use panel labels “A”, “B”, “C”.

### v1 intent (revised for clarity)

Create a **publication-ready, reviewer-proof** multi-panel figure (PNG) for an Imaging Neuroscience paper. The purpose is to show that **behavior-matched adaptation can be mechanistically different**: on Subject 05, Rescue and Sham-random have moderate map divergence and different **ROI update budgets**.

Styling constraints:
- Clean journal aesthetic (no gradients), white background, thin axes, consistent font sizes across panels.
- Colorblind-safe palette; keep “Rescue” and “Sham-random” colors consistent across the whole paper.
- Use clear, unambiguous axis labels: these ROI values represent **delta magnitude / update budget** (not activation).

Panel A (left): “Map-level summary (S05)”.
- Text-only. Show:
  - map correlation (Rescue vs Sham-random)
  - mean absolute voxelwise contrast
  - top-5 ROI Jaccard
- Add one subtitle sentence under the title: “Moderate map divergence despite gain-matched behavior.”

Panel B (center): “ROI update budget: Rescue vs Sham-random (S05)”.
- x-axis ROIs (order fixed): V1, V2, V3, LO1, V3B, PH, PHA1, PHA2, PHA3
- Primary y-axis: **Mean ROI delta magnitude** (label it as “Mean ROI |ΔW| (pooled voxels)” or “Mean ROI delta magnitude”)
- Grouped bars: Rescue vs Sham-random using the provided arrays.
- Secondary y-axis: **Contrast in delta magnitude** (Rescue − Sham-random) with 95% CI error bars.
- Add a horizontal reference line at 0 on the contrast axis.
- Significance: use q-values, but avoid visual spam:
  - Put stars only above the **contrast points**, not above bars.
  - Use *** for q<1e-3, ** for q<1e-2, * for q<0.05.
- Emphasize the “high-level” ROIs without overclaiming sign:
  - Bold the tick labels for LO1 and V3B.
  - Optionally annotate the contrast value numerically for LO1 and V3B only.

Panel C (right): “Relative semantic bias (update concentration)”.
- Show Early vs High mean contrast bars.
- The text label should explicitly say: “High/Early ratio = …”.
- Add one sentence under the panel title: “Rescue allocates a disproportionate update budget to higher-level ROIs.”

Strict rule: do not invent data; use the JSON exactly; keep layout readable at 1-column width when exported.

### v2 intent (strict blueprint; Gemini-style)

```text
Generate a publication-ready, 3-panel scientific figure (PNG) laid out as 1 row x 3 columns on a pure white background. Use a 1:2.5:1 width ratio (Panel A : Panel B : Panel C).

Global typography:
- Use a single sans-serif font (Helvetica/Arial).
- Panel titles: bold, size 14.
- Axis labels: size 12.
- Tick labels: size 11.
- Panel labels: bold "A", "B", "C" at the top-left of each panel.

Global styling:
- No background gridlines.
- Thin black axis lines.
- Remove top/right spines.

Global colors (hex):
- Rescue: Navy "#174A7E"
- Sham-random: Orange "#D95319"
- Contrast (Rescue − Sham-random): Green "#2CA02C"
- Non-highlight bars: Gray "#7F7F7F"
- Significance stars: Black "#000000"

Panel A (left): text-only summary
- Title: "Map-level summary (S05)"
- Render three stacked metric blocks using data_json.panelA_metrics:
  1) label: "map corr (Rescue vs Sham-random)" value: map_corr_rescue_vs_sham_random (format 3 decimals)
  2) label: "contrast abs mean" value: contrast_abs_mean (format 4 decimals)
  3) label: "top-5 ROI Jaccard" value: top5_roi_jaccard (format 3 decimals)
- Each block: small label above, large numeric value below.

Panel B (center): ROI update budget + contrast with CI
- Title: "Key ROIs: Rescue vs Sham-random (S05)"
- X-axis categories: use data_json.panelB_key_rois.rois in the provided order.
- Left Y-axis label (exact): "Mean ROI delta magnitude"
- Grouped bars per ROI:
  - Rescue bars: data_json.panelB_key_rois.mean_delta_rescue in Navy "#174A7E"
  - Sham-random bars: data_json.panelB_key_rois.mean_delta_sham_random in Orange "#D95319"
- Legend: inside panel, top-left, mapping the two colors to "Rescue" and "Sham-random".

- Add a secondary Y-axis on the right with label (exact): "Contrast (Rescue − Sham-random)"
- Plot contrast as green circle markers (no fill) with vertical error bars:
  - Contrast values: data_json.panelB_key_rois.contrast_rescue_minus_sham
  - CI low/high: data_json.panelB_key_rois.contrast_ci_low and contrast_ci_high (use as asymmetric error bars)
- Add a horizontal dashed reference line at y=0 on the contrast axis.

- Significance annotation:
  - Use data_json.panelB_key_rois.wilcoxon_q per ROI.
  - Place stars above the contrast point for that ROI:
    "***" if q < 0.001
    "**" if q < 0.01
    "*" if q < 0.05
    no star otherwise
  - Keep stars small and unobtrusive; do not annotate every value.

Panel C (right): relative semantic bias
- Title: "Relative semantic bias"
- X-axis categories: "Early", "High"
- Y-axis label (exact): "Mean contrast"
- Bar values from data_json.panelC_relative_semantic_bias:
  - Early bar: early_mean_contrast in Gray "#7F7F7F"
  - High bar: high_mean_contrast in Green "#2CA02C"
- Add a bold text annotation centered inside the plot: "ratio = [ratio_high_over_early]" formatted to 2 decimals.

Constraint: do not hallucinate data; use values exactly as provided in data_json.
```

## Fig3 (Boundary Conditions): Cross-Subject Map Similarity + Canonical ROI Contrasts

**Data JSON (pass as `data_json`)**

`/data/brain_researcher_data/runs/paper_figs_imag_paperbanana_20260305/prompts/Fig3_paperbanana_data.json`

### v0 intent (original)

Create a publication-ready 2-panel figure (PNG) with panels A and B.

Panel A: “Map similarity across subjects”.
- Bar chart: map_corr_rescue_vs_sham_random for S01, S02, S05.
- y-axis: correlation (0 to 1).

Panel B: “Canonical ROI contrasts”.
- Grouped bars per subject for V1, LO1, V3B.
- y-axis: ROI contrast (Rescue − Sham-random).
- Include a horizontal zero line.
- Include legend.

Use the JSON values exactly; do not invent.

### v1 intent (revised for clarity)

Create a compact figure (PNG) that makes the boundary-condition claim visually obvious:
- Some subjects show “locked-in” routing (high map correlation),
- Others show divergence-prone routing (lower correlation),
even under behaviorally similar endpoints.

Panel A: Map similarity.
- Bars for S01/S02/S05.
- Show numeric values above bars (3 decimals).

Panel B: Canonical ROI contrasts.
- Grouped bars for V1 (gray), LO1 (green), V3B (orange-red).
- Keep y-axis label explicit: “ROI contrast in delta magnitude (Rescue − Sham-random)”.

No p-values in this figure; it is descriptive and points to Fig2/Supp for statistics.

### v2 intent (strict blueprint; Gemini-style)

```text
Generate a publication-ready, 2-panel scientific figure (PNG) laid out as 1 row x 2 columns on a pure white background.

Global typography:
- Sans-serif font (Helvetica/Arial).
- Titles: bold, size 14.
- Axis labels: size 12.
- Tick labels: size 11.
- Panel labels: bold "A" and "B" at the top-left of each panel.

Global styling:
- No background gridlines.
- Thin black axis lines.
- Remove top/right spines.

Panel A (left):
- Title text: "Map similarity across subjects"
- X-axis categories (exact): "S01", "S02", "S05"
- Y-axis label (exact): "Map correlation (Rescue vs Sham-random)"
- Y-axis scale: 0 to 1
- Plot: bar chart using panelA_map_similarity[*].map_corr_rescue_vs_sham_random
- Bar color: Navy "#174A7E"
- Annotation: print numeric value above each bar formatted to 3 decimals.

Panel B (right):
- Title text: "Canonical ROI contrasts"
- X-axis categories (exact): "S01", "S02", "S05"
- Y-axis label (exact): "ROI contrast in delta magnitude (Rescue − Sham-random)"
- Plot: grouped bars per subject using panelB_canonical_roi_contrasts with exactly 3 bars per subject:
  - V1 color Gray "#7F7F7F"
  - LO1 color Green "#2CA02C"
  - V3B color Orange "#D95319"
- Add a horizontal dashed reference line at y=0.
- Legend: top-right inside panel mapping the three colors to "V1", "LO1", "V3B".

Constraint: do not hallucinate data; use values exactly as provided in data_json.
```

## Supplementary S1: Subj05 All-ROI Contrast Rank Plot

**Data JSON (pass as `data_json`)**

`/data/brain_researcher_data/runs/paper_figs_imag_paperbanana_20260305/prompts/Supp_S1_paperbanana_data.json`

### v0 intent (original)

Create a publication-ready scatter plot (PNG).
- x-axis: ROI rank by contrast (rank 0 = largest contrast_delta)
- y-axis: contrast_delta (Rescue − Sham-random)
- Color points by significance:
  - q < 0.05 (highlight color)
  - q >= 0.05 (gray)
- Include legend and a horizontal zero line.

### v1 intent (revised for clarity)

Create a compact scatter plot (PNG) for supplement.
- Emphasize that the y-axis is “contrast in adapter delta magnitude” (not activation).
- Use a colorblind-safe palette; keep the significant points in a single accent color.
- Keep title: “Supplementary S1: Subj05 all-ROI contrasts (rescue vs sham_random)”.

### v2 intent (strict blueprint; Gemini-style)

```text
Generate a single-panel scientific scatter plot (PNG) on a pure white background.

Typography:
- Sans-serif font (Helvetica/Arial).
- Title: bold, size 14.
- Axis labels: size 12.
- Tick labels: size 11.

Title (exact):
"Supplementary S1: Subj05 all-ROI contrasts (rescue vs sham_random)"

Axes:
- X-axis label (exact): "ROI rank by contrast"
- Y-axis label (exact): "Contrast in adapter delta magnitude"
- Add a horizontal dashed reference line at y=0.

Data:
- Use data_json.points[*].rank for x and data_json.points[*].contrast_delta for y.
- Use data_json.points[*].wilcoxon_q for significance thresholding.

Point styling:
- If wilcoxon_q >= 0.05: light gray "#B0B0B0", marker size 10
- If wilcoxon_q < 0.05: red "#D62728", marker size 16

Legend:
- Place top-right.
- Gray circle label: "q ≥ 0.05"
- Red circle label: "q < 0.05"

Constraint: do not hallucinate data; use values exactly as provided in data_json.
```

## Fig4 (Diagram): Control Logic for Adaptation Claims

**Use `generate_diagram` (source_context text below).**

### v0 source_context (original)

Draw a methods-control schematic titled “Control logic for adaptation claims”.

Boxes:
- Native (baseline)
- Rescue (targeted weight) [pair-preserving]
- Continue-train (untargeted) [pair-preserving]
- Sham-random (pair-preserving)
- True sham (label-shuffle targets) [pair-breaking]

Arrows:
- Native branches to each condition.

Analysis callouts:
- H1: Native weak-class deficit: test weak < control (MW, one-sided)
- Pairing dependence: Rescue > True sham
- Targeted specificity: Rescue > Continue AND Rescue > Sham-random
- Mechanistic routing diagnostics: compare delta maps / ROI contrasts (Rescue vs Sham-random; Rescue vs Continue)

Keep it clean, white background, readable in 1-column width.

### v1 source_context (revised for clarity)

Create a **minimal, reviewer-friendly** flow diagram titled:
“Control logic for adaptation claims (pair-preserving vs pair-breaking)”.

Design constraints:
- Use consistent rounded rectangles, thin strokes, and a colorblind-safe accent scheme.
- Explicitly label the “pair-preserving” family and the “pair-breaking” control.

Required content (same boxes/arrows as v0), but also:
- Add a short sentence in the bottom diagnostics box: “Behavioral equifinality does not imply mechanistic equivalence.”
- Ensure the diagram reads left-to-right: Native → Interventions → Claims/Diagnostics.

### v2 source_context (strict blueprint; Gemini-style)

```text
Draw a minimal, left-to-right flow diagram (PNG) on a pure white background using uniform rounded rectangles, thin black 1px strokes, and sans-serif text.

Layout & Nodes:
- Start node (left): "Native (baseline)"

- Middle column (interventions): draw two dashed bounding boxes.
  - Top dashed box label: "Pair-preserving"
    - Inside place 3 rounded-rectangle nodes stacked vertically (top to bottom):
      1) "Rescue (targeted weight)"
      2) "Continue-train (untargeted)"
      3) "Sham-random"
  - Bottom dashed box label: "Pair-breaking"
    - Inside place 1 rounded-rectangle node:
      - "True sham (label-shuffle targets)"

- Right column (diagnostics): 4 rounded-rectangle nodes stacked vertically (top to bottom):
  1) "H1: Native weak-class deficit"
  2) "Pairing dependence"
  3) "Targeted specificity"
  4) "Mechanistic routing diagnostics"

- Bottom footer: a wide rounded-rectangle box spanning the width with the exact text:
  "Behavioral equifinality does not imply mechanistic equivalence."

Edges:
- Solid arrows from "Native (baseline)" to all 4 intervention nodes.
- Solid arrows from intervention boxes to the right-column diagnostic nodes.

Keep spacing generous and all text fully legible at 1-column width.
```

## Fig5 (Diagram): Reproducibility and Provenance Workflow

**Use `generate_diagram`.**

### v0 source_context (original)

Draw a workflow diagram titled “Reproducibility and provenance workflow”.

Top row boxes (left to right):
- Frozen evidence whitelist
- Derived tables (behavior, routing)
- Figures (Fig1–Fig6)
- Manuscript assembly

Bottom row boxes (supporting artifacts):
- Claim–evidence trace (claim map + numeric tables)
- Automated checks (constraints, coherence)
- Input manifest (hashes + paths)

Arrows:
- Frozen evidence whitelist → Derived tables → Figures → Manuscript assembly
- Dashed arrows from Derived tables to Claim–evidence trace
- Dashed arrows from Figures to Automated checks
- Dashed arrows from Manuscript assembly to Input manifest

Footer text box:
“Principle: main-text claims must be supported by frozen outputs; implementation logs/manifests stay in supplement unless interpretation depends on them.”

### v1 source_context (revised for clarity)

Same structure as v0, but ensure:
- The “Principle” footer is a single, short sentence.
- Keep the diagram visually balanced with equal box sizes and generous spacing.
- No decorative elements; this is a transparency/provenance figure.

### v2 source_context (strict blueprint; Gemini-style)

```text
Draw a top-down hierarchy workflow diagram (PNG) on a pure white background. Use sharp rectangular boxes of exactly equal height, with uniform generous spacing. No gradients or shadows.

Title:
- Centered at the top: "Reproducibility and provenance workflow"

Top row (left to right), connected by solid horizontal arrows:
"Frozen evidence whitelist" -> "Derived tables (behavior, routing)" -> "Figures (Fig1–Fig6)" -> "Manuscript assembly"

Bottom row (left to right directly beneath the top row), no horizontal connections:
"Claim–evidence trace (claim map + numeric tables)", "Automated checks (constraints, coherence)", "Input manifest (hashes + paths)"

Vertical dashed arrows:
- From "Derived tables (behavior, routing)" down to "Claim–evidence trace (claim map + numeric tables)"
- From "Figures (Fig1–Fig6)" down to "Automated checks (constraints, coherence)"
- From "Manuscript assembly" down to "Input manifest (hashes + paths)"

Footer:
- A single text block at the very bottom with the exact sentence:
"Principle: main-text claims must be supported by frozen outputs; implementation logs/manifests stay in supplement unless interpretation depends on them."
```

## Fig6 (Diagram): Practical Evaluation Workflow for Weak-Class Rescue Claims

**Use `generate_diagram`.**

### v0 source_context (original)

Draw a decision flowchart titled “Practical evaluation workflow for weak-class rescue claims”.

Flow:
1) Observe weak-class underperformance after cross-subject transfer.
2) Is native weak deficit significant? (MW one-sided)
   - If NO: treat as noise / collect more data
   - If YES: run compute-matched controls (Continue-train, Sham-random, True sham)
3) Does Rescue exceed Continue AND Sham-random?
   - If YES: rescue-specific behavioral benefit
4) Does Rescue exceed True sham?
   - If NO: behavioral equifinality
5) If pair-dependent and behavior is equifinal: run routing diagnostics (delta maps, ROI contrasts) and report boundary conditions.

Use rounded rectangles and arrows; white background; compact.

### v1 source_context (revised for clarity)

Same flow as v0, but:
- Make “pair-dependent” vs “pair-breaking” explicitly visible (use a small label near True sham).
- Keep decision diamonds minimal; if diamonds look messy, use labeled rectangles (“Decision: …”) instead.

### v2 source_context (strict blueprint; Gemini-style)

```text
Draw a minimal top-down decision flowchart (PNG) on a pure white background. Do NOT use diamond shapes; use standard rounded rectangles with the prefix "Decision:" to keep text legible and neat.

Sequence & Nodes (top to bottom):
1) Node: "1) Observe weak-class underperformance after cross-subject transfer."
2) Node: "Decision: Is native weak deficit significant? (MW one-sided)"
   - Branch labeled "NO" to node: "Treat as noise / collect more data"
   - Branch labeled "YES" down to node 3
3) Node: "Run compute-matched controls"
   Inside the same box, list exactly:
   "- Continue-train"
   "- Sham-random"
   "- True sham"
4) Node: "Decision: Does Rescue exceed Continue AND Sham-random?"
   - Branch labeled "YES" to node: "Rescue-specific behavioral benefit"
   - Branch labeled "NO" down to node 5
5) Node: "Decision: Does Rescue exceed True sham?"
   Add italic subtext under main text: "*pair-breaking test*"
   - Branch labeled "NO" to node: "Behavioral equifinality"
   - Branch labeled "YES" down to node 6
6) Final node: "If pair-dependent and behavior is equifinal: run routing diagnostics (delta maps, ROI contrasts) and report boundary conditions."

Use thin black arrows and generous spacing so text never overlaps.
```
