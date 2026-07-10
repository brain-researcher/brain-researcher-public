"""Claim -> (region coordinate, term) grounding for the NiMARE backend.

The v0.1 backend resolved a target via a tiny inline region lexicon + naive substring
term match — the panel's "extraction is the weakest link". This module makes that step
explicit, confidence-bearing, and vocabulary-grounded:

* :func:`resolve_region` maps functional/anatomical region names (with aliases and
  left/right) to **curated functional MNI foci**, with a per-region confidence
  reflecting how tightly the name localises (amygdala 0.9 vs dlPFC 0.65).

  NOTE on foci vs atlas centroids: an earlier version used AAL parcel centroids
  (via nilearn). On the real Neurosynth corpus that FAILED — e.g. the AAL
  ``Frontal_Mid`` centroid (-34, 32, 34) returns *unresolved* for working memory,
  while the functional WM/dlPFC focus (-44, 18, 28) is strongly supported (z=7.6).
  A parcel centroid is the geometric centre of a whole gyrus, not the functional
  activation focus — exactly the coordinate->region error this system guards against.
  So the foci below are literature/Neurosynth-typical activation peaks, not atlas
  centroids. (An atlas is still useful for the reverse check — which parcel a peak
  falls in and how ambiguous — a future enhancement.)

* :func:`resolve_term` matches a claim against a real term vocabulary (the corpus's
  Neurosynth terms) with normalisation + a small synonym/abbreviation map.

The resolution confidences feed the report's coordinate->region and task->ontology
uncertainty dims, so those stop being blanket 'sorries'. Matching is word-boundary
(padded-substring) so short aliases like "acc" never fire inside "accuracy".
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

# Curated LEFT-hemisphere functional MNI foci (mm) — literature/Neurosynth-typical
# activation peaks, NOT atlas parcel centroids (see module docstring). Right hemisphere
# is the same with x negated.
_REGION_FOCI: dict[str, tuple[float, float, float]] = {
    "dlPFC": (-44.0, 18.0, 28.0),
    "vmPFC": (-4.0, 46.0, -8.0),
    "mPFC": (-6.0, 52.0, 20.0),
    "ACC": (-4.0, 24.0, 32.0),
    "amygdala": (-23.0, -2.0, -18.0),
    "hippocampus": (-25.0, -22.0, -11.0),
    "parahippocampal": (-26.0, -40.0, -12.0),
    "insula": (-36.0, 16.0, 4.0),
    "fusiform": (-40.0, -52.0, -18.0),
    "V1": (-8.0, -90.0, 2.0),
    "M1": (-38.0, -22.0, 56.0),
    "S1": (-42.0, -28.0, 52.0),
    "inferior_parietal": (-44.0, -46.0, 46.0),
    "superior_parietal": (-24.0, -62.0, 56.0),
    "putamen": (-24.0, 4.0, 2.0),
    "caudate": (-12.0, 12.0, 8.0),
    "STG": (-54.0, -22.0, 6.0),
    "MTG": (-54.0, -38.0, -2.0),
    "occipital": (-32.0, -84.0, 14.0),
    "SMA": (-4.0, 6.0, 58.0),
    "IFG": (-48.0, 18.0, 18.0),
    "angular": (-44.0, -62.0, 34.0),
    "precuneus": (-6.0, -58.0, 34.0),
    "thalamus": (-12.0, -18.0, 8.0),
}

# functional/anatomical alias -> (region focus key, mapping confidence in [0,1]).
# Confidence = how tightly the name localises onto the focus (a functional subregion,
# e.g. FFA within fusiform, gets lower confidence). The resolver tries the
# longest-matching alias first.
_REGION_ALIASES: tuple[tuple[str, str, float], ...] = (
    ("dorsolateral prefrontal", "dlPFC", 0.65),
    ("dlpfc", "dlPFC", 0.65),
    ("middle frontal", "dlPFC", 0.6),
    ("ventromedial prefrontal", "vmPFC", 0.65),
    ("vmpfc", "vmPFC", 0.65),
    ("medial orbitofrontal", "vmPFC", 0.6),
    ("medial prefrontal", "mPFC", 0.55),
    ("mpfc", "mPFC", 0.55),
    ("anterior cingulate", "ACC", 0.8),
    ("acc", "ACC", 0.8),
    ("amygdala", "amygdala", 0.9),
    ("parahippocampal place area", "parahippocampal", 0.6),
    ("parahippocampal", "parahippocampal", 0.8),
    ("ppa", "parahippocampal", 0.5),
    ("hippocampus", "hippocampus", 0.9),
    ("hippocampal", "hippocampus", 0.85),
    ("insula", "insula", 0.8),
    ("insular", "insula", 0.75),
    ("fusiform face area", "fusiform", 0.6),
    ("ffa", "fusiform", 0.6),
    ("fusiform", "fusiform", 0.8),
    ("primary visual", "V1", 0.85),
    ("calcarine", "V1", 0.85),
    ("striate", "V1", 0.7),
    ("v1", "V1", 0.85),
    ("primary motor", "M1", 0.85),
    ("precentral", "M1", 0.8),
    ("m1", "M1", 0.85),
    ("motor cortex", "M1", 0.6),
    ("somatosensory", "S1", 0.7),
    ("postcentral", "S1", 0.8),
    ("s1", "S1", 0.7),
    ("intraparietal", "inferior_parietal", 0.6),
    ("ips", "inferior_parietal", 0.55),
    ("inferior parietal", "inferior_parietal", 0.75),
    ("superior parietal", "superior_parietal", 0.75),
    ("precuneus", "precuneus", 0.8),
    ("posterior cingulate", "precuneus", 0.5),
    ("pcc", "precuneus", 0.5),
    ("putamen", "putamen", 0.85),
    ("caudate", "caudate", 0.85),
    ("dorsal striatum", "putamen", 0.5),
    ("striatum", "putamen", 0.45),
    ("superior temporal", "STG", 0.75),
    ("auditory cortex", "STG", 0.55),
    ("stg", "STG", 0.7),
    ("middle temporal", "MTG", 0.75),
    ("mtg", "MTG", 0.7),
    ("supplementary motor", "SMA", 0.8),
    ("pre-sma", "SMA", 0.6),
    ("sma", "SMA", 0.75),
    ("inferior frontal", "IFG", 0.65),
    ("pars opercularis", "IFG", 0.7),
    ("pars triangularis", "IFG", 0.65),
    ("broca", "IFG", 0.6),
    ("ifg", "IFG", 0.65),
    ("angular gyrus", "angular", 0.8),
    ("angular", "angular", 0.7),
    ("temporoparietal junction", "angular", 0.5),
    ("tpj", "angular", 0.5),
    ("thalamus", "thalamus", 0.85),
    ("occipital", "occipital", 0.55),
)

# abbreviation / synonym -> canonical term (human form; should appear in the vocabulary).
_TERM_ALIASES: tuple[tuple[str, str], ...] = (
    ("n-back", "working memory"),
    ("nback", "working memory"),
    ("wm", "working memory"),
    ("tom", "theory of mind"),
    ("response inhibition", "inhibition"),
    ("inhibitory control", "inhibition"),
    ("reward prediction error", "reward"),
    ("rpe", "reward"),
    ("fearful faces", "fear"),
    ("face processing", "faces"),
    ("spatial attention", "attention"),
    ("episodic retrieval", "episodic"),
)


# When a name/term is ambiguous we keep the best mapping but (a) lower its mapping
# confidence and (b) surface the alternatives, rather than silently committing to one.
# These factors scale the *mapping* confidence (coordinate->region / task->ontology
# dims of the uncertainty vector), never the scientific association probability.
_AMBIGUITY_PENALTY = 0.6  # multiplier applied when a clear best candidate survives
_TIED_PENALTY = 0.4  # multiplier applied when candidates are genuinely tied
# Two candidate confidences within this delta are treated as a genuine tie.
_TIE_EPS = 0.05


@dataclass(frozen=True)
class RegionResolution:
    name: str  # the matched alias (human form)
    region_label: str  # canonical region key + hemisphere, e.g. "dlPFC_L"
    xyz: tuple[float, float, float]
    hemisphere: str  # "L" or "R"
    confidence: float
    source: str
    ambiguous: bool = False  # the name plausibly mapped to >1 atlas region
    # Other plausible (region_key, base_confidence) candidates, best-first. Empty when
    # the mapping is unambiguous.
    ambiguous_candidates: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True)
class TermResolution:
    term: str  # human form of the resolved term
    label: str  # the corpus label that was matched (passed to the backend)
    confidence: float
    source: str
    ambiguous: bool = False  # the term plausibly mapped to >1 ontology concept
    # Other plausible (label, human_form) ontology concepts, best-first. Empty when the
    # mapping is unambiguous.
    alternatives: tuple[tuple[str, str], ...] = ()


def _norm(text: str) -> str:
    """Lower-case, replace non-alphanumerics with spaces, pad — for word-boundary `in`."""
    return " " + re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip() + " "


def _contains(norm_text: str, phrase: str) -> bool:
    return f" {phrase} " in norm_text


def _hemisphere(norm_text: str) -> str:
    has_r, has_l = _contains(norm_text, "right"), _contains(norm_text, "left")
    return "R" if (has_r and not has_l) else "L"


def resolve_region(text: str) -> RegionResolution | None:
    """Resolve a region name to a curated functional MNI focus.

    Atlas reverse-ambiguity: a single claim can mention aliases that localise onto
    *different* region foci (e.g. "dorsal striatum / caudate", "precuneus / posterior
    cingulate"). When >1 distinct focus key is plausible we still pick the best
    candidate (longest, then most specific alias) but flag the resolution ambiguous,
    surface the rival foci in :attr:`RegionResolution.ambiguous_candidates`, and lower
    the *mapping* confidence (the coordinate->region uncertainty dim) rather than
    silently committing to one parcel.
    """
    norm = _norm(text)
    hemi = _hemisphere(norm)
    # Collect every alias that fires, best-first: longest alias wins, ties broken by the
    # higher per-alias confidence (the more specific localisation).
    matches: list[tuple[str, str, float]] = [
        (alias, key, conf)
        for alias, key, conf in _REGION_ALIASES
        if _contains(norm, alias)
    ]
    if not matches:
        return None
    matches.sort(key=lambda a: (len(a[0]), a[2]), reverse=True)

    best_alias, best_key, best_conf = matches[0]
    # Distinct rival foci: other matched aliases pointing at a *different* region key.
    rival_keys: list[tuple[str, float]] = []
    seen = {best_key}
    for _alias, key, conf in matches[1:]:
        if key in seen:
            continue
        seen.add(key)
        rival_keys.append((key, conf))

    ambiguous = bool(rival_keys)
    confidence = best_conf
    candidates: tuple[tuple[str, float], ...] = ()
    if ambiguous:
        # Genuine tie when the strongest rival is essentially as confident as the best.
        top_rival_conf = max(conf for _key, conf in rival_keys)
        tied = top_rival_conf >= best_conf - _TIE_EPS
        confidence = best_conf * (_TIED_PENALTY if tied else _AMBIGUITY_PENALTY)
        candidates = ((best_key, best_conf), *rival_keys)

    x, y, z = _REGION_FOCI[best_key]
    xyz = (-x, y, z) if hemi == "R" else (x, y, z)
    source = f"focus:{best_key}_{hemi}"
    if ambiguous:
        source = f"focus:{best_key}_{hemi}:ambiguous"
    return RegionResolution(
        name=best_alias,
        region_label=f"{best_key}_{hemi}",
        xyz=xyz,
        hemisphere=hemi,
        confidence=confidence,
        source=source,
        ambiguous=ambiguous,
        ambiguous_candidates=candidates,
    )


def region_surface_aliases(region_key: str) -> tuple[str, ...]:
    """Anatomical surface phrases to mask from term resolution for a resolved region.

    Returns every ``_REGION_ALIASES`` surface pointing at ``region_key``'s focus plus the
    key rendered as a phrase (underscores -> spaces). These are the region's own words —
    also corpus terms (``hippocampus``, ``insula``, ``inferior parietal``, ...) — that the
    longest-match rule would otherwise return as the cognitive term. Pass to
    ``resolve_term(..., exclude_surfaces=region_surface_aliases(key))`` so the region words
    can't hijack a short construct. ``region_key`` may be a bare key or a
    ``"{key}_{hemi}"`` region_label; the hemisphere suffix is stripped. Longest-first so a
    caller masking sequentially removes the widest span before its sub-words.
    """
    if not region_key:
        return ()
    key = region_key
    if key not in _REGION_FOCI and "_" in key:
        head = key.rsplit("_", 1)[0]  # strip a trailing _L / _R hemisphere tag
        if head in _REGION_FOCI:
            key = head
    surfaces = {alias for alias, k, _conf in _REGION_ALIASES if k == key}
    surfaces.add(key.replace("_", " ").lower())
    return tuple(sorted(surfaces, key=len, reverse=True))


def _humanize(label: str) -> str:
    return label.split("__")[-1].replace("_", " ").strip().lower()


def resolve_term(
    text: str, vocabulary, *, exclude_surfaces: Sequence[str] = ()
) -> TermResolution | None:
    """Resolve a claim's cognitive term against a vocabulary of corpus labels.

    1. direct: a vocabulary term (human form, >=3 chars) that appears as a word-bounded
       phrase in the claim (base confidence 0.9);
    2. else a synonym/abbreviation whose canonical term is in the vocabulary (0.8).

    Ontology disambiguation: when the claim word-matches >1 *distinct* vocabulary
    concept, we pick the best by a transparent rule — the longest humanised form wins
    (the most specific concept), since a longer phrase is a more constrained match. The
    rival concepts are recorded in :attr:`TermResolution.alternatives` and the *mapping*
    confidence (task->ontology dim) is lowered. When two concepts are genuinely tied
    (equal-length human forms) the resolution is flagged ambiguous with a heavier
    penalty rather than committing arbitrarily.

    ``exclude_surfaces`` are word-bounded phrases to MASK from the claim before matching —
    used to strip a region's own surface words (which are also corpus terms, e.g.
    ``hippocampus``/``insula``) that the longest-match rule would otherwise return as the
    cognitive term. Masking the whole span also removes any sub-word (e.g. ``parietal``
    inside ``inferior parietal``). Default ``()`` preserves the prior behavior exactly.
    """
    norm = _norm(text)
    for surface in exclude_surfaces:
        s = _norm(surface).strip()
        if not s:
            continue
        prev = None
        while prev != norm:  # collapse adjacent/repeated occurrences of the region span
            prev = norm
            norm = norm.replace(f" {s} ", " ")
    human = {label: _humanize(label) for label in (vocabulary or [])}

    direct = [
        (label, h)
        for label, h in human.items()
        if len(h) >= 3 and _contains(norm, h)
    ]
    if direct:
        # Best = longest human form (most specific); deterministic label tiebreak.
        direct.sort(key=lambda kv: (len(kv[1]), kv[0]), reverse=True)
        best_label, best_h = direct[0]
        # Distinct rival concepts (different humanised form than the winner).
        rivals = [(label, h) for label, h in direct[1:] if h != best_h]
        if not rivals:
            return TermResolution(
                term=best_h, label=best_label, confidence=0.9, source="vocab:direct"
            )
        # Genuine tie when the strongest rival's human form is the same length.
        top_rival_len = max(len(h) for _label, h in rivals)
        tied = top_rival_len >= len(best_h)
        confidence = 0.9 * (_TIED_PENALTY if tied else _AMBIGUITY_PENALTY)
        source = "vocab:direct:tied" if tied else "vocab:direct:ambiguous"
        return TermResolution(
            term=best_h,
            label=best_label,
            confidence=confidence,
            source=source,
            ambiguous=True,
            alternatives=tuple(rivals),
        )

    for alias, canonical in sorted(_TERM_ALIASES, key=lambda a: len(a[0]), reverse=True):
        if not _contains(norm, alias):
            continue
        for label, h in human.items():
            if h == canonical or _contains(_norm(h), canonical):
                return TermResolution(
                    term=h, label=label, confidence=0.8, source=f"alias:{alias}"
                )
    return None
