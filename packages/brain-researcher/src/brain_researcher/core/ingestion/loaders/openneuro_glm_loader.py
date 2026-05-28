"""Loader and helpers for OpenNeuro GLM FitLins statistical maps."""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Protocol,
    Set,
)

from brain_researcher.semantics.taxonomy.matcher import (
    ConceptMatcher,
    MatchCandidate,
    TaskMatcher,
)

from .openneuro_glm_spec_parser import ContrastSpec, TaskSpec, discover_task_specs

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


SOURCE_NAME = "openneuro_glmfitlins"


class OpenNeuroOnvocLinkerProtocol(Protocol):
    """Service-provided ONVOC linker surface used by this core loader."""

    available: bool

    def link_task_analysis(
        self,
        entity_id: str,
        *,
        names: Sequence[str],
        canonical_ids: Sequence[str],
        concept_ids: Sequence[str],
    ) -> int: ...

    def link_contrast(
        self,
        entity_id: str,
        *,
        names: Sequence[str],
        canonical_ids: Sequence[str],
        concept_ids: Sequence[str],
    ) -> int: ...

    def link_stats_map(
        self,
        entity_id: str,
        *,
        names: Sequence[str],
        contrast_onvoc_ids: Sequence[str],
        task_onvoc_ids: Sequence[str],
        dataset_ids: Sequence[str],
    ) -> int: ...


class OpenNeuroConstructManagerProtocol(Protocol):
    """Service-provided construct/process linker used by this core loader."""

    def process_ids_for_concepts(self, concept_ids: Iterable[str]) -> Set[str]: ...

    def link_entity_to_processes(
        self,
        entity_id: str,
        process_ids: Iterable[str],
        *,
        source: str,
        method: str,
        confidence: float = 0.85,
        relationship: str = "IN_DOMAIN",
    ) -> int: ...


OnvocLinkerFactory = Callable[[Any], OpenNeuroOnvocLinkerProtocol]
ConstructManagerFactory = Callable[[Any], OpenNeuroConstructManagerProtocol]


STATMAP_SUFFIXES = (
    ".nii.gz",
    ".nii",
    ".dscalar.nii",
    ".dlabel.nii",
)

_ENTITY_RE = re.compile(r"^(?P<key>[a-zA-Z0-9]+)-(?P<value>.+)$")

_DATASET_ID_RE = re.compile(r"(ds\d{3,})", re.IGNORECASE)
_DOI_RE = re.compile(r"(10\.\d{4,9}/[^\s\"<>]+)", re.IGNORECASE)
_PMID_RE = re.compile(r"pmid[:\s]*([0-9]+)", re.IGNORECASE)

NODE_LEVEL_MAP = {
    "node-subjectlevel": "subject",
    "node-runlevel": "run",
    "node-sessionlevel": "session",
    "node-datalevel": "dataset",
    "node-datasetlevel": "dataset",
    "node-onesamplet": "group",
    "node-onesampletcov": "group",
    "node-onesampletfirm": "group",
    "node-fironesamplet": "group",
    "node-twosamplet": "group",
    "node-twosampletcov": "group",
    "node-twosampletcovint": "group",
    "node-anova": "group",
}


def _strip_suffix(name: str) -> str:
    """Remove known neuroimaging suffixes from the file name."""

    for suffix in STATMAP_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _slugify(value: str) -> str:
    """Convert free text to a stable identifier component."""

    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "unknown"


def _normalize_doi(value: str) -> str:
    if not value:
        return ""
    value = value.strip()
    value = re.sub(r"^doi:\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^https?://doi\.org/", "", value, flags=re.IGNORECASE)
    return value.strip().strip(").,;")


def _extract_doi(text: str) -> Optional[str]:
    if not text:
        return None
    match = _DOI_RE.search(text)
    if match:
        return _normalize_doi(match.group(1))
    return None


def _extract_pmid(text: str) -> Optional[str]:
    if not text:
        return None
    match = _PMID_RE.search(text)
    if match:
        return match.group(1)
    return None


def _reference_title(text: str) -> str:
    if not text:
        return ""
    cleaned = " ".join(str(text).split())
    lower = cleaned.lower()
    if "doi:" in lower:
        head, _ = re.split(r"doi:\s*", cleaned, maxsplit=1, flags=re.IGNORECASE)
        return head.strip(" .;")
    return cleaned.strip()


def _parse_entities(name: str) -> Dict[str, str]:
    """Parse BIDS-style key-value entities from a file name."""

    entities: Dict[str, str] = {}
    for token in _strip_suffix(name).split("_"):
        if token in {"statmap", "bold", "cope"}:
            continue
        match = _ENTITY_RE.match(token)
        if not match:
            continue
        key = match.group("key").lower()
        value = match.group("value").strip()
        entities[key] = value
    return entities


def _dedupe_preserve_order(values: Iterable[str]) -> List[str]:
    """Return a list with duplicates removed while preserving input order."""

    seen: Set[str] = set()
    result: List[str] = []
    for item in values:
        if not item:
            continue
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


MANUAL_CONTRAST_CONCEPTS: Dict[str, Dict[str, object]] = {
    # Response inhibition / stop-signal contrasts
    "successstop": {"concept_ids": ["trm_4a3fd79d0af66"], "confidence": 0.95},
    "successstopvgo": {"concept_ids": ["trm_4a3fd79d0af66"], "confidence": 0.95},
    "successstopvfailstop": {"concept_ids": ["trm_4a3fd79d0af66"], "confidence": 0.95},
    "failstopvgo": {"concept_ids": ["trm_4a3fd79d0af66"], "confidence": 0.95},
    "allstopvgo": {"concept_ids": ["trm_4a3fd79d0af66"], "confidence": 0.95},
    "failstop": {"concept_ids": ["trm_4a3fd79d0af66"], "confidence": 0.92},
    "failstopcritvgocrit": {"concept_ids": ["trm_4a3fd79d0af66"], "confidence": 0.92},
    "allstopcritvgocrit": {"concept_ids": ["trm_4a3fd79d0af66"], "confidence": 0.92},
    "successstopcritvgocrit": {
        "concept_ids": ["trm_4a3fd79d0af66"],
        "confidence": 0.92,
    },
    "failstopcritvnoncrit": {"concept_ids": ["trm_4a3fd79d0af66"], "confidence": 0.9},
    "successstopcritvfailstopcrit": {
        "concept_ids": ["trm_4a3fd79d0af66"],
        "confidence": 0.9,
    },
    # Delay discounting contrasts
    "discounting": {"concept_ids": ["trm_a4WdpQW5JYPH0"], "confidence": 0.93},
    "choice": {"concept_ids": ["trm_a4WdpQW5JYPH0"], "confidence": 0.9},
    "choicehardveasy": {"concept_ids": ["trm_a4WdpQW5JYPH0"], "confidence": 0.9},
    "parasmallsonner": {"concept_ids": ["trm_a4WdpQW5JYPH0"], "confidence": 0.9},
    "pararelativelargelater": {"concept_ids": ["trm_a4WdpQW5JYPH0"], "confidence": 0.9},
    "paradelay": {"concept_ids": ["trm_a4WdpQW5JYPH0"], "confidence": 0.9},
    "paragain": {"concept_ids": ["trm_a4WdpQW5JYPH0"], "confidence": 0.88},
    "paraloss": {"concept_ids": ["trm_a4WdpQW5JYPH0"], "confidence": 0.88},
    "paragainvloss": {"concept_ids": ["trm_a4WdpQW5JYPH0"], "confidence": 0.88},
    # Balloon Analogue Risk contrasts
    "cashpara": {"concept_ids": ["trm_4l7BDO8GJ3LdM"], "confidence": 0.9},
    "explodepara": {"concept_ids": ["trm_4l7BDO8GJ3LdM"], "confidence": 0.9},
    "explodevcash": {"concept_ids": ["trm_4l7BDO8GJ3LdM"], "confidence": 0.92},
    "allpumps": {"concept_ids": ["trm_4l7BDO8GJ3LdM"], "confidence": 0.92},
    "pumpspara": {"concept_ids": ["trm_4l7BDO8GJ3LdM"], "confidence": 0.9},
    "pumps": {"concept_ids": ["trm_4l7BDO8GJ3LdM"], "confidence": 0.9},
    "pumpsvcash": {"concept_ids": ["trm_4l7BDO8GJ3LdM"], "confidence": 0.9},
    "pumpsvexplode": {"concept_ids": ["trm_4l7BDO8GJ3LdM"], "confidence": 0.9},
    "pumpsexplodevcontrol": {"concept_ids": ["trm_4l7BDO8GJ3LdM"], "confidence": 0.9},
    # Emotion regulation contrasts
    "attendneg": {"concept_ids": ["trm_51a690a7492eb"], "confidence": 0.9},
    "attendneutvneg": {"concept_ids": ["trm_51a690a7492eb"], "confidence": 0.9},
    "neg": {"concept_ids": ["trm_51a690a7492eb"], "confidence": 0.85},
    "pos": {"concept_ids": ["trm_51a690a7492eb"], "confidence": 0.82},
    "negvpos": {"concept_ids": ["trm_51a690a7492eb"], "confidence": 0.88},
    "negattendvsuppress": {"concept_ids": ["trm_51a690a7492eb"], "confidence": 0.9},
    "suppressneg": {"concept_ids": ["trm_51a690a7492eb"], "confidence": 0.9},
    "negmusicvsounds": {"concept_ids": ["trm_51a690a7492eb"], "confidence": 0.85},
    "posmusicvsounds": {"concept_ids": ["trm_51a690a7492eb"], "confidence": 0.85},
    "posmusicvnegmusic": {"concept_ids": ["trm_51a690a7492eb"], "confidence": 0.85},
}


