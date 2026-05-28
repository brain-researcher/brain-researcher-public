'use client'

import { WebSocketManager, WebSocketMessage } from './websocket-manager'
import { resolveRealtimeWsBaseUrl } from './service-endpoints'

export interface StateOperation {
  type: 'set' | 'update' | 'delete' | 'merge'
  path: string[]
  value?: any
  timestamp: number
  userId: string
  operationId: string
}

export interface StateConflict {
  operationId: string
  conflictingOperations: StateOperation[]
  resolution?: 'local' | 'remote' | 'merge' | 'manual'
}

export interface SharedStateOptions {
  documentId: string
  userId: string
  userName: string
  wsUrl?: string
  conflictResolutionStrategy?: 'last-write-wins' | 'manual' | 'merge'
  debounceMs?: number
  maxOperationHistory?: number
}

export interface SharedStateHandlers {
  onStateChange?: (state: any, operation: StateOperation) => void
  onConflict?: (conflict: StateConflict) => void
  onSync?: () => void
  onError?: (error: Error) => void
}

export class SharedState {
  private state: any = {}
  private operations: Map<string, StateOperation> = new Map()
  private pendingOperations: Map<string, StateOperation> = new Map()
  private wsManager: WebSocketManager | null = null
  private options: Required<SharedStateOptions>
  private handlers: SharedStateHandlers
  private debounceTimer: NodeJS.Timeout | null = null
  private vectorClock: Map<string, number> = new Map()
  private isDestroyed = false

  constructor(options: SharedStateOptions, handlers: SharedStateHandlers = {}) {
    this.options = {
      wsUrl: options.wsUrl || resolveRealtimeWsBaseUrl(),
      conflictResolutionStrategy: 'last-write-wins',
      debounceMs: 100,
      maxOperationHistory: 1000,
      ...options
    }
    this.handlers = handlers
    this.initializeWebSocket()
  }

  private async initializeWebSocket(): Promise<void> {
    try {
      this.wsManager = new WebSocketManager(
        {
          url: this.options.wsUrl,
          documentId: this.options.documentId,
          userId: this.options.userId,
          userName: this.options.userName
        },
        {
          onConnect: () => this.requestStateSync(),
          onMessage: (message) => this.handleWebSocketMessage(message),
          onError: (error) => this.handlers.onError?.(new Error('WebSocket error'))
        }
      )
      
      await this.wsManager.connect()
    } catch (error) {
      this.handlers.onError?.(error as Error)
    }
  }

  private handleWebSocketMessage(message: WebSocketMessage): void {
    switch (message.type) {
      case 'state_operation':
        if (message.data && message.userId !== this.options.userId) {
          this.applyRemoteOperation(message.data)
        }
        break

      case 'state_sync_request':
        if (message.userId !== this.options.userId) {
          this.sendStateSnapshot()
        }
        break

      case 'state_sync_response':
        if (message.data) {
          this.applyStateSnapshot(message.data)
        }
        break

      case 'operation_ack':
        if (message.data?.operationId) {
          this.pendingOperations.delete(message.data.operationId)
        }
        break

      case 'conflict_detected':
        if (message.data) {
          this.handleConflict(message.data)
        }
        break
    }
  }

  // Public API
  get<T = any>(path: string | string[]): T | undefined {
    const pathArray = Array.isArray(path) ? path : path.split('.')
    return this.getValueAtPath(this.state, pathArray)
  }

  set(path: string | string[], value: any): void {
    const pathArray = Array.isArray(path) ? path : path.split('.')
    const operation: StateOperation = {
      type: 'set',
      path: pathArray,
      value,
      timestamp: Date.now(),
      userId: this.options.userId,
      operationId: this.generateOperationId()
    }

    this.applyLocalOperation(operation)
    this.broadcastOperation(operation)
  }

  update(path: string | string[], updater: (current: any) => any): void {
    const pathArray = Array.isArray(path) ? path : path.split('.')
    const currentValue = this.getValueAtPath(this.state, pathArray)
    const newValue = updater(currentValue)

    const operation: StateOperation = {
      type: 'update',
      path: pathArray,
      value: newValue,
      timestamp: Date.now(),
      userId: this.options.userId,
      operationId: this.generateOperationId()
    }

    this.applyLocalOperation(operation)
    this.broadcastOperation(operation)
  }

