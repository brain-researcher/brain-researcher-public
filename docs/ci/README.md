CI validation sequence for the catalog and resource schemas:

- Step 1: `python scripts/ci/generate_resources_schema.py`
- Step 2: `python scripts/ci/validate_capabilities.py`
- Step 3: `python -m jsonschema -i configs/tools_catalog.json configs/schemas/tools_catalog.schema.json`

Notes:
- Steps 1–3 run in the lint job of `.github/workflows/ci.yml`; keep this order so capabilities validation always uses the freshly generated resources schema.
- Update this list if additional schema checks are added so local runs mirror CI.
