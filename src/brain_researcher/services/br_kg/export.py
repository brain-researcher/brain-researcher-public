"""
Data export functionality for BR-KG.
Implements KG-014: Data Export Functionality
"""

import csv
import json
import logging
import xml.etree.ElementTree as ET
from collections.abc import Generator
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from io import StringIO
from typing import IO

logger = logging.getLogger(__name__)


class ExportFormat(Enum):
    """Supported export formats."""

    JSON = "json"
    NDJSON = "ndjson"
    CSV = "csv"
    GRAPHML = "graphml"
    CYPHER = "cypher"
    GEXF = "gexf"  # Gephi format


@dataclass
class ExportConfig:
    """Configuration for data export."""

    format: ExportFormat
    include_nodes: bool = True
    include_edges: bool = True
    node_types: list[str] | None = None
    edge_types: list[str] | None = None
    max_nodes: int | None = None
    max_edges: int | None = None
    stream: bool = False
    include_metadata: bool = True


class DataExporter:
    """Export graph data in multiple formats."""

    def __init__(self, db):
        """Initialize exporter with database."""
        self.db = db

    def export(self, config: ExportConfig, output: IO | None = None) -> str | None:
        """
        Export data according to configuration.

        Args:
            config: Export configuration
            output: Optional output stream

        Returns:
            Exported data as string if no output stream provided
        """
        if config.format == ExportFormat.JSON:
            return self._export_json(config, output)
        elif config.format == ExportFormat.NDJSON:
            return self._export_ndjson(config, output)
        elif config.format == ExportFormat.CSV:
            return self._export_csv(config, output)
        elif config.format == ExportFormat.GRAPHML:
            return self._export_graphml(config, output)
        elif config.format == ExportFormat.CYPHER:
            return self._export_cypher(config, output)
        elif config.format == ExportFormat.GEXF:
            return self._export_gexf(config, output)
        else:
            raise ValueError(f"Unsupported format: {config.format}")

    def _export_json(self, config: ExportConfig, output: IO | None) -> str | None:
        """Export as JSON."""
        data = {
            "metadata": (
                {
                    "exported_at": datetime.now().isoformat(),
                    "format": "json",
                    "version": "1.0",
                }
                if config.include_metadata
                else {}
            ),
            "nodes": [],
            "edges": [],
        }

        # Export nodes
        if config.include_nodes:
            node_count = 0
            for node_type in config.node_types or [
                "Concept",
                "Task",
                "Region",
                "Dataset",
                "Publication",
            ]:
                for node_id, props in self.db.find_nodes(node_type, None):
                    if config.max_nodes and node_count >= config.max_nodes:
                        break

                    data["nodes"].append(
                        {"id": node_id, "type": node_type, "properties": props}
                    )
                    node_count += 1

        # Export edges
        if config.include_edges:
            edge_count = 0
            for source, target, props in self.db.find_relationships(None, None, None):
                if config.max_edges and edge_count >= config.max_edges:
                    break

                edge_type = props.get("type", "UNKNOWN")
                if config.edge_types and edge_type not in config.edge_types:
                    continue

                data["edges"].append(
                    {
                        "source": source,
                        "target": target,
                        "type": edge_type,
                        "properties": {k: v for k, v in props.items() if k != "type"},
                    }
                )
                edge_count += 1

        # Output
        json_str = json.dumps(data, indent=2, default=str)

        if output:
            output.write(json_str)
            return None
        return json_str

    def _export_ndjson(self, config: ExportConfig, output: IO | None) -> str | None:
        """Export as NDJSON (newline-delimited JSON)."""
        lines = []

        # Export nodes
        if config.include_nodes:
            node_count = 0
            for node_type in config.node_types or [
                "Concept",
                "Task",
                "Region",
                "Dataset",
                "Publication",
            ]:
                for node_id, props in self.db.find_nodes(node_type, None):
                    if config.max_nodes and node_count >= config.max_nodes:
                        break

                    entity = {"type": node_type, "id": node_id, **props}

                    line = json.dumps(entity, default=str)
                    if output:
                        output.write(line + "\n")
                    else:
                        lines.append(line)
                    node_count += 1

        # Export edges
        if config.include_edges:
            edge_count = 0
            for source, target, props in self.db.find_relationships(None, None, None):
                if config.max_edges and edge_count >= config.max_edges:
                    break

                edge_type = props.get("type", "UNKNOWN")
                if config.edge_types and edge_type not in config.edge_types:
                    continue

                entity = {
                    "type": edge_type,
                    "source_id": source,
                    "target_id": target,
                    **{k: v for k, v in props.items() if k != "type"},
                }

                line = json.dumps(entity, default=str)
                if output:
                    output.write(line + "\n")
                else:
                    lines.append(line)
                edge_count += 1

        if not output:
            return "\n".join(lines)
        return None

    def _export_csv(self, config: ExportConfig, output: IO | None) -> str | None:
        """Export as CSV (separate files for nodes and edges)."""
        csv_data = {}

        # Export nodes
        if config.include_nodes:
            node_buffer = StringIO()
            node_writer = None
            node_count = 0

            for node_type in config.node_types or [
                "Concept",
                "Task",
                "Region",
                "Dataset",
                "Publication",
            ]:
                for node_id, props in self.db.find_nodes(node_type, None):
                    if config.max_nodes and node_count >= config.max_nodes:
                        break

                    row = {"id": node_id, "type": node_type, **props}

                    if node_writer is None:
                        # Create writer with headers from first row
                        node_writer = csv.DictWriter(
                            node_buffer,
                            fieldnames=list(row.keys()),
                            extrasaction="ignore",
                        )
                        node_writer.writeheader()

                    node_writer.writerow(row)
                    node_count += 1

            csv_data["nodes"] = node_buffer.getvalue()

        # Export edges
        if config.include_edges:
            edge_buffer = StringIO()
            edge_writer = None
            edge_count = 0

            for source, target, props in self.db.find_relationships(None, None, None):
                if config.max_edges and edge_count >= config.max_edges:
                    break

                edge_type = props.get("type", "UNKNOWN")
                if config.edge_types and edge_type not in config.edge_types:
                    continue

                row = {
                    "source": source,
                    "target": target,
                    "type": edge_type,
                    **{k: v for k, v in props.items() if k != "type"},
                }

                if edge_writer is None:
                    edge_writer = csv.DictWriter(
                        edge_buffer, fieldnames=list(row.keys()), extrasaction="ignore"
                    )
                    edge_writer.writeheader()

                edge_writer.writerow(row)
                edge_count += 1

            csv_data["edges"] = edge_buffer.getvalue()

        # Combine or return
        if output:
            if config.include_nodes:
                output.write("=== NODES ===\n")
                output.write(csv_data.get("nodes", ""))
            if config.include_edges:
                output.write("\n=== EDGES ===\n")
                output.write(csv_data.get("edges", ""))
            return None

        return json.dumps(csv_data)  # Return as JSON with separate CSV strings

    def _export_graphml(self, config: ExportConfig, output: IO | None) -> str | None:
        """Export as GraphML XML format."""
        # Create root element
        graphml = ET.Element("graphml", xmlns="http://graphml.graphdrawing.org/xmlns")

        # Add schema
        if config.include_metadata:
            for attr_name, attr_type in [
                ("name", "string"),
                ("type", "string"),
                ("confidence", "double"),
                ("source", "string"),
            ]:
                key = ET.SubElement(
                    graphml,
                    "key",
                    {
                        "id": attr_name,
                        "for": "node" if attr_name == "name" else "edge",
                        "attr.name": attr_name,
                        "attr.type": attr_type,
                    },
                )

        # Create graph element
        graph = ET.SubElement(
            graphml, "graph", {"id": "BR-KG", "edgedefault": "directed"}
        )

        # Export nodes
        if config.include_nodes:
            node_count = 0
            for node_type in config.node_types or [
                "Concept",
                "Task",
                "Region",
                "Dataset",
                "Publication",
            ]:
                for node_id, props in self.db.find_nodes(node_type, None):
                    if config.max_nodes and node_count >= config.max_nodes:
                        break

                    node = ET.SubElement(graph, "node", {"id": node_id})

                    # Add node data
                    data = ET.SubElement(node, "data", {"key": "type"})
                    data.text = node_type

                    for key, value in props.items():
                        if value is not None:
                            data = ET.SubElement(node, "data", {"key": key})
                            data.text = str(value)

                    node_count += 1

        # Export edges
        if config.include_edges:
            edge_count = 0
            for source, target, props in self.db.find_relationships(None, None, None):
                if config.max_edges and edge_count >= config.max_edges:
                    break

                edge_type = props.get("type", "UNKNOWN")
                if config.edge_types and edge_type not in config.edge_types:
                    continue

                edge = ET.SubElement(
                    graph,
                    "edge",
                    {
                        "id": f"{source}_{target}_{edge_count}",
                        "source": source,
                        "target": target,
                    },
                )

                # Add edge data
                for key, value in props.items():
                    if value is not None:
                        data = ET.SubElement(edge, "data", {"key": key})
                        data.text = str(value)

                edge_count += 1

        # Convert to string
        xml_str = ET.tostring(graphml, encoding="unicode", method="xml")

        if output:
            output.write(xml_str)
            return None
        return xml_str

    def _export_cypher(self, config: ExportConfig, output: IO | None) -> str | None:
        """Export as Cypher queries for Neo4j import."""
        queries = []

        # Add header
        if config.include_metadata:
            queries.append(f"// Exported from BR-KG on {datetime.now().isoformat()}")
            queries.append("// Cypher queries for Neo4j import\n")

        # Export nodes
        if config.include_nodes:
            queries.append("// Create nodes")
            node_count = 0

            for node_type in config.node_types or [
                "Concept",
                "Task",
                "Region",
                "Dataset",
                "Publication",
            ]:
                for node_id, props in self.db.find_nodes(node_type, None):
                    if config.max_nodes and node_count >= config.max_nodes:
                        break

                    # Build properties string
                    prop_strs = [f"id: '{node_id}'"]
                    for key, value in props.items():
                        if value is not None:
                            if isinstance(value, str):
                                prop_strs.append(f"{key}: '{value}'")
                            else:
                                prop_strs.append(f"{key}: {value}")

                    query = f"CREATE (:{node_type} {{{', '.join(prop_strs)}}});"
                    queries.append(query)
                    node_count += 1

        # Export edges
        if config.include_edges:
            queries.append("\n// Create relationships")
            edge_count = 0

            for source, target, props in self.db.find_relationships(None, None, None):
                if config.max_edges and edge_count >= config.max_edges:
                    break

                edge_type = props.get("type", "UNKNOWN")
                if config.edge_types and edge_type not in config.edge_types:
                    continue

                # Build properties string
                prop_strs = []
                for key, value in props.items():
                    if key != "type" and value is not None:
                        if isinstance(value, str):
                            prop_strs.append(f"{key}: '{value}'")
                        else:
                            prop_strs.append(f"{key}: {value}")

                props_str = f" {{{', '.join(prop_strs)}}}" if prop_strs else ""

                query = (
                    f"MATCH (s {{id: '{source}'}}), (t {{id: '{target}'}}) "
                    f"CREATE (s)-[:{edge_type}{props_str}]->(t);"
                )
                queries.append(query)
                edge_count += 1

        # Output
        cypher_str = "\n".join(queries)

        if output:
            output.write(cypher_str)
            return None
        return cypher_str

    def _export_gexf(self, config: ExportConfig, output: IO | None) -> str | None:
        """Export as GEXF format for Gephi."""
        # Similar to GraphML but using GEXF schema
        # This is a simplified version
        return self._export_graphml(config, output)  # Fallback to GraphML

    def stream_export(self, config: ExportConfig) -> Generator[str, None, None]:
        """
        Stream export data for large datasets.

        Yields:
            Chunks of exported data
        """
        if config.format == ExportFormat.NDJSON:
            # Stream nodes
            if config.include_nodes:
                for node_type in config.node_types or [
                    "Concept",
                    "Task",
                    "Region",
                    "Dataset",
                    "Publication",
                ]:
                    for node_id, props in self.db.find_nodes(node_type, None):
                        entity = {"type": node_type, "id": node_id, **props}
                        yield json.dumps(entity, default=str) + "\n"

            # Stream edges
            if config.include_edges:
                for source, target, props in self.db.find_relationships(
                    None, None, None
                ):
                    edge_type = props.get("type", "UNKNOWN")
                    if config.edge_types and edge_type not in config.edge_types:
                        continue

                    entity = {
                        "type": edge_type,
                        "source_id": source,
                        "target_id": target,
                        **{k: v for k, v in props.items() if k != "type"},
                    }
                    yield json.dumps(entity, default=str) + "\n"
        else:
            # For non-streaming formats, export all at once
            result = self.export(config)
            if result:
                yield result


