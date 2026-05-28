#!/usr/bin/env python3
"""Compile taxonomy family crosswalks into mapping_rules.generated.yaml."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict

import typer
import yaml

app = typer.Typer(help="Sync taxonomy family crosswalks into mapping rules")


def load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


@app.command()
def compile(
    crosswalk: Path = typer.Option(
        Path("configs/taxonomy/crosswalks/families__to__onvoc.v1.yaml"),
        exists=True,
        readable=True,
        help="Crosswalk file mapping tf_* families to ONVOC URIs",
    ),
    mapping_rules: Path = typer.Option(
        Path("configs/mapping_rules.yaml"),
        exists=True,
        readable=True,
        help="Existing manual mapping rules (used to look up ONVOC labels)",
    ),
    output: Path = typer.Option(
        Path("configs/mapping_rules.generated.yaml"),
        help="Destination for generated rules",
    ),
) -> None:
    crosswalk_cfg = load_yaml(crosswalk)

    try:
        mapping_cfg = load_yaml(mapping_rules)
    except Exception as exc:  # pragma: no cover - best-effort fallback
        typer.echo(
            f"Warning: failed to parse {mapping_rules} ({exc}); proceeding without manual label lookup",
            err=True,
        )
        mapping_cfg = {}

    label_lookup: Dict[str, str] = {}
    for anchor in mapping_cfg.get("anchors", []):
        uri = anchor.get("onvoc_uri")
        if uri and uri not in label_lookup:
            label_lookup[uri] = anchor.get("label")

    defaults = crosswalk_cfg.get("defaults", {})
    default_accept = defaults.get("accept", {})

    anchors_out = []
    for entry in crosswalk_cfg.get("mappings", []):
        onvoc_uri = entry["onvoc_uri"]
        label = entry.get("label") or label_lookup.get(onvoc_uri) or onvoc_uri
        family_id = entry.get("family_id")

        seed_slugs = entry.get("seeds", {}).get("slugs", [])
        seed_tasks = [{"slug": slug} for slug in seed_slugs]

        matchers: Dict[str, Any] = {}
        if entry.get("keywords_any"):
            matchers["keywords_any"] = entry["keywords_any"]
        if entry.get("regex"):
            matchers["regex"] = entry["regex"]

        accept_cfg = default_accept.copy()
        if entry.get("accept"):
            accept_cfg.update(entry["accept"])

        anchor_out: Dict[str, Any] = {
            "family_id": family_id,
            "onvoc_uri": onvoc_uri,
            "label": label,
        }
        if seed_tasks:
            anchor_out["seed_tasks"] = seed_tasks
        if matchers:
            anchor_out["matchers"] = matchers
        if accept_cfg:
            anchor_out["accept"] = accept_cfg

        anchors_out.append(anchor_out)

    generated = {
        "generated_from": {
            "crosswalk": str(crosswalk),
            "ruleset_version": crosswalk_cfg.get("ruleset_version"),
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        },
        "anchors": anchors_out,
    }

    ensure_parent(output)
    with output.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(generated, handle, sort_keys=False, allow_unicode=True)

    typer.echo(
        f"Wrote {len(anchors_out)} generated anchors to {output} using crosswalk {crosswalk.name}"
    )


if __name__ == "__main__":
    app()
