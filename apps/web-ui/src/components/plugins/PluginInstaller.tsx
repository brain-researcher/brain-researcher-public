/**
 * PluginInstaller Component
 * Handles plugin installation flow with detailed progress tracking and rollback capabilities
 */

import React, { useState, useEffect } from 'react'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { 
  Download, 
  Shield, 
  AlertTriangle, 
  CheckCircle, 
  XCircle, 
  Loader2, 
  Package, 
  HardDrive,
  Clock,
  ArrowLeft,
  ExternalLink,
  FileText,
  Users,
  Star,
  Eye,
  EyeOff,
  Info
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { usePlugins } from '@/hooks/use-plugins'
import { PluginPermissions } from './PluginPermissions'
import type { Plugin, PluginInstallationProgress } from '@/types/plugins'

interface PluginInstallerProps {
  pluginId: string
  open: boolean
  onClose: () => void
  onInstallComplete?: (pluginId: string) => void
  onInstallError?: (pluginId: string, error: string) => void
}

type InstallStep = 'overview' | 'permissions' | 'dependencies' | 'installing' | 'complete' | 'error'

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
  const minutes = Math.floor(seconds / 60)
  
  if (minutes > 0) {
    return `${minutes}m ${seconds % 60}s`
  }
  return `${seconds}s`
}

