"""
Evidence Collection Module for the Brain Researcher Agent.

Tracks provenance, sources, parameters, versions, and citations for
reproducibility and transparency. Captures evidence from tools, datasets,
publications, and analysis steps. Supports JSON-LD export and Run Card
generation.

Relocated from ``services/agent/evidence_collection`` into the shared layer so
that lower layers (``services/tools``, ``services/br_kg``) can depend on the
evidence-collection primitives without importing from ``services/agent``. The
original agent module re-exports everything here for backward compatibility.
"""

import hashlib
import json
import logging
import platform
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


class EvidenceType(Enum):
    """Types of evidence that can be collected."""

    DATASET = "dataset"  # Dataset used (OpenNeuro, NeuroVault, etc.)
    PUBLICATION = "publication"  # Scientific publication
    TOOL = "tool"  # Tool or software used
    PARAMETER = "parameter"  # Parameter values used
    RESULT = "result"  # Analysis result
    COORDINATE = "coordinate"  # Brain coordinate
    CONCEPT = "concept"  # Cognitive concept
    FILE = "file"  # Input/output file
    API_CALL = "api_call"  # External API call
    KNOWLEDGE_GRAPH = "knowledge_graph"  # KG query or result
    USER_INPUT = "user_input"  # User-provided information
    INFERENCE = "inference"  # Inferred or derived information
    ENVIRONMENT = "environment"  # Environment and versions
    RUN = "run"  # Overall run/session metadata


class ConfidenceLevel(Enum):
    """Confidence levels for evidence."""

    HIGH = "high"  # Direct, verified evidence
    MEDIUM = "medium"  # Indirect or partially verified
    LOW = "low"  # Inferred or uncertain
    UNKNOWN = "unknown"  # Confidence not assessed


@dataclass
class Evidence:
    """Single piece of evidence."""

    evidence_id: str = field(default_factory=lambda: f"ev_{uuid4().hex[:8]}")
    type: EvidenceType = EvidenceType.RESULT
    source: str = ""  # Source of evidence (tool name, database, etc.)
    content: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "evidence_id": self.evidence_id,
            "type": self.type.value,
            "source": self.source,
            "content": self.content,
            "timestamp": self.timestamp,
            "confidence": self.confidence.value,
            "metadata": self.metadata,
        }

    def to_citation(self) -> str | None:
        """Generate a citation string if applicable."""
        if self.type == EvidenceType.PUBLICATION:
            doi = self.content.get("doi")
            title = self.content.get("title")
            authors = self.content.get("authors", [])
            year = self.content.get("year")

            if authors and year:
                author_str = authors[0] if isinstance(authors, list) else str(authors)
                if len(authors) > 1:
                    author_str += " et al."
                citation = f"{author_str} ({year})"
                if title:
                    citation += f". {title}"
                if doi:
                    citation += f" DOI: {doi}"
                return citation

        elif self.type == EvidenceType.DATASET:
            dataset_id = self.content.get("dataset_id")
            name = self.content.get("name", dataset_id)
            version = self.content.get("version")

            citation = f"Dataset: {name}"
            if version:
                citation += f" (v{version})"
            if doi := self.content.get("doi"):
                citation += f" DOI: {doi}"
            return citation

        elif self.type == EvidenceType.TOOL:
            tool_name = self.content.get("name", self.source)
            version = self.content.get("version")

            citation = f"Tool: {tool_name}"
            if version:
                citation += f" (v{version})"
            return citation

        return None


@dataclass
class EvidenceChain:
    """Chain of evidence showing derivation path."""

    chain_id: str = field(default_factory=lambda: f"chain_{uuid4().hex[:8]}")
    steps: list[Evidence] = field(default_factory=list)
    description: str = ""
    created_at: float = field(default_factory=time.time)

    def add_evidence(self, evidence: Evidence):
        """Add evidence to the chain."""
        self.steps.append(evidence)

    def get_provenance_graph(self) -> dict[str, Any]:
        """Get provenance as a graph structure."""
        nodes = []
        edges = []

        for i, step in enumerate(self.steps):
            nodes.append(
                {
                    "id": step.evidence_id,
                    "type": step.type.value,
                    "source": step.source,
                    "label": step.source or step.type.value,
                }
            )

            if i > 0:
                edges.append(
                    {
                        "from": self.steps[i - 1].evidence_id,
                        "to": step.evidence_id,
                        "label": "derives_from",
                    }
                )

        return {"nodes": nodes, "edges": edges}


