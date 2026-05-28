'use client'

const WS_UNAVAILABLE_TTL_MS = 60 * 1000
const WS_STARTUP_FAILURE_THRESHOLD = 2
const wsUnavailableUntil = new Map<string, number>()

function getWsEndpointKey(url: string): string {
  return url.replace(/\/+$/, '')
}

function isWsEndpointTemporarilyUnavailable(url: string): boolean {
  const key = getWsEndpointKey(url)
  const until = wsUnavailableUntil.get(key)
  if (!until) return false
  if (Date.now() >= until) {
    wsUnavailableUntil.delete(key)
    return false
  }
  return true
}

function markWsEndpointUnavailable(url: string): void {
  wsUnavailableUntil.set(getWsEndpointKey(url), Date.now() + WS_UNAVAILABLE_TTL_MS)
}

function clearWsEndpointUnavailable(url: string): void {
  wsUnavailableUntil.delete(getWsEndpointKey(url))
}

export interface WebSocketMessage {
  type: string
  userId?: string
  userName?: string
  documentId?: string
  timestamp?: number
  data?: any
  // Optional checkpoint metadata for chat/tool streams
  checkpoint_id?: string | number
  // Optional pipeline subscription metadata
  request_id?: string
  streams?: any[]
}

export interface WebSocketConnectionOptions {
  url: string
  documentId: string
  userId: string
  userName: string
  protocols?: string[]
  reconnectInterval?: number
  maxReconnectAttempts?: number
  heartbeatInterval?: number
  enableHeartbeat?: boolean
}

export interface WebSocketEventHandlers {
  onConnect?: () => void
  onDisconnect?: () => void
  onMessage?: (message: WebSocketMessage) => void
  onError?: (error: Event) => void
  onReconnecting?: (attempt: number) => void
  onReconnectFailed?: () => void
}

export class WebSocketManager {
  private ws: WebSocket | null = null
  private options: WebSocketConnectionOptions
  private handlers: WebSocketEventHandlers
  private reconnectTimer: NodeJS.Timeout | null = null
  private heartbeatTimer: NodeJS.Timeout | null = null
  private reconnectAttempts = 0
  private isConnecting = false
  private isDestroyed = false
  private messageQueue: WebSocketMessage[] = []
  private lastPingTime = 0
  private latency = 0
  private connectStartedAt = 0
  private hasEverOpened = false
  private startupFailureCount = 0

  constructor(options: WebSocketConnectionOptions, handlers: WebSocketEventHandlers = {}) {
    this.options = {
      reconnectInterval: 1000,
      maxReconnectAttempts: 3,
      heartbeatInterval: 30000,
      ...options
    }
    this.handlers = handlers
  }

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      if (this.isDestroyed) {
        reject(new Error('WebSocketManager has been destroyed'))
        return
      }

      if (this.ws?.readyState === WebSocket.OPEN) {
        resolve()
        return
      }

      if (this.isConnecting) {
        return
      }

      if (!this.options.url || !this.options.url.trim()) {
        this.handlers.onReconnectFailed?.()
        reject(new Error('WebSocket URL is not configured'))
        return
      }

      if (isWsEndpointTemporarilyUnavailable(this.options.url)) {
        this.handlers.onReconnectFailed?.()
        reject(new Error(`WebSocket endpoint temporarily disabled: ${this.options.url}`))
        return
      }

      this.isConnecting = true
      this.connectStartedAt = Date.now()

