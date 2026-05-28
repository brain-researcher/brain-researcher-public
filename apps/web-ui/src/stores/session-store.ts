'use client'

import { create } from 'zustand'
import { subscribeWithSelector } from 'zustand/middleware'
import { immer } from 'zustand/middleware/immer'

export interface SessionState {
  // Session identification
  sessionId: string
  userId: string
  documentId?: string
  
  // UI State
  activeTab: string
  sidebarOpen: boolean
  darkMode: boolean
  theme: string
  
  // Application state
  selectedDatasets: string[]
  analysisParameters: Record<string, any>
  currentWorkflow: string | null
  searchQuery: string
  filters: Record<string, any>
  
  // History for undo/redo
  history: {
    past: SessionSnapshot[]
    present: SessionSnapshot
    future: SessionSnapshot[]
  }
  
  // Temporary state (not persisted)
  isLoading: boolean
  error: string | null
  notifications: Notification[]
  
  // Collaboration state
  collaborators: string[]
  sharedCursor?: { x: number; y: number }
  
  // Form state
  forms: Record<string, FormState>
  
  // View state
  views: Record<string, ViewState>
}

export interface SessionSnapshot {
  timestamp: number
  state: Partial<SessionState>
  action: string
  description?: string
}

export interface Notification {
  id: string
  type: 'info' | 'success' | 'warning' | 'error'
  title: string
  message: string
  timestamp: number
  read: boolean
  actions?: NotificationAction[]
}

export interface NotificationAction {
  label: string
  action: () => void
  variant?: 'primary' | 'secondary'
}

export interface FormState {
  values: Record<string, any>
  errors: Record<string, string[]>
  touched: Record<string, boolean>
  isSubmitting: boolean
  isDirty: boolean
}

export interface ViewState {
  scroll: { x: number; y: number }
  zoom: number
  selection: any[]
  expanded: string[]
  collapsed: string[]
}

export interface SessionActions {
  // Session management
  initializeSession: (userId: string, documentId?: string) => void
  resetSession: () => void
  updateSession: (updates: Partial<SessionState>) => void
  
  // UI actions
  setActiveTab: (tab: string) => void
  toggleSidebar: () => void
  setDarkMode: (enabled: boolean) => void
  setTheme: (theme: string) => void
  
  // Application actions
  setSelectedDatasets: (datasets: string[]) => void
  updateAnalysisParameters: (parameters: Record<string, any>) => void
  setCurrentWorkflow: (workflow: string | null) => void
  setSearchQuery: (query: string) => void
  updateFilters: (filters: Record<string, any>) => void
  
  // History actions (undo/redo)
  undo: () => void
  redo: () => void
  clearHistory: () => void
  canUndo: () => boolean
  canRedo: () => boolean
  saveSnapshot: (action: string, description?: string) => void
  
  // Notification actions
  addNotification: (notification: Omit<Notification, 'id' | 'timestamp' | 'read'>) => void
  removeNotification: (id: string) => void
  markNotificationAsRead: (id: string) => void
  clearNotifications: () => void
  
  // Error handling
  setError: (error: string | null) => void
  setLoading: (loading: boolean) => void
  
  // Collaboration
  addCollaborator: (userId: string) => void
  removeCollaborator: (userId: string) => void
  updateSharedCursor: (cursor: { x: number; y: number } | undefined) => void
  
  // Form management
  initializeForm: (formId: string, initialValues?: Record<string, any>) => void
  updateFormValues: (formId: string, values: Record<string, any>) => void
  setFormErrors: (formId: string, errors: Record<string, string[]>) => void
  touchFormField: (formId: string, field: string) => void
  setFormSubmitting: (formId: string, submitting: boolean) => void
  resetForm: (formId: string) => void
  removeForm: (formId: string) => void
  
  // View management
  updateView: (viewId: string, updates: Partial<ViewState>) => void
  resetView: (viewId: string) => void
  removeView: (viewId: string) => void
}

