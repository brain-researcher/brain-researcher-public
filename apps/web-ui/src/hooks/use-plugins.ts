/**
 * Plugin Management Hook for Brain Researcher
 * Provides state management and actions for the plugin system
 */

import { useState, useCallback, useEffect } from 'react'
import { useToast } from './use-toast'
import { serviceEndpoints } from '@/lib/service-endpoints'
import type {
  Plugin,
  PluginConfiguration,
  PluginInstallationProgress,
  PluginUpdate,
  PluginState,
  PluginActions,
  PluginMarketplaceFilters,
  PluginSearchResult,
  PluginUsageStats
} from '@/types/plugins'

// Mock API endpoints - would be replaced with actual API calls
const API_BASE = serviceEndpoints.orchestrator('/api/plugins')

class PluginAPI {
  static async searchPlugins(filters: Partial<PluginMarketplaceFilters>): Promise<PluginSearchResult> {
    const params = new URLSearchParams()
    
    if (filters.search) params.append('search', filters.search)
    if (filters.categories) params.append('categories', filters.categories.join(','))
    if (filters.tags) params.append('tags', filters.tags.join(','))
    if (filters.minRating) params.append('minRating', filters.minRating.toString())
    if (filters.freeOnly) params.append('freeOnly', 'true')
    if (filters.verifiedOnly) params.append('verifiedOnly', 'true')
    if (filters.compatibleOnly) params.append('compatibleOnly', 'true')
    if (filters.sortBy) params.append('sortBy', filters.sortBy)
    if (filters.sortOrder) params.append('sortOrder', filters.sortOrder)
    
    const response = await fetch(`${API_BASE}/search?${params}`)
    if (!response.ok) throw new Error('Failed to search plugins')
    return response.json()
  }

  static async getPlugin(id: string): Promise<Plugin> {
    const response = await fetch(`${API_BASE}/${id}`)
    if (!response.ok) throw new Error(`Failed to get plugin ${id}`)
    return response.json()
  }

  static async getInstalledPlugins(): Promise<PluginConfiguration[]> {
    const response = await fetch(`${API_BASE}/installed`)
    if (!response.ok) throw new Error('Failed to get installed plugins')
    return response.json()
  }

  static async installPlugin(id: string, version?: string): Promise<void> {
    const response = await fetch(`${API_BASE}/${id}/install`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ version })
    })
    if (!response.ok) throw new Error(`Failed to install plugin ${id}`)
  }

  static async uninstallPlugin(id: string): Promise<void> {
    const response = await fetch(`${API_BASE}/${id}/uninstall`, {
      method: 'POST'
    })
    if (!response.ok) throw new Error(`Failed to uninstall plugin ${id}`)
  }

  static async updatePlugin(id: string, version?: string): Promise<void> {
    const response = await fetch(`${API_BASE}/${id}/update`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ version })
    })
    if (!response.ok) throw new Error(`Failed to update plugin ${id}`)
  }

  static async configurePlugin(id: string, config: Record<string, any>): Promise<void> {
    const response = await fetch(`${API_BASE}/${id}/config`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config)
    })
    if (!response.ok) throw new Error(`Failed to configure plugin ${id}`)
  }

  static async enablePlugin(id: string): Promise<void> {
    const response = await fetch(`${API_BASE}/${id}/enable`, {
      method: 'POST'
    })
    if (!response.ok) throw new Error(`Failed to enable plugin ${id}`)
  }

  static async disablePlugin(id: string): Promise<void> {
    const response = await fetch(`${API_BASE}/${id}/disable`, {
      method: 'POST'
    })
    if (!response.ok) throw new Error(`Failed to disable plugin ${id}`)
  }

  static async checkUpdates(): Promise<PluginUpdate[]> {
    const response = await fetch(`${API_BASE}/updates`)
    if (!response.ok) throw new Error('Failed to check for updates')
    return response.json()
  }

  static async getInstallationProgress(): Promise<PluginInstallationProgress[]> {
    const response = await fetch(`${API_BASE}/installation-progress`)
    if (!response.ok) return []
    return response.json()
  }

  static async getUsageStats(id: string, period?: { start: string; end: string }): Promise<PluginUsageStats> {
    const params = new URLSearchParams()
    if (period) {
      params.append('start', period.start)
      params.append('end', period.end)
    }
    
    const response = await fetch(`${API_BASE}/${id}/stats?${params}`)
    if (!response.ok) throw new Error(`Failed to get usage stats for plugin ${id}`)
    return response.json()
  }
}

