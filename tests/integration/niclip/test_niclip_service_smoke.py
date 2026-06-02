import os
from pathlib import Path

import pytest


@pytest.mark.integration
def test_niclip_engine_smoke():
    """Smoke-test NiCLIP engine with real data (env-gated)."""
    if os.getenv("BR_REAL_NICLIP") != "1":
        pytest.skip("Set BR_REAL_NICLIP=1 to run real NiCLIP engine smoke test")

    data_path = os.getenv("NICLIP_EMBEDDINGS_PATH") or os.getenv("NICLIP_DATA_PATH")
    if not data_path or not Path(data_path).exists():
        pytest.skip("Set NICLIP_DATA_PATH or NICLIP_EMBEDDINGS_PATH to a valid path")

    from brain_researcher.services.br_kg.niclip.engine import (
        NiclipEngine,
        NiclipEngineConfig,
    )

    engine = NiclipEngine.get(
        NiclipEngineConfig(data_path=data_path), force_reload=True
    )
    status = engine.status()
    if status.get("status") != "healthy":
        pytest.skip(f"NiCLIP engine not ready: {status.get('missing')}")

    embeddings = engine.encode_text("working memory")
    assert embeddings is not None

    results = engine.search("working memory", top_k=3)
    assert len(results) > 0
