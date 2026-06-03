"""
Schema Mapper Agent for Natural Language Query Processing

Maps parsed query entities to graph schema elements.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .parser_agent import EntityType, ExtractedEntity, ParsedQuery

logger = logging.getLogger(__name__)


class NodeType(str, Enum):
    """Graph node types in BR-KG schema"""

    BRAIN_REGION = "BrainRegion"
    STUDY = "Study"
    DATASET = "Dataset"
    TASK = "Task"
    SUBJECT = "Subject"
    ACTIVATION = "Activation"
    COORDINATE = "Coordinate"
    GENE = "Gene"
    DISORDER = "Disorder"
    DRUG = "Drug"
    PUBLICATION = "Publication"
    AUTHOR = "Author"


class RelationType(str, Enum):
    """Graph relationship types in BR-KG schema"""

    ACTIVATES = "ACTIVATES"
    LOCATED_IN = "LOCATED_IN"
    PART_OF = "PART_OF"
    CONNECTED_TO = "CONNECTED_TO"
    ASSOCIATED_WITH = "ASSOCIATED_WITH"
    HAS_DISORDER = "HAS_DISORDER"
    PUBLISHED = "PUBLISHED"
    AUTHORED_BY = "AUTHORED_BY"
    USES_TASK = "USES_TASK"
    FROM_DATASET = "FROM_DATASET"
    TARGETS = "TARGETS"
    EXPRESSES = "EXPRESSES"


@dataclass
class GraphPattern:
    """A graph pattern for querying"""

    pattern_id: str
    nodes: list[dict[str, Any]]  # Node specifications
    relationships: list[dict[str, Any]]  # Relationship specifications
    pattern_string: str  # Cypher-like pattern
    confidence: float


@dataclass
class MappedQuery:
    """Result of mapping parsed query to graph schema"""

    parsed_query: ParsedQuery
    graph_patterns: list[GraphPattern]
    node_filters: dict[str, list[dict[str, Any]]]  # Filters per node
    relationship_filters: dict[str, list[dict[str, Any]]]  # Filters per relationship
    constraints: list[dict[str, Any]]
    projections: list[str]  # What to return
    confidence_score: float


class SchemaMapperAgent:
    """
    Agent responsible for mapping parsed entities to graph schema.

    Converts natural language entities and intents into:
    - Graph node types
    - Relationship patterns
    - Property filters
    - Traversal paths
    """

    # Entity to node type mapping
    ENTITY_NODE_MAPPING = {
        EntityType.BRAIN_REGION: NodeType.BRAIN_REGION,
        EntityType.COGNITIVE_TASK: NodeType.TASK,
        EntityType.DATASET: NodeType.DATASET,
        EntityType.STUDY: NodeType.STUDY,
        EntityType.AUTHOR: NodeType.AUTHOR,
        EntityType.DISORDER: NodeType.DISORDER,
        EntityType.GENE: NodeType.GENE,
        EntityType.DRUG: NodeType.DRUG,
        EntityType.COORDINATE: NodeType.COORDINATE,
    }

    # Common query patterns
    QUERY_PATTERNS = {
        "activation_in_region": {
            "pattern": "(task:Task)-[:ACTIVATES]->(region:BrainRegion)",
            "description": "Tasks that activate a brain region",
        },
        "region_connectivity": {
            "pattern": "(r1:BrainRegion)-[:CONNECTED_TO]->(r2:BrainRegion)",
            "description": "Connectivity between brain regions",
        },
        "disorder_regions": {
            "pattern": "(disorder:Disorder)-[:ASSOCIATED_WITH]->(region:BrainRegion)",
            "description": "Brain regions associated with disorders",
        },
        "gene_expression": {
            "pattern": "(gene:Gene)-[:EXPRESSES]->(region:BrainRegion)",
            "description": "Gene expression in brain regions",
        },
        "study_activations": {
            "pattern": "(study:Study)-[:HAS_ACTIVATION]->(activation:Activation)-[:LOCATED_IN]->(region:BrainRegion)",
            "description": "Activations from studies in brain regions",
        },
        "drug_targets": {
            "pattern": "(drug:Drug)-[:TARGETS]->(gene:Gene)-[:EXPRESSES]->(region:BrainRegion)",
            "description": "Drug targets and their brain expression",
        },
    }

    def __init__(self):
        """Initialize the schema mapper agent"""
        self.schema = self._load_schema()

    def _load_schema(self) -> dict[str, Any]:
        """Load the graph schema definition"""
        return {
            "nodes": {
                NodeType.BRAIN_REGION: {
                    "properties": [
                        "name",
                        "abbreviation",
                        "volume",
                        "coordinates",
                        "atlas",
                    ],
                    "indexed": ["name", "abbreviation"],
                },
                NodeType.TASK: {
                    "properties": ["name", "domain", "paradigm", "description"],
                    "indexed": ["name", "domain"],
                },
                NodeType.STUDY: {
                    "properties": ["id", "title", "year", "doi", "pmid"],
                    "indexed": ["id", "doi", "pmid"],
                },
                NodeType.GENE: {
                    "properties": ["symbol", "name", "entrez_id", "chromosome"],
                    "indexed": ["symbol", "entrez_id"],
                },
                NodeType.DISORDER: {
                    "properties": ["name", "icd10", "doid", "category"],
                    "indexed": ["name", "icd10"],
                },
            },
            "relationships": {
                RelationType.ACTIVATES: {
                    "source": [NodeType.TASK],
                    "target": [NodeType.BRAIN_REGION],
                    "properties": ["z_score", "p_value", "cluster_size"],
                },
                RelationType.CONNECTED_TO: {
                    "source": [NodeType.BRAIN_REGION],
                    "target": [NodeType.BRAIN_REGION],
                    "properties": ["weight", "method", "correlation"],
                },
                RelationType.ASSOCIATED_WITH: {
                    "source": [NodeType.DISORDER, NodeType.GENE],
                    "target": [NodeType.BRAIN_REGION, NodeType.DISORDER],
                    "properties": ["evidence", "p_value", "effect_size"],
                },
            },
        }

    def map_to_schema(
        self, parsed_query: ParsedQuery, context: dict[str, Any] | None = None
    ) -> MappedQuery:
        """
        Map a parsed query to graph schema elements

        Args:
            parsed_query: The parsed natural language query
            context: Optional context for mapping

        Returns:
            MappedQuery with graph patterns and filters
        """
        # Map entities to nodes
        node_mappings = self._map_entities_to_nodes(parsed_query.entities)

        # Generate graph patterns based on intent and entities
        patterns = self._generate_patterns(
            parsed_query.intent, node_mappings, parsed_query.entities
        )

        # Generate filters from constraints
        node_filters, rel_filters = self._generate_filters(
            parsed_query.constraints, node_mappings
        )

        # Determine projections (what to return)
        projections = self._determine_projections(
            parsed_query.intent, node_mappings, patterns
        )

        # Calculate confidence
        confidence = self._calculate_mapping_confidence(
            node_mappings, patterns, parsed_query.confidence_score
        )

        return MappedQuery(
            parsed_query=parsed_query,
            graph_patterns=patterns,
            node_filters=node_filters,
            relationship_filters=rel_filters,
            constraints=self._map_constraints(parsed_query.constraints),
            projections=projections,
            confidence_score=confidence,
        )

    def _map_entities_to_nodes(
        self, entities: list[ExtractedEntity]
    ) -> dict[str, dict[str, Any]]:
        """Map extracted entities to graph nodes"""
        node_mappings = {}

        for i, entity in enumerate(entities):
            node_type = self.ENTITY_NODE_MAPPING.get(entity.type)

            if node_type:
                node_id = f"n{i}"
                node_mappings[node_id] = {
                    "type": node_type,
                    "entity": entity,
                    "alias": entity.type.value.lower(),
                    "properties": self._get_node_properties(entity, node_type),
                }

        return node_mappings

    def _generate_patterns(
        self,
        intent: str,
        node_mappings: dict[str, dict[str, Any]],
        entities: list[ExtractedEntity],
    ) -> list[GraphPattern]:
        """Generate graph patterns based on intent and entities"""
        patterns = []

        # Get entity types present
        entity_types = {e.type for e in entities}

        # Pattern selection based on entities present
        if EntityType.BRAIN_REGION in entity_types:
            if EntityType.COGNITIVE_TASK in entity_types:
                patterns.append(self._create_activation_pattern(node_mappings))

            if EntityType.DISORDER in entity_types:
                patterns.append(self._create_disorder_pattern(node_mappings))

            if EntityType.GENE in entity_types:
                patterns.append(self._create_gene_pattern(node_mappings))

            if len(patterns) == 0:
                # Default pattern for brain region alone
                patterns.append(self._create_region_pattern(node_mappings))

        elif EntityType.COGNITIVE_TASK in entity_types:
            patterns.append(self._create_task_pattern(node_mappings))

        elif EntityType.DATASET in entity_types or EntityType.STUDY in entity_types:
            patterns.append(self._create_study_pattern(node_mappings))

        # If no specific patterns, create a general search pattern
        if not patterns and node_mappings:
            patterns.append(self._create_general_pattern(node_mappings))

        return patterns

    def _create_activation_pattern(
        self, node_mappings: dict[str, dict[str, Any]]
    ) -> GraphPattern:
        """Create pattern for task-region activation"""
        nodes = []
        relationships = []

        # Find task and region nodes
        task_node = None
        region_node = None

        for node_id, mapping in node_mappings.items():
            if mapping["type"] == NodeType.TASK:
                task_node = node_id
                nodes.append({"id": node_id, "type": NodeType.TASK, "alias": "task"})
            elif mapping["type"] == NodeType.BRAIN_REGION:
                region_node = node_id
                nodes.append(
                    {"id": node_id, "type": NodeType.BRAIN_REGION, "alias": "region"}
                )

        if task_node and region_node:
            relationships.append(
                {
                    "type": RelationType.ACTIVATES,
                    "source": task_node,
                    "target": region_node,
                    "alias": "activation",
                }
            )

            pattern_string = f"(task:{NodeType.TASK})-[activation:{RelationType.ACTIVATES}]->(region:{NodeType.BRAIN_REGION})"
        else:
            pattern_string = f"(n:{NodeType.BRAIN_REGION})"

        return GraphPattern(
            pattern_id="activation_pattern",
            nodes=nodes,
            relationships=relationships,
            pattern_string=pattern_string,
            confidence=0.9,
        )

    def _create_disorder_pattern(
        self, node_mappings: dict[str, dict[str, Any]]
    ) -> GraphPattern:
        """Create pattern for disorder-region association"""
        nodes = []
        relationships = []
        pattern_string = ""

        disorder_node = None
        region_node = None

        for node_id, mapping in node_mappings.items():
            if mapping["type"] == NodeType.DISORDER:
                disorder_node = node_id
                nodes.append(
                    {"id": node_id, "type": NodeType.DISORDER, "alias": "disorder"}
                )
            elif mapping["type"] == NodeType.BRAIN_REGION:
                region_node = node_id
                nodes.append(
                    {"id": node_id, "type": NodeType.BRAIN_REGION, "alias": "region"}
                )

        if disorder_node and region_node:
            relationships.append(
                {
                    "type": RelationType.ASSOCIATED_WITH,
                    "source": disorder_node,
                    "target": region_node,
                    "alias": "association",
                }
            )
            pattern_string = f"(disorder:{NodeType.DISORDER})-[association:{RelationType.ASSOCIATED_WITH}]->(region:{NodeType.BRAIN_REGION})"

        return GraphPattern(
            pattern_id="disorder_pattern",
            nodes=nodes,
            relationships=relationships,
            pattern_string=pattern_string,
            confidence=0.85,
        )

    def _create_gene_pattern(
        self, node_mappings: dict[str, dict[str, Any]]
    ) -> GraphPattern:
        """Create pattern for gene expression in brain regions"""
        nodes = []
        relationships = []

        gene_node = None
        region_node = None

        for node_id, mapping in node_mappings.items():
            if mapping["type"] == NodeType.GENE:
                gene_node = node_id
                nodes.append({"id": node_id, "type": NodeType.GENE, "alias": "gene"})
            elif mapping["type"] == NodeType.BRAIN_REGION:
                region_node = node_id
                nodes.append(
                    {"id": node_id, "type": NodeType.BRAIN_REGION, "alias": "region"}
                )

        if gene_node and region_node:
            relationships.append(
                {
                    "type": RelationType.EXPRESSES,
                    "source": gene_node,
                    "target": region_node,
                    "alias": "expression",
                }
            )

            pattern_string = f"(gene:{NodeType.GENE})-[expression:{RelationType.EXPRESSES}]->(region:{NodeType.BRAIN_REGION})"
        else:
            pattern_string = f"(gene:{NodeType.GENE})"

        return GraphPattern(
            pattern_id="gene_pattern",
            nodes=nodes,
            relationships=relationships,
            pattern_string=pattern_string,
            confidence=0.8,
        )

    def _create_region_pattern(
        self, node_mappings: dict[str, dict[str, Any]]
    ) -> GraphPattern:
        """Create pattern for brain region alone"""
        nodes = []

        for node_id, mapping in node_mappings.items():
            if mapping["type"] == NodeType.BRAIN_REGION:
                nodes.append(
                    {"id": node_id, "type": NodeType.BRAIN_REGION, "alias": "region"}
                )
                break

        pattern_string = f"(region:{NodeType.BRAIN_REGION})"

        return GraphPattern(
            pattern_id="region_pattern",
            nodes=nodes,
            relationships=[],
            pattern_string=pattern_string,
            confidence=0.7,
        )

    def _create_task_pattern(
        self, node_mappings: dict[str, dict[str, Any]]
    ) -> GraphPattern:
        """Create pattern for cognitive task"""
        nodes = []

        for node_id, mapping in node_mappings.items():
            if mapping["type"] == NodeType.TASK:
                nodes.append({"id": node_id, "type": NodeType.TASK, "alias": "task"})
                break

        pattern_string = f"(task:{NodeType.TASK})"

        return GraphPattern(
            pattern_id="task_pattern",
            nodes=nodes,
            relationships=[],
            pattern_string=pattern_string,
            confidence=0.7,
        )

    def _create_study_pattern(
        self, node_mappings: dict[str, dict[str, Any]]
    ) -> GraphPattern:
        """Create pattern for study/dataset queries"""
        nodes = []
        pattern_parts = []

        for node_id, mapping in node_mappings.items():
            if mapping["type"] in [NodeType.STUDY, NodeType.DATASET]:
                nodes.append(
                    {
                        "id": node_id,
                        "type": mapping["type"],
                        "alias": mapping["type"].value.lower(),
                    }
                )
                pattern_parts.append(
                    f"({mapping['type'].value.lower()}:{mapping['type']})"
                )

        pattern_string = "-".join(pattern_parts) if pattern_parts else "(study:Study)"

        return GraphPattern(
            pattern_id="study_pattern",
            nodes=nodes,
            relationships=[],
            pattern_string=pattern_string,
            confidence=0.75,
        )

    def _create_general_pattern(
        self, node_mappings: dict[str, dict[str, Any]]
    ) -> GraphPattern:
        """Create a general search pattern"""
        nodes = []

        for node_id, mapping in node_mappings.items():
            nodes.append(
                {"id": node_id, "type": mapping["type"], "alias": f"n{node_id}"}
            )

        # Create pattern with all nodes
        if nodes:
            pattern_string = "".join(
                [f"(n{i}:{n['type']})" for i, n in enumerate(nodes)]
            )
        else:
            pattern_string = "(n)"  # Match any node

        return GraphPattern(
            pattern_id="general_pattern",
            nodes=nodes,
            relationships=[],
            pattern_string=pattern_string,
            confidence=0.5,
        )

    def _get_node_properties(
        self, entity: ExtractedEntity, node_type: NodeType
    ) -> dict[str, Any]:
        """Get property filters for a node based on the entity"""
        properties = {}

        # Set name/label property
        if node_type in self.schema["nodes"]:
            if "name" in self.schema["nodes"][node_type]["properties"]:
                properties["name"] = entity.normalized_form
            elif "symbol" in self.schema["nodes"][node_type]["properties"]:
                properties["symbol"] = entity.normalized_form
            elif "title" in self.schema["nodes"][node_type]["properties"]:
                properties["title"] = entity.text

        return properties

    def _generate_filters(
        self, constraints: list[Any], node_mappings: dict[str, dict[str, Any]]
    ) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
        """Generate property filters from constraints"""
        node_filters = {}
        rel_filters = {}

        for constraint in constraints:
            # Determine which node or relationship the constraint applies to
            if constraint.type == "numeric":
                # Numeric constraints often apply to relationships (scores, counts)
                rel_filters.setdefault("activation", []).append(
                    {
                        "property": constraint.field,
                        "operator": constraint.operator,
                        "value": constraint.value,
                    }
                )
            elif constraint.type == "temporal":
                # Temporal constraints apply to studies/datasets
                for node_id, mapping in node_mappings.items():
                    if mapping["type"] in [NodeType.STUDY, NodeType.DATASET]:
                        node_filters.setdefault(node_id, []).append(
                            {
                                "property": "year",
                                "operator": constraint.operator,
                                "value": constraint.value,
                            }
                        )

        return node_filters, rel_filters

    def _determine_projections(
        self,
        intent: str,
        node_mappings: dict[str, dict[str, Any]],
        patterns: list[GraphPattern],
    ) -> list[str]:
        """Determine what to return from the query"""
        projections = []

        # Based on intent
        if "aggregate" in intent.lower():
            projections.append("count(*)")
        elif "compare" in intent.lower():
            # Return properties for comparison
            for node_id in node_mappings:
                projections.extend([f"{node_id}.name", f"{node_id}.value"])
        else:
            # Default: return main entities
            for pattern in patterns:
                for node in pattern.nodes:
                    projections.append(f"{node['alias']}")
                for rel in pattern.relationships:
                    projections.append(f"{rel['alias']}")

        return projections if projections else ["*"]

    def _map_constraints(self, constraints: list[Any]) -> list[dict[str, Any]]:
        """Map parsed constraints to graph query constraints"""
        mapped = []

        for constraint in constraints:
            mapped.append(
                {
                    "type": constraint.type,
                    "field": constraint.field,
                    "operator": constraint.operator,
                    "value": constraint.value,
                    "confidence": constraint.confidence,
                }
            )

        return mapped

    def _calculate_mapping_confidence(
        self,
        node_mappings: dict[str, dict[str, Any]],
        patterns: list[GraphPattern],
        base_confidence: float,
    ) -> float:
        """Calculate confidence in the schema mapping"""
        confidence = base_confidence

        # Adjust based on mapping completeness
        if not node_mappings:
            confidence *= 0.5
        elif not patterns:
            confidence *= 0.7
        else:
            # Average pattern confidence
            pattern_confidence = sum(p.confidence for p in patterns) / len(patterns)
            confidence = (confidence + pattern_confidence) / 2

        return min(1.0, confidence)
