"""
Request and Response Transformers for API Gateway.

Handles transformation of HTTP requests and responses as they pass through
the gateway, including:

Request Transformations:
- Header manipulation (add/remove/modify)
- Query parameter transformation
- Body transformation and validation
- Authentication token injection
- Request format conversion (JSON/XML/form data)

Response Transformations:
- Response header manipulation
- Content transformation and filtering
- Format conversion
- Error response standardization
- Response compression
- Response caching headers

Features:
- Configurable transformation rules
- Content type detection and conversion
- Schema validation
- Template-based transformations
- Plugin architecture for custom transformers
"""

import base64
import gzip
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import httpx
import yaml
from fastapi import Request
from jinja2 import Template
from pydantic import BaseModel, Field, validator

from brain_researcher.services.shared.api_version import API_VERSION, API_VERSION_HEADER

try:
    import xmltodict
except ImportError:
    xmltodict = None

try:
    import dicttoxml
except ImportError:
    dicttoxml = None

logger = logging.getLogger(__name__)


class TransformationAction(str, Enum):
    """Types of transformation actions."""

    ADD = "add"
    REMOVE = "remove"
    REPLACE = "replace"
    APPEND = "append"
    PREPEND = "prepend"
    TRANSFORM = "transform"


class ContentType(str, Enum):
    """Supported content types."""

    JSON = "application/json"
    XML = "application/xml"
    FORM = "application/x-www-form-urlencoded"
    TEXT = "text/plain"
    HTML = "text/html"
    BINARY = "application/octet-stream"


@dataclass
class TransformationRule:
    """Single transformation rule."""

    name: str
    action: TransformationAction
    target: str  # header name, json path, etc.
    value: Optional[str] = None
    condition: Optional[str] = None  # Jinja2 condition
    template: Optional[str] = None  # Jinja2 template
    enabled: bool = True


class HeaderTransformation(BaseModel):
    """Header transformation configuration."""

    rules: List[TransformationRule] = Field(
        default_factory=list, description="Header rules"
    )
    preserve_original: bool = Field(True, description="Preserve original headers")
    blacklist: List[str] = Field(default_factory=list, description="Headers to remove")
    whitelist: Optional[List[str]] = Field(None, description="Only allow these headers")


class BodyTransformation(BaseModel):
    """Body transformation configuration."""

    input_format: Optional[ContentType] = Field(
        None, description="Expected input format"
    )
    output_format: Optional[ContentType] = Field(
        None, description="Target output format"
    )
    schema_validation: bool = Field(False, description="Enable schema validation")
    schema_path: Optional[str] = Field(None, description="JSON schema file path")
    transformation_template: Optional[str] = Field(
        None, description="Jinja2 transformation template"
    )
    rules: List[TransformationRule] = Field(
        default_factory=list, description="Body transformation rules"
    )
    max_size_bytes: int = Field(10 * 1024 * 1024, description="Maximum body size")


class RequestTransformationConfig(BaseModel):
    """Request transformation configuration."""

    name: str = Field(..., description="Configuration name")
    path_patterns: List[str] = Field(..., description="URL path patterns to match")
    methods: List[str] = Field(
        default_factory=lambda: ["*"], description="HTTP methods to match"
    )
    headers: HeaderTransformation = Field(
        default_factory=HeaderTransformation, description="Header transformations"
    )
    query_params: List[TransformationRule] = Field(
        default_factory=list, description="Query parameter rules"
    )
    body: BodyTransformation = Field(
        default_factory=BodyTransformation, description="Body transformations"
    )
    priority: int = Field(0, description="Rule priority (higher = first)")
    enabled: bool = Field(True, description="Enable this configuration")


class ResponseTransformationConfig(BaseModel):
    """Response transformation configuration."""

    name: str = Field(..., description="Configuration name")
    status_codes: List[int] = Field(
        default_factory=lambda: [200], description="Status codes to match"
    )
    path_patterns: List[str] = Field(..., description="URL path patterns to match")
    headers: HeaderTransformation = Field(
        default_factory=HeaderTransformation, description="Header transformations"
    )
    body: BodyTransformation = Field(
        default_factory=BodyTransformation, description="Body transformations"
    )
    cache_control: Optional[str] = Field(None, description="Cache-Control header value")
    compression: bool = Field(False, description="Enable response compression")
    priority: int = Field(0, description="Rule priority (higher = first)")
    enabled: bool = Field(True, description="Enable this configuration")


