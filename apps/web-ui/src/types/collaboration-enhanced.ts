import { KnowledgeGraphNode, KnowledgeGraphEdge, BrainMapData } from './visualization'

export interface User {
  id: string
  name: string
  email: string
  avatar?: string
  color: string
  status: 'online' | 'idle' | 'offline'
  lastSeen?: Date
  role?: 'owner' | 'editor' | 'viewer'
  cursor?: CursorPosition
}

export interface CursorPosition {
  userId: string
  x: number
  y: number
  timestamp: number
  viewType?: 'brain' | 'graph' | 'analysis'
  elementId?: string
}

export interface Annotation {
  id: string
  userId: string
  userName: string
  userColor: string
  type: 'point' | 'region' | 'comment' | 'measurement'
  position: {
    x: number
    y: number
    z?: number
  }
  coordinates?: {
    mni: [number, number, number]
    voxel: [number, number, number]
  }
  content: string
  timestamp: Date
  replies?: Annotation[]
  resolved?: boolean
  visible: boolean
  metadata?: Record<string, any>
}

export interface BrainAnnotation extends Annotation {
  anatomicalRegion?: string
  hemisphere?: 'left' | 'right' | 'bilateral'
  sliceType?: 'axial' | 'coronal' | 'sagittal'
  sliceIndex?: number
  volume?: string
}

export interface GraphAnnotation extends Annotation {
  nodeId?: string
  edgeId?: string
  graphPosition?: { x: number; y: number }
}

export interface Operation {
  id: string
  type: 'insert' | 'delete' | 'retain' | 'format' | 'move' | 'annotate' | 'view_change'
  userId: string
  timestamp: number
  documentId: string
  target?: string
  data?: any
  metadata?: Record<string, any>
}

export interface BrainViewOperation extends Operation {
  type: 'view_change'
  data: {
    viewMode: '3d' | 'axial' | 'coronal' | 'sagittal' | 'mosaic'
    coordinates?: [number, number, number]
    threshold?: number
    opacity?: number
    colormap?: string
    zoom?: number
    rotation?: [number, number, number]
  }
}

export interface AnnotationOperation extends Operation {
  type: 'annotate'
  data: {
    action: 'create' | 'update' | 'delete' | 'resolve'
    annotation: Partial<Annotation>
  }
}

export interface TransformResult {
  operation: Operation
  transformed: Operation[]
  conflicts?: ConflictInfo[]
}

export interface ConflictInfo {
  id: string
  type: 'concurrent_edit' | 'view_conflict' | 'annotation_overlap' | 'permission_conflict'
  operations: Operation[]
  users: User[]
  timestamp: Date
  severity: 'low' | 'medium' | 'high'
  autoResolved?: boolean
  resolution?: ConflictResolution
}

export interface ConflictResolution {
  strategy: 'merge' | 'user_priority' | 'timestamp' | 'manual'
  selectedOperation?: string
  mergedResult?: any
  userChoice?: string
  timestamp: Date
}

export interface CollaborationState {
  documentId: string
  activeUsers: User[]
  annotations: Annotation[]
  operations: Operation[]
  conflicts: ConflictInfo[]
  syncStatus: SyncStatus
  permissions: CollaborationPermissions
  version: number
  lastSynced: Date
}

export interface SyncStatus {
  status: 'connected' | 'connecting' | 'disconnected' | 'syncing' | 'conflict' | 'error'
  message?: string
  lastUpdate: Date
  operationsQueue: number
  retryCount?: number
  networkLatency?: number
}

export interface CollaborationPermissions {
  canEdit: boolean
  canAnnotate: boolean
  canComment: boolean
  canViewOthers: boolean
  canResolveConflicts: boolean
  canManageUsers: boolean
  canExport: boolean
}

export interface BrainViewState {
  viewMode: '3d' | 'axial' | 'coronal' | 'sagittal' | 'mosaic'
  coordinates: [number, number, number]
  threshold: number
  opacity: number
  colormap: string
  zoom: number
  rotation: [number, number, number]
  overlays: string[]
  annotations: BrainAnnotation[]
  measurements: BrainMeasurement[]
}

export interface BrainMeasurement {
  id: string
  userId: string
  type: 'distance' | 'angle' | 'volume' | 'surface_area'
  points: Array<{
    x: number
    y: number
    z: number
    mni: [number, number, number]
  }>
  value: number
  unit: string
  timestamp: Date
  visible: boolean
  color: string
}

