from brain_researcher.services.orchestrator.marimo_server_patch import (
    patch_providers_source,
)


def test_patch_providers_source_wraps_stream_completion() -> None:
    source = (
        "from marimo._utils.http import HTTPStatus\n"
        "    async def stream_completion(\n"
        "        self,\n"
        "    ) -> StreamingResponse:\n"
        "        event_stream = adapter.run_stream()\n"
        "        return adapter.streaming_response(event_stream)\n"
    )

    patched = patch_providers_source(source)

    assert "wrap_br_tool_name_guardrail_stream" in patched
    assert (
        "        event_stream = "
        "wrap_br_tool_name_guardrail_stream(adapter.run_stream())\n"
        in patched
    )


def test_patch_providers_source_is_idempotent() -> None:
    source = (
        "from marimo._utils.http import HTTPStatus\n"
        "    async def stream_completion(\n"
        "        self,\n"
        "    ) -> StreamingResponse:\n"
        "        event_stream = adapter.run_stream()\n"
        "        return adapter.streaming_response(event_stream)\n"
    )

    once = patch_providers_source(source)
    twice = patch_providers_source(once)

    assert twice == once
