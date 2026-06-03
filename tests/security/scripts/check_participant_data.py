#!/usr/bin/env python3
"""
Pre-commit hook to check for potential participant data exposure.

Checks for:
- Participant/subject identifier exposure in logs
- Medical data in error messages
- Unencrypted participant data storage
- Missing anonymization in data handling functions
"""

import argparse
import re
import sys
from pathlib import Path


class ParticipantDataChecker:
    """Check for potential participant data exposure in code."""

    def __init__(self):
        # Patterns that might indicate participant data exposure
        self.exposure_patterns = {
            "logging_participant_id": [
                r"log.*\(.*participant[_-]?id.*\)",
                r"logger\.[a-z]+.*\(.*participant[_-]?id.*\)",
                r"print.*\(.*participant[_-]?id.*\)",
                r"console\.log.*\(.*participant[_-]?id.*\)",
            ],
            "logging_subject_id": [
                r"log.*\(.*subject[_-]?id.*\)",
                r"logger\.[a-z]+.*\(.*subject[_-]?id.*\)",
                r"print.*\(.*subject[_-]?id.*\)",
            ],
            "error_with_participant_data": [
                r"raise\s+\w*Error.*\(.*participant.*\)",
                r"raise\s+\w*Error.*\(.*subject.*\)",
                r"throw\s+new\s+Error.*\(.*participant.*\)",
                r"Exception.*\(.*participant.*\)",
            ],
            "medical_data_in_logs": [
                r"log.*\(.*medical.*\)",
                r"print.*\(.*diagnosis.*\)",
                r"log.*\(.*patient.*\)",
                r"console\.log.*\(.*medical.*\)",
            ],
            "unencrypted_storage": [
                r"pickle\.dump.*\(.*participant.*\)",
                r"json\.dump.*\(.*participant.*\)",
                r"csv\.write.*\(.*participant.*\)",
                r"open.*\(.*participant.*\.txt.*\)",
            ],
            "database_exposure": [
                r"SELECT.*participant[_-]?id.*FROM",
                r"INSERT.*participant[_-]?id.*VALUES",
                r"UPDATE.*participant[_-]?id.*SET",
                r"WHERE.*participant[_-]?id.*=",
            ],
        }

        # Patterns for functions that should include anonymization
        self.anonymization_patterns = [
            r"def\s+(\w*participant\w*)\s*\([^)]*participant[_-]?id[^)]*\):",
            r"def\s+(\w*subject\w*)\s*\([^)]*subject[_-]?id[^)]*\):",
            r"def\s+(\w*process\w*data\w*)\s*\([^)]*participant[^)]*\):",
            r"def\s+(\w*export\w*)\s*\([^)]*participant[^)]*\):",
        ]

        # Patterns that indicate proper anonymization/pseudonymization
        self.good_patterns = [
            r"anonymize\(",
            r"pseudonymize\(",
            r"hash\(",
            r"encrypt\(",
            r"de_identify\(",
            r"remove_identifiers\(",
            r"participant[_-]?hash",
            r"subject[_-]?hash",
            r"pseudonym",
        ]

        # File extensions to check
        self.check_extensions = {".py", ".js", ".ts", ".sql"}

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
        """Check a single file for participant data exposure."""
        if not self.should_check_file(file_path):
            return []

        issues = []

        try:
            with open(file_path, encoding="utf-8", errors="ignore") as f:
                content = f.read()
                lines = content.split("\n")
        except Exception as e:
            return [{"error": f"Could not read file: {e}"}]

        # Check for exposure patterns
        for line_num, line in enumerate(lines, 1):
            for issue_type, patterns in self.exposure_patterns.items():
                for pattern in patterns:
                    if re.search(pattern, line, re.IGNORECASE):
                        # Check if this line also has good practices
                        has_good_practice = any(
                            re.search(good_pattern, line, re.IGNORECASE)
                            for good_pattern in self.good_patterns
                        )

                        if not has_good_practice:
                            issues.append(
                                {
                                    "file": str(file_path),
                                    "line": line_num,
                                    "type": issue_type,
                                    "severity": self._get_severity(issue_type),
                                    "context": line.strip(),
                                    "recommendation": self._get_recommendation(
                                        issue_type
                                    ),
                                }
                            )

        # Check for functions handling participant data without anonymization
        function_issues = self._check_function_anonymization(content, file_path)
        issues.extend(function_issues)

        return issues

    def _check_function_anonymization(
        self, content: str, file_path: Path
    ) -> list[dict]:
        """Check if functions handling participant data include anonymization."""
        issues = []

        for pattern in self.anonymization_patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE)

            for match in matches:
                function_name = match.group(1)
                start_pos = match.start()

                # Get the function body (simplified - look for next function or class)
                function_end = self._find_function_end(content, start_pos)
                function_body = content[start_pos:function_end]

                # Check if function body contains anonymization practices
                has_anonymization = any(
                    re.search(good_pattern, function_body, re.IGNORECASE)
                    for good_pattern in self.good_patterns
                )

                if not has_anonymization:
                    line_num = content[:start_pos].count("\n") + 1
                    issues.append(
                        {
                            "file": str(file_path),
                            "line": line_num,
                            "type": "missing_anonymization",
                            "severity": "MEDIUM",
                            "context": f"Function {function_name} handles participant data",
                            "recommendation": "Add proper data anonymization/pseudonymization before processing",
                        }
                    )

        return issues

    def _find_function_end(self, content: str, start_pos: int) -> int:
        """Find the approximate end of a function (simplified)."""
        # Look for the next function or class definition, or end of file
        next_def = re.search(r"\n(?:def|class)\s+", content[start_pos + 100 :])
        if next_def:
            return start_pos + 100 + next_def.start()
        else:
            # Look ahead 2000 characters or end of file
            return min(start_pos + 2000, len(content))

    def _get_severity(self, issue_type: str) -> str:
        """Get severity level for different issue types."""
        high_severity = {
            "logging_participant_id",
            "logging_subject_id",
            "error_with_participant_data",
            "database_exposure",
        }
        medium_severity = {
            "medical_data_in_logs",
            "unencrypted_storage",
            "missing_anonymization",
        }

        if issue_type in high_severity:
            return "HIGH"
        elif issue_type in medium_severity:
            return "MEDIUM"
        else:
            return "LOW"

    def _get_recommendation(self, issue_type: str) -> str:
        """Get specific recommendation for each issue type."""
        recommendations = {
            "logging_participant_id": "Avoid logging participant IDs directly. Use hashed/pseudonymized identifiers.",
            "logging_subject_id": "Avoid logging subject IDs directly. Use hashed/pseudonymized identifiers.",
            "error_with_participant_data": "Remove participant data from error messages. Use generic error codes.",
            "medical_data_in_logs": "Avoid logging medical data. Use anonymized references or codes.",
            "unencrypted_storage": "Encrypt participant data before storage or use anonymized datasets.",
            "database_exposure": "Use parameterized queries and avoid direct ID exposure.",
            "missing_anonymization": "Add proper data anonymization before processing participant data.",
        }
        return recommendations.get(
            issue_type, "Review code for participant data protection."
        )

    def check_multiple_files(self, file_paths: list[Path]) -> dict:
        """Check multiple files for participant data issues."""
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
    """Main entry point for participant data checking."""
    parser = argparse.ArgumentParser(
        description="Check for participant data exposure in code"
    )
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

    checker = ParticipantDataChecker()

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
        print("Participant Data Security Check Results:")
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
                print(f"    Context: {issue['context'][:100]}...")
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
