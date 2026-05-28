import { 
  Operation, 
  BrainViewOperation, 
  AnnotationOperation, 
  TransformResult, 
  ConflictInfo, 
  ConflictResolution,
  BrainViewState,
  Annotation 
} from '@/types/collaboration-enhanced'

export class OperationalTransformClient {
  private operations: Operation[] = []
  private remoteOperations: Operation[] = []
  private localVersion = 0
  private remoteVersion = 0

  /**
   * Transform a local operation against a list of remote operations
   */
  async transformOperation(localOp: Operation, remoteOps: Operation[]): Promise<TransformResult> {
    try {
      let transformedOp = localOp
      const conflicts: ConflictInfo[] = []

      for (const remoteOp of remoteOps) {
        const result = this.transformPair(transformedOp, remoteOp)
        transformedOp = result.transformedLocal
        
        if (result.conflict) {
          conflicts.push(result.conflict)
        }
      }

      return {
        operation: localOp,
        transformed: [transformedOp],
        conflicts: conflicts.length > 0 ? conflicts : undefined
      }
    } catch (error) {
      console.error('Error transforming operation:', error)
      throw new Error(`Failed to transform operation: ${error}`)
    }
  }

  /**
   * Transform two operations against each other
   */
  private transformPair(localOp: Operation, remoteOp: Operation): {
    transformedLocal: Operation
    transformedRemote: Operation
    conflict?: ConflictInfo
  } {
    // Handle same-type operations
    if (localOp.type === remoteOp.type) {
      return this.transformSameType(localOp, remoteOp)
    }

    // Handle different-type operations
    return this.transformDifferentType(localOp, remoteOp)
  }

  /**
   * Transform operations of the same type
   */
  private transformSameType(localOp: Operation, remoteOp: Operation): {
    transformedLocal: Operation
    transformedRemote: Operation
    conflict?: ConflictInfo
  } {
    switch (localOp.type) {
      case 'view_change':
        return this.transformViewChanges(localOp as BrainViewOperation, remoteOp as BrainViewOperation)
      
      case 'annotate':
        return this.transformAnnotations(localOp as AnnotationOperation, remoteOp as AnnotationOperation)
      
      case 'insert':
      case 'delete':
        return this.transformTextOperations(localOp, remoteOp)
      
      default:
        return {
          transformedLocal: localOp,
          transformedRemote: remoteOp
        }
    }
  }

  /**
   * Transform operations of different types
   */
  private transformDifferentType(localOp: Operation, remoteOp: Operation): {
    transformedLocal: Operation
    transformedRemote: Operation
    conflict?: ConflictInfo
  } {
    // Generally, different-type operations don't interfere
    return {
      transformedLocal: localOp,
      transformedRemote: remoteOp
    }
  }

  /**
   * Transform concurrent view changes
   */
  private transformViewChanges(localOp: BrainViewOperation, remoteOp: BrainViewOperation): {
    transformedLocal: Operation
    transformedRemote: Operation
    conflict?: ConflictInfo
  } {
    const localData = localOp.data
    const remoteData = remoteOp.data

    // Check for conflicting view changes
    const hasConflict = this.detectViewConflict(localData, remoteData)

    if (hasConflict) {
      const conflict: ConflictInfo = {
        id: `conflict_${localOp.id}_${remoteOp.id}`,
        type: 'view_conflict',
        operations: [localOp, remoteOp],
        users: [], // Will be filled by the collaboration system
        timestamp: new Date(),
        severity: 'medium',
        autoResolved: false
      }

      return {
        transformedLocal: localOp,
        transformedRemote: remoteOp,
        conflict
      }
    }

    // Merge non-conflicting view changes
    const mergedData = this.mergeViewStates(localData, remoteData)
    
    const transformedLocal: BrainViewOperation = {
      ...localOp,
      data: mergedData
    }

    return {
      transformedLocal,
      transformedRemote: remoteOp
    }
  }

