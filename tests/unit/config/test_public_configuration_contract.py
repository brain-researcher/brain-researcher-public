from __future__ import annotations

import json
import re
import shlex
import subprocess
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
HELM_TEMPLATE_PREFIX = "infrastructure/k8s/helm/brain-researcher/templates/"
DECLARATIVE_SUFFIXES = {".json", ".jsonl", ".yaml", ".yml", ".toml"}


class _ConfigLoader(yaml.SafeLoader):
    """Safe YAML loader with the two application tags used by this repository."""

    def construct_mapping(
        self, node: yaml.MappingNode, deep: bool = False
    ) -> dict[Any, Any]:
        seen: dict[Any, yaml.Node] = {}
        for key_node, _value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"duplicate key: {key}",
                    key_node.start_mark,
                )
            seen[key] = key_node
        return super().construct_mapping(node, deep=deep)


class _DuplicateJsonKeyError(ValueError):
    pass


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError(f"duplicate key: {key}")
        result[key] = value
    return result


def _strict_json_lines(text: str) -> list[Any]:
    documents: list[Any] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            documents.append(
                json.loads(line, object_pairs_hook=_strict_json_object)
            )
        except (json.JSONDecodeError, _DuplicateJsonKeyError) as exc:
            raise _DuplicateJsonKeyError(
                f"JSONL line {line_number}: {exc}"
            ) from exc
    return documents


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
        return [json.loads(text, object_pairs_hook=_strict_json_object)]
    if suffix == ".jsonl":
        return _strict_json_lines(text)
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
        except (
            json.JSONDecodeError,
            _DuplicateJsonKeyError,
            tomllib.TOMLDecodeError,
            yaml.YAMLError,
        ) as exc:
            problem = getattr(exc, "problem", None) or type(exc).__name__
            failures.append(f"{relpath}::{problem}")

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


def test_declarative_loaders_reject_duplicate_mapping_keys() -> None:
    with pytest.raises(_DuplicateJsonKeyError, match="duplicate key: mode"):
        json.loads(
            '{"mode": "first", "mode": "second"}',
            object_pairs_hook=_strict_json_object,
        )

    with pytest.raises(yaml.constructor.ConstructorError, match="duplicate key: mode"):
        yaml.load("mode: first\nmode: second\n", Loader=_ConfigLoader)

    with pytest.raises(_DuplicateJsonKeyError, match="JSONL line 2.*duplicate key"):
        _strict_json_lines('{"mode": "first"}\n{"mode": 1, "mode": 2}\n')

    for payload in (
        "true: first\nTrue: second\n",
        "1: first\n01: second\n",
        "null: first\nNull: second\n",
    ):
        with pytest.raises(yaml.constructor.ConstructorError, match="duplicate key"):
            yaml.load(payload, Loader=_ConfigLoader)


