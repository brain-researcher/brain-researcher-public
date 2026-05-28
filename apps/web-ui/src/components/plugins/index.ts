/**
 * Plugin System Components Export
 * Centralized exports for all plugin-related components
 */

export { PluginCard } from './PluginCard'
export { PluginMarketplace } from './PluginMarketplace'
export { PluginInstaller } from './PluginInstaller'
export { PluginConfig } from './PluginConfig'
export { PluginManager } from './PluginManager'
export { PluginPermissions } from './PluginPermissions'

// Re-export types for convenience
export type {
  Plugin,
  PluginCategory,
  PluginStatus,
  PluginPermission,
  PluginPermissionDetails,
  PluginConfiguration,
  PluginInstallationProgress,
  PluginUpdate,
  PluginUsageStats,
  PluginMarketplaceFilters,
  PluginSearchResult,
  PluginState,
  PluginActions,
  PluginConfigField
} from '@/types/plugins'

// Re-export hook
export { usePlugins } from '@/hooks/use-plugins'