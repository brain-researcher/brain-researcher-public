'use client'

import { useToast } from "@/hooks/use-toast"
import {
  Toast,
  ToastClose,
  ToastDescription,
  ToastProvider,
  ToastTitle,
  ToastViewport,
} from "@/components/ui/toast"
import { CheckCircle, AlertCircle, AlertTriangle, Info, Loader2 } from "lucide-react"
import { cn } from "@/lib/utils"

const notificationIcons = {
  success: CheckCircle,
  error: AlertCircle,
  warning: AlertTriangle,
  info: Info,
  loading: Loader2,
}

const notificationColors = {
  success: "text-green-600 dark:text-green-400",
  error: "text-red-600 dark:text-red-400", 
  warning: "text-yellow-600 dark:text-yellow-400",
  info: "text-blue-600 dark:text-blue-400",
  loading: "text-blue-600 dark:text-blue-400 animate-spin",
}

export function Toaster() {
  const { toasts } = useToast()

  return (
    <ToastProvider swipeDirection="right">
      {toasts.map(function ({ id, title, description, action, type, progress, ...props }) {
        const IconComponent = type ? notificationIcons[type as keyof typeof notificationIcons] : null
        const iconColor = type ? notificationColors[type as keyof typeof notificationColors] : ""

        return (
          <Toast key={id} {...props}>
            <div className="flex items-start gap-3 w-full">
              {IconComponent && (
                <div className="flex-shrink-0 mt-0.5">
                  <IconComponent className={cn("h-4 w-4", iconColor)} />
                </div>
              )}
              
              <div className="flex-1 min-w-0">
                <div className="grid gap-1">
                  {title && <ToastTitle>{title}</ToastTitle>}
                  {description && (
                    <ToastDescription>{description}</ToastDescription>
                  )}
                  
                  {progress !== undefined && (
                    <div className="mt-2">
                      <div className="w-full bg-secondary rounded-full h-2 overflow-hidden">
                        <div
                          className="bg-primary rounded-full h-2 transition-all duration-300 ease-out"
                          style={{ width: `${Math.max(0, Math.min(100, progress))}%` }}
                        />
                      </div>
                      <div className="text-xs text-muted-foreground mt-1">
                        {Math.round(progress)}% complete
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
            
            {action}
            <ToastClose />
          </Toast>
        )
      })}
      <ToastViewport />
    </ToastProvider>
  )
}