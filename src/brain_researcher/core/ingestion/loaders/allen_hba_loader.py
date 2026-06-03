"""Allen Human Brain Atlas ingestion helpers.

This module exposes a lightweight ingest path that keeps BR-KG focused on
searchable metadata ("spine") while delegating bulk expression matrices to
external object storage.  The loader expects that expression data has already
been aggregated to a parcellation (e.g., Schaefer 400) and summarised as a
manifest describing each region-level expression profile.

The intent is to make it easy to swap in different normalization pipelines
without rewriting the database logic.  The heavy lifting (probe re-annotation,
per-donor normalization, region aggregation, etc.) happens upstream; here we
only hydrate the knowledge graph with:

* Genes referenced by the manifest (created lazily if missing)
* ExpressionProfile nodes, one per region/profile combination
* OF_REGION relationships linking profiles back to Region nodes
* COVERS_GENE relationships for a small set of summary statistics (Top-K genes)

Manifest format
---------------
We expect a JSON Lines (ndjson) or JSON file with entries shaped like:

```
{
  "profile_id": "expr:schaefer400-7n:v1.0:R_Vis_1",
  "region_id": "schaefer400-7n:R_Vis_1",
  "atlas": "schaefer400-7n",
  "uri": "s3://bucket/path/to/expr_schaefer400_v1.0.parquet",
  "etag": "sha256:...",  # optional but recommended
  "n_genes": 5861,
  "donors": ["10021", "12876", ...],
  "norm_pipeline": "abagen_v1.2.0",
  "top_genes": [
    {"gene_id": "ENSG00000141510", "score": 2.13, "metric": "mean_z"},
    ...
  ]
}
```

The loader is agnostic to the exact upstream tooling – as long as the manifest
matches the schema above (extra keys are ignored), it can hydrate the graph.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class AllenHBAProfile:
    """Region-level expression profile descriptor."""

    profile_id: str
    region_id: str
    atlas: str
    uri: str
    etag: Optional[str] = None
    n_genes: Optional[int] = None
    donors: List[str] = field(default_factory=list)
    norm_pipeline: Optional[str] = None
    top_genes: List[Dict[str, Any]] = field(default_factory=list)


class AllenHBALoader:
    """Helper class that keeps AHBA ingestion logic organised."""

    def __init__(
        self,
        manifest_path: Path,
        *,
        max_genes_per_region: int = 100,
    ) -> None:
        self.manifest_path = manifest_path
        self.max_genes_per_region = max_genes_per_region
        self._profiles: list[AllenHBAProfile] = []

    # ------------------------------------------------------------------
    def load_manifest(self) -> list[AllenHBAProfile]:
        """Read the manifest file once and cache the parsed records."""

        if self._profiles:
            return self._profiles

        if not self.manifest_path.exists():
            raise FileNotFoundError(f"Allen HBA manifest not found: {self.manifest_path}")

        raw = self.manifest_path.read_text(encoding="utf-8").strip()
        if not raw:
            logger.warning("Allen HBA manifest %s was empty", self.manifest_path)
            self._profiles = []
            return self._profiles

        try:
            if raw.lstrip().startswith("["):
                payload = json.loads(raw)
            else:
                payload = [json.loads(line) for line in raw.splitlines() if line.strip()]
        except json.JSONDecodeError as exc:
            raise ValueError(f"Failed to parse Allen HBA manifest {self.manifest_path}: {exc}")

        profiles: list[AllenHBAProfile] = []
        for entry in payload:
            try:
                profiles.append(
                    AllenHBAProfile(
                        profile_id=entry["profile_id"],
                        region_id=entry["region_id"],
                        atlas=entry.get("atlas", "unknown"),
                        uri=entry["uri"],
                        etag=entry.get("etag"),
                        n_genes=entry.get("n_genes"),
                        donors=list(entry.get("donors", [])),
                        norm_pipeline=entry.get("norm_pipeline"),
                        top_genes=list(entry.get("top_genes", [])),
                    )
                )
            except KeyError as exc:
                logger.warning("Skipping malformed manifest entry missing %s: %s", exc, entry)

        if not profiles:
            logger.warning("Allen HBA manifest did not yield any profiles")

        self._profiles = profiles
        return self._profiles

    # ------------------------------------------------------------------
    def iter_profiles(self) -> Iterable[AllenHBAProfile]:
        """Convenience generator over cached profiles."""

        yield from self.load_manifest()


def upsert_expression_spine(
    db,
    loader: AllenHBALoader,
    *,
    max_genes_per_region: Optional[int] = None,
) -> dict:
    """Insert ExpressionProfile nodes plus lightweight COVERS_GENE edges.

    Returns a stats dict that mirrors other loaders.
    """

    stats = {
        "profiles_created": 0,
        "profile_updates": 0,
        "genes_touched": 0,
        "covers_gene_edges": 0,
        "missing_regions": 0,
    }

    max_genes = max_genes_per_region or loader.max_genes_per_region

    for profile in loader.iter_profiles():
        region_matches = db.find_nodes("Region", {"id": profile.region_id})
        if not region_matches:
            stats["missing_regions"] += 1
            logger.debug("Skipping expression profile %s: missing region %s", profile.profile_id, profile.region_id)
            continue

        profile_props = {
            "id": profile.profile_id,
            "atlas": profile.atlas,
            "uri": profile.uri,
            "etag": profile.etag,
            "n_genes": profile.n_genes,
            "donors": profile.donors,
            "norm_pipeline": profile.norm_pipeline,
        }

        existing = db.find_nodes("ExpressionProfile", {"id": profile.profile_id})
        if existing:
            db._save_node(profile.profile_id, existing[0][1].get("labels", ["ExpressionProfile"]), profile_props)
            stats["profile_updates"] += 1
            profile_node_id = profile.profile_id
        else:
            profile_node_id = db.create_node("ExpressionProfile", profile_props)
            stats["profiles_created"] += 1

        region_node_id = region_matches[0][0]
        db.create_relationship(profile_node_id, region_node_id, "OF_REGION", {"source": "allen_hba"})

        # Seed lightweight gene summaries (Top-K per region)
        for summary in profile.top_genes[:max_genes]:
            gene_id = summary.get("gene_id") or summary.get("id")
            if not gene_id:
                continue

            # Lazy upsert gene nodes (prefer existing ones)
            gene_matches = db.find_nodes("Gene", {"id": gene_id})
            if gene_matches:
                gene_node_id = gene_matches[0][0]
            else:
                gene_node_id = db.create_node("Gene", {"id": gene_id})
                stats["genes_touched"] += 1

            rel_props = {
                "score": summary.get("score"),
                "metric": summary.get("metric", "mean_z"),
                "rank": summary.get("rank"),
                "source": "allen_hba",
            }
            if db.create_relationship(profile_node_id, gene_node_id, "COVERS_GENE", rel_props):
                stats["covers_gene_edges"] += 1

    return stats
