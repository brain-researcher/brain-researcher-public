"""Persisted queries for BR-KG - completes KG-008.

This module provides 20+ pre-defined, optimized queries for common patterns.
"""

import json
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class PersistedQuery:
    """Persisted query definition."""
    
    id: str
    name: str
    description: str
    query: str
    parameters: List[str]
    version: int = 1
    category: str = "general"
    performance_target_ms: int = 100
    

class QueryLibrary:
    """Library of persisted queries."""
    
    def __init__(self):
        """Initialize query library."""
        self.queries = self._load_queries()
        self.query_map = {q.id: q for q in self.queries}
        
    def _load_queries(self) -> List[PersistedQuery]:
        """Load all persisted queries."""
        return [
            # Navigation Queries
            PersistedQuery(
                id="Q1_TASK_TO_REGION",
                name="Task to Brain Regions",
                description="Find brain regions activated by a specific task",
                query="""
                    MATCH (t:Task {name: $task_name})-[:MEASURES]->(c:Concept)
                    MATCH (c)-[:ACTIVATES]->(r)
                    WHERE r:BrainRegion OR r:Region
                    RETURN DISTINCT r.name as region, 
                           r.mni_coordinates as coordinates,
                           count(c) as concept_count
                    ORDER BY concept_count DESC
                """,
                parameters=["task_name"],
                category="navigation",
                performance_target_ms=50
            ),
            
            PersistedQuery(
                id="Q2_PUB_TO_COORDS",
                name="Publication to Coordinates",
                description="Get activation coordinates from a publication",
                query="""
                    MATCH (p:Publication {pmid: $pmid})-[:HAS_COORDINATE]->(c:Coordinate)
                    OPTIONAL MATCH (c)-[:IN_REGION]->(legacy_region:Region)
                    WITH p, c, collect(DISTINCT legacy_region.name) AS legacy_region_names
                    CALL {
                        WITH p
                        OPTIONAL MATCH (m)-[:DERIVED_FROM]->(p)
                        WHERE any(lbl IN labels(m) WHERE lbl IN ['StatsMap', 'StatMap', 'StatisticalMap'])
                        OPTIONAL MATCH (m)-[:IN_REGION]->(brain_region:BrainRegion)
                        RETURN collect(DISTINCT brain_region.name) AS brain_region_names
                    }
                    RETURN c.x as x, c.y as y, c.z as z,
                           c.statistic_type as stat_type,
                           c.statistic_value as stat_value,
                           head(legacy_region_names) as region_name,
                           brain_region_names,
                           legacy_region_names as compatibility_region_names
                    ORDER BY c.statistic_value DESC
                """,
                parameters=["pmid"],
                category="navigation",
                performance_target_ms=30
            ),
            
            PersistedQuery(
                id="Q3_CONCEPT_TO_STUDIES",
                name="Concept to Studies",
                description="Find all studies investigating a concept",
                query="""
                    MATCH (c:Concept {name: $concept_name})<-[:MEASURES]-(t:Task)
                    MATCH (t)<-[:CONTAINS]-(d:Dataset)
                    OPTIONAL MATCH (d)-[:DESCRIBED_BY]->(p:Publication)
                    RETURN DISTINCT d.name as dataset,
                           d.dataset_id as dataset_id,
                           count(t) as task_count,
                           collect(DISTINCT p.pmid) as publications
                    ORDER BY task_count DESC
                    LIMIT 50
                """,
                parameters=["concept_name"],
                category="navigation",
                performance_target_ms=80
            ),
            
            # Analysis Queries
            PersistedQuery(
                id="Q4_REGION_COACTIVATION",
                name="Region Co-activation Network",
                description="Find regions that co-activate with a target region",
                query="""
                    MATCH (r1 {name: $region_name})
                    WHERE r1:BrainRegion OR r1:Region
                    MATCH (r1)<-[:ACTIVATES]-(c:Concept)
                    MATCH (c)-[:ACTIVATES]->(r2)
                    WHERE r2:BrainRegion OR r2:Region
                    WHERE r1 <> r2
                    WITH r2, count(c) as coactivation_count
                    RETURN r2.name as region,
                           r2.mni_coordinates as coordinates,
                           coactivation_count
                    ORDER BY coactivation_count DESC
                    LIMIT 20
                """,
                parameters=["region_name"],
                category="analysis",
                performance_target_ms=100
            ),
            
            PersistedQuery(
                id="Q5_TASK_SIMILARITY",
                name="Similar Tasks by Concepts",
                description="Find tasks similar to a given task based on shared concepts",
                query="""
                    MATCH (t1:Task {name: $task_name})-[:MEASURES]->(c:Concept)
                    MATCH (t2:Task)-[:MEASURES]->(c)
                    WHERE t1 <> t2
                    WITH t2, collect(c.name) as shared_concepts, count(c) as similarity_score
                    RETURN t2.name as task,
                           t2.dataset_id as dataset,
                           shared_concepts,
                           similarity_score
                    ORDER BY similarity_score DESC
                    LIMIT 10
                """,
                parameters=["task_name"],
                category="analysis",
                performance_target_ms=120
            ),
            
            PersistedQuery(
                id="Q6_CONCEPT_HIERARCHY",
                name="Concept Hierarchy",
                description="Get concept hierarchy from ontology",
                query="""
                    MATCH path = (c:Concept {name: $concept_name})-[:IS_A*0..3]->(parent:Concept)
                    RETURN c.name as concept,
                           parent.name as parent_concept,
                           length(path) as depth,
                           parent.ontology_id as ontology_id
                    ORDER BY depth
                """,
                parameters=["concept_name"],
                category="ontology",
                performance_target_ms=50
            ),
            
            # Meta-analysis Queries
            PersistedQuery(
                id="Q7_META_ANALYSIS_COORDS",
                name="Meta-analysis Coordinates",
                description="Get all coordinates for meta-analysis of a concept",
                query="""
                    MATCH (c:Concept {name: $concept_name})<-[:MEASURES]-(t:Task)
                    MATCH (t)-[:HAS_CONTRAST]->(contrast:Contrast)
                    MATCH (contrast)-[:HAS_COORDINATE]->(coord:Coordinate)
                    RETURN coord.x as x, coord.y as y, coord.z as z,
                           contrast.name as contrast_name,
                           t.name as task_name,
                           coord.statistic_value as effect_size
                    WHERE coord.statistic_value > $threshold
                """,
                parameters=["concept_name", "threshold"],
                category="meta_analysis",
                performance_target_ms=150
            ),
            
            PersistedQuery(
                id="Q8_PUBLICATION_NETWORK",
                name="Publication Citation Network",
                description="Get citation network for publications",
                query="""
                    MATCH (p1:Publication)-[:CITES]->(p2:Publication)
                    WHERE p1.year >= $start_year AND p1.year <= $end_year
                    RETURN p1.pmid as source,
                           p2.pmid as target,
                           p1.title as source_title,
                           p2.title as target_title,
                           p1.year as source_year,
                           p2.year as target_year
                    LIMIT 500
                """,
                parameters=["start_year", "end_year"],
                category="network",
                performance_target_ms=200
            ),
            
            # Statistical Queries
            PersistedQuery(
                id="Q9_DATASET_STATISTICS",
                name="Dataset Statistics",
                description="Get comprehensive statistics for a dataset",
                query="""
                    MATCH (d:Dataset {dataset_id: $dataset_id})
                    OPTIONAL MATCH (d)-[:CONTAINS]->(t:Task)
                    OPTIONAL MATCH (t)-[:MEASURES]->(c:Concept)
                    OPTIONAL MATCH (d)-[:HAS_SUBJECT]->(s:Subject)
                    RETURN d.name as dataset_name,
                           count(DISTINCT t) as task_count,
                           count(DISTINCT c) as concept_count,
                           count(DISTINCT s) as subject_count,
                           avg(s.age) as mean_age,
                           d.metadata as metadata
                """,
                parameters=["dataset_id"],
                category="statistics",
                performance_target_ms=100
            ),
            
            PersistedQuery(
                id="Q10_CONCEPT_FREQUENCY",
                name="Concept Frequency Distribution",
                description="Get frequency distribution of concepts",
                query="""
                    MATCH (c:Concept)<-[:MEASURES]-(t:Task)
                    WITH c, count(t) as frequency
                    WHERE frequency >= $min_frequency
                    RETURN c.name as concept,
                           c.ontology_id as ontology_id,
                           frequency
                    ORDER BY frequency DESC
                    LIMIT 100
                """,
                parameters=["min_frequency"],
                category="statistics",
                performance_target_ms=80
            ),
            
            # Spatial Queries
            PersistedQuery(
                id="Q11_NEARBY_REGIONS",
                name="Spatially Nearby Regions",
                description="Find regions within a distance from coordinates",
                query="""
                    MATCH (r)
                    WHERE (r:BrainRegion OR r:Region) AND r.mni_coordinates IS NOT NULL
                    WITH r,
                         distance(
                            point({x: toFloat(split(r.mni_coordinates, ',')[0]), 
                                   y: toFloat(split(r.mni_coordinates, ',')[1]), 
                                   z: toFloat(split(r.mni_coordinates, ',')[2])}),
                            point({x: $x, y: $y, z: $z})
                         ) as distance_mm
                    WHERE distance_mm <= $max_distance
                    RETURN r.name as region,
                           r.mni_coordinates as coordinates,
                           r.atlas as atlas,
                           distance_mm,
                           CASE
                               WHEN r:BrainRegion THEN 'BrainRegion'
                               ELSE 'Region'
                           END as region_type
                    ORDER BY distance_mm
                    LIMIT 10
                """,
                parameters=["x", "y", "z", "max_distance"],
                category="spatial",
                performance_target_ms=150
            ),
            
            PersistedQuery(
                id="Q12_HEMISPHERE_COMPARISON",
                name="Hemisphere Lateralization",
                description="Compare activation between hemispheres",
                query="""
                    MATCH (c:Concept {name: $concept_name})-[:ACTIVATES]->(r)
                    WHERE r:BrainRegion OR r:Region
                    WITH r,
                         CASE 
                           WHEN toFloat(split(r.mni_coordinates, ',')[0]) > 0 THEN 'right'
                           WHEN toFloat(split(r.mni_coordinates, ',')[0]) < 0 THEN 'left'
                           ELSE 'midline'
                         END as hemisphere
                    RETURN hemisphere,
                           count(r) as region_count,
                           collect(r.name) as regions
                """,
                parameters=["concept_name"],
                category="spatial",
                performance_target_ms=100
            ),
            
            # Temporal Queries
            PersistedQuery(
                id="Q13_TEMPORAL_TRENDS",
                name="Research Trends Over Time",
                description="Track concept popularity over time",
                query="""
                    MATCH (p:Publication)-[:STUDIES]->(c:Concept {name: $concept_name})
                    WHERE p.year >= $start_year AND p.year <= $end_year
                    RETURN p.year as year,
                           count(p) as publication_count,
                           collect(p.pmid)[..5] as sample_pmids
                    ORDER BY year
                """,
                parameters=["concept_name", "start_year", "end_year"],
                category="temporal",
                performance_target_ms=120
            ),
            
            PersistedQuery(
                id="Q14_RECENT_PUBLICATIONS",
                name="Recent Publications",
                description="Get most recent publications for a topic",
                query="""
                    MATCH (p:Publication)-[:STUDIES]->(c:Concept)
                    WHERE c.name CONTAINS $keyword
                    AND p.year >= $min_year
                    RETURN p.pmid as pmid,
                           p.title as title,
                           p.authors as authors,
                           p.year as year,
                           p.journal as journal
                    ORDER BY p.year DESC, p.pmid DESC
                    LIMIT 20
                """,
                parameters=["keyword", "min_year"],
                category="temporal",
                performance_target_ms=80
            ),
            
            # Path Queries
            PersistedQuery(
                id="Q15_CONCEPT_PATH",
                name="Shortest Path Between Concepts",
                description="Find shortest path between two concepts",
                query="""
                    MATCH path = shortestPath(
                        (c1:Concept {name: $concept1})-[*..5]-(c2:Concept {name: $concept2})
                    )
                    RETURN [n in nodes(path) | n.name] as path_nodes,
                           [r in relationships(path) | type(r)] as path_relationships,
                           length(path) as path_length
                """,
                parameters=["concept1", "concept2"],
                category="path",
                performance_target_ms=200
            ),
            
            PersistedQuery(
                id="Q16_ACTIVATION_CASCADE",
                name="Activation Cascade",
                description="Trace activation cascade from task to regions",
                query="""
                    MATCH path = (t:Task {name: $task_name})-[:MEASURES]->(c:Concept)-[:ACTIVATES]->(r:Region)
                    RETURN t.name as task,
                           c.name as concept,
                           r.name as region,
                           r.mni_coordinates as coordinates,
                           length(path) as path_length
                """,
                parameters=["task_name"],
                category="path",
                performance_target_ms=100
            ),
            
            # Validation Queries
            PersistedQuery(
                id="Q17_DATA_QUALITY_CHECK",
                name="Data Quality Check",
                description="Check data quality and completeness",
                query="""
                    MATCH (n)
                    WHERE labels(n)[0] = $node_type
                    AND (n.name IS NULL OR n.name = '')
                    RETURN count(n) as missing_name_count,
                           collect(id(n))[..10] as sample_ids
                """,
                parameters=["node_type"],
                category="validation",
                performance_target_ms=150
            ),
            
            PersistedQuery(
                id="Q18_ORPHANED_NODES",
                name="Find Orphaned Nodes",
                description="Find nodes without relationships",
                query="""
                    MATCH (n)
                    WHERE labels(n)[0] = $node_type
                    AND NOT (n)--()
                    RETURN count(n) as orphaned_count,
                           collect(n.name)[..20] as sample_names
                """,
                parameters=["node_type"],
                category="validation",
                performance_target_ms=200
            ),
            
            # Recommendation Queries
            PersistedQuery(
                id="Q19_RELATED_CONCEPTS",
                name="Recommend Related Concepts",
                description="Recommend concepts related to user's interest",
                query="""
                    MATCH (c1:Concept {name: $concept_name})<-[:MEASURES]-(t:Task)
                    MATCH (t)-[:MEASURES]->(c2:Concept)
                    WHERE c1 <> c2
                    WITH c2, count(t) as correlation_score
                    RETURN c2.name as concept,
                           c2.definition as definition,
                           correlation_score
                    ORDER BY correlation_score DESC
                    LIMIT 10
                """,
                parameters=["concept_name"],
                category="recommendation",
                performance_target_ms=100
            ),
            
            PersistedQuery(
                id="Q20_SUGGESTED_DATASETS",
                name="Suggest Relevant Datasets",
                description="Suggest datasets for research question",
                query="""
                    MATCH (c:Concept)<-[:MEASURES]-(t:Task)
                    WHERE c.name IN $concept_list
                    MATCH (t)<-[:CONTAINS]-(d:Dataset)
                    WITH d, count(DISTINCT c) as relevance_score, 
                         collect(DISTINCT c.name) as matched_concepts
                    WHERE relevance_score >= $min_relevance
                    RETURN d.dataset_id as dataset_id,
                           d.name as dataset_name,
                           d.description as description,
                           relevance_score,
                           matched_concepts
                    ORDER BY relevance_score DESC
                    LIMIT 10
                """,
                parameters=["concept_list", "min_relevance"],
                category="recommendation",
                performance_target_ms=150
            )
        ]
        
    def get_query(self, query_id: str) -> Optional[PersistedQuery]:
        """Get a persisted query by ID.
        
        Args:
            query_id: Query ID
            
        Returns:
            PersistedQuery or None
        """
        return self.query_map.get(query_id)
        
    def execute_query(
        self, 
        query_id: str, 
        parameters: Dict[str, Any],
        db_session
    ) -> List[Dict[str, Any]]:
        """Execute a persisted query.
        
        Args:
            query_id: Query ID
            parameters: Query parameters
            db_session: Database session
            
        Returns:
            Query results
        """
        query_def = self.get_query(query_id)
        if not query_def:
            raise ValueError(f"Query {query_id} not found")
            
        # Validate parameters
        missing = set(query_def.parameters) - set(parameters.keys())
        if missing:
            raise ValueError(f"Missing parameters: {missing}")
            
        # Execute query
        start_time = datetime.now()
        result = db_session.run(query_def.query, parameters)
        records = [dict(r) for r in result]
        
        execution_time = (datetime.now() - start_time).total_seconds() * 1000
        
        # Log performance
        if execution_time > query_def.performance_target_ms:
            logger.warning(
                f"Query {query_id} exceeded target: {execution_time:.0f}ms > {query_def.performance_target_ms}ms"
            )
        else:
            logger.debug(f"Query {query_id} executed in {execution_time:.0f}ms")
            
        return records
        
    def list_queries(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """List available queries.
        
        Args:
            category: Filter by category
            
        Returns:
            List of query metadata
        """
        queries = self.queries
        if category:
            queries = [q for q in queries if q.category == category]
            
        return [
            {
                "id": q.id,
                "name": q.name,
                "description": q.description,
                "category": q.category,
                "parameters": q.parameters,
                "performance_target_ms": q.performance_target_ms,
                "version": q.version
            }
            for q in queries
        ]
        
    def get_categories(self) -> List[str]:
        """Get all query categories.
        
        Returns:
            List of categories
        """
        return list(set(q.category for q in self.queries))
        
    def export_queries(self, format: str = "json") -> str:
        """Export queries in specified format.
        
        Args:
            format: Export format (json, cypher, markdown)
            
        Returns:
            Exported queries
        """
        if format == "json":
            return json.dumps(self.list_queries(), indent=2)
            
        elif format == "cypher":
            output = []
            for q in self.queries:
                output.append(f"-- {q.id}: {q.name}")
                output.append(f"-- {q.description}")
                output.append(f"-- Parameters: {', '.join(q.parameters)}")
                output.append(q.query.strip())
                output.append("")
            return "\n".join(output)
            
        elif format == "markdown":
            output = ["# BR-KG Persisted Queries\n"]
            
            for category in self.get_categories():
                output.append(f"\n## {category.title()} Queries\n")
                
                for q in self.queries:
                    if q.category == category:
                        output.append(f"### {q.id}: {q.name}")
                        output.append(f"\n{q.description}\n")
                        output.append(f"**Parameters:** `{', '.join(q.parameters)}`\n")
                        output.append(f"**Performance Target:** {q.performance_target_ms}ms\n")
                        output.append("```cypher")
                        output.append(q.query.strip())
                        output.append("```\n")
                        
            return "\n".join(output)
            
        else:
            raise ValueError(f"Unsupported format: {format}")
            
    def validate_all_queries(self, db_session) -> Dict[str, Any]:
        """Validate all queries syntax.
        
        Args:
            db_session: Database session
            
        Returns:
            Validation results
        """
        results = {
            "valid": [],
            "invalid": [],
            "total": len(self.queries)
        }
        
        for query in self.queries:
            try:
                # Try to explain the query
                explain_query = f"EXPLAIN {query.query}"
                
                # Create dummy parameters
                dummy_params = {}
                for param in query.parameters:
                    if "year" in param:
                        dummy_params[param] = 2020
                    elif "threshold" in param or "distance" in param:
                        dummy_params[param] = 10
                    elif "frequency" in param or "relevance" in param:
                        dummy_params[param] = 1
                    elif param.endswith("_list"):
                        dummy_params[param] = ["dummy"]
                    else:
                        dummy_params[param] = "dummy"
                        
                db_session.run(explain_query, dummy_params)
                results["valid"].append(query.id)
                
            except Exception as e:
                results["invalid"].append({
                    "id": query.id,
                    "error": str(e)
                })
                
        return results
