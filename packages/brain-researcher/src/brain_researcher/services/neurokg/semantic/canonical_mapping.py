"""Canonical relation and link-mode mapping for lens evidence edges."""

from __future__ import annotations

from typing import Any, Mapping

_RELATION_ALIASES: dict[str, str] = {
    # Core ONVOC/entity links.
    "in_onvoc": "IN_ONVOC",
    "onvoc": "IN_ONVOC",
    "maps_to": "MAPS_TO",
    "map_to": "MAPS_TO",
    "mapped_to": "MAPS_TO",
    "aligns_with": "ALIGNS_WITH",
    "classified_under": "CLASSIFIED_UNDER",
    "subclass_of": "CLASSIFIED_UNDER",
    "is_a": "CLASSIFIED_UNDER",
    "about": "ABOUT",
    "studies": "STUDIES",
    "has_population": "HAS_POPULATION",
    "has_lead_locus": "HAS_LEAD_LOCUS",
    "implicates_gene": "IMPLICATES_GENE",
    "associated_with": "ASSOCIATED_WITH",
    "mentions_concept": "MENTIONS_CONCEPT",
    "involves_construct": "INVOLVES_CONSTRUCT",
    "describes": "DESCRIBES",
    "measures": "MEASURES",
    "related_to": "RELATED_TO",
    # Task links.
    "has_task": "HAS_TASK",
    "uses_task": "USES_TASK",
    "uses_paradigm": "USES_PARADIGM",
    "implements_task": "IMPLEMENTS_TASK",
    # Dataset/statmap links.
    "generated_from": "GENERATED_FROM",
    "derived_from": "DERIVED_FROM",
    "has_resource": "HAS_RESOURCE",
    "from_dataset": "FROM_DATASET",
    "uses_dataset": "USES_DATASET",
    # Contrast links.
    "measures_contrast": "MEASURES_CONTRAST",
    "has_contrast": "HAS_CONTRAST",
    "contrast_of": "CONTRAST_OF",
    "describes_contrast": "DESCRIBES_CONTRAST",
    # Evidence links.
    "evidence_of": "EVIDENCE_OF",
    "reports_claim": "REPORTS_CLAIM",
    "supports": "SUPPORTS",
    "assumes": "ASSUMES",
    "challenges_assumption": "CHALLENGES_ASSUMPTION",
    "contradicts": "CONTRADICTS",
    "null_result_for": "NULL_RESULT_FOR",
    "replicates": "REPLICATES",
    "failed_replication_of": "FAILED_REPLICATION_OF",
    "generated": "GENERATED",
}

_LINK_MODE_ALIASES: dict[str, str] = {
    "direct": "direct",
    "direct_link": "direct",
    "direct_edge": "direct",
    "paper": "via_paper",
    "publication": "via_paper",
    "via_publication": "via_paper",
    "via_paper": "via_paper",
    "study": "via_study",
    "experiment": "via_study",
    "via_study": "via_study",
    "task": "via_task",
    "via_task": "via_task",
    "statmap": "via_statmap",
    "map": "via_statmap",
    "via_statmap": "via_statmap",
}

_RELATION_SEMANTICS: dict[str, str] = {
    "IN_ONVOC": "ontology_alignment",
    "MAPS_TO": "ontology_alignment",
    "ALIGNS_WITH": "study_alignment",
    "CLASSIFIED_UNDER": "taxonomy_hierarchy",
    "ABOUT": "concept_association",
    "STUDIES": "concept_association",
    "HAS_POPULATION": "study_association",
    "HAS_LEAD_LOCUS": "genetic_association",
    "IMPLICATES_GENE": "genetic_association",
    "ASSOCIATED_WITH": "genetic_association",
    "MENTIONS_CONCEPT": "concept_association",
    "INVOLVES_CONSTRUCT": "concept_association",
    "DESCRIBES": "concept_association",
    "MEASURES": "concept_association",
    "RELATED_TO": "concept_association",
    "HAS_TASK": "task_association",
    "USES_TASK": "task_association",
    "USES_PARADIGM": "task_association",
    "IMPLEMENTS_TASK": "task_association",
    "GENERATED_FROM": "dataset_association",
    "DERIVED_FROM": "dataset_association",
    "HAS_RESOURCE": "dataset_association",
    "FROM_DATASET": "dataset_association",
    "USES_DATASET": "dataset_association",
    "MEASURES_CONTRAST": "contrast_association",
    "HAS_CONTRAST": "contrast_association",
    "CONTRAST_OF": "contrast_association",
    "DESCRIBES_CONTRAST": "contrast_association",
    "EVIDENCE_OF": "coordinate_evidence",
    "REPORTS_CLAIM": "claim_provenance",
    "SUPPORTS": "claim_provenance",
    "ASSUMES": "assumption_association",
    "CHALLENGES_ASSUMPTION": "assumption_association",
    "CONTRADICTS": "claim_relation",
    "NULL_RESULT_FOR": "claim_relation",
    "REPLICATES": "claim_relation",
    "FAILED_REPLICATION_OF": "claim_relation",
    "GENERATED": "measurement_provenance",
}

