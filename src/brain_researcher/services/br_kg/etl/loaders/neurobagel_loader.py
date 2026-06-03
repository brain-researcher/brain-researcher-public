#!/usr/bin/env python3
"""Neurobagel Phenotype Loader

Fetches subject and phenotype data from the Neurobagel example dataset.
If the remote dataset is not available, falls back to a tiny local sample.
"""

import logging
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

# URL of a small publicly available Neurobagel sample
NEUROBAGEL_TSV_URL = (
    "https://raw.githubusercontent.com/neurobagel/neurobagel_examples/main/"
    "data-upload/example_synthetic.tsv"
)

_DEMOGRAPHIC_FIELDS = {
    "pheno_age": "age",
    "pheno_sex": "sex",
    "pheno_group": "group",
    "site": "site",
    "cohort": "cohort",
}


def _coerce_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _classify_phenotype_field(field_name: str) -> str:
    normalized = field_name.strip().lower()
    if normalized in {"pheno_age", "age"}:
        return "demographic_age"
    if normalized in {"pheno_sex", "sex", "gender"}:
        return "demographic_sex"
    if normalized in {"pheno_group", "group"}:
        return "cohort_group"
    if normalized in {"site", "cohort", "session_id"}:
        return "cohort_context"
    return "phenotype_measure"


def _extract_subject_audit_metadata(row: dict[str, Any]) -> dict[str, Any] | None:
    assignments: dict[str, Any] = {}
    for raw_key, normalized_key in _DEMOGRAPHIC_FIELDS.items():
        value = _coerce_text(row.get(raw_key))
        if value is not None:
            assignments[normalized_key] = value

    session_id = _coerce_text(row.get("session_id"))
    if session_id is not None:
        assignments.setdefault("session_id", session_id)

    if not assignments:
        return None

    resolved_group_keys = sorted(assignments.keys())
    return {
        "schema_version": "neurobagel-subject-audit-v1",
        "resolved_group_keys": resolved_group_keys,
        "missing_group_keys": sorted(
            normalized_key
            for normalized_key in _DEMOGRAPHIC_FIELDS.values()
            if normalized_key not in assignments
        ),
        "group_assignments": assignments,
    }


