"""Back-compat shim: metrics collector moved to services/telemetry.

Existing ``brain_researcher.services.agent.monitoring.metrics_collector``
imports keep resolving, including private names. New code should import from
``brain_researcher.services.telemetry.metrics_collector``.
"""

import sys as _sys

from brain_researcher.services.telemetry import metrics_collector as _moved

_sys.modules[__name__] = _moved
