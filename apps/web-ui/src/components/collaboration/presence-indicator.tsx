'use client'

import React, { useState, useEffect, useCallback, useMemo } from 'react'
import { 
  Users, Wifi, WifiOff, Circle, Activity, 
  Eye, Edit3, MessageCircle, Clock, Settings,
  ChevronDown, ChevronUp, UserX, Volume2, VolumeX
} from 'lucide-react'
import { useWebSocket, WebSocketMessage } from '@/lib/websocket-manager'
import { resolveRealtimeWsBaseUrl } from '@/lib/service-endpoints'

export interface PresenceUser {
  id: string
  name: string
  email?: string
  avatar?: string
  color: string
  status: 'online' | 'away' | 'idle' | 'offline'
  lastSeen: number
  currentActivity?: 'viewing' | 'editing' | 'commenting' | 'idle'
  currentPage?: string
  cursor?: { x: number; y: number }
  permissions?: 'owner' | 'editor' | 'viewer'
}

export interface PresenceIndicatorProps {
  documentId: string
  currentUser: {
    id: string
    name: string
    email?: string
    avatar?: string
  }
  wsUrl?: string
  maxVisibleUsers?: number
  showActivityIndicators?: boolean
  enableSounds?: boolean
  onUserClick?: (user: PresenceUser) => void
  onInviteUser?: () => void
  className?: string
}

const PRESENCE_COLORS = [
  '#EF4444', '#F97316', '#EAB308', '#22C55E',
  '#06B6D4', '#3B82F6', '#8B5CF6', '#EC4899',
  '#F59E0B', '#10B981', '#6366F1', '#8B5A2B'
]

const getPresenceColor = (userId: string): string => {
  let hash = 0
  for (let i = 0; i < userId.length; i++) {
    hash = ((hash << 5) - hash + userId.charCodeAt(i)) & 0xffffffff
  }
  return PRESENCE_COLORS[Math.abs(hash) % PRESENCE_COLORS.length]
}