def _analysis_level_from_node(node_part: Optional[str]) -> Optional[str]:
    if not node_part:
        return None
    normalized = node_part.lower()
    return NODE_LEVEL_MAP.get(normalized)


def load_path_config(config_path: Path) -> Dict[str, str]:
    """Load the path_config.json used by the FitLins repo."""

    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"path_config not found: {config_path}")
    return json.loads(config_path.read_text())


@dataclass
class StatsMapManifestRow:
    """Structured representation of a single statistical map."""

    dataset_id: str
    dataset_folder: str
    task: str
    contrast: str
    level: str
    stat: str
    space: str
    path: Path
    checksum: Optional[str] = None
    estimator: Optional[str] = None
    smoothing_fwhm: Optional[float] = None
    density: Optional[str] = None
    format: Optional[str] = None
    n_subjects: Optional[int] = None
    subject: Optional[str] = None
    session: Optional[str] = None
    run: Optional[str] = None
    hemisphere: Optional[str] = None
    description: Optional[str] = None
    node_name: Optional[str] = None
    relative_path: Optional[str] = None
    metadata: Dict[str, object] = field(default_factory=dict)

    def statsmap_id(self) -> str:
        """Return a stable Neo4j identifier for the map."""

        components = [
            "glmfitlins",
            self.dataset_id,
            self.task or "task",
            self.contrast or "contrast",
            self.level or "level",
            self.stat or "stat",
            self.space or "space",
        ]
        if self.density:
            components.append(self.density)
        if self.relative_path:
            components.append(self.relative_path)
        elif self.node_name:
            components.append(self.node_name)
        slug = ":".join(_slugify(part) for part in components)
        return slug

    def to_record(self) -> Dict[str, object]:
        """Convert to a dict ready for Neo4j ingestion."""

        record: Dict[str, object] = {
            "id": self.statsmap_id(),
            "dataset_id": self.dataset_id,
            "dataset_folder": self.dataset_folder,
            "task": self.task,
            "contrast": self.contrast,
            "level": self.level,
            "stat": self.stat,
            "space": self.space,
            "density": self.density,
            "format": self.format,
            "estimator": self.estimator,
            "smoothing_fwhm": self.smoothing_fwhm,
            "n_subjects": self.n_subjects,
            "checksum": self.checksum,
            "path": str(self.path),
            "metadata": self.metadata,
        }
        if self.subject:
            record["subject"] = self.subject
        if self.session:
            record["session"] = self.session
        if self.run:
            record["run"] = self.run
        if self.hemisphere:
            record["hemisphere"] = self.hemisphere
        if self.description:
            record["description"] = self.description
        if self.node_name:
            record["node_name"] = self.node_name
        if self.relative_path:
            record["relative_path"] = self.relative_path
        return record

    @classmethod
    def from_path(
        cls,
        dataset_id: str,
        dataset_folder: str,
        path: Path,
        dataset_root: Optional[Path] = None,
        compute_checksum: bool = False,
    ) -> Optional["StatsMapManifestRow"]:
        """Create a manifest row by parsing a map file path."""

        entities = _parse_entities(path.name)
        stat = entities.get("stat")
        if stat not in {"z", "t"}:
            logger.debug("Skipping non-stat map file %s", path)
            return None

        relative_path = None
        task = entities.get("task")
        contrast = entities.get("contrast") or entities.get("desc")
        level = entities.get("level")
        space = entities.get("space") or "unknown"
        density = entities.get("den") or entities.get("res") or None
        estimator = entities.get("model") or entities.get("estimator")
        format_hint = next((s for s in STATMAP_SUFFIXES if path.name.endswith(s)), None)

        node_name = None
        subject = entities.get("sub")
        session = entities.get("ses")
        run = entities.get("run")
        hemisphere = entities.get("hemi")
        description = entities.get("desc")

        if dataset_root is not None:
            try:
                relative = path.relative_to(dataset_root)
                relative_path = str(relative)
                parts = list(relative.parts)
            except ValueError:
                parts = []
                relative_path = None
        else:
            parts = []

        if parts:
            for part in parts:
                if part.startswith("task-"):
                    task = task or part.split("-", 1)[1]
                if part.startswith("node-"):
                    node_name = part
                    inferred = _analysis_level_from_node(part)
                    if inferred:
                        level = level or inferred
                if part.startswith("sub-") and not subject:
                    subject = part.split("-", 1)[1]
                if part.startswith("ses-") and not session:
                    session = part.split("-", 1)[1]
                if part.startswith("run-") and not run:
                    run = part.split("-", 1)[1]

        if not level:
            level = _infer_level(path, dataset_root) or "unknown"
        if not task:
            task = "unknown"
        if not contrast:
            contrast = "unknown"

        checksum = None
        if compute_checksum:
            checksum = cls._compute_checksum(path)

        metadata: Dict[str, object] = {"entities": entities}
        metadata["dataset_folder"] = dataset_folder
        if node_name:
            metadata["node_dir"] = node_name
        if relative_path:
            metadata["relative_path"] = relative_path
        if subject:
            metadata["subject_dir"] = subject
        if session:
            metadata["session_dir"] = session

        return cls(
            dataset_id=dataset_id,
            dataset_folder=dataset_folder,
            task=task,
            contrast=contrast,
            level=level or "unknown",
            stat=stat,
            space=space,
            density=density,
            path=path,
            format=format_hint,
            estimator=estimator,
            checksum=checksum,
            subject=subject,
            session=session,
            run=run,
            hemisphere=hemisphere,
            description=description,
            node_name=node_name,
            relative_path=relative_path,
            metadata=metadata,
        )

    @staticmethod
    def _compute_checksum(path: Path) -> str:
        """Compute SHA-256 checksum for the file path."""

        h = sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()


@dataclass
class LinkMatch:
    label: str
    confidence: float
    method: str
    node_id: Optional[str]
    canonical_ids: List[str] = field(default_factory=list)
    concept_ids: List[str] = field(default_factory=list)
    onvoc_ids: List[str] = field(default_factory=list)


@dataclass
class LinkResult:
    created: int = 0
    matches: List[LinkMatch] = field(default_factory=list)

    def extend(self, other: "LinkResult") -> None:
        self.created += other.created
        self.matches.extend(other.matches)

    @property
    def canonical_id_set(self) -> List[str]:
        return _dedupe_preserve_order(
            canonical_id
            for match in self.matches
            for canonical_id in match.canonical_ids
        )

    @property
    def concept_id_set(self) -> List[str]:
        return _dedupe_preserve_order(
            concept_id for match in self.matches for concept_id in match.concept_ids
        )

    @property
    def onvoc_id_set(self) -> List[str]:
        return _dedupe_preserve_order(
            onvoc_id for match in self.matches for onvoc_id in match.onvoc_ids
        )


def _infer_level(path: Path, dataset_root: Optional[Path]) -> Optional[str]:
    """Infer analysis level from the directory structure if not encoded as entity."""

    for part in reversed(path.parts):
        if part.startswith("node-"):
            mapped = _analysis_level_from_node(part)
            if mapped:
                return mapped
        if part.startswith("level-"):
            return part.split("-", 1)[1]
        if part in {"run", "subject", "dataset"}:
            return part
    if dataset_root and "task-" in path.name:
        relative = path.relative_to(dataset_root)
        for part in relative.parts:
            if part.startswith("level"):
                return part.replace("level", "").strip("-") or None
    return None


