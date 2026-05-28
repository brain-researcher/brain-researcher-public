'use client'

import React, { useEffect, useRef, useState, useCallback, useMemo } from 'react'
import { MousePointer, MousePointer2, Edit3, Eye } from 'lucide-react'
import { useWebSocket, WebSocketMessage } from '@/lib/websocket-manager'
import { resolveRealtimeWsBaseUrl } from '@/lib/service-endpoints'

export interface CursorPosition {
  userId: string
  userName: string
  x: number
  y: number
  color: string
  timestamp: number
  element?: string // CSS selector or element ID
  activity?: 'viewing' | 'editing' | 'selecting'
}

export interface TextSelection {
  userId: string
  userName: string
  startOffset: number
  endOffset: number
  text: string
  color: string
  element: string
  timestamp: number
}

export interface CollaborativeCursorsProps {
  documentId: string
  userId: string
  userName: string
  wsUrl?: string
  containerRef?: React.RefObject<HTMLElement>
  onCursorMove?: (cursor: CursorPosition) => void
  onSelection?: (selection: TextSelection) => void
  showUserNames?: boolean
  cursorSize?: 'sm' | 'md' | 'lg'
  fadeTimeout?: number
}

const CURSOR_COLORS = [
  '#EF4444', '#F97316', '#EAB308', '#22C55E', 
  '#06B6D4', '#3B82F6', '#8B5CF6', '#EC4899',
  '#F59E0B', '#10B981', '#6366F1', '#8B5A2B'
]

const getCursorColor = (userId: string): string => {
  let hash = 0
  for (let i = 0; i < userId.length; i++) {
    hash = ((hash << 5) - hash + userId.charCodeAt(i)) & 0xffffffff
  }
  return CURSOR_COLORS[Math.abs(hash) % CURSOR_COLORS.length]
}

