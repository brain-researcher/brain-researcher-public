import React, { memo } from 'react'
import { Handle, Position, NodeProps } from 'reactflow'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  Brain,
  Activity,
  BarChart3,
  Database,
  Cpu,
  FileText,
  CheckCircle,
  XCircle,
  Loader2,
} from 'lucide-react'

const categoryIcons: Record<string, React.ElementType> = {
  fmri: Brain,
  connectivity: Activity,
  statistics: BarChart3,
  preprocessing: Database,
  'deep-learning': Cpu,
  visualization: FileText,
}

const statusIcons: Record<string, React.ElementType> = {
  completed: CheckCircle,
  error: XCircle,
  running: Loader2,
}

const statusColors: Record<string, string> = {
  idle: 'border-slate-300 bg-white',
  running: 'border-blue-500 bg-blue-50 animate-pulse',
  completed: 'border-green-500 bg-green-50',
  error: 'border-red-500 bg-red-50',
}

interface ToolNodeData {
  label: string
  category: string
  tool: {
    name: string
    description?: string
    inputs?: string[]
    outputs?: string[]
  }
  parameters?: Record<string, any>
  status?: 'idle' | 'running' | 'completed' | 'error'
}

function ToolNode({ data, selected }: NodeProps<ToolNodeData>) {
  const Icon = categoryIcons[data.category] || Brain
  const StatusIcon = data.status ? statusIcons[data.status] : null
  const statusClass = statusColors[data.status || 'idle']

  return (
    <Card
      className={`p-3 min-w-[200px] transition-all ${statusClass} ${
        selected ? 'ring-2 ring-primary' : ''
      }`}
    >
      {/* Input handles */}
      {data.tool.inputs?.map((input, index) => (
        <Handle
          key={`input-${index}`}
          type="target"
          position={Position.Left}
          id={`input-${index}`}
          style={{
            top: `${(index + 1) * (100 / (data.tool.inputs!.length + 1))}%`,
            background: '#64748b',
            width: 8,
            height: 8,
          }}
          title={input}
        />
      ))}

      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2">
          <Icon className="h-4 w-4 text-primary" />
          <span className="font-medium text-sm">{data.label}</span>
        </div>
        {StatusIcon && (
          <StatusIcon
            className={`h-4 w-4 ${
              data.status === 'running' ? 'animate-spin' : ''
            } ${
              data.status === 'completed' ? 'text-green-500' : ''
            } ${
              data.status === 'error' ? 'text-red-500' : ''
            }`}
          />
        )}
      </div>

      <Badge variant="secondary" className="text-xs">
        {data.category}
      </Badge>

      {data.tool.description && (
        <p className="text-xs text-muted-foreground mt-2 line-clamp-2">
          {data.tool.description}
        </p>
      )}

      {data.parameters && Object.keys(data.parameters).length > 0 && (
        <div className="mt-2 pt-2 border-t">
          <p className="text-xs text-muted-foreground">
            {Object.keys(data.parameters).length} params configured
          </p>
        </div>
      )}

      {/* Output handles */}
      {data.tool.outputs?.map((output, index) => (
        <Handle
          key={`output-${index}`}
          type="source"
          position={Position.Right}
          id={`output-${index}`}
          style={{
            top: `${(index + 1) * (100 / (data.tool.outputs!.length + 1))}%`,
            background: '#10b981',
            width: 8,
            height: 8,
          }}
          title={output}
        />
      ))}
    </Card>
  )
}

export default memo(ToolNode)