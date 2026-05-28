/**
 * PluginPermissions Component
 * Displays detailed plugin permissions with security implications and explanations
 */

import React from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { 
  Shield, 
  AlertTriangle, 
  Info, 
  FileText, 
  Globe, 
  Cpu, 
  Database, 
  User, 
  Settings,
  ExternalLink,
  ChevronDown,
  ChevronRight,
  Eye,
  EyeOff,
  Lock,
  Unlock,
  Check,
  X
} from 'lucide-react'
import { cn } from '@/lib/utils'
import type { PluginPermissionDetails, PluginPermission } from '@/types/plugins'

interface PluginPermissionsProps {
  permissions: PluginPermissionDetails[]
  showAdvanced?: boolean
  onToggleAdvanced?: () => void
  showSecurityWarnings?: boolean
  compactMode?: boolean
  className?: string
}

// Permission metadata with icons, descriptions, and security levels
const permissionMeta: Record<PluginPermission, {
  icon: React.ReactNode
  label: string
  description: string
  securityLevel: 'low' | 'medium' | 'high' | 'critical'
  implications: string[]
  examples?: string[]
}> = {
  'file-system': {
    icon: <FileText className="w-4 h-4" />,
    label: 'File System Access',
    description: 'Read and write files on your computer',
    securityLevel: 'high',
    implications: [
      'Can access files in your home directory',
      'May create, modify, or delete files',
      'Could potentially access sensitive documents'
    ],
    examples: []
  },
  'network': {
    icon: <Globe className="w-4 h-4" />,
    label: 'Network Access',
    description: 'Connect to the internet and external services',
    securityLevel: 'medium',
    implications: [
      'Can send data to external servers',
      'May download content from the internet',
      'Could potentially transmit sensitive information'
    ],
    examples: []
  },
  'compute': {
    icon: <Cpu className="w-4 h-4" />,
    label: 'Compute Resources',
    description: 'Use significant CPU, memory, or GPU resources',
    securityLevel: 'low',
    implications: [
      'May consume significant system resources',
      'Could slow down other applications',
      'May generate heat and reduce battery life'
    ],
    examples: []
  },
  'data-access': {
    icon: <Database className="w-4 h-4" />,
    label: 'Data Access',
    description: 'Access Brain Researcher data and databases',
    securityLevel: 'medium',
    implications: [
      'Can read your research data',
      'May access your analysis history',
      'Could view saved projects and results'
    ],
    examples: []
  },
  'user-data': {
    icon: <User className="w-4 h-4" />,
    label: 'User Data',
    description: 'Access personal settings and preferences',
    securityLevel: 'high',
    implications: [
      'Can access your profile information',
      'May read your application preferences',
      'Could view your usage patterns'
    ],
    examples: []
  },
  'system-integration': {
    icon: <Settings className="w-4 h-4" />,
    label: 'System Integration',
    description: 'Integrate with system services and other applications',
    securityLevel: 'critical',
    implications: [
      'Can interact with other installed applications',
      'May access system-level services',
      'Could modify system settings'
    ],
    examples: []
  },
  'external-apis': {
    icon: <ExternalLink className="w-4 h-4" />,
    label: 'External APIs',
    description: 'Connect to third-party services and APIs',
    securityLevel: 'medium',
    implications: [
      'Can send requests to external services',
      'May share data with third parties',
      'Could be subject to external service policies'
    ],
    examples: []
  }
}

const securityLevelColors = {
  low: 'text-green-600 bg-green-50 border-green-200',
  medium: 'text-yellow-600 bg-yellow-50 border-yellow-200',
  high: 'text-orange-600 bg-orange-50 border-orange-200',
  critical: 'text-red-600 bg-red-50 border-red-200'
}

const securityLevelIcons = {
  low: <Check className="w-3 h-3" />,
  medium: <Info className="w-3 h-3" />,
  high: <AlertTriangle className="w-3 h-3" />,
  critical: <X className="w-3 h-3" />
}

