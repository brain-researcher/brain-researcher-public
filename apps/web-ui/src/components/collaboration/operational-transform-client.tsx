'use client'

import React, { useState, useCallback } from 'react'
import { 
  Operation, 
  ConflictInfo, 
  ConflictResolution, 
  User,
  TransformResult 
} from '@/types/collaboration-enhanced'
import { 
  AlertTriangle, 
  Clock, 
  Users, 
  Merge, 
  ArrowRight,
  CheckCircle,
  XCircle,
  Info,
  RefreshCw
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { useOperationalTransform } from '@/hooks/use-operational-transform'

interface OperationalTransformClientProps {
  documentId: string
  currentUser: User
  onConflictResolved?: (conflictId: string, resolution: ConflictResolution) => void
  className?: string
}

export function OperationalTransformClient({
  documentId,
  currentUser,
  onConflictResolved,
  className = ''
}: OperationalTransformClientProps) {
  const {
    transformOperation,
    applyOperation,
    getOperationHistory,
    resolveConflicts
  } = useOperationalTransform(documentId)

  const [pendingOperations, setPendingOperations] = useState<Operation[]>([])
  const [conflicts, setConflicts] = useState<ConflictInfo[]>([])
  const [isTransforming, setIsTransforming] = useState(false)
  const [transformStats, setTransformStats] = useState({
    totalOperations: 0,
    conflictsResolved: 0,
    autoResolved: 0
  })

  /**
   * Process a new operation through the OT system
   */
  const processOperation = useCallback(async (operation: Operation) => {
    setIsTransforming(true)
    
    try {
      const history = getOperationHistory()
      const relevantOps = history.slice(-50) // Last 50 operations for context
      
      const result = await transformOperation(operation, relevantOps)
      
      if (result.conflicts && result.conflicts.length > 0) {
        setConflicts(prev => [...prev, ...result.conflicts!])
      }
      
      // Apply transformed operations
      result.transformed.forEach(transformedOp => {
        applyOperation(transformedOp)
      })
      
      setPendingOperations(prev => prev.filter(op => op.id !== operation.id))
      
      setTransformStats(prev => ({
        ...prev,
        totalOperations: prev.totalOperations + 1
      }))
      
    } catch (error) {
      console.error('Failed to process operation:', error)
    } finally {
      setIsTransforming(false)
    }
  }, [transformOperation, getOperationHistory, applyOperation])

  /**
   * Resolve a conflict
   */
  const handleResolveConflict = useCallback(async (
    conflictId: string, 
    resolution: ConflictResolution
  ) => {
    try {
      const conflict = conflicts.find(c => c.id === conflictId)
      if (!conflict) return

      const resolutions = await resolveConflicts([conflict])
      const resolvedConflict = resolutions[0]
      
      if (resolvedConflict) {
        setConflicts(prev => prev.filter(c => c.id !== conflictId))
        setTransformStats(prev => ({
          ...prev,
          conflictsResolved: prev.conflictsResolved + 1,
          autoResolved: resolution.strategy === 'timestamp' ? prev.autoResolved + 1 : prev.autoResolved
        }))
        
        onConflictResolved?.(conflictId, resolvedConflict)
      }
    } catch (error) {
      console.error('Failed to resolve conflict:', error)
    }
  }, [conflicts, resolveConflicts, onConflictResolved])

  /**
   * Auto-resolve all conflicts
   */
  const autoResolveAll = useCallback(async () => {
    try {
      const resolutions = await resolveConflicts(conflicts)
      
      resolutions.forEach((resolution, index) => {
        const conflict = conflicts[index]
        if (conflict) {
          handleResolveConflict(conflict.id, resolution)
        }
      })
    } catch (error) {
      console.error('Failed to auto-resolve conflicts:', error)
    }
  }, [conflicts, resolveConflicts, handleResolveConflict])

  /**
   * Get conflict severity color
   */
  const getConflictColor = (severity: 'low' | 'medium' | 'high') => {
    switch (severity) {
      case 'high': return 'bg-red-100 border-red-300 text-red-800'
      case 'medium': return 'bg-yellow-100 border-yellow-300 text-yellow-800'
      case 'low': return 'bg-blue-100 border-blue-300 text-blue-800'
      default: return 'bg-gray-100 border-gray-300 text-gray-800'
    }
  }

  /**
   * Get operation type icon
   */
  const getOperationIcon = (type: string) => {
    switch (type) {
      case 'view_change': return <RefreshCw className="w-4 h-4" />
      case 'annotate': return <Info className="w-4 h-4" />
      case 'insert': return <ArrowRight className="w-4 h-4" />
      case 'delete': return <XCircle className="w-4 h-4" />
      default: return <CheckCircle className="w-4 h-4" />
    }
  }

  /**
   * Format operation description
   */
  const formatOperationDescription = (operation: Operation) => {
    switch (operation.type) {
      case 'view_change':
        return `Changed view to ${(operation as any).data?.viewMode || 'unknown'}`
      case 'annotate':
        const action = (operation as any).data?.action
        return `${action === 'create' ? 'Added' : action === 'update' ? 'Updated' : 'Deleted'} annotation`
      case 'insert':
        return 'Inserted content'
      case 'delete':
        return 'Deleted content'
      default:
        return `Performed ${operation.type} operation`
    }
  }

  // Conflicts are reported by the OT hook; no dev-only injected demo users.

  return (
    <div className={`space-y-4 ${className}`}>
      {/* Transform Stats */}
      <Card className="p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold">Operational Transform Status</h3>
          <Badge variant={isTransforming ? "default" : "secondary"}>
            {isTransforming ? 'Processing' : 'Ready'}
          </Badge>
        </div>
        
        <div className="grid grid-cols-3 gap-4">
          <div className="text-center">
            <div className="text-2xl font-bold text-blue-600">{transformStats.totalOperations}</div>
            <div className="text-sm text-gray-600">Operations Processed</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-green-600">{transformStats.conflictsResolved}</div>
            <div className="text-sm text-gray-600">Conflicts Resolved</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-orange-600">{transformStats.autoResolved}</div>
            <div className="text-sm text-gray-600">Auto-resolved</div>
          </div>
        </div>
      </Card>

      {/* Active Conflicts */}
      {conflicts.length > 0 && (
        <Card className="p-4">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-orange-600 flex items-center">
              <AlertTriangle className="w-5 h-5 mr-2" />
              Active Conflicts ({conflicts.length})
            </h3>
            
            <div className="space-x-2">
              <Button
                size="sm"
                onClick={autoResolveAll}
                disabled={conflicts.length === 0}
              >
                Auto-resolve All
              </Button>
            </div>
          </div>

          <div className="space-y-3">
            {conflicts.map(conflict => (
              <div
                key={conflict.id}
                className={`p-4 rounded-lg border-2 ${getConflictColor(conflict.severity)}`}
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center space-x-2">
                    <Badge variant="secondary">{conflict.type.replace('_', ' ')}</Badge>
                    <Badge variant={conflict.severity === 'high' ? 'destructive' : 'secondary'}>
                      {conflict.severity}
                    </Badge>
                  </div>
                  
                  <div className="flex items-center space-x-1 text-sm text-gray-600">
                    <Clock className="w-4 h-4" />
                    <span>{new Date(conflict.timestamp).toLocaleTimeString()}</span>
                  </div>
                </div>

                <div className="mb-3">
                  <div className="flex items-center space-x-1 mb-2">
                    <Users className="w-4 h-4" />
                    <span className="text-sm font-medium">Involved Users:</span>
                  </div>
                  <div className="flex space-x-2">
                    {conflict.users.map(user => (
                      <div
                        key={user.id}
                        className="flex items-center space-x-1 text-xs"
                      >
                        <div
                          className="w-3 h-3 rounded-full"
                          style={{ backgroundColor: user.color }}
                        />
                        <span>{user.name}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="mb-4">
                  <div className="text-sm font-medium mb-2">Conflicting Operations:</div>
                  <div className="space-y-2">
                    {conflict.operations.map((operation, index) => (
                      <div key={operation.id} className="flex items-center space-x-2 text-sm">
                        {getOperationIcon(operation.type)}
                        <span>{formatOperationDescription(operation)}</span>
                        <Badge variant="outline">
                          {conflict.users.find(u => u.id === operation.userId)?.name || 'Unknown'}
                        </Badge>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="flex space-x-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => handleResolveConflict(conflict.id, {
                      strategy: 'timestamp',
                      timestamp: new Date()
                    })}
                  >
                    Use Latest
                  </Button>
                  
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => handleResolveConflict(conflict.id, {
                      strategy: 'merge',
                      timestamp: new Date()
                    })}
                  >
                    <Merge className="w-4 h-4 mr-1" />
                    Merge
                  </Button>
                  
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => handleResolveConflict(conflict.id, {
                      strategy: 'user_priority',
                      selectedOperation: conflict.operations[0].id,
                      timestamp: new Date()
                    })}
                  >
                    Use First
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Pending Operations */}
      {pendingOperations.length > 0 && (
        <Card className="p-4">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold">Pending Operations ({pendingOperations.length})</h3>
            <Badge variant="secondary">Processing Queue</Badge>
          </div>

          <div className="space-y-2">
            {pendingOperations.map(operation => (
              <div key={operation.id} className="flex items-center justify-between p-2 bg-gray-50 rounded">
                <div className="flex items-center space-x-2">
                  {getOperationIcon(operation.type)}
                  <span className="text-sm">{formatOperationDescription(operation)}</span>
                </div>
                <Badge variant="outline" className="text-xs">
                  {new Date(operation.timestamp).toLocaleTimeString()}
                </Badge>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* No Issues */}
      {conflicts.length === 0 && pendingOperations.length === 0 && !isTransforming && (
        <Card className="p-6 text-center">
          <CheckCircle className="w-12 h-12 text-green-500 mx-auto mb-3" />
          <h3 className="text-lg font-medium text-green-700 mb-2">All Clear</h3>
          <p className="text-gray-600">
            No conflicts detected. All operations are synchronized.
          </p>
        </Card>
      )}
    </div>
  )
}
