/**
 * PluginConfig Component
 * Dynamic configuration interface for plugins with form validation and persistence
 */

import React, { useState, useEffect, useCallback } from 'react'
import { useForm, Controller } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import * as z from 'zod'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Checkbox } from '@/components/ui/checkbox'
import { Badge } from '@/components/ui/badge'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Separator } from '@/components/ui/separator'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { 
  Settings, 
  Save, 
  RotateCcw, 
  AlertTriangle, 
  CheckCircle, 
  Info, 
  FileText, 
  FolderOpen,
  Loader2,
  Eye,
  EyeOff,
  HelpCircle,
  ExternalLink,
  Copy,
  RefreshCw
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { usePlugins } from '@/hooks/use-plugins'
import type { Plugin, PluginConfiguration, PluginConfigField } from '@/types/plugins'

interface PluginConfigProps {
  plugin: Plugin
  config?: PluginConfiguration
  onSave?: (config: Record<string, any>) => void
  onCancel?: () => void
  className?: string
}

// Generate Zod schema from plugin config fields
const generateSchema = (fields: PluginConfigField[]) => {
  const schemaFields: Record<string, any> = {}

  fields.forEach(field => {
    let fieldSchema: any

    switch (field.type) {
      case 'string':
        fieldSchema = z.string()
        if (field.validation?.pattern) {
          fieldSchema = fieldSchema.regex(new RegExp(field.validation.pattern))
        }
        if (field.validation?.min) {
          fieldSchema = fieldSchema.min(field.validation.min)
        }
        if (field.validation?.max) {
          fieldSchema = fieldSchema.max(field.validation.max)
        }
        break
        
      case 'number':
        fieldSchema = z.number()
        if (field.validation?.min !== undefined) {
          fieldSchema = fieldSchema.min(field.validation.min)
        }
        if (field.validation?.max !== undefined) {
          fieldSchema = fieldSchema.max(field.validation.max)
        }
        break
        
      case 'boolean':
        fieldSchema = z.boolean()
        break
        
      case 'select':
      case 'multiselect':
        if (field.type === 'multiselect') {
          fieldSchema = z.array(z.string())
        } else {
          fieldSchema = z.string()
        }
        break
        
      case 'file':
      case 'directory':
        fieldSchema = z.string()
        break
        
      default:
        fieldSchema = z.string()
    }

    if (!field.required) {
      fieldSchema = fieldSchema.optional()
    }

    schemaFields[field.key] = fieldSchema
  })

  return z.object(schemaFields)
}

const formatFieldLabel = (field: PluginConfigField) => {
  return (
    <div className="flex items-center gap-2">
      <Label htmlFor={field.key} className="font-medium">
        {field.label}
        {field.required && <span className="text-red-500">*</span>}
      </Label>
      {field.description && (
        <div className="group relative">
          <HelpCircle className="w-3 h-3 text-muted-foreground cursor-help" />
          <div className="absolute bottom-full left-1/2 transform -translate-x-1/2 mb-2 px-2 py-1 bg-popover text-popover-foreground text-xs rounded border shadow-md opacity-0 group-hover:opacity-100 transition-opacity z-10 max-w-xs">
            {field.description}
          </div>
        </div>
      )}
    </div>
  )
}

export function PluginConfig({ 
  plugin, 
  config, 
  onSave, 
  onCancel, 
  className 
}: PluginConfigProps) {
  const { configurePlugin } = usePlugins()
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [activeTab, setActiveTab] = useState<string>('general')

  if (!plugin.configSchema || plugin.configSchema.length === 0) {
    return (
      <Card className={className}>
        <CardContent className="p-6 text-center">
          <Settings className="w-8 h-8 mx-auto text-muted-foreground mb-2" />
          <h3 className="font-medium text-sm">No configuration required</h3>
          <p className="text-xs text-muted-foreground">
            This plugin works out of the box with no additional setup.
          </p>
        </CardContent>
      </Card>
    )
  }

  // Group fields by category or use default groups
  const fieldGroups = plugin.configSchema.reduce((groups, field) => {
    // Extract category from field key or use 'general'
    const category = field.key.includes('.') ? field.key.split('.')[0] : 'general'
    if (!groups[category]) groups[category] = []
    groups[category].push(field)
    return groups
  }, {} as Record<string, PluginConfigField[]>)

  const schema = generateSchema(plugin.configSchema)
  
  const form = useForm({
    resolver: zodResolver(schema),
    defaultValues: config?.config || plugin.configSchema.reduce((defaults, field) => {
      defaults[field.key] = field.defaultValue ?? (
        field.type === 'boolean' ? false :
        field.type === 'multiselect' ? [] :
        field.type === 'number' ? 0 :
        ''
      )
      return defaults
    }, {} as Record<string, any>)
  })

  const { handleSubmit, control, formState: { errors, isDirty }, reset, watch } = form

  // Watch all form values for preview
  const watchedValues = watch()

  const onSubmit = async (data: Record<string, any>) => {
    try {
      setSaving(true)
      setError(null)
      
      if (onSave) {
        onSave(data)
      } else {
        await configurePlugin(plugin.id, data)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save configuration')
    } finally {
      setSaving(false)
    }
  }

  const handleReset = () => {
    reset()
    setError(null)
  }

  const renderField = (field: PluginConfigField) => {
    const fieldError = errors[field.key]

    return (
      <div key={field.key} className="space-y-2">
        {formatFieldLabel(field)}
        
        <Controller
          name={field.key}
          control={control}
          render={({ field: { onChange, value, ...fieldProps } }) => {
            switch (field.type) {
              case 'string':
                return (
                  <Input
                    {...fieldProps}
                    value={value || ''}
                    onChange={onChange}
                    placeholder={field.defaultValue as string}
                    className={fieldError ? 'border-red-500' : ''}
                  />
                )
                
              case 'number':
                return (
                  <Input
                    {...fieldProps}
                    type="number"
                    value={value || ''}
                    onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
                    min={field.validation?.min}
                    max={field.validation?.max}
                    placeholder={field.defaultValue?.toString()}
                    className={fieldError ? 'border-red-500' : ''}
                  />
                )
                
              case 'boolean':
                return (
                  <div className="flex items-center space-x-2">
                    <Switch
                      {...fieldProps}
                      checked={value || false}
                      onCheckedChange={onChange}
                    />
                    <span className="text-sm text-muted-foreground">
                      {value ? 'Enabled' : 'Disabled'}
                    </span>
                  </div>
                )
                
              case 'select':
                return (
                  <Select value={value || ''} onValueChange={onChange}>
                    <SelectTrigger className={fieldError ? 'border-red-500' : ''}>
                      <SelectValue placeholder="Select an option" />
                    </SelectTrigger>
                    <SelectContent>
                      {field.options?.map(option => (
                        <SelectItem key={option.value} value={option.value.toString()}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )
                
              case 'multiselect':
                return (
                  <div className="space-y-2">
                    {field.options?.map(option => (
                      <div key={option.value} className="flex items-center space-x-2">
                        <Checkbox
                          checked={(value || []).includes(option.value)}
                          onCheckedChange={(checked) => {
                            const currentValues = value || []
                            const newValues = checked
                              ? [...currentValues, option.value]
                              : currentValues.filter((v: any) => v !== option.value)
                            onChange(newValues)
                          }}
                        />
                        <Label className="text-sm">{option.label}</Label>
                      </div>
                    ))}
                  </div>
                )
                
              case 'file':
                return (
                  <div className="space-y-2">
                    <Input
                      {...fieldProps}
                      value={value || ''}
                      onChange={onChange}
                      placeholder="Enter file path or click browse"
                      className={fieldError ? 'border-red-500' : ''}
                    />
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        // In a real implementation, this would open a file dialog
                        const path = prompt('Enter file path:')
                        if (path) onChange(path)
                      }}
                    >
                      <FileText className="w-4 h-4 mr-2" />
                      Browse File
                    </Button>
                  </div>
                )
                
              case 'directory':
                return (
                  <div className="space-y-2">
                    <Input
                      {...fieldProps}
                      value={value || ''}
                      onChange={onChange}
                      placeholder="Enter directory path or click browse"
                      className={fieldError ? 'border-red-500' : ''}
                    />
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        // In a real implementation, this would open a directory dialog
                        const path = prompt('Enter directory path:')
                        if (path) onChange(path)
                      }}
                    >
                      <FolderOpen className="w-4 h-4 mr-2" />
                      Browse Folder
                    </Button>
                  </div>
                )
                
              default:
                return (
                  <Textarea
                    {...fieldProps}
                    value={value || ''}
                    onChange={onChange}
                    placeholder={field.defaultValue as string}
                    className={fieldError ? 'border-red-500' : ''}
                    rows={3}
                  />
                )
            }
          }}
        />
        
        {fieldError && (
          <div className="flex items-center gap-1 text-sm text-red-600">
            <AlertTriangle className="w-3 h-3" />
            {String(fieldError.message || '')}
          </div>
        )}
        
        {field.description && (
          <p className="text-xs text-muted-foreground">{field.description}</p>
        )}
      </div>
    )
  }

  const renderFieldGroup = (groupName: string, fields: PluginConfigField[]) => {
    return (
      <div className="space-y-4">
        <div className="space-y-4">
          {fields.map(renderField)}
        </div>
      </div>
    )
  }

  return (
    <div className={cn('space-y-6', className)}>
      {/* Header */}
      <div className="flex items-center gap-3">
        <Settings className="w-6 h-6" />
        <div>
          <h2 className="text-xl font-semibold">Configure {plugin.name}</h2>
          <p className="text-sm text-muted-foreground">
            Customize plugin settings to match your workflow
          </p>
        </div>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
        {Object.keys(fieldGroups).length > 1 ? (
          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsList className="grid w-full grid-cols-3">
              {Object.keys(fieldGroups).slice(0, 3).map(groupName => (
                <TabsTrigger key={groupName} value={groupName} className="capitalize">
                  {groupName}
                </TabsTrigger>
              ))}
            </TabsList>
            
            {Object.entries(fieldGroups).map(([groupName, fields]) => (
              <TabsContent key={groupName} value={groupName} className="mt-6">
                <Card>
                  <CardHeader>
                    <CardTitle className="capitalize">{groupName} Settings</CardTitle>
                    <CardDescription>
                      Configure {groupName} options for {plugin.name}
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    {renderFieldGroup(groupName, fields)}
                  </CardContent>
                </Card>
              </TabsContent>
            ))}
          </Tabs>
        ) : (
          <Card>
            <CardHeader>
              <CardTitle>Plugin Settings</CardTitle>
              <CardDescription>
                Configure options for {plugin.name}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {renderFieldGroup('general', plugin.configSchema)}
            </CardContent>
          </Card>
        )}

        {/* Configuration Preview */}
        {isDirty && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Configuration Preview</CardTitle>
              <CardDescription>
                Preview of the configuration that will be saved
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ScrollArea className="max-h-40">
                <pre className="text-xs bg-muted p-3 rounded overflow-x-auto">
                  {JSON.stringify(watchedValues, null, 2)}
                </pre>
              </ScrollArea>
            </CardContent>
          </Card>
        )}

        {/* Action Buttons */}
        <div className="flex items-center justify-between pt-4 border-t">
          <div className="flex items-center gap-2">
            {onCancel && (
              <Button type="button" variant="outline" onClick={onCancel}>
                Cancel
              </Button>
            )}
            <Button
              type="button"
              variant="ghost"
              onClick={handleReset}
              disabled={!isDirty}
            >
              <RotateCcw className="w-4 h-4 mr-2" />
              Reset to Default
            </Button>
          </div>
          
          <div className="flex items-center gap-2">
            {isDirty && (
              <Badge variant="secondary" className="text-xs">
                Unsaved changes
              </Badge>
            )}
            <Button
              type="submit"
              disabled={saving || !isDirty}
              className="min-w-[100px]"
            >
              {saving ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Saving...
                </>
              ) : (
                <>
                  <Save className="w-4 h-4 mr-2" />
                  Save Config
                </>
              )}
            </Button>
          </div>
        </div>
      </form>

      {/* Help Section */}
      {plugin.documentation && (
        <Card className="border-blue-200 bg-blue-50/50">
          <CardContent className="p-4">
            <div className="flex items-start gap-2">
              <Info className="w-4 h-4 text-blue-600 mt-0.5 shrink-0" />
              <div className="text-sm">
                <div className="font-medium text-blue-900 mb-1">Need help configuring this plugin?</div>
                <div className="text-blue-800">
                  Check out the{' '}
                  <a 
                    href={plugin.documentation} 
                    target="_blank" 
                    rel="noopener noreferrer"
                    className="underline hover:no-underline"
                  >
                    plugin documentation
                    <ExternalLink className="w-3 h-3 ml-1 inline" />
                  </a>
                  {' '}for detailed configuration instructions.
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

export default PluginConfig