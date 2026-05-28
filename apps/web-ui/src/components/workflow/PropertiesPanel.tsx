import React, { useState, useEffect } from 'react'
import { Node } from 'reactflow'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Slider } from '@/components/ui/slider'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { X, Save, RotateCcw } from 'lucide-react'

// Tool-specific parameter schemas
const parameterSchemas: Record<string, any> = {
  fmriprep: {
    participant_label: { type: 'text', label: 'Participant Label', default: '' },
    task_id: { type: 'text', label: 'Task ID', default: '' },
    output_spaces: { 
      type: 'select', 
      label: 'Output Spaces',
      options: ['MNI152NLin2009cAsym', 'MNI152NLin6Asym', 'fsaverage'],
      default: 'MNI152NLin2009cAsym'
    },
    use_aroma: { type: 'boolean', label: 'Use AROMA', default: false },
    skull_strip: { type: 'boolean', label: 'Skull Strip', default: true },
  },
  fsl_feat: {
    tr: { type: 'number', label: 'TR (seconds)', default: 2.0, min: 0.1, max: 10, step: 0.1 },
    high_pass: { type: 'number', label: 'High Pass Filter (s)', default: 100, min: 0, max: 1000 },
    smoothing: { type: 'number', label: 'Smoothing FWHM (mm)', default: 5, min: 0, max: 20 },
    threshold: { type: 'slider', label: 'Z Threshold', default: 2.3, min: 0, max: 5, step: 0.1 },
    cluster_threshold: { type: 'slider', label: 'Cluster Threshold', default: 0.05, min: 0, max: 1, step: 0.01 },
  },
  nilearn_connectivity: {
    atlas: {
      type: 'select',
      label: 'Atlas',
      options: ['AAL', 'Harvard-Oxford', 'BASC', 'Power', 'Dosenbach'],
      default: 'AAL'
    },
    metric: {
      type: 'select',
      label: 'Connectivity Metric',
      options: ['correlation', 'partial correlation', 'tangent', 'covariance'],
      default: 'correlation'
    },
    standardize: { type: 'boolean', label: 'Standardize', default: true },
    detrend: { type: 'boolean', label: 'Detrend', default: true },
    low_pass: { type: 'number', label: 'Low Pass (Hz)', default: 0.1, min: 0, max: 1, step: 0.01 },
    high_pass: { type: 'number', label: 'High Pass (Hz)', default: 0.01, min: 0, max: 0.1, step: 0.001 },
  },
  dl_pytorch: {
    model_type: {
      type: 'select',
      label: 'Model Type',
      options: ['3D CNN', 'VAE', 'LSTM', 'GRU', 'Transformer', 'GNN'],
      default: '3D CNN'
    },
    batch_size: { type: 'number', label: 'Batch Size', default: 32, min: 1, max: 256 },
    learning_rate: { type: 'number', label: 'Learning Rate', default: 0.001, min: 0.00001, max: 0.1, step: 0.00001 },
    epochs: { type: 'number', label: 'Epochs', default: 100, min: 1, max: 1000 },
    use_gpu: { type: 'boolean', label: 'Use GPU', default: true },
    dropout: { type: 'slider', label: 'Dropout Rate', default: 0.5, min: 0, max: 1, step: 0.1 },
  },
}

interface PropertiesPanelProps {
  node: Node | null
  onClose: () => void
  onUpdate: (nodeId: string, data: any) => void
}

