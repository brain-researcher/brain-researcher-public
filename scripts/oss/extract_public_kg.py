"""Extract a sanitized public subset of the live Brain Researcher KG.

Reads configs/br-kg/pii_redaction.yaml (profile = "public") and applies
per-label keep/drop/transform rules. For labels not covered by the PII
config, applies a hardcoded ship/drop policy declared below.

Output:
- <out>/kg_public.cypher           reproducible CREATE script
- <out>/kg_public_manifest.json    per-label counts + exclusion reasons + sha256

Usage (caller supplies Neo4j connection via env vars, never via CLI):
    export NEO4J_URI=bolt://localhost:7687
    export NEO4J_USER=neo4j
    export NEO4J_PASSWORD=...
    python scripts/oss/extract_public_kg.py --out /tmp/kg-public-v0.1.0

Or in dry-run-against-fixtures mode (no Neo4j needed):
    python scripts/oss/extract_public_kg.py --dry-run --out /tmp/kg-public-v0.1.0
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    sys.exit("install pyyaml first: pip install pyyaml")

REPO_ROOT = Path(__file__).resolve().parents[2]
PII_CONFIG = REPO_ROOT / "configs" / "br-kg" / "pii_redaction.yaml"

# All node labels accepted by bulk_loader.VALID_NODE_TYPES. Mirrored here so
# the extractor stays runnable without importing brain_researcher.
ALL_NODE_LABELS = {
    "Concept", "Task", "TaskFamily", "Region", "BrainRegion", "Atlas",
    "Dataset", "Publication", "Study", "Coordinate", "StatisticalMap",
    "StatsMap", "StatMap", "Author", "Construct", "Contrast",
    "DiseaseTrait", "Population", "Gene", "RiskLocus", "Subject",
    "SubjectGroup", "Phenotype", "Assumption", "Claim", "EvidenceSpan",
    "MeasurementRun",
    # Review machinery — config-like, generally shareable
    "ReviewCalibrationCase", "ReviewImplementationRule",
    "ReviewImplementationRuleCatalog", "ReviewLifecycleStatus",
    "ReviewPolicyDecision", "ReviewPositiveModifier", "ReviewReasonTag",
    "ReviewRule", "ReviewRuleGroup", "ReviewRuleRegistry",
    "ReviewSchemaField", "ReviewSensitivityTemplate", "ReviewSeverity",
    "ReviewValidityLayer",
    # Session / runtime state — internal-only, drop from public
    "AgentSession", "TaskSurface", "ValidationEvidence", "OpenRisk",
    "Outcome", "Lesson", "NextAction",
}

# Labels not covered by pii_redaction.yaml's "public" profile.
# Default ship/drop policy applied here. Override on a per-deployment basis
# by editing this file or supplying --policy-overlay.
UNCOVERED_DEFAULT_POLICY = {
    # Scientific reference data — ship all non-PII properties
    "ship": {
        "TaskFamily", "BrainRegion", "Atlas", "Author", "Construct",
        "Contrast", "DiseaseTrait", "Population", "Gene", "RiskLocus",
        "Phenotype", "Assumption", "Claim", "EvidenceSpan",
        "MeasurementRun", "Study", "StatsMap", "StatMap",
        # Review config: catalog-like, no per-session state
        "ReviewImplementationRule", "ReviewImplementationRuleCatalog",
        "ReviewLifecycleStatus", "ReviewPositiveModifier",
        "ReviewReasonTag", "ReviewRule", "ReviewRuleGroup",
        "ReviewRuleRegistry", "ReviewSchemaField",
        "ReviewSensitivityTemplate", "ReviewSeverity",
        "ReviewValidityLayer", "ReviewCalibrationCase",
    },
    # Session / runtime / internal-policy — DROP entirely
    "drop": {
        "AgentSession", "TaskSurface", "ValidationEvidence", "OpenRisk",
        "Outcome", "Lesson", "NextAction", "ReviewPolicyDecision",
    },
}

# Properties stripped from EVERY shipped node (defense in depth)
ALWAYS_STRIP_PROPERTIES = {
    "_internal", "_debug", "_sentry_id", "session_id", "client_session_id",
    "user_email", "uploader", "owner_email", "author_email",
    "api_key", "auth_token", "bearer", "ssh_key", "secret",
    "local_path", "absolute_path", "host_path",
}


def load_pii_profile(profile_name: str = "public") -> dict[str, Any]:
    with PII_CONFIG.open() as fh:
        config = yaml.safe_load(fh)
    return (config.get("profiles") or {}).get(profile_name, {})


def label_policy(label: str, pii_profile: dict) -> dict:
    """Return {action: keep|drop|ship_default, keep: [...], drop: [...]}."""
    pii_nodes = pii_profile.get("nodes") or {}
    if label in pii_nodes:
        rules = pii_nodes[label]
        return {
            "action": "pii_explicit",
            "keep": rules.get("keep") or [],
            "drop": rules.get("drop") or [],
            "transforms": rules.get("transforms") or {},
        }
    if label in UNCOVERED_DEFAULT_POLICY["drop"]:
        return {"action": "drop_uncovered_internal"}
    if label in UNCOVERED_DEFAULT_POLICY["ship"]:
        return {"action": "ship_default", "keep": [], "drop": []}
    return {"action": "drop_unknown_label"}


def filter_node_properties(label: str, props: dict, policy: dict) -> dict:
    """Apply keep/drop/strip rules to a node's property dict."""
    out = dict(props)
    for k in list(out.keys()):
        if k in ALWAYS_STRIP_PROPERTIES:
            out.pop(k, None)
    action = policy["action"]
    if action == "pii_explicit":
        keep_set = set(policy["keep"])
        if keep_set:
            out = {k: v for k, v in out.items() if k in keep_set}
        for k in policy["drop"]:
            out.pop(k, None)
    return out


