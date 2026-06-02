"""
Natural Language Query Parser for BR-KG

This module parses natural language queries into structured filters and Cypher queries.
It uses pattern matching and NLP techniques to extract entities, date ranges, and query intent.
"""

import logging
import re
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class NLQueryParser:
    """Parse natural language queries into structured components."""

    def __init__(self):
        """Initialize the parser with domain-specific patterns."""

        # Entity patterns
        self.concept_keywords = {
            "memory": ["memory", "remembering", "recall", "recognition"],
            "attention": ["attention", "attentional", "attending", "focus"],
            "emotion": ["emotion", "emotional", "affect", "feeling"],
            "language": ["language", "linguistic", "speech", "verbal"],
            "perception": ["perception", "perceptual", "visual", "auditory"],
            "motor": ["motor", "movement", "action", "execution"],
            "executive": ["executive", "control", "inhibition", "planning"],
            "learning": ["learning", "acquisition", "training", "practice"],
        }

        # Brain region patterns
        self.region_patterns = {
            "frontal": ["frontal", "pfc", "prefrontal", "dlpfc", "vmpfc", "ofc"],
            "parietal": ["parietal", "ips", "spl", "ipl"],
            "temporal": ["temporal", "stg", "mtg", "itg", "hippocampus", "amygdala"],
            "occipital": ["occipital", "visual", "v1", "v2", "v4"],
            "cingulate": ["cingulate", "acc", "pcc", "mcc"],
            "basal ganglia": ["basal ganglia", "striatum", "caudate", "putamen"],
            "cerebellum": ["cerebellum", "cerebellar"],
            "thalamus": ["thalamus", "thalamic"],
        }

        # Task patterns
        self.task_patterns = {
            "n-back": ["n-back", "nback", "2-back", "3-back"],
            "stroop": ["stroop"],
            "go/no-go": ["go/no-go", "go no go", "gonogo"],
            "oddball": ["oddball"],
            "flanker": ["flanker"],
            "wisconsin": ["wisconsin", "card sorting", "wcst"],
            "resting state": ["resting state", "rest", "rs-fmri"],
        }

        # Date patterns
        self.year_pattern = re.compile(r"\b(19|20)\d{2}\b")
        self.year_range_pattern = re.compile(r"\b(19|20)\d{2}\s*[-–]\s*(19|20)\d{2}\b")
        self.recent_patterns = ["recent", "latest", "new", "current"]
        self.time_ranges = {
            "last 5 years": 5,
            "last decade": 10,
            "past 5 years": 5,
            "past decade": 10,
        }

        # Query type indicators
        self.query_types = {
            "papers": ["papers", "studies", "articles", "publications"],
            "authors": ["authors", "researchers", "scientists"],
            "datasets": ["datasets", "data", "neuroimaging data"],
            "brain regions": ["brain regions", "regions", "areas"],
            "tasks": ["tasks", "paradigms", "experiments"],
            "concepts": ["concepts", "cognitive functions", "processes"],
        }

    def parse(self, query: str) -> dict[str, Any]:
        """
        Parse a natural language query into structured components.

        Args:
            query: Natural language query string

        Returns:
            Dictionary containing:
                - entity_type: Primary entity type being searched
                - filters: Extracted filters (concepts, regions, tasks, etc.)
                - date_range: Tuple of (start_year, end_year) if specified
                - cypher: Generated Cypher query
                - confidence: Confidence score for the parse
                - original_query: The original query string
        """
        query_lower = query.lower()

        # Determine query type
        entity_type = self._detect_entity_type(query_lower)

        # Extract filters
        filters = {
            "concepts": self._extract_concepts(query_lower),
            "regions": self._extract_regions(query_lower),
            "tasks": self._extract_tasks(query_lower),
            "authors": self._extract_authors(query),  # Use original case
            "keywords": self._extract_keywords(query_lower),
        }

        # Extract date range
        date_range = self._extract_date_range(query_lower)

        # Generate Cypher query
        cypher = self._generate_cypher(entity_type, filters, date_range)

        # Calculate confidence
        confidence = self._calculate_confidence(filters, date_range)

        return {
            "entity_type": entity_type,
            "filters": {k: v for k, v in filters.items() if v},  # Remove empty filters
            "date_range": date_range,
            "cypher": cypher,
            "confidence": confidence,
            "original_query": query,
            "parsed_entities": self._get_parsed_entities_summary(filters),
        }

    def _detect_entity_type(self, query: str) -> str:
        """Detect the primary entity type being searched."""
        for entity_type, keywords in self.query_types.items():
            for keyword in keywords:
                if keyword in query:
                    return entity_type.replace(" ", "_")

        # Default to papers/studies
        return "papers"

    def _extract_concepts(self, query: str) -> list[str]:
        """Extract cognitive concepts from the query."""
        concepts = []

        for concept, keywords in self.concept_keywords.items():
            for keyword in keywords:
                if keyword in query:
                    concepts.append(concept)
                    break

        return list(set(concepts))

    def _extract_regions(self, query: str) -> list[str]:
        """Extract brain regions from the query."""
        regions = []

        for region, patterns in self.region_patterns.items():
            for pattern in patterns:
                if pattern in query:
                    regions.append(region)
                    break

        return list(set(regions))

    def _extract_tasks(self, query: str) -> list[str]:
        """Extract experimental tasks from the query."""
        tasks = []

        for task, patterns in self.task_patterns.items():
            for pattern in patterns:
                if pattern in query:
                    tasks.append(task)
                    break

        return list(set(tasks))

    def _extract_authors(self, query: str) -> list[str]:
        """Extract author names (preserving case)."""
        # Simple heuristic: look for capitalized words that might be names
        # This is a simplified version - could be enhanced with NER
        potential_names = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", query)

        # Filter out common words that aren't names
        common_words = {"Study", "Paper", "Brain", "Task", "Using", "The", "And", "For"}
        authors = [name for name in potential_names if name not in common_words]

        return authors

    def _extract_keywords(self, query: str) -> list[str]:
        """Extract general keywords not captured by other extractors."""
        # Remove common words and already extracted entities
        stopwords = {
            "the",
            "a",
            "an",
            "and",
            "or",
            "but",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "with",
            "by",
            "from",
            "as",
            "is",
            "was",
            "are",
            "were",
            "been",
            "be",
            "have",
            "has",
            "had",
            "about",
            "using",
        }

        words = query.split()
        keywords = []

        for word in words:
            # Clean and check word
            cleaned = re.sub(r"[^\w\s-]", "", word)
            if (
                len(cleaned) > 2
                and cleaned not in stopwords
                and not any(cleaned in v for v in self.concept_keywords.values())
                and not any(cleaned in v for v in self.region_patterns.values())
            ):
                keywords.append(cleaned)

        return list(set(keywords))[:5]  # Limit to top 5 keywords

    def _extract_date_range(self, query: str) -> tuple[int, int] | None:
        """Extract date range from the query."""
        current_year = datetime.now().year

        # Check for year range pattern (e.g., "2020-2023")
        range_match = self.year_range_pattern.search(query)
        if range_match:
            start_year = int(range_match.group(1))
            end_year = int(range_match.group(2))
            return (start_year, end_year)

        # Check for relative time ranges
        for phrase, years_back in self.time_ranges.items():
            if phrase in query:
                return (current_year - years_back, current_year)

        # Check for "recent" keywords
        if any(pattern in query for pattern in self.recent_patterns):
            return (current_year - 5, current_year)

        # Check for single year
        year_matches = self.year_pattern.findall(query)
        if year_matches:
            if len(year_matches) == 1:
                year = int(year_matches[0])
                return (year, year)
            else:
                # Multiple years - use as range
                years = [int(y) for y in year_matches]
                return (min(years), max(years))

        return None

    def _generate_cypher(
        self, entity_type: str, filters: dict, date_range: tuple[int, int] | None
    ) -> str:
        """Generate a Cypher query based on extracted components."""

        if entity_type == "papers":
            return self._generate_paper_query(filters, date_range)
        elif entity_type == "authors":
            return self._generate_author_query(filters)
        elif entity_type == "datasets":
            return self._generate_dataset_query(filters)
        elif entity_type == "brain_regions":
            return self._generate_region_query(filters)
        elif entity_type == "tasks":
            return self._generate_task_query(filters)
        else:
            return self._generate_concept_query(filters)

    def _generate_paper_query(
        self, filters: dict, date_range: tuple[int, int] | None
    ) -> str:
        """Generate Cypher query for papers/studies."""
        query_parts = ["MATCH (s:Study)"]
        where_clauses = []

        # Add concept filters
        if filters.get("concepts"):
            query_parts.append("MATCH (s)-[:MENTIONS_CONCEPT]->(c:Concept)")
            concept_conditions = " OR ".join(
                [f"c.name =~ '(?i).*{concept}.*'" for concept in filters["concepts"]]
            )
            where_clauses.append(f"({concept_conditions})")

        # Add task filters
        if filters.get("tasks"):
            query_parts.append("MATCH (s)-[:USES_TASK]->(t:Task)")
            task_conditions = " OR ".join(
                [f"t.name =~ '(?i).*{task}.*'" for task in filters["tasks"]]
            )
            where_clauses.append(f"({task_conditions})")

        # Add region filters via coordinates
        if filters.get("regions"):
            query_parts.append(
                "MATCH (s)-[:HAS_COORDINATE]->(coord:Coordinate)-[:LOCATED_IN]->(r:BrainRegion)"
            )
            region_conditions = " OR ".join(
                [f"r.name =~ '(?i).*{region}.*'" for region in filters["regions"]]
            )
            where_clauses.append(f"({region_conditions})")

        # Add date range filter
        if date_range:
            where_clauses.append(
                f"s.year >= {date_range[0]} AND s.year <= {date_range[1]}"
            )

        # Add keyword filters
        if filters.get("keywords"):
            keyword_conditions = []
            for keyword in filters["keywords"]:
                keyword_conditions.append(
                    f"(s.title =~ '(?i).*{keyword}.*' OR s.abstract =~ '(?i).*{keyword}.*')"
                )
            where_clauses.append(f"({' OR '.join(keyword_conditions)})")

        # Combine query
        if where_clauses:
            query_parts.append(f"WHERE {' AND '.join(where_clauses)}")

        query_parts.append("RETURN DISTINCT s")
        query_parts.append("ORDER BY s.year DESC")
        query_parts.append("LIMIT 100")

        return "\n".join(query_parts)

    def _generate_author_query(self, filters: dict) -> str:
        """Generate Cypher query for authors."""
        query_parts = ["MATCH (a:Author)"]
        where_clauses = []

        if filters.get("authors"):
            author_conditions = " OR ".join(
                [f"a.name =~ '(?i).*{author}.*'" for author in filters["authors"]]
            )
            where_clauses.append(f"({author_conditions})")

        if filters.get("concepts"):
            query_parts.append(
                "MATCH (a)-[:STUDIES]->(s:Study)-[:MENTIONS_CONCEPT]->(c:Concept)"
            )
            concept_conditions = " OR ".join(
                [f"c.name =~ '(?i).*{concept}.*'" for concept in filters["concepts"]]
            )
            where_clauses.append(f"({concept_conditions})")

        if where_clauses:
            query_parts.append(f"WHERE {' AND '.join(where_clauses)}")

        query_parts.append("RETURN DISTINCT a")
        query_parts.append("LIMIT 50")

        return "\n".join(query_parts)

    def _generate_dataset_query(self, filters: dict) -> str:
        """Generate Cypher query for datasets."""
        query_parts = ["MATCH (d:Dataset)"]
        where_clauses = []

        if filters.get("tasks"):
            query_parts.append("MATCH (d)-[:HAS_TASK]->(t:Task)")
            task_conditions = " OR ".join(
                [f"t.name =~ '(?i).*{task}.*'" for task in filters["tasks"]]
            )
            where_clauses.append(f"({task_conditions})")

        if where_clauses:
            query_parts.append(f"WHERE {' AND '.join(where_clauses)}")

        query_parts.append("RETURN DISTINCT d")
        query_parts.append("LIMIT 50")

        return "\n".join(query_parts)

    def _generate_region_query(self, filters: dict) -> str:
        """Generate Cypher query for brain regions."""
        query_parts = ["MATCH (r:BrainRegion)"]
        where_clauses = []

        if filters.get("regions"):
            region_conditions = " OR ".join(
                [f"r.name =~ '(?i).*{region}.*'" for region in filters["regions"]]
            )
            where_clauses.append(f"({region_conditions})")

        if where_clauses:
            query_parts.append(f"WHERE {' AND '.join(where_clauses)}")

        query_parts.append("RETURN DISTINCT r")
        query_parts.append("LIMIT 50")

        return "\n".join(query_parts)

    def _generate_task_query(self, filters: dict) -> str:
        """Generate Cypher query for tasks."""
        query_parts = ["MATCH (t:Task)"]
        where_clauses = []

        if filters.get("tasks"):
            task_conditions = " OR ".join(
                [f"t.name =~ '(?i).*{task}.*'" for task in filters["tasks"]]
            )
            where_clauses.append(f"({task_conditions})")

        if where_clauses:
            query_parts.append(f"WHERE {' AND '.join(where_clauses)}")

        query_parts.append("RETURN DISTINCT t")
        query_parts.append("LIMIT 50")

        return "\n".join(query_parts)

    def _generate_concept_query(self, filters: dict) -> str:
        """Generate Cypher query for concepts."""
        query_parts = ["MATCH (c:Concept)"]
        where_clauses = []

        if filters.get("concepts"):
            concept_conditions = " OR ".join(
                [f"c.name =~ '(?i).*{concept}.*'" for concept in filters["concepts"]]
            )
            where_clauses.append(f"({concept_conditions})")

        if where_clauses:
            query_parts.append(f"WHERE {' AND '.join(where_clauses)}")

        query_parts.append("RETURN DISTINCT c")
        query_parts.append("LIMIT 50")

        return "\n".join(query_parts)

    def _calculate_confidence(
        self, filters: dict, date_range: tuple[int, int] | None
    ) -> float:
        """Calculate confidence score for the parse."""
        confidence = 0.5  # Base confidence

        # Increase confidence for each type of filter found
        if filters.get("concepts"):
            confidence += 0.1 * min(len(filters["concepts"]), 2)
        if filters.get("regions"):
            confidence += 0.1 * min(len(filters["regions"]), 2)
        if filters.get("tasks"):
            confidence += 0.15
        if filters.get("authors"):
            confidence += 0.1
        if date_range:
            confidence += 0.1

        return min(confidence, 1.0)

    def _get_parsed_entities_summary(self, filters: dict) -> str:
        """Generate a human-readable summary of parsed entities."""
        parts = []

        if filters.get("concepts"):
            parts.append(f"Concepts: {', '.join(filters['concepts'])}")
        if filters.get("regions"):
            parts.append(f"Brain regions: {', '.join(filters['regions'])}")
        if filters.get("tasks"):
            parts.append(f"Tasks: {', '.join(filters['tasks'])}")
        if filters.get("authors"):
            parts.append(f"Authors: {', '.join(filters['authors'])}")

        return "; ".join(parts) if parts else "No specific entities detected"


# Example usage
if __name__ == "__main__":
    parser = NLQueryParser()

    # Test queries
    test_queries = [
        "working memory papers in frontal cortex from 2020-2023",
        "recent studies on attention and stroop task",
        "papers by Smith about emotion in amygdala",
        "resting state fMRI datasets",
        "brain regions involved in language processing",
    ]

    for query in test_queries:
        print(f"\nQuery: {query}")
        result = parser.parse(query)
        print(f"Entity type: {result['entity_type']}")
        print(f"Filters: {result['filters']}")
        print(f"Date range: {result['date_range']}")
        print(f"Confidence: {result['confidence']:.2f}")
        print(f"Summary: {result['parsed_entities']}")
        print(f"\nCypher:\n{result['cypher']}")
        print("-" * 80)
