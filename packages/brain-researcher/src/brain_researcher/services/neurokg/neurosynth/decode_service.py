from __future__ import annotations

import json
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import nibabel as nib
import numpy as np
import pandas as pd
import scipy.sparse as sp
from nibabel.affines import apply_affine
from neo4j import GraphDatabase

from brain_researcher.services.neurokg.etl.yeo17_features import Yeo17Feature
from brain_researcher.services.neurokg.etl.yeo17_writer import WriterConfig, write_sparse_edges
from brain_researcher.services.neurokg.spatial.neuromaps_assets import (
    NeuromapsAssets,
    resolve_neuromaps_assets,
)

logger = logging.getLogger(__name__)


@dataclass
class DecodeResult:
    map_id: str
    edge_count: int
    ttl_expires_at: int
    study_count: int
    features: List[Yeo17Feature]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class _LdaVariant:
    name: str
    matrix: sp.csr_matrix
    topic_count: int
    description: str
    keywords: Dict[int, str]


class NeurosynthDecoder:
    """On-demand Neurosynth term decoder -> Yeo-17 sparse edges."""

    def __init__(
        self,
        *,
        data_dir: Path,
        lda_dir: Optional[Path] = None,
        writer_config: WriterConfig,
        neuromaps_root: Optional[Path] = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.lda_dir = Path(lda_dir) if lda_dir else None
        self.writer_config = writer_config
        self.neuromaps_root = neuromaps_root
        self._load_term_matrix()
        self._load_metadata()
        self._load_coordinates()
        self._load_label_assets()
        self._lda_variants: Dict[str, _LdaVariant] = {}
        if self.lda_dir and self.lda_dir.exists():
            self._load_lda_variants()
        elif self.lda_dir:
            logger.warning(
                "Configured LDA directory %s does not exist", self.lda_dir
            )

    # ------------------------------------------------------------------
    def _load_term_matrix(self) -> None:
        features_path = self.data_dir / "data-neurosynth_version-7_vocab-terms_source-abstract_type-tfidf_features.npz"
        vocab_path = self.data_dir / "data-neurosynth_version-7_vocab-terms_vocabulary.txt"
        if not features_path.exists() or not vocab_path.exists():
            raise FileNotFoundError(f"Missing Neurosynth feature files under {self.data_dir}")
        logger.info("Loading Neurosynth term feature matrix from %s", features_path)
        self._term_matrix = sp.load_npz(features_path).tocsc()
        with vocab_path.open("r", encoding="utf-8") as f:
            vocab = [line.strip() for line in f]
        self._term_index = {term.lower(): idx for idx, term in enumerate(vocab)}
        self._terms = vocab
        logger.info("Loaded %d terms; matrix shape=%s", len(vocab), self._term_matrix.shape)

    def _load_metadata(self) -> None:
        metadata_path = self.data_dir / "data-neurosynth_version-7_metadata.tsv.gz"
        if not metadata_path.exists():
            raise FileNotFoundError(metadata_path)
        logger.info("Loading Neurosynth metadata from %s", metadata_path)
        df = pd.read_csv(metadata_path, sep="\t")
        self._study_ids = df["id"].astype(str).tolist()
        logger.info("Loaded %d study metadata rows", len(self._study_ids))

    def _load_coordinates(self) -> None:
        coords_path = self.data_dir / "data-neurosynth_version-7_coordinates.tsv.gz"
        if not coords_path.exists():
            raise FileNotFoundError(coords_path)
        logger.info("Loading Neurosynth coordinates from %s", coords_path)
        coords_df = pd.read_csv(coords_path, sep="\t")
        grouped: Dict[str, List[tuple[float, float, float]]] = defaultdict(list)
        for row in coords_df.itertuples(index=False):
            grouped[str(row.id)].append((float(row.x), float(row.y), float(row.z)))
        self._coords_by_study = grouped
        logger.info("Indexed coordinates for %d studies", len(grouped))

    def _load_label_assets(self) -> None:
        assets: NeuromapsAssets = resolve_neuromaps_assets(self.neuromaps_root)
        label_img = assets.load_label()
        self._label_data = np.asarray(label_img.get_fdata(), dtype=np.int16)
        self._inv_affine = np.linalg.inv(label_img.affine)
        self._label_shape = self._label_data.shape
        logger.info("Loaded Yeo-17 label image %s", assets.label_img)

    def _load_lda_variants(self) -> None:
        assert self.lda_dir is not None
        for variant_dir in sorted(self.lda_dir.iterdir()):
            if not variant_dir.is_dir():
                continue
            variant_name = variant_dir.name
            prefix = f"data-neurosynth_version-7_vocab-{variant_name}"
            features_path = variant_dir / f"{prefix}_source-abstract_type-weight_features.npz"
            metadata_path = variant_dir / f"{prefix}_metadata.json"
            keys_path = variant_dir / f"{prefix}_keys.tsv"
            if not features_path.exists():
                logger.warning("Skipping LDA variant %s (missing %s)", variant_name, features_path)
                continue
            try:
                matrix = sp.load_npz(features_path).tocsr()
            except Exception as exc:
                logger.warning("Failed to load LDA matrix %s: %s", features_path, exc)
                continue

            description = ""
            if metadata_path.exists():
                try:
                    meta = json.loads(metadata_path.read_text())
                    description = meta.get("description", "")
                except Exception as exc:
                    logger.warning("Failed to parse %s: %s", metadata_path, exc)

            keywords: Dict[int, str] = {}
            if keys_path.exists():
                with keys_path.open("r", encoding="utf-8") as f:
                    for line in f:
                        parts = line.rstrip("\n").split("\t", 2)
                        if len(parts) < 3:
                            continue
                        try:
                            topic_idx = int(parts[0])
                        except ValueError:
                            continue
                        keywords[topic_idx] = parts[2]

            variant = _LdaVariant(
                name=variant_name,
                matrix=matrix,
                topic_count=matrix.shape[1],
                description=description,
                keywords=keywords,
            )
            key = variant_name.lower()
            self._lda_variants[key] = variant
            # Allow requests like "LDA100" or mixed case aliases
            self._lda_variants[variant_name.upper()] = variant
            logger.info(
                "Loaded LDA variant %s with %d topics and matrix shape %s",
                variant_name,
                variant.topic_count,
                matrix.shape,
            )
        if not self._lda_variants:
            logger.warning(
                "LDA directory %s is configured but no variants were loaded", self.lda_dir
            )

    def _get_lda_variant(self, variant_name: str) -> _LdaVariant:
        if not self._lda_variants:
            raise ValueError("No LDA topic variants are configured")
        key = variant_name.strip()
        match = self._lda_variants.get(key) or self._lda_variants.get(key.lower())
        if not match:
            available = sorted({variant.name for variant in self._lda_variants.values()})
            raise ValueError(
                f"Unknown LDA variant {variant_name}. Available: {available}"
            )
        return match

    def _summarize_topics(
        self,
        *,
        variant_name: str,
        study_indices: np.ndarray,
        study_weights: np.ndarray,
        top_k: int,
    ) -> Dict[str, Any]:
        variant = self._get_lda_variant(variant_name)
        if study_indices.size == 0:
            return {}
        rows = variant.matrix[study_indices]
        weights = study_weights.astype(np.float64, copy=True)
        weighted_rows = rows.multiply(weights[:, None])
        topic_weights = np.asarray(weighted_rows.sum(axis=0)).ravel()
        if topic_weights.size == 0:
            return {}
        total = float(topic_weights.sum())
        if total <= 0:
            return {}
        order = np.argsort(topic_weights)[::-1]
        top_indices = order[: max(top_k, 0)]
        topics = []
        for idx in top_indices:
            weight = float(topic_weights[idx])
            if weight <= 0:
                continue
            topics.append(
                {
                    "topic": int(idx),
                    "weight": weight,
                    "pct": weight / total if total else 0.0,
                    "keywords": variant.keywords.get(int(idx), ""),
                }
            )
        return {
            "variant": variant.name,
            "topic_count": variant.topic_count,
            "description": variant.description,
            "top_k": top_k,
            "topics": topics,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def decode_term(
        self,
        *,
        term: str,
        analysis_type: str = "association",
        ttl_hours: int = 24,
        top_k: int = 8,
        topic_variant: Optional[str] = None,
        topic_top_k: int = 5,
    ) -> DecodeResult:
        term_idx = self._term_index.get(term.lower())
        if term_idx is None:
            raise ValueError(f"Unknown Neurosynth term {term}")

        column = self._term_matrix.getcol(term_idx)
        if column.nnz == 0:
            raise ValueError(f"Term {term} has no associated studies in Neurosynth")

        study_indices = np.asarray(column.indices, dtype=int)
        study_weights = np.asarray(column.data, dtype=np.float64)

        region_weights: Dict[int, float] = defaultdict(float)
        region_counts: Dict[int, int] = defaultdict(int)
        studies_used = set()

        for study_idx, weight in zip(study_indices, study_weights):
            pmid = self._study_ids[study_idx]
            coords = self._coords_by_study.get(pmid)
            if not coords:
                continue
            per_coord = float(weight) / max(len(coords), 1)
            for coord in coords:
                label = self._label_for_coord(coord)
                if label <= 0:
                    continue
                region_weights[label] += per_coord
                region_counts[label] += 1
            studies_used.add(pmid)

        if not region_weights:
            raise RuntimeError(
                f"Decoded zero Yeo-17 regions for term {term}. Check coordinate coverage."
            )

        total_weight = sum(region_weights.values())
        features = [
            Yeo17Feature(
                region_id=f"yeo17:{label:02d}",
                weight=float(weight),
                pct_active=float(weight) / total_weight if total_weight else 0.0,
                n_vox=int(region_counts[label]),
                z_thr=0.0,
            )
            for label, weight in region_weights.items()
        ]
        features.sort(key=lambda f: f.weight, reverse=True)

        expires_at = int(time.time()) + ttl_hours * 3600
        map_id = self._build_map_id(term, analysis_type)
        self._upsert_stats_map(
            map_id=map_id,
            term=term,
            analysis_type=analysis_type,
            study_count=len(studies_used),
        )
        edge_count = write_sparse_edges(
            config=self.writer_config,
            map_id=map_id,
            map_source="neurosynth",
            template_space="tpl:MNI152NLin2009cAsym_2mm",
            edge_source="neurosynth",
            features=features,
            top_k=top_k,
            etl_version="v1",
            expires_at_epoch=expires_at,
        )
        metadata: Dict[str, Any] = {}
        if topic_variant:
            summary = self._summarize_topics(
                variant_name=topic_variant,
                study_indices=study_indices,
                study_weights=study_weights,
                top_k=topic_top_k,
            )
            if summary:
                metadata["topics"] = summary
        return DecodeResult(
            map_id=map_id,
            edge_count=edge_count,
            ttl_expires_at=expires_at,
            study_count=len(studies_used),
            features=features[:top_k],
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _label_for_coord(self, coord: tuple[float, float, float]) -> int:
        ijk = np.rint(apply_affine(self._inv_affine, coord)).astype(int)
        if np.any(ijk < 0):
            return 0
        if ijk[0] >= self._label_shape[0] or ijk[1] >= self._label_shape[1] or ijk[2] >= self._label_shape[2]:
            return 0
        return int(self._label_data[ijk[0], ijk[1], ijk[2]])

    def _build_map_id(self, term: str, analysis_type: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", term.lower()).strip("-") or "term"
        return f"neurosynth:{slug}:{analysis_type}:v1"

    def _upsert_stats_map(
        self,
        *,
        map_id: str,
        term: str,
        analysis_type: str,
        study_count: int,
    ) -> None:
        query = """
        MERGE (m:StatsMap {id: $map_id})
        ON CREATE SET m.source = "neurosynth", m.created_at = timestamp()
        SET m.term = $term,
            m.analysis_type = $analysis_type,
            m.study_count = $study_count,
            m.updated_at = timestamp()
        """
        driver = GraphDatabase.driver(
            self.writer_config.uri,
            auth=(self.writer_config.user, self.writer_config.password),
        )
        try:
            with driver.session(database=self.writer_config.database) as session:
                session.run(
                    query,
                    map_id=map_id,
                    term=term,
                    analysis_type=analysis_type,
                    study_count=study_count,
                )
        finally:
            driver.close()


__all__ = ["NeurosynthDecoder", "DecodeResult"]
