#!/usr/bin/env python3
"""Parse data/cognitive_atlas/cogat.owl and emit CAO/Concept artifacts."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

OWL = "http://www.w3.org/2002/07/owl#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
DC = "http://purl.org/dc/elements/1.1/"
SKOS = "http://www.w3.org/2004/02/skos/core#"

NAMESPACES = {
    "owl": OWL,
    "rdf": RDF,
    "rdfs": RDFS,
    "dc": DC,
    "skos": SKOS,
}

OWL_PATH = Path("data/cognitive_atlas/cogat.owl")
CONSTRUCTS_OUT = Path("data/cognitive_atlas/cao_constructs.json")
PROCESS_OUT = Path("data/cognitive_atlas/cao_concept_to_process.json")


def node_text(element: ET.Element | None) -> str:
    if element is None or element.text is None:
        return ""
    return element.text.strip()


def coalesce_text(*candidates: str) -> str:
    for value in candidates:
        if value:
            return value
    return ""


def fragment(iri: str | None) -> str:
    if not iri:
        return ""
    if "#" in iri:
        return iri.split("#", 1)[1]
    return iri.rsplit("/", 1)[-1]


def main() -> None:
    if not OWL_PATH.exists():
        raise SystemExit(f"Missing OWL file: {OWL_PATH}")

    print("Parsing", OWL_PATH)
    tree = ET.parse(OWL_PATH)
    root = tree.getroot()

    process_labels: dict[str, str] = {}
    constructs: list[dict] = []
    links: list[dict] = []

    for cls in root.findall("owl:Class", NAMESPACES):
        about = cls.get(f"{{{RDF}}}about")
        if not about:
            continue
        fragment_id = fragment(about)

        label = coalesce_text(
            node_text(cls.find("rdfs:label", NAMESPACES)),
            node_text(cls.find("skos:prefLabel", NAMESPACES)),
            node_text(cls.find("dc:Title", NAMESPACES)),
        )

        # Collect process labels first
        if fragment_id.startswith("ctp_"):
            process_label = label or node_text(cls.find("skos:prefLabel", NAMESPACES))
            if process_label:
                process_labels[fragment_id] = process_label
            continue

        identifier_el = cls.find("dc:identifier", NAMESPACES)
        identifier = node_text(identifier_el) or fragment_id
        if not identifier:
            continue

        if not identifier.lower().startswith(("cao_", "trm_")):
            continue

        definition = coalesce_text(
            node_text(cls.find("skos:definition", NAMESPACES)),
            node_text(cls.find("rdfs:comment", NAMESPACES)),
            node_text(cls.find("dc:description", NAMESPACES)),
        )

        synonyms = set()
        for synonym_tag in ("skos:prefLabel", "skos:altLabel", "dc:Title", "rdfs:label"):
            for syn in cls.findall(synonym_tag, NAMESPACES):
                value = node_text(syn)
                if value:
                    synonyms.add(value)
        if label:
            synonyms.discard(label)

        constructs.append(
            {
                "id": identifier.upper(),
                "label": label or identifier,
                "definition": definition,
                "synonyms": sorted(synonyms),
            }
        )

        for top in cls.findall("skos:hasTopConcept", NAMESPACES):
            process_iri = top.get(f"{{{RDF}}}resource")
            pid = fragment(process_iri)
            if not pid:
                continue
            links.append(
                {
                    "concept_id": identifier.upper(),
                    "process_id": pid,
                }
            )

    constructs.sort(key=lambda row: row["id"])
    for row in links:
        pid = row["process_id"]
        row["process_name"] = process_labels.get(pid, pid)

    PROCESS_OUT.parent.mkdir(parents=True, exist_ok=True)
    CONSTRUCTS_OUT.write_text(json.dumps(constructs, indent=2, ensure_ascii=False))
    PROCESS_OUT.write_text(json.dumps(links, indent=2, ensure_ascii=False))
    print(f"Wrote {len(constructs)} constructs to {CONSTRUCTS_OUT}")
    print(f"Wrote {len(links)} concept→process rows to {PROCESS_OUT}")


if __name__ == "__main__":
    main()
