"""Back-compat shim: moved to services/llm_gateway/codegen/model_policy.py."""

import sys as _sys

from brain_researcher.services.llm_gateway.codegen import model_policy as _moved

_sys.modules[__name__] = _moved
