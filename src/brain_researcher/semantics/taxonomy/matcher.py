"""Enhanced taxonomy matcher utilities."""

from __future__ import annotations

import json
import logging
import math
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

try:  # pragma: no cover - rapidfuzz optional
    from rapidfuzz import fuzz, process  # type: ignore
except ImportError:  # pragma: no cover
    fuzz = None
    process = None

logger = logging.getLogger(__name__)

_TAXONOMY_PATH = Path(__file__).parent
ENTITIES_PATH = _TAXONOMY_PATH / "entities.json"
SURFACE_RULES_PATH = _TAXONOMY_PATH / "surface_rules.json"

_NUMBER_WORDS = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}

_METHOD_PRIORITY = {
    "exact_label": 0,
    "exact_alias": 1,
    "source_alias": 2,
    "surface_rule": 3,
    "fuzzy_label": 4,
    "fuzzy_alias": 5,
}

_CAMEL_RE = re.compile("(?<=[a-z0-9])(?=[A-Z])")
_PAREN_RE = re.compile(r"\((.*?)\)")


def normalize_text(text: str) -> str:
    """Normalize a text string for robust matching."""

    if not text:
        return ""

    text = _CAMEL_RE.sub(" ", text)
    text = _PAREN_RE.sub(" ", text)

    text = unicodedata.normalize("NFKC", text)
    text = text.casefold()

    for word, digit in _NUMBER_WORDS.items():
        text = re.sub(rf"\\b{word}\\b", digit, text)

    text = re.sub(r"[-/\\_\u2010]+", " ", text)
    text = re.sub(r"[.:,'\"!_?\[\]{}]", " ", text)

    text = re.sub(r"\b(task|test|paradigm|experiment|block|the)\b", " ", text)

    text = re.sub(r"\s+", " ", text).strip()
    return text


@dataclass
class MatchCandidate:
    canonical_id: str
    label: str
    entity_type: Optional[str]
    confidence: float
    method: str
    match_text: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    rule: Optional[Dict[str, Any]] = None
    entity: Dict[str, Any] = field(default_factory=dict)

    def to_legacy_dict(self) -> Dict[str, Any]:
        legacy = {
            "match_string": self.match_text,
            "canonical_id": self.canonical_id,
            "label": self.label,
            "type": self.entity_type,
            "parameters": self.parameters,
            "confidence": self.confidence,
            "method": self.method,
        }
        if self.rule:
            legacy["source_rule"] = self.rule
        legacy["entity"] = self.entity
        return legacy


