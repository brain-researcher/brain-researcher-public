'use client'

import React, { useState, useEffect, useCallback, useRef } from 'react'
import { 
  Users, MessageSquare, Share2, Lock, Unlock, Eye, 
  Edit, UserPlus, Settings, Activity, AtSign, Hash,
  Send, Heart, ThumbsUp, Reply, MoreHorizontal,
  Circle, CheckCircle, X, XCircle, Clock, Bell,
  Link2, Copy, Mail, Globe, Shield, UserCheck
} from 'lucide-react'
import { useToast } from '@/hooks/use-toast'
import { resolveRealtimeWsBaseUrl } from '@/lib/service-endpoints'

interface User {
  id: string
  name: string
  email: string
  avatar?: string
  color: string
  status: 'online' | 'idle' | 'offline'
  lastSeen?: Date
  role?: 'owner' | 'editor' | 'viewer'
}

interface Comment {
  id: string
  userId: string
  userName: string
  userAvatar?: string
  content: string
  timestamp: Date
  likes: string[]
  replies?: Comment[]
  resolved?: boolean
  mentions?: string[]
  edited?: boolean
  editedAt?: Date
}

interface Activity {
  id: string
  type: 'edit' | 'comment' | 'share' | 'mention' | 'status'
  userId: string
  userName: string
  action: string
  target?: string
  timestamp: Date
  details?: any
}

interface ShareSettings {
  visibility: 'private' | 'team' | 'public'
  permissions: {
    canEdit: boolean
    canComment: boolean
    canShare: boolean
    canDownload: boolean
  }
  expiresAt?: Date
  password?: string
}

interface CursorPosition {
  userId: string
  x: number
  y: number
  timestamp: number
}

