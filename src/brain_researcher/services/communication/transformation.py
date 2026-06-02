"""
Request/Response Transformation Components.

Provides advanced transformation capabilities for API Gateway
including content conversion, validation, and custom transformations.
"""

import base64
import gzip
import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Type, Union

import yaml

try:
    import dicttoxml
    import xmltodict

    XML_AVAILABLE = True
except ImportError:
    XML_AVAILABLE = False

try:
    from jsonschema import ValidationError, validate

    JSONSCHEMA_AVAILABLE = True
except ImportError:
    JSONSCHEMA_AVAILABLE = False

try:
    from jinja2 import BaseLoader, Environment, Template

    JINJA2_AVAILABLE = True
except ImportError:
    JINJA2_AVAILABLE = False

logger = logging.getLogger(__name__)


class ContentFormat(str, Enum):
    """Supported content formats."""

    JSON = "json"
    XML = "xml"
    YAML = "yaml"
    CSV = "csv"
    TEXT = "text"
    BINARY = "binary"
    FORM_ENCODED = "form_encoded"
    MULTIPART = "multipart"


class TransformationType(str, Enum):
    """Types of transformations."""

    FORMAT_CONVERSION = "format_conversion"
    FIELD_MAPPING = "field_mapping"
    VALIDATION = "validation"
    FILTERING = "filtering"
    AGGREGATION = "aggregation"
    TEMPLATE = "template"
    CUSTOM = "custom"


@dataclass
class TransformationRule:
    """Individual transformation rule."""

    name: str
    type: TransformationType
    input_path: Optional[str] = None
    output_path: Optional[str] = None
    template: Optional[str] = None
    function: Optional[Callable] = None
    parameters: Dict[str, Any] = None
    condition: Optional[str] = None
    enabled: bool = True

    def __post_init__(self):
        if self.parameters is None:
            self.parameters = {}


@dataclass
class ValidationRule:
    """Validation rule configuration."""

    name: str
    field_path: str
    rule_type: str  # required, type, format, range, regex, custom
    parameters: Dict[str, Any] = None
    error_message: Optional[str] = None
    enabled: bool = True

    def __post_init__(self):
        if self.parameters is None:
            self.parameters = {}