  /**
   * Transform concurrent annotations
   */
  private transformAnnotations(localOp: AnnotationOperation, remoteOp: AnnotationOperation): {
    transformedLocal: Operation
    transformedRemote: Operation
    conflict?: ConflictInfo
  } {
    const localAnnotation = localOp.data.annotation
    const remoteAnnotation = remoteOp.data.annotation

    // Check for annotation conflicts
    if (this.detectAnnotationConflict(localAnnotation, remoteAnnotation)) {
      const conflict: ConflictInfo = {
        id: `annotation_conflict_${localOp.id}_${remoteOp.id}`,
        type: 'annotation_overlap',
        operations: [localOp, remoteOp],
        users: [],
        timestamp: new Date(),
        severity: this.getAnnotationConflictSeverity(localAnnotation, remoteAnnotation),
        autoResolved: false
      }

      return {
        transformedLocal: localOp,
        transformedRemote: remoteOp,
        conflict
      }
    }

    return {
      transformedLocal: localOp,
      transformedRemote: remoteOp
    }
  }

  /**
   * Transform text-based operations (insert/delete)
   */
  private transformTextOperations(localOp: Operation, remoteOp: Operation): {
    transformedLocal: Operation
    transformedRemote: Operation
    conflict?: ConflictInfo
  } {
    // Simplified text transformation
    // In a real implementation, this would use proper OT algorithms
    
    return {
      transformedLocal: localOp,
      transformedRemote: remoteOp
    }
  }

  /**
   * Detect conflicts in view changes
   */
  private detectViewConflict(localData: any, remoteData: any): boolean {
    const conflictingFields = ['viewMode', 'coordinates', 'threshold', 'colormap']
    
    return conflictingFields.some(field => 
      localData[field] !== undefined && 
      remoteData[field] !== undefined && 
      JSON.stringify(localData[field]) !== JSON.stringify(remoteData[field])
    )
  }

  /**
   * Merge compatible view states
   */
  private mergeViewStates(localData: any, remoteData: any): any {
    const merged = { ...localData }

    // Use timestamp-based priority for conflicting fields
    const localTime = new Date(localData.timestamp || 0).getTime()
    const remoteTime = new Date(remoteData.timestamp || 0).getTime()

    if (remoteTime > localTime) {
      Object.keys(remoteData).forEach(key => {
        if (remoteData[key] !== undefined) {
          merged[key] = remoteData[key]
        }
      })
    }

    return merged
  }

  /**
   * Detect annotation conflicts
   */
  private detectAnnotationConflict(localAnnotation: Partial<Annotation>, remoteAnnotation: Partial<Annotation>): boolean {
    if (!localAnnotation.position || !remoteAnnotation.position) {
      return false
    }

    // Check for spatial overlap
    const distance = Math.sqrt(
      Math.pow(localAnnotation.position.x - remoteAnnotation.position.x, 2) +
      Math.pow(localAnnotation.position.y - remoteAnnotation.position.y, 2) +
      Math.pow((localAnnotation.position.z || 0) - (remoteAnnotation.position.z || 0), 2)
    )

    const overlapThreshold = 10 // pixels or mm
    return distance < overlapThreshold
  }

  /**
   * Determine annotation conflict severity
   */
  private getAnnotationConflictSeverity(localAnnotation: Partial<Annotation>, remoteAnnotation: Partial<Annotation>): 'low' | 'medium' | 'high' {
    if (!localAnnotation.position || !remoteAnnotation.position) {
      return 'low'
    }

    const distance = Math.sqrt(
      Math.pow(localAnnotation.position.x - remoteAnnotation.position.x, 2) +
      Math.pow(localAnnotation.position.y - remoteAnnotation.position.y, 2) +
      Math.pow((localAnnotation.position.z || 0) - (remoteAnnotation.position.z || 0), 2)
    )

    if (distance < 5) return 'high'
    if (distance < 10) return 'medium'
    return 'low'
  }

  /**
   * Apply an operation to the local state
   */
  applyOperation(operation: Operation): void {
    this.operations.push(operation)
    this.localVersion++
  }

  /**
   * Apply a remote operation
   */
  applyRemoteOperation(operation: Operation): void {
    this.remoteOperations.push(operation)
    this.remoteVersion++
  }

  /**
   * Get operation history
   */
  getOperationHistory(): Operation[] {
    return [...this.operations]
  }

