#!/usr/bin/env python3
"""
Update tools_catalog.json with categories from tool_categories.yaml

This script reads the tool categorization rules and applies them to
tools_catalog.json, replacing "unknown" categories with appropriate ones.
"""

import json
import re
from pathlib import Path
from typing import Dict, List

import yaml


def load_category_config() -> Dict:
    """Load tool_categories.yaml configuration."""
    config_path = Path(__file__).parent.parent / "configs" / "tool_categories.yaml"
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def categorize_tool(tool_name: str, config: Dict) -> str:
    """
    Categorize a tool based on its name using the configuration.

    Returns the category name or "unknown" if no match found.
    """
    pattern_matching = config.get("pattern_matching", {})

    # First, try exact matches
    exact_matches = pattern_matching.get("exact_matches", {})
    if tool_name in exact_matches:
        return exact_matches[tool_name]

    # Then, try pattern rules
    pattern_rules = pattern_matching.get("pattern_rules", [])
    for rule in pattern_rules:
        pattern = rule.get("pattern", "")
        category = rule.get("category", "")
        if pattern and category:
            if re.match(pattern, tool_name, re.IGNORECASE):
                return category

    return config.get("default_category", "unknown")


def update_tools_catalog():
    """Update tools_catalog.json with categories."""
    repo_root = Path(__file__).parent.parent
    catalog_path = repo_root / "configs" / "tools_catalog.json"
    config_path = repo_root / "configs" / "tool_categories.yaml"

    # Load configuration
    print(f"Loading category configuration from {config_path}...")
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    # Load tools catalog
    print(f"Loading tools catalog from {catalog_path}...")
    with open(catalog_path, "r") as f:
        catalog = json.load(f)

    # Update categories
    tools = catalog.get("tools", [])
    updated_count = 0

    print(f"\nCategorizing {len(tools)} tools...")
    for tool in tools:
        tool_name = tool.get("name", "")
        current_category = tool.get("category", "unknown")

        if current_category == "unknown":
            new_category = categorize_tool(tool_name, config)
            if new_category != "unknown":
                tool["category"] = new_category
                updated_count += 1
                print(f"  {tool_name}: {current_category} -> {new_category}")

    # Save updated catalog
    print(f"\nUpdated {updated_count} tools. Saving to {catalog_path}...")
    with open(catalog_path, "w") as f:
        json.dump(catalog, f, indent=2)

    # Print summary
    category_counts = {}
    for tool in tools:
        cat = tool.get("category", "unknown")
        category_counts[cat] = category_counts.get(cat, 0) + 1

    print("\nCategory distribution:")
    for cat, count in sorted(category_counts.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count}")

    print(f"\n✅ Done! Updated {updated_count} tools.")


if __name__ == "__main__":
    update_tools_catalog()
