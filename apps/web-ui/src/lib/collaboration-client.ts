import { 
  CollaborationState, 
  CollaborationEvent, 
  CollaborationWebSocketMessage,
  Operation, 
  User, 
  Annotation, 
  ConflictInfo, 
  ConflictResolution,
  SyncStatus,
  CollaborationPermissions,
  BrainViewState,
  CursorPosition,
  CollaborationEventHandlers,
  CollaborationConfig
} from '@/types/collaboration-enhanced'
import { WebSocketManager } from './websocket-manager'
import { OperationalTransformClient } from './operational-transform-client'
import { resolveRealtimeWsBaseUrl } from './service-endpoints'

export class CollaborationClient {
  private wsManager: WebSocketManager | null = null
  private otClient: OperationalTransformClient
  private state: CollaborationState
  private config: CollaborationConfig
  private eventHandlers: CollaborationEventHandlers
  private reconnectTimeout: NodeJS.Timeout | null = null
  private heartbeatInterval: NodeJS.Timeout | null = null
  private operationQueue: Operation[] = []
  private isProcessingQueue = false

  constructor(
    documentId: string, 
    currentUser: User, 
    config: Partial<CollaborationConfig> = {},
    eventHandlers: CollaborationEventHandlers = {}
  ) {
    this.otClient = new OperationalTransformClient()
    this.eventHandlers = eventHandlers
    
    this.config = {
      enableRealtime: true,
      enableConflictResolution: true,
      enableViewSync: true,
      enableAnnotationSync: true,
      conflictResolutionStrategy: 'hybrid',
      maxRetries: 3,
      reconnectDelay: 2000,
      operationBatchSize: 10,
      syncViewOptions: {
        syncCursor: true,
        syncView: true,
        syncAnnotations: true,
        syncThreshold: true,
        syncColormap: true
      },
      ...config
    }

    this.state = {
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
      permissions: this.getDefaultPermissions(currentUser),
      version: 0,
      lastSynced: new Date()
    }

    this.initializeWebSocket()
  }

  /**
   * Initialize WebSocket connection
   */
  private async initializeWebSocket(): Promise<void> {
    if (!this.config.enableRealtime) {
      return
    }

    try {
      this.updateSyncStatus({ 
        status: 'connecting',
        message: 'Connecting to collaboration server...',
        lastUpdate: new Date(),
        operationsQueue: this.operationQueue.length
      })

      const wsUrl = resolveRealtimeWsBaseUrl()
      
      this.wsManager = new WebSocketManager(
        {
          url: wsUrl,
          documentId: `collaboration/${this.state.documentId}`,
          userId: this.state.activeUsers[0]?.id || 'anonymous',
          userName: this.state.activeUsers[0]?.name || 'anonymous',
          protocols: ['collaboration-v1'],
          maxReconnectAttempts: this.config.maxRetries,
          reconnectInterval: this.config.reconnectDelay,
          enableHeartbeat: true,
          heartbeatInterval: 30000
        },
        {
          onConnect: () => this.handleWebSocketOpen(),
          onDisconnect: () => this.handleWebSocketClose(),
          onError: (error) => this.handleWebSocketError(error as unknown as Error),
          onMessage: (message) => {
            const normalized: CollaborationWebSocketMessage = {
              ...(message as any),
              timestamp: message.timestamp ? new Date(message.timestamp) : undefined
            }
            this.handleWebSocketMessage(normalized)
          }
        }
      )

      await this.wsManager.connect()
      
    } catch (error) {
      console.error('Failed to initialize WebSocket:', error)
      this.updateSyncStatus({ 
        status: 'error',
        message: 'Failed to connect to collaboration server',
        lastUpdate: new Date(),
        operationsQueue: this.operationQueue.length
      })
      
      this.eventHandlers.onError?.(error as Error)
      this.scheduleReconnect()
    }
  }

