from __future__ import annotations

import argparse
import ast
import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class ImportEdge:
    importer_file: str
    importer_module: str
    imported_module: str
    line: int
    kind: str


@dataclass(frozen=True)
class ParseError:
    file: str
    error: str


@dataclass(frozen=True)
class ImportGraphAnalysis:
    package: str
    src_root: str
    modules: dict[str, str]
    imports: list[ImportEdge]
    parse_errors: list[ParseError]


def _display_path(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _iter_python_files(src_root: Path) -> Iterable[Path]:
    for path in sorted(src_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path


def module_name_for_path(path: Path, src_root: Path, package: str) -> str:
    rel = path.relative_to(src_root)
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join([package, *parts]) if parts else package


def _current_package_parts(module: str, is_package: bool) -> list[str]:
    parts = module.split(".")
    return parts if is_package else parts[:-1]


def _resolve_import_from(
    node: ast.ImportFrom,
    current_module: str,
    current_is_package: bool,
) -> str | None:
    if node.level <= 0:
        return node.module or ""

    package_parts = _current_package_parts(current_module, current_is_package)
    keep = len(package_parts) - node.level + 1
    if keep < 0:
        return None

    parts = package_parts[:keep]
    if node.module:
        parts.extend(node.module.split("."))
    return ".".join(parts)


def _is_internal_module(module: str, package: str) -> bool:
    return module == package or module.startswith(f"{package}.")


def collect_import_graph(
    src_root: Path = Path("src/brain_researcher"),
    package: str = "brain_researcher",
    repo_root: Path = Path("."),
) -> ImportGraphAnalysis:
    src_root = src_root.resolve()
    repo_root = repo_root.resolve()
    modules: dict[str, str] = {}
    imports: list[ImportEdge] = []
    parse_errors: list[ParseError] = []

    for path in _iter_python_files(src_root):
        module = module_name_for_path(path, src_root, package)
        modules[module] = _display_path(path, repo_root)
        current_is_package = path.name == "__init__.py"
        display = _display_path(path, repo_root)

        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError) as exc:
            parse_errors.append(ParseError(file=display, error=str(exc)))
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported = alias.name
                    if _is_internal_module(imported, package):
                        imports.append(
                            ImportEdge(
                                importer_file=display,
                                importer_module=module,
                                imported_module=imported,
                                line=node.lineno,
                                kind="import",
                            )
                        )
            elif isinstance(node, ast.ImportFrom):
                imported = _resolve_import_from(node, module, current_is_package)
                if imported and _is_internal_module(imported, package):
                    imports.append(
                        ImportEdge(
                            importer_file=display,
                            importer_module=module,
                            imported_module=imported,
                            line=node.lineno,
                            kind="from",
                        )
                    )

    return ImportGraphAnalysis(
        package=package,
        src_root=_display_path(src_root, repo_root),
        modules=modules,
        imports=imports,
        parse_errors=parse_errors,
    )


def package_area(module: str, package: str, focus: str | None = None) -> str | None:
    prefix = package if focus is None else f"{package}.{focus}"
    if module == prefix:
        return "(root)" if focus is None else f"{focus}/(root)"
    if not module.startswith(f"{prefix}."):
        return None

    rest = module[len(prefix) + 1 :].split(".")
    if not rest or not rest[0]:
        return "(root)" if focus is None else f"{focus}/(root)"
    return rest[0] if focus is None else f"{focus}/{rest[0]}"


def cross_area_edges(
    imports: Iterable[ImportEdge],
    package: str,
    focus: str | None = None,
) -> Counter[tuple[str, str]]:
    counts: Counter[tuple[str, str]] = Counter()
    for edge in imports:
        source = package_area(edge.importer_module, package, focus=focus)
        target = package_area(edge.imported_module, package, focus=focus)
        if source is None or target is None or source == target:
            continue
        counts[(source, target)] += 1
    return counts


def find_boundary_edges(
    imports: Iterable[ImportEdge],
    package: str,
    source: str,
    target: str,
) -> list[ImportEdge]:
    edges = []
    for edge in imports:
        source_area = package_area(edge.importer_module, package)
        target_area = package_area(edge.imported_module, package)
        if source_area == source and target_area == target:
            edges.append(edge)
    return sorted(
        edges,
        key=lambda edge: (
            edge.importer_file,
            edge.imported_module,
            edge.line,
        ),
    )


def strongly_connected_components(
    graph: dict[str, set[str]],
) -> list[list[str]]:
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indexes: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    components: list[list[str]] = []

    def strongconnect(node: str) -> None:
        nonlocal index
        indexes[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)

        for target in sorted(graph.get(node, set())):
            if target not in indexes:
                strongconnect(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indexes[target])

        if lowlinks[node] == indexes[node]:
            component = []
            while True:
                target = stack.pop()
                on_stack.remove(target)
                component.append(target)
                if target == node:
                    break
            components.append(sorted(component))

    for node in sorted(graph):
        if node not in indexes:
            strongconnect(node)

    return components


def _graph_from_counts(
    counts: Counter[tuple[str, str]],
    nodes: Iterable[str],
) -> dict[str, set[str]]:
    graph = {node: set() for node in nodes}
    for source, target in counts:
        graph.setdefault(source, set()).add(target)
        graph.setdefault(target, set())
    return graph


def grouped_summary(
    analysis: ImportGraphAnalysis,
    focus: str | None = None,
) -> dict[str, object]:
    package = analysis.package
    file_counts: Counter[str] = Counter()
    for module in analysis.modules:
        area = package_area(module, package, focus=focus)
        if area is not None:
            file_counts[area] += 1

    edge_counts = cross_area_edges(analysis.imports, package, focus=focus)
    imports_out: Counter[str] = Counter()
    imports_in: Counter[str] = Counter()
    for (source, target), count in edge_counts.items():
        imports_out[source] += count
        imports_in[target] += count

    nodes = set(file_counts) | set(imports_out) | set(imports_in)
    graph = _graph_from_counts(edge_counts, nodes)
    cycles = [
        component
        for component in strongly_connected_components(graph)
        if len(component) > 1
    ]

    areas = [
        {
            "area": area,
            "python_files": file_counts.get(area, 0),
            "imports_out": imports_out.get(area, 0),
            "imports_in": imports_in.get(area, 0),
        }
        for area in sorted(nodes)
    ]
    edges = [
        {"source": source, "target": target, "count": count}
        for (source, target), count in sorted(
            edge_counts.items(), key=lambda item: (-item[1], item[0])
        )
    ]
    return {"areas": areas, "edges": edges, "cycles": cycles}


def boundary_key(edge: ImportEdge) -> str:
    return f"{edge.importer_file}|{edge.imported_module}"


def _render_area_table(summary: dict[str, object]) -> list[str]:
    lines = [
        "| Area | Python files | Imports out | Imports in |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in summary["areas"]:
        lines.append(
            "| `{area}` | {python_files} | {imports_out} | {imports_in} |".format(
                **row
            )
        )
    return lines


def _render_top_edges(summary: dict[str, object], limit: int = 20) -> list[str]:
    edges = summary["edges"][:limit]
    if not edges:
        return ["No cross-area imports found."]
    lines = [
        "| Source | Target | Imports |",
        "| --- | --- | ---: |",
    ]
    for edge in edges:
        lines.append(
            "| `{source}` | `{target}` | {count} |".format(**edge)
        )
    return lines


def _render_cycles(summary: dict[str, object]) -> list[str]:
    cycles = summary["cycles"]
    if not cycles:
        return ["No cross-area cycles found."]
    return ["- " + " -> ".join(f"`{node}`" for node in cycle) for cycle in cycles]


def render_markdown(
    analysis: ImportGraphAnalysis,
    boundaries: list[tuple[str, str]],
) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "# Code Import Graph Snapshot",
        "",
        f"Generated: {generated_at}",
        "",
        f"Package: `{analysis.package}`",
        f"Source root: `{analysis.src_root}`",
        "",
        "This is a static import graph over Python source files. It is a",
        "navigation and boundary-checking artifact; it does not imply that",
        "directories have been moved or that runtime services were exercised.",
        "",
        "## Top-Level Package Areas",
        "",
    ]
    top_summary = grouped_summary(analysis)
    lines.extend(_render_area_table(top_summary))
    lines.extend(["", "### Largest Cross-Area Imports", ""])
    lines.extend(_render_top_edges(top_summary))
    lines.extend(["", "### Cycles", ""])
    lines.extend(_render_cycles(top_summary))

    for focus in ("core", "services"):
        summary = grouped_summary(analysis, focus=focus)
        lines.extend(["", f"## `{focus}/*` Subpackage Areas", ""])
        lines.extend(_render_area_table(summary))
        lines.extend(["", "### Largest Cross-Area Imports", ""])
        lines.extend(_render_top_edges(summary))
        lines.extend(["", "### Cycles", ""])
        lines.extend(_render_cycles(summary))

    if boundaries:
        lines.extend(["", "## Boundary Checks", ""])
        for source, target in boundaries:
            edges = find_boundary_edges(
                analysis.imports,
                analysis.package,
                source,
                target,
            )
            lines.extend(
                [
                    f"### `{source}` -> `{target}`",
                    "",
                    f"Current imports: {len(edges)}",
                    "",
                ]
            )
            if edges:
                lines.extend(
                    [
                        "| File | Line | Imported module |",
                        "| --- | ---: | --- |",
                    ]
                )
                for edge in edges:
                    lines.append(
                        f"| `{edge.importer_file}` | {edge.line} | "
                        f"`{edge.imported_module}` |"
                    )
                lines.append("")

    if analysis.parse_errors:
        lines.extend(["", "## Parse Errors", ""])
        for error in analysis.parse_errors:
            lines.append(f"- `{error.file}`: {error.error}")

    return "\n".join(lines).rstrip() + "\n"


def render_json(
    analysis: ImportGraphAnalysis,
    boundaries: list[tuple[str, str]],
) -> dict[str, object]:
    return {
        "schema_version": "code_import_graph_snapshot_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "analysis": {
            "package": analysis.package,
            "src_root": analysis.src_root,
            "modules": analysis.modules,
            "imports": [asdict(edge) for edge in analysis.imports],
            "parse_errors": [asdict(error) for error in analysis.parse_errors],
        },
        "summaries": {
            "top_level": grouped_summary(analysis),
            "core": grouped_summary(analysis, focus="core"),
            "services": grouped_summary(analysis, focus="services"),
        },
        "boundaries": [
            {
                "source": source,
                "target": target,
                "imports": [
                    asdict(edge)
                    for edge in find_boundary_edges(
                        analysis.imports,
                        analysis.package,
                        source,
                        target,
                    )
                ],
            }
            for source, target in boundaries
        ],
    }


def _parse_boundary(value: str) -> tuple[str, str]:
    if ":" not in value:
        raise argparse.ArgumentTypeError("boundary must use SOURCE:TARGET")
    source, target = value.split(":", 1)
    source = source.strip()
    target = target.strip()
    if not source or not target:
        raise argparse.ArgumentTypeError("boundary must use SOURCE:TARGET")
    return source, target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyze static imports inside the Brain Researcher package."
    )
    parser.add_argument("--src-root", type=Path, default=Path("src/brain_researcher"))
    parser.add_argument("--package", default="brain_researcher")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    parser.add_argument(
        "--boundary",
        action="append",
        type=_parse_boundary,
        default=[],
        help="Add a boundary report in SOURCE:TARGET form, e.g. core:services.",
    )
    args = parser.parse_args(argv)

    analysis = collect_import_graph(
        src_root=args.src_root,
        package=args.package,
        repo_root=args.repo_root,
    )
    boundaries = list(args.boundary)

    payload = render_json(analysis, boundaries)
    markdown = render_markdown(analysis, boundaries)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(markdown, encoding="utf-8")
    if not args.json_out and not args.markdown_out:
        print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
