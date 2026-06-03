"""Ontology validation and consistency checking."""

from collections import defaultdict
from typing import Any

import networkx as nx


class OntologyValidator:
    """Validator for ontology consistency."""

    def __init__(self):
        self.errors = []
        self.warnings = []
        self.stats = {}

    def check_hierarchy_cycles(self, ontology: nx.DiGraph) -> bool:
        """Check for cycles in is-a relationships.

        Args:
            ontology: Directed graph representing ontology

        Returns:
            True if no cycles found
        """
        try:
            cycles = list(nx.simple_cycles(ontology))

            if cycles:
                for cycle in cycles:
                    self.errors.append(
                        {
                            "type": "CYCLE_DETECTED",
                            "message": f"Cycle found in hierarchy: {' -> '.join(map(str, cycle + [cycle[0]]))}",
                            "nodes": cycle,
                        }
                    )
                return False

            return True

        except Exception as e:
            self.errors.append(
                {
                    "type": "VALIDATION_ERROR",
                    "message": f"Error checking cycles: {str(e)}",
                }
            )
            return False

    def validate_domain_range(
        self, ontology: nx.DiGraph, properties: dict[str, dict[str, Any]]
    ) -> bool:
        """Validate domain and range constraints.

        Args:
            ontology: Ontology graph
            properties: Property definitions with domain/range

        Returns:
            True if all constraints satisfied
        """
        valid = True

        for prop_name, prop_def in properties.items():
            domain = prop_def.get("domain")
            range_type = prop_def.get("range")

            # Check domain exists
            if domain and domain not in ontology:
                self.errors.append(
                    {
                        "type": "DOMAIN_NOT_FOUND",
                        "message": f"Domain '{domain}' not found for property '{prop_name}'",
                        "property": prop_name,
                    }
                )
                valid = False

            # Check range exists
            if range_type and range_type not in ontology:
                # Check if it's a datatype
                if range_type not in ["string", "integer", "float", "boolean", "date"]:
                    self.errors.append(
                        {
                            "type": "RANGE_NOT_FOUND",
                            "message": f"Range '{range_type}' not found for property '{prop_name}'",
                            "property": prop_name,
                        }
                    )
                    valid = False

        return valid

    def check_cardinality_constraints(
        self,
        instances: dict[str, dict[str, Any]],
        properties: dict[str, dict[str, Any]],
    ) -> bool:
        """Check cardinality constraints on instances.

        Args:
            instances: Instance data
            properties: Property definitions with cardinality

        Returns:
            True if all constraints satisfied
        """
        valid = True

        for instance_id, instance_data in instances.items():
            for prop_name, prop_def in properties.items():
                min_card = prop_def.get("min_cardinality", 0)
                max_card = prop_def.get("max_cardinality", float("inf"))

                # Count property occurrences
                prop_values = instance_data.get(prop_name, [])
                if not isinstance(prop_values, list):
                    prop_values = [prop_values]

                count = len(prop_values)

                if count < min_card:
                    self.errors.append(
                        {
                            "type": "MIN_CARDINALITY_VIOLATION",
                            "message": f"Instance '{instance_id}' has {count} values for '{prop_name}', minimum is {min_card}",
                            "instance": instance_id,
                            "property": prop_name,
                        }
                    )
                    valid = False

                if count > max_card:
                    self.errors.append(
                        {
                            "type": "MAX_CARDINALITY_VIOLATION",
                            "message": f"Instance '{instance_id}' has {count} values for '{prop_name}', maximum is {max_card}",
                            "instance": instance_id,
                            "property": prop_name,
                        }
                    )
                    valid = False

        return valid

    def check_orphaned_concepts(self, ontology: nx.DiGraph) -> bool:
        """Check for orphaned concepts (unreachable from root).

        Args:
            ontology: Ontology graph

        Returns:
            True if no orphans found
        """
        # Find root nodes (no incoming edges)
        roots = [n for n in ontology.nodes() if ontology.in_degree(n) == 0]

        if not roots:
            self.warnings.append(
                {"type": "NO_ROOT", "message": "No root concept found in ontology"}
            )
            return True

        # Find all reachable nodes from roots
        reachable = set()
        for root in roots:
            reachable.update(nx.descendants(ontology, root))
            reachable.add(root)

        # Find orphaned nodes
        all_nodes = set(ontology.nodes())
        orphans = all_nodes - reachable

        if orphans:
            self.warnings.append(
                {
                    "type": "ORPHANED_CONCEPTS",
                    "message": f"Found {len(orphans)} orphaned concepts",
                    "concepts": list(orphans),
                }
            )

        return len(orphans) == 0

    def check_unique_uris(self, concepts: dict[str, dict[str, Any]]) -> bool:
        """Check that all concepts have unique URIs.

        Args:
            concepts: Concept definitions

        Returns:
            True if all URIs are unique
        """
        uri_to_concepts = defaultdict(list)

        for concept_id, concept_data in concepts.items():
            uri = concept_data.get("uri", concept_id)
            uri_to_concepts[uri].append(concept_id)

        duplicates = {
            uri: concepts
            for uri, concepts in uri_to_concepts.items()
            if len(concepts) > 1
        }

        if duplicates:
            for uri, concepts in duplicates.items():
                self.errors.append(
                    {
                        "type": "DUPLICATE_URI",
                        "message": f"URI '{uri}' used by multiple concepts: {concepts}",
                        "uri": uri,
                        "concepts": concepts,
                    }
                )
            return False

        return True

    def validate_transitivity(self, ontology: nx.DiGraph) -> bool:
        """Check transitivity of is-a relationships.

        Args:
            ontology: Ontology graph

        Returns:
            True if transitivity holds
        """
        valid = True

        # For each node, check if all ancestors are properly connected
        for node in ontology.nodes():
            ancestors = nx.ancestors(ontology, node)

            for ancestor in ancestors:
                # Check if there's a path from ancestor to node
                if not nx.has_path(ontology, ancestor, node):
                    self.errors.append(
                        {
                            "type": "TRANSITIVITY_VIOLATION",
                            "message": f"No path from ancestor '{ancestor}' to '{node}'",
                            "ancestor": ancestor,
                            "descendant": node,
                        }
                    )
                    valid = False

        return valid

    def validate_ontology(
        self,
        ontology: nx.DiGraph,
        concepts: dict[str, dict[str, Any]],
        properties: dict[str, dict[str, Any]] | None = None,
        instances: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Perform complete ontology validation.

        Args:
            ontology: Ontology graph
            concepts: Concept definitions
            properties: Property definitions
            instances: Instance data

        Returns:
            Validation report
        """
        self.errors = []
        self.warnings = []
        self.stats = {
            "concepts": len(concepts),
            "relations": ontology.number_of_edges(),
            "properties": len(properties) if properties else 0,
            "instances": len(instances) if instances else 0,
        }

        # Run validation checks
        checks_passed = []

        checks_passed.append(self.check_hierarchy_cycles(ontology))
        checks_passed.append(self.check_orphaned_concepts(ontology))
        checks_passed.append(self.check_unique_uris(concepts))
        checks_passed.append(self.validate_transitivity(ontology))

        if properties:
            checks_passed.append(self.validate_domain_range(ontology, properties))

        if properties and instances:
            checks_passed.append(
                self.check_cardinality_constraints(instances, properties)
            )

        # Check for deprecated concepts
        deprecated = [
            c for c, data in concepts.items() if data.get("deprecated", False)
        ]
        if deprecated:
            self.warnings.append(
                {
                    "type": "DEPRECATED_CONCEPTS",
                    "message": f"Found {len(deprecated)} deprecated concepts in use",
                    "concepts": deprecated,
                }
            )

        return {
            "consistency": all(checks_passed),
            "errors": self.errors,
            "warnings": self.warnings,
            "stats": self.stats,
        }
