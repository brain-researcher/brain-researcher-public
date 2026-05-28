'use client'

import Link from 'next/link'
import { useState } from 'react'
import { Code2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { HandoffModal, type HandoffTemplatePayload } from '@/components/handoff/HandoffModal'

export type WorkflowDetailHandoffActionsProps = {
  workflowId: string
  workflowLabel?: string | null
  datasetId?: string | null
  datasetVersion?: string | null
  supportedTargets?: string[] | null
  recipeAvailable: boolean
}

export function WorkflowDetailHandoffActions({
  workflowId,
  workflowLabel,
  datasetId,
  datasetVersion,
  supportedTargets,
  recipeAvailable,
}: WorkflowDetailHandoffActionsProps) {
  const [open, setOpen] = useState(false)
  const hasDatasetContext = Boolean(datasetId?.trim())

  const payload: HandoffTemplatePayload = {
    kind: 'template',
    workflowId,
    workflowLabel: workflowLabel || workflowId,
    datasetId: datasetId || null,
    datasetVersion: datasetVersion || null,
    supportedTargets: supportedTargets ?? null,
    unresolvedInputs: hasDatasetContext ? [] : ['dataset_id'],
  }

  return (
    <div className="flex shrink-0 items-center gap-2">
      <Button onClick={() => setOpen(true)} disabled={!recipeAvailable}>
        <Code2 className="mr-2 h-4 w-4" />
        Hand off
      </Button>
      <Button asChild variant="outline">
        <Link
          href={`/studio?tab=plan&pipeline=${encodeURIComponent(workflowId)}${
            hasDatasetContext ? `&datasetId=${encodeURIComponent(datasetId || '')}` : ''
          }`}
          prefetch={false}
        >
          Open in Studio
        </Link>
      </Button>
      <HandoffModal
        open={open}
        onClose={() => setOpen(false)}
        mode="template"
        payload={payload}
      />
    </div>
  )
}
