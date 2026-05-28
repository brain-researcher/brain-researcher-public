"""
Coordinate-to-concept mapping using real NiCLIP backends.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

import nibabel as nib

from brain_researcher.config.paths import get_data_root
from brain_researcher.core.analysis.neurosynth_integration import (
    _build_activation_map_from_coordinates,
)
from brain_researcher.services.neurokg.etl.mappers.niclip_task_mapper import (
    NiCLIPTaskMapper,
)
from brain_researcher.services.neurokg.niclip.engine import (
    NiclipEngine,
    NiclipEngineConfig,
)
from brain_researcher.services.tools.atlas_utils import default_atlas_output_root

logger = logging.getLogger(__name__)


def _dedupe_and_sort_predictions(
    pairs: list[tuple[str, float]], *, top_k: int
) -> list[tuple[str, float]]:
    table: dict[str, float] = {}
    for name, score in pairs:
        if name not in table or score > table[name]:
            table[name] = score
    rows = sorted(table.items(), key=lambda item: item[1], reverse=True)
    return rows[:top_k]


def _extract_task_predictions_payload(
    payload: Any, *, top_k: int
) -> list[tuple[str, float]]:
    predictions: list[tuple[str, float]] = []

    try:
        import pandas as pd  # type: ignore
    except Exception:  # pragma: no cover
        pd = None  # type: ignore

    if pd is not None and isinstance(payload, pd.DataFrame):
        if payload.empty:
            return []
        name_cols = ("task", "label", "name", "item", "text")
        score_cols = ("similarity", "score", "probability", "weight")
        name_col = next((c for c in name_cols if c in payload.columns), None)
        score_col = next((c for c in score_cols if c in payload.columns), None)
        if name_col:
            for _, row in payload.iterrows():
                label = str(row[name_col]).strip()
                if not label:
                    continue
                score = float(row[score_col]) if score_col else 0.0
                predictions.append((label, score))
            return _dedupe_and_sort_predictions(predictions, top_k=top_k)

    if isinstance(payload, dict):
        for key in ("predictions", "labels", "results"):
            if key in payload:
                return _extract_task_predictions_payload(payload[key], top_k=top_k)

    if isinstance(payload, list):
        for idx, item in enumerate(payload):
            if isinstance(item, dict):
                label = str(
                    item.get("task")
                    or item.get("label")
                    or item.get("name")
                    or item.get("item")
                    or item.get("text")
                    or ""
                ).strip()
                if not label:
                    continue
                raw_score = (
                    item.get("similarity")
                    or item.get("score")
                    or item.get("probability")
                    or item.get("weight")
                )
                score = float(raw_score) if raw_score is not None else 1.0 / (idx + 1)
                predictions.append((label, score))
                continue

            if isinstance(item, (list, tuple)) and item:
                label = str(item[0]).strip()
                if not label:
                    continue
                score = (
                    float(item[1])
                    if len(item) > 1 and isinstance(item[1], (int, float))
                    else 1.0 / (idx + 1)
                )
                predictions.append((label, score))
                continue

            if isinstance(item, str):
                label = item.strip()
                if label:
                    predictions.append((label, 1.0 / (idx + 1)))

    return _dedupe_and_sort_predictions(predictions, top_k=top_k)


def _predict_full_worker(
    config_kwargs: dict[str, Any],
    nifti_path: str,
    top_k: int,
    queue: Any,
) -> None:
    try:
        config = NiclipEngineConfig(**config_kwargs)
        engine = NiclipEngine.get(config=config, force_reload=True)
        model = engine.get_model()
        if model is None or getattr(model, "model", None) is None:
            raise RuntimeError("full backend model checkpoint failed to load")
        payload = engine.predict_from_nifti(nifti_path, top_k=top_k, use_bayes=True)
        tasks = _extract_task_predictions_payload(payload, top_k=top_k)
        if not tasks:
            raise RuntimeError("full backend returned no task predictions")
        queue.put({"ok": True, "tasks": tasks})
    except Exception as exc:  # pragma: no cover - subprocess path
        queue.put({"ok": False, "error": str(exc)})


class NiCLIPCoordinateMapper:
    """Coordinate mapping with full-model first and embedding-only fallback."""

    def __init__(
        self,
        niclip_path: Optional[Path | str] = None,
        *,
        model_name: Optional[str] = None,
        section: Optional[str] = None,
        full_timeout_sec: Optional[float] = None,
        full_cooldown_sec: Optional[float] = None,
    ):
        self.model_name = model_name or os.environ.get(
            "NICLIP_MODEL_NAME", "BrainGPT-7B-v0.2"
        )
        self.section = section or os.environ.get("NICLIP_TEXT_SECTION", "abstract")
        self.full_timeout_sec = (
            float(full_timeout_sec)
            if full_timeout_sec is not None
            else float(os.environ.get("BR_NICLIP_FULL_TIMEOUT_SEC", "45"))
        )
        self.full_cooldown_sec = (
            float(full_cooldown_sec)
            if full_cooldown_sec is not None
            else float(os.environ.get("BR_NICLIP_FULL_COOLDOWN_SEC", "300"))
        )
        self._full_disabled_until = 0.0

        self.niclip_path = self._resolve_data_path(niclip_path)
        self.niclip_data_root = self._resolve_data_root(self.niclip_path)
        self.model_path = self._resolve_model_path(
            self.niclip_path, self.niclip_data_root
        )

        self.engine_config = NiclipEngineConfig(
            data_path=str(self.niclip_path),
            model_path=self.model_path,
            model_name=self.model_name,
            section=self.section,
        )
        self.engine = NiclipEngine.get(config=self.engine_config, force_reload=True)

        self.task_mapper = NiCLIPTaskMapper(data_path=self.niclip_data_root)
        self.task_priors = self._load_task_priors()
        self.concept_to_process = dict(
            getattr(self.task_mapper, "concept_to_process", {})
        )
        self._loaded = self._check_ready()

    @staticmethod
    def _looks_like_niclip_path(path: Path) -> bool:
        candidates = (
            path / "vocabulary",
            path / "data" / "vocabulary",
            path
            / "osf_data"
            / "dsj56"
            / "osfstorage"
            / "osfstorage"
            / "data"
            / "vocabulary",
        )
        return any(c.exists() for c in candidates)

    @classmethod
    def _resolve_data_path(cls, explicit: Optional[Path | str]) -> Path:
        candidates: list[Path] = []
        if explicit:
            candidates.append(Path(explicit))

        env_keys = ("NICLIP_DATA_PATH", "NICLIP_EMBEDDINGS_PATH", "NICLIP_DATA_DIR")
        for key in env_keys:
            value = os.environ.get(key)
            if value:
                candidates.append(Path(value))

        candidates.extend(
            [
                default_atlas_output_root() / "niclip",
                Path("/data/niclip"),
                Path("/data/ECoG-foundation-model/mnndl_temp/niclip"),
                get_data_root() / "niclip",
            ]
        )

        seen: set[str] = set()
        for candidate in candidates:
            token = str(candidate.resolve()) if candidate.exists() else str(candidate)
            if token in seen:
                continue
            seen.add(token)
            if cls._looks_like_niclip_path(candidate):
                return candidate

        raise FileNotFoundError(
            "NiCLIP data path not found. Checked explicit path, env paths, /data defaults, "
            "and repository fallback."
        )

    @staticmethod
    def _resolve_data_root(base: Path) -> Path:
        if (base / "vocabulary").exists():
            return base
        if (base / "data" / "vocabulary").exists():
            return base / "data"
        osf_root = base / "osf_data" / "dsj56" / "osfstorage" / "osfstorage" / "data"
        if (osf_root / "vocabulary").exists():
            return osf_root
        raise FileNotFoundError(f"NiCLIP data root unresolved under: {base}")

    def _resolve_model_path(self, base: Path, data_root: Path) -> Optional[str]:
        explicit_model = os.environ.get("NICLIP_MODEL_PATH")
        if explicit_model and Path(explicit_model).exists():
            return explicit_model

        model_dir = os.environ.get("NICLIP_MODEL_DIR")
        if model_dir:
            model_dir_path = Path(model_dir)
            if model_dir_path.is_file() and model_dir_path.exists():
                return str(model_dir_path)
            if model_dir_path.exists():
                candidate = (
                    model_dir_path
                    / f"model-clip_section-{self.section}_embedding-{self.model_name}_best.pth"
                )
                if candidate.exists():
                    return str(candidate)

        result_dirs = [
            base / "results" / "pubmed",
            data_root.parent / "results" / "pubmed",
            base
            / "osf_data"
            / "dsj56"
            / "osfstorage"
            / "osfstorage"
            / "results"
            / "pubmed",
        ]
        for directory in result_dirs:
            if not directory.exists():
                continue
            for suffix in ("best", "current", "last"):
                candidate = (
                    directory
                    / f"model-clip_section-{self.section}_embedding-{self.model_name}_{suffix}.pth"
                )
                if candidate.exists():
                    return str(candidate)

            fallback = sorted(
                directory.glob(
                    f"model-clip_section-{self.section}_embedding-{self.model_name}_*.pth"
                )
            )
            if fallback:
                return str(fallback[0])

        return None

    def _check_ready(self) -> bool:
        if not self.niclip_path.exists():
            return False
        model = self.engine.get_model()
        if model is None or getattr(model, "model", None) is None:
            logger.warning(
                "NiCLIP model checkpoint unavailable for coordinate mapping "
                "(data_path=%s, model_path=%s)",
                self.niclip_path,
                self.model_path,
            )
            return False
        return True

    def _load_task_priors(self) -> dict[str, float]:
        priors: dict[str, float] = {}
        prior_files = (self.niclip_data_root / "vocabulary").glob(
            "vocabulary-cogatlas_task-combined_embedding-*_section-*_prior.csv"
        )
        for file in prior_files:
            try:
                with open(file, encoding="utf-8") as handle:
                    header = handle.readline().strip().split(",")
                    if "name" not in header or "prior" not in header:
                        continue
                    idx_name = header.index("name")
                    idx_prior = header.index("prior")
                    for line in handle:
                        parts = line.rstrip("\n").split(",")
                        if len(parts) <= max(idx_name, idx_prior):
                            continue
                        name = parts[idx_name].strip()
                        if not name:
                            continue
                        try:
                            value = float(parts[idx_prior])
                        except ValueError:
                            continue
                        if name not in priors or value > priors[name]:
                            priors[name] = value
            except Exception:
                continue
        return priors

    @staticmethod
    def _normalize_coordinates(
        coordinates: Iterable[Sequence[float]],
    ) -> list[tuple[float, float, float]]:
        normalized: list[tuple[float, float, float]] = []
        for coord in coordinates:
            if not isinstance(coord, (list, tuple)) or len(coord) != 3:
                raise ValueError(
                    "Each coordinate must be a length-3 list/tuple: [x, y, z]"
                )
            x, y, z = coord
            normalized.append((float(x), float(y), float(z)))
        return normalized

    @staticmethod
    def _save_activation_map(
        coordinate: tuple[float, float, float], radius_mm: float
    ) -> str:
        image = _build_activation_map_from_coordinates(
            [coordinate], radius_mm=radius_mm
        )
        with tempfile.NamedTemporaryFile(suffix=".nii.gz", delete=False) as handle:
            path = handle.name
        nib.save(image, path)
        return path

    def _extract_task_predictions(
        self, payload: Any, *, top_k: int
    ) -> list[tuple[str, float]]:
        return _extract_task_predictions_payload(payload, top_k=top_k)

    def _predict_tasks_full(
        self, nifti_path: str, top_k: int
    ) -> list[tuple[str, float]]:
        now = time.time()
        if now < self._full_disabled_until:
            raise RuntimeError("full backend is in cooldown after previous timeout")

        config_kwargs = {
            "data_path": str(self.niclip_path),
            "model_path": self.model_path,
            "model_name": self.model_name,
            "section": self.section,
            "device": self.engine_config.device,
        }
        import __main__ as main_module

        main_file = getattr(main_module, "__file__", None)
        if not main_file or str(main_file).endswith("<stdin>"):
            raise RuntimeError("full backend unavailable in interactive/stdin runtime")

        ctx = mp.get_context("spawn")
        queue = ctx.Queue(maxsize=1)
        proc = ctx.Process(
            target=_predict_full_worker,
            args=(config_kwargs, nifti_path, top_k, queue),
            daemon=True,
        )
        proc.start()
        proc.join(self.full_timeout_sec if self.full_timeout_sec > 0 else None)

        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=5)
            self._full_disabled_until = time.time() + self.full_cooldown_sec
            raise TimeoutError(
                f"full backend timed out after {self.full_timeout_sec:.1f}s"
            )

        if queue.empty():
            raise RuntimeError("full backend exited without returning predictions")
        result = queue.get()
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "full backend prediction failed"))
        return [(str(name), float(score)) for name, score in result.get("tasks", [])]

    def _predict_tasks_embedding_only(
        self, nifti_path: str, top_k: int
    ) -> list[tuple[str, float]]:
        model = self.engine.get_model()
        if model is None or getattr(model, "model", None) is None:
            raise RuntimeError("NiCLIP model checkpoint not loaded")
        embedding = model.encode_fmri(nifti_path)
        payload = model.decode_to_text(embedding, top_k=top_k, return_scores=True)
        return self._extract_task_predictions(payload, top_k=top_k)

    def _tasks_to_concepts(
        self, task_predictions: list[tuple[str, float]], top_k: int
    ) -> list[dict[str, Any]]:
        concept_scores: dict[str, dict[str, Any]] = {}
        for task, task_score in task_predictions:
            concepts = self.task_mapper.get_task_concepts(task)
            primary_process = self.task_mapper.get_primary_process(task)
            process_name = (
                self.task_mapper.get_process_name(primary_process)
                if primary_process
                else "unmapped"
            )
            if not concepts:
                concepts = [task]

            for idx, concept in enumerate(concepts):
                concept_score = float(task_score) * max(0.1, 1.0 - (0.15 * idx))
                process_id = self.concept_to_process.get(concept, primary_process)
                concept_process = (
                    self.task_mapper.get_process_name(process_id)
                    if process_id
                    else process_name
                )
                record = concept_scores.get(
                    concept,
                    {
                        "concept": concept,
                        "score": concept_score,
                        "process": concept_process or "unmapped",
                        "source_tasks": [task],
                    },
                )
                if concept_score > record["score"]:
                    record["score"] = concept_score
                if task not in record["source_tasks"]:
                    record["source_tasks"].append(task)
                concept_scores[concept] = record

        ranked = sorted(
            concept_scores.values(), key=lambda row: float(row["score"]), reverse=True
        )
        return ranked[:top_k]

    def map_with_metadata(
        self,
        coordinates: Iterable[Sequence[float]],
        *,
        radius_mm: float = 10.0,
        top_k: int = 5,
        allow_full: bool = True,
    ) -> dict[str, Any]:
        if not self._loaded:
            raise RuntimeError(
                "NiCLIP coordinate mapper is not ready (model/data unavailable)."
            )

        norm_coords = self._normalize_coordinates(coordinates)
        mappings: list[dict[str, Any]] = []
        backend_counts = {"full": 0, "embedding_only": 0}
        errors: list[str] = []
        full_enabled = allow_full

        for coord in norm_coords:
            nifti_path: Optional[str] = None
            used_backend: Optional[str] = None
            try:
                nifti_path = self._save_activation_map(coord, radius_mm)
                task_predictions: list[tuple[str, float]] = []
                full_error = None

                if full_enabled:
                    try:
                        task_predictions = self._predict_tasks_full(
                            nifti_path, top_k=top_k
                        )
                        if task_predictions:
                            used_backend = "full"
                            backend_counts["full"] += 1
                    except Exception as exc:
                        full_error = str(exc)
                        full_enabled = False
                        errors.append(f"full:{coord}:{exc}")

                if not task_predictions:
                    task_predictions = self._predict_tasks_embedding_only(
                        nifti_path, top_k=top_k
                    )
                    used_backend = "embedding_only"
                    backend_counts["embedding_only"] += 1

                concepts = self._tasks_to_concepts(task_predictions, top_k=top_k)
                mapping = {
                    "coordinate": coord,
                    "concepts": concepts,
                    "backend": used_backend,
                    "source_tasks": [task for task, _ in task_predictions],
                }
                if full_error:
                    mapping["warning"] = f"full backend unavailable: {full_error}"
                mappings.append(mapping)
            except Exception as exc:
                errors.append(f"mapping:{coord}:{exc}")
                mappings.append(
                    {
                        "coordinate": coord,
                        "concepts": [],
                        "backend": None,
                        "warning": str(exc),
                    }
                )
            finally:
                if nifti_path:
                    try:
                        Path(nifti_path).unlink(missing_ok=True)
                    except Exception:
                        pass

        if backend_counts["full"] > 0 and backend_counts["embedding_only"] == 0:
            backend = "full"
        elif backend_counts["embedding_only"] > 0 and backend_counts["full"] == 0:
            backend = "embedding_only"
        elif backend_counts["full"] > 0 and backend_counts["embedding_only"] > 0:
            backend = "hybrid"
        else:
            backend = "unavailable"

        return {
            "mappings": mappings,
            "backend": backend,
            "backend_counts": backend_counts,
            "errors": errors,
            "niclip_data_path": str(self.niclip_path),
            "niclip_model_path": self.model_path,
        }

    # Compatibility helpers expected by some scripts/tests.
    def coordinate_to_concepts(
        self,
        coordinates: Iterable[Sequence[float]],
        radius: float = 10.0,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        payload = self.map_with_metadata(
            coordinates, radius_mm=radius, top_k=top_k, allow_full=True
        )
        return payload["mappings"]

    def get_task_brain_alignment(self, task_name: str) -> Optional[float]:
        return self.task_priors.get(task_name)

    def get_concept_process(self, concept: str) -> Optional[str]:
        return self.concept_to_process.get(concept)
