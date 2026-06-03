"""Custom validation rules for neuroimaging data.

These rules complement JSON Schema validation with domain-specific checks.
"""

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any


def validate_doi(doi: str) -> bool:
    """Validate DOI format.

    Args:
        doi: DOI string

    Returns:
        True if valid DOI format
    """
    if not doi:
        return False

    # Basic DOI pattern: 10.xxxx/yyyy
    pattern = r"^10\.\d{4,}(?:\.\d+)*\/[-._;()\/:a-zA-Z0-9]+$"
    return bool(re.match(pattern, doi))


def validate_pmid(pmid: str) -> bool:
    """Validate PubMed ID format.

    Args:
        pmid: PMID string

    Returns:
        True if valid PMID
    """
    if not pmid:
        return False

    # PMID should be numeric, typically 1-8 digits
    return pmid.isdigit() and 1 <= len(pmid) <= 10


def coord_in_mni(x: float, y: float, z: float) -> bool:
    """Check if coordinates are within MNI space bounds.

    Args:
        x, y, z: Coordinates in mm

    Returns:
        True if within reasonable MNI bounds
    """
    return -100 <= x <= 100 and -140 <= y <= 110 and -80 <= z <= 120


def coord_in_tal(x: float, y: float, z: float) -> bool:
    """Check if coordinates are within Talairach space bounds.

    Args:
        x, y, z: Coordinates in mm

    Returns:
        True if within reasonable Talairach bounds
    """
    return -80 <= x <= 80 and -120 <= y <= 90 and -60 <= z <= 90


def validate_bids_path(path: str) -> bool:
    """Validate BIDS file path format.

    Args:
        path: File path

    Returns:
        True if valid BIDS format
    """
    path_obj = Path(path)
    name = path_obj.name

    # Basic BIDS patterns

    # Must start with sub-
    if not name.startswith("sub-"):
        return False

    # Check for valid suffixes
    valid_suffixes = [
        "_T1w.nii.gz",
        "_T2w.nii.gz",
        "_bold.nii.gz",
        "_dwi.nii.gz",
        "_fmap.nii.gz",
        "_events.tsv",
        ".json",
    ]

    has_valid_suffix = any(name.endswith(suffix) for suffix in valid_suffixes)

    return has_valid_suffix


def validate_bids_required_files(dataset_path: str) -> list[str]:
    """Check for required BIDS files.

    Args:
        dataset_path: Path to BIDS dataset

    Returns:
        List of missing required files
    """
    missing = []
    dataset = Path(dataset_path)

    # Required files
    if not (dataset / "dataset_description.json").exists():
        missing.append("dataset_description.json")

    # README is required (can be .md or plain)
    if not ((dataset / "README").exists() or (dataset / "README.md").exists()):
        missing.append("README")

    return missing


def validate_bids_naming_convention(filename: str) -> bool:
    """Validate BIDS naming conventions.

    Args:
        filename: Name of file to validate

    Returns:
        True if follows BIDS naming convention
    """
    # BIDS entity order
    entity_order = [
        "sub",
        "ses",
        "task",
        "acq",
        "ce",
        "rec",
        "dir",
        "run",
        "mod",
        "echo",
        "flip",
        "inv",
        "mt",
        "part",
        "recording",
    ]

    # Extract entities from filename
    entities = re.findall(r"([a-z]+)-([a-zA-Z0-9]+)", filename)

    if not entities:
        # No entities found - might be a top-level file
        return filename in [
            "README",
            "README.md",
            "CHANGES",
            "LICENSE",
            "dataset_description.json",
            "participants.tsv",
            "participants.json",
        ]

    # Check entity order
    prev_idx = -1
    for entity, _ in entities:
        if entity in entity_order:
            idx = entity_order.index(entity)
            if idx <= prev_idx:
                return False  # Out of order
            prev_idx = idx

    return True


