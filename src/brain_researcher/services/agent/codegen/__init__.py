"""Back-compat shim package: codegen moved to services/llm_gateway/codegen."""

import sys as _sys

from brain_researcher.services.llm_gateway import codegen as _moved

_sys.modules[__name__] = _moved
