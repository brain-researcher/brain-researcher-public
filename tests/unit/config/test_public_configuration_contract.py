from __future__ import annotations

import json
import re
import subprocess
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
HELM_TEMPLATE_PREFIX = "infrastructure/k8s/helm/brain-researcher/templates/"
DECLARATIVE_SUFFIXES = {".json", ".yaml", ".yml", ".toml"}


class _ConfigLoader(yaml.SafeLoader):
    """Safe YAML loader with the two application tags used by this repository."""


def _construct_compose_reset(
    loader: _ConfigLoader, node: yaml.Node
) -> Any:
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return loader.construct_scalar(node)


def _construct_python_name(
    _loader: _ConfigLoader, suffix: str, _node: yaml.Node
) -> str:
    return suffix


_ConfigLoader.add_constructor("!reset", _construct_compose_reset)
_ConfigLoader.add_multi_constructor(
    "tag:yaml.org,2002:python/name:", _construct_python_name
)


def _tracked_relpaths() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    return [path for path in result.stdout.decode().split("\0") if path]


def _is_declarative(relpath: str) -> bool:
    return Path(relpath).suffix.lower() in DECLARATIVE_SUFFIXES


def _is_env_template(relpath: str) -> bool:
    name = Path(relpath).name
    return name.startswith(".env") and (
        name.endswith("example") or name.endswith("template")
    )


def _is_helm_source_template(relpath: str) -> bool:
    return relpath.startswith(HELM_TEMPLATE_PREFIX) and Path(relpath).suffix in {
        ".yaml",
        ".yml",
    }


def _parse_documents(relpath: str) -> list[Any]:
    text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
    suffix = Path(relpath).suffix.lower()
    if suffix == ".json":
        return [json.loads(text)]
    if suffix in {".yaml", ".yml"}:
        return list(yaml.load_all(text, Loader=_ConfigLoader))
    if suffix == ".toml":
        return [tomllib.loads(text)]
    raise AssertionError(f"unsupported declarative suffix: {relpath}")


def test_all_tracked_json_yaml_and_toml_parse() -> None:
    failures: list[str] = []
    for relpath in _tracked_relpaths():
        if not _is_declarative(relpath) or _is_helm_source_template(relpath):
            continue
        try:
            _parse_documents(relpath)
        except (json.JSONDecodeError, tomllib.TOMLDecodeError, yaml.YAMLError) as exc:
            failures.append(f"{relpath}::{type(exc).__name__}")

    assert not failures, "Unparseable tracked configuration:\n" + "\n".join(
        sorted(failures)
    )


def test_yaml_parser_exclusion_is_limited_to_helm_go_templates() -> None:
    excluded = [
        relpath
        for relpath in _tracked_relpaths()
        if _is_helm_source_template(relpath)
    ]
    assert excluded
    for relpath in excluded:
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        assert "{{" in text, f"Excluded file is not a Go template: {relpath}"


_SECRET_EXACT_KEYS = {
    "api_key",
    "client_secret",
    "password",
    "passwd",
    "private_key",
    "secret",
    "secret_access_key",
    "secret_key",
    "token",
}
_SECRET_KEY_SUFFIXES = (
    "_api_key",
    "_auth_token",
    "_client_secret",
    "_password",
    "_passwd",
    "_private_key",
    "_secret",
    "_secret_access_key",
    "_secret_key",
    "_session_token",
    "_token",
)
_IDENTIFIER_KEYS = {
    "api_key_env",
    "auth_token_env",
    "existing_secret",
    "password_key",
    "secret_name",
    "token_env",
}
_IDENTIFIER_CONTEXTS = {
    "annotations",
    "keys",
    "labels",
    "optional_keys",
    "required_keys",
    "secret_key_ref",
}
_IDENTIFIER_PATHS = {
    ("agent", "freesurfer_license", "secret_key"),
    ("mcp", "freesurfer_license", "secret_key"),
}
_PLACEHOLDER = re.compile(
    r"^(?:<[^>\n]+>|(?:your|replace|change[-_]?me|changeme|placeholder|"
    r"example|test|demo|dev|local)(?:[-_ ].*)?)$",
    re.IGNORECASE,
)
_NAMED_TEMPLATE = re.compile(
    r"^\{\{?\s*[A-Za-z_][A-Za-z0-9_.]*\s*\}?\}$"
)
_ENV_REFERENCE = re.compile(r"^\$\{([A-Z][A-Z0-9_]*)(?::-([^}]*))?\}$")
_SPECIAL_REFERENCE = re.compile(
    r"^(?:env:[A-Z][A-Z0-9_]*|os\.environ/[A-Z][A-Z0-9_]*|"
    r"\$__\w+\{[^}\n]+\})$"
)
_HIGH_CONFIDENCE_SECRET_PATTERNS = {
    "aws-access-key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "credentialed-dsn": re.compile(
        r"(?i)\b(?:postgres(?:ql)?|mysql|mariadb|redis|neo4j|bolt)://"
        r"[^\s:/]+:[^\s@/]+@"
    ),
    "github-token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "google-api-key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "openai-token": re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    "private-key": re.compile(
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"
    ),
    "slack-token": re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{20,}\b"),
}


