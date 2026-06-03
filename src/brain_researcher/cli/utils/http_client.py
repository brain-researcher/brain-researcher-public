"""
HTTP client utilities for Brain Researcher CLI.

Provides convenient functions for making requests to the orchestrator API
with proper error handling and formatting.
"""

import json
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx
from rich.console import Console

console = Console()


def get_orchestrator_url() -> str:
    """
    Get the orchestrator base URL from environment or use default.

    Returns:
        str: Base URL for the orchestrator API (e.g., http://localhost:3001)
    """
    return (
        os.getenv("BR_ORCHESTRATOR_URL")
        or os.getenv("ORCHESTRATOR_BASE_URL")
        or os.getenv("ORCHESTRATOR_API")
        or os.getenv("ORCHESTRATOR_URL")
        or os.getenv("ORCHESTRATOR_API_URL")
        or "http://localhost:3001"
    )


def format_http_error(response: httpx.Response) -> str:
    """
    Format an HTTP error response into a readable message.

    Args:
        response: The HTTP response object

    Returns:
        str: Formatted error message
    """
    try:
        error_data = response.json()
        if isinstance(error_data, dict) and "detail" in error_data:
            detail = error_data["detail"]
            if isinstance(detail, dict):
                # Structured error with error code
                return f"{detail.get('error', 'Error')}: {detail.get('message', 'Unknown error')}"
            else:
                # Simple string detail
                return str(detail)
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback to status code
    return f"HTTP {response.status_code}: {response.reason_phrase}"


async def api_get(
    path: str, params: dict[str, Any] | None = None, timeout: float = 30.0
) -> dict[str, Any]:
    """
    Make a GET request to the orchestrator API.

    Args:
        path: API path (e.g., "/api/jobs/run_123")
        params: Optional query parameters
        timeout: Request timeout in seconds

    Returns:
        Dict: JSON response data

    Raises:
        httpx.HTTPStatusError: On HTTP errors
        httpx.ConnectError: On connection errors
    """
    base_url = get_orchestrator_url()
    url = f"{base_url}{path}"

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        error_msg = format_http_error(e.response)
        console.print(f"[red]Error:[/red] {error_msg}")
        raise
    except httpx.ConnectError:
        console.print(
            f"[red]Error:[/red] Could not connect to orchestrator at {base_url}"
        )
        console.print(
            "[yellow]Tip:[/yellow] Start the orchestrator with: [cyan]br serve orchestrator[/cyan]"
        )
        raise


async def api_post(
    path: str, json_data: dict[str, Any], timeout: float = 30.0
) -> dict[str, Any]:
    """
    Make a POST request to the orchestrator API.

    Args:
        path: API path (e.g., "/run")
        json_data: JSON payload
        timeout: Request timeout in seconds

    Returns:
        Dict: JSON response data

    Raises:
        httpx.HTTPStatusError: On HTTP errors
        httpx.ConnectError: On connection errors
    """
    base_url = get_orchestrator_url()
    url = f"{base_url}{path}"

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=json_data)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        error_msg = format_http_error(e.response)
        console.print(f"[red]Error:[/red] {error_msg}")
        raise
    except httpx.ConnectError:
        console.print(
            f"[red]Error:[/red] Could not connect to orchestrator at {base_url}"
        )
        console.print(
            "[yellow]Tip:[/yellow] Start the orchestrator with: [cyan]br serve orchestrator[/cyan]"
        )
        raise


async def api_stream(
    path: str, params: dict[str, Any] | None = None, timeout: float = 300.0
) -> AsyncIterator[str]:
    """
    Stream data from an SSE endpoint.

    Args:
        path: API path (e.g., "/api/jobs/run_123/logs/stream")
        params: Optional query parameters
        timeout: Request timeout in seconds

    Yields:
        str: Lines from the SSE stream

    Raises:
        httpx.HTTPStatusError: On HTTP errors
        httpx.ConnectError: On connection errors
    """
    base_url = get_orchestrator_url()
    url = f"{base_url}{path}"

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("GET", url, params=params) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        yield line[6:]  # Strip "data: " prefix
    except httpx.HTTPStatusError as e:
        error_msg = format_http_error(e.response)
        console.print(f"[red]Error:[/red] {error_msg}")
        raise
    except httpx.ConnectError:
        console.print(
            f"[red]Error:[/red] Could not connect to orchestrator at {base_url}"
        )
        console.print(
            "[yellow]Tip:[/yellow] Start the orchestrator with: [cyan]br serve orchestrator[/cyan]"
        )
        raise


def api_get_sync(
    path: str, params: dict[str, Any] | None = None, timeout: float = 30.0
) -> dict[str, Any]:
    """
    Make a synchronous GET request to the orchestrator API.

    Args:
        path: API path (e.g., "/api/jobs/run_123")
        params: Optional query parameters
        timeout: Request timeout in seconds

    Returns:
        Dict: JSON response data

    Raises:
        httpx.HTTPStatusError: On HTTP errors
        httpx.ConnectError: On connection errors
    """
    base_url = get_orchestrator_url()
    url = f"{base_url}{path}"

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        error_msg = format_http_error(e.response)
        console.print(f"[red]Error:[/red] {error_msg}")
        raise
    except httpx.ConnectError:
        console.print(
            f"[red]Error:[/red] Could not connect to orchestrator at {base_url}"
        )
        console.print(
            "[yellow]Tip:[/yellow] Start the orchestrator with: [cyan]br serve orchestrator[/cyan]"
        )
        raise


def api_post_sync(
    path: str, json_data: dict[str, Any], timeout: float = 30.0
) -> dict[str, Any]:
    """
    Make a synchronous POST request to the orchestrator API.

    Args:
        path: API path (e.g., "/run")
        json_data: JSON payload
        timeout: Request timeout in seconds

    Returns:
        Dict: JSON response data

    Raises:
        httpx.HTTPStatusError: On HTTP errors
        httpx.ConnectError: On connection errors
    """
    base_url = get_orchestrator_url()
    url = f"{base_url}{path}"

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, json=json_data)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        error_msg = format_http_error(e.response)
        console.print(f"[red]Error:[/red] {error_msg}")
        raise
    except httpx.ConnectError:
        console.print(
            f"[red]Error:[/red] Could not connect to orchestrator at {base_url}"
        )
        console.print(
            "[yellow]Tip:[/yellow] Start the orchestrator with: [cyan]br serve orchestrator[/cyan]"
        )
        raise
