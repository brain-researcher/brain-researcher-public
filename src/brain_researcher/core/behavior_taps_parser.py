"""Pure TAPS/psyflow/PsychoPy CSV parser into canonical BehaviorTrial dicts.

Extracted from ``services/tools/behavior_tools.BehaviorIngestTAPSTool`` so
that callers outside services (e.g. ``behavior/psyflow_adapter``) can
normalize task outputs without crossing the boundary into the tool layer.
The tool wrapper is now a thin adapter around ``parse_taps_directory``.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from brain_researcher.core.contracts.behavior import BehaviorTrial


class TapsParseError(Exception):
    """Raised when the TAPS parser cannot locate or parse the data file."""


def _first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def _coerce_bool(val: Any) -> bool | None:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, int | float):
        if math.isnan(val):
            return None
        return val != 0
    if isinstance(val, str):
        v = val.strip().lower()
        if v in {"true", "t", "yes", "y", "1"}:
            return True
        if v in {"false", "f", "no", "n", "0"}:
            return False
    return None


def _row_to_trial(
    row: pd.Series,
    idx: int,
    data_path: Path,
    custom_map: dict[str, list[str]],
) -> dict[str, Any]:
    def pick(names: list[str]) -> Any:
        for name in names:
            if name in row and not pd.isna(row[name]):
                return row[name]
        return None

    trial_index = pick(
        custom_map.get("trial_index", [])
        + ["trial_index", "trial", "trialNumber", "TrialNumber", "trialNum"]
    )
    if trial_index is None:
        trial_index = idx
    try:
        trial_index = int(trial_index)
    except Exception:
        trial_index = idx

    onset = pick(
        custom_map.get("onset_sec", [])
        + ["onset", "onset_sec", "t_onset", "onset_s", "trial_onset"]
    )
    if onset is None:
        onset = 0.0
    onset = float(onset)

    duration = pick(
        custom_map.get("duration_sec", [])
        + ["duration", "duration_sec", "trial_duration", "duration_s"]
    )
    duration = None if duration is None else float(duration)

    rt = pick(
        custom_map.get("rt_sec", [])
        + [
            "rt",
            "rt_sec",
            "response_time",
            "rt_seconds",
            "key_resp.rt",
            "resp.rt",
            "RT",
        ]
    )
    if rt is None:
        rt_ms = pick(
            custom_map.get("rt_ms", []) + ["rt_ms", "response_time_ms", "RT_ms"]
        )
        rt = float(rt_ms) / 1000.0 if rt_ms is not None else None
    else:
        rt = float(rt)

    correct = _coerce_bool(
        pick(custom_map.get("correct", []) + ["correct", "is_correct", "accuracy"])
    )

    response = pick(
        custom_map.get("response", [])
        + ["response", "resp", "key_press", "keypress", "key", "key_resp.keys"]
    )
    trial_type = pick(
        custom_map.get("trial_type", [])
        + ["trial_type", "condition", "condition_label", "trialType", "trial_type_text"]
    )
    condition_label = pick(
        custom_map.get("condition_label", [])
        + ["condition_label", "conditionName", "block"]
    )
    session = pick(custom_map.get("session", []) + ["session", "sess"])
    run = pick(custom_map.get("run", []) + ["run", "run_id", "run_number"])
    subject_id = pick(
        custom_map.get("subject_id", [])
        + ["subject_id", "participant", "sub", "participant_id", "Participant"]
    )
    stimulus_id = pick(
        custom_map.get("stimulus_id", [])
        + ["stimulus", "stim_id", "stimulus_id", "stimFile"]
    )

    known_cols = {
        "trial_index",
        "trial",
        "trialNumber",
        "TrialNumber",
        "trialNum",
        "onset",
        "onset_sec",
        "t_onset",
        "onset_s",
        "trial_onset",
        "duration",
        "duration_sec",
        "trial_duration",
        "duration_s",
        "rt",
        "rt_sec",
        "response_time",
        "rt_seconds",
        "rt_ms",
        "response_time_ms",
        "RT",
        "RT_ms",
        "correct",
        "is_correct",
        "accuracy",
        "response",
        "resp",
        "key_press",
        "keypress",
        "key",
        "key_resp.keys",
        "trial_type",
        "condition",
        "condition_label",
        "trialType",
        "conditionName",
        "trial_type_text",
        "block",
        "session",
        "sess",
        "run",
        "run_id",
        "run_number",
        "subject_id",
        "participant",
        "sub",
        "participant_id",
        "Participant",
        "stimulus",
        "stim_id",
        "stimulus_id",
        "stimFile",
    }

    metadata: dict[str, Any] = {}
    for name, value in row.items():
        if name in known_cols or pd.isna(value):
            continue
        try:
            json.dumps(value)
            metadata[name] = value
        except Exception:
            metadata[name] = str(value)

    trial = BehaviorTrial(
        subject_id=subject_id if subject_id is not None else None,
        session=session if session is not None else None,
        run=run if run is not None else None,
        trial_index=trial_index,
        trial_type=str(trial_type) if trial_type is not None else None,
        condition_label=str(condition_label) if condition_label is not None else None,
        onset_sec=float(onset),
        duration_sec=duration,
        response=str(response) if response is not None else None,
        rt_sec=rt,
        correct=correct,
        stimulus_id=str(stimulus_id) if stimulus_id is not None else None,
        raw_source=f"{data_path.name}:{idx + 2}",
        metadata=metadata,
    )
    return trial.model_dump()


def parse_taps_directory(
    task_dir: str | Path,
    *,
    data_file: str | None = None,
    config_file: str | None = None,
    encoding: str | None = None,
    column_map: dict[str, list[str]] | None = None,
    column_map_path: str | None = None,
) -> dict[str, Any]:
    """Parse a TAPS/psyflow/PsychoPy task directory into canonical trial dicts.

    Returns a dict with keys ``trials``, ``source_file``, ``config``,
    ``n_trials``. Raises :class:`TapsParseError` if no data file is found.
    """
    task_path = Path(task_dir).expanduser()
    candidates: list[Path] = []
    if data_file:
        candidates.append(Path(data_file).expanduser())
    candidates.extend(task_path.glob("data/*.csv"))
    candidates.extend(task_path.glob("*.csv"))
    candidates.extend(task_path.glob("data/*.tsv"))
    candidates.extend(task_path.glob("*.tsv"))

    data_path = _first_existing(candidates)
    if data_path is None:
        raise TapsParseError(
            "No data file found (searched data/*.csv, *.csv, data/*.tsv, *.tsv).",
        )

    df = pd.read_csv(data_path, encoding=encoding or "utf-8")

    config: dict[str, Any] | None = None
    if config_file:
        cfg_path: Path | None = Path(config_file).expanduser()
    else:
        cfg_path = _first_existing(
            [task_path / "config.yaml", task_path / "config.yml"]
        )
    if cfg_path and cfg_path.exists():
        config = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

    custom_map: dict[str, list[str]] = {}
    if column_map_path:
        map_path = Path(column_map_path).expanduser()
        if map_path.exists():
            with open(map_path, encoding="utf-8") as f:
                custom = yaml.safe_load(f) or {}
                if isinstance(custom, dict):
                    custom_map = {
                        str(k): [str(vv) for vv in (v or [])]
                        for k, v in custom.items()
                        if isinstance(v, list | tuple)
                    }
    if column_map:
        for k, v in column_map.items():
            custom_map.setdefault(k, [])
            custom_map[k].extend([str(x) for x in v])

    trials: list[dict[str, Any]] = []
    for idx, row in df.iterrows():
        trials.append(_row_to_trial(row, idx, data_path, custom_map))

    return {
        "trials": trials,
        "source_file": str(data_path),
        "config": config,
        "n_trials": len(trials),
    }


__all__ = ["TapsParseError", "parse_taps_directory"]
