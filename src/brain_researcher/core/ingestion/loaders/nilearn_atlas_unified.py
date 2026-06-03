"""Unified loader for common Nilearn parcellation atlases."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from brain_researcher.config.paths import (
    get_default_atlas_output_root as default_atlas_output_root,
)

logger = logging.getLogger(__name__)

BACKGROUND_LABELS = {"", "background", "???", "background label", "none"}


def _slugify(text: str) -> str:
    """Create a filesystem/database friendly slug from free text."""
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "atlas"


def _normalize_label(label: Any) -> str:
    """Convert raw label to normalized text."""
    if label is None:
        return ""
    text = str(label).strip()
    return text


@dataclass
class AtlasSpec:
    """Configuration for a single Nilearn atlas fetcher."""

    name: str
    fetcher: str
    slug: str | None = None
    variant: str | None = None
    parser: str = "generic"
    params: dict[str, Any] = field(default_factory=dict)
    space: str = "MNI152"
    space_variant: str | None = None
    space_resolution_mm: float | None = None
    scale: str | int | None = None
    modality: str | None = None

    def resolved_slug(self) -> str:
        return self.slug or _slugify(f"{self.fetcher}-{self.variant or self.name}")


class NilearnAtlasUnifiedLoader:
    """Loader that fetches common atlases via Nilearn and prepares BrainRegion nodes."""

    DEFAULT_ATLASES: list[AtlasSpec] = [
        AtlasSpec(
            name="Automated Anatomical Labeling (AAL)",
            fetcher="fetch_atlas_aal",
            slug="aal",
            space="MNI152",
            space_variant="SPM12",
            space_resolution_mm=2.0,
            scale=116,
            modality="volume",
        ),
        AtlasSpec(
            name="Destrieux 2009",
            fetcher="fetch_atlas_destrieux_2009",
            slug="destrieux_2009",
            parser="destrieux",
            space="fsaverage",
            space_variant="surface",
            modality="surface",
        ),
        AtlasSpec(
            name="Harvard-Oxford Cortical (25% threshold)",
            fetcher="fetch_atlas_harvard_oxford",
            slug="harvard_oxford_cort25",
            variant="cort-maxprob-thr25-2mm",
            params={"atlas_name": "cort-maxprob-thr25-2mm"},
            space="MNI152",
            space_variant="cortical",
            space_resolution_mm=2.0,
            modality="volume",
        ),
        AtlasSpec(
            name="Harvard-Oxford Subcortical (25% threshold)",
            fetcher="fetch_atlas_harvard_oxford",
            slug="harvard_oxford_sub25",
            variant="sub-maxprob-thr25-2mm",
            params={"atlas_name": "sub-maxprob-thr25-2mm"},
            space="MNI152",
            space_variant="subcortical",
            space_resolution_mm=2.0,
            modality="volume",
        ),
        AtlasSpec(
            name="Schaefer 2018 (100 parcels, 7 networks, 2mm)",
            fetcher="fetch_atlas_schaefer_2018",
            slug="schaefer2018_100_7n_2mm",
            parser="schaefer",
            params={"n_rois": 100, "yeo_networks": 7, "resolution_mm": 2},
            space="MNI152",
            space_resolution_mm=2.0,
            scale=100,
            modality="volume",
        ),
        AtlasSpec(
            name="Schaefer 2018 (200 parcels, 17 networks, 2mm)",
            fetcher="fetch_atlas_schaefer_2018",
            slug="schaefer2018_200_17n_2mm",
            parser="schaefer",
            params={"n_rois": 200, "yeo_networks": 17, "resolution_mm": 2},
            space="MNI152",
            space_resolution_mm=2.0,
            scale=200,
            modality="volume",
        ),
        AtlasSpec(
            name="BASC Multiscale 2015 (122 regions)",
            fetcher="fetch_atlas_basc_multiscale_2015",
            slug="basc_multiscale_2015_scale122",
            variant="scale122",
            params={"version": "sym", "resolution": 122},
            space="MNI152",
            space_variant="sym",
            scale=122,
            modality="volume",
        ),
        AtlasSpec(
            name="MSDL Dictionary Learning Atlas",
            fetcher="fetch_atlas_msdl",
            slug="msdl",
            space="MNI152",
            space_resolution_mm=2.0,
            modality="volume",
        ),
    ]

    def __init__(
        self,
        atlas_specs: Iterable[AtlasSpec] | None = None,
        data_dir: str | Path = default_atlas_output_root() / "nilearn",
    ) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)

        if atlas_specs is None:
            self.atlas_specs = list(self.DEFAULT_ATLASES)
        else:
            self.atlas_specs = [
                spec if isinstance(spec, AtlasSpec) else AtlasSpec(**spec)
                for spec in atlas_specs
            ]

        self.region_nodes: list[dict[str, Any]] = []
        self.parcellation_payloads: list[
            tuple[AtlasSpec, list[dict[str, Any]], list[str]]
        ] = []
        self.failed_atlases: list[dict[str, Any]] = []
        self.atlas_stats: dict[str, dict[str, Any]] = {}

    def _parse_generic_label(
        self,
        label: str,
        index: int,
        spec: AtlasSpec,
    ) -> dict[str, Any]:
        name = label
        hemisphere = None

        # Attempt to infer hemisphere from suffix/prefix tokens
        if name.endswith("_L") or name.endswith("_Left"):
            hemisphere = "left"
            name = name.rstrip("_L").rstrip("_Left")
        elif name.endswith("_R") or name.endswith("_Right"):
            hemisphere = "right"
            name = name.rstrip("_R").rstrip("_Right")
        elif name.lower().startswith("ctx-lh-"):
            hemisphere = "left"
            name = name[len("ctx-lh-") :]
        elif name.lower().startswith("ctx-rh-"):
            hemisphere = "right"
            name = name[len("ctx-rh-") :]

        clean_name = name.replace("_", " ").strip()

        node = {
            "id": f"atlas:{spec.resolved_slug()}:{index}",
            "region_id": f"{spec.resolved_slug()}:{index}",
            "name": clean_name,
            "atlas": spec.name,
            "atlas_slug": spec.resolved_slug(),
            "atlas_variant": spec.variant,
            "label_original": label,
            "index": index,
            "hemisphere": hemisphere,
            "source": "nilearn",
        }
        return node

    def _parse_schaefer_label(
        self,
        label: str,
        index: int,
        spec: AtlasSpec,
    ) -> dict[str, Any]:
        parts = label.split("_")
        hemisphere = None
        network = None
        network_set = None
        roi_number = None

        if len(parts) >= 4:
            network_set = parts[0]  # e.g., 7Networks
            hemisphere_code = parts[1]
            hemisphere = (
                "left"
                if hemisphere_code.upper() == "LH"
                else "right" if hemisphere_code.upper() == "RH" else None
            )
            network = parts[2]
            try:
                roi_number = int(parts[3])
            except ValueError:
                roi_number = None

        clean_name = label.replace("_", " ")

        node = self._parse_generic_label(label, index, spec)
        node.update(
            {
                "name": clean_name,
                "network": network,
                "yeo_network_set": network_set,
                "roi_number": roi_number,
                "yeo_networks": spec.params.get("yeo_networks"),
                "n_rois": spec.params.get("n_rois"),
                "resolution_mm": spec.params.get("resolution_mm"),
                "hemisphere": hemisphere or node.get("hemisphere"),
            }
        )
        return node

    def _parse_basc_label(
        self,
        label: str,
        index: int,
        spec: AtlasSpec,
    ) -> dict[str, Any]:
        node = self._parse_generic_label(label, index, spec)
        # BASC labels typically formatted as e.g. "ROI_1"
        try:
            if "_" in label:
                node["roi_number"] = int(label.split("_")[-1])
        except ValueError:
            pass
        node["resolution"] = spec.params.get("resolution")
        node["version"] = spec.params.get("version")
        return node

    def _parse_label(
        self,
        label: str,
        index: int,
        spec: AtlasSpec,
    ) -> dict[str, Any]:
        parsers = {
            "generic": self._parse_generic_label,
            "schaefer": self._parse_schaefer_label,
            "destrieux": self._parse_generic_label,
            "basc": self._parse_basc_label,
        }
        parser = parsers.get(spec.parser, self._parse_generic_label)
        return parser(label, index, spec)

    def _extract_regions_from_labels(
        self,
        labels: Iterable[Any],
        spec: AtlasSpec,
    ) -> list[dict[str, Any]]:
        regions: list[dict[str, Any]] = []

        pandas_series = None
        pandas_dataframe = None
        pd = None
        try:  # pragma: no cover - pandas optional
            import pandas as _pd  # type: ignore

            pd = _pd
        except ImportError:  # pragma: no cover - pandas might not be available
            pd = None

        if pd is not None and isinstance(labels, pd.Series):
            pandas_series = labels
        if pd is not None and isinstance(labels, pd.DataFrame):
            pandas_dataframe = labels

        if pandas_dataframe is not None:
            if "name" in pandas_dataframe.columns:
                iterator = enumerate(pandas_dataframe["name"].tolist())
            else:
                iterator = enumerate(pandas_dataframe.iloc[:, 0].tolist())
        elif pandas_series is not None:
            iterator = enumerate(pandas_series.tolist())
        else:
            try:
                iterator = enumerate(list(labels))
            except TypeError:
                iterator = enumerate([labels])

        for index, raw_label in iterator:
            label = _normalize_label(raw_label)
            if not label or label.lower() in BACKGROUND_LABELS:
                continue
            node = self._parse_label(label, index, spec)
            regions.append(node)
        return regions

    def _ensure_nilearn(self):
        try:
            from nilearn import datasets  # noqa: F401
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "Nilearn is required to fetch parcellation atlases. "
                "Install it with `pip install nilearn`."
            ) from exc

    def load_regions(self) -> list[dict[str, Any]]:
        """Fetch configured atlases and convert them to BrainRegion metadata."""
        if self.region_nodes:
            return self.region_nodes

        self._ensure_nilearn()
        from nilearn import datasets

        all_regions: list[dict[str, Any]] = []
        self.atlas_stats = {}
        self.failed_atlases = []

        for spec in self.atlas_specs:
            slug = spec.resolved_slug()
            try:
                fetcher = getattr(datasets, spec.fetcher)
            except AttributeError:
                logger.error("Nilearn datasets has no fetcher named %s", spec.fetcher)
                self.failed_atlases.append({"slug": slug, "reason": "missing_fetcher"})
                continue

            try:
                bunch = fetcher(data_dir=str(self.data_dir), verbose=1, **spec.params)
            except Exception as exc:  # pragma: no cover - network/download errors
                logger.warning("Failed to fetch atlas %s: %s", slug, exc)
                self.failed_atlases.append({"slug": slug, "reason": str(exc)})
                continue

            labels = getattr(bunch, "labels", None)
            if labels is None:
                logger.warning(
                    "Atlas %s does not provide label metadata, skipping", slug
                )
                self.failed_atlases.append({"slug": slug, "reason": "no_labels"})
                continue

            regions = self._extract_regions_from_labels(labels, spec)
            if not regions:
                logger.warning("Atlas %s did not yield any valid regions", slug)
                self.failed_atlases.append({"slug": slug, "reason": "empty_regions"})
                continue

            map_path = getattr(bunch, "maps", None)
            map_locations: list[str] = []
            if map_path is not None:
                if isinstance(map_path, str | Path):
                    map_locations.append(str(Path(map_path).resolve()))
                elif isinstance(map_path, list | tuple):
                    for item in map_path:
                        if isinstance(item, str | Path):
                            map_locations.append(str(Path(item).resolve()))
                else:  # nibabel objects or arrays are skipped
                    pass

            if map_locations:
                primary_map = map_locations[0]
                for node in regions:
                    node["map_file"] = primary_map

            for node in regions:
                node["parcellation_id"] = self._parcellation_id(spec)
                node["parcellation_slug"] = spec.resolved_slug()
                node["space"] = spec.space
                node["space_variant"] = spec.space_variant
                node["space_resolution_mm"] = spec.space_resolution_mm
                node["scale"] = spec.scale
                if spec.modality:
                    node["modality"] = spec.modality

            self.atlas_stats[slug] = {
                "atlas": spec.name,
                "slug": slug,
                "variant": spec.variant,
                "region_count": len(regions),
            }
            self.parcellation_payloads.append((spec, regions, map_locations))
            all_regions.extend(regions)
            logger.info("Loaded %d regions from atlas %s", len(regions), spec.name)

        self.region_nodes = all_regions
        return all_regions

    def _parcellation_id(self, spec: AtlasSpec) -> str:
        return f"parcellation:nilearn:{spec.resolved_slug()}"

    def _template_space_id(self, spec: AtlasSpec) -> str:
        components = [spec.space.lower()]
        if spec.space_variant:
            components.append(spec.space_variant.lower())
        if spec.space_resolution_mm:
            components.append(f"{int(spec.space_resolution_mm)}mm")
        return "space:" + ":".join(components)

    def _template_space_properties(self, spec: AtlasSpec) -> dict[str, Any]:
        props: dict[str, Any] = {
            "id": self._template_space_id(spec),
            "name": spec.space,
            "source": "nilearn",
        }
        if spec.space_variant:
            props["variant"] = spec.space_variant
        if spec.space_resolution_mm:
            props["resolution_mm"] = spec.space_resolution_mm
        if spec.modality:
            props["modality"] = spec.modality
        return props

    @staticmethod
    def _data_resource_id(spec: AtlasSpec, file_path: str) -> str:
        name = Path(file_path).name
        return f"resource:nilearn:{spec.resolved_slug()}:{name}"

    @staticmethod
    def _data_resource_properties(spec: AtlasSpec, file_path: str) -> dict[str, Any]:
        path = Path(file_path).resolve()
        suffixes = path.suffixes
        if (
            len(suffixes) >= 2
            and suffixes[-2].lower() == ".nii"
            and suffixes[-1].lower() == ".gz"
        ):
            file_format = "nii.gz"
        else:
            file_format = suffixes[-1].lstrip(".").lower() if suffixes else ""
        return {
            "id": NilearnAtlasUnifiedLoader._data_resource_id(spec, str(path)),
            "path": str(path),
            "format": file_format,
            "source": "nilearn",
            "atlas_slug": spec.resolved_slug(),
        }

    def ingest(self, db) -> dict[str, Any]:
        """Insert fetched regions into BR-KG."""
        if not self.region_nodes:
            self.load_regions()

        parcellations_created = 0
        parcellations_skipped = 0
        template_spaces_created = 0
        template_spaces_skipped = 0
        regions_created = 0
        regions_skipped = 0
        resources_created = 0
        resources_skipped = 0

        for spec, regions, map_locations in self.parcellation_payloads:
            parcellation_id = self._parcellation_id(spec)
            parcellation_props: dict[str, Any] = {
                "id": parcellation_id,
                "name": spec.name,
                "slug": spec.resolved_slug(),
                "variant": spec.variant,
                "source": "nilearn",
                "space": spec.space,
                "space_variant": spec.space_variant,
                "space_resolution_mm": spec.space_resolution_mm,
                "scale": spec.scale,
            }
            if spec.modality:
                parcellation_props["modality"] = spec.modality
            if map_locations:
                parcellation_props["map_files"] = map_locations

            existing_parcellation = db.find_nodes(
                "Parcellation", {"id": parcellation_id}
            )
            if existing_parcellation:
                parcellations_skipped += 1
            else:
                parcellations_created += 1
            try:
                db.create_node("Parcellation", parcellation_props)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Failed to insert Parcellation %s: %s", parcellation_id, exc
                )

            template_id = self._template_space_id(spec)
            template_props = self._template_space_properties(spec)
            existing_template = db.find_nodes("TemplateSpace", {"id": template_id})
            if existing_template:
                template_spaces_skipped += 1
            else:
                template_spaces_created += 1
            try:
                db.create_node("TemplateSpace", template_props)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Failed to insert TemplateSpace %s: %s", template_id, exc
                )

            try:
                db.create_relationship(
                    parcellation_id, template_id, "IN_SPACE", {"source": "nilearn"}
                )
            except Exception:
                pass

            for node in regions:
                node_id = node.get("id")
                if not node_id:
                    continue
                existing_region = db.find_nodes("BrainRegion", {"id": node_id})
                if existing_region:
                    regions_skipped += 1
                else:
                    regions_created += 1
                try:
                    db.create_node("BrainRegion", node)
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("Failed to insert BrainRegion %s: %s", node_id, exc)
                    continue

                try:
                    db.create_relationship(
                        parcellation_id, node_id, "HAS_REGION", {"source": "nilearn"}
                    )
                except Exception:
                    pass

            for file_path in map_locations:
                resource_props = self._data_resource_properties(spec, file_path)
                resource_id = resource_props["id"]
                existing_resource = db.find_nodes("DataResource", {"id": resource_id})
                if existing_resource:
                    resources_skipped += 1
                else:
                    resources_created += 1
                try:
                    db.create_node("DataResource", resource_props)
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning(
                        "Failed to insert DataResource %s: %s", resource_id, exc
                    )
                try:
                    db.create_relationship(
                        parcellation_id,
                        resource_id,
                        "HAS_RESOURCE",
                        {"source": "nilearn"},
                    )
                except Exception:
                    pass

        stats = {
            "regions_created": regions_created,
            "regions_skipped": regions_skipped,
            "parcellations_created": parcellations_created,
            "parcellations_skipped": parcellations_skipped,
            "template_spaces_created": template_spaces_created,
            "template_spaces_skipped": template_spaces_skipped,
            "resources_created": resources_created,
            "resources_skipped": resources_skipped,
            "atlases": self.atlas_stats,
            "failures": self.failed_atlases,
        }

        return stats
