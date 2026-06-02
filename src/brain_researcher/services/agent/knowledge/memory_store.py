"""Lightweight knowledge memory store per account/user.

Stores EvidenceBundle snapshots keyed by account_id. Uses Redis when available
for cross-process sharing; falls back to an in-process dictionary otherwise.
Intended to keep recent knowledge bundles for personalization/debugging.
"""

from __future__ import annotations

import json
import os
import time
from typing import Dict, List, Optional

try:  # pragma: no cover - optional dependency
    import redis  # type: ignore
except Exception:  # pragma: no cover
    redis = None

from brain_researcher.services.agent.knowledge.evidence_models import EvidenceBundle


class KnowledgeMemoryStore:
    """Per-account knowledge memory with optional Redis backing."""

    def __init__(
        self,
        redis_client: Optional["redis.Redis"] = None,
        namespace: str = "knowledge_memory",
        max_per_account: int = 100,
    ) -> None:
        self.namespace = namespace
        self.max_per_account = max_per_account
        self.redis_client = redis_client or self._maybe_init_redis()
        self._mem: Dict[str, List[dict]] = {}  # L1 fallback

    def _maybe_init_redis(self) -> Optional["redis.Redis"]:
        if redis is None:
            return None
        try:
            url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            client = redis.from_url(url, decode_responses=True)
            client.ping()
            return client
        except Exception:
            return None

    def _make_key(self, account_id: str) -> str:
        return f"{self.namespace}:{account_id}"

    def add_bundle(self, account_id: str, bundle: EvidenceBundle) -> None:
        """Persist a bundle for an account.

        Keeps only the most recent `max_per_account` entries.
        """

        payload = {
            "ts": time.time(),
            "bundle": bundle.to_dict(),
        }
        if self.redis_client:
            key = self._make_key(account_id)
            pipe = self.redis_client.pipeline()
            pipe.lpush(key, json.dumps(payload))
            pipe.ltrim(key, 0, self.max_per_account - 1)
            pipe.execute()
        else:
            lst = self._mem.setdefault(account_id, [])
            lst.insert(0, payload)
            if len(lst) > self.max_per_account:
                del lst[self.max_per_account :]

    def get_size(self, account_id: str) -> int:
        """Return stored bundle count for account."""

        if self.redis_client:
            key = self._make_key(account_id)
            try:
                return int(self.redis_client.llen(key))
            except Exception:
                return 0
        return len(self._mem.get(account_id, []))

    def get_bundles(self, account_id: str, limit: Optional[int] = None) -> List[dict]:
        if self.redis_client:
            key = self._make_key(account_id)
            count = limit or self.max_per_account
            raw = self.redis_client.lrange(key, 0, count - 1)
            return [json.loads(x) for x in raw]

        lst = self._mem.get(account_id, [])
        if limit is None:
            return list(lst)
        return lst[:limit]
