'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import { DashboardLayout, Widget, WidgetType, DashboardState, DashboardActions } from '@/types/dashboard'
import { WIDGET_CATALOG } from '@/components/dashboard/widget-library'
import { serviceEndpoints } from '@/lib/service-endpoints'

const STORAGE_KEY = 'brain_researcher_dashboard_layouts'
const DEFAULT_LAYOUT_ID = 'default'

// Default dashboard layout
const createDefaultLayout = (): DashboardLayout => ({
  id: DEFAULT_LAYOUT_ID,
  name: 'Default Dashboard',
  description: 'Default layout with essential widgets',
  widgets: [
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
  ],
  breakpoints: {
    lg: [],
    md: [],
    sm: [],
    xs: []
  },
  isDefault: true,
  created_at: new Date(),
  updated_at: new Date()
})

// API functions for backend integration
const api = {
  async getLayouts(): Promise<DashboardLayout[]> {
    try {
      const response = await fetch(serviceEndpoints.orchestrator('/api/dashboard/layouts'))
      if (response.ok) {
        return await response.json()
      }
    } catch (error) {
      console.warn('Failed to fetch layouts from API, using localStorage:', error)
    }
    
    // Fallback to localStorage
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      try {
        const layouts = JSON.parse(stored)
        return Array.isArray(layouts) ? layouts : [createDefaultLayout()]
      } catch {
        return [createDefaultLayout()]
      }
    }
    return [createDefaultLayout()]
  },

  async saveLayout(layout: DashboardLayout): Promise<DashboardLayout> {
    try {
      const response = await fetch(serviceEndpoints.orchestrator('/api/dashboard/layouts'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(layout)
      })
      if (response.ok) {
        return await response.json()
      }
    } catch (error) {
      console.warn('Failed to save layout to API, using localStorage:', error)
    }
    
    // Fallback to localStorage
    const stored = localStorage.getItem(STORAGE_KEY)
    const layouts = stored ? JSON.parse(stored) : []
    const existingIndex = layouts.findIndex((l: DashboardLayout) => l.id === layout.id)
    
    if (existingIndex >= 0) {
      layouts[existingIndex] = layout
    } else {
      layouts.push(layout)
    }
    
    localStorage.setItem(STORAGE_KEY, JSON.stringify(layouts))
    return layout
  },

  async deleteLayout(layoutId: string): Promise<void> {
    try {
      const endpoint = serviceEndpoints.orchestrator(`/api/dashboard/layouts/${layoutId}`)
      const response = await fetch(endpoint, {
        method: 'DELETE'
      })
      if (response.ok) {
        return
      }
    } catch (error) {
      console.warn('Failed to delete layout from API, using localStorage:', error)
    }
    
    // Fallback to localStorage
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      const layouts = JSON.parse(stored)
      const filtered = layouts.filter((l: DashboardLayout) => l.id !== layoutId)
      localStorage.setItem(STORAGE_KEY, JSON.stringify(filtered))
    }
  }
}