_LINK_MODE_PATH_SEMANTICS: dict[str, str] = {
    "direct": "direct",
    "via_paper": "mediated_publication",
    "via_study": "mediated_study",
    "via_task": "mediated_task",
    "via_statmap": "mediated_statmap",
}


def _normalize_token(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    if not text:
        return ""
    for old, new in (("-", "_"), (" ", "_"), ("/", "_")):
        text = text.replace(old, new)
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_")


def canonicalize_relation_type(relation_type: Any) -> str | None:
    """Normalize a relation type to its canonical uppercase representation."""

    token = _normalize_token(relation_type)
    if not token:
        return None
    return _RELATION_ALIASES.get(token, token.upper())


def canonicalize_link_mode(link_mode: Any) -> str | None:
    """Normalize lens evidence `link_mode` aliases."""

    token = _normalize_token(link_mode)
    if not token:
        return None
    return _LINK_MODE_ALIASES.get(token, token)


def canonicalize_lens_edge_semantics(
    *,
    relation_type: Any = None,
    link_mode: Any = None,
) -> dict[str, Any]:
    """Map relation type + link mode into canonical lens edge semantics."""

    canonical_relation = canonicalize_relation_type(relation_type)
    canonical_link_mode = canonicalize_link_mode(link_mode)

    if canonical_link_mode is None:
        canonical_link_mode = "direct"
        basis = "relation_type" if canonical_relation else "default"
    else:
        basis = "link_mode"

    relation_semantics = _RELATION_SEMANTICS.get(canonical_relation, "association")
    path_semantics = _LINK_MODE_PATH_SEMANTICS.get(canonical_link_mode, "direct")
    edge_semantics = f"{path_semantics}:{relation_semantics}"

    return {
        "relation_type": canonical_relation,
        "link_mode": canonical_link_mode,
        "relation_semantics": relation_semantics,
        "path_semantics": path_semantics,
        "edge_semantics": edge_semantics,
        "is_mediated": path_semantics.startswith("mediated_"),
        "basis": basis,
    }


def append_canonical_lens_edge_semantics(
    item: Mapping[str, Any],
    *,
    relation_key: str = "relation_type",
    link_mode_key: str = "link_mode",
) -> dict[str, Any]:
    """Return an append-only enriched evidence item with canonical semantics."""

    enriched = dict(item)
    mapped = canonicalize_lens_edge_semantics(
        relation_type=item.get(relation_key),
        link_mode=item.get(link_mode_key),
    )
    enriched["canonical_relation_type"] = mapped["relation_type"]
    enriched["canonical_link_mode"] = mapped["link_mode"]
    enriched["canonical_relation_semantics"] = mapped["relation_semantics"]
    enriched["canonical_path_semantics"] = mapped["path_semantics"]
    enriched["canonical_edge_semantics"] = mapped["edge_semantics"]
    enriched["canonical_edge_is_mediated"] = mapped["is_mediated"]
    enriched["canonical_mapping_basis"] = mapped["basis"]
    return enriched


__all__ = [
    "append_canonical_lens_edge_semantics",
    "canonicalize_lens_edge_semantics",
    "canonicalize_link_mode",
    "canonicalize_relation_type",
]
