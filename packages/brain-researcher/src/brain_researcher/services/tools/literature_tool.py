"""
GLM literature/reference helper for multiverse and provenance.

Sources:
- BR-KG priors (already available via GLMPriorsTool) for evidence counts.
- Dataset DOI from dataset_description.json.
- Static method references (CompCor, motion, HRF, HPF) from core.literature.references.
"""

from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from neo4j import GraphDatabase

from brain_researcher.services.tools.tool_base import CachedToolWrapper, ToolResult
from brain_researcher.services.tools.neurokg_tools import GLMPriorsTool
from brain_researcher.core.literature.references import gather_references

logger = logging.getLogger(__name__)


class GLMLiteratureArgs(BaseModel):
    dataset_id: str = Field(..., description="Dataset id (e.g., ds000114)")
    task: str = Field(..., description="Task label (e.g., fingerfootlips)")
    contrast: Optional[str] = Field(
        default=None,
        description="Optional contrast label to include in literature queries.",
    )
    decision_points: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Decision dict (e.g., {'hrf':'canonical','confounds':'6mot','high_pass':128})",
    )
    keywords: Optional[List[str]] = Field(
        default=None,
        description="Optional extra keywords to include in file-search query.",
    )
    parcellations: Optional[List[str]] = Field(
        default=None,
        description="Optional parcellation names to pull atlas citations (e.g., ['Yeo2011-7']).",
    )
    use_neurokg: bool = Field(
        default=True, description="Include BR-KG priors as evidence"
    )
    include_static: bool = Field(
        default=True, description="Include static method references"
    )
    use_neo4j: bool = Field(
        default=True,
        description="Run a Neo4j Cypher for publication references when possible",
    )
    use_file_search: bool = Field(
        default=False, description="Include Google File Search evidence if configured"
    )
    file_search_query: Optional[str] = Field(
        default=None, description="Override query for Google File Search evidence"
    )
    file_search_store: Optional[str] = Field(
        default=None,
        description=(
            "Override file search store name(s). Defaults to "
            "BR_FILE_SEARCH_STORE_NAMES when set, otherwise FILE_SEARCH_STORE/"
            "BR_FILE_SEARCH_STORE."
        ),
    )
    file_search_top_k: int = Field(
        default=5, description="Top-K chunks to return from file search"
    )
    file_search_model: Optional[str] = Field(
        default=None,
        description="Override model for file search (defaults to env/DEFAULT_LLM_MODEL)",
    )


