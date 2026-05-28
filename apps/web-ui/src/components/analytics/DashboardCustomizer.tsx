'use client'

import React, { useState, useEffect } from 'react'
import {
  Settings2,
  Layout,
  Move,
  Eye,
  EyeOff,
  Save,
  RotateCcw,
  Check,
  X,
  GripVertical
} from 'lucide-react'

interface WidgetConfig {
  id: string
  name: string
  visible: boolean
  order: number
  size: 'small' | 'medium' | 'large'
}

interface DashboardCustomizerProps {
  onSave?: (config: WidgetConfig[]) => void
  onReset?: () => void
  className?: string
}

const defaultWidgets: WidgetConfig[] = [
  { id: 'kpi-cards', name: 'KPI Cards', visible: true, order: 0, size: 'large' },
  { id: 'usage-chart', name: 'Usage Chart', visible: true, order: 1, size: 'medium' },
  { id: 'system-health', name: 'System Health', visible: true, order: 2, size: 'medium' },
  { id: 'resource-usage', name: 'Resource Usage', visible: true, order: 3, size: 'small' },
  { id: 'recent-activity', name: 'Recent Activity', visible: true, order: 4, size: 'medium' },
  { id: 'pipeline-status', name: 'Pipeline Status', visible: true, order: 5, size: 'small' },
  { id: 'storage-overview', name: 'Storage Overview', visible: false, order: 6, size: 'small' },
  { id: 'user-analytics', name: 'User Analytics', visible: false, order: 7, size: 'medium' }
]

export function DashboardCustomizer({ onSave, onReset, className = '' }: DashboardCustomizerProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [widgets, setWidgets] = useState<WidgetConfig[]>(() => {
    // Load from localStorage if available
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('dashboard-widgets')
      return saved ? JSON.parse(saved) : defaultWidgets
    }
    return defaultWidgets
  })
  const [draggedItem, setDraggedItem] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  const toggleWidget = (id: string) => {
    setWidgets(prev =>
      prev.map(w => w.id === id ? { ...w, visible: !w.visible } : w)
    )
  }

  const changeSize = (id: string, size: WidgetConfig['size']) => {
    setWidgets(prev =>
      prev.map(w => w.id === id ? { ...w, size } : w)
    )
  }

  const handleDragStart = (e: React.DragEvent, id: string) => {
    setDraggedItem(id)
    e.dataTransfer.effectAllowed = 'move'
  }

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
  }

  const handleDrop = (e: React.DragEvent, targetId: string) => {
    e.preventDefault()
    if (!draggedItem || draggedItem === targetId) return

    const draggedIndex = widgets.findIndex(w => w.id === draggedItem)
    const targetIndex = widgets.findIndex(w => w.id === targetId)

    const newWidgets = [...widgets]
    const [removed] = newWidgets.splice(draggedIndex, 1)
    newWidgets.splice(targetIndex, 0, removed)

    // Update order
    newWidgets.forEach((w, i) => {
      w.order = i
    })

    setWidgets(newWidgets)
    setDraggedItem(null)
  }

  const handleSave = () => {
    // Save to localStorage
    localStorage.setItem('dashboard-widgets', JSON.stringify(widgets))
    onSave?.(widgets)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  const handleReset = () => {
    setWidgets(defaultWidgets)
    localStorage.removeItem('dashboard-widgets')
    onReset?.()
  }

  return (
    <div className={`relative ${className}`}>
      {/* Customizer Toggle Button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="inline-flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
      >
        <Settings2 className="h-4 w-4" />
        Customize Dashboard
      </button>

      {/* Customizer Panel */}
      {isOpen && (
        <div className="absolute right-0 top-12 z-50 w-80 bg-white border border-gray-200 rounded-lg shadow-lg">
          <div className="border-b border-gray-200 px-4 py-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-gray-900">Dashboard Customization</h3>
              <button
                onClick={() => setIsOpen(false)}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>

          <div className="max-h-96 overflow-y-auto p-4">
            <div className="space-y-3">
              {widgets.map((widget) => (
                <div
                  key={widget.id}
                  draggable
                  onDragStart={(e) => handleDragStart(e, widget.id)}
                  onDragOver={handleDragOver}
                  onDrop={(e) => handleDrop(e, widget.id)}
                  className={`flex items-center justify-between p-3 bg-gray-50 rounded-lg cursor-move hover:bg-gray-100 transition-colors ${
                    draggedItem === widget.id ? 'opacity-50' : ''
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <GripVertical className="h-4 w-4 text-gray-400" />
                    <span className="text-sm font-medium text-gray-700">{widget.name}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    {/* Size Selector */}
                    <select
                      value={widget.size}
                      onChange={(e) => changeSize(widget.id, e.target.value as WidgetConfig['size'])}
                      className="text-xs border border-gray-200 rounded px-1.5 py-1"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <option value="small">S</option>
                      <option value="medium">M</option>
                      <option value="large">L</option>
                    </select>
                    {/* Visibility Toggle */}
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        toggleWidget(widget.id)
                      }}
                      className={`p-1.5 rounded transition-colors ${
                        widget.visible
                          ? 'text-blue-600 bg-blue-50 hover:bg-blue-100'
                          : 'text-gray-400 bg-gray-100 hover:bg-gray-200'
                      }`}
                    >
                      {widget.visible ? (
                        <Eye className="h-3.5 w-3.5" />
                      ) : (
                        <EyeOff className="h-3.5 w-3.5" />
                      )}
                    </button>
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-4 text-xs text-gray-500">
              <p>• Drag widgets to reorder</p>
              <p>• Toggle visibility with the eye icon</p>
              <p>• Adjust widget size (S/M/L)</p>
            </div>
          </div>

          <div className="border-t border-gray-200 px-4 py-3">
            <div className="flex items-center justify-between gap-2">
              <button
                onClick={handleReset}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-gray-600 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                Reset
              </button>
              <button
                onClick={handleSave}
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-white rounded-lg transition-colors ${
                  saved
                    ? 'bg-green-600 hover:bg-green-700'
                    : 'bg-blue-600 hover:bg-blue-700'
                }`}
              >
                {saved ? (
                  <>
                    <Check className="h-3.5 w-3.5" />
                    Saved
                  </>
                ) : (
                  <>
                    <Save className="h-3.5 w-3.5" />
                    Save Changes
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}