'use client'

import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { Brain3D } from '@/components/brain/Brain3D'
import { 
  User, 
  BrainAnnotation, 
  BrainViewState, 
  CursorPosition,
  BrainMeasurement,
  CollaborationPermissions 
} from '@/types/collaboration-enhanced'
import {
  Users,
  Eye,
  EyeOff,
  MousePointer,
  Ruler,
  MessageCircle,
  Settings,
  Share2,
  Lock,
  Unlock,
  RefreshCw
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Slider } from '@/components/ui/slider'
import { Badge } from '@/components/ui/badge'
import { useEnhancedCollaboration } from '@/hooks/use-enhanced-collaboration'
import { useBrainAnnotations } from '@/hooks/use-brain-annotations'
import { resolveKgVizUrl } from '@/lib/service-endpoints'

interface CollaborativeBrainViewerProps {
  jobId?: string
  documentId: string
  currentUser: User
  initialViewState?: Partial<BrainViewState>
  permissions?: CollaborationPermissions
  onViewChange?: (viewState: BrainViewState) => void
  onAnnotationCreate?: (annotation: BrainAnnotation) => void
  className?: string
}

export function CollaborativeBrainViewer({
  jobId,
  documentId,
  currentUser,
  initialViewState,
  permissions,
  onViewChange,
  onAnnotationCreate,
  className = ''
}: CollaborativeBrainViewerProps) {
  const effectiveJobId = jobId || documentId
  // Collaboration state
  const {
    state: collaborationState,
    actions: collaborationActions,
    connectionStatus
  } = useEnhancedCollaboration(documentId, currentUser)

  // Brain annotations
  const {
    annotations,
    measurements,
    actions: annotationActions,
    selectedAnnotation,
    setSelectedAnnotation
  } = useBrainAnnotations(documentId)

  // Local state
  const [viewState, setViewState] = useState<BrainViewState>({
    viewMode: '3d',
    coordinates: [0, 0, 0],
    threshold: 2.3,
    opacity: 1.0,
    colormap: 'hot',
    zoom: 1.0,
    rotation: [0, 0, 0],
    overlays: [],
    annotations: [],
    measurements: [],
    ...initialViewState
  })

  const [showCursors, setShowCursors] = useState(true)
  const [showAnnotations, setShowAnnotations] = useState(true)
  const [showMeasurements, setShowMeasurements] = useState(true)
  const [followingUser, setFollowingUser] = useState<string | null>(null)
  const [annotationMode, setAnnotationMode] = useState(false)
  const [measurementMode, setMeasurementMode] = useState(false)
  const [isViewLocked, setIsViewLocked] = useState(false)

  // Refs
  const viewerRef = useRef<HTMLDivElement>(null)
  const cursorUpdateTimeoutRef = useRef<NodeJS.Timeout>()
  const viewSyncTimeoutRef = useRef<NodeJS.Timeout>()

  // Computed values
  const activeUsers = collaborationState.activeUsers
  const otherUsers = activeUsers.filter(user => user.id !== currentUser.id)
  const userCursors = useMemo(() => {
    return otherUsers
      .filter(user => user.cursor && showCursors)
      .map(user => ({ ...user.cursor!, user }))
  }, [otherUsers, showCursors])

  /**
   * Handle view state changes
   */
  const handleViewChange = useCallback((newViewState: Partial<BrainViewState>) => {
    if (isViewLocked) return

    const updatedViewState = { ...viewState, ...newViewState }
    setViewState(updatedViewState)
    onViewChange?.(updatedViewState)

    // Debounce view sync to avoid too many updates
    if (viewSyncTimeoutRef.current) {
      clearTimeout(viewSyncTimeoutRef.current)
    }

    viewSyncTimeoutRef.current = setTimeout(() => {
      collaborationActions.syncView(newViewState)
    }, 300)
  }, [viewState, collaborationActions, onViewChange, isViewLocked])

  /**
   * Handle mouse movement for cursor tracking
   */
  const handleMouseMove = useCallback((event: React.MouseEvent) => {
    if (!viewerRef.current || !permissions?.canViewOthers) return

    const rect = viewerRef.current.getBoundingClientRect()
    const x = event.clientX - rect.left
    const y = event.clientY - rect.top

    // Debounce cursor updates
    if (cursorUpdateTimeoutRef.current) {
      clearTimeout(cursorUpdateTimeoutRef.current)
    }

    cursorUpdateTimeoutRef.current = setTimeout(() => {
      const cursor: CursorPosition = {
        userId: currentUser.id,
        x,
        y,
        timestamp: Date.now(),
        viewType: 'brain',
        elementId: effectiveJobId
      }

      collaborationActions.setCursorPosition(cursor)
    }, 50)
  }, [currentUser.id, permissions, effectiveJobId, collaborationActions])

  /**
   * Handle click for annotations
   */
  const handleViewerClick = useCallback(async (event: React.MouseEvent) => {
    if (!annotationMode || !permissions?.canAnnotate) return

    const rect = viewerRef.current?.getBoundingClientRect()
    if (!rect) return

    const x = event.clientX - rect.left
    const y = event.clientY - rect.top

    // Create new annotation
    const annotation: Partial<BrainAnnotation> = {
      type: 'point',
      position: { x, y },
      coordinates: {
        mni: viewState.coordinates,
        voxel: viewState.coordinates // Would need proper coordinate conversion
      },
      content: '',
      anatomicalRegion: 'Unknown', // Would need proper region detection
      sliceType: viewState.viewMode === '3d' ? undefined : viewState.viewMode as any,
      volume: effectiveJobId
    }

    try {
      await annotationActions.addAnnotation(annotation)
      onAnnotationCreate?.(annotation as BrainAnnotation)
      setAnnotationMode(false) // Exit annotation mode after creating
    } catch (error) {
      console.error('Failed to create annotation:', error)
    }
  }, [annotationMode, permissions, viewState, effectiveJobId, annotationActions, onAnnotationCreate])

  /**
   * Follow another user's view
   */
  const followUser = useCallback((userId: string | null) => {
    setFollowingUser(userId)
    collaborationActions.followUser(userId)

    if (userId) {
      const user = activeUsers.find(u => u.id === userId)
      if (user?.cursor) {
        // Sync to their view state if available
        // This would need to be implemented in the collaboration system
      }
    }
  }, [activeUsers, collaborationActions])

  /**
   * Handle remote view changes from other users
   */
  useEffect(() => {
    const handleRemoteViewChange = (remoteViewState: Partial<BrainViewState>, userId: string) => {
      if (followingUser === userId) {
        setViewState(prevState => ({ ...prevState, ...remoteViewState }))
      }
    }

    // This would be connected through the collaboration system
    // collaborationActions.onViewChange(handleRemoteViewChange)
  }, [followingUser])

  /**
   * Sync annotations with collaboration system
   */
  useEffect(() => {
    const updatedViewState = {
      ...viewState,
      annotations,
      measurements
    }
    setViewState(updatedViewState)
  }, [annotations, measurements])

  /**
   * Brain3D configuration with collaboration features
   */
  const brainConfig = useMemo(() => ({
    baseVolume: resolveKgVizUrl('/volume', new URLSearchParams({ job_id: effectiveJobId })),
    overlays: viewState.overlays.map(overlay => ({
      url: resolveKgVizUrl(
        '/overlay',
        new URLSearchParams({ job_id: effectiveJobId, overlay }),
      ),
      colormap: viewState.colormap,
      threshold: viewState.threshold,
      opacity: viewState.opacity
    })),
    export: { enableSnapshot: true },
    interaction: { 
      allowPick: true, 
      allowSlice: true,
      allowDrag: !isViewLocked 
    },
    metadata: {
      subject: 'collaborative',
      session: documentId,
      task: 'collaboration',
      dataset: jobId
    }
  }), [effectiveJobId, viewState, isViewLocked, documentId])

  // User presence indicator
  const UserPresence = () => (
    <div className="flex items-center space-x-3 p-3 bg-white/90 backdrop-blur rounded-lg shadow-sm">
      <div className="flex items-center space-x-2">
        <Users className="w-4 h-4 text-gray-600" />
        <span className="text-sm font-medium">
          {activeUsers.length} user{activeUsers.length !== 1 ? 's' : ''}
        </span>
      </div>
      
      <div className="flex -space-x-2">
        {activeUsers.slice(0, 5).map(user => (
          <div
            key={user.id}
            className="relative group cursor-pointer"
            onClick={() => followUser(followingUser === user.id ? null : user.id)}
          >
            <div
              className={`w-8 h-8 rounded-full border-2 flex items-center justify-center text-xs font-medium text-white ${
                followingUser === user.id ? 'border-blue-500 ring-2 ring-blue-200' : 'border-white'
              }`}
              style={{ backgroundColor: user.color }}
              title={`${user.name} (${user.status})`}
            >
              {user.avatar ? (
                <img src={user.avatar} alt={user.name} className="w-full h-full rounded-full" />
              ) : (
                user.name.split(' ').map(n => n[0]).join('')
              )}
            </div>
            
            {/* Status indicator */}
            <div className={`absolute bottom-0 right-0 w-2.5 h-2.5 rounded-full border-2 border-white ${
              user.status === 'online' ? 'bg-green-500' :
              user.status === 'idle' ? 'bg-yellow-500' :
              'bg-gray-400'
            }`} />
            
            {/* Tooltip */}
            <div className="absolute bottom-full mb-2 left-1/2 transform -translate-x-1/2 px-2 py-1 bg-black text-white text-xs rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap z-50">
              {user.name}
              {followingUser === user.id && ' (Following)'}
            </div>
          </div>
        ))}
        
        {activeUsers.length > 5 && (
          <div className="w-8 h-8 rounded-full bg-gray-200 border-2 border-white flex items-center justify-center text-xs font-medium">
            +{activeUsers.length - 5}
          </div>
        )}
      </div>
    </div>
  )

  // Collaboration controls
  const CollaborationControls = () => (
    <div className="flex items-center space-x-2 p-3 bg-white/90 backdrop-blur rounded-lg shadow-sm">
      <Button
        size="sm"
        variant={showCursors ? "default" : "outline"}
        onClick={() => setShowCursors(!showCursors)}
      >
        <MousePointer className="w-4 h-4 mr-1" />
        Cursors
      </Button>
      
      <Button
        size="sm"
        variant={showAnnotations ? "default" : "outline"}
        onClick={() => setShowAnnotations(!showAnnotations)}
      >
        <MessageCircle className="w-4 h-4 mr-1" />
        Annotations ({annotations.length})
      </Button>
      
      <Button
        size="sm"
        variant={showMeasurements ? "default" : "outline"}
        onClick={() => setShowMeasurements(!showMeasurements)}
      >
        <Ruler className="w-4 h-4 mr-1" />
        Measurements ({measurements.length})
      </Button>
      
      <div className="w-px h-6 bg-gray-300" />
      
      <Button
        size="sm"
        variant={annotationMode ? "default" : "outline"}
        onClick={() => setAnnotationMode(!annotationMode)}
        disabled={!permissions?.canAnnotate}
      >
        <MessageCircle className="w-4 h-4 mr-1" />
        Annotate
      </Button>
      
      <Button
        size="sm"
        variant={measurementMode ? "default" : "outline"}
        onClick={() => setMeasurementMode(!measurementMode)}
        disabled={!permissions?.canAnnotate}
      >
        <Ruler className="w-4 h-4 mr-1" />
        Measure
      </Button>
      
      <Button
        size="sm"
        variant={isViewLocked ? "default" : "outline"}
        onClick={() => setIsViewLocked(!isViewLocked)}
      >
        {isViewLocked ? <Lock className="w-4 h-4" /> : <Unlock className="w-4 h-4" />}
      </Button>
    </div>
  )

  // View sync controls
  const ViewSyncControls = () => (
    <div className="space-y-3 p-3 bg-white/90 backdrop-blur rounded-lg shadow-sm">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">Threshold</span>
        <div className="flex items-center space-x-2">
          <Slider
            value={[viewState.threshold]}
            onValueChange={(value) => handleViewChange({ threshold: value[0] })}
            min={0}
            max={10}
            step={0.1}
            className="w-24"
            disabled={isViewLocked}
          />
          <span className="text-xs font-mono w-8">{viewState.threshold.toFixed(1)}</span>
        </div>
      </div>
      
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">Opacity</span>
        <div className="flex items-center space-x-2">
          <Slider
            value={[viewState.opacity]}
            onValueChange={(value) => handleViewChange({ opacity: value[0] })}
            min={0}
            max={1}
            step={0.1}
            className="w-24"
            disabled={isViewLocked}
          />
          <span className="text-xs font-mono w-8">{(viewState.opacity * 100).toFixed(0)}%</span>
        </div>
      </div>
    </div>
  )

  // Collaborative cursors overlay
  const CollaborativeCursors = () => (
    <>
      {userCursors.map(({ user, ...cursor }) => (
        <div
          key={cursor.userId}
          className="absolute pointer-events-none z-50 transition-all duration-75"
          style={{
            left: cursor.x,
            top: cursor.y,
            transform: 'translate(-50%, -50%)'
          }}
        >
          <div
            className="w-4 h-4 rounded-full border-2 border-white shadow-lg"
            style={{ backgroundColor: user.color }}
          />
          <div
            className="absolute top-4 left-0 px-2 py-1 rounded text-xs text-white whitespace-nowrap shadow-lg"
            style={{ backgroundColor: user.color }}
          >
            {user.name}
          </div>
        </div>
      ))}
    </>
  )

  // Annotations overlay
  const AnnotationsOverlay = () => (
    <>
      {annotations
        .filter(annotation => annotation.visible && showAnnotations)
        .map(annotation => (
          <div
            key={annotation.id}
            className={`absolute z-40 cursor-pointer transition-all ${
              selectedAnnotation?.id === annotation.id ? 'scale-110' : 'hover:scale-105'
            }`}
            style={{
              left: annotation.position.x,
              top: annotation.position.y,
              transform: 'translate(-50%, -50%)'
            }}
            onClick={() => setSelectedAnnotation(
              selectedAnnotation?.id === annotation.id ? null : annotation
            )}
          >
            <div
              className="w-3 h-3 rounded-full border-2 border-white shadow-lg"
              style={{ backgroundColor: annotation.userColor }}
            />
            {annotation.content && (
              <div className="absolute top-4 left-0 px-2 py-1 bg-black/80 text-white text-xs rounded whitespace-nowrap max-w-48 truncate">
                {annotation.content}
              </div>
            )}
          </div>
        ))}
    </>
  )

  // Connection status indicator
  const ConnectionStatus = () => (
    <div className="flex items-center space-x-2 p-2 bg-white/90 backdrop-blur rounded-lg shadow-sm">
      <div className={`w-2 h-2 rounded-full ${
        connectionStatus.status === 'connected' ? 'bg-green-500' :
        connectionStatus.status === 'connecting' || connectionStatus.status === 'syncing' ? 'bg-yellow-500 animate-pulse' :
        connectionStatus.status === 'conflict' ? 'bg-orange-500' :
        'bg-red-500'
      }`} />
      <span className="text-xs text-gray-600">
        {connectionStatus.message || connectionStatus.status}
      </span>
      {connectionStatus.operationsQueue > 0 && (
        <Badge variant="secondary" className="text-xs">
          {connectionStatus.operationsQueue} queued
        </Badge>
      )}
    </div>
  )

  return (
    <div className={`relative bg-black rounded-lg overflow-hidden ${className}`}>
      {/* Main viewer */}
      <div
        ref={viewerRef}
        className="relative"
        onMouseMove={handleMouseMove}
        onClick={handleViewerClick}
        style={{ cursor: annotationMode ? 'crosshair' : measurementMode ? 'copy' : 'default' }}
      >
        <Brain3D
          jobId={jobId}
          config={brainConfig}
          height="600px"
        />
        
        {/* Collaborative overlays */}
        <CollaborativeCursors />
        <AnnotationsOverlay />
      </div>

      {/* Control overlays */}
      <div className="absolute top-4 left-4 space-y-3">
        <UserPresence />
        <CollaborationControls />
        <ViewSyncControls />
      </div>

      <div className="absolute top-4 right-4">
        <ConnectionStatus />
      </div>

      {/* Following indicator */}
      {followingUser && (
        <div className="absolute bottom-4 left-1/2 transform -translate-x-1/2 px-4 py-2 bg-blue-500 text-white rounded-lg shadow-lg">
          <div className="flex items-center space-x-2">
            <Eye className="w-4 h-4" />
            <span className="text-sm">
              Following {activeUsers.find(u => u.id === followingUser)?.name}
            </span>
            <button
              onClick={() => followUser(null)}
              className="ml-2 text-blue-100 hover:text-white"
            >
              <EyeOff className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* Mode indicators */}
      {annotationMode && (
        <div className="absolute bottom-4 right-4 px-4 py-2 bg-green-500 text-white rounded-lg shadow-lg">
          <div className="flex items-center space-x-2">
            <MessageCircle className="w-4 h-4" />
            <span className="text-sm">Click to add annotation</span>
            <button
              onClick={() => setAnnotationMode(false)}
              className="ml-2 text-green-100 hover:text-white"
            >
              ×
            </button>
          </div>
        </div>
      )}

      {measurementMode && (
        <div className="absolute bottom-4 right-4 px-4 py-2 bg-purple-500 text-white rounded-lg shadow-lg">
          <div className="flex items-center space-x-2">
            <Ruler className="w-4 h-4" />
            <span className="text-sm">Click to start measuring</span>
            <button
              onClick={() => setMeasurementMode(false)}
              className="ml-2 text-purple-100 hover:text-white"
            >
              ×
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
