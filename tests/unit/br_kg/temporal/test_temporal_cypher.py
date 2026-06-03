"""Unit tests for temporal Cypher query language module.

This module tests the temporal query functionality including:
- Temporal filter conditions
- Query builder patterns
- Time-aware Cypher generation
- Predefined query templates
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
from typing import Dict, List, Any, Tuple

# Import the modules to test
try:
    from brain_researcher.services.br_kg.temporal.temporal_cypher import (
        TemporalCypherBuilder,
        TemporalFilter,
        TemporalOperator,
        TemporalQueryType,
        TEMPORAL_QUERY_TEMPLATES
    )
except ImportError:
    # Fallback if absolute imports don't work
    import sys
    import os
    sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
    from brain_researcher.services.br_kg.temporal.temporal_cypher import (
        TemporalCypherBuilder,
        TemporalFilter,
        TemporalOperator,
        TemporalQueryType,
        TEMPORAL_QUERY_TEMPLATES
    )


class TestTemporalFilter:
    """Test TemporalFilter class."""

    def test_at_time_condition(self):
        """Test AT_TIME temporal filter condition."""
        filter_time = datetime(2023, 1, 15, 10, 30, 0)
        temp_filter = TemporalFilter(
            operator=TemporalOperator.AT_TIME,
            entity_path="n",
            time_value=filter_time
        )

        condition, params = temp_filter.to_cypher_condition()

        assert "transaction_time_start <= $temp_at_time" in condition
        assert "transaction_time_end IS NULL OR" in condition
        assert "transaction_time_end > $temp_at_time" in condition
        assert params["temp_at_time"] == filter_time

    def test_before_condition(self):
        """Test BEFORE temporal filter condition."""
        before_time = datetime(2023, 1, 10, 12, 0, 0)
        temp_filter = TemporalFilter(
            operator=TemporalOperator.BEFORE,
            entity_path="n",
            time_value=before_time
        )

        condition, params = temp_filter.to_cypher_condition()

        assert "n.transaction_time_start < $temp_before_time" in condition
        assert params["temp_before_time"] == before_time

    def test_after_condition(self):
        """Test AFTER temporal filter condition."""
        after_time = datetime(2023, 1, 20, 14, 15, 0)
        temp_filter = TemporalFilter(
            operator=TemporalOperator.AFTER,
            entity_path="n",
            time_value=after_time
        )

        condition, params = temp_filter.to_cypher_condition()

        assert "n.transaction_time_start > $temp_after_time" in condition
        assert params["temp_after_time"] == after_time

    def test_during_condition(self):
        """Test DURING temporal filter condition."""
        start_time = datetime(2023, 1, 1, 0, 0, 0)
        end_time = datetime(2023, 1, 31, 23, 59, 59)
        temp_filter = TemporalFilter(
            operator=TemporalOperator.DURING,
            entity_path="n",
            time_range=(start_time, end_time)
        )

        condition, params = temp_filter.to_cypher_condition()

        assert "n.transaction_time_start >= $temp_during_start" in condition
        assert "n.transaction_time_start <= $temp_during_end" in condition
        assert params["temp_during_start"] == start_time
        assert params["temp_during_end"] == end_time

    def test_between_condition(self):
        """Test BETWEEN temporal filter condition."""
        start_time = datetime(2023, 2, 1, 0, 0, 0)
        end_time = datetime(2023, 2, 28, 23, 59, 59)
        temp_filter = TemporalFilter(
            operator=TemporalOperator.BETWEEN,
            entity_path="n",
            time_range=(start_time, end_time)
        )

        condition, params = temp_filter.to_cypher_condition()

        assert "n.transaction_time_start >= $temp_between_start" in condition
        assert "n.transaction_time_start <= $temp_between_end" in condition
        assert params["temp_between_start"] == start_time
        assert params["temp_between_end"] == end_time

    def test_created_condition(self):
        """Test CREATED temporal filter condition."""
        start_time = datetime(2023, 3, 1, 0, 0, 0)
        end_time = datetime(2023, 3, 15, 23, 59, 59)
        temp_filter = TemporalFilter(
            operator=TemporalOperator.CREATED,
            entity_path="n",
            time_range=(start_time, end_time)
        )

        condition, params = temp_filter.to_cypher_condition()

        assert "n.created_at >= $temp_created_start" in condition
        assert "n.created_at <= $temp_created_end" in condition
        assert params["temp_created_start"] == start_time
        assert params["temp_created_end"] == end_time

    def test_changed_condition(self):
        """Test CHANGED temporal filter condition."""
        start_time = datetime(2023, 4, 1, 0, 0, 0)
        end_time = datetime(2023, 4, 30, 23, 59, 59)
        temp_filter = TemporalFilter(
            operator=TemporalOperator.CHANGED,
            entity_path="n",
            time_range=(start_time, end_time)
        )

        condition, params = temp_filter.to_cypher_condition()

        assert "n.updated_at IS NOT NULL" in condition
        assert "n.updated_at >= $temp_changed_start" in condition
        assert "n.updated_at <= $temp_changed_end" in condition
        assert params["temp_changed_start"] == start_time
        assert params["temp_changed_end"] == end_time

    def test_deleted_condition(self):
        """Test DELETED temporal filter condition."""
        start_time = datetime(2023, 5, 1, 0, 0, 0)
        end_time = datetime(2023, 5, 31, 23, 59, 59)
        temp_filter = TemporalFilter(
            operator=TemporalOperator.DELETED,
            entity_path="n",
            time_range=(start_time, end_time)
        )

        condition, params = temp_filter.to_cypher_condition()

        assert "n.transaction_time_end IS NOT NULL" in condition
        assert "n.transaction_time_end >= $temp_deleted_start" in condition
        assert "n.transaction_time_end <= $temp_deleted_end" in condition
        assert params["temp_deleted_start"] == start_time
        assert params["temp_deleted_end"] == end_time

    def test_custom_param_prefix(self):
        """Test custom parameter prefix."""
        filter_time = datetime(2023, 1, 15, 10, 30, 0)
        temp_filter = TemporalFilter(
            operator=TemporalOperator.AT_TIME,
            entity_path="n",
            time_value=filter_time
        )

        condition, params = temp_filter.to_cypher_condition("custom")

        assert "$custom_at_time" in condition
        assert params["custom_at_time"] == filter_time

    def test_no_time_condition(self):
        """Test condition with no time specified."""
        temp_filter = TemporalFilter(
            operator=TemporalOperator.AT_TIME,
            entity_path="n"
        )

        condition, params = temp_filter.to_cypher_condition()

        assert condition == "TRUE"
        assert len(params) == 0


class TestTemporalCypherBuilder:
    """Test TemporalCypherBuilder class."""

    def test_initialization(self):
        """Test builder initialization."""
        builder = TemporalCypherBuilder()

        assert builder.query_type == TemporalQueryType.SNAPSHOT
        assert len(builder.match_patterns) == 0
        assert len(builder.temporal_filters) == 0
        assert len(builder.where_conditions) == 0
        assert len(builder.return_clauses) == 0
        assert len(builder.parameters) == 0

    def test_snapshot_at(self):
        """Test snapshot at specific time."""
        builder = TemporalCypherBuilder()
        snapshot_time = datetime(2023, 6, 15, 12, 0, 0)

        result = builder.snapshot_at(snapshot_time)

        assert result is builder  # Fluent interface
        assert builder.query_type == TemporalQueryType.SNAPSHOT
        assert len(builder.temporal_filters) == 1
        assert builder.temporal_filters[0].operator == TemporalOperator.AT_TIME
        assert builder.temporal_filters[0].time_value == snapshot_time

    def test_during_interval(self):
        """Test during time interval."""
        builder = TemporalCypherBuilder()
        start_time = datetime(2023, 1, 1, 0, 0, 0)
        end_time = datetime(2023, 1, 31, 23, 59, 59)

        result = builder.during_interval(start_time, end_time)

        assert result is builder
        assert builder.query_type == TemporalQueryType.INTERVAL
        assert len(builder.temporal_filters) == 1
        assert builder.temporal_filters[0].operator == TemporalOperator.DURING
        assert builder.temporal_filters[0].time_range == (start_time, end_time)

    def test_evolution_between(self):
        """Test evolution between times."""
        builder = TemporalCypherBuilder()
        start_time = datetime(2023, 2, 1, 0, 0, 0)
        end_time = datetime(2023, 2, 28, 23, 59, 59)

        result = builder.evolution_between(start_time, end_time)

        assert result is builder
        assert builder.query_type == TemporalQueryType.EVOLUTION
        assert len(builder.temporal_filters) == 0  # No automatic filters for evolution

    def test_match_temporal_nodes(self):
        """Test matching temporal nodes."""
        builder = TemporalCypherBuilder()
        labels = ["Person", "User"]
        properties = {"name": "John", "age": 30}

        result = builder.match_temporal_nodes(
            labels=labels,
            alias="u",
            properties=properties
        )

        assert result is builder
        assert len(builder.match_patterns) == 1

        pattern = builder.match_patterns[0]
        assert "(u:TemporalNode:`Person`:`User`)" == pattern

        # Check property filters in WHERE conditions
        assert "u.name = $u_name" in builder.where_conditions
        assert "u.age = $u_age" in builder.where_conditions
        assert builder.parameters["u_name"] == "John"
        assert builder.parameters["u_age"] == 30

        assert builder._current_entity_alias == "u"

    def test_match_temporal_nodes_no_labels(self):
        """Test matching temporal nodes without additional labels."""
        builder = TemporalCypherBuilder()

        result = builder.match_temporal_nodes(alias="n")

        assert result is builder
        assert len(builder.match_patterns) == 1
        assert "(n:TemporalNode)" == builder.match_patterns[0]

    def test_match_temporal_relationships(self):
        """Test matching temporal relationships."""
        builder = TemporalCypherBuilder()

        result = builder.match_temporal_relationships(
            relationship_type="KNOWS",
            start_alias="a",
            end_alias="b",
            rel_alias="r"
        )

        assert result is builder
        assert len(builder.match_patterns) == 1

        expected_pattern = "(a:TemporalNode)-[r:TEMPORAL_REL {type: 'KNOWS'}]->(b:TemporalNode)"
        assert builder.match_patterns[0] == expected_pattern

    def test_match_temporal_relationships_no_type(self):
        """Test matching temporal relationships without specific type."""
        builder = TemporalCypherBuilder()

        result = builder.match_temporal_relationships()

        assert result is builder
        assert len(builder.match_patterns) == 1

        expected_pattern = "(start:TemporalNode)-[r:TEMPORAL_REL]->(end:TemporalNode)"
        assert builder.match_patterns[0] == expected_pattern

    def test_where_created_during(self):
        """Test where entities created during time range."""
        builder = TemporalCypherBuilder()
        start_time = datetime(2023, 3, 1, 0, 0, 0)
        end_time = datetime(2023, 3, 31, 23, 59, 59)

        result = builder.where_created_during(start_time, end_time, "n")

        assert result is builder
        assert len(builder.temporal_filters) == 1

        temp_filter = builder.temporal_filters[0]
        assert temp_filter.operator == TemporalOperator.CREATED
        assert temp_filter.entity_path == "n"
        assert temp_filter.time_range == (start_time, end_time)

    def test_where_changed_during(self):
        """Test where entities changed during time range."""
        builder = TemporalCypherBuilder()
        start_time = datetime(2023, 4, 1, 0, 0, 0)
        end_time = datetime(2023, 4, 30, 23, 59, 59)

        result = builder.where_changed_during(start_time, end_time)

        assert result is builder
        assert len(builder.temporal_filters) == 1

        temp_filter = builder.temporal_filters[0]
        assert temp_filter.operator == TemporalOperator.CHANGED
        assert temp_filter.entity_path == "n"  # Default current entity
        assert temp_filter.time_range == (start_time, end_time)

    def test_where_deleted_during(self):
        """Test where entities deleted during time range."""
        builder = TemporalCypherBuilder()
        start_time = datetime(2023, 5, 1, 0, 0, 0)
        end_time = datetime(2023, 5, 31, 23, 59, 59)

        result = builder.where_deleted_during(start_time, end_time, "e")

        assert result is builder
        assert len(builder.temporal_filters) == 1

        temp_filter = builder.temporal_filters[0]
        assert temp_filter.operator == TemporalOperator.DELETED
        assert temp_filter.entity_path == "e"
        assert temp_filter.time_range == (start_time, end_time)

    def test_where_stable_during(self):
        """Test where entities remained stable."""
        builder = TemporalCypherBuilder()
        start_time = datetime(2023, 6, 1, 0, 0, 0)
        end_time = datetime(2023, 6, 30, 23, 59, 59)

        result = builder.where_stable_during(start_time, end_time, "s")

        assert result is builder
        assert len(builder.where_conditions) == 1

        condition = builder.where_conditions[0]
        assert "s.created_at < $stable_start_time" in condition
        assert "s.updated_at IS NULL OR s.updated_at < $stable_start_time" in condition
        assert "s.transaction_time_end IS NULL OR s.transaction_time_end > $stable_end_time" in condition

        assert builder.parameters["stable_start_time"] == start_time
        assert builder.parameters["stable_end_time"] == end_time

    def test_where_property_changed(self):
        """Test where specific property changed."""
        builder = TemporalCypherBuilder()
        start_time = datetime(2023, 7, 1, 0, 0, 0)
        end_time = datetime(2023, 7, 31, 23, 59, 59)

        result = builder.where_property_changed("name", start_time, end_time, "p")

        assert result is builder
        assert len(builder.where_conditions) == 1

        condition = builder.where_conditions[0]
        assert "EXISTS" in condition
        assert "p_old.name <> p.name" in condition

        assert builder.parameters["prop_change_start_time"] == start_time
        assert builder.parameters["prop_change_end_time"] == end_time

    def test_where_custom(self):
        """Test custom WHERE condition."""
        builder = TemporalCypherBuilder()
        custom_condition = "n.status = $status"
        custom_params = {"status": "active"}

        result = builder.where_custom(custom_condition, custom_params)

        assert result is builder
        assert custom_condition in builder.where_conditions
        assert builder.parameters["status"] == "active"

    def test_return_entities(self):
        """Test returning entities."""
        builder = TemporalCypherBuilder()

        result = builder.return_entities("n", "r", "m")

        assert result is builder
        assert "n" in builder.return_clauses
        assert "r" in builder.return_clauses
        assert "m" in builder.return_clauses

    def test_return_properties(self):
        """Test returning specific properties."""
        builder = TemporalCypherBuilder()

        result = builder.return_properties("n", "name", "age", "created_at")

        assert result is builder
        assert "n.name" in builder.return_clauses
        assert "n.age" in builder.return_clauses
        assert "n.created_at" in builder.return_clauses

    def test_return_temporal_info(self):
        """Test returning temporal information."""
        builder = TemporalCypherBuilder()

        result = builder.return_temporal_info("n")

        assert result is builder
        expected_props = [
            "n.created_at",
            "n.updated_at",
            "n.version",
            "n.transaction_time_start",
            "n.transaction_time_end",
            "n.valid_time_start",
            "n.valid_time_end"
        ]

        for prop in expected_props:
            assert prop in builder.return_clauses

    def test_return_evolution_summary(self):
        """Test returning evolution summary."""
        builder = TemporalCypherBuilder()
        start_time = datetime(2023, 8, 1, 0, 0, 0)
        end_time = datetime(2023, 8, 31, 23, 59, 59)

        result = builder.return_evolution_summary("n", start_time, end_time)

        assert result is builder
        assert len(builder.return_clauses) == 1

        summary_expr = builder.return_clauses[0]
        assert "entity_id: n.id" in summary_expr
        assert "versions_in_range:" in summary_expr
        assert "evolution_summary" in summary_expr

        assert builder.parameters["evolution_start_time"] == start_time
        assert builder.parameters["evolution_end_time"] == end_time

    def test_order_by_time(self):
        """Test ordering by time."""
        builder = TemporalCypherBuilder()

        result = builder.order_by_time("n", ascending=False)

        assert result is builder
        assert "n.transaction_time_start DESC" in builder.order_by_clauses

    def test_order_by_creation(self):
        """Test ordering by creation time."""
        builder = TemporalCypherBuilder()

        result = builder.order_by_creation("n", ascending=True)

        assert result is builder
        assert "n.created_at ASC" in builder.order_by_clauses

    def test_limit(self):
        """Test result limit."""
        builder = TemporalCypherBuilder()

        result = builder.limit(100)

        assert result is builder
        assert builder.limit_value == 100

    def test_build_simple_query(self):
        """Test building a simple query."""
        builder = TemporalCypherBuilder()
        snapshot_time = datetime(2023, 1, 15, 12, 0, 0)

        query, params = (builder
                        .snapshot_at(snapshot_time)
                        .match_temporal_nodes(["Person"])
                        .return_entities("n")
                        .limit(10)
                        .build())

        assert "MATCH (n:TemporalNode:`Person`)" in query
        assert "WHERE" in query
        assert "RETURN n" in query
        assert "LIMIT 10" in query

        # Check temporal filters were applied
        assert "temp_0_at_time" in params
        assert params["temp_0_at_time"] == snapshot_time

    def test_build_complex_query(self):
        """Test building a complex query."""
        builder = TemporalCypherBuilder()
        start_time = datetime(2023, 1, 1, 0, 0, 0)
        end_time = datetime(2023, 12, 31, 23, 59, 59)

        query, params = (builder
                        .during_interval(start_time, end_time)
                        .match_temporal_nodes(["Document"], alias="d")
                        .match_temporal_relationships("AUTHORED", "u", "d", "r")
                        .where_created_during(start_time, end_time, "d")
                        .where_custom("u.name = $author_name", {"author_name": "Alice"})
                        .return_entities("u", "d")
                        .return_temporal_info("d")
                        .order_by_creation("d", ascending=False)
                        .limit(50)
                        .build())

        assert "MATCH (d:TemporalNode:`Document`)" in query
        assert "(u:TemporalNode)-[r:TEMPORAL_REL {type: 'AUTHORED'}]->(d:TemporalNode)" in query
        assert "WHERE" in query
        assert "u.name = $author_name" in query
        assert "RETURN u, d" in query
        assert "d.created_at, d.updated_at" in query
        assert "ORDER BY d.created_at DESC" in query
        assert "LIMIT 50" in query

        # Check parameters
        assert "author_name" in params
        assert params["author_name"] == "Alice"

    def test_build_with_no_match_patterns(self):
        """Test building query without match patterns."""
        builder = TemporalCypherBuilder()

        query, params = (builder
                        .where_custom("1=1")
                        .build())

        # Should have default return
        assert "RETURN n" in query
        assert "WHERE 1=1" in query

    def test_reset(self):
        """Test resetting builder state."""
        builder = TemporalCypherBuilder()

        # Add some state
        builder.match_temporal_nodes(["Person"])
        builder.where_custom("n.age > 18")
        builder.return_entities("n")
        builder.limit(10)

        # Reset
        result = builder.reset()

        assert result is builder
        assert builder.query_type == TemporalQueryType.SNAPSHOT
        assert len(builder.match_patterns) == 0
        assert len(builder.temporal_filters) == 0
        assert len(builder.where_conditions) == 0
        assert len(builder.return_clauses) == 0
        assert len(builder.parameters) == 0
        assert builder.limit_value is None
        assert builder._current_entity_alias is None


class TestTemporalCypherTemplates:
    """Test predefined temporal query templates."""

    def test_templates_exist(self):
        """Test that required templates exist."""
        expected_templates = [
            "snapshot_at_time",
            "entities_created_during",
            "entities_changed_during",
            "entity_evolution",
            "relationship_evolution",
            "most_changed_entities",
            "temporal_pattern_match"
        ]

        for template_name in expected_templates:
            assert template_name in TEMPORAL_QUERY_TEMPLATES
            template_query = TEMPORAL_QUERY_TEMPLATES[template_name]
            assert isinstance(template_query, str)
            assert len(template_query.strip()) > 0

    def test_snapshot_template(self):
        """Test snapshot template structure."""
        template = TEMPORAL_QUERY_TEMPLATES["snapshot_at_time"]

        assert "MATCH (n:TemporalNode)" in template
        assert "transaction_time_start <=" in template
        assert "transaction_time_end IS NULL OR" in template
        assert "$snapshot_time" in template
        assert "RETURN n" in template

    def test_entities_created_template(self):
        """Test entities created template."""
        template = TEMPORAL_QUERY_TEMPLATES["entities_created_during"]

        assert "MATCH (n:TemporalNode)" in template
        assert "n.created_at >=" in template
        assert "$start_time" in template
        assert "$end_time" in template
        assert "RETURN n, n.created_at" in template
        assert "ORDER BY n.created_at DESC" in template

    def test_entity_evolution_template(self):
        """Test entity evolution template."""
        template = TEMPORAL_QUERY_TEMPLATES["entity_evolution"]

        assert "MATCH (n:TemporalNode {id: $entity_id})" in template
        assert "n.transaction_time_start >=" in template
        assert "RETURN n, n.version" in template
        assert "ORDER BY n.version ASC" in template

    def test_most_changed_entities_template(self):
        """Test most changed entities template."""
        template = TEMPORAL_QUERY_TEMPLATES["most_changed_entities"]

        assert "MATCH (n:TemporalNode)" in template
        assert "WITH n.id as entity_id, count(*) as change_count" in template
        assert "ORDER BY change_count DESC" in template
        assert "LIMIT $top_k" in template


class TestTemporalCypherIntegration:
    """Integration tests for temporal Cypher functionality."""

    def test_snapshot_query_classmethod(self):
        """Test snapshot query class method."""
        query_time = datetime(2023, 6, 15, 14, 30, 0)
        labels = ["Person", "Employee"]
        properties = {"department": "Engineering"}

        query, params = TemporalCypherBuilder.snapshot_query(
            time=query_time,
            labels=labels,
            properties=properties
        )

        assert "MATCH (n:TemporalNode:`Person`:`Employee`)" in query
        assert "WHERE" in query
        assert "RETURN n" in query

        # Check temporal filter
        assert "temp_0_at_time" in params
        assert params["temp_0_at_time"] == query_time

        # Check property filters
        assert "n_department" in params
        assert params["n_department"] == "Engineering"

    def test_evolution_query_classmethod(self):
        """Test evolution query class method."""
        entity_id = "person_123"
        start_time = datetime(2023, 1, 1, 0, 0, 0)
        end_time = datetime(2023, 12, 31, 23, 59, 59)

        query, params = TemporalCypherBuilder.evolution_query(
            entity_id=entity_id,
            start_time=start_time,
            end_time=end_time
        )

        assert "MATCH (n:TemporalNode)" in query
        assert "n.transaction_time_start >= $evolution_start" in query
        assert "n.transaction_time_start <= $evolution_end" in query
        assert "RETURN n" in query
        assert "ORDER BY n.transaction_time_start ASC" in query

        # Check parameters
        assert params["id"] == entity_id
        assert params["evolution_start"] == start_time
        assert params["evolution_end"] == end_time

    def test_change_detection_query_classmethod(self):
        """Test change detection query class method."""
        start_time = datetime(2023, 3, 1, 0, 0, 0)
        end_time = datetime(2023, 3, 31, 23, 59, 59)
        labels = ["Document"]

        query, params = TemporalCypherBuilder.change_detection_query(
            start_time=start_time,
            end_time=end_time,
            labels=labels
        )

        assert "MATCH (n:TemporalNode:`Document`)" in query
        assert "WHERE" in query
        assert "RETURN n" in query
        assert "ORDER BY n.transaction_time_start DESC" in query

        # Check temporal filters applied
        assert len([p for p in params.keys() if "during" in p]) >= 2
        assert len([p for p in params.keys() if "changed" in p]) >= 2

    def test_fluent_interface_workflow(self):
        """Test complete fluent interface workflow."""
        builder = TemporalCypherBuilder()

        # Chain multiple operations
        result = (builder
                 .snapshot_at(datetime(2023, 1, 1))
                 .match_temporal_nodes(["Person"])
                 .where_created_during(
                     datetime(2022, 1, 1),
                     datetime(2022, 12, 31)
                 )
                 .return_entities("n")
                 .return_temporal_info("n")
                 .order_by_creation("n")
                 .limit(100))

        # Should return the same builder instance
        assert result is builder

        # Build final query
        query, params = builder.build()

        # Verify complete query structure
        assert "MATCH" in query
        assert "WHERE" in query
        assert "RETURN" in query
        assert "ORDER BY" in query
        assert "LIMIT" in query

        # Verify parameters exist
        assert len(params) > 0

    def test_complex_temporal_conditions(self):
        """Test combining multiple temporal conditions."""
        builder = TemporalCypherBuilder()

        base_time = datetime(2023, 1, 15, 12, 0, 0)
        start_time = datetime(2023, 1, 1, 0, 0, 0)
        end_time = datetime(2023, 1, 31, 23, 59, 59)

        query, params = (builder
                        .snapshot_at(base_time)
                        .match_temporal_nodes(["Person"], alias="p")
                        .where_created_during(start_time, end_time, "p")
                        .where_stable_during(start_time, end_time, "p")
                        .where_custom("p.active = $active", {"active": True})
                        .return_entities("p")
                        .build())

        # Should have multiple WHERE conditions
        where_section = query[query.index("WHERE"):query.index("RETURN")]
        assert where_section.count("AND") >= 3  # Multiple conditions joined

        # Should have parameters from all conditions
        assert "temp_0_at_time" in params  # snapshot condition
        assert "temp_1_created_start" in params  # created condition
        assert "stable_start_time" in params  # stable condition
        assert "active" in params  # custom condition


if __name__ == "__main__":
    pytest.main([__file__])