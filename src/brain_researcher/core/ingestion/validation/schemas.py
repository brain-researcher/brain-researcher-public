"""JSON Schema definitions for data validation.

Uses fastjsonschema for high-performance validation.
Schemas are pre-compiled for speed.
"""

from typing import Any, Callable, Dict

try:
    import fastjsonschema

    HAS_FASTJSONSCHEMA = True
except ImportError:
    import json

    from jsonschema import ValidationError as JSONSchemaError
    from jsonschema import validate

    HAS_FASTJSONSCHEMA = False
    print("Warning: fastjsonschema not available, using jsonschema (slower)")


# Schema definitions
_SCHEMA_DEFINITIONS = {
    "cognitive_atlas.concept": {
        "type": "object",
        "properties": {
            "concept_id": {"type": "string", "minLength": 1},
            "name": {"type": "string", "minLength": 1},
            "definition": {"type": "string"},
            "category": {
                "type": "string",
                "enum": ["process", "task", "condition", "contrast"],
            },
            "parent_id": {"type": ["string", "null"]},
            "aliases": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["concept_id", "name", "category"],
        "additionalProperties": True,
    },
    "cognitive_atlas.task": {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "minLength": 1},
            "name": {"type": "string", "minLength": 1},
            "description": {"type": "string"},
            "concepts": {"type": "array", "items": {"type": "string"}},
            "conditions": {"type": "array", "items": {"type": "string"}},
            "contrasts": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["task_id", "name"],
        "additionalProperties": True,
    },
    "pubmed.article": {
        "type": "object",
        "properties": {
            "pmid": {"type": "string", "pattern": "^[0-9]+$"},
            "doi": {"type": ["string", "null"]},
            "title": {"type": "string", "minLength": 1},
            "abstract": {"type": "string"},
            "authors": {"type": "array", "items": {"type": "string"}},
            "year": {"type": "integer", "minimum": 1900, "maximum": 2100},
            "journal": {"type": "string"},
            "keywords": {"type": "array", "items": {"type": "string"}},
            "coordinates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                        "z": {"type": "number"},
                        "space": {
                            "type": "string",
                            "enum": ["MNI", "TAL", "MNI152", "UNKNOWN"],
                        },
                    },
                    "required": ["x", "y", "z"],
                },
            },
        },
        "required": ["pmid", "title"],
        "additionalProperties": True,
    },
    "neurosynth.study": {
        "type": "object",
        "properties": {
            "study_id": {"type": "string", "minLength": 1},
            "pmid": {"type": ["string", "null"], "pattern": "^[0-9]*$"},
            "doi": {"type": ["string", "null"]},
            "title": {"type": "string"},
            "space": {"type": "string", "enum": ["MNI", "TAL", "MNI152", "UNKNOWN"]},
            "coordinates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                        "z": {"type": "number"},
                    },
                    "required": ["x", "y", "z"],
                },
            },
            "topics": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["study_id"],
        "additionalProperties": True,
    },
    "neurovault.collection": {
        "type": "object",
        "properties": {
            "collection_id": {"type": "integer"},
            "name": {"type": "string", "minLength": 1},
            "description": {"type": "string"},
            "doi": {"type": ["string", "null"]},
            "owner": {"type": "string"},
            "number_of_images": {"type": "integer", "minimum": 0},
        },
        "required": ["collection_id", "name"],
        "additionalProperties": True,
    },
    "neurovault.statmap": {
        "type": "object",
        "properties": {
            "map_id": {"type": "integer"},
            "collection_id": {"type": "integer"},
            "name": {"type": "string"},
            "map_type": {"type": "string"},
            "cognitive_paradigm": {"type": ["string", "null"]},
            "cognitive_contrast": {"type": ["string", "null"]},
            "file_url": {"type": "string", "format": "uri"},
        },
        "required": ["map_id", "collection_id"],
        "additionalProperties": True,
    },
    "wikidata.brain_region": {
        "type": "object",
        "properties": {
            "region_id": {"type": "string", "pattern": "^Q[0-9]+$"},
            "name": {"type": "string", "minLength": 1},
            "description": {"type": "string"},
            "aliases": {"type": "array", "items": {"type": "string"}},
            "parent_id": {"type": ["string", "null"], "pattern": "^Q[0-9]*$"},
            "coordinates": {
                "type": ["object", "null"],
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "z": {"type": "number"},
                },
            },
            "atlas": {"type": "string"},
        },
        "required": ["region_id", "name"],
        "additionalProperties": True,
    },
    "openneuro.dataset": {
        "type": "object",
        "properties": {
            "dataset_id": {"type": "string", "pattern": "^ds[0-9]+$"},
            "name": {"type": "string"},
            "description": {"type": "string"},
            "doi": {"type": ["string", "null"]},
            "authors": {"type": "array", "items": {"type": "string"}},
            "n_subjects": {"type": "integer", "minimum": 1},
            "tasks": {"type": "array", "items": {"type": "string"}},
            "modalities": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["dataset_id"],
        "additionalProperties": True,
    },
    "bids.dataset_description": {
        "type": "object",
        "properties": {
            "Name": {"type": "string", "minLength": 1},
            "BIDSVersion": {"type": "string", "pattern": "^[0-9]+\\.[0-9]+\\.[0-9]+$"},
            "DatasetType": {"type": "string", "enum": ["raw", "derivative"]},
            "License": {"type": "string"},
            "Authors": {"type": "array", "items": {"type": "string"}},
            "Acknowledgements": {"type": "string"},
            "HowToAcknowledge": {"type": "string"},
            "Funding": {"type": "array", "items": {"type": "string"}},
            "ReferencesAndLinks": {"type": "array", "items": {"type": "string"}},
            "DatasetDOI": {"type": "string"},
            "GeneratedBy": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "Name": {"type": "string"},
                        "Version": {"type": "string"},
                        "Description": {"type": "string"},
                        "CodeURL": {"type": "string"},
                        "Container": {"type": "object"},
                    },
                },
            },
            "SourceDatasets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "DOI": {"type": "string"},
                        "URL": {"type": "string"},
                        "Version": {"type": "string"},
                    },
                },
            },
        },
        "required": ["Name", "BIDSVersion"],
        "additionalProperties": True,
    },
    "bids.participant": {
        "type": "object",
        "properties": {
            "participant_id": {"type": "string", "pattern": "^sub-[a-zA-Z0-9]+$"},
            "age": {"type": ["number", "string", "null"]},
            "sex": {
                "type": ["string", "null"],
                "enum": ["M", "F", "O", "m", "f", "o", None],
            },
            "handedness": {
                "type": ["string", "null"],
                "enum": ["L", "R", "A", "l", "r", "a", None],
            },
            "group": {"type": ["string", "null"]},
            "species": {"type": "string", "default": "homo sapiens"},
            "strain": {"type": ["string", "null"]},
            "strain_rrid": {"type": ["string", "null"]},
        },
        "required": ["participant_id"],
        "additionalProperties": True,
    },
    "bids.task_events": {
        "type": "object",
        "properties": {
            "onset": {"type": "number", "minimum": 0},
            "duration": {"type": "number", "minimum": 0},
            "trial_type": {"type": ["string", "null"]},
            "response_time": {"type": ["number", "null"]},
            "stim_file": {"type": ["string", "null"]},
            "value": {"type": ["number", "string", "null"]},
            "HED": {"type": ["string", "null"]},
        },
        "required": ["onset", "duration"],
        "additionalProperties": True,
    },
    "bids.validation_result": {
        "type": "object",
        "properties": {
            "dataset_path": {"type": "string"},
            "is_valid": {"type": "boolean"},
            "validation_time": {"type": "string", "format": "date-time"},
            "bids_version": {"type": "string"},
            "errors": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "file": {"type": ["string", "null"]},
                        "severity": {
                            "type": "string",
                            "enum": ["error", "warning", "info"],
                        },
                    },
                },
            },
            "warnings": {"type": "array", "items": {"type": "object"}},
            "quality_metrics": {
                "type": "object",
                "properties": {
                    "overall_quality_score": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 100,
                    },
                    "completeness_score": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 100,
                    },
                    "required_files_score": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 100,
                    },
                },
            },
            "metadata": {
                "type": "object",
                "properties": {
                    "n_subjects": {"type": "integer", "minimum": 0},
                    "n_sessions": {"type": "integer", "minimum": 0},
                    "tasks": {"type": "array", "items": {"type": "string"}},
                    "modalities": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "required": ["dataset_path", "is_valid", "validation_time"],
        "additionalProperties": True,
    },
}


