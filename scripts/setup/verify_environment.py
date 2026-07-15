#!/usr/bin/env python3
"""Verify one declared Brain Researcher environment profile.

This script is standard-library only. It reports package, import, entrypoint,
external-tool, and service-configuration status without reading or printing any
credential value.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata as metadata
import json
import os
import re
import shutil
import subprocess
import sys
import sysconfig
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

PYTHON_REQUIREMENT = ">=3.11,<3.12"

BASE_PACKAGES = {
    "brain-researcher": ("brain_researcher", None),
    "PyYAML": ("yaml", ">=6,<7"),
    "typer": ("typer", ">=0.24"),
}

PROFILE_PACKAGES = {
    "core": {},
    "mcp": {
        "mcp": ("mcp", ">=1.12"),
        "fastapi": ("fastapi", ">=0.104"),
        "langchain-anthropic": ("langchain_anthropic", ">=0.0.1"),
        "neo4j": ("neo4j", ">=5.28"),
    },
    "agent": {
        "langgraph": ("langgraph", ">=0.0.20"),
        "langchain": ("langchain", ">=0.1"),
        "langchain-anthropic": ("langchain_anthropic", ">=0.0.1"),
        "neo4j": ("neo4j", ">=5.28"),
        "numpy": ("numpy", ">=1.24"),
        "scipy": ("scipy", ">=1.11"),
        "scikit-learn": ("sklearn", ">=1.3"),
        "nibabel": ("nibabel", ">=5.3"),
        "nilearn": ("nilearn", ">=0.11"),
        "nimare": ("nimare", ">=0.5"),
    },
    "br-kg": {
        "neo4j": ("neo4j", ">=5.28"),
        "rapidfuzz": ("rapidfuzz", ">=3"),
        "nibabel": ("nibabel", ">=5.3"),
        "nilearn": ("nilearn", ">=0.11"),
        "scikit-learn": ("sklearn", ">=1.3"),
    },
    "dev": {
        "pytest": ("pytest", ">=7.4"),
        "ruff": ("ruff", ">=0.1"),
        "black": ("black", ">=23"),
        "mkdocs": ("mkdocs", ">=1.5"),
    },
}

PROFILE_INCLUDES = {
    "core": (),
    "mcp": ("mcp",),
    "agent": ("agent",),
    "br-kg": ("br-kg",),
    "dev": ("mcp", "agent", "br-kg", "dev"),
}

PROFILE_ENTRYPOINTS = {
    "core": ("brain-researcher", "brain-researcher-mcp"),
    "mcp": ("brain-researcher-mcp",),
    "agent": ("brain-researcher",),
    "br-kg": ("brain-researcher",),
    "dev": ("brain-researcher", "brain-researcher-mcp"),
}

PROFILE_BINARIES = {
    "core": (("git", False),),
    "mcp": (("curl", False),),
    "agent": (("docker", False),),
    "br-kg": (("cypher-shell", False),),
    "dev": (("git", True), ("docker", False)),
}

SERVICE_ENV_NAMES = {
    "mcp_transport": ("BR_MCP_TRANSPORT",),
    "llm_provider": ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"),
    "neo4j": ("NEO4J_URI", "NEO4J_AUTH"),
}

PROFILE_SERVICES = {
    "core": (),
    "mcp": ("mcp_transport",),
    "agent": ("llm_provider",),
    "br-kg": ("neo4j",),
    "dev": ("mcp_transport", "llm_provider", "neo4j"),
}

SAFE_SUBPROCESS_ENV = (
    "HOME",
    "LANG",
    "LC_ALL",
    "TERM",
    "CONDA_PREFIX",
    "VIRTUAL_ENV",
    "LD_LIBRARY_PATH",
)


def check_python(version_info: Sequence[int] = sys.version_info) -> dict[str, Any]:
    version = ".".join(str(part) for part in version_info[:3])
    return {
        "version": version,
        "requirement": PYTHON_REQUIREMENT,
        "ok": tuple(version_info[:2]) == (3, 11),
    }


def version_satisfies(version: str, requirement: str | None) -> bool:
    """Evaluate the simple numeric bounds used by the environment profiles."""
    if requirement is None:
        return True
    observed_parts = tuple(int(part) for part in re.findall(r"\d+", version)[:4])
    if not observed_parts:
        return False
    for clause in requirement.split(","):
        match = re.fullmatch(r"\s*(>=|<=|==|>|<)\s*(\d+(?:\.\d+)*)\s*", clause)
        if match is None:
            return False
        operator, expected = match.groups()
        expected_parts = tuple(int(part) for part in expected.split("."))
        width = max(len(observed_parts), len(expected_parts))
        observed_value = observed_parts + (0,) * (width - len(observed_parts))
        expected_value = expected_parts + (0,) * (width - len(expected_parts))
        comparisons = {
            ">=": observed_value >= expected_value,
            "<=": observed_value <= expected_value,
            "==": observed_value == expected_value,
            ">": observed_value > expected_value,
            "<": observed_value < expected_value,
        }
        if not comparisons[operator]:
            return False
    return True


def check_package(
    distribution: str,
    import_name: str,
    requirement: str | None,
    *,
    version_lookup: Callable[[str], str] = metadata.version,
    module_importer: Callable[[str], Any] = importlib.import_module,
) -> dict[str, Any]:
    try:
        version = version_lookup(distribution)
        installed = True
    except metadata.PackageNotFoundError:
        version = None
        installed = False

    version_ok = bool(installed and version_satisfies(version, requirement))
    import_error = None
    if installed:
        try:
            module_importer(import_name)
            importable = True
        except Exception as exc:  # importing is the behavior this verifier checks
            importable = False
            import_error = type(exc).__name__
    else:
        importable = False
    return {
        "distribution": distribution,
        "version": version,
        "requirement": requirement,
        "version_ok": version_ok,
        "import": import_name,
        "installed": installed,
        "importable": importable,
        "import_error": import_error,
        "ok": installed and version_ok and importable,
    }


def resolve_current_entrypoint(name: str) -> str | None:
    """Resolve a console script only from the active interpreter's scripts dir."""
    scripts_dir = Path(sysconfig.get_path("scripts")).resolve()
    candidate = shutil.which(name, path=str(scripts_dir))
    if candidate is None:
        return None
    resolved = Path(candidate).resolve()
    if resolved.parent != scripts_dir:
        return None
    return str(resolved)


