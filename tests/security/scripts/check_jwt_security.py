#!/usr/bin/env python3
"""
Pre-commit hook to check JWT implementation security.

Checks for:
- Weak JWT secrets
- Missing token expiration
- Algorithm confusion vulnerabilities
- Insecure token storage
- Missing signature verification
"""

import argparse
import re
import sys
from pathlib import Path


class JWTSecurityChecker:
    """Check JWT implementation security in code."""

    def __init__(self):
        # Patterns for JWT security issues
        self.security_patterns = {
            "weak_secret": [
                r'jwt\.encode\([^,]+,\s*["\']([^"\']{1,16})["\']',  # Short secrets
                r'jwt\.encode\([^,]+,\s*["\']((secret|password|key|test|admin|123|abc))["\']',  # Common weak secrets
                r'SECRET_KEY\s*=\s*["\']([^"\']{1,16})["\']',  # Short secret keys
            ],
            "no_expiration": [
                r"jwt\.encode\([^}]+\}[^,]*,[^)]+\)",  # JWT encode without checking for 'exp'
                r"jwt\.encode\(\s*\{[^}]*\}[^,]*,[^)]*\)",  # More specific pattern
            ],
            "algorithm_none": [
                r'jwt\.encode\([^,]+,[^,]+,\s*algorithm\s*=\s*["\']none["\']',
                r'jwt\.decode\([^,]+,[^,]+,\s*algorithms\s*=\s*\[["\']none["\']\]',
            ],
            "no_algorithm_verification": [
                r"jwt\.decode\([^,]+,[^,]+,\s*verify\s*=\s*False",
                r'jwt\.decode\([^,]+,[^,]+,\s*options\s*=\s*\{["\']verify_signature["\']\s*:\s*False\}',
            ],
            "insecure_storage": [
                r'localStorage\.setItem\(["\'].*[tT]oken["\'][^)]*\)',  # JWT in localStorage
                r'sessionStorage\.setItem\(["\'].*[tT]oken["\'][^)]*\)',  # JWT in sessionStorage
                r'document\.cookie\s*=\s*["\'].*[tT]oken["\']',  # JWT in regular cookie
            ],
            "token_in_logs": [
                r"log.*\([^)]*[tT]oken[^)]*\)",
                r"print.*\([^)]*[tT]oken[^)]*\)",
                r"console\.log.*\([^)]*[tT]oken[^)]*\)",
            ],
            "hardcoded_tokens": [
                r'["\']eyJ[A-Za-z0-9+/=]{20,}["\']',  # Base64-encoded JWT pattern
            ],
            "missing_audience": [
                r"jwt\.decode\([^,]+,[^,]+[^)]*\)",  # JWT decode without audience check
            ],
        }

        # Patterns that indicate good JWT practices
        self.good_patterns = [
            r'exp["\']?\s*:\s*',  # Expiration claim
            r'iat["\']?\s*:\s*',  # Issued at claim
            r'nbf["\']?\s*:\s*',  # Not before claim
            r'aud["\']?\s*:\s*',  # Audience claim
            r'verify_signature["\']?\s*:\s*True',
            r'algorithms\s*=\s*\[["\'][HS]S?\d{3}["\']',  # Specific algorithms
            r"Secure[;,]",  # Secure cookie flag
            r"HttpOnly[;,]",  # HttpOnly cookie flag
            r"SameSite[;,]",  # SameSite cookie flag
        ]

        # File extensions to check
        self.check_extensions = {".py", ".js", ".ts", ".jsx", ".tsx"}

        # Directories/files to exclude
        self.exclude_patterns = {
            "test",
            "tests",
            "example",
            "examples",
            "demo",
            "docs",
            "__pycache__",
            "node_modules",
            ".git",
            "external",
        }

    def should_check_file(self, file_path: Path) -> bool:
        """Determine if file should be checked."""
        # Check extension
        if file_path.suffix not in self.check_extensions:
            return False

        # Check for excluded patterns
        file_str = str(file_path).lower()
        for exclude in self.exclude_patterns:
            if exclude in file_str:
                return False

        return True

    def check_file(self, file_path: Path) -> list[dict]:
        """Check a single file for JWT security issues."""
        if not self.should_check_file(file_path):
            return []

        issues = []

        try:
            with open(file_path, encoding="utf-8", errors="ignore") as f:
                content = f.read()
                lines = content.split("\n")
        except Exception as e:
            return [{"error": f"Could not read file: {e}"}]

        # Check for JWT security issues
        for line_num, line in enumerate(lines, 1):
            self._check_line_for_issues(line, line_num, file_path, issues)

        # Check for missing expiration in JWT encode calls
        self._check_jwt_encode_expiration(content, file_path, issues)

        return issues

    def _check_line_for_issues(
        self, line: str, line_num: int, file_path: Path, issues: list[dict]
    ):
        """Check a single line for JWT security issues."""
        for issue_type, patterns in self.security_patterns.items():
            for pattern in patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    # Special handling for different issue types
                    if issue_type == "weak_secret" and match.groups():
                        secret_value = match.group(1)
                        if not self._is_weak_secret(secret_value):
                            continue

                    # Check if line has compensating good practices
                    if issue_type in ["no_algorithm_verification", "missing_audience"]:
                        if any(
                            re.search(good_pattern, line, re.IGNORECASE)
                            for good_pattern in self.good_patterns
                        ):
                            continue

                    issues.append(
                        {
                            "file": str(file_path),
                            "line": line_num,
                            "type": issue_type,
                            "severity": self._get_severity(issue_type),
                            "context": line.strip()[:150],
                            "recommendation": self._get_recommendation(issue_type),
                        }
                    )

    def _check_jwt_encode_expiration(
        self, content: str, file_path: Path, issues: list[dict]
    ):
        """Check JWT encode calls for missing expiration."""
        # Find all JWT encode calls
        jwt_encode_pattern = r"jwt\.encode\s*\(\s*(\{[^}]+\})\s*,[^)]+\)"
        matches = re.finditer(jwt_encode_pattern, content, re.MULTILINE | re.DOTALL)

        for match in matches:
            payload = match.group(1)

            # Check if payload includes expiration
            if not re.search(r'["\']?exp["\']?\s*:', payload, re.IGNORECASE):
                line_num = content[: match.start()].count("\n") + 1
                issues.append(
                    {
                        "file": str(file_path),
                        "line": line_num,
                        "type": "missing_expiration",
                        "severity": "HIGH",
                        "context": match.group(0)[:150],
                        "recommendation": "Add expiration (exp) claim to JWT payload",
                    }
                )

    def _is_weak_secret(self, secret: str) -> bool:
        """Check if a JWT secret is weak."""
        # Too short
        if len(secret) < 16:
            return True

        # Common weak secrets
        weak_secrets = {
            "secret",
            "password",
            "key",
            "test",
            "admin",
            "demo",
            "123456",
            "abc123",
            "password123",
            "secret123",
            "qwerty",
            "admin123",
            "test123",
        }

        if secret.lower() in weak_secrets:
            return True

        # All same character
        if len(set(secret)) == 1:
            return True

        # Sequential or predictable patterns
        if secret.lower() in ["abcdefghijklmnop", "1234567890123456"]:
            return True

        return False

    def _get_severity(self, issue_type: str) -> str:
        """Get severity level for different JWT issue types."""
        high_severity = {
            "weak_secret",
            "algorithm_none",
            "no_algorithm_verification",
            "missing_expiration",
            "hardcoded_tokens",
        }
        medium_severity = {"insecure_storage", "token_in_logs", "missing_audience"}

        if issue_type in high_severity:
            return "HIGH"
        elif issue_type in medium_severity:
            return "MEDIUM"
        else:
            return "LOW"

    def _get_recommendation(self, issue_type: str) -> str:
        """Get specific recommendation for each JWT issue type."""
        recommendations = {
            "weak_secret": "Use a strong, randomly generated secret key (at least 256 bits/32 characters)",
            "missing_expiration": "Add expiration (exp) claim to JWT tokens to prevent token reuse",
            "algorithm_none": 'Never use "none" algorithm for JWT tokens - use HS256 or RS256',
            "no_algorithm_verification": "Always verify JWT signatures - do not disable signature verification",
            "insecure_storage": "Store JWT tokens in secure HttpOnly cookies, not localStorage/sessionStorage",
            "token_in_logs": "Do not log JWT tokens or include them in error messages",
            "hardcoded_tokens": "Do not hardcode JWT tokens in source code - use environment variables",
            "missing_audience": "Include and verify audience (aud) claim in JWT tokens",
        }
        return recommendations.get(
            issue_type, "Review JWT implementation for security best practices"
        )

    def check_multiple_files(self, file_paths: list[Path]) -> dict:
        """Check multiple files for JWT security issues."""
        all_issues = []
        files_with_issues = 0

        for file_path in file_paths:
            issues = self.check_file(file_path)
            if issues and not any("error" in issue for issue in issues):
                all_issues.extend(issues)
                if issues:
                    files_with_issues += 1

        # Summarize results
        severity_counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
        issue_types = {}

        for issue in all_issues:
            severity_counts[issue["severity"]] += 1
            issue_type = issue["type"]
            issue_types[issue_type] = issue_types.get(issue_type, 0) + 1

        return {
            "total_issues": len(all_issues),
            "files_affected": files_with_issues,
            "severity_counts": severity_counts,
            "issue_types": issue_types,
            "issues": all_issues,
        }