export function CollaborativeCursors({
  documentId,
  userId,
  userName,
  wsUrl,
  containerRef,
  onCursorMove,
  onSelection,
  showUserNames = true,
  cursorSize = 'md',
  fadeTimeout = 5000
}: CollaborativeCursorsProps) {
  const resolvedWsUrl = wsUrl || resolveRealtimeWsBaseUrl()
  const [cursors, setCursors] = useState<Map<string, CursorPosition>>(new Map())
  const [selections, setSelections] = useState<Map<string, TextSelection>>(new Map())
  const [isTracking, setIsTracking] = useState(true)
  
  const lastMousePosition = useRef<{ x: number, y: number }>({ x: 0, y: 0 })
  const throttleTimer = useRef<NodeJS.Timeout | null>(null)
  const fadeTimers = useRef<Map<string, NodeJS.Timeout>>(new Map())
  const cursorActivity = useRef<Map<string, 'viewing' | 'editing' | 'selecting'>>(new Map())

  // WebSocket connection
  const { send, isConnected } = useWebSocket(
    {
      url: resolvedWsUrl,
      documentId,
      userId,
      userName,
      autoConnect: true
    },
    {
      onMessage: handleWebSocketMessage
    }
  )

  const cursorSizes = useMemo(() => ({
    sm: { size: 'w-3 h-3', text: 'text-xs' },
    md: { size: 'w-4 h-4', text: 'text-sm' },
    lg: { size: 'w-5 h-5', text: 'text-base' }
  }), [])

  function handleWebSocketMessage(message: WebSocketMessage) {
    switch (message.type) {
      case 'cursor':
        if (message.data && message.userId !== userId) {
          const cursor: CursorPosition = {
            ...message.data,
            color: getCursorColor(message.userId!),
            timestamp: Date.now()
          }
          
          setCursors(prev => {
            const next = new Map(prev)
            next.set(message.userId!, cursor)
            return next
          })

          // Set fade timer
          setFadeTimer(message.userId!)
          onCursorMove?.(cursor)
        }
        break

      case 'selection':
        if (message.data && message.userId !== userId) {
          if (message.data.cleared) {
            setSelections(prev => {
              const next = new Map(prev)
              next.delete(message.userId!)
              return next
            })
          } else {
            const selection: TextSelection = {
              ...message.data,
              color: getCursorColor(message.userId!),
              timestamp: Date.now()
            }
            
            setSelections(prev => {
              const next = new Map(prev)
              next.set(message.userId!, selection)
              return next
            })

            onSelection?.(selection)
          }
        }
        break

      case 'activity':
        if (message.data && message.userId !== userId) {
          cursorActivity.current.set(message.userId!, message.data.activity)
        }
        break

      case 'user_left':
        if (message.userId) {
          setCursors(prev => {
            const next = new Map(prev)
            next.delete(message.userId!)
            return next
          })
          setSelections(prev => {
            const next = new Map(prev)
            next.delete(message.userId!)
            return next
          })
          cursorActivity.current.delete(message.userId)
          clearFadeTimer(message.userId)
        }
        break
    }
  }

  const setFadeTimer = useCallback((targetUserId: string) => {
    // Clear existing timer
    clearFadeTimer(targetUserId)
    
    // Set new timer
    const timer = setTimeout(() => {
      setCursors(prev => {
        const next = new Map(prev)
        next.delete(targetUserId)
        return next
      })
      cursorActivity.current.delete(targetUserId)
    }, fadeTimeout)
    
    fadeTimers.current.set(targetUserId, timer)
  }, [fadeTimeout])

  const clearFadeTimer = useCallback((targetUserId: string) => {
    const timer = fadeTimers.current.get(targetUserId)
    if (timer) {
      clearTimeout(timer)
      fadeTimers.current.delete(targetUserId)
    }
  }, [])

  // Send cursor position with throttling
  const sendCursorPosition = useCallback((x: number, y: number, activity: 'viewing' | 'editing' | 'selecting' = 'viewing') => {
    if (!isConnected || !isTracking) return

    const element = document.elementFromPoint(x, y)
    const elementSelector = element ? getElementSelector(element) : undefined

    const cursor: Omit<CursorPosition, 'color' | 'timestamp'> = {
      userId,
      userName,
      x,
      y,
      element: elementSelector,
      activity
    }

    send({
      type: 'cursor',
      userId,
      userName,
      documentId,
      data: cursor,
      timestamp: Date.now()
    })
  }, [isConnected, isTracking, userId, userName, documentId, send])

  // Send text selection
  const sendSelection = useCallback((selection: Partial<TextSelection> | null) => {
    if (!isConnected || !isTracking) return

    send({
      type: 'selection',
      userId,
      userName,
      documentId,
      data: selection || { cleared: true },
      timestamp: Date.now()
    })
  }, [isConnected, isTracking, userId, userName, documentId, send])

  // Send activity change
  const sendActivity = useCallback((activity: 'viewing' | 'editing' | 'selecting') => {
    if (!isConnected) return

    send({
      type: 'activity',
      userId,
      userName,
      documentId,
      data: { activity },
      timestamp: Date.now()
    })
  }, [isConnected, userId, userName, documentId, send])

  // Mouse move handler with throttling
  const handleMouseMove = useCallback((event: MouseEvent) => {
    if (!isTracking) return

    lastMousePosition.current = { x: event.clientX, y: event.clientY }

    // Throttle cursor updates to 20fps
    if (throttleTimer.current) return

    throttleTimer.current = setTimeout(() => {
      sendCursorPosition(
        lastMousePosition.current.x, 
        lastMousePosition.current.y,
        'viewing'
      )
      throttleTimer.current = null
    }, 50)
  }, [isTracking, sendCursorPosition])

  // Selection change handler
  const handleSelectionChange = useCallback(() => {
    if (!isTracking) return

    const selection = window.getSelection()
    if (!selection || selection.rangeCount === 0) {
      sendSelection(null)
      return
    }

    const range = selection.getRangeAt(0)
    if (range.collapsed) {
      sendSelection(null)
      return
    }

    const element = range.commonAncestorContainer.nodeType === Node.ELEMENT_NODE 
      ? range.commonAncestorContainer as Element
      : range.commonAncestorContainer.parentElement

    if (element) {
      const textSelection: Omit<TextSelection, 'color' | 'timestamp'> = {
        userId,
        userName,
        startOffset: range.startOffset,
        endOffset: range.endOffset,
        text: range.toString(),
        element: getElementSelector(element)
      }

      sendSelection(textSelection)
      sendActivity('selecting')
    }
  }, [isTracking, userId, userName, sendSelection, sendActivity])

  // Focus/blur handlers to detect editing
  const handleFocus = useCallback((event: FocusEvent) => {
    const target = event.target as HTMLElement
    if (isEditableElement(target)) {
      sendActivity('editing')
    }
  }, [sendActivity])

  const handleBlur = useCallback(() => {
    sendActivity('viewing')
  }, [sendActivity])

  // Setup event listeners
  useEffect(() => {
    const container = containerRef?.current || document

    container.addEventListener('mousemove', handleMouseMove, { passive: true })
    document.addEventListener('selectionchange', handleSelectionChange)
    document.addEventListener('focusin', handleFocus)
    document.addEventListener('focusout', handleBlur)

    return () => {
      container.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('selectionchange', handleSelectionChange)
      document.removeEventListener('focusin', handleFocus)
      document.removeEventListener('focusout', handleBlur)
      
      if (throttleTimer.current) {
        clearTimeout(throttleTimer.current)
      }
      
      fadeTimers.current.forEach(timer => clearTimeout(timer))
      fadeTimers.current.clear()
    }
  }, [handleMouseMove, handleSelectionChange, handleFocus, handleBlur])

  // Render cursors
  const renderCursors = () => {
    return Array.from(cursors.values()).map(cursor => {
      const activity = cursorActivity.current.get(cursor.userId) || 'viewing'
      const { size, text } = cursorSizes[cursorSize]
      
      return (
        <div
          key={cursor.userId}
          className="fixed pointer-events-none z-50 transition-all duration-100 ease-out"
          style={{
            left: cursor.x,
            top: cursor.y,
            transform: 'translate(-2px, -2px)'
          }}
        >
          {/* Cursor icon */}
          <div className="relative">
            {activity === 'editing' ? (
              <Edit3 
                className={`${size} animate-pulse`}
                style={{ color: cursor.color, fill: cursor.color }}
              />
            ) : activity === 'selecting' ? (
              <MousePointer2
                className={size}
                style={{ color: cursor.color, fill: cursor.color }}
              />
            ) : (
              <MousePointer
                className={size}
                style={{ color: cursor.color, fill: cursor.color }}
              />
            )}
            
            {/* User name label */}
            {showUserNames && (
              <div
                className={`absolute top-5 left-0 px-2 py-1 rounded text-white font-medium whitespace-nowrap ${text}`}
                style={{ backgroundColor: cursor.color }}
              >
                {cursor.userName}
                {activity === 'editing' && (
                  <span className="ml-1 text-xs opacity-75">✏️</span>
                )}
                {activity === 'selecting' && (
                  <span className="ml-1 text-xs opacity-75">📝</span>
                )}
              </div>
            )}
          </div>
        </div>
      )
    })
  }

  // Render text selections
  const renderSelections = () => {
    return Array.from(selections.values()).map(selection => (
      <div
        key={selection.userId}
        className="selection-highlight"
        data-user-id={selection.userId}
        data-user-name={selection.userName}
        data-element={selection.element}
        style={{
          '--selection-color': selection.color,
          '--selection-opacity': '0.2'
        } as React.CSSProperties}
      />
    ))
  }

  // Toggle tracking
  const toggleTracking = useCallback(() => {
    setIsTracking(prev => !prev)
  }, [])

  return (
    <div className="collaborative-cursors">
      {/* Render cursors and selections */}
      {renderCursors()}
      {renderSelections()}
      
      {/* Control panel (optional) */}
      <div className="fixed bottom-4 right-20 z-40">
        <button
          onClick={toggleTracking}
          className={`px-3 py-2 rounded-full text-sm font-medium transition-colors ${
            isTracking 
              ? 'bg-green-500 text-white hover:bg-green-600' 
              : 'bg-gray-300 text-gray-700 hover:bg-gray-400'
          }`}
          title={`${isTracking ? 'Disable' : 'Enable'} cursor tracking`}
          aria-label={`${isTracking ? 'Disable' : 'Enable'} collaborative cursors`}
        >
          {isTracking ? <Eye className="w-4 h-4" /> : <Eye className="w-4 h-4 opacity-50" />}
        </button>
      </div>

      {/* CSS for text selections */}
      <style jsx>{`
        .selection-highlight {
          position: absolute;
          background-color: var(--selection-color);
          opacity: var(--selection-opacity);
          pointer-events: none;
          border-radius: 2px;
        }
        
        /* Hide browser's native selection highlighting for remote selections */
        .collaborative-selection::selection {
          background: transparent;
        }
      `}</style>
    </div>
  )
}

// Utility functions
function getElementSelector(element: Element): string {
  if (element.id) {
    return `#${element.id}`
  }
  
  if (element.className) {
    const classes = element.className.toString().split(/\s+/).slice(0, 2).join('.')
    return `.${classes}`
  }
  
  return element.tagName.toLowerCase()
}

function isEditableElement(element: HTMLElement): boolean {
  return element.isContentEditable || 
         element.tagName === 'INPUT' || 
         element.tagName === 'TEXTAREA' ||
         element.getAttribute('role') === 'textbox'
}
