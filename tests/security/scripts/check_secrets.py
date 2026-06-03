#!/usr/bin/env python3
"""
Pre-commit hook to check for hardcoded secrets in code.

Checks for:
- API keys and tokens
- Database credentials
- JWT secrets
- Neuroimaging service credentials
"""

import argparse
import re
import sys
from pathlib import Path


class SecretChecker:
    """Check for hardcoded secrets in source code."""

    def __init__(self):
        # Patterns to detect various types of secrets
        self.secret_patterns = {
            "api_key": [
                r'api[_-]?key["\s]*[:=]["\s]*["\'][a-zA-Z0-9]{20,}["\']',
                r'apikey["\s]*[:=]["\s]*["\'][a-zA-Z0-9]{20,}["\']',
                r'key["\s]*[:=]["\s]*["\'][a-zA-Z0-9]{32,}["\']',
            ],
            "openai_key": [
                r"sk-[a-zA-Z0-9]{48}",
                r'openai[_-]?api[_-]?key["\s]*[:=]["\s]*["\']sk-[a-zA-Z0-9]+["\']',
            ],
            "database_password": [
                r'password["\s]*[:=]["\s]*["\'][^"\']{8,}["\']',
                r'db[_-]?password["\s]*[:=]["\s]*["\'][^"\']{8,}["\']',
                r'database[_-]?password["\s]*[:=]["\s]*["\'][^"\']{8,}["\']',
                r"postgresql://[^:]+:([^@]{8,})@",
                r"mysql://[^:]+:([^@]{8,})@",
            ],
            "jwt_secret": [
                r'jwt[_-]?secret["\s]*[:=]["\s]*["\'][^"\']{16,}["\']',
                r'secret[_-]?key["\s]*[:=]["\s]*["\'][^"\']{32,}["\']',
                r'signing[_-]?key["\s]*[:=]["\s]*["\'][^"\']{16,}["\']',
            ],
            "redis_password": [
                r'redis[_-]?password["\s]*[:=]["\s]*["\'][^"\']{8,}["\']',
                r"redis://:[^@]{8,}@",
            ],
            "neo4j_password": [
                r'neo4j[_-]?password["\s]*[:=]["\s]*["\'][^"\']{8,}["\']',
                r"bolt://[^:]+:([^@]{8,})@",
            ],
            "private_key": [
                r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
                r'private[_-]?key["\s]*[:=]["\s]*["\'][^"\']{100,}["\']',
            ],
            "aws_credentials": [
                r"AKIA[0-9A-Z]{16}",  # AWS Access Key ID
                r'aws[_-]?secret[_-]?access[_-]?key["\s]*[:=]',
                r'aws[_-]?access[_-]?key[_-]?id["\s]*[:=]',
            ],
        }

        # Whitelist patterns (legitimate uses that should be ignored)
        self.whitelist_patterns = [
            r'password["\s]*[:=]["\s]*["\'](<PASSWORD>|<your_password>|password|test|demo)["\']',
            r'api[_-]?key["\s]*[:=]["\s]*["\'](<API_KEY>|<your_api_key>|test_key|demo_key)["\']',
            r'secret["\s]*[:=]["\s]*["\'](<SECRET>|<your_secret>|test_secret|demo_secret)["\']',
            r"example\.com",
            r"localhost",
            r"127\.0\.0\.1",
            r"test[_-]?(key|secret|password)",
            r"demo[_-]?(key|secret|password)",
            r"placeholder",
            r"<[A-Z_]+>",  # Placeholder patterns like <API_KEY>
        ]

        # File patterns to exclude (substring match on path).
        #
        # Keep this list broad enough to avoid scanning vendored code, virtualenvs,
        # build outputs, and local caches, which create huge false-positive rates.
        self.exclude_files = {
            ".git/",
            "__pycache__/",
            ".pytest_cache/",
            ".pytest_tmp/",
            "node_modules/",
            ".venv/",
            "venv/",
            ".tox/",
            ".mypy_cache/",
            ".ruff_cache/",
            "build/",
            "dist/",
            "external/",
            "out/",
            "tmp/",
            "data/",
            ".cache/",
            ".env",
            ".env.",
            ".env.example",
            ".env.template",
            "tests/",
            "test_",
            "_test.py",
            "example",
            "template",
            "mock",
        }

    def is_whitelisted(self, line: str, file_path: Path) -> bool:
        """Check if a line matches whitelist patterns."""
        line_lower = line.lower()

        # Check file-based exclusions
        file_str = str(file_path).lower()
        for exclude in self.exclude_files:
            if exclude in file_str:
                return True

        # Check pattern-based exclusions
        for pattern in self.whitelist_patterns:
            if re.search(pattern, line_lower, re.IGNORECASE):
                return True

        return False

    def check_file(self, file_path: Path) -> list[dict]:
        """Check a single file for secrets."""
        secrets_found = []

        try:
            with open(file_path, encoding="utf-8", errors="ignore") as f:
                content = f.read()
                lines = content.split("\n")
        except Exception as e:
            return [{"error": f"Could not read file: {e}"}]

        for line_num, line in enumerate(lines, 1):
            # Skip if line is whitelisted
            if self.is_whitelisted(line, file_path):
                continue

            # Check each secret pattern
            for secret_type, patterns in self.secret_patterns.items():
                for pattern in patterns:
                    matches = re.finditer(pattern, line, re.IGNORECASE)
                    for match in matches:
                        # Extract the potential secret
                        secret_value = (
                            match.group(1) if match.groups() else match.group(0)
                        )

                        # Additional validation for common false positives
                        if self._is_likely_secret(secret_value, secret_type):
                            secrets_found.append(
                                {
                                    "file": str(file_path),
                                    "line": line_num,
                                    "type": secret_type,
                                    "pattern": pattern,
                                    "context": line.strip()[:100],  # First 100 chars
                                    "severity": self._get_severity(secret_type),
                                }
                            )

        return secrets_found

    def _is_likely_secret(self, value: str, secret_type: str) -> bool:
        """Additional validation to reduce false positives."""
        value_lower = value.lower()

        # Common test/placeholder values
        test_values = {
            "password",
            "secret",
            "test",
            "demo",
            "example",
            "placeholder",
            "your_password",
            "your_secret",
            "your_key",
            "change_me",
            "123456",
            "admin",
            "root",
            "default",
        }

        if value_lower in test_values:
            return False

        # Check for obvious placeholder patterns
        if re.match(r"^[<{]\w+[}>]$", value):  # <PASSWORD> or {SECRET}
            return False

        # Type-specific validation
        if secret_type == "api_key":
            # API keys should have sufficient entropy
            if len(value) < 20 or value.isdigit() or value.isalpha():
                return False

        elif secret_type == "database_password":
            # Database passwords should be reasonably complex
            if len(value) < 8:
                return False

        elif secret_type == "jwt_secret":
            # JWT secrets should be sufficiently long
            if len(value) < 16:
                return False

        return True

    def _get_severity(self, secret_type: str) -> str:
        """Get severity level for different secret types."""
        high_severity = {"openai_key", "api_key", "private_key", "aws_credentials"}
        medium_severity = {"database_password", "redis_password", "neo4j_password"}

        if secret_type in high_severity:
            return "HIGH"
        elif secret_type in medium_severity:
            return "MEDIUM"
        else:
            return "LOW"

    def check_multiple_files(self, file_paths: list[Path]) -> dict:
        """Check multiple files for secrets."""
        all_secrets = []
        files_with_secrets = 0

        for file_path in file_paths:
            secrets = self.check_file(file_path)
            if secrets and not any("error" in s for s in secrets):
                all_secrets.extend(secrets)
                if secrets:
                    files_with_secrets += 1

        # Summarize results
        severity_counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for secret in all_secrets:
            severity_counts[secret["severity"]] += 1

        return {
            "total_secrets": len(all_secrets),
            "files_affected": files_with_secrets,
            "severity_counts": severity_counts,
            "secrets": all_secrets,
        }


