'use client'

import React, { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Slider } from '@/components/ui/slider'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { Separator } from '@/components/ui/separator'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@/components/ui/tabs'
import { 
  Settings,
  Palette,
  Clock,
  Layout,
  Eye,
  Zap
} from 'lucide-react'
import { Widget, WidgetConfig, WidgetType } from '@/types/dashboard'

interface WidgetConfigModalProps {
  widget: Widget | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onSave: (config: WidgetConfig) => void
}

export const WidgetConfigModal: React.FC<WidgetConfigModalProps> = ({
  widget,
  open,
  onOpenChange,
  onSave
}) => {
  const [config, setConfig] = useState<WidgetConfig>({})
  const [title, setTitle] = useState('')

  useEffect(() => {
    if (widget) {
      setConfig(widget.config)
      setTitle(widget.title)
    }
  }, [widget])

  const handleSave = () => {
    onSave({
      ...config,
      title
    })
    onOpenChange(false)
  }

  const updateConfig = (key: string, value: any) => {
    setConfig(prev => ({ ...prev, [key]: value }))
  }

  const getWidgetSpecificConfig = () => {
    if (!widget) return null

    switch (widget.type) {
      case WidgetType.ANALYSIS_QUEUE:
        return (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <Label htmlFor="show-completed">Show Completed Jobs</Label>
              <Switch
                id="show-completed"
                checked={config.showCompleted ?? true}
                onCheckedChange={(checked) => updateConfig('showCompleted', checked)}
              />
            </div>
            <div className="space-y-2">
              <Label>Max Jobs to Display</Label>
              <Slider
                value={[config.maxJobs ?? 10]}
                onValueChange={(value) => updateConfig('maxJobs', value[0])}
                min={5}
                max={20}
                step={1}
                className="w-full"
              />
              <div className="text-sm text-muted-foreground">
                Currently: {config.maxJobs ?? 10} jobs
              </div>
            </div>
          </div>
        )

      case WidgetType.RECENT_RESULTS:
        return (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Results to Show</Label>
              <Select 
                value={String(config.maxResults ?? 10)}
                onValueChange={(value) => updateConfig('maxResults', parseInt(value))}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="5">5 results</SelectItem>
                  <SelectItem value="10">10 results</SelectItem>
                  <SelectItem value="15">15 results</SelectItem>
                  <SelectItem value="20">20 results</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-center justify-between">
              <Label htmlFor="show-thumbnails">Show Thumbnails</Label>
              <Switch
                id="show-thumbnails"
                checked={config.showThumbnails ?? true}
                onCheckedChange={(checked) => updateConfig('showThumbnails', checked)}
              />
            </div>
            <div className="flex items-center justify-between">
              <Label htmlFor="group-by-type">Group by File Type</Label>
              <Switch
                id="group-by-type"
                checked={config.groupByType ?? false}
                onCheckedChange={(checked) => updateConfig('groupByType', checked)}
              />
            </div>
          </div>
        )

      case WidgetType.RESOURCE_USAGE:
        return (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <Label htmlFor="show-gpu">Show GPU Usage</Label>
              <Switch
                id="show-gpu"
                checked={config.showGPU ?? true}
                onCheckedChange={(checked) => updateConfig('showGPU', checked)}
              />
            </div>
            <div className="flex items-center justify-between">
              <Label htmlFor="show-storage">Show Storage Usage</Label>
              <Switch
                id="show-storage"
                checked={config.showStorage ?? true}
                onCheckedChange={(checked) => updateConfig('showStorage', checked)}
              />
            </div>
            <div className="space-y-2">
              <Label>Warning Threshold (%)</Label>
              <Slider
                value={[config.warningThreshold ?? 80]}
                onValueChange={(value) => updateConfig('warningThreshold', value[0])}
                min={50}
                max={95}
                step={5}
                className="w-full"
              />
              <div className="text-sm text-muted-foreground">
                Currently: {config.warningThreshold ?? 80}%
              </div>
            </div>
          </div>
        )

      case WidgetType.CUSTOM_CHART:
        return (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Chart Type</Label>
              <Select 
                value={config.chartType ?? 'line'}
                onValueChange={(value) => updateConfig('chartType', value)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="line">Line Chart</SelectItem>
                  <SelectItem value="bar">Bar Chart</SelectItem>
                  <SelectItem value="scatter">Scatter Plot</SelectItem>
                  <SelectItem value="area">Area Chart</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Color Scheme</Label>
              <Select 
                value={config.colorScheme ?? 'blue'}
                onValueChange={(value) => updateConfig('colorScheme', value)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="blue">Blue</SelectItem>
                  <SelectItem value="green">Green</SelectItem>
                  <SelectItem value="purple">Purple</SelectItem>
                  <SelectItem value="orange">Orange</SelectItem>
                  <SelectItem value="red">Red</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-center justify-between">
              <Label htmlFor="show-grid">Show Grid Lines</Label>
              <Switch
                id="show-grid"
                checked={config.showGrid ?? true}
                onCheckedChange={(checked) => updateConfig('showGrid', checked)}
              />
            </div>
          </div>
        )

      case WidgetType.TEAM_ACTIVITY:
        return (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Activities to Show</Label>
              <Slider
                value={[config.maxActivities ?? 10]}
                onValueChange={(value) => updateConfig('maxActivities', value[0])}
                min={5}
                max={25}
                step={5}
                className="w-full"
              />
              <div className="text-sm text-muted-foreground">
                Currently: {config.maxActivities ?? 10} activities
              </div>
            </div>
            <div className="flex items-center justify-between">
              <Label htmlFor="show-avatars">Show User Avatars</Label>
              <Switch
                id="show-avatars"
                checked={config.showAvatars ?? true}
                onCheckedChange={(checked) => updateConfig('showAvatars', checked)}
              />
            </div>
            <div className="flex items-center justify-between">
              <Label htmlFor="group-by-user">Group by User</Label>
              <Switch
                id="group-by-user"
                checked={config.groupByUser ?? false}
                onCheckedChange={(checked) => updateConfig('groupByUser', checked)}
              />
            </div>
          </div>
        )

      default:
        return (
          <div className="text-sm text-muted-foreground">
            No specific configuration options available for this widget type.
          </div>
        )
    }
  }

  if (!widget) return null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Settings className="h-5 w-5" />
            Configure Widget
          </DialogTitle>
          <DialogDescription>
            Customize the appearance and behavior of your {widget.title} widget
          </DialogDescription>
        </DialogHeader>

        <Tabs defaultValue="general" className="w-full">
          <TabsList className="grid w-full grid-cols-4">
            <TabsTrigger value="general" className="text-xs">
              <Settings className="h-3 w-3 mr-1" />
              General
            </TabsTrigger>
            <TabsTrigger value="appearance" className="text-xs">
              <Palette className="h-3 w-3 mr-1" />
              Style
            </TabsTrigger>
            <TabsTrigger value="data" className="text-xs">
              <Zap className="h-3 w-3 mr-1" />
              Data
            </TabsTrigger>
            <TabsTrigger value="advanced" className="text-xs">
              <Eye className="h-3 w-3 mr-1" />
              Advanced
            </TabsTrigger>
          </TabsList>

          <TabsContent value="general" className="space-y-4 mt-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Basic Settings</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="widget-title">Widget Title</Label>
                  <Input
                    id="widget-title"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="Enter widget title..."
                  />
                </div>
                
                <div className="flex items-center justify-between">
                  <Label htmlFor="show-header">Show Header</Label>
                  <Switch
                    id="show-header"
                    checked={config.showHeader ?? true}
                    onCheckedChange={(checked) => updateConfig('showHeader', checked)}
                  />
                </div>

                <div className="flex items-center justify-between">
                  <Label htmlFor="auto-refresh">Auto Refresh</Label>
                  <Switch
                    id="auto-refresh"
                    checked={config.autoRefresh ?? true}
                    onCheckedChange={(checked) => updateConfig('autoRefresh', checked)}
                  />
                </div>

                {config.autoRefresh && (
                  <div className="space-y-2">
                    <Label>Refresh Interval (seconds)</Label>
                    <Select 
                      value={String(config.refreshInterval ?? 30)}
                      onValueChange={(value) => updateConfig('refreshInterval', parseInt(value) * 1000)}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="5">5 seconds</SelectItem>
                        <SelectItem value="10">10 seconds</SelectItem>
                        <SelectItem value="30">30 seconds</SelectItem>
                        <SelectItem value="60">1 minute</SelectItem>
                        <SelectItem value="300">5 minutes</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="appearance" className="space-y-4 mt-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Visual Style</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label>Theme</Label>
                  <Select 
                    value={config.theme ?? 'default'}
                    onValueChange={(value) => updateConfig('theme', value)}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="default">Default</SelectItem>
                      <SelectItem value="minimal">Minimal</SelectItem>
                      <SelectItem value="colorful">Colorful</SelectItem>
                      <SelectItem value="dark">Dark</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <Label>Border Style</Label>
                  <Select 
                    value={config.borderStyle ?? 'default'}
                    onValueChange={(value) => updateConfig('borderStyle', value)}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="default">Default</SelectItem>
                      <SelectItem value="rounded">Rounded</SelectItem>
                      <SelectItem value="sharp">Sharp</SelectItem>
                      <SelectItem value="none">No Border</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="flex items-center justify-between">
                  <Label htmlFor="show-shadow">Drop Shadow</Label>
                  <Switch
                    id="show-shadow"
                    checked={config.showShadow ?? true}
                    onCheckedChange={(checked) => updateConfig('showShadow', checked)}
                  />
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="data" className="space-y-4 mt-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Data Settings</CardTitle>
              </CardHeader>
              <CardContent>
                {getWidgetSpecificConfig()}
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="advanced" className="space-y-4 mt-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Advanced Options</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="custom-css">Custom CSS Classes</Label>
                  <Input
                    id="custom-css"
                    value={config.customCss ?? ''}
                    onChange={(e) => updateConfig('customCss', e.target.value)}
                    placeholder="Enter CSS classes..."
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="custom-data-source">Custom Data Source URL</Label>
                  <Input
                    id="custom-data-source"
                    value={config.customDataSource ?? ''}
                    onChange={(e) => updateConfig('customDataSource', e.target.value)}
                    placeholder="Enter data endpoint URL"
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="widget-notes">Notes</Label>
                  <Textarea
                    id="widget-notes"
                    value={config.notes ?? ''}
                    onChange={(e) => updateConfig('notes', e.target.value)}
                    placeholder="Add notes about this widget configuration..."
                    rows={3}
                  />
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>

        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleSave}>
            Save Changes
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
