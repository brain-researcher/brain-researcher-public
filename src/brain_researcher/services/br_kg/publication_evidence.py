"""Publication / cross-reference evidence collection for the KG query service.

Carved out of ``br_kg/query_service.py`` (decomposition slice 3). Holds the
publication-anchor matching, dataset/entity publication evidence collection, and
coordinate/citation/shared-reference overlap evidence builders.

``query_service`` re-exports these names so existing ``query_service.<name>``
references keep resolving. The shared qs helpers these call (``_as_list``,
``_rec_get``, ``_node_summary_payload``, ``_normalize_graph_node``,
``_entity_lookup_terms``, etc.) stay in ``query_service`` and are imported
lazily inside the consumers, avoiding an import cycle (verified both import
orders). ``KGNodeSummary`` is a type-hint-only dependency, imported under
``TYPE_CHECKING``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from brain_researcher.services.br_kg.graph.neo4j_graph_database import Neo4jGraphDB
    from brain_researcher.services.br_kg.query_service import KGNodeSummary

_PUBLICATION_IDENTIFIER_FIELDS = (
    "id",
    "dataset_id",
    "uid",
    "identifier",
    "study_id",
    "pmid",
    "pmcid",
    "doi",
)


def _publication_anchor_match_clause(node_alias: str) -> str:
    return (
        f"any(key IN $publication_identifier_keys WHERE "
        f"toLower(coalesce(toString({node_alias}[key]), '')) = term)"
    )


def _publication_anchor_lookup_terms(entity: KGNodeSummary) -> list[str]:
    # Lazy import to avoid an import cycle (query_service imports this module).
    from brain_researcher.services.br_kg.query_service import (
        _canonical_ood_node_type,
        _dataset_publication_lookup_terms,
        _entity_lookup_terms,
    )

    terms = list(_dataset_publication_lookup_terms(entity))
    if _canonical_ood_node_type(entity.node_type) in {"Publication", "Paper", "Study"}:
        terms.extend(_entity_lookup_terms(entity))
    seen: set[str] = set()
    deduped: list[str] = []
    for term in terms:
        key = str(term or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def _collect_dataset_publication_anchor_evidence(
    entity: KGNodeSummary,
    *,
    limit: int,
    client: Neo4jGraphDB,
) -> list[dict[str, Any]]:
    # Lazy import to avoid an import cycle (query_service imports this module).
    from brain_researcher.services.br_kg.query_service import (
        _as_list,
        _dataset_publication_lookup_terms,
        _normalize_publication_anchor_record,
    )

    lookup_terms = _dataset_publication_lookup_terms(entity)
    if not lookup_terms:
        return []

    cypher = f"""
    MATCH (p:Publication)
    WHERE any(term IN $lookup_terms WHERE
      {_publication_anchor_match_clause("p")} OR
      toLower(coalesce(toString(p.label), '')) = term OR
      toLower(coalesce(toString(p.name), '')) = term OR
      toLower(coalesce(toString(p.title), '')) = term OR
      any(alias IN coalesce(p.aliases, []) WHERE toLower(alias) = term)
    )
    OPTIONAL MATCH (p)-[rc:REPORTS_CLAIM]->(c:Claim)
    OPTIONAL MATCH (e:EvidenceSpan)-[sup:SUPPORTS]->(c)
    RETURN
      p AS p,
      'DATASET_PUBLICATION_ANCHOR' AS mention_type,
      {{
        dataset_publication_anchor: true,
        evidence_quality: 'medium'
      }} AS mention_props,
      c AS c,
      properties(rc) AS claim_edge_props,
      e AS e,
      properties(sup) AS support_edge_props
    LIMIT $limit
    """
    records = _as_list(
        client._run(
            cypher,
            {
                "lookup_terms": lookup_terms,
                "publication_identifier_keys": list(_PUBLICATION_IDENTIFIER_FIELDS),
                "limit": int(limit),
            },
        )
    )
    rows: list[dict[str, Any]] = []
    for record in records:
        row = _normalize_publication_anchor_record(record, entity=entity)
        if row is not None:
            rows.append(row)
    return rows


def _collect_publication_evidence_for_entity(
    entity: KGNodeSummary,
    *,
    limit: int,
    client: Neo4jGraphDB,
) -> list[dict[str, Any]]:
    # Lazy import to avoid an import cycle (query_service imports this module).
    from brain_researcher.services.br_kg.query_service import (
        _KG_IDENTIFIER_FIELDS,
        _as_list,
        _entity_lookup_terms,
        _identifier_exact_match_clause,
        _is_dataset_like_entity,
        _is_onvoc_like_entity,
        _node_summary_payload,
        _normalize_graph_node,
        _rec_get,
    )

    lookup_terms = _entity_lookup_terms(entity)
    if not lookup_terms:
        return []

    cypher = f"""
    MATCH (p)
    WHERE any(lbl IN labels(p) WHERE lbl IN ['Publication', 'Paper', 'Study'])
    MATCH (p)-[m]->(ent)
    WHERE type(m) IN ['MENTIONS', 'MENTIONS_REGION']
      AND any(term IN $lookup_terms WHERE
        {_identifier_exact_match_clause("ent")} OR
        toLower(coalesce(toString(ent.label), '')) = term OR
        toLower(coalesce(toString(ent.name), '')) = term OR
        toLower(elementId(ent)) = term
      )
    OPTIONAL MATCH (p)-[rc:REPORTS_CLAIM]->(c:Claim)
    OPTIONAL MATCH (e:EvidenceSpan)-[sup:SUPPORTS]->(c)
    RETURN
      p AS p,
      ent AS ent,
      CASE
        WHEN any(lbl IN labels(p) WHERE lbl = 'Study')
          THEN coalesce(toString(p.id), elementId(p))
        ELSE head([
          (p)-[:ALIGNS_WITH]->(aligned_study:Study) |
          coalesce(toString(aligned_study.id), elementId(aligned_study))
        ])
      END AS aligned_study_id,
      CASE
        WHEN any(lbl IN labels(p) WHERE lbl IN ['Publication', 'Paper'])
          THEN coalesce(
            toString(p.id),
            toString(p.pmid),
            toString(p.doi),
            elementId(p)
          )
        ELSE head([
          (aligned_publication)-[:ALIGNS_WITH]->(p)
          WHERE any(lbl IN labels(aligned_publication) WHERE lbl IN ['Publication', 'Paper']) |
          coalesce(
            toString(aligned_publication.id),
            toString(aligned_publication.pmid),
            toString(aligned_publication.doi),
            elementId(aligned_publication)
          )
        ])
      END AS aligned_publication_id,
      type(m) AS mention_type,
      properties(m) AS mention_props,
      c AS c,
      properties(rc) AS claim_edge_props,
      e AS e,
      properties(sup) AS support_edge_props
    LIMIT $limit
    """
    records = _as_list(
        client._run(
            cypher,
            {
                "lookup_terms": lookup_terms,
                "identifier_keys": list(_KG_IDENTIFIER_FIELDS),
                "limit": int(limit),
            },
        )
    )

    rows: list[dict[str, Any]] = []
    for record in records:
        publication = _normalize_graph_node(
            _rec_get(record, "p"), default_type="Publication"
        )
        if not publication.get("kg_id"):
            continue
        aligned_study_id = str(_rec_get(record, "aligned_study_id") or "").strip()
        if aligned_study_id:
            publication["aligned_study_id"] = aligned_study_id
        aligned_publication_id = str(
            _rec_get(record, "aligned_publication_id") or ""
        ).strip()
        if aligned_publication_id:
            publication["aligned_publication_id"] = aligned_publication_id
        matched = _normalize_graph_node(
            _rec_get(record, "ent"), default_type=entity.node_type
        )
        claim = _normalize_graph_node(_rec_get(record, "c"), default_type="Claim")
        if not claim.get("kg_id"):
            claim = {}
        evidence_span = _normalize_graph_node(
            _rec_get(record, "e"), default_type="EvidenceSpan"
        )
        if not evidence_span.get("kg_id"):
            evidence_span = {}
        rows.append(
            {
                "publication": publication,
                "matched_entity": matched or _node_summary_payload(entity),
                "mention_type": str(_rec_get(record, "mention_type") or "MENTIONS"),
                "mention_props": _rec_get(record, "mention_props", {}) or {},
                "claim": claim,
                "claim_edge_props": _rec_get(record, "claim_edge_props", {}) or {},
                "evidence_span": evidence_span,
                "support_edge_props": _rec_get(record, "support_edge_props", {}) or {},
                "evidence_anchor_scope": "direct",
            }
        )
    if _is_onvoc_like_entity(entity):
        mediated_records = _as_list(
            client._run(
                f"""
                MATCH (d:Dataset)
                WHERE EXISTS {{
                  MATCH (d)-[r]-(o)
                  WHERE type(r) IN ['IN_ONVOC', 'HAS_ONVOC_ANNOTATION']
                    AND any(lbl IN labels(o) WHERE lbl IN ['Concept', 'OnvocClass', 'OntologyConcept', 'LegacyOnvocTag'])
                    AND (
                      toUpper(coalesce(o.scheme, '')) IN ['ONVOC', 'ONVOC_LEGACY']
                      OR toUpper(coalesce(o.id, '')) STARTS WITH 'ONVOC_'
                      OR toUpper(coalesce(o.id, '')) STARTS WITH 'ONVOC:'
                      OR toLower(coalesce(o.id, '')) STARTS WITH 'legacy_onvoc:'
                    )
                    AND any(term IN $lookup_terms WHERE
                      {_identifier_exact_match_clause("o")} OR
                      toLower(coalesce(toString(o.label), '')) = term OR
                      toLower(coalesce(toString(o.name), '')) = term
                    )
                }}
                MATCH (d)-[:CITED_BY]->(p)
                WHERE any(lbl IN labels(p) WHERE lbl IN ['Publication', 'Paper', 'Study'])
                OPTIONAL MATCH (p)-[rc:REPORTS_CLAIM]->(c:Claim)
                OPTIONAL MATCH (e:EvidenceSpan)-[sup:SUPPORTS]->(c)
                RETURN
                  p AS p,
                  d AS d,
                  CASE
                    WHEN any(lbl IN labels(p) WHERE lbl = 'Study')
                      THEN coalesce(toString(p.id), elementId(p))
                    ELSE head([
                      (p)-[:ALIGNS_WITH]->(aligned_study:Study) |
                      coalesce(toString(aligned_study.id), elementId(aligned_study))
                    ])
                  END AS aligned_study_id,
                  CASE
                    WHEN any(lbl IN labels(p) WHERE lbl IN ['Publication', 'Paper'])
                      THEN coalesce(
                        toString(p.id),
                        toString(p.pmid),
                        toString(p.doi),
                        elementId(p)
                      )
                    ELSE head([
                      (aligned_publication)-[:ALIGNS_WITH]->(p)
                      WHERE any(lbl IN labels(aligned_publication) WHERE lbl IN ['Publication', 'Paper']) |
                      coalesce(
                        toString(aligned_publication.id),
                        toString(aligned_publication.pmid),
                        toString(aligned_publication.doi),
                        elementId(aligned_publication)
                      )
                    ])
                  END AS aligned_publication_id,
                  'DATASET_MEDIATED' AS mention_type,
                  {{dataset_mediated: true}} AS mention_props,
                  c AS c,
                  properties(rc) AS claim_edge_props,
                  e AS e,
                  properties(sup) AS support_edge_props
                LIMIT $limit
                """,
                {
                    "lookup_terms": lookup_terms,
                    "identifier_keys": list(_KG_IDENTIFIER_FIELDS),
                    "limit": int(limit),
                },
            )
        )
        for record in mediated_records:
            publication = _normalize_graph_node(
                _rec_get(record, "p"), default_type="Publication"
            )
            if not publication.get("kg_id"):
                continue
            aligned_study_id = str(_rec_get(record, "aligned_study_id") or "").strip()
            if aligned_study_id:
                publication["aligned_study_id"] = aligned_study_id
            aligned_publication_id = str(
                _rec_get(record, "aligned_publication_id") or ""
            ).strip()
            if aligned_publication_id:
                publication["aligned_publication_id"] = aligned_publication_id
            matched = _normalize_graph_node(
                _rec_get(record, "d"), default_type="Dataset"
            )
            claim = _normalize_graph_node(_rec_get(record, "c"), default_type="Claim")
            if not claim.get("kg_id"):
                claim = {}
            evidence_span = _normalize_graph_node(
                _rec_get(record, "e"), default_type="EvidenceSpan"
            )
            if not evidence_span.get("kg_id"):
                evidence_span = {}
            rows.append(
                {
                    "publication": publication,
                    "matched_entity": matched or _node_summary_payload(entity),
                    "mention_type": str(
                        _rec_get(record, "mention_type") or "DATASET_MEDIATED"
                    ),
                    "mention_props": _rec_get(record, "mention_props", {}) or {},
                    "claim": claim,
                    "claim_edge_props": _rec_get(record, "claim_edge_props", {}) or {},
                    "evidence_span": evidence_span,
                    "support_edge_props": _rec_get(record, "support_edge_props", {}) or {},
                    "evidence_anchor_scope": "dataset_mediated",
                }
            )
    deduped_rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        publication = row.get("publication") or {}
        matched = row.get("matched_entity") or {}
        key = (
            _publication_identity_key(publication),
            str(matched.get("kg_id") or matched.get("id") or ""),
            str(row.get("mention_type") or ""),
        )
        existing = deduped_rows.get(key)
        if existing is None or _publication_row_priority(row) < _publication_row_priority(
            existing
        ):
            deduped_rows[key] = row
    ordered_rows = list(deduped_rows.values())
    if ordered_rows or not _is_dataset_like_entity(entity):
        return ordered_rows
    return _collect_dataset_publication_anchor_evidence(
        entity,
        limit=limit,
        client=client,
    )


def _publication_entity_match_clause(
    publication_var: str,
    mention_var: str,
    entity_var: str,
    *,
    entity_terms_param: str,
    publication_terms_param: str,
) -> str:
    # Lazy import to avoid an import cycle (query_service imports this module).
    from brain_researcher.services.br_kg.query_service import (
        _identifier_exact_match_clause,
    )

    return f"""
    (
      EXISTS {{
        MATCH ({publication_var})-[{mention_var}]->({entity_var})
        WHERE type({mention_var}) IN ['MENTIONS', 'MENTIONS_REGION']
          AND any(term IN ${entity_terms_param} WHERE
            {_identifier_exact_match_clause(entity_var)} OR
            toLower(coalesce(toString({entity_var}.label), '')) = term OR
            toLower(coalesce(toString({entity_var}.name), '')) = term OR
            toLower(elementId({entity_var})) = term
          )
      }}
      OR any(term IN ${publication_terms_param} WHERE
        {_publication_anchor_match_clause(publication_var)} OR
        toLower(coalesce(toString({publication_var}.label), '')) = term OR
        toLower(coalesce(toString({publication_var}.name), '')) = term OR
        toLower(coalesce(toString({publication_var}.title), '')) = term OR
        any(alias IN coalesce({publication_var}.aliases, []) WHERE toLower(alias) = term)
      )
    )
    """


def _collect_coordinate_overlap_evidence(
    subject: KGNodeSummary,
    obj: KGNodeSummary,
    *,
    limit: int,
    client: Neo4jGraphDB,
) -> list[dict[str, Any]]:
    # Lazy import to avoid an import cycle (query_service imports this module).
    from brain_researcher.services.br_kg.query_service import (
        _KG_IDENTIFIER_FIELDS,
        _as_list,
        _entity_lookup_terms,
        _node_summary_payload,
        _normalize_graph_node,
        _rec_get,
    )

    subject_terms = _entity_lookup_terms(subject)
    object_terms = _entity_lookup_terms(obj)
    subject_pub_terms = _publication_anchor_lookup_terms(subject)
    object_pub_terms = _publication_anchor_lookup_terms(obj)
    if not subject_terms or not object_terms:
        return []
    subject_match_clause = _publication_entity_match_clause(
        "p_a",
        "m_a",
        "ent_a",
        entity_terms_param="subject_terms",
        publication_terms_param="subject_publication_terms",
    )
    object_match_clause = _publication_entity_match_clause(
        "p_b",
        "m_b",
        "ent_b",
        entity_terms_param="object_terms",
        publication_terms_param="object_publication_terms",
    )

    cypher = f"""
    MATCH (p_a:Publication)-[:HAS_COORDINATE]->(coord)<-[:HAS_COORDINATE]-(p_b:Publication)
    WHERE p_a <> p_b
      AND {subject_match_clause}
      AND {object_match_clause}
    WITH p_a, p_b, collect(coord) AS coords, count(coord) AS shared_coordinate_count
    RETURN
      p_a AS p_a,
      p_b AS p_b,
      coords[0] AS coord,
      shared_coordinate_count AS shared_coordinate_count
    ORDER BY shared_coordinate_count DESC,
      coalesce(p_a.year, 0) DESC,
      coalesce(p_b.year, 0) DESC
    LIMIT $limit
    """
    records = _as_list(
        client._run(
            cypher,
            {
                "subject_terms": subject_terms,
                "object_terms": object_terms,
                "subject_publication_terms": subject_pub_terms,
                "object_publication_terms": object_pub_terms,
                "identifier_keys": list(_KG_IDENTIFIER_FIELDS),
                "publication_identifier_keys": list(_PUBLICATION_IDENTIFIER_FIELDS),
                "limit": int(limit),
            },
        )
    )

    rows: list[dict[str, Any]] = []
    for record in records:
        pub_a = _normalize_graph_node(
            _rec_get(record, "p_a"), default_type="Publication"
        )
        pub_b = _normalize_graph_node(
            _rec_get(record, "p_b"), default_type="Publication"
        )
        coord = _normalize_graph_node(
            _rec_get(record, "coord"), default_type="Coordinate"
        )
        if not pub_a.get("kg_id") or not pub_b.get("kg_id"):
            continue
        shared_count = max(1, int(_rec_get(record, "shared_coordinate_count", 1) or 1))
        rows.append(
            {
                "publication": pub_a,
                "secondary_publication": pub_b,
                "matched_entity": _node_summary_payload(subject),
                "secondary_matched_entity": _node_summary_payload(obj),
                "mention_type": "COORDINATE_OVERLAP",
                "mention_props": {
                    "typed_path_kind": "coordinate_overlap",
                    "shared_coordinate_count": shared_count,
                    "claim_polarity": "supports",
                    "claim_strength": round(min(0.95, 0.45 + 0.08 * shared_count), 3),
                    "mention_strength": round(min(0.95, 0.45 + 0.08 * shared_count), 3),
                    "method_rigor": 0.63,
                    "evidence_quality": "high",
                    "provenance_completeness": 0.74,
                },
                "secondary_mention_props": {
                    "mention_strength": round(min(0.95, 0.42 + 0.08 * shared_count), 3),
                },
                "claim": {},
                "claim_edge_props": {},
                "evidence_span": {},
                "support_edge_props": {},
                "shared_coordinate": coord,
                "typed_path_kind": "coordinate_overlap",
                "evidence_anchor_scope": "typed_path",
            }
        )
    return rows


def _collect_citation_bridge_evidence(
    subject: KGNodeSummary,
    obj: KGNodeSummary,
    *,
    limit: int,
    client: Neo4jGraphDB,
) -> list[dict[str, Any]]:
    # Lazy import to avoid an import cycle (query_service imports this module).
    from brain_researcher.services.br_kg.query_service import (
        _KG_IDENTIFIER_FIELDS,
        _as_list,
        _entity_lookup_terms,
        _node_summary_payload,
        _normalize_graph_node,
        _rec_get,
    )

    subject_terms = _entity_lookup_terms(subject)
    object_terms = _entity_lookup_terms(obj)
    subject_pub_terms = _publication_anchor_lookup_terms(subject)
    object_pub_terms = _publication_anchor_lookup_terms(obj)
    if not subject_terms or not object_terms:
        return []
    subject_match_clause = _publication_entity_match_clause(
        "p_a",
        "m_a",
        "ent_a",
        entity_terms_param="subject_terms",
        publication_terms_param="subject_publication_terms",
    )
    object_match_clause = _publication_entity_match_clause(
        "p_b",
        "m_b",
        "ent_b",
        entity_terms_param="object_terms",
        publication_terms_param="object_publication_terms",
    )

    cypher = f"""
    CALL {{
      MATCH (p_a:Publication)-[cite:CITES]->(p_b:Publication)
      WHERE p_a <> p_b
        AND {subject_match_clause}
        AND {object_match_clause}
      RETURN
        p_a AS p_a,
        p_b AS p_b,
        properties(cite) AS cite_props,
        'subject_to_object' AS citation_direction
      UNION
      MATCH (p_b:Publication)-[cite:CITES]->(p_a:Publication)
      WHERE p_a <> p_b
        AND {subject_match_clause}
        AND {object_match_clause}
      RETURN
        p_a AS p_a,
        p_b AS p_b,
        properties(cite) AS cite_props,
        'object_to_subject' AS citation_direction
    }}
    RETURN
      p_a AS p_a,
      p_b AS p_b,
      cite_props AS cite_props,
      citation_direction AS citation_direction
    ORDER BY
      coalesce(p_a.year, 0) DESC,
      coalesce(p_b.year, 0) DESC
    LIMIT $limit
    """
    records = _as_list(
        client._run(
            cypher,
            {
                "subject_terms": subject_terms,
                "object_terms": object_terms,
                "subject_publication_terms": subject_pub_terms,
                "object_publication_terms": object_pub_terms,
                "identifier_keys": list(_KG_IDENTIFIER_FIELDS),
                "publication_identifier_keys": list(_PUBLICATION_IDENTIFIER_FIELDS),
                "limit": int(limit),
            },
        )
    )

    rows: list[dict[str, Any]] = []
    for record in records:
        pub_a = _normalize_graph_node(
            _rec_get(record, "p_a"), default_type="Publication"
        )
        pub_b = _normalize_graph_node(
            _rec_get(record, "p_b"), default_type="Publication"
        )
        if not pub_a.get("kg_id") or not pub_b.get("kg_id"):
            continue
        citation_direction = str(
            _rec_get(record, "citation_direction") or "subject_to_object"
        ).strip()
        cite_props = _rec_get(record, "cite_props", {}) or {}
        rows.append(
            {
                "publication": pub_a,
                "secondary_publication": pub_b,
                "matched_entity": _node_summary_payload(subject),
                "secondary_matched_entity": _node_summary_payload(obj),
                "mention_type": "CITATION_BRIDGE",
                "mention_props": {
                    "typed_path_kind": "citation_bridge",
                    "citation_direction": citation_direction,
                    "claim_polarity": "supports",
                    "claim_strength": 0.58,
                    "mention_strength": 0.58,
                    "method_rigor": 0.57,
                    "evidence_quality": "medium",
                    "provenance_completeness": 0.66,
                },
                "secondary_mention_props": {
                    "mention_strength": 0.55,
                },
                "claim": {},
                "claim_edge_props": {},
                "evidence_span": {},
                "support_edge_props": {},
                "citation_edge_props": cite_props,
                "typed_path_kind": "citation_bridge",
                "evidence_anchor_scope": "typed_path",
            }
        )
    return rows


def _collect_shared_reference_overlap_evidence(
    subject: KGNodeSummary,
    obj: KGNodeSummary,
    *,
    limit: int,
    client: Neo4jGraphDB,
) -> list[dict[str, Any]]:
    # Lazy import to avoid an import cycle (query_service imports this module).
    from brain_researcher.services.br_kg.query_service import (
        _KG_IDENTIFIER_FIELDS,
        _as_list,
        _entity_lookup_terms,
        _node_summary_payload,
        _normalize_graph_node,
        _rec_get,
    )

    subject_terms = _entity_lookup_terms(subject)
    object_terms = _entity_lookup_terms(obj)
    subject_pub_terms = _publication_anchor_lookup_terms(subject)
    object_pub_terms = _publication_anchor_lookup_terms(obj)
    if not subject_terms or not object_terms:
        return []
    subject_match_clause = _publication_entity_match_clause(
        "p_a",
        "m_a",
        "ent_a",
        entity_terms_param="subject_terms",
        publication_terms_param="subject_publication_terms",
    )
    object_match_clause = _publication_entity_match_clause(
        "p_b",
        "m_b",
        "ent_b",
        entity_terms_param="object_terms",
        publication_terms_param="object_publication_terms",
    )

    cypher = f"""
    MATCH (p_a:Publication)-[:CITES]->(ref:Publication)<-[:CITES]-(p_b:Publication)
    WHERE p_a <> p_b
      AND {subject_match_clause}
      AND {object_match_clause}
    WITH p_a, p_b, collect(ref) AS refs, count(DISTINCT ref) AS shared_reference_count
    RETURN
      p_a AS p_a,
      p_b AS p_b,
      refs[0] AS ref,
      shared_reference_count AS shared_reference_count
    ORDER BY shared_reference_count DESC,
      coalesce(p_a.year, 0) DESC,
      coalesce(p_b.year, 0) DESC
    LIMIT $limit
    """
    records = _as_list(
        client._run(
            cypher,
            {
                "subject_terms": subject_terms,
                "object_terms": object_terms,
                "subject_publication_terms": subject_pub_terms,
                "object_publication_terms": object_pub_terms,
                "identifier_keys": list(_KG_IDENTIFIER_FIELDS),
                "publication_identifier_keys": list(_PUBLICATION_IDENTIFIER_FIELDS),
                "limit": int(limit),
            },
        )
    )

    rows: list[dict[str, Any]] = []
    for record in records:
        pub_a = _normalize_graph_node(
            _rec_get(record, "p_a"), default_type="Publication"
        )
        pub_b = _normalize_graph_node(
            _rec_get(record, "p_b"), default_type="Publication"
        )
        ref = _normalize_graph_node(_rec_get(record, "ref"), default_type="Publication")
        if not pub_a.get("kg_id") or not pub_b.get("kg_id") or not ref.get("kg_id"):
            continue
        shared_count = max(1, int(_rec_get(record, "shared_reference_count", 1) or 1))
        rows.append(
            {
                "publication": pub_a,
                "secondary_publication": pub_b,
                "matched_entity": _node_summary_payload(subject),
                "secondary_matched_entity": _node_summary_payload(obj),
                "mention_type": "SHARED_REFERENCE_OVERLAP",
                "mention_props": {
                    "typed_path_kind": "shared_reference_overlap",
                    "shared_reference_count": shared_count,
                    "claim_polarity": "supports",
                    "claim_strength": round(min(0.9, 0.44 + 0.06 * shared_count), 3),
                    "mention_strength": round(min(0.9, 0.44 + 0.06 * shared_count), 3),
                    "method_rigor": 0.56,
                    "evidence_quality": "medium",
                    "provenance_completeness": 0.69,
                },
                "secondary_mention_props": {
                    "mention_strength": round(min(0.9, 0.42 + 0.06 * shared_count), 3),
                },
                "claim": {},
                "claim_edge_props": {},
                "evidence_span": {},
                "support_edge_props": {},
                "shared_reference": ref,
                "typed_path_kind": "shared_reference_overlap",
                "evidence_anchor_scope": "typed_path",
            }
        )
    return rows


def _publication_value(
    publication: Mapping[str, Any] | None,
    key: str,
) -> str:
    if not isinstance(publication, Mapping):
        return ""
    value = publication.get(key)
    if value in (None, ""):
        props = publication.get("properties")
        if isinstance(props, Mapping):
            value = props.get(key)
    return str(value or "").strip()


def _publication_identity_key(publication: Mapping[str, Any] | None) -> str:
    # Lazy import to avoid an import cycle (query_service imports this module).
    from brain_researcher.services.br_kg.query_service import _normalize_paper_like_text

    aligned_study_id = _publication_value(publication, "aligned_study_id").lower()
    if aligned_study_id:
        return f"aligned_study:{aligned_study_id}"
    aligned_publication_id = _publication_value(
        publication, "aligned_publication_id"
    ).lower()
    if aligned_publication_id:
        return f"aligned_publication:{aligned_publication_id}"
    pmid = _publication_value(publication, "pmid").lower()
    if pmid:
        return f"pmid:{pmid}"
    doi = _publication_value(publication, "doi").lower()
    if doi:
        return f"doi:{doi}"
    title = _normalize_paper_like_text(
        _publication_value(publication, "title")
        or _publication_value(publication, "label")
    )
    if title:
        return f"title:{title}"
    kg_id = _publication_value(publication, "kg_id").lower()
    if kg_id:
        return f"id:{kg_id}"
    return ""


def _publication_row_priority(row: Mapping[str, Any]) -> tuple[int, int, int]:
    publication = row.get("publication") or {}
    node_type = str((publication or {}).get("node_type") or "").strip().lower()
    source_rank = 0 if node_type in {"publication", "paper"} else 1
    claim_rank = 0 if (row.get("claim") or {}).get("kg_id") else 1
    scope_rank = 0 if str(row.get("evidence_anchor_scope") or "") == "direct" else 1
    return (source_rank, claim_rank, scope_rank)


def _publication_ids_from_rows(rows: Sequence[dict[str, Any]]) -> set[str]:
    pub_ids: set[str] = set()
    for row in rows:
        publication_id = _publication_identity_key(row.get("publication") or {})
        if publication_id:
            pub_ids.add(publication_id)
    return pub_ids
