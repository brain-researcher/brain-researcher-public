#!/usr/bin/env python3
"""Run an authenticated /act smoke against API-USD managed billing.

The smoke mirrors the production rollout check:
- create or reuse a credentials account through the public web app;
- sign in through NextAuth credentials;
- grant a monthly API-USD allowance through either the guarded credits API or
  a kubectl exec into the orchestrator pod;
- call /internal/agent/act with a budget id;
- verify the response and, when kubectl access is available, the shared ledger.

No secrets are embedded here. Pass credentials and GCP targeting through CLI
flags or environment variables.
"""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import secrets
import shlex
import subprocess
import sys
import time
from typing import Any, Sequence
from urllib.parse import urljoin
import uuid

import requests


DEFAULT_QUERY = (
    "Smoke test. Reply with exactly this sentence and do not use tools: "
    "API USD smoke ok."
)


@dataclass(frozen=True)
class SmokeConfig:
    base_url: str
    email: str
    password: str
    username: str
    signup: bool
    workspace_id: str
    month: str
    allowance_milli: int
    cap_milli: int
    session_id: str
    budget_id: str
    query: str
    top_up_mode: str
    ledger_mode: str
    gcp_project: str | None
    gcp_zone: str | None
    gcp_vm: str | None
    namespace: str
    orchestrator_target: str
    timeout_seconds: int


def current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def usd_to_milli(value: float) -> int:
    return int(round(float(value) * 1000))


def normalize_base_url(value: str) -> str:
    return value.rstrip("/") + "/"


def random_identity() -> tuple[str, str, str]:
    suffix = secrets.token_hex(5)
    username = f"br_smoke_{suffix}"
    email = f"br-smoke-{suffix}@example.com"
    password = f"BrSmoke-{suffix}-2026!"
    return username, email, password


def signup_payload(config: SmokeConfig) -> dict[str, Any]:
    return {
        "username": config.username,
        "email": config.email,
        "password": config.password,
        "full_name": "BR API USD Smoke",
        "accept_terms": True,
    }


def act_payload(config: SmokeConfig) -> dict[str, Any]:
    return {
        "query": config.query,
        "session_id": config.session_id,
        "budget_id": config.budget_id,
        "llm_budget_id": config.budget_id,
        "tool_mode": "off",
        "budget_ms": 30000,
    }


def extract_user_id(session_json: dict[str, Any], signup_json: dict[str, Any]) -> str | None:
    user = session_json.get("user")
    if isinstance(user, dict) and user.get("id"):
        return str(user["id"])
    signup_user = signup_json.get("user")
    if isinstance(signup_user, dict) and signup_user.get("id"):
        return str(signup_user["id"])
    return None


def extract_api_fee_debit(body: dict[str, Any]) -> dict[str, Any] | None:
    run_card = body.get("runCard") or body.get("run_card") or {}
    execution = run_card.get("execution") if isinstance(run_card, dict) else {}
    if isinstance(execution, dict) and isinstance(execution.get("api_fee_debit"), dict):
        return execution["api_fee_debit"]
    if isinstance(run_card, dict) and isinstance(run_card.get("api_fee_debit"), dict):
        return run_card["api_fee_debit"]
    if isinstance(body.get("api_fee_debit"), dict):
        return body["api_fee_debit"]
    return None


def extract_execution(body: dict[str, Any]) -> dict[str, Any]:
    run_card = body.get("runCard") or body.get("run_card") or {}
    execution = run_card.get("execution") if isinstance(run_card, dict) else {}
    return execution if isinstance(execution, dict) else {}


def build_remote_python_command(
    *,
    project: str,
    zone: str,
    vm: str,
    namespace: str,
    target: str,
    python_code: str,
) -> list[str]:
    encoded = base64.b64encode(python_code.encode("utf-8")).decode("ascii")
    remote_python = "python -c " + shlex.quote(
        f"import base64; exec(base64.b64decode('{encoded}'))"
    )
    kubectl_command = (
        f"sudo k3s kubectl -n {shlex.quote(namespace)} exec {shlex.quote(target)} "
        f"-- {remote_python}"
    )
    return [
        "gcloud",
        "compute",
        "ssh",
        vm,
        "--zone",
        zone,
        "--project",
        project,
        "--command",
        kubectl_command,
    ]


