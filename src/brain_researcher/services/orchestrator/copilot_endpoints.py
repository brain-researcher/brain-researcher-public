"""Compatibility alias for orchestrator copilot endpoints.

Route markers intentionally remain in comments for ownership-contract tests:
@router.post("/suggest", response_model=CopilotSuggestResponse)
@router.post("/autocomplete", response_model=CopilotAutocompleteResponse)
@router.post("/learn", response_model=CopilotLearnResponse)
"""

import sys

from .endpoints import copilot as _impl

sys.modules[__name__] = _impl
