"""
Brain Annotation Collaboration Manager for Real-time Neuroimaging Annotation.

Provides specialized collaboration features for brain imaging annotations,
including ROI (Region of Interest) marking, statistical annotation, and 
collaborative brain mapping.
"""

import asyncio
import json
import logging
import numpy as np
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, Union, Tuple, Set
import uuid

from .operational_transform import Operation, OperationType

logger = logging.getLogger(__name__)


class AnnotationType(str, Enum):
    """Types of brain annotations."""
    ROI = "roi"  # Region of Interest
    ACTIVATION = "activation"  # Activation cluster
    STATISTICAL = "statistical"  # Statistical annotation
    ANATOMICAL = "anatomical"  # Anatomical label
    FUNCTIONAL = "functional"  # Functional annotation
    LANDMARK = "landmark"  # Anatomical landmark
    COMMENT = "comment"  # Text comment
    MEASUREMENT = "measurement"  # Quantitative measurement


class CoordinateSystem(str, Enum):
    """Coordinate systems used in neuroimaging."""
    TALAIRACH = "talairach"
    MNI = "mni"
    NATIVE = "native"
    SURFACE = "surface"
    VOXEL = "voxel"


class AnnotationStatus(str, Enum):
    """Status of annotations."""
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    ARCHIVED = "archived"


@dataclass
class BrainCoordinate:
    """3D coordinate in brain space."""
    x: float
    y: float
    z: float
    coordinate_system: CoordinateSystem
    hemisphere: Optional[str] = None  # left, right, bilateral
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BrainCoordinate':
        return cls(**data)
    
    def distance_to(self, other: 'BrainCoordinate') -> float:
        """Calculate Euclidean distance to another coordinate."""
        if self.coordinate_system != other.coordinate_system:
            raise ValueError("Cannot calculate distance between different coordinate systems")
        
        return np.sqrt((self.x - other.x)**2 + (self.y - other.y)**2 + (self.z - other.z)**2)


@dataclass
class BrainRegion:
    """Represents a brain region or ROI."""
    region_id: str
    name: str
    coordinates: List[BrainCoordinate]
    center: BrainCoordinate
    volume_mm3: Optional[float] = None
    anatomical_labels: List[str] = None
    confidence: float = 1.0
    
    def __post_init__(self):
        if not self.region_id:
            self.region_id = f"region_{uuid.uuid4().hex[:8]}"
        if self.anatomical_labels is None:
            self.anatomical_labels = []
    
    def contains_coordinate(self, coord: BrainCoordinate, tolerance: float = 2.0) -> bool:
        """Check if coordinate is within this region."""
        return any(c.distance_to(coord) <= tolerance for c in self.coordinates)
    
    def overlaps_with(self, other: 'BrainRegion', tolerance: float = 5.0) -> bool:
        """Check if this region overlaps with another."""
        return any(
            other.contains_coordinate(coord, tolerance) 
            for coord in self.coordinates
        )


