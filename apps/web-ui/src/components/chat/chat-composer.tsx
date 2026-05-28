'use client'

import { useEffect, useState, useRef, KeyboardEvent } from 'react'
import { Send, Paperclip, Zap } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { FileUploadZone } from '@/components/ui/file-upload-zone'
import { UploadProgress } from '@/components/ui/upload-progress'
import { FilePreview } from '@/components/ui/file-preview'
import { useFileUpload } from '@/hooks/use-file-upload'
import { useToast } from '@/hooks/use-toast'
import { FileAttachment } from '@/types/chat'
import { Checkbox } from '@/components/ui/checkbox'
import { Badge } from '@/components/ui/badge'

interface ChatComposerProps {
  onSubmit: (prompt: string, attachments?: FileAttachment[]) => void
  isLoading?: boolean
  placeholder?: string
  initialValue?: string
  codingMode: boolean
  onToggleCodingMode: () => void
  explainOnly?: boolean
  onToggleExplainOnly?: () => void
  context?: {
    dataset?: string
    datasetVersion?: string
    pipeline?: string
  }
  suggestions?: string[]
  injectedText?: string | null
  onConsumeInjectedText?: () => void
}

const PARAMETER_CHIPS = [
  { label: 'TR=2s', value: 'TR=2s' },
  { label: 'MNI152', value: 'template=MNI152' },
  { label: 'FWHM=6mm', value: 'smoothing_fwhm=6mm' },
  { label: 'p<0.001', value: 'threshold=0.001' },
]

const DEFAULT_SUGGESTED_QUESTIONS = [
  'What brain atlas/parcellation should I use for this neuroimaging analysis?',
  'How should I handle high motion subjects?',
  'Show me related papers for this pipeline.',
]

