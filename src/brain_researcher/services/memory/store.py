"""Persistence and retrieval for derived memory cards."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any

from brain_researcher.config.run_artifacts import (
    get_mcp_run_root,
    get_mcp_run_roots_for_read,
)

from .models import (
    ClaimMemoryV1,
    ClaimRelationEventV1,
    ClaimRelationLinkV1,
    EpisodicRunMemoryV1,
    MemoryRecord,
    build_embedding_vector,
    build_memory_record,
    cosine_similarity,
    normalize_space,
    normalize_token_text,
    unique_non_empty,
)

logger = logging.getLogger(__name__)

_SQLITE_BUSY_TIMEOUT_MS = 5000


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _memory_root_for_run_root(run_root: Path) -> Path:
    return run_root / "memory"


def _iter_memory_roots_for_read(run_root: Path) -> list[Path]:
    return [
        _memory_root_for_run_root(Path(root).expanduser().resolve())
        for root in get_mcp_run_roots_for_read(run_root)
    ]


class MemoryStore:
    """Local JSON + SQLite-backed runtime memory store."""

    def __init__(self, run_root: Path | str | None = None):
        self._run_root = (
            Path(run_root).expanduser().resolve()
            if run_root is not None
            else Path(get_mcp_run_root()).expanduser().resolve()
        )
        self._memory_root = _memory_root_for_run_root(self._run_root)
        self._cards_root = self._memory_root / "cards"
        self._relations_root = self._memory_root / "relations"
        self._index_dir = self._memory_root / "index"
        self._db_path = self._index_dir / "memory.sqlite3"
        self._lock = threading.Lock()
        self._initialized = False
        self._ensure_initialized()

    @property
    def memory_root(self) -> Path:
        return self._memory_root

    def _connect(self, db_path: Path) -> sqlite3.Connection:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(db_path),
            timeout=_SQLITE_BUSY_TIMEOUT_MS / 1000.0,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS};")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            self._cards_root.mkdir(parents=True, exist_ok=True)
            self._relations_root.mkdir(parents=True, exist_ok=True)
            self._index_dir.mkdir(parents=True, exist_ok=True)
            with self._connect(self._db_path) as conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS memory_records (
                      card_id TEXT PRIMARY KEY,
                      stable_key TEXT UNIQUE,
                      card_type TEXT NOT NULL,
                      created_at TEXT NOT NULL,
                      source_run_id TEXT,
                      source_session_id TEXT,
                      status TEXT,
                      task_type TEXT,
                      claim_type TEXT,
                      relation_type TEXT,
                      dataset_refs_json TEXT NOT NULL DEFAULT '[]',
                      target_ids_json TEXT NOT NULL DEFAULT '[]',
                      tags_json TEXT NOT NULL DEFAULT '[]',
                      embedding_text TEXT NOT NULL DEFAULT '',
                      embedding_vector_json TEXT NOT NULL DEFAULT '[]',
                      file_path TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_memory_records_card_type
                      ON memory_records(card_type);
                    CREATE INDEX IF NOT EXISTS idx_memory_records_source_run
                      ON memory_records(source_run_id);
                    CREATE INDEX IF NOT EXISTS idx_memory_records_created_at
                      ON memory_records(created_at DESC);
                    """
                )
                conn.commit()
            self._initialized = True

    def write(self, card_type: str, card_data: dict[str, Any]) -> dict[str, Any]:
        raw_card_data = dict(card_data or {})
        skip_relation_derivation = bool(
            raw_card_data.pop("_skip_relation_derivation", False)
        )
        record = build_memory_record(card_type, raw_card_data)
        relation_events: list[ClaimRelationEventV1] = []

        with self._lock, self._connect(self._db_path) as conn:
            existing = self._load_existing_by_stable_key(conn, record.stable_key)
            if isinstance(record, EpisodicRunMemoryV1):
                record = self._merge_episodic(existing, record)
            elif isinstance(record, ClaimMemoryV1):
                record = self._merge_claim(existing, record)
                if not skip_relation_derivation:
                    record, relation_events = self._derive_relation_events(conn, record)
            elif isinstance(record, ClaimRelationEventV1) and existing is not None:
                record = existing

            self._persist_record(conn, record)
            persisted_events: list[dict[str, Any]] = []
            for event in relation_events:
                existing_event = self._load_existing_by_stable_key(conn, event.stable_key)
                if existing_event is None:
                    self._persist_record(conn, event)
                    persisted_events.append(event.model_dump(exclude_none=True))
                else:
                    persisted_events.append(existing_event.model_dump(exclude_none=True))
            conn.commit()

        return {
            "ok": True,
            "card_id": record.card_id,
            "card_type": record.card_type,
            "stable_key": record.stable_key,
            "memory_root": str(self._memory_root),
            "card": record.model_dump(exclude_none=True),
            "record": record.model_dump(exclude_none=True),
            "relation_events": persisted_events,
        }

    def get(self, card_id: str) -> dict[str, Any]:
        normalized = normalize_space(card_id)
        if not normalized:
            return {"ok": False, "error": "card_id is required"}

        for memory_root in _iter_memory_roots_for_read(self._run_root):
            db_path = memory_root / "index" / "memory.sqlite3"
            if not db_path.exists():
                continue
            with self._connect(db_path) as conn:
                row = conn.execute(
                    "SELECT * FROM memory_records WHERE card_id = ?",
                    (normalized,),
                ).fetchone()
                if row is None:
                    continue
                record = self._row_to_record(memory_root, row)
                if record is None:
                    continue
                return {
                    "ok": True,
                    "card_id": record.card_id,
                    "card_type": record.card_type,
                    "memory_root": str(memory_root),
                    "card": self._record_response_payload(record),
                    "record": self._record_response_payload(record),
                }
        return {"ok": False, "error": f"memory card not found: {normalized}"}

    def search(
        self,
        query: str = "",
        *,
        card_type: str | None = None,
        filters: dict[str, Any] | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        normalized_query = normalize_space(query)
        safe_filters = dict(filters or {})
        safe_limit = max(1, min(int(limit), 50))

        candidates: list[MemoryRecord] = []
        for memory_root in _iter_memory_roots_for_read(self._run_root):
            db_path = memory_root / "index" / "memory.sqlite3"
            if not db_path.exists():
                continue
            with self._connect(db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM memory_records
                    WHERE (? IS NULL OR card_type = ?)
                    ORDER BY created_at DESC
                    LIMIT 500
                    """,
                    (card_type, card_type),
                ).fetchall()
                for row in rows:
                    record = self._row_to_record(memory_root, row)
                    if record is None:
                        continue
                    if self._matches_filters(record, safe_filters):
                        candidates.append(record)

        if normalized_query:
            query_vector = build_embedding_vector(normalized_query)
            scored = [
                (
                    cosine_similarity(query_vector, candidate.embedding_vector),
                    candidate,
                )
                for candidate in candidates
            ]
            scored.sort(
                key=lambda item: (
                    item[0],
                    item[1].created_at,
                ),
                reverse=True,
            )
            hits = [
                {
                    "card_id": candidate.card_id,
                    "card_type": candidate.card_type,
                    "score": round(score, 6),
                    "record": self._record_response_payload(candidate),
                }
                for score, candidate in scored[:safe_limit]
            ]
        else:
            candidates.sort(key=lambda candidate: candidate.created_at, reverse=True)
            hits = [
                {
                    "card_id": candidate.card_id,
                    "card_type": candidate.card_type,
                    "score": None,
                    "record": self._record_response_payload(candidate),
                }
                for candidate in candidates[:safe_limit]
            ]

        return {
            "ok": True,
            "query": normalized_query,
            "card_type": card_type,
            "filters": safe_filters,
            "count": len(hits),
            "cards": [dict(hit.get("record") or {}, score=hit.get("score")) for hit in hits],
            "hits": hits,
        }

    def _record_response_payload(self, record: MemoryRecord) -> dict[str, Any]:
        payload = record.model_dump(exclude_none=True)
        if isinstance(record, ClaimMemoryV1):
            payload.update(self._claim_update_summary(record))
        return payload

    def _claim_update_entries(self, record: ClaimMemoryV1) -> list[dict[str, Any]]:
        claim_updates = record.extra.get("claim_updates")
        if not isinstance(claim_updates, list):
            return []
        return [item for item in claim_updates if isinstance(item, dict)]

    def _claim_update_summary(self, record: ClaimMemoryV1) -> dict[str, Any]:
        entries = self._claim_update_entries(record)
        actions = unique_non_empty([item.get("action") for item in entries])
        roles = unique_non_empty([item.get("applied_role") for item in entries])
        updated_ats = unique_non_empty([item.get("updated_at") for item in entries])
        return {
            "claim_update_count": len(entries),
            "claim_update_actions": actions,
            "claim_update_roles": roles,
            "latest_claim_update_at": updated_ats[-1] if updated_ats else None,
        }

    def _load_existing_by_stable_key(
        self,
        conn: sqlite3.Connection,
        stable_key: str | None,
    ) -> MemoryRecord | None:
        if not stable_key:
            return None
        row = conn.execute(
            "SELECT * FROM memory_records WHERE stable_key = ?",
            (stable_key,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(self._memory_root, row)

    def _record_path(self, record: MemoryRecord) -> Path:
        if isinstance(record, ClaimRelationEventV1):
            return self._relations_root / f"{record.card_id}.json"
        return self._cards_root / record.card_type / f"{record.card_id}.json"

    def _persist_record(self, conn: sqlite3.Connection, record: MemoryRecord) -> None:
        path = self._record_path(record)
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(path, record.model_dump(exclude_none=True))
        primary_source_run_id = self._primary_source_run_id(record)
        primary_source_session_id = self._primary_source_session_id(record)
        dataset_refs = record.dataset_refs if isinstance(record, EpisodicRunMemoryV1) else []
        target_ids = record.target_ids if isinstance(record, ClaimMemoryV1) else []
        relation_type = record.relation_type if isinstance(record, ClaimRelationEventV1) else None
        conn.execute(
            """
            INSERT INTO memory_records (
              card_id,
              stable_key,
              card_type,
              created_at,
              source_run_id,
              source_session_id,
              status,
              task_type,
              claim_type,
              relation_type,
              dataset_refs_json,
              target_ids_json,
              tags_json,
              embedding_text,
              embedding_vector_json,
              file_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(card_id) DO UPDATE SET
              stable_key=excluded.stable_key,
              card_type=excluded.card_type,
              created_at=excluded.created_at,
              source_run_id=excluded.source_run_id,
              source_session_id=excluded.source_session_id,
              status=excluded.status,
              task_type=excluded.task_type,
              claim_type=excluded.claim_type,
              relation_type=excluded.relation_type,
              dataset_refs_json=excluded.dataset_refs_json,
              target_ids_json=excluded.target_ids_json,
              tags_json=excluded.tags_json,
              embedding_text=excluded.embedding_text,
              embedding_vector_json=excluded.embedding_vector_json,
              file_path=excluded.file_path
            """,
            (
                record.card_id,
                record.stable_key,
                record.card_type,
                record.created_at,
                primary_source_run_id,
                primary_source_session_id,
                getattr(record, "status", None),
                getattr(record, "task_type", None),
                getattr(record, "claim_type", None),
                relation_type,
                _json_dumps(dataset_refs),
                _json_dumps(target_ids),
                _json_dumps(record.tags),
                record.embedding_text,
                _json_dumps(record.embedding_vector),
                path.relative_to(self._memory_root).as_posix(),
            ),
        )

    def _row_to_record(
        self,
        memory_root: Path,
        row: sqlite3.Row | dict[str, Any],
    ) -> MemoryRecord | None:
        raw = dict(row)
        file_path = memory_root / str(raw.get("file_path") or "")
        payload = _load_json(file_path)
        if not isinstance(payload, dict):
            return None
        try:
            return build_memory_record(str(payload.get("card_type") or ""), payload)
        except Exception as exc:
            logger.warning("Failed to load memory record from %s: %s", file_path, exc)
            return None

    def _merge_episodic(
        self,
        existing: MemoryRecord | None,
        incoming: EpisodicRunMemoryV1,
    ) -> EpisodicRunMemoryV1:
        if not isinstance(existing, EpisodicRunMemoryV1):
            return incoming
        merged = incoming.model_copy(
            update={
                "card_id": existing.card_id,
                "created_at": existing.created_at,
                "tags": unique_non_empty(existing.tags + incoming.tags),
                "provenance_refs": unique_non_empty(
                    existing.provenance_refs + incoming.provenance_refs
                ),
            }
        )
        return EpisodicRunMemoryV1.model_validate(merged.model_dump(exclude_none=True))

    def _merge_claim(
        self,
        existing: MemoryRecord | None,
        incoming: ClaimMemoryV1,
    ) -> ClaimMemoryV1:
        if not isinstance(existing, ClaimMemoryV1):
            return incoming

        supporting = self._merge_evidence_lists(
            existing.supporting_evidence,
            incoming.supporting_evidence,
        )
        conflicting = self._merge_evidence_lists(
            existing.conflicting_evidence,
            incoming.conflicting_evidence,
        )
        related = self._merge_relation_links(
            existing.related_claims,
            incoming.related_claims,
        )
        claim_polarity = incoming.claim_polarity or existing.claim_polarity
        if existing.claim_polarity and incoming.claim_polarity:
            if normalize_token_text(existing.claim_polarity) != normalize_token_text(
                incoming.claim_polarity
            ):
                claim_polarity = "mixed"
        merged_status = (
            "superseded"
            if "superseded" in {existing.status, incoming.status}
            else incoming.status or existing.status
        )
        merged_superseded_by = incoming.superseded_by or existing.superseded_by

        merged_payload = existing.model_dump(exclude_none=True)
        merged_payload.update(
            {
                "source_run_ids": unique_non_empty(
                    existing.source_run_ids + incoming.source_run_ids
                ),
                "source_session_ids": unique_non_empty(
                    existing.source_session_ids + incoming.source_session_ids
                ),
                "claim_text": incoming.claim_text or existing.claim_text,
                "claim_type": incoming.claim_type or existing.claim_type,
                "claim_polarity": claim_polarity,
                "domain": incoming.domain or existing.domain,
                "target_ids": unique_non_empty(existing.target_ids + incoming.target_ids),
                "extra": self._merge_claim_extra(existing.extra, incoming.extra),
                "status": merged_status,
                "superseded_by": merged_superseded_by,
                "analytic_conditions": unique_non_empty(
                    existing.analytic_conditions + incoming.analytic_conditions
                ),
                "supporting_evidence": [
                    item.model_dump(exclude_none=True) for item in supporting
                ],
                "conflicting_evidence": [
                    item.model_dump(exclude_none=True) for item in conflicting
                ],
                "tags": unique_non_empty(existing.tags + incoming.tags),
                "last_tested_at": max(
                    normalize_space(existing.last_tested_at),
                    normalize_space(incoming.last_tested_at),
                )
                or existing.last_tested_at
                or incoming.last_tested_at,
                "times_tested": max(
                    len(unique_non_empty(existing.source_run_ids + incoming.source_run_ids)),
                    int(existing.times_tested or 0),
                    int(incoming.times_tested or 0),
                ),
                "related_claims": [
                    item.model_dump(exclude_none=True) for item in related
                ],
                "card_id": existing.card_id,
                "created_at": existing.created_at,
            }
        )
        merged = ClaimMemoryV1.model_validate(merged_payload)
        merged.confidence = self._derive_claim_confidence(merged)
        return merged

    def _merge_claim_extra(
        self,
        left: dict[str, Any] | None,
        right: dict[str, Any] | None,
    ) -> dict[str, Any]:
        merged: dict[str, Any] = dict(left or {})
        for key, value in (right or {}).items():
            if key == "claim_updates":
                existing_items = (
                    merged.get("claim_updates")
                    if isinstance(merged.get("claim_updates"), list)
                    else []
                )
                incoming_items = value if isinstance(value, list) else []
                deduped: list[dict[str, Any]] = []
                seen: set[str] = set()
                for item in [*existing_items, *incoming_items]:
                    if not isinstance(item, dict):
                        continue
                    item_key = _json_dumps(item)
                    if item_key in seen:
                        continue
                    seen.add(item_key)
                    deduped.append(item)
                if deduped:
                    merged["claim_updates"] = deduped
                continue
            if key not in merged:
                merged[key] = value
                continue
            existing_value = merged.get(key)
            if isinstance(existing_value, dict) and isinstance(value, dict):
                merged[key] = {**existing_value, **value}
            elif isinstance(existing_value, list) and isinstance(value, list):
                serialized: set[str] = set()
                deduped_list: list[Any] = []
                for item in [*existing_value, *value]:
                    item_key = _json_dumps(item)
                    if item_key in serialized:
                        continue
                    serialized.add(item_key)
                    deduped_list.append(item)
                merged[key] = deduped_list
            elif value not in (None, "", [], {}):
                merged[key] = value
        return merged

    def _merge_evidence_lists(
        self,
        left: list[Any],
        right: list[Any],
    ) -> list[Any]:
        by_key: dict[str, Any] = {}
        for item in [*left, *right]:
            key = item.identity_key()
            if key and key not in by_key:
                by_key[key] = item
        return list(by_key.values())

    def _merge_relation_links(
        self,
        left: list[ClaimRelationLinkV1],
        right: list[ClaimRelationLinkV1],
    ) -> list[ClaimRelationLinkV1]:
        merged: dict[tuple[str, str], ClaimRelationLinkV1] = {}
        for item in [*left, *right]:
            key = (item.claim_id, item.relation)
            if key not in merged:
                merged[key] = item
        return list(merged.values())

    def _derive_claim_confidence(self, record: ClaimMemoryV1) -> str:
        supporting = len(record.supporting_evidence)
        conflicting = len(record.conflicting_evidence)
        if conflicting > supporting and conflicting > 0:
            return "contested"
        if supporting >= 3 and conflicting == 0:
            return "strong"
        if supporting >= 2:
            return "moderate"
        return "preliminary"

    def _derive_relation_events(
        self,
        conn: sqlite3.Connection,
        record: ClaimMemoryV1,
    ) -> tuple[ClaimMemoryV1, list[ClaimRelationEventV1]]:
        if not record.target_ids:
            return record, []

        others: list[ClaimMemoryV1] = []
        rows = conn.execute(
            "SELECT * FROM memory_records WHERE card_type = 'claim_memory'"
        ).fetchall()
        for row in rows:
            other = self._row_to_record(self._memory_root, row)
            if not isinstance(other, ClaimMemoryV1):
                continue
            if other.card_id == record.card_id or other.stable_key == record.stable_key:
                continue
            if not set(record.target_ids).intersection(other.target_ids):
                continue
            others.append(other)

        relation_events: list[ClaimRelationEventV1] = []
        updated_record = record
        for other in others:
            relation = self._classify_claim_relation(updated_record, other)
            if relation is None:
                continue
            relation_type, note = relation
            updated_record = self._with_related_claim(
                updated_record,
                claim_id=other.card_id or "",
                relation_type=relation_type,
                note=note,
            )
            updated_other = self._with_related_claim(
                other,
                claim_id=updated_record.card_id or "",
                relation_type=relation_type,
                note=note,
            )
            self._persist_record(conn, updated_other)
            relation_events.append(
                ClaimRelationEventV1(
                    triggering_run_id=self._primary_source_run_id(updated_record),
                    lhs_claim_id=updated_record.card_id or "",
                    rhs_claim_id=other.card_id or "",
                    relation_type=relation_type,
                    note=note,
                    evidence_refs=[
                        *updated_record.supporting_evidence[:1],
                        *updated_record.conflicting_evidence[:1],
                    ][:2],
                )
            )
        return updated_record, relation_events

    def _with_related_claim(
        self,
        record: ClaimMemoryV1,
        *,
        claim_id: str,
        relation_type: str,
        note: str,
    ) -> ClaimMemoryV1:
        merged = self._merge_relation_links(
            record.related_claims,
            [ClaimRelationLinkV1(claim_id=claim_id, relation=relation_type, note=note)],
        )
        return ClaimMemoryV1.model_validate(
            {
                **record.model_dump(exclude_none=True),
                "related_claims": [item.model_dump(exclude_none=True) for item in merged],
            }
        )

    def _classify_claim_relation(
        self,
        left: ClaimMemoryV1,
        right: ClaimMemoryV1,
    ) -> tuple[str, str] | None:
        similarity = cosine_similarity(left.embedding_vector, right.embedding_vector)
        left_polarity = normalize_token_text(left.claim_polarity)
        right_polarity = normalize_token_text(right.claim_polarity)
        polarity_conflict = bool(
            left_polarity and right_polarity and left_polarity != right_polarity
        )
        left_conditions = {normalize_token_text(item) for item in left.analytic_conditions}
        right_conditions = {
            normalize_token_text(item) for item in right.analytic_conditions
        }
        if (
            polarity_conflict
            and left_conditions
            and right_conditions
            and left_conditions != right_conditions
        ):
            return ("conditions", "Claims diverge under different analytic conditions.")
        if polarity_conflict:
            return ("contradicts", "Claims share targets but carry opposing polarity.")
        if similarity < 0.45:
            return None
        if similarity >= 0.9 and normalize_token_text(left.claim_text) != normalize_token_text(
            right.claim_text
        ):
            return ("refines", "Claims strongly overlap and likely refine each other.")
        if similarity >= 0.6:
            return ("supports", "Claims align on target and overall direction.")
        return None

    def _matches_filters(self, record: MemoryRecord, filters: dict[str, Any]) -> bool:
        if not filters:
            return True
        for raw_key, raw_expected in filters.items():
            key = normalize_token_text(raw_key)
            expected = normalize_space(raw_expected)
            if not expected:
                continue
            if key == "status":
                if normalize_token_text(getattr(record, "status", "")) != normalize_token_text(expected):
                    return False
            elif key == "task_type":
                if normalize_token_text(getattr(record, "task_type", "")) != normalize_token_text(expected):
                    return False
            elif key == "dataset_ref":
                if not isinstance(record, EpisodicRunMemoryV1):
                    return False
                if normalize_token_text(expected) not in {
                    normalize_token_text(item) for item in record.dataset_refs
                }:
                    return False
            elif key == "target_id":
                if not isinstance(record, ClaimMemoryV1):
                    return False
                if normalize_token_text(expected) not in {
                    normalize_token_text(item) for item in record.target_ids
                }:
                    return False
            elif key == "claim_type":
                if normalize_token_text(getattr(record, "claim_type", "")) != normalize_token_text(expected):
                    return False
            elif key == "claim_update_action":
                if not isinstance(record, ClaimMemoryV1):
                    return False
                if normalize_token_text(expected) not in {
                    normalize_token_text(item.get("action"))
                    for item in self._claim_update_entries(record)
                }:
                    return False
            elif key == "claim_update_role":
                if not isinstance(record, ClaimMemoryV1):
                    return False
                if normalize_token_text(expected) not in {
                    normalize_token_text(item.get("applied_role"))
                    for item in self._claim_update_entries(record)
                }:
                    return False
            elif key == "relation_type":
                if not isinstance(record, ClaimRelationEventV1):
                    return False
                if normalize_token_text(record.relation_type) != normalize_token_text(expected):
                    return False
            else:
                candidate = getattr(record, raw_key, None)
                if isinstance(candidate, list):
                    if normalize_token_text(expected) not in {
                        normalize_token_text(item) for item in candidate
                    }:
                        return False
                elif normalize_token_text(candidate) != normalize_token_text(expected):
                    return False
        return True

    def _primary_source_run_id(self, record: MemoryRecord) -> str | None:
        if isinstance(record, EpisodicRunMemoryV1):
            return record.source_run_id
        if isinstance(record, ClaimMemoryV1):
            return record.source_run_ids[0] if record.source_run_ids else None
        if isinstance(record, ClaimRelationEventV1):
            return record.triggering_run_id
        return None

    def _primary_source_session_id(self, record: MemoryRecord) -> str | None:
        if isinstance(record, EpisodicRunMemoryV1):
            return record.source_session_id
        if isinstance(record, ClaimMemoryV1):
            return record.source_session_ids[0] if record.source_session_ids else None
        return None


__all__ = ["MemoryStore"]