      try {
        const query = new URLSearchParams({
          user_id: this.options.userId,
          user_name: this.options.userName,
          userId: this.options.userId,
          userName: this.options.userName,
        })
        const wsUrl = `${this.options.url}/${this.options.documentId}?${query.toString()}`
        this.ws = new WebSocket(wsUrl)

        const connectTimeout = setTimeout(() => {
          if (this.ws?.readyState !== WebSocket.OPEN) {
            this.ws?.close()
            reject(new Error('WebSocket connection timeout'))
          }
        }, 10000)

        this.ws.onopen = () => {
          clearTimeout(connectTimeout)
          this.isConnecting = false
          this.reconnectAttempts = 0
          this.hasEverOpened = true
          this.startupFailureCount = 0
          clearWsEndpointUnavailable(this.options.url)
          
          // Send join message
          this.send({
            type: 'join',
            userId: this.options.userId,
            userName: this.options.userName,
            documentId: this.options.documentId,
            timestamp: Date.now()
          })

          // Start heartbeat
          this.startHeartbeat()

          // Send queued messages
          this.flushMessageQueue()

          this.handlers.onConnect?.()
          resolve()
        }

        this.ws.onmessage = (event) => {
          try {
            const message: WebSocketMessage = JSON.parse(event.data)
            
            // Handle pong for latency calculation
            if (message.type === 'pong') {
              this.latency = Date.now() - this.lastPingTime
            }

            this.handlers.onMessage?.(message)
          } catch (error) {
            console.error('Failed to parse WebSocket message:', error)
          }
        }

        this.ws.onerror = (error) => {
          clearTimeout(connectTimeout)
          this.isConnecting = false
          this.handlers.onError?.(error)
          reject(error)
        }

        this.ws.onclose = (event) => {
          clearTimeout(connectTimeout)
          this.isConnecting = false
          this.stopHeartbeat()
          this.handlers.onDisconnect?.()

          const connectionLifetimeMs = Date.now() - this.connectStartedAt
          const startupFailure = !event.wasClean && !this.hasEverOpened && connectionLifetimeMs < 5000
          if (startupFailure) {
            this.startupFailureCount += 1
            if (this.startupFailureCount >= WS_STARTUP_FAILURE_THRESHOLD) {
              markWsEndpointUnavailable(this.options.url)
              this.handlers.onReconnectFailed?.()
              return
            }
          }

          if (!this.isDestroyed && !event.wasClean) {
            this.scheduleReconnect()
          }
        }
      } catch (error) {
        this.isConnecting = false
        reject(error)
      }
    })
  }

  disconnect(): void {
    this.isDestroyed = true
    this.stopReconnect()
    this.stopHeartbeat()
    
    if (this.ws) {
      // Send leave message before closing
      if (this.ws.readyState === WebSocket.OPEN) {
        this.send({
          type: 'leave',
          userId: this.options.userId,
          documentId: this.options.documentId,
          timestamp: Date.now()
        })
      }
      
      this.ws.close(1000, 'Normal closure')
      this.ws = null
    }
  }

  send(message: WebSocketMessage): boolean {
    if (this.ws?.readyState === WebSocket.OPEN) {
      try {
        this.ws.send(JSON.stringify(message))
        return true
      } catch (error) {
        console.error('Failed to send WebSocket message:', error)
        return false
      }
    } else {
      // Queue message for when connection is restored
      this.messageQueue.push(message)
      return false
    }
  }

  getConnectionState(): 'connecting' | 'open' | 'closing' | 'closed' {
    if (!this.ws) return 'closed'
    
    switch (this.ws.readyState) {
      case WebSocket.CONNECTING:
        return 'connecting'
      case WebSocket.OPEN:
        return 'open'
      case WebSocket.CLOSING:
        return 'closing'
      case WebSocket.CLOSED:
      default:
        return 'closed'
    }
  }

  getLatency(): number {
    return this.latency
  }

  getReconnectAttempts(): number {
    return this.reconnectAttempts
  }

  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }

  private scheduleReconnect(): void {
    if (this.isDestroyed || this.reconnectAttempts >= (this.options.maxReconnectAttempts || 10)) {
      this.handlers.onReconnectFailed?.()
      return
    }
    if (isWsEndpointTemporarilyUnavailable(this.options.url)) {
      this.handlers.onReconnectFailed?.()
      return
    }

    const delay = Math.min(
      this.options.reconnectInterval! * Math.pow(2, this.reconnectAttempts),
      30000 // Max 30 seconds
    )

    this.reconnectTimer = setTimeout(() => {
      if (!this.isDestroyed) {
        this.reconnectAttempts++
        this.handlers.onReconnecting?.(this.reconnectAttempts)
        this.connect().catch(() => {
          // Reconnection failed, scheduleReconnect will be called via onclose
        })
      }
    }, delay)
  }

  private stopReconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
  }

  private startHeartbeat(): void {
    this.stopHeartbeat()
    
    this.heartbeatTimer = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.lastPingTime = Date.now()
        this.send({ type: 'ping', timestamp: this.lastPingTime })
      }
    }, this.options.heartbeatInterval)
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
  }

  private flushMessageQueue(): void {
    while (this.messageQueue.length > 0 && this.ws?.readyState === WebSocket.OPEN) {
      const message = this.messageQueue.shift()!
      this.send(message)
    }
  }
}

// React hook for WebSocket management
import { useEffect, useRef, useState, useCallback } from 'react'

export interface UseWebSocketOptions extends WebSocketConnectionOptions {
  autoConnect?: boolean
}

export interface UseWebSocketReturn {
  connectionState: 'connecting' | 'open' | 'closing' | 'closed'
  latency: number
  reconnectAttempts: number
  isConnected: boolean
  connect: () => Promise<void>
  disconnect: () => void
  send: (message: WebSocketMessage) => boolean
  lastMessage: WebSocketMessage | null
  error: Event | null
}

export function useWebSocket(
  options: UseWebSocketOptions,
  handlers: WebSocketEventHandlers = {}
): UseWebSocketReturn {
  const wsManager = useRef<WebSocketManager | null>(null)
  const [connectionState, setConnectionState] = useState<'connecting' | 'open' | 'closing' | 'closed'>('closed')
  const [latency, setLatency] = useState(0)
  const [reconnectAttempts, setReconnectAttempts] = useState(0)
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null)
  const [error, setError] = useState<Event | null>(null)

  const connect = useCallback(async () => {
    if (!wsManager.current) return
    try {
      await wsManager.current.connect()
    } catch (err) {
      if (!(err instanceof Error && err.message.includes('temporarily disabled'))) {
        console.warn('WebSocket connection failed:', err)
      }
    }
  }, [])

  const disconnect = useCallback(() => {
    wsManager.current?.disconnect()
  }, [])

  const send = useCallback((message: WebSocketMessage) => {
    return wsManager.current?.send(message) || false
  }, [])

  useEffect(() => {
    const wsHandlers: WebSocketEventHandlers = {
      onConnect: () => {
        setConnectionState('open')
        setError(null)
        handlers.onConnect?.()
      },
      onDisconnect: () => {
        setConnectionState('closed')
        handlers.onDisconnect?.()
      },
      onMessage: (message) => {
        setLastMessage(message)
        handlers.onMessage?.(message)
      },
      onError: (err) => {
        setError(err)
        handlers.onError?.(err)
      },
      onReconnecting: (attempt) => {
        setConnectionState('connecting')
        setReconnectAttempts(attempt)
        handlers.onReconnecting?.(attempt)
      },
      onReconnectFailed: () => {
        setConnectionState('closed')
        handlers.onReconnectFailed?.()
      }
    }

    wsManager.current = new WebSocketManager(options, wsHandlers)

    // Auto-connect if enabled
    if (options.autoConnect !== false) {
      connect()
    }

    // Update state periodically
    const stateInterval = setInterval(() => {
      if (wsManager.current) {
        setConnectionState(wsManager.current.getConnectionState())
        setLatency(wsManager.current.getLatency())
        setReconnectAttempts(wsManager.current.getReconnectAttempts())
      }
    }, 1000)

    return () => {
      clearInterval(stateInterval)
      wsManager.current?.disconnect()
      wsManager.current = null
    }
  }, [connect, handlers, options])

  return {
    connectionState,
    latency,
    reconnectAttempts,
    isConnected: connectionState === 'open',
    connect,
    disconnect,
    send,
    lastMessage,
    error
  }
}
