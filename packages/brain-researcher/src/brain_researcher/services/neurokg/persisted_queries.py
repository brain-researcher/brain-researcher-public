"""
Persisted Query System for BR-KG
Pre-defined, optimized queries for common operations.
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum


class QueryCategory(Enum):
    """Categories of persisted queries."""
    TRAVERSAL = "traversal"
    SEARCH = "search"
    ANALYTICS = "analytics"
    EXPORT = "export"


@dataclass
class PersistedQuery:
    """Persisted query definition."""
    id: str
    name: str
    description: str
    category: QueryCategory
    query: str
    parameters: List[str]
    version: str = "1.0"
    cacheable: bool = True
    cache_ttl: int = 3600  # seconds


# Core traversal queries
QUERIES: Dict[str, PersistedQuery] = {
    "Q1_TASK_TO_REGION": PersistedQuery(
        id="Q1_TASK_TO_REGION",
        name="Task to Brain Region",
        description="Find brain regions activated by a specific task",
        category=QueryCategory.TRAVERSAL,
        query="""
        query TaskToRegion($taskId: String!) {
            tasks(name: $taskId) {
                id
                name
                regions {
                    id
                    name
                    abbreviation
                    coordinates {
                        x
                        y
                        z
                    }
                }
            }
        }
        """,
        parameters=["taskId"]
    ),
    
    "Q2_PUB_TO_COORDS": PersistedQuery(
        id="Q2_PUB_TO_COORDS",
        name="Publication to Coordinates",
        description="Get all coordinates reported in a publication",
        category=QueryCategory.TRAVERSAL,
        query="""
        query PublicationToCoordinates($pmid: String!) {
            publications(pmid: $pmid) {
                id
                pmid
                title
                coordinates {
                    x
                    y
                    z
                    region {
                        name
                        abbreviation
                    }
                }
            }
        }
        """,
        parameters=["pmid"]
    ),
    
    "Q3_CONCEPT_NETWORK": PersistedQuery(
        id="Q3_CONCEPT_NETWORK",
        name="Concept Network",
        description="Get related concepts within N hops",
        category=QueryCategory.TRAVERSAL,
        query="""
        query ConceptNetwork($conceptId: String!, $depth: Int = 2) {
            concepts(name: $conceptId) {
                id
                name
                relatedConcepts(depth: $depth) {
                    id
                    name
                    relationshipType
                    confidence
                }
            }
        }
        """,
        parameters=["conceptId", "depth"]
    ),
    
    "Q4_REGION_TASKS": PersistedQuery(
        id="Q4_REGION_TASKS",
        name="Region to Tasks",
        description="Find all tasks that activate a specific brain region",
        category=QueryCategory.TRAVERSAL,
        query="""
        query RegionToTasks($regionName: String!) {
            regions(name: $regionName) {
                id
                name
                abbreviation
                tasks {
                    id
                    name
                    concepts {
                        id
                        name
                    }
                }
            }
        }
        """,
        parameters=["regionName"]
    ),
    
    "Q5_DATASET_OVERVIEW": PersistedQuery(
        id="Q5_DATASET_OVERVIEW",
        name="Dataset Overview",
        description="Get complete overview of a dataset",
        category=QueryCategory.SEARCH,
        query="""
        query DatasetOverview($datasetId: String!) {
            datasets(accession: $datasetId) {
                id
                name
                accession
                tasks {
                    id
                    name
                }
                publications {
                    pmid
                    title
                }
                statistics {
                    subjectCount
                    scanCount
                    taskCount
                }
            }
        }
        """,
        parameters=["datasetId"]
    ),
    
    "Q6_TASK_PUBLICATIONS": PersistedQuery(
        id="Q6_TASK_PUBLICATIONS",
        name="Task Publications",
        description="Find all publications studying a specific task",
        category=QueryCategory.SEARCH,
        query="""
        query TaskPublications($taskName: String!) {
            tasks(name: $taskName) {
                id
                name
                publications {
                    id
                    pmid
                    title
                    year
                    authors
                }
            }
        }
        """,
        parameters=["taskName"]
    ),
    
    "Q7_COACTIVATION": PersistedQuery(
        id="Q7_COACTIVATION",
        name="Region Coactivation",
        description="Find regions that coactivate with a given region",
        category=QueryCategory.ANALYTICS,
        query="""
        query RegionCoactivation($regionId: String!, $threshold: Float = 0.5) {
            regions(name: $regionId) {
                id
                name
                coactivatedRegions(threshold: $threshold) {
                    id
                    name
                    coactivationScore
                    sharedTasks {
                        id
                        name
                    }
                }
            }
        }
        """,
        parameters=["regionId", "threshold"]
    ),
    
    "Q8_CONCEPT_HIERARCHY": PersistedQuery(
        id="Q8_CONCEPT_HIERARCHY",
        name="Concept Hierarchy",
        description="Get concept hierarchy (parent/child relationships)",
        category=QueryCategory.TRAVERSAL,
        query="""
        query ConceptHierarchy($conceptId: String!) {
            concepts(name: $conceptId) {
                id
                name
                parents {
                    id
                    name
                }
                children {
                    id
                    name
                }
                siblings {
                    id
                    name
                }
            }
        }
        """,
        parameters=["conceptId"]
    ),
    
    "Q9_META_ANALYSIS": PersistedQuery(
        id="Q9_META_ANALYSIS",
        name="Meta-Analysis Query",
        description="Aggregate coordinates across studies for a concept",
        category=QueryCategory.ANALYTICS,
        query="""
        query MetaAnalysis($conceptName: String!) {
            concepts(name: $conceptName) {
                id
                name
                aggregatedCoordinates {
                    x
                    y
                    z
                    frequency
                    studies {
                        pmid
                        title
                    }
                }
            }
        }
        """,
        parameters=["conceptName"]
    ),
    
    "Q10_PUBLICATION_GRAPH": PersistedQuery(
        id="Q10_PUBLICATION_GRAPH",
        name="Publication Citation Graph",
        description="Get citation network for a publication",
        category=QueryCategory.TRAVERSAL,
        query="""
        query PublicationGraph($pmid: String!, $depth: Int = 1) {
            publications(pmid: $pmid) {
                id
                pmid
                title
                cites {
                    pmid
                    title
                }
                citedBy {
                    pmid
                    title
                }
            }
        }
        """,
        parameters=["pmid", "depth"]
    ),
    
    "Q11_TASK_SIMILARITY": PersistedQuery(
        id="Q11_TASK_SIMILARITY",
        name="Similar Tasks",
        description="Find tasks similar to a given task",
        category=QueryCategory.ANALYTICS,
        query="""
        query SimilarTasks($taskName: String!, $limit: Int = 10) {
            tasks(name: $taskName) {
                id
                name
                similarTasks(limit: $limit) {
                    id
                    name
                    similarityScore
                    sharedConcepts {
                        id
                        name
                    }
                    sharedRegions {
                        id
                        name
                    }
                }
            }
        }
        """,
        parameters=["taskName", "limit"]
    ),
    
    "Q12_COORDINATE_CLUSTERS": PersistedQuery(
        id="Q12_COORDINATE_CLUSTERS",
        name="Coordinate Clusters",
        description="Find spatial clusters of activation coordinates",
        category=QueryCategory.ANALYTICS,
        query="""
        query CoordinateClusters($taskId: String, $radius: Float = 10) {
            coordinateClusters(taskId: $taskId, radius: $radius) {
                centroid {
                    x
                    y
                    z
                }
                size
                region {
                    name
                    abbreviation
                }
                tasks {
                    id
                    name
                }
            }
        }
        """,
        parameters=["taskId", "radius"]
    ),
    
    "Q13_DATASET_SEARCH": PersistedQuery(
        id="Q13_DATASET_SEARCH",
        name="Dataset Search",
        description="Search datasets by multiple criteria",
        category=QueryCategory.SEARCH,
        query="""
        query DatasetSearch($taskName: String, $minSubjects: Int, $modality: String) {
            datasets(
                filter: {
                    task: $taskName,
                    minSubjects: $minSubjects,
                    modality: $modality
                }
            ) {
                id
                name
                accession
                subjectCount
                tasks {
                    name
                }
                modalities
            }
        }
        """,
        parameters=["taskName", "minSubjects", "modality"]
    ),
    
    "Q14_ONTOLOGY_PATH": PersistedQuery(
        id="Q14_ONTOLOGY_PATH",
        name="Ontology Path",
        description="Find shortest path between two concepts in ontology",
        category=QueryCategory.TRAVERSAL,
        query="""
        query OntologyPath($concept1: String!, $concept2: String!) {
            shortestPath(from: $concept1, to: $concept2, type: "Concept") {
                path {
                    id
                    name
                }
                relationships {
                    type
                    properties
                }
                length
            }
        }
        """,
        parameters=["concept1", "concept2"]
    ),
    
    "Q15_REGION_PARCELLATION": PersistedQuery(
        id="Q15_REGION_PARCELLATION",
        name="Region Parcellation",
        description="Get parcellation hierarchy for a region",
        category=QueryCategory.TRAVERSAL,
        query="""
        query RegionParcellation($regionName: String!, $atlas: String = "AAL") {
            regions(name: $regionName) {
                id
                name
                parcellation(atlas: $atlas) {
                    parentRegion {
                        name
                    }
                    subRegions {
                        name
                        volume
                    }
                    atlas
                }
            }
        }
        """,
        parameters=["regionName", "atlas"]
    ),
    
    "Q16_TEMPORAL_EVOLUTION": PersistedQuery(
        id="Q16_TEMPORAL_EVOLUTION",
        name="Temporal Evolution",
        description="Track concept/task popularity over time",
        category=QueryCategory.ANALYTICS,
        query="""
        query TemporalEvolution($conceptName: String!, $startYear: Int, $endYear: Int) {
            concepts(name: $conceptName) {
                id
                name
                temporalTrend(startYear: $startYear, endYear: $endYear) {
                    year
                    publicationCount
                    citationCount
                    datasets {
                        count
                    }
                }
            }
        }
        """,
        parameters=["conceptName", "startYear", "endYear"]
    ),
    
    "Q17_CROSS_MODAL": PersistedQuery(
        id="Q17_CROSS_MODAL",
        name="Cross-Modal Analysis",
        description="Compare results across imaging modalities",
        category=QueryCategory.ANALYTICS,
        query="""
        query CrossModalAnalysis($taskName: String!) {
            tasks(name: $taskName) {
                id
                name
                modalityResults {
                    modality
                    regions {
                        name
                        activationStrength
                    }
                    publicationCount
                }
            }
        }
        """,
        parameters=["taskName"]
    ),
    
    "Q18_AUTHOR_NETWORK": PersistedQuery(
        id="Q18_AUTHOR_NETWORK",
        name="Author Collaboration Network",
        description="Get collaboration network for an author",
        category=QueryCategory.TRAVERSAL,
        query="""
        query AuthorNetwork($authorName: String!, $depth: Int = 2) {
            authors(name: $authorName) {
                id
                name
                collaborators(depth: $depth) {
                    id
                    name
                    sharedPublications {
                        pmid
                        title
                    }
                }
            }
        }
        """,
        parameters=["authorName", "depth"]
    ),
    
    "Q19_EVIDENCE_LINEAGE": PersistedQuery(
        id="Q19_EVIDENCE_LINEAGE",
        name="Evidence Lineage",
        description="Track evidence provenance for a claim",
        category=QueryCategory.TRAVERSAL,
        query="""
        query EvidenceLineage($claimId: String!) {
            claims(id: $claimId) {
                id
                statement
                evidence {
                    type
                    source {
                        pmid
                        title
                    }
                    confidence
                    derivedFrom {
                        id
                        type
                    }
                }
            }
        }
        """,
        parameters=["claimId"]
    ),
    
    "Q20_CONFLICT_DETECTION": PersistedQuery(
        id="Q20_CONFLICT_DETECTION",
        name="Conflict Detection",
        description="Find conflicting evidence for a relationship",
        category=QueryCategory.ANALYTICS,
        query="""
        query ConflictDetection($relationship: String!) {
            conflicts(relationship: $relationship) {
                relationship
                supportingEvidence {
                    source
                    confidence
                }
                contradictingEvidence {
                    source
                    confidence
                }
                resolution {
                    method
                    result
                }
            }
        }
        """,
        parameters=["relationship"]
    )
}


class PersistedQueryExecutor:
    """Execute persisted queries with caching and optimization."""
    
    def __init__(self, schema):
        self.schema = schema
        self.cache = {}
    
    def execute(self, query_id: str, variables: Dict[str, Any]) -> Any:
        """Execute a persisted query by ID."""
        if query_id not in QUERIES:
            raise ValueError(f"Unknown query ID: {query_id}")
        
        query = QUERIES[query_id]
        
        # Check cache if enabled
        if query.cacheable:
            cache_key = f"{query_id}:{variables}"
            if cache_key in self.cache:
                return self.cache[cache_key]
        
        # Execute query
        result = self.schema.execute_sync(query.query, variable_values=variables)
        
        # Cache result
        if query.cacheable and not result.errors:
            self.cache[cache_key] = result
        
        return result
    
    def list_queries(self, category: Optional[QueryCategory] = None) -> List[Dict[str, Any]]:
        """List available persisted queries."""
        queries = []
        for query_id, query in QUERIES.items():
            if category is None or query.category == category:
                queries.append({
                    "id": query.id,
                    "name": query.name,
                    "description": query.description,
                    "category": query.category.value,
                    "parameters": query.parameters,
                    "version": query.version
                })
        return queries
    
    def get_query(self, query_id: str) -> Optional[PersistedQuery]:
        """Get a specific persisted query definition."""
        return QUERIES.get(query_id)