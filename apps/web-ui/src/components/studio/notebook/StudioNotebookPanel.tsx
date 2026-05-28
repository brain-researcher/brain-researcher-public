'use client'

import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  ArrowDown,
  ArrowUp,
  Code2,
  FileText,
  Play,
  Plus,
  Save,
  Trash2,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import type {
  StudioNotebookCell,
  StudioNotebookCellType,
  StudioNotebookDocument,
  StudioNotebookMode,
} from '@/lib/api/studio-notebook'

type StudioNotebookPanelProps = {
  notebook: StudioNotebookDocument
  mode: StudioNotebookMode
  isConnected: boolean
  isSaving: boolean
  isDirty: boolean
  onModeChange: (mode: StudioNotebookMode) => void
  onSave: () => void
  onOpenOrCreate: () => void
  onRunCell: (cellId: string) => void
  onAppendCell: (cellType: StudioNotebookCellType) => void
  onUpdateCellSource: (cellId: string, source: string) => void
  onDeleteCell: (cellId: string) => void
  onMoveCell: (cellId: string, direction: -1 | 1) => void
}

function CellBadge({ cell }: { cell: StudioNotebookCell }) {
  if (cell.cell_type === 'markdown') {
    return (
      <Badge variant="secondary" className="gap-1">
        <FileText className="h-3 w-3" />
        Markdown
      </Badge>
    )
  }
  return (
    <Badge variant="outline" className="gap-1">
      <Code2 className="h-3 w-3" />
      Code
    </Badge>
  )
}