class RequestTransformer:
    """Handles request transformations."""

    def __init__(self, config_path: Optional[str] = None):
        """Initialize request transformer.

        Args:
            config_path: Path to transformation configuration file
        """
        self.configs: List[RequestTransformationConfig] = []
        self.custom_transformers: Dict[str, Callable] = {}

        if config_path:
            self.load_config(config_path)
        else:
            self._load_default_config()

    def load_config(self, config_path: str):
        """Load transformation configuration from file."""
        try:
            config_file = Path(config_path)
            if config_file.exists():
                with open(config_file, "r") as f:
                    if config_file.suffix.lower() == ".yaml":
                        config_data = yaml.safe_load(f)
                    else:
                        config_data = json.load(f)

                self.configs = [
                    RequestTransformationConfig(**config)
                    for config in config_data.get("request_transformations", [])
                ]
            else:
                logger.warning(f"Config file not found: {config_path}")
                self._load_default_config()

        except Exception as e:
            logger.error(f"Failed to load transformation config: {e}")
            self._load_default_config()

    def _load_default_config(self):
        """Load default transformation configurations."""
        self.configs = [
            # Add standard headers
            RequestTransformationConfig(
                name="add_standard_headers",
                path_patterns=["/**"],
                headers=HeaderTransformation(
                    rules=[
                        TransformationRule(
                            name="add_request_id",
                            action=TransformationAction.ADD,
                            target="X-Request-ID",
                            template="{{ request_id }}",
                        ),
                        TransformationRule(
                            name="add_timestamp",
                            action=TransformationAction.ADD,
                            target="X-Request-Timestamp",
                            template="{{ timestamp }}",
                        ),
                        TransformationRule(
                            name="remove_internal_headers",
                            action=TransformationAction.REMOVE,
                            target="X-Internal-*",
                        ),
                    ]
                ),
                priority=1,
            ),
            # API versioning
            RequestTransformationConfig(
                name="api_versioning",
                path_patterns=["/api/**"],
                headers=HeaderTransformation(
                    rules=[
                        TransformationRule(
                            name="add_api_version",
                            action=TransformationAction.ADD,
                            target=API_VERSION_HEADER,
                            value=API_VERSION,
                            condition=f"'{API_VERSION_HEADER}' not in headers",
                        )
                    ]
                ),
                priority=2,
            ),
        ]

    async def transform(
        self, request: Request, headers: Dict[str, str], body: bytes
    ) -> Tuple[Dict[str, str], bytes]:
        """Transform request headers and body.

        Args:
            request: FastAPI request object
            headers: Request headers
            body: Request body

        Returns:
            Tuple of (transformed_headers, transformed_body)
        """
        try:
            # Find matching configurations
            matching_configs = self._find_matching_configs(request)

            # Transform headers
            transformed_headers = await self._transform_headers(
                request, headers, matching_configs
            )

            # Transform body
            transformed_body = await self._transform_body(
                request, body, matching_configs
            )

            return transformed_headers, transformed_body

        except Exception as e:
            logger.error(f"Request transformation error: {e}")
            # Return original on error
            return headers, body

    def _find_matching_configs(
        self, request: Request
    ) -> List[RequestTransformationConfig]:
        """Find transformation configurations that match the request."""
        matching = []

        for config in self.configs:
            if not config.enabled:
                continue

            # Check method match
            if "*" not in config.methods and request.method not in config.methods:
                continue

            # Check path patterns
            path_matches = False
            for pattern in config.path_patterns:
                if self._path_matches(request.url.path, pattern):
                    path_matches = True
                    break

            if path_matches:
                matching.append(config)

        # Sort by priority (higher first)
        matching.sort(key=lambda c: c.priority, reverse=True)
        return matching

    def _path_matches(self, path: str, pattern: str) -> bool:
        """Check if path matches pattern (supports wildcards)."""
        # Convert pattern to regex
        regex_pattern = pattern.replace("**", ".*").replace("*", "[^/]*")
        regex_pattern = f"^{regex_pattern}$"

        return bool(re.match(regex_pattern, path))

    async def _transform_headers(
        self,
        request: Request,
        headers: Dict[str, str],
        configs: List[RequestTransformationConfig],
    ) -> Dict[str, str]:
        """Transform request headers."""
        transformed = headers.copy()

        # Context for template rendering
        context = {
            "headers": headers,
            "method": request.method,
            "path": request.url.path,
            "query": dict(request.query_params),
            "request_id": getattr(request.state, "request_id", "unknown"),
            "timestamp": datetime.utcnow().isoformat(),
        }

        for config in configs:
            for rule in config.headers.rules:
                if not rule.enabled:
                    continue

                # Check condition
                if rule.condition and not self._evaluate_condition(
                    rule.condition, context
                ):
                    continue

                # Apply transformation
                await self._apply_header_rule(rule, transformed, context)

            # Apply blacklist/whitelist
            if config.headers.blacklist:
                for header_pattern in config.headers.blacklist:
                    self._remove_headers_by_pattern(transformed, header_pattern)

            if config.headers.whitelist:
                allowed_headers = {}
                for header_name, header_value in transformed.items():
                    if any(
                        self._header_matches(header_name, pattern)
                        for pattern in config.headers.whitelist
                    ):
                        allowed_headers[header_name] = header_value
                transformed = allowed_headers

        return transformed

    async def _apply_header_rule(
        self, rule: TransformationRule, headers: Dict[str, str], context: Dict[str, Any]
    ):
        """Apply a single header transformation rule."""
        if rule.action == TransformationAction.ADD:
            value = self._render_template(rule.template or rule.value, context)
            headers[rule.target] = value

        elif rule.action == TransformationAction.REMOVE:
            self._remove_headers_by_pattern(headers, rule.target)

        elif rule.action == TransformationAction.REPLACE:
            if rule.target in headers:
                value = self._render_template(rule.template or rule.value, context)
                headers[rule.target] = value

        elif rule.action == TransformationAction.APPEND:
            if rule.target in headers:
                value = self._render_template(rule.template or rule.value, context)
                headers[rule.target] += f", {value}"
            else:
                value = self._render_template(rule.template or rule.value, context)
                headers[rule.target] = value

        elif rule.action == TransformationAction.PREPEND:
            if rule.target in headers:
                value = self._render_template(rule.template or rule.value, context)
                headers[rule.target] = f"{value}, {headers[rule.target]}"
            else:
                value = self._render_template(rule.template or rule.value, context)
                headers[rule.target] = value

    async def _transform_body(
        self, request: Request, body: bytes, configs: List[RequestTransformationConfig]
    ) -> bytes:
        """Transform request body."""
        if not body:
            return body

        current_body = body

        for config in configs:
            if not config.body.rules:
                continue

            try:
                # Detect content type
                content_type = request.headers.get("content-type", "").split(";")[0]

                # Check size limit
                if len(current_body) > config.body.max_size_bytes:
                    logger.warning(
                        f"Body size {len(current_body)} exceeds limit {config.body.max_size_bytes}"
                    )
                    continue

                # Parse body based on content type
                parsed_body = self._parse_body(current_body, content_type)

                # Apply transformations
                if isinstance(parsed_body, dict):
                    transformed_data = await self._transform_json_body(
                        parsed_body, config.body.rules
                    )
                else:
                    transformed_data = parsed_body

                # Convert back to bytes
                current_body = self._serialize_body(transformed_data, content_type)

            except Exception as e:
                logger.error(f"Body transformation error: {e}")
                continue

        return current_body

    def _parse_body(self, body: bytes, content_type: str) -> Any:
        """Parse request body based on content type."""
        try:
            body_str = body.decode("utf-8")

            if content_type == ContentType.JSON:
                return json.loads(body_str)
            elif content_type == ContentType.XML:
                if xmltodict:
                    return xmltodict.parse(body_str)
                else:
                    logger.warning("xmltodict not available, returning raw string")
                    return body_str
            elif content_type == ContentType.FORM:
                # Parse form data
                import urllib.parse

                return dict(urllib.parse.parse_qsl(body_str))
            else:
                return body_str

        except Exception as e:
            logger.error(f"Failed to parse body: {e}")
            return body.decode("utf-8", errors="ignore")

    def _serialize_body(self, data: Any, content_type: str) -> bytes:
        """Serialize data back to bytes."""
        try:
            if content_type == ContentType.JSON:
                return json.dumps(data, ensure_ascii=False).encode("utf-8")
            elif content_type == ContentType.XML:
                if isinstance(data, dict) and dicttoxml:
                    return dicttoxml.dicttoxml(data, custom_root="root")
                else:
                    return str(data).encode("utf-8")
            elif content_type == ContentType.FORM:
                if isinstance(data, dict):
                    import urllib.parse

                    return urllib.parse.urlencode(data).encode("utf-8")
                else:
                    return str(data).encode("utf-8")
            else:
                return str(data).encode("utf-8")

        except Exception as e:
            logger.error(f"Failed to serialize body: {e}")
            return str(data).encode("utf-8")

    async def _transform_json_body(
        self, data: Dict[str, Any], rules: List[TransformationRule]
    ) -> Dict[str, Any]:
        """Transform JSON body using rules."""
        transformed = data.copy()

        for rule in rules:
            if not rule.enabled:
                continue

            try:
                # JSON path operations
                if rule.action == TransformationAction.ADD:
                    self._set_json_path(transformed, rule.target, rule.value)
                elif rule.action == TransformationAction.REMOVE:
                    self._delete_json_path(transformed, rule.target)
                elif rule.action == TransformationAction.REPLACE:
                    if self._get_json_path(transformed, rule.target) is not None:
                        self._set_json_path(transformed, rule.target, rule.value)

            except Exception as e:
                logger.error(f"JSON transformation error for rule {rule.name}: {e}")

        return transformed

    def _get_json_path(self, data: Dict[str, Any], path: str) -> Any:
        """Get value from JSON object using dot notation."""
        keys = path.split(".")
        current = data

        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None

        return current

    def _set_json_path(self, data: Dict[str, Any], path: str, value: Any):
        """Set value in JSON object using dot notation."""
        keys = path.split(".")
        current = data

        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]

        current[keys[-1]] = value

    def _delete_json_path(self, data: Dict[str, Any], path: str):
        """Delete value from JSON object using dot notation."""
        keys = path.split(".")
        current = data

        for key in keys[:-1]:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return

        if isinstance(current, dict) and keys[-1] in current:
            del current[keys[-1]]

    def _remove_headers_by_pattern(self, headers: Dict[str, str], pattern: str):
        """Remove headers matching pattern (supports wildcards)."""
        to_remove = []

        for header_name in headers.keys():
            if self._header_matches(header_name, pattern):
                to_remove.append(header_name)

        for header_name in to_remove:
            del headers[header_name]

    def _header_matches(self, header_name: str, pattern: str) -> bool:
        """Check if header name matches pattern."""
        regex_pattern = pattern.replace("*", ".*")
        regex_pattern = f"^{regex_pattern}$"

        return bool(re.match(regex_pattern, header_name, re.IGNORECASE))

    def _evaluate_condition(self, condition: str, context: Dict[str, Any]) -> bool:
        """Evaluate Jinja2 condition."""
        try:
            template = Template(f"{{{{ {condition} }}}}")
            result = template.render(**context)
            return result.lower() in ("true", "1", "yes")
        except Exception as e:
            logger.error(f"Condition evaluation error: {e}")
            return False

    def _render_template(
        self, template_str: Optional[str], context: Dict[str, Any]
    ) -> str:
        """Render Jinja2 template."""
        if not template_str:
            return ""

        try:
            template = Template(template_str)
            return template.render(**context)
        except Exception as e:
            logger.error(f"Template rendering error: {e}")
            return template_str


