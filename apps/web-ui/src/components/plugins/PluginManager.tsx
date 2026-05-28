/**
 * PluginManager Component
 * Comprehensive plugin management interface with installation, configuration, and analytics
 */

import React, { useState, useEffect } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Progress } from '@/components/ui/progress'
import { ScrollArea } from '@/components/ui/scroll-area'
import { 
  Search, 
  Settings, 
  Package, 
  RefreshCw, 
  Trash2, 
  BarChart3, 
  Download, 
  AlertTriangle, 
  CheckCircle, 
  Clock, 
  Users, 
  HardDrive,
  Cpu,
  TrendingUp,
  TrendingDown,
  Activity,
  Shield,
  ExternalLink,
  Filter,
  MoreVertical,
  Play,
  Pause,
  Info,
  Star,
  Calendar,
  FileText
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { usePlugins } from '@/hooks/use-plugins'
import { PluginCard } from './PluginCard'
import { PluginConfig } from './PluginConfig'
import { PluginMarketplace } from './PluginMarketplace'
import type { Plugin, PluginUsageStats } from '@/types/plugins'

interface PluginManagerProps {
  className?: string
}

type ManagerView = 'overview' | 'installed' | 'marketplace' | 'configure' | 'analytics'

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

const formatDuration = (ms: number): string => {
  const seconds = Math.floor(ms / 1000)
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  
  if (hours > 0) return `${hours}h ${minutes}m`
  if (minutes > 0) return `${minutes}m`
  return `${seconds}s`
}

export function PluginManager({ className }: PluginManagerProps) {
  const {
    plugins,
    installed,
    installing,
    updates,
    loading,
    installPlugin,
    uninstallPlugin,
    updatePlugin,
    enablePlugin,
    disablePlugin,
    checkUpdates,
    updateAllPlugins,
    getUsageStats
  } = usePlugins()

  const [currentView, setCurrentView] = useState<ManagerView>('overview')
  const [selectedPlugin, setSelectedPlugin] = useState<Plugin | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [sortBy, setSortBy] = useState<'name' | 'usage' | 'updated'>('name')
  const [filterStatus, setFilterStatus] = useState<'all' | 'enabled' | 'disabled'>('all')
  const [usageStats, setUsageStats] = useState<Record<string, PluginUsageStats>>({})

  // Load usage stats for installed plugins
  useEffect(() => {
    const loadUsageStats = async () => {
      const stats: Record<string, PluginUsageStats> = {}
      
      for (const config of installed) {
        try {
          const pluginStats = await getUsageStats(config.pluginId)
          stats[config.pluginId] = pluginStats
        } catch (error) {
          console.error(`Failed to load stats for ${config.pluginId}:`, error)
        }
      }
      
      setUsageStats(stats)
    }

    if (installed.length > 0) {
      loadUsageStats()
    }
  }, [installed, getUsageStats])

  // Filter and sort installed plugins
  const filteredInstalledPlugins = plugins
    .filter(plugin => installed.some(config => config.pluginId === plugin.id))
    .filter(plugin => {
      const config = installed.find(c => c.pluginId === plugin.id)
      if (filterStatus === 'enabled' && !config?.enabled) return false
      if (filterStatus === 'disabled' && config?.enabled) return false
      if (searchQuery && !plugin.name.toLowerCase().includes(searchQuery.toLowerCase())) return false
      return true
    })
    .sort((a, b) => {
      switch (sortBy) {
        case 'usage':
          const statsA = usageStats[a.id]?.usage.totalTime || 0
          const statsB = usageStats[b.id]?.usage.totalTime || 0
          return statsB - statsA
        case 'updated':
          return new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()
        default:
          return a.name.localeCompare(b.name)
      }
    })

  const handlePluginAction = async (action: string, pluginId: string) => {
    try {
      switch (action) {
        case 'enable':
          await enablePlugin(pluginId)
          break
        case 'disable':
          await disablePlugin(pluginId)
          break
        case 'uninstall':
          await uninstallPlugin(pluginId)
          break
        case 'update':
          await updatePlugin(pluginId)
          break
        case 'configure':
          const plugin = plugins.find(p => p.id === pluginId)
          if (plugin) {
            setSelectedPlugin(plugin)
            setCurrentView('configure')
          }
          break
      }
    } catch (error) {
      console.error(`Failed to ${action} plugin ${pluginId}:`, error)
    }
  }

  const renderOverview = () => {
    const enabledCount = installed.filter(c => c.enabled).length
    const totalUsage = Object.values(usageStats).reduce((sum, stats) => sum + stats.usage.totalTime, 0)
    const totalMemory = Object.values(usageStats).reduce((sum, stats) => sum + (stats.performance?.memoryPeak || 0), 0)
    
    return (
      <div className="space-y-6">
        {/* Quick Stats */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <Card>
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-muted-foreground">Installed</p>
                  <p className="text-2xl font-bold">{installed.length}</p>
                </div>
                <Package className="w-8 h-8 text-blue-500" />
              </div>
              <p className="text-xs text-muted-foreground mt-2">
                {enabledCount} active, {installed.length - enabledCount} disabled
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-muted-foreground">Updates</p>
                  <p className="text-2xl font-bold">{updates.length}</p>
                </div>
                <RefreshCw className="w-8 h-8 text-green-500" />
              </div>
              <p className="text-xs text-muted-foreground mt-2">
                {updates.filter(u => u.critical).length} critical
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-muted-foreground">Total Usage</p>
                  <p className="text-2xl font-bold">{formatDuration(totalUsage)}</p>
                </div>
                <Clock className="w-8 h-8 text-purple-500" />
              </div>
              <p className="text-xs text-muted-foreground mt-2">
                This week
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-muted-foreground">Memory</p>
                  <p className="text-2xl font-bold">{formatBytes(totalMemory)}</p>
                </div>
                <HardDrive className="w-8 h-8 text-orange-500" />
              </div>
              <p className="text-xs text-muted-foreground mt-2">
                Peak usage
              </p>
            </CardContent>
          </Card>
        </div>

        {/* Recent Activity */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Activity className="w-5 h-5" />
              Recent Activity
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {installing.map(progress => (
                <div key={progress.pluginId} className="flex items-center justify-between p-3 bg-muted/50 rounded-lg">
                  <div className="flex items-center gap-3">
                    <div className="w-2 h-2 bg-blue-500 rounded-full animate-pulse" />
                    <div>
                      <div className="font-medium text-sm">Installing {progress.pluginId}</div>
                      <div className="text-xs text-muted-foreground capitalize">
                        {progress.status.replace('-', ' ')}
                      </div>
                    </div>
                  </div>
                  <Progress value={progress.progress} className="w-24 h-2" />
                </div>
              ))}

              {updates.length > 0 && (
                <div className="flex items-center justify-between p-3 bg-orange-50 border border-orange-200 rounded-lg">
                  <div className="flex items-center gap-3">
                    <RefreshCw className="w-4 h-4 text-orange-600" />
                    <div>
                      <div className="font-medium text-sm text-orange-900">
                        {updates.length} update{updates.length === 1 ? '' : 's'} available
                      </div>
                      <div className="text-xs text-orange-700">
                        {updates.filter(u => u.critical).length > 0 && 'Includes critical updates'}
                      </div>
                    </div>
                  </div>
                  <Button size="sm" variant="outline" onClick={() => updateAllPlugins()}>
                    Update All
                  </Button>
                </div>
              )}

              {installing.length === 0 && updates.length === 0 && (
                <div className="text-center py-6 text-muted-foreground">
                  <CheckCircle className="w-8 h-8 mx-auto mb-2 text-green-500" />
                  <p className="text-sm">All plugins are up to date</p>
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Top Plugins by Usage */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <TrendingUp className="w-5 h-5" />
              Most Used Plugins
            </CardTitle>
            <CardDescription>
              Plugin usage over the last 7 days
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {Object.entries(usageStats)
                .sort(([, a], [, b]) => b.usage.totalTime - a.usage.totalTime)
                .slice(0, 5)
                .map(([pluginId, stats]) => {
                  const plugin = plugins.find(p => p.id === pluginId)
                  if (!plugin) return null

                  return (
                    <div key={pluginId} className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        {plugin.icon ? (
                          <img src={plugin.icon} alt={plugin.name} className="w-8 h-8 rounded" />
                        ) : (
                          <div className="w-8 h-8 bg-muted rounded flex items-center justify-center">
                            <Package className="w-4 h-4" />
                          </div>
                        )}
                        <div>
                          <div className="font-medium text-sm">{plugin.name}</div>
                          <div className="text-xs text-muted-foreground">
                            {stats.usage.activations} activations
                          </div>
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="font-medium text-sm">{formatDuration(stats.usage.totalTime)}</div>
                        <div className="text-xs text-muted-foreground">
                          Avg: {formatDuration(stats.usage.averageSession)}
                        </div>
                      </div>
                    </div>
                  )
                })}
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  const renderInstalled = () => {
    return (
      <div className="space-y-6">
        {/* Filter Controls */}
        <div className="flex flex-col sm:flex-row gap-4">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              placeholder="Search installed plugins..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-10"
            />
          </div>
          
          <Select value={sortBy} onValueChange={(value: any) => setSortBy(value)}>
            <SelectTrigger className="w-[140px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="name">Name</SelectItem>
              <SelectItem value="usage">Usage</SelectItem>
              <SelectItem value="updated">Updated</SelectItem>
            </SelectContent>
          </Select>
          
          <Select value={filterStatus} onValueChange={(value: any) => setFilterStatus(value)}>
            <SelectTrigger className="w-[120px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All</SelectItem>
              <SelectItem value="enabled">Enabled</SelectItem>
              <SelectItem value="disabled">Disabled</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Plugin List */}
        {filteredInstalledPlugins.length === 0 ? (
          <div className="text-center py-12">
            <Package className="w-12 h-12 mx-auto text-muted-foreground mb-4" />
            <h3 className="text-lg font-semibold mb-2">No plugins found</h3>
            <p className="text-muted-foreground mb-4">
              {searchQuery || filterStatus !== 'all'
                ? 'Try adjusting your search or filters'
                : 'You haven\'t installed any plugins yet'}
            </p>
            <Button onClick={() => setCurrentView('marketplace')}>
              Browse Marketplace
            </Button>
          </div>
        ) : (
          <div className="grid gap-4">
            {filteredInstalledPlugins.map(plugin => {
              const config = installed.find(c => c.pluginId === plugin.id)
              const stats = usageStats[plugin.id]
              const update = updates.find(u => u.pluginId === plugin.id)
              const installProgress = installing.find(p => p.pluginId === plugin.id)

              return (
                <Card key={plugin.id} className="hover:shadow-md transition-shadow">
                  <CardContent className="p-6">
                    <div className="flex items-start justify-between">
                      <div className="flex items-start gap-4 flex-1">
                        {plugin.icon ? (
                          <img src={plugin.icon} alt={plugin.name} className="w-12 h-12 rounded-lg" />
                        ) : (
                          <div className="w-12 h-12 bg-muted rounded-lg flex items-center justify-center">
                            <Package className="w-6 h-6" />
                          </div>
                        )}
                        
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1">
                            <h3 className="font-semibold">{plugin.name}</h3>
                            {config?.enabled ? (
                              <Badge variant="default" className="bg-green-100 text-green-800">
                                <CheckCircle className="w-3 h-3 mr-1" />
                                Active
                              </Badge>
                            ) : (
                              <Badge variant="secondary">Disabled</Badge>
                            )}
                            {update && (
                              <Badge variant="outline" className="border-orange-200 text-orange-800">
                                Update Available
                              </Badge>
                            )}
                          </div>
                          
                          <p className="text-sm text-muted-foreground mb-2">
                            {plugin.shortDescription}
                          </p>
                          
                          <div className="flex items-center gap-4 text-sm text-muted-foreground">
                            <span>v{plugin.version}</span>
                            {stats && (
                              <>
                                <span>{formatDuration(stats.usage.totalTime)} used</span>
                                <span>{stats.usage.activations} activations</span>
                              </>
                            )}
                            {config?.lastUsed && (
                              <span>Last used: {new Date(config.lastUsed).toLocaleDateString()}</span>
                            )}
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center gap-2 ml-4">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handlePluginAction('configure', plugin.id)}
                        >
                          <Settings className="w-4 h-4" />
                        </Button>
                        
                        {config?.enabled ? (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => handlePluginAction('disable', plugin.id)}
                          >
                            <Pause className="w-4 h-4" />
                          </Button>
                        ) : (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => handlePluginAction('enable', plugin.id)}
                          >
                            <Play className="w-4 h-4" />
                          </Button>
                        )}
                        
                        {update && (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => handlePluginAction('update', plugin.id)}
                            disabled={Boolean(installProgress)}
                          >
                            <RefreshCw className="w-4 h-4" />
                          </Button>
                        )}
                        
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handlePluginAction('uninstall', plugin.id)}
                          disabled={Boolean(installProgress)}
                        >
                          <Trash2 className="w-4 h-4" />
                        </Button>
                      </div>
                    </div>

                    {installProgress && (
                      <div className="mt-4 space-y-2">
                        <div className="flex items-center justify-between text-sm">
                          <span className="capitalize">{installProgress.status.replace('-', ' ')}</span>
                          <span>{installProgress.progress.toFixed(0)}%</span>
                        </div>
                        <Progress value={installProgress.progress} className="h-1" />
                      </div>
                    )}
                  </CardContent>
                </Card>
              )
            })}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className={cn('flex flex-col h-full', className)}>
      {/* Header */}
      <div className="border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="flex items-center justify-between p-6">
          <div>
            <h1 className="text-2xl font-bold">Plugin Manager</h1>
            <p className="text-muted-foreground">
              Manage your installed plugins and discover new ones
            </p>
          </div>
          
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={checkUpdates} disabled={loading}>
              <RefreshCw className={cn('w-4 h-4 mr-2', loading && 'animate-spin')} />
              Check Updates
            </Button>
            <Button onClick={() => setCurrentView('marketplace')}>
              <Package className="w-4 h-4 mr-2" />
              Browse Marketplace
            </Button>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden">
        <Tabs value={currentView} onValueChange={(value: any) => setCurrentView(value)} className="flex flex-col h-full">
          <div className="border-b px-6">
            <TabsList className="grid w-full grid-cols-4">
              <TabsTrigger value="overview" className="flex items-center gap-2">
                <BarChart3 className="w-4 h-4" />
                Overview
              </TabsTrigger>
              <TabsTrigger value="installed" className="flex items-center gap-2">
                <Package className="w-4 h-4" />
                Installed ({installed.length})
              </TabsTrigger>
              <TabsTrigger value="marketplace" className="flex items-center gap-2">
                <Search className="w-4 h-4" />
                Marketplace
              </TabsTrigger>
              <TabsTrigger value="analytics" className="flex items-center gap-2">
                <Activity className="w-4 h-4" />
                Analytics
              </TabsTrigger>
            </TabsList>
          </div>

          <div className="flex-1 overflow-auto">
            <TabsContent value="overview" className="p-6 mt-0">
              {renderOverview()}
            </TabsContent>

            <TabsContent value="installed" className="p-6 mt-0">
              {renderInstalled()}
            </TabsContent>

            <TabsContent value="marketplace" className="mt-0">
              <PluginMarketplace onPluginSelect={(id) => {
                const plugin = plugins.find(p => p.id === id)
                if (plugin) {
                  setSelectedPlugin(plugin)
                  setCurrentView('configure')
                }
              }} />
            </TabsContent>

            <TabsContent value="analytics" className="p-6 mt-0">
              <div className="text-center py-12">
                <Activity className="w-12 h-12 mx-auto text-muted-foreground mb-4" />
                <h3 className="text-lg font-semibold mb-2">Analytics Dashboard</h3>
                <p className="text-muted-foreground">
                  Detailed plugin usage analytics coming soon
                </p>
              </div>
            </TabsContent>
          </div>
        </Tabs>
      </div>

      {/* Plugin Configuration Dialog */}
      <Dialog 
        open={currentView === 'configure' && selectedPlugin !== null} 
        onOpenChange={(open) => {
          if (!open) {
            setCurrentView('installed')
            setSelectedPlugin(null)
          }
        }}
      >
        <DialogContent className="sm:max-w-4xl max-h-[80vh]">
          <DialogHeader>
            <DialogTitle>Configure {selectedPlugin?.name}</DialogTitle>
            <DialogDescription>
              Customize plugin settings and behavior
            </DialogDescription>
          </DialogHeader>
          
          <ScrollArea className="max-h-[60vh] pr-6">
            {selectedPlugin && (
              <PluginConfig
                plugin={selectedPlugin}
                config={installed.find(c => c.pluginId === selectedPlugin.id)}
                onSave={() => {
                  setCurrentView('installed')
                  setSelectedPlugin(null)
                }}
                onCancel={() => {
                  setCurrentView('installed')
                  setSelectedPlugin(null)
                }}
              />
            )}
          </ScrollArea>
        </DialogContent>
      </Dialog>
    </div>
  )
}

export default PluginManager