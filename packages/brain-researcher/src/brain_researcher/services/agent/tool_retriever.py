"""
Two-stage tool retrieval for BR-KG.

Stage 1: LLM-based ToolFamily selection
Stage 2: Hybrid retrieval (SPARQL filter + embedding similarity)

This enables efficient retrieval from 4000+ tools by first narrowing
to relevant families, then using semantic search within those families.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import numpy as np
import yaml
from neo4j import GraphDatabase
from pydantic import BaseModel, Field

from brain_researcher.config.paths import resolve_from_config
from brain_researcher.core.literature.gfs_store import (
    route_gfs_stores,
    search_gfs_auto,
)
from brain_researcher.services.shared.runtime_semantic import (
    get_cached_sentence_transformer,
    semantic_matching_enabled,
)

logger = logging.getLogger(__name__)


_FAMILY_CARD_STOPWORDS = {
    "the",
    "and",
    "that",
    "this",
    "with",
    "from",
    "into",
    "onto",
    "over",
    "under",
    "about",
    "have",
    "has",
    "had",
    "been",
    "being",
    "are",
    "is",
    "was",
    "were",
    "will",
    "would",
    "should",
    "could",
    "can",
    "to",
    "of",
    "in",
    "on",
    "for",
    "as",
    "at",
    "by",
    "or",
    "not",
    "no",
    "please",
    "help",
    "me",
    "my",
    "your",
    "our",
    "we",
    "you",
    "i",
    "run",
    "execute",
    "analysis",
    "analyze",
    "compute",
    "show",
    "get",
    "generate",
    "query",
    "match",
    "matches",
    "before",
    "after",
    "data",
    "task",
    "tasks",
    "using",
    "use",
    "apply",
    "perform",
    "removing",
    "remove",
}

_DECODING_OUTCOME_HINTS = {
    "decode",
    "decoding",
    "classification",
    "classifier",
    "classify",
    "mvpa",
}
_DECODING_PREP_HINTS = {
    "anova feature selection",
    "feature selection",
    "confound regression",
    "deconfound",
    "deconfounding",
}
_BRAIN_AGE_PHRASES = {"brain age", "brain-age", "age gap"}
_BRAIN_EXTRACTION_HINTS = {
    "brain extraction",
    "skull stripping",
    "skull strip",
    "skullstrip",
    "fsl bet",
    "non-brain tissue",
}
_MORPHOMETRY_HINTS = {
    "vbm",
    "voxel-based morphometry",
    "voxel based morphometry",
    "grey matter volume",
    "gray matter volume",
    "white matter volume",
    "tissue volume",
    "cat12",
}
_PREPROCESSING_DENOISING_HINTS = {
    "ica-aroma",
    "ica aroma",
    "aroma",
    "fix",
    "fsl fix",
    "multi-echo",
    "multi echo",
    "tedana",
    "compcor",
    "nuisance regression",
    "physiological noise",
    "noise removal",
    "temporal filtering",
    "temporal filter",
    "band-pass",
    "bandpass",
    "high-pass",
    "highpass",
    "low-pass",
    "lowpass",
    "cleaned bold",
    "t2star",
    "t2*",
}
_QC_MOTION_TIMESERIES_HINTS = {
    "quality control",
    "qc",
    "temporal snr",
    "tsnr",
    "signal spikes",
    "spikes in timeseries",
    "artifact detection",
    "artifacts",
    "framewise displacement",
    "dvars",
    "outlier subjects",
    "brain coverage",
    "coverage check",
    "motion outlier",
    "timeseries qc",
    "mriqc",
}
_LESION_DETECTION_HINTS = {
    "lesion detection",
    "lesion segmentation",
    "lesion mask",
    "stroke lesion",
    "stroke patient",
    "automated lesion",
    "lesion mapping",
}
_STATISTICAL_RANDOMISE_HINTS = {
    "randomise",
    "fsl randomise",
    "palm",
    "cluster extent",
    "cluster-extent",
    "cluster mass",
    "tfce",
    "permutation inference",
    "nonparametric inference",
    "permutation test",
}
_MODEL_SELECTION_HINTS = {
    "nested cross-validation",
    "nested cross validation",
    "nested cv",
    "cross-validation",
    "cross validation",
    "hyperparameter tuning",
    "grid search",
    "model selection",
    "dimensionality reduction",
    "pca",
    "random seeds",
    "reproducibility",
    "validation metrics",
}
_DATA_VALIDATION_HINTS = {
    "preflight validation",
    "fail-fast",
    "fail fast",
    "missing required inputs",
    "required inputs",
    "bids validation",
    "input validation",
    "derivatives sanity",
    "missing files",
}
_STRUCTURAL_SEGMENTATION_HINTS = {
    "fast tissue segmentation",
    "tissue segmentation",
    "bias field correction",
    "bias correction",
    "fsl fast",
    "tissue classes",
    "gm",
    "wm",
    "csf",
}
_GROUP_ICA_HINTS = {
    "group ica",
    "melodic",
    "dual regression",
    "independent vector analysis",
    "iva",
    "linked components",
    "group independent component analysis",
}
_DIFFUSION_RECONSTRUCTION_HINTS = {
    "pseudo-fod",
    "pseudo fod",
    "fod",
    "fiber orientation distribution",
    "fibre orientation distribution",
    "spherical harmonic",
    "spherical deconvolution",
    "dwi2fod",
    "dti",
    "diffusion",
}
_VISUALIZATION_HINTS = {
    "glass brain",
    "plot",
    "overlay",
    "figure",
    "render",
    "activation map",
    "activation",
}
_KNOWLEDGE_GRAPH_HINTS = {
    "knowledge graph",
    "ontology",
    "hierarchical relationships",
    "hierarchical relation",
    "neurosynth terms",
    "ontology terms",
    "link",
    "map",
    "graph evidence",
    "multihop",
    "gene-brain-behavior",
}
_EEG_ICA_HINTS = {
    "ica",
    "independent component analysis",
    "eye blink",
    "blink artifact",
    "artifact removal",
    "remove components",
}
_EEG_TIME_FREQUENCY_HINTS = {
    "time-frequency",
    "time frequency",
    "gamma band",
    "wavelet",
    "morlet",
    "spectral power",
    "spectrogram",
    "power spectral",
}
_EEG_SOURCE_LOCALIZATION_HINTS = {
    "source localization",
    "source localize",
    "inverse solution",
    "dspm",
    "sloreta",
    "evoked responses",
    "auditory evoked",
}
_DISTORTION_CORRECTION_HINTS = {
    "fieldmap",
    "susceptibility distortion correction",
    "distortion correction",
    "sdc",
    "topup",
    "epi_reg",
    "epi reg",
    "unwarping",
    "prepare fieldmap",
}


class ToolMatch(BaseModel):
    """A matched tool with relevance score."""

    id: str
    name: str
    family_id: str
    score: float
    description: Optional[str] = None
    capabilities: List[str] = Field(default_factory=list)
    consumes: List[str] = Field(default_factory=list)
    produces: List[str] = Field(default_factory=list)
    runtime_kind: str = "container"
    source: str = "embedding"  # embedding | file_search


@dataclass
class FileSearchHit:
    tool_id: str
    score: float


@dataclass
class FamilyCard:
    id: str
    title: str
    summary: str
    when_to_use: List[str]
    tags: List[str]
    canonical_entrypoints: List[str]
    query_service_intents: List[str]
    graph_family_ids: List[str]


@lru_cache(maxsize=4)
def _load_family_cards(path_str: Optional[str] = None) -> List[FamilyCard]:
    override = path_str or os.environ.get("BR_TOOL_FAMILY_CARDS_PATH")
    if override:
        path = Path(override)
    else:
        path = resolve_from_config("catalog", "tool_family_cards.yaml")
    if not path.exists():
        return []

    data = yaml.safe_load(path.read_text()) or {}
    cards: List[FamilyCard] = []
    for item in data.get("family_cards", []) or []:
        card_id = str(item.get("id") or "").strip()
        if not card_id:
            continue
        cards.append(
            FamilyCard(
                id=card_id,
                title=str(item.get("title") or card_id),
                summary=str(item.get("summary") or "").strip(),
                when_to_use=[
                    str(value).strip()
                    for value in (item.get("when_to_use") or [])
                    if str(value).strip()
                ],
                tags=[
                    str(value).strip()
                    for value in (item.get("tags") or [])
                    if str(value).strip()
                ],
                canonical_entrypoints=[
                    str(value).strip()
                    for value in (item.get("canonical_entrypoints") or [])
                    if str(value).strip()
                ],
                query_service_intents=[
                    str(value).strip()
                    for value in (item.get("query_service_intents") or [])
                    if str(value).strip()
                ],
                graph_family_ids=[
                    str(value).strip()
                    for value in (item.get("graph_family_ids") or [])
                    if str(value).strip()
                ],
            )
        )
    return cards


@lru_cache(maxsize=2)
def _cached_sentence_transformer(model_name: str):
    return get_cached_sentence_transformer(model_name)


@lru_cache(maxsize=8)
def _family_cards_by_id(path_str: Optional[str] = None) -> dict[str, FamilyCard]:
    return {card.id: card for card in _load_family_cards(path_str)}


def _family_card_text(card: FamilyCard) -> str:
    parts = [
        card.id,
        card.title,
        card.summary,
        " ".join(card.when_to_use),
        " ".join(card.tags),
        " ".join(card.canonical_entrypoints),
    ]
    return " ".join(part for part in parts if part).strip()


def _routing_terms(text: str) -> set[str]:
    return {
        tok
        for tok in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(tok) >= 3 and tok not in _FAMILY_CARD_STOPWORDS
    }


def _family_card_lexical_bonus(
    card: FamilyCard,
    *,
    query: str,
    query_terms: set[str],
) -> float:
    card_terms = _routing_terms(
        " ".join(
            [
                card.id,
                card.title,
                card.summary,
                *card.tags,
                *card.when_to_use,
            ]
        )
    )
    overlap = len(query_terms & card_terms)
    bonus = 0.03 * overlap
    query_lower = (query or "").lower()

    if card.id == "decoding":
        if any(hint in query_lower for hint in _DECODING_OUTCOME_HINTS):
            bonus += 0.12
        if any(hint in query_lower for hint in _DECODING_PREP_HINTS):
            bonus += 0.06
    elif card.id == "model_selection":
        if any(hint in query_lower for hint in _MODEL_SELECTION_HINTS):
            bonus += 0.16
    elif card.id == "data_validation":
        if any(hint in query_lower for hint in _DATA_VALIDATION_HINTS):
            bonus += 0.18
        if {"required", "inputs"} <= query_terms or "preflight" in query_terms:
            bonus += 0.08
    elif card.id == "searchlight_decoding":
        if "searchlight" in query_lower:
            bonus += 0.12
    elif card.id == "brain_extraction":
        if any(hint in query_lower for hint in _BRAIN_EXTRACTION_HINTS):
            bonus += 0.18
        if {"brain", "extraction"} <= query_terms:
            bonus += 0.08
    elif card.id == "morphometry":
        if any(hint in query_lower for hint in _MORPHOMETRY_HINTS):
            bonus += 0.18
        if "vbm" in query_terms:
            bonus += 0.10
    elif card.id == "preprocessing_denoising":
        if any(hint in query_lower for hint in _PREPROCESSING_DENOISING_HINTS):
            bonus += 0.16
        if "denois" in query_lower:
            bonus += 0.06
    elif card.id == "qc_motion_timeseries":
        if any(hint in query_lower for hint in _QC_MOTION_TIMESERIES_HINTS):
            bonus += 0.18
        if {"motion", "outlier"} <= query_terms or {"brain", "coverage"} <= query_terms:
            bonus += 0.08
    elif card.id == "lesion_detection":
        if any(hint in query_lower for hint in _LESION_DETECTION_HINTS):
            bonus += 0.20
        if "lesion" in query_terms:
            bonus += 0.08
    elif card.id == "statistical_inference_randomise":
        if any(hint in query_lower for hint in _STATISTICAL_RANDOMISE_HINTS):
            bonus += 0.20
        if "randomise" in query_terms or "tfce" in query_terms:
            bonus += 0.08
    elif card.id == "brain_age":
        if any(phrase in query_lower for phrase in _BRAIN_AGE_PHRASES):
            bonus += 0.10
    elif card.id == "visualization":
        if any(hint in query_lower for hint in _VISUALIZATION_HINTS):
            bonus += 0.14
    elif card.id == "knowledge_graph":
        if any(hint in query_lower for hint in _KNOWLEDGE_GRAPH_HINTS):
            bonus += 0.18
        if {"knowledge", "graph"} <= query_terms or {
            "ontology",
            "terms",
        } <= query_terms:
            bonus += 0.08
    elif card.id == "electrophysiology_ica":
        if any(hint in query_lower for hint in _EEG_ICA_HINTS):
            bonus += 0.18
        if "ica" in query_terms or {"eye", "blink"} <= query_terms:
            bonus += 0.08
    elif card.id == "electrophysiology_time_frequency":
        if any(hint in query_lower for hint in _EEG_TIME_FREQUENCY_HINTS):
            bonus += 0.18
        if {"time", "frequency"} <= query_terms or {"gamma", "band"} <= query_terms:
            bonus += 0.08
    elif card.id == "electrophysiology_source_localization":
        if any(hint in query_lower for hint in _EEG_SOURCE_LOCALIZATION_HINTS):
            bonus += 0.18
        if {"source", "localization"} <= query_terms or "dspm" in query_terms:
            bonus += 0.08
    elif card.id == "distortion_correction":
        if any(hint in query_lower for hint in _DISTORTION_CORRECTION_HINTS):
            bonus += 0.18
        if "fieldmap" in query_terms or {"distortion", "correction"} <= query_terms:
            bonus += 0.08
    elif card.id == "structural_segmentation":
        if any(hint in query_lower for hint in _STRUCTURAL_SEGMENTATION_HINTS):
            bonus += 0.18
        if {"tissue", "segmentation"} <= query_terms or "fast" in query_terms:
            bonus += 0.08
    elif card.id == "group_ica":
        if any(hint in query_lower for hint in _GROUP_ICA_HINTS):
            bonus += 0.18
        if {"group", "ica"} <= query_terms or "iva" in query_terms:
            bonus += 0.08
    elif card.id == "diffusion_reconstruction":
        if any(hint in query_lower for hint in _DIFFUSION_RECONSTRUCTION_HINTS):
            bonus += 0.18
        if "dti" in query_terms or "fod" in query_lower or "diffusion" in query_terms:
            bonus += 0.08

    return bonus


@lru_cache(maxsize=8)
def _family_card_embedding_matrix(
    path_str: Optional[str],
    embedding_model_name: str,
):
    cards = _load_family_cards(path_str)
    if not cards:
        return np.zeros((0, 0), dtype=np.float32)
    model = _cached_sentence_transformer(embedding_model_name)
    texts = [_family_card_text(card) for card in cards]
    matrix = model.encode(texts, normalize_embeddings=True)
    return np.asarray(matrix, dtype=np.float32)


def select_family_card_ids(
    query: str,
    *,
    max_families: int,
    path_str: Optional[str] = None,
    embedding_model_name: str = "all-MiniLM-L6-v2",
) -> List[str]:
    cards = _load_family_cards(path_str)
    if not cards:
        return []

    matrix = _family_card_embedding_matrix(path_str, embedding_model_name)
    if matrix.size == 0:
        return []

    model = _cached_sentence_transformer(embedding_model_name)
    query_vec = np.asarray(
        model.encode(query, normalize_embeddings=True),
        dtype=np.float32,
    )
    similarities = matrix @ query_vec
    query_terms = _routing_terms(query)

    ranked: List[tuple[float, FamilyCard]] = []
    for index, card in enumerate(cards):
        lexical_bonus = _family_card_lexical_bonus(
            card,
            query=query,
            query_terms=query_terms,
        )
        ranked.append((float(similarities[index]) + lexical_bonus, card))

    ranked.sort(key=lambda item: (-item[0], item[1].id))
    return [card.id for score, card in ranked[:max_families] if score > 0]


def rank_family_card_entrypoints(
    query: str,
    *,
    max_families: int,
    limit: int,
    path_str: Optional[str] = None,
    embedding_model_name: str = "all-MiniLM-L6-v2",
) -> list[str]:
    family_ids = select_family_card_ids(
        query,
        max_families=max_families,
        path_str=path_str,
        embedding_model_name=embedding_model_name,
    )
    if family_ids:
        logger.info("Family-card-selected families: %s", family_ids)

    by_id = _family_cards_by_id(path_str)
    seen: set[str] = set()
    ranked_ids: list[str] = []
    for family_id in family_ids:
        card = by_id.get(str(family_id))
        if card is None:
            continue
        for tool_id in card.canonical_entrypoints:
            normalized = str(tool_id or "").strip()
            if not normalized or normalized in seen:
                continue
            ranked_ids.append(normalized)
            seen.add(normalized)
            if len(ranked_ids) >= max(1, min(int(limit), 50)):
                return ranked_ids
    return ranked_ids


def family_card_query_service_intents(
    family_ids: Optional[List[str]],
    *,
    path_str: Optional[str] = None,
) -> Optional[List[str]]:
    if not family_ids:
        return family_ids

    by_id = _family_cards_by_id(path_str)
    intents: List[str] = []
    seen: Set[str] = set()
    for family_id in family_ids:
        card = by_id.get(str(family_id))
        values = card.query_service_intents if card is not None else [family_id]
        for intent in values:
            normalized = str(intent or family_id).strip()
            if not normalized or normalized in seen:
                continue
            intents.append(normalized)
            seen.add(normalized)
    return intents or None


def family_card_graph_family_ids(
    family_ids: Optional[List[str]],
    *,
    path_str: Optional[str] = None,
) -> Optional[List[str]]:
    if not family_ids:
        return family_ids

    by_id = _family_cards_by_id(path_str)
    graph_ids: List[str] = []
    seen: Set[str] = set()
    for family_id in family_ids:
        card = by_id.get(str(family_id))
        values = card.graph_family_ids if card is not None else [family_id]
        for graph_id in values:
            normalized = str(graph_id or family_id).strip()
            if not normalized or normalized in seen:
                continue
            graph_ids.append(normalized)
            seen.add(normalized)
    return graph_ids or None


class ToolRetriever:
    """
    Two-stage tool retrieval system.

    Stage 1: Select relevant ToolFamilies based on query
    Stage 2: Retrieve tools from those families using hybrid search
    """

    def __init__(
        self,
        neo4j_uri: Optional[str] = None,
        neo4j_user: Optional[str] = None,
        neo4j_password: Optional[str] = None,
        embedding_model: Optional[str] = None,
        embedding_field: Optional[str] = None,
        enable_semantic: bool | None = None,
    ):
        """
        Initialize the retriever.

        Args:
            neo4j_uri: Neo4j connection URI (defaults to NEO4J_URI env)
            neo4j_user: Neo4j username (defaults to NEO4J_USER env)
            neo4j_password: Neo4j password (defaults to NEO4J_PASSWORD env)
            embedding_model: Model for query embedding (defaults to all-MiniLM-L6-v2)
        """
        self.uri = neo4j_uri or os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        self.user = neo4j_user or os.environ.get("NEO4J_USER", "neo4j")
        self.password = neo4j_password or os.environ.get("NEO4J_PASSWORD", "")
        self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
        self.use_query_service = os.environ.get(
            "BR_TOOL_RETRIEVER_SOURCE", "neurokg"
        ).lower() in {"neurokg", "kg", "query_service"}
        self.semantic_enabled = semantic_matching_enabled(
            enable_semantic,
            default=True,
        )

        # Initialize embedding model
        self.embedding_model_name = embedding_model or "all-MiniLM-L6-v2"
        self._embed_model = None
        self.family_routing_mode = (
            os.environ.get("BR_TOOL_FAMILY_ROUTING_MODE", "legacy").strip().lower()
        )
        self.embedding_field = (
            embedding_field or os.environ.get("BR_EMBEDDING_FIELD") or "embedding"
        ).strip()
        if self.embedding_field not in {"embedding", "embedding_v2"}:
            logger.warning(
                "Unsupported embedding field %s; falling back to 'embedding'",
                self.embedding_field,
            )
            self.embedding_field = "embedding"

        # File search integration
        self.use_file_search = os.environ.get(
            "BR_USE_GOOGLE_FILE_SEARCH", "true"
        ).lower() not in {"false", "0", "no"}
        raw_stores = os.environ.get("BR_FILE_SEARCH_STORE_NAMES")
        if raw_stores:
            self.file_search_stores = [
                s.strip() for s in raw_stores.split(",") if s.strip()
            ]
        else:
            single_store = (
                os.environ.get("FILE_SEARCH_STORE")
                or os.environ.get("BR_FILE_SEARCH_STORE")
                or os.environ.get("BR_GOOGLE_FILE_SEARCH_STORE")
                or os.environ.get("GOOGLE_FILE_SEARCH_STORE")
                or "fileSearchStores/brain-researcher-codebase-5i70bkfmcumj"
            )
            self.file_search_stores = [single_store]

        # Backwards-compat alias used by older call-sites.
        self.file_search_store = self.file_search_stores[0]
        self.file_search_model = (
            os.environ.get("BR_FILE_SEARCH_MODEL")
            or os.environ.get("DEFAULT_LLM_MODEL")
            or "gemini-3-flash-preview"
        )
        self._file_search_client = None
        self._file_search_tool = None
        # Auto GFS trigger (bounded, query-only)
        self.gfs_enabled = os.environ.get(
            "BR_GFS_AUTORETRIEVAL_ENABLED", "true"
        ).lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.max_snippets_per_doc = int(
            os.environ.get("BR_GFS_AUTORETRIEVAL_MAX_SNIPPETS", "2") or "2"
        )
        self.snippet_max_chars = int(
            os.environ.get("BR_GFS_AUTORETRIEVAL_SNIPPET_MAX_CHARS", "300") or "300"
        )
        self.last_gfs_diagnostics: Dict[str, Any] = {}

    def _get_file_search_tool(self):
        return None  # legacy path disabled

    def _file_search_hits(self, query: str, top_k: int = 20) -> list[FileSearchHit]:
        """Use generate_content + FileSearch tool to retrieve tool_id hits (best effort).

        SDK no longer exposes file_search_stores.query; we call generate_content with FileSearch tool
        and extract custom_metadata.tool_id from grounding chunks.
        """
        if not self.use_file_search:
            return []
        client = self.file_search_client
        if not client:
            return []
        try:
            from google.genai import types
        except Exception:
            return []

        # Aggregate hits from all stores
        all_hits: list[FileSearchHit] = []
        for store in route_gfs_stores(query, stores=self.file_search_stores):
            try:
                resp = client.models.generate_content(
                    model=self.file_search_model,
                    contents=query,
                    config=types.GenerateContentConfig(
                        tools=[
                            types.Tool(
                                file_search=types.FileSearch(
                                    file_search_store_names=[store]
                                )
                            )
                        ]
                    ),
                )
                cands = getattr(resp, "candidates", []) or []
                for cand in cands:
                    gm = getattr(cand, "grounding_metadata", None)
                    if not gm:
                        continue
                    chunks = getattr(gm, "grounding_chunks", []) or []
                    for ch in chunks:
                        tool_ids = self._extract_tool_ids_from_chunk(ch)
                        for tid in tool_ids:
                            score = getattr(ch, "relevance_score", 1.0) or 1.0
                            all_hits.append(FileSearchHit(tool_id=tid, score=score))
            except Exception as e:
                logger.debug("file_search generate_content failed for %s: %s", store, e)
                continue

        # Deduplicate by tool_id, keeping max score
        dedup: dict[str, FileSearchHit] = {}
        for hit in all_hits:
            if hit.tool_id not in dedup or hit.score > dedup[hit.tool_id].score:
                dedup[hit.tool_id] = hit
        return sorted(dedup.values(), key=lambda h: h.score, reverse=True)[:top_k]

    @staticmethod
    def _extract_tool_ids_from_chunk(chunk) -> list[str]:
        """Best-effort extract tool_id from grounding chunk.

        Priority: custom_metadata.tool_id ; fallback: regex on retrieved_context.text
        """
        ids: set[str] = set()
        for attr in (
            getattr(chunk, "metadata", None),
            getattr(chunk, "custom_metadata", None),
        ):
            if not attr:
                continue
            for cm in attr:
                if getattr(cm, "key", None) == "tool_id" and getattr(
                    cm, "string_value", None
                ):
                    ids.add(cm.string_value)
        try:
            rc = getattr(chunk, "retrieved_context", None)
            txt = getattr(rc, "text", "") if rc else ""
            import re

            # Allow optional prefix (pkg/version.), capture tool ids ending with .run
            patterns = [
                r"id\s*[:=]\s*['\"]?([A-Za-z0-9._-]*\.run)",
                r"tool_id\s*[:=]\s*['\"]?([A-Za-z0-9._-]*\.run)",
            ]
            for pat in patterns:
                ids.update(re.findall(pat, txt))
        except Exception:
            pass
        return list(ids)

    def _record_gfs_diagnostics(self, surface: str, payload: Dict[str, Any]) -> None:
        event = {
            "surface": surface,
            "gfs_triggered": bool(payload.get("triggered")),
            "gfs_reason": payload.get("reason"),
            "gfs_stores_hit": list(payload.get("stores_hit") or []),
            "gfs_call_count": int(payload.get("call_count") or 0),
            "gfs_status": payload.get("status"),
            "gfs_query_used": payload.get("query_used") or payload.get("query"),
            "gfs_n_docs_hit": int(payload.get("n_docs_hit") or 0),
        }
        try:
            from brain_researcher.services.agent import telemetry

            telemetry.record_event(event, event_type="gfs")
        except Exception:
            logger.debug("Failed to record GFS telemetry event", exc_info=True)
        try:
            from brain_researcher.services.agent.monitoring import metrics_collector

            metrics_collector.record_gfs_usage(
                surface=surface,
                status=str(payload.get("status") or "unknown"),
                call_count=int(payload.get("call_count") or 0),
                triggered=bool(payload.get("triggered")),
                n_docs_hit=int(payload.get("n_docs_hit") or 0),
            )
        except Exception:
            logger.debug("Failed to record GFS metrics", exc_info=True)

    def _snippets_from_gfs_hits(self, hits: List[Dict[str, Any]]) -> List[str]:
        snippets: list[str] = []
        seen_docs: set[str] = set()
        for hit in hits:
            doc_id = hit.get("doc_id") or "doc"
            if doc_id in seen_docs:
                continue
            seen_docs.add(doc_id)
            snippet = hit.get("snippet") or hit.get("text") or ""
            if len(snippet) > self.snippet_max_chars:
                snippet = snippet[: self.snippet_max_chars] + "..."
            snippets.append(snippet)
            if len(snippets) >= self.max_snippets_per_doc:
                break
        return snippets

    def _enrich_query_with_file_search(
        self,
        query: str,
        *,
        top_k: int = 6,
        result_count: Optional[int] = None,
        top_score: Optional[float] = None,
        weak_evidence: bool = False,
        max_calls: int = 2,
        surface: str = "agent.tool_retriever",
    ) -> tuple[str, Dict[str, Any]]:
        if not self.gfs_enabled:
            return query, {
                "status": "skipped",
                "reason": "disabled",
                "triggered": False,
                "stores_hit": [],
                "call_count": 0,
                "query": query,
                "query_used": query,
                "n_docs_hit": 0,
            }
        try:
            store_override = ",".join(self.file_search_stores)
            res = search_gfs_auto(
                query,
                top_k=top_k,
                store=store_override,
                model=self.file_search_model,
                gfs_enabled=self.gfs_enabled,
                result_count=result_count,
                top_score=top_score,
                weak_evidence=weak_evidence,
                max_calls=max_calls,
            )
        except Exception as exc:  # pragma: no cover - best effort
            logger.debug("GFS enrichment failed: %s", exc)
            return query, {
                "status": "error",
                "reason": "exception",
                "triggered": False,
                "stores_hit": [],
                "call_count": 0,
                "query": query,
                "query_used": query,
                "n_docs_hit": 0,
                "error": str(exc),
            }
        self.last_gfs_diagnostics = dict(res)
        self._record_gfs_diagnostics(surface, res)
        if not isinstance(res, dict) or res.get("status") != "ok":
            return query, res
        hits = res.get("hits") or []
        if not hits:
            return query, res

        snippets = self._snippets_from_gfs_hits(hits)
        if not snippets:
            return query, res
        enriched = query + "\n\nCONTEXT (gfs):\n" + "\n---\n".join(snippets)
        logger.debug("Enriched query with %d GFS snippets", len(snippets))
        return enriched, res

    @property
    def embed_model(self):
        """Lazy load embedding model."""
        if not self.semantic_enabled:
            raise RuntimeError("semantic_tool_retrieval_disabled")
        if self._embed_model is None:
            started_at = time.perf_counter()
            self._embed_model = _cached_sentence_transformer(self.embedding_model_name)
            logger.info(
                "ToolRetriever embedding model ready model=%s elapsed_ms=%.1f",
                self.embedding_model_name,
                (time.perf_counter() - started_at) * 1000.0,
            )
        return self._embed_model

    @property
    def file_search_client(self):
        """Lazy init google genai client for file search."""
        if self._file_search_client is None:
            try:
                from google import genai

                api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get(
                    "GOOGLE_API_KEY"
                )
                if api_key:
                    self._file_search_client = genai.Client(api_key=api_key)
                else:
                    self._file_search_client = False  # sentinel for "unavailable"
            except Exception as e:
                logger.warning("File search client init failed: %s", e)
                self._file_search_client = False
        return self._file_search_client

    def get_all_families(self) -> List[dict]:
        """Get all ToolFamilies with their tool counts."""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (f:ToolFamily)
                OPTIONAL MATCH (t:Tool)-[:BELONGS_TO_FAMILY]->(f)
                WITH f, count(t) AS tool_count
                RETURN f.id AS id, f.name AS name, tool_count
                ORDER BY tool_count DESC
            """)
            return [dict(r) for r in result]

    def select_families_by_query(
        self,
        query: str,
        llm: Any = None,
        max_families: int = 3,
    ) -> List[str]:
        """
        Stage 1: Select relevant ToolFamilies based on query.

        Args:
            query: User's query describing the task
            llm: Optional LLM for intelligent selection (falls back to keyword matching)
            max_families: Maximum number of families to select

        Returns:
            List of selected family IDs
        """
        if self.family_routing_mode == "cards" and self.semantic_enabled:
            selected = select_family_card_ids(
                query,
                max_families=max_families,
                path_str=os.environ.get("BR_TOOL_FAMILY_CARDS_PATH"),
                embedding_model_name=self.embedding_model_name,
            )
            if selected:
                return selected

        families = self.get_all_families()
        family_info = "\n".join(
            [f"- {f['id']}: {f['name']} ({f['tool_count']} tools)" for f in families]
        )

        if llm:
            # Use LLM for intelligent selection
            prompt = f"""Given this neuroimaging task query, select the most relevant tool families.

Query: {query}

Available families:
{family_info}

Return ONLY the family IDs (comma-separated) that are most relevant. Select 1-{max_families} families.
Example response: fsl,freesurfer,ants"""

            try:
                response = llm.invoke(prompt)
                content = (
                    response.content if hasattr(response, "content") else str(response)
                )
                # Parse comma-separated family IDs
                selected = [f.strip().lower() for f in content.split(",")]
                valid_ids = {f["id"] for f in families}
                selected = [f for f in selected if f in valid_ids][:max_families]
                if selected:
                    logger.info(f"LLM selected families: {selected}")
                    return selected
            except Exception as e:
                logger.warning(
                    f"LLM family selection failed: {e}, falling back to keyword matching"
                )

        # Keyword-based selection: Neo4j family IDs with config enrichment
        query_lower = query.lower()

        # Start with hardcoded keyword map matching Neo4j ToolFamily IDs
        keyword_map = {
            "fsl": ["fsl", "bet", "flirt", "fnirt", "melodic", "feat", "fmrib"],
            "freesurfer": [
                "freesurfer",
                "recon",
                "surface",
                "cortical",
                "parcellation",
            ],
            "ants": ["ants", "registration", "normalization", "antsregistration"],
            "afni": ["afni", "3d", "tshift", "volreg"],
            "mrtrix3": ["mrtrix", "dwi", "tractography", "diffusion", "fiber"],
            "workbench": ["workbench", "cifti", "surface", "hcp"],
            "bidsapps": ["fmriprep", "mriqc", "qsiprep", "preprocessing"],
            "niwrap_generic": ["niwrap", "generic"],
        }

        # Ensure all Neo4j families are in the map (use family ID as keyword)
        for fam in families:
            fid = fam.get("id", "").lower()
            if fid and fid not in keyword_map:
                keyword_map[fid] = [fid]

        # Enrich with aliases from config (optional - don't replace family IDs)
        config_map = self._load_keyword_map(families)
        if config_map:
            # Map config family IDs to Neo4j family IDs if possible
            config_to_neo4j = {
                "surface.pipeline_client": "freesurfer",
                "advanced_analysis.client": "fsl",
                "labels.client": "freesurfer",
            }
            for cfg_fid, keywords in config_map.items():
                neo4j_fid = config_to_neo4j.get(cfg_fid, cfg_fid)
                if neo4j_fid in keyword_map:
                    # Add config keywords to existing family
                    existing = set(keyword_map[neo4j_fid])
                    existing.update(keywords)
                    keyword_map[neo4j_fid] = list(existing)

        scores = {}
        for family_id, keywords in keyword_map.items():
            score = sum(1 for kw in keywords if kw in query_lower)
            if score > 0:
                scores[family_id] = score

        if scores:
            sorted_families = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            selected = [f[0] for f in sorted_families[:max_families]]
            logger.info(f"Keyword-selected families: {selected}")
            return selected

        # Default: return top families by tool count
        default = [f["id"] for f in families[:max_families]]
        logger.info(f"Default families (by tool count): {default}")
        return default

    def _load_keyword_map(self, families: List[dict]) -> Optional[dict]:
        """Build keyword map from catalog configs + tool aliases."""

        base_dir = resolve_from_config("catalog")
        family_files = [base_dir / "tool_families.yaml", base_dir / "chat_tools.yaml"]
        mappings_file = base_dir / "tool_mappings.yaml"

        keywords: dict[str, Set[str]] = {}

        # Load family descriptions/ops
        for cfg in family_files:
            if not cfg.exists():
                continue
            try:
                data = yaml.safe_load(cfg.read_text()) or {}
            except Exception:
                continue
            fam_entries = data.get("families") if isinstance(data, dict) else data
            if isinstance(fam_entries, list):
                for fam in fam_entries:
                    fid = (fam.get("id") or "").lower()
                    if not fid:
                        continue
                    pool = keywords.setdefault(fid, set())
                    desc = fam.get("description") or ""
                    pool.update(desc.lower().split())
                    for op_id in (fam.get("ops") or {}).keys():
                        pool.add(str(op_id).lower())

        # Enrich with aliases from tool_mappings.yaml
        if mappings_file.exists():
            try:
                mappings = yaml.safe_load(mappings_file.read_text()) or {}
            except Exception:
                mappings = {}
            if isinstance(mappings, dict):
                for family_id, tools in mappings.items():
                    if not isinstance(tools, dict):
                        continue
                    pool = keywords.setdefault(str(family_id).lower(), set())
                    for tool_id, meta in tools.items():
                        pool.add(str(tool_id).lower())
                        if isinstance(meta, dict):
                            aliases = meta.get("aliases") or []
                            pool.update([str(a).lower() for a in aliases])

        # Backfill ids missing in config with family ids
        for fam in families:
            fid = fam.get("id")
            if fid and fid.lower() not in keywords:
                keywords[fid.lower()] = {fid.lower()}

        return {fid: sorted(list(vals)) for fid, vals in keywords.items()}

    def _retrieve_via_query_service(
        self,
        query: str,
        family_ids: Optional[List[str]],
        top_k: int,
        filters: Optional[dict] = None,
    ) -> List[ToolMatch]:
        """
        Retrieve tools via BR-KG query_service (structured search + resolve).

        This keeps planner and chat layers on the same source of truth.
        """
        exposed_only = True
        if filters:
            if filters.get("exposed_only") is False:
                exposed_only = False
            if filters.get("include_unexposed") or filters.get("include_long_tail"):
                exposed_only = False
        if exposed_only and self._looks_like_explicit_tool_reference(query):
            # Preserve an "advanced mode" for explicit tool ids without polluting default search.
            exposed_only = False

        try:
            from brain_researcher.services.neurokg import query_service
        except Exception as exc:
            logger.debug("query_service import failed: %s", exc)
            return []

        primary_intents = family_ids if family_ids else None
        if primary_intents and self.family_routing_mode == "cards":
            primary_intents = family_card_query_service_intents(
                primary_intents,
                path_str=os.environ.get("BR_TOOL_FAMILY_CARDS_PATH"),
            )
        resp = query_service.search_tools_structured(
            query=query,
            primary_intents=primary_intents,
            exposed_only=exposed_only,
            k_candidates=max(50, top_k * 2),
        )
        candidates = resp.get("candidates") if isinstance(resp, dict) else None
        if not candidates:
            return []

        explicit_ref = self._looks_like_explicit_tool_reference(query)

        # If the query_service returns candidates but none have any overlap with the query,
        # treat this as "no candidates" to avoid returning arbitrary tools for nonsense queries.
        def _fallback_overlap_score(q: str, cand: dict[str, Any]) -> float:
            import re

            toks = [
                t for t in re.split(r"[^a-zA-Z0-9]+", (q or "").lower()) if len(t) >= 3
            ]
            stopwords = {
                "the",
                "and",
                "that",
                "this",
                "with",
                "from",
                "into",
                "onto",
                "over",
                "under",
                "about",
                "have",
                "has",
                "had",
                "been",
                "being",
                "are",
                "is",
                "was",
                "were",
                "will",
                "would",
                "should",
                "could",
                "can",
                "to",
                "of",
                "in",
                "on",
                "for",
                "as",
                "at",
                "by",
                "or",
                "not",
                "no",
                "please",
                "help",
                "me",
                "my",
                "your",
                "our",
                "we",
                "you",
                "i",
                "run",
                "execute",
                "analysis",
                "analyze",
                "compute",
                "show",
                "get",
                "generate",
                "query",
                "match",
                "matches",
                "nothing",
                "something",
            }
            toks = [t for t in toks if t not in stopwords]
            if not toks:
                return 0.0

            parts = [
                cand.get("tool_id"),
                cand.get("method"),
                cand.get("software"),
                cand.get("op"),
                cand.get("op_key"),
                cand.get("version"),
                cand.get("category"),
            ]
            intents = cand.get("intents")
            if isinstance(intents, list):
                parts.extend(intents)
            elif intents:
                parts.append(intents)
            hay = " ".join([str(p) for p in parts if p]).lower()
            if not hay:
                return 0.0

            return float(sum(1 for t in toks if t in hay))

        scores: list[tuple[dict[str, Any], float]] = []
        for cand in candidates:
            raw_score = cand.get("score")
            try:
                score = float(raw_score) if raw_score is not None else None
            except Exception:
                score = None
            if score is None:
                score = _fallback_overlap_score(query, cand)
            scores.append((cand, score))

        max_score = max((s for _, s in scores), default=0.0)
        if max_score <= 0.0 and not explicit_ref:
            return []

        # Drop zero-scored candidates unless the user explicitly referenced a tool id.
        if not explicit_ref:
            scores = [(c, s) for (c, s) in scores if s > 0.0]
            if not scores:
                return []

        scores.sort(
            key=lambda cs: (
                -cs[1],
                str(cs[0].get("tool_id") or ""),
            )
        )

        matches: List[ToolMatch] = []
        for idx, (cand, score) in enumerate(scores[:top_k]):
            tool_id = cand.get("tool_id")
            if not tool_id:
                continue
            matches.append(
                ToolMatch(
                    id=str(tool_id),
                    name=str(tool_id),
                    family_id=cand.get("method") or "",
                    score=score if score > 0.0 else max(0.1, 1.0 - 0.02 * idx),
                    description=None,
                    capabilities=[],
                    consumes=[],
                    produces=[],
                    runtime_kind="container",
                    source="neurokg",
                )
            )
        return matches

    _EXPLICIT_TOOL_RE = re.compile(
        r"(?:^|\\s)(?:afni|fsl|ants|spm|workbench|mrtrix3|freesurfer|nilearn|python)\\.[^\\s]+",
        re.IGNORECASE,
    )

    def _looks_like_explicit_tool_reference(self, query: str) -> bool:
        q = (query or "").strip()
        if not q:
            return False
        if ".run" in q or "@image:" in q or "@py:" in q or "@unknown" in q:
            return True
        return bool(self._EXPLICIT_TOOL_RE.search(q))

    def retrieve_tools(
        self,
        query: str,
        family_ids: Optional[List[str]] = None,
        top_k: int = 10,
        filters: Optional[dict] = None,
    ) -> List[ToolMatch]:
        """
        Stage 2: Retrieve tools using hybrid search.

        Args:
            query: User's query for semantic matching
            family_ids: List of family IDs to search within (None = all)
            top_k: Number of tools to return
            filters: Optional SPARQL-style filters (modality, runtime_kind, etc.)

        Returns:
            List of matched tools with scores
        """
        filters = filters or {}
        disable_gfs = filters.get("disable_gfs") or filters.get("disable_literature")
        working_query = query
        gfs_result: Dict[str, Any] = {
            "status": "skipped",
            "reason": "not_attempted",
            "triggered": False,
            "stores_hit": [],
            "call_count": 0,
            "query": query,
            "query_used": query,
            "n_docs_hit": 0,
        }

        if not disable_gfs:
            working_query, gfs_result = self._enrich_query_with_file_search(
                query,
                top_k=min(max(4, top_k), 6),
                max_calls=2,
                surface="agent.tool_retriever.preflight",
            )

        # Prefer BR-KG query_service path when enabled (unified source of truth)
        if self.use_query_service:
            try:
                ks_matches = self._retrieve_via_query_service(
                    query=working_query,
                    family_ids=family_ids,
                    top_k=top_k,
                    filters=filters,
                )
                if ks_matches:
                    if not disable_gfs and not gfs_result.get("triggered"):
                        top_match_score = max(
                            (float(match.score or 0.0) for match in ks_matches),
                            default=0.0,
                        )
                        retry_query, retry_result = self._enrich_query_with_file_search(
                            query,
                            top_k=min(max(4, top_k), 6),
                            result_count=len(ks_matches),
                            top_score=top_match_score,
                            weak_evidence=True,
                            max_calls=2,
                            surface="agent.tool_retriever.weak_fallback",
                        )
                        gfs_result = retry_result
                        if retry_result.get("status") == "ok" and retry_query != query:
                            retry_matches = self._retrieve_via_query_service(
                                query=retry_query,
                                family_ids=family_ids,
                                top_k=top_k,
                                filters=filters,
                            )
                            if retry_matches:
                                return retry_matches
                    return ks_matches
            except Exception as exc:
                logger.debug(
                    "query_service tool retrieval failed, falling back: %s", exc
                )

        if not disable_gfs and not gfs_result.get("triggered"):
            retry_query, retry_result = self._enrich_query_with_file_search(
                query,
                top_k=min(max(4, top_k), 6),
                result_count=0,
                top_score=0.0,
                weak_evidence=True,
                max_calls=2,
                surface="agent.tool_retriever.embedding_fallback",
            )
            if retry_result.get("status") == "ok":
                working_query = retry_query

        # Phase 0: optional file search → direct tool_id hits (tool-id metadata boost)
        fs_hits = (
            [] if disable_gfs else self._file_search_hits(working_query, top_k=top_k)
        )
        fs_tool_ids = [h.tool_id for h in fs_hits]

        if not self.semantic_enabled:
            logger.info(
                "ToolRetriever semantic retrieval disabled; skipping embedding search query=%r",
                query,
            )
            return [
                ToolMatch(
                    id=hit.tool_id,
                    name=hit.tool_id,
                    family_id="",
                    score=hit.score + 10.0,
                    runtime_kind="container",
                    source="file_search",
                )
                for hit in fs_hits[:top_k]
            ]

        # Generate query embedding
        query_embedding = self.embed_model.encode(
            working_query, normalize_embeddings=True
        ).tolist()

        # Choose vector index based on field
        index_name = (
            "tool_embedding_v2_idx"
            if self.embedding_field == "embedding_v2"
            else "tool_embedding_idx"
        )

        # Build Cypher query using vector index, with optional filters applied after ANN step.
        # When a family filter is present, overfetch ANN candidates and fall back to an exact
        # family-restricted dot-product pass if the post-filtered ANN pool is too small.
        where_clauses = []
        params = {"query_embedding": query_embedding, "top_k": top_k}

        graph_family_ids = family_ids
        if graph_family_ids and self.family_routing_mode == "cards":
            graph_family_ids = family_card_graph_family_ids(
                graph_family_ids,
                path_str=os.environ.get("BR_TOOL_FAMILY_CARDS_PATH"),
            )
        if graph_family_ids:
            where_clauses.append("f.id IN $family_ids")
            params["family_ids"] = graph_family_ids

        if filters:
            if filters.get("modality"):
                where_clauses.append("$modality IN t.modality")
                params["modality"] = filters["modality"]
            if filters.get("runtime_kind"):
                where_clauses.append("t.runtime_kind = $runtime_kind")
                params["runtime_kind"] = filters["runtime_kind"]
            if filters.get("gpu") is not None:
                where_clauses.append("t.gpu = $gpu")
                params["gpu"] = filters["gpu"]

        where_clause = " AND ".join(where_clauses)
        where_clause = f"WHERE {where_clause}" if where_clause else ""
        ann_top_k = top_k
        if graph_family_ids:
            ann_top_k = max(top_k * 8, len(graph_family_ids) * top_k * 4, 25)
        params["ann_top_k"] = ann_top_k

        cypher = f"""
            CALL db.index.vector.queryNodes('{index_name}', $ann_top_k, $query_embedding)
            YIELD node AS t, score
            MATCH (t)-[:BELONGS_TO_FAMILY]->(f:ToolFamily)
            {where_clause}
            RETURN t.id AS id, t.name AS name, f.id AS family_id,
                   score AS score, t.description AS description,
                   t.capabilities AS capabilities, t.consumes AS consumes,
                   t.produces AS produces, t.runtime_kind AS runtime_kind
            ORDER BY score DESC
            LIMIT $top_k
        """

        fallback_cypher = f"""
            MATCH (t:Tool)-[:BELONGS_TO_FAMILY]->(f:ToolFamily)
            WHERE t.{self.embedding_field} IS NOT NULL
            {("AND " + where_clause[6:]) if where_clause else ""}
            WITH t, f,
                 reduce(dot = 0.0, i IN range(0, size(t.{self.embedding_field})-1) |
                     dot + t.{self.embedding_field}[i] * $query_embedding[i]) AS score
            RETURN t.id AS id, t.name AS name, f.id AS family_id,
                   score AS score, t.description AS description,
                   t.capabilities AS capabilities, t.consumes AS consumes,
                   t.produces AS produces, t.runtime_kind AS runtime_kind
            ORDER BY score DESC
            LIMIT $top_k
        """

        matches: List[ToolMatch] = []

        # If file search produced tool_ids, fetch them directly with a neutral high score to keep ordering
        if fs_tool_ids:
            with self.driver.session() as session:
                rows = session.run(
                    "MATCH (t:Tool) WHERE t.id IN $ids RETURN t.id AS id, t.name AS name, t.runtime_kind AS runtime_kind",
                    ids=fs_tool_ids,
                )
                score_map = {h.tool_id: h.score for h in fs_hits}
                for r in rows:
                    matches.append(
                        ToolMatch(
                            id=r["id"],
                            name=r["name"],
                            family_id="",  # will fill via embedding results if present
                            score=score_map.get(r["id"], 1.0)
                            + 10.0,  # bump to rank ahead of embedding
                            runtime_kind=r.get("runtime_kind") or "container",
                            source="file_search",
                        )
                    )

        with self.driver.session() as session:
            need_exact_family_backfill = False
            try:
                ann_rows = list(session.run(cypher, **params))
                need_exact_family_backfill = bool(
                    graph_family_ids and len(ann_rows) < top_k
                )
            except Exception as e:
                logger.warning(
                    "Vector index query failed (%s); falling back to dot-product search",
                    e,
                )
                ann_rows = list(session.run(fallback_cypher, **params))

            for r in ann_rows:
                matches.append(
                    ToolMatch(
                        id=r["id"],
                        name=r["name"],
                        family_id=r["family_id"],
                        score=r["score"],
                        description=r["description"],
                        capabilities=r["capabilities"] or [],
                        consumes=r["consumes"] or [],
                        produces=r["produces"] or [],
                        runtime_kind=r["runtime_kind"] or "container",
                        source="embedding",
                    )
                )

            if need_exact_family_backfill:
                logger.debug(
                    "ToolRetriever ANN family backfill triggered query=%r family_ids=%s ann_hits=%d top_k=%d",
                    query,
                    graph_family_ids,
                    len(ann_rows),
                    top_k,
                )
                for r in session.run(fallback_cypher, **params):
                    matches.append(
                        ToolMatch(
                            id=r["id"],
                            name=r["name"],
                            family_id=r["family_id"],
                            score=r["score"],
                            description=r["description"],
                            capabilities=r["capabilities"] or [],
                            consumes=r["consumes"] or [],
                            produces=r["produces"] or [],
                            runtime_kind=r["runtime_kind"] or "container",
                            source="embedding",
                        )
                    )

        # Deduplicate by tool_id, keep highest score
        dedup = {}
        for m in matches:
            if m.id not in dedup or m.score > dedup[m.id].score:
                dedup[m.id] = m

        # Sort by score desc
        return sorted(dedup.values(), key=lambda x: x.score, reverse=True)[:top_k]

    def search(
        self,
        query: str,
        llm: Any = None,
        top_k: int = 10,
        max_families: int = 3,
        filters: Optional[dict] = None,
    ) -> List[ToolMatch]:
        """
        Full two-stage search: family selection + tool retrieval.

        Args:
            query: User's query
            llm: Optional LLM for family selection
            top_k: Number of tools to return
            max_families: Maximum families to search
            filters: Optional filters

        Returns:
            List of matched tools
        """
        filters = filters or {}
        disable_gfs = filters.get("disable_gfs") or filters.get("disable_literature")

        # Enrich query with Google File Search context (best effort)
        if disable_gfs:
            enriched_query = query
        else:
            enriched_query, _gfs = self._enrich_query_with_file_search(
                query,
                top_k=min(max(4, top_k), 6),
                max_calls=2,
                surface="agent.tool_retriever.search",
            )

        # Stage 1: Select families
        family_ids = self.select_families_by_query(
            enriched_query, llm=llm, max_families=max_families
        )

        # If selection is empty or only misc.client (catch-all), drop family filter
        if not family_ids or family_ids == ["misc.client"]:
            family_ids = None

        # Stage 2: Retrieve tools (embedding search) using enriched query
        filters_for_retrieval = dict(filters)
        if not disable_gfs:
            filters_for_retrieval["disable_gfs"] = True

        return self.retrieve_tools(
            query=enriched_query,
            family_ids=family_ids,
            top_k=top_k,
            filters=filters_for_retrieval,
        )

    def close(self):
        """Close the Neo4j driver."""
        self.driver.close()


# Convenience function for quick searches
def search_tools(query: str, top_k: int = 10) -> List[ToolMatch]:
    """Quick search for tools matching a query."""
    retriever = ToolRetriever()
    try:
        return retriever.search(query, top_k=top_k)
    finally:
        retriever.close()


if __name__ == "__main__":
    # Test the retriever
    import logging

    logging.basicConfig(level=logging.INFO)

    retriever = ToolRetriever()

    print("=== Testing Tool Retriever ===\n")

    # Test 1: Family listing
    print("Available families:")
    for f in retriever.get_all_families():
        print(f"  {f['id']}: {f['tool_count']} tools")

    # Test 2: Simple search
    print("\n--- Search: 'brain extraction skull stripping' ---")
    results = retriever.search("brain extraction skull stripping", top_k=5)
    for r in results:
        print(f"  {r.id}: {r.name} (score={r.score:.3f}, family={r.family_id})")

    # Test 3: Search with modality filter
    print("\n--- Search: 'registration' with modality=smri ---")
    results = retriever.search(
        "registration alignment", top_k=5, filters={"modality": "smri"}
    )
    for r in results:
        print(f"  {r.id}: {r.name} (score={r.score:.3f})")

    retriever.close()
    print("\nDone!")
