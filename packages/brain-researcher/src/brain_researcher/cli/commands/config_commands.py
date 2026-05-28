"""
Configuration management commands for Brain Researcher CLI.

Provides commands for managing credentials and other configuration.
"""

import json
from pathlib import Path
from typing import Optional

import typer
from rich import print
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from brain_researcher.services.agent.credential_resolver import (
    CredentialResolver,
    get_default_credential_path,
)

app = typer.Typer(help="Configuration management commands")
console = Console()


def _config_path() -> Path:
    """Determine the credential config path respecting test overrides."""
    return get_default_credential_path()


@app.command("list")
def list_credentials():
    """List all available credentials."""
    resolver = CredentialResolver(config_path=_config_path())
    credentials = resolver.list_credentials()

    if not credentials:
        console.print("[yellow]No credentials configured.[/yellow]")
        console.print("\nAdd credentials using: [cyan]br config add[/cyan]")
        return

    table = Table(title="Available Credentials")
    table.add_column("Name", style="cyan")
    table.add_column("Provider", style="green")
    table.add_column("Source", style="magenta")

    for name, provider in credentials.items():
        if name.startswith("env_"):
            source = "Environment"
        elif name.startswith("byok_"):
            source = "Configured"
        elif name == "local_oauth":
            source = "OAuth (CLI)"
        else:
            source = "Unknown"

        table.add_row(name, provider, source)

    console.print(table)


@app.command("add")
def add_credential(
    name: str = typer.Argument(..., help="Credential name (e.g., 'personal_gemini')"),
    provider: str = typer.Option(
        None, "--provider", "-p", help="Provider: gemini or openai"
    ),
    api_key: Optional[str] = typer.Option(
        None, "--key", "-k", help="API key (will prompt if not provided)"
    ),
):
    """Add or update a BYOK credential."""
    # Validate provider
    if not provider:
        provider = Prompt.ask(
            "Select provider", choices=["gemini", "openai"], default="gemini"
        )

    provider = provider.lower()
    if provider not in ["gemini", "openai"]:
        console.print(
            f"[red]Error: Invalid provider '{provider}'. Must be 'gemini' or 'openai'.[/red]"
        )
        raise typer.Exit(1)

    # Get API key
    if not api_key:
        api_key = Prompt.ask(f"Enter {provider.upper()} API key", password=True)

    if not api_key:
        console.print("[red]Error: API key cannot be empty.[/red]")
        raise typer.Exit(1)

    # Validate API key format (basic check)
    if provider == "openai" and not api_key.startswith("sk-"):
        console.print("[yellow]Warning: OpenAI keys usually start with 'sk-'[/yellow]")
        if not Prompt.ask("Continue anyway?", choices=["y", "n"], default="n") == "y":
            raise typer.Exit(0)

    # Add credential
    try:
        resolver = CredentialResolver(config_path=_config_path())
        resolver.add_credential(name, api_key, provider)
        console.print(f"[green]✓[/green] Added credential '{name}' for {provider}")

        # Show how to use it
        console.print(f"\n[cyan]To use this credential:[/cyan]")
        console.print(
            "  • Set BR_GEMINI_CREDENTIAL_PREFERENCE=byok_first to prefer API keys over local Gemini CLI OAuth"
        )
        console.print(
            "  • Or set BR_GEMINI_CREDENTIAL_PREFERENCE=byok_only to disable local Gemini CLI fallback"
        )
        console.print(
            f"  • The credential will be used automatically based on model selection"
        )
        console.print(f"  • Or specify it explicitly in API calls")

    except Exception as e:
        console.print(f"[red]Error adding credential: {e}[/red]")
        raise typer.Exit(1)


@app.command("remove")
def remove_credential(
    name: str = typer.Argument(..., help="Credential name to remove"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Remove a BYOK credential."""
    if not yes:
        confirm = Prompt.ask(
            f"Remove credential '{name}'?", choices=["y", "n"], default="n"
        )
        if confirm != "y":
            console.print("[yellow]Cancelled.[/yellow]")
            raise typer.Exit(0)

    resolver = CredentialResolver(config_path=_config_path())
    if resolver.remove_credential(name):
        console.print(f"[green]✓[/green] Removed credential '{name}'")
    else:
        console.print(f"[red]Error: Credential '{name}' not found.[/red]")
        raise typer.Exit(1)


@app.command("test")
def test_credential(
    name: Optional[str] = typer.Argument(None, help="Credential name to test"),
    model: str = typer.Option(
        "gemini-3-flash-preview", "--model", "-m", help="Model to test with"
    ),
):
    """Test a credential by sending a simple request."""
    resolver = CredentialResolver(config_path=_config_path())

    # Resolve credential
    if name:
        cred = resolver._resolve_specific(name)
        if not cred:
            console.print(f"[red]Error: Credential '{name}' not found.[/red]")
            raise typer.Exit(1)
    else:
        cred = resolver.resolve_for_chat(model_hint=model)
        if not cred:
            console.print("[red]Error: No suitable credential found.[/red]")
            console.print("\n[cyan]Available credentials:[/cyan]")
            list_credentials()
            raise typer.Exit(1)

    console.print(f"[cyan]Testing credential:[/cyan] {cred.kind}")
    console.print(f"[cyan]Source:[/cyan] {cred.metadata.get('source', 'unknown')}")

    # Test the credential
    try:
        if cred.kind == "local_gemini":
            from brain_researcher.services.agent.utils import gemini_cli

            result = gemini_cli.execute_chat(
                "Say 'Hello, credentials working!'", model=model
            )
            console.print(f"[green]✓ Success![/green] Response: {result.text[:100]}...")

        elif cred.kind == "byok_gemini":
            # Test with Gemini API
            import google.generativeai as genai

            genai.configure(api_key=cred.api_key)
            model_obj = genai.GenerativeModel(model)
            response = model_obj.generate_content("Say 'Hello, credentials working!'")
            console.print(
                f"[green]✓ Success![/green] Response: {response.text[:100]}..."
            )

        elif cred.kind == "byok_openai":
            # Test with OpenAI API
            from openai import OpenAI

            client = OpenAI(api_key=cred.api_key)
            response = client.chat.completions.create(
                model="gpt-3.5-turbo" if "gpt" not in model else model,
                messages=[
                    {"role": "user", "content": "Say 'Hello, credentials working!'"}
                ],
                max_tokens=50,
            )
            console.print(
                f"[green]✓ Success![/green] Response: {response.choices[0].message.content[:100]}..."
            )

        else:
            console.print(
                f"[yellow]Warning: Unknown credential type '{cred.kind}'[/yellow]"
            )

    except Exception as e:
        console.print(f"[red]✗ Failed![/red] Error: {e}")
        raise typer.Exit(1)


@app.command("show")
def show_config():
    """Show configuration file location and contents (without sensitive data)."""
    config_path = _config_path()

    console.print(f"[cyan]Configuration file:[/cyan] {config_path}")

    if not config_path.exists():
        console.print("[yellow]No configuration file found.[/yellow]")
        return

    try:
        with open(config_path, "r") as f:
            config = json.load(f)

        # Mask API keys
        if "byok" in config:
            for name, info in config["byok"].items():
                if "api_key" in info:
                    key = info["api_key"]
                    info["api_key"] = (
                        f"{key[:8]}...{key[-4:]}" if len(key) > 12 else "***"
                    )

        console.print("\n[cyan]Configuration (keys masked):[/cyan]")
        console.print(json.dumps(config, indent=2))

    except Exception as e:
        console.print(f"[red]Error reading configuration: {e}[/red]")


if __name__ == "__main__":
    app()
