from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List, Optional


class VirtualBrainAdapter:
    """Adapter that exposes Virtual Brain simulation summaries on demand."""

    def __init__(self, *, cache_dir: Optional[str] = None) -> None:
        self.cache_dir = Path(cache_dir or "data/virtual_brain/cache")

    def _iter_reports(self) -> Iterable[Path]:
        if not self.cache_dir.exists():
            return []
        return sorted(self.cache_dir.glob("*/report.json"), key=lambda path: path.stat().st_mtime, reverse=True)

    def _load_report(self, sim_id: str) -> Optional[dict]:
        report_path = self.cache_dir / sim_id.replace(":", "_") / "report.json"
        if not report_path.exists():
            return None
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            payload["_report_path"] = str(report_path)
            return payload
        except (OSError, json.JSONDecodeError):
            return None

    def fetch(
        self,
        *,
        simulation_ids: Optional[Iterable[str]] = None,
        task_id: Optional[str] = None,
        latest: bool = False,
        limit: int = 5,
    ) -> List[dict]:
        results: List[dict] = []
        if simulation_ids:
            for sim_id in simulation_ids:
                report = self._load_report(sim_id)
                if not report:
                    continue
                if task_id and report.get("simulation", {}).get("seeded_task_id") != task_id:
                    continue
                results.append(report)
            return results

        count = 0
        for report_path in self._iter_reports():
            if latest and count >= limit:
                break
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
                report["_report_path"] = str(report_path)
            except (OSError, json.JSONDecodeError):
                continue
            if task_id and report.get("simulation", {}).get("seeded_task_id") != task_id:
                continue
            results.append(report)
            count += 1
        return results

    def __call__(self, **kwargs):
        return self.fetch(**kwargs)
