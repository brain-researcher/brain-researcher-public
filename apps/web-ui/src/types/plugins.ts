/**
 * Plugin System Types for Brain Researcher
 * Defines interfaces for plugin management, installation, and configuration
 */

export type PluginCategory = 
  | 'analysis-tools'
  | 'visualization' 
  | 'data-import'
  | 'data-export'
  | 'preprocessing'
  | 'utilities'
  | 'integrations'
  | 'workflows'

export type PluginStatus = 
  | 'available'
  | 'installing'
  | 'installed'
  | 'updating'
  | 'error'
  | 'disabled'
  | 'deprecated'

export type PluginPermission = 
  | 'file-system'
  | 'network'
  | 'compute'
  | 'data-access'
  | 'user-data'
  | 'system-integration'
  | 'external-apis'

export interface PluginVersion {
  version: string
  releaseDate: string
  changelog: string[]
  compatibility: {
    minVersion: string
    maxVersion?: string
  }
  downloadUrl: string
  checksum: string
}

export interface PluginAuthor {
  name: string
  email?: string
  url?: string
  avatar?: string
  verified: boolean
}

export interface PluginRating {
  average: number
  count: number
  distribution: {
    '1': number
    '2': number
    '3': number
    '4': number
    '5': number
  }
}

export interface PluginDependency {
  name: string
  version: string
  optional?: boolean
  reason?: string
}

export interface PluginConfigField {
  key: string
  label: string
  description?: string
  type: 'string' | 'number' | 'boolean' | 'select' | 'multiselect' | 'file' | 'directory'
  required?: boolean
  defaultValue?: any
  options?: Array<{ label: string; value: any }>
  validation?: {
    min?: number
    max?: number
    pattern?: string
    customValidator?: string
  }
}

export interface PluginPermissionDetails {
  permission: PluginPermission
  description: string
  required: boolean
  justification: string
}

export interface Plugin {
  id: string
  name: string
  description: string
  shortDescription: string
  category: PluginCategory
  tags: string[]
  
  // Version info
  version: string
  versions: PluginVersion[]
  
  // Author info
  author: PluginAuthor
  contributors?: PluginAuthor[]
  
  // Repository and links
  repository?: string
  homepage?: string
  documentation?: string
  bugReports?: string
  
  // Media
  icon?: string
  screenshots: string[]
  videos?: string[]
  
  // Installation and compatibility
  size: number
  installSize?: number
  dependencies: PluginDependency[]
  
  // Permissions and security
  permissions: PluginPermissionDetails[]
  
  // Rating and community
  rating: PluginRating
  downloads: number
  weeklyDownloads: number
  
  // Metadata
  createdAt: string
  updatedAt: string
  license: string
  
  // Configuration
  configSchema?: PluginConfigField[]
  
  // Status
  status: PluginStatus
  installed?: {
    version: string
    installedAt: string
    configuredAt?: string
    lastUsed?: string
    usageCount: number
  }
  
  // Performance and analytics
  performance?: {
    averageLoadTime: number
    memoryUsage: number
    cpuUsage: number
    errorRate: number
  }
}

export interface PluginInstallationProgress {
  pluginId: string
  status: 'downloading' | 'extracting' | 'installing' | 'configuring' | 'completing' | 'error'
  progress: number // 0-100
  message?: string
  error?: string
  startTime: string
  estimatedCompletion?: string
}

export interface PluginConfiguration {
  pluginId: string
  version: string
  enabled: boolean
  config: Record<string, any>
  lastModified: string
  autoUpdate: boolean
  lastUsed?: string
}

export interface PluginUpdate {
  pluginId: string
  currentVersion: string
  availableVersion: string
  updateType: 'major' | 'minor' | 'patch'
  changelog: string[]
  size: number
  critical: boolean
  releaseDate: string
}

export interface PluginUsageStats {
  pluginId: string
  timePeriod: {
    start: string
    end: string
  }
  usage: {
    activations: number
    totalTime: number
    averageSession: number
    errors: number
    crashes: number
  }
  performance: {
    averageLoadTime: number
    memoryPeak: number
    cpuAverage: number
  }
}

export interface PluginMarketplaceFilters {
  categories: PluginCategory[]
  tags: string[]
  minRating?: number
  freeOnly?: boolean
  verifiedOnly?: boolean
  compatibleOnly?: boolean
  search?: string
  sortBy: 'relevance' | 'popularity' | 'rating' | 'updated' | 'name'
  sortOrder: 'asc' | 'desc'
}

export interface PluginSearchResult {
  plugins: Plugin[]
  total: number
  page: number
  pageSize: number
  facets: {
    categories: Array<{ category: PluginCategory; count: number }>
    tags: Array<{ tag: string; count: number }>
    authors: Array<{ author: string; count: number }>
  }
}

// Hook interfaces
export interface PluginState {
  plugins: Plugin[]
  installed: PluginConfiguration[]
  installing: PluginInstallationProgress[]
  updates: PluginUpdate[]
  loading: boolean
  error?: string
}

export interface PluginActions {
  // Marketplace
  searchPlugins: (filters: Partial<PluginMarketplaceFilters>) => Promise<PluginSearchResult>
  getPlugin: (id: string) => Promise<Plugin>
  
  // Installation
  installPlugin: (id: string, version?: string) => Promise<void>
  uninstallPlugin: (id: string) => Promise<void>
  updatePlugin: (id: string, version?: string) => Promise<void>
  
  // Configuration
  configurePlugin: (id: string, config: Record<string, any>) => Promise<void>
  enablePlugin: (id: string) => Promise<void>
  disablePlugin: (id: string) => Promise<void>
  
  // Updates
  checkUpdates: () => Promise<PluginUpdate[]>
  updateAllPlugins: () => Promise<void>
  
  // Analytics
  getUsageStats: (id: string, period?: { start: string; end: string }) => Promise<PluginUsageStats>
}