  merge(path: string | string[], value: any): void {
    const pathArray = Array.isArray(path) ? path : path.split('.')
    const currentValue = this.getValueAtPath(this.state, pathArray)
    const mergedValue = this.deepMerge(currentValue, value)

    const operation: StateOperation = {
      type: 'merge',
      path: pathArray,
      value: mergedValue,
      timestamp: Date.now(),
      userId: this.options.userId,
      operationId: this.generateOperationId()
    }

    this.applyLocalOperation(operation)
    this.broadcastOperation(operation)
  }

  delete(path: string | string[]): void {
    const pathArray = Array.isArray(path) ? path : path.split('.')
    const operation: StateOperation = {
      type: 'delete',
      path: pathArray,
      timestamp: Date.now(),
      userId: this.options.userId,
      operationId: this.generateOperationId()
    }

    this.applyLocalOperation(operation)
    this.broadcastOperation(operation)
  }

  getState(): any {
    return this.deepClone(this.state)
  }

  // Subscribe to state changes
  subscribe(callback: (state: any, operation: StateOperation) => void): () => void {
    const originalHandler = this.handlers.onStateChange
    this.handlers.onStateChange = (state, operation) => {
      originalHandler?.(state, operation)
      callback(state, operation)
    }

    return () => {
      this.handlers.onStateChange = originalHandler
    }
  }

  // Conflict resolution
  resolveConflict(conflict: StateConflict, resolution: 'local' | 'remote' | 'merge' | 'manual', mergedValue?: any): void {
    switch (resolution) {
      case 'local':
        // Keep local state, ignore remote operations
        break

      case 'remote':
        // Apply remote operations
        conflict.conflictingOperations.forEach(op => {
          if (op.userId !== this.options.userId) {
            this.applyOperationToState(op)
          }
        })
        break

      case 'merge':
        // Merge states
        if (mergedValue !== undefined) {
          const latestOperation = conflict.conflictingOperations[0]
          const mergeOperation: StateOperation = {
            ...latestOperation,
            type: 'set',
            value: mergedValue,
            userId: this.options.userId,
            operationId: this.generateOperationId(),
            timestamp: Date.now()
          }
          this.applyLocalOperation(mergeOperation)
          this.broadcastOperation(mergeOperation)
        }
        break

      case 'manual':
        // Let the application handle it
        break
    }
  }

  // Cleanup
  destroy(): void {
    this.isDestroyed = true
    if (this.debounceTimer) {
      clearTimeout(this.debounceTimer)
    }
    this.wsManager?.disconnect()
    this.operations.clear()
    this.pendingOperations.clear()
    this.vectorClock.clear()
  }

  // Private methods
  private applyLocalOperation(operation: StateOperation): void {
    this.applyOperationToState(operation)
    this.operations.set(operation.operationId, operation)
    this.pendingOperations.set(operation.operationId, operation)
    this.updateVectorClock(operation.userId, operation.timestamp)
    this.trimOperationHistory()
    
    this.handlers.onStateChange?.(this.getState(), operation)
  }

  private applyRemoteOperation(operation: StateOperation): void {
    // Check for conflicts
    const conflicts = this.detectConflicts(operation)
    if (conflicts.length > 0) {
      this.handleConflict({
        operationId: operation.operationId,
        conflictingOperations: [operation, ...conflicts]
      })
      return
    }

    this.applyOperationToState(operation)
    this.operations.set(operation.operationId, operation)
    this.updateVectorClock(operation.userId, operation.timestamp)
    this.trimOperationHistory()

    // Send acknowledgment
    this.wsManager?.send({
      type: 'operation_ack',
      userId: this.options.userId,
      documentId: this.options.documentId,
      data: { operationId: operation.operationId },
      timestamp: Date.now()
    })

    this.handlers.onStateChange?.(this.getState(), operation)
  }

  private applyOperationToState(operation: StateOperation): void {
    switch (operation.type) {
      case 'set':
        this.setValueAtPath(this.state, operation.path, operation.value)
        break

      case 'update':
      case 'merge':
        this.setValueAtPath(this.state, operation.path, operation.value)
        break

      case 'delete':
        this.deleteValueAtPath(this.state, operation.path)
        break
    }
  }

