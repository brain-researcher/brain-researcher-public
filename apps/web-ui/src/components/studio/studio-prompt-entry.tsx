'use client'

import {
  STUDIO_ENTRY_PROMPT_PLACEHOLDER,
  STUDIO_ENTRY_PROMPT_TITLE,
} from '@/components/studio/studio-entry-copy'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'

type StudioPromptEntryProps = {
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
  submitDisabled?: boolean
  submitLabel: string
  secondaryActionLabel?: string
  onSecondaryAction?: () => void
  title?: string
  placeholder?: string
  textareaClassName?: string
}

export function StudioPromptEntry({
  value,
  onChange,
  onSubmit,
  submitDisabled = false,
  submitLabel,
  secondaryActionLabel,
  onSecondaryAction,
  title = STUDIO_ENTRY_PROMPT_TITLE,
  placeholder = STUDIO_ENTRY_PROMPT_PLACEHOLDER,
  textareaClassName,
}: StudioPromptEntryProps) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="space-y-3">
          <div className="text-sm font-medium">{title}</div>
          <Textarea
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder={placeholder}
            className={textareaClassName}
          />
          <div className="flex flex-wrap items-center justify-between gap-2">
            {secondaryActionLabel && onSecondaryAction ? (
              <Button type="button" variant="ghost" onClick={onSecondaryAction}>
                {secondaryActionLabel}
              </Button>
            ) : (
              <div />
            )}
            <Button type="button" onClick={onSubmit} disabled={submitDisabled}>
              {submitLabel}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
