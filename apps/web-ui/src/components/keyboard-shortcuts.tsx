'use client'

import React, { useState, useEffect, useCallback } from 'react'
import { Command, Search, X, HelpCircle, Settings, FileText, Home, Save } from 'lucide-react'

interface Shortcut {
  id: string
  key: string
  modifiers: string[]
  description: string
  action: () => void
  category: string
  customizable?: boolean
}

interface CommandPaletteItem {
  id: string
  label: string
  description?: string
  icon?: React.ElementType
  shortcut?: string
  action: () => void
  category?: string
}

interface KeyboardShortcutsProps {
  shortcuts?: Shortcut[]
  onExecute?: (shortcutId: string) => void
  enableCommandPalette?: boolean
  customizable?: boolean
}

const defaultShortcuts: Shortcut[] = [
  {
    id: 'search',
    key: 'k',
    modifiers: ['cmd', 'ctrl'],
    description: 'Open command palette',
    action: () => {},
    category: 'General'
  },
  {
    id: 'save',
    key: 's',
    modifiers: ['cmd', 'ctrl'],
    description: 'Save current work',
    action: () => {},
    category: 'General'
  },
  {
    id: 'new',
    key: 'n',
    modifiers: ['cmd', 'ctrl'],
    description: 'New analysis',
    action: () => {},
    category: 'General'
  },
  {
    id: 'help',
    key: '?',
    modifiers: ['shift'],
    description: 'Show keyboard shortcuts',
    action: () => {},
    category: 'General'
  },
  {
    id: 'home',
    key: 'h',
    modifiers: ['cmd', 'ctrl', 'shift'],
    description: 'Go to home',
    action: () => {},
    category: 'Navigation'
  },
  {
    id: 'settings',
    key: ',',
    modifiers: ['cmd', 'ctrl'],
    description: 'Open settings',
    action: () => {},
    category: 'Navigation'
  },
  {
    id: 'toggle-sidebar',
    key: 'b',
    modifiers: ['cmd', 'ctrl'],
    description: 'Toggle sidebar',
    action: () => {},
    category: 'View'
  },
  {
    id: 'toggle-theme',
    key: 't',
    modifiers: ['cmd', 'ctrl', 'shift'],
    description: 'Toggle dark mode',
    action: () => {},
    category: 'View'
  },
  {
    id: 'zoom-in',
    key: '+',
    modifiers: ['cmd', 'ctrl'],
    description: 'Zoom in',
    action: () => {},
    category: 'View'
  },
  {
    id: 'zoom-out',
    key: '-',
    modifiers: ['cmd', 'ctrl'],
    description: 'Zoom out',
    action: () => {},
    category: 'View'
  }
]

const commandPaletteItems: CommandPaletteItem[] = [
  {
    id: 'new-analysis',
    label: 'New Analysis',
    description: 'Start a new analysis',
    icon: FileText,
    shortcut: '⌘N',
    action: () => console.log('New analysis'),
    category: 'Actions'
  },
  {
    id: 'open-dataset',
    label: 'Open Dataset',
    description: 'Browse and open datasets',
    shortcut: '⌘O',
    action: () => console.log('Open dataset'),
    category: 'Actions'
  },
  {
    id: 'run-pipeline',
    label: 'Run Pipeline',
    description: 'Execute analysis pipeline',
    shortcut: '⌘R',
    action: () => console.log('Run pipeline'),
    category: 'Actions'
  },
  {
    id: 'go-home',
    label: 'Go to Home',
    icon: Home,
    shortcut: '⌘⇧H',
    action: () => console.log('Go home'),
    category: 'Navigation'
  },
  {
    id: 'go-settings',
    label: 'Settings',
    icon: Settings,
    shortcut: '⌘,',
    action: () => console.log('Open settings'),
    category: 'Navigation'
  },
  {
    id: 'help',
    label: 'Help & Documentation',
    icon: HelpCircle,
    shortcut: '⇧?',
    action: () => console.log('Show help'),
    category: 'Help'
  }
]