export interface CollaborationEvent {
  type: 'user_joined' | 'user_left' | 'cursor_move' | 'operation' | 'conflict' | 'sync_status' | 'annotation' | 'view_change'
  userId?: string
  data: any
  timestamp: Date
  documentId: string
}

export interface ViewSyncOptions {
  syncCursor: boolean
  syncView: boolean
  syncAnnotations: boolean
  syncThreshold: boolean
  syncColormap: boolean
  followUser?: string
}

export interface CollaborationConfig {
  enableRealtime: boolean
  enableConflictResolution: boolean
  enableViewSync: boolean
  enableAnnotationSync: boolean
  conflictResolutionStrategy: 'automatic' | 'manual' | 'hybrid'
  maxRetries: number
  reconnectDelay: number
  operationBatchSize: number
  syncViewOptions: ViewSyncOptions
}

export interface WebSocketMessage {
  type: string
  data: any
  timestamp: Date
  userId?: string
  documentId?: string
}

export interface CollaborationWebSocketMessage extends WebSocketMessage {
  type: 'join' | 'leave' | 'operation' | 'cursor' | 'annotation' | 'conflict' | 'sync' | 'view_change' | 'heartbeat'
}

// Hook return types
export interface UseEnhancedCollaborationReturn {
  state: CollaborationState
  actions: {
    applyOperation: (operation: Operation) => Promise<void>
    createAnnotation: (annotation: Partial<Annotation>) => Promise<void>
    updateAnnotation: (id: string, updates: Partial<Annotation>) => Promise<void>
    deleteAnnotation: (id: string) => Promise<void>
    resolveConflict: (conflictId: string, resolution: ConflictResolution) => Promise<void>
    syncView: (viewState: Partial<BrainViewState>) => void
    followUser: (userId: string | null) => void
    setCursorPosition: (position: CursorPosition) => void
  }
  connectionStatus: SyncStatus
  permissions: CollaborationPermissions
}

export interface UseOperationalTransformReturn {
  transformOperation: (operation: Operation, againstOps: Operation[]) => Promise<TransformResult>
  applyOperation: (operation: Operation) => void
  getOperationHistory: () => Operation[]
  resolveConflicts: (conflicts: ConflictInfo[]) => Promise<ConflictResolution[]>
  clearPendingOperations: (operationIds: string[]) => void
  autoResolveConflict: (conflict: ConflictInfo) => Promise<ConflictResolution>
  getConflictById: (conflictId: string) => ConflictInfo | null
  getConflictsByType: (type: ConflictInfo['type']) => ConflictInfo[]
  getConflictsBySeverity: (severity: ConflictInfo['severity']) => ConflictInfo[]
  checkOperationsConflict: (op1: Operation, op2: Operation) => Promise<boolean>
  getTransformStats: () => {
    totalOperations: number
    remoteOperations: number
    pendingOperations: number
    activeConflicts: number
    localVersion: number
    remoteVersion: number
    isTransforming: boolean
  }
  compactHistory: () => void
  resetState: () => void
  // State properties
  isTransforming: boolean
  pendingOperations: Operation[]
  conflicts: ConflictInfo[]
}

export interface UseBrainAnnotationsReturn {
  annotations: BrainAnnotation[]
  measurements: BrainMeasurement[]
  actions: {
    addAnnotation: (annotation: Partial<BrainAnnotation>) => Promise<void>
    updateAnnotation: (id: string, updates: Partial<BrainAnnotation>) => Promise<void>
    deleteAnnotation: (id: string) => Promise<void>
    addMeasurement: (measurement: Partial<BrainMeasurement>) => Promise<void>
    updateMeasurement: (id: string, updates: Partial<BrainMeasurement>) => Promise<void>
    deleteMeasurement: (id: string) => Promise<void>
    toggleVisibility: (id: string, type: 'annotation' | 'measurement') => void
  }
  selectedAnnotation: BrainAnnotation | null
  setSelectedAnnotation: (annotation: BrainAnnotation | null) => void
  isLoading: boolean
}

// Event callbacks
export interface CollaborationEventHandlers {
  onUserJoin?: (user: User) => void
  onUserLeave?: (userId: string) => void
  onCursorMove?: (cursor: CursorPosition) => void
  onOperation?: (operation: Operation) => void
  onConflict?: (conflict: ConflictInfo) => void
  onAnnotation?: (annotation: Annotation, action: 'create' | 'update' | 'delete') => void
  onViewChange?: (viewState: Partial<BrainViewState>, userId: string) => void
  onSyncStatusChange?: (status: SyncStatus) => void
  onError?: (error: Error) => void
}