_SECRET_EXACT_KEYS = {
    "access_key",
    "access_key_id",
    "api_key",
    "client_secret",
    "master_key",
    "neo4j_auth",
    "password",
    "passwd",
    "private_key",
    "secret",
    "secret_access_key",
    "secret_key",
    "token",
}
_SECRET_KEY_SUFFIXES = (
    "_access_key",
    "_access_key_id",
    "_api_key",
    "_auth_token",
    "_client_secret",
    "_master_key",
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
_IDENTIFIER_CONTAINERS = {
    "keys",
    "optional_keys",
    "required_keys",
}
_ANNOTATION_IDENTIFIER_SUFFIXES = ("_auth_secret", "_secret_name")
_IDENTIFIER_PATHS = {
    ("agent", "freesurfer_license", "secret_key"),
    ("mcp", "freesurfer_license", "secret_key"),
}
_PLACEHOLDER = re.compile(
    r"^(?:<[^>\n]+>|(?:your|replace|change[-_]?me|changeme|placeholder|"
    r"example)(?:[-_ ].*)?|test|demo|dev|local)$",
    re.IGNORECASE,
)
_NAMED_TEMPLATE = re.compile(
    r"^\{\{?\s*[A-Za-z_][A-Za-z0-9_.]*\s*\}?\}$"
)
_GO_TEMPLATE = re.compile(r"^\{\{[^{}\n]+\}\}$")
_ENV_REFERENCE = re.compile(
    r"^\$\{([A-Z][A-Z0-9_]*)(?:(:?[-?])([^}]*))?\}$"
)
_ENV_INTERPOLATION = re.compile(
    r"\$\{([A-Z][A-Z0-9_]*)(?:(:?[-?])([^}]*))?\}"
)
_NESTED_REQUIRED_ENV_FALLBACK = re.compile(
    r"^\$\{[A-Z][A-Z0-9_]*:-\$\{[A-Z][A-Z0-9_]*(?::?\?)[^{}]*\}\}$"
)
_KEY_IDENTIFIER = re.compile(r"^[A-Z][A-Z0-9_.-]*$")
_SENSITIVE_HEADER_REFERENCE = re.compile(
    r"^request\.headers\[[^\]]*(?:authorization|api[-_]?key|token|secret)[^\]]*\]$",
    re.IGNORECASE,
)
_HEADER_POLICY_WILDCARDS = {"Bearer *"}
_SPECIAL_REFERENCE = re.compile(
    r"^(?:env:[A-Z][A-Z0-9_]*|os\.environ/[A-Z][A-Z0-9_]*|"
    r"\$__\w+\{[^}\n]+\})$"
)
_NEO4J_AUTH_REFERENCE = re.compile(
    r"^[^/\s]+/\$\{[A-Z][A-Z0-9_]*(?::?\?)[^{}]*\}$"
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
    "sql-role-password": re.compile(
        r"(?is)\b(?:CREATE|ALTER)\s+ROLE\b[^;]*\bPASSWORD\s+'[^']+'"
    ),
    "pgbouncer-user-hash": re.compile(
        r'(?m)^\s*"[^"]+"\s+"md5[0-9A-Za-z]+"\s*$'
    ),
}
_KNOWN_CREDENTIAL_MARKERS = (
    "DemoPass123!",
    "admin-secret-token",
    "dev-telemetry-token",
    "sk-br-local",
    "_pass_change_me",
)
_RUNTIME_CONFIG_SUFFIXES = {".conf", ".ini", ".sql", ".txt"}


def _normalize_key(key: str) -> str:
    snake = (
        key
        if not any(character.islower() for character in key)
        else re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
    )
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
    if (
        _NAMED_TEMPLATE.fullmatch(stripped)
        or _GO_TEMPLATE.fullmatch(stripped)
        or _SPECIAL_REFERENCE.fullmatch(stripped)
        or _NESTED_REQUIRED_ENV_FALLBACK.fullmatch(stripped)
        or _NEO4J_AUTH_REFERENCE.fullmatch(stripped)
    ):
        return True

    env_match = _ENV_REFERENCE.fullmatch(stripped)
    if env_match is None:
        return False
    operator = env_match.group(2)
    operand = env_match.group(3)
    if operator is None or operator in {"?", ":?"}:
        return True
    return not (operand or "").strip()


def _walk_sensitive_values(
    value: Any, chain: tuple[str, ...] = ()
) -> Iterator[tuple[tuple[str, ...], Any]]:
    if isinstance(value, dict):
        header_reference = value.get("key")
        header_values = value.get("values")
        if (
            isinstance(header_reference, str)
            and _SENSITIVE_HEADER_REFERENCE.fullmatch(header_reference.strip())
            and isinstance(header_values, list)
        ):
            for index, header_value in enumerate(header_values):
                if header_value not in _HEADER_POLICY_WILDCARDS:
                    yield (*chain, "values", str(index)), header_value

        for raw_key, child in value.items():
            key = str(raw_key)
            normalized_key = _normalize_key(key)
            child_chain = (*chain, key)
            normalized_chain = tuple(_normalize_key(part) for part in child_chain)
            parent = _normalize_key(chain[-1]) if chain else None
            is_identifier = (
                normalized_key in _IDENTIFIER_KEYS
                or normalized_chain in _IDENTIFIER_PATHS
                or (
                    parent == "annotations"
                    and normalized_key.endswith(_ANNOTATION_IDENTIFIER_SUFFIXES)
                )
                or (
                    parent in _IDENTIFIER_CONTAINERS
                    and isinstance(child, str)
                    and bool(_KEY_IDENTIFIER.fullmatch(child.strip()))
                )
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
            item_chain = (*chain, str(index))
            if isinstance(child, str) and "=" in child:
                key, assignment = child.split("=", 1)
                if _is_sensitive_key(key):
                    yield (*item_chain, key), assignment
            yield from _walk_sensitive_values(child, item_chain)


def _detected_secret_paths(value: Any) -> set[str]:
    return {
        ".".join(chain)
        for chain, secret_value in _walk_sensitive_values(value)
        if not _is_explicit_placeholder_or_reference(secret_value)
    }


def _iter_string_leaves(
    value: Any, chain: tuple[str, ...]
) -> Iterator[tuple[tuple[str, ...], str]]:
    if isinstance(value, str):
        yield chain, value
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _iter_string_leaves(child, (*chain, str(index)))
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from _iter_string_leaves(child, (*chain, str(key)))


_LONG_SECRET_FLAG = re.compile(
    r"^--(?:auth|bearer[-_]?token|credentials?|password|passwd|token|"
    r"api[-_]?key|secret|master[-_]?key)(?:=(.*))?$",
    re.IGNORECASE,
)


def _contains_literal_secret_flag(value: Any) -> bool:
    tokens: list[str] = []
    for _chain, text in _iter_string_leaves(value, ()):
        try:
            tokens.extend(shlex.split(text))
        except ValueError:
            tokens.append(text)

    for index, token in enumerate(tokens):
        long_flag = _LONG_SECRET_FLAG.fullmatch(token)
        if long_flag:
            attached_value = long_flag.group(1)
            if attached_value is not None:
                return bool(attached_value)
            return index + 1 < len(tokens)
        if token in {"-p", "-P"} and index + 1 < len(tokens):
            # Numeric ``-p`` values are conventionally ports (for example psql).
            # A non-numeric value is credential material in supported clients such
            # as cypher-shell and must not be embedded in container argv.
            if index > 0 and tokens[index - 1] == "mkdir":
                continue
            return not tokens[index + 1].isdigit()
    return False


def _process_argv_secret_paths(
    value: Any, chain: tuple[str, ...] = ()
) -> set[str]:
    findings: set[str] = set()
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key)
            child_chain = (*chain, key)
            normalized_key = _normalize_key(key)
            parent = _normalize_key(chain[-1]) if chain else None
            is_process_argv = normalized_key in {"command", "entrypoint"} or (
                parent == "healthcheck" and normalized_key == "test"
            )
            if is_process_argv:
                for leaf_chain, text in _iter_string_leaves(child, child_chain):
                    for match in _ENV_INTERPOLATION.finditer(text):
                        if _is_sensitive_key(match.group(1)):
                            findings.add(".".join(leaf_chain))
                if _contains_literal_secret_flag(child):
                    findings.add(".".join(child_chain) + "<literal-secret-flag>")
            findings.update(_process_argv_secret_paths(child, child_chain))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.update(
                _process_argv_secret_paths(child, (*chain, str(index)))
            )
    return findings


def test_secret_detector_catches_values_without_flagging_key_identifiers() -> None:
    unsafe = {
        "password": "correct-horse-battery-staple",
        "secret_key": "runtime-signing-material-12345",
        "token": "opaque-runtime-credential-12345",
        "annotations": {"token": "annotation-runtime-credential-12345"},
        "keys": {"password": "lowercase-runtime-credential-12345"},
        "environment": ["SERVICE_TOKEN=embedded-runtime-credential-12345"],
        "runtime": [
            "LITELLM_MASTER_KEY=arbitrary-real-secret-value",
            "NEO4J_AUTH=neo4j/arbitrary-real-password",
        ],
    }
    assert _detected_secret_paths(unsafe) == {
        "annotations.token",
        "keys.password",
        "environment.0.SERVICE_TOKEN",
        "password",
        "runtime.0.LITELLM_MASTER_KEY",
        "runtime.1.NEO4J_AUTH",
        "secret_key",
        "token",
    }
    assert not _is_explicit_placeholder_or_reference(
        "local-real-production-secret-12345"
    )
    assert _is_explicit_placeholder_or_reference("local")
    assert _is_explicit_placeholder_or_reference("${TOKEN:?Set TOKEN}")
    assert not _is_explicit_placeholder_or_reference(
        "${TOKEN:-local-real-production-secret-12345}"
    )
    assert _is_explicit_placeholder_or_reference(
        "${TOKEN:-${FALLBACK_TOKEN:?set FALLBACK_TOKEN}}"
    )
    assert _is_explicit_placeholder_or_reference(
        "neo4j/${NEO4J_PASSWORD:?set NEO4J_PASSWORD}"
    )

    header_policy = {
        "when": [
            {
                "key": "request.headers[x-admin-token]",
                "values": ["opaque-runtime-token-12345"],
            }
        ]
    }
    assert _detected_secret_paths(header_policy) == {"when.0.values.0"}
    assert not _detected_secret_paths(
        {
            "when": [
                {
                    "key": "request.headers[authorization]",
                    "values": ["Bearer *"],
                }
            ]
        }
    )
    assert _process_argv_secret_paths(
        {
            "services": {
                "database": {
                    "healthcheck": {
                        "test": ["CMD-SHELL", "client -p ${DB_PASSWORD:?required}"]
                    }
                }
            }
        }
    ) == {
        "services.database.healthcheck.test.1",
        "services.database.healthcheck.test<literal-secret-flag>",
    }
    assert _process_argv_secret_paths(
        {"command": ["client", "--password", "arbitrary-real-secret"]}
    ) == {"command<literal-secret-flag>"}
    assert _process_argv_secret_paths(
        {"healthcheck": {"test": ["CMD", "client", "-p", "arbitrary-real-secret"]}}
    ) == {"healthcheck.test<literal-secret-flag>"}
    assert _process_argv_secret_paths(
        {"entrypoint": "client --token arbitrary-real-secret"}
    ) == {"entrypoint<literal-secret-flag>"}
    assert _process_argv_secret_paths(
        {"entrypoint": "client --credential arbitrary-real-secret"}
    ) == {"entrypoint<literal-secret-flag>"}
    assert not _process_argv_secret_paths(
        {"healthcheck": {"test": ["CMD-SHELL", "psql -p 6432 -c 'SELECT 1'"]}}
    )

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
        "metadata": {
            "annotations": {
                "nginx.ingress.kubernetes.io/auth-secret": "monitoring-basic-auth"
            }
        },
    }
    assert not _detected_secret_paths(identifier_contract)

    assert _helm_literal_secret_violations(
        "templates/example.yaml",
        "password: arbitrary-real-secret\nAuthorization: 'Bearer literal-token'\n",
    ) == [
        "templates/example.yaml:1:password",
        "templates/example.yaml:2:Authorization",
    ]
    assert not _helm_literal_secret_violations(
        "templates/example.yaml",
        "password: {{ .Values.password | quote }}\n"
        "Authorization: 'Bearer {{ .Values.token }}'\n",
    )
    assert _helm_literal_secret_violations(
        "templates/deployment.yaml",
        "env:\n"
        "  - name: DATABASE_PASSWORD\n"
        "    value: arbitrary-real-secret\n"
        'headers: {Authorization: "Bearer arbitrary-real-token"}\n'
        "auth: arbitrary-real-auth\n",
    ) == [
        "templates/deployment.yaml:3:DATABASE_PASSWORD",
        "templates/deployment.yaml:4:Authorization",
        "templates/deployment.yaml:5:auth",
    ]
    assert not _helm_literal_secret_violations(
        "templates/deployment.yaml",
        "env:\n"
        "  - name: DATABASE_PASSWORD\n"
        "    valueFrom:\n"
        "      secretKeyRef:\n"
        "        name: database-secret\n"
        "        key: password\n",
    )
    assert _helm_literal_secret_violations(
        "templates/deployment.yaml",
        "env:\n"
        '  - name: "DATABASE_PASSWORD"\n'
        "    value: arbitrary-real-secret\n",
    ) == ["templates/deployment.yaml:3:DATABASE_PASSWORD"]
    assert _runtime_text_secret_violations(
        "runtime.conf",
        "password = arbitrary-real-secret\n"
        "admin_password: another-real-secret\n"
        "token=opaque-real-token\n",
    ) == [
        "runtime.conf:1:password",
        "runtime.conf:2:admin_password",
        "runtime.conf:3:token",
    ]
    assert _runtime_text_secret_violations(
        "runtime.conf", '"password" = arbitrary-real-secret\n'
    ) == ["runtime.conf:1:password"]
    assert not _runtime_text_secret_violations(
        "runtime.conf",
        "password = ${DB_PASSWORD:?set DB_PASSWORD}\ntoken=\n",
    )