const initialState: Omit<SessionState, 'sessionId' | 'userId'> = {
  documentId: undefined,
  activeTab: 'dashboard',
  sidebarOpen: true,
  darkMode: false,
  theme: 'default',
  selectedDatasets: [],
  analysisParameters: {},
  currentWorkflow: null,
  searchQuery: '',
  filters: {},
  history: {
    past: [],
    present: {
      timestamp: Date.now(),
      state: {},
      action: 'initialize'
    },
    future: []
  },
  isLoading: false,
  error: null,
  notifications: [],
  collaborators: [],
  sharedCursor: undefined,
  forms: {},
  views: {}
}

export const useSessionStore = create<SessionState & SessionActions>()(
  subscribeWithSelector(
    immer((set, get) => ({
      // Initial state
      sessionId: '',
      userId: '',
      ...initialState,

      // Session management
      initializeSession: (userId: string, documentId?: string) => {
        const sessionId = `session_${userId}_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
        set((state) => {
          state.sessionId = sessionId
          state.userId = userId
          state.documentId = documentId
          
          // Create initial snapshot
          state.history.present = {
            timestamp: Date.now(),
            state: {
              activeTab: state.activeTab,
              sidebarOpen: state.sidebarOpen,
              darkMode: state.darkMode,
              theme: state.theme,
              selectedDatasets: [...state.selectedDatasets],
              analysisParameters: { ...state.analysisParameters },
              currentWorkflow: state.currentWorkflow,
              searchQuery: state.searchQuery,
              filters: { ...state.filters }
            },
            action: 'initialize',
            description: 'Session initialized'
          }
        })
      },

      resetSession: () => {
        set((state) => {
          const { sessionId, userId } = state
          Object.assign(state, initialState)
          state.sessionId = sessionId
          state.userId = userId
        })
      },

      updateSession: (updates: Partial<SessionState>) => {
        set((state) => {
          Object.assign(state, updates)
        })
      },

      // UI actions
      setActiveTab: (tab: string) => {
        set((state) => {
          state.activeTab = tab
        })
        get().saveSnapshot('setActiveTab', `Switched to ${tab} tab`)
      },

      toggleSidebar: () => {
        set((state) => {
          state.sidebarOpen = !state.sidebarOpen
        })
        get().saveSnapshot('toggleSidebar', `Sidebar ${get().sidebarOpen ? 'opened' : 'closed'}`)
      },

      setDarkMode: (enabled: boolean) => {
        set((state) => {
          state.darkMode = enabled
        })
        get().saveSnapshot('setDarkMode', `Dark mode ${enabled ? 'enabled' : 'disabled'}`)
      },

      setTheme: (theme: string) => {
        set((state) => {
          state.theme = theme
        })
        get().saveSnapshot('setTheme', `Theme changed to ${theme}`)
      },

      // Application actions
      setSelectedDatasets: (datasets: string[]) => {
        set((state) => {
          state.selectedDatasets = datasets
        })
        get().saveSnapshot('setSelectedDatasets', `Selected ${datasets.length} datasets`)
      },

      updateAnalysisParameters: (parameters: Record<string, any>) => {
        set((state) => {
          Object.assign(state.analysisParameters, parameters)
        })
        get().saveSnapshot('updateAnalysisParameters', 'Updated analysis parameters')
      },

      setCurrentWorkflow: (workflow: string | null) => {
        set((state) => {
          state.currentWorkflow = workflow
        })
        get().saveSnapshot('setCurrentWorkflow', workflow ? `Set workflow: ${workflow}` : 'Cleared workflow')
      },

      setSearchQuery: (query: string) => {
        set((state) => {
          state.searchQuery = query
        })
        // Don't create history snapshots for search queries to avoid noise
      },

      updateFilters: (filters: Record<string, any>) => {
        set((state) => {
          Object.assign(state.filters, filters)
        })
        get().saveSnapshot('updateFilters', 'Updated filters')
      },

      // History actions (undo/redo)
      undo: () => {
        const { history } = get()
        if (history.past.length === 0) return

        set((state) => {
          const previous = state.history.past[state.history.past.length - 1]
          const newPast = state.history.past.slice(0, -1)
          const newFuture = [state.history.present, ...state.history.future]

          // Apply the previous state
          Object.assign(state, previous.state)
          
          state.history = {
            past: newPast,
            present: previous,
            future: newFuture
          }
        })
      },

      redo: () => {
        const { history } = get()
        if (history.future.length === 0) return

        set((state) => {
          const next = state.history.future[0]
          const newFuture = state.history.future.slice(1)
          const newPast = [...state.history.past, state.history.present]

          // Apply the next state
          Object.assign(state, next.state)
          
          state.history = {
            past: newPast,
            present: next,
            future: newFuture
          }
        })
      },

      clearHistory: () => {
        set((state) => {
          state.history = {
            past: [],
            present: state.history.present,
            future: []
          }
        })
      },

      canUndo: () => {
        return get().history.past.length > 0
      },

      canRedo: () => {
        return get().history.future.length > 0
      },

      saveSnapshot: (action: string, description?: string) => {
        const MAX_HISTORY_SIZE = 50
        
        set((state) => {
          const snapshot: SessionSnapshot = {
            timestamp: Date.now(),
            state: {
              activeTab: state.activeTab,
              sidebarOpen: state.sidebarOpen,
              darkMode: state.darkMode,
              theme: state.theme,
              selectedDatasets: [...state.selectedDatasets],
              analysisParameters: { ...state.analysisParameters },
              currentWorkflow: state.currentWorkflow,
              searchQuery: state.searchQuery,
              filters: { ...state.filters }
            },
            action,
            description
          }

          state.history.past.push(state.history.present)
          state.history.present = snapshot
          state.history.future = [] // Clear future when new action is performed

          // Limit history size
          if (state.history.past.length > MAX_HISTORY_SIZE) {
            state.history.past = state.history.past.slice(-MAX_HISTORY_SIZE)
          }
        })
      },

      // Notification actions
      addNotification: (notification) => {
        const id = `notification_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
        set((state) => {
          state.notifications.push({
            ...notification,
            id,
            timestamp: Date.now(),
            read: false
          })
        })
      },

      removeNotification: (id: string) => {
        set((state) => {
          state.notifications = state.notifications.filter(n => n.id !== id)
        })
      },

      markNotificationAsRead: (id: string) => {
        set((state) => {
          const notification = state.notifications.find(n => n.id === id)
          if (notification) {
            notification.read = true
          }
        })
      },

      clearNotifications: () => {
        set((state) => {
          state.notifications = []
        })
      },

      // Error handling
      setError: (error: string | null) => {
        set((state) => {
          state.error = error
        })
      },

      setLoading: (loading: boolean) => {
        set((state) => {
          state.isLoading = loading
        })
      },

      // Collaboration
      addCollaborator: (userId: string) => {
        set((state) => {
          if (!state.collaborators.includes(userId)) {
            state.collaborators.push(userId)
          }
        })
      },

      removeCollaborator: (userId: string) => {
        set((state) => {
          state.collaborators = state.collaborators.filter(id => id !== userId)
        })
      },

      updateSharedCursor: (cursor: { x: number; y: number } | undefined) => {
        set((state) => {
          state.sharedCursor = cursor
        })
      },

      // Form management
      initializeForm: (formId: string, initialValues = {}) => {
        set((state) => {
          state.forms[formId] = {
            values: { ...initialValues },
            errors: {},
            touched: {},
            isSubmitting: false,
            isDirty: false
          }
        })
      },

      updateFormValues: (formId: string, values: Record<string, any>) => {
        set((state) => {
          const form = state.forms[formId]
          if (form) {
            Object.assign(form.values, values)
            form.isDirty = true
          }
        })
      },

      setFormErrors: (formId: string, errors: Record<string, string[]>) => {
        set((state) => {
          const form = state.forms[formId]
          if (form) {
            form.errors = errors
          }
        })
      },

      touchFormField: (formId: string, field: string) => {
        set((state) => {
          const form = state.forms[formId]
          if (form) {
            form.touched[field] = true
          }
        })
      },

      setFormSubmitting: (formId: string, submitting: boolean) => {
        set((state) => {
          const form = state.forms[formId]
          if (form) {
            form.isSubmitting = submitting
          }
        })
      },

      resetForm: (formId: string) => {
        set((state) => {
          const form = state.forms[formId]
          if (form) {
            form.values = {}
            form.errors = {}
            form.touched = {}
            form.isSubmitting = false
            form.isDirty = false
          }
        })
      },

      removeForm: (formId: string) => {
        set((state) => {
          delete state.forms[formId]
        })
      },

      // View management
      updateView: (viewId: string, updates: Partial<ViewState>) => {
        set((state) => {
          if (!state.views[viewId]) {
            state.views[viewId] = {
              scroll: { x: 0, y: 0 },
              zoom: 1,
              selection: [],
              expanded: [],
              collapsed: []
            }
          }
          Object.assign(state.views[viewId], updates)
        })
      },

      resetView: (viewId: string) => {
        set((state) => {
          state.views[viewId] = {
            scroll: { x: 0, y: 0 },
            zoom: 1,
            selection: [],
            expanded: [],
            collapsed: []
          }
        })
      },

      removeView: (viewId: string) => {
        set((state) => {
          delete state.views[viewId]
        })
      }
    }))
  )
)