class TransformationError(Exception):
    """Exception raised during transformation."""

    def __init__(
        self,
        message: str,
        rule_name: Optional[str] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.rule_name = rule_name
        self.original_error = original_error


class ContentConverter:
    """Handles content format conversion."""

    @staticmethod
    def convert(data: Any, from_format: ContentFormat, to_format: ContentFormat) -> Any:
        """Convert data between formats.

        Args:
            data: Data to convert
            from_format: Source format
            to_format: Target format

        Returns:
            Converted data

        Raises:
            TransformationError: If conversion fails
        """
        try:
            # Parse from source format
            parsed_data = ContentConverter._parse(data, from_format)

            # Serialize to target format
            return ContentConverter._serialize(parsed_data, to_format)

        except Exception as e:
            raise TransformationError(
                f"Format conversion failed: {from_format} -> {to_format}",
                original_error=e,
            )

    @staticmethod
    def _parse(data: Any, format_type: ContentFormat) -> Any:
        """Parse data from specific format."""
        if isinstance(data, bytes):
            data = data.decode("utf-8")

        if format_type == ContentFormat.JSON:
            return json.loads(data) if isinstance(data, str) else data

        elif format_type == ContentFormat.XML:
            if not XML_AVAILABLE:
                raise TransformationError(
                    "XML support not available (install xmltodict)"
                )
            return xmltodict.parse(data) if isinstance(data, str) else data

        elif format_type == ContentFormat.YAML:
            return yaml.safe_load(data) if isinstance(data, str) else data

        elif format_type == ContentFormat.CSV:
            import csv
            import io

            if isinstance(data, str):
                reader = csv.DictReader(io.StringIO(data))
                return list(reader)
            return data

        elif format_type == ContentFormat.FORM_ENCODED:
            import urllib.parse

            if isinstance(data, str):
                return dict(urllib.parse.parse_qsl(data))
            return data

        elif format_type in [ContentFormat.TEXT, ContentFormat.BINARY]:
            return data

        else:
            raise TransformationError(f"Unsupported format: {format_type}")

    @staticmethod
    def _serialize(data: Any, format_type: ContentFormat) -> Any:
        """Serialize data to specific format."""
        if format_type == ContentFormat.JSON:
            return json.dumps(data, ensure_ascii=False, indent=2)

        elif format_type == ContentFormat.XML:
            if not XML_AVAILABLE:
                raise TransformationError(
                    "XML support not available (install dicttoxml)"
                )
            if isinstance(data, dict):
                return dicttoxml.dicttoxml(
                    data, custom_root="root", attr_type=False
                ).decode("utf-8")
            return str(data)

        elif format_type == ContentFormat.YAML:
            return yaml.dump(data, default_flow_style=False, allow_unicode=True)

        elif format_type == ContentFormat.CSV:
            import csv
            import io

            if isinstance(data, list) and data and isinstance(data[0], dict):
                output = io.StringIO()
                writer = csv.DictWriter(output, fieldnames=data[0].keys())
                writer.writeheader()
                writer.writerows(data)
                return output.getvalue()
            return str(data)

        elif format_type == ContentFormat.FORM_ENCODED:
            import urllib.parse

            if isinstance(data, dict):
                return urllib.parse.urlencode(data)
            return str(data)

        elif format_type == ContentFormat.TEXT:
            return str(data)

        elif format_type == ContentFormat.BINARY:
            if isinstance(data, str):
                return data.encode("utf-8")
            return data

        else:
            raise TransformationError(f"Unsupported format: {format_type}")


class DataValidator:
    """Validates data against rules and schemas."""

    def __init__(self):
        """Initialize validator."""
        self.validators = {
            "required": self._validate_required,
            "type": self._validate_type,
            "format": self._validate_format,
            "range": self._validate_range,
            "regex": self._validate_regex,
            "length": self._validate_length,
            "enum": self._validate_enum,
        }

    def validate(self, data: Dict[str, Any], rules: List[ValidationRule]) -> List[str]:
        """Validate data against rules.

        Args:
            data: Data to validate
            rules: Validation rules

        Returns:
            List of validation errors
        """
        errors = []

        for rule in rules:
            if not rule.enabled:
                continue

            try:
                # Get field value
                field_value = self._get_field_value(data, rule.field_path)

                # Apply validation
                validator = self.validators.get(rule.rule_type)
                if validator:
                    error = validator(field_value, rule)
                    if error:
                        errors.append(error)
                else:
                    logger.warning(f"Unknown validation rule type: {rule.rule_type}")

            except Exception as e:
                error_msg = (
                    rule.error_message
                    or f"Validation failed for {rule.field_path}: {e}"
                )
                errors.append(error_msg)

        return errors

    def validate_schema(
        self, data: Dict[str, Any], schema: Dict[str, Any]
    ) -> List[str]:
        """Validate data against JSON schema.

        Args:
            data: Data to validate
            schema: JSON schema

        Returns:
            List of validation errors
        """
        if not JSONSCHEMA_AVAILABLE:
            return ["JSON Schema validation not available (install jsonschema)"]

        try:
            validate(instance=data, schema=schema)
            return []
        except ValidationError as e:
            return [str(e)]
        except Exception as e:
            return [f"Schema validation error: {e}"]

    def _get_field_value(self, data: Dict[str, Any], field_path: str) -> Any:
        """Get field value using dot notation path."""
        keys = field_path.split(".")
        current = data

        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None

        return current

    def _validate_required(self, value: Any, rule: ValidationRule) -> Optional[str]:
        """Validate required field."""
        if value is None or value == "":
            return rule.error_message or f"Field {rule.field_path} is required"
        return None

    def _validate_type(self, value: Any, rule: ValidationRule) -> Optional[str]:
        """Validate field type."""
        if value is None:
            return None

        expected_type = rule.parameters.get("type")
        type_map = {
            "string": str,
            "number": (int, float),
            "integer": int,
            "boolean": bool,
            "array": list,
            "object": dict,
        }

        expected_python_type = type_map.get(expected_type)
        if expected_python_type and not isinstance(value, expected_python_type):
            return (
                rule.error_message
                or f"Field {rule.field_path} must be of type {expected_type}"
            )

        return None

    def _validate_format(self, value: Any, rule: ValidationRule) -> Optional[str]:
        """Validate field format."""
        if value is None or not isinstance(value, str):
            return None

        format_type = rule.parameters.get("format")

        if format_type == "email":
            email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
            if not re.match(email_pattern, value):
                return (
                    rule.error_message
                    or f"Field {rule.field_path} must be a valid email"
                )

        elif format_type == "url":
            url_pattern = r"^https?://[^\s/$.?#].[^\s]*$"
            if not re.match(url_pattern, value):
                return (
                    rule.error_message or f"Field {rule.field_path} must be a valid URL"
                )

        elif format_type == "date":
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return (
                    rule.error_message
                    or f"Field {rule.field_path} must be a valid date"
                )

        return None

    def _validate_range(self, value: Any, rule: ValidationRule) -> Optional[str]:
        """Validate numeric range."""
        if value is None or not isinstance(value, (int, float)):
            return None

        min_val = rule.parameters.get("min")
        max_val = rule.parameters.get("max")

        if min_val is not None and value < min_val:
            return rule.error_message or f"Field {rule.field_path} must be >= {min_val}"

        if max_val is not None and value > max_val:
            return rule.error_message or f"Field {rule.field_path} must be <= {max_val}"

        return None

    def _validate_length(self, value: Any, rule: ValidationRule) -> Optional[str]:
        """Validate string/array length."""
        if value is None:
            return None

        if not hasattr(value, "__len__"):
            return None

        length = len(value)
        min_length = rule.parameters.get("min")
        max_length = rule.parameters.get("max")

        if min_length is not None and length < min_length:
            return (
                rule.error_message
                or f"Field {rule.field_path} must have at least {min_length} items"
            )

        if max_length is not None and length > max_length:
            return (
                rule.error_message
                or f"Field {rule.field_path} must have at most {max_length} items"
            )

        return None

    def _validate_regex(self, value: Any, rule: ValidationRule) -> Optional[str]:
        """Validate against regex pattern."""
        if value is None or not isinstance(value, str):
            return None

        pattern = rule.parameters.get("pattern")
        if pattern and not re.match(pattern, value):
            return (
                rule.error_message
                or f"Field {rule.field_path} does not match required pattern"
            )

        return None

    def _validate_enum(self, value: Any, rule: ValidationRule) -> Optional[str]:
        """Validate against allowed values."""
        if value is None:
            return None

        allowed_values = rule.parameters.get("values", [])
        if allowed_values and value not in allowed_values:
            return (
                rule.error_message
                or f"Field {rule.field_path} must be one of: {allowed_values}"
            )

        return None


class TemplateProcessor:
    """Processes template-based transformations."""

    def __init__(self):
        """Initialize template processor."""
        if JINJA2_AVAILABLE:
            self.env = Environment(loader=BaseLoader())
        else:
            self.env = None

    def process_template(self, template_str: str, context: Dict[str, Any]) -> str:
        """Process Jinja2 template.

        Args:
            template_str: Template string
            context: Template context variables

        Returns:
            Rendered template
        """
        if not JINJA2_AVAILABLE:
            raise TransformationError(
                "Template processing not available (install jinja2)"
            )

        try:
            template = self.env.from_string(template_str)
            return template.render(**context)
        except Exception as e:
            raise TransformationError(
                f"Template processing failed: {e}", original_error=e
            )

    def process_field_template(
        self, data: Dict[str, Any], field_path: str, template_str: str
    ) -> Dict[str, Any]:
        """Process template for specific field.

        Args:
            data: Input data
            field_path: Field path to update
            template_str: Template string

        Returns:
            Updated data
        """
        context = {
            "data": data,
            "field_value": self._get_field_value(data, field_path),
            "timestamp": datetime.utcnow().isoformat(),
        }

        rendered_value = self.process_template(template_str, context)

        # Parse as JSON if possible
        try:
            rendered_value = json.loads(rendered_value)
        except (json.JSONDecodeError, TypeError):
            pass  # Keep as string

        self._set_field_value(data, field_path, rendered_value)
        return data

    def _get_field_value(self, data: Dict[str, Any], field_path: str) -> Any:
        """Get field value using dot notation."""
        keys = field_path.split(".")
        current = data

        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None

        return current

    def _set_field_value(self, data: Dict[str, Any], field_path: str, value: Any):
        """Set field value using dot notation."""
        keys = field_path.split(".")
        current = data

        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]

        current[keys[-1]] = value


