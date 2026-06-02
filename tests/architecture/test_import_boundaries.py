from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = Path(__file__).with_name("core_services_import_baseline.txt")
SERVICES_LAYER_BASELINE_PATH = Path(__file__).with_name("services_layer_baseline.txt")
SCRIPT_PATH = REPO_ROOT / "scripts" / "analyze_code_import_graph.py"

# Optimal low->high layer order for services/* (min feedback arc set, computed
# 2026-06-01; llm_gateway inserted after the router relocation). Higher layers
# may import lower layers; a lower layer importing a higher one is a back-edge.
# See docs/architecture/code_graph_folder_order.md.
_SERVICES_LAYER_ORDER = (
    "memory",
    "shared",
    "telemetry",
    "llm_gateway",
    "br_kg",
    "review",
    "tools",
    "agent",
    "mcp",
    "orchestrator",
)


def _load_import_graph_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "analyze_code_import_graph",
        SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


import_graph = _load_import_graph_module()


def _load_baseline(path: Path) -> set[str]:
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }


def test_collect_import_graph_resolves_absolute_and_relative_imports(
    tmp_path: Path,
) -> None:
    src_root = tmp_path / "src" / "example_pkg"
    (src_root / "core").mkdir(parents=True)
    (src_root / "services").mkdir()
    (src_root / "__init__.py").write_text("", encoding="utf-8")
    (src_root / "core" / "__init__.py").write_text("", encoding="utf-8")
    (src_root / "core" / "local.py").write_text("", encoding="utf-8")
    (src_root / "services" / "__init__.py").write_text("", encoding="utf-8")
    (src_root / "services" / "bar.py").write_text("", encoding="utf-8")
    (src_root / "core" / "foo.py").write_text(
        "\n".join(
            [
                "import example_pkg.services.bar",
                "from . import local",
                "from ..services import bar",
            ]
        ),
        encoding="utf-8",
    )

    analysis = import_graph.collect_import_graph(
        src_root=src_root,
        package="example_pkg",
        repo_root=tmp_path,
    )

    imports = {
        (edge.importer_module, edge.imported_module) for edge in analysis.imports
    }
    assert ("example_pkg.core.foo", "example_pkg.services.bar") in imports
    assert ("example_pkg.core.foo", "example_pkg.core") in imports
    assert ("example_pkg.core.foo", "example_pkg.services") in imports

    boundary_edges = import_graph.find_boundary_edges(
        analysis.imports,
        "example_pkg",
        "core",
        "services",
    )
    assert {edge.imported_module for edge in boundary_edges} == {
        "example_pkg.services",
        "example_pkg.services.bar",
    }


def test_core_to_services_import_boundary_does_not_expand() -> None:
    analysis = import_graph.collect_import_graph(
        src_root=REPO_ROOT / "src" / "brain_researcher",
        package="brain_researcher",
        repo_root=REPO_ROOT,
    )
    current = {
        import_graph.boundary_key(edge)
        for edge in import_graph.find_boundary_edges(
            analysis.imports,
            "brain_researcher",
            "core",
            "services",
        )
    }
    baseline = _load_baseline(BASELINE_PATH)

    additions = sorted(current - baseline)
    assert not additions, (
        "New core -> services imports were added. Move the dependency behind a "
        "core contract/services shared interface, or update this ratchet only "
        f"after an intentional architecture decision. Additions: {additions}"
    )


def test_research_loops_do_not_import_services() -> None:
    """Lock the resolved top-level cycle: ``behavior``/``research``/
    ``autoresearch`` must not import ``services`` directly. These were
    execution-convenience edges; see step 3 of
    ``docs/architecture/code_graph_folder_order.md``.
    """
    analysis = import_graph.collect_import_graph(
        src_root=REPO_ROOT / "src" / "brain_researcher",
        package="brain_researcher",
        repo_root=REPO_ROOT,
    )
    offenders: dict[str, list[str]] = {}
    for area in ("behavior", "research", "autoresearch"):
        edges = import_graph.find_boundary_edges(
            analysis.imports, "brain_researcher", area, "services"
        )
        if edges:
            offenders[area] = sorted(
                f"{edge.importer_module} -> {edge.imported_module}" for edge in edges
            )
    assert not offenders, (
        "Top-level research loops must not import services directly; keep "
        "reusable logic in core/behavior and runtime under services. "
        f"Offending imports: {offenders}"
    )


def test_core_contracts_does_not_import_artifact_validator() -> None:
    """``core/contracts`` is a low layer and must not import up into
    ``core/artifact_validator`` (which depends on ``core.contracts`` for the
    ``Violation`` types). Guards the 2-node cycle that was broken by relocating
    the pure contract specs to ``core/contracts/artifact_contract.py`` (the
    validator now re-exports them).
    """
    analysis = import_graph.collect_import_graph(
        src_root=REPO_ROOT / "src" / "brain_researcher",
        package="brain_researcher",
        repo_root=REPO_ROOT,
    )
    offenders = sorted(
        f"{edge.importer_module} -> {edge.imported_module}"
        for edge in analysis.imports
        if edge.importer_module.startswith("brain_researcher.core.contracts")
        and edge.imported_module.startswith("brain_researcher.core.artifact_validator")
    )
    assert not offenders, (
        "core/contracts must not import core/artifact_validator (import "
        "cycle). Keep pure contract specs in core/contracts (see "
        "artifact_contract.py) instead of importing up into the validator. "
        f"Offending imports: {offenders}"
    )


def _services_subarea(module: str) -> str | None:
    parts = module.split(".")
    if len(parts) >= 3 and parts[1] == "services":
        return parts[2]
    return None


def test_services_internal_layer_does_not_regress() -> None:
    """Ratchet the ``services/*`` cycle toward the target layer order (see
    ``docs/architecture/code_graph_folder_order.md`` step 4). A lower layer
    importing a higher one is a back-edge; no NEW back-edges may appear, and the
    baseline only shrinks as edges are cut. A lazy import does NOT count as a
    cut -- the static graph still sees it -- so the dependency must be genuinely
    removed (relocate the symbol to a lower layer, or inject an interface from
    ``services/shared``).
    """
    pos = {name: i for i, name in enumerate(_SERVICES_LAYER_ORDER)}
    analysis = import_graph.collect_import_graph(
        src_root=REPO_ROOT / "src" / "brain_researcher",
        package="brain_researcher",
        repo_root=REPO_ROOT,
    )
    current: set[str] = set()
    for edge in analysis.imports:
        s = _services_subarea(edge.importer_module)
        d = _services_subarea(edge.imported_module)
        if s in pos and d in pos and s != d and pos[s] < pos[d]:
            current.add(f"{s} -> {d}")
    baseline = _load_baseline(SERVICES_LAYER_BASELINE_PATH)
    additions = sorted(current - baseline)
    assert not additions, (
        "New services/* back-edges introduced (a lower layer importing a "
        "higher one). Break the dependency by relocating the symbol to a lower "
        "layer or injecting an interface from services/shared; do NOT use a "
        f"lazy import. New back-edges: {additions}"
    )