  /**
   * Handle WebSocket connection open
   */
  private handleWebSocketOpen(): void {
    console.log('Collaboration WebSocket connected')
    
    this.updateSyncStatus({ 
      status: 'connected',
      message: 'Connected to collaboration server',
      lastUpdate: new Date(),
      operationsQueue: this.operationQueue.length,
      retryCount: 0
    })

    // Send join message
    this.sendMessage({
      type: 'join',
      data: {
        user: this.getCurrentUser(),
        permissions: this.state.permissions,
        version: this.state.version
      },
      timestamp: new Date(),
      documentId: this.state.documentId
    })

    // Process queued operations
    this.processOperationQueue()

    // Start heartbeat
    this.startHeartbeat()
  }

  /**
   * Handle WebSocket connection close
   */
  private handleWebSocketClose(): void {
    console.log('Collaboration WebSocket disconnected')
    
    this.updateSyncStatus({ 
      status: 'disconnected',
      message: 'Disconnected from collaboration server',
      lastUpdate: new Date(),
      operationsQueue: this.operationQueue.length
    })

    this.stopHeartbeat()
    this.scheduleReconnect()
  }

  /**
   * Handle WebSocket errors
   */
  private handleWebSocketError(error: Error): void {
    console.error('Collaboration WebSocket error:', error)
    
    this.updateSyncStatus({ 
      status: 'error',
      message: error.message,
      lastUpdate: new Date(),
      operationsQueue: this.operationQueue.length
    })

    this.eventHandlers.onError?.(error)
  }

  /**
   * Handle incoming WebSocket messages
   */
  private async handleWebSocketMessage(message: CollaborationWebSocketMessage): Promise<void> {
    try {
      switch (message.type) {
        case 'join':
          this.handleUserJoin(message.data.user)
          break
        
        case 'leave':
          this.handleUserLeave(message.data.userId)
          break
        
        case 'operation':
          await this.handleRemoteOperation(message.data.operation)
          break
        
        case 'cursor':
          this.handleCursorMove(message.data.cursor)
          break
        
        case 'annotation':
          this.handleAnnotationUpdate(message.data)
          break
        
        case 'conflict':
          this.handleConflict(message.data.conflict)
          break
        
        case 'view_change':
          this.handleViewChange(message.data)
          break
        
        case 'sync':
          this.handleSyncUpdate(message.data)
          break
        
        default:
          console.warn('Unknown message type:', message.type)
      }
    } catch (error) {
      console.error('Error handling WebSocket message:', error)
      this.eventHandlers.onError?.(error as Error)
    }
  }

  /**
   * Handle user join
   */
  private handleUserJoin(user: User): void {
    if (!this.state.activeUsers.find(u => u.id === user.id)) {
      this.state.activeUsers.push(user)
      this.eventHandlers.onUserJoin?.(user)
    }
  }

  /**
   * Handle user leave
   */
  private handleUserLeave(userId: string): void {
    this.state.activeUsers = this.state.activeUsers.filter(u => u.id !== userId)
    this.eventHandlers.onUserLeave?.(userId)
  }

  /**
   * Handle remote operation
   */
  private async handleRemoteOperation(operation: Operation): Promise<void> {
    if (this.config.enableConflictResolution) {
      // Transform operation against local operations
      const localOps = this.getUnacknowledgedOperations()
      const transformResult = await this.otClient.transformOperation(operation, localOps)
      
      if (transformResult.conflicts && transformResult.conflicts.length > 0) {
        // Handle conflicts
        for (const conflict of transformResult.conflicts) {
          this.handleConflict(conflict)
        }
      }
      
      // Apply transformed operation
      this.applyRemoteOperationToState(transformResult.transformed[0])
    } else {
      // Apply operation directly
      this.applyRemoteOperationToState(operation)
    }
    
    this.otClient.applyRemoteOperation(operation)
    this.eventHandlers.onOperation?.(operation)
  }

  /**
   * Handle cursor movement
   */
  private handleCursorMove(cursor: CursorPosition): void {
    const user = this.state.activeUsers.find(u => u.id === cursor.userId)
    if (user) {
      user.cursor = cursor
      this.eventHandlers.onCursorMove?.(cursor)
    }
  }

