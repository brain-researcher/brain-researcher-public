#!/usr/bin/env python3
"""Parse ONVOC (OpenNeuro Vocabulary) OWL export into JSON artifacts."""

from __future__ import annotations

import csv
import json
import xml.etree.ElementTree as ET
from pathlib import Path


RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
OWL = "http://www.w3.org/2002/07/owl#"
SKOS = "http://www.w3.org/2004/02/skos/core#"
DCT = "http://purl.org/dc/terms/"


NAMESPACES = {
    "rdf": RDF,
    "rdfs": RDFS,
    "owl": OWL,
    "skos": SKOS,
    "dct": DCT,
}


DEFAULT_OWL_PATH = Path("data/ontologies/onvoc/onvoc.owl")
DEFAULT_CSV_PATH = Path("data/ontologies/onvoc/ONVOC.csv")
CONCEPTS_OUT = Path("data/ontologies/onvoc/onvoc_concepts.json")
RELATIONSHIPS_OUT = Path("data/ontologies/onvoc/onvoc_relationships.json")


def fragment(uri: str | None) -> str:
    if not uri:
        return ""
    if "#" in uri:
        return uri.rsplit("#", 1)[-1]
    return uri.rstrip("/").rsplit("/", 1)[-1]


def node_text(element: ET.Element | None) -> str:
    if element is None or element.text is None:
        return ""
    return element.text.strip()


def coalesce_text(*values: str) -> str:
    for value in values:
        if value:
            return value
    return ""


def parse_onvoc(owl_path: Path = DEFAULT_OWL_PATH) -> tuple[list[dict], list[dict]]:
    if owl_path.exists():
        return _parse_onvoc_owl(owl_path)

    csv_path = DEFAULT_CSV_PATH
    if csv_path.exists():
        return _parse_onvoc_csv(csv_path)

    raise FileNotFoundError(
        f"Neither {owl_path} nor {csv_path} was found. Provide an ONVOC export (OWL or CSV)."
    )


def _parse_onvoc_owl(owl_path: Path) -> tuple[list[dict], list[dict]]:
    tree = ET.parse(owl_path)
    root = tree.getroot()

    concepts: list[dict] = []
    relationships: list[dict] = []

    for cls in root.findall("owl:Class", NAMESPACES):
        about = cls.get(f"{{{RDF}}}about")
        identifier = fragment(about)
        if not identifier:
            continue

        label = coalesce_text(
            node_text(cls.find("skos:prefLabel", NAMESPACES)),
            node_text(cls.find("rdfs:label", NAMESPACES)),
        )
        definition = coalesce_text(
            node_text(cls.find("skos:definition", NAMESPACES)),
            node_text(cls.find("dct:description", NAMESPACES)),
            node_text(cls.find("rdfs:comment", NAMESPACES)),
        )

        synonyms: set[str] = set()
        for tag in ("skos:altLabel", "skos:hiddenLabel"):
            for syn in cls.findall(tag, NAMESPACES):
                text = node_text(syn)
                if text and text != label:
                    synonyms.add(text)

        top_concepts = [
            fragment(ref.get(f"{{{RDF}}}resource"))
            for ref in cls.findall("skos:topConceptOf", NAMESPACES)
        ]
        broader_refs = [
            fragment(ref.get(f"{{{RDF}}}resource"))
            for ref in cls.findall("skos:broader", NAMESPACES)
        ]

        concept_payload = {
            "id": identifier,
            "uri": about,
            "label": label or identifier,
            "definition": definition,
            "synonyms": sorted(synonyms),
            "top_of": [ref for ref in top_concepts if ref],
            "is_top_concept": bool(top_concepts),
            "scheme": "ONVOC",
        }
        concepts.append(concept_payload)

        for parent in broader_refs:
            if parent:
                relationships.append(
                    {
                        "child_id": identifier,
                        "parent_id": parent,
                        "relation": "skos:broader",
                        "edge_type": "CLASSIFIED_UNDER",
                    }
                )

    for cls in root.findall("owl:Class", NAMESPACES):
        child_id = fragment(cls.get(f"{{{RDF}}}about"))
        if not child_id:
            continue
        for narrower in cls.findall("skos:narrower", NAMESPACES):
            target = fragment(narrower.get(f"{{{RDF}}}resource"))
            if target:
                relationships.append(
                    {
                        "child_id": target,
                        "parent_id": child_id,
                        "relation": "skos:narrower",
                        "edge_type": "CLASSIFIED_UNDER",
                    }
                )

    return _dedupe_relationships(concepts, relationships)


