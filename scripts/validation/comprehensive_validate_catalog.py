#!/usr/bin/env python
"""Comprehensive validation of tool catalog metadata.

Checks domain, function, runtime_kind, risk, and normalized tags for all tools.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from brain_researcher.services.tools.metadata_schema import (
    DOMAIN,
    FUNCTION,
    RISK,
    RUNTIME_KIND,
    normalize_tags,
    validate_metadata,
)

CATALOG = Path("configs/tools_catalog_merged.json")


def main() -> int:
    if not CATALOG.exists():
        print(f"Missing catalog file: {CATALOG}")
        return 1

    print(f"Loading catalog from {CATALOG}...")
    data = json.loads(CATALOG.read_text())
    tools = data.get("tools", data if isinstance(data, list) else [])
    print(f"Found {len(tools)} tools\n")

    # Track all issues
    validation_errors = []
    tag_normalization_issues = []
    field_statistics = defaultdict(int)

    # Track field values for analysis
    domain_values = defaultdict(int)
    function_values = defaultdict(int)
    runtime_kind_values = defaultdict(int)
    risk_values = defaultdict(int)

    for idx, tool in enumerate(tools, 1):
        tool_name = tool.get("name") or tool.get("id") or f"tool_{idx}"

        meta = {
            "domain": tool.get("domain"),
            "function": tool.get("function"),
            "runtime_kind": tool.get("runtime_kind"),
            "risk": tool.get("risk"),
            "exposure": tool.get("exposure"),
            "tags": tool.get("tags"),
        }

        # Collect statistics
        if meta["domain"]:
            domain_values[meta["domain"]] += 1
        if meta["function"]:
            function_values[meta["function"]] += 1
        if meta["runtime_kind"]:
            runtime_kind_values[meta["runtime_kind"]] += 1
        if meta["risk"]:
            risk_values[meta["risk"]] += 1
        # exposure is tracked via validate_metadata; we don't bin-count separately

        # Validate metadata fields
        errs = validate_metadata(meta)
        if errs:
            validation_errors.append((tool_name, errs))
            field_statistics["validation_errors"] += 1
            # Skip tag normalization for tools with validation errors
            # to avoid processing malformed data (e.g., tags as string instead of list)
            continue

        # Check tag normalization (only for tools that passed validation)
        tags = set(meta.get("tags") or [])
        expected_tags = set()

        # Build expected tags from core fields
        for key in ("domain", "function", "runtime_kind", "risk"):
            val = meta.get(key)
            if val:
                expected_tags.add(str(val))

        # Check if tags are normalized (include all core fields)
        missing_tags = expected_tags - tags

        # Also check for mismatches (tags that don't match field values)
        tag_mismatches = []
        if meta["domain"] and meta["domain"] not in tags:
            tag_mismatches.append(f"domain '{meta['domain']}' missing from tags")
        if meta["function"] and meta["function"] not in tags:
            tag_mismatches.append(f"function '{meta['function']}' missing from tags")
        if meta["runtime_kind"] and meta["runtime_kind"] not in tags:
            tag_mismatches.append(f"runtime_kind '{meta['runtime_kind']}' missing from tags")
        if meta["risk"] and meta["risk"] not in tags:
            tag_mismatches.append(f"risk '{meta['risk']}' missing from tags")

        if missing_tags or tag_mismatches:
            normalized = normalize_tags(meta)
            tag_normalization_issues.append({
                "tool": tool_name,
                "missing_tags": sorted(missing_tags),
                "mismatches": tag_mismatches,
                "current_tags": sorted(tags),
                "normalized_tags": normalized,
                "domain": meta["domain"],
                "function": meta["function"],
                "runtime_kind": meta["runtime_kind"],
                "risk": meta["risk"],
            })
            field_statistics["tag_issues"] += 1

    # Print summary
    print("=" * 80)
    print("VALIDATION SUMMARY")
    print("=" * 80)
    print(f"\nTotal tools checked: {len(tools)}")
    print(f"Tools with validation errors: {len(validation_errors)}")
    print(f"Tools with tag normalization issues: {len(tag_normalization_issues)}")

    # Print field value distributions
    print("\n" + "=" * 80)
    print("FIELD VALUE DISTRIBUTIONS")
    print("=" * 80)

    print(f"\nDomain values ({len(domain_values)} unique):")
    for domain, count in sorted(domain_values.items(), key=lambda x: -x[1]):
        print(f"  {domain:20s}: {count:4d}")

    print(f"\nFunction values ({len(function_values)} unique):")
    for func, count in sorted(function_values.items(), key=lambda x: -x[1]):
        print(f"  {func:20s}: {count:4d}")

    print(f"\nRuntime_kind values ({len(runtime_kind_values)} unique):")
    for rk, count in sorted(runtime_kind_values.items(), key=lambda x: -x[1]):
        print(f"  {rk:20s}: {count:4d}")

    print(f"\nRisk values ({len(risk_values)} unique):")
    for risk, count in sorted(risk_values.items(), key=lambda x: -x[1]):
        print(f"  {risk:20s}: {count:4d}")

    # Print validation errors
    if validation_errors:
        print("\n" + "=" * 80)
        print("VALIDATION ERRORS")
        print("=" * 80)
        for tool_name, errs in validation_errors[:50]:  # Show first 50
            print(f"\n{tool_name}:")
            for err in errs:
                print(f"  - {err}")
        if len(validation_errors) > 50:
            print(f"\n... and {len(validation_errors) - 50} more tools with errors")

    # Print tag normalization issues
    if tag_normalization_issues:
        print("\n" + "=" * 80)
        print("TAG NORMALIZATION ISSUES")
        print("=" * 80)
        print(f"\nFound {len(tag_normalization_issues)} tools with missing tags in normalized form")

        # Group by missing tag type
        missing_by_type = defaultdict(list)
        for issue in tag_normalization_issues:
            for tag in issue["missing_tags"]:
                missing_by_type[tag].append(issue["tool"])

        print("\nMissing tags breakdown:")
        for tag, tools_list in sorted(missing_by_type.items()):
            print(f"  {tag}: {len(tools_list)} tools")

        # Show examples
        print("\nExample issues (first 20):")
        for issue in tag_normalization_issues[:20]:
            print(f"\n  {issue['tool']}:")
            print(f"    Domain: {issue['domain']}, Function: {issue['function']}, Runtime: {issue['runtime_kind']}, Risk: {issue['risk']}")
            if issue['missing_tags']:
                print(f"    Missing tags: {', '.join(issue['missing_tags'])}")
            if issue['mismatches']:
                print(f"    Mismatches: {', '.join(issue['mismatches'])}")
            print(f"    Current tags ({len(issue['current_tags'])}): {', '.join(issue['current_tags'][:10])}{'...' if len(issue['current_tags']) > 10 else ''}")

    # Check for invalid values
    print("\n" + "=" * 80)
    print("INVALID VALUE CHECKS")
    print("=" * 80)

    invalid_domains = set(domain_values.keys()) - DOMAIN
    invalid_functions = set(function_values.keys()) - FUNCTION
    invalid_runtime_kinds = set(runtime_kind_values.keys()) - RUNTIME_KIND
    invalid_risks = set(risk_values.keys()) - RISK

    if invalid_domains:
        print(f"\nInvalid domain values found: {invalid_domains}")
    else:
        print("\n✓ All domain values are valid")

    if invalid_functions:
        print(f"\nInvalid function values found: {invalid_functions}")
    else:
        print("✓ All function values are valid")

    if invalid_runtime_kinds:
        print(f"\nInvalid runtime_kind values found: {invalid_runtime_kinds}")
    else:
        print("✓ All runtime_kind values are valid")

    if invalid_risks:
        print(f"\nInvalid risk values found: {invalid_risks}")
    else:
        print("✓ All risk values are valid")

    # Final summary
    print("\n" + "=" * 80)
    print("FINAL SUMMARY")
    print("=" * 80)

    total_issues = len(validation_errors) + len(tag_normalization_issues)
    if total_issues == 0:
        print("\n✓ All tools pass validation!")
        print("✓ All tags are properly normalized!")
        return 0
    else:
        print(f"\n✗ Found {total_issues} total issues:")
        print(f"  - {len(validation_errors)} tools with validation errors")
        print(f"  - {len(tag_normalization_issues)} tools with tag normalization issues")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