# Compile schemas for performance
COMPILED_SCHEMAS: Dict[str, Callable[[dict], None]] = {}

if HAS_FASTJSONSCHEMA:
    for key, schema in _SCHEMA_DEFINITIONS.items():
        try:
            COMPILED_SCHEMAS[key] = fastjsonschema.compile(schema)
        except Exception as e:
            print(f"Warning: Failed to compile schema {key}: {e}")
            # Fallback to uncompiled
            COMPILED_SCHEMAS[key] = lambda obj, s=schema: fastjsonschema.validate(
                s, obj
            )
else:
    # Fallback to jsonschema
    def make_validator(schema):
        def validator(obj):
            try:
                validate(obj, schema)
            except JSONSchemaError as e:
                raise ValueError(str(e))

        return validator

    for key, schema in _SCHEMA_DEFINITIONS.items():
        COMPILED_SCHEMAS[key] = make_validator(schema)


def get_schema(key: str) -> Dict[str, Any]:
    """Get raw schema definition by key.

    Args:
        key: Schema key (e.g., "pubmed.article")

    Returns:
        Schema dictionary

    Raises:
        KeyError: If schema not found
    """
    return _SCHEMA_DEFINITIONS[key]


def list_schemas() -> list[str]:
    """List all available schema keys."""
    return list(_SCHEMA_DEFINITIONS.keys())
