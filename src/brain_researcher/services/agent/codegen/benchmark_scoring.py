"""Back-compat shim: moved to services/llm_gateway/codegen/benchmark_scoring.py."""

import sys as _sys

from brain_researcher.services.llm_gateway.codegen import benchmark_scoring as _moved

_sys.modules[__name__] = _moved
