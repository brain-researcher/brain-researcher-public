#!/usr/bin/env python
"""Generate test summary for neuroimaging tools."""

import subprocess
import os
from pathlib import Path
import pytest

test_dir = Path(__file__).resolve().parents[1] / "unit/agent/tools"

if not test_dir.exists():
    pytest.skip(f"Tool test directory not found: {test_dir}", allow_module_level=True)

results = []
for test_file in sorted(test_dir.glob("test_*.py")):
    tool_name = test_file.stem.replace("test_", "")
    
    # Run pytest quietly and capture output
    cmd = f"python -m pytest {test_file} -q --tb=no 2>/dev/null"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    
    # Parse output
    output = result.stdout
    if "passed" in output:
        # Extract pass/fail counts
        import re
        match = re.search(r"(\d+) failed.*?(\d+) passed", output)
        if match:
            failed = int(match.group(1))
            passed = int(match.group(2))
        else:
            match = re.search(r"(\d+) passed", output)
            if match:
                passed = int(match.group(1))
                failed = 0
            else:
                continue
        
        total = passed + failed
        if failed == 0:
            status = "✅"
        else:
            status = "⚠️"
        
        results.append((status, tool_name, passed, total, failed))

# Print summary
print("\n=== NEUROIMAGING TOOLS TEST SUMMARY ===\n")
total_passed = 0
total_tests = 0

for status, name, passed, total, failed in results:
    total_passed += passed
    total_tests += total
    if failed == 0:
        print(f"{status} {name:20s}: {passed:3d}/{total:3d} tests passing (100%)")
    else:
        pct = int(100 * passed / total)
        print(f"{status} {name:20s}: {passed:3d}/{total:3d} tests passing ({pct}%, {failed} failed)")

print(f"\n{'='*50}")
if total_tests == 0:
    print("TOTAL: 0/0 tests passing (no tool tests discovered)")
else:
    print(f"TOTAL: {total_passed}/{total_tests} tests passing ({int(100*total_passed/total_tests)}%)")
print(f"{'='*50}")
