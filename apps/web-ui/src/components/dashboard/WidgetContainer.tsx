'use client'

import React, { useState } from 'react'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { 
  MoreVertical,
  Settings,
  Trash2,
  RefreshCw,
  Eye,
  EyeOff,
  Maximize2,
  Minimize2
} from 'lucide-react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Widget, WidgetComponentProps } from '@/types/dashboard'
import { getWidgetComponent } from './widget-library'

interface WidgetContainerProps {
  widget: Widget
  data?: any
  loading?: boolean
  error?: string
  isEditing?: boolean
  onUpdate?: (updates: Partial<Widget>) => void
  onRemove?: () => void
  onRefresh?: () => void
  onConfigure?: () => void
  className?: string
}

export const WidgetContainer: React.FC<WidgetContainerProps> = ({
  widget,
  data,
  loading = false,
  error,
  isEditing = false,
  onUpdate,
  onRemove,
  onRefresh,
  onConfigure,
  className = ''
}) => {
  const [isHovered, setIsHovered] = useState(false)
  const [isMaximized, setIsMaximized] = useState(false)

  const WidgetComponent = getWidgetComponent(widget.type)

  const handleConfigChange = (config: any) => {
    if (onUpdate) {
      onUpdate({
        config: { ...widget.config, ...config },
        updated_at: new Date()
      })
    }
  }

  const handleVisibilityToggle = () => {
    if (onUpdate) {
      onUpdate({
        visible: !widget.visible,
        updated_at: new Date()
      })
    }
  }

  const handleMaximizeToggle = () => {
    setIsMaximized(!isMaximized)
  }

  if (!WidgetComponent) {
    return (
      <Card className={`h-full ${className} border-dashed border-2`}>
        <div className="flex flex-col items-center justify-center h-full p-4 text-muted-foreground">
          <div className="text-2xl mb-2">⚠️</div>
          <p className="text-sm text-center">Widget type '{widget.type}' not found</p>
        </div>
      </Card>
    )
  }

  const widgetProps: WidgetComponentProps = {
    widget,
    data,
    loading,
    error,
    onConfigChange: handleConfigChange,
    onRemove,
    onRefresh
  }

  return (
    <div 
      className={`relative h-full group ${className}`}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {/* Widget Content */}
      <div 
        className={`h-full transition-all duration-200 ${
          isMaximized ? 'fixed inset-4 z-50 rounded-lg shadow-2xl' : ''
        } ${
          !widget.visible ? 'opacity-50' : ''
        } ${
          isEditing ? 'ring-2 ring-blue-200 hover:ring-blue-300' : ''
        }`}
      >
        <WidgetComponent {...widgetProps} />
        
        {/* Widget Controls Overlay */}
        {(isEditing || isHovered) && (
          <div className="absolute top-2 right-2 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity duration-200">
            {/* Visibility Toggle */}
            <Button
              variant="secondary"
              size="sm"
              className="h-6 w-6 p-0 bg-white/80 backdrop-blur-sm hover:bg-white/90"
              onClick={handleVisibilityToggle}
            >
              {widget.visible ? (
                <Eye className="h-3 w-3" />
              ) : (
                <EyeOff className="h-3 w-3" />
              )}
            </Button>

            {/* Maximize Toggle */}
            <Button
              variant="secondary"
              size="sm"
              className="h-6 w-6 p-0 bg-white/80 backdrop-blur-sm hover:bg-white/90"
              onClick={handleMaximizeToggle}
            >
              {isMaximized ? (
                <Minimize2 className="h-3 w-3" />
              ) : (
                <Maximize2 className="h-3 w-3" />
              )}
            </Button>

            {/* Widget Menu */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="secondary"
                  size="sm"
                  className="h-6 w-6 p-0 bg-white/80 backdrop-blur-sm hover:bg-white/90"
                >
                  <MoreVertical className="h-3 w-3" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-48">
                {onRefresh && (
                  <DropdownMenuItem onClick={onRefresh}>
                    <RefreshCw className="h-4 w-4 mr-2" />
                    Refresh Data
                  </DropdownMenuItem>
                )}
                {onConfigure && (
                  <DropdownMenuItem onClick={onConfigure}>
                    <Settings className="h-4 w-4 mr-2" />
                    Configure Widget
                  </DropdownMenuItem>
                )}
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={handleVisibilityToggle}
                  className="text-orange-600"
                >
                  {widget.visible ? (
                    <>
                      <EyeOff className="h-4 w-4 mr-2" />
                      Hide Widget
                    </>
                  ) : (
                    <>
                      <Eye className="h-4 w-4 mr-2" />
                      Show Widget
                    </>
                  )}
                </DropdownMenuItem>
                {isEditing && onRemove && (
                  <DropdownMenuItem
                    onClick={onRemove}
                    className="text-red-600"
                  >
                    <Trash2 className="h-4 w-4 mr-2" />
                    Remove Widget
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        )}

        {/* Edit Mode Overlay */}
        {isEditing && (
          <div className="absolute inset-0 border-2 border-dashed border-blue-300 rounded-lg pointer-events-none">
            <div className="absolute -top-6 left-0 bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded-t">
              {widget.title || widget.type}
            </div>
          </div>
        )}

        {/* Loading Overlay */}
        {loading && (
          <div className="absolute inset-0 bg-white/50 backdrop-blur-sm flex items-center justify-center rounded-lg">
            <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary"></div>
          </div>
        )}
      </div>

      {/* Maximize Backdrop */}
      {isMaximized && (
        <div 
          className="fixed inset-0 bg-black/20 backdrop-blur-sm z-40"
          onClick={handleMaximizeToggle}
        />
      )}
    </div>
  )
}