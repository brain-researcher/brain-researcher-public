'use client'

import { useState } from 'react'

import type { HypothesisChatMessage } from '@/types/hypothesis'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'

type HypothesisChatBoxProps = {
  messages: HypothesisChatMessage[]
  disabled?: boolean
  submitting?: boolean
  onSend: (message: string) => Promise<void> | void
}

export function HypothesisChatBox({
  messages,
  disabled = false,
  submitting = false,
  onSend,
}: HypothesisChatBoxProps) {
  const [value, setValue] = useState('')

  const submit = async () => {
    const trimmed = value.trim()
    if (!trimmed || disabled || submitting) return
    await onSend(trimmed)
    setValue('')
  }

  return (
    <Card className="border-border/70">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Chatbot</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 pt-0">
        <div className="max-h-48 overflow-y-auto rounded-md border border-border/70 p-3 space-y-2 text-sm">
          {messages.length ? (
            messages.slice(-8).map((message) => (
              <div key={message.id}>
                <span className="font-medium capitalize">{message.role}:</span>{' '}
                <span className="text-muted-foreground">{message.content}</span>
              </div>
            ))
          ) : (
            <div className="text-xs text-muted-foreground">No conversation yet.</div>
          )}
        </div>

        <div className="flex items-end gap-2">
          <Textarea
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder="Ask why this ranks high, improve MDE, or say: explore new ideas"
            className="min-h-[80px]"
            disabled={disabled || submitting}
          />
          <Button type="button" onClick={submit} disabled={disabled || submitting || !value.trim()}>
            {submitting ? 'Sending...' : 'Send'}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
