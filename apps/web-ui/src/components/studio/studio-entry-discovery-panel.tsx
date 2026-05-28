'use client'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

type NamedOption = {
  value: string
  label: string
}

type StudioEntryDiscoveryPanelProps = {
  workflowOptions: NamedOption[]
  toolOptions: NamedOption[]
  workflowLoading: boolean
  toolLoading: boolean
  workflowError: string | null
  toolError: string | null
  onSelectWorkflow: (value: string) => void
  onSelectTool: (value: string) => void
  onBrowseWorkflows: () => void
  onBrowseTools: () => void
}

export function StudioEntryDiscoveryPanel({
  workflowOptions,
  toolOptions,
  workflowLoading,
  toolLoading,
  workflowError,
  toolError,
  onSelectWorkflow,
  onSelectTool,
  onBrowseWorkflows,
  onBrowseTools,
}: StudioEntryDiscoveryPanelProps) {
  return (
    <div className="space-y-3">
      <div className="text-sm font-medium text-center">— or browse the workflow catalog —</div>
      <Card>
        <CardContent className="p-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <div className="text-xs font-medium text-muted-foreground">Workflow catalog</div>
              <Select
                onValueChange={(value) => {
                  if (!value) return
                  onSelectWorkflow(value)
                }}
                disabled={workflowLoading || workflowOptions.length === 0}
              >
                <SelectTrigger className="h-9 text-xs">
                  <SelectValue
                    placeholder={
                      workflowLoading
                        ? 'Loading workflows...'
                        : workflowError
                          ? 'Failed to load workflows'
                          : 'Choose a workflow'
                    }
                  />
                </SelectTrigger>
                <SelectContent>
                  {workflowOptions.map((workflow) => (
                    <SelectItem key={workflow.value} value={workflow.value}>
                      {workflow.label}
                    </SelectItem>
                  ))}
                  {!workflowOptions.length && !workflowLoading ? (
                    <SelectItem value="__none__" disabled>
                      No workflows available
                    </SelectItem>
                  ) : null}
                </SelectContent>
              </Select>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-xs"
                onClick={onBrowseWorkflows}
              >
                Browse Workflows →
              </Button>
            </div>
            <div className="space-y-2">
              <div className="text-xs font-medium text-muted-foreground">Tools catalog</div>
              <Select
                onValueChange={(value) => {
                  if (!value) return
                  onSelectTool(value)
                }}
                disabled={toolLoading || toolOptions.length === 0}
              >
                <SelectTrigger className="h-9 text-xs">
                  <SelectValue
                    placeholder={
                      toolLoading
                        ? 'Loading tools...'
                        : toolError
                          ? 'Failed to load tools'
                          : 'Choose a tool'
                    }
                  />
                </SelectTrigger>
                <SelectContent>
                  {toolOptions.map((tool) => (
                    <SelectItem key={tool.value} value={tool.value}>
                      {tool.label}
                    </SelectItem>
                  ))}
                  {!toolOptions.length && !toolLoading ? (
                    <SelectItem value="__none__" disabled>
                      No tools available
                    </SelectItem>
                  ) : null}
                </SelectContent>
              </Select>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-xs"
                onClick={onBrowseTools}
              >
                Browse Tools →
              </Button>
            </div>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <Badge variant="outline">Official ✓</Badge>
            <span>Use Studio to validate first; browse catalogs when you need deeper detail.</span>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