  /**
   * Handle annotation updates
   */
  private handleAnnotationUpdate(data: any): void {
    const { annotation, action } = data
    
    switch (action) {
      case 'create':
        this.state.annotations.push(annotation)
        break
      
      case 'update':
        const index = this.state.annotations.findIndex(a => a.id === annotation.id)
        if (index !== -1) {
          this.state.annotations[index] = { ...this.state.annotations[index], ...annotation }
        }
        break
      
      case 'delete':
        this.state.annotations = this.state.annotations.filter(a => a.id !== annotation.id)
        break
    }
    
    this.eventHandlers.onAnnotation?.(annotation, action)
  }

  /**
   * Handle conflicts
   */
  private handleConflict(conflict: ConflictInfo): void {
    this.state.conflicts.push(conflict)
    
    this.updateSyncStatus({ 
      status: 'conflict',
      message: `Conflict detected: ${conflict.type}`,
      lastUpdate: new Date(),
      operationsQueue: this.operationQueue.length
    })
    
    this.eventHandlers.onConflict?.(conflict)
    
    // Auto-resolve if configured
    if (this.config.conflictResolutionStrategy === 'automatic') {
      this.autoResolveConflict(conflict)
    }
  }

  /**
   * Handle view changes
   */
  private handleViewChange(data: any): void {
    const { viewState, userId } = data
    
    if (this.config.syncViewOptions.syncView) {
      this.eventHandlers.onViewChange?.(viewState, userId)
    }
  }

  /**
   * Handle sync updates
   */
  private handleSyncUpdate(data: any): void {
    const { version, timestamp } = data
    
    this.state.version = version
    this.state.lastSynced = new Date(timestamp)
    
    this.updateSyncStatus({ 
      status: 'connected',
      message: 'Synchronized',
      lastUpdate: new Date(),
      operationsQueue: this.operationQueue.length
    })
  }

  /**
   * Apply operation locally
   */
  async applyOperation(operation: Operation): Promise<void> {
    try {
      // Add to queue if not connected
      if (!this.isConnected()) {
        this.operationQueue.push(operation)
        this.updateSyncStatus({ 
          status: 'disconnected',
          message: 'Operation queued',
          lastUpdate: new Date(),
          operationsQueue: this.operationQueue.length
        })
        return
      }

      // Apply locally first
      this.applyOperationToState(operation)
      this.otClient.applyOperation(operation)

      // Send to server
      await this.sendMessage({
        type: 'operation',
        data: { operation },
        timestamp: new Date(),
        userId: this.getCurrentUser()?.id,
        documentId: this.state.documentId
      })

    } catch (error) {
      console.error('Failed to apply operation:', error)
      this.eventHandlers.onError?.(error as Error)
    }
  }

  /**
   * Create annotation
   */
  async createAnnotation(annotation: Partial<Annotation>): Promise<void> {
    const fullAnnotation: Annotation = {
      id: `ann_${Date.now()}_${Math.random()}`,
      userId: this.getCurrentUser()?.id || '',
      userName: this.getCurrentUser()?.name || '',
      userColor: this.getCurrentUser()?.color || '#007bff',
      type: 'comment',
      position: { x: 0, y: 0 },
      content: '',
      timestamp: new Date(),
      visible: true,
      ...annotation
    }

    const operation: Operation = {
      id: `op_${Date.now()}_${Math.random()}`,
      type: 'annotate',
      userId: fullAnnotation.userId,
      timestamp: Date.now(),
      documentId: this.state.documentId,
      data: {
        action: 'create',
        annotation: fullAnnotation
      }
    }

    await this.applyOperation(operation)
  }

  /**
   * Update annotation
   */
  async updateAnnotation(id: string, updates: Partial<Annotation>): Promise<void> {
    const operation: Operation = {
      id: `op_${Date.now()}_${Math.random()}`,
      type: 'annotate',
      userId: this.getCurrentUser()?.id || '',
      timestamp: Date.now(),
      documentId: this.state.documentId,
      data: {
        action: 'update',
        annotation: { id, ...updates }
      }
    }

    await this.applyOperation(operation)
  }