  private detectConflicts(operation: StateOperation): StateOperation[] {
    const conflicts: StateOperation[] = []
    const operationPath = operation.path.join('.')

    for (const [_, pendingOp] of Array.from(this.pendingOperations)) {
      const pendingPath = pendingOp.path.join('.')
      
      // Check if paths conflict (same path or overlapping)
      if (this.pathsConflict(operationPath, pendingPath)) {
        conflicts.push(pendingOp)
      }
    }

    return conflicts
  }

  private pathsConflict(path1: string, path2: string): boolean {
    return path1 === path2 || 
           path1.startsWith(path2 + '.') || 
           path2.startsWith(path1 + '.')
  }

  private handleConflict(conflict: StateConflict): void {
    switch (this.options.conflictResolutionStrategy) {
      case 'last-write-wins':
        const latestOperation = conflict.conflictingOperations.reduce((latest, current) =>
          current.timestamp > latest.timestamp ? current : latest
        )
        this.applyOperationToState(latestOperation)
        break

      case 'merge':
        // Attempt automatic merge
        this.attemptAutoMerge(conflict)
        break

      case 'manual':
        this.handlers.onConflict?.(conflict)
        break
    }
  }

  private attemptAutoMerge(conflict: StateConflict): void {
    const basePath = conflict.conflictingOperations[0].path
    const currentValue = this.getValueAtPath(this.state, basePath)
    
    let mergedValue = currentValue
    for (const operation of conflict.conflictingOperations) {
      if (operation.type === 'merge' && typeof operation.value === 'object') {
        mergedValue = this.deepMerge(mergedValue, operation.value)
      }
    }

    this.setValueAtPath(this.state, basePath, mergedValue)
  }

  private broadcastOperation(operation: StateOperation): void {
    if (this.debounceTimer) {
      clearTimeout(this.debounceTimer)
    }

    this.debounceTimer = setTimeout(() => {
      this.wsManager?.send({
        type: 'state_operation',
        userId: this.options.userId,
        userName: this.options.userName,
        documentId: this.options.documentId,
        data: operation,
        timestamp: Date.now()
      })
    }, this.options.debounceMs)
  }

  private requestStateSync(): void {
    this.wsManager?.send({
      type: 'state_sync_request',
      userId: this.options.userId,
      documentId: this.options.documentId,
      timestamp: Date.now()
    })
  }

  private sendStateSnapshot(): void {
    this.wsManager?.send({
      type: 'state_sync_response',
      userId: this.options.userId,
      documentId: this.options.documentId,
      data: {
        state: this.state,
        operations: Array.from(this.operations.values()).slice(-100), // Last 100 operations
        vectorClock: Object.fromEntries(this.vectorClock)
      },
      timestamp: Date.now()
    })
  }

  private applyStateSnapshot(snapshot: any): void {
    this.state = snapshot.state || {}
    
    if (snapshot.operations) {
      this.operations.clear()
      snapshot.operations.forEach((op: StateOperation) => {
        this.operations.set(op.operationId, op)
      })
    }

    if (snapshot.vectorClock) {
      this.vectorClock = new Map(Object.entries(snapshot.vectorClock))
    }

    this.handlers.onSync?.()
    this.handlers.onStateChange?.(this.getState(), {
      type: 'set',
      path: [],
      value: this.state,
      timestamp: Date.now(),
      userId: 'system',
      operationId: this.generateOperationId()
    })
  }

  private updateVectorClock(userId: string, timestamp: number): void {
    const currentClock = this.vectorClock.get(userId) || 0
    this.vectorClock.set(userId, Math.max(currentClock, timestamp))
  }

  private trimOperationHistory(): void {
    if (this.operations.size > this.options.maxOperationHistory) {
      const sortedOps = Array.from(this.operations.entries())
        .sort(([,a], [,b]) => a.timestamp - b.timestamp)
      
      const toRemove = sortedOps.slice(0, sortedOps.length - this.options.maxOperationHistory)
      toRemove.forEach(([id]) => this.operations.delete(id))
    }
  }

