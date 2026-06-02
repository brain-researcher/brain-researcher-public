"""Back-compat shim: moved to services/llm_gateway/codegen/fs_context.py."""

import sys as _sys

from brain_researcher.services.llm_gateway.codegen import fs_context as _moved

_sys.modules[__name__] = _moved
