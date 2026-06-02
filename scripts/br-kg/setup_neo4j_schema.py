"""
Setup Neo4j schema: constraints and indexes for BR-KG.

This script exposes `setup_schema(db)` which accepts an object that provides
`create_constraint(label, property, constraint_type)` and
`create_index(label, property, index_type)` methods (as in Neo4jGraphDB).
"""

from __future__ import annotations
