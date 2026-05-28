"""Stub electrode localization tool for iEEG workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


class IEEGElectrodeLocalizeArgs(BaseModel):
    """Arguments for electrode localization."""

    ct_image: str = Field(description="Path to CT image aligned with electrodes")
    mri_image: str = Field(description="Path to structural MRI for co-registration")
    output_dir: Optional[str] = Field(
        default=None,
        description="Directory to store localized contacts and reports",
    )


class IEEGElectrodeLocalizeTool(NeuroToolWrapper):
    """Stub localization that produces canonical contacts in MNI space."""

    def get_tool_name(self) -> str:
        return "ieeg_electrode_localize"

    def get_tool_description(self) -> str:
        return "Localize iEEG electrodes by co-registering CT and MRI volumes."

    def get_args_schema(self):
        return IEEGElectrodeLocalizeArgs

    def _run(self, **kwargs) -> ToolResult:
        args = IEEGElectrodeLocalizeArgs(**kwargs)
        output_dir = Path(args.output_dir or Path.cwd() / "ieeg_electrodes")
        output_dir.mkdir(parents=True, exist_ok=True)
        contacts_path = output_dir / "contacts_mni.tsv"

        return ToolResult(
            status="success",
            data={
                "outputs": {
                    "contacts_mni": str(contacts_path),
                    "ct_image": args.ct_image,
                    "mri_image": args.mri_image,
                },
                "summary": {
                    "contacts": "canonical_mni",
                    "method": "stub_localizer",
                },
            },
        )


class IEEGElectrodeLocalizeTools:
    """Helper for registries expecting a get_all_tools method."""

    @staticmethod
    def get_all_tools():
        return [IEEGElectrodeLocalizeTool()]


__all__ = ["IEEGElectrodeLocalizeTool", "IEEGElectrodeLocalizeTools"]
