"""EEG preprocessing tool using MNE."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from brain_researcher.core.utils import configure_mne_environment
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


class EEGPreprocessArgs(BaseModel):
    raw_eeg: str = Field(description="Path to raw EEG recording")
    montage_def: str = Field(description="Resolved montage file")
    highpass_hz: float = Field(default=1.0)
    lowpass_hz: float = Field(default=40.0)
    output_dir: str | None = Field(default=None, description="Output directory")
    reference: str = Field(default="average", description="EEG reference")


class EEGPreprocessTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "eeg_preprocess"

    def get_tool_description(self) -> str:
        return "Band-pass filter, re-reference, and clean raw EEG data."

    def get_args_schema(self):
        return EEGPreprocessArgs

    def _run(self, raw_eeg: str, montage_def: str, **kwargs) -> ToolResult:
        configure_mne_environment()
        try:
            import mne
        except ImportError as exc:
            return ToolResult(
                status="error", error=f"MNE not available: {exc}", data={}
            )
        args = EEGPreprocessArgs(
            raw_eeg=raw_eeg,
            montage_def=montage_def,
            highpass_hz=kwargs.get("highpass_hz", 1.0),
            lowpass_hz=kwargs.get("lowpass_hz", 40.0),
            output_dir=kwargs.get("output_dir"),
            reference=kwargs.get("reference", "average"),
        )

        raw_path = Path(args.raw_eeg)
        if not raw_path.exists():
            return ToolResult(status="error", error="raw_eeg not found", data={})

        if raw_path.suffix == ".fif":
            raw = mne.io.read_raw_fif(raw_path, preload=True, verbose=False)
        elif raw_path.suffix in {".edf", ".bdf"}:
            raw = mne.io.read_raw_edf(raw_path, preload=True, verbose=False)
        else:
            return ToolResult(
                status="error", error="Unsupported raw_eeg format", data={}
            )

        montage_path = Path(args.montage_def)
        if montage_path.exists():
            montage = mne.channels.read_custom_montage(montage_path)
        else:
            montage = mne.channels.make_standard_montage(args.montage_def)
        raw.set_montage(montage, on_missing="ignore")

        raw.filter(args.highpass_hz, args.lowpass_hz, verbose=False)
        # MEG-only recordings do not contain EEG channels to re-reference.
        if mne.pick_types(raw.info, eeg=True, meg=False).size:
            raw.set_eeg_reference(args.reference, verbose=False)

        output_dir = Path(args.output_dir) if args.output_dir else raw_path.parent
        output_dir.mkdir(parents=True, exist_ok=True)
        clean_path = output_dir / f"{raw_path.stem}_clean_raw.fif"
        raw.save(clean_path, overwrite=True, verbose=False)

        return ToolResult(
            status="success",
            data={
                "outputs": {"clean_eeg": str(clean_path)},
                "summary": {
                    "raw": args.raw_eeg,
                    "montage": args.montage_def,
                    "band": [args.highpass_hz, args.lowpass_hz],
                    "reference": args.reference,
                    "n_channels": len(raw.ch_names),
                },
            },
        )


__all__ = ["EEGPreprocessTool"]
