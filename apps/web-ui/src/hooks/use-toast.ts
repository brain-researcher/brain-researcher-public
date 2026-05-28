import * as React from "react"

import type {
  ToastActionElement,
  ToastProps,
} from "@/components/ui/toast"

const TOAST_LIMIT = 5
const TOAST_REMOVE_DELAY = 1000000

type ToasterToast = ToastProps & {
  id: string
  title?: React.ReactNode
  description?: React.ReactNode
  action?: ToastActionElement
  type?: 'success' | 'error' | 'warning' | 'info' | 'loading'
  progress?: number
  sound?: boolean
  persistent?: boolean
  position?: 'top-right' | 'top-left' | 'bottom-right' | 'bottom-left' | 'top-center' | 'bottom-center'
  timestamp?: Date
}

const actionTypes = {
  ADD_TOAST: "ADD_TOAST",
  UPDATE_TOAST: "UPDATE_TOAST",
  DISMISS_TOAST: "DISMISS_TOAST",
  REMOVE_TOAST: "REMOVE_TOAST",
  TOGGLE_DND: "TOGGLE_DND",
  TOGGLE_SOUND: "TOGGLE_SOUND",
  CLEAR_HISTORY: "CLEAR_HISTORY",
} as const

let count = 0

function genId() {
  count = (count + 1) % Number.MAX_SAFE_INTEGER
  return count.toString()
}

type ActionType = typeof actionTypes

type Action =
  | {
      type: ActionType["ADD_TOAST"]
      toast: ToasterToast
    }
  | {
      type: ActionType["UPDATE_TOAST"]
      toast: Partial<ToasterToast>
    }
  | {
      type: ActionType["DISMISS_TOAST"]
      toastId?: ToasterToast["id"]
    }
  | {
      type: ActionType["REMOVE_TOAST"]
      toastId?: ToasterToast["id"]
    }
  | {
      type: ActionType["TOGGLE_DND"]
    }
  | {
      type: ActionType["TOGGLE_SOUND"]
    }
  | {
      type: ActionType["CLEAR_HISTORY"]
    }

interface State {
  toasts: ToasterToast[]
  doNotDisturb: boolean
  soundEnabled: boolean
  history: ToasterToast[]
}

const toastTimeouts = new Map<string, ReturnType<typeof setTimeout>>()

const addToRemoveQueue = (toastId: string) => {
  if (toastTimeouts.has(toastId)) {
    return
  }

  const timeout = setTimeout(() => {
    toastTimeouts.delete(toastId)
    dispatch({
      type: "REMOVE_TOAST",
      toastId: toastId,
    })
  }, TOAST_REMOVE_DELAY)

  toastTimeouts.set(toastId, timeout)
}

// Sound utility functions
const playNotificationSound = (type: string) => {
  if (typeof window !== 'undefined' && memoryState.soundEnabled) {
    try {
      const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)()
      const oscillator = audioContext.createOscillator()
      const gainNode = audioContext.createGain()
      
      oscillator.connect(gainNode)
      gainNode.connect(audioContext.destination)
      
      // Different frequencies for different notification types
      const frequencies = {
        success: [523.25, 659.25], // C5, E5
        error: [329.63, 261.63], // E4, C4
        warning: [440, 493.88], // A4, B4
        info: [587.33], // D5
        loading: [783.99] // G5
      }
      
      const freq = frequencies[type as keyof typeof frequencies] || frequencies.info
      
      oscillator.frequency.setValueAtTime(freq[0], audioContext.currentTime)
      if (freq[1]) {
        oscillator.frequency.setValueAtTime(freq[1], audioContext.currentTime + 0.1)
      }
      
      gainNode.gain.setValueAtTime(0.1, audioContext.currentTime)
      gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.3)
      
      oscillator.start(audioContext.currentTime)
      oscillator.stop(audioContext.currentTime + 0.3)
    } catch (error) {
      // Silently fail if audio context is not available
      console.debug('Audio context not available:', error)
    }
  }
}

