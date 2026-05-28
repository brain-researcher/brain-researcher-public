/**
 * PluginCard Component
 * Displays individual plugin information in marketplace and management views
 */

import React from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { Switch } from '@/components/ui/switch'
import { 
  Download, 
  Star, 
  Shield, 
  Settings, 
  Trash2, 
  RefreshCw, 
  ExternalLink,
  AlertTriangle,
  Check,
  Loader2,
  Users,
  Calendar,
  HardDrive
} from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Plugin, PluginInstallationProgress, PluginConfiguration, PluginUpdate } from '@/types/plugins'

interface PluginCardProps {
  plugin: Plugin
  installed?: PluginConfiguration
  installing?: PluginInstallationProgress
  update?: PluginUpdate
  variant?: 'marketplace' | 'installed' | 'compact'
  onInstall?: (id: string) => void
  onUninstall?: (id: string) => void
  onUpdate?: (id: string) => void
  onConfigure?: (id: string) => void
  onToggleEnabled?: (id: string, enabled: boolean) => void
  onViewDetails?: (id: string) => void
  className?: string
}

const categoryColors = {
  'analysis-tools': 'bg-blue-100 text-blue-800 border-blue-200',
  'visualization': 'bg-green-100 text-green-800 border-green-200',
  'data-import': 'bg-purple-100 text-purple-800 border-purple-200',
  'data-export': 'bg-orange-100 text-orange-800 border-orange-200',
  'preprocessing': 'bg-pink-100 text-pink-800 border-pink-200',
  'utilities': 'bg-gray-100 text-gray-800 border-gray-200',
  'integrations': 'bg-indigo-100 text-indigo-800 border-indigo-200',
  'workflows': 'bg-teal-100 text-teal-800 border-teal-200'
}

const formatBytes = (bytes: number): string => {
  const units = ['B', 'KB', 'MB', 'GB']
  let size = bytes
  let unitIndex = 0
  
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex++
  }
  
  return `${size.toFixed(1)} ${units[unitIndex]}`
}