class ResponseTransformer:
    """Handles response transformations."""

    def __init__(self, config_path: Optional[str] = None):
        """Initialize response transformer.

        Args:
            config_path: Path to transformation configuration file
        """
        self.configs: List[ResponseTransformationConfig] = []

        if config_path:
            self.load_config(config_path)
        else:
            self._load_default_config()

    def _load_default_config(self):
        """Load default response transformation configurations."""
        self.configs = [
            # Add security headers
            ResponseTransformationConfig(
                name="security_headers",
                path_patterns=["/**"],
                status_codes=[200, 201, 202, 204],
                headers=HeaderTransformation(
                    rules=[
                        TransformationRule(
                            name="add_cors_headers",
                            action=TransformationAction.ADD,
                            target="Access-Control-Allow-Origin",
                            value="*",
                        ),
                        TransformationRule(
                            name="add_security_headers",
                            action=TransformationAction.ADD,
                            target="X-Content-Type-Options",
                            value="nosniff",
                        ),
                        TransformationRule(
                            name="remove_server_header",
                            action=TransformationAction.REMOVE,
                            target="Server",
                        ),
                    ]
                ),
                priority=1,
            ),
            # API response formatting
            ResponseTransformationConfig(
                name="api_response_format",
                path_patterns=["/api/**"],
                status_codes=[200, 201, 202],
                headers=HeaderTransformation(
                    rules=[
                        TransformationRule(
                            name="add_api_version",
                            action=TransformationAction.ADD,
                            target="X-API-Version",
                            value="v1",
                        )
                    ]
                ),
                cache_control="max-age=300",
                compression=True,
                priority=2,
            ),
        ]

    async def transform(
        self, response: httpx.Response, headers: Dict[str, str], body: bytes
    ) -> Tuple[Dict[str, str], bytes]:
        """Transform response headers and body.

        Args:
            response: HTTP response object
            headers: Response headers
            body: Response body

        Returns:
            Tuple of (transformed_headers, transformed_body)
        """
        try:
            # Find matching configurations
            matching_configs = self._find_matching_configs(response)

            # Transform headers
            transformed_headers = await self._transform_headers(
                response, headers, matching_configs
            )

            # Transform body
            transformed_body = await self._transform_body(
                response, body, matching_configs
            )

            # Apply compression if enabled
            for config in matching_configs:
                if config.compression and len(transformed_body) > 1024:
                    transformed_body = gzip.compress(transformed_body)
                    transformed_headers["Content-Encoding"] = "gzip"
                    break

            return transformed_headers, transformed_body

        except Exception as e:
            logger.error(f"Response transformation error: {e}")
            return headers, body

    def _find_matching_configs(
        self, response: httpx.Response
    ) -> List[ResponseTransformationConfig]:
        """Find transformation configurations that match the response."""
        matching = []

        for config in self.configs:
            if not config.enabled:
                continue

            # Check status code match
            if response.status_code not in config.status_codes:
                continue

            # Check path patterns (if available from request context)
            # This would need to be passed from the gateway
            matching.append(config)

        # Sort by priority (higher first)
        matching.sort(key=lambda c: c.priority, reverse=True)
        return matching

    async def _transform_headers(
        self,
        response: httpx.Response,
        headers: Dict[str, str],
        configs: List[ResponseTransformationConfig],
    ) -> Dict[str, str]:
        """Transform response headers."""
        transformed = headers.copy()

        context = {
            "headers": headers,
            "status_code": response.status_code,
            "timestamp": datetime.utcnow().isoformat(),
        }

        for config in configs:
            # Apply header transformations
            for rule in config.headers.rules:
                if not rule.enabled:
                    continue

                if rule.condition and not self._evaluate_condition(
                    rule.condition, context
                ):
                    continue

                await self._apply_header_rule(rule, transformed, context)

            # Apply cache control
            if config.cache_control:
                transformed["Cache-Control"] = config.cache_control

        return transformed

    async def _transform_body(
        self,
        response: httpx.Response,
        body: bytes,
        configs: List[ResponseTransformationConfig],
    ) -> bytes:
        """Transform response body."""
        # Similar to request body transformation but for responses
        return body

    async def _apply_header_rule(
        self, rule: TransformationRule, headers: Dict[str, str], context: Dict[str, Any]
    ):
        """Apply header transformation rule (same as request transformer)."""
        if rule.action == TransformationAction.ADD:
            value = self._render_template(rule.template or rule.value, context)
            headers[rule.target] = value

        elif rule.action == TransformationAction.REMOVE:
            if rule.target in headers:
                del headers[rule.target]

        # Add other transformation actions as needed

    def _evaluate_condition(self, condition: str, context: Dict[str, Any]) -> bool:
        """Evaluate condition (same as request transformer)."""
        try:
            template = Template(f"{{{{ {condition} }}}}")
            result = template.render(**context)
            return result.lower() in ("true", "1", "yes")
        except:
            return False

    def _render_template(
        self, template_str: Optional[str], context: Dict[str, Any]
    ) -> str:
        """Render template (same as request transformer)."""
        if not template_str:
            return ""

        try:
            template = Template(template_str)
            return template.render(**context)
        except Exception as e:
            logger.error(f"Template rendering error: {e}")
            return template_str


# Export components
__all__ = [
    "RequestTransformer",
    "ResponseTransformer",
    "RequestTransformationConfig",
    "ResponseTransformationConfig",
    "HeaderTransformation",
    "BodyTransformation",
    "TransformationRule",
    "TransformationAction",
    "ContentType",
]