def _config_secret_violations(relpath: str) -> list[str]:
    if not (
        relpath.startswith("configs/")
        or relpath.startswith("infrastructure/")
        or relpath.startswith("docker-compose")
        or relpath == "litellm_config.yaml"
    ):
        return []

    violations: list[str] = []
    text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
    for match in _ENV_INTERPOLATION.finditer(text):
        key, operator, operand = match.groups()
        if (
            _is_sensitive_key(key)
            and operator in {"-", ":-"}
            and (operand or "").strip()
            and not re.fullmatch(
                r"\$\{[A-Z][A-Z0-9_]*(?::?\?)[^{}]*",
                (operand or "").strip(),
            )
        ):
            violations.append(f"{relpath}::<env-default:{key}>")

    if _is_helm_source_template(relpath):
        violations.extend(_helm_literal_secret_violations(relpath, text))
        return violations

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

        for process_path in _process_argv_secret_paths(document):
            violations.append(f"{relpath}::{process_path}<secret-in-process-argv>")

        violations.extend(_embedded_yaml_secret_violations(relpath, document))
    return violations


_HELM_KEY_VALUE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*:\s*(.*?)\s*$")
_HELM_BEARER_TEMPLATE = re.compile(r"^Bearer\s+\{\{[^{}\n]+\}\}$")
_HELM_ENV_NAME = re.compile(
    r"^\s*-\s*name\s*:\s*(?P<quote>['\"]?)(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?P=quote)\s*$"
)
_HELM_INLINE_PAIR = re.compile(
    r"(?P<key>authorization|[A-Za-z0-9_.-]*(?:password|token|api[-_]?key|"
    r"secret|master[-_]?key)[A-Za-z0-9_.-]*)\s*:\s*"
    r"(?P<value>\"[^\"]*\"|'[^']*'|[^,}]+)",
    re.IGNORECASE,
)
_HELM_FLOW_MAPPING = re.compile(r"(?<!\{)\{(?!\{).*?(?<!\})\}(?!\})")
_SENSITIVE_HEADER_NAME = re.compile(
    r"^(?:authorization|[^\s]*(?:api[-_]?key|token|secret)[^\s]*)$",
    re.IGNORECASE,
)


