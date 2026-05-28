export type NotificationPriority = 'low' | 'normal' | 'high' | 'urgent'

export type NotificationType =
  | 'job_complete'
  | 'job_failed'
  | 'system_alert'
  | 'dataset_available'
  | 'analysis_shared'
  | 'maintenance'
  | 'welcome'
  | string

export interface UserProfile {
  id: string
  username: string
  fullName?: string | null
  avatarUrl?: string | null
  role?: string | null
  unreadNotifications: number
  lastActivity?: string | null
}

export interface NotificationItem {
  id: string
  type: NotificationType
  priority: NotificationPriority
  title: string
  message: string
  read: boolean
  createdAt: string
  readAt?: string | null
  expiresAt?: string | null
  actionUrl?: string | null
  actionText?: string | null
  data?: Record<string, unknown>
}

export interface NotificationListResponse {
  notifications: NotificationItem[]
  unreadCount: number
  totalCount: number
  hasMore: boolean
  cursor?: string | null
  endpointSupported?: boolean
  endpointStatus?: 'unknown' | 'supported' | 'unsupported'
}
