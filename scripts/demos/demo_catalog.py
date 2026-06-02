#!/usr/bin/env python3
"""Demo script showing capability catalog functionality."""

import os

# Enable catalog mode
os.environ["BR_PLANNER_SOURCE"] = "catalog"

from brain_researcher.services.agent.planner.catalog_loader import (
    get_capability_index,
    get_tool_by_id,
    search_by_capability,
    search_by_modality,
    search_by_package,
)


def main():
    print("=" * 70)
    print("Brain Researcher Capability Catalog Demo")
    print("=" * 70)
    print()

    # Get index
    print("Loading capability index...")
    index = get_capability_index()
    print(f"✓ Loaded {len(index.by_id)} tools")
    print()

    # Show packages
    print("Available Packages:")
    print("-" * 70)
    for package, tool_ids in sorted(index.by_package.items()):
        print(f"  {package:15} - {len(tool_ids)} tools")
    print()

    # Show modalities
    print("Supported Modalities:")
    print("-" * 70)
    for modality, tool_ids in sorted(index.by_modality.items()):
        print(f"  {modality:10} - {len(tool_ids)} tools")
    print()

    # Show capabilities
    print("Available Capabilities (sample):")
    print("-" * 70)
    for i, (capability, tool_ids) in enumerate(sorted(index.by_capability.items())):
        if i < 10:  # Show first 10
            print(f"  {capability:25} - {len(tool_ids)} tool(s)")
    print(f"  ... and {len(index.by_capability) - 10} more")
    print()

    # Example 1: Get specific tool
    print("Example 1: Get Specific Tool")
    print("-" * 70)
    tool = get_tool_by_id("fsl.bet.run")
    if tool:
        print(f"Tool: {tool.name}")
        print(f"  ID: {tool.id}")
        print(f"  Package: {tool.package}")
        print(f"  Modality: {', '.join(tool.modality)}")
        print(f"  Capabilities: {', '.join(tool.capabilities)}")
        print(f"  Resources: {tool.resources.cpu_min} CPU, {tool.resources.mem_mb_min} MB")
        print(f"  Container: {tool.container.package_ref} ({tool.container.runtime})")
    print()

    # Example 2: Search by capability
    print("Example 2: Search by Capability (skull_strip)")
    print("-" * 70)
    tools = search_by_capability("skull_strip")
    for tool in tools:
        print(f"  - {tool.name:30} [{tool.package}]")
    print()

    # Example 3: Search by modality
    print("Example 3: Search by Modality (fmri)")
    print("-" * 70)
    tools = search_by_modality("fmri")
    for tool in tools[:5]:  # Show first 5
        print(f"  - {tool.name:30} [{', '.join(tool.capabilities[:3])}...]")
    if len(tools) > 5:
        print(f"  ... and {len(tools) - 5} more")
    print()

    # Example 4: Search by package
    print("Example 4: Search by Package (ants)")
    print("-" * 70)
    tools = search_by_package("ants")
    for tool in tools:
        print(f"  - {tool.name:40} {tool.id}")
    print()

    print("=" * 70)
    print("Demo Complete!")
    print("=" * 70)


if __name__ == "__main__":
    main()