  private generateOperationId(): string {
    return `${this.options.userId}_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
  }

  // Utility methods
  private getValueAtPath(obj: any, path: string[]): any {
    return path.reduce((current, key) => current?.[key], obj)
  }

  private setValueAtPath(obj: any, path: string[], value: any): void {
    if (path.length === 0) return

    const lastKey = path[path.length - 1]
    const parent = path.slice(0, -1).reduce((current, key) => {
      if (current[key] === undefined) {
        current[key] = {}
      }
      return current[key]
    }, obj)

    parent[lastKey] = value
  }

  private deleteValueAtPath(obj: any, path: string[]): void {
    if (path.length === 0) return

    const lastKey = path[path.length - 1]
    const parent = path.slice(0, -1).reduce((current, key) => current?.[key], obj)
    
    if (parent && typeof parent === 'object') {
      delete parent[lastKey]
    }
  }

  private deepClone(obj: any): any {
    if (obj === null || typeof obj !== 'object') return obj
    if (obj instanceof Date) return new Date(obj)
    if (Array.isArray(obj)) return obj.map(item => this.deepClone(item))
    
    const cloned: any = {}
    for (const key in obj) {
      if (obj.hasOwnProperty(key)) {
        cloned[key] = this.deepClone(obj[key])
      }
    }
    return cloned
  }

  private deepMerge(target: any, source: any): any {
    if (source === null || typeof source !== 'object') return source
    if (target === null || typeof target !== 'object') return source
    if (Array.isArray(source)) return [...source]

    const result = { ...target }
    for (const key in source) {
      if (source.hasOwnProperty(key)) {
        if (typeof source[key] === 'object' && !Array.isArray(source[key]) && source[key] !== null) {
          result[key] = this.deepMerge(target[key], source[key])
        } else {
          result[key] = source[key]
        }
      }
    }
    return result
  }
}

// React hook for shared state
import { useEffect, useRef, useState, useCallback } from 'react'

export interface UseSharedStateOptions extends SharedStateOptions {
  initialState?: any
}

export function useSharedState<T = any>(
  options: UseSharedStateOptions,
  handlers: SharedStateHandlers = {}
): {
  state: T
  get: <U = any>(path: string | string[]) => U | undefined
  set: (path: string | string[], value: any) => void
  update: (path: string | string[], updater: (current: any) => any) => void
  merge: (path: string | string[], value: any) => void
  delete: (path: string | string[]) => void
  isConnected: boolean
  conflicts: StateConflict[]
  resolveConflict: (conflict: StateConflict, resolution: 'local' | 'remote' | 'merge' | 'manual', mergedValue?: any) => void
} {
  const sharedStateRef = useRef<SharedState | null>(null)
  const [state, setState] = useState<T>(options.initialState || {} as T)
  const [isConnected, setIsConnected] = useState(false)
  const [conflicts, setConflicts] = useState<StateConflict[]>([])

  const get = useCallback(<U = any>(path: string | string[]): U | undefined => {
    return sharedStateRef.current?.get<U>(path)
  }, [])

  const set = useCallback((path: string | string[], value: any) => {
    sharedStateRef.current?.set(path, value)
  }, [])

  const update = useCallback((path: string | string[], updater: (current: any) => any) => {
    sharedStateRef.current?.update(path, updater)
  }, [])

  const merge = useCallback((path: string | string[], value: any) => {
    sharedStateRef.current?.merge(path, value)
  }, [])

  const deleteValue = useCallback((path: string | string[]) => {
    sharedStateRef.current?.delete(path)
  }, [])

  const resolveConflict = useCallback((
    conflict: StateConflict, 
    resolution: 'local' | 'remote' | 'merge' | 'manual', 
    mergedValue?: any
  ) => {
    sharedStateRef.current?.resolveConflict(conflict, resolution, mergedValue)
    setConflicts(prev => prev.filter(c => c.operationId !== conflict.operationId))
  }, [])

  useEffect(() => {
    const stateHandlers: SharedStateHandlers = {
      onStateChange: (newState) => {
        setState(newState)
        handlers.onStateChange?.(newState, undefined as any)
      },
      onConflict: (conflict) => {
        setConflicts(prev => [...prev, conflict])
        handlers.onConflict?.(conflict)
      },
      onSync: () => {
        setIsConnected(true)
        handlers.onSync?.()
      },
      onError: handlers.onError
    }

    sharedStateRef.current = new SharedState(options, stateHandlers)

    return () => {
      sharedStateRef.current?.destroy()
    }
  }, [handlers, options])

  return {
    state,
    get,
    set,
    update,
    merge,
    delete: deleteValue,
    isConnected,
    conflicts,
    resolveConflict
  }
}
