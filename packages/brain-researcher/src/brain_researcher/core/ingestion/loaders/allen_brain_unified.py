"""Unified loader for Allen Human Brain Atlas data."""

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from ..api.allen_client import AllenBrainClient

logger = logging.getLogger(__name__)


def _cache_root() -> Path:
    base = Path(os.getenv("XDG_CACHE_HOME", str(Path.home() / ".cache"))).expanduser()
    return base / "brain_researcher"


def _default_cache_dir(name: str) -> Path:
    return _cache_root() / name


class AllenBrainUnifiedLoader:
    """Loader for Allen Brain Atlas data."""

    def __init__(self, cache_dir: str | None = None):
        """Initialize Allen Brain loader.

        Args:
            cache_dir: Directory for caching processed data
        """
        cache_dir = cache_dir or str(_default_cache_dir("allen_loader_cache"))
        preferred_cache = Path(cache_dir).expanduser()
        try:
            preferred_cache.mkdir(parents=True, exist_ok=True)
            self.cache_dir = preferred_cache
        except Exception as exc:  # pragma: no cover
            fallback_root = _cache_root()
            try:
                fallback_root.mkdir(parents=True, exist_ok=True)
            except Exception:
                fallback_root = Path(tempfile.gettempdir()) / "brain_researcher"
                fallback_root.mkdir(parents=True, exist_ok=True)
            fallback = Path(
                tempfile.mkdtemp(prefix="allen_loader_cache_", dir=str(fallback_root))
            )
            logger.warning(
                "Allen loader cache dir %s not writable (%s); using %s",
                preferred_cache,
                exc,
                fallback,
            )
            self.cache_dir = fallback

        self.client = AllenBrainClient()

        self.donors = []
        self.structures = []
        self.expression_data = {}
        self.connectivity_data = {}

    def load_atlas_hierarchy(
        self, structure_ids: list[int] | None = None
    ) -> dict[str, Any]:
        """Load the Allen CCFv3 atlas hierarchy only.

        This is the dedicated atlas-only entry point used by the BR-KG
        ingest command when callers want a region hierarchy without loading
        expression or connectivity data.
        """
        structures = self.client.get_structures()
        if structure_ids is not None:
            selected_ids = set(structure_ids)
            structures = [
                struct
                for struct in structures
                if struct.get("id") in selected_ids
                or str(struct.get("id")) in selected_ids
            ]

        self.structures = structures
        return {
            "atlas": "AllenCCFv3",
            "structures_count": len(structures),
            "structure_ids": [struct.get("id") for struct in structures],
            "structures": structures,
        }

    def load_gene_expression(
        self, gene_symbols: list[str] | None = None, donors: list[str] | None = None
    ) -> dict[str, Any]:
        """Load gene expression data.

        Args:
            gene_symbols: List of genes to load (default: common genes)
            donors: List of donor IDs (default: all donors)

        Returns:
            Expression data dictionary
        """
        # Default genes if not specified
        if gene_symbols is None:
            gene_symbols = [
                "FOXP2",  # Language/speech
                "BDNF",  # Neuroplasticity
                "DRD2",  # Dopamine receptor
                "HTR2A",  # Serotonin receptor
                "GRIN1",  # NMDA receptor
                "SLC6A4",  # Serotonin transporter
                "COMT",  # Catechol-O-methyltransferase
                "APOE",  # Alzheimer's risk
                "MAPT",  # Tau protein
                "APP",  # Amyloid precursor
            ]

        # Get available donors
        self.donors = self.client.get_donors()

        if donors:
            # Filter to requested donors
            self.donors = [d for d in self.donors if d["id"] in donors]

        logger.info(
            f"Loading expression for {len(gene_symbols)} genes from {len(self.donors)} donors"
        )

        # Load expression for each donor
        all_expression = {}

        for donor in self.donors:
            donor_id = donor["id"]

            # Check cache
            cache_file = self.cache_dir / f"expression_{donor_id}.json"
            if cache_file.exists():
                with open(cache_file) as f:
                    donor_expression = json.load(f)
            else:
                # Load from API
                donor_expression = self.client.get_expression_data(
                    donor_id, gene_symbols
                )

                # Process and normalize
                donor_expression = self._process_expression(donor_expression)

                # Cache processed data
                with open(cache_file, "w") as f:
                    json.dump(donor_expression, f)

            all_expression[donor_id] = donor_expression

        self.expression_data = all_expression

        # Calculate summary statistics
        stats = self._calculate_expression_stats(all_expression)

        return {
            "donors": len(self.donors),
            "genes": gene_symbols,
            "expression": all_expression,
            "statistics": stats,
        }

    def load_connectivity(
        self, structure_ids: list[int] | None = None
    ) -> dict[str, Any]:
        """Load structural connectivity data.

        Args:
            structure_ids: List of structure IDs (default: major structures)

        Returns:
            Connectivity data dictionary
        """
        # Get structures
        self.structures = self.client.get_structures()

        # Default to major structures if not specified
        if structure_ids is None:
            # Filter to major cortical and subcortical structures
            major_structures = [
                s
                for s in self.structures
                if s.get("parent_structure_id") is None
                or s.get("parent_structure_id") == 4000  # Cerebral cortex
            ]
            structure_ids = [s["id"] for s in major_structures[:20]]

        logger.info(f"Loading connectivity for {len(structure_ids)} structures")

        # Load connectivity for each structure
        connectivity = {}

        for struct_id in structure_ids:
            # Check cache
            cache_file = self.cache_dir / f"connectivity_{struct_id}.json"
            if cache_file.exists():
                with open(cache_file) as f:
                    struct_conn = json.load(f)
            else:
                # Load from API
                struct_conn = self.client.get_connectivity(struct_id)

                # Process connectivity
                struct_conn = self._process_connectivity(struct_conn)

                # Cache processed data
                with open(cache_file, "w") as f:
                    json.dump(struct_conn, f)

            connectivity[struct_id] = struct_conn

        self.connectivity_data = connectivity

        # Build connectivity matrix
        conn_matrix = self._build_connectivity_matrix(connectivity)

        return {
            "structures": len(structure_ids),
            "connectivity": connectivity,
            "matrix": conn_matrix,
        }

    def _process_expression(self, expression_data: dict[str, Any]) -> dict[str, Any]:
        """Process and normalize expression data.

        Args:
            expression_data: Raw expression data

        Returns:
            Processed expression data
        """
        if "expression" not in expression_data:
            return expression_data

        # Group by structure
        by_structure = {}

        for item in expression_data["expression"]:
            struct_id = item.get("structure_id")
            if struct_id not in by_structure:
                by_structure[struct_id] = {
                    "structure_name": item.get("structure_name"),
                    "genes": {},
                }

            gene = item.get("gene")
            if gene:
                by_structure[struct_id]["genes"][gene] = item.get("expression_level", 0)

        # Normalize expression values (z-score)
        all_values = []
        for struct in by_structure.values():
            all_values.extend(struct["genes"].values())

        if all_values:
            mean_val = np.mean(all_values)
            std_val = np.std(all_values)

            if std_val > 0:
                for struct in by_structure.values():
                    for gene in struct["genes"]:
                        struct["genes"][gene] = (
                            struct["genes"][gene] - mean_val
                        ) / std_val

        expression_data["by_structure"] = by_structure
        return expression_data

    def _process_connectivity(
        self, connectivity_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Process connectivity data.

        Args:
            connectivity_data: Raw connectivity data

        Returns:
            Processed connectivity data
        """
        # Extract projection strengths
        projections = connectivity_data.get("projections", [])

        connections = {}
        for proj in projections:
            target_id = proj.get("structure_id")
            if target_id:
                # Calculate connection strength (simplified)
                strength = proj.get("normalized_projection_volume", 0)
                connections[target_id] = strength

        connectivity_data["connections"] = connections
        return connectivity_data

    def _calculate_expression_stats(
        self, expression_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Calculate expression statistics across donors.

        Args:
            expression_data: Expression data by donor

        Returns:
            Statistics dictionary
        """
        # Aggregate expression across donors
        gene_expression = {}
        structure_expression = {}

        for _donor_id, donor_data in expression_data.items():
            if "by_structure" in donor_data:
                for struct_id, struct_data in donor_data["by_structure"].items():
                    if struct_id not in structure_expression:
                        structure_expression[struct_id] = []

                    for gene, expr in struct_data["genes"].items():
                        if gene not in gene_expression:
                            gene_expression[gene] = []
                        gene_expression[gene].append(expr)
                        structure_expression[struct_id].append(expr)

        # Calculate statistics
        gene_stats = {}
        for gene, values in gene_expression.items():
            if values:
                gene_stats[gene] = {
                    "mean": float(np.mean(values)),
                    "std": float(np.std(values)),
                    "min": float(np.min(values)),
                    "max": float(np.max(values)),
                }

        structure_stats = {}
        for struct_id, values in structure_expression.items():
            if values:
                structure_stats[struct_id] = {
                    "mean": float(np.mean(values)),
                    "std": float(np.std(values)),
                }

        return {
            "gene_stats": gene_stats,
            "structure_stats": structure_stats,
            "total_measurements": sum(len(v) for v in gene_expression.values()),
        }

    def _build_connectivity_matrix(
        self, connectivity_data: dict[int, dict]
    ) -> np.ndarray:
        """Build connectivity matrix from pairwise connections.

        Args:
            connectivity_data: Connectivity by structure

        Returns:
            Connectivity matrix
        """
        structure_ids = list(connectivity_data.keys())
        n = len(structure_ids)

        # Initialize matrix
        matrix = np.zeros((n, n))

        # Fill matrix
        for i, source_id in enumerate(structure_ids):
            connections = connectivity_data[source_id].get("connections", {})

            for j, target_id in enumerate(structure_ids):
                if target_id in connections:
                    matrix[i, j] = connections[target_id]

        # Make symmetric (average forward and backward connections)
        matrix = (matrix + matrix.T) / 2

        return matrix

    def map_allen_to_mni(self, allen_coords: list[float]) -> list[float]:
        """Map Allen atlas coordinates to MNI space.

        Args:
            allen_coords: [x, y, z] in Allen space

        Returns:
            [x, y, z] in MNI space
        """
        # This is a simplified transformation
        # Actual transformation would use the Allen-to-MNI registration

        # Allen space is in micrometers, MNI is in mm
        # Also need to apply affine transform

        x, y, z = allen_coords

        # Convert from micrometers to mm
        x_mm = x / 1000
        y_mm = y / 1000
        z_mm = z / 1000

        # Apply approximate transform (these values are illustrative)
        x_mni = x_mm * 0.95 - 45
        y_mni = y_mm * 0.95 - 60
        z_mni = z_mm * 0.95 - 50

        return [x_mni, y_mni, z_mni]

    def export_for_kg(self) -> dict[str, Any]:
        """Export data formatted for knowledge graph.

        Returns:
            KG-ready data
        """
        nodes = []
        edges = []
        atlas_id = "atlas:allenccfv3"
        template_space_id = "space:allenccfv3"

        nodes.append(
            {
                "id": atlas_id,
                "type": "Atlas",
                "properties": {
                    "name": "Allen Common Coordinate Framework v3",
                    "short_name": "Allen CCFv3",
                    "atlas": "AllenCCFv3",
                    "atlas_slug": "allenccfv3",
                    "space": "AllenCCFv3",
                    "species": "mouse",
                    "source": "Allen Brain Atlas",
                },
            }
        )
        nodes.append(
            {
                "id": template_space_id,
                "type": "TemplateSpace",
                "properties": {
                    "name": "Allen CCFv3",
                    "atlas": "AllenCCFv3",
                    "atlas_slug": "allenccfv3",
                    "space": "AllenCCFv3",
                    "species": "mouse",
                    "source": "Allen Brain Atlas",
                },
            }
        )
        edges.append(
            {
                "source": atlas_id,
                "target": template_space_id,
                "type": "IN_SPACE",
                "properties": {
                    "source": "Allen Brain Atlas",
                    "atlas": "AllenCCFv3",
                },
            }
        )

        # Create structure nodes
        struct_map = {}
        for struct in self.structures:
            structure_id = struct["id"]
            node_id = f"ccfv3:{structure_id}"
            struct_map[str(structure_id)] = node_id
            struct_map[structure_id] = node_id

            nodes.append(
                {
                    "id": node_id,
                    "type": "BrainRegion",
                    "properties": {
                        "name": struct["name"],
                        "abbreviation": struct.get("acronym", ""),
                        "acronym": struct.get("acronym", ""),
                        "atlas": "AllenCCFv3",
                        "atlas_slug": "allenccfv3",
                        "label_index": structure_id,
                        "structure_id": structure_id,
                        "parent_structure_id": struct.get("parent_structure_id"),
                        "graph_order": struct.get("graph_order"),
                        "depth": struct.get("depth"),
                        "structure_id_path": struct.get("structure_id_path"),
                        "space": "AllenCCFv3",
                        "species": "mouse",
                        "source": "Allen Brain Atlas",
                    },
                }
            )
            edges.append(
                {
                    "source": atlas_id,
                    "target": node_id,
                    "type": "HAS_REGION",
                    "properties": {
                        "source": "Allen Brain Atlas",
                        "atlas": "AllenCCFv3",
                    },
                }
            )

            # Add hierarchy edges
            if struct.get("parent_structure_id") is not None:
                parent_id = f"ccfv3:{struct['parent_structure_id']}"
                edges.append(
                    {
                        "source": node_id,
                        "target": parent_id,
                        "type": "PART_OF",
                        "properties": {
                            "source": "Allen CCFv3",
                            "atlas": "AllenCCFv3",
                            "hierarchy_type": "anatomical",
                        },
                    }
                )

        # Create gene expression nodes
        for donor_id, donor_data in self.expression_data.items():
            if "by_structure" in donor_data:
                for struct_id, struct_expr in donor_data["by_structure"].items():
                    for gene, expr_value in struct_expr["genes"].items():
                        expr_id = f"expr_{donor_id}_{struct_id}_{gene}"

                        nodes.append(
                            {
                                "id": expr_id,
                                "type": "GeneExpression",
                                "properties": {
                                    "gene": gene,
                                    "donor": donor_id,
                                    "expression_level": expr_value,
                                },
                            }
                        )

                        # Link to structure
                        struct_node_id = struct_map.get(struct_id) or struct_map.get(
                            str(struct_id)
                        )
                        if struct_node_id:
                            edges.append(
                                {
                                    "source": expr_id,
                                    "target": struct_node_id,
                                    "type": "EXPRESSED_IN",
                                }
                            )

        # Create connectivity edges
        for source_id, conn_data in self.connectivity_data.items():
            source_node_id = struct_map.get(source_id) or struct_map.get(str(source_id))
            if source_node_id:
                for target_id, strength in conn_data.get("connections", {}).items():
                    target_node_id = struct_map.get(target_id) or struct_map.get(
                        str(target_id)
                    )
                    if target_node_id and strength > 0:
                        edges.append(
                            {
                                "source": source_node_id,
                                "target": target_node_id,
                                "type": "CONNECTED_TO",
                                "properties": {"strength": strength},
                            }
                        )

        return {
            "nodes": nodes,
            "edges": edges,
            "metadata": {
                "donors": len(self.donors),
                "structures": len(self.structures),
                "atlas": "AllenCCFv3",
                "genes": len(
                    {
                        g
                        for d in self.expression_data.values()
                        for s in d.get("by_structure", {}).values()
                        for g in s["genes"].keys()
                    }
                ),
            },
        }
