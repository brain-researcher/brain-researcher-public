#!/usr/bin/env python3
"""
Legacy standalone wrapper for the packaged Agent web service.
"""

from pathlib import Path
import os
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from brain_researcher.services.agent.web_service import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    debug = os.environ.get("DEBUG", "false").lower() == "true"

    print(f"Starting legacy Agent wrapper on http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