export const useDashboardLayout = () => {
  const [state, setState] = useState<DashboardState>({
    currentLayout: null,
    availableLayouts: [],
    isEditing: false,
    selectedWidget: null,
    configPanelOpen: false
  })

  // Load layouts on mount
  useEffect(() => {
    const loadLayouts = async () => {
      try {
        const layouts = await api.getLayouts()
        const currentLayout = layouts.find(l => l.isDefault) || layouts[0] || createDefaultLayout()
        
        setState(prev => ({
          ...prev,
          currentLayout,
          availableLayouts: layouts
        }))
      } catch (error) {
        console.error('Failed to load dashboard layouts:', error)
        const defaultLayout = createDefaultLayout()
        setState(prev => ({
          ...prev,
          currentLayout: defaultLayout,
          availableLayouts: [defaultLayout]
        }))
      }
    }

    loadLayouts()
  }, [])

  const actions: DashboardActions = useMemo(() => ({
    loadLayout: async (layoutId: string) => {
      const layout = state.availableLayouts.find(l => l.id === layoutId)
      if (layout) {
        setState(prev => ({ ...prev, currentLayout: layout }))
      }
    },

    saveLayout: async (layout: DashboardLayout) => {
      try {
        const savedLayout = await api.saveLayout(layout)
        setState(prev => ({
          ...prev,
          currentLayout: savedLayout,
          availableLayouts: prev.availableLayouts.map(l => 
            l.id === savedLayout.id ? savedLayout : l
          )
        }))
      } catch (error) {
        console.error('Failed to save layout:', error)
        throw error
      }
    },

    createLayout: async (name: string, description?: string) => {
      const newLayout: DashboardLayout = {
        id: `layout_${Date.now()}`,
        name,
        description,
        widgets: [],
        breakpoints: { lg: [], md: [], sm: [], xs: [] },
        isDefault: false,
        created_at: new Date(),
        updated_at: new Date()
      }

      try {
        const savedLayout = await api.saveLayout(newLayout)
        setState(prev => ({
          ...prev,
          availableLayouts: [...prev.availableLayouts, savedLayout]
        }))
        return savedLayout
      } catch (error) {
        console.error('Failed to create layout:', error)
        throw error
      }
    },

    deleteLayout: async (layoutId: string) => {
      if (layoutId === DEFAULT_LAYOUT_ID) {
        throw new Error('Cannot delete default layout')
      }

      try {
        await api.deleteLayout(layoutId)
        setState(prev => {
          const newAvailableLayouts = prev.availableLayouts.filter(l => l.id !== layoutId)
          const newCurrentLayout = prev.currentLayout?.id === layoutId 
            ? newAvailableLayouts[0] || createDefaultLayout()
            : prev.currentLayout

          return {
            ...prev,
            currentLayout: newCurrentLayout,
            availableLayouts: newAvailableLayouts
          }
        })
      } catch (error) {
        console.error('Failed to delete layout:', error)
        throw error
      }
    },

    duplicateLayout: async (layoutId: string, newName: string) => {
      const originalLayout = state.availableLayouts.find(l => l.id === layoutId)
      if (!originalLayout) {
        throw new Error('Layout not found')
      }

      const duplicatedLayout: DashboardLayout = {
        ...originalLayout,
        id: `layout_${Date.now()}`,
        name: newName,
        isDefault: false,
        created_at: new Date(),
        updated_at: new Date(),
        widgets: originalLayout.widgets.map(w => ({
          ...w,
          id: `widget_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
          created_at: new Date(),
          updated_at: new Date()
        }))
      }

      try {
        const savedLayout = await api.saveLayout(duplicatedLayout)
        setState(prev => ({
          ...prev,
          availableLayouts: [...prev.availableLayouts, savedLayout]
        }))
        return savedLayout
      } catch (error) {
        console.error('Failed to duplicate layout:', error)
        throw error
      }
    },

    exportLayout: async (layoutId: string) => {
      const layout = state.availableLayouts.find(l => l.id === layoutId)
      if (!layout) {
        throw new Error('Layout not found')
      }

      const exportData = {
        version: '1.0',
        exported_at: new Date().toISOString(),
        layout: {
          ...layout,
          id: undefined, // Remove ID for import
          created_at: undefined,
          updated_at: undefined
        }
      }

      return JSON.stringify(exportData, null, 2)
    },

    importLayout: async (layoutData: string) => {
      try {
        const importData = JSON.parse(layoutData)
        if (!importData.layout) {
          throw new Error('Invalid layout data')
        }

        const importedLayout: DashboardLayout = {
          ...importData.layout,
          id: `layout_${Date.now()}`,
          name: `${importData.layout.name} (Imported)`,
          isDefault: false,
          created_at: new Date(),
          updated_at: new Date(),
          widgets: importData.layout.widgets?.map((w: any) => ({
            ...w,
            id: `widget_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
            created_at: new Date(),
            updated_at: new Date()
          })) || []
        }

        const savedLayout = await api.saveLayout(importedLayout)
        setState(prev => ({
          ...prev,
          availableLayouts: [...prev.availableLayouts, savedLayout]
        }))
        return savedLayout
      } catch (error) {
        console.error('Failed to import layout:', error)
        throw new Error('Invalid layout data format')
      }
    },

    addWidget: (type: WidgetType, position?: Partial<Widget['position']>) => {
      if (!state.currentLayout) return

      const catalogItem = WIDGET_CATALOG.find(item => item.type === type)
      if (!catalogItem) return

      // Find available position
      const existingPositions = state.currentLayout.widgets.map(w => w.position)
      let newX = position?.x ?? 0
      let newY = position?.y ?? 0

      if (!position) {
        // Auto-placement logic
        const gridWidth = 12
        let placed = false
        for (let y = 0; y < 20 && !placed; y++) {
          for (let x = 0; x <= gridWidth - catalogItem.defaultSize.w && !placed; x++) {
            const wouldOverlap = existingPositions.some(pos => 
              x < pos.x + pos.w && x + catalogItem.defaultSize.w > pos.x &&
              y < pos.y + pos.h && y + catalogItem.defaultSize.h > pos.y
            )
            if (!wouldOverlap) {
              newX = x
              newY = y
              placed = true
            }
          }
        }
      }

      const newWidget: Widget = {
        id: `widget_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
        type,
        title: catalogItem.name,
        position: {
          x: newX,
          y: newY,
          w: position?.w ?? catalogItem.defaultSize.w,
          h: position?.h ?? catalogItem.defaultSize.h,
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

      setState(prev => ({
        ...prev,
        currentLayout: prev.currentLayout ? {
          ...prev.currentLayout,
          widgets: [...prev.currentLayout.widgets, newWidget],
          updated_at: new Date()
        } : null
      }))
    },

    removeWidget: (widgetId: string) => {
      setState(prev => ({
        ...prev,
        currentLayout: prev.currentLayout ? {
          ...prev.currentLayout,
          widgets: prev.currentLayout.widgets.filter(w => w.id !== widgetId),
          updated_at: new Date()
        } : null
      }))
    },

    updateWidget: (widgetId: string, updates: Partial<Widget>) => {
      setState(prev => ({
        ...prev,
        currentLayout: prev.currentLayout ? {
          ...prev.currentLayout,
          widgets: prev.currentLayout.widgets.map(w => 
            w.id === widgetId ? { ...w, ...updates, updated_at: new Date() } : w
          ),
          updated_at: new Date()
        } : null
      }))
    },

    updateWidgetConfig: (widgetId: string, config: any) => {
      setState(prev => ({
        ...prev,
        currentLayout: prev.currentLayout ? {
          ...prev.currentLayout,
          widgets: prev.currentLayout.widgets.map(w => 
            w.id === widgetId ? { 
              ...w, 
              config: { ...w.config, ...config },
              updated_at: new Date() 
            } : w
          ),
          updated_at: new Date()
        } : null
      }))
    },

    moveWidget: (widgetId: string, position: Widget['position']) => {
      actions.updateWidget(widgetId, { position })
    },

    setEditing: (editing: boolean) => {
      setState(prev => ({ ...prev, isEditing: editing }))
    },

    setSelectedWidget: (widget: Widget | null) => {
      setState(prev => ({ ...prev, selectedWidget: widget }))
    },

    setConfigPanelOpen: (open: boolean) => {
      setState(prev => ({ ...prev, configPanelOpen: open }))
    },

    resetToDefault: () => {
      const defaultLayout = createDefaultLayout()
      setState(prev => ({ ...prev, currentLayout: defaultLayout }))
    },

    autoArrangeWidgets: () => {
      if (!state.currentLayout) return

      // Simple auto-arrangement: place widgets in a grid pattern
      const gridWidth = 12
      let currentX = 0
      let currentY = 0
      const rowHeight = 8

      const arrangedWidgets = state.currentLayout.widgets.map(widget => {
        const widgetWidth = Math.min(widget.position.w, gridWidth - currentX) || 4
        const widgetHeight = widget.position.h || 6

        if (currentX + widgetWidth > gridWidth) {
          currentX = 0
          currentY += rowHeight
        }

        const arrangedWidget = {
          ...widget,
          position: {
            ...widget.position,
            x: currentX,
            y: currentY,
            w: widgetWidth,
            h: widgetHeight
          },
          updated_at: new Date()
        }

        currentX += widgetWidth
        return arrangedWidget
      })

      setState(prev => ({
        ...prev,
        currentLayout: prev.currentLayout ? {
          ...prev.currentLayout,
          widgets: arrangedWidgets,
          updated_at: new Date()
        } : null
      }))
    }
  }), [state])

  return {
    ...state,
    ...actions
  }
}
