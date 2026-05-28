import * as React from "react"
import { 
  Bell, 
  BellOff, 
  Volume2, 
  VolumeX, 
  Trash2, 
  CheckCircle, 
  AlertCircle, 
  AlertTriangle, 
  Info,
  Clock,
  X
} from "lucide-react"
import { cn } from "@/lib/utils"
import { useToast } from "@/hooks/use-toast"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import { Badge } from "@/components/ui/badge"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"

const notificationIcons = {
  success: CheckCircle,
  error: AlertCircle,
  warning: AlertTriangle,
  info: Info,
  loading: Clock,
  default: Bell,
}

const notificationColors = {
  success: "text-green-600 dark:text-green-400",
  error: "text-red-600 dark:text-red-400", 
  warning: "text-yellow-600 dark:text-yellow-400",
  info: "text-blue-600 dark:text-blue-400",
  loading: "text-gray-600 dark:text-gray-400",
  default: "text-gray-600 dark:text-gray-400",
}

function formatTimeAgo(date: Date): string {
  const now = new Date()
  const diffInSeconds = Math.floor((now.getTime() - date.getTime()) / 1000)
  
  if (diffInSeconds < 60) {
    return 'just now'
  } else if (diffInSeconds < 3600) {
    const minutes = Math.floor(diffInSeconds / 60)
    return `${minutes}m ago`
  } else if (diffInSeconds < 86400) {
    const hours = Math.floor(diffInSeconds / 3600)
    return `${hours}h ago`
  } else {
    const days = Math.floor(diffInSeconds / 86400)
    return `${days}d ago`
  }
}

interface NotificationCenterProps {
  className?: string
}

