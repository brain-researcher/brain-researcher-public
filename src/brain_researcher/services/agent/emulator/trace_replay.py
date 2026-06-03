"""
Trace-replay emulator for fast, logic-level rollouts.

This module provides a lightweight "environment" that replays recorded
trajectory.json files (ATIF-v1.4) and returns observations/masks/violations/cost
for each step. It is intended to satisfy BR-TRC-004 as a 100x-faster surrogate
for live orchestration during training/eval.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class TraceReplayEnv:
    """
    Minimal replay environment.

    - reset() loads frames (if not already) and returns the first observation.
    - step(action) advances to the next trace record; action is ignored because
      this is a replay (but kept for interface compatibility).
    - observations are dicts; by default we replay ATIF steps.
    """

    def __init__(
        self,
        records: List[Dict[str, Any]] | None = None,
        trace_path: Path | None = None,
        trajectory_path: Path | None = None,
    ):
        if records is None and trace_path is None and trajectory_path is None:
            raise ValueError("Provide records, trace_path, or trajectory_path")
        self._trace_path = trace_path
        self._trajectory_path = trajectory_path
        self._raw_records = records
        self._records: List[Dict[str, Any]] = []
        self._cursor: int = 0
        self._loaded = False

    def _load_trajectory(self, path: Path) -> None:
        obj = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(obj, dict):
            return
        steps = obj.get("steps") or []
        if not isinstance(steps, list):
            return
        session_id = obj.get("session_id")
        for step in steps:
            if not isinstance(step, dict):
                continue
            if step.get("source") != "agent":
                continue
            tool_calls = step.get("tool_calls")
            observation = step.get("observation")
            if not isinstance(tool_calls, list) or not isinstance(observation, dict):
                continue
            frame = {
                "schema_version": obj.get("schema_version") or "ATIF-v1.4",
                "session_id": session_id,
                "step_id": step.get("step_id"),
                "message": step.get("message"),
                "tool_calls": tool_calls,
                "observation": observation,
                "metrics": step.get("metrics"),
                "extra": step.get("extra"),
            }
            self._records.append(frame)

    def _load(self) -> None:
        if self._loaded:
            return
        if self._raw_records is not None:
            self._records = [r for r in self._raw_records if isinstance(r, dict)]
            self._loaded = True
            return

        if self._trajectory_path is not None:
            self._load_trajectory(self._trajectory_path)
            self._loaded = True
            return

        # Legacy support: trace-v1 record-per-line (deprecated).
        if self._trace_path is not None:
            with self._trace_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(obj, dict):
                        continue
                    # Skip trace-event logs; those are not replay frames.
                    if obj.get("schema_version") == "trace-event-v1":
                        continue
                    self._records.append(obj)
        self._loaded = True

    def reset(self) -> Dict[str, Any]:
        self._load()
        if not self._records:
            raise RuntimeError("TraceReplayEnv has no records to replay")
        self._cursor = 0
        return self._records[0]

    def step(self, action: Optional[Any] = None) -> Tuple[Dict[str, Any], float, bool, Dict[str, Any]]:
        """
        Advance to next record. Action is ignored (replay), but kept for API parity.
        Returns: observation, reward (0), done, info
        """
        if not self._loaded:
            self.reset()
        self._cursor += 1
        done = self._cursor >= len(self._records)
        if done:
            # Stay at last frame for terminal observation
            obs = self._records[-1]
        else:
            obs = self._records[self._cursor]
        violations = obs.get("violations")
        if violations is None and isinstance(obs.get("observation"), dict):
            results = obs["observation"].get("results")
            if isinstance(results, list) and results:
                content = results[0].get("content") if isinstance(results[0], dict) else None
                if isinstance(content, dict):
                    violations = content.get("violations")

        info = {
            "violations": violations,
            "mask_reasons": obs.get("mask_reasons"),
            "cost": obs.get("cost"),
            "recovery": obs.get("recovery"),
        }
        return obs, 0.0, done, info

    def rollout(self) -> List[Dict[str, Any]]:
        """Return all observations in order (fast path for training)."""
        self._load()
        return list(self._records)


__all__ = ["TraceReplayEnv"]