export function PluginPermissions({
  permissions,
  showAdvanced = false,
  onToggleAdvanced,
  showSecurityWarnings = true,
  compactMode = false,
  className
}: PluginPermissionsProps) {
  // Group permissions by security level
  const permissionsByLevel = permissions.reduce((acc, perm) => {
    const meta = permissionMeta[perm.permission]
    if (!meta) return acc
    
    if (!acc[meta.securityLevel]) acc[meta.securityLevel] = []
    acc[meta.securityLevel].push(perm)
    return acc
  }, {} as Record<string, PluginPermissionDetails[]>)

  // Calculate overall security risk
  const overallRisk = permissions.reduce((max, perm) => {
    const meta = permissionMeta[perm.permission]
    if (!meta) return max
    
    const levels = { low: 1, medium: 2, high: 3, critical: 4 }
    return Math.max(max, levels[meta.securityLevel] || 0)
  }, 0)

  const riskLevelName = Object.keys({ low: 1, medium: 2, high: 3, critical: 4 })[overallRisk - 1] as keyof typeof securityLevelColors

  const renderPermissionItem = (perm: PluginPermissionDetails, detailed: boolean = false) => {
    const meta = permissionMeta[perm.permission]
    if (!meta) return null

    if (compactMode && !detailed) {
      return (
        <div key={perm.permission} className="flex items-center justify-between p-2 border rounded-lg">
          <div className="flex items-center gap-2">
            {meta.icon}
            <span className="font-medium text-sm">{meta.label}</span>
            {perm.required && (
              <Badge variant="outline" className="text-xs">Required</Badge>
            )}
          </div>
          <Badge 
            variant="outline" 
            className={cn('text-xs', securityLevelColors[meta.securityLevel])}
          >
            {securityLevelIcons[meta.securityLevel]}
            {meta.securityLevel}
          </Badge>
        </div>
      )
    }

    return (
      <Card key={perm.permission} className="border-l-4" style={{
        borderLeftColor: meta.securityLevel === 'critical' ? 'rgb(239 68 68)' :
                         meta.securityLevel === 'high' ? 'rgb(249 115 22)' :
                         meta.securityLevel === 'medium' ? 'rgb(245 158 11)' :
                         'rgb(34 197 94)'
      }}>
        <CardHeader className="pb-3">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-2">
              {meta.icon}
              <CardTitle className="text-base">{meta.label}</CardTitle>
              {perm.required && (
                <Badge variant="outline">Required</Badge>
              )}
            </div>
            <Badge 
              variant="outline" 
              className={cn('text-xs', securityLevelColors[meta.securityLevel])}
            >
              {securityLevelIcons[meta.securityLevel]}
              {meta.securityLevel.toUpperCase()}
            </Badge>
          </div>
          <CardDescription>{meta.description}</CardDescription>
        </CardHeader>
        
        <CardContent className="pt-0 space-y-4">
          <div>
            <div className="font-medium text-sm mb-1">Plugin's justification:</div>
            <p className="text-sm text-muted-foreground">{perm.justification}</p>
          </div>

          {detailed && (
            <>
              <div>
                <div className="font-medium text-sm mb-2">Security implications:</div>
                <ul className="text-sm text-muted-foreground space-y-1">
                  {meta.implications.map((implication, idx) => (
                    <li key={idx} className="flex items-start gap-2">
                      <AlertTriangle className="w-3 h-3 mt-0.5 text-amber-500 shrink-0" />
                      {implication}
                    </li>
                  ))}
                </ul>
              </div>
              
              {meta.examples && meta.examples.length > 0 ? (
                <div>
                  <div className="font-medium text-sm mb-2">Usage notes:</div>
                  <ul className="text-sm text-muted-foreground space-y-1">
                    {meta.examples.map((example, idx) => (
                      <li key={idx} className="flex items-start gap-2">
                        <Check className="w-3 h-3 mt-0.5 text-green-500 shrink-0" />
                        {example}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </>
          )}
        </CardContent>
      </Card>
    )
  }

  if (permissions.length === 0) {
    return (
      <Card className={className}>
        <CardContent className="p-6 text-center">
          <Shield className="w-8 h-8 mx-auto text-green-500 mb-2" />
          <h3 className="font-medium text-sm">No special permissions required</h3>
          <p className="text-xs text-muted-foreground">
            This plugin runs in a restricted environment and doesn't need additional access.
          </p>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className={cn('space-y-4', className)}>
      {/* Security Overview */}
      {showSecurityWarnings && (
        <Alert className={cn('border-l-4', 
          riskLevelName === 'critical' ? 'border-l-red-500 bg-red-50' :
          riskLevelName === 'high' ? 'border-l-orange-500 bg-orange-50' :
          riskLevelName === 'medium' ? 'border-l-yellow-500 bg-yellow-50' :
          'border-l-green-500 bg-green-50'
        )}>
          <div className="flex items-center gap-2">
            {riskLevelName === 'critical' ? <AlertTriangle className="h-4 w-4 text-red-600" /> :
             riskLevelName === 'high' ? <AlertTriangle className="h-4 w-4 text-orange-600" /> :
             riskLevelName === 'medium' ? <Info className="h-4 w-4 text-yellow-600" /> :
             <Shield className="h-4 w-4 text-green-600" />}
            <div className="font-medium text-sm">
              Security Level: {riskLevelName.charAt(0).toUpperCase() + riskLevelName.slice(1)}
            </div>
          </div>
          <AlertDescription className="mt-2">
            {riskLevelName === 'critical' && 
              'This plugin requires critical system permissions. Only install if you fully trust the developer.'}
            {riskLevelName === 'high' && 
              'This plugin requires significant access to your system and data. Review carefully before installing.'}
            {riskLevelName === 'medium' && 
              'This plugin requires moderate permissions. Standard security precautions apply.'}
            {riskLevelName === 'low' && 
              'This plugin requires minimal permissions and poses low security risk.'}
          </AlertDescription>
        </Alert>
      )}

      {/* Permissions List */}
      <div className="space-y-3">
        {permissions.map(perm => renderPermissionItem(perm, showAdvanced))}
      </div>

      {/* Advanced Toggle */}
      {onToggleAdvanced && (
        <div className="flex items-center justify-center pt-2">
          <Button 
            variant="ghost" 
            size="sm" 
            onClick={onToggleAdvanced}
            className="text-xs"
          >
            {showAdvanced ? (
              <>
                <EyeOff className="w-3 h-3 mr-1" />
                Hide detailed explanations
              </>
            ) : (
              <>
                <Eye className="w-3 h-3 mr-1" />
                Show detailed explanations
              </>
            )}
          </Button>
        </div>
      )}

      {/* Permission Summary */}
      {!compactMode && (
        <Card className="bg-muted/50">
          <CardContent className="p-4">
            <div className="flex items-start gap-2">
              <Info className="w-4 h-4 mt-0.5 text-muted-foreground shrink-0" />
              <div className="text-sm text-muted-foreground">
                <div className="font-medium mb-1">Permission Summary</div>
                <p>
                  This plugin requires {permissions.length} permission{permissions.length === 1 ? '' : 's'}.{' '}
                  {permissions.filter(p => p.required).length > 0 && (
                    <>
                      {permissions.filter(p => p.required).length} are required for basic functionality.{' '}
                    </>
                  )}
                  Review each permission carefully to understand what access the plugin will have.
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

export default PluginPermissions