class BaseMatcher:
    """Layered matcher capable of returning ranked candidates."""

    def __init__(
        self,
        *,
        entities_path: Path = ENTITIES_PATH,
        rules_path: Optional[Path] = SURFACE_RULES_PATH,
        entity_types: Optional[Sequence[str]] = None,
    ) -> None:
        self.entities_path = Path(entities_path)
        self.rules_path = Path(rules_path) if rules_path else None

        self.entities: Dict[str, Dict[str, Any]] = {}
        self._label_index: Dict[str, List[str]] = defaultdict(list)
        self._alias_index: Dict[str, List[str]] = defaultdict(list)
        self._source_alias_index: Dict[str, List[str]] = defaultdict(list)
        self._fuzzy_lookup: Dict[str, str] = {}
        self._fuzzy_strings: List[str] = []
        self.compiled_rules: List[Dict[str, Any]] = []

        self._load_entities(entity_types)
        self._build_indexes()
        self._compile_rules()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def _load_entities(self, entity_types: Optional[Sequence[str]]) -> None:
        with self.entities_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        raw_entities: Dict[str, Dict[str, Any]] = payload.get("entities", {})

        if entity_types:
            allowed = {et.casefold() for et in entity_types}
            self.entities = {
                entity_id: data
                for entity_id, data in raw_entities.items()
                if data.get("type", "").casefold() in allowed
            }
        else:
            self.entities = raw_entities

    def _compile_rules(self) -> None:
        if not self.rules_path or not self.rules_path.exists():
            return
        with self.rules_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        for rule in payload.get("surface_rules", []):
            try:
                rule["_pattern_re"] = re.compile(rule["pattern"], re.IGNORECASE)
                self.compiled_rules.append(rule)
            except re.error as exc:  # pragma: no cover - invalid rule
                logger.warning(
                    "Could not compile taxonomy surface rule %s: %s",
                    rule.get("canonical"),
                    exc,
                )
        self.compiled_rules.sort(key=lambda r: len(r.get("pattern", "")), reverse=True)

    def _build_indexes(self) -> None:
        for entity_id, entity in self.entities.items():
            label = str(entity.get("label", entity_id))
            normalized_label = normalize_text(label)
            if normalized_label:
                self._label_index[normalized_label].append(entity_id)
                self._register_fuzzy_term(label, entity_id)

            for alias in entity.get("alt_labels", []) or []:
                alias_str = str(alias)
                normalized_alias = normalize_text(alias_str)
                if normalized_alias:
                    self._alias_index[normalized_alias].append(entity_id)
                    self._register_fuzzy_term(alias_str, entity_id)

            for source_aliases in (entity.get("source_aliases") or {}).values():
                for alias in source_aliases or []:
                    alias_str = str(alias)
                    normalized_alias = normalize_text(alias_str)
                    if normalized_alias:
                        self._source_alias_index[normalized_alias].append(entity_id)
                        self._register_fuzzy_term(alias_str, entity_id)

    def _register_fuzzy_term(self, text: str, entity_id: str) -> None:
        if not text:
            return
        if text not in self._fuzzy_lookup:
            self._fuzzy_strings.append(text)
        self._fuzzy_lookup[text] = entity_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def match_candidates(
        self,
        text: str,
        *,
        max_results: int = 5,
        min_confidence: float = 0.5,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[MatchCandidate]:
        normalized = normalize_text(text)
        if not normalized:
            return []

        context_norm: Dict[str, str] = {}
        if context:
            for key, value in context.items():
                if value is None:
                    continue
                context_norm[key] = normalize_text(str(value))

        candidates: Dict[str, MatchCandidate] = {}

        self._collect_exact_matches(candidates, text, normalized)
        self._collect_source_alias_matches(candidates, text, normalized)
        self._collect_surface_rule_matches(candidates, text)
        self._collect_fuzzy_matches(candidates, text, normalized)

        if context_norm:
            self._apply_context_boost(candidates, normalized, context_norm)

        ranked = sorted(
            candidates.values(),
            key=lambda c: (
                -c.confidence,
                _METHOD_PRIORITY.get(c.method, math.inf),
                c.label,
            ),
        )
        return [c for c in ranked if c.confidence >= min_confidence][:max_results]

    def match(self, text: str) -> Optional[Dict[str, Any]]:
        candidates = self.match_candidates(text, max_results=1)
        if not candidates:
            return None
        return candidates[0].to_legacy_dict()

    def _apply_context_boost(
        self,
        candidates: Dict[str, MatchCandidate],
        normalized_text: str,
        context: Dict[str, str],
    ) -> None:
        if not candidates:
            return

        context_tokens = {token for token in context.values() if token}
        if not context_tokens:
            return

        dataset_token = context.get("dataset")
        source_token = context.get("source")

        for candidate in candidates.values():
            entity = candidate.entity or {}
            source_aliases: Dict[str, Sequence[str]] = entity.get("source_aliases") or {}
            boost = 0.0

            for alias_source, aliases in source_aliases.items():
                source_norm = normalize_text(str(alias_source))
                if source_token and source_norm == source_token:
                    boost = max(boost, 0.03)
                elif source_norm in context_tokens:
                    boost = max(boost, 0.02)

                for alias in aliases or []:
                    alias_norm = normalize_text(str(alias))
                    if alias_norm == normalized_text:
                        boost = max(boost, 0.04)
                    if dataset_token and alias_norm == dataset_token:
                        boost = max(boost, 0.035)

            if boost > 0.0:
                candidate.confidence = min(0.99, candidate.confidence + boost)
                boosts = candidate.parameters.setdefault("context_boosts", [])
                boosts.append(
                    {
                        "boost": round(boost, 4),
                        "context": context,
                    }
                )

    # ------------------------------------------------------------------
    # Matching stages
    # ------------------------------------------------------------------
    def _collect_exact_matches(
        self,
        candidates: Dict[str, MatchCandidate],
        text: str,
        normalized: str,
    ) -> None:
        for entity_id in self._label_index.get(normalized, []):
            self._register_candidate(
                candidates,
                entity_id,
                confidence=1.0,
                method="exact_label",
                match_text=text,
            )
        for entity_id in self._alias_index.get(normalized, []):
            self._register_candidate(
                candidates,
                entity_id,
                confidence=0.98,
                method="exact_alias",
                match_text=text,
            )

    def _collect_source_alias_matches(
        self,
        candidates: Dict[str, MatchCandidate],
        text: str,
        normalized: str,
    ) -> None:
        for entity_id in self._source_alias_index.get(normalized, []):
            self._register_candidate(
                candidates,
                entity_id,
                confidence=0.96,
                method="source_alias",
                match_text=text,
            )

    def _collect_surface_rule_matches(
        self,
        candidates: Dict[str, MatchCandidate],
        text: str,
    ) -> None:
        if not self.compiled_rules:
            return
        for rule in self.compiled_rules:
            pattern = rule.get("_pattern_re")
            if not pattern:
                continue
            match = pattern.search(text)
            if not match:
                continue
            canonical_id = rule.get("canonical")
            if not canonical_id or canonical_id not in self.entities:
                continue
            parameters: Dict[str, Any] = {}
            for param_name, group_name in (rule.get("extract") or {}).items():
                value = None
                try:
                    value = match.group(group_name)
                except (IndexError, KeyError):
                    try:
                        value = match.group(int(group_name))
                    except (ValueError, IndexError):
                        value = None
                if value:
                    parameters[param_name] = _NUMBER_WORDS.get(value.lower(), value)
            confidence = float(rule.get("confidence", 0.94))
            self._register_candidate(
                candidates,
                canonical_id,
                confidence=confidence,
                method="surface_rule",
                match_text=match.group(0),
                parameters=parameters,
                rule=rule,
            )

    def _collect_fuzzy_matches(
        self,
        candidates: Dict[str, MatchCandidate],
        text: str,
        normalized: str,
    ) -> None:
        if not process or not self._fuzzy_strings:
            return
        try:
            results = process.extract(
                normalized,
                self._fuzzy_strings,
                scorer=fuzz.QRatio if fuzz else None,
                limit=10,
            )
        except Exception:  # pragma: no cover - rapidfuzz optional
            return
        for match_string, score, _ in results:
            if score < 80:
                continue
            entity_id = self._fuzzy_lookup.get(match_string)
            if not entity_id:
                continue
            method = "fuzzy_label" if normalize_text(match_string) in self._label_index else "fuzzy_alias"
            confidence = 0.85 * (score / 100)
            self._register_candidate(
                candidates,
                entity_id,
                confidence=confidence,
                method=method,
                match_text=text,
            )

    # ------------------------------------------------------------------
    # Candidate registration
    # ------------------------------------------------------------------
    def _register_candidate(
        self,
        candidates: Dict[str, MatchCandidate],
        entity_id: str,
        *,
        confidence: float,
        method: str,
        match_text: str,
        parameters: Optional[Dict[str, Any]] = None,
        rule: Optional[Dict[str, Any]] = None,
    ) -> None:
        entity = self.entities.get(entity_id)
        if not entity:
            return
        label = str(entity.get("label", entity_id))
        entity_type = entity.get("type")
        parameters = parameters or {}

        existing = candidates.get(entity_id)
        if existing and existing.confidence >= confidence:
            return

        candidates[entity_id] = MatchCandidate(
            canonical_id=entity_id,
            label=label,
            entity_type=entity_type,
            confidence=confidence,
            method=method,
            match_text=match_text,
            parameters=parameters,
            rule=rule,
            entity=entity,
        )


class TaskMatcher(BaseMatcher):
    def __init__(
        self,
        *,
        entities_path: Path = ENTITIES_PATH,
        rules_path: Path = SURFACE_RULES_PATH,
    ) -> None:
        super().__init__(
            entities_path=entities_path,
            rules_path=rules_path,
            entity_types=("Task",),
        )


class ConceptMatcher(BaseMatcher):
    def __init__(
        self,
        *,
        entities_path: Path = ENTITIES_PATH,
        rules_path: Optional[Path] = None,
    ) -> None:
        super().__init__(
            entities_path=entities_path,
            rules_path=rules_path,
            entity_types=("Construct", "Concept"),
        )


def build_flat_map(
    entities_path: Path = ENTITIES_PATH,
    rules_path: Path = SURFACE_RULES_PATH,
) -> Dict[str, str]:
    matcher = TaskMatcher(entities_path=entities_path, rules_path=rules_path)
    flat_map: Dict[str, str] = {}
    for rule in matcher.compiled_rules:
        canonical_id = rule.get("canonical")
        entity = matcher.entities.get(canonical_id)
        if not entity:
            continue
        raw_pattern = rule.get("pattern", "")
        simplified = raw_pattern.replace("\\b", "").replace("\\s*", " ").strip()
        flat_map[simplified] = entity.get("label", canonical_id)
    return flat_map


if __name__ == "__main__":
    matcher = TaskMatcher()
    samples = [
        "2-back task",
        "Go/No-Go",
        "verbal n-back",
        "Stop Signal",
        "word generation",
        "random string",
    ]
    for sample in samples:
        result = matcher.match(sample)
        print(f"Input: {sample!r}")
        if result:
            print(
                f"  -> {result['label']} (id={result['canonical_id']}, conf={result['confidence']:.3f}, method={result.get('method')})"
            )
        else:
            print("  -> no match")
