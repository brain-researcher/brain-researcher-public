import { useState, useEffect, useCallback, useRef } from 'react'
import { 
  CollaborationState,
  UseEnhancedCollaborationReturn,
  Operation,
  User,
  Annotation,
  ConflictInfo,
  ConflictResolution,
  BrainViewState,
  CursorPosition,
  SyncStatus,
  CollaborationPermissions,
  CollaborationConfig,
  CollaborationEventHandlers
} from '@/types/collaboration-enhanced'
import { CollaborationClient } from '@/lib/collaboration-client'

/**
 * Enhanced collaboration hook providing real-time collaboration features
 */
export function useEnhancedCollaboration(
  documentId: string,
  currentUser: User,
  config: Partial<CollaborationConfig> = {},
  eventHandlers: CollaborationEventHandlers = {}
): UseEnhancedCollaborationReturn {
  // State
  const [collaborationState, setCollaborationState] = useState<CollaborationState>({
    documentId,
    activeUsers: [currentUser],
    annotations: [],
    operations: [],
    conflicts: [],
    syncStatus: {
      status: 'disconnected',
      lastUpdate: new Date(),
      operationsQueue: 0
    },
    permissions: {
      canEdit: currentUser.role !== 'viewer',
      canAnnotate: true,
      canComment: true,
      canViewOthers: true,
      canResolveConflicts: currentUser.role === 'owner',
      canManageUsers: currentUser.role === 'owner',
      canExport: currentUser.role !== 'viewer'
    },
    version: 0,
    lastSynced: new Date()
  })

  // Refs
  const collaborationClientRef = useRef<CollaborationClient | null>(null)
  const mountedRef = useRef(true)

  /**
   * Initialize collaboration client
   */
  useEffect(() => {
    if (!collaborationClientRef.current) {
      const clientEventHandlers: CollaborationEventHandlers = {
        onUserJoin: (user: User) => {
          if (!mountedRef.current) return
          setCollaborationState(prev => ({
            ...prev,
            activeUsers: prev.activeUsers.find(u => u.id === user.id) 
              ? prev.activeUsers 
              : [...prev.activeUsers, user]
          }))
          eventHandlers.onUserJoin?.(user)
        },

        onUserLeave: (userId: string) => {
          if (!mountedRef.current) return
          setCollaborationState(prev => ({
            ...prev,
            activeUsers: prev.activeUsers.filter(u => u.id !== userId)
          }))
          eventHandlers.onUserLeave?.(userId)
        },

        onCursorMove: (cursor: CursorPosition) => {
          if (!mountedRef.current) return
          setCollaborationState(prev => ({
            ...prev,
            activeUsers: prev.activeUsers.map(user => 
              user.id === cursor.userId 
                ? { ...user, cursor }
                : user
            )
          }))
          eventHandlers.onCursorMove?.(cursor)
        },

        onOperation: (operation: Operation) => {
          if (!mountedRef.current) return
          setCollaborationState(prev => ({
            ...prev,
            operations: [...prev.operations, operation],
            version: prev.version + 1
          }))
          eventHandlers.onOperation?.(operation)
        },

        onConflict: (conflict: ConflictInfo) => {
          if (!mountedRef.current) return
          setCollaborationState(prev => ({
            ...prev,
            conflicts: [...prev.conflicts, conflict]
          }))
          eventHandlers.onConflict?.(conflict)
        },

        onAnnotation: (annotation: Annotation, action: 'create' | 'update' | 'delete') => {
          if (!mountedRef.current) return
          setCollaborationState(prev => {
            let annotations = [...prev.annotations]
            
            switch (action) {
              case 'create':
                annotations = [...annotations, annotation]
                break
              case 'update':
                const updateIndex = annotations.findIndex(a => a.id === annotation.id)
                if (updateIndex !== -1) {
                  annotations[updateIndex] = { ...annotations[updateIndex], ...annotation }
                }
                break
              case 'delete':
                annotations = annotations.filter(a => a.id !== annotation.id)
                break
            }
            
            return { ...prev, annotations }
          })
          eventHandlers.onAnnotation?.(annotation, action)
        },

        onViewChange: (viewState: Partial<BrainViewState>, userId: string) => {
          eventHandlers.onViewChange?.(viewState, userId)
        },

        onSyncStatusChange: (syncStatus: SyncStatus) => {
          if (!mountedRef.current) return
          setCollaborationState(prev => ({
            ...prev,
            syncStatus
          }))
          eventHandlers.onSyncStatusChange?.(syncStatus)
        },

        onError: (error: Error) => {
          console.error('Collaboration error:', error)
          eventHandlers.onError?.(error)
        }
      }

      collaborationClientRef.current = new CollaborationClient(
        documentId,
        currentUser,
        config,
        clientEventHandlers
      )
    }

    return () => {
      mountedRef.current = false
    }
  }, [documentId, currentUser, config, eventHandlers])

  /**
   * Cleanup on unmount
   */
  useEffect(() => {
    return () => {
      collaborationClientRef.current?.destroy()
      mountedRef.current = false
    }
  }, [])

  /**
   * Apply operation
   */
  const applyOperation = useCallback(async (operation: Operation) => {
    if (!collaborationClientRef.current) {
      throw new Error('Collaboration client not initialized')
    }

    try {
      await collaborationClientRef.current.applyOperation(operation)
    } catch (error) {
      console.error('Failed to apply operation:', error)
      throw error
    }
  }, [])

  /**
   * Create annotation
   */
  const createAnnotation = useCallback(async (annotation: Partial<Annotation>) => {
    if (!collaborationClientRef.current) {
      throw new Error('Collaboration client not initialized')
    }

    try {
      await collaborationClientRef.current.createAnnotation(annotation)
    } catch (error) {
      console.error('Failed to create annotation:', error)
      throw error
    }
  }, [])

  /**
   * Update annotation
   */
  const updateAnnotation = useCallback(async (id: string, updates: Partial<Annotation>) => {
    if (!collaborationClientRef.current) {
      throw new Error('Collaboration client not initialized')
    }

    try {
      await collaborationClientRef.current.updateAnnotation(id, updates)
    } catch (error) {
      console.error('Failed to update annotation:', error)
      throw error
    }
  }, [])

  /**
   * Delete annotation
   */
  const deleteAnnotation = useCallback(async (id: string) => {
    if (!collaborationClientRef.current) {
      throw new Error('Collaboration client not initialized')
    }

    try {
      await collaborationClientRef.current.deleteAnnotation(id)
    } catch (error) {
      console.error('Failed to delete annotation:', error)
      throw error
    }
  }, [])

  /**
   * Resolve conflict
   */
  const resolveConflict = useCallback(async (conflictId: string, resolution: ConflictResolution) => {
    if (!collaborationClientRef.current) {
      throw new Error('Collaboration client not initialized')
    }

    try {
      await collaborationClientRef.current.resolveConflict(conflictId, resolution)
      
      // Update local state
      setCollaborationState(prev => ({
        ...prev,
        conflicts: prev.conflicts.filter(c => c.id !== conflictId)
      }))
    } catch (error) {
      console.error('Failed to resolve conflict:', error)
      throw error
    }
  }, [])

  /**
   * Sync view state
   */
  const syncView = useCallback((viewState: Partial<BrainViewState>) => {
    if (!collaborationClientRef.current) {
      console.warn('Collaboration client not initialized')
      return
    }

    collaborationClientRef.current.syncView(viewState)
  }, [])

  /**
   * Follow user
   */
  const followUser = useCallback((userId: string | null) => {
    // This would be implemented in the collaboration client
    console.log('Following user:', userId)
  }, [])

  /**
   * Set cursor position
   */
  const setCursorPosition = useCallback((position: CursorPosition) => {
    if (!collaborationClientRef.current) {
      console.warn('Collaboration client not initialized')
      return
    }

    collaborationClientRef.current.setCursorPosition(position)
  }, [])

  /**
   * Get connection status
   */
  const connectionStatus = collaborationState.syncStatus

  /**
   * Get permissions
   */
  const permissions = collaborationState.permissions

  /**
   * Actions object
   */
  const actions = {
    applyOperation,
    createAnnotation,
    updateAnnotation,
    deleteAnnotation,
    resolveConflict,
    syncView,
    followUser,
    setCursorPosition
  }

  return {
    state: collaborationState,
    actions,
    connectionStatus,
    permissions
  }
}