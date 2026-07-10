"""Named uncertainty vector for ``neuroclaim_compile`` (the anti-false-formality core).

The single most important epistemic rule in the design: the uncertainty attached to
a neuroscience claim is a NAMED VECTOR, never a single laundered number. In
particular **LLM extraction confidence is never folded into the scientific
association probability** — a confident extraction of a weak study must never read
as a strong claim. That separation is enforced *structurally* here: extraction
confidence is simply not a member of :data:`_EVIDENTIAL_DIMS`, the only dims any
evidential aggregation (weakest-link, sorries) is permitted to read.

The five dims (all in ``[0, 1]``, higher = more confident / stronger; ``None`` =
not yet resolved):

* ``association_p``         — scientific association probability (the backend output)
* ``extraction_confidence``— how sure the extractor was it read the claim/facts right
* ``evidence_quality``     — study-quality / method-rigor weight
* ``coordinate_to_region`` — atlas/threshold mapping confidence (peak -> region)
* ``task_to_ontology``     — task -> ontology mapping confidence

The last two are the two largest neuroimaging-specific uncertainty sources that a
naive three-probability model omits (a peak maps to different regions under AAL vs
Harvard-Oxford; a task maps ambiguously under a contested ontology).

Nothing here imports the service tier, so the module is safe inside ``autoresearch``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

#: Below this, a *premise* dim is surfaced as a 'sorry' (an explicit missing premise).
WEAK_THRESHOLD: float = 0.5

#: Dims that any *evidential* aggregation is permitted to read. ``extraction_confidence``
#: is DELIBERATELY excluded: it must never enter the scientific-strength calculus.
#: :func:`NamedUncertainty.assert_no_extraction_laundering` and the unit tests assert
#: this membership.
_EVIDENTIAL_DIMS: tuple[str, ...] = (
    "association_p",
    "evidence_quality",
    "coordinate_to_region",
    "task_to_ontology",
)

#: Dims whose *weakness* (not just absence) surfaces as a 'sorry'. ``association_p`` is
#: excluded — a genuinely-low-but-known association is a finding, not a missing premise
#: (only an unresolved ``association_p`` becomes a sorry, handled below).
_PREMISE_DIMS: frozenset[str] = frozenset(
    {"extraction_confidence", "evidence_quality", "coordinate_to_region", "task_to_ontology"}
)


class UncertaintyDim(BaseModel):
    """One named uncertainty source: its value, provenance, and sorry-flag."""

    name: str
    value: float | None = None  # [0, 1]; None == unresolved
    source: str = ""  # provenance: which tool / mapping_profile produced it
    is_sorry: bool = False  # True -> surfaces as an explicit missing premise
    note: str = ""

    @property
    def resolved(self) -> bool:
        return self.value is not None


def _mk(name: str, value: float | None, source: str, note: str = "") -> UncertaintyDim:
    """Build one dim, validating the domain and deriving ``is_sorry``.

    A dim is a 'sorry' when it is unresolved (``value is None``) or when it is a
    *premise* dim whose confidence is below :data:`WEAK_THRESHOLD`.
    """
    if value is not None and not (0.0 <= float(value) <= 1.0):
        raise ValueError(f"uncertainty dim {name!r} out of [0, 1]: {value!r}")
    is_sorry = value is None or (name in _PREMISE_DIMS and float(value) < WEAK_THRESHOLD)
    return UncertaintyDim(
        name=name, value=value, source=source, is_sorry=is_sorry, note=note
    )


class NamedUncertainty(BaseModel):
    """The five-dimensional, never-collapsed uncertainty vector for a claim."""

    association_p: UncertaintyDim
    extraction_confidence: UncertaintyDim
    evidence_quality: UncertaintyDim
    coordinate_to_region: UncertaintyDim
    task_to_ontology: UncertaintyDim

    def dims(self) -> list[UncertaintyDim]:
        return [
            self.association_p,
            self.extraction_confidence,
            self.evidence_quality,
            self.coordinate_to_region,
            self.task_to_ontology,
        ]

    def evidential_dims(self) -> list[UncertaintyDim]:
        """The dims an evidential aggregation may read — never extraction_confidence."""
        return [getattr(self, name) for name in _EVIDENTIAL_DIMS]

    def weakest_link(self) -> UncertaintyDim | None:
        """The bottleneck evidential dim (lowest resolved value).

        Surfacing the weakest link is the honest alternative to a polished
        derivation — and it is explicitly NOT a product of the dims, so a low
        extraction confidence can never silently drag the *scientific* strength
        down (or up). extraction_confidence is not even a candidate here.
        """
        resolved = [d for d in self.evidential_dims() if d.value is not None]
        if not resolved:
            return None
        return min(resolved, key=lambda d: d.value)  # type: ignore[arg-type,return-value]

    def sorries(self) -> list[str]:
        """Explicit missing / under-resolved premises (the 'sorry' analog)."""
        out: list[str] = []
        for d in self.dims():
            if not d.is_sorry:
                continue
            where = d.source or "no source"
            if d.value is None:
                out.append(f"{d.name}: unresolved ({where})")
            else:
                tail = f" — {d.note}" if d.note else ""
                out.append(f"{d.name}: weak ({d.value:.2f}; {where}){tail}")
        return out

    def as_vector(self) -> dict[str, Any]:
        """The named vector for display — five entries, never one number."""
        return {
            d.name: {
                "value": d.value,
                "source": d.source,
                "is_sorry": d.is_sorry,
                "note": d.note,
            }
            for d in self.dims()
        }

    def assert_no_extraction_laundering(self) -> None:
        """Hard invariant: extraction_confidence never enters the evidential calculus.

        Cheap to call on every compile; the unit tests also assert it directly.
        """
        if "extraction_confidence" in _EVIDENTIAL_DIMS:
            raise AssertionError(
                "extraction_confidence must never be an evidential dim — it would "
                "launder extraction certainty into scientific strength."
            )


def build_uncertainty(
    *,
    association_p: float | None = None,
    association_source: str = "",
    extraction_confidence: float | None = None,
    extraction_source: str = "",
    evidence_quality: float | None = None,
    evidence_source: str = "",
    coordinate_to_region: float | None = None,
    coordinate_source: str = "",
    task_to_ontology: float | None = None,
    task_source: str = "",
    notes: dict[str, str] | None = None,
) -> NamedUncertainty:
    """Assemble a :class:`NamedUncertainty`, deriving each dim's sorry-flag.

    Every value is validated to ``[0, 1]``; ``None`` means the dim could not be
    resolved (and therefore becomes a sorry). ``*_source`` strings carry provenance
    (e.g. ``"kg_verify.confidence"``, ``"mapping_profile:<hash>"``).
    """
    notes = notes or {}
    nu = NamedUncertainty(
        association_p=_mk(
            "association_p", association_p, association_source, notes.get("association_p", "")
        ),
        extraction_confidence=_mk(
            "extraction_confidence",
            extraction_confidence,
            extraction_source,
            notes.get("extraction_confidence", ""),
        ),
        evidence_quality=_mk(
            "evidence_quality", evidence_quality, evidence_source, notes.get("evidence_quality", "")
        ),
        coordinate_to_region=_mk(
            "coordinate_to_region",
            coordinate_to_region,
            coordinate_source,
            notes.get("coordinate_to_region", ""),
        ),
        task_to_ontology=_mk(
            "task_to_ontology", task_to_ontology, task_source, notes.get("task_to_ontology", "")
        ),
    )
    nu.assert_no_extraction_laundering()
    return nu
