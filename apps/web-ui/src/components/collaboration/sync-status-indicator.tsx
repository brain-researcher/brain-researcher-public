'use client'

import React, { useState, useEffect } from 'react'
import { SyncStatus, CollaborationState } from '@/types/collaboration-enhanced'
import { 
  Wifi, 
  WifiOff, 
  RefreshCw, 
  AlertTriangle, 
  CheckCircle, 
  Clock,
  Activity,
  SignalHigh,
  SignalLow,
  Signal,
  Zap
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'

interface SyncStatusIndicatorProps {
  status: SyncStatus
  collaborationState?: CollaborationState
  onRetryConnection?: () => void
  onForceSync?: () => void
  detailed?: boolean
  className?: string
}

export function SyncStatusIndicator({
  status,
  collaborationState,
  onRetryConnection,
  onForceSync,
  detailed = false,
  className = ''
}: SyncStatusIndicatorProps) {
  const [isVisible, setIsVisible] = useState(true)
  const [pulseCount, setPulseCount] = useState(0)

  // Auto-hide success messages after delay
  useEffect(() => {
    if (status.status === 'connected' && status.operationsQueue === 0) {
      const timer = setTimeout(() => {
        if (detailed) setIsVisible(false)
      }, 3000)
      return () => clearTimeout(timer)
    } else {
      setIsVisible(true)
    }
  }, [status.status, status.operationsQueue, detailed])

  // Pulse animation for syncing status
  useEffect(() => {
    if (status.status === 'syncing' || status.status === 'connecting') {
      const interval = setInterval(() => {
        setPulseCount(prev => prev + 1)
      }, 1000)
      return () => clearInterval(interval)
    }
  }, [status.status])

  /**
   * Get status configuration
   */
  const getStatusConfig = () => {
    switch (status.status) {
      case 'connected':
        return {
          icon: status.operationsQueue > 0 ? RefreshCw : CheckCircle,
          color: status.operationsQueue > 0 ? 'text-blue-500' : 'text-green-500',
          bgColor: status.operationsQueue > 0 ? 'bg-blue-50' : 'bg-green-50',
          borderColor: status.operationsQueue > 0 ? 'border-blue-200' : 'border-green-200',
          label: status.operationsQueue > 0 ? 'Syncing' : 'Connected',
          badgeVariant: status.operationsQueue > 0 ? 'default' as const : 'secondary' as const,
          animate: status.operationsQueue > 0
        }
      
      case 'connecting':
        return {
          icon: RefreshCw,
          color: 'text-yellow-500',
          bgColor: 'bg-yellow-50',
          borderColor: 'border-yellow-200',
          label: 'Connecting',
          badgeVariant: 'default' as const,
          animate: true
        }
      
      case 'syncing':
        return {
          icon: Activity,
          color: 'text-blue-500',
          bgColor: 'bg-blue-50',
          borderColor: 'border-blue-200',
          label: 'Syncing',
          badgeVariant: 'default' as const,
          animate: true
        }
      
      case 'conflict':
        return {
          icon: AlertTriangle,
          color: 'text-orange-500',
          bgColor: 'bg-orange-50',
          borderColor: 'border-orange-200',
          label: 'Conflicts',
          badgeVariant: 'destructive' as const,
          animate: false
        }
      
      case 'error':
        return {
          icon: WifiOff,
          color: 'text-red-500',
          bgColor: 'bg-red-50',
          borderColor: 'border-red-200',
          label: 'Error',
          badgeVariant: 'destructive' as const,
          animate: false
        }
      
      case 'disconnected':
      default:
        return {
          icon: WifiOff,
          color: 'text-gray-500',
          bgColor: 'bg-gray-50',
          borderColor: 'border-gray-200',
          label: 'Disconnected',
          badgeVariant: 'secondary' as const,
          animate: false
        }
    }
  }

  /**
   * Get network quality indicator
   */
  const getNetworkQuality = () => {
    if (!status.networkLatency) return null

    const latency = status.networkLatency
    
    if (latency < 100) {
      return { icon: SignalHigh, color: 'text-green-500', label: 'Excellent' }
    } else if (latency < 300) {
      return { icon: Signal, color: 'text-yellow-500', label: 'Good' }
    } else {
      return { icon: SignalLow, color: 'text-red-500', label: 'Poor' }
    }
  }

  /**
   * Format time ago
   */
  const formatTimeAgo = (date: Date) => {
    const now = new Date()
    const diffInSeconds = Math.floor((now.getTime() - date.getTime()) / 1000)
    
    if (diffInSeconds < 60) return `${diffInSeconds}s ago`
    if (diffInSeconds < 3600) return `${Math.floor(diffInSeconds / 60)}m ago`
    if (diffInSeconds < 86400) return `${Math.floor(diffInSeconds / 3600)}h ago`
    return `${Math.floor(diffInSeconds / 86400)}d ago`
  }

  const config = getStatusConfig()
  const networkQuality = getNetworkQuality()
  const Icon = config.icon

  // Simple indicator for non-detailed mode
  if (!detailed) {
    if (!isVisible && status.status === 'connected' && status.operationsQueue === 0) {
      return null
    }

    return (
      <div className={`flex items-center space-x-2 ${className}`}>
        <div className="flex items-center space-x-1">
          <Icon 
            className={`w-4 h-4 ${config.color} ${config.animate ? 'animate-spin' : ''}`} 
          />
          <span className="text-sm text-gray-600">{config.label}</span>
        </div>
        
        {status.operationsQueue > 0 && (
          <Badge variant={config.badgeVariant} className="text-xs">
            {status.operationsQueue} pending
          </Badge>
        )}
        
        {status.retryCount && status.retryCount > 0 && (
          <Badge variant="outline" className="text-xs">
            Retry {status.retryCount}
          </Badge>
        )}
      </div>
    )
  }

  // Detailed status card
  return (
    <Card className={`p-4 border-2 ${config.borderColor} ${config.bgColor} ${className}`}>
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center space-x-3">
          <Icon 
            className={`w-5 h-5 ${config.color} ${config.animate ? 'animate-spin' : ''}`} 
          />
          <div>
            <div className="flex items-center space-x-2">
              <span className="font-medium">{config.label}</span>
              <Badge variant={config.badgeVariant}>
                {status.status}
              </Badge>
            </div>
            
            {status.message && (
              <p className="text-sm text-gray-600 mt-1">{status.message}</p>
            )}
          </div>
        </div>

        {networkQuality && (
          <div className="flex items-center space-x-1 text-xs text-gray-500">
            <networkQuality.icon className={`w-3 h-3 ${networkQuality.color}`} />
            <span>{networkQuality.label}</span>
            <span>({status.networkLatency}ms)</span>
          </div>
        )}
      </div>

      {/* Status details */}
      <div className="grid grid-cols-2 gap-4 text-sm">
        <div>
          <div className="text-gray-500">Last Update</div>
          <div className="font-medium">{formatTimeAgo(status.lastUpdate)}</div>
        </div>
        
        <div>
          <div className="text-gray-500">Operations Queue</div>
          <div className="font-medium">
            {status.operationsQueue}
            {status.operationsQueue > 0 && (
              <span className="text-xs text-gray-500 ml-1">pending</span>
            )}
          </div>
        </div>
        
        {status.retryCount !== undefined && (
          <div>
            <div className="text-gray-500">Retry Count</div>
            <div className="font-medium">{status.retryCount}</div>
          </div>
        )}
        
        {collaborationState && (
          <div>
            <div className="text-gray-500">Document Version</div>
            <div className="font-medium">v{collaborationState.version}</div>
          </div>
        )}
      </div>

      {/* Collaboration state details */}
      {collaborationState && (
        <div className="mt-4 pt-3 border-t border-gray-200">
          <div className="grid grid-cols-3 gap-4 text-sm">
            <div className="text-center">
              <div className="text-lg font-bold text-blue-600">
                {collaborationState.activeUsers.length}
              </div>
              <div className="text-xs text-gray-500">Active Users</div>
            </div>
            
            <div className="text-center">
              <div className="text-lg font-bold text-green-600">
                {collaborationState.annotations.length}
              </div>
              <div className="text-xs text-gray-500">Annotations</div>
            </div>
            
            <div className="text-center">
              <div className="text-lg font-bold text-orange-600">
                {collaborationState.conflicts.length}
              </div>
              <div className="text-xs text-gray-500">Conflicts</div>
            </div>
          </div>
        </div>
      )}

      {/* Action buttons */}
      <div className="flex space-x-2 mt-4">
        {(status.status === 'error' || status.status === 'disconnected') && onRetryConnection && (
          <Button size="sm" onClick={onRetryConnection}>
            <RefreshCw className="w-3 h-3 mr-1" />
            Retry Connection
          </Button>
        )}
        
        {status.operationsQueue > 0 && onForceSync && (
          <Button size="sm" variant="outline" onClick={onForceSync}>
            <Zap className="w-3 h-3 mr-1" />
            Force Sync
          </Button>
        )}
        
        {status.status === 'conflict' && collaborationState && collaborationState.conflicts.length > 0 && (
          <Button size="sm" variant="outline">
            <AlertTriangle className="w-3 h-3 mr-1" />
            View Conflicts ({collaborationState.conflicts.length})
          </Button>
        )}
      </div>

      {/* Progress indicator for sync operations */}
      {status.operationsQueue > 0 && status.status === 'syncing' && (
        <div className="mt-3">
          <div className="flex items-center justify-between text-xs text-gray-500 mb-1">
            <span>Syncing operations...</span>
            <span>{status.operationsQueue} remaining</span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-1">
            <div 
              className="bg-blue-500 h-1 rounded-full transition-all duration-300"
              style={{ 
                width: `${Math.max(10, 100 - (status.operationsQueue * 10))}%` 
              }}
            />
          </div>
        </div>
      )}

      {/* Connection quality indicator */}
      {status.status === 'connected' && (
        <div className="mt-3 flex items-center justify-between text-xs text-gray-500">
          <div className="flex items-center space-x-2">
            <Wifi className="w-3 h-3" />
            <span>Connection stable</span>
          </div>
          
          <div className="flex items-center space-x-2">
            <Clock className="w-3 h-3" />
            <span>Last sync: {formatTimeAgo(collaborationState?.lastSynced || status.lastUpdate)}</span>
          </div>
        </div>
      )}
    </Card>
  )
}