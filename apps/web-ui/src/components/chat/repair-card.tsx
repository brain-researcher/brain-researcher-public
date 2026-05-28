'use client'

import { useState } from 'react'

import { Wrench } from 'lucide-react'

import type { RepairProposal } from '@/lib/chat-repair'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

type RepairCardProps = {
  proposal: RepairProposal
  attemptCount?: number
  onApplyFix?: (proposal: RepairProposal) => void
  onRevalidate?: (proposal: RepairProposal) => void
  onHandOffToIde?: (proposal: RepairProposal) => void
}

function renderPreview(value: unknown): string {
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

export function RepairCard({
  proposal,
  attemptCount = 0,
  onApplyFix,
  onRevalidate,
  onHandOffToIde,
}: RepairCardProps) {
  const [applied, setApplied] = useState(false)
  const canApplyFix = Boolean(proposal.planPatch) && Boolean(onApplyFix)
  const showHandoff = Boolean(proposal.handoff?.required) || attemptCount >= 2

  return (
    <Card className="border-amber-200 bg-amber-50/40" data-testid="repair-card">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm text-amber-900">
          <Wrench className="h-4 w-4" />
          Repair proposal
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 pt-0">
        {proposal.narrative ? (
          <div className="space-y-1">
            <div className="text-xs font-medium text-amber-950">Agent recommendation</div>
            <div className="text-sm whitespace-pre-wrap text-amber-900">{proposal.narrative}</div>
          </div>
        ) : null}

        {proposal.planPatch ? (
          <div className="space-y-1">
            <div className="text-xs font-medium text-amber-950">Plan/config changes</div>
            <pre className="max-h-56 overflow-auto rounded-md border bg-background p-2 text-xs">
              {renderPreview(proposal.planPatch)}
            </pre>
          </div>
        ) : null}

        {proposal.recipePatchPreview ? (
          <div className="space-y-1">
            <div className="text-xs font-medium text-amber-950">Recipe preview</div>
            <pre className="max-h-56 overflow-auto rounded-md border bg-background p-2 text-xs">
              {renderPreview(proposal.recipePatchPreview)}
            </pre>
          </div>
        ) : null}

        {proposal.validationIntent ? (
          <div className="space-y-1">
            <div className="text-xs font-medium text-amber-950">Validation intent</div>
            <div className="text-sm text-amber-900">{proposal.validationIntent}</div>
          </div>
        ) : null}

        {showHandoff ? (
          <div className="space-y-1 rounded-md border border-amber-200 bg-amber-100/60 p-2">
            <div className="text-xs font-medium text-amber-950">External handoff recommended</div>
            <div className="text-sm text-amber-900">
              {proposal.handoff?.reason || 'This repair likely needs environment, dependency, or external IDE work.'}
            </div>
          </div>
        ) : null}

        {canApplyFix || onRevalidate || (showHandoff && onHandOffToIde) ? (
          <div className="flex flex-wrap gap-2">
            {canApplyFix ? (
              <Button
                size="sm"
                onClick={() => {
                  onApplyFix?.(proposal)
                  setApplied(true)
                }}
              >
                {applied ? 'Fix applied' : 'Apply fix'}
              </Button>
            ) : null}
            {onRevalidate ? (
              <Button
                variant="outline"
                size="sm"
                disabled={canApplyFix ? !applied : false}
                onClick={() => onRevalidate(proposal)}
              >
                Re-validate
              </Button>
            ) : null}
            {showHandoff && onHandOffToIde ? (
              <Button variant="outline" size="sm" onClick={() => onHandOffToIde(proposal)}>
                Hand off to IDE
              </Button>
            ) : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}
