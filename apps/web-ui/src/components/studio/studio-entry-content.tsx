'use client'

import type { ReactNode } from 'react'
import { Sparkles } from 'lucide-react'

import {
  STUDIO_ENTRY_DESCRIPTION,
  STUDIO_ENTRY_TITLE,
} from '@/components/studio/studio-entry-copy'
import { OfficialWorkflowTemplates } from '@/components/studio/official-workflow-templates'
import { StudioPromptEntry } from '@/components/studio/studio-prompt-entry'

type StudioEntryContentProps = {
  promptValue: string
  onPromptChange: (value: string) => void
  onSubmitPrompt: () => void
  promptSubmitLabel: string
  promptSubmitDisabled?: boolean
  promptSecondaryActionLabel?: string
  onPromptSecondaryAction?: () => void
  promptTextareaClassName?: string
  onPickPipeline: (pipelineId: string) => void
  templateTestIdPrefix: string
  children?: ReactNode
}

export function StudioEntryContent({
  promptValue,
  onPromptChange,
  onSubmitPrompt,
  promptSubmitLabel,
  promptSubmitDisabled = false,
  promptSecondaryActionLabel,
  onPromptSecondaryAction,
  promptTextareaClassName,
  onPickPipeline,
  templateTestIdPrefix,
  children,
}: StudioEntryContentProps) {
  return (
    <div className="space-y-6">
      <div className="space-y-2 text-center">
        <div className="inline-flex items-center justify-center rounded-full bg-muted/40 px-3 py-1 text-xs text-muted-foreground">
          <Sparkles className="mr-2 h-3 w-3" />
          Welcome
        </div>
        <h2 className="text-2xl font-semibold">{STUDIO_ENTRY_TITLE}</h2>
        <p className="text-sm text-muted-foreground">{STUDIO_ENTRY_DESCRIPTION}</p>
      </div>

      <StudioPromptEntry
        value={promptValue}
        onChange={onPromptChange}
        onSubmit={onSubmitPrompt}
        submitDisabled={promptSubmitDisabled}
        submitLabel={promptSubmitLabel}
        secondaryActionLabel={promptSecondaryActionLabel}
        onSecondaryAction={onPromptSecondaryAction}
        textareaClassName={promptTextareaClassName}
      />

      <OfficialWorkflowTemplates
        onPickPipeline={onPickPipeline}
        testIdPrefix={templateTestIdPrefix}
      />

      {children}
    </div>
  )
}
