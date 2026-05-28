'use client'

import { Bot, ExternalLink, FolderOpen, Loader2 } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import type { StudioRuntimeProfile, StudioSession } from '@/lib/api/studio-sessions'

export type StudioAssistantMessage = {
  id: string
  role: 'assistant' | 'user' | 'system'
  title: string
  content: string
  pending?: boolean
}

type StudioAssistantPaneProps = {
  projectId: string
  displayName: string
  runtimeProfileId: StudioRuntimeProfile
  assistantMessages: StudioAssistantMessage[]
  assistantPrompt: string
  session: StudioSession | null
  loading: boolean
  connecting: boolean
  launchingWorkspace: boolean
  sending: boolean
  notebookReady: boolean
  onProjectIdChange: (value: string) => void
  onDisplayNameChange: (value: string) => void
  onRuntimeProfileChange: (value: StudioRuntimeProfile) => void
  onAssistantPromptChange: (value: string) => void
  onConnectSession: () => void
  onSubmitPrompt: () => void
  onLaunchWorkspace: () => void
  onOpenNotebook: () => void
}

const runtimeProfiles: Array<{ value: StudioRuntimeProfile; label: string }> = [
  { value: 'standard', label: 'Standard' },
  { value: 'high_mem', label: 'High memory' },
  { value: 'gpu', label: 'GPU' },
]

function statusTone(session: StudioSession | null) {
  if (!session) return 'system'
  return session.status === 'ready' ? 'assistant' : 'user'
}

export function StudioAssistantPane({
  projectId,
  displayName,
  runtimeProfileId,
  assistantMessages,
  assistantPrompt,
  session,
  loading,
  connecting,
  launchingWorkspace,
  sending,
  notebookReady,
  onProjectIdChange,
  onDisplayNameChange,
  onRuntimeProfileChange,
  onAssistantPromptChange,
  onConnectSession,
  onSubmitPrompt,
  onLaunchWorkspace,
  onOpenNotebook,
}: StudioAssistantPaneProps) {
  return (
    <Card className="flex h-[calc(100vh-5.5rem)] min-h-[720px] flex-col overflow-hidden border-slate-200 bg-white shadow-sm">
      <CardContent className="flex min-h-0 flex-1 flex-col p-0">
        <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
          <div className="flex min-w-0 items-center gap-2">
            <Bot className="h-4 w-4 text-slate-500" />
            <div className="min-w-0">
              <div className="text-sm font-semibold text-slate-950">Chat</div>
              <div className="truncate text-xs text-slate-500">
                {session?.project_id ?? projectId} · {notebookReady ? 'notebook synced' : 'draft notebook'}
              </div>
            </div>
          </div>
          <Badge
            variant="outline"
            className={cn(
              'shrink-0 capitalize',
              statusTone(session) === 'assistant' && 'border-emerald-300 bg-emerald-50 text-emerald-900',
            )}
          >
            {session?.status ?? 'draft'}
          </Badge>
        </div>

        <div className="border-b border-slate-200 px-4 py-3">
          <div className="grid gap-2">
            <Input
              value={projectId}
              onChange={(event) => onProjectIdChange(event.target.value)}
              placeholder="Project ID"
              className="h-9"
            />
            <div className="grid grid-cols-[minmax(0,1fr)_124px] gap-2">
              <Input
                value={displayName}
                onChange={(event) => onDisplayNameChange(event.target.value)}
                placeholder="Session name"
                className="h-9"
              />
              <select
                className="h-9 rounded-md border border-input bg-background px-3 text-sm"
                value={runtimeProfileId}
                onChange={(event) =>
                  onRuntimeProfileChange(event.target.value as StudioRuntimeProfile)
                }
              >
                {runtimeProfiles.map((profile) => (
                  <option key={profile.value} value={profile.value}>
                    {profile.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button type="button" size="sm" onClick={onConnectSession} disabled={connecting || loading}>
                {connecting ? <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" /> : null}
                {session ? 'Reconnect' : 'Create'}
              </Button>
              <Button type="button" size="sm" variant="outline" onClick={onOpenNotebook}>
                <FolderOpen className="mr-2 h-3.5 w-3.5" />
                Notebook
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={onLaunchWorkspace}
                disabled={launchingWorkspace}
              >
                {launchingWorkspace ? (
                  <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <ExternalLink className="mr-2 h-3.5 w-3.5" />
                )}
                {launchingWorkspace ? 'Launching…' : 'Launch Workspace'}
              </Button>
            </div>
            <p className="text-xs leading-5 text-slate-500">
              For the full notebook-native experience, launch your workspace in JupyterLab.
            </p>
          </div>
        </div>

        <ScrollArea className="min-h-0 flex-1 px-4 py-4">
          <div className="space-y-3">
            {assistantMessages.map((message) => (
              <div
                key={message.id}
                className={cn(
                  'rounded-2xl border px-4 py-3 text-sm',
                  message.role === 'assistant' && 'border-slate-200 bg-slate-50',
                  message.role === 'user' && 'ml-6 border-sky-200 bg-sky-50',
                  message.role === 'system' && 'border-dashed border-slate-300 bg-white',
                  message.pending && 'border-amber-200 bg-amber-50',
                )}
              >
                <div className="mb-1 flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">
                    {message.pending ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
                    <span>{message.title}</span>
                  </div>
                  <div className="text-[11px] uppercase tracking-[0.12em] text-slate-400">
                    {message.pending ? 'working' : message.role}
                  </div>
                </div>
                <div className="whitespace-pre-wrap leading-6 text-slate-800">{message.content}</div>
              </div>
            ))}
          </div>
        </ScrollArea>

        <div className="border-t border-slate-200 p-4">
          <div className="space-y-2">
            <Textarea
              value={assistantPrompt}
              onChange={(event) => onAssistantPromptChange(event.target.value)}
              placeholder="Describe the notebook you want, for example: generate a notebook to visualize T1 images."
              className="min-h-[110px] resize-none border-slate-200"
            />
            <div className="flex gap-2">
              <Button
                type="button"
                onClick={onSubmitPrompt}
                disabled={!assistantPrompt.trim() || sending}
              >
                {sending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Bot className="mr-2 h-4 w-4" />
                )}
                Send
              </Button>
              <Button type="button" variant="ghost" onClick={onOpenNotebook}>
                Focus notebook
              </Button>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