def _normalize_key(key: str) -> str:
    snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
    return re.sub(r"[^A-Za-z0-9]+", "_", snake).strip("_").lower()


def _is_sensitive_key(key: str) -> bool:
    normalized = _normalize_key(key)
    return normalized in _SECRET_EXACT_KEYS or normalized.endswith(
        _SECRET_KEY_SUFFIXES
    )


def _is_explicit_placeholder_or_reference(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False

    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {
        "'",
        '"',
    }:
        stripped = stripped[1:-1].strip()
    if not stripped or _PLACEHOLDER.fullmatch(stripped):
        return True
    if _NAMED_TEMPLATE.fullmatch(stripped) or _SPECIAL_REFERENCE.fullmatch(stripped):
        return True

    env_match = _ENV_REFERENCE.fullmatch(stripped)
    if env_match is None:
        return False
    default = env_match.group(2)
    return default is None or not default or bool(_PLACEHOLDER.fullmatch(default))


def _walk_sensitive_values(
    value: Any, chain: tuple[str, ...] = ()
) -> Iterator[tuple[tuple[str, ...], Any]]:
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key)
            normalized_key = _normalize_key(key)
            normalized_context = {_normalize_key(part) for part in chain}
            child_chain = (*chain, key)
            normalized_chain = tuple(_normalize_key(part) for part in child_chain)
            is_identifier = (
                normalized_key in _IDENTIFIER_KEYS
                or bool(normalized_context & _IDENTIFIER_CONTEXTS)
                or normalized_chain in _IDENTIFIER_PATHS
            )
            if (
                _is_sensitive_key(key)
                and not is_identifier
                and not isinstance(child, dict | list)
            ):
                yield child_chain, child
            yield from _walk_sensitive_values(child, child_chain)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_sensitive_values(child, (*chain, str(index)))


def _detected_secret_paths(value: Any) -> set[str]:
    return {
        ".".join(chain)
        for chain, secret_value in _walk_sensitive_values(value)
        if not _is_explicit_placeholder_or_reference(secret_value)
    }


def test_secret_detector_catches_values_without_flagging_key_identifiers() -> None:
    unsafe = {
        "password": "correct-horse-battery-staple",
        "secret_key": "runtime-signing-material-12345",
        "token": "opaque-runtime-credential-12345",
    }
    assert _detected_secret_paths(unsafe) == {"password", "secret_key", "token"}

    identifier_contract = {
        "existingSecret": "operator-provided-secret",
        "passwordKey": "POSTGRES_PASSWORD",
        "valueFrom": {
            "secretKeyRef": {
                "name": "operator-provided-secret",
                "key": "API_TOKEN",
            }
        },
        "keys": {"jwtSecret": "JWT_SECRET"},
        "agent": {"freesurferLicense": {"secretKey": "license.txt"}},
        "mcp": {"freesurferLicense": {"secretKey": "license.txt"}},
    }
    assert not _detected_secret_paths(identifier_contract)


def _config_secret_violations(relpath: str) -> list[str]:
    if not (
        relpath.startswith("configs/")
        or relpath.startswith("infrastructure/")
        or relpath == "litellm_config.yaml"
    ):
        return []

    violations: list[str] = []
    for document in _parse_documents(relpath):
        if not isinstance(document, dict):
            continue
        if document.get("kind") == "Secret":
            for field in ("data", "stringData"):
                payload = document.get(field) or {}
                if not isinstance(payload, dict):
                    violations.append(f"{relpath}::{field}")
                    continue
                for key, value in payload.items():
                    if value not in {None, ""}:
                        violations.append(f"{relpath}::{field}.{key}")
            continue

        for chain, value in _walk_sensitive_values(document):
            if not _is_explicit_placeholder_or_reference(value):
                violations.append(f"{relpath}::{'.'.join(chain)}")
    return violations


def _env_secret_violations(relpath: str) -> list[str]:
    violations: list[str] = []
    text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if _is_sensitive_key(key) and not _is_explicit_placeholder_or_reference(
            value
        ):
            violations.append(f"{relpath}::{key}")
    return violations


def test_public_configurations_do_not_ship_credentials() -> None:
    violations: list[str] = []
    for relpath in _tracked_relpaths():
        if _is_declarative(relpath) and not _is_helm_source_template(relpath):
            text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
            for secret_kind, pattern in _HIGH_CONFIDENCE_SECRET_PATTERNS.items():
                if pattern.search(text):
                    violations.append(f"{relpath}::<{secret_kind}>")
            violations.extend(_config_secret_violations(relpath))
        elif _is_env_template(relpath):
            violations.extend(_env_secret_violations(relpath))

    assert not violations, "Credential-bearing public configuration keys:\n" + "\n".join(
        sorted(set(violations))
    )
