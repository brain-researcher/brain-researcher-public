# OpenNeuro Vocabulary (ONVOC)

* **Source:** [NCBO BioPortal – ONVOC](https://bioportal.bioontology.org/ontologies/ONVOC)
* **Latest tested release:** 1.0.0 (17 Oct 2025)
* **Download:** Place the OWL export as `data/ontologies/onvoc/onvoc.owl`

## Regenerating Artifacts

```bash
python scripts/tools/once/parse_onvoc_owl.py
```

This writes:

* `data/ontologies/onvoc/onvoc_concepts.json`
* `data/ontologies/onvoc/onvoc_relationships.json`

## Loader Integration

`OnvocUnifiedLoader` reads the JSON artifacts and the master ingestion pipeline can be run with:

```bash
python launch_ingestion.py --sources onvoc
```

Nodes are created with `source: "onvoc"` and hierarchical edges are emitted as `CLASSIFIED_UNDER` with `scheme: "ONVOC"`.