export function KeyboardShortcuts({
  shortcuts = defaultShortcuts,
  onExecute,
  enableCommandPalette = true,
  customizable = true
}: KeyboardShortcutsProps) {
  const [showHelp, setShowHelp] = useState(false)
  const [showCommandPalette, setShowCommandPalette] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [customShortcuts, setCustomShortcuts] = useState<Record<string, string>>({})
  const [recordingShortcut, setRecordingShortcut] = useState<string | null>(null)

  // Filter command palette items
  const filteredItems = commandPaletteItems.filter(item => {
    const query = searchQuery.toLowerCase()
    return item.label.toLowerCase().includes(query) ||
           item.description?.toLowerCase().includes(query) ||
           item.category?.toLowerCase().includes(query)
  })

  // Group items by category
  const groupedItems = filteredItems.reduce((groups, item) => {
    const category = item.category || 'Other'
    if (!groups[category]) groups[category] = []
    groups[category].push(item)
    return groups
  }, {} as Record<string, CommandPaletteItem[]>)

  // Handle keyboard events
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Check for recording mode
      if (recordingShortcut) {
        e.preventDefault()
        const key = e.key.toLowerCase()
        const modifiers = []
        if (e.metaKey || e.ctrlKey) modifiers.push('cmd')
        if (e.shiftKey) modifiers.push('shift')
        if (e.altKey) modifiers.push('alt')
        
        const shortcutString = [...modifiers, key].join('+')
        setCustomShortcuts({ ...customShortcuts, [recordingShortcut]: shortcutString })
        setRecordingShortcut(null)
        return
      }

      // Command palette
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setShowCommandPalette(!showCommandPalette)
        return
      }

      // Help overlay
      if (e.shiftKey && e.key === '?') {
        e.preventDefault()
        setShowHelp(!showHelp)
        return
      }

      // Command palette navigation
      if (showCommandPalette) {
        if (e.key === 'ArrowDown') {
          e.preventDefault()
          setSelectedIndex((prev) => Math.min(prev + 1, filteredItems.length - 1))
        } else if (e.key === 'ArrowUp') {
          e.preventDefault()
          setSelectedIndex((prev) => Math.max(prev - 1, 0))
        } else if (e.key === 'Enter') {
          e.preventDefault()
          if (filteredItems[selectedIndex]) {
            filteredItems[selectedIndex].action()
            setShowCommandPalette(false)
          }
        } else if (e.key === 'Escape') {
          e.preventDefault()
          setShowCommandPalette(false)
        }
        return
      }

      // Check shortcuts
      shortcuts.forEach(shortcut => {
        const modifiersMatch = shortcut.modifiers.every(mod => {
          if (mod === 'cmd' || mod === 'ctrl') return e.metaKey || e.ctrlKey
          if (mod === 'shift') return e.shiftKey
          if (mod === 'alt') return e.altKey
          return false
        })

        if (modifiersMatch && e.key.toLowerCase() === shortcut.key.toLowerCase()) {
          e.preventDefault()
          shortcut.action()
          onExecute?.(shortcut.id)
        }
      })
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [shortcuts, showCommandPalette, showHelp, filteredItems, selectedIndex, recordingShortcut, customShortcuts, onExecute])

  const formatShortcut = (modifiers: string[], key: string) => {
    const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0
    const symbols: Record<string, string> = {
      cmd: isMac ? '⌘' : 'Ctrl',
      ctrl: isMac ? '⌃' : 'Ctrl',
      shift: '⇧',
      alt: isMac ? '⌥' : 'Alt'
    }

    const formatted = modifiers.map(mod => symbols[mod] || mod)
    formatted.push(key.toUpperCase())
    return formatted.join('')
  }

  const startRecording = (shortcutId: string) => {
    setRecordingShortcut(shortcutId)
  }

  return (
    <>
      {/* Command Palette */}
      {enableCommandPalette && showCommandPalette && (
        <div className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-start justify-center pt-20">
          <div className="bg-white rounded-lg shadow-2xl w-full max-w-2xl max-h-[500px] overflow-hidden">
            {/* Search Input */}
            <div className="p-4 border-b border-gray-200">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 h-5 w-5" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => {
                    setSearchQuery(e.target.value)
                    setSelectedIndex(0)
                  }}
                  placeholder="Type a command or search..."
                  className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  autoFocus
                />
              </div>
            </div>

            {/* Results */}
            <div className="max-h-[400px] overflow-y-auto">
              {Object.entries(groupedItems).map(([category, items]) => (
                <div key={category}>
                  <div className="px-4 py-2 bg-gray-50 text-xs font-semibold text-gray-500 uppercase">
                    {category}
                  </div>
                  {items.map((item, idx) => {
                    const Icon = item.icon
                    const globalIndex = filteredItems.indexOf(item)
                    const isSelected = globalIndex === selectedIndex
                    
                    return (
                      <button
                        key={item.id}
                        onClick={() => {
                          item.action()
                          setShowCommandPalette(false)
                        }}
                        onMouseEnter={() => setSelectedIndex(globalIndex)}
                        className={`w-full px-4 py-3 flex items-center justify-between hover:bg-gray-50 ${
                          isSelected ? 'bg-blue-50' : ''
                        }`}
                      >
                        <div className="flex items-center gap-3">
                          {Icon && <Icon className="h-5 w-5 text-gray-400" />}
                          <div className="text-left">
                            <div className="font-medium">{item.label}</div>
                            {item.description && (
                              <div className="text-sm text-gray-500">{item.description}</div>
                            )}
                          </div>
                        </div>
                        {item.shortcut && (
                          <kbd className="px-2 py-1 bg-gray-100 rounded text-xs">
                            {item.shortcut}
                          </kbd>
                        )}
                      </button>
                    )
                  })}
                </div>
              ))}

              {filteredItems.length === 0 && (
                <div className="p-8 text-center text-gray-500">
                  No commands found for "{searchQuery}"
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Help Overlay */}
      {showHelp && (
        <div className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-lg shadow-2xl w-full max-w-3xl max-h-[80vh] overflow-hidden">
            {/* Header */}
            <div className="p-4 border-b border-gray-200 flex items-center justify-between">
              <h2 className="text-xl font-semibold">Keyboard Shortcuts</h2>
              <button
                onClick={() => setShowHelp(false)}
                className="p-1 hover:bg-gray-100 rounded"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {/* Shortcuts List */}
            <div className="p-4 overflow-y-auto max-h-[calc(80vh-120px)]">
              {Object.entries(
                shortcuts.reduce((groups, shortcut) => {
                  if (!groups[shortcut.category]) groups[shortcut.category] = []
                  groups[shortcut.category].push(shortcut)
                  return groups
                }, {} as Record<string, Shortcut[]>)
              ).map(([category, categoryShortcuts]) => (
                <div key={category} className="mb-6">
                  <h3 className="font-semibold text-gray-900 mb-3">{category}</h3>
                  <div className="space-y-2">
                    {categoryShortcuts.map(shortcut => (
                      <div
                        key={shortcut.id}
                        className="flex items-center justify-between py-2 px-3 hover:bg-gray-50 rounded"
                      >
                        <span className="text-gray-700">{shortcut.description}</span>
                        <div className="flex items-center gap-2">
                          <kbd className="px-2 py-1 bg-gray-100 border border-gray-300 rounded text-sm">
                            {customShortcuts[shortcut.id] || formatShortcut(shortcut.modifiers, shortcut.key)}
                          </kbd>
                          {customizable && shortcut.customizable !== false && (
                            <button
                              onClick={() => startRecording(shortcut.id)}
                              className={`text-xs px-2 py-1 rounded ${
                                recordingShortcut === shortcut.id
                                  ? 'bg-blue-500 text-white'
                                  : 'bg-gray-200 hover:bg-gray-300'
                              }`}
                            >
                              {recordingShortcut === shortcut.id ? 'Press keys...' : 'Edit'}
                            </button>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>

            {/* Footer */}
            <div className="p-4 border-t border-gray-200 bg-gray-50">
              <div className="flex items-center justify-between text-sm text-gray-600">
                <div>
                  Press <kbd className="px-2 py-1 bg-white border border-gray-300 rounded">⇧?</kbd> to toggle this help
                </div>
                <div>
                  Press <kbd className="px-2 py-1 bg-white border border-gray-300 rounded">⌘K</kbd> for command palette
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}