export const NotificationCenter: React.FC<NotificationCenterProps> = ({ 
  className 
}) => {
  const { 
    toasts, 
    history, 
    doNotDisturb, 
    soundEnabled,
    toggleDoNotDisturb, 
    toggleSound, 
    clearHistory, 
    dismiss 
  } = useToast()

  const [isOpen, setIsOpen] = React.useState(false)
  const unreadCount = toasts.length

  const handleDismissAll = () => {
    dismiss() // Dismiss all active toasts
  }

  const handleClearHistory = () => {
    clearHistory()
  }

  return (
    <Popover open={isOpen} onOpenChange={setIsOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className={cn("relative", className)}
          aria-label={`Notifications${unreadCount > 0 ? ` (${unreadCount} unread)` : ''}`}
        >
          {doNotDisturb ? (
            <BellOff className="h-5 w-5" />
          ) : (
            <Bell className="h-5 w-5" />
          )}
          {unreadCount > 0 && (
            <Badge 
              variant="destructive" 
              className="absolute -top-1 -right-1 h-5 w-5 rounded-full p-0 flex items-center justify-center text-xs"
            >
              {unreadCount > 9 ? '9+' : unreadCount}
            </Badge>
          )}
        </Button>
      </PopoverTrigger>
      
      <PopoverContent 
        className="w-96 p-0" 
        align="end"
        sideOffset={5}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b">
          <h3 className="text-lg font-semibold">Notifications</h3>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={toggleSound}
              className="h-8 w-8 p-0"
              title={soundEnabled ? "Disable sounds" : "Enable sounds"}
            >
              {soundEnabled ? (
                <Volume2 className="h-4 w-4" />
              ) : (
                <VolumeX className="h-4 w-4" />
              )}
            </Button>
            
            <Button
              variant="ghost"
              size="sm"
              onClick={toggleDoNotDisturb}
              className="h-8 w-8 p-0"
              title={doNotDisturb ? "Disable do not disturb" : "Enable do not disturb"}
            >
              {doNotDisturb ? (
                <BellOff className="h-4 w-4" />
              ) : (
                <Bell className="h-4 w-4" />
              )}
            </Button>
            
            {history.length > 0 && (
              <Button
                variant="ghost"
                size="sm"
                onClick={handleClearHistory}
                className="h-8 w-8 p-0"
                title="Clear history"
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            )}
          </div>
        </div>

        {/* Active Notifications */}
        {toasts.length > 0 && (
          <div className="p-4">
            <div className="flex items-center justify-between mb-3">
              <h4 className="text-sm font-medium">Active ({toasts.length})</h4>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleDismissAll}
                className="text-xs h-6"
              >
                Dismiss All
              </Button>
            </div>
            <div className="space-y-2">
              {toasts.map((toast) => {
                const IconComponent = notificationIcons[toast.type as keyof typeof notificationIcons] || notificationIcons.default
                const iconColor = notificationColors[toast.type as keyof typeof notificationColors] || notificationColors.default
                
                return (
                  <div
                    key={toast.id}
                    className="flex items-start gap-3 p-3 rounded-lg border bg-card text-card-foreground"
                  >
                    <IconComponent className={cn("h-4 w-4 shrink-0 mt-0.5", iconColor)} />
                    <div className="flex-1 min-w-0">
                      {toast.title && (
                        <div className="font-medium text-sm mb-1">
                          {toast.title}
                        </div>
                      )}
                      {toast.description && (
                        <div className="text-sm text-muted-foreground">
                          {toast.description}
                        </div>
                      )}
                      {toast.progress && (
                        <div className="mt-2">
                          <div className="w-full bg-secondary rounded-full h-1.5">
                            <div
                              className="bg-primary rounded-full h-1.5 transition-all duration-300"
                              style={{ width: `${toast.progress}%` }}
                            />
                          </div>
                        </div>
                      )}
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => dismiss(toast.id)}
                      className="h-auto p-1 hover:bg-muted"
                    >
                      <X className="h-3 w-3" />
                    </Button>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {toasts.length > 0 && history.length > 0 && <Separator />}

        {/* Notification History */}
        {history.length > 0 ? (
          <div className="p-4">
            <h4 className="text-sm font-medium mb-3">
              History ({history.length})
            </h4>
            <ScrollArea className="h-64">
              <div className="space-y-2">
                {history.map((notification, index) => {
                  const IconComponent = notificationIcons[notification.type as keyof typeof notificationIcons] || notificationIcons.default
                  const iconColor = notificationColors[notification.type as keyof typeof notificationColors] || notificationColors.default
                  
                  return (
                    <div
                      key={`${notification.id}-${index}`}
                      className="flex items-start gap-3 p-2 rounded-md hover:bg-muted/50"
                    >
                      <IconComponent className={cn("h-3 w-3 shrink-0 mt-1", iconColor)} />
                      <div className="flex-1 min-w-0">
                        {notification.title && (
                          <div className="font-medium text-xs mb-0.5">
                            {notification.title}
                          </div>
                        )}
                        {notification.description && (
                          <div className="text-xs text-muted-foreground mb-1">
                            {notification.description}
                          </div>
                        )}
                        {notification.timestamp && (
                          <div className="text-xs text-muted-foreground">
                            {formatTimeAgo(notification.timestamp)}
                          </div>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </ScrollArea>
          </div>
        ) : toasts.length === 0 ? (
          <div className="p-8 text-center text-muted-foreground">
            <Bell className="h-12 w-12 mx-auto mb-4 opacity-50" />
            <p className="text-sm">No notifications</p>
            <p className="text-xs mt-1">
              {doNotDisturb 
                ? "Do not disturb is enabled" 
                : "You'll see notifications here when they arrive"
              }
            </p>
          </div>
        ) : null}

        {/* Status Footer */}
        <div className="px-4 py-2 border-t bg-muted/20">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <div className="flex items-center gap-2">
              {doNotDisturb && (
                <Badge variant="secondary" className="text-xs">
                  Do Not Disturb
                </Badge>
              )}
              {!soundEnabled && (
                <Badge variant="outline" className="text-xs">
                  Sounds Off
                </Badge>
              )}
            </div>
            <div>
              Press Esc to dismiss all
            </div>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  )
}