def safe_subprocess_env(environ: Mapping[str, str] = os.environ) -> dict[str, str]:
    """Return a minimal environment that never forwards credential variables."""
    safe = {name: environ[name] for name in SAFE_SUBPROCESS_ENV if environ.get(name)}
    safe["PATH"] = os.pathsep.join((sysconfig.get_path("scripts"), os.defpath))
    safe["NO_COLOR"] = "1"
    safe["PYTHONNOUSERSITE"] = "1"
    return safe


def check_entrypoint(
    name: str,
    *,
    resolver: Callable[[str], str | None] = resolve_current_entrypoint,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    path = resolver(name)
    if path is None:
        return {"name": name, "path": None, "returncode": None, "ok": False}

    try:
        completed = runner(
            [path, "--help"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env=safe_subprocess_env(),
            cwd=str(Path(sys.prefix).resolve()),
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"name": name, "path": path, "returncode": None, "ok": False}
    return {
        "name": name,
        "path": path,
        "returncode": completed.returncode,
        "ok": completed.returncode == 0,
    }


def check_binary(
    name: str,
    required: bool,
    *,
    which: Callable[[str], str | None] = shutil.which,
) -> dict[str, Any]:
    path = which(name)
    return {
        "name": name,
        "required": required,
        "path": path,
        "available": path is not None,
        "ok": path is not None or not required,
    }


def check_service(name: str, environ: Mapping[str, str] = os.environ) -> dict[str, Any]:
    variable_names = SERVICE_ENV_NAMES[name]
    present = [variable for variable in variable_names if bool(environ.get(variable))]
    if name == "neo4j":
        configured = len(present) == len(variable_names)
    else:
        configured = bool(present)
    return {
        "name": name,
        "status": "configured" if configured else "not_configured",
        "configured_variables": present,
        "expected_variables": list(variable_names),
        "required": False,
    }


def build_report(profile: str, *, skip_cli: bool = False) -> dict[str, Any]:
    packages = dict(BASE_PACKAGES)
    for included_profile in PROFILE_INCLUDES[profile]:
        packages.update(PROFILE_PACKAGES[included_profile])
    package_rows = [
        check_package(distribution, import_name, requirement)
        for distribution, (import_name, requirement) in packages.items()
    ]
    entrypoint_rows = (
        []
        if skip_cli
        else [check_entrypoint(name) for name in PROFILE_ENTRYPOINTS[profile]]
    )
    binary_rows = [
        check_binary(name, required) for name, required in PROFILE_BINARIES[profile]
    ]
    service_rows = [check_service(name) for name in PROFILE_SERVICES[profile]]
    python_row = check_python()

    failures = []
    if not python_row["ok"]:
        failures.append("python")
    failures.extend(
        f"package:{row['distribution']}" for row in package_rows if not row["ok"]
    )
    failures.extend(
        f"entrypoint:{row['name']}" for row in entrypoint_rows if not row["ok"]
    )
    failures.extend(f"binary:{row['name']}" for row in binary_rows if not row["ok"])

    return {
        "schema_version": "br.environment_report.v1",
        "profile": profile,
        "ok": not failures,
        "python": python_row,
        "packages": package_rows,
        "entrypoints": entrypoint_rows,
        "entrypoints_skipped": skip_cli,
        "external_tools": binary_rows,
        "services": service_rows,
        "failures": failures,
    }


def format_human(report: Mapping[str, Any]) -> str:
    lines = [
        f"Brain Researcher environment profile: {report['profile']}",
        f"Python {report['python']['version']} ({report['python']['requirement']}): "
        f"{'ok' if report['python']['ok'] else 'FAIL'}",
        "Packages:",
    ]
    for row in report["packages"]:
        version = row["version"] or "missing"
        lines.append(
            f"  {'ok' if row['ok'] else 'FAIL':4} {row['distribution']} {version}"
        )
    if report["entrypoints_skipped"]:
        lines.append("Entrypoints: skipped by request")
    else:
        lines.append("Entrypoints:")
        for row in report["entrypoints"]:
            lines.append(f"  {'ok' if row['ok'] else 'FAIL':4} {row['name']}")
    lines.append("External tools:")
    for row in report["external_tools"]:
        qualifier = "required" if row["required"] else "optional"
        lines.append(
            f"  {'ok' if row['available'] else 'warn':4} {row['name']} ({qualifier})"
        )
    if report["services"]:
        lines.append("Service configuration (values are never read or printed):")
        for row in report["services"]:
            lines.append(f"  {row['name']}: {row['status']}")
    lines.append("Result: PASS" if report["ok"] else "Result: FAIL")
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        choices=tuple(PROFILE_INCLUDES),
        default="core",
        help="Declared dependency profile to verify (default: core).",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    parser.add_argument(
        "--skip-cli",
        action="store_true",
        help="Skip entrypoint subprocess checks (diagnostics only).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(args.profile, skip_cli=args.skip_cli)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_human(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
