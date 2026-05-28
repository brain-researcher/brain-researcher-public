"""Utility functions for CLI commands."""

from collections.abc import Callable

from rich.console import Console

console = Console()


def run_script(script_name: str, main_func: str | None = "main") -> Callable:
    """
    Wrapper to run existing scripts as CLI commands.

    Args:
        script_name: Name of the script module to import
        main_func: Name of the main function to call (default: "main")

    Returns:
        A function that can be used as a Typer command
    """

    def wrapper(**kwargs):
        try:
            # Import the script module
            module = __import__(script_name, fromlist=[main_func])

            # Get the main function
            func = getattr(module, main_func, None)

            if func is None:
                console.print(
                    f"[red]Error: No '{main_func}' function found in {script_name}[/red]"
                )
                return

            # Set any environment variables from kwargs
            import os

            for key, value in kwargs.items():
                if value is not None:
                    os.environ[key.upper()] = str(value)

            # Run the function
            func()

        except Exception as e:
            console.print(f"[red]Error running {script_name}: {e}[/red]")
            raise

    return wrapper


def confirm_action(message: str, default: bool = False) -> bool:
    """
    Ask user for confirmation before proceeding.

    Args:
        message: Confirmation message to display
        default: Default response if user just presses Enter

    Returns:
        True if user confirms, False otherwise
    """
    suffix = " [Y/n]" if default else " [y/N]"
    response = console.input(f"[yellow]{message}{suffix}[/yellow] ")

    if not response:
        return default

    return response.lower() in ["y", "yes"]


def format_size(bytes: int) -> str:
    """Format bytes as human-readable size."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes < 1024.0:
            return f"{bytes:.1f} {unit}"
        bytes /= 1024.0
    return f"{bytes:.1f} PB"
