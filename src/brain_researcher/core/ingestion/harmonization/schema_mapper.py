"""Schema mapping for cross-dataset harmonization."""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
from fuzzywuzzy import fuzz, process

logger = logging.getLogger(__name__)


@dataclass
class FieldMapping:
    """Represents a field mapping between datasets."""

    source_field: str
    target_field: str
    transform_func: Optional[callable] = None
    confidence: float = 1.0
    mapping_type: str = "direct"  # direct, derived, computed


class SchemaMapper:
    """Maps schemas between different neuroimaging datasets."""

    def __init__(self, mapping_config: Optional[str] = None):
        """Initialize schema mapper.

        Args:
            mapping_config: Path to mapping configuration file
        """
        self.mappings = {}
        self.standard_schemas = self._load_standard_schemas()
        self.custom_mappings = {}
        self._dataset_schemas: Dict[str, Dict[str, Any]] = {}

        if mapping_config:
            self._load_mapping_config(mapping_config)

        # Common field mappings across neuroimaging datasets
        self.common_mappings = {
            "subject_id": [
                "sub",
                "subject",
                "participant_id",
                "id",
                "subject_id",
                "SubjectID",
                "Subject",
                "subj_id",
            ],
            "session": ["ses", "session", "visit", "timepoint", "wave", "Session"],
            "age": ["age", "Age", "age_years", "age_at_scan", "AgeAtScan"],
            "sex": ["sex", "gender", "Sex", "Gender", "biological_sex"],
            "handedness": ["handedness", "hand", "Handedness", "dominant_hand"],
            "diagnosis": [
                "diagnosis",
                "dx",
                "Diagnosis",
                "clinical_diagnosis",
                "group",
            ],
        }

        # BIDS to other dataset mappings
        self.bids_mappings = {
            "OpenNeuro": {
                "participant_id": "sub",
                "age": "age",
                "sex": "sex",
                "session": "ses",
            },
            "HCP": {
                "participant_id": "Subject",
                "age": "Age_in_Yrs",
                "sex": "Gender",
                "handedness": "Handedness",
            },
            "ABCD": {
                "participant_id": "subjectkey",
                "age": "interview_age",
                "sex": "sex",
                "session": "eventname",
            },
        }

    def map_schemas(
        self, source_schema: Dict[str, Any], target_format: str = "BIDS"
    ) -> Dict[str, FieldMapping]:
        """Map source schema to target format.

        Args:
            source_schema: Source dataset schema
            target_format: Target schema format

        Returns:
            Field mappings from source to target
        """
        mappings = {}
        target_schema = self.standard_schemas.get(target_format, {})

        for source_field, field_info in source_schema.items():
            # Try exact match first
            if source_field in target_schema:
                mappings[source_field] = FieldMapping(
                    source_field=source_field, target_field=source_field, confidence=1.0
                )
                continue

            # Try common mappings
            mapping = self._find_common_mapping(source_field)
            if mapping:
                mappings[source_field] = mapping
                continue

            # Try fuzzy matching
            fuzzy_match = self._fuzzy_match_field(
                source_field, list(target_schema.keys())
            )
            if fuzzy_match:
                mappings[source_field] = fuzzy_match
                continue

            # Try semantic matching
            semantic_match = self._semantic_match(source_field, target_schema)
            if semantic_match:
                mappings[source_field] = semantic_match

        logger.info(f"Mapped {len(mappings)} fields from source to {target_format}")
        return mappings

    def apply_mappings(
        self, data: pd.DataFrame, mappings: Dict[str, FieldMapping]
    ) -> pd.DataFrame:
        """Apply schema mappings to data.

        Args:
            data: Input data with source schema
            mappings: Field mappings to apply

        Returns:
            Data with mapped schema
        """
        mapped_data = pd.DataFrame()

        for source_field, mapping in mappings.items():
            if source_field not in data.columns:
                logger.warning(f"Source field '{source_field}' not found in data")
                continue

            # Apply transformation if specified
            if mapping.transform_func:
                try:
                    mapped_data[mapping.target_field] = data[source_field].apply(
                        mapping.transform_func
                    )
                except Exception as e:
                    logger.error(f"Failed to transform field '{source_field}': {e}")
                    mapped_data[mapping.target_field] = data[source_field]
            else:
                mapped_data[mapping.target_field] = data[source_field]

        return mapped_data

    def create_mapping_profile(self, datasets: List[str]) -> Dict[str, Any]:
        """Create mapping profile for multiple datasets.

        Args:
            datasets: List of dataset identifiers

        Returns:
            Mapping profile with compatibility scores
        """
        profile = {
            "datasets": datasets,
            "compatibility_matrix": {},
            "common_fields": [],
            "mapping_quality": {},
        }

        # Build compatibility matrix
        for source in datasets:
            profile["compatibility_matrix"][source] = {}
            for target in datasets:
                if source != target:
                    score = self._calculate_compatibility(source, target)
                    profile["compatibility_matrix"][source][target] = score

        # Find common fields across all datasets
        all_fields = []
        for dataset in datasets:
            schema = self._get_dataset_schema(dataset)
            all_fields.extend(list(schema.keys()))

        field_counts = pd.Series(all_fields).value_counts()
        profile["common_fields"] = field_counts[
            field_counts == len(datasets)
        ].index.tolist()

        # Assess mapping quality
        for dataset in datasets:
            profile["mapping_quality"][dataset] = self._assess_mapping_quality(dataset)

        return profile

    def harmonize_field_names(
        self, datasets: Dict[str, pd.DataFrame]
    ) -> Dict[str, pd.DataFrame]:
        """Harmonize field names across multiple datasets.

        Args:
            datasets: Dictionary of dataset names to DataFrames

        Returns:
            Datasets with harmonized field names
        """
        harmonized = {}

        # Find the most complete schema as reference
        reference_dataset = self._find_reference_schema(datasets)
        reference_schema = set(datasets[reference_dataset].columns)

        for name, data in datasets.items():
            if name == reference_dataset:
                harmonized[name] = data.copy()
                self._dataset_schemas[name] = {
                    col: {"type": str(harmonized[name][col].dtype)}
                    for col in harmonized[name].columns
                }
                continue

            # Map to reference schema
            mappings = self._map_to_reference(
                source_schema=set(data.columns), reference_schema=reference_schema
            )

            # Apply mappings
            harmonized_data = data.copy()
            for old_name, new_name in mappings.items():
                if old_name in harmonized_data.columns:
                    harmonized_data.rename(columns={old_name: new_name}, inplace=True)

            harmonized[name] = harmonized_data
            self._dataset_schemas[name] = {
                col: {"type": str(harmonized_data[col].dtype)}
                for col in harmonized_data.columns
            }

        logger.info(f"Harmonized field names across {len(datasets)} datasets")
        return harmonized

    def validate_mapping(
        self, mapping: Dict[str, FieldMapping], data: pd.DataFrame
    ) -> Dict[str, Any]:
        """Validate schema mapping against actual data.

        Args:
            mapping: Field mappings
            data: Data to validate against

        Returns:
            Validation results
        """
        validation_results = {
            "valid": True,
            "coverage": 0.0,
            "missing_fields": [],
            "type_mismatches": [],
            "warnings": [],
        }

        # Check field coverage
        mapped_fields = set(m.source_field for m in mapping.values())
        data_fields = set(data.columns)

        validation_results["coverage"] = len(mapped_fields & data_fields) / len(
            data_fields
        )
        validation_results["missing_fields"] = list(data_fields - mapped_fields)

        # Check data type compatibility
        for source_field, field_mapping in mapping.items():
            if source_field in data.columns:
                source_dtype = data[source_field].dtype
                expected_dtype = self._get_expected_dtype(field_mapping.target_field)

                if expected_dtype and not self._compatible_dtypes(
                    source_dtype, expected_dtype
                ):
                    validation_results["type_mismatches"].append(
                        {
                            "field": source_field,
                            "source_type": str(source_dtype),
                            "expected_type": str(expected_dtype),
                        }
                    )

        # Generate warnings
        if validation_results["coverage"] < 0.8:
            validation_results["warnings"].append(
                f"Low field coverage: {validation_results['coverage']:.1%}"
            )

        if validation_results["type_mismatches"]:
            validation_results["warnings"].append(
                f"Found {len(validation_results['type_mismatches'])} type mismatches"
            )

        validation_results["valid"] = (
            validation_results["coverage"] > 0.5
            and len(validation_results["type_mismatches"]) == 0
        )

        return validation_results

    def export_mapping_config(
        self, mappings: Dict[str, FieldMapping], output_path: str
    ):
        """Export mapping configuration for reuse.

        Args:
            mappings: Field mappings
            output_path: Path to save configuration
        """
        config = {"version": "1.0", "mappings": []}

        for source_field, mapping in mappings.items():
            config["mappings"].append(
                {
                    "source": mapping.source_field,
                    "target": mapping.target_field,
                    "confidence": mapping.confidence,
                    "type": mapping.mapping_type,
                }
            )

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w") as f:
            json.dump(config, f, indent=2)

        logger.info(f"Exported mapping configuration to {output_path}")

    def register_custom_mapping(
        self, source_format: str, target_format: str, mapping: Dict[str, str]
    ):
        """Register custom field mapping.

        Args:
            source_format: Source dataset format
            target_format: Target dataset format
            mapping: Field name mappings
        """
        key = f"{source_format}_to_{target_format}"
        self.custom_mappings[key] = mapping
        logger.info(f"Registered custom mapping: {key}")

    # Private helper methods

    def _load_standard_schemas(self) -> Dict[str, Dict[str, Any]]:
        """Load standard schema definitions."""
        return {
            "BIDS": {
                "participant_id": {"type": "string", "required": True},
                "age": {"type": "float", "required": False},
                "sex": {"type": "string", "required": False, "values": ["M", "F"]},
                "handedness": {"type": "string", "required": False},
                "session": {"type": "string", "required": False},
            },
            "NIDM": {
                "subject_id": {"type": "string", "required": True},
                "age_at_scan": {"type": "float", "required": False},
                "gender": {"type": "string", "required": False},
            },
        }

    def _load_mapping_config(self, config_path: str):
        """Load mapping configuration from file."""
        config_path = Path(config_path)
        if config_path.exists():
            with open(config_path, "r") as f:
                config = json.load(f)
                # Process and store mappings
                for mapping in config.get("mappings", []):
                    self.mappings[mapping["source"]] = FieldMapping(
                        source_field=mapping["source"],
                        target_field=mapping["target"],
                        confidence=mapping.get("confidence", 1.0),
                        mapping_type=mapping.get("type", "direct"),
                    )

    def _find_common_mapping(self, field_name: str) -> Optional[FieldMapping]:
        """Find mapping using common field names."""
        field_lower = field_name.lower()

        for standard_field, variations in self.common_mappings.items():
            if field_lower in [v.lower() for v in variations]:
                return FieldMapping(
                    source_field=field_name,
                    target_field=standard_field,
                    confidence=0.9,
                    mapping_type="common",
                )

        return None

    def _fuzzy_match_field(
        self, source_field: str, target_fields: List[str], threshold: int = 80
    ) -> Optional[FieldMapping]:
        """Find field mapping using fuzzy matching."""
        if not target_fields:
            return None

        # Use fuzzy matching
        match, score = process.extractOne(source_field, target_fields)

        if score >= threshold:
            return FieldMapping(
                source_field=source_field,
                target_field=match,
                confidence=score / 100.0,
                mapping_type="fuzzy",
            )

        return None

    def _semantic_match(
        self, source_field: str, target_schema: Dict[str, Any]
    ) -> Optional[FieldMapping]:
        """Find mapping using semantic similarity."""
        # This would use word embeddings or ontologies
        # For now, use simple keyword matching

        source_keywords = set(source_field.lower().split("_"))

        for target_field in target_schema:
            target_keywords = set(target_field.lower().split("_"))

            # Check for significant overlap
            overlap = source_keywords & target_keywords
            if len(overlap) >= min(len(source_keywords), len(target_keywords)) * 0.5:
                return FieldMapping(
                    source_field=source_field,
                    target_field=target_field,
                    confidence=0.7,
                    mapping_type="semantic",
                )

        return None

    def _calculate_compatibility(self, source: str, target: str) -> float:
        """Calculate compatibility score between datasets."""
        # Get schemas
        source_schema = self._get_dataset_schema(source)
        target_schema = self._get_dataset_schema(target)

        if not source_schema or not target_schema:
            return 0.0

        # Calculate field overlap
        source_fields = set(source_schema.keys())
        target_fields = set(target_schema.keys())

        overlap = len(source_fields & target_fields)
        total = len(source_fields | target_fields)

        return overlap / total if total > 0 else 0.0

    def _get_dataset_schema(self, dataset: str) -> Dict[str, Any]:
        """Get schema for a dataset."""
        if dataset in self._dataset_schemas:
            return self._dataset_schemas[dataset]
        # Return known schemas or empty dict
        if dataset == "BIDS":
            return self.standard_schemas.get("BIDS", {})
        elif dataset in self.bids_mappings:
            return self.bids_mappings[dataset]

        return {}

    def _assess_mapping_quality(self, dataset: str) -> Dict[str, Any]:
        """Assess mapping quality for a dataset."""
        return {
            "completeness": 0.85,  # Placeholder
            "accuracy": 0.90,  # Placeholder
            "consistency": 0.88,  # Placeholder
        }

    def _find_reference_schema(self, datasets: Dict[str, pd.DataFrame]) -> str:
        """Find the most complete dataset to use as reference."""
        scores = {}

        for name, data in datasets.items():
            # Score based on number of columns and rows
            scores[name] = len(data.columns) * np.log(len(data) + 1)

        return max(scores, key=scores.get)

    def _map_to_reference(
        self, source_schema: set, reference_schema: set
    ) -> Dict[str, str]:
        """Map source schema to reference schema."""
        mappings = {}

        for source_field in source_schema:
            # Try exact match
            if source_field in reference_schema:
                mappings[source_field] = source_field
                continue

            # Try fuzzy match
            match, score = process.extractOne(source_field, list(reference_schema))
            if score >= 80:
                mappings[source_field] = match

        return mappings

    def _get_expected_dtype(self, field_name: str) -> Optional[type]:
        """Get expected data type for a field."""
        type_mappings = {
            "age": float,
            "participant_id": str,
            "sex": str,
            "handedness": str,
            "diagnosis": str,
        }

        return type_mappings.get(field_name)

    def _compatible_dtypes(self, source_dtype: type, expected_dtype: type) -> bool:
        """Check if data types are compatible."""
        # Handle numpy dtypes
        if "int" in str(source_dtype) and expected_dtype == float:
            return True
        if "float" in str(source_dtype) and expected_dtype == float:
            return True
        if "object" in str(source_dtype) and expected_dtype == str:
            return True

        return source_dtype == expected_dtype
