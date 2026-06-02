"""
Enhanced embedding index with configuration and metrics support.

This module provides a sharded FAISS index for text/figure embeddings
with integrated configuration management and performance monitoring.
"""

import glob
import logging
import os
import pickle
import threading
import time
from typing import Any

import faiss
import numpy as np
import psutil
from sentence_transformers import SentenceTransformer

from .embedding_config import EmbeddingConfig, get_config
from .embedding_metrics import QueryTimer, get_metrics_collector

logger = logging.getLogger(__name__)


class EmbeddingIndex:
    """Enhanced sharded FAISS index with config and metrics."""

    def __init__(
        self,
        config: EmbeddingConfig | None = None,
        db_dir: str | None = None,
        model_name: str | None = None,
        shard_size: int | None = None,
    ) -> None:
        """
        Initialize the embedding index.

        Args:
            config: Optional configuration object (defaults to global config)
            db_dir: Override database directory
            model_name: Override model name
            shard_size: Override shard size
        """
        # Load configuration
        self.config = config or get_config()

        # Apply overrides
        self.db_dir = db_dir or self.config.db_dir
        self.model_name = model_name or self.config.model_name
        self.shard_size = shard_size or self.config.shard_size

        # Initialize components
        self.model = self._load_model()
        self.indices: list[faiss.Index] = []
        self.metadata: list[list[dict[str, Any]]] = []
        self.lock = threading.Lock()
        self._refresh_thread: threading.Thread | None = None
        self._refresh_stop = threading.Event()

        # Metrics collector
        self.metrics = get_metrics_collector()

        # Create directory and load existing shards
        os.makedirs(self.db_dir, exist_ok=True)
        self._load()

        # Start periodic refresh if enabled
        if self.config.enable_periodic_refresh:
            self.start_periodic_refresh(self.config.refresh_interval)

        # Update initial metrics
        self._update_metrics()

    def _load_model(self) -> SentenceTransformer:
        """Load the sentence transformer model."""
        logger.info(f"Loading embedding model: {self.model_name}")
        kwargs = {}
        if self.config.model_cache_dir:
            kwargs["cache_folder"] = self.config.model_cache_dir
        return SentenceTransformer(self.model_name, **kwargs)

    def _create_index(self, dimension: int) -> faiss.Index:
        """Create a new FAISS index based on configuration."""
        if self.config.index_type == "IndexFlatIP":
            return faiss.IndexFlatIP(dimension)
        elif self.config.index_type == "IndexFlatL2":
            return faiss.IndexFlatL2(dimension)
        else:
            raise ValueError(f"Unknown index type: {self.config.index_type}")

    def _load(self) -> None:
        """Load existing shards from disk if available."""
        shard_paths = sorted(glob.glob(os.path.join(self.db_dir, "shard_*.faiss")))
        logger.info(f"Found {len(shard_paths)} existing shards")

        for path in shard_paths:
            try:
                idx = faiss.read_index(path)
                base = os.path.splitext(os.path.basename(path))[0]
                meta_path = os.path.join(self.db_dir, f"{base}.pkl")

                if os.path.exists(meta_path):
                    with open(meta_path, "rb") as f:
                        meta = pickle.load(f)
                else:
                    logger.warning(
                        f"Metadata not found for {path}, creating empty metadata"
                    )
                    meta = []

                self.indices.append(idx)
                self.metadata.append(meta)
                logger.debug(f"Loaded shard {base} with {idx.ntotal} vectors")

            except Exception as e:
                logger.error(f"Failed to load shard {path}: {e}")
                continue

    def _get_embedding_dimension(self, has_figure: bool = False) -> int:
        """Calculate total embedding dimension."""
        text_dim = self.model.get_sentence_embedding_dimension()
        if has_figure and self.config.enable_multimodal:
            return text_dim + self.config.figure_embedding_dim
        return text_dim

    def _get_or_create_shard(self, dimension: int) -> tuple[faiss.Index, int]:
        """Get existing compatible shard or create new one."""
        # Check if last shard is compatible and has space
        if self.indices:
            last_idx = self.indices[-1]
            if last_idx.d == dimension and last_idx.ntotal < self.shard_size:
                return last_idx, len(self.indices) - 1

        # Create new shard
        logger.info(f"Creating new shard with dimension {dimension}")
        index = self._create_index(dimension)
        self.indices.append(index)
        self.metadata.append([])
        return index, len(self.indices) - 1

    def add_records(self, records: list[dict[str, Any]]) -> None:
        """Add new records with text and optional figure features."""
        if not records:
            return

        with self.lock:
            # Group records by dimension
            text_only_records = []
            multimodal_records = []

            for rec in records:
                if rec.get("figure") is not None and self.config.enable_multimodal:
                    multimodal_records.append(rec)
                else:
                    text_only_records.append(rec)

            # Process text-only records
            if text_only_records:
                self._add_record_batch(text_only_records, has_figure=False)

            # Process multimodal records
            if multimodal_records:
                self._add_record_batch(multimodal_records, has_figure=True)

            # Update metrics
            self._update_metrics()

    def _add_record_batch(
        self, records: list[dict[str, Any]], has_figure: bool
    ) -> None:
        """Add a batch of records with same dimension."""
        # Prepare embeddings
        texts = [rec.get("text", "") for rec in records]
        text_embeddings = self.model.encode(
            texts,
            normalize_embeddings=self.config.normalize_embeddings,
            batch_size=self.config.embedding_batch_size,
            show_progress_bar=False,
        )

        # Add figure embeddings if present
        if has_figure:
            embeddings = []
            for i, rec in enumerate(records):
                text_emb = text_embeddings[i]
                fig_emb = rec.get("figure", np.zeros(self.config.figure_embedding_dim))

                if self.config.concatenation_strategy == "simple":
                    combined = np.concatenate([text_emb, fig_emb])
                else:
                    # Future: implement weighted concatenation
                    combined = np.concatenate([text_emb, fig_emb])

                embeddings.append(combined)
            embeddings = np.array(embeddings, dtype="float32")
        else:
            embeddings = text_embeddings.astype("float32")

        # Get appropriate shard
        dimension = embeddings.shape[1]
        shard, shard_idx = self._get_or_create_shard(dimension)

        # Add in batches to respect shard size
        for i in range(0, len(embeddings), self.shard_size - shard.ntotal):
            batch_end = min(i + self.shard_size - shard.ntotal, len(embeddings))
            batch_embeddings = embeddings[i:batch_end]
            batch_records = records[i:batch_end]

            shard.add(batch_embeddings)
            self.metadata[shard_idx].extend(batch_records)

            # Get new shard if needed
            if batch_end < len(embeddings):
                shard, shard_idx = self._get_or_create_shard(dimension)

    def search(
        self, query: str, top_k: int = 5, figure_vec: np.ndarray | None = None
    ) -> list[dict[str, Any]]:
        """Search all shards and return top results with metrics tracking."""
        # Start timing
        with QueryTimer(self.metrics, query, len(self.indices)) as timer:
            try:
                # Prepare query embedding
                q_emb = self.model.encode(
                    query, normalize_embeddings=self.config.normalize_embeddings
                ).astype("float32")

                # Add figure embedding if provided
                if figure_vec is not None and self.config.enable_multimodal:
                    q_emb = np.concatenate([q_emb, figure_vec]).astype("float32")

                q_emb = q_emb.reshape(1, -1)

                # Search across shards
                results: list[dict[str, Any]] = []

                with self.lock:
                    for idx, meta in zip(self.indices, self.metadata, strict=False):
                        if idx.ntotal == 0:
                            continue

                        # Skip incompatible shards
                        if idx.d != q_emb.shape[1]:
                            logger.debug(
                                f"Skipping shard with dimension {idx.d} (query dim: {q_emb.shape[1]})"
                            )
                            continue

                        # Search this shard
                        D, I = idx.search(q_emb, min(top_k, idx.ntotal))

                        for score, i in zip(D[0], I[0], strict=False):
                            if i >= 0:  # Valid result
                                rec = meta[i].copy()
                                rec["score"] = float(score)
                                results.append(rec)

                # Sort by score
                results.sort(key=lambda x: x.get("score", 0), reverse=True)
                final_results = results[:top_k]

                # Update timer with results
                timer.set_results(len(final_results))

                # Log slow queries
                if self.config.log_slow_queries and timer.start_time:
                    latency = (time.time() - timer.start_time) * 1000
                    if latency > self.config.slow_query_threshold * 1000:
                        logger.warning(f"Slow query ({latency:.0f}ms): {query[:100]}")

                return final_results

            except Exception as e:
                logger.error(f"Search failed: {e}")
                raise

    def save(self) -> None:
        """Persist indices and metadata to disk."""
        with self.lock:
            for shard_id, (idx, meta) in enumerate(
                zip(self.indices, self.metadata, strict=False)
            ):
                if idx.ntotal == 0:
                    logger.debug(f"Skipping empty shard {shard_id}")
                    continue

                try:
                    faiss_path = os.path.join(self.db_dir, f"shard_{shard_id}.faiss")
                    meta_path = os.path.join(self.db_dir, f"shard_{shard_id}.pkl")

                    faiss.write_index(idx, faiss_path)
                    with open(meta_path, "wb") as f:
                        pickle.dump(meta, f)

                    logger.debug(f"Saved shard {shard_id} with {idx.ntotal} vectors")

                except Exception as e:
                    logger.error(f"Failed to save shard {shard_id}: {e}")

    def start_periodic_refresh(self, interval: int) -> None:
        """Start periodic refresh thread."""

        def _refresh_loop():
            while not self._refresh_stop.wait(interval):
                try:
                    logger.info("Starting periodic refresh...")
                    self.refresh()
                    self.metrics.record_refresh()
                except Exception as e:
                    logger.error(f"Periodic refresh failed: {e}")

        if self._refresh_thread is None or not self._refresh_thread.is_alive():
            self._refresh_thread = threading.Thread(
                target=_refresh_loop, daemon=True, name="EmbeddingIndexRefresh"
            )
            self._refresh_thread.start()
            logger.info(f"Started periodic refresh with interval {interval}s")

    def refresh(self) -> None:
        """Refresh index with new data (implement based on your data sources)."""
        # This is a placeholder - implement based on your specific needs
        # For example: fetch new papers from PubMed, process them, add to index
        logger.info("Refresh called - implement based on data sources")
        self.save()  # Save after refresh

    def _update_metrics(self) -> None:
        """Update index metrics."""
        total_embeddings = sum(idx.ntotal for idx in self.indices)
        total_shards = len(self.indices)

        # Estimate memory usage
        memory_usage_mb = 0.0
        for idx in self.indices:
            if hasattr(idx, "d") and hasattr(idx, "ntotal"):
                # Rough estimate: dimension * vectors * 4 bytes per float
                memory_usage_mb += (idx.d * idx.ntotal * 4) / (1024 * 1024)

        # Add Python object overhead
        process = psutil.Process()
        memory_usage_mb = process.memory_info().rss / (1024 * 1024)

        self.metrics.update_index_metrics(
            total_embeddings=total_embeddings,
            total_shards=total_shards,
            memory_usage_mb=memory_usage_mb,
        )

    def get_stats(self) -> dict[str, Any]:
        """Get current index statistics."""
        with self.lock:
            stats = {
                "total_shards": len(self.indices),
                "total_embeddings": sum(idx.ntotal for idx in self.indices),
                "shard_details": [],
            }

            for i, (idx, meta) in enumerate(
                zip(self.indices, self.metadata, strict=False)
            ):
                stats["shard_details"].append(
                    {
                        "shard_id": i,
                        "dimension": idx.d if hasattr(idx, "d") else 0,
                        "vectors": idx.ntotal if hasattr(idx, "ntotal") else 0,
                        "metadata_entries": len(meta),
                    }
                )

            return stats

    def shutdown(self) -> None:
        """Gracefully shutdown the index."""
        logger.info("Shutting down embedding index...")

        # Stop refresh thread
        self._refresh_stop.set()
        if self._refresh_thread and self._refresh_thread.is_alive():
            self._refresh_thread.join(timeout=5)

        # Save final state
        self.save()

        # Save metrics snapshot
        self.metrics.save_to_file(
            os.path.join(self.db_dir, "..", "metrics", "final_metrics.json")
        )

        logger.info("Embedding index shutdown complete")


# Example usage
if __name__ == "__main__":
    # Initialize with custom config
    from .embedding_config import EmbeddingConfig

    config = EmbeddingConfig(
        model_name="all-MiniLM-L6-v2",
        shard_size=1000,
        enable_metrics=True,
        log_slow_queries=True,
        slow_query_threshold=0.1,
    )

    index = EmbeddingIndex(config=config)

    # Add some test records
    test_records = [
        {"id": "1", "text": "Deep learning for brain imaging analysis"},
        {"id": "2", "text": "Functional connectivity in resting state fMRI"},
        {"id": "3", "text": "Multimodal neuroimaging data fusion techniques"},
    ]

    index.add_records(test_records)

    # Search
    results = index.search("brain connectivity analysis", top_k=2)
    for res in results:
        print(
            f"ID: {res['id']}, Score: {res['score']:.3f}, Text: {res['text'][:50]}..."
        )

    # Get stats
    print("\nIndex Statistics:")
    print(index.get_stats())

    # Get metrics
    print("\nMetrics Summary:")
    print(index.metrics.get_summary())

    # Shutdown
    index.shutdown()
