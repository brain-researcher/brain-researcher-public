import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.integration
def test_niclip_cli_smoke():
    """Smoke-test NiCLIP CLI commands (env-gated)."""
    if os.getenv("BR_REAL_NICLIP") != "1":
        pytest.skip("Set BR_REAL_NICLIP=1 to run real NiCLIP CLI smoke test")

    data_path = os.getenv("NICLIP_EMBEDDINGS_PATH") or os.getenv("NICLIP_DATA_PATH")
    if not data_path or not Path(data_path).exists():
        pytest.skip("Set NICLIP_DATA_PATH or NICLIP_EMBEDDINGS_PATH to a valid path")

    br = shutil.which("br") or shutil.which("brain-researcher")
    if not br:
        pytest.skip("CLI binary 'br' (or 'brain-researcher') not found on PATH")

    env = os.environ.copy()
    env["BR_REAL_NICLIP"] = "1"

    health = subprocess.run(
        [br, "niclip", "health"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert health.returncode == 0

    encode = subprocess.run(
        [br, "niclip", "encode", "working memory"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert encode.returncode == 0

    search = subprocess.run(
        [br, "niclip", "search", "working memory", "--top-k", "3"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert search.returncode == 0