# REST API endpoints
def create_export_endpoints(app):
    """Add export endpoints to Flask app."""
    from flask import Response, jsonify, request

    from brain_researcher.services.br_kg.db.bootstrap import get_db

    @app.route("/api/export", methods=["POST"])
    def export_data():
        """Export graph data."""
        data = request.get_json()

        # Parse configuration
        try:
            format_str = data.get("format", "json")
            config = ExportConfig(
                format=ExportFormat(format_str),
                include_nodes=data.get("include_nodes", True),
                include_edges=data.get("include_edges", True),
                node_types=data.get("node_types"),
                edge_types=data.get("edge_types"),
                max_nodes=data.get("max_nodes"),
                max_edges=data.get("max_edges"),
                stream=data.get("stream", False),
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

        # Export data
        db = get_db()
        exporter = DataExporter(db)

        if config.stream:
            # Stream response
            def generate():
                yield from exporter.stream_export(config)

            mimetype = {
                ExportFormat.JSON: "application/json",
                ExportFormat.NDJSON: "application/x-ndjson",
                ExportFormat.CSV: "text/csv",
                ExportFormat.GRAPHML: "application/xml",
                ExportFormat.CYPHER: "text/plain",
                ExportFormat.GEXF: "application/xml",
            }.get(config.format, "text/plain")

            return Response(generate(), mimetype=mimetype)
        else:
            # Regular response
            result = exporter.export(config)
            return Response(result, mimetype="application/json")

    @app.route("/api/export/formats", methods=["GET"])
    def get_export_formats():
        """Get available export formats."""
        formats = [
            {
                "format": f.value,
                "name": f.name,
                "description": {
                    ExportFormat.JSON: "JavaScript Object Notation",
                    ExportFormat.NDJSON: "Newline-delimited JSON",
                    ExportFormat.CSV: "Comma-separated values",
                    ExportFormat.GRAPHML: "Graph Markup Language (XML)",
                    ExportFormat.CYPHER: "Neo4j Cypher queries",
                    ExportFormat.GEXF: "Graph Exchange XML Format (Gephi)",
                }.get(f, ""),
            }
            for f in ExportFormat
        ]

        return jsonify(formats)