export function CollaborationFeatures({
  documentId,
  currentUser,
  onUserJoin,
  onUserLeave,
  className
}: {
  documentId: string
  currentUser: User
  onUserJoin?: (user: User) => void
  onUserLeave?: (userId: string) => void
  className?: string
}) {
  const { toast } = useToast()
  const [activeUsers, setActiveUsers] = useState<User[]>([currentUser])
  const [comments, setComments] = useState<Comment[]>([])
  const [activities, setActivities] = useState<Activity[]>([])
  const [showShareDialog, setShowShareDialog] = useState(false)
  const [showComments, setShowComments] = useState(false)
  const [showActivity, setShowActivity] = useState(false)
  const [cursors, setCursors] = useState<Map<string, CursorPosition>>(new Map())
  const [isTyping, setIsTyping] = useState<Set<string>>(new Set())
  const [mentions, setMentions] = useState<string[]>([])
  const [shareLink, setShareLink] = useState('')
  const [shareSettings, setShareSettings] = useState<ShareSettings>({
    visibility: 'private',
    permissions: {
      canEdit: false,
      canComment: true,
      canShare: false,
      canDownload: true
    }
  })

  // WebSocket connection ref
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout>()
  const typingTimeoutRef = useRef<NodeJS.Timeout>()

  // Initialize WebSocket connection
  useEffect(() => {
    const connectWebSocket = () => {
      try {
        // In production, use actual WebSocket URL
        const wsUrl = resolveRealtimeWsBaseUrl()
        wsRef.current = new WebSocket(`${wsUrl}/collaboration/${documentId}`)

        wsRef.current.onopen = () => {
          console.log('WebSocket connected')
          // Send join message
          wsRef.current?.send(JSON.stringify({
            type: 'join',
            user: currentUser,
            documentId
          }))
        }

        wsRef.current.onmessage = (event) => {
          const message = JSON.parse(event.data)
          handleWebSocketMessage(message)
        }

        wsRef.current.onerror = (error) => {
          console.error('WebSocket error:', error)
        }

        wsRef.current.onclose = () => {
          console.log('WebSocket disconnected')
          // Attempt reconnect after 3 seconds
          reconnectTimeoutRef.current = setTimeout(connectWebSocket, 3000)
        }
      } catch (error) {
        console.error('Failed to connect WebSocket:', error)
      }
    }

    // Best-effort: connect to collaboration WS if available; otherwise keep local-only state.
    connectWebSocket()

    return () => {
      if (wsRef.current) {
        wsRef.current.close()
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
    }
  }, [documentId, currentUser])

  // Handle WebSocket messages
  const handleWebSocketMessage = (message: any) => {
    switch (message.type) {
      case 'user-joined':
        setActiveUsers(prev => [...prev, message.user])
        if (onUserJoin) onUserJoin(message.user)
        break
      case 'user-left':
        setActiveUsers(prev => prev.filter(u => u.id !== message.userId))
        if (onUserLeave) onUserLeave(message.userId)
        break
      case 'cursor-move':
        setCursors(prev => {
          const updated = new Map(prev)
          updated.set(message.userId, message.position)
          return updated
        })
        break
      case 'comment-added':
        setComments(prev => [...prev, message.comment])
        break
      case 'typing-start':
        setIsTyping(prev => new Set(prev).add(message.userId))
        break
      case 'typing-stop':
        setIsTyping(prev => {
          const updated = new Set(prev)
          updated.delete(message.userId)
          return updated
        })
        break
      case 'activity':
        setActivities(prev => [message.activity, ...prev].slice(0, 50))
        break
    }
  }

  // Send cursor position
  const sendCursorPosition = useCallback((x: number, y: number) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'cursor-move',
        userId: currentUser.id,
        position: { userId: currentUser.id, x, y, timestamp: Date.now() }
      }))
    }
  }, [currentUser.id])

  // Handle mouse move for cursor tracking
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      sendCursorPosition(e.clientX, e.clientY)
    }

    // Throttle cursor updates
    let lastUpdate = 0
    const throttledHandler = (e: MouseEvent) => {
      const now = Date.now()
      if (now - lastUpdate > 50) {
        handleMouseMove(e)
        lastUpdate = now
      }
    }

    window.addEventListener('mousemove', throttledHandler)
    return () => window.removeEventListener('mousemove', throttledHandler)
  }, [sendCursorPosition])

  // Presence Indicator Component
  const PresenceIndicator = () => (
    <div className="flex items-center space-x-2">
      <div className="flex -space-x-2">
        {activeUsers.slice(0, 3).map(user => (
          <div
            key={user.id}
            className="relative group"
            title={`${user.name} (${user.status})`}
          >
            <div
              className="w-8 h-8 rounded-full border-2 border-white dark:border-gray-900 flex items-center justify-center text-xs font-medium text-white"
              style={{ backgroundColor: user.color }}
            >
              {user.avatar ? (
                <img src={user.avatar} alt={user.name} className="w-full h-full rounded-full" />
              ) : (
                user.name.split(' ').map(n => n[0]).join('')
              )}
            </div>
            <div className={`absolute bottom-0 right-0 w-2.5 h-2.5 rounded-full border-2 border-white dark:border-gray-900 ${
              user.status === 'online' ? 'bg-green-500' :
              user.status === 'idle' ? 'bg-yellow-500' :
              'bg-gray-400'
            }`} />
          </div>
        ))}
        {activeUsers.length > 3 && (
          <div className="w-8 h-8 rounded-full bg-gray-200 dark:bg-gray-700 border-2 border-white dark:border-gray-900 flex items-center justify-center text-xs font-medium">
            +{activeUsers.length - 3}
          </div>
        )}
      </div>
      <span className="text-sm text-gray-500">
        {activeUsers.length} {activeUsers.length === 1 ? 'user' : 'users'} online
      </span>
    </div>
  )

  // Comments Panel Component
  const CommentsPanel = () => {
    const [newComment, setNewComment] = useState('')
    const [replyTo, setReplyTo] = useState<string | null>(null)

    const handleAddComment = () => {
      if (newComment.trim()) {
        const comment: Comment = {
          id: Date.now().toString(),
          userId: currentUser.id,
          userName: currentUser.name,
          userAvatar: currentUser.avatar,
          content: newComment,
          timestamp: new Date(),
          likes: [],
          mentions: extractMentions(newComment)
        }

        if (replyTo) {
          const parentComment = comments.find(c => c.id === replyTo)
          if (parentComment) {
            parentComment.replies = [...(parentComment.replies || []), comment]
            setComments([...comments])
          }
        } else {
          setComments([...comments, comment])
        }

        // Send via WebSocket
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({
            type: 'comment-add',
            comment
          }))
        }

        setNewComment('')
        setReplyTo(null)
        
        toast({
          title: 'Comment added',
          description: 'Your comment has been posted'
        })
      }
    }

    const extractMentions = (text: string): string[] => {
      const mentions = text.match(/@(\w+)/g) || []
      return mentions.map(m => m.substring(1))
    }

    const handleTyping = () => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({
          type: 'typing-start',
          userId: currentUser.id
        }))
      }

      if (typingTimeoutRef.current) {
        clearTimeout(typingTimeoutRef.current)
      }

      typingTimeoutRef.current = setTimeout(() => {
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({
            type: 'typing-stop',
            userId: currentUser.id
          }))
        }
      }, 1000)
    }

    return (
      <div className="fixed right-0 top-0 h-full w-96 bg-white dark:bg-gray-900 border-l shadow-xl z-40 flex flex-col">
        <div className="p-4 border-b flex items-center justify-between">
          <h3 className="font-semibold flex items-center space-x-2">
            <MessageSquare className="w-5 h-5" />
            <span>Comments ({comments.length})</span>
          </h3>
          <button
            onClick={() => setShowComments(false)}
            className="p-1 hover:bg-gray-100 dark:hover:bg-gray-800 rounded"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {comments.map(comment => (
            <CommentItem
              key={comment.id}
              comment={comment}
              currentUserId={currentUser.id}
              onReply={() => setReplyTo(comment.id)}
              onLike={(commentId) => {
                const c = comments.find(com => com.id === commentId)
                if (c) {
                  if (c.likes.includes(currentUser.id)) {
                    c.likes = c.likes.filter(id => id !== currentUser.id)
                  } else {
                    c.likes.push(currentUser.id)
                  }
                  setComments([...comments])
                }
              }}
            />
          ))}
        </div>

        {/* Typing indicators */}
        {isTyping.size > 0 && (
          <div className="px-4 py-2 text-sm text-gray-500">
            {Array.from(isTyping).map(userId => {
              const user = activeUsers.find(u => u.id === userId)
              return user?.name
            }).filter(Boolean).join(', ')} {isTyping.size === 1 ? 'is' : 'are'} typing...
          </div>
        )}

        <div className="p-4 border-t">
          {replyTo && (
            <div className="mb-2 text-sm text-gray-500 flex items-center justify-between">
              <span>Replying to comment</span>
              <button onClick={() => setReplyTo(null)} className="text-blue-600">
                Cancel
              </button>
            </div>
          )}
          <div className="flex space-x-2">
            <input
              type="text"
              value={newComment}
              onChange={(e) => {
                setNewComment(e.target.value)
                handleTyping()
              }}
              onKeyPress={(e) => e.key === 'Enter' && handleAddComment()}
              placeholder="Add a comment..."
              className="flex-1 px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button
              onClick={handleAddComment}
              className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600"
            >
              <Send className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    )
  }

  // Comment Item Component
  const CommentItem = ({ comment, currentUserId, onReply, onLike }: any) => (
    <div className="space-y-2">
      <div className="flex items-start space-x-3">
        <div
          className="w-8 h-8 rounded-full bg-gradient-to-r from-blue-500 to-purple-500 flex items-center justify-center text-white text-xs font-medium"
        >
          {comment.userAvatar ? (
            <img src={comment.userAvatar} alt="" className="w-full h-full rounded-full" />
          ) : (
            comment.userName.split(' ').map((n: string) => n[0]).join('')
          )}
        </div>
        <div className="flex-1">
          <div className="flex items-center space-x-2">
            <span className="font-medium text-sm">{comment.userName}</span>
            <span className="text-xs text-gray-500">
              {new Date(comment.timestamp).toLocaleTimeString()}
            </span>
            {comment.edited && (
              <span className="text-xs text-gray-500">(edited)</span>
            )}
          </div>
          <p className="text-sm mt-1">{comment.content}</p>
          <div className="flex items-center space-x-4 mt-2">
            <button
              onClick={() => onLike(comment.id)}
              className="text-xs text-gray-500 hover:text-blue-600 flex items-center space-x-1"
            >
              <ThumbsUp className="w-3 h-3" />
              <span>{comment.likes.length}</span>
            </button>
            <button
              onClick={onReply}
              className="text-xs text-gray-500 hover:text-blue-600 flex items-center space-x-1"
            >
              <Reply className="w-3 h-3" />
              <span>Reply</span>
            </button>
          </div>
        </div>
      </div>
      
      {comment.replies && comment.replies.length > 0 && (
        <div className="ml-11 space-y-2">
          {comment.replies.map((reply: Comment) => (
            <CommentItem
              key={reply.id}
              comment={reply}
              currentUserId={currentUserId}
              onReply={() => {}}
              onLike={onLike}
            />
          ))}
        </div>
      )}
    </div>
  )

  // Share Dialog Component
  const ShareDialog = () => (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
      <div className="bg-white dark:bg-gray-900 rounded-xl max-w-md w-full p-6">
        <h3 className="text-lg font-semibold mb-4">Share Document</h3>

        {/* Visibility Settings */}
        <div className="space-y-3 mb-4">
          <label className="flex items-center justify-between p-3 border rounded-lg cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800">
            <div className="flex items-center space-x-3">
              <Lock className="w-5 h-5 text-gray-500" />
              <div>
                <div className="font-medium">Private</div>
                <div className="text-sm text-gray-500">Only specific people can access</div>
              </div>
            </div>
            <input
              type="radio"
              name="visibility"
              checked={shareSettings.visibility === 'private'}
              onChange={() => setShareSettings({ ...shareSettings, visibility: 'private' })}
              className="w-4 h-4"
            />
          </label>

          <label className="flex items-center justify-between p-3 border rounded-lg cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800">
            <div className="flex items-center space-x-3">
              <Users className="w-5 h-5 text-gray-500" />
              <div>
                <div className="font-medium">Team</div>
                <div className="text-sm text-gray-500">Anyone in your team can access</div>
              </div>
            </div>
            <input
              type="radio"
              name="visibility"
              checked={shareSettings.visibility === 'team'}
              onChange={() => setShareSettings({ ...shareSettings, visibility: 'team' })}
              className="w-4 h-4"
            />
          </label>

          <label className="flex items-center justify-between p-3 border rounded-lg cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800">
            <div className="flex items-center space-x-3">
              <Globe className="w-5 h-5 text-gray-500" />
              <div>
                <div className="font-medium">Public</div>
                <div className="text-sm text-gray-500">Anyone with the link can access</div>
              </div>
            </div>
            <input
              type="radio"
              name="visibility"
              checked={shareSettings.visibility === 'public'}
              onChange={() => setShareSettings({ ...shareSettings, visibility: 'public' })}
              className="w-4 h-4"
            />
          </label>
        </div>

        {/* Permissions */}
        <div className="space-y-2 mb-4">
          <h4 className="font-medium text-sm">Permissions</h4>
          {Object.entries(shareSettings.permissions).map(([key, value]) => (
            <label key={key} className="flex items-center justify-between">
              <span className="text-sm capitalize">{key.replace('can', 'Can ')}</span>
              <input
                type="checkbox"
                checked={value}
                onChange={(e) => setShareSettings({
                  ...shareSettings,
                  permissions: { ...shareSettings.permissions, [key]: e.target.checked }
                })}
                className="w-4 h-4 rounded"
              />
            </label>
          ))}
        </div>

        {/* Share Link */}
        <div className="mb-4">
          <label className="text-sm font-medium">Share Link</label>
          <div className="flex space-x-2 mt-1">
            <input
              type="text"
              value={`https://app.brainresearcher.ai/share/${documentId}`}
              readOnly
              className="flex-1 px-3 py-2 border rounded-lg bg-gray-50 dark:bg-gray-800"
            />
            <button
              onClick={() => {
                navigator.clipboard.writeText(`https://app.brainresearcher.ai/share/${documentId}`)
                toast({ title: 'Link copied!' })
              }}
              className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600"
            >
              <Copy className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Actions */}
        <div className="flex justify-end space-x-2">
          <button
            onClick={() => setShowShareDialog(false)}
            className="px-4 py-2 text-gray-600 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg"
          >
            Cancel
          </button>
          <button
            onClick={() => {
              // Save share settings
              toast({ title: 'Share settings updated' })
              setShowShareDialog(false)
            }}
            className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600"
          >
            Save & Share
          </button>
        </div>
      </div>
    </div>
  )

  // Activity Feed Component
  const ActivityFeed = () => (
    <div className="absolute top-12 right-0 w-80 bg-white dark:bg-gray-900 rounded-lg shadow-xl border p-4 max-h-96 overflow-y-auto z-30">
      <h3 className="font-semibold mb-3 flex items-center space-x-2">
        <Activity className="w-4 h-4" />
        <span>Activity Feed</span>
      </h3>
      <div className="space-y-3">
        {activities.map(activity => (
          <div key={activity.id} className="flex items-start space-x-3 text-sm">
            <div className={`w-2 h-2 rounded-full mt-1.5 ${
              activity.type === 'edit' ? 'bg-blue-500' :
              activity.type === 'comment' ? 'bg-green-500' :
              activity.type === 'share' ? 'bg-purple-500' :
              'bg-gray-500'
            }`} />
            <div className="flex-1">
              <p>
                <span className="font-medium">{activity.userName}</span>{' '}
                {activity.action}
              </p>
              <p className="text-xs text-gray-500">
                {new Date(activity.timestamp).toLocaleTimeString()}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )

  // Collaborative Cursors
  const CollaborativeCursors = () => (
    <>
      {Array.from(cursors.values()).map(cursor => {
        const user = activeUsers.find(u => u.id === cursor.userId)
        if (!user || user.id === currentUser.id) return null
        
        return (
          <div
            key={cursor.userId}
            className="fixed pointer-events-none z-50 transition-all duration-75"
            style={{
              left: cursor.x,
              top: cursor.y,
              transform: 'translate(-50%, -50%)'
            }}
          >
            <div
              className="w-4 h-4 rounded-full border-2 border-white"
              style={{ backgroundColor: user.color }}
            />
            <div
              className="absolute top-4 left-0 px-2 py-1 rounded text-xs text-white whitespace-nowrap"
              style={{ backgroundColor: user.color }}
            >
              {user.name}
            </div>
          </div>
        )
      })}
    </>
  )

  return (
    <div className={`${className || ''}`}>
      {/* Main Toolbar */}
      <div className="flex items-center justify-between p-4 border-b">
        <PresenceIndicator />
        
        <div className="flex items-center space-x-2">
          <button
            onClick={() => setShowComments(!showComments)}
            className="relative p-2 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg"
          >
            <MessageSquare className="w-5 h-5" />
            {comments.length > 0 && (
              <span className="absolute top-0 right-0 w-2 h-2 bg-red-500 rounded-full" />
            )}
          </button>
          
          <button
            onClick={() => setShowActivity(!showActivity)}
            className="p-2 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg"
          >
            <Activity className="w-5 h-5" />
          </button>
          
          <button
            onClick={() => setShowShareDialog(true)}
            className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 flex items-center space-x-2"
          >
            <Share2 className="w-4 h-4" />
            <span>Share</span>
          </button>
        </div>
      </div>

      {/* Comments Panel */}
      {showComments && <CommentsPanel />}
      
      {/* Activity Feed */}
      {showActivity && <ActivityFeed />}
      
      {/* Share Dialog */}
      {showShareDialog && <ShareDialog />}
      
      {/* Collaborative Cursors */}
      <CollaborativeCursors />
    </div>
  )
}

export default CollaborationFeatures
