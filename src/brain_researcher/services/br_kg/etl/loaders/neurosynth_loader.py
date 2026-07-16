"""
Neurosynth Data Loader

Loads Neurosynth data using NiMARE Dataset for robust and standardized access.
Consumes only a local dataset associated with the verified pinned source bundle.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nimare.dataset import Dataset

from brain_researcher.core.datasets.neurosynth_source import (
    DEFAULT_DATASET_PICKLE,
    DEFAULT_SOURCE_DIR,
    verify_converted_dataset,
)

logger = logging.getLogger(__name__)

NEUROSYNTH_PATH = DEFAULT_DATASET_PICKLE
NEUROSYNTH_DATA_DIR = DEFAULT_SOURCE_DIR


class NeurosynthDataError(Exception):
    """Custom exception for Neurosynth data processing errors."""

    pass


def load_neurosynth_data(
    output_dir: str,
    sample_size: int = 10000,
    use_local: bool = True,
    *,
    dataset_path: str | Path | None = None,
    source_dir: str | Path | None = None,
) -> dict[str, str]:
    """
    Load Neurosynth data using NiMARE Dataset.

    Args:
        output_dir: Directory to save processed files
        sample_size: Maximum number of studies to process (for MVP)
        use_local: Legacy switch. ``False`` now fails because network fetches are
            not an authoritative source path.
        dataset_path: Explicit NiMARE pickle derived from the verified bundle.
        source_dir: Directory containing the pinned raw bundle and manifest.

    Returns:
        Dictionary mapping data type to output file path
    """
    logger.info(
        f"📥 Loading Neurosynth data (sample_size={sample_size}, use_local={use_local})"
    )

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    coordinates_output = output_path / "neurosynth_coordinates.json"
    features_output = output_path / "neurosynth_features.json"
    metadata_output = output_path / "neurosynth_metadata.json"
    published_outputs = (coordinates_output, features_output, metadata_output)
    for path in published_outputs:
        path.unlink(missing_ok=True)

    if not use_local:
        raise NeurosynthDataError(
            "automatic Neurosynth fetching is disabled; run "
            "python scripts/data/download_neurosynth_data.py and "
            "python scripts/data/convert_neurosynth.py"
        )

    verified_dir = Path(source_dir or NEUROSYNTH_DATA_DIR).expanduser().resolve()
    pickle_path = Path(dataset_path or NEUROSYNTH_PATH).expanduser().resolve()
    verify_converted_dataset(pickle_path, verified_dir)
    from nimare.dataset import Dataset

    try:
        dataset = Dataset.load(str(pickle_path))
    except Exception as exc:
        raise NeurosynthDataError(
            f"failed to load Neurosynth dataset pickle {pickle_path}: {exc}"
        ) from exc

    output_files = {}
    try:
        studies_processed = _extract_coordinates_from_dataset(
            dataset, coordinates_output, sample_size
        )
        if not studies_processed:
            raise NeurosynthDataError(
                "verified Neurosynth dataset yielded zero studies"
            )
        output_files["coordinates"] = str(coordinates_output)

        features_processed = _extract_features_from_dataset(
            dataset, features_output, studies_processed
        )
        if features_processed <= 0:
            raise NeurosynthDataError(
                "verified Neurosynth dataset yielded zero features"
            )
        output_files["features"] = str(features_output)

        metadata_processed = _extract_metadata_from_dataset(
            dataset, metadata_output, studies_processed
        )
        if metadata_processed <= 0:
            raise NeurosynthDataError(
                "verified Neurosynth dataset yielded zero metadata rows"
            )
        output_files["metadata"] = str(metadata_output)
    except Exception:
        for path in published_outputs:
            path.unlink(missing_ok=True)
        raise

    logger.info(
        "Processed %d verified Neurosynth studies with %d features",
        len(studies_processed),
        features_processed,
    )
    return output_files


def _extract_coordinates_from_dataset(
    dataset: Dataset, output_file: Path, sample_size: int
) -> set:
    """Extract coordinates from NiMARE dataset."""
    logger.info("🔄 Extracting coordinates from dataset")

    coordinates = []
    studies_processed = set()

    try:
        # Get coordinates DataFrame
        coords_df = dataset.coordinates

        logger.info(f"📊 Found {len(coords_df)} coordinates in dataset")

        # Sample if needed
        if len(coords_df) > sample_size:
            coords_df = coords_df.sample(n=sample_size, random_state=42)
            logger.info(f"📊 Sampled {sample_size} coordinates")

        # Process coordinates
        for idx, (_, row) in enumerate(coords_df.iterrows()):
            try:
                coordinate = {
                    "id": f"coord_{idx:06d}",
                    "study_id": str(row["id"]),
                    "x": float(row["x"]),
                    "y": float(row["y"]),
                    "z": float(row["z"]),
                    "space": str(row.get("space", "MNI")),
                    "source": "neurosynth",
                }

                coordinates.append(coordinate)
                studies_processed.add(coordinate["study_id"])

            except (ValueError, TypeError) as e:
                logger.warning(f"⚠️ Invalid coordinate data: {e}")
                continue

        # Save coordinates
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(coordinates, f, indent=2, ensure_ascii=False)

        logger.info(
            f"✅ Extracted {len(coordinates)} coordinates from {len(studies_processed)} studies"
        )

    except Exception as e:
        logger.error(f"❌ Error extracting coordinates: {e}")
        raise NeurosynthDataError(f"Coordinate extraction failed: {e}") from e

    return studies_processed


def _extract_features_from_dataset(
    dataset: Dataset, output_file: Path, studies_processed: set
) -> int:
    """Extract features/annotations from NiMARE dataset."""
    logger.info("🔄 Extracting features from dataset")

    features = []

    try:
        # Get annotations DataFrame
        if not hasattr(dataset, "annotations") or dataset.annotations is None:
            raise NeurosynthDataError("Neurosynth dataset has no annotations")
        annotations_df = dataset.annotations

        logger.info(f"📊 Found annotations for {len(annotations_df)} studies")

        annotations_df = annotations_df[annotations_df.index.isin(studies_processed)]
        if annotations_df.empty:
            raise NeurosynthDataError(
                "Neurosynth annotations contain no processed studies"
            )

        for study_id, row in annotations_df.iterrows():
            try:
                study_features = row[row > 0].sort_values(ascending=False)

                if len(study_features) > 0:
                    feature_data = {
                        "study_id": str(study_id),
                        "features": [
                            {"name": feature_name, "value": float(value)}
                            for feature_name, value in study_features.head(20).items()
                        ],
                        "source": "neurosynth",
                    }

                    features.append(feature_data)

            except Exception as exc:
                raise NeurosynthDataError(
                    f"failed to process annotations for study {study_id}: {exc}"
                ) from exc

        if not features:
            raise NeurosynthDataError("Neurosynth annotations yielded zero features")

        # Save features
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(features, f, indent=2, ensure_ascii=False)

        logger.info(f"✅ Extracted features for {len(features)} studies")

    except NeurosynthDataError:
        output_file.unlink(missing_ok=True)
        raise
    except Exception as exc:
        output_file.unlink(missing_ok=True)
        raise NeurosynthDataError(f"Feature extraction failed: {exc}") from exc

    return len(features)


def _extract_metadata_from_dataset(
    dataset: Dataset, output_file: Path, studies_processed: set
) -> int:
    """Extract metadata from NiMARE dataset."""
    logger.info("🔄 Extracting metadata from dataset")

    metadata = []

    try:
        # Get metadata DataFrame
        if not hasattr(dataset, "metadata") or dataset.metadata is None:
            raise NeurosynthDataError("Neurosynth dataset has no metadata")
        metadata_df = dataset.metadata

        logger.info(f"📊 Found metadata for {len(metadata_df)} studies")

        metadata_df = metadata_df[metadata_df.index.isin(studies_processed)]
        if metadata_df.empty:
            raise NeurosynthDataError("Neurosynth metadata contain no processed studies")

        for study_id, row in metadata_df.iterrows():
            try:
                study_metadata = {
                    "study_id": str(study_id),
                    "title": str(row.get("title", "")),
                    "authors": str(row.get("authors", "")),
                    "journal": str(row.get("journal", "")),
                    "year": row.get("year"),
                    "doi": str(row.get("doi", "")),
                    "pmid": str(row.get("pmid", "")),
                    "source": "neurosynth",
                }

                metadata.append(study_metadata)

            except Exception as exc:
                raise NeurosynthDataError(
                    f"failed to process metadata for study {study_id}: {exc}"
                ) from exc

        if not metadata:
            raise NeurosynthDataError("Neurosynth metadata yielded zero rows")

        # Save metadata
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        logger.info(f"✅ Extracted metadata for {len(metadata)} studies")

    except NeurosynthDataError:
        output_file.unlink(missing_ok=True)
        raise
    except Exception as exc:
        output_file.unlink(missing_ok=True)
        raise NeurosynthDataError(f"Metadata extraction failed: {exc}") from exc

    return len(metadata)


def _create_sample_neurosynth_data(output_path: Path) -> dict[str, str]:
    """Create sample Neurosynth data when dataset is unavailable."""
    logger.info("📝 Creating sample Neurosynth data")

    # Sample coordinates (working memory related)
    sample_coordinates = [
        {
            "id": "coord_000001",
            "study_id": "study_001",
            "x": -45.0,
            "y": 23.0,
            "z": 35.0,
            "space": "MNI",
            "source": "neurosynth",
        },
        {
            "id": "coord_000002",
            "study_id": "study_001",
            "x": 48.0,
            "y": 20.0,
            "z": 32.0,
            "space": "MNI",
            "source": "neurosynth",
        },
        {
            "id": "coord_000003",
            "study_id": "study_002",
            "x": -32.0,
            "y": -58.0,
            "z": 48.0,
            "space": "MNI",
            "source": "neurosynth",
        },
        {
            "id": "coord_000004",
            "study_id": "study_002",
            "x": 35.0,
            "y": -55.0,
            "z": 45.0,
            "space": "MNI",
            "source": "neurosynth",
        },
        {
            "id": "coord_000005",
            "study_id": "study_003",
            "x": 0.0,
            "y": 15.0,
            "z": 50.0,
            "space": "MNI",
            "source": "neurosynth",
        },
    ]

    # Sample features
    sample_features = [
        {
            "study_id": "study_001",
            "features": [
                {"name": "working memory", "value": 0.85},
                {"name": "attention", "value": 0.72},
                {"name": "executive", "value": 0.68},
                {"name": "prefrontal", "value": 0.65},
            ],
            "source": "neurosynth",
        },
        {
            "study_id": "study_002",
            "features": [
                {"name": "working memory", "value": 0.78},
                {"name": "spatial", "value": 0.65},
                {"name": "parietal", "value": 0.71},
                {"name": "visual", "value": 0.58},
            ],
            "source": "neurosynth",
        },
        {
            "study_id": "study_003",
            "features": [
                {"name": "working memory", "value": 0.82},
                {"name": "cognitive control", "value": 0.75},
                {"name": "anterior cingulate", "value": 0.69},
            ],
            "source": "neurosynth",
        },
    ]

    # Sample metadata
    sample_metadata = [
        {
            "study_id": "study_001",
            "title": "Working memory and prefrontal cortex activation",
            "authors": "Smith, J. et al.",
            "journal": "NeuroImage",
            "year": 2020,
            "doi": "10.1016/j.neuroimage.2020.001",
            "pmid": "12345678",
            "source": "neurosynth",
        },
        {
            "study_id": "study_002",
            "title": "Spatial working memory in parietal cortex",
            "authors": "Johnson, M. et al.",
            "journal": "Journal of Neuroscience",
            "year": 2021,
            "doi": "10.1523/JNEUROSCI.2021.002",
            "pmid": "23456789",
            "source": "neurosynth",
        },
        {
            "study_id": "study_003",
            "title": "Cognitive control and anterior cingulate",
            "authors": "Brown, K. et al.",
            "journal": "Cerebral Cortex",
            "year": 2022,
            "doi": "10.1093/cercor.2022.003",
            "pmid": "34567890",
            "source": "neurosynth",
        },
    ]

    for record in (*sample_coordinates, *sample_features, *sample_metadata):
        record["source"] = "synthetic_neurosynth_demo"
        record["synthetic"] = True

    output_files = {}

    # Save sample coordinates
    coordinates_output = output_path / "neurosynth_coordinates.json"
    with open(coordinates_output, "w", encoding="utf-8") as f:
        json.dump(sample_coordinates, f, indent=2, ensure_ascii=False)
    output_files["coordinates"] = str(coordinates_output)

    # Save sample features
    features_output = output_path / "neurosynth_features.json"
    with open(features_output, "w", encoding="utf-8") as f:
        json.dump(sample_features, f, indent=2, ensure_ascii=False)
    output_files["features"] = str(features_output)

    # Save sample metadata
    metadata_output = output_path / "neurosynth_metadata.json"
    with open(metadata_output, "w", encoding="utf-8") as f:
        json.dump(sample_metadata, f, indent=2, ensure_ascii=False)
    output_files["metadata"] = str(metadata_output)

    logger.info(
        f"✅ Created sample data: {len(sample_coordinates)} coordinates, "
        f"{len(sample_features)} feature sets, {len(sample_metadata)} metadata entries"
    )

    return output_files


def process_neurosynth_data(
    raw_dir: str, output_dir: str, coordinate_limit: int = 10000
) -> dict[str, str]:
    """
    Process Neurosynth data into BR-KG format.

    Args:
        raw_dir: Directory containing raw Neurosynth files
        output_dir: Directory to save processed files
        coordinate_limit: Maximum coordinates to process

    Returns:
        Dictionary mapping data type to output file path
    """
    logger.info(f"🔄 Processing Neurosynth data from {raw_dir}")

    raw_path = Path(raw_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    output_files = {}

    required = {
        "coordinates": raw_path / "neurosynth_coordinates.json",
        "features": raw_path / "neurosynth_features.json",
        "metadata": raw_path / "neurosynth_metadata.json",
    }
    missing = [str(path) for path in required.values() if not path.is_file()]
    if missing:
        raise NeurosynthDataError(
            "processed Neurosynth bundle is incomplete: " + ", ".join(missing)
        )

    coordinates_file = raw_path / "neurosynth_coordinates.json"
    coordinates_output = output_path / "coordinates.csv"
    _convert_coordinates_to_csv(coordinates_file, coordinates_output, coordinate_limit)
    output_files["coordinates"] = str(coordinates_output)
    logger.info("✅ Converted coordinates to CSV")

    features_file = raw_path / "neurosynth_features.json"
    features_output = output_path / "features.csv"
    _convert_features_to_csv(features_file, features_output)
    output_files["features"] = str(features_output)
    logger.info("✅ Converted features to CSV")

    metadata_file = raw_path / "neurosynth_metadata.json"
    metadata_output = output_path / "metadata.csv"
    _convert_metadata_to_csv(metadata_file, metadata_output)
    output_files["metadata"] = str(metadata_output)
    logger.info("✅ Converted metadata to CSV")

    return output_files


def _convert_coordinates_to_csv(coordinates_file: Path, output_file: Path, limit: int):
    """Convert coordinates JSON to CSV format."""
    with open(coordinates_file, encoding="utf-8") as f:
        coordinates = json.load(f)
    if not isinstance(coordinates, list) or not coordinates:
        raise NeurosynthDataError("coordinates JSON is empty or invalid")

    with open(output_file, "w", encoding="utf-8") as f:
        # Write CSV header
        f.write("study_id,x,y,z,space\n")

        for coord in coordinates[:limit]:
            f.write(
                f"{coord['study_id']},{coord['x']},{coord['y']},{coord['z']},"
                f"{coord.get('space', 'MNI')}\n"
            )


def _convert_features_to_csv(features_file: Path, output_file: Path):
    """Convert features JSON to CSV format."""
    with open(features_file, encoding="utf-8") as f:
        features = json.load(f)
    if not isinstance(features, list) or not features:
        raise NeurosynthDataError("features JSON is empty or invalid")

    with open(output_file, "w", encoding="utf-8") as f:
        # Write CSV header
        f.write("study_id,feature_name,feature_value\n")

        for study_features in features:
            study_id = study_features["study_id"]
            for feature in study_features["features"]:
                f.write(f"{study_id},{feature['name']},{feature['value']}\n")


def _convert_metadata_to_csv(metadata_file: Path, output_file: Path):
    """Convert metadata JSON to CSV format."""
    with open(metadata_file, encoding="utf-8") as f:
        metadata = json.load(f)
    if not isinstance(metadata, list) or not metadata:
        raise NeurosynthDataError("metadata JSON is empty or invalid")

    with open(output_file, "w", encoding="utf-8") as f:
        # Write CSV header
        f.write("study_id,title,authors,journal,year,doi,pmid\n")

        for study in metadata:
            # Escape CSV fields
            title = study.get("title", "").replace('"', '""')
            authors = study.get("authors", "").replace('"', '""')
            journal = study.get("journal", "").replace('"', '""')

            f.write(
                f'"{study["study_id"]}","{title}","{authors}","{journal}",'
                f'{study.get("year", "")},"{study.get("doi", "")}","{study.get("pmid", "")}"\n'
            )


if __name__ == "__main__":
    # Test the loader
    import tempfile

    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            result = load_neurosynth_data(temp_dir, sample_size=100, use_local=True)
            print(f"✅ Test successful: {result}")
        except Exception as e:
            raise SystemExit(f"Neurosynth loader test failed: {e}") from e
