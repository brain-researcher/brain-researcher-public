'use client'

import { AlertCircle } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

type DiagnosisCardProps = {
  title: string
  message?: string
  whatHappened?: string[]
  suggestedActions?: string[]
  viewToolHref?: string
  onSwitchVersion?: () => void
  onViewLogs?: () => void
  onRetry?: () => void
  onAskAgent?: () => void
}

export function DiagnosisCard({
  title,
  message,
  whatHappened,
  suggestedActions,
  viewToolHref,
  onSwitchVersion,
  onAskAgent,
  onRetry,
  onViewLogs,
}: DiagnosisCardProps) {
  return (
    <Card className="border-red-200 bg-red-50/50">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-2 text-red-800">
          <AlertCircle className="h-4 w-4" />
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0 space-y-3">
        {message ? (
          <div className="text-sm text-red-800 whitespace-pre-wrap">{message}</div>
        ) : (
          <div className="text-sm text-red-800">This run failed. Check logs for details.</div>
        )}
        {Array.isArray(whatHappened) && whatHappened.length > 0 ? (
          <div className="space-y-1">
            <div className="text-xs font-medium text-red-900">What happened</div>
            <ul className="space-y-1 text-sm text-red-800 list-disc pl-4">
              {whatHappened.slice(0, 6).map((item, idx) => (
                <li key={`${idx}-${item}`}>{item}</li>
              ))}
            </ul>
          </div>
        ) : null}
        {Array.isArray(suggestedActions) && suggestedActions.length > 0 ? (
          <div className="space-y-1">
            <div className="text-xs font-medium text-red-900">Suggested actions</div>
            <ul className="space-y-1 text-sm text-red-800 list-disc pl-4">
              {suggestedActions.slice(0, 6).map((item, idx) => (
                <li key={`${idx}-${item}`}>{item}</li>
              ))}
            </ul>
          </div>
        ) : null}
        {onAskAgent || onRetry || onViewLogs || onSwitchVersion || viewToolHref ? (
          <div className="flex flex-wrap gap-2">
            {onRetry ? (
              <Button size="sm" onClick={onRetry}>
                Retry
              </Button>
            ) : null}
            {onSwitchVersion ? (
              <Button variant="outline" size="sm" onClick={onSwitchVersion}>
                Switch version
              </Button>
            ) : null}
            {onAskAgent ? (
              <Button variant="outline" size="sm" onClick={onAskAgent}>
                Repair in Studio
              </Button>
            ) : null}
            {onViewLogs ? (
              <Button variant="outline" size="sm" onClick={onViewLogs}>
                View logs
              </Button>
            ) : null}
            {viewToolHref ? (
              <Button variant="outline" size="sm" asChild>
                <a href={viewToolHref}>View tool</a>
              </Button>
            ) : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}
