"""
Contrast text orchestration for Task -> Construct -> Map prediction.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from brain_researcher.core.analysis.neurosynth_integration import get_neurosynth_mapping
from brain_researcher.services.neurokg.etl.mappers.niclip_task_mapper import (
    NiCLIPTaskMapper,
)
from brain_researcher.services.neurokg.niclip.engine import NiclipEngine

logger = logging.getLogger(__name__)


def _safe_slug(text: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in text.strip())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned or "term"


class ContrastTextToPredictedMapOrchestrator:
    """Orchestrates contrast-text -> task -> construct -> activation map prediction."""

    def __init__(
        self,
        *,
        engine: NiclipEngine | None = None,
        task_mapper: NiCLIPTaskMapper | None = None,
        map_threshold: float = 3.0,
    ):
        self.engine = engine or NiclipEngine.get()
        self.task_mapper = task_mapper or NiCLIPTaskMapper()
        self.map_threshold = float(map_threshold)

    @staticmethod
    def _dedupe_tasks(rows: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for row in rows:
            task = str(row.get("task", "")).strip()
            if not task:
                continue
            score = float(row.get("score", 0.0))
            key = task.casefold()
            if key not in merged or score > float(merged[key].get("score", 0.0)):
                merged[key] = {
                    "task": task,
                    "score": score,
                    "source": row.get("source", "unknown"),
                }
        ranked = sorted(merged.values(), key=lambda item: float(item["score"]), reverse=True)
        return ranked[:top_k]

    def _predict_tasks(
        self,
        *,
        contrast_text: str,
        task_name: str | None,
        top_k_tasks: int,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []

        if task_name and str(task_name).strip():
            rows.append(
                {
                    "task": str(task_name).strip(),
                    "score": 1.0,
                    "source": "provided",
                }
            )

        search_hits = self.engine.search(contrast_text, top_k=max(top_k_tasks, 1))
        for hit in search_hits:
            task = str(hit.get("item", "")).strip()
            if not task:
                continue
            rows.append(
                {
                    "task": task,
                    "score": float(hit.get("similarity", 0.0)),
                    "source": "niclip_text_search",
                }
            )

        deduped = self._dedupe_tasks(rows, top_k=top_k_tasks)
        if not deduped:
            raise RuntimeError("No task predictions available for contrast text.")
        return deduped

    def _tasks_to_constructs(
        self,
        task_predictions: list[dict[str, Any]],
        *,
        top_k_constructs: int,
    ) -> list[dict[str, Any]]:
        concept_scores: dict[str, dict[str, Any]] = {}

        for item in task_predictions:
            task = str(item.get("task", "")).strip()
            if not task:
                continue
            task_score = float(item.get("score", 0.0))
            concepts = self.task_mapper.get_task_concepts(task)
            if not concepts:
                concepts = [task]

            primary_process = self.task_mapper.get_primary_process(task)
            default_process = (
                self.task_mapper.get_process_name(primary_process)
                if primary_process
                else "unmapped"
            )

            for idx, concept in enumerate(concepts):
                concept_name = str(concept).strip()
                if not concept_name:
                    continue
                concept_score = task_score * max(0.1, 1.0 - (0.15 * idx))
                process = default_process
                process_id = self.task_mapper.concept_to_process.get(concept_name)
                if process_id:
                    process = self.task_mapper.get_process_name(process_id)

                record = concept_scores.get(
                    concept_name,
                    {
                        "concept": concept_name,
                        "score": concept_score,
                        "process": process or "unmapped",
                        "source_tasks": [task],
                    },
                )
                if concept_score > float(record.get("score", 0.0)):
                    record["score"] = concept_score
                if task not in record["source_tasks"]:
                    record["source_tasks"].append(task)
                concept_scores[concept_name] = record

        ranked = sorted(
            concept_scores.values(),
            key=lambda row: float(row.get("score", 0.0)),
            reverse=True,
        )
        return ranked[:top_k_constructs]

    def _predict_map_from_constructs(
        self,
        constructs: list[dict[str, Any]],
        *,
        top_k_map_terms: int,
        save_dir: str | None,
    ) -> dict[str, Any]:
        candidate_terms = [
            str(row.get("concept", "")).strip()
            for row in constructs[:top_k_map_terms]
            if str(row.get("concept", "")).strip()
        ]

        if not candidate_terms:
            return {
                "map_generated": False,
                "error": "No construct terms available for map prediction.",
                "candidate_terms_tried": [],
            }

        for term in candidate_terms:
            payload = get_neurosynth_mapping(term, threshold=self.map_threshold)
            maps = payload.get("activation_maps") or []
            if not maps:
                continue

            map_path = None
            if save_dir:
                output_dir = Path(save_dir)
                output_dir.mkdir(parents=True, exist_ok=True)
                filename = f"predicted_map_{_safe_slug(term)}.nii.gz"
                map_path = str(output_dir / filename)
                try:
                    import nibabel as nib

                    nib.save(maps[0], map_path)
                except Exception as exc:
                    logger.warning("Failed to save predicted map for term '%s': %s", term, exc)
                    map_path = None

            return {
                "map_generated": True,
                "selected_term": term,
                "term_used": payload.get("term_used", term),
                "n_studies": int(payload.get("n_studies", 0)),
                "n_coords": int(payload.get("n_coords", 0)),
                "threshold_count": payload.get("threshold_count"),
                "coordinates": payload.get("coordinates", []),
                "map_path": map_path,
                "candidate_terms_tried": candidate_terms,
            }

        return {
            "map_generated": False,
            "error": "No activation map was produced for predicted constructs.",
            "candidate_terms_tried": candidate_terms,
        }

    @staticmethod
    def to_coordinate_to_concept_args(
        predicted_map_payload: dict[str, Any],
        *,
        top_n_coords: int = 5,
        radius_mm: float = 10.0,
        top_k: int = 5,
    ) -> dict[str, Any]:
        rows = predicted_map_payload.get("coordinates") or []
        parsed: list[list[float]] = []
        for row in rows:
            if isinstance(row, dict):
                if {"x", "y", "z"}.issubset(row.keys()):
                    parsed.append([float(row["x"]), float(row["y"]), float(row["z"])])
            elif isinstance(row, list | tuple) and len(row) == 3:
                parsed.append([float(row[0]), float(row[1]), float(row[2])])
            if len(parsed) >= int(top_n_coords):
                break

        return {
            "coordinates": parsed,
            "radius": float(radius_mm),
            "top_k": int(top_k),
        }

    def orchestrate(
        self,
        *,
        contrast_text: str,
        task_name: str | None = None,
        top_k_tasks: int = 20,
        top_k_constructs: int = 10,
        top_k_map_terms: int = 3,
        save_dir: str | None = None,
        coord_top_n: int = 5,
        coord_radius_mm: float = 10.0,
        coord_top_k: int = 5,
    ) -> dict[str, Any]:
        text = str(contrast_text or "").strip()
        if not text:
            raise ValueError("contrast_text is required")

        task_predictions = self._predict_tasks(
            contrast_text=text,
            task_name=task_name,
            top_k_tasks=int(top_k_tasks),
        )
        constructs = self._tasks_to_constructs(
            task_predictions,
            top_k_constructs=int(top_k_constructs),
        )
        if not constructs:
            raise RuntimeError("No constructs predicted from task candidates.")

        predicted_map = self._predict_map_from_constructs(
            constructs,
            top_k_map_terms=int(top_k_map_terms),
            save_dir=save_dir,
        )
        coord_args = self.to_coordinate_to_concept_args(
            predicted_map,
            top_n_coords=int(coord_top_n),
            radius_mm=float(coord_radius_mm),
            top_k=int(coord_top_k),
        )

        engine_status: dict[str, Any] = {}
        try:
            engine_status = self.engine.status()
        except Exception as exc:
            logger.warning("Failed to collect NiCLIP engine status: %s", exc)
            engine_status = {"status": "unknown", "error": str(exc)}

        return {
            "contrast_text": text,
            "task_name": task_name,
            "task_predictions": task_predictions,
            "constructs": constructs,
            "predicted_map": predicted_map,
            "coordinate_to_concept_args": coord_args,
            "metadata": {
                "map_threshold": self.map_threshold,
                "engine_status": engine_status,
            },
        }