  /**
   * Delete annotation
   */
  async deleteAnnotation(id: string): Promise<void> {
    const operation: Operation = {
      id: `op_${Date.now()}_${Math.random()}`,
      type: 'annotate',
      userId: this.getCurrentUser()?.id || '',
      timestamp: Date.now(),
      documentId: this.state.documentId,
      data: {
        action: 'delete',
        annotation: { id }
      }
    }

    await this.applyOperation(operation)
  }

  /**
   * Sync view state
   */
  syncView(viewState: Partial<BrainViewState>): void {
    if (!this.config.enableViewSync || !this.isConnected()) {
      return
    }

    this.sendMessage({
      type: 'view_change',
      data: { viewState },
      timestamp: new Date(),
      userId: this.getCurrentUser()?.id,
      documentId: this.state.documentId
    })
  }

  /**
   * Update cursor position
   */
  setCursorPosition(position: CursorPosition): void {
    if (!this.config.syncViewOptions.syncCursor || !this.isConnected()) {
      return
    }

    this.sendMessage({
      type: 'cursor',
      data: { cursor: position },
      timestamp: new Date(),
      userId: this.getCurrentUser()?.id,
      documentId: this.state.documentId
    })
  }

  /**
   * Resolve conflict
   */
  async resolveConflict(conflictId: string, resolution: ConflictResolution): Promise<void> {
    const conflict = this.state.conflicts.find(c => c.id === conflictId)
    if (!conflict) {
      return
    }

    conflict.resolution = resolution
    conflict.autoResolved = false

    // Remove from conflicts list
    this.state.conflicts = this.state.conflicts.filter(c => c.id !== conflictId)

    // Send resolution to server
    await this.sendMessage({
      type: 'conflict',
      data: { 
        conflictId, 
        resolution,
        action: 'resolve'
      },
      timestamp: new Date(),
      userId: this.getCurrentUser()?.id,
      documentId: this.state.documentId
    })

    this.updateSyncStatus({ 
      status: 'connected',
      message: 'Conflict resolved',
      lastUpdate: new Date(),
      operationsQueue: this.operationQueue.length
    })
  }

  /**
   * Auto-resolve conflict
   */
  private async autoResolveConflict(conflict: ConflictInfo): Promise<void> {
    try {
      const resolutions = await this.otClient.resolveConflicts([conflict])
      if (resolutions.length > 0) {
        const resolution = resolutions[0]
        resolution.userChoice = 'auto'
        await this.resolveConflict(conflict.id, resolution)
        conflict.autoResolved = true
      }
    } catch (error) {
      console.error('Failed to auto-resolve conflict:', error)
    }
  }

  /**
   * Send WebSocket message
   */
  private async sendMessage(message: CollaborationWebSocketMessage): Promise<void> {
    if (this.wsManager?.isConnected()) {
      const payload: any = {
        ...message,
        timestamp: message.timestamp instanceof Date
          ? message.timestamp.getTime()
          : message.timestamp
      }
      this.wsManager.send(payload)
    } else {
      console.warn('WebSocket not connected, message not sent:', message.type)
    }
  }

  /**
   * Process operation queue
   */
  private async processOperationQueue(): Promise<void> {
    if (this.isProcessingQueue || this.operationQueue.length === 0) {
      return
    }

    this.isProcessingQueue = true
    
    try {
      this.updateSyncStatus({ 
        status: 'syncing',
        message: `Syncing ${this.operationQueue.length} operations...`,
        lastUpdate: new Date(),
        operationsQueue: this.operationQueue.length
      })

      const batchSize = this.config.operationBatchSize
      while (this.operationQueue.length > 0) {
        const batch = this.operationQueue.splice(0, batchSize)
        
        for (const operation of batch) {
          await this.sendMessage({
            type: 'operation',
            data: { operation },
            timestamp: new Date(),
            userId: this.getCurrentUser()?.id,
            documentId: this.state.documentId
          })
        }

        // Small delay between batches
        await new Promise(resolve => setTimeout(resolve, 50))
      }

      this.updateSyncStatus({ 
        status: 'connected',
        message: 'All operations synced',
        lastUpdate: new Date(),
        operationsQueue: 0
      })

    } catch (error) {
      console.error('Failed to process operation queue:', error)
      this.updateSyncStatus({ 
        status: 'error',
        message: 'Failed to sync operations',
        lastUpdate: new Date(),
        operationsQueue: this.operationQueue.length
      })
    } finally {
      this.isProcessingQueue = false
    }
  }

