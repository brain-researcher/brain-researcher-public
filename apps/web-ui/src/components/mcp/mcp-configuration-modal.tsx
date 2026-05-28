'use client'

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { McpConfigurationPanel } from '@/components/mcp/mcp-configuration-panel'

type McpConfigurationModalProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  onManageInSettings?: () => void
  planId?: string | null
  threadId?: string | null
  workflowId?: string | null
  workflowLabel?: string | null
  datasetId?: string | null
  datasetVersion?: string | null
  continuationPrompt?: string | null
}

export function McpConfigurationModal({
  open,
  onOpenChange,
  onManageInSettings,
  planId,
  threadId,
  workflowId,
  workflowLabel,
  datasetId,
  datasetVersion,
  continuationPrompt,
}: McpConfigurationModalProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] w-[calc(100vw-1rem)] max-w-3xl overflow-y-auto sm:w-full">
        <DialogHeader>
          <DialogTitle>Run via MCP in Codex/Cursor</DialogTitle>
          <DialogDescription>
            Configure MCP in your IDE and continue the current Studio plan with the
            generated handoff prompt.
          </DialogDescription>
        </DialogHeader>
        <McpConfigurationPanel
          showManageInSettings={Boolean(onManageInSettings)}
          onManageInSettings={onManageInSettings}
          planId={planId}
          threadId={threadId}
          workflowId={workflowId}
          workflowLabel={workflowLabel}
          datasetId={datasetId}
          datasetVersion={datasetVersion}
          continuationPrompt={continuationPrompt}
        />
      </DialogContent>
    </Dialog>
  )
}
