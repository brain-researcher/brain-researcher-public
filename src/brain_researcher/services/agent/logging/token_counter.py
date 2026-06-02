"""Back-compat shim: this module moved to services/llm_gateway. Re-exported via
module aliasing so existing `brain_researcher.services.agent.token_counter`-style imports
keep resolving (including private names). New code should import from
`brain_researcher.services.llm_gateway`."""

import sys as _sys

from brain_researcher.services.llm_gateway import token_counter as _moved

_sys.modules[__name__] = _moved