def _normalized_helm_value(raw_value: str) -> str:
    value = raw_value.split(" #", maxsplit=1)[0].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1].strip()
    return value


def _is_helm_secret_surface(raw_key: str) -> bool:
    return (
        _is_sensitive_key(raw_key)
        or _normalize_key(raw_key) == "auth"
        or bool(_SENSITIVE_HEADER_NAME.fullmatch(raw_key))
    )


def _is_safe_helm_secret_value(value: str) -> bool:
    return _is_explicit_placeholder_or_reference(value) or bool(
        _HELM_BEARER_TEMPLATE.fullmatch(value)
    )


def _helm_literal_secret_violations(relpath: str, text: str) -> list[str]:
    """Catch literal credential values without pretending to parse Go templates."""
    violations: list[str] = []
    pending_env: tuple[int, str] | None = None
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())

        if pending_env is not None:
            pending_indent, env_name = pending_env
            if stripped.startswith("value:"):
                value = _normalized_helm_value(stripped.split(":", maxsplit=1)[1])
                if not _is_safe_helm_secret_value(value):
                    violations.append(f"{relpath}:{line_number}:{env_name}")
                pending_env = None
            elif stripped.startswith("valueFrom:"):
                pending_env = None
            elif stripped and indent <= pending_indent:
                pending_env = None

        env_match = _HELM_ENV_NAME.match(line)
        if env_match is not None and _is_sensitive_key(env_match.group("name")):
            pending_env = (indent, env_match.group("name"))

        match = _HELM_KEY_VALUE.match(line)
        if match is not None:
            raw_key, raw_value = match.groups()
            value = _normalized_helm_value(raw_value)
            if _is_helm_secret_surface(raw_key) and not _is_safe_helm_secret_value(
                value
            ):
                violations.append(f"{relpath}:{line_number}:{raw_key}")

        for flow_mapping in _HELM_FLOW_MAPPING.finditer(line):
            for inline_match in _HELM_INLINE_PAIR.finditer(flow_mapping.group()):
                raw_key = inline_match.group("key")
                value = _normalized_helm_value(inline_match.group("value"))
                if not _is_safe_helm_secret_value(value):
                    finding = f"{relpath}:{line_number}:{raw_key}"
                    if finding not in violations:
                        violations.append(finding)
    return violations