def validate_bids_metadata_consistency(metadata: dict[str, Any]) -> list[str]:
    """Validate BIDS metadata consistency.

    Args:
        metadata: Dataset metadata dictionary

    Returns:
        List of inconsistency messages
    """
    issues = []

    # Check BIDSVersion format
    if "BIDSVersion" in metadata:
        if not re.match(r"^\d+\.\d+\.\d+$", metadata["BIDSVersion"]):
            issues.append(f"Invalid BIDSVersion format: {metadata['BIDSVersion']}")

    # Check DatasetType values
    if "DatasetType" in metadata:
        if metadata["DatasetType"] not in ["raw", "derivative"]:
            issues.append(f"Invalid DatasetType: {metadata['DatasetType']}")

    # Check Authors format
    if "Authors" in metadata:
        if not isinstance(metadata["Authors"], list):
            issues.append("Authors must be a list")
        elif not all(isinstance(a, str) for a in metadata["Authors"]):
            issues.append("All Authors must be strings")

    return issues


def validate_bids_participant_id(participant_id: str) -> bool:
    """Validate BIDS participant ID format.

    Args:
        participant_id: Participant ID to validate

    Returns:
        True if valid format
    """
    return bool(re.match(r"^sub-[a-zA-Z0-9]+$", participant_id))


def validate_bids_task_events(events: list[dict[str, Any]]) -> list[str]:
    """Validate BIDS task events.

    Args:
        events: List of event dictionaries

    Returns:
        List of validation errors
    """
    errors = []

    for i, event in enumerate(events):
        # Check required fields
        if "onset" not in event:
            errors.append(f"Event {i}: missing 'onset' field")
        elif not isinstance(event["onset"], int | float) or event["onset"] < 0:
            errors.append(f"Event {i}: 'onset' must be non-negative number")

        if "duration" not in event:
            errors.append(f"Event {i}: missing 'duration' field")
        elif not isinstance(event["duration"], int | float) or event["duration"] < 0:
            errors.append(f"Event {i}: 'duration' must be non-negative number")

        # Check optional fields
        if "response_time" in event:
            if event["response_time"] is not None:
                if not isinstance(event["response_time"], int | float):
                    errors.append(
                        f"Event {i}: 'response_time' must be a number or null"
                    )

    return errors


def validate_tr(tr: float) -> bool:
    """Validate repetition time (TR) value.

    Args:
        tr: TR in seconds

    Returns:
        True if reasonable TR value
    """
    # Typical TR range: 0.5s to 10s
    return 0.3 <= tr <= 15.0


def validate_smoothing_kernel(fwhm: float) -> bool:
    """Validate smoothing kernel size.

    Args:
        fwhm: Full width at half maximum in mm

    Returns:
        True if reasonable smoothing kernel
    """
    # Typical smoothing: 0-12mm
    return 0 <= fwhm <= 20


def validate_threshold(threshold: float, threshold_type: str = "p") -> bool:
    """Validate statistical threshold.

    Args:
        threshold: Threshold value
        threshold_type: Type of threshold ('p', 'z', 't')

    Returns:
        True if reasonable threshold
    """
    if threshold_type == "p":
        return 0 < threshold <= 1
    elif threshold_type in ["z", "t"]:
        return 0 < threshold <= 10
    else:
        return False


def validate_wikidata_region_id(region_id: str) -> bool:
    """Validate Wikidata region ID format (Q[0-9]+).

    Args:
        region_id: Wikidata region ID string

    Returns:
        True if valid Wikidata region ID format
    """
    if not region_id:
        return False
    # Wikidata IDs follow pattern Q[0-9]+
    return bool(re.match(r"^Q[0-9]+$", region_id))


def validate_wikidata_parent_id(parent_id: str | None) -> bool:
    """Validate Wikidata parent ID format (Q[0-9]*).

    Args:
        parent_id: Wikidata parent ID string (can be None)

    Returns:
        True if valid Wikidata parent ID format or None
    """
    if parent_id is None:
        return True
    # Parent ID can be empty string or Q[0-9]+
    return bool(re.match(r"^Q[0-9]*$", parent_id))


def validate_cognitive_atlas_concept_id(concept_id: str) -> bool:
    """Validate Cognitive Atlas concept ID format.

    Args:
        concept_id: Concept ID string

    Returns:
        True if valid concept ID format
    """
    if not concept_id:
        return False
    # Cognitive Atlas IDs are typically alphanumeric with underscores/hyphens
    return bool(re.match(r"^[a-zA-Z0-9_-]+$", concept_id))


