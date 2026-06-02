#!/usr/bin/env python3
"""
Local smoke test for the BR-KG Flask API using the Flask test client.

This avoids external networking and validates core endpoints:
- /health
- /stats

Optionally seeds the DB first by setting SEED=1.
"""

from __future__ import annotations

import os
from importlib import import_module


def main() -> None:
    # Optionally seed the DB
    if os.environ.get("SEED", "0") == "1":
        seed = import_module("brain_researcher.services.br_kg.db.bootstrap")
        db = seed.get_db()
        seed.seed(db)

    # Import Flask app
    mod = import_module("brain_researcher.services.br_kg.api.graph_api")
    app = getattr(mod, "app")

    with app.test_client() as client:
        r = client.get("/health")
        assert r.status_code == 200, r.data
        data = r.get_json()
        assert data.get("status") == "healthy", data
        print("/health OK", data)

        r = client.get("/stats")
        assert r.status_code == 200, r.data
        stats = r.get_json()
        assert "total_nodes" in stats and "total_relationships" in stats
        print("/stats OK", stats)


if __name__ == "__main__":
    main()
