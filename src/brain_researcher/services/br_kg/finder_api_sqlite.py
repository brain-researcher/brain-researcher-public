"""
SQLite adapter for Finder API - provides same interface as Neo4j version
but queries SQLite database with graph data stored in relational format.
"""

import json
import sqlite3
from dataclasses import dataclass
from enum import Enum
from typing import Any


class FilterOperator(Enum):
    """Filter operators for queries"""

    EQUALS = "="
    NOT_EQUALS = "!="
    GREATER_THAN = ">"
    LESS_THAN = "<"
    GREATER_THAN_OR_EQUAL = ">="
    LESS_THAN_OR_EQUAL = "<="
    CONTAINS = "contains"
    IN = "in"


@dataclass
class Filter:
    facet: str
    value: Any
    op: str = "="


class SQLiteConnection:
    """SQLite connection wrapper that mimics Neo4j driver interface"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def run(self, query: str, **params) -> list[dict]:
        """Execute query and return results"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            cursor.execute(query, params)
            results = []
            for row in cursor.fetchall():
                results.append(dict(row))
            return results
        finally:
            conn.close()


class SQLiteFacetCounter:
    """Count facet values using SQLite database"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def count_facets(self, filters: list[Filter]) -> dict[str, dict[str, int]]:
        """Get facet counts for current filter set"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Get all dataset nodes
            cursor.execute(
                """
                SELECT properties
                FROM nodes
                WHERE labels LIKE '%Dataset%'
                   OR labels LIKE '%Study%'
                   OR labels LIKE '%Project%'
            """
            )

            datasets = []
            for row in cursor.fetchall():
                if row[0]:
                    try:
                        props = json.loads(row[0])
                        datasets.append(props)
                    except json.JSONDecodeError:
                        continue

            # Apply filters
            filtered_datasets = self._apply_filters(datasets, filters)

            # Count facets
            facets = {
                "modality": {},
                "task": {},
                "population": {},
                "scanner": {},
                "source": {},
            }

            for dataset in filtered_datasets:
                # Count modality
                modality = dataset.get("modality", "unknown")
                if modality:
                    facets["modality"][modality] = (
                        facets["modality"].get(modality, 0) + 1
                    )

                # Count task
                task = dataset.get("task", dataset.get("paradigm"))
                if task:
                    facets["task"][task] = facets["task"].get(task, 0) + 1

                # Count population
                population = dataset.get("population", "healthy")
                facets["population"][population] = (
                    facets["population"].get(population, 0) + 1
                )

                # Count scanner
                scanner = dataset.get("scanner", dataset.get("scanner_manufacturer"))
                if scanner:
                    facets["scanner"][scanner] = facets["scanner"].get(scanner, 0) + 1

                # Count source
                source = dataset.get("source", dataset.get("repository", "unknown"))
                facets["source"][source] = facets["source"].get(source, 0) + 1

            # Remove empty facets
            facets = {k: v for k, v in facets.items() if v}

            return facets

        finally:
            conn.close()

    def _apply_filters(self, datasets: list[dict], filters: list[Filter]) -> list[dict]:
        """Apply filters to dataset list"""
        if not filters:
            return datasets

        filtered = []
        for dataset in datasets:
            match = True
            for f in filters:
                if f.facet == "modality":
                    if dataset.get("modality") != f.value:
                        match = False
                        break
                elif f.facet == "task":
                    task = dataset.get("task", dataset.get("paradigm"))
                    if task != f.value:
                        match = False
                        break
                elif f.facet == "population":
                    if dataset.get("population", "healthy") != f.value:
                        match = False
                        break
                elif f.facet == "year":
                    year = dataset.get("year", dataset.get("publication_year"))
                    if year:
                        try:
                            year = int(year)
                            if f.op == ">=" and year < f.value:
                                match = False
                                break
                            elif f.op == "<=" and year > f.value:
                                match = False
                                break
                        except (ValueError, TypeError):
                            pass
                elif f.facet == "sample_size" or f.facet == "n":
                    n = dataset.get(
                        "n", dataset.get("sample_size", dataset.get("subjects"))
                    )
                    if n:
                        try:
                            n = int(n)
                            if f.op == ">=" and n < f.value:
                                match = False
                                break
                            elif f.op == "<=" and n > f.value:
                                match = False
                                break
                        except (ValueError, TypeError):
                            pass

            if match:
                filtered.append(dataset)

        return filtered


