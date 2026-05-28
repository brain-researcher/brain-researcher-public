'use client'

import { PlugZap } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'

type StudioEntryIdeCardProps = {
  onConnectIde: () => void
}

export function StudioEntryIdeCard({ onConnectIde }: StudioEntryIdeCardProps) {
  return (
    <Card>
      <CardContent className="p-4 flex items-start justify-between gap-4">
        <div className="space-y-1">
          <div className="text-sm font-medium flex items-center gap-2">
            <PlugZap className="h-4 w-4 text-muted-foreground" />
            Use in your IDE
          </div>
          <div className="text-sm text-muted-foreground">
            Take validated plans into Cursor, Codex, or Claude Code for full execution.
          </div>
        </div>
        <Button type="button" variant="outline" onClick={onConnectIde}>
          Connect IDE →
        </Button>
      </CardContent>
    </Card>
  )
}