def _parse_onvoc_csv(csv_path: Path) -> tuple[list[dict], list[dict]]:
    concepts: list[dict] = []
    relationships: list[dict] = []

    with csv_path.open("r", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            uri = row.get("Class ID") or ""
            identifier = fragment(uri)
            if not identifier:
                continue

            label = coalesce_text(
                (row.get("Preferred Label") or "").strip(),
                identifier,
            )
            definition = (row.get("Definitions") or "").strip()
            synonyms = _split_multi(row.get("Synonyms") or "")
            top_concept_targets = _split_multi(
                row.get("http://www.w3.org/2004/02/skos/core#topConceptOf") or ""
            )
            has_top_concept = bool(top_concept_targets)

            concept_payload = {
                "id": identifier,
                "uri": uri or None,
                "label": label or identifier,
                "definition": definition,
                "synonyms": sorted({syn for syn in synonyms if syn and syn != label}),
                "top_of": [fragment(value) for value in top_concept_targets if value],
                "is_top_concept": has_top_concept,
                "scheme": "ONVOC",
            }
            concepts.append(concept_payload)

            broader_values = _split_multi(
                row.get("http://www.w3.org/2004/02/skos/core#broader") or ""
            )
            for parent_uri in broader_values:
                parent_id = fragment(parent_uri)
                if parent_id:
                    relationships.append(
                        {
                            "child_id": identifier,
                            "parent_id": parent_id,
                            "relation": "skos:broader",
                            "edge_type": "CLASSIFIED_UNDER",
                        }
                    )

            narrower_values = _split_multi(
                row.get("http://www.w3.org/2004/02/skos/core#narrower") or ""
            )
            for child_uri in narrower_values:
                child_id = fragment(child_uri)
                if child_id:
                    relationships.append(
                        {
                            "child_id": child_id,
                            "parent_id": identifier,
                            "relation": "skos:narrower",
                            "edge_type": "CLASSIFIED_UNDER",
                        }
                    )

    return _dedupe_relationships(concepts, relationships)


def _split_multi(value: str) -> list[str]:
    if not value:
        return []
    separators = ["|", ";"]
    for sep in separators:
        if sep in value:
            parts = [item.strip() for item in value.split(sep)]
            return [part for part in parts if part]
    return [value.strip()] if value.strip() else []


def _dedupe_relationships(
    concepts: list[dict],
    relationships: list[dict],
) -> tuple[list[dict], list[dict]]:
    unique_edges: dict[tuple[str, str], dict] = {}
    for rel in relationships:
        key = (rel["child_id"], rel["parent_id"])
        if key not in unique_edges:
            unique_edges[key] = rel
    return concepts, list(unique_edges.values())


def main() -> None:
    concepts, relationships = parse_onvoc()

    CONCEPTS_OUT.parent.mkdir(parents=True, exist_ok=True)
    RELATIONSHIPS_OUT.parent.mkdir(parents=True, exist_ok=True)

    CONCEPTS_OUT.write_text(json.dumps(concepts, indent=2, ensure_ascii=False))
    RELATIONSHIPS_OUT.write_text(json.dumps(relationships, indent=2, ensure_ascii=False))

    print(f"Wrote {len(concepts)} concepts to {CONCEPTS_OUT}")
    print(f"Wrote {len(relationships)} relationships to {RELATIONSHIPS_OUT}")


if __name__ == "__main__":
    main()
