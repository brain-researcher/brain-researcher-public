"""Operational helpers to repair credential users with missing password hashes.

Usage:
  python -m brain_researcher.services.orchestrator.password_recovery \
    --redis-url redis://brain-researcher-redis.brain-researcher-data:6379/0 \
    --mark-reset-required

Optional seed account restoration:
  python -m brain_researcher.services.orchestrator.password_recovery \
    --restore-seed-users --mark-reset-required
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone

import redis
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

SEED_USERS: dict[str, tuple[str, str]] = {
    "demo@brain-researcher.ai": ("demo", "BR_DEMO_USER_PASSWORD"),
    "admin@brain-researcher.ai": ("admin", "BR_DEMO_ADMIN_PASSWORD"),
    "researcher@university.edu": ("researcher", "BR_DEMO_RESEARCHER_PASSWORD"),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iter_user_keys(client: redis.Redis):
    yield from client.scan_iter(match="user:user_*")


def repair_missing_password_hashes(
    redis_url: str,
    *,
    dry_run: bool,
    mark_reset_required: bool,
    restore_seed_users: bool,
) -> dict:
    client = redis.Redis.from_url(redis_url, decode_responses=True)
    report = {
        "scanned": 0,
        "password_users": 0,
        "missing_hash": 0,
        "normalized_provider": 0,
        "restored_seed_users": 0,
        "missing_seed_password_env": 0,
        "marked_reset_required": 0,
        "unchanged": 0,
        "errors": [],
        "timestamp": _now_iso(),
    }

    for key in _iter_user_keys(client):
        report["scanned"] += 1
        raw = client.get(key)
        if not raw:
            continue

        try:
            user = json.loads(raw)
        except Exception as exc:  # pragma: no cover - operational safety
            report["errors"].append(f"{key}: invalid json ({exc})")
            continue

        provider = str(user.get("auth_provider") or "").lower()
        email = str(user.get("email") or "").lower()
        username = str(user.get("username") or "")
        seed = SEED_USERS.get(email)
        is_seed_credential_user = bool(seed and username == seed[0])

        if provider != "password" and not is_seed_credential_user:
            report["unchanged"] += 1
            continue

        provider_updated = False
        if provider != "password":
            user["auth_provider"] = "password"
            provider_updated = True
            report["normalized_provider"] += 1

        report["password_users"] += 1
        if user.get("hashed_password"):
            if provider_updated and not dry_run:
                client.set(key, json.dumps(user, default=str))
            report["unchanged"] += 1
            continue

        report["missing_hash"] += 1
        updated = False

        if restore_seed_users and seed and username == seed[0]:
            password_env = seed[1]
            seed_password = (os.getenv(password_env) or "").strip()
            if seed_password:
                user["hashed_password"] = pwd_context.hash(seed_password)
                prefs = dict(user.get("preferences") or {})
                prefs.pop("must_reset_password", None)
                prefs.pop("password_reset", None)
                user["preferences"] = prefs
                report["restored_seed_users"] += 1
                updated = True
            else:
                report["missing_seed_password_env"] += 1
        elif mark_reset_required:
            prefs = dict(user.get("preferences") or {})
            prefs["must_reset_password"] = True
            prefs["password_reset"] = {
                "required": True,
                "reason": "missing_password_hash",
                "updated_at": _now_iso(),
            }
            user["preferences"] = prefs
            report["marked_reset_required"] += 1
            updated = True

        if (updated or provider_updated) and not dry_run:
            client.set(key, json.dumps(user, default=str))

    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Repair missing password hashes in Orchestrator user store"
    )
    parser.add_argument(
        "--redis-url",
        default=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        help="Redis URL containing user:* keys",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not write changes, only print report",
    )
    parser.add_argument(
        "--mark-reset-required",
        action="store_true",
        help="Mark missing-hash password users as must_reset_password",
    )
    parser.add_argument(
        "--restore-seed-users",
        action="store_true",
        help="Restore known seed users using BR_DEMO_* password env vars",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = repair_missing_password_hashes(
        args.redis_url,
        dry_run=args.dry_run,
        mark_reset_required=args.mark_reset_required,
        restore_seed_users=args.restore_seed_users,
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