class DataTransformer:
    """Main data transformation engine."""

    def __init__(self):
        """Initialize transformer."""
        self.converter = ContentConverter()
        self.validator = DataValidator()
        self.template_processor = TemplateProcessor()

    def transform(
        self,
        data: Any,
        rules: List[TransformationRule],
        context: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Apply transformation rules to data.

        Args:
            data: Input data
            rules: Transformation rules
            context: Additional context for transformations

        Returns:
            Transformed data
        """
        result = data
        context = context or {}

        for rule in rules:
            if not rule.enabled:
                continue

            # Check condition if specified
            if rule.condition and not self._evaluate_condition(
                rule.condition, result, context
            ):
                continue

            try:
                result = self._apply_rule(result, rule, context)
            except Exception as e:
                raise TransformationError(
                    f"Transformation rule '{rule.name}' failed: {e}",
                    rule_name=rule.name,
                    original_error=e,
                )

        return result

    def _apply_rule(
        self, data: Any, rule: TransformationRule, context: Dict[str, Any]
    ) -> Any:
        """Apply single transformation rule."""
        if rule.type == TransformationType.FORMAT_CONVERSION:
            return self._apply_format_conversion(data, rule)

        elif rule.type == TransformationType.FIELD_MAPPING:
            return self._apply_field_mapping(data, rule)

        elif rule.type == TransformationType.TEMPLATE:
            return self._apply_template_transformation(data, rule, context)

        elif rule.type == TransformationType.FILTERING:
            return self._apply_filtering(data, rule)

        elif rule.type == TransformationType.CUSTOM:
            return self._apply_custom_transformation(data, rule, context)

        else:
            logger.warning(f"Unsupported transformation type: {rule.type}")
            return data

    def _apply_format_conversion(self, data: Any, rule: TransformationRule) -> Any:
        """Apply format conversion."""
        from_format = ContentFormat(rule.parameters.get("from_format", "json"))
        to_format = ContentFormat(rule.parameters.get("to_format", "json"))

        return self.converter.convert(data, from_format, to_format)

    def _apply_field_mapping(self, data: Any, rule: TransformationRule) -> Any:
        """Apply field mapping transformation."""
        if not isinstance(data, dict):
            return data

        result = data.copy()

        if rule.input_path and rule.output_path:
            # Move/copy field
            input_value = self._get_nested_value(result, rule.input_path)
            if input_value is not None:
                self._set_nested_value(result, rule.output_path, input_value)

                # Remove original field if it's a move operation
                if rule.parameters.get("move", False):
                    self._delete_nested_value(result, rule.input_path)

        return result

    def _apply_template_transformation(
        self, data: Any, rule: TransformationRule, context: Dict[str, Any]
    ) -> Any:
        """Apply template-based transformation."""
        if not isinstance(data, dict):
            return data

        template_context = {
            "data": data,
            **context,
            "timestamp": datetime.utcnow().isoformat(),
        }

        if rule.template and rule.output_path:
            # Apply template to specific field
            return self.template_processor.process_field_template(
                data.copy(), rule.output_path, rule.template
            )
        elif rule.template:
            # Apply template to entire data
            rendered = self.template_processor.process_template(
                rule.template, template_context
            )
            try:
                return json.loads(rendered)
            except json.JSONDecodeError:
                return rendered

        return data

    def _apply_filtering(self, data: Any, rule: TransformationRule) -> Any:
        """Apply filtering transformation."""
        if not isinstance(data, dict):
            return data

        filter_type = rule.parameters.get("type", "include")
        fields = rule.parameters.get("fields", [])

        if filter_type == "include":
            # Include only specified fields
            return {key: value for key, value in data.items() if key in fields}
        elif filter_type == "exclude":
            # Exclude specified fields
            return {key: value for key, value in data.items() if key not in fields}

        return data

    def _apply_custom_transformation(
        self, data: Any, rule: TransformationRule, context: Dict[str, Any]
    ) -> Any:
        """Apply custom transformation function."""
        if rule.function and callable(rule.function):
            return rule.function(data, context, rule.parameters)

        return data

    def _evaluate_condition(
        self, condition: str, data: Any, context: Dict[str, Any]
    ) -> bool:
        """Evaluate transformation condition."""
        try:
            # Simple condition evaluation
            # In production, use a safer evaluation method
            eval_context = {"data": data, **context}
            return eval(condition, {"__builtins__": {}}, eval_context)
        except Exception:
            return False

    def _get_nested_value(self, data: Dict[str, Any], path: str) -> Any:
        """Get nested value using dot notation."""
        keys = path.split(".")
        current = data

        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None

        return current

    def _set_nested_value(self, data: Dict[str, Any], path: str, value: Any):
        """Set nested value using dot notation."""
        keys = path.split(".")
        current = data

        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]

        current[keys[-1]] = value

    def _delete_nested_value(self, data: Dict[str, Any], path: str):
        """Delete nested value using dot notation."""
        keys = path.split(".")
        current = data

        for key in keys[:-1]:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return

        if isinstance(current, dict) and keys[-1] in current:
            del current[keys[-1]]


# Export components
__all__ = [
    "DataTransformer",
    "ContentConverter",
    "DataValidator",
    "TemplateProcessor",
    "TransformationRule",
    "ValidationRule",
    "ContentFormat",
    "TransformationType",
    "TransformationError",
]