class OpenNeuroGLMFitlinsLoader:
    """Discover and prepare GLM FitLins statistical maps for ingestion."""

    def __init__(
        self,
        datasets_root: Path,
        manifest_path: Optional[Path] = None,
        compute_checksum: bool = False,
        onvoc_linker_factory: Optional[OnvocLinkerFactory] = None,
        construct_manager_factory: Optional[ConstructManagerFactory] = None,
    ) -> None:
        self.datasets_root = Path(datasets_root)
        self.manifest_path = Path(manifest_path) if manifest_path else None
        self.compute_checksum = compute_checksum
        self._space_cache: Set[str] = set()
        self._modelspec_cache: Set[str] = set()
        self._modelspec_hash_cache: Dict[Path, str] = {}
        self._spec_lookup: Dict[Path, TaskSpec] = {}
        self._resource_cache: Set[str] = set()
        self._task_lookup: Dict[tuple[str, str], str] = {}
        self._contrast_lookup: Dict[tuple[str, str, str], str] = {}
        self._task_canonical_lookup: Dict[tuple[str, str], Set[str]] = {}
        self._task_concept_lookup: Dict[tuple[str, str], Set[str]] = {}
        self._task_onvoc_lookup: Dict[tuple[str, str], Set[str]] = {}
        self._contrast_canonical_lookup: Dict[tuple[str, str, str], Set[str]] = {}
        self._contrast_concept_lookup: Dict[tuple[str, str, str], Set[str]] = {}
        self._contrast_onvoc_lookup: Dict[tuple[str, str, str], Set[str]] = {}
        self._task_matcher = TaskMatcher()
        self._concept_matcher = ConceptMatcher()
        self._onvoc_linker_factory = onvoc_linker_factory
        self._construct_manager_factory = construct_manager_factory
        self._onvoc_linker: Optional[OpenNeuroOnvocLinkerProtocol] = None
        self._construct_manager: Optional[OpenNeuroConstructManagerProtocol] = None
        self._contrast_confidence_lookup: Dict[
            tuple[str, str, str], Dict[str, float]
        ] = {}
        self._publication_cache: Dict[str, List[str]] = {}

    @classmethod
    def from_config(
        cls,
        config: Dict[str, str],
        *,
        manifest_path: Optional[Path | str] = None,
        compute_checksum: bool = False,
        onvoc_linker_factory: Optional[OnvocLinkerFactory] = None,
        construct_manager_factory: Optional[ConstructManagerFactory] = None,
    ) -> "OpenNeuroGLMFitlinsLoader":
        datasets_root = Path(config["datasets_folder"])
        resolved_manifest = Path(manifest_path) if manifest_path is not None else None
        return cls(
            datasets_root=datasets_root,
            manifest_path=resolved_manifest,
            compute_checksum=compute_checksum,
            onvoc_linker_factory=onvoc_linker_factory,
            construct_manager_factory=construct_manager_factory,
        )

    def discover(self) -> List[StatsMapManifestRow]:
        if self.manifest_path and self.manifest_path.exists():
            logger.info("Loading manifest from %s", self.manifest_path)
            return list(self._load_manifest(self.manifest_path))
        return list(self._scan_filesystem())

    def _scan_filesystem(self) -> Iterator[StatsMapManifestRow]:
        analyses_root = self._analyses_root()
        if analyses_root is None:
            return
        for dataset_dir in sorted(d for d in analyses_root.iterdir() if d.is_dir()):
            canonical_id = self._canonical_dataset_id(dataset_dir.name)
            if canonical_id is None:
                continue
            for path in dataset_dir.rglob("*statmap*.nii*"):
                record = StatsMapManifestRow.from_path(
                    dataset_id=canonical_id,
                    dataset_folder=dataset_dir.name,
                    path=path,
                    dataset_root=dataset_dir,
                    compute_checksum=self.compute_checksum,
                )
                if record:
                    yield record

    def _load_manifest(self, manifest_path: Path) -> Iterator[StatsMapManifestRow]:
        rows = json.loads(manifest_path.read_text())
        total = len(rows) if isinstance(rows, list) else None
        for idx, row in enumerate(rows, 1):
            if idx % 1000 == 0:
                if total is not None:
                    logger.info("Manifest progress: %d/%d rows", idx, total)
                else:
                    logger.info("Manifest progress: %d rows", idx)
            yield StatsMapManifestRow(
                dataset_id=row["dataset_id"],
                dataset_folder=row.get("dataset_folder", row["dataset_id"]),
                task=row.get("task", "unknown"),
                contrast=row.get("contrast", "unknown"),
                level=row.get("level", "unknown"),
                stat=row.get("stat", "z"),
                space=row.get("space", "unknown"),
                density=row.get("density"),
                path=Path(row["path"]),
                format=row.get("format"),
                estimator=row.get("estimator"),
                checksum=row.get("checksum"),
                smoothing_fwhm=row.get("smoothing_fwhm"),
                n_subjects=row.get("n_subjects"),
                subject=row.get("subject"),
                session=row.get("session"),
                run=row.get("run"),
                hemisphere=row.get("hemisphere"),
                description=row.get("description"),
                node_name=row.get("node_name"),
                relative_path=row.get("relative_path"),
                metadata=row.get("metadata", {}),
            )

    def _analyses_root(self) -> Optional[Path]:
        analyses_root = self.datasets_root / "analyses"
        if not analyses_root.exists():
            logger.warning("Analyses root is missing: %s", analyses_root)
            return None
        return analyses_root

    def _openneuro_metadata_root(self) -> Path:
        return Path(
            os.getenv(
                "OPENNEURO_METADATA_ROOT",
                "/app/data/openneuro_metadata",
            )
        )

    def _dataset_metadata_path(self, dataset_id: str) -> Path:
        return (
            self._openneuro_metadata_root()
            / "openneuro"
            / dataset_id
            / "dataset_description.json"
        )

    def _load_dataset_description(self, dataset_id: str) -> Optional[Dict[str, Any]]:
        dataset_path = self._dataset_metadata_path(dataset_id)
        if not dataset_path.exists():
            return None
        try:
            return json.loads(dataset_path.read_text())
        except Exception as exc:
            logger.debug(
                "Failed to read dataset_description for %s: %s", dataset_id, exc
            )
            return None

    def _dataset_node_id(self, db, dataset_id: str) -> Optional[str]:
        if not dataset_id:
            return None
        dataset_key = f"ds:openneuro:{dataset_id.lower()}"
        candidates = [
            ("id", dataset_key),
            ("id", dataset_id),
            ("dataset_id", dataset_id),
            ("name", dataset_id),
            ("dataset_id", dataset_id.lower()),
            ("name", dataset_id.lower()),
        ]
        for key, value in candidates:
            try:
                matches = db.find_nodes("Dataset", {key: value})
            except Exception:  # pragma: no cover - defensive
                matches = []
            if matches:
                return matches[0][0]
        return None

    def _publication_records_for_dataset(
        self, db, dataset_id: str
    ) -> List[Dict[str, Any]]:
        description = self._load_dataset_description(dataset_id)
        records: List[Dict[str, Any]] = []
        seen_keys: Set[str] = set()

        if description:
            for ref in description.get("ReferencesAndLinks", []) or []:
                ref_text = str(ref).strip()
                if not ref_text:
                    continue
                doi = _extract_doi(ref_text)
                pmid = _extract_pmid(ref_text)
                title = _reference_title(ref_text)
                dedupe_key = doi or (f"pmid:{pmid}" if pmid else ref_text)
                if dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)
                records.append(
                    {
                        "doi": doi,
                        "pmid": pmid,
                        "title": title,
                        "reference": ref_text,
                        "is_dataset_doi": False,
                    }
                )

            if not records and description.get("DatasetDOI"):
                dataset_doi = _normalize_doi(str(description["DatasetDOI"]))
                if dataset_doi:
                    records.append(
                        {
                            "doi": dataset_doi,
                            "pmid": None,
                            "title": description.get("Name") or dataset_id,
                            "reference": f"Dataset DOI: {dataset_doi}",
                            "is_dataset_doi": True,
                        }
                    )

        if not records:
            dataset_node_id = self._dataset_node_id(db, dataset_id)
            if dataset_node_id:
                try:
                    nodes = db.find_nodes(properties={"id": dataset_node_id})
                except Exception:
                    nodes = []
                if nodes:
                    props = nodes[0][1]
                    for candidate in [
                        props.get("primary_url"),
                        props.get("source_version"),
                        props.get("doi"),
                        props.get("DatasetDOI"),
                    ]:
                        doi = _extract_doi(str(candidate or ""))
                        if doi:
                            records.append(
                                {
                                    "doi": doi,
                                    "pmid": None,
                                    "title": props.get("name") or dataset_id,
                                    "reference": f"Dataset DOI: {doi}",
                                    "is_dataset_doi": True,
                                }
                            )
                            break

        return records

    def _ensure_publications(self, db, dataset_id: str) -> tuple[List[str], int, int]:
        dataset_key = dataset_id.lower()
        if dataset_key in self._publication_cache:
            return self._publication_cache[dataset_key], 0, 0

        records = self._publication_records_for_dataset(db, dataset_id)
        publication_ids: List[str] = []
        created_count = 0
        dataset_links = 0

        for record in records:
            doi = record.get("doi") or ""
            pmid = record.get("pmid") or ""
            reference = record.get("reference") or ""
            if doi:
                node_id = doi.lower()
            elif pmid:
                node_id = f"pmid:{pmid}"
            else:
                node_id = f"ref:{sha256(reference.encode()).hexdigest()[:12]}"

            if node_id in publication_ids:
                continue

            props = {
                "id": node_id,
                "doi": doi or None,
                "pmid": pmid or None,
                "title": record.get("title") or reference or node_id,
                "reference": reference or None,
                "source": SOURCE_NAME,
                "dataset_id": dataset_id,
            }
            if record.get("is_dataset_doi"):
                props["is_dataset_doi"] = True

            existing = self._node_exists(db, node_id)
            db.create_node(["Publication"], props, node_id=node_id)
            if not existing:
                created_count += 1

            publication_ids.append(node_id)

        dataset_node_id = self._dataset_node_id(db, dataset_id)
        if dataset_node_id:
            for pub_id in publication_ids:
                if db.create_relationship(
                    dataset_node_id,
                    pub_id,
                    "CITED_BY",
                    {"source": SOURCE_NAME},
                ):
                    dataset_links += 1

        self._publication_cache[dataset_key] = publication_ids
        return publication_ids, created_count, dataset_links

    def _canonical_dataset_id(self, dataset_folder: str) -> Optional[str]:
        match = _DATASET_ID_RE.search(dataset_folder)
        if not match:
            return None
        return match.group(1).lower()

    def to_neo4j_payload(
        self, records: Iterable[StatsMapManifestRow]
    ) -> Dict[str, List[Dict[str, object]]]:
        stats_maps = [row.to_record() for row in records]
        return {"stats_maps": stats_maps}

    def ingest(
        self,
        db,
        *,
        statsmodel_dir: Optional[Path] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Ingest discovered statistical maps into the graph database."""

        logger.info("Discovering stats maps...")
        records = self.discover()
        if limit is not None:
            records = records[:limit]
        logger.info("Discovered %d stats maps", len(records))

        stats = {
            "maps_processed": 0,
            "maps_created": 0,
            "template_spaces_created": 0,
            "template_space_links": 0,
            "model_specs_created": 0,
            "model_spec_links": 0,
            "model_spec_task_links": 0,
            "task_analyses_created": 0,
            "task_analyses_processed": 0,
            "contrasts_created": 0,
            "conditions_created": 0,
            "subjects_created": 0,
            "data_resources_created": 0,
            "map_task_links": 0,
            "map_contrast_links": 0,
            "statsmap_measures": 0,
            "statsmap_suggests": 0,
            "statsmap_domain_links": 0,
            "map_resources_created": 0,
            "task_analysis_task_links": 0,
            "task_analysis_measures": 0,
            "task_analysis_suggests": 0,
            "task_analysis_domain_links": 0,
            "contrast_concept_links": 0,
            "task_analysis_onvoc_links": 0,
            "contrast_onvoc_links": 0,
            "statsmap_onvoc_links": 0,
            "publications_created": 0,
            "publication_links": 0,
            "dataset_citation_links": 0,
            "failures": [],
        }

        self._ensure_onvoc_linker(db)

        statsmodel_root = Path(statsmodel_dir) if statsmodel_dir else None

        if statsmodel_root and statsmodel_root.exists():
            spec_stats = self._ingest_specs(db, statsmodel_root)
            for key, value in spec_stats.items():
                if key == "failures":
                    stats["failures"].extend(value)
                else:
                    stats[key] = stats.get(key, 0) + value

        total_maps = len(records)
        logger.info("Statsmap ingest start: %d maps", total_maps)
        for row in records:
            stats["maps_processed"] += 1
            if stats["maps_processed"] % 100 == 0:
                logger.info(
                    "Statsmap ingest progress: %d/%d maps",
                    stats["maps_processed"],
                    total_maps,
                )
            map_id = row.statsmap_id()

            try:
                existing_map = self._node_exists(db, map_id)
                map_props = self._build_stats_map_properties(row)
                db.create_node(["StatsMap"], map_props, node_id=map_id)
                if not existing_map:
                    stats["maps_created"] += 1

                space_id, space_props = self._template_space_for(row)
                space_existing = self._node_exists(db, space_id)
                if space_id not in self._space_cache:
                    db.create_node(["TemplateSpace"], space_props, node_id=space_id)
                    if not space_existing:
                        stats["template_spaces_created"] += 1
                    self._space_cache.add(space_id)

                if db.create_relationship(
                    map_id,
                    space_id,
                    "IN_SPACE",
                    {"source": SOURCE_NAME},
                ):
                    stats["template_space_links"] += 1

                spec_props = self._prepare_model_spec(row, statsmodel_root)
                if spec_props:
                    spec_id = spec_props["id"]
                    spec_existing = self._node_exists(db, spec_id)
                    if spec_id not in self._modelspec_cache:
                        db.create_node(["ModelSpec"], spec_props, node_id=spec_id)
                        if not spec_existing:
                            stats["model_specs_created"] += 1
                        self._modelspec_cache.add(spec_id)

                    if db.create_relationship(
                        map_id,
                        spec_id,
                        "COMPUTED_WITH",
                        {"source": SOURCE_NAME},
                    ):
                        stats["model_spec_links"] += 1

                # Link to task analysis
                task_slug = _slugify(row.task.replace("task-", ""))
                task_key = (row.dataset_id.lower(), task_slug)
                task_node_id = self._task_lookup.get(task_key)
                if task_node_id:
                    if db.create_relationship(
                        map_id,
                        task_node_id,
                        "GENERATED_FROM",
                        {"source": SOURCE_NAME},
                    ):
                        stats["map_task_links"] += 1
                else:
                    logger.debug(
                        "No TaskAnalysis found for dataset=%s task=%s",
                        row.dataset_id,
                        row.task,
                    )

                # Link to contrast
                contrast_slug = _slugify(row.contrast)
                contrast_key = (row.dataset_id.lower(), task_slug, contrast_slug)
                contrast_node_id = self._contrast_lookup.get(contrast_key)
                if contrast_node_id:
                    if db.create_relationship(
                        map_id,
                        contrast_node_id,
                        "DERIVED_FROM",
                        {"source": SOURCE_NAME},
                    ):
                        stats["map_contrast_links"] += 1
                else:
                    logger.debug(
                        "No Contrast found for dataset=%s task=%s contrast=%s",
                        row.dataset_id,
                        row.task,
                        row.contrast,
                    )

                concept_conf_map = self._contrast_confidence_lookup.get(
                    contrast_key, {}
                )
                for concept_id, confidence in concept_conf_map.items():
                    if confidence >= 0.9:
                        rel_type = "MEASURES"
                    elif confidence >= 0.75:
                        rel_type = "SUGGESTS_MEASURES"
                    else:
                        continue
                    if not self._node_exists(db, concept_id):
                        continue
                    if self._relationship_exists(db, map_id, concept_id, rel_type):
                        continue
                    rel_props = {
                        "source": f"{SOURCE_NAME}_inferred",
                        "method": "contrast_match",
                        "confidence": float(confidence),
                    }
                    if db.create_relationship(map_id, concept_id, rel_type, rel_props):
                        if rel_type == "MEASURES":
                            stats["statsmap_measures"] += 1
                        else:
                            stats["statsmap_suggests"] += 1

                construct_manager = (
                    self._get_construct_manager(db) if concept_conf_map else None
                )
                if concept_conf_map and construct_manager is not None:
                    domain_concept_ids = [
                        concept_id
                        for concept_id, confidence in concept_conf_map.items()
                        if confidence >= 0.75
                    ]
                    if domain_concept_ids:
                        process_ids = construct_manager.process_ids_for_concepts(
                            domain_concept_ids
                        )
                        if process_ids:
                            created = construct_manager.link_entity_to_processes(
                                map_id,
                                process_ids,
                                source=f"{SOURCE_NAME}_inferred",
                                method="contrast_concept",
                                confidence=0.8,
                            )
                            if created:
                                stats["statsmap_domain_links"] += created

                task_onvoc_ids = sorted(self._task_onvoc_lookup.get(task_key, set()))
                if not task_onvoc_ids and task_node_id:
                    task_onvoc_ids = sorted(self._fetch_onvoc_ids(db, task_node_id))

                contrast_onvoc_ids = sorted(
                    self._contrast_onvoc_lookup.get(contrast_key, set())
                )
                if not contrast_onvoc_ids and contrast_node_id:
                    contrast_onvoc_ids = sorted(
                        self._fetch_onvoc_ids(db, contrast_node_id)
                    )
                if self._onvoc_linker:
                    try:
                        stats[
                            "statsmap_onvoc_links"
                        ] += self._onvoc_linker.link_stats_map(
                            map_id,
                            names=[row.contrast, row.task, row.dataset_id],
                            contrast_onvoc_ids=contrast_onvoc_ids,
                            task_onvoc_ids=task_onvoc_ids,
                            dataset_ids=[row.dataset_id],
                        )
                    except Exception as exc:  # pragma: no cover - defensive
                        logger.debug(
                            "ONVOC linking failed for StatsMap %s: %s",
                            map_id,
                            exc,
                        )

                created_resource = self._ensure_data_resource(
                    db,
                    row.path,
                    owner_id=map_id,
                    base_path=self.datasets_root,
                )
                if created_resource:
                    stats["map_resources_created"] += 1

            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Failed to ingest stat map %s: %s",
                    map_id,
                    exc,
                )
                stats["failures"].append({"id": map_id, "error": str(exc)})

        return stats

    def _build_stats_map_properties(self, row: StatsMapManifestRow) -> Dict[str, Any]:
        path = row.path
        try:
            rel_path = path.relative_to(self.datasets_root)
        except ValueError:
            rel_path = None

        symlink_target = None
        is_symlink = path.is_symlink()
        if is_symlink:
            try:
                symlink_target = str(path.resolve(strict=False))
            except OSError:
                symlink_target = None

        file_size_bytes = None
        try:
            file_size_bytes = path.lstat().st_size
        except OSError:
            file_size_bytes = None

        metadata_json = (
            json.dumps(row.metadata, sort_keys=True) if row.metadata else None
        )

        properties: Dict[str, Any] = {
            "id": row.statsmap_id(),
            "source": SOURCE_NAME,
            "provided_by": SOURCE_NAME,
            "dataset_id": row.dataset_id,
            "dataset_folder": row.dataset_folder,
            "task": row.task,
            "contrast": row.contrast,
            "analysis_level": row.level,
            "stat_type": row.stat,
            "space": row.space,
            "density": row.density,
            "format": (row.format.lstrip(". ") if row.format else None),
            "estimator": row.estimator,
            "smoothing_fwhm": row.smoothing_fwhm,
            "n_subjects": row.n_subjects,
            "checksum": row.checksum,
            "path": str(path),
            "relative_path": str(rel_path) if rel_path else None,
            "is_symlink": is_symlink,
            "symlink_target": symlink_target,
            "file_size_bytes": file_size_bytes,
            "metadata_json": metadata_json,
            "ingested_at": datetime.utcnow().isoformat(),
        }
        if row.subject:
            properties["subject"] = row.subject
        if row.session:
            properties["session"] = row.session
        if row.run:
            properties["run"] = row.run
        if row.hemisphere:
            properties["hemisphere"] = row.hemisphere
        if row.description:
            properties["description"] = row.description
        if row.node_name:
            properties["node_name"] = row.node_name
        if row.relative_path:
            properties["relative_path"] = row.relative_path

        if not row.dataset_folder or row.dataset_folder == row.dataset_id:
            properties.pop("dataset_folder", None)

        return {
            key: value
            for key, value in properties.items()
            if value not in (None, "", [])
        }

    def _ingest_specs(self, db, statsmodel_root: Path) -> Dict[str, Any]:
        counts: Dict[str, Any] = {
            "taskspecs_created": 0,
            "taskspec_dataset_links": 0,
            "task_analyses_processed": 0,
            "task_analyses_created": 0,
            "model_specs_created": 0,
            "model_spec_task_links": 0,
            "task_analysis_task_links": 0,
            "task_analysis_measures": 0,
            "task_analysis_suggests": 0,
            "task_analysis_onvoc_links": 0,
            "task_analysis_domain_links": 0,
            "contrasts_created": 0,
            "contrast_concept_links": 0,
            "contrast_onvoc_links": 0,
            "conditions_created": 0,
            "subjects_created": 0,
            "data_resources_created": 0,
            "publications_created": 0,
            "publication_links": 0,
            "dataset_citation_links": 0,
            "failures": [],
        }

        task_specs = discover_task_specs(statsmodel_root)
        total_specs = len(task_specs)
        logger.info("Spec ingest start: %d specs", total_specs)

        for spec in task_specs:
            self._spec_lookup[spec.spec_path] = spec
            counts["task_analyses_processed"] += 1
            if counts["task_analyses_processed"] % 100 == 0:
                logger.info(
                    "Spec ingest progress: %d/%d specs",
                    counts["task_analyses_processed"],
                    total_specs,
                )
            try:
                publication_ids, created_pubs, dataset_links = (
                    self._ensure_publications(db, spec.dataset_id)
                )
                counts["publications_created"] += created_pubs
                counts["dataset_citation_links"] += dataset_links

                taskspec_id = self._taskspec_id(spec.dataset_id, spec.task_name)
                taskspec_props = self._build_taskspec_properties(spec)
                existing_taskspec = self._node_exists(db, taskspec_id)
                db.create_node(["TaskSpec"], taskspec_props, node_id=taskspec_id)
                if not existing_taskspec:
                    counts["taskspecs_created"] += 1

                dataset_node_id = self._dataset_node_id(db, spec.dataset_id)
                if dataset_node_id:
                    if db.create_relationship(
                        dataset_node_id,
                        taskspec_id,
                        "HAS_TASK",
                        {"source": SOURCE_NAME},
                    ):
                        counts["taskspec_dataset_links"] += 1

                task_id = self._task_analysis_id(spec.dataset_id, spec.task_name)
                task_props = self._build_task_analysis_properties(spec)
                existing_task = self._node_exists(db, task_id)
                db.create_node(["TaskAnalysis"], task_props, node_id=task_id)
                if not existing_task:
                    counts["task_analyses_created"] += 1

                task_key = (spec.dataset_id.lower(), _slugify(spec.task_name))
                self._task_lookup[task_key] = task_id

                link_result = self._link_task_analysis_to_tasks(
                    db,
                    task_id,
                    spec.task_name,
                    context={
                        "source": SOURCE_NAME,
                        "dataset": spec.dataset_id,
                    },
                )
                counts["task_analysis_task_links"] += link_result.created
                canonical_ids = link_result.canonical_id_set
                concept_ids = link_result.concept_id_set
                onvoc_ids = link_result.onvoc_id_set
                if self._onvoc_linker:
                    try:
                        counts[
                            "task_analysis_onvoc_links"
                        ] += self._onvoc_linker.link_task_analysis(
                            task_id,
                            names=[spec.task_name],
                            canonical_ids=canonical_ids,
                            concept_ids=concept_ids,
                        )
                    except Exception as exc:  # pragma: no cover - defensive
                        logger.debug(
                            "ONVOC linking failed for TaskAnalysis %s: %s",
                            task_id,
                            exc,
                        )
                    # Refresh ONVOC ids after linking so downstream stats maps inherit them.
                    onvoc_ids = self._fetch_onvoc_ids(db, task_id)
                self._task_canonical_lookup.setdefault(task_key, set()).update(
                    canonical_ids
                )
                self._task_concept_lookup.setdefault(task_key, set()).update(
                    concept_ids
                )
                self._task_onvoc_lookup.setdefault(task_key, set()).update(onvoc_ids)

                domain_source_concepts: Set[str] = set(concept_ids)

                for match in link_result.matches:
                    rel_type = None
                    if match.confidence >= 0.9:
                        rel_type = "MEASURES"
                    elif match.confidence >= 0.75:
                        rel_type = "SUGGESTS_MEASURES"
                    if not rel_type:
                        continue

                    candidate_records: List[Dict[str, object]] = []
                    if match.concept_ids:
                        for concept_id in match.concept_ids:
                            candidate_records.append(
                                {
                                    "concept_id": concept_id,
                                    "rel_type": rel_type,
                                    "confidence": float(match.confidence),
                                }
                            )
                    else:
                        candidate_records.extend(
                            self._task_concept_relationships(db, match.node_id)
                        )

                    for record in candidate_records:
                        concept_id = record.get("concept_id")
                        if not concept_id:
                            continue
                        concept_id = str(concept_id)
                        rel_type_override = str(record.get("rel_type") or rel_type)
                        if not rel_type_override:
                            continue
                        if not self._node_exists(db, concept_id):
                            continue
                        if self._relationship_exists(
                            db, task_id, concept_id, rel_type_override
                        ):
                            domain_source_concepts.add(concept_id)
                            continue
                        rel_props = {
                            "source": f"{SOURCE_NAME}_inferred",
                            "method": match.method,
                            "confidence": float(
                                record.get("confidence", match.confidence)
                            ),
                        }
                        if db.create_relationship(
                            task_id,
                            concept_id,
                            rel_type_override,
                            rel_props,
                        ):
                            domain_source_concepts.add(concept_id)
                            if rel_type_override == "MEASURES":
                                counts["task_analysis_measures"] += 1
                            else:
                                counts["task_analysis_suggests"] += 1

                concept_ids = sorted(domain_source_concepts)

                construct_manager = (
                    self._get_construct_manager(db) if concept_ids else None
                )
                if concept_ids and construct_manager is not None:
                    process_ids = construct_manager.process_ids_for_concepts(
                        concept_ids
                    )
                    if process_ids:
                        created = construct_manager.link_entity_to_processes(
                            task_id,
                            process_ids,
                            source=f"{SOURCE_NAME}_inferred",
                            method="task_concept",
                            confidence=0.82,
                        )
                        if created:
                            counts["task_analysis_domain_links"] += created

                # Link auxiliary resources (subjects, basic-details, contrasts JSON)
                for resource_path in spec.auxiliary_resources:
                    created = self._ensure_data_resource(
                        db,
                        resource_path,
                        owner_id=task_id,
                        base_path=statsmodel_root,
                    )
                    if created:
                        counts["data_resources_created"] += 1

                # Model specification node
                spec_hash = self._hash_file_cached(spec.spec_path)
                spec_id = self._modelspec_id(spec.dataset_id, spec.task_name, spec_hash)
                spec_props = self._build_model_spec_properties(spec, spec_hash)
                existing_spec = self._node_exists(db, spec_id)
                db.create_node(["ModelSpec"], spec_props, node_id=spec_id)
                if not existing_spec:
                    counts["model_specs_created"] += 1

                if db.create_relationship(
                    spec_id,
                    task_id,
                    "DESCRIBES_TASK",
                    {"source": SOURCE_NAME},
                ):
                    counts["model_spec_task_links"] += 1

                created = self._ensure_data_resource(
                    db,
                    spec.spec_path,
                    owner_id=spec_id,
                    base_path=statsmodel_root,
                )
                if created:
                    counts["data_resources_created"] += 1

                # Subjects
                for subject_code in spec.subjects:
                    subject_id = self._subject_id(spec.dataset_id, subject_code)
                    subject_props = {
                        "id": subject_id,
                        "source": SOURCE_NAME,
                        "dataset_id": spec.dataset_id,
                        "subject_code": subject_code,
                    }
                    existing_subject = self._node_exists(db, subject_id)
                    db.create_node(["Subject"], subject_props, node_id=subject_id)
                    if not existing_subject:
                        counts["subjects_created"] += 1
                    db.create_relationship(
                        subject_id,
                        task_id,
                        "PARTICIPATES_IN",
                        {"source": SOURCE_NAME},
                    )

                # Conditions and contrasts
                for contrast in spec.contrasts:
                    contrast_id = self._contrast_id(
                        spec.dataset_id, spec.task_name, contrast.name
                    )
                    contrast_props = self._build_contrast_properties(
                        spec, contrast, contrast_id
                    )
                    existing_contrast = self._node_exists(db, contrast_id)
                    db.create_node(["Contrast"], contrast_props, node_id=contrast_id)
                    if not existing_contrast:
                        counts["contrasts_created"] += 1

                    contrast_key = (
                        spec.dataset_id.lower(),
                        _slugify(spec.task_name),
                        _slugify(contrast.name),
                    )
                    self._contrast_lookup[contrast_key] = contrast_id

                    db.create_relationship(
                        spec_id,
                        contrast_id,
                        "HAS_CONTRAST",
                        {"source": SOURCE_NAME},
                    )

                    contrast_links = self._link_contrast_to_concepts(
                        db,
                        contrast_id,
                        contrast.name,
                    )
                    counts["contrast_concept_links"] += contrast_links.created
                    contrast_canonical_ids = contrast_links.canonical_id_set
                    contrast_concept_ids = contrast_links.concept_id_set
                    contrast_onvoc_ids = contrast_links.onvoc_id_set
                    if self._onvoc_linker:
                        try:
                            counts[
                                "contrast_onvoc_links"
                            ] += self._onvoc_linker.link_contrast(
                                contrast_id,
                                names=[contrast.name],
                                canonical_ids=contrast_canonical_ids,
                                concept_ids=contrast_concept_ids,
                            )
                        except Exception as exc:  # pragma: no cover - defensive
                            logger.debug(
                                "ONVOC linking failed for Contrast %s: %s",
                                contrast_id,
                                exc,
                            )
                        contrast_onvoc_ids = self._fetch_onvoc_ids(db, contrast_id)
                    self._contrast_canonical_lookup.setdefault(
                        contrast_key, set()
                    ).update(contrast_canonical_ids)
                    self._contrast_concept_lookup.setdefault(
                        contrast_key, set()
                    ).update(contrast_concept_ids)
                    self._contrast_onvoc_lookup.setdefault(contrast_key, set()).update(
                        contrast_onvoc_ids
                    )

                    if publication_ids:
                        for pub_id in publication_ids:
                            if db.create_relationship(
                                contrast_id,
                                pub_id,
                                "BELONGS_TO",
                                {"source": SOURCE_NAME},
                            ):
                                counts["publication_links"] += 1

                    confidence_map = self._contrast_confidence_lookup.setdefault(
                        contrast_key, {}
                    )
                    for match in contrast_links.matches:
                        node_id = match.node_id
                        if not node_id:
                            continue
                        current = confidence_map.get(node_id, 0.0)
                        if match.confidence > current:
                            confidence_map[node_id] = float(match.confidence)

                    for order, condition_name in enumerate(contrast.condition_list):
                        condition_id = self._condition_id(
                            spec.dataset_id,
                            spec.task_name,
                            condition_name,
                        )
                        condition_props = self._build_condition_properties(
                            spec,
                            condition_name,
                            order,
                            condition_id,
                        )
                        existing_condition = self._node_exists(db, condition_id)
                        db.create_node(
                            ["Condition"], condition_props, node_id=condition_id
                        )
                        if not existing_condition:
                            counts["conditions_created"] += 1

                        db.create_relationship(
                            task_id,
                            condition_id,
                            "HAS_CONDITION",
                            {"source": SOURCE_NAME, "order": order},
                        )

                        weight = (
                            contrast.weights[order]
                            if order < len(contrast.weights)
                            else None
                        )
                        rel_props = {"source": SOURCE_NAME, "order": order}
                        if weight is not None:
                            rel_props["weight"] = weight
                        db.create_relationship(
                            contrast_id,
                            condition_id,
                            "USES_CONDITION",
                            rel_props,
                        )

            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning(
                    "Failed to ingest spec for dataset=%s task=%s: %s",
                    spec.dataset_id,
                    spec.task_name,
                    exc,
                )
                counts["failures"].append(
                    {
                        "dataset_id": spec.dataset_id,
                        "task": spec.task_name,
                        "error": str(exc),
                    }
                )

        return counts

    def _template_space_for(
        self, row: StatsMapManifestRow
    ) -> tuple[str, Dict[str, Any]]:
        space_name = row.space or "unknown"
        density = row.density
        slug_components = [_slugify(space_name)]
        if density:
            slug_components.append(_slugify(density))
        space_id = "space:" + ":".join(slug_components)
        props: Dict[str, Any] = {
            "id": space_id,
            "name": space_name,
            "source": SOURCE_NAME,
        }
        if density:
            props["density"] = density
        return space_id, props

    def _task_analysis_id(self, dataset_id: str, task_name: str) -> str:
        return ":".join(
            [
                "taskanalysis",
                SOURCE_NAME,
                _slugify(dataset_id),
                _slugify(task_name),
            ]
        )

    def _contrast_id(self, dataset_id: str, task_name: str, contrast_name: str) -> str:
        return ":".join(
            [
                "contrast",
                SOURCE_NAME,
                _slugify(dataset_id),
                _slugify(task_name),
                _slugify(contrast_name),
            ]
        )

    def _condition_id(
        self, dataset_id: str, task_name: str, condition_name: str
    ) -> str:
        return ":".join(
            [
                "condition",
                SOURCE_NAME,
                _slugify(dataset_id),
                _slugify(task_name),
                _slugify(condition_name),
            ]
        )

    def _subject_id(self, dataset_id: str, subject_code: str) -> str:
        return ":".join(
            [
                "subject",
                SOURCE_NAME,
                _slugify(dataset_id),
                _slugify(subject_code),
            ]
        )

    def _modelspec_id(self, dataset_id: str, task_name: str, spec_hash: str) -> str:
        return ":".join(
            [
                "modelspec",
                SOURCE_NAME,
                _slugify(dataset_id),
                _slugify(task_name),
                spec_hash,
            ]
        )

    def _taskspec_id(self, dataset_id: str, task_name: str) -> str:
        return f"{dataset_id}_task-{task_name}"

    def _node_exists(self, db, node_id: str) -> bool:
        graph = getattr(db, "graph", None)
        if graph is not None and hasattr(graph, "has_node"):
            if graph.has_node(node_id):
                return True
        try:
            existing = db.find_nodes(properties={"id": node_id})
        except Exception:  # pragma: no cover - defensive
            existing = []
        return bool(existing)

    def _relationship_exists(self, db, start: str, end: str, rel_type: str) -> bool:
        existing = db.find_relationships(
            start_node=start, end_node=end, rel_type=rel_type
        )
        return bool(existing)

    def _ensure_onvoc_linker(
        self,
        db,
    ) -> Optional[OpenNeuroOnvocLinkerProtocol]:
        if self._onvoc_linker is not None:
            return self._onvoc_linker
        if self._onvoc_linker_factory is None:
            return None
        try:
            linker = self._onvoc_linker_factory(db)
            if not getattr(linker, "available", False):
                self._onvoc_linker = None
            else:
                self._onvoc_linker = linker
        except Exception as exc:  # pragma: no cover - optional dependency
            logger.debug("ONVOC linker unavailable: %s", exc)
            self._onvoc_linker = None
        return self._onvoc_linker

    def _get_construct_manager(
        self,
        db,
    ) -> Optional[OpenNeuroConstructManagerProtocol]:
        if self._construct_manager is None:
            if self._construct_manager_factory is None:
                return None
            self._construct_manager = self._construct_manager_factory(db)
        return self._construct_manager

    def _task_concept_relationships(
        self,
        db,
        task_node_id: Optional[str],
    ) -> List[Dict[str, object]]:
        if not task_node_id:
            return []
        query = (
            "MATCH (t:Task {id:$id})-[r:MEASURES|SUGGESTS_MEASURES]->(c:Concept) "
            "RETURN c.id AS concept_id, type(r) AS rel_type, coalesce(r.confidence, 0.82) AS confidence"
        )
        try:
            result = db._run(query, {"id": task_node_id})
        except Exception:  # pragma: no cover - Neo4j access errors
            return []

        records: List[Dict[str, object]] = []
        try:
            for record in result:
                concept_id = record.get("concept_id")
                rel_type = record.get("rel_type")
                confidence = record.get("confidence")
                if concept_id and rel_type:
                    records.append(
                        {
                            "concept_id": concept_id,
                            "rel_type": rel_type,
                            "confidence": confidence,
                        }
                    )
        finally:
            try:
                result.close()
            except Exception:  # pragma: no cover
                pass
        return records

    def _build_task_analysis_properties(self, spec: TaskSpec) -> Dict[str, Any]:
        fitlins_params = spec.fitlins_params or {}
        model_options = fitlins_params.get("model_options")
        properties: Dict[str, Any] = {
            "id": self._task_analysis_id(spec.dataset_id, spec.task_name),
            "source": SOURCE_NAME,
            "dataset_id": spec.dataset_id,
            "task": spec.task_name,
            "model_name": spec.model_name,
            "bids_model_version": spec.bids_model_version,
            "group_by": spec.group_by,
            "subjects": spec.subjects,
            "n_subjects": len(spec.subjects) if spec.subjects else None,
            "task_metadata_json": (
                json.dumps(spec.task_metadata, sort_keys=True)
                if spec.task_metadata
                else None
            ),
            "extra_metadata_json": (
                json.dumps(spec.extra_metadata, sort_keys=True)
                if spec.extra_metadata
                else None
            ),
            "fitlins_params_json": (
                json.dumps(fitlins_params, sort_keys=True) if fitlins_params else None
            ),
            "model_options_json": (
                json.dumps(model_options, sort_keys=True)
                if isinstance(model_options, dict)
                else None
            ),
            "hrf_model": fitlins_params.get("hrf_model"),
            "hrf_derivative": fitlins_params.get("hrf_derivative"),
            "hrf_dispersion": fitlins_params.get("hrf_dispersion"),
            "convolve_input": fitlins_params.get("convolve_input"),
            "model_type": fitlins_params.get("model_type"),
            "high_pass": fitlins_params.get("high_pass"),
            "confounds_terms": fitlins_params.get("confounds_terms"),
            "ingested_at": datetime.utcnow().isoformat(),
        }

        return {
            key: value
            for key, value in properties.items()
            if value not in (None, "", [])
        }

    def _build_taskspec_properties(self, spec: TaskSpec) -> Dict[str, Any]:
        meta = spec.task_metadata or {}
        column_names = meta.get("column_names", [])
        # events_present: True when events column names were extracted from the
        # dataset (indicating *_events.tsv files existed at scan time).
        events_present: bool = bool(column_names)
        events_metadata_source = "column_names_proxy"
        properties: Dict[str, Any] = {
            "id": self._taskspec_id(spec.dataset_id, spec.task_name),
            "source": SOURCE_NAME,
            "dataset": spec.dataset_id,
            "name": spec.task_name,
            "bold_volumes": meta.get("bold_volumes"),
            "dummy_volumes": meta.get("dummy_volumes"),
            "cite_links": meta.get("cite_links", []),
            "column_names": column_names,
            "events_present": events_present,
            "events_metadata_source": events_metadata_source,
            "task_metadata_json": json.dumps(meta, sort_keys=True) if meta else None,
            "bids_model_version": spec.bids_model_version,
            "model_name": spec.model_name,
            "group_by": spec.group_by,
            "n_subjects": len(spec.subjects) if spec.subjects else None,
            "ingested_at": datetime.utcnow().isoformat(),
        }

        return {
            key: value
            for key, value in properties.items()
            if value not in (None, "", [])
        }

    def _build_model_spec_properties(
        self, spec: TaskSpec, spec_hash: str
    ) -> Dict[str, Any]:
        fitlins_params = spec.fitlins_params or {}
        model_options = fitlins_params.get("model_options")
        properties: Dict[str, Any] = {
            "id": self._modelspec_id(spec.dataset_id, spec.task_name, spec_hash),
            "source": SOURCE_NAME,
            "dataset_id": spec.dataset_id,
            "task": spec.task_name,
            "model_name": spec.model_name,
            "bids_model_version": spec.bids_model_version,
            "group_by": spec.group_by,
            "path": str(spec.spec_path),
            "hash": spec_hash,
            "fitlins_params_json": (
                json.dumps(fitlins_params, sort_keys=True) if fitlins_params else None
            ),
            "model_options_json": (
                json.dumps(model_options, sort_keys=True)
                if isinstance(model_options, dict)
                else None
            ),
            "hrf_model": fitlins_params.get("hrf_model"),
            "hrf_derivative": fitlins_params.get("hrf_derivative"),
            "hrf_dispersion": fitlins_params.get("hrf_dispersion"),
            "convolve_input": fitlins_params.get("convolve_input"),
            "model_type": fitlins_params.get("model_type"),
            "high_pass": fitlins_params.get("high_pass"),
            "confounds_terms": fitlins_params.get("confounds_terms"),
            "ingested_at": datetime.utcnow().isoformat(),
        }

        return {
            key: value
            for key, value in properties.items()
            if value not in (None, "", [])
        }

    def _build_contrast_properties(
        self,
        spec: TaskSpec,
        contrast: ContrastSpec,
        contrast_id: str,
    ) -> Dict[str, Any]:
        properties: Dict[str, Any] = {
            "id": contrast_id,
            "source": SOURCE_NAME,
            "dataset_id": spec.dataset_id,
            "task": spec.task_name,
            "name": contrast.name,
            "test": contrast.test,
            "condition_list": contrast.condition_list,
            "weights": contrast.weights,
            "metadata_json": (
                json.dumps(contrast.metadata, sort_keys=True)
                if contrast.metadata
                else None
            ),
            "ingested_at": datetime.utcnow().isoformat(),
        }

        return {
            key: value
            for key, value in properties.items()
            if value not in (None, "", [])
        }

    def _build_condition_properties(
        self,
        spec: TaskSpec,
        condition_name: str,
        order: int,
        condition_id: str,
    ) -> Dict[str, Any]:
        properties: Dict[str, Any] = {
            "id": condition_id,
            "source": SOURCE_NAME,
            "dataset_id": spec.dataset_id,
            "task": spec.task_name,
            "name": condition_name,
            "order_index": order,
            "ingested_at": datetime.utcnow().isoformat(),
        }

        return {
            key: value
            for key, value in properties.items()
            if value not in (None, "", [])
        }

    def _ensure_data_resource(
        self,
        db,
        path: Path,
        *,
        owner_id: str,
        base_path: Optional[Path] = None,
    ) -> bool:
        path = Path(path)
        if not path.exists():
            logger.debug("Resource missing on disk: %s", path)
            return False

        resource_id = self._data_resource_id(path)
        created = False
        if resource_id not in self._resource_cache:
            props = self._build_data_resource_properties(path, base_path=base_path)
            db.create_node(["DataResource"], props, node_id=resource_id)
            self._resource_cache.add(resource_id)
            created = True

        db.create_relationship(
            owner_id,
            resource_id,
            "HAS_RESOURCE",
            {"source": SOURCE_NAME},
        )

        return created

    def _data_resource_id(self, path: Path) -> str:
        digest = sha256(str(path).encode("utf-8")).hexdigest()[:16]
        return f"resource:{SOURCE_NAME}:{digest}"

    def _build_data_resource_properties(
        self,
        path: Path,
        *,
        base_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        try:
            file_size = path.stat().st_size
        except OSError:
            file_size = None

        suffix = "".join(path.suffixes)
        rel_path = None
        if base_path:
            try:
                rel_path = path.relative_to(base_path)
            except ValueError:
                rel_path = None

        properties: Dict[str, Any] = {
            "id": self._data_resource_id(path),
            "source": SOURCE_NAME,
            "path": str(path),
            "relative_path": str(rel_path) if rel_path is not None else None,
            "name": path.name,
            "format": suffix.lstrip(".") if suffix else path.suffix.lstrip("."),
            "file_size_bytes": file_size,
            "is_symlink": path.is_symlink(),
        }

        return {
            key: value
            for key, value in properties.items()
            if value not in (None, "", [])
        }

    def _link_task_analysis_to_tasks(
        self,
        db,
        task_id: str,
        task_name: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> LinkResult:
        matches = self._task_matcher.match_candidates(
            task_name,
            max_results=5,
            min_confidence=0.75,
            context=context,
        )

        result = LinkResult()
        seen_nodes: Set[str] = set()

        for candidate in matches:
            node_id = self._ensure_task_node(db, candidate)
            if not node_id or node_id in seen_nodes:
                continue

            properties = {
                "source": SOURCE_NAME,
                "method": candidate.method,
                "confidence": float(candidate.confidence),
            }
            if candidate.parameters:
                properties["parameters_json"] = json.dumps(
                    candidate.parameters, sort_keys=True
                )
            rel_created = db.create_relationship(
                task_id, node_id, "MAPS_TO", properties
            )
            if rel_created:
                result.created += 1
            seen_nodes.add(node_id)

            canonical_ids = self._collect_canonical_ids(candidate)
            canonical_ids.append(node_id)
            canonical_ids = _dedupe_preserve_order(canonical_ids)
            concept_ids = self._collect_concept_ids(candidate)
            if self._onvoc_linker and self._onvoc_linker.available:
                onvoc_ids = self._fetch_onvoc_ids(db, node_id)
            else:
                onvoc_ids = []
            result.matches.append(
                LinkMatch(
                    label=candidate.label,
                    confidence=float(candidate.confidence),
                    method=candidate.method,
                    node_id=node_id,
                    canonical_ids=canonical_ids,
                    concept_ids=concept_ids,
                    onvoc_ids=onvoc_ids,
                )
            )

        if result.matches:
            return result

        return self._legacy_task_lookup(db, task_id, task_name)

    def _link_manual_concepts(
        self,
        db,
        contrast_id: str,
        concept_ids: Sequence[str],
        *,
        confidence: float,
    ) -> tuple[LinkResult, Set[str]]:
        link_result = LinkResult()
        linked_nodes: Set[str] = set()

        for concept_id in concept_ids:
            if not concept_id:
                continue
            try:
                nodes = db.find_nodes("Concept", {"id": concept_id})
            except Exception:
                nodes = []
            if not nodes:
                continue

            node_id, props = nodes[0]
            node_id = str(node_id)
            label = (props or {}).get("name") or concept_id

            rel_props = {
                "source": f"{SOURCE_NAME}_manual",
                "method": "manual_mapping",
                "confidence": float(confidence),
            }
            try:
                created = db.create_relationship(
                    contrast_id,
                    node_id,
                    "CONTRAST_OF",
                    rel_props,
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug(
                    "Manual contrast mapping failed for %s -> %s: %s",
                    contrast_id,
                    concept_id,
                    exc,
                )
                created = False

            if created:
                link_result.created += 1

            onvoc_ids = self._fetch_onvoc_ids(db, node_id)
            link_result.matches.append(
                LinkMatch(
                    label=label,
                    confidence=float(confidence),
                    method="manual_mapping",
                    node_id=node_id,
                    canonical_ids=_dedupe_preserve_order([concept_id]),
                    concept_ids=_dedupe_preserve_order([concept_id]),
                    onvoc_ids=onvoc_ids,
                )
            )
            linked_nodes.add(node_id)

        return link_result, linked_nodes

    def _link_contrast_to_concepts(
        self,
        db,
        contrast_id: str,
        contrast_name: str,
    ) -> LinkResult:
        matches = self._concept_matcher.match_candidates(
            contrast_name,
            max_results=5,
            min_confidence=0.7,
        )

        result = LinkResult()
        seen_nodes: Set[str] = set()

        slug = _slugify(contrast_name)
        manual_entry = MANUAL_CONTRAST_CONCEPTS.get(slug)
        if manual_entry:
            concept_ids = manual_entry.get("concept_ids") or []
            base_confidence = float(manual_entry.get("confidence", 0.9))
            manual_result, manual_nodes = self._link_manual_concepts(
                db,
                contrast_id,
                concept_ids,
                confidence=base_confidence,
            )
            if manual_result.matches:
                result.extend(manual_result)
                seen_nodes.update(manual_nodes)

        for candidate in matches:
            node_id = self._ensure_concept_node(db, candidate)
            if not node_id or node_id in seen_nodes:
                continue

            properties = {
                "source": SOURCE_NAME,
                "method": candidate.method,
                "confidence": float(candidate.confidence),
            }
            rel_created = db.create_relationship(
                contrast_id, node_id, "CONTRAST_OF", properties
            )
            if rel_created:
                result.created += 1
            seen_nodes.add(node_id)

            canonical_ids = self._collect_canonical_ids(candidate)
            canonical_ids.append(node_id)
            canonical_ids = _dedupe_preserve_order(canonical_ids)
            concept_ids = self._collect_concept_ids(candidate)
            if node_id not in concept_ids:
                concept_ids.append(node_id)
            concept_ids = _dedupe_preserve_order(concept_ids)
            if self._onvoc_linker and self._onvoc_linker.available:
                onvoc_ids = self._fetch_onvoc_ids(db, node_id)
            else:
                onvoc_ids = []
            result.matches.append(
                LinkMatch(
                    label=candidate.label,
                    confidence=float(candidate.confidence),
                    method=candidate.method,
                    node_id=node_id,
                    canonical_ids=canonical_ids,
                    concept_ids=concept_ids,
                    onvoc_ids=onvoc_ids,
                )
            )

        if result.matches:
            return result

        return self._legacy_concept_lookup(db, contrast_id, contrast_name)

    def _ensure_task_node(self, db, candidate: MatchCandidate) -> Optional[str]:
        entity = candidate.entity or {}
        canonical_id = candidate.canonical_id
        label = candidate.label

        candidate_ids: List[str] = []
        if canonical_id:
            candidate_ids.append(canonical_id)

        links = entity.get("links") or {}
        for scheme, value in links.items():
            if not value:
                continue
            scheme_norm = scheme.lower()
            if scheme_norm in {"cogat", "trm"}:
                candidate_ids.append(f"cogat:{value}")
                candidate_ids.append(value)
            elif scheme_norm == "neurostore":
                candidate_ids.append(f"neurostore:{value}")

        for candidate_id in candidate_ids:
            nodes = db.find_nodes("Task", {"id": candidate_id})
            if nodes:
                return nodes[0][0]

        # Fallback by label
        nodes = db.find_nodes("Task", {"name": label})
        if nodes:
            return nodes[0][0]

        node_id = canonical_id or label.replace(" ", "_")
        properties = {
            "id": canonical_id or node_id,
            "name": label,
            "source": f"{SOURCE_NAME}_taxonomy",
        }
        if links:
            properties["links_json"] = json.dumps(links, sort_keys=True)
        return db.create_node("Task", properties, node_id=node_id)

    def _ensure_concept_node(self, db, candidate: MatchCandidate) -> Optional[str]:
        entity = candidate.entity or {}
        canonical_id = candidate.canonical_id
        label = candidate.label

        candidate_ids: List[str] = []
        if canonical_id:
            candidate_ids.append(canonical_id)

        links = entity.get("links") or {}
        for scheme, value in links.items():
            if not value:
                continue
            scheme_norm = scheme.lower()
            if scheme_norm in {"cao", "cogat", "trm"}:
                candidate_ids.append(f"{scheme_norm}:{value}")
                candidate_ids.append(value)

        for candidate_id in candidate_ids:
            nodes = db.find_nodes("Concept", {"id": candidate_id})
            if nodes:
                return nodes[0][0]

        nodes = db.find_nodes("Concept", {"name": label})
        if nodes:
            return nodes[0][0]

        return None

    def _collect_canonical_ids(self, candidate: MatchCandidate) -> List[str]:
        entity = candidate.entity or {}
        ids: List[str] = []
        if candidate.canonical_id:
            ids.append(str(candidate.canonical_id))
        links = entity.get("links") or {}
        for scheme, value in links.items():
            if not value:
                continue
            scheme_norm = str(scheme).lower()
            ids.append(f"{scheme_norm}:{value}")
            ids.append(str(value))
        return _dedupe_preserve_order(ids)

    def _collect_concept_ids(self, candidate: MatchCandidate) -> List[str]:
        entity = candidate.entity or {}
        concept_ids: List[str] = []
        for key in ("measures", "concepts", "domains"):
            values = entity.get(key) or []
            if isinstance(values, dict):
                values = values.values()
            for value in values:
                if value is None:
                    continue
                concept_ids.append(str(value))
        return _dedupe_preserve_order(concept_ids)

    def _legacy_task_lookup(
        self,
        db,
        task_id: str,
        task_name: str,
    ) -> LinkResult:
        exact = task_name.lower()
        slug = _slugify(task_name)
        slug_us = slug.replace("-", "_")
        slug_compact = slug.replace("-", "")
        query = (
            "MATCH (t:Task) "
            "WHERE toLower(t.name) = $exact "
            "   OR replace(toLower(t.name),' ','-') = $slug "
            "   OR replace(toLower(t.name),' ','_') = $slug_us "
            "   OR replace(toLower(t.name),' ','') = $compact "
            "   OR toLower(coalesce(t.slug,'')) IN [$slug, $slug_us] "
            "   OR toLower(coalesce(t.id,'')) IN [$slug, $slug_us] "
            "RETURN t.id AS id, t.name AS name"
        )
        params = {
            "exact": exact,
            "slug": slug,
            "slug_us": slug_us,
            "compact": slug_compact,
        }
        link_result = LinkResult()
        try:
            result = db._run(query, params)
        except Exception as exc:
            logger.debug("Legacy task lookup failed for %s: %s", task_name, exc)
            return link_result
        try:
            for record in result:
                target_id = record.get("id")
                if not target_id:
                    continue
                name = (record.get("name") or "").lower()
                confidence = 1.0 if name == exact else 0.88
                rel_created = db.create_relationship(
                    task_id,
                    target_id,
                    "MAPS_TO",
                    {
                        "source": SOURCE_NAME,
                        "method": "name_lookup",
                        "confidence": confidence,
                    },
                )
                if rel_created:
                    link_result.created += 1
                label = record.get("name") or target_id
                onvoc_ids = self._fetch_onvoc_ids(db, target_id)
                link_result.matches.append(
                    LinkMatch(
                        label=label,
                        confidence=confidence,
                        method="name_lookup",
                        node_id=target_id,
                        canonical_ids=_dedupe_preserve_order([target_id]),
                        concept_ids=[],
                        onvoc_ids=onvoc_ids,
                    )
                )
        finally:
            try:
                result.close()
            except Exception:
                pass
        return link_result

    def _legacy_concept_lookup(
        self,
        db,
        contrast_id: str,
        contrast_name: str,
    ) -> LinkResult:
        exact = contrast_name.lower()
        slug = _slugify(contrast_name)
        slug_us = slug.replace("-", "_")
        query = (
            "MATCH (c:Concept) "
            "WHERE toLower(c.name) = $exact "
            "   OR replace(toLower(c.name),' ','-') = $slug "
            "   OR replace(toLower(c.name),' ','_') = $slug_us "
            "   OR toLower(coalesce(c.id,'')) IN [$slug, $slug_us] "
            "RETURN c.id AS id, c.name AS name"
        )
        params = {"exact": exact, "slug": slug, "slug_us": slug_us}
        link_result = LinkResult()
        try:
            result = db._run(query, params)
        except Exception as exc:
            logger.debug("Legacy concept lookup failed for %s: %s", contrast_name, exc)
            return link_result
        try:
            for record in result:
                concept_id = record.get("id")
                if not concept_id:
                    continue
                name = (record.get("name") or "").lower()
                confidence = 1.0 if name == exact else 0.88
                rel_created = db.create_relationship(
                    contrast_id,
                    concept_id,
                    "CONTRAST_OF",
                    {
                        "source": SOURCE_NAME,
                        "method": "name_lookup",
                        "confidence": confidence,
                    },
                )
                if rel_created:
                    link_result.created += 1
                label = record.get("name") or concept_id
                onvoc_ids = self._fetch_onvoc_ids(db, concept_id)
                link_result.matches.append(
                    LinkMatch(
                        label=label,
                        confidence=confidence,
                        method="name_lookup",
                        node_id=concept_id,
                        canonical_ids=_dedupe_preserve_order([concept_id]),
                        concept_ids=_dedupe_preserve_order([concept_id]),
                        onvoc_ids=onvoc_ids,
                    )
                )
        finally:
            try:
                result.close()
            except Exception:
                pass
        return link_result

    def _fetch_onvoc_ids(self, db, node_id: Optional[str]) -> List[str]:
        if self._onvoc_linker is None or not getattr(
            self._onvoc_linker, "available", False
        ):
            return []

        if not node_id:
            return []
        try:
            result = db._run(
                "MATCH (n {id:$id})-[:IN_ONVOC]->(o:OnvocClass) RETURN o.id AS id",
                {"id": node_id},
            )
        except Exception:
            return []
        ids = [record.get("id") for record in result if record.get("id")]
        try:
            result.close()
        except Exception:
            pass
        return ids

    def _prepare_model_spec(
        self,
        row: StatsMapManifestRow,
        statsmodel_root: Optional[Path],
    ) -> Optional[Dict[str, Any]]:
        if statsmodel_root is None:
            return None

        spec_path = self._locate_model_spec(statsmodel_root, row)
        if spec_path is None:
            return None

        spec_hash = self._hash_file_cached(spec_path)
        cached_spec = self._spec_lookup.get(spec_path)
        if cached_spec:
            spec_id = self._modelspec_id(
                cached_spec.dataset_id, cached_spec.task_name, spec_hash
            )
            spec_props = self._build_model_spec_properties(cached_spec, spec_hash)
            spec_props["id"] = spec_id
            return spec_props

        spec_id = self._modelspec_id(row.dataset_id, row.task, spec_hash)

        return {
            "id": spec_id,
            "dataset_id": row.dataset_id,
            "task": row.task,
            "path": str(spec_path),
            "hash": spec_hash,
            "source": SOURCE_NAME,
        }

    def _locate_model_spec(
        self, statsmodel_root: Path, row: StatsMapManifestRow
    ) -> Optional[Path]:
        dataset_dir = statsmodel_root / row.dataset_id
        if not dataset_dir.exists():
            return None

        task_slug = _slugify(row.task.replace("task-", ""))

        candidates = sorted(dataset_dir.glob(f"*{task_slug}*specs.json"))
        if candidates:
            return candidates[0]

        # Fallback: look for generic specs within dataset directory
        generic = sorted(dataset_dir.glob("*specs.json"))
        return generic[0] if generic else None

    def _hash_file_cached(self, path: Path) -> str:
        cached = self._modelspec_hash_cache.get(path)
        if cached:
            return cached
        digest = self._hash_file(path)
        self._modelspec_hash_cache[path] = digest
        return digest

    @staticmethod
    def _hash_file(path: Path) -> str:
        h = sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
