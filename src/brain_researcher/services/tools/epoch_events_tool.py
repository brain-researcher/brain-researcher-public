"""Epoch extraction tool for EEG."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from brain_researcher.core.utils import configure_mne_environment
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


class EpochEventsArgs(BaseModel):
    clean_eeg: str = Field(description="Preprocessed EEG file")
    tmin: float = Field(default=-0.2)
    tmax: float = Field(default=0.8)
    events_file: str | None = Field(
        default=None, description="Events TSV/CSV or numpy file"
    )
    event_id: int | None = Field(default=1, description="Event ID to epoch around")
    output_dir: str | None = Field(default=None, description="Output directory")


class EpochEventsTool(NeuroToolWrapper):
    def get_tool_name(self) -> str:
        return "epoch_events"

    def get_tool_description(self) -> str:
        return "Segment cleaned EEG into epochs around labeled events."

    def get_args_schema(self):
        return EpochEventsArgs

    def _run(self, clean_eeg: str, **kwargs) -> ToolResult:
        configure_mne_environment()
        try:
            import mne
        except ImportError as exc:
            return ToolResult(
                status="error", error=f"MNE not available: {exc}", data={}
            )
        args = EpochEventsArgs(
            clean_eeg=clean_eeg,
            tmin=kwargs.get("tmin", -0.2),
            tmax=kwargs.get("tmax", 0.8),
            events_file=kwargs.get("events_file"),
            event_id=kwargs.get("event_id", 1),
            output_dir=kwargs.get("output_dir"),
        )

        raw_path = Path(args.clean_eeg)
        if not raw_path.exists():
            return ToolResult(status="error", error="clean_eeg not found", data={})

        raw = mne.io.read_raw_fif(raw_path, preload=True, verbose=False)

        events = None
        if args.events_file:
            events_path = Path(args.events_file)
            if not events_path.exists():
                return ToolResult(
                    status="error", error="events_file not found", data={}
                )
            if events_path.suffix in {".tsv", ".csv"}:
                sep = "\t" if events_path.suffix == ".tsv" else ","
                df = pd.read_csv(events_path, sep=sep)
                if {"sample", "event_id"}.issubset(df.columns):
                    events = df[["sample", "event_id"]].values
                    events = np.column_stack(
                        [events[:, 0], np.zeros(len(events), dtype=int), events[:, 1]]
                    )
                elif {"onset", "event_id"}.issubset(df.columns):
                    samples = (df["onset"].to_numpy() * raw.info["sfreq"]).astype(int)
                    events = np.column_stack(
                        [
                            samples,
                            np.zeros(len(samples), dtype=int),
                            df["event_id"].to_numpy(),
                        ]
                    )
                else:
                    events = df.values
            elif events_path.suffix == ".npy":
                events = np.load(events_path)
            else:
                return ToolResult(
                    status="error", error="Unsupported events_file format", data={}
                )
        else:
            events = mne.make_fixed_length_events(raw, duration=1.0, id=args.event_id)

        event_id = args.event_id if args.event_id is not None else 1
        epochs = mne.Epochs(
            raw,
            events,
            event_id=event_id,
            tmin=args.tmin,
            tmax=args.tmax,
            baseline=(None, 0),
            preload=True,
            verbose=False,
        )

        output_dir = Path(args.output_dir) if args.output_dir else raw_path.parent
        output_dir.mkdir(parents=True, exist_ok=True)
        epochs_path = output_dir / f"{raw_path.stem}_epo.fif"
        epochs.save(epochs_path, overwrite=True)

        return ToolResult(
            status="success",
            data={
                "outputs": {"epochs": str(epochs_path)},
                "summary": {
                    "n_epochs": len(epochs),
                    "tmin": args.tmin,
                    "tmax": args.tmax,
                    "event_id": event_id,
                },
            },
        )


__all__ = ["EpochEventsTool"]