@dataclass
class BrainAnnotation:
    """Comprehensive brain annotation with collaborative metadata."""
    annotation_id: str
    annotation_type: AnnotationType
    title: str
    description: str
    author_id: str
    author_name: str
    created_at: datetime
    modified_at: datetime
    status: AnnotationStatus = AnnotationStatus.DRAFT
    
    # Spatial information
    coordinate: Optional[BrainCoordinate] = None
    region: Optional[BrainRegion] = None
    slice_index: Optional[int] = None
    
    # Statistical information
    statistical_values: Dict[str, float] = None
    thresholds: Dict[str, float] = None
    
    # Visual properties
    color: str = "#FF0000"
    opacity: float = 0.7
    marker_size: float = 5.0
    visible: bool = True
    
    # Collaborative metadata
    reviewers: List[str] = None
    comments: List[Dict[str, Any]] = None
    version: int = 1
    parent_annotation_id: Optional[str] = None
    tags: List[str] = None
    
    # Data references
    source_dataset: Optional[str] = None
    source_image: Optional[str] = None
    analysis_id: Optional[str] = None
    
    def __post_init__(self):
        if not self.annotation_id:
            self.annotation_id = f"annotation_{uuid.uuid4().hex[:12]}"
        if self.statistical_values is None:
            self.statistical_values = {}
        if self.thresholds is None:
            self.thresholds = {}
        if self.reviewers is None:
            self.reviewers = []
        if self.comments is None:
            self.comments = []
        if self.tags is None:
            self.tags = []
    
    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        # Convert datetime objects to ISO strings
        data['created_at'] = self.created_at.isoformat()
        data['modified_at'] = self.modified_at.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BrainAnnotation':
        # Convert ISO strings back to datetime objects
        if isinstance(data.get('created_at'), str):
            data['created_at'] = datetime.fromisoformat(data['created_at'])
        if isinstance(data.get('modified_at'), str):
            data['modified_at'] = datetime.fromisoformat(data['modified_at'])
        
        # Handle nested objects
        if data.get('coordinate'):
            data['coordinate'] = BrainCoordinate.from_dict(data['coordinate'])
        if data.get('region'):
            region_data = data['region']
            if region_data.get('coordinates'):
                region_data['coordinates'] = [
                    BrainCoordinate.from_dict(c) for c in region_data['coordinates']
                ]
            if region_data.get('center'):
                region_data['center'] = BrainCoordinate.from_dict(region_data['center'])
            data['region'] = BrainRegion(**region_data)
        
        return cls(**data)