export function ChatComposer({
  onSubmit,
  isLoading,
  placeholder,
  initialValue,
  codingMode,
  onToggleCodingMode,
  explainOnly = false,
  onToggleExplainOnly,
  context,
  suggestions,
  injectedText,
  onConsumeInjectedText,
}: ChatComposerProps) {
  const [prompt, setPrompt] = useState(initialValue || '')
  const [hydrated, setHydrated] = useState(false)
  const [showFileUpload, setShowFileUpload] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const lastInjectedTextRef = useRef<string | null>(null)
  const { toast } = useToast()

  useEffect(() => setHydrated(true), [])

  useEffect(() => {
    if (!initialValue) return
    setPrompt((prev) => (prev.trim() ? prev : initialValue))
  }, [initialValue])

  useEffect(() => {
    if (!textareaRef.current) return
    const textarea = textareaRef.current
    textarea.style.height = 'auto'
    textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`
  }, [prompt])

  useEffect(() => {
    const value = injectedText?.trim()
    if (!value) return
    if (lastInjectedTextRef.current === value) return
    lastInjectedTextRef.current = value
    setPrompt((previous) => {
      const trimmed = previous.trim()
      if (!trimmed) return value
      if (trimmed.includes(value)) return previous
      return `${trimmed}\n${value}`
    })
    onConsumeInjectedText?.()
    requestAnimationFrame(() => {
      textareaRef.current?.focus()
    })
  }, [injectedText, onConsumeInjectedText])
  
  const {
    attachments,
    uploadingFiles,
    uploadFile,
    removeAttachment,
    clearAttachments,
    retryUpload,
    validateFile
  } = useFileUpload()

  const handleSubmit = () => {
    if (!prompt.trim() || isLoading) return
    onSubmit(prompt, attachments)
    setPrompt('')
    clearAttachments()
    setShowFileUpload(false)
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }

  const handleFilesSelected = async (files: File[]) => {
    for (const file of files) {
      const validation = validateFile(file)
      if (!validation.valid) {
        toast({
          title: "File validation failed",
          description: validation.error,
          variant: "destructive"
        })
        continue
      }

      try {
        await uploadFile(file)
        toast({
          title: "File uploaded",
          description: `${file.name} has been attached to your message.`
        })
      } catch (error) {
        toast({
          title: "Upload failed",
          description: error instanceof Error ? error.message : 'Failed to upload file',
          variant: "destructive"
        })
      }
    }
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const handleTextareaChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setPrompt(e.target.value)
    
    // Auto-resize textarea
    const textarea = e.target
    textarea.style.height = 'auto'
    textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`
  }

  const addParameterChip = (chip: string) => {
    const newPrompt = prompt + (prompt ? ' ' : '') + chip
    setPrompt(newPrompt)
    textareaRef.current?.focus()
  }

  const addSuggestedQuestion = (question: string) => {
    const contextParts = ['Context: neuroimaging analysis']
    if (context?.dataset) contextParts.push(`dataset=${context.dataset}`)
    if (context?.datasetVersion) contextParts.push(`dataset_version=${context.datasetVersion}`)
    if (context?.pipeline) contextParts.push(`pipeline=${context.pipeline}`)
    const groundedQuestion = contextParts.length > 1 ? `${contextParts.join('; ')}.\n${question}` : question
    setPrompt((previous) => {
      const trimmed = previous.trim()
      if (trimmed.includes(groundedQuestion)) return previous
      return trimmed ? `${trimmed}\n${groundedQuestion}` : groundedQuestion
    })
    setShowFileUpload(false)
    requestAnimationFrame(() => {
      textareaRef.current?.focus()
    })
  }

  const suggestedQuestions =
    suggestions && suggestions.length > 0 ? suggestions.slice(0, 4) : DEFAULT_SUGGESTED_QUESTIONS
  const datasetLabel = context?.dataset || 'No dataset selected'
  const datasetVersionLabel = context?.datasetVersion || 'No version'
  const pipelineLabel = context?.pipeline || 'No pipeline'
  const showSuggested = Boolean(context?.dataset || context?.pipeline)

  return (
    <Card
      className="p-4 border-2 focus-within:border-primary/50 transition-colors"
      data-testid="chat-composer"
      data-hydrated={hydrated ? '1' : '0'}
    >
      <div className="space-y-3">
        {/* Suggested questions */}
        {showSuggested ? (
          <div className="space-y-2">
            <div className="text-xs text-muted-foreground">Suggested questions</div>
            <div className="flex flex-wrap gap-2">
              {suggestedQuestions.map((question) => (
                <Button
                  key={question}
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={(event) => {
                    event.preventDefault()
                    event.stopPropagation()
                    addSuggestedQuestion(question)
                  }}
                  className="h-7 text-xs"
                  disabled={isLoading}
                >
                  {question}
                </Button>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
              <span className="font-medium">Context</span>
              <Badge variant="secondary">Dataset: {datasetLabel}</Badge>
              <Badge variant="secondary">Version: {datasetVersionLabel}</Badge>
              <Badge variant="secondary">Pipeline: {pipelineLabel}</Badge>
            </div>
          </div>
        ) : null}

        {/* Parameter chips */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex flex-wrap gap-2">
            {PARAMETER_CHIPS.map((chip) => (
              <Button
                key={chip.label}
                type="button"
                variant="outline"
                size="sm"
                onClick={() => addParameterChip(chip.value)}
                className="h-7 text-xs"
                disabled={isLoading}
              >
                <Zap className="h-3 w-3 mr-1" />
                {chip.label}
              </Button>
            ))}
          </div>
          {codingMode && onToggleExplainOnly && (
            <label className="flex items-center gap-2 text-xs text-muted-foreground select-none">
              <Checkbox
                id="explain-only"
                checked={explainOnly}
                onCheckedChange={() => onToggleExplainOnly?.()}
              />
              <span>Explain only (no file changes)</span>
            </label>
          )}
        </div>

        {/* Main input area */}
        <div className="relative">
          <textarea
            ref={textareaRef}
            data-testid="chat-input"
            value={prompt}
            onChange={handleTextareaChange}
            onKeyDown={handleKeyDown}
            placeholder={placeholder || 'Ask a question about your plan, evidence, or data...'}
            className="w-full min-h-[60px] max-h-[200px] p-3 pr-20 text-sm bg-transparent border-0 resize-none focus:outline-none placeholder:text-muted-foreground"
            disabled={isLoading}
          />
          
          {/* Action buttons */}
          <div className="absolute bottom-2 right-2 flex items-center gap-2">
            <Button
              type="button"
              variant={codingMode ? "default" : "ghost"}
              size="icon"
              className="h-8 w-8"
              disabled={isLoading}
              onClick={onToggleCodingMode}
              title={codingMode ? "Coding mode on (tools enabled)" : "Coding mode off (plain chat)"}
            >
              <Zap className="h-4 w-4" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              disabled={isLoading}
              onClick={() => setShowFileUpload(!showFileUpload)}
              title="Attach files"
            >
              <Paperclip className="h-4 w-4" />
            </Button>
            
            <Button
              type="button"
              data-testid="chat-send-button"
              aria-label="Send message"
              onClick={handleSubmit}
              disabled={(!prompt.trim() && attachments.length === 0) || isLoading || uploadingFiles.some(uf => uf.status === 'uploading')}
              size="icon"
              className="h-8 w-8"
            >
              <Send className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {/* File Upload Section */}
        {showFileUpload && (
          <div className="space-y-3 pt-3 border-t">
            <FileUploadZone
              onFilesSelected={handleFilesSelected}
              disabled={isLoading}
            />
            
            <UploadProgress
              uploadingFiles={uploadingFiles}
              onRetry={retryUpload}
            />
          </div>
        )}

        {/* File Attachments Preview */}
        {attachments.length > 0 && (
          <div className="pt-3 border-t">
            <FilePreview
              attachments={attachments}
              onRemove={removeAttachment}
              showRemove={!isLoading}
            />
          </div>
        )}

        {/* Helper text */}
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>
            {attachments.length > 0 
              ? `${attachments.length} file(s) attached` 
              : 'Use parameter chips or type freely'
            }
          </span>
          <span>⌘ + Enter to send</span>
        </div>
      </div>
    </Card>
  )
}
