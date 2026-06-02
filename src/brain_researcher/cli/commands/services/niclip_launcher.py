"""
NICLIP Service Launcher

Launches the NICLIP prediction service with FastAPI.
"""

from rich.console import Console

console = Console()


def launch_niclip_service(
    host: str = "127.0.0.1",
    port: int = 8001,
    niclip_data_path: str | None = None,
    model_name: str = "BrainGPT-7B-v0.2",
    section: str = "abstract",
    verbose: bool = False,
):
    """
    Launch the NICLIP prediction service.

    Args:
        host: Host to bind to
        port: Port to bind to
        niclip_data_path: Path to NICLIP data directory
        model_name: NICLIP model name to use
        section: Section embeddings to use (abstract/body)
        verbose: Enable verbose output
    """
    console.print(
        "[yellow]NICLIP HTTP service is disabled by default. Use `br niclip health/search/encode` instead.[/yellow]"
    )
    console.print(
        "[dim]If you still need HTTP locally, run the FastAPI app directly via uvicorn.[/dim]"
    )


if __name__ == "__main__":
    # Test launch
    launch_niclip_service(verbose=True)
