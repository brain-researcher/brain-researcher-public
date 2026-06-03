"""
Artifact Metadata Index - Deterministic lookup system for demo NIfTI files

Addresses Codex review concern: "The plan omits how demo_id/artifact_id map to
the 920 files. Without a deterministic lookup every request risks 404s or serving
the wrong subject/contrast."

This module creates a searchable index of all artifacts with extracted metadata.
"""

from pathlib import Path
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, ConfigDict
import re
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class ArtifactMetadata(BaseModel):
    """Structured metadata for a single NIfTI artifact"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    artifact_id: str = Field(..., description="Unique identifier (relative path)")
    demo_id: str = Field(..., description="Parent demo ID (e.g., glm_motor)")
    file_path: Path = Field(..., description="Absolute path to NIfTI file")
    file_name: str = Field(..., description="Original filename")
    file_size_bytes: int = Field(..., description="File size in bytes")

    # Extracted from filename
    subject_id: Optional[str] = Field(None, description="Subject ID (e.g., sub-01)")
    session: Optional[str] = Field(None, description="Session (e.g., retest)")
    contrast: Optional[str] = Field(None, description="Contrast type (finger/foot/lips)")
    statistic: Optional[str] = Field(None, description="Stat type (z/t/p/effect/variance)")

    # Additional metadata
    coordinate_space: str = Field(default="MNI152", description="Coordinate space")
    modification_time: datetime = Field(..., description="File modification timestamp")


class ArtifactIndex:
    """Index manager for demo artifacts"""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.data_root = project_root / "data"
        self._indexes: Dict[str, Dict[str, ArtifactMetadata]] = {}

    def build_index(self, demo_id: str, output_path: Path) -> Dict[str, ArtifactMetadata]:
        """
        Build searchable index for a demo's artifacts

        Args:
            demo_id: Demo identifier (e.g., 'glm_motor')
            output_path: Path to demo output directory (relative to data_root)

        Returns:
            Dictionary mapping artifact_id -> ArtifactMetadata
        """
        if demo_id in self._indexes:
            return self._indexes[demo_id]

        index = {}
        full_output_path = self.data_root / output_path

        if not full_output_path.exists():
            logger.warning(f"Output path does not exist: {full_output_path}")
            return index

        # Find all NIfTI files recursively
        nifti_files = list(full_output_path.rglob("*.nii.gz"))
        logger.info(f"Building index for {demo_id}: found {len(nifti_files)} NIfTI files")

        for nifti_file in nifti_files:
            # Handle git-annex symlinks - check if it's a symlink OR exists
            if not (nifti_file.is_symlink() or nifti_file.exists()):
                continue

            # Create artifact ID as relative path from output directory
            try:
                artifact_id = str(nifti_file.relative_to(full_output_path))
            except ValueError:
                logger.warning(f"File outside output path: {nifti_file}")
                continue

            # Extract metadata from filename
            try:
                metadata = self._extract_metadata(
                    demo_id=demo_id,
                    artifact_id=artifact_id,
                    file_path=nifti_file
                )
                index[artifact_id] = metadata
            except Exception as e:
                logger.warning(f"Failed to extract metadata for {nifti_file}: {e}")
                continue

        self._indexes[demo_id] = index
        logger.info(f"Index built for {demo_id}: {len(index)} artifacts indexed")
        return index

    def get_artifact_metadata(
        self,
        demo_id: str,
        artifact_id: str
    ) -> Optional[ArtifactMetadata]:
        """
        Get metadata for a specific artifact (deterministic lookup)

        Args:
            demo_id: Demo identifier
            artifact_id: Artifact identifier (relative path)

        Returns:
            ArtifactMetadata if found, None otherwise
        """
        if demo_id not in self._indexes:
            return None
        return self._indexes[demo_id].get(artifact_id)

    def get_artifact_path(
        self,
        demo_id: str,
        artifact_id: str
    ) -> Optional[Path]:
        """
        Get absolute path to artifact file (deterministic lookup)

        Prevents 404s and ensures we serve the correct file.

        Args:
            demo_id: Demo identifier
            artifact_id: Artifact identifier

        Returns:
            Absolute Path if found, None otherwise
        """
        metadata = self.get_artifact_metadata(demo_id, artifact_id)
        if metadata:
            return metadata.file_path
        return None

    def filter_artifacts(
        self,
        demo_id: str,
        contrast: Optional[str] = None,
        statistic: Optional[str] = None,
        subject_id: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[ArtifactMetadata]:
        """
        Filter artifacts by metadata fields

        Args:
            demo_id: Demo identifier
            contrast: Filter by contrast type (e.g., 'finger')
            statistic: Filter by statistic type (e.g., 'z')
            subject_id: Filter by subject ID (e.g., 'sub-01')
            limit: Maximum number of results

        Returns:
            List of matching ArtifactMetadata
        """
        if demo_id not in self._indexes:
            return []

        artifacts = list(self._indexes[demo_id].values())

        # Apply filters
        if contrast:
            artifacts = [a for a in artifacts if a.contrast == contrast]
        if statistic:
            artifacts = [a for a in artifacts if a.statistic == statistic]
        if subject_id:
            artifacts = [a for a in artifacts if a.subject_id == subject_id]

        # Sort by modification time (most recent first)
        artifacts.sort(key=lambda a: a.modification_time, reverse=True)

        # Apply limit
        if limit:
            artifacts = artifacts[:limit]

        return artifacts

    def get_contrasts(self, demo_id: str) -> List[str]:
        """Get list of unique contrasts for a demo"""
        if demo_id not in self._indexes:
            return []
        contrasts = {a.contrast for a in self._indexes[demo_id].values() if a.contrast}
        return sorted(list(contrasts))

    def get_subjects(self, demo_id: str) -> List[str]:
        """Get list of unique subjects for a demo"""
        if demo_id not in self._indexes:
            return []
        subjects = {a.subject_id for a in self._indexes[demo_id].values() if a.subject_id}
        return sorted(list(subjects))

    def get_statistics(self, demo_id: str) -> List[str]:
        """Get list of unique statistic types for a demo"""
        if demo_id not in self._indexes:
            return []
        stats = {a.statistic for a in self._indexes[demo_id].values() if a.statistic}
        return sorted(list(stats))

    def _extract_metadata(
        self,
        demo_id: str,
        artifact_id: str,
        file_path: Path
    ) -> ArtifactMetadata:
        """
        Extract metadata from NIfTI filename

        Expected format: sub-{id}_ses-{session}_contrast-{contrast}_stat-{stat}_statmap.nii.gz
        Example: sub-06_ses-retest_contrast-finger_stat-z_statmap.nii.gz
        """
        filename = file_path.name

        # Extract subject ID
        subject_match = re.search(r'sub-(\d+)', filename)
        subject_id = f"sub-{subject_match.group(1)}" if subject_match else None

        # Extract session
        session_match = re.search(r'ses-(\w+)', filename)
        session = session_match.group(1) if session_match else None

        # Extract contrast
        contrast_match = re.search(r'contrast-([a-z]+)', filename)
        contrast = contrast_match.group(1) if contrast_match else None

        # Extract statistic type
        stat_match = re.search(r'stat-([a-z]+)', filename)
        statistic = stat_match.group(1) if stat_match else None

        # Get file stats (use lstat for symlinks to avoid errors on broken links)
        stat_info = file_path.lstat()

        return ArtifactMetadata(
            artifact_id=artifact_id,
            demo_id=demo_id,
            file_path=file_path,
            file_name=filename,
            file_size_bytes=stat_info.st_size,
            subject_id=subject_id,
            session=session,
            contrast=contrast,
            statistic=statistic,
            coordinate_space="MNI152",  # FSL FEAT default
            modification_time=datetime.fromtimestamp(stat_info.st_mtime)
        )

    def get_index_stats(self, demo_id: str) -> Dict[str, Any]:
        """Get statistics about the indexed artifacts"""
        if demo_id not in self._indexes:
            return {}

        index = self._indexes[demo_id]

        return {
            "total_artifacts": len(index),
            "unique_subjects": len(self.get_subjects(demo_id)),
            "unique_contrasts": len(self.get_contrasts(demo_id)),
            "unique_statistics": len(self.get_statistics(demo_id)),
            "total_size_bytes": sum(a.file_size_bytes for a in index.values()),
            "contrasts": self.get_contrasts(demo_id),
            "subjects": self.get_subjects(demo_id),
            "statistics": self.get_statistics(demo_id)
        }