  /**
   * Apply operation to local state
   */
  private applyOperationToState(operation: Operation): void {
    this.state.operations.push(operation)
    this.state.version++

    switch (operation.type) {
      case 'annotate':
        this.applyAnnotationOperation(operation)
        break
      // Add other operation types as needed
    }
  }

  /**
   * Apply remote operation to state
   */
  private applyRemoteOperationToState(operation: Operation): void {
    this.applyOperationToState(operation)
  }

  /**
   * Apply annotation operation
   */
  private applyAnnotationOperation(operation: Operation): void {
    const { action, annotation } = (operation as any).data

    switch (action) {
      case 'create':
        this.state.annotations.push(annotation)
        break
      
      case 'update':
        const index = this.state.annotations.findIndex(a => a.id === annotation.id)
        if (index !== -1) {
          this.state.annotations[index] = { ...this.state.annotations[index], ...annotation }
        }
        break
      
      case 'delete':
        this.state.annotations = this.state.annotations.filter(a => a.id !== annotation.id)
        break
    }
  }

  /**
   * Get unacknowledged operations
   */
  private getUnacknowledgedOperations(): Operation[] {
    // In a real implementation, this would track which operations have been acknowledged by the server
    return this.otClient.getOperationHistory().slice(-10) // Last 10 operations
  }

  /**
   * Update sync status
   */
  private updateSyncStatus(status: Partial<SyncStatus>): void {
    this.state.syncStatus = { ...this.state.syncStatus, ...status }
    this.eventHandlers.onSyncStatusChange?.(this.state.syncStatus)
  }

  /**
   * Start heartbeat
   */
  private startHeartbeat(): void {
    this.stopHeartbeat()
    
    this.heartbeatInterval = setInterval(() => {
      if (this.isConnected()) {
        this.sendMessage({
          type: 'heartbeat',
          data: { timestamp: new Date() },
          timestamp: new Date(),
          userId: this.getCurrentUser()?.id,
          documentId: this.state.documentId
        })
      }
    }, 30000) // 30 seconds
  }

  /**
   * Stop heartbeat
   */
  private stopHeartbeat(): void {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval)
      this.heartbeatInterval = null
    }
  }

  /**
   * Schedule reconnection
   */
  private scheduleReconnect(): void {
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout)
    }

    this.reconnectTimeout = setTimeout(() => {
      console.log('Attempting to reconnect...')
      this.initializeWebSocket()
    }, this.config.reconnectDelay)
  }

  /**
   * Get default permissions
   */
  private getDefaultPermissions(user: User): CollaborationPermissions {
    return {
      canEdit: user.role !== 'viewer',
      canAnnotate: true,
      canComment: true,
      canViewOthers: true,
      canResolveConflicts: user.role === 'owner',
      canManageUsers: user.role === 'owner',
      canExport: user.role !== 'viewer'
    }
  }

  /**
   * Get current user
   */
  private getCurrentUser(): User | undefined {
    return this.state.activeUsers[0] // First user is always current user
  }

  /**
   * Check if connected
   */
  isConnected(): boolean {
    return this.wsManager?.isConnected() || false
  }

  /**
   * Get current state
   */
  getState(): CollaborationState {
    return { ...this.state }
  }

  /**
   * Get operation transform client
   */
  getOTClient(): OperationalTransformClient {
    return this.otClient
  }

  /**
   * Destroy the collaboration client
   */
  destroy(): void {
    this.stopHeartbeat()
    
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout)
    }

    this.wsManager?.disconnect()
    this.otClient.reset()
  }
}