export const reducer = (state: State, action: Action): State => {
  switch (action.type) {
    case "ADD_TOAST": {
      // Don't add toast if do not disturb is enabled (except for errors)
      if (state.doNotDisturb && action.toast.type !== 'error') {
        return {
          ...state,
          history: [{ ...action.toast, timestamp: new Date() }, ...state.history].slice(0, 50)
        }
      }

      // Play sound for new toast
      if (action.toast.sound !== false && action.toast.type) {
        playNotificationSound(action.toast.type)
      }

      return {
        ...state,
        toasts: [action.toast, ...state.toasts].slice(0, TOAST_LIMIT),
        history: [{ ...action.toast, timestamp: new Date() }, ...state.history].slice(0, 50)
      }
    }

    case "UPDATE_TOAST":
      return {
        ...state,
        toasts: state.toasts.map((t) =>
          t.id === action.toast.id ? { ...t, ...action.toast } : t
        ),
      }

    case "DISMISS_TOAST": {
      const { toastId } = action

      if (toastId) {
        addToRemoveQueue(toastId)
      } else {
        state.toasts.forEach((toast) => {
          addToRemoveQueue(toast.id)
        })
      }

      return {
        ...state,
        toasts: state.toasts.map((t) =>
          t.id === toastId || toastId === undefined
            ? {
                ...t,
                open: false,
              }
            : t
        ),
      }
    }
    
    case "REMOVE_TOAST":
      if (action.toastId === undefined) {
        return {
          ...state,
          toasts: [],
        }
      }
      return {
        ...state,
        toasts: state.toasts.filter((t) => t.id !== action.toastId),
      }

    case "TOGGLE_DND":
      return {
        ...state,
        doNotDisturb: !state.doNotDisturb
      }

    case "TOGGLE_SOUND":
      return {
        ...state,
        soundEnabled: !state.soundEnabled
      }

    case "CLEAR_HISTORY":
      return {
        ...state,
        history: []
      }

    default:
      return state
  }
}

const listeners: Array<(state: State) => void> = []

let memoryState: State = { 
  toasts: [], 
  doNotDisturb: false, 
  soundEnabled: true, 
  history: [] 
}

function dispatch(action: Action) {
  memoryState = reducer(memoryState, action)
  listeners.forEach((listener) => {
    listener(memoryState)
  })
}

type Toast = Omit<ToasterToast, "id">

function toast({ ...props }: Toast) {
  const id = genId()

  const update = (props: Partial<Omit<ToasterToast, 'id'>>) =>
    dispatch({
      type: "UPDATE_TOAST",
      toast: { ...props, id },
    })
  const dismiss = () => dispatch({ type: "DISMISS_TOAST", toastId: id })

  dispatch({
    type: "ADD_TOAST",
    toast: {
      ...props,
      id,
      open: true,
      timestamp: new Date(),
      onOpenChange: (open) => {
        if (!open) dismiss()
      },
    },
  })

  return {
    id: id,
    dismiss,
    update,
  }
}

function useToast() {
  const [state, setState] = React.useState<State>(memoryState)

  React.useEffect(() => {
    listeners.push(setState)
    return () => {
      const index = listeners.indexOf(setState)
      if (index > -1) {
        listeners.splice(index, 1)
      }
    }
  }, [state])

  // Keyboard shortcuts
  React.useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      // Escape to dismiss all toasts
      if (event.key === 'Escape' && state.toasts.length > 0) {
        event.preventDefault()
        dispatch({ type: "DISMISS_TOAST" })
      }
      // Ctrl+Shift+N to toggle do not disturb
      if (event.ctrlKey && event.shiftKey && event.key === 'N') {
        event.preventDefault()
        dispatch({ type: "TOGGLE_DND" })
      }
      // Ctrl+Shift+S to toggle sound
      if (event.ctrlKey && event.shiftKey && event.key === 'S') {
        event.preventDefault()
        dispatch({ type: "TOGGLE_SOUND" })
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [state.toasts.length])

  return {
    ...state,
    toast,
    dismiss: (toastId?: string) => dispatch({ type: "DISMISS_TOAST", toastId }),
    toggleDoNotDisturb: () => dispatch({ type: "TOGGLE_DND" }),
    toggleSound: () => dispatch({ type: "TOGGLE_SOUND" }),
    clearHistory: () => dispatch({ type: "CLEAR_HISTORY" }),
  }
}

export { useToast, toast }