  /**
   * Get remote operation history
   */
  getRemoteOperationHistory(): Operation[] {
    return [...this.remoteOperations]
  }

  /**
   * Resolve conflicts using different strategies
   */
  async resolveConflicts(conflicts: ConflictInfo[]): Promise<ConflictResolution[]> {
    const resolutions: ConflictResolution[] = []

    for (const conflict of conflicts) {
      const resolution = await this.resolveConflict(conflict)
      resolutions.push(resolution)
    }

    return resolutions
  }

  /**
   * Resolve a single conflict
   */
  private async resolveConflict(conflict: ConflictInfo): Promise<ConflictResolution> {
    switch (conflict.type) {
      case 'view_conflict':
        return this.resolveViewConflict(conflict)
      
      case 'annotation_overlap':
        return this.resolveAnnotationConflict(conflict)
      
      case 'concurrent_edit':
        return this.resolveConcurrentEdit(conflict)
      
      default:
        return this.resolveDefault(conflict)
    }
  }

  /**
   * Resolve view conflicts
   */
  private resolveViewConflict(conflict: ConflictInfo): ConflictResolution {
    const operations = conflict.operations as BrainViewOperation[]
    
    // Use timestamp priority for automatic resolution
    const sortedOps = operations.sort((a, b) => b.timestamp - a.timestamp)
    const winningOp = sortedOps[0]

    return {
      strategy: 'timestamp',
      selectedOperation: winningOp.id,
      timestamp: new Date()
    }
  }

  /**
   * Resolve annotation conflicts
   */
  private resolveAnnotationConflict(conflict: ConflictInfo): ConflictResolution {
    // For annotation conflicts, we'll merge them if possible
    const operations = conflict.operations as AnnotationOperation[]
    
    if (operations.length === 2) {
      const merged = this.mergeAnnotations(operations[0], operations[1])
      
      return {
        strategy: 'merge',
        mergedResult: merged,
        timestamp: new Date()
      }
    }

    // Default to user priority (first user wins)
    return {
      strategy: 'user_priority',
      selectedOperation: operations[0].id,
      timestamp: new Date()
    }
  }

  /**
   * Resolve concurrent edits
   */
  private resolveConcurrentEdit(conflict: ConflictInfo): ConflictResolution {
    // Use timestamp priority
    const sortedOps = conflict.operations.sort((a, b) => b.timestamp - a.timestamp)
    
    return {
      strategy: 'timestamp',
      selectedOperation: sortedOps[0].id,
      timestamp: new Date()
    }
  }

  /**
   * Default conflict resolution
   */
  private resolveDefault(conflict: ConflictInfo): ConflictResolution {
    return {
      strategy: 'manual',
      timestamp: new Date()
    }
  }

  /**
   * Merge two annotations
   */
  private mergeAnnotations(op1: AnnotationOperation, op2: AnnotationOperation): Partial<Annotation> {
    const ann1 = op1.data.annotation
    const ann2 = op2.data.annotation

    // Merge content and preserve both users' information
    return {
      ...ann1,
      content: `${ann1.content || ''}\n---\n${ann2.content || ''}`,
      metadata: {
        ...ann1.metadata,
        ...ann2.metadata,
        mergedFrom: [op1.userId, op2.userId],
        mergedAt: new Date()
      }
    }
  }

  /**
   * Compact operation history to avoid memory issues
   */
  compactHistory(): void {
    const maxHistorySize = 1000
    
    if (this.operations.length > maxHistorySize) {
      this.operations = this.operations.slice(-maxHistorySize)
    }
    
    if (this.remoteOperations.length > maxHistorySize) {
      this.remoteOperations = this.remoteOperations.slice(-maxHistorySize)
    }
  }

  /**
   * Get current version vectors
   */
  getVersions(): { local: number; remote: number } {
    return {
      local: this.localVersion,
      remote: this.remoteVersion
    }
  }

  /**
   * Reset the transform client state
   */
  reset(): void {
    this.operations = []
    this.remoteOperations = []
    this.localVersion = 0
    this.remoteVersion = 0
  }
}