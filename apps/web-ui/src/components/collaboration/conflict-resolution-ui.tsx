'use client'

import React, { useState, useCallback, useEffect } from 'react'
import { 
  ConflictInfo, 
  ConflictResolution, 
  Operation, 
  User, 
  BrainViewOperation,
  AnnotationOperation 
} from '@/types/collaboration-enhanced'
import { 
  AlertTriangle, 
  Users, 
  Clock, 
  ArrowRight, 
  Merge, 
  User as UserIcon,
  Zap,
  CheckCircle,
  XCircle,
  Eye,
  MessageCircle,
  RotateCw,
  ThumbsUp,
  ThumbsDown
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'

interface ConflictResolutionUIProps {
  conflicts: ConflictInfo[]
  currentUser: User
  onResolveConflict: (conflictId: string, resolution: ConflictResolution) => Promise<void>
  onDismissConflict?: (conflictId: string) => void
  className?: string
}

export function ConflictResolutionUI({
  conflicts,
  currentUser,
  onResolveConflict,
  onDismissConflict,
  className = ''
}: ConflictResolutionUIProps) {
  const [selectedConflict, setSelectedConflict] = useState<ConflictInfo | null>(null)
  const [isResolving, setIsResolving] = useState(false)
  const [resolutionPreview, setResolutionPreview] = useState<any>(null)
  const [autoResolveEnabled, setAutoResolveEnabled] = useState(true)

  /**
   * Handle conflict resolution
   */
  const handleResolve = useCallback(async (
    conflict: ConflictInfo, 
    resolution: ConflictResolution
  ) => {
    setIsResolving(true)
    
    try {
      await onResolveConflict(conflict.id, resolution)
      setSelectedConflict(null)
      setResolutionPreview(null)
    } catch (error) {
      console.error('Failed to resolve conflict:', error)
    } finally {
      setIsResolving(false)
    }
  }, [onResolveConflict])

  /**
   * Preview resolution result
   */
  const previewResolution = useCallback((
    conflict: ConflictInfo, 
    strategy: ConflictResolution['strategy'],
    selectedOperation?: string
  ) => {
    let preview = null

    switch (strategy) {
      case 'merge':
        preview = mergeOperations(conflict.operations)
        break
      
      case 'timestamp':
        const latestOp = [...conflict.operations].sort((a, b) => b.timestamp - a.timestamp)[0]
        preview = latestOp
        break
      
      case 'user_priority':
        const priorityOp = conflict.operations.find(op => op.id === selectedOperation) || conflict.operations[0]
        preview = priorityOp
        break
      
      default:
        preview = null
    }

    setResolutionPreview(preview)
  }, [])

  /**
   * Merge operations (simplified)
   */
  const mergeOperations = (operations: Operation[]) => {
    if (operations.length < 2) return operations[0]

    const merged: any = { ...operations[0] }
    
    if (operations[0].type === 'view_change') {
      const viewOps = operations as BrainViewOperation[]
      merged.data = viewOps.reduce((acc, op) => ({ ...acc, ...op.data }), {})
    } else if (operations[0].type === 'annotate') {
      const annotationOps = operations as AnnotationOperation[]
      const contents = annotationOps.map(op => op.data.annotation.content).filter(Boolean)
      merged.data = {
        ...merged.data,
        annotation: {
          ...merged.data.annotation,
          content: contents.join('\n---\n'),
          metadata: {
            ...merged.data.annotation.metadata,
            mergedFrom: annotationOps.map(op => op.userId),
            mergedAt: new Date()
          }
        }
      }
    }

    return merged
  }

  /**
   * Get conflict severity color
   */
  const getSeverityColor = (severity: 'low' | 'medium' | 'high') => {
    switch (severity) {
      case 'high': return 'text-red-600 bg-red-50 border-red-200'
      case 'medium': return 'text-yellow-600 bg-yellow-50 border-yellow-200'
      case 'low': return 'text-blue-600 bg-blue-50 border-blue-200'
      default: return 'text-gray-600 bg-gray-50 border-gray-200'
    }
  }

  /**
   * Format operation for display
   */
  const formatOperation = (operation: Operation) => {
    switch (operation.type) {
      case 'view_change':
        const viewData = (operation as BrainViewOperation).data
        return `View: ${viewData.viewMode || 'unknown'} (threshold: ${viewData.threshold || 'N/A'})`
      
      case 'annotate':
        const annotationData = (operation as AnnotationOperation).data
        return `${annotationData.action} annotation: "${annotationData.annotation.content || 'No content'}"`
      
      default:
        return `${operation.type} operation`
    }
  }

  /**
   * Auto-resolve conflicts based on rules
   */
  const autoResolve = useCallback(async (conflict: ConflictInfo) => {
    let resolution: ConflictResolution

    switch (conflict.type) {
      case 'view_conflict':
        // Use timestamp for view conflicts
        resolution = {
          strategy: 'timestamp',
          timestamp: new Date()
        }
        break
      
      case 'annotation_overlap':
        // Merge annotation conflicts
        resolution = {
          strategy: 'merge',
          timestamp: new Date()
        }
        break
      
      default:
        // Default to user priority (first user)
        resolution = {
          strategy: 'user_priority',
          selectedOperation: conflict.operations[0].id,
          timestamp: new Date()
        }
    }

    resolution.userChoice = 'auto'
    await handleResolve(conflict, resolution)
  }, [handleResolve])

  /**
   * Auto-resolve all conflicts
   */
  const autoResolveAll = useCallback(async () => {
    const autoResolvableConflicts = conflicts.filter(c => c.severity !== 'high')
    
    for (const conflict of autoResolvableConflicts) {
      await autoResolve(conflict)
    }
  }, [conflicts, autoResolve])

  // Auto-resolve low severity conflicts if enabled
  useEffect(() => {
    if (autoResolveEnabled) {
      const lowSeverityConflicts = conflicts.filter(c => 
        c.severity === 'low' && !c.autoResolved && !c.resolution
      )
      
      lowSeverityConflicts.forEach(conflict => {
        setTimeout(() => autoResolve(conflict), 1000)
      })
    }
  }, [conflicts, autoResolveEnabled, autoResolve])

  if (conflicts.length === 0) {
    return (
      <div className={`text-center py-8 ${className}`}>
        <CheckCircle className="w-16 h-16 text-green-500 mx-auto mb-4" />
        <h3 className="text-lg font-medium text-green-700 mb-2">No Conflicts</h3>
        <p className="text-gray-600">All operations are synchronized successfully.</p>
      </div>
    )
  }

  return (
    <div className={className}>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center space-x-3">
          <AlertTriangle className="w-6 h-6 text-orange-500" />
          <h2 className="text-xl font-semibold">Conflict Resolution</h2>
          <Badge variant="destructive">{conflicts.length} conflicts</Badge>
        </div>
        
        <div className="flex items-center space-x-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setAutoResolveEnabled(!autoResolveEnabled)}
          >
            <Zap className="w-4 h-4 mr-1" />
            Auto-resolve: {autoResolveEnabled ? 'ON' : 'OFF'}
          </Button>
          
          <Button
            variant="default"
            size="sm"
            onClick={autoResolveAll}
            disabled={conflicts.filter(c => c.severity !== 'high').length === 0}
          >
            Resolve All Safe
          </Button>
        </div>
      </div>

      {/* Conflict List */}
      <div className="space-y-4">
        {conflicts.map(conflict => (
          <Card
            key={conflict.id}
            className={`p-4 border-2 ${getSeverityColor(conflict.severity)}`}
          >
            <div className="flex items-start justify-between mb-4">
              <div className="flex items-center space-x-3">
                <Badge variant="secondary">
                  {conflict.type.replace('_', ' ')}
                </Badge>
                
                <Badge variant={
                  conflict.severity === 'high' ? 'destructive' : 
                  conflict.severity === 'medium' ? 'default' : 'secondary'
                }>
                  {conflict.severity} priority
                </Badge>
                
                {conflict.autoResolved && (
                  <Badge variant="outline">
                    <Zap className="w-3 h-3 mr-1" />
                    Auto-resolved
                  </Badge>
                )}
              </div>

              <div className="flex items-center space-x-1 text-sm text-gray-500">
                <Clock className="w-4 h-4" />
                <span>{new Date(conflict.timestamp).toLocaleTimeString()}</span>
              </div>
            </div>

            {/* Involved Users */}
            <div className="flex items-center space-x-2 mb-4">
              <Users className="w-4 h-4 text-gray-500" />
              <span className="text-sm text-gray-600">Involved users:</span>
              {conflict.users.map(user => (
                <div key={user.id} className="flex items-center space-x-1">
                  <div
                    className="w-3 h-3 rounded-full"
                    style={{ backgroundColor: user.color }}
                  />
                  <span className="text-sm">{user.name}</span>
                </div>
              ))}
            </div>

            {/* Operations */}
            <div className="mb-4">
              <h4 className="text-sm font-medium mb-2">Conflicting Operations:</h4>
              <div className="space-y-2">
                {conflict.operations.map((operation, index) => (
                  <div
                    key={operation.id}
                    className="flex items-center justify-between p-2 bg-white/50 rounded border"
                  >
                    <div className="flex items-center space-x-2">
                      <div className="text-xs text-gray-500">#{index + 1}</div>
                      <div className="text-sm">{formatOperation(operation)}</div>
                    </div>
                    
                    <div className="flex items-center space-x-2">
                      <Badge variant="outline">
                        {conflict.users.find(u => u.id === operation.userId)?.name || 'Unknown'}
                      </Badge>
                      <span className="text-xs text-gray-500">
                        {new Date(operation.timestamp).toLocaleTimeString()}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Resolution Options */}
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  const resolution: ConflictResolution = {
                    strategy: 'timestamp',
                    timestamp: new Date()
                  }
                  handleResolve(conflict, resolution)
                }}
                disabled={isResolving}
              >
                <Clock className="w-4 h-4 mr-1" />
                Use Latest
              </Button>
              
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  const resolution: ConflictResolution = {
                    strategy: 'merge',
                    timestamp: new Date()
                  }
                  handleResolve(conflict, resolution)
                }}
                disabled={isResolving}
              >
                <Merge className="w-4 h-4 mr-1" />
                Merge
              </Button>
              
              <Button
                size="sm"
                variant="outline"
                onClick={() => setSelectedConflict(conflict)}
                disabled={isResolving}
              >
                <Eye className="w-4 h-4 mr-1" />
                Review
              </Button>
              
              {onDismissConflict && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => onDismissConflict(conflict.id)}
                  disabled={isResolving}
                >
                  <XCircle className="w-4 h-4 mr-1" />
                  Dismiss
                </Button>
              )}
            </div>
          </Card>
        ))}
      </div>

      {/* Detailed Resolution Dialog */}
      <Dialog open={!!selectedConflict} onOpenChange={(open) => !open && setSelectedConflict(null)}>
        <DialogContent className="max-w-4xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center space-x-2">
              <AlertTriangle className="w-5 h-5 text-orange-500" />
              <span>Resolve Conflict: {selectedConflict?.type.replace('_', ' ')}</span>
            </DialogTitle>
            <DialogDescription>
              Review differences and choose how to merge or dismiss this conflict.
            </DialogDescription>
          </DialogHeader>

          {selectedConflict && (
            <div className="space-y-6">
              {/* Conflict Details */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <h4 className="font-medium mb-2">Conflict Information</h4>
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between">
                      <span>Type:</span>
                      <Badge variant="secondary">
                        {selectedConflict.type.replace('_', ' ')}
                      </Badge>
                    </div>
                    <div className="flex justify-between">
                      <span>Severity:</span>
                      <Badge variant={selectedConflict.severity === 'high' ? 'destructive' : 'secondary'}>
                        {selectedConflict.severity}
                      </Badge>
                    </div>
                    <div className="flex justify-between">
                      <span>Time:</span>
                      <span>{new Date(selectedConflict.timestamp).toLocaleString()}</span>
                    </div>
                  </div>
                </div>

                <div>
                  <h4 className="font-medium mb-2">Involved Users</h4>
                  <div className="space-y-2">
                    {selectedConflict.users.map(user => (
                      <div key={user.id} className="flex items-center space-x-2">
                        <div
                          className="w-4 h-4 rounded-full"
                          style={{ backgroundColor: user.color }}
                        />
                        <span className="text-sm">{user.name}</span>
                        <Badge variant="outline" className="text-xs">{user.role}</Badge>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Operations Comparison */}
              <div>
                <h4 className="font-medium mb-3">Operations Comparison</h4>
                <div className="grid grid-cols-2 gap-4">
                  {selectedConflict.operations.map((operation, index) => (
                    <Card key={operation.id} className="p-3">
                      <div className="flex items-center justify-between mb-2">
                        <Badge variant="outline">Operation {index + 1}</Badge>
                        <span className="text-xs text-gray-500">
                          {new Date(operation.timestamp).toLocaleTimeString()}
                        </span>
                      </div>
                      
                      <div className="text-sm space-y-1">
                        <div><strong>User:</strong> {selectedConflict.users.find(u => u.id === operation.userId)?.name}</div>
                        <div><strong>Action:</strong> {formatOperation(operation)}</div>
                      </div>

                      <Button
                        size="sm"
                        variant="outline"
                        className="w-full mt-2"
                        onClick={() => previewResolution(selectedConflict, 'user_priority', operation.id)}
                      >
                        <ThumbsUp className="w-3 h-3 mr-1" />
                        Use This
                      </Button>
                    </Card>
                  ))}
                </div>
              </div>

              {/* Resolution Preview */}
              {resolutionPreview && (
                <div>
                  <h4 className="font-medium mb-2">Resolution Preview</h4>
                  <Card className="p-3 bg-green-50 border-green-200">
                    <div className="text-sm">
                      <strong>Result:</strong> {formatOperation(resolutionPreview)}
                    </div>
                  </Card>
                </div>
              )}

              {/* Resolution Strategies */}
              <div>
                <h4 className="font-medium mb-3">Resolution Strategies</h4>
                <div className="grid grid-cols-3 gap-3">
                  <Button
                    variant="outline"
                    className="h-auto p-4 flex flex-col items-center"
                    onClick={() => previewResolution(selectedConflict, 'timestamp')}
                  >
                    <Clock className="w-6 h-6 mb-2" />
                    <div className="text-center">
                      <div className="font-medium">Use Latest</div>
                      <div className="text-xs text-gray-500">Most recent wins</div>
                    </div>
                  </Button>
                  
                  <Button
                    variant="outline"
                    className="h-auto p-4 flex flex-col items-center"
                    onClick={() => previewResolution(selectedConflict, 'merge')}
                  >
                    <Merge className="w-6 h-6 mb-2" />
                    <div className="text-center">
                      <div className="font-medium">Merge</div>
                      <div className="text-xs text-gray-500">Combine changes</div>
                    </div>
                  </Button>
                  
                  <Button
                    variant="outline"
                    className="h-auto p-4 flex flex-col items-center"
                    onClick={() => previewResolution(selectedConflict, 'user_priority', selectedConflict.operations[0].id)}
                  >
                    <UserIcon className="w-6 h-6 mb-2" />
                    <div className="text-center">
                      <div className="font-medium">First User</div>
                      <div className="text-xs text-gray-500">Priority by user</div>
                    </div>
                  </Button>
                </div>
              </div>
            </div>
          )}

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setSelectedConflict(null)}
            >
              Cancel
            </Button>
            
            {resolutionPreview && (
              <Button
                onClick={() => {
                  if (selectedConflict) {
                    const resolution: ConflictResolution = {
                      strategy: 'manual',
                      mergedResult: resolutionPreview,
                      timestamp: new Date()
                    }
                    handleResolve(selectedConflict, resolution)
                  }
                }}
                disabled={isResolving}
              >
                {isResolving ? 'Resolving...' : 'Apply Resolution'}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