export default function PropertiesPanel({
  node,
  onClose,
  onUpdate,
}: PropertiesPanelProps) {
  const [parameters, setParameters] = useState<Record<string, any>>({})
  const [hasChanges, setHasChanges] = useState(false)

  useEffect(() => {
    if (node?.data?.parameters) {
      setParameters(node.data.parameters)
    } else if (node?.data?.tool?.id) {
      // Initialize with default parameters
      const schema = parameterSchemas[node.data.tool.id]
      if (schema) {
        const defaults: Record<string, any> = {}
        Object.entries(schema).forEach(([key, config]: [string, any]) => {
          defaults[key] = config.default
        })
        setParameters(defaults)
      }
    }
  }, [node])

  if (!node) return null

  const toolId = node.data?.tool?.id
  const schema = parameterSchemas[toolId] || {}

  const handleParameterChange = (key: string, value: any) => {
    setParameters((prev) => ({
      ...prev,
      [key]: value,
    }))
    setHasChanges(true)
  }

  const handleSave = () => {
    onUpdate(node.id, { parameters })
    setHasChanges(false)
  }

  const handleReset = () => {
    if (toolId && parameterSchemas[toolId]) {
      const defaults: Record<string, any> = {}
      Object.entries(parameterSchemas[toolId]).forEach(([key, config]: [string, any]) => {
        defaults[key] = config.default
      })
      setParameters(defaults)
      setHasChanges(true)
    }
  }

  const renderParameterInput = (key: string, config: any) => {
    const value = parameters[key] ?? config.default

    switch (config.type) {
      case 'text':
        return (
          <Input
            value={value}
            onChange={(e) => handleParameterChange(key, e.target.value)}
            placeholder={config.placeholder}
          />
        )

      case 'number':
        return (
          <Input
            type="number"
            value={value}
            onChange={(e) => handleParameterChange(key, parseFloat(e.target.value))}
            min={config.min}
            max={config.max}
            step={config.step}
          />
        )

      case 'boolean':
        return (
          <Switch
            checked={value}
            onCheckedChange={(checked) => handleParameterChange(key, checked)}
          />
        )

      case 'slider':
        return (
          <div className="flex items-center gap-4">
            <Slider
              value={[value]}
              onValueChange={([v]) => handleParameterChange(key, v)}
              min={config.min}
              max={config.max}
              step={config.step}
              className="flex-1"
            />
            <span className="text-sm w-12 text-right">{value}</span>
          </div>
        )

      case 'select':
        return (
          <Select
            value={value}
            onValueChange={(v) => handleParameterChange(key, v)}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {config.options.map((option: string) => (
                <SelectItem key={option} value={option}>
                  {option}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )

      case 'textarea':
        return (
          <Textarea
            value={value}
            onChange={(e) => handleParameterChange(key, e.target.value)}
            placeholder={config.placeholder}
            rows={config.rows || 3}
          />
        )

      default:
        return null
    }
  }

  return (
    <>
      <SheetHeader>
        <SheetTitle className="flex items-center justify-between">
          <span>{node.data?.label || 'Tool Properties'}</span>
          <Badge variant="outline">{node.data?.category}</Badge>
        </SheetTitle>
        <SheetDescription>
          Configure parameters for {node.data?.tool?.name}
        </SheetDescription>
      </SheetHeader>

      <Separator className="my-4" />

      <ScrollArea className="flex-1 pr-4">
        <div className="space-y-4">
          {/* Tool Information */}
          <div>
            <h3 className="font-medium mb-2">Tool Information</h3>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Name:</span>
                <span>{node.data?.tool?.name}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">ID:</span>
                <span className="font-mono text-xs">{node.id}</span>
              </div>
              {node.data?.tool?.description && (
                <div>
                  <span className="text-muted-foreground">Description:</span>
                  <p className="mt-1">{node.data.tool.description}</p>
                </div>
              )}
            </div>
          </div>

          <Separator />

          {/* Input/Output Information */}
          <div>
            <h3 className="font-medium mb-2">Connections</h3>
            <div className="space-y-2">
              {node.data?.tool?.inputs && (
                <div>
                  <Label className="text-xs text-muted-foreground">Inputs</Label>
                  <div className="flex gap-1 mt-1">
                    {node.data.tool.inputs.map((input: string) => (
                      <Badge key={input} variant="secondary" className="text-xs">
                        {input}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
              {node.data?.tool?.outputs && (
                <div>
                  <Label className="text-xs text-muted-foreground">Outputs</Label>
                  <div className="flex gap-1 mt-1">
                    {node.data.tool.outputs.map((output: string) => (
                      <Badge key={output} variant="secondary" className="text-xs">
                        {output}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          <Separator />

          {/* Parameters */}
          <div>
            <h3 className="font-medium mb-2">Parameters</h3>
            {Object.keys(schema).length > 0 ? (
              <div className="space-y-4">
                {Object.entries(schema).map(([key, config]: [string, any]) => (
                  <div key={key} className="space-y-2">
                    <Label className="text-sm">
                      {config.label || key}
                      {config.required && (
                        <span className="text-red-500 ml-1">*</span>
                      )}
                    </Label>
                    {renderParameterInput(key, config)}
                    {config.description && (
                      <p className="text-xs text-muted-foreground">
                        {config.description}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                No configurable parameters for this tool.
              </p>
            )}
          </div>
        </div>
      </ScrollArea>

      <div className="flex gap-2 mt-4">
        <Button
          variant="outline"
          size="sm"
          onClick={handleReset}
          disabled={!hasChanges}
        >
          <RotateCcw className="h-4 w-4 mr-2" />
          Reset
        </Button>
        <Button
          size="sm"
          onClick={handleSave}
          disabled={!hasChanges}
          className="flex-1"
        >
          <Save className="h-4 w-4 mr-2" />
          Save Changes
        </Button>
      </div>
    </>
  )
}