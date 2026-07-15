"""Lazy Typer subcommand registration for optional command profiles."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any

import click
import typer
from typer.core import TyperCommand, TyperGroup

_PROFILE_PROBES = {
    "agent": "langgraph",
    "br-kg": "nibabel",
    "notebook": "marimo",
}


@dataclass(frozen=True)
class LazyTyperSpec:
    """Import target and install profile for one root command group."""

    module: str
    help: str
    attribute: str = "app"
    extra: str | None = None


class MissingOptionalProfile(RuntimeError):
    """Raised only for a known optional-profile import failure."""


class LazyTyperCommand(TyperCommand):
    """A lightweight proxy that imports its Typer application when invoked."""

    def __init__(self, name: str, spec: LazyTyperSpec) -> None:
        super().__init__(
            name=name,
            callback=None,
            params=[],
            help=spec.help,
            short_help=spec.help,
            add_help_option=False,
            context_settings={
                "allow_extra_args": True,
                "ignore_unknown_options": True,
            },
        )
        self._spec = spec

    def _load_command(self) -> click.Command:
        profile_probe = _PROFILE_PROBES.get(self._spec.extra or "")
        if profile_probe and importlib.util.find_spec(profile_probe) is None:
            raise self._missing_profile(profile_probe)

        try:
            module = importlib.import_module(self._spec.module)
        except ModuleNotFoundError as exc:
            missing = exc.name or ""
            is_internal = missing == "brain_researcher" or missing.startswith(
                "brain_researcher."
            )
            if self._spec.extra and missing and not is_internal:
                raise self._missing_profile(missing) from exc
            raise

        typer_app = getattr(module, self._spec.attribute)
        if not isinstance(typer_app, typer.Typer):
            raise TypeError(
                f"{self._spec.module}:{self._spec.attribute} is not a Typer app"
            )
        # get_group() intentionally preserves the command-group shape even when
        # a Typer app currently contains only one command.
        return typer.main.get_group(typer_app)

    def _missing_profile(self, missing: str) -> MissingOptionalProfile:
        return MissingOptionalProfile(
            f"Command {self.name!r} requires the optional "
            f"{self._spec.extra!r} profile (missing module {missing!r}). "
            f"Install it with `pip install '.[{self._spec.extra}]'` "
            f"or `pip install 'brain_researcher[{self._spec.extra}]'`."
        )

    def invoke(self, ctx: click.Context) -> Any:
        try:
            command = self._load_command()
        except MissingOptionalProfile as exc:
            click.echo(f"Error: {exc}", err=True)
            ctx.exit(2)
        child_ctx = command.make_context(
            info_name=self.name,
            args=list(ctx.args),
            parent=ctx.parent,
        )
        with child_ctx:
            return command.invoke(child_ctx)


def lazy_typer_group(
    specs: dict[str, LazyTyperSpec],
) -> type[TyperGroup]:
    """Create a root group class that overlays lazy commands on direct commands."""

    class LazyRootGroup(TyperGroup):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            # Overlay after Typer builds direct commands. This preserves the old
            # add_typer precedence for names such as ``chat``.
            for command_name, spec in specs.items():
                self.commands[command_name] = LazyTyperCommand(command_name, spec)

    LazyRootGroup.__name__ = "LazyRootGroup"
    return LazyRootGroup