export function PluginInstaller({ 
  pluginId, 
  open, 
  onClose, 
  onInstallComplete,
  onInstallError 
}: PluginInstallerProps) {
  const { getPlugin, installPlugin, installing } = usePlugins()
  
  const [plugin, setPlugin] = useState<Plugin | null>(null)
  const [currentStep, setCurrentStep] = useState<InstallStep>('overview')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [showAdvancedPermissions, setShowAdvancedPermissions] = useState(false)
  const [installStartTime, setInstallStartTime] = useState<number | null>(null)

  // Get current installation progress for this plugin
  const installProgress = installing.find(p => p.pluginId === pluginId)

  // Load plugin details when dialog opens
  useEffect(() => {
    if (open && pluginId) {
      loadPluginDetails()
    }
  }, [open, pluginId])

  // Monitor installation progress
  useEffect(() => {
    if (installProgress) {
      if (installProgress.status === 'error') {
        setCurrentStep('error')
        setError(installProgress.error || 'Installation failed')
        onInstallError?.(pluginId, installProgress.error || 'Installation failed')
      } else if (installProgress.progress === 100 && installProgress.status === 'completing') {
        setCurrentStep('complete')
        onInstallComplete?.(pluginId)
      } else {
        setCurrentStep('installing')
      }
    }
  }, [installProgress, pluginId, onInstallComplete, onInstallError])

  const loadPluginDetails = async () => {
    try {
      setLoading(true)
      setError(null)
      const pluginData = await getPlugin(pluginId)
      setPlugin(pluginData)
      setCurrentStep('overview')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load plugin details')
      setCurrentStep('error')
    } finally {
      setLoading(false)
    }
  }

  const handleInstall = async () => {
    if (!plugin) return

    try {
      setError(null)
      setInstallStartTime(Date.now())
      setCurrentStep('installing')
      await installPlugin(plugin.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Installation failed')
      setCurrentStep('error')
    }
  }

  const handleClose = () => {
    // Don't allow closing during installation unless there's an error
    if (currentStep === 'installing' && !error) {
      return
    }
    
    setCurrentStep('overview')
    setError(null)
    setPlugin(null)
    setInstallStartTime(null)
    onClose()
  }

  const handleRetry = () => {
    setError(null)
    setCurrentStep('overview')
    loadPluginDetails()
  }

  if (!open) return null

  const renderOverviewStep = () => {
    if (!plugin) return null

    return (
      <div className="space-y-6">
        {/* Plugin Header */}
        <div className="flex items-start gap-4">
          {plugin.icon ? (
            <img 
              src={plugin.icon} 
              alt={`${plugin.name} icon`} 
              className="w-16 h-16 rounded-lg object-cover"
            />
          ) : (
            <div className="w-16 h-16 bg-muted rounded-lg flex items-center justify-center">
              <Package className="w-8 h-8 text-muted-foreground" />
            </div>
          )}
          
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-2">
              <h3 className="text-xl font-bold">{plugin.name}</h3>
              {plugin.author.verified && (
                <Badge variant="outline" className="text-blue-600 border-blue-200">
                  <Shield className="w-3 h-3 mr-1" />
                  Verified
                </Badge>
              )}
            </div>
            
            <p className="text-sm text-muted-foreground mb-2">
              by {plugin.author.name}
            </p>
            
            <div className="flex items-center gap-4 text-sm text-muted-foreground">
              <div className="flex items-center gap-1">
                <Star className="w-3 h-3 fill-current text-yellow-400" />
                <span>{plugin.rating.average.toFixed(1)}</span>
                <span>({plugin.rating.count.toLocaleString()})</span>
              </div>
              <div className="flex items-center gap-1">
                <Download className="w-3 h-3" />
                <span>{plugin.downloads.toLocaleString()}</span>
              </div>
              <div className="flex items-center gap-1">
                <HardDrive className="w-3 h-3" />
                <span>{formatBytes(plugin.size)}</span>
              </div>
            </div>
          </div>
        </div>

        <p className="text-sm text-muted-foreground leading-relaxed">
          {plugin.description}
        </p>

        {/* Installation Details */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Installation Details</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <div className="font-medium">Version</div>
                <div className="text-muted-foreground">{plugin.version}</div>
              </div>
              <div>
                <div className="font-medium">License</div>
                <div className="text-muted-foreground">{plugin.license}</div>
              </div>
              <div>
                <div className="font-medium">Download Size</div>
                <div className="text-muted-foreground">{formatBytes(plugin.size)}</div>
              </div>
              <div>
                <div className="font-medium">Install Size</div>
                <div className="text-muted-foreground">
                  {formatBytes(plugin.installSize || plugin.size * 2)}
                </div>
              </div>
            </div>

            {plugin.dependencies.length > 0 && (
              <div className="space-y-2">
                <div className="font-medium">Dependencies</div>
                <div className="space-y-1">
                  {plugin.dependencies.map(dep => (
                    <div key={dep.name} className="flex items-center justify-between text-sm">
                      <span>{dep.name}</span>
                      <Badge variant="outline">{dep.version}</Badge>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Permissions Preview */}
        {plugin.permissions.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <Shield className="w-4 h-4" />
                Permissions Required
              </CardTitle>
              <CardDescription>
                This plugin requires the following permissions to function
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                {plugin.permissions.slice(0, 3).map(perm => (
                  <div key={perm.permission} className="flex items-start gap-2">
                    <AlertTriangle className="w-4 h-4 text-amber-500 mt-0.5 shrink-0" />
                    <div className="min-w-0">
                      <div className="font-medium text-sm">
                        {perm.permission.replace('-', ' ').toUpperCase()}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {perm.description}
                      </div>
                    </div>
                  </div>
                ))}
                {plugin.permissions.length > 3 && (
                  <Button 
                    variant="ghost" 
                    size="sm" 
                    onClick={() => setCurrentStep('permissions')}
                    className="text-xs"
                  >
                    View all {plugin.permissions.length} permissions
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Action Buttons */}
        <div className="flex items-center justify-between pt-4">
          <Button variant="ghost" onClick={handleClose}>
            Cancel
          </Button>
          <div className="flex items-center gap-2">
            {plugin.permissions.length > 0 && (
              <Button 
                variant="outline" 
                onClick={() => setCurrentStep('permissions')}
              >
                Review Permissions
              </Button>
            )}
            <Button onClick={handleInstall} disabled={loading}>
              {loading ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <Download className="w-4 h-4 mr-2" />
              )}
              Install Plugin
            </Button>
          </div>
        </div>
      </div>
    )
  }

  const renderPermissionsStep = () => {
    if (!plugin) return null

    return (
      <div className="space-y-6">
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => setCurrentStep('overview')}>
            <ArrowLeft className="w-4 h-4" />
          </Button>
          <div>
            <h3 className="text-lg font-semibold">Review Permissions</h3>
            <p className="text-sm text-muted-foreground">
              {plugin.name} requires the following permissions
            </p>
          </div>
        </div>

        <PluginPermissions 
          permissions={plugin.permissions}
          showAdvanced={showAdvancedPermissions}
          onToggleAdvanced={() => setShowAdvancedPermissions(!showAdvancedPermissions)}
        />

        <div className="flex items-center justify-between pt-4">
          <Button variant="ghost" onClick={() => setCurrentStep('overview')}>
            <ArrowLeft className="w-4 h-4 mr-2" />
            Back
          </Button>
          <Button onClick={handleInstall}>
            <Download className="w-4 h-4 mr-2" />
            Accept & Install
          </Button>
        </div>
      </div>
    )
  }

  const renderInstallingStep = () => {
    if (!plugin || !installProgress) return null

    const progress = installProgress.progress || 0
    const elapsedTime = installStartTime ? Date.now() - installStartTime : 0
    const estimatedTotal = elapsedTime > 0 && progress > 0 ? (elapsedTime / progress) * 100 : 0
    const estimatedRemaining = estimatedTotal > elapsedTime ? estimatedTotal - elapsedTime : 0

    return (
      <div className="space-y-6">
        <div className="text-center space-y-4">
          <div className="w-16 h-16 mx-auto bg-blue-100 rounded-full flex items-center justify-center">
            <Loader2 className="w-8 h-8 text-blue-600 animate-spin" />
          </div>
          
          <div>
            <h3 className="text-lg font-semibold">Installing {plugin.name}</h3>
            <p className="text-sm text-muted-foreground">
              {installProgress.message || 'Please wait while the plugin is being installed...'}
            </p>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between text-sm">
              <span className="capitalize">{installProgress.status.replace('-', ' ')}</span>
              <span>{progress.toFixed(0)}%</span>
            </div>
            <Progress value={progress} className="h-2" />
          </div>

          {elapsedTime > 0 && (
            <div className="grid grid-cols-2 gap-4 text-sm text-muted-foreground">
              <div className="text-center">
                <div className="font-medium text-foreground">Elapsed</div>
                <div>{formatDuration(elapsedTime)}</div>
              </div>
              {estimatedRemaining > 0 && (
                <div className="text-center">
                  <div className="font-medium text-foreground">Remaining</div>
                  <div>{formatDuration(estimatedRemaining)}</div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Installation Steps */}
        <Card>
          <CardContent className="p-4">
            <div className="space-y-3">
              {[
                { step: 'downloading', label: 'Downloading', icon: Download },
                { step: 'extracting', label: 'Extracting', icon: Package },
                { step: 'installing', label: 'Installing', icon: HardDrive },
                { step: 'configuring', label: 'Configuring', icon: Shield },
                { step: 'completing', label: 'Completing', icon: CheckCircle }
              ].map(({ step, label, icon: Icon }, index) => {
                const isActive = installProgress.status === step
                const isComplete = ['downloading', 'extracting', 'installing', 'configuring'].slice(0, index).every(s => 
                  s === installProgress.status || progress > (index * 20)
                )

                return (
                  <div key={step} className="flex items-center gap-3">
                    <div className={cn(
                      'w-6 h-6 rounded-full flex items-center justify-center',
                      isActive ? 'bg-blue-100 text-blue-600' :
                      isComplete ? 'bg-green-100 text-green-600' :
                      'bg-muted text-muted-foreground'
                    )}>
                      {isActive ? (
                        <Loader2 className="w-3 h-3 animate-spin" />
                      ) : isComplete ? (
                        <CheckCircle className="w-3 h-3" />
                      ) : (
                        <Icon className="w-3 h-3" />
                      )}
                    </div>
                    <span className={cn(
                      'text-sm',
                      isActive ? 'font-medium' : 
                      isComplete ? 'text-muted-foreground line-through' :
                      'text-muted-foreground'
                    )}>
                      {label}
                    </span>
                  </div>
                )
              })}
            </div>
          </CardContent>
        </Card>

        <Alert>
          <Info className="h-4 w-4" />
          <AlertDescription>
            Please don't close this dialog during installation. The plugin will be available in your installed plugins once complete.
          </AlertDescription>
        </Alert>
      </div>
    )
  }

  const renderCompleteStep = () => {
    if (!plugin) return null

    return (
      <div className="space-y-6 text-center">
        <div className="w-16 h-16 mx-auto bg-green-100 rounded-full flex items-center justify-center">
          <CheckCircle className="w-8 h-8 text-green-600" />
        </div>
        
        <div>
          <h3 className="text-lg font-semibold">Installation Complete!</h3>
          <p className="text-sm text-muted-foreground">
            {plugin.name} has been successfully installed and is ready to use.
          </p>
        </div>

        <Card>
          <CardContent className="p-4">
            <div className="space-y-2">
              <div className="font-medium">What's next?</div>
              <ul className="text-sm text-muted-foreground space-y-1">
                <li>• The plugin is now available in your installed plugins</li>
                <li>• Configure plugin settings if needed</li>
                <li>• Check plugin documentation for usage instructions</li>
              </ul>
            </div>
          </CardContent>
        </Card>

        <div className="flex items-center justify-center gap-2">
          <Button variant="outline" onClick={handleClose}>
            Close
          </Button>
          <Button onClick={handleClose}>
            View Installed Plugins
          </Button>
        </div>
      </div>
    )
  }

  const renderErrorStep = () => {
    return (
      <div className="space-y-6 text-center">
        <div className="w-16 h-16 mx-auto bg-red-100 rounded-full flex items-center justify-center">
          <XCircle className="w-8 h-8 text-red-600" />
        </div>
        
        <div>
          <h3 className="text-lg font-semibold">Installation Failed</h3>
          <p className="text-sm text-muted-foreground">
            We encountered an error while installing the plugin.
          </p>
        </div>

        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>
            {error || 'An unknown error occurred during installation.'}
          </AlertDescription>
        </Alert>

        <div className="flex items-center justify-center gap-2">
          <Button variant="outline" onClick={handleClose}>
            Close
          </Button>
          <Button onClick={handleRetry}>
            Try Again
          </Button>
        </div>
      </div>
    )
  }

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-2xl max-h-[80vh]">
        <DialogHeader>
          <DialogTitle>
            {currentStep === 'overview' && 'Install Plugin'}
            {currentStep === 'permissions' && 'Review Permissions'}
            {currentStep === 'installing' && 'Installing Plugin'}
            {currentStep === 'complete' && 'Installation Complete'}
            {currentStep === 'error' && 'Installation Error'}
          </DialogTitle>
          {currentStep === 'overview' && (
            <DialogDescription>
              Review plugin details and permissions before installing
            </DialogDescription>
          )}
        </DialogHeader>

        <ScrollArea className="max-h-[60vh] pr-6">
          {loading && (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-6 h-6 animate-spin mr-2" />
              <span>Loading plugin details...</span>
            </div>
          )}

          {!loading && currentStep === 'overview' && renderOverviewStep()}
          {!loading && currentStep === 'permissions' && renderPermissionsStep()}
          {!loading && currentStep === 'installing' && renderInstallingStep()}
          {!loading && currentStep === 'complete' && renderCompleteStep()}
          {!loading && currentStep === 'error' && renderErrorStep()}
        </ScrollArea>
      </DialogContent>
    </Dialog>
  )
}

export default PluginInstaller