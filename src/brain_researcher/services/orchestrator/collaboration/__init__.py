"""
Real-time Collaboration Infrastructure for Brain Researcher.

This package provides comprehensive real-time collaboration features including:
- Operational transformation for conflict-free collaborative editing
- Sophisticated conflict resolution with multiple strategies
- Brain annotation collaboration with specialized tools
- State synchronization with versioning and consistency guarantees
- Enhanced WebSocket endpoints with integrated collaboration features

Key Components:
- CollaborationManager: Core collaboration session management
- OperationalTransform: Conflict-free operation transformation
- ConflictResolver: Advanced conflict resolution strategies
- BrainAnnotationManager: Specialized brain annotation collaboration
- StateSynchronizer: Document state synchronization protocol
- Enhanced WebSocket endpoints: WebSocket API integration

Usage:
    from brain_researcher.services.orchestrator.collaboration import (
        CollaborationManager,
        BrainAnnotationManager,
        OperationalTransform,
        ConflictResolver,
        StateSynchronizer
    )
"""

from .brain_annotation_manager import (
    AnnotationStatus,
    AnnotationType,
    BrainAnnotation,
    BrainAnnotationManager,
    BrainCoordinate,
    BrainRegion,
    CoordinateSystem,
)
from .collaboration_manager import (
    CollaborationManager,
    CollaborativeUser,
    DocumentSession,
    PermissionLevel,
    SessionState,
    UserRole,
)
from .conflict_resolver import (
    ConflictInfo,
    ConflictResolution,
    ConflictResolutionStrategy,
    ConflictResolver,
    ConflictType,
)
from .enhanced_websocket_endpoints import (
    initialize_collaboration_infrastructure,
)
from .enhanced_websocket_endpoints import router as collaboration_router
from .enhanced_websocket_endpoints import (
    shutdown_collaboration_infrastructure,
)
from .operational_transform import (
    DocumentState,
    Operation,
    OperationalTransform,
    OperationType,
)
from .state_synchronizer import (
    ClientState,
    DocumentFormat,
    DocumentState,
    StateSynchronizer,
    SyncEvent,
    SyncEventType,
)

__all__ = [
    # Core managers
    "CollaborationManager",
    "BrainAnnotationManager",
    "OperationalTransform",
    "ConflictResolver",
    "StateSynchronizer",
    # Data models
    "CollaborativeUser",
    "DocumentSession",
    "Operation",
    "DocumentState",
    "ConflictInfo",
    "ConflictResolution",
    "BrainAnnotation",
    "BrainCoordinate",
    "BrainRegion",
    "SyncEvent",
    "ClientState",
    # Enums
    "UserRole",
    "PermissionLevel",
    "SessionState",
    "OperationType",
    "ConflictResolutionStrategy",
    "ConflictType",
    "AnnotationType",
    "CoordinateSystem",
    "AnnotationStatus",
    "SyncEventType",
    "DocumentFormat",
    # WebSocket integration
    "collaboration_router",
    "initialize_collaboration_infrastructure",
    "shutdown_collaboration_infrastructure",
]

# Version info
__version__ = "1.0.0"
__author__ = "Brain Researcher Team"
__description__ = "Real-time Collaboration Infrastructure"
