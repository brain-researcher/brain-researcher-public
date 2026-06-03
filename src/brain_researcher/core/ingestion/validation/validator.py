"""Main validation engine combining schema and custom rules.

Provides batch validation with detailed error reporting.
"""

import logging
from collections.abc import Callable
from typing import Any

from .rules import RuleValidator, get_rules_for_schema
from .schemas import COMPILED_SCHEMAS

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Validation error with line number context."""

    def __init__(self, line: int, message: str, field: str | None = None):
        """Initialize validation error.

        Args:
            line: Line number where error occurred
            message: Error message
            field: Optional field name that failed
        """
        self.line = line
        self.message = message
        self.field = field

        full_message = f"Line {line}"
        if field:
            full_message += f", field '{field}'"
        full_message += f": {message}"

        super().__init__(full_message)


class ValidationEngine:
    """Main validation engine with schema and custom rules."""

    def __init__(
        self,
        schema_key: str,
        extra_checks: list[Callable[[dict[str, Any]], None]] | None = None,
        strict: bool = True,
    ):
        """Initialize validation engine.

        Args:
            schema_key: Schema key (e.g., "pubmed.article")
            extra_checks: Additional validation functions
            strict: If True, fail on unknown fields
        """
        if schema_key not in COMPILED_SCHEMAS:
            raise ValueError(f"Unknown schema: {schema_key}")

        self.schema_key = schema_key
        self._validate_schema = COMPILED_SCHEMAS[schema_key]
        self.strict = strict

        # Combine default and extra rules
        self.rules = get_rules_for_schema(schema_key)
        if extra_checks:
            self.rules.extend(extra_checks)

        self.rule_validator = RuleValidator(self.rules)

        # Statistics
        self.stats = {
            "total": 0,
            "valid": 0,
            "invalid": 0,
            "schema_errors": 0,
            "rule_errors": 0,
        }

    def validate_single(
        self, obj: dict[str, Any], line: int = 0
    ) -> list[ValidationError]:
        """Validate a single object.

        Args:
            obj: Object to validate
            line: Line number for error reporting

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        # Schema validation
        try:
            self._validate_schema(obj)
        except Exception as e:
            errors.append(ValidationError(line, f"Schema validation: {str(e)}"))
            self.stats["schema_errors"] += 1

        # Custom rule validation
        rule_errors = self.rule_validator.validate(obj)
        for error_msg in rule_errors:
            errors.append(ValidationError(line, f"Rule validation: {error_msg}"))
            self.stats["rule_errors"] += 1

        # Update statistics
        self.stats["total"] += 1
        if errors:
            self.stats["invalid"] += 1
        else:
            self.stats["valid"] += 1

        return errors

    def validate_batch(
        self, items: list[tuple[int, dict[str, Any]]], stop_on_error: bool = False
    ) -> tuple[list[dict[str, Any]], list[ValidationError]]:
        """Validate a batch of items.

        Args:
            items: List of (line_number, object) tuples
            stop_on_error: If True, stop on first error

        Returns:
            Tuple of (valid_objects, errors)
        """
        valid_objects = []
        all_errors = []

        for line_num, obj in items:
            errors = self.validate_single(obj, line_num)

            if errors:
                all_errors.extend(errors)
                if stop_on_error:
                    break
            else:
                valid_objects.append(obj)

        return valid_objects, all_errors

    def get_statistics(self) -> dict[str, Any]:
        """Get validation statistics.

        Returns:
            Statistics dictionary
        """
        stats = dict(self.stats)

        # Calculate rates
        if stats["total"] > 0:
            stats["valid_rate"] = stats["valid"] / stats["total"]
            stats["invalid_rate"] = stats["invalid"] / stats["total"]
        else:
            stats["valid_rate"] = 0
            stats["invalid_rate"] = 0

        return stats

    def reset_statistics(self):
        """Reset validation statistics."""
        self.stats = {
            "total": 0,
            "valid": 0,
            "invalid": 0,
            "schema_errors": 0,
            "rule_errors": 0,
        }


class MultiSchemaValidator:
    """Validate objects against multiple schemas based on type field."""

    def __init__(self, schema_mapping: dict[str, str]):
        """Initialize multi-schema validator.

        Args:
            schema_mapping: Map of type values to schema keys
                e.g., {"concept": "cognitive_atlas.concept"}
        """
        self.validators = {}

        for type_value, schema_key in schema_mapping.items():
            self.validators[type_value] = ValidationEngine(schema_key)

    def validate(
        self, obj: dict[str, Any], type_field: str = "type", line: int = 0
    ) -> list[ValidationError]:
        """Validate object based on its type field.

        Args:
            obj: Object to validate
            type_field: Name of field containing type
            line: Line number for error reporting

        Returns:
            List of validation errors
        """
        obj_type = obj.get(type_field)

        if not obj_type:
            return [ValidationError(line, f"Missing required field: {type_field}")]

        if obj_type not in self.validators:
            return [ValidationError(line, f"Unknown type: {obj_type}")]

        return self.validators[obj_type].validate_single(obj, line)


class ValidationReport:
    """Generate validation reports with detailed error analysis."""

    def __init__(self):
        """Initialize report generator."""
        self.errors_by_type: dict[str, int] = {}
        self.errors_by_field: dict[str, int] = {}
        self.sample_errors: list[ValidationError] = []
        self.max_samples = 10

    def add_error(self, error: ValidationError):
        """Add an error to the report.

        Args:
            error: Validation error
        """
        # Categorize error
        if "Schema" in error.message:
            error_type = "schema"
        elif "Rule" in error.message:
            error_type = "rule"
        else:
            error_type = "other"

        self.errors_by_type[error_type] = self.errors_by_type.get(error_type, 0) + 1

        # Track field errors
        if error.field:
            self.errors_by_field[error.field] = (
                self.errors_by_field.get(error.field, 0) + 1
            )

        # Keep sample errors
        if len(self.sample_errors) < self.max_samples:
            self.sample_errors.append(error)

    def generate_report(self) -> dict[str, Any]:
        """Generate validation report.

        Returns:
            Report dictionary
        """
        return {
            "total_errors": sum(self.errors_by_type.values()),
            "errors_by_type": self.errors_by_type,
            "errors_by_field": self.errors_by_field,
            "sample_errors": [
                {"line": e.line, "message": e.message, "field": e.field}
                for e in self.sample_errors
            ],
        }

    def print_report(self):
        """Print human-readable report."""
        report = self.generate_report()

        print("\n=== Validation Report ===")
        print(f"Total errors: {report['total_errors']}")

        if report["errors_by_type"]:
            print("\nErrors by type:")
            for error_type, count in report["errors_by_type"].items():
                print(f"  {error_type}: {count}")

        if report["errors_by_field"]:
            print("\nTop fields with errors:")
            sorted_fields = sorted(
                report["errors_by_field"].items(), key=lambda x: x[1], reverse=True
            )[:5]
            for field, count in sorted_fields:
                print(f"  {field}: {count}")

        if report["sample_errors"]:
            print("\nSample errors:")
            for error in report["sample_errors"][:5]:
                print(f"  Line {error['line']}: {error['message']}")
