'use client'

import React, { useCallback, useMemo, useState } from 'react'
import { Responsive, WidthProvider } from 'react-grid-layout'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { 
  Edit3,
  Save,
  X,
  Plus,
  Download,
  Upload,
  RotateCcw,
  Grid,
  Eye,
  EyeOff,
  Settings2
} from 'lucide-react'
import { Widget, DashboardLayout, BreakpointLayouts, WidgetType } from '@/types/dashboard'
import { WidgetContainer } from './WidgetContainer'
import { WIDGET_CATALOG } from './widget-library'

const ResponsiveReactGridLayout = WidthProvider(Responsive)

interface DashboardCustomizerProps {
  layout: DashboardLayout
  onLayoutChange?: (layout: DashboardLayout) => void
  onSaveLayout?: () => void
  className?: string
}

export const DashboardCustomizer: React.FC<DashboardCustomizerProps> = ({
  layout,
  onLayoutChange,
  onSaveLayout,
  className = ''
}) => {
  const [isEditing, setIsEditing] = useState(false)
  const [widgetCatalogOpen, setWidgetCatalogOpen] = useState(false)
  const [selectedWidget, setSelectedWidget] = useState<Widget | null>(null)
  const [configPanelOpen, setConfigPanelOpen] = useState(false)

  // Convert widgets to grid layout format
  const generateLayouts = useCallback((widgets: Widget[]): BreakpointLayouts => {
    const visibleWidgets = widgets.filter(w => w.visible)
    
    return {
      lg: visibleWidgets.map(w => ({
        i: w.id,
        x: w.position.x,
        y: w.position.y,
        w: w.position.w,
        h: w.position.h,
        minW: w.position.minW,
        minH: w.position.minH,
        maxW: w.position.maxW,
        maxH: w.position.maxH
      })),
      md: visibleWidgets.map(w => ({
        i: w.id,
        x: Math.floor(w.position.x * 0.75),
        y: w.position.y,
        w: Math.max(2, Math.floor(w.position.w * 0.75)),
        h: w.position.h,
        minW: w.position.minW ? Math.floor(w.position.minW * 0.75) : undefined,
        minH: w.position.minH,
        maxW: w.position.maxW ? Math.floor(w.position.maxW * 0.75) : undefined,
        maxH: w.position.maxH
      })),
      sm: visibleWidgets.map(w => ({
        i: w.id,
        x: 0,
        y: w.position.y,
        w: 4,
        h: Math.max(4, w.position.h),
        minW: 4,
        minH: w.position.minH || 4,
        maxW: 4,
        maxH: w.position.maxH
      })),
      xs: visibleWidgets.map(w => ({
        i: w.id,
        x: 0,
        y: w.position.y,
        w: 2,
        h: Math.max(4, w.position.h),
        minW: 2,
        minH: w.position.minH || 4,
        maxW: 2,
        maxH: w.position.maxH
      }))
    }
  }, [])

  const layouts = useMemo(() => generateLayouts(layout.widgets), [layout.widgets, generateLayouts])

  const handleLayoutChange = useCallback((currentLayout: any, allLayouts: any) => {
    if (!onLayoutChange || !isEditing) return

    const updatedWidgets = layout.widgets.map(widget => {
      const gridItem = currentLayout.find((item: any) => item.i === widget.id)
      if (gridItem) {
        return {
          ...widget,
          position: {
            ...widget.position,
            x: gridItem.x,
            y: gridItem.y,
            w: gridItem.w,
            h: gridItem.h
          },
          updated_at: new Date()
        }
      }
      return widget
    })

    const updatedLayout = {
      ...layout,
      widgets: updatedWidgets,
      breakpoints: {
        lg: allLayouts.lg || layouts.lg,
        md: allLayouts.md || layouts.md,
        sm: allLayouts.sm || layouts.sm,
        xs: allLayouts.xs || layouts.xs
      },
      updated_at: new Date()
    }

    onLayoutChange(updatedLayout)
  }, [layout, onLayoutChange, isEditing, layouts])

  const handleAddWidget = useCallback((widgetType: WidgetType) => {
    if (!onLayoutChange) return

    const catalogItem = WIDGET_CATALOG.find(item => item.type === widgetType)
    if (!catalogItem) return

    // Find a good position for the new widget
    const existingPositions = layout.widgets.map(w => w.position)
    let newX = 0
    let newY = 0
    
    // Simple placement algorithm - find first available spot
    const gridWidth = 12
    for (let y = 0; y < 20; y++) {
      for (let x = 0; x <= gridWidth - catalogItem.defaultSize.w; x++) {
        const wouldOverlap = existingPositions.some(pos => 
          x < pos.x + pos.w && x + catalogItem.defaultSize.w > pos.x &&
          y < pos.y + pos.h && y + catalogItem.defaultSize.h > pos.y
        )
        if (!wouldOverlap) {
          newX = x
          newY = y
          break
        }
      }
      if (newX !== undefined) break
    }

    const newWidget: Widget = {
      id: `widget_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
      type: widgetType,
      title: catalogItem.name,
      position: {
        x: newX,
        y: newY,
        w: catalogItem.defaultSize.w,
        h: catalogItem.defaultSize.h,
        minW: catalogItem.minSize.w,
        minH: catalogItem.minSize.h,
        maxW: catalogItem.maxSize?.w,
        maxH: catalogItem.maxSize?.h
      },
      config: {
        showHeader: true,
        refreshInterval: 30000
      },
      visible: true,
      created_at: new Date(),
      updated_at: new Date()
    }

    const updatedLayout = {
      ...layout,
      widgets: [...layout.widgets, newWidget],
      updated_at: new Date()
    }

    onLayoutChange(updatedLayout)
    setWidgetCatalogOpen(false)
  }, [layout, onLayoutChange])

  const handleRemoveWidget = useCallback((widgetId: string) => {
    if (!onLayoutChange) return

    const updatedLayout = {
      ...layout,
      widgets: layout.widgets.filter(w => w.id !== widgetId),
      updated_at: new Date()
    }

    onLayoutChange(updatedLayout)
  }, [layout, onLayoutChange])

  const handleUpdateWidget = useCallback((widgetId: string, updates: Partial<Widget>) => {
    if (!onLayoutChange) return

    const updatedLayout = {
      ...layout,
      widgets: layout.widgets.map(w => 
        w.id === widgetId ? { ...w, ...updates } : w
      ),
      updated_at: new Date()
    }

    onLayoutChange(updatedLayout)
  }, [layout, onLayoutChange])

  const handleResetLayout = useCallback(() => {
    if (!onLayoutChange) return
    
    // Reset to a default layout with some basic widgets
    const defaultWidgets: Widget[] = [
      {
        id: 'analysis_queue',
        type: WidgetType.ANALYSIS_QUEUE,
        title: 'Analysis Queue',
        position: { x: 0, y: 0, w: 6, h: 8, minW: 4, minH: 6 },
        config: { showHeader: true, refreshInterval: 5000 },
        visible: true,
        created_at: new Date(),
        updated_at: new Date()
      },
      {
        id: 'recent_results',
        type: WidgetType.RECENT_RESULTS,
        title: 'Recent Results',
        position: { x: 6, y: 0, w: 6, h: 8, minW: 4, minH: 6 },
        config: { showHeader: true, refreshInterval: 10000 },
        visible: true,
        created_at: new Date(),
        updated_at: new Date()
      },
      {
        id: 'resource_usage',
        type: WidgetType.RESOURCE_USAGE,
        title: 'Resource Usage',
        position: { x: 0, y: 8, w: 8, h: 6, minW: 6, minH: 4 },
        config: { showHeader: true, refreshInterval: 3000 },
        visible: true,
        created_at: new Date(),
        updated_at: new Date()
      },
      {
        id: 'quick_actions',
        type: WidgetType.QUICK_ACTIONS,
        title: 'Quick Actions',
        position: { x: 8, y: 8, w: 4, h: 6, minW: 3, minH: 4 },
        config: { showHeader: true },
        visible: true,
        created_at: new Date(),
        updated_at: new Date()
      }
    ]

    const resetLayout: DashboardLayout = {
      ...layout,
      widgets: defaultWidgets,
      breakpoints: generateLayouts(defaultWidgets),
      updated_at: new Date()
    }

    onLayoutChange(resetLayout)
  }, [layout, onLayoutChange, generateLayouts])

  return (
    <div className={`relative ${className}`}>
      {/* Dashboard Controls */}
      <div className="flex items-center justify-between mb-4 p-4 bg-background border-b">
        <div className="flex items-center gap-2">
          <Grid className="h-5 w-5" />
          <h2 className="text-lg font-semibold">{layout.name}</h2>
          {layout.description && (
            <p className="text-sm text-muted-foreground">• {layout.description}</p>
          )}
        </div>
        
        <div className="flex items-center gap-2">
          {!isEditing ? (
            <Button 
              variant="outline" 
              onClick={() => setIsEditing(true)}
              className="gap-2"
            >
              <Edit3 className="h-4 w-4" />
              Customize
            </Button>
          ) : (
            <>
              <Dialog open={widgetCatalogOpen} onOpenChange={setWidgetCatalogOpen}>
                <DialogTrigger asChild>
                  <Button variant="outline" size="sm" className="gap-2">
                    <Plus className="h-4 w-4" />
                    Add Widget
                  </Button>
                </DialogTrigger>
                <DialogContent className="max-w-4xl">
                  <DialogHeader>
                    <DialogTitle>Add Widget</DialogTitle>
                    <DialogDescription>
                      Choose a widget to add to your dashboard
                    </DialogDescription>
                  </DialogHeader>
                  <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 p-4">
                    {WIDGET_CATALOG.map((widget) => (
                      <Card 
                        key={widget.type}
                        className="cursor-pointer hover:shadow-md transition-shadow"
                        onClick={() => handleAddWidget(widget.type)}
                      >
                        <CardHeader className="pb-2">
                          <div className="flex items-center gap-2">
                            {typeof widget.icon === 'function'
                              ? React.createElement(widget.icon as React.ElementType, { className: "h-4 w-4" })
                              : widget.icon}
                            <h3 className="text-sm font-medium">{widget.name}</h3>
                          </div>
                        </CardHeader>
                        <CardContent>
                          <p className="text-xs text-muted-foreground">
                            {widget.description}
                          </p>
                          <div className="flex flex-wrap gap-1 mt-2">
                            {widget.tags.slice(0, 2).map((tag) => (
                              <span 
                                key={tag}
                                className="px-1.5 py-0.5 text-xs bg-gray-100 rounded"
                              >
                                {tag}
                              </span>
                            ))}
                          </div>
                        </CardContent>
                      </Card>
                    ))}
                  </div>
                </DialogContent>
              </Dialog>

              <Button variant="outline" size="sm" onClick={handleResetLayout}>
                <RotateCcw className="h-4 w-4" />
              </Button>
              
              <Button variant="outline" size="sm">
                <Download className="h-4 w-4" />
              </Button>
              
              <Button variant="outline" size="sm">
                <Upload className="h-4 w-4" />
              </Button>

              <Button 
                onClick={() => {
                  setIsEditing(false)
                  onSaveLayout?.()
                }}
                size="sm"
                className="gap-2"
              >
                <Save className="h-4 w-4" />
                Save
              </Button>
              
              <Button 
                variant="ghost" 
                size="sm"
                onClick={() => setIsEditing(false)}
              >
                <X className="h-4 w-4" />
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Dashboard Grid */}
      <div className="p-4">
        <ResponsiveReactGridLayout
          className="layout"
          layouts={layouts}
          breakpoints={{ lg: 1200, md: 996, sm: 768, xs: 480 }}
          cols={{ lg: 12, md: 8, sm: 4, xs: 2 }}
          rowHeight={60}
          margin={[16, 16]}
          containerPadding={[0, 0]}
          isDraggable={isEditing}
          isResizable={isEditing}
          onLayoutChange={handleLayoutChange}
          useCSSTransforms={true}
          measureBeforeMount={false}
          draggableHandle=".widget-drag-handle"
        >
          {layout.widgets.filter(w => w.visible).map((widget) => (
            <div key={widget.id} className="relative">
              {isEditing && (
                <div className="widget-drag-handle absolute -top-6 left-0 right-0 h-6 bg-blue-100 border border-blue-200 rounded-t cursor-move flex items-center justify-center text-xs text-blue-600 opacity-0 hover:opacity-100 transition-opacity">
                  Drag to move • Resize from corners
                </div>
              )}
              <WidgetContainer
                widget={widget}
                isEditing={isEditing}
                onUpdate={(updates) => handleUpdateWidget(widget.id, updates)}
                onRemove={() => handleRemoveWidget(widget.id)}
                onConfigure={() => {
                  setSelectedWidget(widget)
                  setConfigPanelOpen(true)
                }}
              />
            </div>
          ))}
        </ResponsiveReactGridLayout>
      </div>

      {/* Widget Configuration Panel */}
      <Dialog open={configPanelOpen} onOpenChange={setConfigPanelOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Configure Widget</DialogTitle>
            <DialogDescription>
              Customize the settings for {selectedWidget?.title}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 p-4">
            <div className="text-sm text-muted-foreground">
              Widget configuration panel - coming soon
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setConfigPanelOpen(false)}>
                Cancel
              </Button>
              <Button onClick={() => setConfigPanelOpen(false)}>
                Save Changes
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}