def validate_cognitive_atlas_task_id(task_id: str) -> bool:
    """Validate Cognitive Atlas task ID format.

    Args:
        task_id: Task ID string

    Returns:
        True if valid task ID format
    """
    if not task_id:
        return False
    # Cognitive Atlas task IDs follow similar pattern to concept IDs
    return bool(re.match(r"^[a-zA-Z0-9_-]+$", task_id))


def validate_neurovault_collection_id(collection_id: int) -> bool:
    """Validate NeuroVault collection ID.

    Args:
        collection_id: Collection ID integer

    Returns:
        True if valid collection ID (positive integer)
    """
    return isinstance(collection_id, int) and collection_id > 0


def validate_neurovault_map_id(map_id: int) -> bool:
    """Validate NeuroVault map ID.

    Args:
        map_id: Map ID integer

    Returns:
        True if valid map ID (positive integer)
    """
    return isinstance(map_id, int) and map_id > 0


def validate_openneuro_dataset_id(dataset_id: str) -> bool:
    """Validate OpenNeuro dataset ID format (ds[0-9]+).

    Args:
        dataset_id: Dataset ID string

    Returns:
        True if valid OpenNeuro dataset ID format
    """
    if not dataset_id:
        return False
    # OpenNeuro IDs follow pattern ds[0-9]+
    return bool(re.match(r"^ds[0-9]+$", dataset_id))


# Named validation rule functions for better debugging and error messages
def validate_coordinates_in_space(obj: dict[str, Any]) -> bool:
    """Validate that all coordinates are within MNI or Talairach space bounds.

    Args:
        obj: Object containing coordinates array

    Returns:
        True if all coordinates are valid
    """
    coordinates = obj.get("coordinates", [])
    if not coordinates:
        return True

    for coord in coordinates:
        if not all(k in coord for k in ["x", "y", "z"]):
            continue
        if not (
            coord_in_mni(coord["x"], coord["y"], coord["z"])
            or coord_in_tal(coord["x"], coord["y"], coord["z"])
        ):
            return False
    return True


def validate_publication_doi(obj: dict[str, Any]) -> bool:
    """Validate publication DOI if present.

    Args:
        obj: Publication object

    Returns:
        True if DOI is valid or not present
    """
    if "doi" not in obj or not obj["doi"]:
        return True
    return validate_doi(obj["doi"])


def validate_publication_pmid(obj: dict[str, Any]) -> bool:
    """Validate publication PMID if present.

    Args:
        obj: Publication object

    Returns:
        True if PMID is valid or not present
    """
    if "pmid" not in obj or not obj["pmid"]:
        return True
    return validate_pmid(obj["pmid"])


def validate_publication_year(obj: dict[str, Any]) -> bool:
    """Validate publication year is within reasonable range.

    Args:
        obj: Publication object

    Returns:
        True if year is valid
    """
    year = obj.get("year", 2000)
    return 1900 <= year <= 2100


def validate_bids_path_field(obj: dict[str, Any]) -> bool:
    """Validate BIDS path if present.

    Args:
        obj: BIDS object

    Returns:
        True if path is valid or not present
    """
    if "path" not in obj:
        return True
    return validate_bids_path(obj["path"])


def validate_bids_tr_field(obj: dict[str, Any]) -> bool:
    """Validate BIDS TR if present.

    Args:
        obj: BIDS object

    Returns:
        True if TR is valid or not present
    """
    if "tr" not in obj:
        return True
    return validate_tr(obj["tr"])


def validate_bids_required_files_field(obj: dict[str, Any]) -> bool:
    """Validate BIDS required files if dataset_path is present.

    Args:
        obj: BIDS object

    Returns:
        True if required files exist or dataset_path not present
    """
    if "dataset_path" not in obj:
        return True
    missing = validate_bids_required_files(obj["dataset_path"])
    return len(missing) == 0


def validate_bids_naming_field(obj: dict[str, Any]) -> bool:
    """Validate BIDS naming convention if filename is present.

    Args:
        obj: BIDS object

    Returns:
        True if naming is valid or filename not present
    """
    if "filename" not in obj:
        return True
    return validate_bids_naming_convention(obj["filename"])


