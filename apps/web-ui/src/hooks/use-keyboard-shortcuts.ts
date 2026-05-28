import { useEffect, useCallback } from 'react'

interface KeyboardShortcut {
  keys: string[]
  handler: (event: KeyboardEvent) => void
  preventDefault?: boolean
  allowInInput?: boolean
}

/**
 * Hook for registering keyboard shortcuts
 * @param shortcuts - Array of keyboard shortcuts to register
 */
export function useKeyboardShortcuts(shortcuts: KeyboardShortcut[]) {
  const handleKeyDown = useCallback((event: KeyboardEvent) => {
    const activeElement = document.activeElement
    const isInputField = 
      activeElement?.tagName === 'INPUT' ||
      activeElement?.tagName === 'TEXTAREA' ||
      activeElement?.getAttribute('contenteditable') === 'true'

    for (const shortcut of shortcuts) {
      // Skip if in input field and not allowed
      if (isInputField && !shortcut.allowInInput) {
        continue
      }

      // Check if all keys match
      const matches = shortcut.keys.every(key => {
        switch (key.toLowerCase()) {
          case 'cmd':
          case 'meta':
            return event.metaKey
          case 'ctrl':
            return event.ctrlKey
          case 'alt':
            return event.altKey
          case 'shift':
            return event.shiftKey
          case 'enter':
            return event.key === 'Enter'
          case 'escape':
          case 'esc':
            return event.key === 'Escape'
          case 'space':
            return event.key === ' '
          case 'tab':
            return event.key === 'Tab'
          case 'delete':
          case 'backspace':
            return event.key === 'Backspace' || event.key === 'Delete'
          case 'up':
          case 'arrowup':
            return event.key === 'ArrowUp'
          case 'down':
          case 'arrowdown':
            return event.key === 'ArrowDown'
          case 'left':
          case 'arrowleft':
            return event.key === 'ArrowLeft'
          case 'right':
          case 'arrowright':
            return event.key === 'ArrowRight'
          default:
            return event.key.toLowerCase() === key.toLowerCase()
        }
      })

      if (matches) {
        if (shortcut.preventDefault !== false) {
          event.preventDefault()
        }
        shortcut.handler(event)
        break
      }
    }
  }, [shortcuts])

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [handleKeyDown])
}

/**
 * Hook for a single keyboard shortcut
 */
export function useKeyboardShortcut(
  keys: string[],
  handler: (event: KeyboardEvent) => void,
  options?: { preventDefault?: boolean; allowInInput?: boolean }
) {
  useKeyboardShortcuts([
    {
      keys,
      handler,
      preventDefault: options?.preventDefault,
      allowInInput: options?.allowInInput
    }
  ])
}

/**
 * Common keyboard shortcuts
 */
export const SHORTCUTS = {
  COMMAND_PALETTE: ['cmd', 'k'],
  SEARCH: ['cmd', '/'],
  SAVE: ['cmd', 's'],
  NEW: ['cmd', 'n'],
  OPEN: ['cmd', 'o'],
  CLOSE: ['cmd', 'w'],
  QUIT: ['cmd', 'q'],
  COPY: ['cmd', 'c'],
  PASTE: ['cmd', 'v'],
  CUT: ['cmd', 'x'],
  UNDO: ['cmd', 'z'],
  REDO: ['cmd', 'shift', 'z'],
  SELECT_ALL: ['cmd', 'a'],
  FIND: ['cmd', 'f'],
  REPLACE: ['cmd', 'shift', 'f'],
  ZOOM_IN: ['cmd', '+'],
  ZOOM_OUT: ['cmd', '-'],
  ZOOM_RESET: ['cmd', '0'],
  FULLSCREEN: ['cmd', 'shift', 'f'],
  HELP: ['cmd', '?'],
  SETTINGS: ['cmd', ','],
  ESCAPE: ['escape'],
  ENTER: ['enter'],
  TAB: ['tab'],
  SHIFT_TAB: ['shift', 'tab'],
  ARROW_UP: ['arrowup'],
  ARROW_DOWN: ['arrowdown'],
  ARROW_LEFT: ['arrowleft'],
  ARROW_RIGHT: ['arrowright']
}

/**
 * Get platform-specific modifier key
 */
export function getModifierKey(): 'cmd' | 'ctrl' {
  if (typeof window === 'undefined') return 'ctrl'
  const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0
  return isMac ? 'cmd' : 'ctrl'
}

/**
 * Format keyboard shortcut for display
 */
export function formatShortcut(keys: string[]): string {
  const isMac = typeof window !== 'undefined' && 
                navigator.platform.toUpperCase().indexOf('MAC') >= 0
  
  return keys.map(key => {
    switch (key.toLowerCase()) {
      case 'cmd':
      case 'meta':
        return isMac ? '⌘' : 'Ctrl'
      case 'ctrl':
        return 'Ctrl'
      case 'alt':
        return isMac ? '⌥' : 'Alt'
      case 'shift':
        return isMac ? '⇧' : 'Shift'
      case 'enter':
        return '↵'
      case 'escape':
      case 'esc':
        return 'Esc'
      case 'space':
        return 'Space'
      case 'tab':
        return '⇥'
      case 'delete':
      case 'backspace':
        return '⌫'
      case 'arrowup':
      case 'up':
        return '↑'
      case 'arrowdown':
      case 'down':
        return '↓'
      case 'arrowleft':
      case 'left':
        return '←'
      case 'arrowright':
      case 'right':
        return '→'
      default:
        return key.charAt(0).toUpperCase() + key.slice(1)
    }
  }).join(isMac ? '' : '+')
}