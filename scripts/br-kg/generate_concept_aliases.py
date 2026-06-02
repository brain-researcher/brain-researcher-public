#!/usr/bin/env python3
"""Generate concept aliases from annotation files."""

import csv
import json
from collections import defaultdict
from pathlib import Path

ANNOT_DIR = Path("../../llm_cogitive_function/data/processed_with_direction")
OUTPUT_FILE = Path("../data/concept_aliases.tsv")


def load_annotations() -> list[dict]:
    """Load all annotation files."""
    annotations = []

    for annot_file in ANNOT_DIR.glob("*.json"):
        try:
            with open(annot_file) as f:
                data = json.load(f)
                # Handle both formats: list directly or dict with "annotations" key
                if isinstance(data, list):
                    annotations.extend(data)
                elif isinstance(data, dict) and "annotations" in data:
                    annotations.extend(data["annotations"])
                else:
                    print(f"Unknown format in {annot_file}")
        except Exception as e:
            print(f"Error loading {annot_file}: {e}")

    return annotations


def extract_concepts(annotations: list[dict]) -> dict[str, set[str]]:
    """Extract concepts and their IDs from annotations."""
    concept_map = defaultdict(set)

    for annot in annotations:
        constructs = annot.get("constructs", [])

        for construct in constructs:
            concept_name = construct.get("name", "").strip()
            concept_id = construct.get("id", "").strip()

            if concept_name and concept_id:
                # Normalize concept name
                normalized_name = concept_name.lower()
                concept_map[normalized_name].add(concept_id)

    return dict(concept_map)


def generate_aliases(concept_map: dict[str, set[str]]) -> list[tuple[str, str]]:
    """Generate concept aliases from the concept map."""
    aliases = []

    # Create aliases for each unique concept
    for concept_name, concept_ids in concept_map.items():
        # Use the first ID as the canonical ID
        canonical_id = sorted(concept_ids)[0]

        # Add the main concept name
        aliases.append((concept_name, canonical_id))

        # Add common variations
        # Remove common suffixes
        base_name = concept_name
        for suffix in [" task", " process", " function", " ability"]:
            if base_name.endswith(suffix):
                base_name = base_name[: -len(suffix)].strip()
                if base_name and base_name != concept_name:
                    aliases.append((base_name, canonical_id))

        # Add acronym variations
        if " " in concept_name:
            # Create acronym
            acronym = "".join(word[0] for word in concept_name.split() if word)
            if len(acronym) > 1:
                aliases.append((acronym, canonical_id))

        # Add hyphenated versions
        if " " in concept_name:
            hyphenated = concept_name.replace(" ", "-")
            aliases.append((hyphenated, canonical_id))

        # Add underscored versions
        if " " in concept_name:
            underscored = concept_name.replace(" ", "_")
            aliases.append((underscored, canonical_id))

    # Remove duplicates while preserving order
    seen = set()
    unique_aliases = []
    for alias in aliases:
        if alias not in seen:
            seen.add(alias)
            unique_aliases.append(alias)

    return unique_aliases


def write_aliases(aliases: list[tuple[str, str]], output_file: Path):
    """Write aliases to TSV file."""
    with open(output_file, "w", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["alias", "concept_id"])

        for alias, concept_id in sorted(aliases):
            writer.writerow([alias, concept_id])


def main():
    """Main function."""
    print("Loading annotations...")
    annotations = load_annotations()
    print(f"Loaded {len(annotations)} annotations")

    print("Extracting concepts...")
    concept_map = extract_concepts(annotations)
    print(f"Found {len(concept_map)} unique concepts")

    print("Generating aliases...")
    aliases = generate_aliases(concept_map)
    print(f"Generated {len(aliases)} aliases")

    print(f"Writing to {OUTPUT_FILE}...")
    write_aliases(aliases, OUTPUT_FILE)
    print("Done!")

    # Print some statistics
    print("\nTop 10 concepts by frequency:")
    concept_counts = defaultdict(int)
    for annot in annotations:
        for construct in annot.get("constructs", []):
            name = construct.get("name", "").strip().lower()
            if name:
                concept_counts[name] += 1

    for concept, count in sorted(
        concept_counts.items(), key=lambda x: x[1], reverse=True
    )[:10]:
        print(f"  {concept}: {count}")


if __name__ == "__main__":
    main()