def validate_bids_participant_id_field(obj: dict[str, Any]) -> bool:
    """Validate BIDS participant ID if present.

    Args:
        obj: BIDS object

    Returns:
        True if participant ID is valid or not present
    """
    if "participant_id" not in obj:
        return True
    return validate_bids_participant_id(obj["participant_id"])


def validate_bids_metadata_consistency_field(obj: dict[str, Any]) -> bool:
    """Validate BIDS metadata consistency if metadata is present.

    Args:
        obj: BIDS object

    Returns:
        True if metadata is consistent or not present
    """
    if "metadata" not in obj:
        return True
    issues = validate_bids_metadata_consistency(obj.get("metadata", {}))
    return len(issues) == 0


def validate_bids_task_events_field(obj: dict[str, Any]) -> bool:
    """Validate BIDS task events if events are present.

    Args:
        obj: BIDS object

    Returns:
        True if events are valid or not present
    """
    if "events" not in obj:
        return True
    errors = validate_bids_task_events(obj.get("events", []))
    return len(errors) == 0


def validate_statistics_threshold_field(obj: dict[str, Any]) -> bool:
    """Validate statistical threshold if present.

    Args:
        obj: Statistics object

    Returns:
        True if threshold is valid or not present
    """
    if "threshold" not in obj:
        return True
    threshold_type = obj.get("threshold_type", "p")
    return validate_threshold(obj["threshold"], threshold_type)


def validate_statistics_smoothing_field(obj: dict[str, Any]) -> bool:
    """Validate smoothing kernel if present.

    Args:
        obj: Statistics object

    Returns:
        True if smoothing is valid or not present
    """
    if "smoothing" not in obj:
        return True
    return validate_smoothing_kernel(obj["smoothing"])


def validate_wikidata_region_id_field(obj: dict[str, Any]) -> bool:
    """Validate Wikidata region ID if present.

    Args:
        obj: Wikidata object

    Returns:
        True if region ID is valid or not present
    """
    if "region_id" not in obj:
        return True
    return validate_wikidata_region_id(obj["region_id"])


def validate_wikidata_parent_id_field(obj: dict[str, Any]) -> bool:
    """Validate Wikidata parent ID if present.

    Args:
        obj: Wikidata object

    Returns:
        True if parent ID is valid or not present
    """
    if "parent_id" not in obj:
        return True
    return validate_wikidata_parent_id(obj["parent_id"])


def validate_cognitive_atlas_concept_id_field(obj: dict[str, Any]) -> bool:
    """Validate Cognitive Atlas concept ID if present.

    Args:
        obj: Cognitive Atlas object

    Returns:
        True if concept ID is valid or not present
    """
    if "concept_id" not in obj:
        return True
    return validate_cognitive_atlas_concept_id(obj["concept_id"])


def validate_cognitive_atlas_task_id_field(obj: dict[str, Any]) -> bool:
    """Validate Cognitive Atlas task ID if present.

    Args:
        obj: Cognitive Atlas object

    Returns:
        True if task ID is valid or not present
    """
    if "task_id" not in obj:
        return True
    return validate_cognitive_atlas_task_id(obj["task_id"])


def validate_neurovault_collection_id_field(obj: dict[str, Any]) -> bool:
    """Validate NeuroVault collection ID if present.

    Args:
        obj: NeuroVault object

    Returns:
        True if collection ID is valid or not present
    """
    if "collection_id" not in obj:
        return True
    return validate_neurovault_collection_id(obj["collection_id"])


def validate_neurovault_map_id_field(obj: dict[str, Any]) -> bool:
    """Validate NeuroVault map ID if present.

    Args:
        obj: NeuroVault object

    Returns:
        True if map ID is valid or not present
    """
    if "map_id" not in obj:
        return True
    return validate_neurovault_map_id(obj["map_id"])


def validate_openneuro_dataset_id_field(obj: dict[str, Any]) -> bool:
    """Validate OpenNeuro dataset ID if present.

    Args:
        obj: OpenNeuro object

    Returns:
        True if dataset ID is valid or not present
    """
    if "dataset_id" not in obj:
        return True
    return validate_openneuro_dataset_id(obj["dataset_id"])