class SQLiteDatasetSearcher:
    """Search datasets using SQLite database"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def search(
        self,
        filters: list[Filter],
        sort_by: str = "relevance",
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict]:
        """Search datasets with filters"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Get all dataset nodes
            cursor.execute(
                """
                SELECT id, properties
                FROM nodes
                WHERE labels LIKE '%Dataset%'
                   OR labels LIKE '%Study%'
                   OR labels LIKE '%Project%'
            """
            )

            datasets = []
            for row in cursor.fetchall():
                if row[1]:
                    try:
                        props = json.loads(row[1])
                        props["id"] = props.get("id", row[0])
                        datasets.append(props)
                    except json.JSONDecodeError:
                        continue

            # Apply filters and track matched fields
            filtered_datasets = []
            for dataset in datasets:
                matched_fields = []
                match = True

                for f in filters:

                    if f.facet == "modality":
                        if dataset.get("modality") == f.value:
                            matched_fields.append("modality")
                        else:
                            match = False
                            break

                    elif f.facet == "task":
                        task = dataset.get("task", dataset.get("paradigm"))
                        if task == f.value:
                            matched_fields.append("task")
                        else:
                            match = False
                            break

                    elif f.facet == "population":
                        if dataset.get("population", "healthy") == f.value:
                            matched_fields.append("population")
                        else:
                            match = False
                            break

                    elif f.facet == "year":
                        year = dataset.get("year", dataset.get("publication_year"))
                        if year:
                            try:
                                year = int(year)
                                if f.op == ">=" and year >= f.value:
                                    matched_fields.append("year")
                                elif f.op == "<=" and year <= f.value:
                                    matched_fields.append("year")
                                else:
                                    match = False
                                    break
                            except (ValueError, TypeError):
                                pass

                if match or not filters:  # Include all if no filters
                    dataset["matched_fields"] = matched_fields
                    filtered_datasets.append(dataset)

            # Calculate readiness for each dataset
            for dataset in filtered_datasets:
                dataset["readiness"] = self._calculate_readiness(dataset)
                dataset["why_matched"] = self._explain_match(dataset, filters)

            # Sort results
            if sort_by == "readiness":
                filtered_datasets.sort(
                    key=lambda d: d["readiness"]["score"], reverse=True
                )
            elif sort_by == "name":
                filtered_datasets.sort(key=lambda d: d.get("name", d.get("title", "")))
            elif sort_by == "date":
                filtered_datasets.sort(key=lambda d: d.get("year", 0), reverse=True)
            # For relevance, keep original order (already sorted by match quality)

            # Apply pagination
            paginated = filtered_datasets[offset : offset + limit]

            # Format for output
            results = []
            for dataset in paginated:
                # Try to get sample size from various fields
                sample_size = (
                    dataset.get("n")
                    or dataset.get("sample_size")
                    or dataset.get("subjects")
                    or dataset.get("subject_count")
                    or 0
                )

                results.append(
                    {
                        "id": dataset.get("id", "unknown"),
                        "name": dataset.get(
                            "name", dataset.get("title", "Unnamed Dataset")
                        ),
                        "description": dataset.get(
                            "description",
                            dataset.get("abstract", dataset.get("accession", "")),
                        ),
                        "modality": dataset.get("modality", "unknown"),
                        "task": dataset.get("task", dataset.get("paradigm", "")),
                        "sample_size": sample_size,
                        "readiness": dataset["readiness"],
                        "why_matched": dataset["why_matched"],
                        "matched_fields": dataset.get("matched_fields", []),
                    }
                )

            return {"datasets": results}

        finally:
            conn.close()

    def _calculate_readiness(self, dataset: dict) -> dict:
        """Calculate dataset readiness score"""
        score = 0.0
        reasons = []

        # Check BIDS compliance
        if dataset.get("has_bids") or dataset.get("bids_version"):
            score += 0.3
            reasons.append("BIDS compliant")
        else:
            reasons.append("Not BIDS")

        # Check QC status
        qc = dataset.get("qc_status", dataset.get("quality_control"))
        if qc == "passed" or qc == "complete":
            score += 0.2
            reasons.append("QC passed")
        elif qc == "failed":
            reasons.append("QC failed")

        # Check sample size
        n = dataset.get(
            "n",
            dataset.get(
                "sample_size", dataset.get("subjects", dataset.get("subject_count", 0))
            ),
        )
        try:
            n = int(n) if n else 0
            if n >= 30:
                score += 0.3
                reasons.append(f"Good sample size (n={n})")
            elif n >= 20:
                score += 0.2
                reasons.append(f"Moderate sample (n={n})")
            elif n > 0:
                score += 0.1
                reasons.append(f"Small sample (n={n})")
        except (ValueError, TypeError):
            pass

        # Check if has derivatives/preprocessing
        if dataset.get("derivatives") or dataset.get("preprocessed"):
            score += 0.2
            reasons.append("Has derivatives")

        # Determine color based on score
        if score >= 0.8:
            color = "green"
        elif score >= 0.5:
            color = "yellow"
        else:
            color = "red"

        return {
            "score": min(score, 1.0),
            "color": color,
            "reason": ", ".join(reasons) if reasons else "No metadata available",
        }

    def _explain_match(self, dataset: dict, filters: list[Filter]) -> dict:
        """Explain why dataset matched filters"""
        explanations = {}

        for f in filters:
            if f.facet == "modality" and dataset.get("modality") == f.value:
                explanations["modality"] = f"Modality is {f.value}"
            elif f.facet == "task":
                task = dataset.get("task", dataset.get("paradigm"))
                if task == f.value:
                    explanations["task"] = f"Task is {f.value}"
            elif f.facet == "population":
                if dataset.get("population", "healthy") == f.value:
                    explanations["population"] = f"Population is {f.value}"
            elif f.facet == "year":
                year = dataset.get("year", dataset.get("publication_year"))
                if year:
                    explanations["year"] = f"Year {f.op} {f.value}"

        return explanations


