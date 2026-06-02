"""Back-compat shim: Gemini fallback moved to services/llm_gateway.

Existing ``brain_researcher.services.agent.utils.gemini_fallback`` imports keep
resolving, including private test helpers. New code should import from
``brain_researcher.services.llm_gateway.gemini_fallback``.
"""

import sys as _sys

from brain_researcher.services.llm_gateway import gemini_fallback as _moved

_sys.modules[__name__] = _moved
