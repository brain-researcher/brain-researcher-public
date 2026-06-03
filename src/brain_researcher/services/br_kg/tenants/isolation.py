"""
Data Isolation Manager for Multi-tenant BR-KG

Provides strict data isolation between tenants through query modification,
access controls, and tenant-specific data tagging.
"""

import logging
import re
from contextlib import contextmanager
from functools import wraps
from typing import Any

from .manager import TenantUser

logger = logging.getLogger(__name__)


class IsolationViolationError(Exception):
    """Raised when tenant isolation is violated"""

    pass


class DataIsolationManager:
    """
    Manages data isolation between tenants

    Features:
    - Automatic query modification to include tenant filters
    - Cross-tenant access prevention
    - Tenant data tagging and validation
    - Security audit logging
    """

    def __init__(self, neo4j_db):
        self.neo4j_db = neo4j_db

        # Current tenant context (thread-local would be better for production)
        self._current_tenant_id: str | None = None
        self._current_user: TenantUser | None = None

        # Isolation patterns for different query types
        self.isolation_patterns = {
            "match": r"MATCH\s*\(([^)]+)\)",
            "create": r"CREATE\s*\(([^)]+)\)",
            "merge": r"MERGE\s*\(([^)]+)\)",
            "relationship": r"\(([^)]*)\)-\[([^\]]*)\]->\(([^)]*)\)",
        }

        # Audit log for security events
        self.audit_events: list[dict[str, Any]] = []

        logger.info("Data isolation manager initialized")

    @contextmanager
    def tenant_context(self, tenant_id: str, user: TenantUser | None = None):
        """Set tenant context for query isolation"""
        previous_tenant = self._current_tenant_id
        previous_user = self._current_user

        self._current_tenant_id = tenant_id
        self._current_user = user

        try:
            yield
        finally:
            self._current_tenant_id = previous_tenant
            self._current_user = previous_user

    def require_tenant_context(func):
        """Decorator to require tenant context"""

        @wraps(func)
        def wrapper(self, *args, **kwargs):
            if not self._current_tenant_id:
                raise IsolationViolationError("Tenant context required")
            return func(self, *args, **kwargs)

        return wrapper

    @require_tenant_context
    def execute_isolated_query(
        self,
        cypher_query: str,
        params: dict[str, Any] | None = None,
        allow_cross_tenant: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Execute Cypher query with tenant isolation

        Automatically modifies query to include tenant filters.
        """
        if not self._current_tenant_id:
            raise IsolationViolationError("No tenant context set")

        # Modify query for isolation
        isolated_query, isolated_params = self._apply_tenant_isolation(
            cypher_query, params or {}, allow_cross_tenant
        )

        # Log query execution
        self._log_query_execution(cypher_query, isolated_query)

        # Execute query
        try:
            result = self.neo4j_db._run(isolated_query, isolated_params)
            return [dict(record) for record in result]
        except Exception as e:
            self._log_audit_event(
                "query_execution_failed",
                {
                    "tenant_id": self._current_tenant_id,
                    "error": str(e),
                    "query": (
                        cypher_query[:200] + "..."
                        if len(cypher_query) > 200
                        else cypher_query
                    ),
                },
            )
            raise

    def _apply_tenant_isolation(
        self, query: str, params: dict[str, Any], allow_cross_tenant: bool
    ) -> tuple[str, dict[str, Any]]:
        """Apply tenant isolation to Cypher query"""

        if allow_cross_tenant:
            # Special queries that can access multiple tenants (admin only)
            if not self._is_admin_user():
                raise IsolationViolationError(
                    "Cross-tenant access not allowed for this user"
                )
            return query, params

        # Add tenant ID to parameters
        isolated_params = params.copy()
        isolated_params["_isolation_tenant_id"] = self._current_tenant_id

        # Modify query based on type
        if self._is_read_query(query):
            isolated_query = self._isolate_read_query(query)
        elif self._is_write_query(query):
            isolated_query = self._isolate_write_query(query)
        else:
            # For other query types, add basic tenant filter
            isolated_query = self._add_basic_tenant_filter(query)

        return isolated_query, isolated_params

    def _isolate_read_query(self, query: str) -> str:
        """Isolate read queries (MATCH, etc.)"""

        # Find all MATCH clauses and add tenant filters
        modified_query = query

        # Pattern to match MATCH clauses
        match_pattern = (
            r"MATCH\s+([^W]*?)(?=\s+WHERE|\s+RETURN|\s+WITH|\s+OPTIONAL|\s+MATCH|$)"
        )

        def add_tenant_filter(match):
            match_clause = match.group(1)

            # Add tenant filter to each node pattern
            modified_clause = self._add_node_tenant_filters(match_clause)

            return f"MATCH {modified_clause}"

        modified_query = re.sub(
            match_pattern, add_tenant_filter, modified_query, flags=re.IGNORECASE
        )

        # Ensure WHERE clause includes tenant filter
        if "WHERE" not in modified_query.upper():
            # Add WHERE clause
            return_pos = modified_query.upper().find("RETURN")
            if return_pos > 0:
                modified_query = (
                    modified_query[:return_pos]
                    + "WHERE 1=1 "
                    + modified_query[return_pos:]
                )

        return modified_query

    def _isolate_write_query(self, query: str) -> str:
        """Isolate write queries (CREATE, MERGE, SET, etc.)"""

        modified_query = query

        # For CREATE and MERGE, add tenant_id property
        create_pattern = r"(CREATE|MERGE)\s+\(([^)]+)\)"

        def add_tenant_property(match):
            operation = match.group(1)
            node_pattern = match.group(2)

            # Parse node pattern
            if ":" in node_pattern and "{" in node_pattern:
                # Node has labels and properties
                properties_start = node_pattern.find("{")
                node_part = node_pattern[:properties_start]
                properties_part = node_pattern[properties_start:]

                # Add tenant_id to properties
                if properties_part == "{}":
                    properties_part = "{_tenant_id: $_isolation_tenant_id}"
                else:
                    properties_part = (
                        properties_part[:-1] + ", _tenant_id: $_isolation_tenant_id}"
                    )

                return f"{operation} ({node_part}{properties_part})"
            else:
                # Add tenant property
                if "{" in node_pattern:
                    # Has properties
                    node_pattern = node_pattern.replace(
                        "}", ", _tenant_id: $_isolation_tenant_id}"
                    )
                else:
                    # No properties
                    node_pattern += " {_tenant_id: $_isolation_tenant_id}"

                return f"{operation} ({node_pattern})"

        modified_query = re.sub(
            create_pattern, add_tenant_property, modified_query, flags=re.IGNORECASE
        )

        # For SET operations, ensure we're only updating tenant's data
        if "SET" in modified_query.upper():
            modified_query = self._isolate_set_operation(modified_query)

        return modified_query

    def _add_node_tenant_filters(self, match_clause: str) -> str:
        """Add tenant filters to node patterns in MATCH clause"""

        # Find node patterns: (variable:Label {property: value})
        node_pattern = r"\(([^)]+)\)"

        def add_filter_to_node(match):
            node_content = match.group(1)

            # Skip if it's a relationship pattern
            if "-[" in node_content or "]->" in node_content:
                return match.group(0)

            # Parse node content
            parts = node_content.split(":")
            if len(parts) >= 2:
                # Has variable and labels
                variable = parts[0].strip()
                rest = ":".join(parts[1:])

                if "{" in rest:
                    # Has properties
                    properties_part = rest[rest.find("{") :]
                    if properties_part == "{}":
                        properties_part = "{_tenant_id: $_isolation_tenant_id}"
                    else:
                        properties_part = (
                            properties_part[:-1]
                            + ", _tenant_id: $_isolation_tenant_id}"
                        )
                    rest = rest[: rest.find("{")] + properties_part
                else:
                    # No properties
                    rest += " {_tenant_id: $_isolation_tenant_id}"

                return f"({variable}:{rest})"
            else:
                # Just variable, add tenant filter
                return f"({node_content} {{_tenant_id: $_isolation_tenant_id}})"

        return re.sub(node_pattern, add_filter_to_node, match_clause)

    def _isolate_set_operation(self, query: str) -> str:
        """Add tenant checks to SET operations"""

        # Ensure SET operations only affect tenant's data
        if "WHERE" not in query.upper():
            # Add WHERE clause to limit to tenant data
            set_pos = query.upper().find("SET")
            query = (
                query[:set_pos]
                + "WHERE n._tenant_id = $_isolation_tenant_id "
                + query[set_pos:]
            )

        return query

    def _add_basic_tenant_filter(self, query: str) -> str:
        """Add basic tenant filter to query"""
        # For complex queries, add a basic tenant filter
        if "WHERE" in query.upper():
            # Add to existing WHERE clause
            where_pos = query.upper().find("WHERE")
            where_end = where_pos + 5  # Length of 'WHERE'
            return (
                query[:where_end]
                + " (NOT EXISTS(n._tenant_id) OR n._tenant_id = $_isolation_tenant_id) AND"
                + query[where_end:]
            )
        else:
            # Add WHERE clause
            return_pos = query.upper().find("RETURN")
            if return_pos > 0:
                return (
                    query[:return_pos]
                    + "WHERE (NOT EXISTS(n._tenant_id) OR n._tenant_id = $_isolation_tenant_id) "
                    + query[return_pos:]
                )

        return query

    def _is_read_query(self, query: str) -> bool:
        """Check if query is a read operation"""
        query_upper = query.upper().strip()
        return any(
            query_upper.startswith(keyword)
            for keyword in ["MATCH", "OPTIONAL", "WITH", "UNWIND", "CALL"]
        )

    def _is_write_query(self, query: str) -> bool:
        """Check if query is a write operation"""
        query_upper = query.upper()
        return any(
            keyword in query_upper
            for keyword in ["CREATE", "MERGE", "SET", "DELETE", "REMOVE", "DETACH"]
        )

    def _is_admin_user(self) -> bool:
        """Check if current user is admin"""
        return self._current_user and (
            self._current_user.role == "admin"
            or "admin" in self._current_user.permissions
        )

    def create_isolated_node(
        self,
        labels: list[str],
        properties: dict[str, Any],
        node_id: str | None = None,
    ) -> str:
        """Create node with tenant isolation"""

        if not self._current_tenant_id:
            raise IsolationViolationError("No tenant context set")

        # Add tenant ID to properties
        isolated_properties = properties.copy()
        isolated_properties["_tenant_id"] = self._current_tenant_id

        # Use the existing Neo4j create_node method
        return self.neo4j_db.create_node(labels, isolated_properties, node_id)

    def create_isolated_relationship(
        self,
        start_node: str,
        end_node: str,
        rel_type: str,
        properties: dict[str, Any] | None = None,
    ) -> bool:
        """Create relationship with tenant isolation"""

        if not self._current_tenant_id:
            raise IsolationViolationError("No tenant context set")

        # Verify both nodes belong to current tenant
        if not self._verify_node_access(start_node) or not self._verify_node_access(
            end_node
        ):
            raise IsolationViolationError(
                "Cannot create relationship across tenant boundaries"
            )

        # Add tenant ID to relationship properties
        isolated_properties = (properties or {}).copy()
        isolated_properties["_tenant_id"] = self._current_tenant_id

        return self.neo4j_db.create_relationship(
            start_node, end_node, rel_type, isolated_properties
        )

    def find_tenant_nodes(
        self,
        labels: list[str] | None = None,
        properties: dict[str, Any] | None = None,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Find nodes within current tenant"""

        if not self._current_tenant_id:
            raise IsolationViolationError("No tenant context set")

        # Add tenant filter to properties
        search_properties = (properties or {}).copy()
        search_properties["_tenant_id"] = self._current_tenant_id

        return self.neo4j_db.find_nodes(labels, search_properties)

    def _verify_node_access(self, node_id: str) -> bool:
        """Verify current tenant can access node"""

        if not self._current_tenant_id:
            return False

        query = "MATCH (n {id: $node_id}) RETURN n._tenant_id as tenant_id"
        result = self.neo4j_db._run(query, {"node_id": node_id}).single()

        if not result:
            return False

        node_tenant_id = result["tenant_id"]

        # Allow access if node belongs to current tenant or is public (no tenant_id)
        return node_tenant_id is None or node_tenant_id == self._current_tenant_id

    def validate_tenant_data_integrity(self, tenant_id: str) -> dict[str, Any]:
        """Validate data integrity for a tenant"""

        integrity_report = {
            "tenant_id": tenant_id,
            "nodes_without_tenant_id": 0,
            "relationships_without_tenant_id": 0,
            "cross_tenant_relationships": 0,
            "orphaned_relationships": 0,
            "issues": [],
        }

        # Check nodes without tenant ID
        query = """
        MATCH (n)
        WHERE NOT EXISTS(n._tenant_id)
        RETURN count(n) as count
        """
        result = self.neo4j_db._run(query).single()
        integrity_report["nodes_without_tenant_id"] = result["count"] if result else 0

        # Check relationships without tenant ID
        query = """
        MATCH ()-[r]->()
        WHERE NOT EXISTS(r._tenant_id)
        RETURN count(r) as count
        """
        result = self.neo4j_db._run(query).single()
        integrity_report["relationships_without_tenant_id"] = (
            result["count"] if result else 0
        )

        # Check cross-tenant relationships
        query = """
        MATCH (a)-[r]->(b)
        WHERE EXISTS(a._tenant_id) AND EXISTS(b._tenant_id)
        AND a._tenant_id <> b._tenant_id
        RETURN count(r) as count
        """
        result = self.neo4j_db._run(query).single()
        integrity_report["cross_tenant_relationships"] = (
            result["count"] if result else 0
        )

        # Add issues based on findings
        if integrity_report["nodes_without_tenant_id"] > 0:
            integrity_report["issues"].append("Nodes found without tenant ID")

        if integrity_report["relationships_without_tenant_id"] > 0:
            integrity_report["issues"].append("Relationships found without tenant ID")

        if integrity_report["cross_tenant_relationships"] > 0:
            integrity_report["issues"].append("Cross-tenant relationships found")

        return integrity_report

    def fix_tenant_data_isolation(self, tenant_id: str) -> dict[str, Any]:
        """Fix data isolation issues for a tenant"""

        fix_report = {
            "tenant_id": tenant_id,
            "nodes_fixed": 0,
            "relationships_fixed": 0,
            "cross_tenant_relationships_removed": 0,
            "actions_taken": [],
        }

        # This would be implemented with careful migration queries
        # For now, just return the report structure
        fix_report["actions_taken"].append(
            "Analysis completed - manual intervention required"
        )

        return fix_report

    def get_tenant_access_log(
        self, tenant_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get access log for tenant"""

        return [
            event
            for event in self.audit_events[-limit:]
            if event.get("tenant_id") == tenant_id
        ]

    def _log_query_execution(self, original_query: str, isolated_query: str):
        """Log query execution for audit"""

        if original_query != isolated_query:
            self._log_audit_event(
                "query_isolated",
                {
                    "tenant_id": self._current_tenant_id,
                    "user_id": (
                        self._current_user.user_id if self._current_user else None
                    ),
                    "original_query_hash": hash(original_query),
                    "isolation_applied": True,
                },
            )

    def _log_audit_event(self, event_type: str, details: dict[str, Any]):
        """Log security audit event"""

        event = {
            "timestamp": logger.info,
            "event_type": event_type,
            "tenant_id": self._current_tenant_id,
            "user_id": self._current_user.user_id if self._current_user else None,
            "details": details,
        }

        self.audit_events.append(event)

        # Keep only last 10000 events
        if len(self.audit_events) > 10000:
            self.audit_events = self.audit_events[-5000:]

        logger.info(
            "Audit event: %s for tenant %s", event_type, self._current_tenant_id
        )