class SQLiteDatasetExplainer:
    """Explain dataset details using SQLite database"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def explain(self, dataset_id: str) -> dict | None:
        """Get detailed explanation for a dataset"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Get dataset node
            cursor.execute(
                """
                SELECT id, properties
                FROM nodes
                WHERE (id = ? OR properties LIKE ?)
                  AND (labels LIKE '%Dataset%'
                       OR labels LIKE '%Study%'
                       OR labels LIKE '%Project%')
                LIMIT 1
            """,
                (dataset_id, f'%"id":"{dataset_id}"%'),
            )

            row = cursor.fetchone()
            if not row:
                return None

            dataset = json.loads(row[1]) if row[1] else {}
            dataset["id"] = dataset.get("id", row[0])

            # Get related nodes through relationships
            cursor.execute(
                """
                SELECT r.type, r.properties, n2.labels, n2.properties
                FROM relationships r
                JOIN nodes n1 ON r.start_id = n1.id OR r.end_id = n1.id
                JOIN nodes n2 ON (r.start_id = n2.id OR r.end_id = n2.id) AND n2.id != n1.id
                WHERE n1.id = ?
            """,
                (row[0],),
            )

            papers = []
            methods = []
            derivatives = []

            for rel_row in cursor.fetchall():
                rel_row[0]
                node_labels = rel_row[2]
                node_props = json.loads(rel_row[3]) if rel_row[3] else {}

                if "Publication" in node_labels or "Paper" in node_labels:
                    papers.append(
                        {
                            "id": node_props.get("pmid", node_props.get("id")),
                            "title": node_props.get("title", ""),
                            "year": node_props.get(
                                "year", node_props.get("publication_year")
                            ),
                            "citations": node_props.get("citations", 0),
                        }
                    )
                elif "Method" in node_labels or "Tool" in node_labels:
                    methods.append(
                        {
                            "id": node_props.get("id"),
                            "name": node_props.get("name", node_props.get("tool_name")),
                            "description": node_props.get("description", ""),
                        }
                    )
                elif "Derivative" in node_labels or "Output" in node_labels:
                    derivatives.append(
                        {
                            "id": node_props.get("id"),
                            "name": node_props.get("name", node_props.get("type")),
                            "type": node_props.get("type", node_props.get("format")),
                        }
                    )

            # Calculate readiness
            readiness = self._calculate_readiness(dataset)

            # Build evidence
            evidence = {
                "papers": papers[:10],  # Limit to 10 items
                "methods": methods[:10],
                "derivatives": derivatives[:10],
            }

            # Build mini graph
            graph = self._build_mini_graph(dataset, evidence)

            return {
                "id": dataset["id"],
                "name": dataset.get("name", dataset.get("title", "Unnamed Dataset")),
                "description": dataset.get("description", dataset.get("abstract", "")),
                "modality": dataset.get("modality"),
                "task": dataset.get("task", dataset.get("paradigm")),
                "sample_size": dataset.get(
                    "n", dataset.get("sample_size", dataset.get("subjects"))
                ),
                "year": dataset.get("year", dataset.get("publication_year")),
                "readiness": readiness,
                "evidence": evidence,
                "graph": graph,
                "metadata": {
                    "scanner": dataset.get(
                        "scanner", dataset.get("scanner_manufacturer")
                    ),
                    "tr": dataset.get("tr", dataset.get("repetition_time")),
                    "field_strength": dataset.get(
                        "field_strength", dataset.get("magnetic_field_strength")
                    ),
                    "voxel_size": dataset.get("voxel_size"),
                    "duration": dataset.get("duration", dataset.get("scan_duration")),
                },
            }

        finally:
            conn.close()

    def _calculate_readiness(self, dataset: dict) -> dict:
        """Calculate dataset readiness score (same as searcher)"""
        searcher = SQLiteDatasetSearcher(self.db_path)
        return searcher._calculate_readiness(dataset)

    def _build_mini_graph(self, dataset: dict, evidence: dict) -> dict:
        """Build mini graph visualization data"""
        nodes = []
        edges = []

        # Add dataset node (center)
        nodes.append(
            {
                "id": dataset["id"],
                "type": "dataset",
                "label": dataset.get("name", dataset.get("title", "Dataset")),
                "x": 400,
                "y": 300,
                "color": "#4F46E5",
            }
        )

        # Add paper nodes
        for i, paper in enumerate(
            evidence["papers"][:3]
        ):  # Limit to 3 for visualization
            node_id = f"paper_{i}"
            nodes.append(
                {
                    "id": node_id,
                    "type": "paper",
                    "label": paper.get("title", "Paper")[:30] + "...",
                    "x": 200 + i * 100,
                    "y": 150,
                    "color": "#10B981",
                }
            )
            edges.append({"source": dataset["id"], "target": node_id, "type": "cites"})

        # Add method nodes
        for i, method in enumerate(evidence["methods"][:3]):
            node_id = f"method_{i}"
            nodes.append(
                {
                    "id": node_id,
                    "type": "method",
                    "label": method.get("name", "Method"),
                    "x": 200 + i * 100,
                    "y": 450,
                    "color": "#F59E0B",
                }
            )
            edges.append({"source": dataset["id"], "target": node_id, "type": "uses"})

        # Add derivative nodes
        for i, derivative in enumerate(evidence["derivatives"][:2]):
            node_id = f"derivative_{i}"
            nodes.append(
                {
                    "id": node_id,
                    "type": "derivative",
                    "label": derivative.get("name", "Output"),
                    "x": 550 + i * 100,
                    "y": 300,
                    "color": "#EF4444",
                }
            )
            edges.append(
                {"source": dataset["id"], "target": node_id, "type": "generates"}
            )

        return {"nodes": nodes, "edges": edges}