def _embedded_yaml_secret_violations(
    relpath: str, value: Any, chain: tuple[str, ...] = ()
) -> list[str]:
    violations: list[str] = []
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key)
            child_chain = (*chain, key)
            if (
                isinstance(child, str)
                and "\n" in child
                and Path(key).suffix.lower() in {".yaml", ".yml"}
            ):
                try:
                    embedded_documents = list(
                        yaml.load_all(child, Loader=_ConfigLoader)
                    )
                except yaml.YAMLError:
                    violations.append(
                        f"{relpath}::{'.'.join(child_chain)}.<invalid-embedded-yaml>"
                    )
                else:
                    for document in embedded_documents:
                        for secret_chain, secret_value in _walk_sensitive_values(
                            document, child_chain
                        ):
                            if not _is_explicit_placeholder_or_reference(secret_value):
                                violations.append(
                                    f"{relpath}::{'.'.join(secret_chain)}"
                                )
            violations.extend(
                _embedded_yaml_secret_violations(relpath, child, child_chain)
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            violations.extend(
                _embedded_yaml_secret_violations(
                    relpath, child, (*chain, str(index))
                )
            )
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


_RUNTIME_SECRET_ASSIGNMENT = re.compile(
    r"^\s*(?:export\s+|set\s+)?(?P<quote>['\"]?)"
    r"(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)(?P=quote)\s*(?:=|:)\s*"
    r"(?P<value>.*?)\s*$"
)


def _runtime_text_secret_violations(relpath: str, text: str) -> list[str]:
    violations: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";", "--")):
            continue
        match = _RUNTIME_SECRET_ASSIGNMENT.match(line)
        if match is None:
            continue
        key = match.group("key")
        value = match.group("value")
        value = value.split(" #", maxsplit=1)[0].strip()
        if _is_sensitive_key(key) and not _is_explicit_placeholder_or_reference(
            value
        ):
            violations.append(f"{relpath}:{line_number}:{key}")
    return violations


