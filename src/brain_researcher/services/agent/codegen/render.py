"""Back-compat shim: moved to services/llm_gateway/codegen/render.py."""

import sys as _sys

from brain_researcher.services.llm_gateway.codegen import render as _moved

_sys.modules[__name__] = _moved