function OutputPanel({ cell }: { cell: StudioNotebookCell }) {
  if (!cell.outputs.length) {
    return (
      <div className="rounded-lg border border-dashed bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
        No outputs yet.
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {cell.outputs.map((output, index) => (
        <div
          key={`${cell.id}-${index}`}
          className={cn(
            'rounded-lg border px-3 py-2 text-xs',
            output.output_type === 'error' && 'border-rose-200 bg-rose-50 text-rose-950',
            output.output_type !== 'error' && 'border-slate-200 bg-slate-50 text-slate-900',
          )}
        >
          <div className="mb-1 font-semibold uppercase tracking-[0.16em] text-[10px] opacity-70">
            {output.output_type}
          </div>
          {typeof output.text === 'string' ? (
            <pre className="whitespace-pre-wrap font-mono text-xs leading-5">{output.text}</pre>
          ) : Array.isArray(output.text) ? (
            <pre className="whitespace-pre-wrap font-mono text-xs leading-5">
              {output.text.join('')}
            </pre>
          ) : output.output_type === 'error' ? (
            <div>
              <div className="font-medium">{output.ename ?? 'Error'}</div>
              <div>{output.evalue ?? 'Execution failed.'}</div>
              {output.traceback?.length ? (
                <pre className="mt-2 whitespace-pre-wrap font-mono text-[11px] leading-5">
                  {output.traceback.join('\n')}
                </pre>
              ) : null}
            </div>
          ) : output.data ? (
            <pre className="whitespace-pre-wrap font-mono text-xs leading-5">
              {JSON.stringify(output.data, null, 2)}
            </pre>
          ) : (
            <span>Rendered output.</span>
          )}
        </div>
      ))}
    </div>
  )
}

function NotebookCellCard({
  cell,
  mode,
  onUpdateCellSource,
  onDeleteCell,
  onMoveCell,
  onRunCell,
}: {
  cell: StudioNotebookCell
  mode: StudioNotebookMode
  onUpdateCellSource: (cellId: string, source: string) => void
  onDeleteCell: (cellId: string) => void
  onMoveCell: (cellId: string, direction: -1 | 1) => void
  onRunCell: (cellId: string) => void
}) {
  return (
    <Card className="overflow-hidden border-slate-200/90 bg-white/90 shadow-sm">
      <CardHeader className="space-y-3 border-b bg-slate-50/80 pb-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <CellBadge cell={cell} />
            <span className="text-xs font-mono text-muted-foreground">
              {cell.id.slice(0, 12)}
            </span>
            <Badge variant="outline" className="capitalize">
              {cell.status}
            </Badge>
          </div>
          <div className="flex items-center gap-2">
            {cell.cell_type === 'code' ? (
              <Button type="button" size="sm" variant="outline" onClick={() => onRunCell(cell.id)}>
                <Play className="mr-2 h-3.5 w-3.5" />
                Run
              </Button>
            ) : null}
            <Button type="button" size="icon" variant="ghost" onClick={() => onMoveCell(cell.id, -1)}>
              <ArrowUp className="h-4 w-4" />
            </Button>
            <Button type="button" size="icon" variant="ghost" onClick={() => onMoveCell(cell.id, 1)}>
              <ArrowDown className="h-4 w-4" />
            </Button>
            <Button type="button" size="icon" variant="ghost" onClick={() => onDeleteCell(cell.id)}>
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 p-4">
        {mode === 'edit' ? (
          <Textarea
            value={cell.source}
            onChange={(event) => onUpdateCellSource(cell.id, event.target.value)}
            className={cn(
              'min-h-[120px] resize-y font-mono text-sm leading-6',
              cell.cell_type === 'markdown' ? 'min-h-[150px]' : '',
            )}
          />
        ) : cell.cell_type === 'markdown' ? (
          <div className="prose prose-slate max-w-none text-sm">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{cell.source}</ReactMarkdown>
          </div>
        ) : (
          <pre className="overflow-auto rounded-lg bg-slate-950 px-4 py-3 font-mono text-sm leading-6 text-slate-100">
            {cell.source}
          </pre>
        )}
        {cell.cell_type === 'code' ? <OutputPanel cell={cell} /> : null}
      </CardContent>
    </Card>
  )
}

export function StudioNotebookPanel({
  notebook,
  mode,
  isConnected,
  isSaving,
  isDirty,
  onModeChange,
  onSave,
  onOpenOrCreate,
  onRunCell,
  onAppendCell,
  onUpdateCellSource,
  onDeleteCell,
  onMoveCell,
}: StudioNotebookPanelProps) {
  return (
    <Card className="flex h-[calc(100vh-5.5rem)] min-h-[720px] flex-col overflow-hidden border-slate-200 bg-white shadow-sm">
      <CardHeader className="border-b border-slate-200 bg-white px-4 py-3">
        <div className="flex flex-wrap items-center gap-3">
          <div className="min-w-0 flex-1">
            <CardTitle className="truncate text-base text-slate-950">{notebook.title}</CardTitle>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
              <span className="truncate">{notebook.path}</span>
              <span>rev {notebook.revision}</span>
              <span>{isConnected ? 'connected' : 'draft'}</span>
              <span>{isDirty ? 'unsaved' : 'saved'}</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <div className="inline-flex rounded-md border border-slate-200 p-0.5">
              <Button
                type="button"
                size="sm"
                variant={mode === 'preview' ? 'secondary' : 'ghost'}
                className="h-8 rounded-sm px-3"
                onClick={() => onModeChange('preview')}
              >
                Preview
              </Button>
              <Button
                type="button"
                size="sm"
                variant={mode === 'edit' ? 'secondary' : 'ghost'}
                className="h-8 rounded-sm px-3"
                onClick={() => onModeChange('edit')}
              >
                Edit
              </Button>
            </div>
            <Button type="button" size="sm" variant="outline" onClick={onOpenOrCreate}>
              Open
            </Button>
            <Button type="button" size="sm" onClick={onSave} disabled={isSaving}>
              <Save className="mr-2 h-4 w-4" />
              {isSaving ? 'Saving' : 'Save'}
            </Button>
          </div>
        </div>
      </CardHeader>

      <CardContent className="flex min-h-0 flex-1 flex-col gap-3 p-3">
        <div className="flex items-center justify-end gap-2">
          <Button type="button" variant="outline" size="sm" onClick={() => onAppendCell('markdown')}>
            <Plus className="mr-2 h-4 w-4" />
            Markdown
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={() => onAppendCell('code')}>
            <Plus className="mr-2 h-4 w-4" />
            Code
          </Button>
        </div>

        <ScrollArea className="min-h-0 flex-1 pr-1">
          <div className="space-y-4 pb-4">
            {notebook.cells.map((cell, index) => (
              <div key={cell.id} className="space-y-3">
                <NotebookCellCard
                  cell={cell}
                  mode={mode}
                  onUpdateCellSource={onUpdateCellSource}
                  onDeleteCell={onDeleteCell}
                  onMoveCell={onMoveCell}
                  onRunCell={onRunCell}
                />
                {index < notebook.cells.length - 1 ? (
                  <Separator className="bg-transparent" />
                ) : null}
              </div>
            ))}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  )
}
