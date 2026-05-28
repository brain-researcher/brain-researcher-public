from __future__ import annotations

from brain_researcher.services.orchestrator.main_enhanced import app


def test_feedback_widget_routes_are_registered() -> None:
    methods_by_path: dict[str, set[str]] = {}
    for route in app.routes:
        route_methods = getattr(route, "methods", None) or set()
        methods_by_path.setdefault(route.path, set()).update(route_methods)

    assert "GET" in methods_by_path.get("/api/feedback", set())
    assert "POST" in methods_by_path.get("/api/feedback", set())
    assert "POST" in methods_by_path.get("/api/feedback/screenshot", set())
    assert "GET" in methods_by_path.get("/api/feedback/screenshot/{screenshot_id}", set())
