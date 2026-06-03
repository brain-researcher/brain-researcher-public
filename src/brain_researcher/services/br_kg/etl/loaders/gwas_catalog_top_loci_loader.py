"""GWAS Catalog top-loci loader for BR-KG.

Fetches genome-wide-significant lead-locus association data from the EBI GWAS
Catalog REST API and returns structured graph rows for:

- ``RiskLocus`` nodes
- ``RiskLocus -[:ASSOCIATED_WITH]-> DiseaseTrait`` edges
- ``Study -[:HAS_LEAD_LOCUS]-> RiskLocus`` edges when a GWAS Catalog study can be
  aligned to an existing OpenMed ``Study:GWASStudy`` node by PMID
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://www.ebi.ac.uk/gwas/rest/api"
_STUDIES_SEARCH = f"{_BASE}/studies/search/findByEfoTrait"
_STUDY_ASSOCIATIONS = f"{_BASE}/studies/{{accession}}/associations"

TOP_LOCI_SOURCE = "gwas_catalog_top_loci_loader"
GENOME_WIDE_SIGNIFICANCE = 5e-8

DISORDER_TRAIT_QUERIES: dict[str, str] = {
    "disease:schizophrenia": "schizophrenia",
    "disease:bipolar_disorder": "bipolar disorder",
    "disease:major_depression": "major depressive disorder",
    "disease:adhd": "attention deficit hyperactivity disorder",
    "disease:autism_spectrum_disorder": "autism spectrum disorder",
    "disease:ptsd": "post-traumatic stress disorder",
    "disease:ocd": "obsessive-compulsive disorder",
    "disease:anxiety_disorders": "anxiety disorder",
    "disease:tourette_syndrome": "Tourette syndrome",
    "disease:anorexia_nervosa": "anorexia nervosa",
    "disease:alcohol_dependence": "alcohol use disorder",
    "disease:opioid_dependence": "opioid dependence",
}


@dataclass(frozen=True)
class GWASCatalogStudySummary:
    accession_id: str
    pubmed_id: str | None = None
    publication: str | None = None
    title: str | None = None


@dataclass(frozen=True)
class TopLocusAssociation:
    disease_id: str
    study_accession: str
    study_pmid: str | None
    rsid: str
    effect_allele: str | None
    chromosome: str | None
    bp_location: int | None
    genes: tuple[str, ...]
    p_value: float
    p_mantissa: float | None = None
    p_exponent: int | None = None
    odds_ratio: float | None = None
    beta: float | None = None
    se: float | None = None


@dataclass(frozen=True)
class TopLociSnapshot:
    """Immutable result of a GWAS Catalog top-loci fetch."""

    node_rows: tuple[dict[str, Any], ...]
    relationship_rows: tuple[dict[str, Any], ...]
    stats: dict[str, Any] = field(default_factory=dict)


def _coerce_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric):
        return None
    return numeric


def _ordered_unique(values: Sequence[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _coerce_text(value)
        if not text:
            continue
        marker = text.lower()
        if marker in seen:
            continue
        seen.add(marker)
        out.append(text)
    return out


def _structured_node_row(
    node_id: str, labels: Sequence[str], properties: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "labels": tuple(labels),
        "properties": dict(properties),
    }


def _structured_relationship_row(
    start_id: str,
    end_id: str,
    rel_type: str,
    properties: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "start_id": start_id,
        "end_id": end_id,
        "rel_type": rel_type,
        "properties": dict(properties),
    }


def _association_sort_key(association: TopLocusAssociation) -> tuple[float, str]:
    return (association.p_value, association.rsid)


def _is_stronger(
    candidate: TopLocusAssociation, incumbent: TopLocusAssociation
) -> bool:
    if candidate.p_value != incumbent.p_value:
        return candidate.p_value < incumbent.p_value
    candidate_gene_count = len(candidate.genes)
    incumbent_gene_count = len(incumbent.genes)
    if candidate_gene_count != incumbent_gene_count:
        return candidate_gene_count > incumbent_gene_count
    candidate_located = (
        candidate.chromosome is not None and candidate.bp_location is not None
    )
    incumbent_located = (
        incumbent.chromosome is not None and incumbent.bp_location is not None
    )
    if candidate_located != incumbent_located:
        return candidate_located and not incumbent_located
    return candidate.study_accession < incumbent.study_accession


def _fetch_study_summaries(
    client: httpx.Client,
    trait_query: str,
    max_studies: int,
    delay: float,
    timeout: float,
) -> list[GWASCatalogStudySummary]:
    """Return up to *max_studies* study summaries for a trait query."""

    studies: list[GWASCatalogStudySummary] = []
    seen_accessions: set[str] = set()
    page = 0
    while len(studies) < max_studies:
        resp = client.get(
            _STUDIES_SEARCH,
            params={
                "efoTrait": trait_query,
                "page": page,
                "size": min(50, max_studies),
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        body = resp.json()
        items = body.get("_embedded", {}).get("studies", [])
        if not items:
            break
        for item in items:
            accession_id = _coerce_text(item.get("accessionId"))
            if not accession_id or accession_id in seen_accessions:
                continue
            publication_info = item.get("publicationInfo") or {}
            studies.append(
                GWASCatalogStudySummary(
                    accession_id=accession_id,
                    pubmed_id=_coerce_text(publication_info.get("pubmedId")),
                    publication=_coerce_text(publication_info.get("publication")),
                    title=_coerce_text(publication_info.get("title")),
                )
            )
            seen_accessions.add(accession_id)
            if len(studies) >= max_studies:
                break
        total_pages = body.get("page", {}).get("totalPages", 1)
        page += 1
        if page >= total_pages:
            break
        time.sleep(delay)
    return studies


def _fetch_study_associations(
    client: httpx.Client,
    accession: str,
    delay: float,
    timeout: float,
) -> list[dict[str, Any]]:
    """Return raw association dicts for a single GWAS study."""

    associations: list[dict[str, Any]] = []
    page = 0
    while True:
        resp = client.get(
            _STUDY_ASSOCIATIONS.format(accession=accession),
            params={"page": page, "size": 100},
            timeout=timeout,
        )
        resp.raise_for_status()
        body = resp.json()
        items = body.get("_embedded", {}).get("associations", [])
        if not items:
            break
        associations.extend(items)
        total_pages = body.get("page", {}).get("totalPages", 1)
        page += 1
        if page >= total_pages:
            break
        time.sleep(delay)
    return associations


def _extract_association(
    raw: dict[str, Any],
    *,
    disease_id: str,
    study: GWASCatalogStudySummary,
) -> TopLocusAssociation | None:
    """Parse a single raw association into a structured record."""

    loci = raw.get("loci") or []
    if not loci:
        return None

    risk_alleles = loci[0].get("strongestRiskAlleles") or []
    allele_name = risk_alleles[0].get("riskAlleleName", "") if risk_alleles else ""
    if not allele_name or "-" not in allele_name:
        return None

    rsid, effect_allele = allele_name.rsplit("-", 1)
    rsid = rsid.strip().lower()
    if not rsid.startswith("rs"):
        return None

    genes: list[str] = []
    for gene in loci[0].get("authorReportedGenes") or []:
        name = _coerce_text(gene.get("geneName"))
        if name:
            genes.append(name)

    chromosome: str | None = None
    bp_location: int | None = None
    snps = raw.get("snps") or []
    if snps:
        locations = snps[0].get("locations") or []
        if locations:
            chromosome = _coerce_text(locations[0].get("chromosomeName"))
            bp_location = _coerce_int(locations[0].get("chromosomePosition"))

    p_value = _coerce_float(raw.get("pvalue"))
    p_mantissa = _coerce_float(raw.get("pvalueMantissa"))
    p_exponent = _coerce_int(raw.get("pvalueExponent"))
    if p_value is None and p_mantissa is not None and p_exponent is not None:
        p_value = p_mantissa * (10**p_exponent)
    if p_value is None or p_value > GENOME_WIDE_SIGNIFICANCE:
        return None

    odds_ratio = _coerce_float(raw.get("orPerCopyNum"))
    beta = _coerce_float(raw.get("betaNum"))
    se = _coerce_float(raw.get("standardError"))

    return TopLocusAssociation(
        disease_id=disease_id,
        study_accession=study.accession_id,
        study_pmid=study.pubmed_id,
        rsid=rsid,
        effect_allele=_coerce_text(effect_allele),
        chromosome=chromosome,
        bp_location=bp_location,
        genes=tuple(_ordered_unique(genes[:3])),
        p_value=p_value,
        p_mantissa=p_mantissa,
        p_exponent=p_exponent,
        odds_ratio=odds_ratio,
        beta=beta,
        se=se,
    )


def _risk_locus_node_properties(association: TopLocusAssociation) -> dict[str, Any]:
    props: dict[str, Any] = {
        "id": f"locus:{association.rsid}",
        "name": association.rsid,
        "rsid": association.rsid,
        "source": TOP_LOCI_SOURCE,
    }
    if association.chromosome:
        props["chromosome"] = association.chromosome
    if association.bp_location is not None:
        props["base_pair_location"] = association.bp_location
    if association.genes:
        props["nearest_gene"] = association.genes[0]
        props["nearest_genes"] = list(association.genes)
    if association.effect_allele:
        props["effect_allele"] = association.effect_allele
    return props


def _merge_risk_locus_node(
    existing: dict[str, Any], candidate: TopLocusAssociation
) -> None:
    props = existing["properties"]
    if candidate.chromosome and not props.get("chromosome"):
        props["chromosome"] = candidate.chromosome
    if candidate.bp_location is not None and props.get("base_pair_location") is None:
        props["base_pair_location"] = candidate.bp_location
    if candidate.genes:
        if not props.get("nearest_gene"):
            props["nearest_gene"] = candidate.genes[0]
        merged_genes = _ordered_unique(
            list(props.get("nearest_genes") or []) + list(candidate.genes)
        )
        if merged_genes:
            props["nearest_genes"] = merged_genes[:3]
    if candidate.effect_allele and not props.get("effect_allele"):
        props["effect_allele"] = candidate.effect_allele


def fetch_top_loci_snapshot(
    *,
    client: httpx.Client | None = None,
    disorder_trait_queries: dict[str, str] | None = None,
    study_ids_by_pmid: Mapping[str, Sequence[str]] | None = None,
    max_associations_per_disorder: int = 500,
    max_studies_per_disorder: int = 50,
    request_delay: float = 0.25,
    timeout: float = 30.0,
) -> TopLociSnapshot:
    """Fetch GWAS Catalog top loci and return a :class:`TopLociSnapshot`."""

    own_client = client is None
    if own_client:
        client = httpx.Client()
    assert client is not None

    queries = disorder_trait_queries or DISORDER_TRAIT_QUERIES
    pmid_to_study_ids = {
        str(pmid): tuple(
            sorted(
                {
                    _coerce_text(study_id)
                    for study_id in study_ids
                    if _coerce_text(study_id)
                }
            )
        )
        for pmid, study_ids in (study_ids_by_pmid or {}).items()
        if _coerce_text(pmid)
    }

    node_rows_by_id: dict[str, dict[str, Any]] = {}
    associated_with_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    has_lead_locus_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    stats: dict[str, Any] = {
        "disorders_queried": 0,
        "studies_fetched": 0,
        "associations_seen": 0,
        "significant_associations_seen": 0,
        "per_disorder": {},
    }

    try:
        for disease_id, trait_query in queries.items():
            stats["disorders_queried"] += 1
            logger.info(
                "GWAS Catalog: querying trait=%r for %s", trait_query, disease_id
            )

            study_summaries = _fetch_study_summaries(
                client,
                trait_query,
                max_studies_per_disorder,
                request_delay,
                timeout,
            )
            stats["studies_fetched"] += len(study_summaries)

            strongest_by_rsid: dict[str, TopLocusAssociation] = {}
            matched_study_edges: dict[tuple[str, str], TopLocusAssociation] = {}
            disorder_stats = {
                "trait_query": trait_query,
                "studies_fetched": len(study_summaries),
                "associations_seen": 0,
                "significant_associations_seen": 0,
                "unique_significant_loci_before_cap": 0,
                "selected_loci": 0,
                "matched_openmed_study_edges": 0,
            }

            for study in study_summaries:
                time.sleep(request_delay)
                try:
                    raw_associations = _fetch_study_associations(
                        client,
                        study.accession_id,
                        request_delay,
                        timeout,
                    )
                except httpx.HTTPStatusError:
                    logger.warning(
                        "Failed to fetch associations for %s", study.accession_id
                    )
                    continue

                for raw in raw_associations:
                    disorder_stats["associations_seen"] += 1
                    stats["associations_seen"] += 1

                    association = _extract_association(
                        raw,
                        disease_id=disease_id,
                        study=study,
                    )
                    if association is None:
                        continue

                    disorder_stats["significant_associations_seen"] += 1
                    stats["significant_associations_seen"] += 1

                    incumbent = strongest_by_rsid.get(association.rsid)
                    if incumbent is None or _is_stronger(association, incumbent):
                        strongest_by_rsid[association.rsid] = association

                    if study.pubmed_id:
                        for study_id in pmid_to_study_ids.get(study.pubmed_id, ()):
                            key = (study_id, association.rsid)
                            current = matched_study_edges.get(key)
                            if current is None or _is_stronger(association, current):
                                matched_study_edges[key] = association

            disorder_stats["unique_significant_loci_before_cap"] = len(
                strongest_by_rsid
            )
            selected = sorted(strongest_by_rsid.values(), key=_association_sort_key)[
                :max_associations_per_disorder
            ]
            disorder_stats["selected_loci"] = len(selected)
            selected_rank_by_rsid = {
                association.rsid: rank
                for rank, association in enumerate(selected, start=1)
            }

            for association in selected:
                locus_id = f"locus:{association.rsid}"
                node = node_rows_by_id.get(locus_id)
                if node is None:
                    node_rows_by_id[locus_id] = _structured_node_row(
                        locus_id,
                        ("RiskLocus",),
                        _risk_locus_node_properties(association),
                    )
                else:
                    _merge_risk_locus_node(node, association)

                aligned_study_ids = (
                    pmid_to_study_ids.get(association.study_pmid, ())
                    if association.study_pmid
                    else ()
                )
                assoc_props: dict[str, Any] = {
                    "source": TOP_LOCI_SOURCE,
                    "association_type": "gwas_top_locus",
                    "rank": selected_rank_by_rsid[association.rsid],
                    "p_value": association.p_value,
                    "study_accession": association.study_accession,
                }
                if association.study_pmid:
                    assoc_props["study_pmid"] = association.study_pmid
                if association.p_mantissa is not None:
                    assoc_props["p_mantissa"] = association.p_mantissa
                if association.p_exponent is not None:
                    assoc_props["p_exponent"] = association.p_exponent
                if association.odds_ratio is not None:
                    assoc_props["odds_ratio"] = association.odds_ratio
                if association.beta is not None:
                    assoc_props["beta"] = association.beta
                if association.se is not None:
                    assoc_props["se"] = association.se
                if len(aligned_study_ids) == 1:
                    assoc_props["study_id"] = aligned_study_ids[0]

                associated_with_by_key[(locus_id, disease_id)] = (
                    _structured_relationship_row(
                        locus_id,
                        disease_id,
                        "ASSOCIATED_WITH",
                        assoc_props,
                    )
                )

            for (study_id, rsid), association in matched_study_edges.items():
                if rsid not in selected_rank_by_rsid:
                    continue
                locus_id = f"locus:{rsid}"
                rank = selected_rank_by_rsid[rsid]
                key = (study_id, locus_id)
                props: dict[str, Any] = {
                    "source": TOP_LOCI_SOURCE,
                    "locus_rank": rank,
                    "variant_id": rsid,
                    "p_value": association.p_value,
                    "study_accession": association.study_accession,
                    "trait_id": disease_id,
                }
                if association.study_pmid:
                    props["study_pmid"] = association.study_pmid
                if association.p_mantissa is not None:
                    props["p_mantissa"] = association.p_mantissa
                if association.p_exponent is not None:
                    props["p_exponent"] = association.p_exponent
                existing = has_lead_locus_by_key.get(key)
                if existing is None or (
                    props.get("p_value") is not None
                    and props["p_value"]
                    < existing["properties"].get("p_value", float("inf"))
                ):
                    has_lead_locus_by_key[key] = _structured_relationship_row(
                        study_id,
                        locus_id,
                        "HAS_LEAD_LOCUS",
                        props,
                    )

            disorder_stats["matched_openmed_study_edges"] = sum(
                1
                for (_study_id, rsid) in matched_study_edges
                if rsid in selected_rank_by_rsid
            )
            stats["per_disorder"][disease_id] = disorder_stats
    finally:
        if own_client:
            client.close()

    stats["unique_loci"] = len(node_rows_by_id)
    stats["associated_with_edges"] = len(associated_with_by_key)
    stats["has_lead_locus_edges"] = len(has_lead_locus_by_key)
    logger.info(
        "GWAS Catalog snapshot: %d RiskLocus nodes, %d ASSOCIATED_WITH edges, %d HAS_LEAD_LOCUS edges",
        len(node_rows_by_id),
        len(associated_with_by_key),
        len(has_lead_locus_by_key),
    )
    return TopLociSnapshot(
        node_rows=tuple(node_rows_by_id.values()),
        relationship_rows=tuple(
            list(associated_with_by_key.values()) + list(has_lead_locus_by_key.values())
        ),
        stats=stats,
    )


__all__ = [
    "DISORDER_TRAIT_QUERIES",
    "GENOME_WIDE_SIGNIFICANCE",
    "TOP_LOCI_SOURCE",
    "TopLociSnapshot",
    "fetch_top_loci_snapshot",
]
