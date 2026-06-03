"""Runtime compatibility patches for Notebook Intelligence integrations."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _snapshot_notebooks(root_dir: Path) -> dict[str, int]:
    if not root_dir.exists():
        return {}
    snapshots: dict[str, int] = {}
    for path in root_dir.rglob("*.ipynb"):
        try:
            rel_path = path.relative_to(root_dir).as_posix()
            snapshots[rel_path] = path.stat().st_mtime_ns
        except OSError:
            continue
    return snapshots


def _normalize_notebook_path(root_dir: Path, raw_path: str | None) -> str | None:
    if not raw_path:
        return None

    path = Path(str(raw_path)).expanduser()
    if not path.is_absolute():
        return path.as_posix()

    try:
        return path.resolve().relative_to(root_dir.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def _extract_path_from_ui_result(root_dir: Path, result: Any) -> str | None:
    if isinstance(result, dict):
        for key in ("path", "file_path", "filepath", "name"):
            value = result.get(key)
            normalized = _normalize_notebook_path(root_dir, value)
            if normalized:
                return normalized
    return None


def _infer_created_notebook_path(
    before: dict[str, int],
    after: dict[str, int],
) -> str | None:
    candidates: list[tuple[int, str]] = []
    for rel_path, mtime_ns in after.items():
        if rel_path not in before or mtime_ns > before.get(rel_path, -1):
            candidates.append((mtime_ns, rel_path))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def _is_placeholder_ui_result(result: Any) -> bool:
    return isinstance(result, str) and result.strip() == "Could not serialize the result"


async def _resolve_notebook_path_after_ui_command(
    root_dir: Path,
    before: dict[str, int],
    *,
    retries: int = 20,
    delay_seconds: float = 0.1,
) -> str | None:
    for _ in range(max(retries, 1)):
        inferred = _infer_created_notebook_path(before, _snapshot_notebooks(root_dir))
        if inferred:
            return inferred
        await asyncio.sleep(delay_seconds)
    return None


async def _wait_for_notebook_path(
    root_dir: Path,
    rel_path: str,
    *,
    retries: int = 20,
    delay_seconds: float = 0.1,
) -> bool:
    target_path = root_dir / rel_path
    for _ in range(max(retries, 1)):
        if target_path.exists():
            return True
        await asyncio.sleep(delay_seconds)
    return False


def _sdk_tool_result_error_message(result: dict[str, Any]) -> str:
    content = result.get("content")
    if isinstance(content, list):
        texts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if text is not None:
                    texts.append(str(text))
        if texts:
            return "\n".join(texts)
    return "SDK MCP tool reported an error"


def _sdk_tool_result_to_lowlevel_response(result: Any) -> Any:
    if not isinstance(result, dict) or "content" not in result:
        return result

    from mcp.types import AudioContent, ImageContent, TextContent

    content: list[Any] = []
    for item in result.get("content") or []:
        if not isinstance(item, dict):
            content.append(item)
            continue

        item_type = item.get("type")
        if item_type == "text":
            content.append(TextContent(type="text", text=str(item.get("text", ""))))
        elif item_type == "image":
            content.append(
                ImageContent(
                    type="image",
                    data=item["data"],
                    mimeType=item["mimeType"],
                )
            )
        elif item_type == "audio":
            content.append(
                AudioContent(
                    type="audio",
                    data=item["data"],
                    mimeType=item["mimeType"],
                )
            )
        elif item_type == "resource_link":
            parts = []
            link_name = item.get("name")
            uri = item.get("uri")
            description = item.get("description")
            if link_name:
                parts.append(str(link_name))
            if uri:
                parts.append(str(uri))
            if description:
                parts.append(str(description))
            content.append(
                TextContent(
                    type="text",
                    text="\n".join(parts) if parts else "Resource link",
                )
            )
        elif item_type == "resource":
            resource = item.get("resource") or {}
            if isinstance(resource, dict) and "text" in resource:
                content.append(TextContent(type="text", text=str(resource["text"])))
            else:
                logger.warning(
                    "Binary embedded resource cannot be converted to text, skipping"
                )
        else:
            logger.warning(
                "Unsupported content type %r in SDK tool result, skipping",
                item_type,
            )

    if result.get("is_error", False):
        raise RuntimeError(_sdk_tool_result_error_message(result))

    structured_content = result.get("structuredContent")
    if structured_content is None:
        structured_content = result.get("structured_content")
    if structured_content is not None:
        return content, structured_content
    return content


def apply_notebook_intelligence_runtime_patches() -> None:
    """Install BR runtime patches for Notebook Intelligence when available."""

    try:
        import claude_agent_sdk
        import notebook_intelligence.claude as nbi_claude
    except Exception as exc:  # pragma: no cover - optional dependency
        logger.debug("Notebook Intelligence Claude module unavailable: %s", exc)
        return

    create_sdk_mcp_server = getattr(claude_agent_sdk, "create_sdk_mcp_server", None)
    if callable(create_sdk_mcp_server) and not getattr(
        create_sdk_mcp_server, "_brain_researcher_patched", False
    ):
        sdk_globals = create_sdk_mcp_server.__globals__
        is_typeddict = sdk_globals["is_typeddict"]
        python_type_to_json_schema = sdk_globals["_python_type_to_json_schema"]
        typeddict_to_json_schema = sdk_globals["_typeddict_to_json_schema"]

        def _patched_create_sdk_mcp_server(
            name: str,
            version: str = "1.0.0",
            tools: list[Any] | None = None,
        ) -> dict[str, Any]:
            from mcp.server import Server
            from mcp.types import Tool

            server = Server(name, version=version)
            if tools:
                tool_map = {tool_def.name: tool_def for tool_def in tools}

                def _build_schema(tool_def: Any) -> dict[str, Any]:
                    if isinstance(tool_def.input_schema, dict):
                        if (
                            "type" in tool_def.input_schema
                            and "properties" in tool_def.input_schema
                            and isinstance(tool_def.input_schema["type"], str)
                        ):
                            return tool_def.input_schema
                        properties = {}
                        for param_name, param_type in tool_def.input_schema.items():
                            properties[param_name] = python_type_to_json_schema(
                                param_type
                            )
                        return {
                            "type": "object",
                            "properties": properties,
                            "required": list(properties.keys()),
                        }
                    if is_typeddict(tool_def.input_schema):
                        return typeddict_to_json_schema(tool_def.input_schema)
                    return {"type": "object", "properties": {}}

                cached_tool_list = [
                    Tool(
                        name=tool_def.name,
                        description=tool_def.description,
                        inputSchema=_build_schema(tool_def),
                        annotations=tool_def.annotations,
                    )
                    for tool_def in tools
                ]

                @server.list_tools()  # type: ignore[no-untyped-call,untyped-decorator]
                async def list_tools() -> list[Tool]:
                    return cached_tool_list

                @server.call_tool()  # type: ignore[untyped-decorator]
                async def call_tool(name: str, arguments: dict[str, Any]) -> Any:
                    if name not in tool_map:
                        raise ValueError(f"Tool '{name}' not found")
                    result = await tool_map[name].handler(arguments)
                    return _sdk_tool_result_to_lowlevel_response(result)

            return claude_agent_sdk.McpSdkServerConfig(
                type="sdk",
                name=name,
                instance=server,
            )

        _patched_create_sdk_mcp_server._brain_researcher_patched = True
        claude_agent_sdk.create_sdk_mcp_server = _patched_create_sdk_mcp_server
        nbi_claude.create_sdk_mcp_server = _patched_create_sdk_mcp_server

    create_new_notebook = getattr(nbi_claude, "create_new_notebook", None)
    rename_notebook = getattr(nbi_claude, "rename_notebook", None)
    open_file_in_jupyter_ui = getattr(nbi_claude, "open_file_in_jupyter_ui", None)
    if (
        create_new_notebook is None
        or getattr(create_new_notebook, "_brain_researcher_patched", False)
    ) and (
        rename_notebook is None
        or getattr(rename_notebook, "_brain_researcher_patched", False)
    ) and (
        open_file_in_jupyter_ui is None
        or getattr(open_file_in_jupyter_ui, "_brain_researcher_patched", False)
    ):
        return

    async def _patched_create_new_notebook(args) -> dict[str, Any]:
        response = nbi_claude.get_current_response()
        if response is None:
            raise RuntimeError("Notebook Intelligence response context is unavailable")

        root_dir_value = nbi_claude.get_jupyter_root_dir() or "."
        root_dir = Path(str(root_dir_value)).expanduser()
        before = _snapshot_notebooks(root_dir)

        ui_cmd_response = await response.run_ui_command(
            "notebook-intelligence:create-new-notebook-from-py",
            {"code": ""},
        )
        file_path = _extract_path_from_ui_result(root_dir, ui_cmd_response)
        if file_path is None:
            file_path = await _resolve_notebook_path_after_ui_command(root_dir, before)

        if file_path is None:
            raise RuntimeError(
                "Notebook Intelligence created a notebook but did not return a "
                "serializable path, and Brain Researcher could not infer the new "
                "notebook file from the workspace."
            )

        logger.info(
            "Recovered notebook path for NBI create-new-notebook tool via runtime patch: %s",
            file_path,
        )
        return nbi_claude.tool_text_response(f"Created new notebook at {file_path}")

    if create_new_notebook is not None and not getattr(
        create_new_notebook, "_brain_researcher_patched", False
    ):
        create_new_notebook.handler = _patched_create_new_notebook
        create_new_notebook._brain_researcher_patched = True

    if rename_notebook is not None and not getattr(
        rename_notebook, "_brain_researcher_patched", False
    ):

        async def _patched_rename_notebook(args) -> dict[str, Any]:
            response = nbi_claude.get_current_response()
            if response is None:
                raise RuntimeError(
                    "Notebook Intelligence response context is unavailable"
                )

            new_name = str(args.get("new_name", "")).strip()
            ui_cmd_response = await response.run_ui_command(
                "notebook-intelligence:rename-notebook",
                {"newName": new_name},
            )
            if not _is_placeholder_ui_result(ui_cmd_response):
                return nbi_claude.tool_text_response(ui_cmd_response)

            root_dir_value = nbi_claude.get_jupyter_root_dir() or "."
            root_dir = Path(str(root_dir_value)).expanduser()
            normalized = _normalize_notebook_path(root_dir, new_name) or new_name
            await _wait_for_notebook_path(root_dir, normalized)
            logger.info(
                "Recovered success status for NBI rename-notebook tool via runtime patch: %s",
                normalized,
            )
            return nbi_claude.tool_text_response(f"Renamed notebook to {normalized}")

        rename_notebook.handler = _patched_rename_notebook
        rename_notebook._brain_researcher_patched = True

    if open_file_in_jupyter_ui is not None and not getattr(
        open_file_in_jupyter_ui, "_brain_researcher_patched", False
    ):

        async def _patched_open_file_in_jupyter_ui(args) -> dict[str, Any]:
            response = nbi_claude.get_current_response()
            if response is None:
                raise RuntimeError(
                    "Notebook Intelligence response context is unavailable"
                )

            file_path = str(args.get("file_path", "")).strip()
            ui_cmd_response = await response.run_ui_command(
                "docmanager:open",
                {"path": file_path},
            )
            if not _is_placeholder_ui_result(ui_cmd_response):
                return nbi_claude.tool_text_response(ui_cmd_response)

            logger.info(
                "Recovered success status for NBI open-file-in-jupyter-ui tool via runtime patch: %s",
                file_path,
            )
            return nbi_claude.tool_text_response(
                f"Opened file in Jupyter UI: {file_path}"
            )

        open_file_in_jupyter_ui.handler = _patched_open_file_in_jupyter_ui
        open_file_in_jupyter_ui._brain_researcher_patched = True