class BrainAnnotationManager:
    """
    Manager for collaborative brain imaging annotations.
    
    Handles real-time collaboration on brain annotations including:
    - ROI definition and editing
    - Statistical annotation
    - Anatomical labeling
    - Collaborative review workflows
    """
    
    def __init__(self, redis_client=None):
        self.redis_client = redis_client
        
        # Storage for active annotations
        self.annotations: Dict[str, BrainAnnotation] = {}
        self.annotations_by_document: Dict[str, Set[str]] = {}
        self.annotations_by_author: Dict[str, Set[str]] = {}
        
        # Collaborative state
        self.active_editors: Dict[str, Dict[str, Any]] = {}  # annotation_id -> user_info
        self.review_sessions: Dict[str, Dict[str, Any]] = {}
        
        # Template annotations and atlases
        self.annotation_templates: Dict[str, Dict[str, Any]] = {}
        self.brain_atlases: Dict[str, Dict[str, Any]] = {}
        
        # Event handlers
        self.annotation_handlers: List[callable] = []
        self.review_handlers: List[callable] = []
        
        self._load_default_templates()
        
        logger.info("Brain annotation manager initialized")
    
    async def create_annotation(
        self,
        document_id: str,
        annotation_type: AnnotationType,
        title: str,
        description: str,
        author_id: str,
        author_name: str,
        coordinate: Optional[BrainCoordinate] = None,
        region: Optional[BrainRegion] = None,
        **kwargs
    ) -> BrainAnnotation:
        """Create a new brain annotation."""
        
        now = datetime.utcnow()
        
        annotation = BrainAnnotation(
            annotation_id="",  # Will be generated in __post_init__
            annotation_type=annotation_type,
            title=title,
            description=description,
            author_id=author_id,
            author_name=author_name,
            created_at=now,
            modified_at=now,
            coordinate=coordinate,
            region=region,
            **kwargs
        )
        
        # Store annotation
        self.annotations[annotation.annotation_id] = annotation
        
        # Update indices
        if document_id not in self.annotations_by_document:
            self.annotations_by_document[document_id] = set()
        self.annotations_by_document[document_id].add(annotation.annotation_id)
        
        if author_id not in self.annotations_by_author:
            self.annotations_by_author[author_id] = set()
        self.annotations_by_author[author_id].add(annotation.annotation_id)
        
        # Notify handlers
        await self._notify_annotation_created(document_id, annotation)
        
        logger.info(f"Created brain annotation: {annotation.annotation_id}")
        return annotation
    
    async def update_annotation(
        self,
        annotation_id: str,
        user_id: str,
        updates: Dict[str, Any]
    ) -> Optional[BrainAnnotation]:
        """Update an existing annotation."""
        
        if annotation_id not in self.annotations:
            logger.warning(f"Annotation {annotation_id} not found")
            return None
        
        annotation = self.annotations[annotation_id]
        
        # Check permissions
        if not await self._check_annotation_permission(annotation, user_id, "edit"):
            logger.warning(f"User {user_id} lacks permission to edit annotation {annotation_id}")
            return None
        
        # Apply updates
        for key, value in updates.items():
            if hasattr(annotation, key):
                setattr(annotation, key, value)
        
        # Update metadata
        annotation.modified_at = datetime.utcnow()
        annotation.version += 1
        
        # Notify handlers
        await self._notify_annotation_updated(annotation, user_id, updates)
        
        return annotation
    
    async def delete_annotation(
        self,
        annotation_id: str,
        user_id: str
    ) -> bool:
        """Delete an annotation."""
        
        if annotation_id not in self.annotations:
            return False
        
        annotation = self.annotations[annotation_id]
        
        # Check permissions
        if not await self._check_annotation_permission(annotation, user_id, "delete"):
            logger.warning(f"User {user_id} lacks permission to delete annotation {annotation_id}")
            return False
        
        # Remove from indices
        for doc_annotations in self.annotations_by_document.values():
            doc_annotations.discard(annotation_id)
        
        if annotation.author_id in self.annotations_by_author:
            self.annotations_by_author[annotation.author_id].discard(annotation_id)
        
        # Remove annotation
        del self.annotations[annotation_id]
        
        # Notify handlers
        await self._notify_annotation_deleted(annotation, user_id)
        
        logger.info(f"Deleted annotation: {annotation_id}")
        return True
    
    async def get_document_annotations(
        self,
        document_id: str,
        filter_criteria: Optional[Dict[str, Any]] = None
    ) -> List[BrainAnnotation]:
        """Get all annotations for a document with optional filtering."""
        
        annotation_ids = self.annotations_by_document.get(document_id, set())
        annotations = [self.annotations[aid] for aid in annotation_ids if aid in self.annotations]
        
        # Apply filters if provided
        if filter_criteria:
            annotations = await self._filter_annotations(annotations, filter_criteria)
        
        return annotations
    
    async def find_annotations_by_coordinate(
        self,
        coordinate: BrainCoordinate,
        radius: float = 10.0,
        document_id: Optional[str] = None
    ) -> List[BrainAnnotation]:
        """Find annotations near a specific coordinate."""
        
        search_annotations = []
        
        if document_id:
            search_annotations = await self.get_document_annotations(document_id)
        else:
            search_annotations = list(self.annotations.values())
        
        nearby_annotations = []
        
        for annotation in search_annotations:
            if annotation.coordinate and annotation.coordinate.distance_to(coordinate) <= radius:
                nearby_annotations.append(annotation)
            elif annotation.region and annotation.region.contains_coordinate(coordinate, radius):
                nearby_annotations.append(annotation)
        
        return nearby_annotations
    
    async def find_overlapping_annotations(
        self,
        region: BrainRegion,
        document_id: Optional[str] = None
    ) -> List[BrainAnnotation]:
        """Find annotations that overlap with a given region."""
        
        search_annotations = []
        
        if document_id:
            search_annotations = await self.get_document_annotations(document_id)
        else:
            search_annotations = list(self.annotations.values())
        
        overlapping = []
        
        for annotation in search_annotations:
            if annotation.region and annotation.region.overlaps_with(region):
                overlapping.append(annotation)
            elif annotation.coordinate and region.contains_coordinate(annotation.coordinate):
                overlapping.append(annotation)
        
        return overlapping
    
    async def start_collaborative_editing(
        self,
        annotation_id: str,
        user_id: str,
        user_name: str
    ) -> bool:
        """Start collaborative editing session for an annotation."""
        
        if annotation_id not in self.annotations:
            return False
        
        annotation = self.annotations[annotation_id]
        
        # Check permissions
        if not await self._check_annotation_permission(annotation, user_id, "edit"):
            return False
        
        # Add to active editors
        if annotation_id not in self.active_editors:
            self.active_editors[annotation_id] = {}
        
        self.active_editors[annotation_id][user_id] = {
            "user_id": user_id,
            "user_name": user_name,
            "started_at": datetime.utcnow(),
            "last_activity": datetime.utcnow(),
            "cursor_position": None
        }
        
        # Notify other editors
        await self._notify_editor_joined(annotation_id, user_id, user_name)
        
        return True
    
    async def stop_collaborative_editing(
        self,
        annotation_id: str,
        user_id: str
    ) -> bool:
        """Stop collaborative editing session."""
        
        if (annotation_id not in self.active_editors or 
            user_id not in self.active_editors[annotation_id]):
            return False
        
        user_name = self.active_editors[annotation_id][user_id]["user_name"]
        
        # Remove from active editors
        del self.active_editors[annotation_id][user_id]
        
        # Clean up empty editor groups
        if not self.active_editors[annotation_id]:
            del self.active_editors[annotation_id]
        
        # Notify other editors
        await self._notify_editor_left(annotation_id, user_id, user_name)
        
        return True
    
    async def update_editor_cursor(
        self,
        annotation_id: str,
        user_id: str,
        cursor_position: Dict[str, Any]
    ) -> bool:
        """Update editor's cursor position."""
        
        if (annotation_id not in self.active_editors or 
            user_id not in self.active_editors[annotation_id]):
            return False
        
        self.active_editors[annotation_id][user_id]["cursor_position"] = cursor_position
        self.active_editors[annotation_id][user_id]["last_activity"] = datetime.utcnow()
        
        # Broadcast cursor update
        await self._notify_cursor_update(annotation_id, user_id, cursor_position)
        
        return True
    
    async def start_annotation_review(
        self,
        annotation_id: str,
        reviewer_id: str,
        reviewer_name: str
    ) -> str:
        """Start a review session for an annotation."""
        
        if annotation_id not in self.annotations:
            raise ValueError(f"Annotation {annotation_id} not found")
        
        annotation = self.annotations[annotation_id]
        
        # Create review session
        review_session_id = f"review_{uuid.uuid4().hex[:8]}"
        
        self.review_sessions[review_session_id] = {
            "session_id": review_session_id,
            "annotation_id": annotation_id,
            "reviewer_id": reviewer_id,
            "reviewer_name": reviewer_name,
            "started_at": datetime.utcnow(),
            "status": "in_progress",
            "comments": [],
            "decision": None
        }
        
        # Add reviewer to annotation
        if reviewer_id not in annotation.reviewers:
            annotation.reviewers.append(reviewer_id)
        
        # Update annotation status
        if annotation.status == AnnotationStatus.DRAFT:
            annotation.status = AnnotationStatus.PENDING_REVIEW
        
        # Notify handlers
        await self._notify_review_started(review_session_id, annotation)
        
        return review_session_id
    
    async def submit_annotation_review(
        self,
        review_session_id: str,
        decision: str,  # "approved", "rejected", "needs_revision"
        comments: str,
        suggested_changes: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Submit a review decision for an annotation."""
        
        if review_session_id not in self.review_sessions:
            return False
        
        review_session = self.review_sessions[review_session_id]
        annotation_id = review_session["annotation_id"]
        
        if annotation_id not in self.annotations:
            return False
        
        annotation = self.annotations[annotation_id]
        
        # Update review session
        review_session["status"] = "completed"
        review_session["decision"] = decision
        review_session["completed_at"] = datetime.utcnow()
        review_session["comments"].append({
            "text": comments,
            "timestamp": datetime.utcnow().isoformat(),
            "suggested_changes": suggested_changes
        })
        
        # Update annotation based on decision
        if decision == "approved":
            annotation.status = AnnotationStatus.APPROVED
        elif decision == "rejected":
            annotation.status = AnnotationStatus.REJECTED
        # "needs_revision" keeps it in pending_review status
        
        # Add review comment to annotation
        annotation.comments.append({
            "author_id": review_session["reviewer_id"],
            "author_name": review_session["reviewer_name"],
            "text": comments,
            "timestamp": datetime.utcnow().isoformat(),
            "type": "review"
        })
        
        # Notify handlers
        await self._notify_review_completed(review_session_id, annotation, decision)
        
        return True
    
    async def create_annotation_from_template(
        self,
        document_id: str,
        template_name: str,
        coordinate: BrainCoordinate,
        author_id: str,
        author_name: str,
        **overrides
    ) -> Optional[BrainAnnotation]:
        """Create annotation from a predefined template."""
        
        if template_name not in self.annotation_templates:
            logger.warning(f"Template {template_name} not found")
            return None
        
        template = self.annotation_templates[template_name].copy()
        
        # Apply overrides
        template.update(overrides)
        template["coordinate"] = coordinate
        template["author_id"] = author_id
        template["author_name"] = author_name
        
        return await self.create_annotation(document_id, **template)
    
    async def export_annotations(
        self,
        document_id: str,
        format: str = "json"  # json, csv, nifti
    ) -> Dict[str, Any]:
        """Export annotations in various formats."""
        
        annotations = await self.get_document_annotations(document_id)
        
        if format == "json":
            return {
                "document_id": document_id,
                "exported_at": datetime.utcnow().isoformat(),
                "count": len(annotations),
                "annotations": [ann.to_dict() for ann in annotations]
            }
        
        elif format == "csv":
            # Convert to CSV-friendly format
            csv_data = []
            for ann in annotations:
                row = {
                    "annotation_id": ann.annotation_id,
                    "type": ann.annotation_type.value,
                    "title": ann.title,
                    "description": ann.description,
                    "author": ann.author_name,
                    "status": ann.status.value,
                    "created_at": ann.created_at.isoformat(),
                }
                
                if ann.coordinate:
                    row.update({
                        "x": ann.coordinate.x,
                        "y": ann.coordinate.y,
                        "z": ann.coordinate.z,
                        "coordinate_system": ann.coordinate.coordinate_system.value
                    })
                
                csv_data.append(row)
            
            return {
                "format": "csv",
                "data": csv_data
            }
        
        else:
            raise ValueError(f"Unsupported export format: {format}")
    
    # Helper methods
    
    async def _check_annotation_permission(
        self,
        annotation: BrainAnnotation,
        user_id: str,
        action: str
    ) -> bool:
        """Check if user has permission to perform action on annotation."""
        
        # Owner can do anything
        if annotation.author_id == user_id:
            return True
        
        # Reviewers can edit during review
        if action == "edit" and user_id in annotation.reviewers:
            return annotation.status == AnnotationStatus.PENDING_REVIEW
        
        # For now, allow read access to all
        if action == "read":
            return True
        
        return False
    
    async def _filter_annotations(
        self,
        annotations: List[BrainAnnotation],
        criteria: Dict[str, Any]
    ) -> List[BrainAnnotation]:
        """Filter annotations based on criteria."""
        
        filtered = []
        
        for ann in annotations:
            if self._matches_criteria(ann, criteria):
                filtered.append(ann)
        
        return filtered
    
    def _matches_criteria(self, annotation: BrainAnnotation, criteria: Dict[str, Any]) -> bool:
        """Check if annotation matches filter criteria."""
        
        for key, value in criteria.items():
            if key == "type" and annotation.annotation_type != AnnotationType(value):
                return False
            elif key == "status" and annotation.status != AnnotationStatus(value):
                return False
            elif key == "author_id" and annotation.author_id != value:
                return False
            elif key == "tags" and not any(tag in annotation.tags for tag in value):
                return False
            # Add more criteria as needed
        
        return True
    
    def _load_default_templates(self):
        """Load default annotation templates."""
        
        self.annotation_templates = {
            "roi_template": {
                "annotation_type": AnnotationType.ROI,
                "title": "Region of Interest",
                "description": "Standard ROI annotation",
                "color": "#FF0000",
                "opacity": 0.7,
                "marker_size": 8.0
            },
            "activation_template": {
                "annotation_type": AnnotationType.ACTIVATION,
                "title": "Activation Cluster",
                "description": "Significant activation cluster",
                "color": "#00FF00",
                "opacity": 0.8,
                "marker_size": 6.0,
                "statistical_values": {"t_stat": 0.0, "p_value": 0.05}
            },
            "anatomical_template": {
                "annotation_type": AnnotationType.ANATOMICAL,
                "title": "Anatomical Label",
                "description": "Anatomical structure label",
                "color": "#0000FF",
                "opacity": 0.6,
                "marker_size": 5.0
            }
        }
    
    # Event notification methods
    
    async def _notify_annotation_created(self, document_id: str, annotation: BrainAnnotation):
        """Notify handlers about new annotation."""
        for handler in self.annotation_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler("annotation_created", document_id, annotation)
                else:
                    handler("annotation_created", document_id, annotation)
            except Exception as e:
                logger.error(f"Annotation handler error: {str(e)}")
    
    async def _notify_annotation_updated(
        self,
        annotation: BrainAnnotation,
        user_id: str,
        updates: Dict[str, Any]
    ):
        """Notify handlers about annotation update."""
        for handler in self.annotation_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler("annotation_updated", annotation, user_id, updates)
                else:
                    handler("annotation_updated", annotation, user_id, updates)
            except Exception as e:
                logger.error(f"Annotation handler error: {str(e)}")
    
    async def _notify_annotation_deleted(self, annotation: BrainAnnotation, user_id: str):
        """Notify handlers about annotation deletion."""
        for handler in self.annotation_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler("annotation_deleted", annotation, user_id)
                else:
                    handler("annotation_deleted", annotation, user_id)
            except Exception as e:
                logger.error(f"Annotation handler error: {str(e)}")
    
    async def _notify_editor_joined(self, annotation_id: str, user_id: str, user_name: str):
        """Notify about editor joining collaborative session."""
        # This will be handled by WebSocket layer
        pass
    
    async def _notify_editor_left(self, annotation_id: str, user_id: str, user_name: str):
        """Notify about editor leaving collaborative session."""
        # This will be handled by WebSocket layer
        pass
    
    async def _notify_cursor_update(
        self,
        annotation_id: str,
        user_id: str,
        cursor_position: Dict[str, Any]
    ):
        """Notify about cursor position update."""
        # This will be handled by WebSocket layer
        pass
    
    async def _notify_review_started(self, review_session_id: str, annotation: BrainAnnotation):
        """Notify handlers about review session start."""
        for handler in self.review_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler("review_started", review_session_id, annotation)
                else:
                    handler("review_started", review_session_id, annotation)
            except Exception as e:
                logger.error(f"Review handler error: {str(e)}")
    
    async def _notify_review_completed(
        self,
        review_session_id: str,
        annotation: BrainAnnotation,
        decision: str
    ):
        """Notify handlers about review completion."""
        for handler in self.review_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler("review_completed", review_session_id, annotation, decision)
                else:
                    handler("review_completed", review_session_id, annotation, decision)
            except Exception as e:
                logger.error(f"Review handler error: {str(e)}")
    
    # Public API methods
    
    def add_annotation_handler(self, handler: callable):
        """Add handler for annotation events."""
        self.annotation_handlers.append(handler)
    
    def add_review_handler(self, handler: callable):
        """Add handler for review events."""
        self.review_handlers.append(handler)
    
    def get_active_editors(self, annotation_id: str) -> Dict[str, Any]:
        """Get active editors for an annotation."""
        return self.active_editors.get(annotation_id, {})
    
    def get_annotation_stats(self) -> Dict[str, Any]:
        """Get statistics about annotations."""
        total_annotations = len(self.annotations)
        
        type_counts = {}
        status_counts = {}
        
        for ann in self.annotations.values():
            type_counts[ann.annotation_type.value] = type_counts.get(ann.annotation_type.value, 0) + 1
            status_counts[ann.status.value] = status_counts.get(ann.status.value, 0) + 1
        
        return {
            "total_annotations": total_annotations,
            "active_documents": len(self.annotations_by_document),
            "active_editors": sum(len(editors) for editors in self.active_editors.values()),
            "active_reviews": len([r for r in self.review_sessions.values() if r["status"] == "in_progress"]),
            "annotation_types": type_counts,
            "annotation_statuses": status_counts
        }