def test_public_configurations_do_not_ship_credentials() -> None:
    violations: list[str] = []
    for relpath in _tracked_relpaths():
        is_runtime_text = relpath.startswith("infrastructure/") and (
            Path(relpath).suffix.lower() in _RUNTIME_CONFIG_SUFFIXES
        )
        if _is_declarative(relpath) or is_runtime_text:
            text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
            for secret_kind, pattern in _HIGH_CONFIDENCE_SECRET_PATTERNS.items():
                if pattern.search(text):
                    violations.append(f"{relpath}::<{secret_kind}>")
            for marker in _KNOWN_CREDENTIAL_MARKERS:
                if marker in text:
                    violations.append(f"{relpath}::<known-credential-marker>")
            if _is_declarative(relpath):
                violations.extend(_config_secret_violations(relpath))
            if is_runtime_text:
                violations.extend(_runtime_text_secret_violations(relpath, text))
        elif _is_env_template(relpath):
            violations.extend(_env_secret_violations(relpath))

    assert not violations, "Credential-bearing public configuration keys:\n" + "\n".join(
        sorted(set(violations))
    )


def test_compose_security_defaults_are_explicit() -> None:
    root = _parse_documents("docker-compose.yml")[0]
    for service in root["services"].values():
        for published_port in service.get("ports", []):
            assert str(published_port).startswith(
                "${BIND_ADDRESS:-127.0.0.1}:"
            )

    web_environment = root["services"]["web-ui"]["environment"]
    assert "ENABLE_DEV_CREDENTIALS=${ENABLE_DEV_CREDENTIALS:-0}" in web_environment
    assert "DEV_CREDENTIALS_EMAIL=${DEV_CREDENTIALS_EMAIL:-}" in web_environment
    assert "DEV_CREDENTIALS_PASSWORD=${DEV_CREDENTIALS_PASSWORD:-}" in web_environment

    cc = _parse_documents("docker-compose.cc-stack.yml")[0]
    for service in cc["services"].values():
        for published_port in service.get("ports", []):
            assert str(published_port).startswith(
                "${BIND_ADDRESS:-127.0.0.1}:"
            )
    assert (
        "LITELLM_MASTER_KEY=${LITELLM_MASTER_KEY:?set LITELLM_MASTER_KEY}"
        in cc["services"]["litellm"]["environment"]
    )
    litellm = _parse_documents("litellm_config.yaml")[0]
    assert litellm["general_settings"]["master_key"] == (
        "os.environ/LITELLM_MASTER_KEY"
    )

    neo4j_services = (
        ("docker-compose.yml", "neo4j", "NEO4J_PASSWORD"),
        ("docker-compose.prod.yml", "neo4j", "NEO4J_PASSWORD"),
        (
            "infrastructure/docker/compose/docker-compose.override.test.yml",
            "neo4j-test",
            "TEST_NEO4J_PASSWORD",
        ),
    )
    for relpath, service_name, password_variable in neo4j_services:
        document = _parse_documents(relpath)[0]
        service = document["services"][service_name]
        healthcheck = json.dumps(service["healthcheck"]["test"])
        assert "PASSWORD" not in healthcheck
        assert '"-p"' not in healthcheck
        assert any(
            entry.startswith("NEO4J_PASSWORD=${")
            and password_variable in entry
            and ":?" in entry
            for entry in service["environment"]
        )


def test_unshipped_cc_overlay_is_not_advertised_as_runnable() -> None:
    overlay_path = REPO_ROOT / "docker-compose.cc-stack.yml"
    overlay_text = overlay_path.read_text(encoding="utf-8")
    env_text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    overlay = _parse_documents("docker-compose.cc-stack.yml")[0]

    assert "EXPERIMENTAL / NOT RUNNABLE FROM A PUBLIC CLONE" in overlay_text
    assert "./br-stream-proxy" in overlay_text
    assert not (REPO_ROOT / "br-stream-proxy").exists()
    assert "docker compose -f docker-compose.yml -f docker-compose.cc-stack.yml up" not in (
        overlay_text + env_text
    )
    assert "not runnable from a" in env_text
    assert "public clone because" in env_text
    assert "networks" not in overlay
    assert all("networks" not in service for service in overlay["services"].values())
