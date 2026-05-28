"""
Testing framework with Tester, StaticAnalyst, and Supervisor roles.

This module provides a comprehensive testing system that includes:
- Automated test execution (Tester)
- Code quality analysis (StaticAnalyst)
- Test orchestration and reporting (Supervisor)
"""

from .runner import TestRunner
from .static_analyst import StaticAnalyst
from .supervisor import Supervisor
from .tester import Tester

__all__ = ["Tester", "StaticAnalyst", "Supervisor", "TestRunner"]
