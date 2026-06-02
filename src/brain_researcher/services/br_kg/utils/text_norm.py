"""Simple text normalization utilities."""

import re

_SYNONYMS = {
    "bart": "balloon analogue risk task",
    "bart task": "balloon analogue risk task task",
    "balloonanalogue risktask": "balloon analogue risk task",
    "balloon analog risk task": "balloon analogue risk task",
}

_CAMEL_RE1 = re.compile(r"(.)([A-Z][a-z]+)")
_CAMEL_RE2 = re.compile(r"([a-z0-9])([A-Z])")


def normalize_task_name(name: str) -> str:
    """Normalize task names for matching."""
    if not name:
        return ""
    lowered = name.replace("_", " ").replace("-", " ")
    lowered = _CAMEL_RE1.sub(r"\1 \2", lowered)
    lowered = _CAMEL_RE2.sub(r"\1 \2", lowered)
    lowered = lowered.lower()
    lowered = " ".join(lowered.split())
    return _SYNONYMS.get(lowered, lowered)
