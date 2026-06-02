from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_run_gateway_script_is_retired_stub() -> None:
    script = (REPO_ROOT / "scripts" / "run_gateway.sh").read_text(encoding="utf-8")

    assert "scripts/services/run_gateway.sh has been retired." in script
    assert "Gateway is no longer part of the active local service topology." in script
    assert "br serve agent --host 0.0.0.0 --port 8000" in script
    assert "uvicorn" not in script
    assert "brain_researcher.services.gateway.asgi_app:app" not in script


def test_start_services_uses_active_five_service_matrix() -> None:
    script = (REPO_ROOT / "scripts" / "services" / "start_services.sh").read_text(
        encoding="utf-8"
    )

    assert 'start_service "kg" 5000 "http://127.0.0.1:5000/health" 45 \\' in script
    assert (
        'start_service "orchestrator" 3001 "http://127.0.0.1:3001/health" 45 \\'
        in script
    )
    assert 'start_service "agent" 8000 "http://127.0.0.1:8000/health" 45 \\' in script
    assert 'start_service "mcp" 7000 "http://127.0.0.1:7000/healthz" 45 \\' in script
    assert 'start_service "web" 3000 "http://127.0.0.1:3000/api/health" 90 \\' in script
    assert "br serve gateway" not in script


def test_stop_services_uses_active_five_service_matrix() -> None:
    script = (REPO_ROOT / "scripts" / "services" / "stop_services.sh").read_text(
        encoding="utf-8"
    )

    assert 'stop_service "web"' in script
    assert 'stop_service "mcp"' in script
    assert 'stop_service "orchestrator"' in script
    assert 'stop_service "agent"' in script
    assert 'stop_service "kg"' in script
    assert "for port in 3000 7000 3001 8000 5000; do" in script
    assert 'stop_service "Gateway"' not in script


def test_ci_docker_matrix_does_not_build_legacy_api_gateway_image() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert "service: [orchestrator, agent, br_kg, web-ui]" in workflow
    assert "service: [orchestrator, agent, br_kg, web-ui, api-gateway]" not in workflow
    assert "matrix.service == 'api-gateway'" not in workflow


def test_blue_green_rollout_omits_legacy_api_gateway_service() -> None:
    script = (REPO_ROOT / "infrastructure" / "deployment" / "blue_green.sh").read_text(
        encoding="utf-8"
    )

    assert 'SERVICES=("orchestrator" "br_kg" "agent" "web-ui")' in script
    assert '"api-gateway"' not in script


def test_chatbot_start_wrappers_delegate_to_canonical_service_scripts() -> None:
    chatbot = (REPO_ROOT / "scripts" / "start_chatbot.sh").read_text(encoding="utf-8")
    chatbot_ui = (REPO_ROOT / "scripts" / "start_chatbot_ui.sh").read_text(
        encoding="utf-8"
    )

    assert "scripts/services/start_services.sh" in chatbot
    assert "scripts/services/stop_services.sh" in chatbot
    assert "nohup br serve agent" not in chatbot
    assert "nohup br serve orchestrator" not in chatbot
    assert 'exec "${ROOT_DIR}/scripts/services/start_chatbot.sh"' in chatbot_ui
    assert "nohup br serve web" not in chatbot_ui


def test_sync_web_is_explicitly_legacy_and_uses_web_ui_paths() -> None:
    script = (REPO_ROOT / "scripts" / "ops" / "sync_web.sh").read_text(encoding="utf-8")

    assert "Legacy static export sync helper for apps/web-ui." in script
    assert 'SRC_DIR="$ROOT_DIR/apps/web-ui"' in script
    assert (
        'DEST_DIR="${BR_SYNC_WEB_DEST:-$ROOT_DIR/artifacts/web-ui-static-export}"'
        in script
    )
    assert 'SRC_DIR="$ROOT_DIR/apps/web"' not in script
    assert (
        'DEST_DIR="$ROOT_DIR/brain_researcher/services/br_kg/web_public"' not in script
    )
