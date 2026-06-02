"""Notebook Intelligence extension entrypoint for Brain Researcher."""

from __future__ import annotations

from typing import Any

from ._compat import Host, NotebookIntelligenceExtension
from .config import BrainResearcherNotebookIntelligenceSettings
from .participant import BrainResearcherParticipant
from .runtime_patches import apply_notebook_intelligence_runtime_patches


class BrainResearcherNotebookIntelligenceExtension(NotebookIntelligenceExtension):
    def __init__(
        self,
        settings: BrainResearcherNotebookIntelligenceSettings | None = None,
    ) -> None:
        self._settings = (
            settings or BrainResearcherNotebookIntelligenceSettings.from_env()
        )

    @property
    def id(self) -> str:
        return self._settings.extension_id

    @property
    def name(self) -> str:
        return self._settings.extension_name

    @property
    def provider(self) -> str:
        return self._settings.provider_name

    @property
    def url(self) -> str:
        return self._settings.provider_url

    def activate(self, host: Host) -> None:
        apply_notebook_intelligence_runtime_patches()
        self._refresh_claude_participant(host)
        participant = BrainResearcherParticipant(host=host, settings=self._settings)
        host.register_chat_participant(participant)
        self._install_primary_participant(host, participant)

    def _install_primary_participant(
        self, host: Host, participant: BrainResearcherParticipant
    ) -> None:
        chat_participants = getattr(host, "chat_participants", None)
        if not isinstance(chat_participants, dict):
            return

        def apply_primary_override() -> None:
            chat_participants["default"] = participant
            chat_participants[participant.id] = participant
            if hasattr(host, "_default_chat_participant"):
                host._default_chat_participant = participant  # type: ignore[attr-defined]

        apply_primary_override()

        original_update = getattr(host, "update_models_from_config", None)
        if not callable(original_update) or getattr(
            host, "_brain_researcher_primary_wrapped", False
        ):
            return

        def wrapped_update_models_from_config(*args: Any, **kwargs: Any):
            result = original_update(*args, **kwargs)
            apply_primary_override()
            return result

        host.update_models_from_config = wrapped_update_models_from_config  # type: ignore[method-assign, attr-defined]
        host._brain_researcher_primary_wrapped = True  # type: ignore[attr-defined]

    def _refresh_claude_participant(self, host: Host) -> None:
        chat_participants = getattr(host, "chat_participants", None)
        if not isinstance(chat_participants, dict):
            return

        claude_participant = chat_participants.get("claude-code")
        if claude_participant is None:
            return

        update_client = getattr(claude_participant, "update_client", None)
        if callable(update_client):
            update_client()
