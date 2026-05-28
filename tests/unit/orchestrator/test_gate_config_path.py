from pathlib import Path

from brain_researcher.core.gates.engine import GateEngine
from brain_researcher.services.orchestrator.worker import _resolve_gate_config_path


def test_worker_resolve_gate_config_path_finds_repo_config(monkeypatch) -> None:
    """Worker should be able to locate configs/gates.yaml from nested working dirs.

    This repo keeps gate rules under `configs/`, not inside the Python package, so we
    verify the resolver can still find it when CWD isn't the repo root.
    """

    monkeypatch.chdir(Path(__file__).resolve().parent)
    path = _resolve_gate_config_path()

    assert path is not None
    assert path.exists()
    assert path.name in {"gates.yaml", "gates.yml"}
    assert "configs" in path.parts

    engine = GateEngine.from_yaml(path)
    assert len(engine.rules) > 0

