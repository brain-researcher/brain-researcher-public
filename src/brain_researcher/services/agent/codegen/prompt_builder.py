"""Back-compat shim: moved to services/llm_gateway/codegen/prompt_builder.py."""

import sys as _sys

from brain_researcher.services.llm_gateway.codegen import prompt_builder as _moved

_sys.modules[__name__] = _moved