def main():
    """Main entry point for JWT security checking."""
    parser = argparse.ArgumentParser(description="Check JWT implementation security")
    parser.add_argument("files", nargs="*", help="Files to check")
    parser.add_argument("--all", action="store_true", help="Check all relevant files")
    parser.add_argument("--json", action="store_true", help="Output in JSON format")
    parser.add_argument(
        "--fail-on",
        choices=["HIGH", "MEDIUM", "LOW"],
        default="HIGH",
        help="Fail on severity level",
    )

    args = parser.parse_args()

    checker = JWTSecurityChecker()

    if args.all:
        # Find all relevant files
        file_paths = []
        for ext in checker.check_extensions:
            file_paths.extend(Path(".").rglob(f"*{ext}"))

        # Filter out excluded directories
        file_paths = [f for f in file_paths if checker.should_check_file(f)]
    else:
        file_paths = [Path(f) for f in args.files if Path(f).exists()]

    if not file_paths:
        print("No files to check")
        return 0

    results = checker.check_multiple_files(file_paths)

    if args.json:
        import json

        print(json.dumps(results, indent=2))
    else:
        # Human-readable output
        print("JWT Security Check Results:")
        print(f"Files checked: {len(file_paths)}")
        print(f"Files with issues: {results['files_affected']}")
        print(f"Total issues found: {results['total_issues']}")
        print(f"Severity breakdown: {results['severity_counts']}")

        if results["issue_types"]:
            print(f"Issue types: {results['issue_types']}")

        if results["issues"]:
            print("\nIssues found:")
            for issue in results["issues"]:
                print(
                    f"  {issue['severity']}: {issue['file']}:{issue['line']} - {issue['type']}"
                )
                print(f"    Context: {issue['context']}")
                print(f"    Recommendation: {issue['recommendation']}")

    # Determine exit code based on severity
    fail_levels = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
    fail_threshold = fail_levels[args.fail_on]

    max_severity = 0
    for severity, count in results["severity_counts"].items():
        if count > 0:
            max_severity = max(max_severity, fail_levels[severity])

    if max_severity >= fail_threshold:
        print(f"\nFailing due to {args.fail_on} or higher severity issues found")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
