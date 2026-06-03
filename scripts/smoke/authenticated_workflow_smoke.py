#!/usr/bin/env python3
"""Authenticated ds000114 workflow smoke for demo/prod environments.

Safe default: this script logs in and runs preflight only. It launches a workflow
only when --launch or BR_WORKFLOW_SMOKE_LAUNCH=1 is set. It grants workflow
credits only when --grant-credit or BR_WORKFLOW_SMOKE_GRANT_CREDIT=1 is set and
BR_WORKFLOW_SMOKE_ALLOW_CREDIT_GRANT=1 is also set.

Common environment variables:
  BR_WORKFLOW_SMOKE_BASE_URL=https://${PUBLIC_HOSTNAME}
  BR_WORKFLOW_SMOKE_EMAIL=...
  BR_WORKFLOW_SMOKE_PASSWORD=...
  BR_WORKFLOW_SMOKE_WORKSPACE_ID=...
  BR_WORKFLOW_SMOKE_LAUNCH=1
  BR_WORKFLOW_SMOKE_GRANT_CREDIT=1
  BR_WORKFLOW_SMOKE_ALLOW_CREDIT_GRANT=1
  BR_WORKFLOW_SMOKE_IMG=/app/data/OpenNeuroDerivatives/fmriprep/ds000114-fmriprep/...
  BR_WORKFLOW_SMOKE_ATLAS_PATH=/app/data/atlases/schaefer_2018/...
  BR_WORKFLOW_SMOKE_REQUIRED_OUTPUTS=timeseries/timeseries.npy,timeseries/timeseries.csv,connectivity_matrix.npy
  BR_WORKFLOW_SMOKE_SUMMARY_PATH=/tmp/br-workflow-smoke.json
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import requests

DEFAULT_BASE_URL = "https://${PUBLIC_HOSTNAME}"
DEFAULT_DATASET_ID = "ds000114"
DEFAULT_WORKFLOW_ID = "workflow_rest_connectome_e2e"
DEFAULT_REQUIRED_OUTPUTS = (
    "timeseries/timeseries.npy",
    "timeseries/timeseries.csv",
    "connectivity_matrix.npy",
)
DEFAULT_IMG = (
    "/app/data/OpenNeuroDerivatives/fmriprep/ds000114-fmriprep/"
    "sub-01/ses-test/func/"
    "sub-01_ses-test_task-linebisection_space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz"
)
DEFAULT_ATLAS_NAME = "Schaefer2018_100"
DEFAULT_ATLAS_PATH = (
    "/app/data/atlases/schaefer_2018/"
    "Schaefer2018_100Parcels_7Networks_order_FSLMNI152_2mm.nii.gz"
)
DEFAULT_OUTPUT_DIR = "outputs/workflow_rest_connectome_e2e_smoke"
TERMINAL_STATUSES = {"completed", "failed", "cancelled", "timeout"}


@dataclass(frozen=True)
class AuthContext:
    access_token: str | None
    user_id: str | None
    session_json: dict[str, Any]


@dataclass(frozen=True)
class SmokeConfig:
    base_url: str
    email: str | None
    password: str | None
    workspace_id: str | None
    project_id: str
    workflow_id: str
    dataset_id: str
    img: str
    output_dir: str
    atlas_name: str
    atlas_path: str | None
    connectivity_kind: str
    standardize: bool
    detrend: bool
    fisher_z: bool
    t_r: float | None
    low_pass: float | None
    high_pass: float | None
    strict_preflight: bool
    launch: bool
    credit_grant_requested: bool
    grant_credit: bool
    credit_amount: float
    required_outputs: tuple[str, ...]
    request_timeout_seconds: float
    poll_timeout_seconds: float
    poll_interval_seconds: float
    run_tag: str
    title: str
    summary_path: str | None


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def normalize_base_url(value: str) -> str:
    return value.rstrip("/") + "/"


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"expected a boolean value, got {value!r}")


def parse_optional_float(value: str | None) -> float | None:
    if value is None:
        return None
    stripped = str(value).strip()
    if not stripped:
        return None
    return float(stripped)


def split_csv(value: str | None, fallback: Iterable[str]) -> tuple[str, ...]:
    if value is None:
        return tuple(fallback)
    items = tuple(item.strip() for item in value.split(",") if item.strip())
    return items or tuple(fallback)


def config_summary(config: SmokeConfig) -> dict[str, Any]:
    return {
        "base_url": config.base_url,
        "workflow_id": config.workflow_id,
        "dataset_id": config.dataset_id,
        "workspace_id": config.workspace_id,
        "project_id": config.project_id,
        "launch": config.launch,
        "grant_credit": config.grant_credit,
        "credit_grant_requested": config.credit_grant_requested,
        "strict_preflight": config.strict_preflight,
        "img": config.img,
        "output_dir": config.output_dir,
        "atlas_name": config.atlas_name,
        "atlas_path": config.atlas_path,
        "required_outputs": list(config.required_outputs),
        "poll_timeout_seconds": config.poll_timeout_seconds,
        "poll_interval_seconds": config.poll_interval_seconds,
        "run_tag": config.run_tag,
    }


def workflow_params(config: SmokeConfig) -> dict[str, Any]:
    params: dict[str, Any] = {
        "dataset_id": config.dataset_id,
        "workflow_id": config.workflow_id,
        "img": config.img,
        "output_dir": config.output_dir,
        "atlas_name": config.atlas_name,
        "connectivity_kind": config.connectivity_kind,
        "standardize": config.standardize,
        "detrend": config.detrend,
        "fisher_z": config.fisher_z,
    }
    if config.atlas_path:
        params["atlas_path"] = config.atlas_path
    if config.t_r is not None:
        params["t_r"] = config.t_r
    if config.low_pass is not None:
        params["low_pass"] = config.low_pass
    if config.high_pass is not None:
        params["high_pass"] = config.high_pass
    return params


def build_preflight_payload(config: SmokeConfig) -> dict[str, Any]:
    return {"params": workflow_params(config), "strict": config.strict_preflight}


def build_launch_payload(config: SmokeConfig) -> dict[str, Any]:
    prompt = (
        f"Run {config.workflow_id} on {config.dataset_id} as an authenticated smoke. "
        "Use the provided BOLD image and verify the connectome outputs."
    )
    return {
        "dataset_id": config.dataset_id,
        "analysis_id": "dynamic_workflow",
        "pipeline_id": config.workflow_id,
        "template_id": f"dynamic_workflow/{config.workflow_id}",
        "project_id": config.project_id,
        "title": config.title,
        "prompt": prompt,
        "parameters": workflow_params(config),
        "thread": {"mode": "none"},
    }


def response_json(response: requests.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {"_raw": response.text}
    return payload if isinstance(payload, dict) else {"value": payload}


def require_http_ok(response: requests.Response, label: str) -> dict[str, Any]:
    body = response_json(response)
    if response.status_code >= 400:
        raise RuntimeError(f"{label} failed HTTP {response.status_code}: {body}")
    return body


def auth_headers(config: SmokeConfig, auth: AuthContext) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if auth.access_token:
        headers["Authorization"] = f"Bearer {auth.access_token}"
    if config.workspace_id:
        headers["X-Workspace-Id"] = config.workspace_id
    return headers


def extract_user_id(session_json: dict[str, Any]) -> str | None:
    user = session_json.get("user")
    if isinstance(user, dict) and user.get("id"):
        return str(user["id"])
    return None


def login(session: requests.Session, config: SmokeConfig) -> AuthContext:
    if not config.email or not config.password:
        raise RuntimeError(
            "BR_WORKFLOW_SMOKE_EMAIL and BR_WORKFLOW_SMOKE_PASSWORD are required."
        )

    csrf_response = session.get(
        urljoin(config.base_url, "api/auth/csrf"),
        timeout=config.request_timeout_seconds,
    )
    csrf_json = require_http_ok(csrf_response, "NextAuth CSRF")
    csrf_token = csrf_json.get("csrfToken")
    if not csrf_token:
        raise RuntimeError(f"missing NextAuth csrf token: {csrf_json}")

    auth_response = session.post(
        urljoin(config.base_url, "api/auth/callback/credentials"),
        data={
            "csrfToken": csrf_token,
            "email": config.email,
            "password": config.password,
            "callbackUrl": urljoin(config.base_url, "studio"),
            "json": "true",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=config.request_timeout_seconds,
    )
    auth_json = require_http_ok(auth_response, "NextAuth credentials login")
    if auth_json.get("error"):
        raise RuntimeError(f"NextAuth credentials login failed: {auth_json}")

    session_json: dict[str, Any] = {}
    for _ in range(20):
        session_response = session.get(
            urljoin(config.base_url, "api/auth/session"),
            timeout=config.request_timeout_seconds,
        )
        session_json = require_http_ok(session_response, "NextAuth session")
        access_token = session_json.get("accessToken")
        user_id = extract_user_id(session_json)
        if access_token or user_id:
            return AuthContext(
                access_token=str(access_token) if access_token else None,
                user_id=user_id,
                session_json=session_json,
            )
        time.sleep(1)

    raise RuntimeError(
        f"session did not expose an authenticated identity: {session_json}"
    )


def run_preflight(
    session: requests.Session,
    config: SmokeConfig,
    auth: AuthContext,
) -> dict[str, Any]:
    headers = auth_headers(config, auth)
    headers["Content-Type"] = "application/json"
    response = session.post(
        urljoin(
            config.base_url,
            f"api/workflows/{config.workflow_id}/preflight",
        ),
        headers=headers,
        json=build_preflight_payload(config),
        timeout=config.request_timeout_seconds,
    )
    payload = require_http_ok(response, "workflow preflight")
    if config.strict_preflight and payload.get("ok") is not True:
        raise RuntimeError(f"workflow preflight was not executable: {payload}")
    return payload


def grant_workflow_credit(
    session: requests.Session,
    config: SmokeConfig,
    auth: AuthContext,
) -> dict[str, Any]:
    headers = auth_headers(config, auth)
    headers["Content-Type"] = "application/json"
    payload = {
        "workspace_id": config.workspace_id,
        "user_id": auth.user_id,
        "amount": config.credit_amount,
        "reason": f"workflow-smoke:{config.workflow_id}",
        "idempotency_key": f"workflow-smoke:{config.workflow_id}:{config.run_tag}",
        "metadata": {
            "source": "scripts/smoke/authenticated_workflow_smoke.py",
            "workflow_id": config.workflow_id,
            "dataset_id": config.dataset_id,
            "run_tag": config.run_tag,
        },
    }
    response = session.post(
        urljoin(config.base_url, "api/credits/grants"),
        headers=headers,
        json=payload,
        timeout=config.request_timeout_seconds,
    )
    return require_http_ok(response, "workflow credit grant")


def launch_analysis(
    session: requests.Session,
    config: SmokeConfig,
    auth: AuthContext,
) -> dict[str, Any]:
    headers = auth_headers(config, auth)
    headers["Content-Type"] = "application/json"
    response = session.post(
        urljoin(config.base_url, "api/analyses"),
        headers=headers,
        json=build_launch_payload(config),
        timeout=config.request_timeout_seconds,
    )
    return require_http_ok(response, "analysis launch")


def detail_output_strings(detail: dict[str, Any]) -> list[str]:
    strings: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, str):
            strings.append(value)
            return
        if isinstance(value, dict):
            for nested in value.values():
                visit(nested)
            return
        if isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(
        {
            "artifacts": detail.get("artifacts"),
            "runcard": detail.get("runcard"),
            "artifact_contract": detail.get("artifact_contract"),
        }
    )
    return strings


def output_matches(required_output: str, observed: str) -> bool:
    required = required_output.strip().lstrip("/")
    value = observed.strip()
    return (
        value == required
        or value.endswith("/" + required)
        or required in value.split("?")[0]
    )


def assert_required_outputs(
    detail: dict[str, Any],
    required_outputs: Iterable[str],
) -> dict[str, Any]:
    observed = detail_output_strings(detail)
    matches: dict[str, list[str]] = {}
    missing: list[str] = []
    for required in required_outputs:
        hits = [value for value in observed if output_matches(required, value)]
        if hits:
            matches[required] = hits[:5]
        else:
            missing.append(required)
    payload = {"ok": not missing, "matches": matches, "missing": missing}
    if missing:
        raise RuntimeError(f"analysis detail missing required outputs: {missing}")
    return payload


def fetch_analysis_detail(
    session: requests.Session,
    config: SmokeConfig,
    auth: AuthContext,
    analysis_id: str,
) -> dict[str, Any]:
    response = session.get(
        urljoin(config.base_url, f"api/analyses/{analysis_id}"),
        headers=auth_headers(config, auth),
        timeout=config.request_timeout_seconds,
    )
    return require_http_ok(response, "analysis detail")


def poll_analysis(
    session: requests.Session,
    config: SmokeConfig,
    auth: AuthContext,
    analysis_id: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + config.poll_timeout_seconds
    attempts = 0
    last_detail: dict[str, Any] | None = None
    while time.monotonic() <= deadline:
        attempts += 1
        detail = fetch_analysis_detail(session, config, auth, analysis_id)
        last_detail = detail
        status = str(detail.get("status") or "").strip().lower()
        print(
            json.dumps(
                {
                    "event": "poll",
                    "analysis_id": analysis_id,
                    "status": status,
                    "attempt": attempts,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        if status in TERMINAL_STATUSES:
            return {"attempts": attempts, "detail": detail}
        time.sleep(config.poll_interval_seconds)

    raise RuntimeError(
        f"analysis {analysis_id} did not reach terminal status after "
        f"{attempts} attempts; last detail: {last_detail}"
    )


def run_smoke(config: SmokeConfig) -> dict[str, Any]:
    session = requests.Session()
    session.headers.update({"User-Agent": "br-authenticated-workflow-smoke/1"})

    auth = login(session, config)
    preflight = run_preflight(session, config, auth)

    result: dict[str, Any] = {
        "ok": True,
        "mode": "launch" if config.launch else "preflight",
        "config": config_summary(config),
        "auth": {
            "user_id": auth.user_id,
            "has_access_token": bool(auth.access_token),
        },
        "preflight": {
            "ok": preflight.get("ok"),
            "workflow_id": preflight.get("workflow_id"),
            "strict": preflight.get("strict"),
            "warnings": preflight.get("warnings") or [],
            "missing_contract_fields": preflight.get("missing_contract_fields") or [],
        },
    }

    if not config.launch:
        result["launch"] = {"skipped": True, "reason": "launch flag not set"}
        if config.credit_grant_requested:
            result["credit_grant"] = {
                "skipped": True,
                "reason": "dry run does not grant credits",
            }
        return result

    if config.grant_credit:
        result["credit_grant"] = grant_workflow_credit(session, config, auth)
    elif config.credit_grant_requested:
        result["credit_grant"] = {
            "skipped": True,
            "reason": "credit grant request was not effective",
        }

    launch = launch_analysis(session, config, auth)
    analysis_id = str(
        launch.get("analysis_id") or launch.get("job_id") or launch.get("run_id") or ""
    ).strip()
    if not analysis_id:
        raise RuntimeError(f"analysis launch did not return an analysis id: {launch}")

    poll = poll_analysis(session, config, auth, analysis_id)
    detail = poll["detail"]
    status = str(detail.get("status") or "").strip().lower()
    if status != "completed":
        raise RuntimeError(
            f"analysis {analysis_id} finished with status {status}: {detail}"
        )

    output_assertions = assert_required_outputs(detail, config.required_outputs)
    result["launch"] = {
        "analysis_id": analysis_id,
        "status": launch.get("status"),
        "links": launch.get("links"),
        "warnings": launch.get("warnings") or [],
    }
    result["poll"] = {"attempts": poll["attempts"], "terminal_status": status}
    result["outputs"] = output_assertions
    return result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("BR_WORKFLOW_SMOKE_BASE_URL", DEFAULT_BASE_URL),
    )
    parser.add_argument("--email", default=os.getenv("BR_WORKFLOW_SMOKE_EMAIL"))
    parser.add_argument("--password", default=os.getenv("BR_WORKFLOW_SMOKE_PASSWORD"))
    parser.add_argument(
        "--workspace-id",
        default=os.getenv("BR_WORKFLOW_SMOKE_WORKSPACE_ID"),
    )
    parser.add_argument(
        "--project-id",
        default=os.getenv("BR_WORKFLOW_SMOKE_PROJECT_ID", "smoke"),
    )
    parser.add_argument(
        "--workflow-id",
        default=os.getenv("BR_WORKFLOW_SMOKE_WORKFLOW_ID", DEFAULT_WORKFLOW_ID),
    )
    parser.add_argument(
        "--dataset-id",
        default=os.getenv("BR_WORKFLOW_SMOKE_DATASET_ID", DEFAULT_DATASET_ID),
    )
    parser.add_argument(
        "--img", default=os.getenv("BR_WORKFLOW_SMOKE_IMG", DEFAULT_IMG)
    )
    parser.add_argument(
        "--output-dir",
        default=os.getenv("BR_WORKFLOW_SMOKE_OUTPUT_DIR", DEFAULT_OUTPUT_DIR),
    )
    parser.add_argument(
        "--atlas-name",
        default=os.getenv("BR_WORKFLOW_SMOKE_ATLAS_NAME", DEFAULT_ATLAS_NAME),
    )
    parser.add_argument(
        "--atlas-path",
        default=os.getenv("BR_WORKFLOW_SMOKE_ATLAS_PATH", DEFAULT_ATLAS_PATH),
    )
    parser.add_argument(
        "--connectivity-kind",
        default=os.getenv("BR_WORKFLOW_SMOKE_CONNECTIVITY_KIND", "correlation"),
    )
    parser.add_argument(
        "--standardize",
        type=parse_bool,
        default=parse_bool(os.getenv("BR_WORKFLOW_SMOKE_STANDARDIZE", "true")),
    )
    parser.add_argument(
        "--detrend",
        type=parse_bool,
        default=parse_bool(os.getenv("BR_WORKFLOW_SMOKE_DETREND", "true")),
    )
    parser.add_argument(
        "--fisher-z",
        type=parse_bool,
        default=parse_bool(os.getenv("BR_WORKFLOW_SMOKE_FISHER_Z", "true")),
    )
    parser.add_argument(
        "--t-r",
        type=float,
        default=parse_optional_float(os.getenv("BR_WORKFLOW_SMOKE_T_R")),
    )
    parser.add_argument(
        "--low-pass",
        type=float,
        default=parse_optional_float(os.getenv("BR_WORKFLOW_SMOKE_LOW_PASS")),
    )
    parser.add_argument(
        "--high-pass",
        type=float,
        default=parse_optional_float(os.getenv("BR_WORKFLOW_SMOKE_HIGH_PASS")),
    )
    parser.set_defaults(
        strict_preflight=env_flag("BR_WORKFLOW_SMOKE_STRICT_PREFLIGHT", True),
        launch=env_flag("BR_WORKFLOW_SMOKE_LAUNCH", False),
        grant_credit=env_flag("BR_WORKFLOW_SMOKE_GRANT_CREDIT", False),
    )
    parser.add_argument(
        "--strict-preflight", dest="strict_preflight", action="store_true"
    )
    parser.add_argument(
        "--non-strict-preflight",
        dest="strict_preflight",
        action="store_false",
    )
    parser.add_argument("--launch", dest="launch", action="store_true")
    parser.add_argument("--dry-run", dest="launch", action="store_false")
    parser.add_argument("--grant-credit", dest="grant_credit", action="store_true")
    parser.add_argument("--no-grant-credit", dest="grant_credit", action="store_false")
    parser.add_argument(
        "--credit-amount",
        type=float,
        default=float(os.getenv("BR_WORKFLOW_SMOKE_CREDIT_AMOUNT", "1.0")),
    )
    parser.add_argument(
        "--required-outputs",
        default=os.getenv("BR_WORKFLOW_SMOKE_REQUIRED_OUTPUTS"),
    )
    parser.add_argument(
        "--request-timeout-seconds",
        type=float,
        default=float(os.getenv("BR_WORKFLOW_SMOKE_REQUEST_TIMEOUT_SECONDS", "60")),
    )
    parser.add_argument(
        "--poll-timeout-seconds",
        type=float,
        default=float(os.getenv("BR_WORKFLOW_SMOKE_POLL_TIMEOUT_SECONDS", "1800")),
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=float(os.getenv("BR_WORKFLOW_SMOKE_POLL_INTERVAL_SECONDS", "10")),
    )
    parser.add_argument("--run-tag", default=os.getenv("BR_WORKFLOW_SMOKE_RUN_TAG"))
    parser.add_argument("--title", default=os.getenv("BR_WORKFLOW_SMOKE_TITLE"))
    parser.add_argument(
        "--summary-path",
        default=os.getenv("BR_WORKFLOW_SMOKE_SUMMARY_PATH"),
    )
    return parser.parse_args(argv)


def config_from_args(args: argparse.Namespace) -> SmokeConfig:
    credit_grant_requested = bool(args.grant_credit)
    allow_credit_grant = env_flag("BR_WORKFLOW_SMOKE_ALLOW_CREDIT_GRANT", False)
    if credit_grant_requested and not allow_credit_grant:
        raise ValueError(
            "Credit grant requested, but BR_WORKFLOW_SMOKE_ALLOW_CREDIT_GRANT=1 "
            "is required before this script may mutate credits."
        )

    run_tag = args.run_tag or f"workflow-smoke-{utc_stamp()}-{secrets.token_hex(4)}"
    title = args.title or f"Smoke {args.workflow_id} {run_tag}"
    return SmokeConfig(
        base_url=normalize_base_url(str(args.base_url)),
        email=args.email,
        password=args.password,
        workspace_id=args.workspace_id,
        project_id=str(args.project_id),
        workflow_id=str(args.workflow_id),
        dataset_id=str(args.dataset_id),
        img=str(args.img),
        output_dir=str(args.output_dir),
        atlas_name=str(args.atlas_name),
        atlas_path=str(args.atlas_path).strip() or None,
        connectivity_kind=str(args.connectivity_kind),
        standardize=bool(args.standardize),
        detrend=bool(args.detrend),
        fisher_z=bool(args.fisher_z),
        t_r=args.t_r,
        low_pass=args.low_pass,
        high_pass=args.high_pass,
        strict_preflight=bool(args.strict_preflight),
        launch=bool(args.launch),
        credit_grant_requested=credit_grant_requested,
        grant_credit=bool(args.launch and credit_grant_requested),
        credit_amount=float(args.credit_amount),
        required_outputs=split_csv(args.required_outputs, DEFAULT_REQUIRED_OUTPUTS),
        request_timeout_seconds=float(args.request_timeout_seconds),
        poll_timeout_seconds=float(args.poll_timeout_seconds),
        poll_interval_seconds=float(args.poll_interval_seconds),
        run_tag=run_tag,
        title=title,
        summary_path=args.summary_path,
    )


def write_summary(path: str | None, payload: dict[str, Any]) -> None:
    if not path:
        return
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def main(argv: Sequence[str] | None = None) -> int:
    config = config_from_args(parse_args(argv))
    result = run_smoke(config)
    write_summary(config.summary_path, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        payload = {"ok": False, "error": str(exc)}
        print(json.dumps(payload, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc
