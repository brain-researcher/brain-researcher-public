'use client'

import React, { useState, useEffect, useCallback, useRef } from 'react'
import { 
  Users, Wifi, WifiOff, Activity, 
  MousePointer, Type, Edit3, Save,
  AlertCircle, CheckCircle, XCircle
} from 'lucide-react'
import { resolveRealtimeWsBaseUrl } from '@/lib/service-endpoints'

interface CursorPosition {
  userId: string
  userName: string
  x: number
  y: number
  color: string
  timestamp: number
}

interface SelectionRange {
  userId: string
  userName: string
  startLine: number
  endLine: number
  startChar: number
  endChar: number
  color: string
}

interface LiveEdit {
  userId: string
  userName: string
  type: 'insert' | 'delete' | 'replace'
  position: { line: number; char: number }
  content?: string
  timestamp: number
}

interface RealtimeCollaborationProps {
  documentId: string
  userId: string
  userName: string
  wsUrl?: string
  onConnectionChange?: (connected: boolean) => void
  onUsersChange?: (users: string[]) => void
  onEditReceived?: (edit: LiveEdit) => void
}

export function RealtimeCollaboration({
  documentId,
  userId,
  userName,
  wsUrl,
  onConnectionChange,
  onUsersChange,
  onEditReceived
}: RealtimeCollaborationProps) {
  const resolvedWsUrl = wsUrl || resolveRealtimeWsBaseUrl()
  const [connected, setConnected] = useState(false)
  const [activeUsers, setActiveUsers] = useState<Map<string, any>>(new Map())
  const [cursors, setCursors] = useState<Map<string, CursorPosition>>(new Map())
  const [selections, setSelections] = useState<Map<string, SelectionRange>>(new Map())
  const [liveEdits, setLiveEdits] = useState<LiveEdit[]>([])
  const [latency, setLatency] = useState<number>(0)
  const [reconnectAttempts, setReconnectAttempts] = useState(0)
  
  const wsRef = useRef<WebSocket | null>(null)
  const pingIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const lastPingTime = useRef<number>(0)

  const userColors = [
    '#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', 
    '#FFEAA7', '#DDA0DD', '#98D8C8', '#F7DC6F'
  ]

  const getUserColor = useCallback((id: string) => {
    const hash = id.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0)
    return userColors[hash % userColors.length]
  }, [])

  const connectWebSocket = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    try {
      const ws = new WebSocket(`${resolvedWsUrl}/${documentId}`)
      wsRef.current = ws

      ws.onopen = () => {
        console.log('WebSocket connected')
        setConnected(true)
        setReconnectAttempts(0)
        onConnectionChange?.(true)

        // Send join message
        ws.send(JSON.stringify({
          type: 'join',
          userId,
          userName,
          documentId,
          timestamp: Date.now()
        }))

        // Start ping interval
        pingIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            lastPingTime.current = Date.now()
            ws.send(JSON.stringify({ type: 'ping' }))
          }
        }, 5000)
      }

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data)
        
        switch (data.type) {
          case 'pong':
            setLatency(Date.now() - lastPingTime.current)
            break
            
          case 'users':
            const users = new Map<string, any>(data.users.map((u: any) => [u.id, u]))
            setActiveUsers(users)
            onUsersChange?.(Array.from(users.keys()))
            break
            
          case 'cursor':
            if (data.userId !== userId) {
              setCursors(prev => {
                const next = new Map(prev)
                next.set(data.userId, {
                  userId: data.userId,
                  userName: data.userName,
                  x: data.x,
                  y: data.y,
                  color: getUserColor(data.userId),
                  timestamp: data.timestamp
                })
                return next
              })
            }
            break
            
          case 'selection':
            if (data.userId !== userId) {
              setSelections(prev => {
                const next = new Map(prev)
                if (data.cleared) {
                  next.delete(data.userId)
                } else {
                  next.set(data.userId, {
                    ...data,
                    color: getUserColor(data.userId)
                  })
                }
                return next
              })
            }
            break
            
          case 'edit':
            if (data.userId !== userId) {
              const edit: LiveEdit = {
                userId: data.userId,
                userName: data.userName,
                type: data.editType,
                position: data.position,
                content: data.content,
                timestamp: data.timestamp
              }
              setLiveEdits(prev => [...prev.slice(-50), edit])
              onEditReceived?.(edit)
            }
            break
            
          case 'user_joined':
            console.log(`${data.userName} joined`)
            break
            
          case 'user_left':
            console.log(`${data.userName} left`)
            setCursors(prev => {
              const next = new Map(prev)
              next.delete(data.userId)
              return next
            })
            setSelections(prev => {
              const next = new Map(prev)
              next.delete(data.userId)
              return next
            })
            break
        }
      }

      ws.onerror = (error) => {
        console.error('WebSocket error:', error)
      }

      ws.onclose = () => {
        console.log('WebSocket disconnected')
        setConnected(false)
        onConnectionChange?.(false)
        
        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current)
        }

        // Attempt reconnection with exponential backoff
        const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000)
        setReconnectAttempts(prev => prev + 1)
        
        reconnectTimeoutRef.current = setTimeout(() => {
          connectWebSocket()
        }, delay)
      }
    } catch (error) {
      console.error('Failed to connect WebSocket:', error)
      setConnected(false)
    }
  }, [documentId, userId, userName, resolvedWsUrl, getUserColor, onConnectionChange, onUsersChange, onEditReceived, reconnectAttempts])

  // Initialize WebSocket connection
  useEffect(() => {
    connectWebSocket()

    return () => {
      if (wsRef.current) {
        wsRef.current.close()
      }
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current)
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
    }
  }, [connectWebSocket])

  // Send cursor position
  const sendCursorPosition = useCallback((x: number, y: number) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'cursor',
        userId,
        userName,
        x,
        y,
        timestamp: Date.now()
      }))
    }
  }, [userId, userName])

  // Send selection
  const sendSelection = useCallback((selection: Partial<SelectionRange> | null) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'selection',
        userId,
        userName,
        ...selection,
        cleared: !selection,
        timestamp: Date.now()
      }))
    }
  }, [userId, userName])

  // Send edit
  const sendEdit = useCallback((edit: Omit<LiveEdit, 'userId' | 'userName' | 'timestamp'>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'edit',
        userId,
        userName,
        editType: edit.type,
        position: edit.position,
        content: edit.content,
        timestamp: Date.now()
      }))
    }
  }, [userId, userName])

  // Track mouse movement
  useEffect(() => {
    let lastSent = 0
    const handleMouseMove = (e: MouseEvent) => {
      const now = Date.now()
      if (now - lastSent > 50) { // Throttle to 20fps
        sendCursorPosition(e.clientX, e.clientY)
        lastSent = now
      }
    }

    if (connected) {
      document.addEventListener('mousemove', handleMouseMove)
    }

    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
    }
  }, [connected, sendCursorPosition])

  // Format latency display
  const formatLatency = (ms: number) => {
    if (ms < 50) return 'Excellent'
    if (ms < 100) return 'Good'
    if (ms < 200) return 'Fair'
    return 'Poor'
  }

  return (
    <div className="relative">
      {/* Connection Status Bar */}
      <div className="fixed top-0 left-0 right-0 z-50 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-10">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                {connected ? (
                  <>
                    <Wifi className="h-4 w-4 text-green-500" />
                    <span className="text-sm text-green-600 dark:text-green-400">Connected</span>
                  </>
                ) : (
                  <>
                    <WifiOff className="h-4 w-4 text-red-500 animate-pulse" />
                    <span className="text-sm text-red-600 dark:text-red-400">
                      Reconnecting... ({reconnectAttempts})
                    </span>
                  </>
                )}
              </div>
              
              {connected && latency > 0 && (
                <div className="flex items-center gap-2">
                  <Activity className="h-4 w-4 text-gray-500" />
                  <span className="text-sm text-gray-600 dark:text-gray-400">
                    {latency}ms ({formatLatency(latency)})
                  </span>
                </div>
              )}
            </div>

            <div className="flex items-center gap-2">
              <Users className="h-4 w-4 text-gray-500" />
              <span className="text-sm text-gray-600 dark:text-gray-400">
                {activeUsers.size} {activeUsers.size === 1 ? 'user' : 'users'} online
              </span>
              <div className="flex -space-x-2">
                {Array.from(activeUsers.values()).slice(0, 5).map(user => (
                  <div
                    key={user.id}
                    className="w-6 h-6 rounded-full border-2 border-white dark:border-gray-800 flex items-center justify-center text-white text-xs font-medium"
                    style={{ backgroundColor: getUserColor(user.id) }}
                    title={user.name}
                  >
                    {user.name.charAt(0).toUpperCase()}
                  </div>
                ))}
                {activeUsers.size > 5 && (
                  <div className="w-6 h-6 rounded-full bg-gray-300 dark:bg-gray-600 border-2 border-white dark:border-gray-800 flex items-center justify-center text-xs">
                    +{activeUsers.size - 5}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Remote Cursors */}
      {Array.from(cursors.values()).map(cursor => (
        <div
          key={cursor.userId}
          className="fixed pointer-events-none z-40 transition-all duration-100"
          style={{
            left: cursor.x,
            top: cursor.y,
            transform: 'translate(-50%, -50%)'
          }}
        >
          <MousePointer
            className="h-4 w-4"
            style={{ color: cursor.color, fill: cursor.color }}
          />
          <span
            className="absolute top-4 left-4 px-1 py-0.5 text-xs text-white rounded whitespace-nowrap"
            style={{ backgroundColor: cursor.color }}
          >
            {cursor.userName}
          </span>
        </div>
      ))}

      {/* Live Edit Indicators */}
      {liveEdits.length > 0 && (
        <div className="fixed bottom-4 left-4 max-w-sm z-40">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-lg p-3 space-y-2">
            <div className="text-xs font-medium text-gray-700 dark:text-gray-300">Live Edits</div>
            {liveEdits.slice(-3).map((edit, idx) => (
              <div key={idx} className="flex items-center gap-2 text-xs">
                <div
                  className="w-2 h-2 rounded-full"
                  style={{ backgroundColor: getUserColor(edit.userId) }}
                />
                <span className="text-gray-600 dark:text-gray-400">
                  {edit.userName} {edit.type === 'insert' ? 'added' : edit.type === 'delete' ? 'removed' : 'changed'} text
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Selection Highlights (would be rendered in the actual document) */}
      <div className="hidden">
        {Array.from(selections.values()).map(selection => (
          <div key={selection.userId} data-selection={JSON.stringify(selection)} />
        ))}
      </div>
    </div>
  )
}