class GLMLiteratureTool(CachedToolWrapper):
    """Return references/evidence for GLM design choices."""

    def get_tool_name(self) -> str:
        return "glm.literature"

    def get_tool_description(self) -> str:
        return "Return literature/references for GLM decisions (hrf/confounds/high_pass) plus dataset citation."

    def get_args_schema(self):
        return GLMLiteratureArgs

    def _run(
        self,
        dataset_id: str,
        task: str,
        contrast: Optional[str] = None,
        decision_points: Optional[Dict[str, Any]] = None,
        keywords: Optional[List[str]] = None,
        parcellations: Optional[List[str]] = None,
        use_neurokg: bool = True,
        include_static: bool = True,
        use_neo4j: bool = True,
        use_file_search: bool = False,
        file_search_query: Optional[str] = None,
        file_search_store: Optional[str] = None,
        file_search_top_k: int = 5,
        file_search_model: Optional[str] = None,
    ) -> ToolResult:
        repo_root = Path(__file__).resolve().parents[4]
        datasets_folder = repo_root / "dataset"

        references = gather_references(
            dataset_id=dataset_id,
            task=task,
            decisions=decision_points or {},
            datasets_folder=datasets_folder,
        )
        if not include_static:
            references = [r for r in references if r.get("source") != "static"]

        evidence: Dict[str, Any] = {}
        if use_neurokg:
            try:
                priors_res = GLMPriorsTool()._run(task=task, study_id=dataset_id)
                evidence["neurokg_scanned"] = priors_res.data.get("outputs", {}).get(
                    "scanned"
                )
                evidence["neurokg_priors"] = priors_res.data.get("outputs", {}).get(
                    "priors"
                )
            except Exception:
                evidence["neurokg_scanned"] = None

        neo_refs: List[Dict[str, Any]] = []
        neo_evidence: Dict[str, Any] = {}
        if use_neo4j:
            try:
                neo_refs, neo_evidence = self._query_neo4j(
                    dataset_id, task, decision_points or {}, parcellations or []
                )
                references.extend(neo_refs)
                evidence.update(neo_evidence)
            except Exception as exc:  # pragma: no cover - best effort
                logger.warning("Neo4j literature lookup failed: %s", exc)
                neo_evidence = {"neo4j_status": "error", "neo4j_error": str(exc)}

        # Structured view (dataset/methods) while keeping flat list for backward compatibility
        structured: Dict[str, Any] = {"dataset": [], "methods": {}, "atlas": {}}
        for ref in references:
            supports = ref.get("supports") or []
            if any(s.get("decision") == "dataset" for s in supports):
                structured["dataset"].append(ref)
            for s in supports:
                d = s.get("decision")
                o = s.get("option")
                if d and d != "dataset":
                    if d == "parcellation":
                        structured.setdefault("atlas", {}).setdefault(
                            str(o), []
                        ).append(ref)
                    else:
                        structured.setdefault("methods", {}).setdefault(
                            d, {}
                        ).setdefault(str(o), []).append(ref)

        # Prevalence vs support separation
        # Avoid circular refs: copy prevalence dicts before nesting
        evidence.setdefault("prevalence", {})
        if neo_evidence.get("prevalence"):
            evidence["prevalence"]["neurokg"] = dict(
                neo_evidence.get("prevalence") or {}
            )
        if use_neurokg and evidence.get("neurokg_priors"):
            evidence["prevalence"]["priors"] = dict(evidence["neurokg_priors"])

        if use_file_search:
            fs = self._file_search_evidence(
                task=task,
                contrast=contrast,
                decision_points=decision_points or {},
                keywords=keywords or [],
                override_query=file_search_query,
                override_store=file_search_store,
                top_k=file_search_top_k,
                override_model=file_search_model,
            )
            evidence["file_search"] = fs

        return ToolResult(
            status="success",
            data={
                "outputs": {
                    "references": references,
                    "references_structured": structured,
                    "evidence": evidence,
                }
            },
        )

    # --- internal helpers -------------------------------------------------

    @staticmethod
    def _neo_driver():
        """Return a Neo4j driver if env vars are set; otherwise None."""
        uri = os.environ.get("NEO4J_URI")
        user = os.environ.get("NEO4J_USER")
        password = os.environ.get("NEO4J_PASSWORD") or os.environ.get("NEO4J_PASS")
        if not (uri and user and password):
            return None
        try:
            return GraphDatabase.driver(uri, auth=(user, password))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to connect Neo4j driver: %s", exc)
            return None

    def _query_neo4j(
        self,
        dataset_id: str,
        task: str,
        decision_points: Dict[str, Any],
        parcellations: List[str],
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Best-effort Cypher to pull publication references + prevalence for the dataset/task."""
        driver = self._neo_driver()
        if driver is None:
            return [], {"neo4j_refs": 0, "neo4j_status": "unconfigured"}

        # Label lists (schema-agnostic but constrained)
        pub_labels = ["Publication", "Paper", "Article", "Citation"]
        spec_labels = ["ModelSpec", "StatsModelSpec", "Spec", "BIDSModel"]

        cypher_pub_from_spec = """
        MATCH (d:Dataset)
        WHERE d.id = $dataset_id OR d.name = $dataset_id
        MATCH (d)--(s)
        WHERE any(l IN labels(s) WHERE l IN $spec_labels)
          AND ($task IS NULL OR s.task = $task OR $task IN coalesce(s.tasks, []))
        OPTIONAL MATCH (s)-[r:CITES|HASCITATION]-(p)
        WHERE any(l IN labels(p) WHERE l IN $pub_labels)
          AND (p.doi IS NOT NULL OR p.title IS NOT NULL)
        WITH p, collect(distinct coalesce(s.id, elementId(s))) AS spec_ids
        RETURN DISTINCT p.title AS title, p.doi AS doi, p.year AS year, p.url AS url, spec_ids AS spec_ids
        LIMIT 20
        """

        cypher_pub_from_dataset = """
        MATCH (d:Dataset)
        WHERE d.id = $dataset_id OR d.name = $dataset_id
        OPTIONAL MATCH (d)-[r:CITES|HASCITATION]-(p)
        WHERE any(l IN labels(p) WHERE l IN $pub_labels)
          AND (p.doi IS NOT NULL OR p.title IS NOT NULL)
        RETURN DISTINCT p.title AS title, p.doi AS doi, p.year AS year, p.url AS url, [] AS spec_ids
        LIMIT 20
        """

        cypher_prevalence = """
        MATCH (d:Dataset)
        WHERE d.id = $dataset_id OR d.name = $dataset_id
        MATCH (d)--(s)
        WHERE any(l IN labels(s) WHERE l IN $spec_labels)
          AND ($task IS NULL OR s.task = $task OR $task IN coalesce(s.tasks, []))
        RETURN collect(distinct coalesce(s.id, elementId(s))) AS spec_ids, count(distinct s) AS n_specs
        """

        cypher_atlas = """
        MATCH (p:Parcellation)
        WHERE p.name IN $parcellations
        OPTIONAL MATCH (p)<-[:HAS_PARCELLATION]-(a:Atlas)
        WITH p, a
        OPTIONAL MATCH (n)-[:CITES]->(pub:Publication)
        WHERE n IN [p,a] AND (pub.doi IS NOT NULL OR pub.title IS NOT NULL)
        RETURN DISTINCT pub.title AS title, pub.doi AS doi, pub.year AS year, pub.url AS url,
               coalesce(a.name, p.name) AS atlas_name, p.name AS parcellation_name
        """

        refs: List[Dict[str, Any]] = []
        neo_evidence: Dict[str, Any] = {"neo4j_status": "connected"}

        def _format_record(rec):
            return {
                "source": "neurokg",
                "kind": "publication",
                "title": rec.get("title") or "Publication",
                "year": rec.get("year"),
                "doi": rec.get("doi"),
                "url": rec.get("url"),
                "supports": (
                    [
                        {"decision": k, "option": str(v)}
                        for k, v in decision_points.items()
                    ]
                    if decision_points
                    else [{"decision": "dataset", "option": dataset_id}]
                ),
                "evidence": {"spec_ids": rec.get("spec_ids") or []},
            }

        with driver.session() as session:
            spec_refs = [
                _format_record(r.data())
                for r in session.run(
                    cypher_pub_from_spec,
                    dataset_id=dataset_id,
                    task=task,
                    pub_labels=pub_labels,
                    spec_labels=spec_labels,
                )
            ]
            dataset_refs = [
                _format_record(r.data())
                for r in session.run(
                    cypher_pub_from_dataset,
                    dataset_id=dataset_id,
                    task=task,
                    pub_labels=pub_labels,
                    spec_labels=spec_labels,
                )
            ]
            prev_rec = session.run(
                cypher_prevalence,
                dataset_id=dataset_id,
                task=task,
                pub_labels=pub_labels,
                spec_labels=spec_labels,
            ).single()
            atlas_refs = []
            if parcellations:
                atlas_refs = [
                    {
                        "source": "neurokg",
                        "kind": "publication",
                        "title": r.get("title") or "Publication",
                        "year": r.get("year"),
                        "doi": r.get("doi"),
                        "url": r.get("url"),
                        "supports": [
                            {
                                "decision": "parcellation",
                                "option": r.get("parcellation_name"),
                            }
                        ],
                        "evidence": {
                            "atlas": r.get("atlas_name"),
                            "parcellation": r.get("parcellation_name"),
                        },
                    }
                    for r in session.run(
                        cypher_atlas,
                        parcellations=parcellations,
                        pub_labels=pub_labels,
                        spec_labels=spec_labels,
                    )
                ]

        driver.close()

        seen = set()
        for r in spec_refs + dataset_refs + atlas_refs:
            key = (r.get("doi"), r.get("title"))
            if key in seen:
                continue
            seen.add(key)
            refs.append(r)

        prev = {"n_specs": 0, "spec_ids": []}
        if prev_rec:
            prev["n_specs"] = prev_rec.get("n_specs", 0)
            prev["spec_ids"] = list(prev_rec.get("spec_ids") or [])[:10]

        neo_evidence["neo4j_refs"] = len(refs)
        neo_evidence["prevalence"] = prev
        return refs, neo_evidence

    # --- file search helpers --------------------------------------------

    @staticmethod
    def _resolve_file_search_store(override_store: Optional[str]) -> Optional[str]:
        if override_store:
            return override_store
        multi = os.environ.get("BR_FILE_SEARCH_STORE_NAMES")
        if multi:
            stores = [s.strip() for s in multi.split(",") if s.strip()]
            if stores:
                return ",".join(stores)
        return (
            os.environ.get("FILE_SEARCH_STORE")
            or os.environ.get("BR_FILE_SEARCH_STORE")
            or os.environ.get("BR_GOOGLE_FILE_SEARCH_STORE")
            or os.environ.get("GOOGLE_FILE_SEARCH_STORE")
        )

    @staticmethod
    def _resolve_file_search_model(override_model: Optional[str]) -> str:
        return (
            override_model
            or os.environ.get("BR_FILE_SEARCH_MODEL")
            or os.environ.get("DEFAULT_LLM_MODEL")
            or "gemini-3-flash-preview"
        )

    @staticmethod
    def _build_file_search_query(
        task: str,
        contrast: Optional[str],
        decision_points: Dict[str, Any],
        keywords: List[str],
    ) -> str:
        terms: List[str] = []
        if task:
            terms.append(task)
        if contrast:
            terms.append(contrast)
        # Make fMRI explicit to stabilize retrieval
        terms.append("fMRI")

        hrf = decision_points.get("hrf")
        if hrf:
            terms.extend(["HRF", str(hrf), "hemodynamic response"])
        confounds = decision_points.get("confounds")
        if confounds:
            confounds_str = str(confounds)
            terms.extend([confounds_str, "confounds", "motion regression"])
            if "acompcor" in confounds_str.lower():
                terms.append("CompCor")
        high_pass = decision_points.get("high_pass")
        if high_pass:
            terms.extend([f"high-pass {high_pass}", "high-pass filter"])

        terms.extend([t for t in keywords if t])
        return " ".join(terms).strip()

    @staticmethod
    def _extract_doc_header(text: str) -> Dict[str, str]:
        header: Dict[str, str] = {}
        for raw in text.splitlines():
            line = raw.strip()
            if not line or ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip()
            if key in {"pmcid", "pmid", "doi", "title", "journal", "year"}:
                header[key] = value
        return header

    def _file_search_evidence(
        self,
        task: str,
        contrast: Optional[str],
        decision_points: Dict[str, Any],
        keywords: List[str],
        override_query: Optional[str],
        override_store: Optional[str],
        top_k: int,
        override_model: Optional[str],
    ) -> Dict[str, Any]:
        from brain_researcher.core.literature.gfs_store import search_gfs_auto

        query = override_query or self._build_file_search_query(
            task, contrast, decision_points, keywords
        )
        result = search_gfs_auto(
            query,
            top_k=top_k,
            store=self._resolve_file_search_store(override_store),
            model=self._resolve_file_search_model(override_model),
            weak_evidence=True,
            max_calls=2,
        )
        if result.get("status") != "ok":
            return result
        return {
            "status": "ok",
            "store": result.get("store"),
            "stores_hit": result.get("stores_hit"),
            "call_count": result.get("call_count"),
            "reason": result.get("reason"),
            "model": result.get("model"),
            "query": query,
            "summary": result.get("summary"),
            "chunks": result.get("hits", [])[:top_k],
        }


class LiteratureTools:
    @staticmethod
    def get_all_tools():
        return [GLMLiteratureTool()]