// Utility hooks
export const useUndo = () => {
  const undo = useSessionStore(state => state.undo)
  const canUndo = useSessionStore(state => state.canUndo())
  return { undo, canUndo }
}

export const useRedo = () => {
  const redo = useSessionStore(state => state.redo)
  const canRedo = useSessionStore(state => state.canRedo())
  return { redo, canRedo }
}

export const useNotifications = () => {
  const notifications = useSessionStore(state => state.notifications)
  const addNotification = useSessionStore(state => state.addNotification)
  const removeNotification = useSessionStore(state => state.removeNotification)
  const markAsRead = useSessionStore(state => state.markNotificationAsRead)
  const clearAll = useSessionStore(state => state.clearNotifications)
  
  const unreadCount = notifications.filter(n => !n.read).length
  
  return {
    notifications,
    unreadCount,
    addNotification,
    removeNotification,
    markAsRead,
    clearAll
  }
}

export const useForm = (formId: string, initialValues?: Record<string, any>) => {
  const form = useSessionStore(state => state.forms[formId])
  const initializeForm = useSessionStore(state => state.initializeForm)
  const updateValues = useSessionStore(state => state.updateFormValues)
  const setErrors = useSessionStore(state => state.setFormErrors)
  const touchField = useSessionStore(state => state.touchFormField)
  const setSubmitting = useSessionStore(state => state.setFormSubmitting)
  const resetForm = useSessionStore(state => state.resetForm)
  
  // Initialize form if it doesn't exist
  if (!form && initialValues !== undefined) {
    initializeForm(formId, initialValues)
  }
  
  return {
    values: form?.values || {},
    errors: form?.errors || {},
    touched: form?.touched || {},
    isSubmitting: form?.isSubmitting || false,
    isDirty: form?.isDirty || false,
    updateValues: (values: Record<string, any>) => updateValues(formId, values),
    setErrors: (errors: Record<string, string[]>) => setErrors(formId, errors),
    touchField: (field: string) => touchField(formId, field),
    setSubmitting: (submitting: boolean) => setSubmitting(formId, submitting),
    reset: () => resetForm(formId)
  }
}

export const useView = (viewId: string) => {
  const view = useSessionStore(state => state.views[viewId])
  const updateView = useSessionStore(state => state.updateView)
  const resetView = useSessionStore(state => state.resetView)
  
  const defaultView: ViewState = {
    scroll: { x: 0, y: 0 },
    zoom: 1,
    selection: [],
    expanded: [],
    collapsed: []
  }
  
  return {
    ...(view || defaultView),
    updateView: (updates: Partial<ViewState>) => updateView(viewId, updates),
    resetView: () => resetView(viewId)
  }
}