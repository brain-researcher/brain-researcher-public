"""NSQUALL — a v0 controlled-English frontend for ``ClaimSpecV1``.

This is the one remaining *spec-only* society layer (see
``docs/specs/br_society_implementation_status.md`` and the HTML "形式层" /
NSQUALL section). It is a **strict, deterministic grammar parser**, NOT free-form
NLP and NOT an LLM call: a claim written in a FIXED Controlled-English grammar is
compiled into a :class:`~brain_researcher.autoresearch.society.cards.ClaimSpecV1`,
the same object :func:`neuroclaim_compile` consumes.

The grammar (the only surface accepted in v0)::

    CLAIM <ID>:
      In <population> <modality>, the <region phrase> is associated with <term phrase>.
      SCOPE population=<p> modality=<m> datasets=<d1,d2,...> workflow=<wf>.
      [CONFIRMATORY|EXPLORATORY] [allowing <alt1>, <alt2>, ...] [null=<constraint>].
      [SUCCESS <text>.]   # optional
      [FAILURE <text>.]   # optional

Design contract:

* **Strict + helpful** — any grammar violation raises :class:`NsquallSyntaxError`
  with line/clause context. A malformed claim fails loudly; it never silently
  produces a wrong ``ClaimSpecV1``.
* **Deterministic** — the same input maps to the same ``ClaimSpecV1`` every time.
* The first sentence is preserved verbatim as ``claim_text`` AND parsed into a
  ``(region, term)`` relation, stored under ``extra["relation"]`` so the
  reverse-inference guard in :func:`neuroclaim_compile` can fire downstream for a
  region->term claim.

Pure stdlib (``re`` / ``dataclasses``) plus the existing society models. No new
dependencies, no LLM, no network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .cards import ClaimSpecV1, ScopeBoundaryV1

__all__ = [
    "NsquallSyntaxError",
    "ParsedRelation",
    "parse_nsquall",
    "compile_nsquall",
]


class NsquallSyntaxError(ValueError):
    """Raised on any NSQUALL grammar violation.

    Carries optional ``line`` / ``clause`` context so the offending location is
    obvious. The message always describes *what* was expected and *where*.
    """

    def __init__(self, message: str, *, line: int | None = None, clause: str | None = None):
        self.base_message = message
        self.line = line
        self.clause = clause
        prefix_parts: list[str] = []
        if line is not None:
            prefix_parts.append(f"line {line}")
        if clause:
            prefix_parts.append(f"clause {clause!r}")
        prefix = f"[{', '.join(prefix_parts)}] " if prefix_parts else ""
        super().__init__(f"{prefix}{message}")


@dataclass(frozen=True)
class ParsedRelation:
    """The ``associates(region=..., term=...)`` relation parsed from sentence 1."""

    region: str
    term: str
    verb: str

    def as_dict(self) -> dict[str, str]:
        return {"predicate": "associates", "region": self.region, "term": self.term, "verb": self.verb}


# ---------------------------------------------------------------------------
# Relation verbs. For v0 only "is associated with" is required; a few cheap
# synonyms are accepted. "shows altered <region> in <term>" is a distinct
# surface handled separately (region and term flank the verb differently).
# ---------------------------------------------------------------------------
_INFIX_VERBS: tuple[str, ...] = (
    "is associated with",
    "is correlated with",
    "correlates with",
    "is linked to",
)

# Default success / failure criteria when the optional clauses are omitted.
_DEFAULT_SUCCESS = "score>=target"
_DEFAULT_FAILURE = "direction flips"


def _strip(text: str) -> str:
    return text.strip()


def _split_logical_lines(body: str) -> list[tuple[int, str]]:
    """Split the post-header body into non-empty (1-based-line-no, text) lines."""
    out: list[tuple[int, str]] = []
    for idx, raw in enumerate(body.splitlines(), start=1):
        stripped = raw.strip()
        if stripped:
            out.append((idx, stripped))
    return out


def _parse_header(line_no: int, line: str) -> str:
    """Parse ``CLAIM <ID>:`` -> claim_id."""
    m = re.fullmatch(r"CLAIM\s+(?P<id>[A-Za-z0-9][A-Za-z0-9_\-.]*)\s*:", line)
    if not m:
        raise NsquallSyntaxError(
            "expected a 'CLAIM <ID>:' header (ID = alphanumerics/_-. , then a colon)",
            line=line_no,
            clause=line,
        )
    return m.group("id")


def _parse_claim_sentence(line_no: int, line: str) -> tuple[str, ParsedRelation]:
    """Parse the natural claim sentence; return (verbatim_text, relation).

    Accepted surfaces (case-insensitive on keywords, region/term preserved as-is):

    * ``In <population> <modality>, the <region> is associated with <term>.``
    * ``In <population> <modality>, <region> shows altered ... in <term>.``
    """
    text = line.rstrip()
    if not text.endswith("."):
        raise NsquallSyntaxError(
            "claim sentence must end with a period '.'",
            line=line_no,
            clause=line,
        )

    # Enforce a SINGLE sentence: after the first sentence-terminating period, any
    # further non-whitespace content is a second sentence and must fail loudly.
    first_period = text.index(".")
    trailing = text[first_period + 1 :]
    if trailing.strip():
        raise NsquallSyntaxError(
            "claim must be a single sentence; found content after the first period "
            f"({trailing.strip()!r})",
            line=line_no,
            clause=line,
        )

    # Must open with "In <population> <modality>, ..."
    head = re.match(r"(?i)^In\s+.+?,\s*", text)
    if not head:
        raise NsquallSyntaxError(
            "claim sentence must begin with 'In <population> <modality>, ...'",
            line=line_no,
            clause=line,
        )
    remainder = text[head.end():].rstrip(".").strip()

    # Surface A: "the <region> <infix verb> <term>".
    #
    # Select the infix verb by EARLIEST POSITION in the sentence (min match.start()),
    # NOT by _INFIX_VERBS list order. If more than one DISTINCT infix verb matches the
    # sentence the predicate is ambiguous and we fail loudly rather than silently
    # picking one.
    verb_hits: list[tuple[int, int, int, str]] = []
    for verb in _INFIX_VERBS:
        m = re.search(rf"(?i)\b{re.escape(verb)}\b", remainder)
        if m:
            verb_hits.append((m.start(), m.end(), len(verb), verb))

    if verb_hits:
        distinct_verbs = {verb for *_rest, verb in verb_hits}
        if len(distinct_verbs) > 1:
            raise NsquallSyntaxError(
                "ambiguous predicate: more than one relation verb matched the claim "
                f"sentence {sorted(distinct_verbs)}; a claim must have exactly one main verb",
                line=line_no,
                clause=line,
            )
        # Single distinct verb (possibly matched once); choose earliest occurrence.
        start, end, _len, verb = min(verb_hits)
        region_part = remainder[:start].strip()
        term_part = remainder[end:].strip()
        region = _strip_leading_article(region_part)
        term = _strip_leading_article(term_part)
        if not region or not term:
            raise NsquallSyntaxError(
                f"'{verb}' must have a region phrase before it and a term phrase after it",
                line=line_no,
                clause=line,
            )
        return text, ParsedRelation(region=region, term=term, verb=verb)

    # Surface B: "<region> shows altered <something> in <term>"
    m = re.search(r"(?i)\bshows?\s+altered\b(?P<mid>.*?)\bin\b\s+(?P<term>.+)", remainder)
    if m:
        region = _strip_leading_article(remainder[: m.start()].strip())
        term = _strip_leading_article(m.group("term").strip())
        if not region or not term:
            raise NsquallSyntaxError(
                "'shows altered ... in ...' must have a region before it and a term after 'in'",
                line=line_no,
                clause=line,
            )
        return text, ParsedRelation(region=region, term=term, verb="shows altered in")

    raise NsquallSyntaxError(
        "claim sentence has no recognized relation verb; expected one of "
        f"{list(_INFIX_VERBS)} or 'shows altered ... in ...'",
        line=line_no,
        clause=line,
    )


def _strip_leading_article(phrase: str) -> str:
    """Drop a single leading 'the '/'a '/'an ' article; preserve the rest verbatim."""
    return re.sub(r"(?i)^(the|a|an)\s+", "", phrase.strip()).strip()


def _parse_scope(line_no: int, line: str) -> ScopeBoundaryV1:
    """Parse ``SCOPE population=<p> modality=<m> datasets=<d1,d2> workflow=<wf>.``"""
    body = line[len("SCOPE"):].rstrip(".").strip()
    if not body:
        raise NsquallSyntaxError(
            "SCOPE clause has no key=value pairs",
            line=line_no,
            clause=line,
        )
    pairs = _parse_key_values(line_no, line, body)
    allowed_keys = {"population", "modality", "datasets", "workflow"}
    unknown = set(pairs) - allowed_keys
    if unknown:
        raise NsquallSyntaxError(
            f"unknown SCOPE key(s) {sorted(unknown)}; allowed keys are {sorted(allowed_keys)}",
            line=line_no,
            clause=line,
        )
    datasets_raw = pairs.get("datasets", "")
    datasets = [d.strip() for d in datasets_raw.split(",") if d.strip()] if datasets_raw else []
    return ScopeBoundaryV1(
        population=pairs.get("population") or None,
        modality=pairs.get("modality") or None,
        datasets=datasets,
        workflow_family=pairs.get("workflow") or None,
    )


def _parse_key_values(line_no: int, line: str, body: str) -> dict[str, str]:
    """Parse ``key=value`` tokens separated by whitespace.

    Values may NOT contain spaces (use commas inside datasets). A bare token with
    no ``=`` is a syntax error.
    """
    out: dict[str, str] = {}
    for token in body.split():
        if "=" not in token:
            raise NsquallSyntaxError(
                f"expected 'key=value' but found bare token {token!r}",
                line=line_no,
                clause=line,
            )
        key, _, value = token.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            raise NsquallSyntaxError(
                f"empty key in token {token!r}",
                line=line_no,
                clause=line,
            )
        out[key] = value
    return out


def _parse_design_line(line_no: int, line: str) -> tuple[bool, list[str], str | None]:
    """Parse ``[CONFIRMATORY|EXPLORATORY] [allowing ...] [null=...].``

    Returns (confirmatory, allowed_alternatives, same_null_constraint).
    """
    body = line.rstrip(".").strip()

    m = re.match(r"(?i)^(?P<mode>CONFIRMATORY|EXPLORATORY)\b", body)
    if not m:
        raise NsquallSyntaxError(
            "design line must begin with CONFIRMATORY or EXPLORATORY",
            line=line_no,
            clause=line,
        )
    confirmatory = m.group("mode").upper() == "CONFIRMATORY"
    rest = body[m.end():].strip()

    allowed: list[str] = []
    null_constraint: str | None = None

    # Optional null=<constraint>: pull it off the tail first (single token, no spaces).
    null_match = re.search(r"(?i)\bnull\s*=\s*(?P<null>\S+)\s*$", rest)
    if null_match:
        null_constraint = null_match.group("null").strip()
        rest = rest[: null_match.start()].strip()

    # Optional allowing <alt1>, <alt2>, ...
    if rest:
        allow_match = re.match(r"(?i)^allowing\b(?P<alts>.*)$", rest)
        if not allow_match:
            raise NsquallSyntaxError(
                "after CONFIRMATORY/EXPLORATORY only 'allowing <alts>' and 'null=<c>' "
                f"are valid; got {rest!r}",
                line=line_no,
                clause=line,
            )
        alts_raw = allow_match.group("alts").strip()
        if not alts_raw:
            raise NsquallSyntaxError(
                "'allowing' must be followed by at least one alternative",
                line=line_no,
                clause=line,
            )
        allowed = [a.strip() for a in alts_raw.split(",") if a.strip()]
        if not allowed:
            raise NsquallSyntaxError(
                "'allowing' alternatives list is empty after splitting on commas",
                line=line_no,
                clause=line,
            )

    return confirmatory, allowed, null_constraint


def _parse_outcome(prefix: str, line: str) -> str:
    """Parse ``SUCCESS <text>.`` / ``FAILURE <text>.`` -> the text (period stripped)."""
    return line[len(prefix):].rstrip(".").strip()


def parse_nsquall(text: str) -> ClaimSpecV1:
    """Parse a strict NSQUALL claim into a :class:`ClaimSpecV1`.

    Raises:
        NsquallSyntaxError: on any grammar violation, with line/clause context.
    """
    if text is None or not text.strip():
        raise NsquallSyntaxError("empty NSQUALL input")

    lines = _split_logical_lines(text)
    if not lines:
        raise NsquallSyntaxError("empty NSQUALL input")

    # --- Line 1: CLAIM header ---
    header_no, header_line = lines[0]
    claim_id = _parse_header(header_no, header_line)

    if len(lines) < 2:
        raise NsquallSyntaxError(
            "missing the claim sentence (expected on the line after the CLAIM header)",
            line=header_no,
        )

    # --- Line 2: claim sentence ---
    sent_no, sent_line = lines[1]
    if sent_line.upper().startswith(("SCOPE", "CONFIRMATORY", "EXPLORATORY", "SUCCESS", "FAILURE")):
        raise NsquallSyntaxError(
            "missing the natural claim sentence before SCOPE",
            line=sent_no,
            clause=sent_line,
        )
    claim_text, relation = _parse_claim_sentence(sent_no, sent_line)

    # --- Remaining lines: SCOPE (required), design line (required),
    #     SUCCESS / FAILURE (optional) ---
    scope: ScopeBoundaryV1 | None = None
    confirmatory: bool | None = None
    allowed_alternatives: list[str] = []
    same_null_constraint: str | None = None
    success_criteria: str | None = None
    failure_criteria: str | None = None

    for line_no, line in lines[2:]:
        upper = line.upper()
        if upper.startswith("SCOPE"):
            if scope is not None:
                raise NsquallSyntaxError("duplicate SCOPE clause", line=line_no, clause=line)
            scope = _parse_scope(line_no, line)
        elif upper.startswith(("CONFIRMATORY", "EXPLORATORY")):
            if confirmatory is not None:
                raise NsquallSyntaxError(
                    "duplicate CONFIRMATORY/EXPLORATORY design line", line=line_no, clause=line
                )
            confirmatory, allowed_alternatives, same_null_constraint = _parse_design_line(
                line_no, line
            )
        elif upper.startswith("SUCCESS"):
            if success_criteria is not None:
                raise NsquallSyntaxError("duplicate SUCCESS clause", line=line_no, clause=line)
            success_criteria = _parse_outcome("SUCCESS", line)
            if not success_criteria:
                raise NsquallSyntaxError("SUCCESS clause has no text", line=line_no, clause=line)
        elif upper.startswith("FAILURE"):
            if failure_criteria is not None:
                raise NsquallSyntaxError("duplicate FAILURE clause", line=line_no, clause=line)
            failure_criteria = _parse_outcome("FAILURE", line)
            if not failure_criteria:
                raise NsquallSyntaxError("FAILURE clause has no text", line=line_no, clause=line)
        else:
            raise NsquallSyntaxError(
                "unrecognized clause; expected one of SCOPE / CONFIRMATORY|EXPLORATORY / "
                "SUCCESS / FAILURE",
                line=line_no,
                clause=line,
            )

    if scope is None:
        raise NsquallSyntaxError(
            "missing required SCOPE clause", line=header_no, clause=header_line
        )
    if confirmatory is None:
        raise NsquallSyntaxError(
            "missing required CONFIRMATORY/EXPLORATORY design line",
            line=header_no,
            clause=header_line,
        )

    extra: dict[str, Any] = {"relation": relation.as_dict()}

    return ClaimSpecV1(
        claim_id=claim_id,
        claim_text=claim_text,
        scope_boundary=scope,
        allowed_alternatives=allowed_alternatives,
        same_null_constraint=same_null_constraint,
        success_criteria=success_criteria if success_criteria is not None else _DEFAULT_SUCCESS,
        failure_criteria=failure_criteria if failure_criteria is not None else _DEFAULT_FAILURE,
        confirmatory=confirmatory,
        extra=extra,
    )


def compile_nsquall(text: str, **kwargs: Any) -> Any:
    """Convenience: parse NSQUALL then run :func:`neuroclaim_compile` on it.

    Thin wrapper — parses with :func:`parse_nsquall`, then forwards the claim text,
    id, and scope into ``neuroclaim_compile``. Any extra keyword args (``backend``,
    ``plan``, ``run_sensitivity`` ...) pass straight through.
    """
    spec = parse_nsquall(text)
    # Lazy import keeps parsing free of the compile/evidence-backend import chain.
    from .compile import neuroclaim_compile

    return neuroclaim_compile(
        spec.claim_text,
        claim_id=spec.claim_id,
        scope=spec.scope_boundary,
        **kwargs,
    )
