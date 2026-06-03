"""Lightweight Hugging Face metadata helper for OpenMed/PGC GWAS repos.

This module intentionally avoids the ``datasets`` package. It uses the public
Hugging Face dataset API, the raw README on the dataset card, and the
datasets-server metadata endpoints to extract study-level metadata without
touching parquet contents.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

HF_AUTHOR_DATASET_API_URL = "https://huggingface.co/api/datasets"
HF_DATASET_API_URL = "https://huggingface.co/api/datasets/{dataset_id}"
HF_DATASET_README_URL = (
    "https://huggingface.co/datasets/{dataset_id}/resolve/main/README.md"
)
HF_DATASETS_SERVER_SPLITS_URL = "https://datasets-server.huggingface.co/splits"
HF_DATASETS_SERVER_INFO_URL = "https://datasets-server.huggingface.co/info"
HF_DATASETS_SERVER_FIRST_ROWS_URL = "https://datasets-server.huggingface.co/first-rows"

DEFAULT_HF_AUTHOR = "OpenMed"
DEFAULT_DATASET_PREFIX = "OpenMed/pgc-"
_HINT_TOKEN_SPLIT_RE = re.compile(
    r"[^A-Za-z0-9]+|(?<=[a-z])(?=[A-Z])|(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])"
)


@dataclass(frozen=True)
class OpenMedPGCStudyMetadata:
    dataset_id: str
    config_name: str
    phenotype: str
    expanded_traits: tuple[str, ...] = ()
    journal: str | None = None
    year: int | None = None
    pmid: str | None = None
    rows: int | None = None
    license: str | None = None
    study_url: str | None = None
    config_info: dict[str, Any] = field(default_factory=dict)
    first_row_example: dict[str, Any] | None = None
    source_files: tuple[str, ...] = ()
    ancestry_hints: tuple[str, ...] = ()
    population_descriptors: tuple["PopulationDescriptor", ...] = ()
    study_id: str = ""
    disease_trait_id: str = ""
    population_id: str = ""
    publication_id: str | None = None


@dataclass(frozen=True)
class OpenMedPGCDatasetMetadata:
    dataset_id: str
    title: str | None = None
    license: str | None = None
    tags: tuple[str, ...] = ()
    readme_url: str | None = None
    card_url: str | None = None
    config_names: tuple[str, ...] = ()
    studies: tuple[OpenMedPGCStudyMetadata, ...] = ()
    splits: tuple[dict[str, Any], ...] = ()
    card_data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OpenMedPGCCollectionMetadata:
    author: str
    dataset_ids: tuple[str, ...]
    datasets: tuple[OpenMedPGCDatasetMetadata, ...]
    source_url: str | None = None


@dataclass(frozen=True)
class OpenMedPGCGraphSnapshot:
    collection_metadata: OpenMedPGCCollectionMetadata
    node_rows: tuple[dict[str, Any], ...]
    relationship_rows: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class PopulationDescriptor:
    node_id: str
    population_id: str
    name: str
    population_type: str
    ancestry: str | None = None
    ancestry_code: str | None = None
    super_population: str | None = None
    cohort: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class PopulationRule:
    key: str
    name: str
    population_type: str
    patterns: tuple[re.Pattern[str], ...]
    ancestry: str | None = None
    ancestry_code: str | None = None
    super_population: str | None = None
    cohort: str | None = None
    description: str | None = None
    negative_patterns: tuple[re.Pattern[str], ...] = ()

    def build_descriptor(self) -> PopulationDescriptor:
        return PopulationDescriptor(
            node_id=f"population:{self.key}",
            population_id=self.key,
            name=self.name,
            population_type=self.population_type,
            ancestry=self.ancestry,
            ancestry_code=self.ancestry_code,
            super_population=self.super_population,
            cohort=self.cohort,
            description=self.description,
        )


def _coerce_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _table_cell_text(value: Any) -> str | None:
    text = _coerce_text(value)
    if not text:
        return None
    return text.strip("`").strip()


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value:
            return None
        return int(value)
    text = _coerce_text(value)
    if not text:
        return None
    text = text.replace(",", "")
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^\w\s-]", "_", value)
    value = re.sub(r"[\s-]+", "_", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("_")


def _dedupe_text(values: Iterable[Any]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = _coerce_text(value)
        if not text:
            continue
        marker = text.lower()
        if marker in seen:
            continue
        seen.add(marker)
        out.append(text)
    return tuple(out)


def _first_present(mapping: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in mapping and mapping.get(key) is not None:
            return mapping.get(key)
    return None


def _dataset_card_url(dataset_id: str) -> str:
    return f"https://huggingface.co/datasets/{dataset_id}"


def _dataset_readme_url(dataset_id: str) -> str:
    return HF_DATASET_README_URL.format(dataset_id=dataset_id)


def _get_json(
    client: httpx.Client,
    url: str,
    *,
    params: dict[str, Any] | None = None,
) -> Any:
    response = client.get(url, params=params)
    response.raise_for_status()
    return response.json()


def _get_text(
    client: httpx.Client,
    url: str,
    *,
    params: dict[str, Any] | None = None,
) -> str:
    response = client.get(url, params=params)
    response.raise_for_status()
    return response.text


def discover_openmed_pgc_dataset_ids(
    *,
    client: httpx.Client | None = None,
    timeout: float = 20.0,
    author: str = DEFAULT_HF_AUTHOR,
    explicit_dataset_ids: Sequence[str] | None = None,
) -> tuple[str, ...]:
    if explicit_dataset_ids is not None:
        return _dedupe_text(explicit_dataset_ids)

    owns_client = client is None
    client = client or httpx.Client(timeout=timeout, follow_redirects=True)
    try:
        payload = _get_json(
            client,
            HF_AUTHOR_DATASET_API_URL,
            params={"author": author, "search": "pgc", "limit": 100},
        )
    finally:
        if owns_client:
            client.close()

    dataset_ids: list[str] = []
    items: list[Any]
    if isinstance(payload, list):
        items = payload
    else:
        items = payload.get("datasets") or payload.get("items") or []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        dataset_id = _coerce_text(item.get("id"))
        if not dataset_id or not dataset_id.startswith(DEFAULT_DATASET_PREFIX):
            continue
        dataset_ids.append(dataset_id)
    return _dedupe_text(dataset_ids)


def _extract_license(payload: Mapping[str, Any]) -> str | None:
    card_data = payload.get("cardData")
    if isinstance(card_data, Mapping):
        value = _first_present(card_data, ("license", "license_name"))
        if value is not None:
            return _coerce_text(value)
    value = _first_present(payload, ("license", "license_name"))
    return _coerce_text(value)


def _extract_tags(payload: Mapping[str, Any]) -> tuple[str, ...]:
    tags: list[Any] = []
    raw_tags = payload.get("tags")
    if isinstance(raw_tags, list | tuple | set):
        tags.extend(raw_tags)
    card_data = payload.get("cardData")
    if isinstance(card_data, Mapping):
        card_tags = card_data.get("tags")
        if isinstance(card_tags, list | tuple | set):
            tags.extend(card_tags)
    return _dedupe_text(tags)


def _parse_markdown_table_lines(lines: Sequence[str]) -> list[dict[str, str]]:
    if not lines:
        return []
    rows = [line for line in lines if line.strip().startswith("|") and line.count("|") >= 2]
    if len(rows) < 2:
        return []
    headers = [cell.strip() for cell in rows[0].strip().strip("|").split("|")]
    parsed: list[dict[str, str]] = []
    for row in rows[1:]:
        cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
        if not cells:
            continue
        if all(set(cell) <= {"-", ":"} for cell in cells):
            continue
        record: dict[str, str] = {}
        for idx, header in enumerate(headers):
            if idx < len(cells):
                record[header] = cells[idx]
            else:
                record[header] = ""
        parsed.append(record)
    return parsed


def _extract_subset_table(readme_text: str) -> list[dict[str, str]]:
    lines = readme_text.splitlines()
    blocks: list[list[str]] = []
    current: list[str] = []
    in_subsets = False
    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith("## "):
            heading = stripped[3:].strip().lower()
            if "subset" in heading:
                in_subsets = True
                current = []
                continue
            if in_subsets and current:
                blocks.append(current)
            in_subsets = False
            current = []
            continue
        if in_subsets and stripped.startswith("|"):
            current.append(stripped)
        elif in_subsets and current and not stripped:
            blocks.append(current)
            current = []
    if in_subsets and current:
        blocks.append(current)

    for block in blocks:
        parsed = _parse_markdown_table_lines(block)
        if not parsed:
            continue
        headers = {key.lower() for key in parsed[0].keys()}
        if "config" in headers and "phenotype" in headers:
            return parsed
    return []


_PMID_PATTERNS = (
    re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", re.IGNORECASE),
    re.compile(r"\bpmid[:\s]*([0-9]{6,9})\b", re.IGNORECASE),
    re.compile(r"\b([0-9]{7,9})\b"),
)


def _extract_pmid(value: Any) -> str | None:
    text = _coerce_text(value)
    if not text:
        return None
    for pattern in _PMID_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return None


def _normalize_year(value: Any) -> int | None:
    year = _coerce_int(value)
    if year is None:
        return None
    if 1800 <= year <= 2100:
        return year
    return None


def _split_hint_tokens(text: str) -> list[str]:
    tokens = _HINT_TOKEN_SPLIT_RE.split(text)
    return [token.lower() for token in tokens if token]


def _compile_patterns(*patterns: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(pattern) for pattern in patterns)


_UKB_NEGATIVE_PATTERNS = _compile_patterns(
    r"\bnoukbb?\b",
    r"\bnoukbiobank\b",
    r"\brmukbb\b",
    r"\b(?:no|wo|without|exclude|excluding|wto)\s+ukbb?\b",
    r"\b(?:no|without|exclude|excluding)\s+uk\s+biobank\b",
)

_ME23_NEGATIVE_PATTERNS = _compile_patterns(
    r"\bno23andme\b",
    r"\brm23andme\b",
    r"\b(?:no|wo|without|exclude|excluding)\s+23andme\b",
)

_AFRICAN_NEGATIVE_PATTERNS = _compile_patterns(
    r"\bafrican\s+american\b",
    r"\baa\d*\b",
    r"\baam\d*\b",
)

_POPULATION_RULES: tuple[PopulationRule, ...] = (
    PopulationRule(
        key="aam",
        name="African American",
        population_type="ancestry",
        patterns=_compile_patterns(
            r"\bafrican\s+american\b",
            r"\baa\d*\b",
            r"\baam\d*\b",
        ),
        ancestry="African American",
        ancestry_code="AAM",
        super_population="African",
        description="African American subset inferred from AA/AAM labels in OpenMed/PGC metadata.",
    ),
    PopulationRule(
        key="eur",
        name="European",
        population_type="ancestry",
        patterns=_compile_patterns(r"\beur\b", r"\beuropean\b", r"\beuro\b"),
        ancestry="European",
        ancestry_code="EUR",
        super_population="West Eurasian",
        description="Canonical European ancestry population inferred from OpenMed/PGC metadata.",
    ),
    PopulationRule(
        key="afr",
        name="African",
        population_type="ancestry",
        patterns=_compile_patterns(
            r"\bafr\b",
            r"\bafrican\b",
            r"african\b",
        ),
        ancestry="African",
        ancestry_code="AFR",
        super_population="African",
        description="Canonical African ancestry population inferred from OpenMed/PGC metadata.",
        negative_patterns=_AFRICAN_NEGATIVE_PATTERNS,
    ),
    PopulationRule(
        key="eas",
        name="East Asian",
        population_type="ancestry",
        patterns=_compile_patterns(
            r"\beast\s+asian\b",
            r"\beas\b",
        ),
        ancestry="East Asian",
        ancestry_code="EAS",
        super_population="Asian",
        description="Canonical East Asian ancestry population inferred from OpenMed/PGC metadata.",
    ),
    PopulationRule(
        key="sas",
        name="South Asian",
        population_type="ancestry",
        patterns=_compile_patterns(r"\bsouth\s+asian\b", r"\bsas\b"),
        ancestry="South Asian",
        ancestry_code="SAS",
        super_population="Asian",
        description="Canonical South Asian ancestry population inferred from OpenMed/PGC metadata.",
    ),
    PopulationRule(
        key="asian",
        name="Asian",
        population_type="ancestry",
        patterns=_compile_patterns(r"\basian\b", r"\basi\b", r"\basn\b"),
        ancestry="Asian",
        ancestry_code="ASN",
        super_population="Asian",
        description="Broad Asian ancestry population inferred from OpenMed/PGC metadata.",
    ),
    PopulationRule(
        key="amr",
        name="Admixed American",
        population_type="ancestry",
        patterns=_compile_patterns(
            r"\badmixed\s+american\b",
            r"\bamr\b",
        ),
        ancestry="Admixed American",
        ancestry_code="AMR",
        super_population="Admixed American",
        description="Canonical admixed American ancestry population inferred from OpenMed/PGC metadata.",
    ),
    PopulationRule(
        key="latino",
        name="Latino",
        population_type="ancestry",
        patterns=_compile_patterns(
            r"\blatino\b",
            r"\blatinx\b",
            r"\bhispanic\b",
            r"\blat\b",
        ),
        ancestry="Latino",
        ancestry_code="LAT",
        super_population="Admixed American",
        description="Latino or Hispanic ancestry population inferred from OpenMed/PGC metadata.",
    ),
    PopulationRule(
        key="multi_ancestry",
        name="Multi-ancestry",
        population_type="ancestry",
        patterns=_compile_patterns(
            r"\bmulti[-\s]*ancestr(?:y|ies)\b",
            r"\btrans[-\s]*ancestr(?:y|ies)\b",
            r"\bcross[-\s]*ancestr(?:y|ies)\b",
            r"\bdiverse\b",
        ),
        ancestry="Multi-ancestry",
        ancestry_code="MULTI",
        super_population="Multi-ancestry",
        description="Cross-ancestry GWAS cohort spanning multiple ancestry groups.",
    ),
    PopulationRule(
        key="swedish",
        name="Swedish cohort",
        population_type="cohort",
        patterns=_compile_patterns(r"\bswedish\b", r"\bsweden\b", r"\bswe\b"),
        ancestry="European",
        ancestry_code="EUR",
        super_population="West Eurasian",
        cohort="Swedish cohort",
        description="Swedish PGC cohort with European ancestry labeling.",
    ),
    PopulationRule(
        key="ipsych",
        name="iPSYCH",
        population_type="cohort",
        patterns=_compile_patterns(r"\bipsych\d*\b"),
        cohort="iPSYCH",
        description="Danish iPSYCH psychiatric genetics cohort referenced by OpenMed/PGC metadata.",
    ),
    PopulationRule(
        key="decode",
        name="deCODE",
        population_type="cohort",
        patterns=_compile_patterns(r"\bdecode\b"),
        cohort="deCODE",
        description="Icelandic deCODE genetics cohort referenced by OpenMed/PGC metadata.",
    ),
    PopulationRule(
        key="clozuk",
        name="CLOZUK",
        population_type="cohort",
        patterns=_compile_patterns(r"\bclozuk\b"),
        cohort="CLOZUK",
        description="CLOZUK treatment-resistant schizophrenia cohort referenced by OpenMed/PGC metadata.",
    ),
    PopulationRule(
        key="uk_biobank",
        name="UK Biobank",
        population_type="cohort",
        patterns=_compile_patterns(r"\bukbb?\b", r"\buk\s+biobank\b", r"\bukbiobank\b"),
        cohort="UK Biobank",
        description="UK Biobank cohort referenced by OpenMed/PGC metadata.",
        negative_patterns=_UKB_NEGATIVE_PATTERNS,
    ),
    PopulationRule(
        key="23andme",
        name="23andMe",
        population_type="cohort",
        patterns=_compile_patterns(r"\b23andme\b"),
        cohort="23andMe",
        description="23andMe participant cohort referenced by OpenMed/PGC metadata.",
        negative_patterns=_ME23_NEGATIVE_PATTERNS,
    ),
    PopulationRule(
        key="twinsuk",
        name="TwinsUK",
        population_type="cohort",
        patterns=_compile_patterns(r"\btwinsuk\b"),
        cohort="TwinsUK",
        description="TwinsUK cohort referenced by OpenMed/PGC metadata.",
    ),
    PopulationRule(
        key="ntr",
        name="Netherlands Twin Register",
        population_type="cohort",
        patterns=_compile_patterns(r"\bntr\b"),
        cohort="Netherlands Twin Register",
        description="Netherlands Twin Register cohort referenced by OpenMed/PGC metadata.",
    ),
    PopulationRule(
        key="sfs",
        name="Study of Families and Siblings",
        population_type="cohort",
        patterns=_compile_patterns(r"\bsfs\b"),
        cohort="Study of Families and Siblings",
        description="Study of Families and Siblings cohort referenced by OpenMed/PGC metadata.",
    ),
    PopulationRule(
        key="utah",
        name="Utah cohort",
        population_type="cohort",
        patterns=_compile_patterns(r"\butah\b"),
        cohort="Utah cohort",
        description="Utah cohort referenced by OpenMed/PGC metadata.",
    ),
    PopulationRule(
        key="whi",
        name="Women's Health Initiative",
        population_type="cohort",
        patterns=_compile_patterns(r"\bwhi\b"),
        cohort="Women's Health Initiative",
        description="Women's Health Initiative cohort referenced by OpenMed/PGC metadata.",
    ),
)


def _population_signal_texts(
    *,
    dataset_id: str,
    config_name: str,
    phenotype: str,
    source_files: Sequence[str],
) -> tuple[str, ...]:
    values = [dataset_id, config_name, phenotype, *source_files]
    texts: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _coerce_text(value)
        if not text:
            continue
        normalized = text.lower()
        tokenized = " ".join(_split_hint_tokens(normalized))
        for candidate in (normalized, tokenized):
            candidate = candidate.strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            texts.append(candidate)
    return tuple(texts)


def _rule_matches(rule: PopulationRule, signal_texts: Sequence[str]) -> bool:
    matched = any(pattern.search(text) for text in signal_texts for pattern in rule.patterns)
    if not matched:
        return False
    return not any(
        pattern.search(text)
        for text in signal_texts
        for pattern in rule.negative_patterns
    )


def _infer_population_descriptors(
    *,
    dataset_id: str,
    config_name: str,
    phenotype: str,
    source_files: Sequence[str],
) -> tuple[PopulationDescriptor, ...]:
    signal_texts = _population_signal_texts(
        dataset_id=dataset_id,
        config_name=config_name,
        phenotype=phenotype,
        source_files=source_files,
    )
    descriptors: list[PopulationDescriptor] = []
    seen: set[str] = set()
    for rule in _POPULATION_RULES:
        if not _rule_matches(rule, signal_texts):
            continue
        descriptor = rule.build_descriptor()
        if descriptor.node_id in seen:
            continue
        seen.add(descriptor.node_id)
        descriptors.append(descriptor)

    if any(descriptor.node_id in {"population:eas", "population:sas"} for descriptor in descriptors):
        descriptors = [
            descriptor for descriptor in descriptors if descriptor.node_id != "population:asian"
        ]
        seen = {descriptor.node_id for descriptor in descriptors}

    ancestry_like = [
        descriptor
        for descriptor in descriptors
        if descriptor.population_type == "ancestry"
        and descriptor.population_id != "multi_ancestry"
    ]
    if len(ancestry_like) > 1 and "population:multi_ancestry" not in seen:
        descriptors.append(
            PopulationRule(
                key="multi_ancestry",
                name="Multi-ancestry",
                population_type="ancestry",
                patterns=(),
                ancestry="Multi-ancestry",
                ancestry_code="MULTI",
                super_population="Multi-ancestry",
                description="Cross-ancestry GWAS cohort spanning multiple ancestry groups.",
            ).build_descriptor()
        )
    return tuple(descriptors)


def _infer_ancestry_hints(
    *,
    dataset_id: str,
    config_name: str,
    phenotype: str,
    source_files: Sequence[str],
) -> tuple[str, ...]:
    descriptors = _infer_population_descriptors(
        dataset_id=dataset_id,
        config_name=config_name,
        phenotype=phenotype,
        source_files=source_files,
    )
    return tuple(descriptor.name for descriptor in descriptors)


def _trait_stable_slug(phenotype: str) -> str:
    slug = _slugify(phenotype)
    return slug or "unknown_trait"


_PARENTHETICAL_SUFFIX_RE = re.compile(r"\s*\([^)]*\)\s*$")
_COMPOSITE_SPLIT_RE = re.compile(r"\s*(?:&|/|\band\b)\s*", re.IGNORECASE)
_TRAIT_FRAGMENT_STOPWORDS = {
    "factor",
    "factors",
    "feature",
    "features",
    "measure",
    "measures",
    "scale",
    "scales",
    "score",
    "scores",
    "symptom",
    "symptoms",
    "item",
    "items",
    "questionnaire",
    "survey",
    "audit",
    "instrument",
    "tools",
    "tool",
}

_TRAIT_ACRONYM_WHITELIST = {
    "ADHD",
    "ASD",
    "BIP",
    "MDD",
    "OCD",
    "PTSD",
    "SCZ",
    "TS",
}


def _normalize_trait_fragment(fragment: str) -> str | None:
    text = _coerce_text(fragment)
    if not text:
        return None
    text = re.sub(r"\s+", " ", text)
    text = text.strip(" ,;:-")
    text = _PARENTHETICAL_SUFFIX_RE.sub("", text).strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in _TRAIT_FRAGMENT_STOPWORDS:
        return None
    if text.isupper() and text not in _TRAIT_ACRONYM_WHITELIST:
        return None
    if any(token in lowered for token in ("factor", "score", "scale", "audit")) and " " not in lowered:
        return None
    return text


def _expand_phenotype_labels(phenotype: str) -> tuple[str, ...]:
    raw = _coerce_text(phenotype)
    if not raw:
        return ()
    fragments = [part for part in _COMPOSITE_SPLIT_RE.split(raw) if part is not None]
    if len(fragments) <= 1:
        normalized = _normalize_trait_fragment(raw)
        return (normalized or raw,)

    normalized = []
    for fragment in fragments:
        text = _normalize_trait_fragment(fragment)
        if text:
            normalized.append(text)

    if not normalized:
        return (raw,)
    if len(normalized) == 1:
        return (normalized[0],)
    return _dedupe_text(normalized)


def _study_id(dataset_id: str, config_name: str) -> str:
    return f"study:{_slugify(dataset_id)}:{_slugify(config_name)}"


def _population_id(dataset_id: str, config_name: str) -> str:
    return f"population:{_slugify(dataset_id)}:{_slugify(config_name)}"


def _disease_trait_id(phenotype: str) -> str:
    return f"disease:{_trait_stable_slug(phenotype)}"


def _publication_id(pmid: str | None) -> str | None:
    if not pmid:
        return None
    return f"pmid:{pmid}"


def _maybe_split_count(info_payload: Mapping[str, Any] | None) -> int | None:
    if not info_payload:
        return None
    splits = info_payload.get("splits")
    if not isinstance(splits, Mapping):
        return None
    train = splits.get("train")
    if not isinstance(train, Mapping):
        return None
    return _coerce_int(train.get("num_examples"))


def _fetch_dataset_splits(
    client: httpx.Client,
    dataset_id: str,
) -> tuple[dict[str, Any], ...]:
    payload = _get_json(
        client,
        HF_DATASETS_SERVER_SPLITS_URL,
        params={"dataset": dataset_id},
    )
    splits = payload.get("splits")
    if not isinstance(splits, list):
        return ()
    out: list[dict[str, Any]] = []
    for item in splits:
        if isinstance(item, Mapping):
            out.append(dict(item))
    return tuple(out)


def _first_row_example(first_rows_payload: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not first_rows_payload:
        return None
    rows = first_rows_payload.get("rows")
    if not isinstance(rows, list) or not rows:
        return None
    row = rows[0]
    if not isinstance(row, Mapping):
        return None
    nested = row.get("row")
    if isinstance(nested, Mapping):
        return dict(nested)
    return dict(row)


def _source_files_from_first_row(first_row: Mapping[str, Any] | None) -> tuple[str, ...]:
    if not first_row:
        return ()
    values = []
    for key in ("_source_file", "source_file", "source", "file"):
        value = first_row.get(key)
        if value:
            values.append(value)
    return _dedupe_text(values)


def _sample_size_fields(first_row: Mapping[str, Any] | None) -> dict[str, int]:
    if not first_row:
        return {}
    n_cases = _coerce_int(first_row.get("Nca") or first_row.get("cases"))
    n_controls = _coerce_int(first_row.get("Nco") or first_row.get("controls"))
    n_samples = _coerce_int(
        first_row.get("N")
        or first_row.get("Neff")
        or first_row.get("Neff_half")
        or first_row.get("n_samples")
    )
    if n_samples is None and n_cases is not None and n_controls is not None:
        n_samples = n_cases + n_controls
    fields = {
        "n_cases": n_cases,
        "n_controls": n_controls,
        "n_samples": n_samples,
    }
    return {key: value for key, value in fields.items() if value is not None}


def _study_row_to_metadata(
    dataset_id: str,
    dataset_license: str | None,
    row: Mapping[str, str],
    *,
    config_info: Mapping[str, Any] | None = None,
    first_row_example: Mapping[str, Any] | None = None,
) -> OpenMedPGCStudyMetadata:
    config_name = _table_cell_text(row.get("Config")) or _table_cell_text(row.get("config")) or ""
    phenotype = _table_cell_text(row.get("Phenotype")) or _table_cell_text(row.get("phenotype")) or ""
    journal = _table_cell_text(row.get("Journal")) or _table_cell_text(row.get("journal"))
    year = _normalize_year(row.get("Year") or row.get("year"))
    pmid = _extract_pmid(row.get("PubMed") or row.get("PMID") or row.get("pmid"))
    rows = _coerce_int(row.get("Rows") or row.get("rows"))
    source_files = _source_files_from_first_row(first_row_example)
    ancestry_hints = _infer_ancestry_hints(
        dataset_id=dataset_id,
        config_name=config_name,
        phenotype=phenotype,
        source_files=source_files,
    )
    population_descriptors = _infer_population_descriptors(
        dataset_id=dataset_id,
        config_name=config_name,
        phenotype=phenotype,
        source_files=source_files,
    )
    study_id = _study_id(dataset_id, config_name)
    expanded_traits = _expand_phenotype_labels(phenotype or config_name)
    if not expanded_traits:
        expanded_traits = (phenotype or config_name,)
    disease_trait_id = _disease_trait_id(expanded_traits[0])
    population_id = (
        population_descriptors[0].node_id
        if population_descriptors
        else _population_id(dataset_id, config_name)
    )
    config_info_dict = dict(config_info or {})
    publication_id = _publication_id(pmid)
    return OpenMedPGCStudyMetadata(
        dataset_id=dataset_id,
        config_name=config_name,
        phenotype=phenotype or config_name,
        expanded_traits=expanded_traits,
        journal=journal,
        year=year,
        pmid=pmid,
        rows=rows or _maybe_split_count(config_info_dict),
        license=dataset_license,
        study_url=_dataset_card_url(dataset_id),
        config_info=config_info_dict,
        first_row_example=dict(first_row_example) if first_row_example else None,
        source_files=source_files,
        ancestry_hints=ancestry_hints,
        population_descriptors=population_descriptors,
        study_id=study_id,
        disease_trait_id=disease_trait_id,
        population_id=population_id,
        publication_id=publication_id,
    )


def _fetch_config_info(
    client: httpx.Client,
    dataset_id: str,
    config_name: str,
) -> dict[str, Any]:
    payload = _get_json(
        client,
        HF_DATASETS_SERVER_INFO_URL,
        params={"dataset": dataset_id, "config": config_name},
    )
    info = payload.get("dataset_info")
    if isinstance(info, Mapping):
        return dict(info)
    return {}


def _fetch_config_first_rows(
    client: httpx.Client,
    dataset_id: str,
    config_name: str,
) -> dict[str, Any]:
    return _get_json(
        client,
        HF_DATASETS_SERVER_FIRST_ROWS_URL,
        params={"dataset": dataset_id, "config": config_name, "split": "train"},
    )


def _extract_config_names(
    payload: Mapping[str, Any],
    readme_rows: Sequence[Mapping[str, str]],
    dataset_splits: Sequence[Mapping[str, Any]] = (),
) -> tuple[str, ...]:
    card_data = payload.get("cardData")
    config_names: list[str] = []
    if isinstance(card_data, Mapping):
        configs = card_data.get("configs")
        if isinstance(configs, list):
            for item in configs:
                if isinstance(item, Mapping):
                    config_name = _table_cell_text(item.get("config_name"))
                    if config_name:
                        config_names.append(config_name)
    for row in readme_rows:
        config_name = _table_cell_text(row.get("Config")) or _table_cell_text(row.get("config"))
        if config_name:
            config_names.append(config_name)
    for split in dataset_splits:
        config_name = _coerce_text(split.get("config"))
        if config_name:
            config_names.append(config_name)
    return _dedupe_text(config_names)


def fetch_openmed_pgc_dataset_metadata(
    dataset_id: str,
    *,
    client: httpx.Client | None = None,
    timeout: float = 20.0,
) -> OpenMedPGCDatasetMetadata:
    owns_client = client is None
    client = client or httpx.Client(timeout=timeout, follow_redirects=True)
    try:
        api_payload = _get_json(client, HF_DATASET_API_URL.format(dataset_id=dataset_id))
        readme_text = _get_text(client, _dataset_readme_url(dataset_id))
        dataset_splits = _fetch_dataset_splits(client, dataset_id)
        readme_rows = _extract_subset_table(readme_text)
        config_names = _extract_config_names(api_payload, readme_rows, dataset_splits)
        card_data = api_payload.get("cardData")
        card_data_dict = dict(card_data) if isinstance(card_data, Mapping) else {}
        dataset_license = _extract_license(api_payload)
        title = _coerce_text(
            _first_present(card_data_dict, ("pretty_name", "dataset_name", "title"))
        ) or _coerce_text(_first_present(api_payload, ("title", "name")))

        studies: list[OpenMedPGCStudyMetadata] = []
        row_by_config = {}
        for row in readme_rows:
            config_name = _table_cell_text(row.get("Config")) or _table_cell_text(row.get("config"))
            if config_name:
                row_by_config[config_name] = row

        splits_by_config: dict[str, list[dict[str, Any]]] = {}
        for split_entry in dataset_splits:
            config_name = _coerce_text(split_entry.get("config"))
            if not config_name:
                continue
            splits_by_config.setdefault(config_name, []).append(dict(split_entry))

        for config_name in config_names:
            config_info = {}
            first_row_example = None
            try:
                config_info = _fetch_config_info(client, dataset_id, config_name)
            except Exception:
                config_info = {}
            if config_name in splits_by_config:
                config_info = dict(config_info)
                config_info.setdefault("hf_splits", splits_by_config[config_name])
            try:
                first_rows_payload = _fetch_config_first_rows(client, dataset_id, config_name)
                first_row_example = _first_row_example(first_rows_payload)
            except Exception:
                first_row_example = None
            row = row_by_config.get(config_name, {})
            studies.append(
                _study_row_to_metadata(
                    dataset_id,
                    dataset_license,
                    row,
                    config_info=config_info,
                    first_row_example=first_row_example,
                )
            )

        return OpenMedPGCDatasetMetadata(
            dataset_id=_coerce_text(_first_present(api_payload, ("id", "datasetId"))) or dataset_id,
            title=title,
            license=dataset_license,
            tags=_extract_tags(api_payload),
            readme_url=_dataset_readme_url(dataset_id),
            card_url=_dataset_card_url(dataset_id),
            config_names=config_names,
            studies=tuple(studies),
            splits=dataset_splits,
            card_data=card_data_dict,
        )
    finally:
        if owns_client:
            client.close()


def fetch_openmed_pgc_collection_metadata(
    *,
    client: httpx.Client | None = None,
    timeout: float = 20.0,
    author: str = DEFAULT_HF_AUTHOR,
    explicit_dataset_ids: Sequence[str] | None = None,
) -> OpenMedPGCCollectionMetadata:
    dataset_ids = discover_openmed_pgc_dataset_ids(
        client=client,
        timeout=timeout,
        author=author,
        explicit_dataset_ids=explicit_dataset_ids,
    )
    owns_client = client is None
    client = client or httpx.Client(timeout=timeout, follow_redirects=True)
    try:
        datasets = [
            fetch_openmed_pgc_dataset_metadata(dataset_id, client=client, timeout=timeout)
            for dataset_id in dataset_ids
        ]
    finally:
        if owns_client:
            client.close()

    return OpenMedPGCCollectionMetadata(
        author=author,
        dataset_ids=dataset_ids,
        datasets=tuple(datasets),
        source_url=f"{HF_AUTHOR_DATASET_API_URL}?author={author}",
    )


def _node_row(node_id: str, labels: Sequence[str], properties: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "labels": list(labels),
        "properties": dict(properties),
    }


def _relationship_row(
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


def _population_descriptor_node_row(
    descriptor: PopulationDescriptor,
) -> dict[str, Any]:
    return _node_row(
        descriptor.node_id,
        ("Population",),
        {
            "id": descriptor.node_id,
            "name": descriptor.name,
            "population_id": descriptor.population_id,
            "ancestry": descriptor.ancestry,
            "ancestry_code": descriptor.ancestry_code,
            "super_population": descriptor.super_population,
            "cohort": descriptor.cohort,
            "description": descriptor.description,
            "source": "openmed_pgc_hf_loader",
            "population_type": descriptor.population_type,
            "normalization_source": "openmed_pgc_population_v2",
        },
    )


def _population_rows_for_study(study: OpenMedPGCStudyMetadata) -> tuple[dict[str, Any], ...]:
    descriptors = study.population_descriptors or ()
    return tuple(_population_descriptor_node_row(descriptor) for descriptor in descriptors)


def _publication_node_row(study: OpenMedPGCStudyMetadata) -> dict[str, Any] | None:
    if not study.publication_id:
        return None
    return _node_row(
        study.publication_id,
        ("Publication",),
        {
            "id": study.publication_id,
            "pmid": study.pmid,
            "journal": study.journal,
            "year": study.year,
            "source": "openmed_pgc_hf_loader",
            "source_dataset_id": study.dataset_id,
            "url": (
                f"https://pubmed.ncbi.nlm.nih.gov/{study.pmid}/"
                if study.pmid
                else None
            ),
        },
    )


def _disease_trait_node_row(
    trait_label: str,
    *,
    study: OpenMedPGCStudyMetadata | None = None,
) -> dict[str, Any]:
    props: dict[str, Any] = {
        "id": _disease_trait_id(trait_label),
        "name": trait_label,
        "trait_slug": _trait_stable_slug(trait_label),
        "source": "openmed_pgc_hf_loader",
    }
    if study is not None:
        props["source_dataset_id"] = study.dataset_id
        props["source_phenotype"] = study.phenotype
    return _node_row(
        _disease_trait_id(trait_label),
        ("DiseaseTrait",),
        props,
    )


def openmed_pgc_snapshot_to_graph_inputs(
    *,
    client: httpx.Client | None = None,
    timeout: float = 20.0,
    author: str = DEFAULT_HF_AUTHOR,
    explicit_dataset_ids: Sequence[str] | None = None,
) -> OpenMedPGCGraphSnapshot:
    collection = fetch_openmed_pgc_collection_metadata(
        client=client,
        timeout=timeout,
        author=author,
        explicit_dataset_ids=explicit_dataset_ids,
    )

    node_rows: list[dict[str, Any]] = []
    relationship_rows: list[dict[str, Any]] = []
    seen_nodes: set[str] = set()
    seen_edges: set[tuple[str, str, str]] = set()

    for dataset in collection.datasets:
        for study in dataset.studies:
            sample_size_fields = _sample_size_fields(study.first_row_example)
            population_nodes = _population_rows_for_study(study)
            population_ids = [node["node_id"] for node in population_nodes]
            population_names = [
                node["properties"].get("name")
                for node in population_nodes
                if node["properties"].get("name")
            ]
            study_node = _node_row(
                study.study_id,
                ("Study", "GWASStudy"),
                {
                    "id": study.study_id,
                    "name": study.config_name,
                    "config_name": study.config_name,
                    "dataset_id": study.dataset_id,
                    "phenotype": study.phenotype,
                    "phenotype_raw": study.phenotype,
                    "expanded_traits": list(study.expanded_traits),
                    "is_composite_phenotype": len(study.expanded_traits) > 1,
                    "journal": study.journal,
                    "year": study.year,
                    "pmid": study.pmid,
                    "rows": study.rows,
                    "license": study.license,
                    "source": "openmed_pgc_hf_loader",
                    "source_dataset_id": study.dataset_id,
                    "source_files": list(study.source_files),
                    "ancestry_hints": list(study.ancestry_hints),
                    "population_ids": population_ids,
                    "population_hints": population_names,
                    "feature_names": sorted((study.config_info.get("features") or {}).keys()),
                    **sample_size_fields,
                },
            )
            pub_node = _publication_node_row(study)
            trait_nodes = [
                _disease_trait_node_row(trait_label, study=study)
                for trait_label in (study.expanded_traits or (study.phenotype,))
            ]

            for node in (*trait_nodes, *population_nodes, study_node, pub_node):
                if node is None:
                    continue
                if node["node_id"] in seen_nodes:
                    continue
                seen_nodes.add(node["node_id"])
                node_rows.append(node)

            rel_specs = [
                (
                    study.study_id,
                    _disease_trait_id(trait_label),
                    "STUDIES",
                    {
                        "source": "openmed_pgc_hf_loader",
                        "dataset_id": study.dataset_id,
                        "config_name": study.config_name,
                        "phenotype": study.phenotype,
                        "trait_label": trait_label,
                        "journal": study.journal,
                        "year": study.year,
                        "pmid": study.pmid,
                    },
                )
                for trait_label in (study.expanded_traits or (study.phenotype,))
            ]
            for population_node in population_nodes:
                population_props = population_node["properties"]
                sample_size = sample_size_fields.get("n_samples")
                rel_specs.append(
                    (
                        study.study_id,
                        population_node["node_id"],
                        "HAS_POPULATION",
                        {
                            "source": "openmed_pgc_hf_loader",
                            "dataset_id": study.dataset_id,
                            "config_name": study.config_name,
                            "phenotype": study.phenotype,
                            "source_files": list(study.source_files),
                            "ancestry_hints": list(study.ancestry_hints),
                            "population_type": population_props.get("population_type"),
                            "population_id": population_props.get("population_id"),
                            "population_name": population_props.get("name"),
                            "cohort_name": population_props.get("cohort"),
                            "ancestry_code": population_props.get("ancestry_code"),
                            "sample_size": sample_size,
                            "normalization_source": population_props.get(
                                "normalization_source"
                            ),
                        },
                    )
                )
            if study.publication_id:
                rel_specs.append(
                    (
                        study.publication_id,
                        study.study_id,
                        "ALIGNS_WITH",
                        {
                            "source": "openmed_pgc_hf_loader",
                            "dataset_id": study.dataset_id,
                            "config_name": study.config_name,
                            "pmid": study.pmid,
                            "match_field": "pmid",
                            "confidence": 1.0,
                        },
                    )
                )

            for start_id, end_id, rel_type, props in rel_specs:
                edge_key = (start_id, end_id, rel_type)
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)
                relationship_rows.append(_relationship_row(start_id, end_id, rel_type, props))

    return OpenMedPGCGraphSnapshot(
        collection_metadata=collection,
        node_rows=tuple(node_rows),
        relationship_rows=tuple(relationship_rows),
    )


def ingest_openmed_pgc_snapshot(
    db: Any,
    *,
    client: httpx.Client | None = None,
    timeout: float = 20.0,
    author: str = DEFAULT_HF_AUTHOR,
    explicit_dataset_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    snapshot = openmed_pgc_snapshot_to_graph_inputs(
        client=client,
        timeout=timeout,
        author=author,
        explicit_dataset_ids=explicit_dataset_ids,
    )

    node_count = 0
    edge_count = 0
    for node in snapshot.node_rows:
        db.create_node(node["labels"], node["properties"], node_id=node["node_id"])
        node_count += 1
    for rel in snapshot.relationship_rows:
        created = db.create_relationship(
            rel["start_id"],
            rel["end_id"],
            rel["rel_type"],
            rel["properties"],
        )
        if created:
            edge_count += 1

    return {
        "collection_metadata": snapshot.collection_metadata,
        "node_rows": snapshot.node_rows,
        "relationship_rows": snapshot.relationship_rows,
        "nodes_created": node_count,
        "relationships_created": edge_count,
    }


__all__ = [
    "DEFAULT_DATASET_PREFIX",
    "DEFAULT_HF_AUTHOR",
    "HF_AUTHOR_DATASET_API_URL",
    "HF_DATASET_API_URL",
    "HF_DATASET_README_URL",
    "HF_DATASETS_SERVER_FIRST_ROWS_URL",
    "HF_DATASETS_SERVER_INFO_URL",
    "HF_DATASETS_SERVER_SPLITS_URL",
    "OpenMedPGCCollectionMetadata",
    "OpenMedPGCDatasetMetadata",
    "OpenMedPGCGraphSnapshot",
    "OpenMedPGCStudyMetadata",
    "discover_openmed_pgc_dataset_ids",
    "fetch_openmed_pgc_collection_metadata",
    "fetch_openmed_pgc_dataset_metadata",
    "ingest_openmed_pgc_snapshot",
    "openmed_pgc_snapshot_to_graph_inputs",
]
