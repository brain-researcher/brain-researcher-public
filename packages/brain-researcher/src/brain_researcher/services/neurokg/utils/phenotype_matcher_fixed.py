from __future__ import annotations

import csv
import logging
from pathlib import Path

try:
    import faiss
    import numpy as np
    from sentence_transformers import SentenceTransformer

    EMBEDDINGS_AVAILABLE = True
except ImportError:
    EMBEDDINGS_AVAILABLE = False

from rapidfuzz import fuzz

logger = logging.getLogger(__name__)


def _load_synonyms(path: Path) -> tuple[dict[str, str], dict[str, str], set[str]]:
    """Load phenotype synonyms from TSV file."""
    label_to_id: dict[str, str] = {}
    lookup: dict[str, str] = {}
    curated_aliases: set[str] = set()

    if not path.exists():
        logger.warning(f"Phenotype aliases file not found: {path}")
        return label_to_id, lookup, curated_aliases

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            pid = row.get("phenotype_id", "")
            label = row.get("label", "")
            alias = row.get("alias") or label

            if pid and label:
                label_to_id[label] = pid
                lookup[label.lower()] = label

            if alias:
                lookup[alias.lower()] = label
                if label and alias.lower() != label.lower():
                    curated_aliases.add(alias.lower())

    logger.info(
        "Loaded %s phenotypes with %s aliases (%s curated aliases)",
        len(label_to_id),
        len(lookup),
        len(curated_aliases),
    )
    return label_to_id, lookup, curated_aliases


class PhenotypeMatcher:
    """Phenotype matcher using embeddings with synonym fallback."""

    def __init__(
        self,
        synonyms_path: Path | None = None,
        embed_threshold: float = 0.86,
        fuzzy_threshold: int = 90,
    ) -> None:
        if synonyms_path is None:
            synonyms_path = (
                Path(__file__).resolve().parent / "../data/phenotype_aliases.tsv"
            )

        self.embed_threshold = embed_threshold
        self.fuzzy_threshold = fuzzy_threshold
        self.weak_fuzzy_floor = 0.95
        self.label_to_id, self.lookup, self.curated_aliases = _load_synonyms(
            Path(synonyms_path)
        )
        self.labels = list(self.label_to_id.keys())

        # Initialize embeddings if available
        self.embeddings_enabled = False
        if EMBEDDINGS_AVAILABLE and self.labels:
            try:
                self.sbert_model = SentenceTransformer("all-MiniLM-L6-v2")
                embs = self.sbert_model.encode(
                    self.labels, normalize_embeddings=True, convert_to_numpy=True
                ).astype("float32")
                self.index = faiss.IndexFlatIP(embs.shape[1])
                self.index.add(embs)
                self.embeddings_enabled = True
                logger.info("Embeddings initialized successfully")
            except Exception as e:
                logger.warning(f"Failed to initialize embeddings: {e}")
                self.index = None
        else:
            self.sbert_model = None
            self.index = None

    def match(self, text: str) -> dict[str, any] | None:
        """Match text to a phenotype using multiple methods."""
        if not text or not text.strip():
            return None

        q = text.strip().lower()

        # 1. Try exact match
        if q in self.lookup:
            label = self.lookup[q]
            return {
                "phenotype_id": self.label_to_id[label],
                "label": label,
                "score": 1.0,
                "method": "exact",
            }

        # 2. Try embedding-based match if available
        if self.embeddings_enabled and self.index is not None:
            try:
                vec = self.sbert_model.encode([text], normalize_embeddings=True).astype(
                    "float32"
                )
                D, I = self.index.search(vec, 1)
                score = float(D[0][0])
                if score >= self.embed_threshold:
                    label = self.labels[int(I[0][0])]
                    return {
                        "phenotype_id": self.label_to_id[label],
                        "label": label,
                        "score": score,
                        "method": "embedding",
                    }
            except Exception as e:
                logger.debug(f"Embedding search failed: {e}")

        # 3. Fuzzy string matching fallback
        best_label = None
        best_alias = ""
        best_score = 0
        for alias, label in self.lookup.items():
            s = fuzz.ratio(q, alias)
            if s > best_score:
                best_score = s
                best_label = label
                best_alias = alias

        if best_label and best_score >= self.fuzzy_threshold:
            score_norm = best_score / 100.0
            alias_corroborated = best_alias in self.curated_aliases
            if score_norm < self.weak_fuzzy_floor and not alias_corroborated:
                logger.debug(
                    "Rejected weak phenotype fuzzy match: query='%s', alias='%s', "
                    "score=%.2f",
                    text,
                    best_alias,
                    score_norm,
                )
                return None
            return {
                "phenotype_id": self.label_to_id[best_label],
                "label": best_label,
                "score": score_norm,
                "method": "fuzzy",
            }

        return None


def get_or_create_disease_trait(
    db, phenotype_id: str, name: str, mesh_term: str = None
) -> str:
    """Create or get a DiseaseTrait node (separate from Phenotype nodes)."""
    # Use DiseaseTrait label to avoid confusion with existing Phenotype nodes
    matches = db.find_nodes(
        labels="DiseaseTrait", properties={"phenotype_id": phenotype_id}
    )
    if matches:
        return matches[0][0]

    properties = {
        "phenotype_id": phenotype_id,
        "name": name,
        "source": "phenotype_matcher",
    }

    if mesh_term:
        properties["mesh_term"] = mesh_term

    return db.create_node("DiseaseTrait", properties)
