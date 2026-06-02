"""Back-compat shim: atlas helpers moved to services/shared."""

import sys as _sys

from brain_researcher.services.shared import atlas_utils as _moved

_sys.modules[__name__] = _moved