export function usePlugins(): PluginState & PluginActions {
  const { toast } = useToast()
  
  const [state, setState] = useState<PluginState>({
    plugins: [],
    installed: [],
    installing: [],
    updates: [],
    loading: false,
    error: undefined
  })

  // Load initial data
  useEffect(() => {
    const loadInitialData = async () => {
      try {
        setState(prev => ({ ...prev, loading: true }))
        
        const [installed, updates, installing] = await Promise.all([
          PluginAPI.getInstalledPlugins().catch(() => []),
          PluginAPI.checkUpdates().catch(() => []),
          PluginAPI.getInstallationProgress().catch(() => [])
        ])

        setState(prev => ({
          ...prev,
          installed,
          updates,
          installing,
          loading: false
        }))
      } catch (error) {
        setState(prev => ({
          ...prev,
          error: error instanceof Error ? error.message : 'Failed to load plugin data',
          loading: false
        }))
      }
    }

    loadInitialData()
  }, [])

  // Poll for installation progress
  useEffect(() => {
    if (state.installing.length === 0) return

    const interval = setInterval(async () => {
      try {
        const installing = await PluginAPI.getInstallationProgress()
        setState(prev => ({ ...prev, installing }))
        
        // Refresh installed list if any installations completed
        if (installing.length < state.installing.length) {
          const installed = await PluginAPI.getInstalledPlugins()
          setState(prev => ({ ...prev, installed }))
        }
      } catch (error) {
        console.error('Failed to update installation progress:', error)
      }
    }, 1000)

    return () => clearInterval(interval)
  }, [state.installing.length])

  const searchPlugins = useCallback(async (filters: Partial<PluginMarketplaceFilters>): Promise<PluginSearchResult> => {
    try {
      setState(prev => ({ ...prev, loading: true, error: undefined }))
      const result = await PluginAPI.searchPlugins(filters)
      setState(prev => ({ ...prev, plugins: result.plugins, loading: false }))
      return result
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to search plugins'
      setState(prev => ({ ...prev, error: message, loading: false }))
      toast({
        title: 'Search Failed',
        description: message,
        variant: 'destructive'
      })
      throw error
    }
  }, [toast])

  const getPlugin = useCallback(async (id: string): Promise<Plugin> => {
    try {
      return await PluginAPI.getPlugin(id)
    } catch (error) {
      const message = error instanceof Error ? error.message : `Failed to get plugin ${id}`
      toast({
        title: 'Plugin Load Failed',
        description: message,
        variant: 'destructive'
      })
      throw error
    }
  }, [toast])

  const installPlugin = useCallback(async (id: string, version?: string): Promise<void> => {
    try {
      await PluginAPI.installPlugin(id, version)
      toast({
        title: 'Installation Started',
        description: `Installing plugin ${id}...`
      })
      
      // Start polling for progress
      const installing = await PluginAPI.getInstallationProgress()
      setState(prev => ({ ...prev, installing }))
    } catch (error) {
      const message = error instanceof Error ? error.message : `Failed to install plugin ${id}`
      toast({
        title: 'Installation Failed',
        description: message,
        variant: 'destructive'
      })
      throw error
    }
  }, [toast])

  const uninstallPlugin = useCallback(async (id: string): Promise<void> => {
    try {
      await PluginAPI.uninstallPlugin(id)
      
      // Update installed list
      const installed = state.installed.filter(p => p.pluginId !== id)
      setState(prev => ({ ...prev, installed }))
      
      toast({
        title: 'Plugin Uninstalled',
        description: `Plugin ${id} has been removed.`
      })
    } catch (error) {
      const message = error instanceof Error ? error.message : `Failed to uninstall plugin ${id}`
      toast({
        title: 'Uninstall Failed',
        description: message,
        variant: 'destructive'
      })
      throw error
    }
  }, [state.installed, toast])

  const updatePlugin = useCallback(async (id: string, version?: string): Promise<void> => {
    try {
      await PluginAPI.updatePlugin(id, version)
      
      // Start polling for progress
      const installing = await PluginAPI.getInstallationProgress()
      setState(prev => ({ ...prev, installing }))
      
      toast({
        title: 'Update Started',
        description: `Updating plugin ${id}...`
      })
    } catch (error) {
      const message = error instanceof Error ? error.message : `Failed to update plugin ${id}`
      toast({
        title: 'Update Failed',
        description: message,
        variant: 'destructive'
      })
      throw error
    }
  }, [toast])

  const configurePlugin = useCallback(async (id: string, config: Record<string, any>): Promise<void> => {
    try {
      await PluginAPI.configurePlugin(id, config)
      
      // Update installed list with new config
      const installed = state.installed.map(p => 
        p.pluginId === id 
          ? { ...p, config, lastModified: new Date().toISOString() }
          : p
      )
      setState(prev => ({ ...prev, installed }))
      
      toast({
        title: 'Configuration Saved',
        description: `Plugin ${id} configuration updated.`
      })
    } catch (error) {
      const message = error instanceof Error ? error.message : `Failed to configure plugin ${id}`
      toast({
        title: 'Configuration Failed',
        description: message,
        variant: 'destructive'
      })
      throw error
    }
  }, [state.installed, toast])

  const enablePlugin = useCallback(async (id: string): Promise<void> => {
    try {
      await PluginAPI.enablePlugin(id)
      
      // Update installed list
      const installed = state.installed.map(p =>
        p.pluginId === id ? { ...p, enabled: true } : p
      )
      setState(prev => ({ ...prev, installed }))
      
      toast({
        title: 'Plugin Enabled',
        description: `Plugin ${id} is now active.`
      })
    } catch (error) {
      const message = error instanceof Error ? error.message : `Failed to enable plugin ${id}`
      toast({
        title: 'Enable Failed',
        description: message,
        variant: 'destructive'
      })
      throw error
    }
  }, [state.installed, toast])

  const disablePlugin = useCallback(async (id: string): Promise<void> => {
    try {
      await PluginAPI.disablePlugin(id)
      
      // Update installed list
      const installed = state.installed.map(p =>
        p.pluginId === id ? { ...p, enabled: false } : p
      )
      setState(prev => ({ ...prev, installed }))
      
      toast({
        title: 'Plugin Disabled',
        description: `Plugin ${id} is now inactive.`
      })
    } catch (error) {
      const message = error instanceof Error ? error.message : `Failed to disable plugin ${id}`
      toast({
        title: 'Disable Failed',
        description: message,
        variant: 'destructive'
      })
      throw error
    }
  }, [state.installed, toast])

  const checkUpdates = useCallback(async (): Promise<PluginUpdate[]> => {
    try {
      const updates = await PluginAPI.checkUpdates()
      setState(prev => ({ ...prev, updates }))
      
      if (updates.length > 0) {
        toast({
          title: 'Updates Available',
          description: `${updates.length} plugin${updates.length === 1 ? '' : 's'} can be updated.`
        })
      }
      
      return updates
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to check for updates'
      toast({
        title: 'Update Check Failed',
        description: message,
        variant: 'destructive'
      })
      throw error
    }
  }, [toast])

  const updateAllPlugins = useCallback(async (): Promise<void> => {
    try {
      const updatePromises = state.updates.map(update => 
        PluginAPI.updatePlugin(update.pluginId, update.availableVersion)
      )
      
      await Promise.all(updatePromises)
      
      // Start polling for progress
      const installing = await PluginAPI.getInstallationProgress()
      setState(prev => ({ ...prev, installing, updates: [] }))
      
      toast({
        title: 'Updates Started',
        description: `Updating ${state.updates.length} plugin${state.updates.length === 1 ? '' : 's'}...`
      })
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to update plugins'
      toast({
        title: 'Update Failed',
        description: message,
        variant: 'destructive'
      })
      throw error
    }
  }, [state.updates, toast])

  const getUsageStats = useCallback(async (id: string, period?: { start: string; end: string }): Promise<PluginUsageStats> => {
    try {
      return await PluginAPI.getUsageStats(id, period)
    } catch (error) {
      const message = error instanceof Error ? error.message : `Failed to get usage stats for plugin ${id}`
      toast({
        title: 'Stats Load Failed',
        description: message,
        variant: 'destructive'
      })
      throw error
    }
  }, [toast])

  return {
    // State
    ...state,
    
    // Actions
    searchPlugins,
    getPlugin,
    installPlugin,
    uninstallPlugin,
    updatePlugin,
    configurePlugin,
    enablePlugin,
    disablePlugin,
    checkUpdates,
    updateAllPlugins,
    getUsageStats
  }
}

export default usePlugins
