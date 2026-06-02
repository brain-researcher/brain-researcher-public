"""Back-compat shim: moved to services/llm_gateway/codegen/loop.py."""

import sys as _sys

from brain_researcher.services.llm_gateway.codegen import loop as _moved

_sys.modules[__name__] = _moved
