#!/usr/bin/env python3
"""
Neo4j-backed Graph Database Adapter for BR-KG.

Mirrors the interface expected by ingestion components while using Neo4j as the
persistence layer. Maintains a lightweight NetworkX cache so existing code that
relies on `db.graph` continues to function.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Iterable
from typing import Any

import networkx as nx

try:
    from neo4j import Driver, GraphDatabase, Session, Transaction
except Exception:  # pragma: no cover
    GraphDatabase = None  # type: ignore
    Driver = None  # type: ignore
    Session = None  # type: ignore
    Transaction = None  # type: ignore


logger = logging.getLogger(__name__)


def _read_positive_float_env(name: str, default: float | None) -> float | None:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if value <= 0:
        return None
    return value


class _ManagedResult:
    """Wrap neo4j.Result so sessions stay open until consumption."""

    def __init__(self, session, result):
        self._session = session
        self._result = result

    def __iter__(self):
        try:
            yield from self._result
        finally:
            self._close()

    def single(self, *args, **kwargs):
        try:
            return self._result.single(*args, **kwargs)
        finally:
            self._close()

    def consume(self):
        try:
            return self._result.consume()
        finally:
            self._close()

    def _close(self):
        if self._session is not None:
            try:
                self._session.close()
            finally:
                self._session = None

    def __getattr__(self, item):
        return getattr(self._result, item)

    def __del__(self):  # pragma: no cover
        self._close()


class _BufferedResult:
    """Result over records already materialized inside a (now-closed) tx.

    Used by the server-side transaction-timeout path: the query is executed
    inside an explicit transaction started with ``begin_transaction(timeout=...)``
    and the records are fully drained *while the transaction is open* (so the
    server-side timeout bounds both execution and streaming). The transaction is
    then committed and the session closed, and consumers iterate / call
    ``single()`` over the buffered records. Callers of ``_run`` only ever iterate
    or call ``single()``; ``consume()`` is intentionally unsupported here.
    """

    def __init__(self, records: list[Any]):
        self._records = records

    def __iter__(self):
        yield from self._records

    def single(self, *args, **kwargs):
        del args, kwargs
        if not self._records:
            return None
        return self._records[0]


class Neo4jGraphDB:
    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        database: str | None = None,
        *,
        preload_cache: bool = True,
    ) -> None:
        if GraphDatabase is None:
            raise ImportError("neo4j driver is not available. Install neo4j and retry.")

        self._query_timeout_s = _read_positive_float_env("NEO4J_QUERY_TIMEOUT_S", 12.0)

        driver_kwargs: dict[str, float] = {}
        connection_timeout_s = _read_positive_float_env(
            "NEO4J_CONNECTION_TIMEOUT_S", 5.0
        )
        acquisition_timeout_s = _read_positive_float_env(
            "NEO4J_CONNECTION_ACQUISITION_TIMEOUT_S", 10.0
        )
        retry_timeout_s = _read_positive_float_env(
            "NEO4J_MAX_TRANSACTION_RETRY_TIME_S", 5.0
        )
        if connection_timeout_s is not None:
            driver_kwargs["connection_timeout"] = connection_timeout_s
        if acquisition_timeout_s is not None:
            driver_kwargs["connection_acquisition_timeout"] = acquisition_timeout_s
        if retry_timeout_s is not None:
            driver_kwargs["max_transaction_retry_time"] = retry_timeout_s

        try:
            self._driver = GraphDatabase.driver(
                uri,
                auth=(user, password),
                **driver_kwargs,
            )
        except TypeError:
            # Backward compatibility for older neo4j drivers that reject kwargs.
            self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self._database = database
        self.graph: nx.MultiDiGraph = nx.MultiDiGraph()
        self._session: Session | None = None
        self._tx: Transaction | None = None

        try:
            self._driver.verify_connectivity()  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover
            self._driver.close()
            raise ConnectionError(
                f"Unable to connect to Neo4j at {uri}: {exc}"
            ) from exc

        logger.info("Initialized Neo4jGraphDB adapter for %s", uri)
        if preload_cache:
            self._load_graph_cache()
        else:
            logger.info("Skipping graph cache preload (preload_cache=False)")

    # -------------
    # Low-level ops
    # -------------
    def _run(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
        timeout_s: float | None = None,
    ):
        run_params = params or {}
        # Resolve the effective server-side transaction timeout. A per-call
        # ``timeout_s`` (e.g. the kg_verify budget) overrides the module default
        # (``NEO4J_QUERY_TIMEOUT_S``). The timeout is enforced by STARTING the
        # transaction with ``begin_transaction(timeout=...)`` -- it is NOT a
        # kwarg on ``Session.run``/``Transaction.run`` (the driver merges run()
        # **kwargs into the Cypher parameter dict, so ``timeout=`` there becomes
        # a silently-ignored ``$timeout`` query parameter and never bounds the
        # query server-side). For neo4j 6.1.0 the value is seconds as a float.
        effective_timeout_s: float | None = (
            self._query_timeout_s if timeout_s is None else timeout_s
        )
        try:
            if effective_timeout_s is not None:
                effective_timeout_s = float(effective_timeout_s)
        except (TypeError, ValueError):
            effective_timeout_s = None
        if effective_timeout_s is not None and effective_timeout_s <= 0:
            effective_timeout_s = None

        # An explicit bulk transaction is already open: its timeout (if any) was
        # fixed when ``begin()`` started it, and a per-query timeout cannot be
        # retroactively applied. Run on the existing tx unchanged.
        if self._tx is not None:
            return self._tx.run(cypher, run_params)

        # No timeout configured: preserve the original autocommit behavior so
        # other callers are not regressed.
        if effective_timeout_s is None:
            session = self._driver.session(database=self._database)
            result = session.run(cypher, run_params)
            return _ManagedResult(session, result)

        # Server-side transaction timeout path: start an explicit transaction
        # with the timeout, run the query, and drain all records *inside* the
        # transaction so the timeout bounds both execution and streaming. If the
        # query exceeds the budget the server terminates it and the driver raises
        # a ClientError/TransientError, which we let propagate to the caller.
        session = self._driver.session(database=self._database)
        try:
            tx = session.begin_transaction(timeout=effective_timeout_s)
        except Exception:
            session.close()
            raise
        try:
            result = tx.run(cypher, run_params)
            records = list(result)
            tx.commit()
        except Exception:
            try:
                tx.close()
            except Exception:  # pragma: no cover - best-effort tx cleanup
                pass
            raise
        finally:
            session.close()
        return _BufferedResult(records)

    def _load_graph_cache(self) -> None:
        """Populate NetworkX cache with current Neo4j state."""
        self.graph.clear()
        with self._driver.session(database=self._database) as session:
            for record in session.run("MATCH (n) RETURN n"):
                node = record["n"]
                node_id = node.get("id") or node.element_id
                props = dict(node)
                props["labels"] = list(node.labels)
                self.graph.add_node(node_id, **props)

            for record in session.run("MATCH (a)-[r]->(b) RETURN a, r, b"):
                a = record["a"]
                b = record["b"]
                rel = record["r"]
                start_id = a.get("id") or a.element_id
                end_id = b.get("id") or b.element_id
                rel_props = dict(rel)
                rel_type = rel.type
                rel_props["type"] = rel_type
                self.graph.add_edge(start_id, end_id, key=rel_type, **rel_props)

    def _sanitize_properties(self, properties: dict[str, Any]) -> dict[str, Any]:
        """Coerce values to Neo4j-supported primitives/arrays."""

        def _sanitize(value: Any) -> Any:
            if value is None or isinstance(value, str | int | float | bool):
                return value
            if isinstance(value, list):
                sanitized = []
                for item in value:
                    if isinstance(item, str | int | float | bool) or item is None:
                        sanitized.append(item)
                    else:
                        sanitized.append(json.dumps(item, sort_keys=True, default=str))
                return sanitized
            if isinstance(value, dict):
                return json.dumps(value, sort_keys=True, default=str)
            return str(value)

        return {key: _sanitize(val) for key, val in properties.items()}

    @staticmethod
    def _maybe_json_load(value: str) -> Any:
        """Best-effort decode for values JSON-encoded by _sanitize_properties."""
        stripped = value.lstrip()
        if not stripped or stripped[0] not in ("{", "["):
            return value
        try:
            return json.loads(stripped)
        except Exception:
            return value

    def _deserialize_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._maybe_json_load(value)
        if isinstance(value, list):
            return [self._deserialize_value(item) for item in value]
        return value

    def _deserialize_properties(self, properties: dict[str, Any]) -> dict[str, Any]:
        # Keep labels as-is (it's our normalized node label list).
        return {
            key: (val if key == "labels" else self._deserialize_value(val))
            for key, val in properties.items()
        }

    def _cache_node(
        self, node_id: str, labels: list[str], sanitized_props: dict[str, Any]
    ) -> None:
        cached = dict(sanitized_props)
        cached["labels"] = labels
        self.graph.add_node(node_id, **cached)

    def _cache_relationship(
        self,
        start_id: str,
        end_id: str,
        rel_type: str,
        sanitized_props: dict[str, Any],
    ) -> None:
        cached = dict(sanitized_props)
        cached["type"] = rel_type
        self.graph.add_edge(start_id, end_id, key=rel_type, **cached)

    def _lookup_labels(self, node_id: str) -> list[str]:
        if self.graph.has_node(node_id):
            cached_labels = self._normalize_label_list(
                self.graph.nodes[node_id].get("labels")
            )
            if cached_labels:
                return cached_labels

        try:
            record = self._run(
                "MATCH (n {id:$id}) RETURN labels(n) AS labels LIMIT 1",
                {"id": node_id},
            ).single()
        except Exception:  # pragma: no cover - defensive logging
            record = None

        if not record:
            return []

        labels = self._normalize_label_list(record.get("labels"))
        if labels:
            if self.graph.has_node(node_id):
                self.graph.nodes[node_id]["labels"] = labels
            else:
                self.graph.add_node(node_id, labels=labels)
        return labels

    @staticmethod
    def _normalize_label_list(raw: Any) -> list[str]:
        if raw is None:
            return []
        if isinstance(raw, str):
            return [raw] if raw else []
        if isinstance(raw, Iterable):
            labels: list[str] = []
            for item in raw:
                if isinstance(item, str) and item:
                    labels.append(item)
            return labels
        return []

    @staticmethod
    def _format_label_clause(labels: list[str]) -> str:
        if not labels:
            return ""
        return ":".join(f"`{label}`" for label in labels)

    def _node_pattern(self, variable: str, node_id: str) -> str:
        labels = self._lookup_labels(node_id)
        clause = self._format_label_clause(labels)
        if clause:
            return f"({variable}:{clause} {{id:${variable}}})"
        return f"({variable} {{id:${variable}}})"

    # --------------------
    # Transaction control
    # --------------------
    def begin(self) -> None:
        """Begin an explicit transaction for bulk operations."""
        if self._tx is not None:
            logger.warning("Transaction already open; committing existing transaction.")
            self.commit()
        if self._session is not None:
            try:
                self._session.close()
            except Exception:  # pragma: no cover
                pass
        self._session = self._driver.session(database=self._database)
        self._tx = self._session.begin_transaction()

    def commit(self) -> None:
        """Commit the current transaction."""
        if self._tx is None:
            return
        try:
            self._tx.commit()
        finally:
            try:
                if self._session is not None:
                    self._session.close()
            finally:
                self._session = None
                self._tx = None

    def rollback(self) -> None:
        """Rollback the current transaction."""
        if self._tx is None:
            return
        try:
            self._tx.rollback()
        finally:
            try:
                if self._session is not None:
                    self._session.close()
            finally:
                self._session = None
                self._tx = None

    # -----------------
    # Schema utilities
    # -----------------
    def create_constraint(
        self, label: str, property: str, constraint_type: str = "UNIQUE"
    ) -> None:
        if constraint_type.upper() != "UNIQUE":
            return
        cypher = f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:`{label}`) REQUIRE n.`{property}` IS UNIQUE"
        self._run(cypher)
        logger.info("Created UNIQUE constraint on %s.%s", label, property)

    def create_index(
        self, label: str, property: str, index_type: str = "BTREE"
    ) -> None:
        cypher = f"CREATE INDEX IF NOT EXISTS FOR (n:`{label}`) ON (n.`{property}`)"
        self._run(cypher)
        logger.info("Created index on %s.%s", label, property)

    # -------------
    # Node helpers
    # -------------
    def _compute_id(self, labels: list[str], properties: dict[str, Any]) -> str:
        if "id" in properties:
            return str(properties["id"])
        key_props = {
            k: properties.get(k)
            for k in ["name", "pmid", "doi", "concept_id", "x", "y", "z"]
        }
        id_string = f"{'-'.join(labels)}-{str(key_props)}"
        return hashlib.md5(id_string.encode()).hexdigest()

    def create_node(
        self,
        labels: str | list[str],
        properties: dict[str, Any] | None = None,
        node_id: str | None = None,
        auto_commit: bool = True,
    ) -> str:
        del auto_commit  # Parity with legacy interface; transactions handled separately.
        if isinstance(labels, str):
            labels = [labels]
        props = dict(properties or {})
        node_id = node_id or self._compute_id(labels, props)
        props["id"] = node_id
        props.setdefault("labels", labels)

        sanitized_props = self._sanitize_properties(
            {k: v for k, v in props.items() if k != "labels"}
        )

        if labels:
            label_str = ":".join(f"`{l}`" for l in labels)
            cypher = f"MERGE (n:{label_str} {{id: $id}}) SET n += $props"
        else:
            cypher = "MERGE (n {id: $id}) SET n += $props"
        self._run(cypher, {"id": node_id, "props": sanitized_props})
        self._run(
            "MATCH (n {id:$id}) SET n.labels = $labels",
            {"id": node_id, "labels": labels},
        )

        self._cache_node(node_id, labels, sanitized_props)
        return node_id

    def _save_node(
        self,
        node_id: str,
        labels: list[str],
        properties: dict[str, Any],
        auto_commit: bool = True,  # parity with SQLite signature
    ) -> str:
        del auto_commit  # Neo4j sessions auto-commit
        return self.create_node(labels, properties, node_id=node_id)

    def find_nodes(
        self,
        labels: str | list[str] | None = None,
        properties: dict[str, Any] | None = None,
    ) -> list[tuple[str, dict[str, Any]]]:
        if isinstance(labels, str):
            labels = [labels]
        label_str = ":".join(f"`{l}`" for l in (labels or []))
        where: list[str] = []
        params: dict[str, Any] = {}
        if properties:
            for i, (k, v) in enumerate(properties.items()):
                p = f"p{i}"
                where.append(f"n.`{k}` = ${p}")
                params[p] = v
        where_clause = (" WHERE " + " AND ".join(where)) if where else ""
        cypher = (
            f"MATCH (n{(':'+label_str) if label_str else ''}){where_clause} RETURN n"
        )
        result = self._run(cypher, params)
        out: list[tuple[str, dict[str, Any]]] = []
        for rec in result:
            node = rec["n"]
            props = dict(node)
            nid = props.get("id") or node.element_id
            out.append((str(nid), props))
        return out

    # ---------------------
    # Relationship helpers
    # ---------------------
    def create_relationship(
        self,
        start_node: str,
        end_node: str,
        rel_type: str,
        properties: dict[str, Any] | None = None,
        auto_commit: bool = True,
    ) -> bool:
        del auto_commit
        sanitized_props = self._sanitize_properties(properties or {})
        start_pattern = self._node_pattern("a", start_node)
        end_pattern = self._node_pattern("b", end_node)
        cypher = (
            f"MATCH {start_pattern} "
            f"MATCH {end_pattern} "
            f"MERGE (a)-[r:`{rel_type}`]->(b) SET r += $props RETURN r"
        )
        result = self._run(
            cypher, {"a": start_node, "b": end_node, "props": sanitized_props}
        )
        rec = result.single()
        if rec is None:
            return False
        self._cache_relationship(start_node, end_node, rel_type, sanitized_props)
        return True

    def _save_relationship(
        self,
        start_node: str,
        end_node: str,
        rel_type: str,
        properties: dict[str, Any],
        auto_commit: bool = True,
    ) -> bool:
        del auto_commit
        return self.create_relationship(start_node, end_node, rel_type, properties)

    def update_relationship(
        self,
        start_node: str,
        end_node: str,
        rel_type: str,
        properties: dict[str, Any],
    ) -> bool:
        sanitized_props = self._sanitize_properties(properties)
        cypher = (
            f"MATCH (a {{id:$a}})-[r:`{rel_type}`]->(b {{id:$b}}) "
            f"WITH r LIMIT 1 SET r += $props RETURN r"
        )
        result = self._run(
            cypher, {"a": start_node, "b": end_node, "props": sanitized_props}
        )
        rec = result.single()
        if rec is None:
            return False
        self._cache_relationship(start_node, end_node, rel_type, sanitized_props)
        return True

    def find_relationships(
        self,
        start_node: str | None = None,
        end_node: str | None = None,
        rel_type: str | None = None,
    ) -> list[tuple[str, str, dict[str, Any]]]:
        matches: list[tuple[str, str, dict[str, Any]]] = []
        for u, v, data in self.graph.edges(data=True):
            if start_node and u != start_node:
                continue
            if end_node and v != end_node:
                continue
            if rel_type and data.get("type") != rel_type:
                continue
            matches.append((u, v, dict(data)))
        if matches:
            return matches

        filters = []
        params: dict[str, Any] = {}
        if start_node:
            filters.append("start.id = $start")
            params["start"] = start_node
        if end_node:
            filters.append("end.id = $end")
            params["end"] = end_node
        if rel_type:
            filters.append("type(rel) = $type")
            params["type"] = rel_type
        where_clause = " WHERE " + " AND ".join(filters) if filters else ""
        query = f"MATCH (start)-[rel]->(end){where_clause} RETURN start, rel, end"
        for record in self._run(query, params):
            start = record["start"]
            end = record["end"]
            rel = record["rel"]
            start_id = start.get("id") or start.element_id
            end_id = end.get("id") or end.element_id
            rel_props = dict(rel)
            rel_type_val = rel.type
            rel_props["type"] = rel_type_val
            self.graph.add_edge(start_id, end_id, key=rel_type_val, **rel_props)
            matches.append((start_id, end_id, rel_props))
        return matches

    def delete_relationships(self, rel_type: str) -> int:
        """Delete all relationships of a specific type."""
        count_record = self._run(
            f"MATCH ()-[r:`{rel_type}`]->() RETURN count(r) AS cnt"
        ).single()
        removed = (
            int(count_record["cnt"]) if count_record and count_record["cnt"] else 0
        )
        if removed:
            self._run(f"MATCH ()-[r:`{rel_type}`]->() DELETE r")
            edges_to_remove = [
                (u, v, key)
                for u, v, key, data in self.graph.edges(keys=True, data=True)
                if data.get("type") == rel_type
            ]
            for u, v, key in edges_to_remove:
                self.graph.remove_edge(u, v, key=key)
        logger.debug("Removed %d relationships of type %s", removed, rel_type)
        return removed

    def delete_nodes_by_label(self, label: str) -> int:
        """Delete all nodes (and attached relationships) with the given label."""
        count_record = self._run(f"MATCH (n:`{label}`) RETURN count(n) AS cnt").single()
        removed = (
            int(count_record["cnt"]) if count_record and count_record["cnt"] else 0
        )
        if removed:
            self._run(f"MATCH (n:`{label}`) DETACH DELETE n")
            nodes_to_remove = [
                node_id
                for node_id, data in self.graph.nodes(data=True)
                if label in data.get("labels", [])
            ]
            for node_id in nodes_to_remove:
                self.graph.remove_node(node_id)
        logger.debug("Removed %d nodes with label %s", removed, label)
        return removed

    # ---------------------
    # Stats & lookups
    # ---------------------
    def get_stats(self) -> dict[str, Any]:
        total_nodes = self.get_node_count()
        total_relationships = self._run(
            "MATCH ()-[r]->() RETURN count(r) AS c"
        ).single()["c"]
        node_labels = [
            rec["label"]
            for rec in self._run("CALL db.labels() YIELD label RETURN label")
        ]
        relationship_types = [
            rec["relationshipType"]
            for rec in self._run(
                "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType"
            )
        ]
        return {
            "backend": "neo4j",
            "total_nodes": int(total_nodes),
            "total_relationships": int(total_relationships or 0),
            "node_labels": node_labels,
            "relationship_types": relationship_types,
        }

    def execute_query(
        self, query: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute raw Cypher and return rows as dictionaries."""
        result = self._run(query, params)
        return [record.data() for record in result]

    def clear(self) -> None:
        """Remove all data from the backing store and cache."""
        self._run("MATCH (n) DETACH DELETE n")
        self.graph.clear()

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        if node_id in self.graph.nodes:
            return self._deserialize_properties(dict(self.graph.nodes[node_id]))
        record = self._run("MATCH (n {id:$id}) RETURN n", {"id": node_id}).single()
        if not record:
            return None
        node = record["n"]
        props = dict(node)
        props["labels"] = list(node.labels)
        self.graph.add_node(node_id, **props)
        return self._deserialize_properties(props)

    def get_node_count(self, label: str | None = None) -> int:
        if label is None:
            cached = self.graph.number_of_nodes()
            if cached:
                return cached
            record = self._run("MATCH (n) RETURN count(n) AS cnt").single()
            return int(record["cnt"] if record else 0)

        total = 0
        for _, data in self.graph.nodes(data=True):
            if label in data.get("labels", []):
                total += 1
        if total:
            return total
        record = self._run(f"MATCH (n:`{label}`) RETURN count(n) AS cnt").single()
        return int(record["cnt"] if record else 0)

    def bulk_create_nodes(
        self,
        nodes: list[tuple[str | list[str], dict[str, Any]]],
        batch_size: int = 1000,
    ) -> list[str]:
        if not nodes:
            return []

        size = max(1, int(batch_size))
        grouped: dict[tuple[str, ...], list[dict[str, Any]]] = {}
        for order, (labels, properties) in enumerate(nodes):
            label_list = [labels] if isinstance(labels, str) else list(labels or [])
            props = dict(properties or {})
            node_id = props.get("id") or self._compute_id(label_list, props)
            props["id"] = node_id
            sanitized_props = self._sanitize_properties(
                {k: v for k, v in props.items() if k != "labels"}
            )
            grouped.setdefault(tuple(label_list), []).append(
                {"id": node_id, "props": sanitized_props, "order": order}
            )

        created_by_order: dict[int, str] = {}
        for label_tuple, rows in grouped.items():
            for row in rows:
                created_by_order[row["order"]] = row["id"]
            labels_list = list(label_tuple)
            label_clause = (
                ":" + ":".join(f"`{label}`" for label in labels_list)
                if labels_list
                else ""
            )
            cypher = (
                f"UNWIND $rows AS row "
                f"MERGE (n{label_clause} {{id: row.id}}) "
                f"SET n += row.props "
                f"SET n.labels = $labels "
                f"RETURN row.order AS order, row.id AS id"
            )
            for start in range(0, len(rows), size):
                chunk = rows[start : start + size]
                result = self._run(cypher, {"rows": chunk, "labels": labels_list})
                for rec in result:
                    created_by_order[int(rec["order"])] = rec["id"]
                for row in chunk:
                    self._cache_node(row["id"], labels_list, row["props"])

        return [created_by_order.get(i) for i in range(len(nodes))]

    def bulk_find_nodes_by_pmid(
        self,
        pmids: list[str],
        label: str = "Publication",
    ) -> dict[str, str]:
        if not pmids:
            return {}

        lookup: dict[str, str] = {}
        targets = set(pmids)
        for node_id, data in self.graph.nodes(data=True):
            if label not in data.get("labels", []):
                continue
            pmid = data.get("pmid")
            if pmid and pmid in targets:
                lookup[str(pmid)] = node_id

        remaining = targets - set(lookup.keys())
        if remaining:
            result = self._run(
                f"MATCH (n:`{label}`) WHERE n.pmid IN $pmids RETURN n",
                {"pmids": list(remaining)},
            )
            for record in result:
                node = record["n"]
                node_id = node.get("id") or node.element_id
                props = dict(node)
                props["labels"] = list(node.labels)
                pmid = props.get("pmid")
                if pmid:
                    lookup[str(pmid)] = node_id
                self.graph.add_node(node_id, **props)
        return lookup

    # -----------------
    # Graph traversal
    # -----------------
    def graph_bfs(
        self, start_id: str, depth: int = 2
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        d = max(1, min(int(depth), 3))
        cy_nodes = (
            f"MATCH (s {{id:$id}}) "
            f"MATCH p=(s)-[*1..{d}]-(n) "
            f"WITH collect(distinct n) as ns "
            f"RETURN ns"
        )
        nodes_rec = self._run(cy_nodes, {"id": start_id}).single()
        raw_nodes: Iterable[Any] = nodes_rec["ns"] if nodes_rec else []
        nodes: list[dict[str, Any]] = []
        for n in raw_nodes:
            props = dict(n)
            props.setdefault("labels", list(n.labels))
            props.setdefault("id", props.get("id", n.element_id))
            nodes.append(
                {
                    "id": props["id"],
                    "labels": props.get("labels", []),
                    "properties": {
                        k: v for k, v in props.items() if k not in {"labels", "id"}
                    },
                }
            )

        cy_edges = (
            f"MATCH (s {{id:$id}}) "
            f"MATCH p=(s)-[r*1..{d}]-(n) "
            f"UNWIND r as rel "
            f"RETURN distinct startNode(rel) as a, endNode(rel) as b, type(rel) as t, properties(rel) as p"
        )
        edges: list[dict[str, Any]] = []
        for rec in self._run(cy_edges, {"id": start_id}):
            a = rec["a"]
            b = rec["b"]
            t = rec["t"]
            p = rec["p"] or {}
            a_id = a.get("id", a.element_id)
            b_id = b.get("id", b.element_id)
            edges.append({"start": a_id, "end": b_id, "type": t, "properties": dict(p)})
        return nodes, edges

    # -------
    # Cleanup
    # -------
    def close(self) -> None:
        try:
            if self._tx is not None:
                try:
                    self._tx.close()
                except Exception:  # pragma: no cover
                    pass
                self._tx = None
            if self._session is not None:
                try:
                    self._session.close()
                except Exception:  # pragma: no cover
                    pass
                self._session = None
            self._driver.close()
        except Exception:  # pragma: no cover
            pass

    def session(self):
        """Expose a managed session for components that need direct access."""
        return self._driver.session(database=self._database)

    def __del__(self) -> None:  # pragma: no cover
        self.close()
