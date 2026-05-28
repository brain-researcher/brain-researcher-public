'use client'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'

type IntentConfirmBarProps = {
  intentQuery: string
  disabled?: boolean
  running?: boolean
  onConfirm: () => Promise<void> | void
}

export function IntentConfirmBar({
  intentQuery,
  disabled = false,
  running = false,
  onConfirm,
}: IntentConfirmBarProps) {
  return (
    <Card className="border-border/70">
      <CardContent className="p-3 flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div className="text-sm">
          <span className="font-medium">Intent query:</span>{' '}
          {intentQuery || 'Send a chat message to set the research intent.'}
        </div>
        <Button
          type="button"
          onClick={() => void onConfirm()}
          disabled={disabled || running || !intentQuery.trim()}
        >
          {running ? 'Running...' : 'Start Deep Research'}
        </Button>
      </CardContent>
    </Card>
  )
}

