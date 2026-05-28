import { useState, useCallback, useRef, useEffect } from 'react'
import { 
  Operation, 
  ConflictInfo, 
  ConflictResolution,
  TransformResult,
  UseOperationalTransformReturn
} from '@/types/collaboration-enhanced'
import { OperationalTransformClient } from '@/lib/operational-transform-client'

/**
 * Operational Transform hook for managing collaborative editing conflicts
 */
export function useOperationalTransform(
  documentId: string
): UseOperationalTransformReturn {
  // State
  const [isTransforming, setIsTransforming] = useState(false)
  const [pendingOperations, setPendingOperations] = useState<Operation[]>([])
  const [conflicts, setConflicts] = useState<ConflictInfo[]>([])
  
  // Refs
  const otClientRef = useRef<OperationalTransformClient>(new OperationalTransformClient())
  const mountedRef = useRef(true)

  /**
   * Cleanup on unmount
   */
  useEffect(() => {
    return () => {
      mountedRef.current = false
    }
  }, [])

  /**
   * Transform operation against other operations
   */
  const transformOperation = useCallback(async (
    operation: Operation, 
    againstOps: Operation[]
  ): Promise<TransformResult> => {
    if (!mountedRef.current) {
      throw new Error('Component unmounted')
    }

    setIsTransforming(true)
    
    try {
      const result = await otClientRef.current.transformOperation(operation, againstOps)
      
      // Update conflicts if any were detected
      if (result.conflicts && result.conflicts.length > 0) {
        setConflicts(prev => [...prev, ...result.conflicts!])
      }
      
      return result
    } catch (error) {
      console.error('Failed to transform operation:', error)
      throw error
    } finally {
      if (mountedRef.current) {
        setIsTransforming(false)
      }
    }
  }, [])

  /**
   * Apply operation to local state
   */
  const applyOperation = useCallback((operation: Operation) => {
    if (!mountedRef.current) return

    otClientRef.current.applyOperation(operation)
    
    // Add to pending operations if it's a local operation
    if (operation.userId === 'current-user') { // This would come from context
      setPendingOperations(prev => [...prev, operation])
    }
  }, [])

  /**
   * Get operation history
   */
  const getOperationHistory = useCallback((): Operation[] => {
    return otClientRef.current.getOperationHistory()
  }, [])

  /**
   * Resolve conflicts
   */
  const resolveConflicts = useCallback(async (
    conflictsToResolve: ConflictInfo[]
  ): Promise<ConflictResolution[]> => {
    if (!mountedRef.current) {
      throw new Error('Component unmounted')
    }

    try {
      const resolutions = await otClientRef.current.resolveConflicts(conflictsToResolve)
      
      // Remove resolved conflicts from state
      const resolvedIds = conflictsToResolve.map(c => c.id)
      setConflicts(prev => prev.filter(c => !resolvedIds.includes(c.id)))
      
      // Remove corresponding pending operations
      const resolvedOperationIds = conflictsToResolve
        .flatMap(c => c.operations)
        .map(op => op.id)
      
      setPendingOperations(prev => 
        prev.filter(op => !resolvedOperationIds.includes(op.id))
      )
      
      return resolutions
    } catch (error) {
      console.error('Failed to resolve conflicts:', error)
      throw error
    }
  }, [])

  /**
   * Clear pending operations (when acknowledged by server)
   */
  const clearPendingOperations = useCallback((operationIds: string[]) => {
    if (!mountedRef.current) return

    setPendingOperations(prev => prev.filter(op => !operationIds.includes(op.id)))
  }, [])

  /**
   * Auto-resolve conflict
   */
  const autoResolveConflict = useCallback(async (conflict: ConflictInfo) => {
    try {
      const resolutions = await resolveConflicts([conflict])
      return resolutions[0]
    } catch (error) {
      console.error('Failed to auto-resolve conflict:', error)
      throw error
    }
  }, [resolveConflicts])

  /**
   * Get conflict by ID
   */
  const getConflictById = useCallback((conflictId: string): ConflictInfo | null => {
    return conflicts.find(c => c.id === conflictId) || null
  }, [conflicts])

  /**
   * Get conflicts by type
   */
  const getConflictsByType = useCallback((type: ConflictInfo['type']): ConflictInfo[] => {
    return conflicts.filter(c => c.type === type)
  }, [conflicts])

  /**
   * Get conflicts by severity
   */
  const getConflictsBySeverity = useCallback((severity: ConflictInfo['severity']): ConflictInfo[] => {
    return conflicts.filter(c => c.severity === severity)
  }, [conflicts])

  /**
   * Check if operations conflict
   */
  const checkOperationsConflict = useCallback(async (
    op1: Operation, 
    op2: Operation
  ): Promise<boolean> => {
    try {
      const result = await otClientRef.current.transformOperation(op1, [op2])
      return result.conflicts ? result.conflicts.length > 0 : false
    } catch (error) {
      console.error('Failed to check operation conflict:', error)
      return false
    }
  }, [])

  /**
   * Get transform statistics
   */
  const getTransformStats = useCallback(() => {
    const totalOperations = otClientRef.current.getOperationHistory().length
    const remoteOperations = otClientRef.current.getRemoteOperationHistory().length
    const versions = otClientRef.current.getVersions()
    
    return {
      totalOperations,
      remoteOperations,
      pendingOperations: pendingOperations.length,
      activeConflicts: conflicts.length,
      localVersion: versions.local,
      remoteVersion: versions.remote,
      isTransforming
    }
  }, [pendingOperations.length, conflicts.length, isTransforming])

  /**
   * Compact operation history to free memory
   */
  const compactHistory = useCallback(() => {
    otClientRef.current.compactHistory()
  }, [])

  /**
   * Reset OT state
   */
  const resetState = useCallback(() => {
    if (!mountedRef.current) return

    otClientRef.current.reset()
    setPendingOperations([])
    setConflicts([])
    setIsTransforming(false)
  }, [])

  return {
    transformOperation,
    applyOperation,
    getOperationHistory,
    resolveConflicts,
    
    // Additional utilities
    clearPendingOperations,
    autoResolveConflict,
    getConflictById,
    getConflictsByType,
    getConflictsBySeverity,
    checkOperationsConflict,
    getTransformStats,
    compactHistory,
    resetState,
    
    // Current state
    isTransforming,
    pendingOperations,
    conflicts
  }
}