# Rule collections for different data types
# Using named functions for better debugging and error messages
VALIDATION_RULES: dict[str, list[Callable]] = {
    "coordinates": [
        validate_coordinates_in_space,
    ],
    "publication": [
        validate_publication_doi,
        validate_publication_pmid,
        validate_publication_year,
    ],
    "bids": [
        validate_bids_path_field,
        validate_bids_tr_field,
        validate_bids_required_files_field,
        validate_bids_naming_field,
        validate_bids_participant_id_field,
        validate_bids_metadata_consistency_field,
        validate_bids_task_events_field,
    ],
    "statistics": [
        validate_statistics_threshold_field,
        validate_statistics_smoothing_field,
    ],
    "wikidata": [
        validate_wikidata_region_id_field,
        validate_wikidata_parent_id_field,
    ],
    "cognitive_atlas": [
        validate_cognitive_atlas_concept_id_field,
        validate_cognitive_atlas_task_id_field,
    ],
    "neurovault": [
        validate_neurovault_collection_id_field,
        validate_neurovault_map_id_field,
    ],
    "openneuro": [
        validate_openneuro_dataset_id_field,
    ],
}


def get_rules_for_schema(schema_key: str) -> list[Callable]:
    """Get validation rules for a schema type.

    Args:
        schema_key: Schema key (e.g., "pubmed.article")

    Returns:
        List of validation functions
    """
    rules = []

    # Map schema keys to rule categories
    if "pubmed" in schema_key or "publication" in schema_key:
        rules.extend(VALIDATION_RULES.get("publication", []))

    if any(x in schema_key for x in ["pubmed", "neurosynth", "wikidata"]):
        rules.extend(VALIDATION_RULES.get("coordinates", []))

    if "openneuro" in schema_key or "bids" in schema_key:
        rules.extend(VALIDATION_RULES.get("bids", []))

    if "statmap" in schema_key:
        rules.extend(VALIDATION_RULES.get("statistics", []))

    # Add domain-specific validations
    if "wikidata" in schema_key:
        rules.extend(VALIDATION_RULES.get("wikidata", []))

    if "cognitive_atlas" in schema_key:
        rules.extend(VALIDATION_RULES.get("cognitive_atlas", []))

    if "neurovault" in schema_key:
        rules.extend(VALIDATION_RULES.get("neurovault", []))

    if "openneuro" in schema_key:
        rules.extend(VALIDATION_RULES.get("openneuro", []))

    return rules


class RuleValidator:
    """Apply custom validation rules with detailed error messages."""

    def __init__(self, rules: list[Callable] | None = None):
        """Initialize with custom rules.

        Args:
            rules: List of validation functions
        """
        self.rules = rules or []

    def _get_rule_name(self, rule: Callable) -> str:
        """Get descriptive name for a validation rule.

        Args:
            rule: Validation function

        Returns:
            Descriptive name for the rule
        """
        # Use function name if available
        if hasattr(rule, "__name__"):
            name = rule.__name__
            # Convert snake_case to readable format
            name = name.replace("_", " ").replace("field", "").strip()
            # Capitalize first letter
            if name:
                name = name[0].upper() + name[1:] if len(name) > 1 else name.upper()
            return name
        return "Unknown rule"

    def validate(self, obj: dict[str, Any]) -> list[str]:
        """Validate object against rules.

        Args:
            obj: Object to validate

        Returns:
            List of error messages (empty if valid)
        """
        errors = []

        for _i, rule in enumerate(self.rules):
            rule_name = self._get_rule_name(rule)
            try:
                if not rule(obj):
                    errors.append(f"Validation failed: {rule_name}")
            except KeyError as e:
                errors.append(
                    f"Validation error ({rule_name}): Missing required field '{e}'"
                )
            except TypeError as e:
                errors.append(
                    f"Validation error ({rule_name}): Type mismatch - {str(e)}"
                )
            except Exception as e:
                errors.append(f"Validation error ({rule_name}): {str(e)}")

        return errors