def run_remote_python(config: SmokeConfig, python_code: str) -> dict[str, Any]:
    missing = [
        name
        for name, value in {
            "gcp_project": config.gcp_project,
            "gcp_zone": config.gcp_zone,
            "gcp_vm": config.gcp_vm,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(f"kubectl mode requires: {', '.join(missing)}")

    cmd = build_remote_python_command(
        project=str(config.gcp_project),
        zone=str(config.gcp_zone),
        vm=str(config.gcp_vm),
        namespace=config.namespace,
        target=config.orchestrator_target,
        python_code=python_code,
    )
    proc = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        timeout=config.timeout_seconds,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "remote python failed "
            f"rc={proc.returncode}\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
        )
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("remote python returned no output")
    return json.loads(lines[-1])


def kubectl_top_up(config: SmokeConfig, user_id: str) -> dict[str, Any]:
    code = f"""
import json
from brain_researcher.services.orchestrator.endpoints.credits import _get_store
store = _get_store()
result = store.top_up_api_monthly_allowance(
    {config.workspace_id!r},
    {user_id!r},
    month={config.month!r},
    allowance_milli={config.allowance_milli},
    cap_milli={config.cap_milli},
)
print(json.dumps({{"db_path": store.db_path, "result": result}}, sort_keys=True))
"""
    return run_remote_python(config, code)


def kubectl_ledger(config: SmokeConfig, user_id: str) -> dict[str, Any]:
    code = f"""
import json, sqlite3
from brain_researcher.services.orchestrator.endpoints.credits import _get_store
store = _get_store()
conn = sqlite3.connect(store.db_path)
conn.row_factory = sqlite3.Row
ledger = [dict(row) for row in conn.execute(\"\"\"
SELECT event_type, amount_milli, balance_after_milli, reservation_id,
       idempotency_key, metadata_json, created_at
FROM credit_bucket_ledger
WHERE workspace_id = ? AND user_id = ?
  AND bucket = 'api_fee_usd' AND currency = 'usd'
ORDER BY created_at ASC
\"\"\", ({config.workspace_id!r}, {user_id!r}))]
reservations = [dict(row) for row in conn.execute(\"\"\"
SELECT reservation_id, amount_milli, status, idempotency_key, metadata_json,
       created_at, updated_at
FROM credit_bucket_reservations
WHERE workspace_id = ? AND user_id = ?
  AND bucket = 'api_fee_usd' AND currency = 'usd'
ORDER BY created_at ASC
\"\"\", ({config.workspace_id!r}, {user_id!r}))]
account = conn.execute(\"\"\"
SELECT balance_milli, updated_at
FROM credit_bucket_accounts
WHERE workspace_id = ? AND user_id = ?
  AND bucket = 'api_fee_usd' AND currency = 'usd'
\"\"\", ({config.workspace_id!r}, {user_id!r})).fetchone()
print(json.dumps({{
    "db_path": store.db_path,
    "ledger": ledger,
    "reservations": reservations,
    "account": dict(account) if account else None,
}}, sort_keys=True))
"""
    return run_remote_python(config, code)


def api_top_up(
    session: requests.Session,
    config: SmokeConfig,
    *,
    access_token: str,
    user_id: str,
) -> dict[str, Any]:
    response = session.post(
        urljoin(config.base_url, "api/credits/api-usd/monthly-top-up"),
        json={
            "workspace_id": config.workspace_id,
            "user_id": user_id,
            "month": config.month,
            "allowance": config.allowance_milli / 1000.0,
            "cap": config.cap_milli / 1000.0,
        },
        headers={
            "Authorization": f"Bearer {access_token}",
            "X-Workspace-Id": config.workspace_id,
        },
        timeout=config.timeout_seconds,
    )
    body = response.json()
    if response.status_code >= 400:
        raise RuntimeError(f"API top-up failed {response.status_code}: {body}")
    return body


def validate_smoke(
    *,
    execution: dict[str, Any],
    api_fee_debit: dict[str, Any] | None,
    ledger: dict[str, Any] | None,
    allowance_milli: int,
) -> list[str]:
    errors: list[str] = []
    if execution.get("credential") != "managed_gemini":
        errors.append("execution credential is not managed_gemini")
    if not str(execution.get("bill_to") or "").startswith("managed:"):
        errors.append("execution bill_to is not managed")
    if not api_fee_debit:
        errors.append("response missing api_fee_debit")
    elif api_fee_debit.get("status") != "debited":
        errors.append(f"api_fee_debit status is {api_fee_debit.get('status')!r}")

    if ledger is None:
        return errors

    rows = ledger.get("ledger") or []
    reservations = ledger.get("reservations") or []
    events = [row.get("event_type") for row in rows if isinstance(row, dict)]
    if "reserve" not in events:
        errors.append("ledger missing reserve event")
    if "commit" not in events:
        errors.append("ledger missing commit event")
    if not any(row.get("status") == "committed" for row in reservations):
        errors.append("ledger missing committed reservation")
    account = ledger.get("account") or {}
    balance_milli = int(account.get("balance_milli") or 0)
    if balance_milli >= allowance_milli:
        errors.append("API-USD balance was not debited below allowance")
    return errors


def run_smoke(config: SmokeConfig) -> dict[str, Any]:
    session = requests.Session()
    session.headers.update({"User-Agent": "br-api-usd-smoke/1"})
    signup_json: dict[str, Any] = {}

    if config.signup:
        signup_response = session.post(
            urljoin(config.base_url, "api/orchestrator/auth/signup"),
            json=signup_payload(config),
            timeout=config.timeout_seconds,
        )
        signup_json = signup_response.json()
        if signup_response.status_code >= 400:
            raise RuntimeError(
                f"signup failed {signup_response.status_code}: {signup_json}"
            )

    csrf_response = session.get(
        urljoin(config.base_url, "api/auth/csrf"),
        timeout=config.timeout_seconds,
    )
    csrf_token = csrf_response.json().get("csrfToken")
    if not csrf_token:
        raise RuntimeError("missing NextAuth csrf token")

    auth_response = session.post(
        urljoin(config.base_url, "api/auth/callback/credentials"),
        data={
            "csrfToken": csrf_token,
            "email": config.email,
            "password": config.password,
            "callbackUrl": urljoin(config.base_url, "dashboard"),
            "json": "true",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=config.timeout_seconds,
    )
    auth_json = auth_response.json()
    if auth_response.status_code >= 400 or auth_json.get("error"):
        raise RuntimeError(f"NextAuth login failed: {auth_json}")

    access_token = None
    user_id = None
    session_json: dict[str, Any] = {}
    for _ in range(20):
        session_response = session.get(
            urljoin(config.base_url, "api/auth/session"),
            timeout=config.timeout_seconds,
        )
        session_json = session_response.json()
        access_token = session_json.get("accessToken")
        user_id = extract_user_id(session_json, signup_json)
        if access_token and user_id:
            break
        time.sleep(1)
    if not access_token or not user_id:
        raise RuntimeError(f"session did not expose access token/user id: {session_json}")

    top_up: dict[str, Any] | None = None
    if config.top_up_mode == "api":
        top_up = api_top_up(
            session,
            config,
            access_token=str(access_token),
            user_id=str(user_id),
        )
    elif config.top_up_mode == "kubectl":
        top_up = kubectl_top_up(config, str(user_id))

    act_response = session.post(
        urljoin(config.base_url, "internal/agent/act"),
        headers={
            "Authorization": f"Bearer {access_token}",
            "X-Workspace-Id": config.workspace_id,
            "X-LLM-Budget-Id": config.budget_id,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        json=act_payload(config),
        timeout=config.timeout_seconds,
    )
    act_json = act_response.json()
    if act_response.status_code >= 400:
        raise RuntimeError(f"/act failed {act_response.status_code}: {act_json}")

    ledger = kubectl_ledger(config, str(user_id)) if config.ledger_mode == "kubectl" else None
    execution = extract_execution(act_json)
    api_fee_debit = extract_api_fee_debit(act_json)
    errors = validate_smoke(
        execution=execution,
        api_fee_debit=api_fee_debit,
        ledger=ledger,
        allowance_milli=config.allowance_milli,
    )
    if errors:
        raise RuntimeError("; ".join(errors))

    return {
        "ok": True,
        "email": config.email,
        "user_id": user_id,
        "workspace_id": config.workspace_id,
        "top_up": top_up,
        "execution": {
            "provider": execution.get("provider"),
            "credential": execution.get("credential"),
            "bill_to": execution.get("bill_to"),
        },
        "api_fee_debit": api_fee_debit,
        "ledger": ledger,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    username, email, password = random_identity()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("BR_SMOKE_BASE_URL", "https://brain-researcher.com"),
    )
    parser.add_argument("--email", default=os.getenv("BR_SMOKE_EMAIL", email))
    parser.add_argument("--password", default=os.getenv("BR_SMOKE_PASSWORD", password))
    parser.add_argument("--username", default=os.getenv("BR_SMOKE_USERNAME", username))
    parser.add_argument("--no-signup", action="store_true")
    parser.add_argument("--workspace-id", default=os.getenv("BR_SMOKE_WORKSPACE_ID"))
    parser.add_argument("--month", default=os.getenv("BR_SMOKE_MONTH", current_month()))
    parser.add_argument("--allowance", type=float, default=10.0)
    parser.add_argument("--cap", type=float, default=10.0)
    parser.add_argument("--session-id", default=os.getenv("BR_SMOKE_SESSION_ID"))
    parser.add_argument("--budget-id", default=os.getenv("BR_SMOKE_BUDGET_ID"))
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument(
        "--top-up-mode",
        choices=("kubectl", "api", "skip"),
        default=os.getenv("BR_SMOKE_TOP_UP_MODE", "kubectl"),
    )
    parser.add_argument(
        "--ledger-mode",
        choices=("kubectl", "skip"),
        default=os.getenv("BR_SMOKE_LEDGER_MODE", "kubectl"),
    )
    parser.add_argument("--gcp-project", default=os.getenv("BR_SMOKE_GCP_PROJECT"))
    parser.add_argument("--gcp-zone", default=os.getenv("BR_SMOKE_GCP_ZONE"))
    parser.add_argument("--gcp-vm", default=os.getenv("BR_SMOKE_GCP_VM"))
    parser.add_argument(
        "--namespace",
        default=os.getenv("BR_SMOKE_K8S_NAMESPACE", "brain-researcher-core"),
    )
    parser.add_argument(
        "--orchestrator-target",
        default=os.getenv(
            "BR_SMOKE_ORCHESTRATOR_TARGET",
            "deployment/brain-researcher-orchestrator",
        ),
    )
    parser.add_argument("--timeout-seconds", type=int, default=180)
    return parser.parse_args(argv)


def config_from_args(args: argparse.Namespace) -> SmokeConfig:
    workspace_id = args.workspace_id or str(uuid.uuid4())
    session_id = args.session_id or f"api-usd-smoke-{secrets.token_hex(5)}"
    budget_id = args.budget_id or f"api-usd-budget-{secrets.token_hex(5)}"
    return SmokeConfig(
        base_url=normalize_base_url(args.base_url),
        email=args.email,
        password=args.password,
        username=args.username,
        signup=not bool(args.no_signup),
        workspace_id=workspace_id,
        month=args.month,
        allowance_milli=usd_to_milli(args.allowance),
        cap_milli=usd_to_milli(args.cap),
        session_id=session_id,
        budget_id=budget_id,
        query=args.query,
        top_up_mode=args.top_up_mode,
        ledger_mode=args.ledger_mode,
        gcp_project=args.gcp_project,
        gcp_zone=args.gcp_zone,
        gcp_vm=args.gcp_vm,
        namespace=args.namespace,
        orchestrator_target=args.orchestrator_target,
        timeout_seconds=args.timeout_seconds,
    )


def main(argv: Sequence[str] | None = None) -> int:
    config = config_from_args(parse_args(argv))
    result = run_smoke(config)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        raise SystemExit(1)
