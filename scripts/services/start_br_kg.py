#!/usr/bin/env python3
"""
Simple BR-KG launcher that bypasses CLI and Neurodesk issues.
"""

import os
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root / "src"))

# Clean problematic environment variables
env_vars_to_clean = [
    'SINGULARITY_BINDPATH',
    'SINGULARITY_CACHEDIR',
    'SINGULARITY_TMPDIR',
    'SINGULARITY_LOCALCACHEDIR',
    'SINGULARITYENV_PREPEND_PATH'
]

for var in env_vars_to_clean:
    os.environ.pop(var, None)

# The live graph is too large to eagerly mirror into the legacy NetworkX cache
# during service bootstrap. Allow explicit override, but keep local startup fast
# by default.
os.environ.setdefault("NEO4J_PRELOAD_CACHE", "false")

def main():
    print("🧠 Starting BR-KG service...")
    print("   Project root:", project_root)

    # Set default port
    port = int(os.environ.get("PORT", 5000))

    # Check for database
    db_path = os.environ.get("BR_KG_GLMFITLINS_DB_PATH")
    if not db_path:
        default_db = project_root / "data" / "br_kg" / "db" / "br_kg_glmfitlins.db"
        if default_db.exists():
            os.environ["BR_KG_GLMFITLINS_DB_PATH"] = str(default_db)
            print(f"   Using database: {default_db}")
        else:
            print("   Warning: No database found. Initialize with 'br db init'")

    try:
        # Import and run the BR-KG app
        from brain_researcher.services.br_kg.app import app

        print(f"   Starting on: http://127.0.0.1:{port}")
        print(f"   API endpoints: http://127.0.0.1:{port}/api/glmfitlins/")
        print("   Web UI: http://127.0.0.1:3000/en/kg/explore")
        print()
        print("   Press Ctrl+C to stop")

        app.run(host="0.0.0.0", port=port, debug=False)

    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("   Make sure you've installed the package:")
        print("   pip install -e '.[br-kg]'")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error starting service: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
