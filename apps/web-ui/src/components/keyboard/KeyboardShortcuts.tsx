'use client'

import React, { useState, useEffect, useCallback } from 'react'
import { Command } from 'cmdk'
import { 
  Search, Settings, FileText, Home, Database, 
  MessageSquare, BarChart3, Layers, HelpCircle,
  Command as CommandIcon, X, ChevronRight,
  Save, Copy, ClipboardPaste, Undo, Redo, ZoomIn, ZoomOut,
  Play, Pause, RotateCcw, Download, Upload,
  Moon, Sun, Globe, User, LogOut, Plus
} from 'lucide-react'
import { usePathname, useRouter } from 'next/navigation'
import { useToast } from '@/hooks/use-toast'

interface Shortcut {
  id: string
  label: string
  keys: string[]
  action: () => void
  category: string
  description?: string
  customizable?: boolean
}

interface CommandItem {
  id: string
  label: string
  icon?: React.ReactNode
  shortcut?: string
  action: () => void
  category?: string
}

export function KeyboardShortcuts() {
  const pathname = usePathname()
  const isStudio = pathname?.startsWith('/studio') ?? false
  const feedbackWidgetEnabled = process.env.NEXT_PUBLIC_ENABLE_FEEDBACK_WIDGET !== 'false'
  const router = useRouter()
  const { toast } = useToast()
  const [open, setOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [customShortcuts, setCustomShortcuts] = useState<Record<string, string[]>>({})
  const [editingShortcut, setEditingShortcut] = useState<string | null>(null)
  const [recordingKeys, setRecordingKeys] = useState<string[]>([])

  // Default shortcuts configuration
  const defaultShortcuts: Shortcut[] = [
    // Navigation
    {
      id: 'cmd-palette',
      label: 'Command Palette',
      keys: ['cmd', 'k'],
      action: () => setOpen(true),
      category: 'Navigation',
      description: 'Open command palette'
    },
    {
      id: 'search',
      label: 'Search',
      keys: ['cmd', '/'],
      action: () => router.push('/search'),
      category: 'Navigation',
      description: 'Global search'
    },
    {
      id: 'home',
      label: 'Go Home',
      keys: ['cmd', 'h'],
      action: () => router.push('/'),
      category: 'Navigation'
    },
    {
      id: 'datasets',
      label: 'Datasets',
      keys: ['cmd', 'd'],
      action: () => router.push('/datasets'),
      category: 'Navigation'
    },
    {
      id: 'chat',
      label: 'Chat',
      keys: ['cmd', 'shift', 'c'],
      action: () => router.push('/chat'),
      category: 'Navigation'
    },
    {
      id: 'settings',
      label: 'Settings',
      keys: ['cmd', ','],
      action: () => router.push('/settings'),
      category: 'Navigation'
    },
    
    // File Operations
    {
      id: 'save',
      label: 'Save',
      keys: ['cmd', 's'],
      action: () => {
        document.dispatchEvent(new CustomEvent('save'))
        toast({ title: 'Saved', description: 'Changes saved successfully' })
      },
      category: 'File',
      description: 'Save current work'
    },
    {
      id: 'export',
      label: 'Export',
      keys: ['cmd', 'e'],
      action: () => {
        document.dispatchEvent(new CustomEvent('export'))
      },
      category: 'File'
    },
    {
      id: 'new',
      label: 'New',
      keys: ['cmd', 'n'],
      action: () => {
        document.dispatchEvent(new CustomEvent('new'))
      },
      category: 'File'
    },
    
    // Edit Operations
    {
      id: 'copy',
      label: 'Copy',
      keys: ['cmd', 'c'],
      action: () => document.execCommand('copy'),
      category: 'Edit'
    },
    {
      id: 'paste',
      label: 'Paste',
      keys: ['cmd', 'v'],
      action: () => document.execCommand('paste'),
      category: 'Edit'
    },
    {
      id: 'undo',
      label: 'Undo',
      keys: ['cmd', 'z'],
      action: () => document.execCommand('undo'),
      category: 'Edit'
    },
    {
      id: 'redo',
      label: 'Redo',
      keys: ['cmd', 'shift', 'z'],
      action: () => document.execCommand('redo'),
      category: 'Edit'
    },
    
    // View Operations
    {
      id: 'zoom-in',
      label: 'Zoom In',
      keys: ['cmd', '+'],
      action: () => {
        document.dispatchEvent(new CustomEvent('zoom', { detail: 'in' }))
      },
      category: 'View'
    },
    {
      id: 'zoom-out',
      label: 'Zoom Out',
      keys: ['cmd', '-'],
      action: () => {
        document.dispatchEvent(new CustomEvent('zoom', { detail: 'out' }))
      },
      category: 'View'
    },
    {
      id: 'fullscreen',
      label: 'Fullscreen',
      keys: ['cmd', 'shift', 'f'],
      action: () => {
        if (document.fullscreenElement) {
          document.exitFullscreen()
        } else {
          document.documentElement.requestFullscreen()
        }
      },
      category: 'View'
    },
    {
      id: 'theme-toggle',
      label: 'Toggle Theme',
      keys: ['cmd', 'shift', 't'],
      action: () => {
        document.dispatchEvent(new CustomEvent('theme-toggle'))
        toast({ title: 'Theme Changed' })
      },
      category: 'View'
    },
    
    // Execution
    {
      id: 'run',
      label: 'Run/Execute',
      keys: ['cmd', 'enter'],
      action: () => {
        document.dispatchEvent(new CustomEvent('execute'))
      },
      category: 'Execution',
      description: 'Run current analysis'
    },
    {
      id: 'stop',
      label: 'Stop',
      keys: ['cmd', '.'],
      action: () => {
        document.dispatchEvent(new CustomEvent('stop'))
      },
      category: 'Execution'
    },
    
    // Help
    {
      id: 'help',
      label: 'Help',
      keys: ['cmd', '?'],
      action: () => setHelpOpen(true),
      category: 'Help',
      description: 'Show keyboard shortcuts'
    }
  ]

  // Merge with custom shortcuts
  const shortcuts = defaultShortcuts.map(shortcut => ({
    ...shortcut,
    keys: customShortcuts[shortcut.id] || shortcut.keys
  }))

  // Command palette items
  const commandItems: CommandItem[] = [
    // Quick Actions
    {
      id: 'new-analysis',
      label: 'New Analysis',
      icon: <Plus className="w-4 h-4" />,
      action: () => {
        router.push('/chat')
        setOpen(false)
      },
      category: 'Quick Actions'
    },
    {
      id: 'open-dataset',
      label: 'Open Dataset',
      icon: <Database className="w-4 h-4" />,
      action: () => {
        router.push('/datasets')
        setOpen(false)
      },
      category: 'Quick Actions'
    },
    {
      id: 'view-results',
      label: 'View Results',
      icon: <BarChart3 className="w-4 h-4" />,
      action: () => {
        router.push('/results')
        setOpen(false)
      },
      category: 'Quick Actions'
    },
    
    // Navigation items from shortcuts
    ...shortcuts
      .filter(s => s.category === 'Navigation')
      .map(s => ({
        id: s.id,
        label: s.label,
        shortcut: s.keys.join(' + '),
        action: s.action,
        category: 'Navigation'
      })),
    
    // Settings
    {
      id: 'preferences',
      label: 'Preferences',
      icon: <Settings className="w-4 h-4" />,
      shortcut: 'Cmd + ,',
      action: () => {
        router.push('/settings/preferences')
        setOpen(false)
      },
      category: 'Settings'
    },
    {
      id: 'profile',
      label: 'Profile',
      icon: <User className="w-4 h-4" />,
      action: () => {
        router.push('/settings/profile')
        setOpen(false)
      },
      category: 'Settings'
    },
    {
      id: 'logout',
      label: 'Log Out',
      icon: <LogOut className="w-4 h-4" />,
      action: () => {
        // Logout logic
        toast({ title: 'Logged out successfully' })
        setOpen(false)
      },
      category: 'Settings'
    }
  ]

  // Key combination formatter
  const formatKeys = (keys: string[]) => {
    return keys
      .map(key => {
        switch (key) {
          case 'cmd': return '⌘'
          case 'ctrl': return 'Ctrl'
          case 'alt': return 'Alt'
          case 'shift': return '⇧'
          case 'enter': return '↵'
          case 'tab': return '⇥'
          case 'escape': return 'Esc'
          default: return key.toUpperCase()
        }
      })
      .join(' ')
  }

  // Keyboard event handler
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    const activeElement = document.activeElement
    const isTyping = activeElement?.tagName === 'INPUT' || 
                    activeElement?.tagName === 'TEXTAREA' || 
                    activeElement?.getAttribute('contenteditable') === 'true'

    // Don't trigger shortcuts when typing unless it's Cmd+K
    if (isTyping && !(e.metaKey && e.key === 'k')) {
      return
    }

    // Check each shortcut
    for (const shortcut of shortcuts) {
      const keys = shortcut.keys
      const matches = 
        keys.includes('cmd') === e.metaKey &&
        keys.includes('ctrl') === e.ctrlKey &&
        keys.includes('alt') === e.altKey &&
        keys.includes('shift') === e.shiftKey &&
        keys.includes(e.key.toLowerCase())

      if (matches) {
        e.preventDefault()
        shortcut.action()
        break
      }
    }
  }, [shortcuts])

  // Record custom shortcut
  const recordShortcut = useCallback((e: KeyboardEvent) => {
    if (!editingShortcut) return

    e.preventDefault()
    const keys: string[] = []
    
    if (e.metaKey) keys.push('cmd')
    if (e.ctrlKey) keys.push('ctrl')
    if (e.altKey) keys.push('alt')
    if (e.shiftKey) keys.push('shift')
    
    if (!['Meta', 'Control', 'Alt', 'Shift'].includes(e.key)) {
      keys.push(e.key.toLowerCase())
      setRecordingKeys(keys)
      
      // Save after a delay
      setTimeout(() => {
        setCustomShortcuts(prev => ({
          ...prev,
          [editingShortcut]: keys
        }))
        setEditingShortcut(null)
        setRecordingKeys([])
        toast({ title: 'Shortcut Updated' })
      }, 500)
    }
  }, [editingShortcut, toast])

  useEffect(() => {
    // Load custom shortcuts from localStorage
    const saved = localStorage.getItem('customShortcuts')
    if (saved) {
      setCustomShortcuts(JSON.parse(saved))
    }

    // Add keyboard listeners
    window.addEventListener('keydown', handleKeyDown)
    
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [handleKeyDown])

  useEffect(() => {
    // Save custom shortcuts
    if (Object.keys(customShortcuts).length > 0) {
      localStorage.setItem('customShortcuts', JSON.stringify(customShortcuts))
    }
  }, [customShortcuts])

  useEffect(() => {
    if (editingShortcut) {
      window.addEventListener('keydown', recordShortcut)
      return () => window.removeEventListener('keydown', recordShortcut)
    }
  }, [editingShortcut, recordShortcut])

  // Help Overlay Component
  const HelpOverlay = () => (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
      <div className="bg-white dark:bg-gray-900 rounded-xl max-w-3xl w-full max-h-[80vh] overflow-hidden">
        <div className="flex items-center justify-between p-4 border-b">
          <h2 className="text-lg font-semibold">Keyboard Shortcuts</h2>
          <button
            onClick={() => setHelpOpen(false)}
            className="p-1 hover:bg-gray-100 dark:hover:bg-gray-800 rounded"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
        
        <div className="p-4 overflow-y-auto max-h-[calc(80vh-120px)]">
          {Object.entries(
            shortcuts.reduce((acc, s) => {
              if (!acc[s.category]) acc[s.category] = []
              acc[s.category].push(s)
              return acc
            }, {} as Record<string, Shortcut[]>)
          ).map(([category, items]) => (
            <div key={category} className="mb-6">
              <h3 className="font-medium text-sm text-gray-500 dark:text-gray-400 mb-3">
                {category}
              </h3>
              <div className="space-y-2">
                {items.map(item => (
                  <div
                    key={item.id}
                    className="flex items-center justify-between p-2 hover:bg-gray-50 dark:hover:bg-gray-800 rounded-lg"
                  >
                    <div>
                      <span className="font-medium">{item.label}</span>
                      {item.description && (
                        <p className="text-sm text-gray-500 dark:text-gray-400">
                          {item.description}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center space-x-2">
                      <kbd className="px-2 py-1 text-xs bg-gray-100 dark:bg-gray-800 rounded border border-gray-300 dark:border-gray-700">
                        {formatKeys(item.keys)}
                      </kbd>
                      {item.customizable !== false && (
                        <button
                          onClick={() => {
                            setEditingShortcut(item.id)
                            setHelpOpen(false)
                          }}
                          className="text-xs text-blue-600 hover:text-blue-700"
                        >
                          Edit
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
        
        <div className="p-4 border-t bg-gray-50 dark:bg-gray-800">
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Press <kbd className="px-1 py-0.5 text-xs bg-gray-100 dark:bg-gray-700 rounded">⌘ K</kbd> to open command palette
          </p>
        </div>
      </div>
    </div>
  )

  // Edit Shortcut Dialog
  const EditShortcutDialog = () => {
    const shortcut = shortcuts.find(s => s.id === editingShortcut)
    
    if (!shortcut) return null
    
    return (
      <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
        <div className="bg-white dark:bg-gray-900 rounded-xl p-6 max-w-md w-full">
          <h3 className="text-lg font-semibold mb-4">Edit Shortcut</h3>
          <p className="text-gray-600 dark:text-gray-400 mb-4">
            Press new key combination for "{shortcut.label}"
          </p>
          
          <div className="p-4 bg-gray-100 dark:bg-gray-800 rounded-lg text-center">
            {recordingKeys.length > 0 ? (
              <kbd className="text-lg">
                {formatKeys(recordingKeys)}
              </kbd>
            ) : (
              <span className="text-gray-500">Press keys...</span>
            )}
          </div>
          
          <div className="flex justify-end space-x-2 mt-4">
            <button
              onClick={() => {
                setEditingShortcut(null)
                setRecordingKeys([])
              }}
              className="px-4 py-2 text-gray-600 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg"
            >
              Cancel
            </button>
            <button
              onClick={() => {
                // Reset to default
                setCustomShortcuts(prev => {
                  const updated = { ...prev }
                  delete updated[editingShortcut]
                  return updated
                })
                setEditingShortcut(null)
                toast({ title: 'Reset to Default' })
              }}
              className="px-4 py-2 bg-gray-200 hover:bg-gray-300 dark:bg-gray-700 dark:hover:bg-gray-600 rounded-lg"
            >
              Reset
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <>
      {/* Command Palette */}
      <Command.Dialog
        open={open}
        onOpenChange={setOpen}
        label="Command Menu"
        className="fixed inset-0 z-50"
      >
        <div
          className="fixed inset-0 bg-black/50"
          onClick={() => setOpen(false)}
        />
        <div className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-2xl">
          <Command className="bg-white dark:bg-gray-900 rounded-xl shadow-2xl border">
            <div className="flex items-center px-4 py-3 border-b">
              <Search className="w-5 h-5 text-gray-400 mr-3" />
              <Command.Input
                value={search}
                onValueChange={setSearch}
                placeholder="Search commands..."
                className="flex-1 bg-transparent outline-none placeholder:text-gray-400"
              />
              <kbd className="px-2 py-1 text-xs bg-gray-100 dark:bg-gray-800 rounded">
                ESC
              </kbd>
            </div>
            
            <Command.List className="max-h-96 overflow-y-auto p-2">
              <Command.Empty className="py-8 text-center text-gray-500">
                No results found
              </Command.Empty>
              
              {Object.entries(
                commandItems.reduce((acc, item) => {
                  const category = item.category || 'Other'
                  if (!acc[category]) acc[category] = []
                  acc[category].push(item)
                  return acc
                }, {} as Record<string, CommandItem[]>)
              ).map(([category, items]) => (
                <Command.Group key={category} heading={category}>
                  {items.map(item => (
                    <Command.Item
                      key={item.id}
                      value={item.label}
                      onSelect={() => item.action()}
                      className="flex items-center justify-between px-3 py-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 cursor-pointer"
                    >
                      <div className="flex items-center space-x-3">
                        {item.icon}
                        <span>{item.label}</span>
                      </div>
                      {item.shortcut && (
                        <kbd className="text-xs px-2 py-1 bg-gray-100 dark:bg-gray-800 rounded">
                          {item.shortcut}
                        </kbd>
                      )}
                    </Command.Item>
                  ))}
                </Command.Group>
              ))}
            </Command.List>
            
            <div className="px-4 py-3 border-t text-xs text-gray-500 flex items-center justify-between">
              <div className="flex items-center space-x-4">
                <span>↑↓ Navigate</span>
                <span>↵ Select</span>
                <span>ESC Close</span>
              </div>
              <button
                onClick={() => {
                  setOpen(false)
                  setHelpOpen(true)
                }}
                className="text-blue-600 hover:text-blue-700 flex items-center space-x-1"
              >
                <HelpCircle className="w-3 h-3" />
                <span>View All Shortcuts</span>
              </button>
            </div>
          </Command>
        </div>
      </Command.Dialog>

      {/* Help Overlay */}
      {helpOpen && <HelpOverlay />}
      
      {/* Edit Shortcut Dialog */}
      {editingShortcut && <EditShortcutDialog />}
      
      {/* Floating Help Button */}
      {!isStudio && (
        <button
          onClick={() => setHelpOpen(true)}
          className={`fixed ${feedbackWidgetEnabled ? 'bottom-6 right-24' : 'bottom-4 right-4'} p-3 bg-blue-500 text-white rounded-full shadow-lg hover:bg-blue-600 z-40`}
          title="Keyboard Shortcuts (⌘ ?)"
        >
          <CommandIcon className="w-5 h-5" />
        </button>
      )}
    </>
  )
}

export default KeyboardShortcuts
