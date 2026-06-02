#!/usr/bin/env python3
"""Migrate predictive/discovery line roots under /data/brain_researcher/research."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from brain_researcher.autoresearch.artifact_schema import (
    DEFAULT_DATA_ROOT,
    LINE_SPECS,
    canonical_line_root,
    legacy_line_root,
    resolve_data_root,
)

ActionKind = Literal["mkdir", "move", "symlink", "skip", "conflict"]


@dataclass(frozen=True)
class MigrationAction:
    line_id: str
    kind: ActionKind
    source: str | None
    destination: str | None
    detail: str


def plan_line_migration(line_id: str, *, data_root: Path) -> list[MigrationAction]:
    spec = LINE_SPECS[line_id]  # type: ignore[index]
    canonical_root = canonical_line_root(spec.line_id, data_root=data_root)
    legacy_root = legacy_line_root(spec.line_id, data_root=data_root)
    actions: list[MigrationAction] = []

    research_root = data_root / "research"
    if research_root.exists():
        actions.append(
            MigrationAction(line_id, "skip", None, str(research_root), "research root already exists")
        )
    else:
        actions.append(
            MigrationAction(line_id, "mkdir", None, str(research_root), "create shared research root")
        )

    legacy_exists = legacy_root.exists() or legacy_root.is_symlink()
    canonical_exists = canonical_root.exists() or canonical_root.is_symlink()

    if canonical_exists and legacy_root.is_symlink() and legacy_root.resolve() == canonical_root:
        actions.append(
            MigrationAction(
                line_id,
                "skip",
                str(legacy_root),
                str(canonical_root),
                "legacy alias already points to canonical root",
            )
        )
        return actions

    if not canonical_exists and legacy_exists and not legacy_root.is_symlink():
        actions.append(
            MigrationAction(
                line_id,
                "move",
                str(legacy_root),
                str(canonical_root),
                "move legacy line root under research/",
            )
        )
    elif canonical_exists and legacy_exists and not legacy_root.is_symlink():
        actions.append(
            MigrationAction(
                line_id,
                "conflict",
                str(legacy_root),
                str(canonical_root),
                "both canonical and legacy roots exist as materialized directories",
            )
        )
        return actions
    elif not canonical_exists and not legacy_exists:
        actions.append(
            MigrationAction(
                line_id,
                "conflict",
                str(legacy_root),
                str(canonical_root),
                "neither legacy nor canonical root exists",
            )
        )
        return actions
    else:
        actions.append(
            MigrationAction(
                line_id,
                "skip",
                str(legacy_root if legacy_exists else canonical_root),
                str(canonical_root),
                "canonical root already materialized",
            )
        )

    if not legacy_root.is_symlink():
        actions.append(
            MigrationAction(
                line_id,
                "symlink",
                str(canonical_root),
                str(legacy_root),
                "create one-release compatibility alias",
            )
        )
    else:
        actions.append(
            MigrationAction(
                line_id,
                "skip",
                str(legacy_root),
                str(canonical_root),
                "legacy path is already a symlink",
            )
        )
    return actions


def apply_actions(actions: list[MigrationAction]) -> None:
    for action in actions:
        if action.kind in {"skip", "conflict"}:
            continue
        if action.kind == "mkdir":
            assert action.destination is not None
            Path(action.destination).mkdir(parents=True, exist_ok=True)
            continue
        if action.kind == "move":
            assert action.source is not None and action.destination is not None
            source = Path(action.source)
            destination = Path(action.destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.rename(destination)
            continue
        if action.kind == "symlink":
            assert action.source is not None and action.destination is not None
            source = Path(action.source)
            destination = Path(action.destination)
            if destination.exists() or destination.is_symlink():
                if destination.is_symlink() and destination.resolve() == source.resolve():
                    continue
                raise FileExistsError(
                    f"Cannot create compatibility symlink; destination already exists: {destination}"
                )
            os.symlink(source, destination)
            continue
        raise ValueError(f"Unhandled migration action: {action.kind}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--apply", action="store_true", help="Apply the migration instead of printing the plan.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of human-readable text.")
    return parser


def render_human(actions: list[MigrationAction]) -> str:
    lines = []
    for action in actions:
        src = f" source={action.source}" if action.source else ""
        dst = f" dest={action.destination}" if action.destination else ""
        lines.append(f"[{action.line_id}] {action.kind}{src}{dst} :: {action.detail}")
    return "\n".join(lines) + ("\n" if lines else "")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    data_root = resolve_data_root(args.data_root)
    actions: list[MigrationAction] = []
    for line_id in ("predictive", "discovery"):
        actions.extend(plan_line_migration(line_id, data_root=data_root))

    conflicts = [action for action in actions if action.kind == "conflict"]
    if args.apply and not conflicts:
        apply_actions(actions)

    if args.json:
        payload = {
            "data_root": str(data_root),
            "applied": bool(args.apply and not conflicts),
            "conflicts": [asdict(action) for action in conflicts],
            "actions": [asdict(action) for action in actions],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_human(actions), end="")
        if args.apply and conflicts:
            print("apply aborted due to conflicts")

    return 1 if conflicts else 0


if __name__ == "__main__":
    raise SystemExit(main())