def main():
    """Main entry point for secret checking."""
    parser = argparse.ArgumentParser(description="Check for hardcoded secrets")
    parser.add_argument("files", nargs="*", help="Files to check")
    parser.add_argument("--all", action="store_true", help="Check all Python files")
    parser.add_argument("--json", action="store_true", help="Output in JSON format")
    parser.add_argument(
        "--fail-on",
        choices=["HIGH", "MEDIUM", "LOW"],
        default="HIGH",
        help="Fail on severity level",
    )

    args = parser.parse_args()

    checker = SecretChecker()

    if args.all:
        # Find all Python files
        file_paths = list(Path(".").rglob("*.py"))
        # Filter out excluded directories
        file_paths = [
            f
            for f in file_paths
            if not any(exclude in str(f) for exclude in checker.exclude_files)
        ]
    else:
        file_paths = [Path(f) for f in args.files]

    if not file_paths:
        print("No files to check")
        return 0

    results = checker.check_multiple_files(file_paths)

    if args.json:
        import json

        print(json.dumps(results, indent=2))
    else:
        # Human-readable output
        print("Secret Check Results:")
        print(f"Files checked: {len(file_paths)}")
        print(f"Files with secrets: {results['files_affected']}")
        print(f"Total secrets found: {results['total_secrets']}")
        print(f"Severity breakdown: {results['severity_counts']}")

        if results["secrets"]:
            print("\nSecrets found:")
            for secret in results["secrets"]:
                print(
                    f"  {secret['severity']}: {secret['file']}:{secret['line']} - {secret['type']}"
                )
                print(f"    Context: {secret['context']}")

    # Determine exit code based on severity
    fail_levels = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
    fail_threshold = fail_levels[args.fail_on]

    max_severity = 0
    for severity, count in results["severity_counts"].items():
        if count > 0:
            max_severity = max(max_severity, fail_levels[severity])

    if max_severity >= fail_threshold:
        print(f"\nFailing due to {args.fail_on} or higher severity secrets found")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
