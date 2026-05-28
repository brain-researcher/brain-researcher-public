"""
Node Label Linker Module

Utility for creating MAPS_TO relationships between similar nodes across different
sources using embedding similarity and fuzzy string matching.

This module now prefers NICLIP vocabulary embeddings when available and falls
back to a locally cached sentence-transformer before finally relying on fuzzy
string matching.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from rapidfuzz import fuzz, process

from brain_researcher.config.paths import resolve_from_repo
from brain_researcher.core.ingestion.utils.label_embedder import (
    EmbeddingBatch,
    HybridLabelEmbedder,
)
from brain_researcher.services.neurokg.utils.matching_profile import (
    MatchingProfile,
    load_matching_profiles,
)

try:
    from sentence_transformers import SentenceTransformer  # type: ignore

    EMBEDDINGS_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    SentenceTransformer = None  # type: ignore
    EMBEDDINGS_AVAILABLE = False

try:
    import faiss  # type: ignore

    FAISS_AVAILABLE = True
except ImportError:  # pragma: no cover - FAISS is optional
    faiss = None  # type: ignore
    FAISS_AVAILABLE = False

logger = logging.getLogger(__name__)


class NodeLabelLinker:
    """Utility for linking nodes across sources based on label similarity."""

    def __init__(
        self,
        db,
        model_name: str = "all-MiniLM-L6-v2",
        niclip_model: str = "BrainGPT-7B-v0.2",
        min_niclip_coverage: float = 0.5,
    ) -> None:
        """Initialize the NodeLabelLinker.

        Args:
            db: NeuroKGGraphDB instance
            model_name: Name of the fallback sentence-transformer model to use
            niclip_model: Preferred NICLIP embedding model (if data available)
            min_niclip_coverage: Minimum fraction of labels (per side) that must
                map to NICLIP vocabulary embeddings before that space is used
        """
        self.db = db
        self.model_name = model_name
        self.last_embedding_model: str | None = None
        self.embedder = HybridLabelEmbedder(
            niclip_model=niclip_model,
            min_niclip_coverage=min_niclip_coverage,
            fallback_model=model_name,
        )
        self.use_gpu = os.environ.get("NICLIP_USE_GPU", "").lower() in {
            "1",
            "true",
            "yes",
        }
        (self.alias_to_canonical, self.canonical_to_aliases) = self._load_alias_map()
        self._matching_profiles = load_matching_profiles()

    @staticmethod
    def _get_label(data: dict[str, Any]) -> str:
        """Extract a human-readable label from node data."""
        return (
            data.get("name")
            or data.get("label")
            or data.get("title")
            or data.get("study_objective")
            or data.get("abbreviation")
            or data.get("task_name")
            or data.get("task_label")
            or data.get("concept_name")
            or ""
        )

    @staticmethod
    def _normalize_for_match(label: str) -> str:
        """Normalize labels for fuzzy matching (e.g., strip trailing 'task')."""
        if not label:
            return ""
        normalized = label.strip().lower()
        # Remove common trailing "task"/"tasks" suffixes.
        for suffix in (" task", " tasks"):
            if normalized.endswith(suffix):
                normalized = normalized[: -len(suffix)].strip()
                break
        # Trim trailing punctuation after suffix removal.
        while normalized and normalized[-1] in {".", ",", ";", ":"}:
            normalized = normalized[:-1].strip()
        return normalized

    def _get_profile(self, profile: str | None) -> MatchingProfile:
        if not profile:
            return self._matching_profiles["default"]
        return self._matching_profiles.get(profile, self._matching_profiles["default"])

    @staticmethod
    def _profile_provenance(profile: MatchingProfile) -> dict[str, str]:
        """Return mapping_profile and mapping_profile_hash for MAPS_TO edge provenance."""
        payload = profile.to_dict(include_aliases=True)
        canonical = json.dumps(
            payload, sort_keys=True, ensure_ascii=True, separators=(",", ":")
        )
        hash_val = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
        return {"mapping_profile": profile.name, "mapping_profile_hash": hash_val}

    def _normalize_label(
        self, label: str, profile: MatchingProfile | None, *, alias_mode: str = "strong"
    ) -> str:
        if profile and hasattr(profile, "normalize_label"):
            return profile.normalize_label(label, alias_mode=alias_mode)
        return self._normalize_for_match(label)

    def _embedding_label(
        self, label: str, profile: MatchingProfile | None = None
    ) -> str:
        """Return the label variant that should be used for embeddings."""
        if not label:
            return ""
        if profile and profile.alias_to_canonical:
            alias_key = label.strip().lower()
            canonical = profile.alias_to_canonical.get(alias_key)
            if canonical:
                return canonical
        return self._embedding_label_default(label)

    def _embedding_label_default(self, label: str) -> str:
        """Fallback embedding label selection using the legacy alias map."""
        if not label:
            return ""
        norm = label.strip().lower()

        canonical = self.alias_to_canonical.get(norm)
        if canonical:
            return canonical

        aliases = self.canonical_to_aliases.get(norm)
        if aliases:
            return aliases[0]

        return label

    @staticmethod
    def _load_alias_map() -> tuple[dict[str, str], dict[str, list[str]]]:
        """Load additional label aliases for improved embedding coverage."""
        if hasattr(NodeLabelLinker, "_alias_cache"):
            return NodeLabelLinker._alias_cache  # type: ignore[attr-defined]

        alias_path = resolve_from_repo(
            "scripts", "neurostore_task", "taxonomy", "alias_map.json"
        )
        alias_to_canonical: dict[str, str] = {}
        canonical_to_aliases: dict[str, set[str]] = {}
        canonical_display: dict[str, str] = {}

        if alias_path.exists():
            try:
                with alias_path.open() as f:
                    raw_aliases = json.load(f)
                for alias, canonical in raw_aliases.items():
                    if not alias or not canonical:
                        continue
                    alias_norm = alias.strip().lower()
                    canonical_norm = canonical.strip().lower()
                    if not alias_norm or not canonical_norm:
                        continue
                    # Skip obvious non-names (headers, separators)
                    if "=" in canonical_norm:
                        continue
                    canonical_display_value = canonical.strip()
                    alias_to_canonical[alias_norm] = canonical_display_value
                    canonical_display.setdefault(
                        canonical_norm, canonical_display_value
                    )
                    canonical_to_aliases.setdefault(canonical_norm, set()).add(
                        alias.strip()
                    )
                    canonical_to_aliases.setdefault(canonical_norm, set()).add(
                        canonical_display_value
                    )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Failed to load alias map from %s: %s", alias_path, exc)
        else:
            logger.debug(
                "Alias map not found at %s; continuing without additional aliases",
                alias_path,
            )

        # Convert sets to sorted lists for deterministic behaviour
        canonical_to_aliases_list: dict[str, list[str]] = {
            canon: [canonical_display.get(canon, canon)]
            + [
                alias
                for alias in sorted({alias for alias in aliases if alias})
                if alias.lower() != canonical_display.get(canon, canon).lower()
            ]
            for canon, aliases in canonical_to_aliases.items()
        }

        NodeLabelLinker._alias_cache = (alias_to_canonical, canonical_to_aliases_list)  # type: ignore[attr-defined]
        return NodeLabelLinker._alias_cache  # type: ignore[attr-defined]

    def _build_faiss_index(self, embeddings: np.ndarray) -> faiss.Index | None:
        """Build FAISS index for efficient similarity search."""
        if not FAISS_AVAILABLE or faiss is None:
            return None

        dim = embeddings.shape[1]

        # GPU index (optional)
        if self.use_gpu:
            try:
                if (
                    hasattr(faiss, "StandardGpuResources")
                    and hasattr(faiss, "get_num_gpus")
                    and faiss.get_num_gpus() > 0
                ):
                    resources = faiss.StandardGpuResources()
                    cpu_index = faiss.IndexFlatIP(dim)
                    gpu_index = faiss.index_cpu_to_gpu(resources, 0, cpu_index)
                    gpu_index.add(embeddings)
                    logger.debug(
                        "Built FAISS GPU index for %d vectors", embeddings.shape[0]
                    )
                    return gpu_index
                logger.debug(
                    "NICLIP_USE_GPU requested but no GPUs detected by FAISS; falling back to CPU index"
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Failed to build FAISS GPU index: %s; falling back to CPU", exc
                )

        try:
            metric = getattr(faiss, "METRIC_INNER_PRODUCT", 0)
            try:
                index = faiss.IndexHNSWFlat(dim, 32, metric)
            except TypeError:
                index = faiss.IndexHNSWFlat(dim, 32)
                if hasattr(index, "metric_type"):
                    index.metric_type = metric  # type: ignore[attr-defined]
            index.hnsw.efConstruction = 40
            index.add(embeddings)
            logger.debug("Built FAISS CPU index for %d vectors", embeddings.shape[0])
            return index
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to build FAISS CPU index: %s", exc)
            return None

    def match_nodes(
        self,
        nodes_a: list[tuple[str, dict[str, Any]]],
        nodes_b: list[tuple[str, dict[str, Any]]],
        embed_threshold: float = 0.85,
        fuzzy_threshold: int = 85,
        use_faiss: bool = True,
        use_embeddings: bool = True,
        profile: str | None = None,
        alias_mode: str | None = None,
    ) -> list[tuple[str, str, float, str]]:
        """Match nodes between two sets based on label similarity."""
        if not nodes_a or not nodes_b:
            logger.warning("Empty node list provided to match_nodes")
            return []

        self.last_embedding_model = None

        labels_a = [self._get_label(d) for _, d in nodes_a]
        labels_b = [self._get_label(d) for _, d in nodes_b]

        valid_a = [
            (node, label)
            for node, label in zip(nodes_a, labels_a, strict=False)
            if label
        ]
        valid_b = [
            (node, label)
            for node, label in zip(nodes_b, labels_b, strict=False)
            if label
        ]

        if not valid_a or not valid_b:
            logger.warning("No valid labels found for matching")
            return []

        labels_only_a = [label for _, label in valid_a]
        labels_only_b = [label for _, label in valid_b]
        active_profile = self._get_profile(profile)
        alias_mode = alias_mode or "strong"
        fuzzy_labels_a = [
            self._normalize_label(label, active_profile, alias_mode=alias_mode)
            for label in labels_only_a
        ]
        fuzzy_labels_b = [
            self._normalize_label(label, active_profile, alias_mode=alias_mode)
            for label in labels_only_b
        ]
        embedding_labels_a = [
            self._embedding_label(label, active_profile) for label in labels_only_a
        ]
        embedding_labels_b = [
            self._embedding_label(label, active_profile) for label in labels_only_b
        ]

        matches: list[tuple[str, str, float, str]] = []

        embedding_batch: EmbeddingBatch | None = None
        if EMBEDDINGS_AVAILABLE and use_embeddings:
            embedding_batch = self.embedder.compute_embeddings(
                embedding_labels_a, embedding_labels_b
            )
        else:
            logger.debug("Embedding backend disabled or skipped")

        if embedding_batch is not None:
            emb_a_matrix = embedding_batch.emb_a
            emb_b_matrix = embedding_batch.emb_b
            mask_a = embedding_batch.mask_a
            mask_b = embedding_batch.mask_b

            embedded_a = [
                (node, emb_a_matrix[idx])
                for idx, (node, _) in enumerate(valid_a)
                if mask_a[idx]
            ]
            embedded_b = [
                (node, emb_b_matrix[idx])
                for idx, (node, _) in enumerate(valid_b)
                if mask_b[idx]
            ]

            if embedded_a and embedded_b:
                self.last_embedding_model = embedding_batch.model_label

                emb_a = np.vstack([vec for _, vec in embedded_a]).astype("float32")
                emb_b = np.vstack([vec for _, vec in embedded_b]).astype("float32")

                try:
                    if use_faiss and FAISS_AVAILABLE and len(embedded_b) > 100:
                        index = self._build_faiss_index(emb_b)
                        if index is not None:
                            D, I = index.search(emb_a, 1)
                            for idx_a, (node_a, _) in enumerate(embedded_a):
                                idx_b = int(I[idx_a][0])
                                score = float(D[idx_a][0])
                                if score >= embed_threshold:
                                    node_b, _ = embedded_b[idx_b]
                                    matches.append(
                                        (node_a[0], node_b[0], score, "embedding")
                                    )
                        else:
                            sim = emb_a @ emb_b.T
                            for idx_a, (node_a, _) in enumerate(embedded_a):
                                scores = sim[idx_a]
                                idx_b = int(np.argmax(scores))
                                score = float(scores[idx_b])
                                if score >= embed_threshold:
                                    node_b, _ = embedded_b[idx_b]
                                    matches.append(
                                        (node_a[0], node_b[0], score, "embedding")
                                    )
                    else:
                        sim = emb_a @ emb_b.T
                        for idx_a, (node_a, _) in enumerate(embedded_a):
                            scores = sim[idx_a]
                            idx_b = int(np.argmax(scores))
                            score = float(scores[idx_b])
                            if score >= embed_threshold:
                                node_b, _ = embedded_b[idx_b]
                                matches.append(
                                    (node_a[0], node_b[0], score, "embedding")
                                )

                    logger.info(
                        "Found %d embedding matches above threshold %.2f (model=%s)",
                        len(matches),
                        embed_threshold,
                        self.last_embedding_model,
                    )
                except Exception as exc:  # pragma: no cover
                    logger.error(f"Embedding matching failed: {exc}")
                    matches = [m for m in matches if m[3] != "embedding"]
            else:
                logger.info("No overlapping embeddings found; using fuzzy matching")
        elif not use_embeddings:
            logger.info("Embedding matching disabled; using fuzzy matching only")

        matched_a = {m[0] for m in matches}
        unmatched_a = [
            (node, label)
            for (node, label), norm_label in zip(valid_a, fuzzy_labels_a, strict=False)
            if node[0] not in matched_a and norm_label
        ]

        if unmatched_a:
            logger.info(f"Trying fuzzy matching for {len(unmatched_a)} unmatched nodes")
            for node_a, label_a in unmatched_a:
                norm_label_a = self._normalize_label(
                    label_a, active_profile, alias_mode=alias_mode
                )
                if not norm_label_a:
                    continue
                best = process.extractOne(
                    norm_label_a, fuzzy_labels_b, scorer=fuzz.ratio
                )
                if best and best[1] >= fuzzy_threshold:
                    # Find corresponding node
                    for (node_b, _), norm_label_b in zip(
                        valid_b, fuzzy_labels_b, strict=False
                    ):
                        if norm_label_b == best[0]:
                            score = best[1] / 100.0
                            matches.append((node_a[0], node_b[0], score, "fuzzy"))
                            break

        if matches:
            dedup: dict[tuple[str, str], tuple[float, str]] = {}
            for n1, n2, score, method in matches:
                key = (n1, n2)
                existing = dedup.get(key)
                if existing is None or score > existing[0]:
                    dedup[key] = (score, method)
                elif (
                    score == existing[0]
                    and method == "embedding"
                    and existing[1] != "embedding"
                ):
                    dedup[key] = (score, method)
            matches = [
                (start, end, score, method)
                for (start, end), (score, method) in dedup.items()
            ]
            matches.sort(key=lambda item: item[2], reverse=True)

        logger.info(
            "Total matches found: %d (%d embedding, %d fuzzy)",
            len(matches),
            sum(1 for m in matches if m[3] == "embedding"),
            sum(1 for m in matches if m[3] == "fuzzy"),
        )

        return matches

    def create_maps_to_edges(
        self,
        nodes_a: list[tuple[str, dict[str, Any]]],
        nodes_b: list[tuple[str, dict[str, Any]]],
        embed_threshold: float = 0.85,
        fuzzy_threshold: int = 85,
        skip_existing: bool = True,
        additional_props: dict[str, Any] | None = None,
        batch_size: int = 500,
        use_embeddings: bool = True,
        profile: str | None = None,
        relationship_key_props: list[str] | None = None,
        equivalence_only: bool = False,
        candidate_output_path: str | None = None,
    ) -> int:
        """Create MAPS_TO edges for high-confidence matches.

        If a Neo4j driver is present (Neo4jGraphDB), create edges in batches via
        UNWIND. Otherwise, fall back to the per-edge creation used by the in-memory
        graph database.
        """

        alias_mode = "all" if equivalence_only else None
        matches = self.match_nodes(
            nodes_a,
            nodes_b,
            embed_threshold,
            fuzzy_threshold,
            use_embeddings=use_embeddings,
            profile=profile,
            alias_mode=alias_mode,
        )
        candidate_rows: list[dict[str, Any]] = []

        if equivalence_only and matches:
            active_profile = self._get_profile(profile)
            label_a = {nid: self._get_label(data) for nid, data in nodes_a}
            label_b = {nid: self._get_label(data) for nid, data in nodes_b}
            filtered_matches: list[tuple[str, str, float, str]] = []
            for n1, n2, score, method in matches:
                src_label = label_a.get(n1, "")
                tgt_label = label_b.get(n2, "")
                (
                    eq,
                    reason,
                    norm_src,
                    norm_tgt,
                    alias_hit_strong,
                    alias_hit_soft,
                ) = self._equivalence_gate(src_label, tgt_label, active_profile)
                if eq:
                    filtered_matches.append((n1, n2, score, method))
                else:
                    candidate_rows.append(
                        {
                            "start_id": n1,
                            "end_id": n2,
                            "source_label": src_label,
                            "target_label": tgt_label,
                            "normalized_source": norm_src,
                            "normalized_target": norm_tgt,
                            "confidence": score,
                            "method": method,
                            "profile": active_profile.name,
                            "alias_hit": alias_hit_strong,
                            "soft_alias_hit": alias_hit_soft,
                            "reason": reason,
                            **(additional_props or {}),
                        }
                    )
            matches = filtered_matches

        if candidate_output_path and candidate_rows:
            self._write_candidates(candidate_output_path, candidate_rows)
        additional_props = additional_props or {}

        active_profile = self._get_profile(profile)
        provenance_props = self._profile_provenance(active_profile)

        if hasattr(self.db, "_driver"):
            rows = []
            now = datetime.utcnow().isoformat()
            for n1, n2, score, method in matches:
                props = {
                    "confidence": score,
                    "method": method,
                    "created_at": now,
                    "created_by": "cross_source_linker",
                    **provenance_props,
                    **additional_props,
                }
                rows.append(
                    {
                        "start_id": n1,
                        "end_id": n2,
                        "props": props,
                    }
                )

            if not rows:
                return 0

            key_props = relationship_key_props or []
            if key_props:
                key_fields = ", ".join(
                    [f"{prop}: row.props.{prop}" for prop in key_props]
                )
                key_fragment = f" {{{key_fields}}}"
                optional_match = (
                    f"OPTIONAL MATCH (a)-[existing:MAPS_TO{key_fragment}]->(b)"
                )
                merge_clause = f"MERGE (a)-[r:MAPS_TO{key_fragment}]->(b)"
            else:
                optional_match = "OPTIONAL MATCH (a)-[existing:MAPS_TO]->(b)"
                merge_clause = "MERGE (a)-[r:MAPS_TO]->(b)"

            query = f"""
            UNWIND $rows AS row
            MATCH (a {{id: row.start_id}})
            MATCH (b {{id: row.end_id}})
            {optional_match}
            WITH row, a, b, existing
            WHERE $skip_existing = false OR existing IS NULL
            {merge_clause}
            ON CREATE SET r += row.props
            """

            created_total = 0
            skipped_total = 0
            with self.db._driver.session(
                database=getattr(self.db, "_database", None)
            ) as session:
                for i in range(0, len(rows), batch_size):
                    chunk = rows[i : i + batch_size]
                    result = session.run(query, rows=chunk, skip_existing=skip_existing)
                    summary = result.consume()
                    created_chunk = summary.counters.relationships_created
                    created_total += created_chunk
                    skipped_total += len(chunk) - created_chunk

            logger.info(
                "Created %d MAPS_TO edges (skipped %d existing) via UNWIND batching",
                created_total,
                skipped_total,
            )
            return created_total

        # Fallback: per-edge creation
        created = 0
        skipped = 0

        def _relationship_exists(start_node: str, end_node: str, rel_type: str) -> bool:
            if hasattr(self.db, "relationship_exists"):
                try:
                    return bool(
                        self.db.relationship_exists(start_node, end_node, rel_type)
                    )
                except TypeError:
                    # Some implementations may not accept rel_type or keyword args.
                    return bool(
                        self.db.relationship_exists(start_node, end_node, rel_type)
                    )

            if hasattr(self.db, "find_relationships"):
                try:
                    existing = self.db.find_relationships(
                        start_node=start_node, end_node=end_node, rel_type=rel_type
                    )
                except TypeError:
                    existing = self.db.find_relationships(
                        start_node, end_node, rel_type
                    )
                return bool(existing)

            return False

        for n1, n2, score, method in matches:
            if skip_existing and _relationship_exists(n1, n2, "MAPS_TO"):
                skipped += 1
                continue

            props = {
                "confidence": score,
                "method": method,
                "created_at": datetime.utcnow().isoformat(),
                "created_by": "cross_source_linker",
                **provenance_props,
                **additional_props,
            }

            try:
                success = self.db.create_relationship(n1, n2, "MAPS_TO", props)
                if success:
                    created += 1
                    logger.debug(
                        "Created MAPS_TO: %s -> %s (method: %s, confidence: %.3f)",
                        n1,
                        n2,
                        method,
                        score,
                    )
                else:
                    logger.warning(f"Failed to create MAPS_TO: {n1} -> {n2}")
            except Exception as exc:  # pragma: no cover
                logger.error(f"Error creating MAPS_TO relationship: {exc}")

        logger.info(f"Created %d MAPS_TO edges, skipped %d existing", created, skipped)
        return created

    @staticmethod
    def _equivalence_gate(
        source_label: str,
        target_label: str,
        profile: MatchingProfile,
    ) -> tuple[bool, str, str, str, bool, bool]:
        """Return whether two labels are equivalent under the matching profile."""
        norm_source = profile.normalize_label(source_label, alias_mode="strong")
        norm_target = profile.normalize_label(target_label, alias_mode="strong")
        if not norm_source or not norm_target:
            return False, "normalized_empty", norm_source, norm_target, False, False
        if norm_source == norm_target:
            return True, "normalized_equal", norm_source, norm_target, False, False

        alias_hit_strong = False
        alias_hit_soft = False
        alias_to_canonical = profile.alias_to_canonical or {}
        alias_to_canonical_soft = profile.alias_to_canonical_soft or {}
        source_key = source_label.strip().lower() if source_label else ""
        target_key = target_label.strip().lower() if target_label else ""
        canonical_source = alias_to_canonical.get(source_key)
        canonical_target = alias_to_canonical.get(target_key)
        if canonical_source:
            alias_hit_strong = True
        if canonical_target:
            alias_hit_strong = True

        soft_source = alias_to_canonical_soft.get(source_key)
        soft_target = alias_to_canonical_soft.get(target_key)
        if soft_source or soft_target:
            alias_hit_soft = True

        canonical_source_norm = (
            profile.normalize_label(canonical_source, alias_mode="strong")
            if canonical_source
            else ""
        )
        canonical_target_norm = (
            profile.normalize_label(canonical_target, alias_mode="strong")
            if canonical_target
            else ""
        )

        if canonical_source_norm and canonical_target_norm:
            if canonical_source_norm == canonical_target_norm:
                return (
                    True,
                    "alias_canonical_equal",
                    norm_source,
                    norm_target,
                    True,
                    alias_hit_soft,
                )
        if canonical_source_norm and canonical_source_norm == norm_target:
            return (
                True,
                "alias_to_normalized",
                norm_source,
                norm_target,
                True,
                alias_hit_soft,
            )
        if canonical_target_norm and canonical_target_norm == norm_source:
            return (
                True,
                "alias_to_normalized",
                norm_source,
                norm_target,
                True,
                alias_hit_soft,
            )
        if alias_hit_soft:
            return False, "soft_alias_candidate", norm_source, norm_target, False, True

        return False, "normalized_mismatch", norm_source, norm_target, False, False

    @staticmethod
    def _write_candidates(path: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=True) + "\n")

    def link_nodes_by_label(
        self,
        label_a: str,
        label_b: str,
        source_a: str | None = None,
        source_b: str | None = None,
        **kwargs,
    ) -> int:
        """Convenience method to link nodes of two different labels."""
        props_a = {"source": source_a} if source_a else None
        props_b = {"source": source_b} if source_b else None

        nodes_a = self.db.find_nodes(labels=label_a, properties=props_a)
        nodes_b = self.db.find_nodes(labels=label_b, properties=props_b)

        logger.info(
            "Found %d %s nodes and %d %s nodes",
            len(nodes_a),
            label_a,
            len(nodes_b),
            label_b,
        )

        if not nodes_a or not nodes_b:
            logger.warning("No nodes found for linking")
            return 0

        additional_props = kwargs.pop("additional_props", {})
        additional_props.update(
            {
                "source_label_a": label_a,
                "source_label_b": label_b,
            }
        )
        if source_a:
            additional_props["source_a"] = source_a
        if source_b:
            additional_props["source_b"] = source_b

        return self.create_maps_to_edges(
            nodes_a, nodes_b, additional_props=additional_props, **kwargs
        )