def cypher_quote(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, list):
        return "[" + ", ".join(cypher_quote(x) for x in v) + "]"
    s = str(v).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{s}'"


def emit_node_cypher(label: str, props: dict) -> str:
    props_str = ", ".join(f"{k}: {cypher_quote(v)}" for k, v in props.items())
    return f"CREATE (:{label} {{{props_str}}});\n"


def extract_from_neo4j(out_dir: Path) -> dict:
    """Connect to Neo4j and stream filtered nodes/edges out."""
    try:
        from neo4j import GraphDatabase
    except ImportError:
        sys.exit("install neo4j driver first: pip install neo4j")
    uri = os.environ["NEO4J_URI"]
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ["NEO4J_PASSWORD"]

    pii_profile = load_pii_profile("public")
    counts_kept = defaultdict(int)
    counts_dropped = defaultdict(int)
    drop_reasons = defaultdict(set)

    cypher_path = out_dir / "kg_public.cypher"
    cypher_fh = cypher_path.open("w")

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session() as session:
            for label in sorted(ALL_NODE_LABELS):
                policy = label_policy(label, pii_profile)
                if policy["action"].startswith("drop_"):
                    # Count what we're skipping
                    total = session.run(
                        f"MATCH (n:{label}) RETURN count(n) AS c"
                    ).single()["c"]
                    if total:
                        counts_dropped[label] = total
                        drop_reasons[label].add(policy["action"])
                    continue

                stream = session.run(f"MATCH (n:{label}) RETURN n LIMIT 500000")
                for record in stream:
                    raw = dict(record["n"])
                    clean = filter_node_properties(label, raw, policy)
                    cypher_fh.write(emit_node_cypher(label, clean))
                    counts_kept[label] += 1
    finally:
        driver.close()
        cypher_fh.close()

    return {
        "kept": dict(counts_kept),
        "dropped": dict(counts_dropped),
        "drop_reasons": {k: list(v) for k, v in drop_reasons.items()},
    }


def extract_from_fixtures(out_dir: Path) -> dict:
    """Dry-run: use bundled sample JSONL fixtures so the pipeline can be
    tested without a live Neo4j."""
    sample = REPO_ROOT / "tests" / "fixtures" / "br_kg" / "gabriel_measurements.sample.jsonl"
    counts_kept = defaultdict(int)
    cypher_path = out_dir / "kg_public.cypher"
    pii_profile = load_pii_profile("public")
    with cypher_path.open("w") as cypher_fh, sample.open() as fh:
        for line in fh:
            row = json.loads(line)
            # Sample fixture is GABRIEL measurement records, not raw node dumps.
            # Synthesize a minimal Claim node per row to exercise the pipeline.
            label = "Claim"
            policy = label_policy(label, pii_profile)
            props = {
                "id": row.get("claim_id") or row.get("id") or "unknown",
                "text": row.get("claim_text", "")[:200],
            }
            clean = filter_node_properties(label, props, policy)
            cypher_fh.write(emit_node_cypher(label, clean))
            counts_kept[label] += 1
    return {"kept": dict(counts_kept), "dropped": {}, "drop_reasons": {}}


def write_manifest(out_dir: Path, counts: dict, dry_run: bool) -> Path:
    cypher_path = out_dir / "kg_public.cypher"
    sha256 = hashlib.sha256(cypher_path.read_bytes()).hexdigest()
    manifest = {
        "extractor_version": "0.1.0",
        "source_mode": "fixtures-dry-run" if dry_run else "neo4j",
        "pii_profile": "public",
        "cypher_path": str(cypher_path.relative_to(out_dir.parent)),
        "cypher_sha256": sha256,
        "cypher_size_bytes": cypher_path.stat().st_size,
        "labels_covered_by_pii_config": sorted(
            (load_pii_profile("public").get("nodes") or {}).keys()
        ),
        "labels_shipped_by_default_uncovered_whitelist": sorted(
            UNCOVERED_DEFAULT_POLICY["ship"]
        ),
        "labels_dropped_by_default_uncovered_blacklist": sorted(
            UNCOVERED_DEFAULT_POLICY["drop"]
        ),
        "labels_dropped_unknown_to_extractor": sorted(
            ALL_NODE_LABELS
            - set((load_pii_profile("public").get("nodes") or {}).keys())
            - UNCOVERED_DEFAULT_POLICY["ship"]
            - UNCOVERED_DEFAULT_POLICY["drop"]
        ),
        "always_stripped_properties": sorted(ALWAYS_STRIP_PROPERTIES),
        "counts": counts,
    }
    path = out_dir / "kg_public_manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=False) + "\n")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Directory to write kg_public.cypher + kg_public_manifest.json into.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip Neo4j; build a tiny output from the bundled GABRIEL sample fixture.",
    )
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    if args.dry_run:
        counts = extract_from_fixtures(args.out)
    else:
        if not os.environ.get("NEO4J_URI") or not os.environ.get("NEO4J_PASSWORD"):
            sys.exit("set NEO4J_URI and NEO4J_PASSWORD env vars (or use --dry-run)")
        counts = extract_from_neo4j(args.out)

    manifest_path = write_manifest(args.out, counts, dry_run=args.dry_run)
    print(f"wrote {args.out / 'kg_public.cypher'}")
    print(f"wrote {manifest_path}")
    print(f"\nLabel summary:")
    for label, n in sorted(counts.get("kept", {}).items()):
        print(f"  kept    {n:>8}  {label}")
    for label, n in sorted(counts.get("dropped", {}).items()):
        reasons = counts.get("drop_reasons", {}).get(label, [])
        print(f"  dropped {n:>8}  {label}  ({', '.join(reasons)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
