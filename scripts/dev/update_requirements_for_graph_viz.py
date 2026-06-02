#!/usr/bin/env python3
"""
Update requirements.txt to include dependencies for graph visualization
"""


def update_requirements():
    """Add graph visualization dependencies to requirements.txt"""

    new_deps = [
        "flask>=2.0.0",
        "dash>=2.14.0",
        "dash-cytoscape>=0.3.0",
        "requests>=2.25.0",
    ]

    requirements_file = "src/brain_researcher/services/br_kg/requirements.txt"

    try:
        # Read existing requirements
        with open(requirements_file, "r") as f:
            existing_lines = f.read().strip().split("\n")

        # Check which dependencies are already present
        existing_deps = set()
        for line in existing_lines:
            if line.strip() and not line.startswith("#"):
                dep_name = line.split(">=")[0].split("==")[0].split("<")[0].strip()
                existing_deps.add(dep_name.lower())

        # Add missing dependencies
        lines_to_add = []
        for dep in new_deps:
            dep_name = dep.split(">=")[0].strip()
            if dep_name.lower() not in existing_deps:
                lines_to_add.append(dep)
                print(f"✅ Adding: {dep}")
            else:
                print(f"⚠️  Already exists: {dep_name}")

        # Write updated requirements
        if lines_to_add:
            with open(requirements_file, "a") as f:
                f.write("\n\n# Graph Visualization Dependencies\n")
                for dep in lines_to_add:
                    f.write(f"{dep}\n")
            print(
                f"\n✅ Updated {requirements_file} with {len(lines_to_add)} new dependencies"
            )
        else:
            print("\n✅ No new dependencies needed - all already present")

    except FileNotFoundError:
        print(f"❌ Could not find {requirements_file}")
        print("Creating new requirements section...")

        with open(requirements_file, "w") as f:
            f.write("# Graph Visualization Dependencies\n")
            for dep in new_deps:
                f.write(f"{dep}\n")
        print(f"✅ Created {requirements_file}")


if __name__ == "__main__":
    print("🔧 Updating requirements for BR-KG Graph Visualization...")
    update_requirements()
    print("\n📝 Next steps:")
    print("1. Copy the GitHub issues from github_issues_graph_visualization.md")
    print("2. Create them in your GitHub repository")
    print(
        "3. Install the new dependencies: pip install -r src/brain_researcher/services/br_kg/requirements.txt"
    )
    print("4. Start with Issue G1 (Graph API)")