export function PresenceIndicator({
  documentId,
  currentUser,
  wsUrl,
  maxVisibleUsers = 8,
  showActivityIndicators = true,
  enableSounds = true,
  onUserClick,
  onInviteUser,
  className = ''
}: PresenceIndicatorProps) {
  const resolvedWsUrl = wsUrl || resolveRealtimeWsBaseUrl()
  const [users, setUsers] = useState<Map<string, PresenceUser>>(new Map())
  const [isExpanded, setIsExpanded] = useState(false)
  const [connectionStatus, setConnectionStatus] = useState<'connecting' | 'connected' | 'disconnected'>('connecting')
  const [soundEnabled, setSoundEnabled] = useState(enableSounds)
  
  // Create current user presence object
  const currentUserPresence: PresenceUser = useMemo(() => ({
    id: currentUser.id,
    name: currentUser.name,
    email: currentUser.email,
    avatar: currentUser.avatar,
    color: getPresenceColor(currentUser.id),
    status: 'online',
    lastSeen: Date.now(),
    currentActivity: 'viewing',
    permissions: 'owner' // Assume current user is owner for now
  }), [currentUser])

  // WebSocket connection
  const { send, isConnected, latency } = useWebSocket(
    {
      url: resolvedWsUrl,
      documentId,
      userId: currentUser.id,
      userName: currentUser.name,
      autoConnect: true
    },
    {
      onConnect: () => setConnectionStatus('connected'),
      onDisconnect: () => setConnectionStatus('disconnected'),
      onReconnecting: () => setConnectionStatus('connecting'),
      onMessage: handleWebSocketMessage
    }
  )

  // Update connection status based on WebSocket state
  useEffect(() => {
    setConnectionStatus(isConnected ? 'connected' : 'connecting')
  }, [isConnected])

  function handleWebSocketMessage(message: WebSocketMessage) {
    switch (message.type) {
      case 'user_joined':
        if (message.userId !== currentUser.id) {
          playSound('join')
          const newUser: PresenceUser = {
            id: message.userId!,
            name: message.userName || 'Anonymous',
            color: getPresenceColor(message.userId!),
            status: 'online',
            lastSeen: Date.now(),
            currentActivity: 'viewing',
            permissions: 'viewer'
          }
          
          setUsers(prev => {
            const next = new Map(prev)
            next.set(message.userId!, newUser)
            return next
          })
        }
        break

      case 'user_left':
        if (message.userId !== currentUser.id) {
          playSound('leave')
          setUsers(prev => {
            const next = new Map(prev)
            next.delete(message.userId!)
            return next
          })
        }
        break

      case 'presence_update':
        if (message.userId !== currentUser.id && message.data) {
          setUsers(prev => {
            const next = new Map(prev)
            const existingUser = next.get(message.userId!)
            if (existingUser) {
              next.set(message.userId!, {
                ...existingUser,
                ...message.data,
                lastSeen: Date.now()
              })
            }
            return next
          })
        }
        break

      case 'users_list':
        if (message.data?.users) {
          const userMap = new Map<string, PresenceUser>()
          message.data.users.forEach((user: any) => {
            if (user.id !== currentUser.id) {
              userMap.set(user.id, {
                ...user,
                color: getPresenceColor(user.id),
                lastSeen: Date.now()
              })
            }
          })
          setUsers(userMap)
        }
        break

      case 'activity_update':
        if (message.userId !== currentUser.id && message.data) {
          updateUserActivity(message.userId!, message.data.activity)
        }
        break
    }
  }

  const updateUserActivity = useCallback((userId: string, activity: string) => {
    setUsers(prev => {
      const next = new Map(prev)
      const user = next.get(userId)
      if (user) {
        next.set(userId, {
          ...user,
          currentActivity: activity as PresenceUser['currentActivity'],
          lastSeen: Date.now()
        })
      }
      return next
    })
  }, [])

  const sendPresenceUpdate = useCallback((updates: Partial<PresenceUser>) => {
    if (!isConnected) return

    send({
      type: 'presence_update',
      userId: currentUser.id,
      userName: currentUser.name,
      documentId,
      data: updates,
      timestamp: Date.now()
    })
  }, [isConnected, send, currentUser, documentId])

  const playSound = useCallback((type: 'join' | 'leave' | 'mention') => {
    if (!soundEnabled) return

    // Create audio context for sound effects
    try {
      const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)()
      const oscillator = audioContext.createOscillator()
      const gainNode = audioContext.createGain()

      oscillator.connect(gainNode)
      gainNode.connect(audioContext.destination)

      // Different frequencies for different events
      switch (type) {
        case 'join':
          oscillator.frequency.setValueAtTime(800, audioContext.currentTime)
          oscillator.frequency.exponentialRampToValueAtTime(1000, audioContext.currentTime + 0.1)
          break
        case 'leave':
          oscillator.frequency.setValueAtTime(600, audioContext.currentTime)
          oscillator.frequency.exponentialRampToValueAtTime(400, audioContext.currentTime + 0.1)
          break
        case 'mention':
          oscillator.frequency.setValueAtTime(1200, audioContext.currentTime)
          break
      }

      gainNode.gain.setValueAtTime(0.1, audioContext.currentTime)
      gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.1)

      oscillator.start(audioContext.currentTime)
      oscillator.stop(audioContext.currentTime + 0.1)
    } catch (error) {
      // Fallback to system sounds if available
      console.log('Audio notification:', type)
    }
  }, [soundEnabled])

  // Auto-update user idle status
  useEffect(() => {
    const interval = setInterval(() => {
      const now = Date.now()
      const idleThreshold = 30000 // 30 seconds
      const awayThreshold = 300000 // 5 minutes

      setUsers(prev => {
        const next = new Map(prev)
        for (const [userId, user] of Array.from(next.entries())) {
          const timeSinceLastSeen = now - user.lastSeen
          let newStatus = user.status

          if (timeSinceLastSeen > awayThreshold) {
            newStatus = 'away'
          } else if (timeSinceLastSeen > idleThreshold) {
            newStatus = 'idle'
          } else {
            newStatus = 'online'
          }

          if (newStatus !== user.status) {
            next.set(userId, { ...user, status: newStatus })
          }
        }
        return next
      })
    }, 5000)

    return () => clearInterval(interval)
  }, [])

  // Send activity updates
  useEffect(() => {
    let lastActivity = Date.now()
    
    const handleActivity = () => {
      lastActivity = Date.now()
      sendPresenceUpdate({ 
        status: 'online', 
        lastSeen: lastActivity,
        currentActivity: 'viewing'
      })
    }

    const events = ['mousedown', 'mousemove', 'keypress', 'scroll', 'touchstart']
    events.forEach(event => {
      document.addEventListener(event, handleActivity, { passive: true })
    })

    return () => {
      events.forEach(event => {
        document.removeEventListener(event, handleActivity)
      })
    }
  }, [sendPresenceUpdate])

  const allUsers = useMemo(() => {
    return [currentUserPresence, ...Array.from(users.values())]
      .sort((a, b) => {
        // Sort by status (online first) then by name
        if (a.status !== b.status) {
          const statusOrder = { online: 0, idle: 1, away: 2, offline: 3 }
          return statusOrder[a.status] - statusOrder[b.status]
        }
        return a.name.localeCompare(b.name)
      })
  }, [currentUserPresence, users])

  const visibleUsers = useMemo(() => {
    return allUsers.slice(0, maxVisibleUsers)
  }, [allUsers, maxVisibleUsers])

  const hiddenUsersCount = Math.max(0, allUsers.length - maxVisibleUsers)

  const getStatusColor = (status: PresenceUser['status']) => {
    switch (status) {
      case 'online': return 'bg-green-400'
      case 'idle': return 'bg-yellow-400'
      case 'away': return 'bg-orange-400'
      case 'offline': return 'bg-gray-400'
      default: return 'bg-gray-400'
    }
  }

  const getActivityIcon = (activity?: PresenceUser['currentActivity']) => {
    switch (activity) {
      case 'editing': return <Edit3 className="w-3 h-3" />
      case 'commenting': return <MessageCircle className="w-3 h-3" />
      case 'viewing': return <Eye className="w-3 h-3" />
      default: return null
    }
  }

  const formatLastSeen = (lastSeen: number) => {
    const diff = Date.now() - lastSeen
    const minutes = Math.floor(diff / 60000)
    const hours = Math.floor(diff / 3600000)
    
    if (minutes < 1) return 'now'
    if (minutes < 60) return `${minutes}m ago`
    if (hours < 24) return `${hours}h ago`
    return 'offline'
  }

  return (
    <div className={`presence-indicator ${className}`}>
      {/* Main presence bar */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700">
        <div className="flex items-center justify-between p-3">
          {/* Connection status */}
          <div className="flex items-center space-x-2">
            {connectionStatus === 'connected' ? (
              <Wifi className="w-4 h-4 text-green-500" />
            ) : connectionStatus === 'connecting' ? (
              <Activity className="w-4 h-4 text-yellow-500 animate-pulse" />
            ) : (
              <WifiOff className="w-4 h-4 text-red-500" />
            )}
            <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
              {allUsers.length} {allUsers.length === 1 ? 'user' : 'users'}
            </span>
            {connectionStatus === 'connected' && latency > 0 && (
              <span className="text-xs text-gray-500">
                ({latency}ms)
              </span>
            )}
          </div>

          {/* User avatars */}
          <div className="flex items-center space-x-1">
            <div className="flex -space-x-2">
              {visibleUsers.map(user => (
                <div
                  key={user.id}
                  className="relative group cursor-pointer"
                  onClick={() => onUserClick?.(user)}
                  title={`${user.name} (${user.status})`}
                >
                  {/* Avatar */}
                  <div
                    className="w-8 h-8 rounded-full border-2 border-white dark:border-gray-800 flex items-center justify-center text-white text-xs font-medium shadow-sm hover:scale-110 transition-transform"
                    style={{ backgroundColor: user.color }}
                  >
                    {user.avatar ? (
                      <img 
                        src={user.avatar} 
                        alt={user.name}
                        className="w-full h-full rounded-full object-cover"
                      />
                    ) : (
                      user.name.charAt(0).toUpperCase()
                    )}
                  </div>

                  {/* Status indicator */}
                  <div className={`absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full border-2 border-white dark:border-gray-800 ${getStatusColor(user.status)}`} />

                  {/* Activity indicator */}
                  {showActivityIndicators && user.currentActivity && user.currentActivity !== 'viewing' && (
                    <div className="absolute -top-1 -right-1 text-gray-600 dark:text-gray-400">
                      {getActivityIcon(user.currentActivity)}
                    </div>
                  )}

                  {/* Tooltip */}
                  <div className="absolute bottom-full left-1/2 transform -translate-x-1/2 mb-2 px-3 py-1 bg-black text-white text-xs rounded whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-50">
                    <div className="font-medium">{user.name}</div>
                    <div className="text-gray-300">
                      {user.status} • {formatLastSeen(user.lastSeen)}
                    </div>
                    {user.currentActivity && user.currentActivity !== 'viewing' && (
                      <div className="text-gray-300 capitalize">
                        {user.currentActivity}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>

            {/* Show more button */}
            {hiddenUsersCount > 0 && (
              <button
                onClick={() => setIsExpanded(!isExpanded)}
                className="w-8 h-8 rounded-full bg-gray-200 dark:bg-gray-700 hover:bg-gray-300 dark:hover:bg-gray-600 flex items-center justify-center text-xs font-medium text-gray-600 dark:text-gray-300 transition-colors"
                title={`${hiddenUsersCount} more ${hiddenUsersCount === 1 ? 'user' : 'users'}`}
              >
                +{hiddenUsersCount}
              </button>
            )}

            {/* Controls */}
            <div className="flex items-center space-x-1 ml-2">
              <button
                onClick={() => setSoundEnabled(!soundEnabled)}
                className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded transition-colors"
                title={`${soundEnabled ? 'Disable' : 'Enable'} notification sounds`}
              >
                {soundEnabled ? (
                  <Volume2 className="w-4 h-4 text-gray-600 dark:text-gray-400" />
                ) : (
                  <VolumeX className="w-4 h-4 text-gray-600 dark:text-gray-400" />
                )}
              </button>

              {onInviteUser && (
                <button
                  onClick={onInviteUser}
                  className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded transition-colors text-blue-500 hover:text-blue-600"
                  title="Invite users"
                >
                  <Users className="w-4 h-4" />
                </button>
              )}

              <button
                onClick={() => setIsExpanded(!isExpanded)}
                className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded transition-colors"
                title="Toggle expanded view"
              >
                {isExpanded ? (
                  <ChevronUp className="w-4 h-4 text-gray-600 dark:text-gray-400" />
                ) : (
                  <ChevronDown className="w-4 h-4 text-gray-600 dark:text-gray-400" />
                )}
              </button>
            </div>
          </div>
        </div>

        {/* Expanded user list */}
        {isExpanded && (
          <div className="border-t border-gray-200 dark:border-gray-700 p-3 max-h-60 overflow-y-auto">
            <div className="space-y-2">
              {allUsers.map(user => (
                <div
                  key={user.id}
                  className="flex items-center justify-between p-2 hover:bg-gray-50 dark:hover:bg-gray-700 rounded cursor-pointer"
                  onClick={() => onUserClick?.(user)}
                >
                  <div className="flex items-center space-x-3">
                    <div className="relative">
                      <div
                        className="w-6 h-6 rounded-full flex items-center justify-center text-white text-xs font-medium"
                        style={{ backgroundColor: user.color }}
                      >
                        {user.avatar ? (
                          <img 
                            src={user.avatar} 
                            alt={user.name}
                            className="w-full h-full rounded-full object-cover"
                          />
                        ) : (
                          user.name.charAt(0).toUpperCase()
                        )}
                      </div>
                      <div className={`absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border border-white dark:border-gray-700 ${getStatusColor(user.status)}`} />
                    </div>
                    
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center space-x-2">
                        <span className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
                          {user.name}
                          {user.id === currentUser.id && (
                            <span className="text-xs text-gray-500 ml-1">(you)</span>
                          )}
                        </span>
                        {showActivityIndicators && user.currentActivity && user.currentActivity !== 'viewing' && (
                          <div className="text-gray-500 dark:text-gray-400">
                            {getActivityIcon(user.currentActivity)}
                          </div>
                        )}
                      </div>
                      <div className="text-xs text-gray-500 capitalize">
                        {user.status} • {formatLastSeen(user.lastSeen)}
                        {user.permissions && (
                          <span className="ml-1">• {user.permissions}</span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
