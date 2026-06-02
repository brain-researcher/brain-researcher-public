#!/usr/bin/env python3
"""
Seed Neo4j backend with a tiny demo graph used by smoke tests.

Reads Neo4j connection from env: NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, NEO4J_DATABASE.
"""

from __future__ import annotations

from brain_researcher.services.br_kg.db.bootstrap import get_db, seed

if __name__ == "__main__":
    db = get_db()
    seed(db)
    stats = db.get_stats()
    print("Seed complete:", stats)
