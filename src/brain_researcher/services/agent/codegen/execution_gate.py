"""Back-compat shim: moved to services/llm_gateway/codegen/execution_gate.py."""

import sys as _sys

from brain_researcher.services.llm_gateway.codegen import execution_gate as _moved

_sys.modules[__name__] = _moved