const formatNumber = (num: number): string => {
  if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`
  if (num >= 1000) return `${(num / 1000).toFixed(1)}K`
  return num.toString()
}

export function PluginCard({
  plugin,
  installed,
  installing,
  update,
  variant = 'marketplace',
  onInstall,
  onUninstall,
  onUpdate,
  onConfigure,
  onToggleEnabled,
  onViewDetails,
  className
}: PluginCardProps) {
  const isInstalled = Boolean(installed)
  const isInstalling = Boolean(installing)
  const hasUpdate = Boolean(update)
  const isEnabled = installed?.enabled ?? false
  
  const handleInstall = () => {
    onInstall?.(plugin.id)
  }
  
  const handleUninstall = () => {
    onUninstall?.(plugin.id)
  }
  
  const handleUpdate = () => {
    onUpdate?.(plugin.id)
  }
  
  const handleConfigure = () => {
    onConfigure?.(plugin.id)
  }
  
  const handleToggleEnabled = (enabled: boolean) => {
    onToggleEnabled?.(plugin.id, enabled)
  }
  
  const handleViewDetails = () => {
    onViewDetails?.(plugin.id)
  }

  const renderInstallButton = () => {
    if (isInstalling) {
      return (
        <div className="space-y-2">
          <Button disabled className="w-full">
            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            {installing?.status === 'downloading' ? 'Downloading...' :
             installing?.status === 'extracting' ? 'Extracting...' :
             installing?.status === 'installing' ? 'Installing...' :
             installing?.status === 'configuring' ? 'Configuring...' :
             'Installing...'}
          </Button>
          {installing && (
            <div className="space-y-1">
              <Progress value={installing.progress} className="h-1" />
              {installing.message && (
                <p className="text-xs text-muted-foreground">{installing.message}</p>
              )}
            </div>
          )}
        </div>
      )
    }

    if (isInstalled) {
      return (
        <div className="flex gap-2">
          {hasUpdate && (
            <Button onClick={handleUpdate} variant="outline" size="sm">
              <RefreshCw className="w-4 h-4 mr-2" />
              Update
            </Button>
          )}
          <Button onClick={handleConfigure} variant="outline" size="sm">
            <Settings className="w-4 h-4 mr-2" />
            Configure
          </Button>
          <Button onClick={handleUninstall} variant="outline" size="sm">
            <Trash2 className="w-4 h-4 mr-2" />
            Remove
          </Button>
        </div>
      )
    }

    return (
      <Button onClick={handleInstall} className="w-full">
        <Download className="w-4 h-4 mr-2" />
        Install
      </Button>
    )
  }

  const renderStatus = () => {
    if (isInstalling) {
      return (
        <Badge variant="secondary" className="animate-pulse">
          <Loader2 className="w-3 h-3 mr-1 animate-spin" />
          Installing
        </Badge>
      )
    }

    if (hasUpdate) {
      return (
        <Badge variant="outline" className="border-orange-200 text-orange-800">
          <RefreshCw className="w-3 h-3 mr-1" />
          Update Available
        </Badge>
      )
    }

    if (isInstalled) {
      return isEnabled ? (
        <Badge variant="default" className="bg-green-100 text-green-800 border-green-200">
          <Check className="w-3 h-3 mr-1" />
          Active
        </Badge>
      ) : (
        <Badge variant="secondary">
          Disabled
        </Badge>
      )
    }

    if (plugin.status === 'deprecated') {
      return (
        <Badge variant="outline" className="border-red-200 text-red-800">
          <AlertTriangle className="w-3 h-3 mr-1" />
          Deprecated
        </Badge>
      )
    }

    return null
  }

  if (variant === 'compact') {
    return (
      <Card className={cn('hover:shadow-md transition-shadow', className)}>
        <CardContent className="p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3 flex-1 min-w-0">
              {plugin.icon ? (
                <img src={plugin.icon} alt={plugin.name} className="w-8 h-8 rounded" />
              ) : (
                <div className="w-8 h-8 bg-muted rounded flex items-center justify-center">
                  <Shield className="w-4 h-4" />
                </div>
              )}
              
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <h3 className="font-medium truncate">{plugin.name}</h3>
                  {renderStatus()}
                </div>
                <p className="text-sm text-muted-foreground truncate">
                  {plugin.shortDescription}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2 ml-4">
              {isInstalled && onToggleEnabled && (
                <Switch
                  checked={isEnabled}
                  onCheckedChange={handleToggleEnabled}
                  aria-label={`${isEnabled ? 'Disable' : 'Enable'} ${plugin.name}`}
                />
              )}
              
              {!isInstalled && (
                <Button onClick={handleInstall} size="sm" disabled={isInstalling}>
                  {isInstalling ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Download className="w-4 h-4" />
                  )}
                </Button>
              )}
            </div>
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className={cn('hover:shadow-lg transition-all duration-200', className)}>
      <CardHeader>
        <div className="flex items-start justify-between">
          <div className="flex items-start gap-3 flex-1">
            {plugin.icon ? (
              <img 
                src={plugin.icon} 
                alt={`${plugin.name} icon`} 
                className="w-12 h-12 rounded-lg object-cover"
              />
            ) : (
              <div className="w-12 h-12 bg-muted rounded-lg flex items-center justify-center">
                <Shield className="w-6 h-6 text-muted-foreground" />
              </div>
            )}
            
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <CardTitle className="text-lg">{plugin.name}</CardTitle>
                {plugin.author.verified && (
                  <Badge variant="outline" className="text-blue-600 border-blue-200">
                    <Shield className="w-3 h-3 mr-1" />
                    Verified
                  </Badge>
                )}
                {renderStatus()}
              </div>
              
              <div className="flex items-center gap-4 mt-1 text-sm text-muted-foreground">
                <span>by {plugin.author.name}</span>
                <div className="flex items-center gap-1">
                  <Star className="w-3 h-3 fill-current text-yellow-400" />
                  <span>{plugin.rating.average.toFixed(1)}</span>
                  <span>({formatNumber(plugin.rating.count)})</span>
                </div>
              </div>
            </div>
          </div>
          
          {variant === 'marketplace' && (
            <Button
              onClick={handleViewDetails}
              variant="ghost"
              size="sm"
              className="shrink-0"
            >
              <ExternalLink className="w-4 h-4" />
            </Button>
          )}
        </div>
        
        <CardDescription className="line-clamp-2">
          {plugin.description}
        </CardDescription>
        
        <div className="flex items-center gap-2 flex-wrap">
          <Badge 
            variant="outline" 
            className={categoryColors[plugin.category] || categoryColors.utilities}
          >
            {plugin.category.replace('-', ' ')}
          </Badge>
          
          {plugin.tags.slice(0, 3).map(tag => (
            <Badge key={tag} variant="secondary" className="text-xs">
              {tag}
            </Badge>
          ))}
          
          {plugin.tags.length > 3 && (
            <Badge variant="secondary" className="text-xs">
              +{plugin.tags.length - 3}
            </Badge>
          )}
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {variant === 'installed' && installed && (
          <div className="flex items-center justify-between p-3 bg-muted/50 rounded-lg">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">Status:</span>
              <Switch
                checked={isEnabled}
                onCheckedChange={handleToggleEnabled}
                aria-label={`${isEnabled ? 'Disable' : 'Enable'} ${plugin.name}`}
              />
              <span className="text-sm text-muted-foreground">
                {isEnabled ? 'Enabled' : 'Disabled'}
              </span>
            </div>
            
            {installed.lastUsed && (
              <div className="text-sm text-muted-foreground">
                Last used: {new Date(installed.lastUsed).toLocaleDateString()}
              </div>
            )}
          </div>
        )}

        {hasUpdate && (
          <div className="p-3 bg-orange-50 border border-orange-200 rounded-lg">
            <div className="flex items-center gap-2 mb-2">
              <RefreshCw className="w-4 h-4 text-orange-600" />
              <span className="font-medium text-orange-900">Update Available</span>
            </div>
            <div className="text-sm text-orange-800">
              Version {update.currentVersion} → {update.availableVersion}
              {update.critical && (
                <Badge variant="destructive" className="ml-2">Critical</Badge>
              )}
            </div>
          </div>
        )}

        <div className="grid grid-cols-2 gap-4 text-sm">
          <div className="space-y-1">
            <div className="flex items-center gap-1 text-muted-foreground">
              <Download className="w-3 h-3" />
              <span>Downloads</span>
            </div>
            <div className="font-medium">{formatNumber(plugin.downloads)}</div>
          </div>
          
          <div className="space-y-1">
            <div className="flex items-center gap-1 text-muted-foreground">
              <HardDrive className="w-3 h-3" />
              <span>Size</span>
            </div>
            <div className="font-medium">{formatBytes(plugin.size)}</div>
          </div>
          
          <div className="space-y-1">
            <div className="flex items-center gap-1 text-muted-foreground">
              <Users className="w-3 h-3" />
              <span>Version</span>
            </div>
            <div className="font-medium">{plugin.version}</div>
          </div>
          
          <div className="space-y-1">
            <div className="flex items-center gap-1 text-muted-foreground">
              <Calendar className="w-3 h-3" />
              <span>Updated</span>
            </div>
            <div className="font-medium">
              {new Date(plugin.updatedAt).toLocaleDateString()}
            </div>
          </div>
        </div>

        {plugin.permissions.length > 0 && (
          <div className="space-y-2">
            <div className="text-sm font-medium">Permissions Required:</div>
            <div className="flex flex-wrap gap-1">
              {plugin.permissions.slice(0, 3).map(perm => (
                <Badge key={perm.permission} variant="outline" className="text-xs">
                  {perm.permission.replace('-', ' ')}
                </Badge>
              ))}
              {plugin.permissions.length > 3 && (
                <Badge variant="outline" className="text-xs">
                  +{plugin.permissions.length - 3} more
                </Badge>
              )}
            </div>
          </div>
        )}
      </CardContent>

      <CardFooter className="pt-0">
        {renderInstallButton()}
      </CardFooter>
    </Card>
  )
}

export default PluginCard