def fetch_neurobagel_data(output_dir: str, use_cache: bool = True) -> str:
    """Fetch phenotype/subject data from Neurobagel.

    Parameters
    ----------
    output_dir : str
        Directory to save the downloaded file.
    use_cache : bool
        Whether to use an existing cached file if present.

    Returns
    -------
    str
        Path to the TSV file containing phenotype data.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    cache_file = output_path / "neurobagel_phenotypes.tsv"

    if use_cache and cache_file.exists():
        logger.info(f"Using cached Neurobagel data: {cache_file}")
        return str(cache_file)

    try:
        logger.info("Downloading Neurobagel phenotype sample ...")
        resp = requests.get(NEUROBAGEL_TSV_URL, timeout=30)
        resp.raise_for_status()
        cache_file.write_bytes(resp.content)
        logger.info(f"Saved Neurobagel data to {cache_file}")
        return str(cache_file)
    except Exception as exc:
        logger.error(f"Failed to download Neurobagel data: {exc}")
        logger.info("Falling back to embedded sample data")
        sample = (
            "participant_id\tsession_id\tpheno_age\tpheno_sex\tpheno_group\n"
            "sub-01\tses-01\t34\tF\tCTRL\n"
            "sub-02\tses-01\t40\tM\tPAT\n"
        )
        cache_file.write_text(sample)
        return str(cache_file)


def load_neurobagel_data(db, tsv_file: str) -> dict:
    """Load subjects and phenotypes from a TSV file into the database.

    Parameters
    ----------
    db : BRKGGraphDB
        Database instance to populate.
    tsv_file : str
        Path to TSV file containing phenotype records.

    Returns
    -------
    dict
        Summary of loaded data with counts and any errors.
    """
    # Initialize counters
    stats = {
        "subjects_created": 0,
        "subjects_skipped": 0,
        "phenotypes_created": 0,
        "phenotypes_skipped": 0,
        "relationships_created": 0,
        "cohort_metadata": {
            "schema_version": "br-cohort-metadata-v1",
            "participant_id_scope": "subject_global",
            "group_audit": {
                "resolved_group_keys": [],
                "missing_group_keys": [],
                "group_counts": {},
            },
        },
        "errors": [],
    }

    # Read and validate TSV file
    try:
        # Use basic file reading to avoid pandas issues
        with open(tsv_file) as f:
            lines = f.readlines()

        if not lines:
            raise ValueError("Empty TSV file")

        # Parse header
        headers = lines[0].strip().split("\t")

        # Parse data rows
        data_rows = []
        for line in lines[1:]:
            if line.strip():
                # Don't strip before splitting to preserve leading tabs
                values = line.rstrip("\n").split("\t")
                # Pad with empty strings if not enough values
                while len(values) < len(headers):
                    values.append("")
                row_dict = dict(zip(headers, values, strict=False))
                data_rows.append(row_dict)

    except Exception as e:
        error_msg = f"Failed to read TSV file: {e}"
        logger.error(error_msg)
        stats["errors"].append(error_msg)
        return stats

    # Validate required columns
    required_columns = ["participant_id"]
    missing_columns = [col for col in required_columns if col not in headers]
    if missing_columns:
        error_msg = f"Missing required columns: {missing_columns}"
        logger.error(error_msg)
        stats["errors"].append(error_msg)
        return stats

    # Process each row
    for row in data_rows:
        participant_id = str(row.get("participant_id", "")).strip()
        if not participant_id or participant_id == "nan" or participant_id == "":
            logger.warning(f"Skipping row with empty participant_id: {row}")
            continue

        # Create Subject node
        subject_audit = _extract_subject_audit_metadata(row)
        subject_props = {
            "subject_id": participant_id,
            "session_id": str(row.get("session_id", "default")),
            "source": "neurobagel",
        }
        if subject_audit:
            subject_props["fairness_audit"] = subject_audit
            subject_props["cohort_assignments"] = dict(
                subject_audit.get("group_assignments", {})
            )
            if subject_audit.get("group_assignments", {}).get("cohort") is not None:
                subject_props["site_or_cohort"] = subject_audit["group_assignments"]["cohort"]
                subject_props["group"] = subject_audit["group_assignments"]["cohort"]
            group_audit = stats["cohort_metadata"]["group_audit"]
            for key in subject_audit.get("resolved_group_keys", []):
                if key not in group_audit["resolved_group_keys"]:
                    group_audit["resolved_group_keys"].append(key)
            for key in subject_audit.get("missing_group_keys", []):
                if key not in group_audit["missing_group_keys"]:
                    group_audit["missing_group_keys"].append(key)
            for key, value in subject_audit.get("group_assignments", {}).items():
                bucket = group_audit["group_counts"].setdefault(
                    key,
                    {"participant_counts": {}, "row_counts": {}, "n_levels": 0},
                )
                bucket["participant_counts"][value] = (
                    int(bucket["participant_counts"].get(value, 0)) + 1
                )
                bucket["row_counts"][value] = int(bucket["row_counts"].get(value, 0)) + 1
                bucket["n_levels"] = len(bucket["participant_counts"])

        subject_node_id = None
        try:
            subject_node_id = db.create_node("Subject", subject_props)
            stats["subjects_created"] += 1
            logger.info(f"Created Subject node: {participant_id}")
        except ValueError as e:
            if "Constraint violation" in str(e):
                # Subject already exists, try to find it
                existing_subjects = db.find_nodes(
                    "Subject", {"subject_id": participant_id}
                )
                if existing_subjects:
                    subject_node_id = existing_subjects[0][0]
                    stats["subjects_skipped"] += 1
                    logger.debug(f"Subject already exists: {participant_id}")
                else:
                    logger.warning(f"Could not find existing subject: {participant_id}")
                    continue
            else:
                logger.error(f"Failed to create Subject node: {e}")
                stats["errors"].append(f"Subject {participant_id}: {str(e)}")
                continue
        except Exception as e:
            logger.error(f"Unexpected error creating Subject node: {e}")
            stats["errors"].append(f"Subject {participant_id}: {str(e)}")
            continue

        # Create Phenotype nodes and relationships
        for col in headers:
            if col in {"participant_id", "session_id"}:
                continue

            value = row.get(col, "")
            if not value or str(value).strip() == "":
                continue

            record_id = f"{participant_id}-{col}"
            pheno_props = {
                "record_id": record_id,
                "subject_id": participant_id,
                "name": col,
                "value": str(value),
                "phenotype_category": _classify_phenotype_field(col),
                "source": "neurobagel",
            }

            try:
                phenotype_node_id = db.create_node("Phenotype", pheno_props)
                stats["phenotypes_created"] += 1
                logger.debug(f"Created Phenotype node: {record_id}")

                # Create relationship between Subject and Phenotype
                if subject_node_id and phenotype_node_id:
                    rel_created = db.create_relationship(
                        subject_node_id,
                        phenotype_node_id,
                        "HAS_PHENOTYPE",
                        {"created_from": "neurobagel_loader"},
                    )
                    if rel_created:
                        stats["relationships_created"] += 1
                        logger.debug(
                            f"Created relationship: {participant_id} -> {record_id}"
                        )

            except ValueError as e:
                if "Constraint violation" in str(e):
                    stats["phenotypes_skipped"] += 1
                    logger.debug(f"Phenotype already exists: {record_id}")
                else:
                    logger.error(f"Failed to create Phenotype node: {e}")
                    stats["errors"].append(f"Phenotype {record_id}: {str(e)}")
            except Exception as e:
                logger.error(f"Unexpected error creating Phenotype node: {e}")
                stats["errors"].append(f"Phenotype {record_id}: {str(e)}")

    # Log summary
    logger.info(
        f"Neurobagel data loading completed: {stats['subjects_created']} subjects, "
        f"{stats['phenotypes_created']} phenotypes, {stats['relationships_created']} relationships created"
    )
    if stats["errors"]:
        logger.warning(f"Encountered {len(stats['errors'])} errors during loading")

    return stats