class EvidenceCollector:
    """
    Collects and manages evidence throughout analysis workflows.

    Features:
    - Automatic evidence capture from tool executions
    - Provenance tracking with chains
    - Citation generation
    - Reproducibility reports
    - Evidence persistence and retrieval
    """

    def __init__(
        self,
        storage_path: Path | None = None,
        auto_persist: bool = True,
        track_parameters: bool = True,
        track_files: bool = True,
        run_metadata: dict[str, Any] | None = None,
    ):
        """
        Initialize the evidence collector.

        Args:
            storage_path: Path to store evidence (defaults to temp)
            auto_persist: Automatically save evidence to disk
            track_parameters: Track all parameter values
            track_files: Track input/output files
        """
        self.storage_path = storage_path or Path("/tmp/evidence")
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self.auto_persist = auto_persist
        self.track_parameters = track_parameters
        self.track_files = track_files

        # Evidence storage
        self.evidence: dict[str, Evidence] = {}
        self.chains: dict[str, EvidenceChain] = {}
        self.current_chain: EvidenceChain | None = None
        self.run_id: str = f"run_{uuid4().hex[:8]}"
        self.run_started_at: str = datetime.now().isoformat()
        self.run_metadata: dict[str, Any] = run_metadata or {}

        # Indices for quick lookup
        self.by_type: dict[EvidenceType, list[str]] = {}
        self.by_source: dict[str, list[str]] = {}
        self.citations: set[str] = set()

        logger.info(f"EvidenceCollector initialized (storage: {self.storage_path})")
        # Record initial environment info
        self.record_environment_versions()

    def collect(
        self,
        type: EvidenceType,
        source: str,
        content: dict[str, Any],
        confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM,
        metadata: dict[str, Any] | None = None,
    ) -> Evidence:
        """
        Collect a piece of evidence.

        Args:
            type: Type of evidence
            source: Source of the evidence
            content: Evidence content
            confidence: Confidence level
            metadata: Additional metadata

        Returns:
            The collected evidence
        """
        evidence = Evidence(
            type=type,
            source=source,
            content=content,
            confidence=confidence,
            metadata=metadata or {},
        )

        # Store evidence
        self.evidence[evidence.evidence_id] = evidence

        # Update indices
        if type not in self.by_type:
            self.by_type[type] = []
        self.by_type[type].append(evidence.evidence_id)

        if source not in self.by_source:
            self.by_source[source] = []
        self.by_source[source].append(evidence.evidence_id)

        # Add to current chain if active
        if self.current_chain:
            self.current_chain.add_evidence(evidence)

        # Generate citation if applicable
        if citation := evidence.to_citation():
            self.citations.add(citation)

        # Persist if enabled
        if self.auto_persist:
            self._persist_evidence(evidence)

        logger.debug(
            f"Collected evidence: {evidence.evidence_id} ({type.value} from {source})"
        )

        return evidence

    def collect_dataset(
        self,
        dataset_id: str,
        name: str | None = None,
        source: str = "OpenNeuro",
        doi: str | None = None,
        version: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Evidence:
        """Collect dataset evidence."""
        content = {
            "dataset_id": dataset_id,
            "name": name or dataset_id,
            "doi": doi,
            "version": version,
        }

        return self.collect(
            type=EvidenceType.DATASET,
            source=source,
            content=content,
            confidence=ConfidenceLevel.HIGH,
            metadata=metadata or {},
        )

    def collect_publication(
        self,
        doi: str | None = None,
        title: str | None = None,
        authors: list[str] | None = None,
        year: int | None = None,
        journal: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Evidence:
        """Collect publication evidence."""
        content = {
            "doi": doi,
            "title": title,
            "authors": authors or [],
            "year": year,
            "journal": journal,
        }

        return self.collect(
            type=EvidenceType.PUBLICATION,
            source="literature",
            content=content,
            confidence=ConfidenceLevel.HIGH if doi else ConfidenceLevel.MEDIUM,
            metadata=metadata or {},
        )

    def collect_tool_execution(
        self,
        tool_name: str,
        version: str | None = None,
        command: str | None = None,
        parameters: dict[str, Any] | None = None,
        execution_time: float | None = None,
        success: bool = True,
    ) -> Evidence:
        """Collect tool execution evidence."""
        content = {
            "name": tool_name,
            "version": version,
            "command": command,
            "parameters": parameters or {},
            "execution_time": execution_time,
            "success": success,
        }

        # Also track parameters separately if enabled
        if self.track_parameters and parameters:
            self.collect_parameters(tool_name, parameters)

        return self.collect(
            type=EvidenceType.TOOL,
            source=tool_name,
            content=content,
            confidence=ConfidenceLevel.HIGH,
            metadata={"execution_timestamp": time.time()},
        )

    def record_environment_versions(self) -> Evidence:
        """Capture environment and version information as evidence."""
        env = {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "system": platform.system(),
            "machine": platform.machine(),
        }
        # Try to capture project/package versions if installed
        for pkg in [
            "brain_researcher",
            "numpy",
            "pandas",
            "networkx",
        ]:
            try:
                env[f"pkg_{pkg}_version"] = importlib_metadata.version(pkg)
            except Exception:
                continue
        return self.collect(
            type=EvidenceType.ENVIRONMENT,
            source="environment",
            content=env,
            confidence=ConfidenceLevel.HIGH,
        )

    def collect_parameters(
        self, tool_name: str, parameters: dict[str, Any]
    ) -> Evidence:
        """Collect parameter evidence."""
        return self.collect(
            type=EvidenceType.PARAMETER,
            source=tool_name,
            content=parameters,
            confidence=ConfidenceLevel.HIGH,
        )

    def collect_file(
        self,
        file_path: str,
        file_type: str = "unknown",
        is_input: bool = True,
        checksum: str | None = None,
        metadata: dict[str, Any] | None = None,
        source: str | None = None,
    ) -> Evidence:
        """Collect file evidence."""
        path = Path(file_path)

        if not checksum and path.exists():
            checksum = self._compute_checksum(path)

        content = {
            "path": str(path),
            "name": path.name,
            "type": file_type,
            "is_input": is_input,
            "exists": path.exists(),
            "size": path.stat().st_size if path.exists() else None,
            "checksum": checksum,
        }

        return self.collect(
            type=EvidenceType.FILE,
            source=source or "filesystem",
            content=content,
            confidence=ConfidenceLevel.HIGH if path.exists() else ConfidenceLevel.LOW,
            metadata=metadata or {},
        )

    def collect_output_files(
        self,
        tool_name: str,
        outputs: Any,
        metadata: dict[str, Any] | None = None,
    ) -> list[Evidence]:
        """Collect output file evidence from tool outputs."""
        paths: list[tuple[str, str | None]] = []
        seen: set[str] = set()

        def _walk(value: Any, key_hint: str | None = None) -> None:
            if isinstance(value, (list, tuple, set)):
                for item in value:
                    _walk(item, key_hint=key_hint)
                return
            if isinstance(value, dict):
                for k, v in value.items():
                    _walk(v, key_hint=str(k))
                return
            if isinstance(value, Path):
                candidate = str(value)
            elif isinstance(value, str):
                candidate = value
            else:
                return

            if not candidate or candidate in seen:
                return
            path = Path(candidate)
            if path.exists() and path.is_file():
                seen.add(candidate)
                paths.append((candidate, key_hint))

        _walk(outputs)

        evidence_items: list[Evidence] = []
        for candidate, key_hint in paths:
            file_type = Path(candidate).suffix or "file"
            file_meta = {"tool": tool_name}
            if key_hint:
                file_meta["artifact_key"] = key_hint
            if metadata:
                file_meta.update(metadata)
            evidence_items.append(
                self.collect_file(
                    candidate,
                    file_type=file_type,
                    is_input=False,
                    metadata=file_meta,
                )
            )
        return evidence_items

    def collect_coordinate(
        self,
        x: float,
        y: float,
        z: float,
        space: str = "MNI",
        label: str | None = None,
        source_tool: str | None = None,
    ) -> Evidence:
        """Collect brain coordinate evidence."""
        content = {"coordinates": [x, y, z], "space": space, "label": label}

        return self.collect(
            type=EvidenceType.COORDINATE,
            source=source_tool or "coordinate",
            content=content,
            confidence=ConfidenceLevel.HIGH,
        )

    def collect_api_call(
        self,
        api_name: str,
        endpoint: str,
        parameters: dict[str, Any] | None = None,
        response: dict[str, Any] | None = None,
        success: bool = True,
    ) -> Evidence:
        """Collect API call evidence."""
        content = {
            "api": api_name,
            "endpoint": endpoint,
            "parameters": parameters or {},
            "success": success,
            "response_summary": (
                self._summarize_response(response) if response else None
            ),
        }

        return self.collect(
            type=EvidenceType.API_CALL,
            source=api_name,
            content=content,
            confidence=ConfidenceLevel.HIGH,
        )

    def start_chain(self, description: str = "") -> EvidenceChain:
        """Start a new evidence chain."""
        chain = EvidenceChain(description=description)
        self.chains[chain.chain_id] = chain
        self.current_chain = chain
        logger.info(f"Started evidence chain: {chain.chain_id}")
        return chain

    def end_chain(self) -> EvidenceChain | None:
        """End the current evidence chain."""
        if self.current_chain:
            chain = self.current_chain
            self.current_chain = None
            logger.info(
                f"Ended evidence chain: {chain.chain_id} ({len(chain.steps)} steps)"
            )
            return chain
        return None

    def get_evidence_by_type(self, type: EvidenceType) -> list[Evidence]:
        """Get all evidence of a specific type."""
        evidence_ids = self.by_type.get(type, [])
        return [self.evidence[eid] for eid in evidence_ids if eid in self.evidence]

    def get_evidence_by_source(self, source: str) -> list[Evidence]:
        """Get all evidence from a specific source."""
        evidence_ids = self.by_source.get(source, [])
        return [self.evidence[eid] for eid in evidence_ids if eid in self.evidence]

    def get_citations(self) -> list[str]:
        """Get all generated citations."""
        return sorted(list(self.citations))

    def generate_report(self) -> dict[str, Any]:
        """
        Generate a comprehensive evidence report.

        Returns:
            Report dictionary with summary and details
        """
        report = {
            "summary": {
                "total_evidence": len(self.evidence),
                "evidence_types": {
                    type.value: len(self.by_type.get(type, [])) for type in EvidenceType
                },
                "sources": list(self.by_source.keys()),
                "chains": len(self.chains),
                "citations": len(self.citations),
            },
            "datasets": [
                e.to_dict() for e in self.get_evidence_by_type(EvidenceType.DATASET)
            ],
            "publications": [
                e.to_dict() for e in self.get_evidence_by_type(EvidenceType.PUBLICATION)
            ],
            "tools": [
                e.to_dict() for e in self.get_evidence_by_type(EvidenceType.TOOL)
            ],
            "files": [
                e.to_dict() for e in self.get_evidence_by_type(EvidenceType.FILE)
            ],
            "citations": self.get_citations(),
            "chains": [
                {
                    "chain_id": chain.chain_id,
                    "description": chain.description,
                    "steps": len(chain.steps),
                    "provenance": chain.get_provenance_graph(),
                }
                for chain in self.chains.values()
            ],
        }

        return report

    def generate_reproducibility_info(self) -> dict[str, Any]:
        """
        Generate information needed for reproducibility.

        Returns:
            Dictionary with all information needed to reproduce the analysis
        """
        tools_used = {}
        for evidence in self.get_evidence_by_type(EvidenceType.TOOL):
            tool_name = evidence.content.get("name")
            if tool_name not in tools_used:
                tools_used[tool_name] = {
                    "version": evidence.content.get("version"),
                    "executions": [],
                }
            tools_used[tool_name]["executions"].append(
                {
                    "command": evidence.content.get("command"),
                    "parameters": evidence.content.get("parameters"),
                    "timestamp": evidence.timestamp,
                }
            )

        return {
            "environment": {
                "timestamp": datetime.now().isoformat(),
                "evidence_collector_version": "1.0.0",
                "run_id": self.run_id,
                "run_started_at": self.run_started_at,
                "run_metadata": self.run_metadata,
            },
            "datasets": [
                {
                    "id": e.content.get("dataset_id"),
                    "name": e.content.get("name"),
                    "version": e.content.get("version"),
                    "doi": e.content.get("doi"),
                }
                for e in self.get_evidence_by_type(EvidenceType.DATASET)
            ],
            "tools": tools_used,
            "parameters": [
                e.content for e in self.get_evidence_by_type(EvidenceType.PARAMETER)
            ],
            "files": [
                {
                    "path": e.content.get("path"),
                    "checksum": e.content.get("checksum"),
                    "is_input": e.content.get("is_input"),
                }
                for e in self.get_evidence_by_type(EvidenceType.FILE)
            ],
            "citations": self.get_citations(),
        }

    def export_jsonld(self, output_path: Path | None = None) -> Path:
        """Export evidence in JSON-LD format with a simple context."""
        if not output_path:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = self.storage_path / f"evidence_{ts}.jsonld"

        context = {
            "@vocab": "https://brain-researcher.org/schema#",
            "schema": "http://schema.org/",
            "prov": "http://www.w3.org/ns/prov#",
            "id": "@id",
            "type": "@type",
        }

        def map_type(t: EvidenceType) -> str:
            return {
                EvidenceType.DATASET: "schema:Dataset",
                EvidenceType.PUBLICATION: "schema:ScholarlyArticle",
                EvidenceType.TOOL: "schema:SoftwareApplication",
                EvidenceType.PARAMETER: "schema:PropertyValue",
                EvidenceType.RESULT: "schema:CreativeWork",
                EvidenceType.COORDINATE: "schema:Place",
                EvidenceType.CONCEPT: "schema:DefinedTerm",
                EvidenceType.FILE: "schema:MediaObject",
                EvidenceType.API_CALL: "schema:Action",
                EvidenceType.KNOWLEDGE_GRAPH: "schema:Dataset",
                EvidenceType.USER_INPUT: "schema:DigitalDocument",
                EvidenceType.INFERENCE: "schema:Intangible",
                EvidenceType.ENVIRONMENT: "schema:SoftwareApplication",
                EvidenceType.RUN: "schema:Action",
            }.get(t, "schema:Thing")

        items: list[dict[str, Any]] = []
        # Run node
        items.append(
            {
                "id": self.run_id,
                "type": map_type(EvidenceType.RUN),
                "schema:name": "Brain Researcher Run",
                "schema:startTime": self.run_started_at,
            }
        )

        for e in self.evidence.values():
            node = {
                "id": e.evidence_id,
                "type": map_type(e.type),
                "schema:identifier": e.evidence_id,
                "schema:dateCreated": datetime.fromtimestamp(e.timestamp).isoformat(),
                "schema:additionalType": e.type.value,
                "schema:creator": e.source,
                "schema:additionalProperty": e.content,
                "prov:wasGeneratedBy": self.run_id,
                "schema:confidence": e.confidence.value,
            }
            items.append(node)

        # Provenance edges from chains
        for chain in self.chains.values():
            for i in range(1, len(chain.steps)):
                prev = chain.steps[i - 1]
                curr = chain.steps[i]
                items.append(
                    {
                        "type": "prov:Association",
                        "prov:agent": prev.evidence_id,
                        "prov:hadRole": "derives_from",
                        "prov:activity": curr.evidence_id,
                    }
                )

        jsonld = {"@context": context, "@graph": items}
        with open(output_path, "w") as f:
            json.dump(jsonld, f, indent=2)
        logger.info(f"Exported JSON-LD to {output_path}")
        return output_path

    def export_to_file(self, output_path: Path | None = None) -> Path:
        """
        Export all evidence to a JSON file.

        Args:
            output_path: Output file path (defaults to timestamp-based name)

        Returns:
            Path to the exported file
        """
        if not output_path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = self.storage_path / f"evidence_{timestamp}.json"

        export_data = {
            "report": self.generate_report(),
            "reproducibility": self.generate_reproducibility_info(),
            "all_evidence": [e.to_dict() for e in self.evidence.values()],
        }

        with open(output_path, "w") as f:
            json.dump(export_data, f, indent=2, default=str)

        logger.info(f"Exported evidence to {output_path}")
        return output_path

    def generate_run_card(self) -> dict[str, Any]:
        """Generate a structured Run Card summarizing the analysis run."""
        repro = self.generate_reproducibility_info()
        report = self.generate_report()
        tools = [e.to_dict() for e in self.get_evidence_by_type(EvidenceType.TOOL)]
        params = [
            e.to_dict() for e in self.get_evidence_by_type(EvidenceType.PARAMETER)
        ]
        pubs = [
            e.to_dict() for e in self.get_evidence_by_type(EvidenceType.PUBLICATION)
        ]
        env = [e.to_dict() for e in self.get_evidence_by_type(EvidenceType.ENVIRONMENT)]

        card = {
            "run_id": self.run_id,
            "started_at": self.run_started_at,
            "metadata": self.run_metadata,
            "datasets": report.get("datasets", []),
            "tools": tools,
            "parameters": params,
            "files": report.get("files", []),
            "citations": report.get("citations", []),
            "publications": pubs,
            "environment": env,
            "chains": report.get("chains", []),
        }
        return card

    def save_run_card(self, output_path: Path | None = None) -> Path:
        """Save the Run Card as JSON (and a Markdown sidecar)."""
        if not output_path:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = self.storage_path / f"run_card_{ts}.json"
        card = self.generate_run_card()
        with open(output_path, "w") as f:
            json.dump(card, f, indent=2)
        # Markdown sidecar
        md_path = output_path.with_suffix(".md")
        try:
            md = self._render_run_card_markdown(card)
            with open(md_path, "w") as f:
                f.write(md)
        except Exception:
            logger.exception("Failed to render Run Card markdown")
        return output_path

    def _render_run_card_markdown(self, card: dict[str, Any]) -> str:
        """Render a simple Markdown Run Card."""
        lines = []
        lines.append(f"# Run Card: {card.get('run_id')}")
        lines.append("")
        lines.append(f"Started: {card.get('started_at')}")
        if card.get("metadata"):
            lines.append(f"Metadata: {json.dumps(card['metadata'])}")
        lines.append("")
        if card.get("datasets"):
            lines.append("## Datasets")
            for d in card["datasets"]:
                name = d.get("content", {}).get("name") or d.get("content", {}).get(
                    "dataset_id"
                )
                lines.append(f"- {name}")
        if card.get("tools"):
            lines.append("\n## Tools")
            for t in card["tools"]:
                c = t.get("content", {})
                lines.append(
                    f"- {c.get('name')} {('v'+c.get('version')) if c.get('version') else ''}"
                )
        if card.get("parameters"):
            lines.append("\n## Parameters")
            for p in card["parameters"]:
                src = p.get("source")
                lines.append(f"- {src}: {json.dumps(p.get('content'))}")
        if card.get("citations"):
            lines.append("\n## Citations")
            for c in card["citations"]:
                lines.append(f"- {c}")
        return "\n".join(lines)

    def link_publication_to_evidence(
        self, evidence_id: str, publication_doi: str
    ) -> bool:
        """Link a publication DOI to a specific evidence item via metadata."""
        ev = self.evidence.get(evidence_id)
        if not ev:
            return False
        links = ev.metadata.get("linked_publications", [])
        if publication_doi not in links:
            links.append(publication_doi)
        ev.metadata["linked_publications"] = links
        # Also add a citation entry if we have a matching publication evidence
        for pub in self.get_evidence_by_type(EvidenceType.PUBLICATION):
            if pub.content.get("doi") == publication_doi and pub.to_citation():
                self.citations.add(pub.to_citation() or publication_doi)
        if self.auto_persist:
            self._persist_evidence(ev)
        return True

    def _persist_evidence(self, evidence: Evidence):
        """Persist evidence to storage."""
        if self.storage_path:
            evidence_file = self.storage_path / f"{evidence.evidence_id}.json"
            with open(evidence_file, "w") as f:
                json.dump(evidence.to_dict(), f, indent=2, default=str)

    def _compute_checksum(self, file_path: Path) -> str:
        """Compute SHA256 checksum of a file."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def _summarize_response(self, response: dict[str, Any]) -> dict[str, Any]:
        """Summarize API response for evidence."""
        summary = {
            "status": response.get("status"),
            "result_count": (
                len(response.get("results", [])) if "results" in response else None
            ),
        }

        # Add key fields without including full data
        for key in ["error", "message", "total", "count"]:
            if key in response:
                summary[key] = response[key]

        return summary

    def clear(self):
        """Clear all collected evidence."""
        self.evidence.clear()
        self.chains.clear()
        self.by_type.clear()
        self.by_source.clear()
        self.citations.clear()
        self.current_chain = None
        logger.info("Cleared all evidence")


class EvidenceIntegration:
    """
    Integration helper for using EvidenceCollector with other components.
    """

    @staticmethod
    def from_tool_execution(
        collector: EvidenceCollector,
        tool_name: str,
        parameters: dict[str, Any],
        result: dict[str, Any],
        execution_time: float,
    ) -> Evidence:
        """Create evidence from tool execution result."""
        return collector.collect_tool_execution(
            tool_name=tool_name,
            parameters=parameters,
            execution_time=execution_time,
            success=result.get("status") == "success",
        )

    @staticmethod
    def from_knowledge_graph_query(
        collector: EvidenceCollector,
        query: str,
        results: list[dict[str, Any]],
        query_time: float,
    ) -> Evidence:
        """Create evidence from knowledge graph query."""
        return collector.collect(
            type=EvidenceType.KNOWLEDGE_GRAPH,
            source="BR-KG",
            content={
                "query": query,
                "result_count": len(results),
                "query_time": query_time,
                "sample_results": results[:3] if results else [],  # Include sample
            },
            confidence=ConfidenceLevel.HIGH,
        )


class EvidenceAPI:
    """Lightweight API for querying and exporting evidence."""

    def __init__(self, collector: EvidenceCollector):
        self.collector = collector

    def counts(self) -> dict[str, int]:
        return {t.value: len(self.collector.by_type.get(t, [])) for t in EvidenceType}

    def list_by_type(self, type_name: str) -> list[dict[str, Any]]:
        try:
            t = EvidenceType(type_name)
        except Exception:
            # Accept lowercase tokens
            t = EvidenceType[type_name.upper()]
        return [e.to_dict() for e in self.collector.get_evidence_by_type(t)]

    def search(self, keyword: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for e in self.collector.evidence.values():
            blob = json.dumps(e.to_dict()).lower()
            if keyword.lower() in blob:
                results.append(e.to_dict())
        return results

    def export_json(self) -> dict[str, Any]:
        return {
            "report": self.collector.generate_report(),
            "reproducibility": self.collector.generate_reproducibility_info(),
        }

    def export_jsonld(self, output_path: Path | None = None) -> Path:
        return self.collector.export_jsonld(output_path)

    def run_card(self) -> dict[str, Any]:
        return self.collector.generate_run_card()

    @staticmethod
    def from_inference(
        collector: EvidenceCollector,
        source: str,
        inferred_data: dict[str, Any],
        confidence: float,
    ) -> Evidence:
        """Create evidence from inference."""
        # Map confidence score to level
        if confidence >= 0.8:
            conf_level = ConfidenceLevel.HIGH
        elif confidence >= 0.5:
            conf_level = ConfidenceLevel.MEDIUM
        else:
            conf_level = ConfidenceLevel.LOW

        return collector.collect(
            type=EvidenceType.INFERENCE,
            source=source,
            content=inferred_data,
            confidence=conf_level,
            metadata={"confidence_score": confidence},
        )
