"""Task family matching helpers for BR-KG task lens."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

try:
    from rapidfuzz import fuzz, process
except Exception:  # pragma: no cover - optional dependency in some envs
    fuzz = None
    process = None


_NONWORD_RE = re.compile(r"[^a-z0-9]+")
_WS_RE = re.compile(r"\s+")
_PAREN_CONTENT_RE = re.compile(r"\([^)]*\)")
_NBACK_RE = re.compile(r"\bn[\s\-]*back\b")
_TRAILING_SUFFIXES = (
    " task",
    " tasks",
    " paradigm",
    " test",
    " assessment",
)
_STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "for",
    "to",
    "in",
    "on",
    "with",
    "without",
    "via",
    "using",
}
_LOW_SIGNAL_TOKENS = {
    "fmri",
    "mri",
    "pet",
    "eeg",
    "meg",
    "dti",
    "bold",
    "resting",
    "state",
    "imaging",
    "scan",
    "scans",
    "contrast",
    "contrasts",
    "map",
    "maps",
    "analysis",
    "protocol",
    "session",
    "sessions",
}
_TRACER_TOKENS = {
    "fdg",
    "mrsi",
    "fwhm",
}
_NOISE_EXACT_LABELS = {
    "404 not found",
    "page not found",
    "activation likelihood estimation meta analysis",
    "meta analytic connectivity modeling",
    "arterial spin labeling",
    "diffusion tensor imaging",
    "magnetic resonance imaging",
    "cerebral blood flow measurement",
    "voxel based morphometry",
    "voxel based morphometry analysis",
    "cognitive assessment",
    "cognitive tests",
    "cognitive tasks",
    "neuropsychological",
    "neuropsychological tests",
    "neuropsychological testing",
    "neuropsychological test battery",
    "neuropsychological battery",
    "neuropsychological assessments",
    "mini mental state examination",
    "symbol digit modalities",
    "beck depression inventory",
    "beck anxiety inventory",
    "state trait anxiety inventory",
    "barratt impulsiveness scale",
    "interpersonal reactivity index",
    "positive and negative syndrome scale",
    "alcohol use disorders identification test",
    "toronto alexithymia scale",
    "childhood trauma questionnaire",
    "general procrastination scale",
    "wechsler abbreviated scale of intelligence",
    "wechsler adult intelligence scale",
    "clock drawing test",
    "frontal assessment battery",
    "neuropsychiatric inventory",
    "repeatable battery for the assessment of neuropsychological status",
    "montreal cognitive",
}
_NUM_ALPHA_TOKEN_RE = re.compile(r"^\d+[a-z]+$")
logger = logging.getLogger(__name__)


def _tokenize(value: str) -> list[str]:
    return [token for token in _WS_RE.split(value.strip()) if token]


def _signal_tokens(value: str) -> set[str]:
    tokens = set()
    for token in _tokenize(value):
        if token in _STOPWORDS:
            continue
        if token in _LOW_SIGNAL_TOKENS:
            continue
        if token.isdigit():
            continue
        tokens.add(token)
    return tokens


def _is_noise_label(normalized: str) -> bool:
    if not normalized:
        return True
    if normalized in _NOISE_EXACT_LABELS:
        return True
    tokens = _tokenize(normalized)
    if not tokens:
        return True
    has_alpha = any(any(ch.isalpha() for ch in token) for token in tokens)
    if not has_alpha:
        return True
    if all(token in _LOW_SIGNAL_TOKENS or token.isdigit() for token in tokens):
        return True
    if all(
        token in _LOW_SIGNAL_TOKENS
        or token in _TRACER_TOKENS
        or token.isdigit()
        or bool(_NUM_ALPHA_TOKEN_RE.match(token))
        for token in tokens
    ):
        return True
    if len(tokens) <= 2 and all(token.isdigit() for token in tokens):
        return True
    return False


def normalize_task_label(
    text: str | None,
    *,
    strip_parenthetical: bool = True,
) -> str:
    if text is None:
        return ""
    value = str(text).strip().lower()
    if not value:
        return ""
    if strip_parenthetical:
        value = _PAREN_CONTENT_RE.sub(" ", value)
    value = _NBACK_RE.sub("n back", value)
    value = _NONWORD_RE.sub(" ", value)
    value = _WS_RE.sub(" ", value).strip()
    for suffix in _TRAILING_SUFFIXES:
        if value.endswith(suffix):
            value = value[: -len(suffix)].strip()
            value = _WS_RE.sub(" ", value).strip()
    return value


@dataclass(frozen=True)
class TaskFamilyRecord:
    family_id: str
    family_label: str
    family_description: str
    subfamily_id: str
    subfamily_label: str
    paradigm_name: str


@dataclass(frozen=True)
class _FuzzyCandidate:
    record: TaskFamilyRecord
    choice: str
    token_set_score: float
    partial_score: float
    overlap_count: int

    @property
    def combined_score(self) -> float:
        return max(self.token_set_score, self.partial_score)


class TaskFamilyMatcher:
    """Resolve free-text task labels into taxonomy family/subfamily/paradigm."""

    def __init__(
        self,
        *,
        taxonomy_path: Path,
        alias_extensions_path: Path | None = None,
        fuzzy_threshold: float = 0.86,
        enable_fuzzy: bool = True,
        aggressive_mode: bool = True,
        aggressive_primary_threshold: float = 0.72,
        aggressive_secondary_threshold: float = 0.64,
        min_token_overlap: int = 1,
        ambiguity_margin: float = 0.04,
    ) -> None:
        self.taxonomy_path = taxonomy_path
        self.alias_extensions_path = alias_extensions_path
        self.fuzzy_threshold = max(0.0, min(float(fuzzy_threshold), 1.0))
        self.enable_fuzzy = bool(enable_fuzzy)
        self.aggressive_mode = bool(aggressive_mode)
        self.aggressive_primary_threshold = max(
            0.0, min(float(aggressive_primary_threshold), 1.0)
        )
        self.aggressive_secondary_threshold = max(
            0.0, min(float(aggressive_secondary_threshold), 1.0)
        )
        self.min_token_overlap = max(0, int(min_token_overlap))
        self.ambiguity_margin = max(0.0, min(float(ambiguity_margin), 1.0))
        self.available = False
        self._alias_to_record: dict[str, TaskFamilyRecord] = {}
        self._fuzzy_choices: list[str] = []
        self._choice_to_tokens: dict[str, set[str]] = {}
        self._load()

    def _load(self) -> None:
        if not self.taxonomy_path.exists():
            return
        data = yaml.safe_load(self.taxonomy_path.read_text(encoding="utf-8")) or {}
        families = data.get("families") if isinstance(data, dict) else None
        if not isinstance(families, list):
            return
        alias_to_record: dict[str, TaskFamilyRecord] = {}
        for family in families:
            if not isinstance(family, dict):
                continue
            family_id = str(family.get("id") or "").strip()
            family_label = str(family.get("label") or family_id).strip()
            family_description = str(family.get("description") or "").strip()
            if not family_id:
                continue
            subfamilies = family.get("subfamilies") or []
            if not isinstance(subfamilies, list):
                continue
            for subfamily in subfamilies:
                if not isinstance(subfamily, dict):
                    continue
                subfamily_id = str(subfamily.get("id") or "").strip() or f"{family_id}::subfamily"
                subfamily_label = str(subfamily.get("label") or subfamily_id).strip()
                paradigms = subfamily.get("paradigms") or []
                if not isinstance(paradigms, list):
                    continue
                for paradigm in paradigms:
                    if not isinstance(paradigm, dict):
                        continue
                    paradigm_name = str(paradigm.get("name") or "").strip()
                    if not paradigm_name:
                        continue
                    record = TaskFamilyRecord(
                        family_id=family_id,
                        family_label=family_label,
                        family_description=family_description,
                        subfamily_id=subfamily_id,
                        subfamily_label=subfamily_label,
                        paradigm_name=paradigm_name,
                    )
                    candidates = [paradigm_name]
                    aliases = paradigm.get("aliases") or []
                    if isinstance(aliases, list):
                        candidates.extend(str(alias).strip() for alias in aliases if alias)
                    for candidate in candidates:
                        normalized = normalize_task_label(candidate)
                        if not normalized:
                            continue
                        alias_to_record.setdefault(normalized, record)
        self._apply_alias_extensions(alias_to_record)
        self._alias_to_record = alias_to_record
        self._fuzzy_choices = list(alias_to_record.keys())
        self._choice_to_tokens = {
            choice: _signal_tokens(choice) for choice in self._fuzzy_choices
        }
        self.available = bool(alias_to_record)

    def _resolve_extension_target(
        self,
        entry: dict[str, Any],
        base_alias_to_record: dict[str, TaskFamilyRecord],
    ) -> TaskFamilyRecord | None:
        target_alias = normalize_task_label(
            str(entry.get("target_alias") or entry.get("canonical_alias") or "")
        )
        if target_alias:
            resolved = base_alias_to_record.get(target_alias)
            if resolved is not None:
                return resolved

        family_id = str(entry.get("family_id") or "").strip()
        subfamily_id = str(entry.get("subfamily_id") or "").strip()
        paradigm_name = normalize_task_label(str(entry.get("paradigm_name") or ""))

        if not family_id and not subfamily_id and not paradigm_name:
            return None

        candidates: list[TaskFamilyRecord] = []
        for record in set(base_alias_to_record.values()):
            if family_id and record.family_id != family_id:
                continue
            if subfamily_id and record.subfamily_id != subfamily_id:
                continue
            if paradigm_name and normalize_task_label(record.paradigm_name) != paradigm_name:
                continue
            candidates.append(record)

        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            logger.warning(
                "Ambiguous task family alias extension target: alias=%r family_id=%r subfamily_id=%r paradigm_name=%r candidates=%d",
                entry.get("alias"),
                family_id,
                subfamily_id,
                entry.get("paradigm_name"),
                len(candidates),
            )
        return None

    def _apply_alias_extensions(
        self,
        alias_to_record: dict[str, TaskFamilyRecord],
    ) -> None:
        path = self.alias_extensions_path
        if path is None or not path.exists():
            return

        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            logger.warning("Failed to load task family alias extensions (%s): %s", path, exc)
            return

        entries = payload.get("aliases") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            logger.warning("Invalid task family alias extensions payload (expected aliases list): %s", path)
            return

        applied = 0
        skipped = 0
        for raw in entries:
            if not isinstance(raw, dict):
                skipped += 1
                continue
            alias = normalize_task_label(str(raw.get("alias") or ""))
            if not alias:
                skipped += 1
                continue
            target = self._resolve_extension_target(raw, alias_to_record)
            if target is None:
                skipped += 1
                continue
            if alias in alias_to_record:
                # Preserve taxonomy-native aliases over extension overrides.
                continue
            alias_to_record[alias] = target
            applied += 1

        logger.info(
            "Loaded task family alias extensions from %s (applied=%d skipped=%d)",
            path,
            applied,
            skipped,
        )

    def _collect_fuzzy_candidates(self, normalized: str) -> list[_FuzzyCandidate]:
        if process is None or fuzz is None or not self._fuzzy_choices:
            return []

        token_matches = process.extract(
            normalized,
            self._fuzzy_choices,
            scorer=fuzz.token_set_ratio,
            limit=8,
        )
        partial_matches = process.extract(
            normalized,
            self._fuzzy_choices,
            scorer=fuzz.partial_ratio,
            limit=8,
        )
        score_map: dict[str, dict[str, float]] = {}

        for choice, score, _ in token_matches:
            entry = score_map.setdefault(choice, {"token_set": 0.0, "partial": 0.0})
            entry["token_set"] = max(entry["token_set"], float(score) / 100.0)
        for choice, score, _ in partial_matches:
            entry = score_map.setdefault(choice, {"token_set": 0.0, "partial": 0.0})
            entry["partial"] = max(entry["partial"], float(score) / 100.0)

        label_tokens = _signal_tokens(normalized)
        candidates: list[_FuzzyCandidate] = []
        for choice, scores in score_map.items():
            record = self._alias_to_record.get(choice)
            if record is None:
                continue
            choice_tokens = self._choice_to_tokens.get(choice, set())
            overlap_count = len(label_tokens & choice_tokens)
            candidates.append(
                _FuzzyCandidate(
                    record=record,
                    choice=choice,
                    token_set_score=scores["token_set"],
                    partial_score=scores["partial"],
                    overlap_count=overlap_count,
                )
            )
        candidates.sort(
            key=lambda item: (
                item.combined_score,
                item.overlap_count,
                item.token_set_score,
                item.partial_score,
            ),
            reverse=True,
        )
        return candidates

    def match(self, label: str | None) -> tuple[TaskFamilyRecord | None, str, float | None]:
        normalized = normalize_task_label(label)
        if not normalized:
            return None, "unmapped", None
        if _is_noise_label(normalized):
            return None, "noise_rejected", None
        direct = self._alias_to_record.get(normalized)
        if direct is not None:
            return direct, "exact_alias", 1.0
        if (
            self.enable_fuzzy
            and process is not None
            and fuzz is not None
            and self._fuzzy_choices
        ):
            candidates = self._collect_fuzzy_candidates(normalized)
            if candidates:
                best = candidates[0]
                second = candidates[1] if len(candidates) > 1 else None
                if (
                    second is not None
                    and (best.combined_score - second.combined_score) <= self.ambiguity_margin
                    and second.combined_score >= self.aggressive_secondary_threshold
                ):
                    return None, "ambiguous_rejected", None

                if self.aggressive_mode:
                    primary_pass = (
                        best.token_set_score >= self.aggressive_primary_threshold
                        and best.overlap_count >= self.min_token_overlap
                    )
                    secondary_pass = (
                        best.token_set_score >= self.aggressive_secondary_threshold
                        and best.partial_score >= self.aggressive_secondary_threshold
                        and best.overlap_count >= self.min_token_overlap
                    )
                    if primary_pass or secondary_pass:
                        return (
                            best.record,
                            "aggressive_fuzzy_guarded",
                            best.combined_score,
                        )
                    return None, "guardrail_rejected", None

                if best.token_set_score >= self.fuzzy_threshold:
                    return best.record, "fuzzy_alias", best.token_set_score
        return None, "unmapped", None

    def enrich_entity(self, entity: dict[str, Any]) -> dict[str, Any]:
        label = (
            entity.get("display_label")
            or entity.get("label")
            or entity.get("id")
            or ""
        )
        record, method, score = self.match(str(label))
        enriched = dict(entity)
        if record is None:
            enriched.update(
                {
                    "family_id": None,
                    "family_label": None,
                    "subfamily_id": None,
                    "subfamily_label": None,
                    "paradigm_name": None,
                    "match_method": method,
                    "match_score": None,
                }
            )
            return enriched
        enriched.update(
            {
                "family_id": record.family_id,
                "family_label": record.family_label,
                "family_description": record.family_description,
                "subfamily_id": record.subfamily_id,
                "subfamily_label": record.subfamily_label,
                "paradigm_name": record.paradigm_name,
                "match_method": method,
                "match_score": score,
            }
        )
        return enriched


def build_task_family_tree(
    entities: Iterable[dict[str, Any]],
    *,
    query: str = "",
    include_unmapped: bool = True,
) -> list[dict[str, Any]]:
    q = normalize_task_label(query)
    family_map: dict[str, dict[str, Any]] = {}
    unmapped_family_id = "tf_unmapped"

    def _ensure_family(
        family_id: str,
        family_label: str,
        family_description: str | None = None,
    ) -> dict[str, Any]:
        bucket = family_map.get(family_id)
        if bucket is None:
            bucket = {
                "id": family_id,
                "label": family_label,
                "description": family_description or "",
                "task_count": 0,
                "children": {},
            }
            family_map[family_id] = bucket
        return bucket

    for entity in entities:
        display_label = str(
            entity.get("display_label")
            or entity.get("label")
            or entity.get("id")
            or ""
        )
        if q and q not in normalize_task_label(display_label):
            continue
        family_id = entity.get("family_id")
        subfamily_id = entity.get("subfamily_id")
        if not family_id or not subfamily_id:
            if not include_unmapped:
                continue
            family = _ensure_family(unmapped_family_id, "Unmapped Tasks")
            subfamily_key = "unmapped"
            subfamily = family["children"].setdefault(
                subfamily_key,
                {
                    "id": subfamily_key,
                    "label": "Unmapped",
                    "children": [],
                    "task_count": 0,
                },
            )
            subfamily["children"].append(dict(entity))
            subfamily["task_count"] = int(subfamily.get("task_count") or 0) + 1
            family["task_count"] = int(family.get("task_count") or 0) + 1
            continue
        family = _ensure_family(
            str(family_id),
            str(entity.get("family_label") or family_id),
            str(entity.get("family_description") or ""),
        )
        subfamily_key = str(subfamily_id)
        subfamily = family["children"].setdefault(
            subfamily_key,
            {
                "id": subfamily_key,
                "label": str(entity.get("subfamily_label") or subfamily_id),
                "children": [],
                "task_count": 0,
            },
        )
        subfamily["children"].append(dict(entity))
        subfamily["task_count"] = int(subfamily.get("task_count") or 0) + 1
        family["task_count"] = int(family.get("task_count") or 0) + 1

    families: list[dict[str, Any]] = []
    for family in family_map.values():
        children = list(family["children"].values())
        children.sort(key=lambda item: str(item.get("label") or "").lower())
        for sub in children:
            sub["children"].sort(
                key=lambda item: str(
                    item.get("display_label") or item.get("label") or item.get("id") or ""
                ).lower()
            )
        families.append(
            {
                "id": family["id"],
                "label": family["label"],
                "description": family.get("description") or "",
                "task_count": int(family.get("task_count") or 0),
                "children": children,
            }
        )

    families.sort(
        key=lambda item: (
            1 if str(item.get("id")) == unmapped_family_id else 0,
            str(item.get("label") or "").lower(),
        )
    )
    return families
