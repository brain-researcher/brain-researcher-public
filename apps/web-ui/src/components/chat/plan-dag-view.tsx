'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { flushSync } from 'react-dom'
import ReactFlow, {
  Background,
  BackgroundVariant,
  BaseEdge,
  Handle,
  type EdgeProps,
  type Node,
  type NodeProps,
  type Edge,
  type Viewport,
  type ReactFlowInstance,
  getSmoothStepPath,
  Position,
  MarkerType,
} from 'reactflow'
import 'reactflow/dist/style.css'

import { Maximize2, Minus, Plus, RefreshCw } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export type PlanDagStep = {
  order: number
  tool: string
  description: string
  paramNames: string[]
}

export type DagNodeStatus =
  | 'pending'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'cancelled'
  | 'skipped'

type PlanDagStepNodeData = {
  order: number
  tool: string
  description: string
  onSelect?: () => void
  status?: DagNodeStatus
}

function PlanDagStepNode({ data }: NodeProps<PlanDagStepNodeData>) {
  const status: DagNodeStatus = data.status ?? 'pending'
  const statusLabel = {
    pending: 'Pending',
    running: 'Running',
    succeeded: 'Done',
    failed: 'Failed',
    cancelled: 'Cancelled',
    skipped: 'Skipped',
  }[status]

  const statusDotClass = {
    pending: 'bg-slate-400',
    running: 'bg-blue-500',
    succeeded: 'bg-emerald-500',
    failed: 'bg-red-500',
    cancelled: 'bg-slate-400',
    skipped: 'bg-slate-400',
  }[status]

  const statusBorderClass = {
    pending: 'border-slate-200 dark:border-slate-700',
    running: 'border-blue-300 dark:border-blue-600',
    succeeded: 'border-emerald-300 dark:border-emerald-600',
    failed: 'border-red-300 dark:border-red-600',
    cancelled: 'border-slate-200 dark:border-slate-700',
    skipped: 'border-slate-200 dark:border-slate-700',
  }[status]

  const statusBgClass = {
    pending: 'bg-white dark:bg-slate-900',
    running: 'bg-blue-50 dark:bg-blue-950/30',
    succeeded: 'bg-emerald-50 dark:bg-emerald-950/30',
    failed: 'bg-red-50 dark:bg-red-950/30',
    cancelled: 'bg-slate-50 dark:bg-slate-900',
    skipped: 'bg-slate-50 dark:bg-slate-900',
  }[status]

  return (
    <button
      type="button"
      data-testid={`dag-node-step-${data.order}`}
      data-status={status}
      onClick={() => data.onSelect?.()}
      aria-label={`Step ${data.order}: ${data.tool} (${statusLabel})`}
      className={cn(
        'min-w-[180px] max-w-[220px] rounded-xl border-2 px-4 py-3 text-left shadow-md transition-all duration-200',
        'hover:shadow-lg hover:scale-[1.02] hover:border-primary/60',
        'focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2',
        statusBorderClass,
        statusBgClass,
      )}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!h-3 !w-3 !border-2 !border-slate-300 !bg-white dark:!border-slate-600 dark:!bg-slate-800"
      />
      <Handle
        type="source"
        position={Position.Right}
        className="!h-3 !w-3 !border-2 !border-slate-300 !bg-white dark:!border-slate-600 dark:!bg-slate-800"
      />
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-primary/10 text-xs font-bold text-primary">
            {data.order}
          </span>
          <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            Step
          </span>
        </div>
        <span
          className={cn(
            'inline-flex h-2.5 w-2.5 shrink-0 rounded-full',
            statusDotClass,
            status === 'running' ? 'animate-pulse' : null,
          )}
          aria-hidden="true"
          title={statusLabel}
        />
      </div>
      <div className="mt-2 text-sm font-semibold text-foreground leading-tight">
        <span className="font-mono text-[13px]">{data.tool}</span>
      </div>
      {data.description ? (
        <div className="mt-1.5 line-clamp-2 text-xs text-muted-foreground leading-relaxed">
          {data.description}
        </div>
      ) : null}
    </button>
  )
}

function PlanDagEdge(props: EdgeProps) {
  const [edgePath] = getSmoothStepPath(props)
  const edgeData = props.data as { status?: DagNodeStatus; stroke?: string } | undefined
  return (
    <>
      <BaseEdge id={props.id} path={edgePath} markerEnd={props.markerEnd} style={props.style} />
      <path
        data-testid={`dag-edge-${props.id}`}
        data-status={edgeData?.status}
        data-stroke={edgeData?.stroke}
        d={edgePath}
        fill="none"
        stroke="transparent"
        strokeWidth={1}
      />
    </>
  )
}

const nodeTypes = { step: PlanDagStepNode }
const edgeTypes = { dag: PlanDagEdge }

const defaultEdgeOptions = {
  type: 'dag',
  markerEnd: {
    type: MarkerType.ArrowClosed,
    width: 16,
    height: 16,
  },
  style: {
    strokeWidth: 2.5,
    strokeLinecap: 'round' as const,
  },
} satisfies Partial<Edge>

type PlanDagViewProps = {
  steps: PlanDagStep[]
  statusByOrder?: Partial<Record<number, DagNodeStatus>>
  onStepSelect?: (order: number) => void
  className?: string
}

export function PlanDagView({ steps, statusByOrder, onStepSelect, className }: PlanDagViewProps) {
  const [viewport, setViewport] = useState<Viewport>({ x: 0, y: 0, zoom: 1 })
  const [isReady, setIsReady] = useState(false)
  const [isSpacePressed, setIsSpacePressed] = useState(false)
  const [isPointerDown, setIsPointerDown] = useState(false)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const reactFlowRef = useRef<ReactFlowInstance | null>(null)

  useEffect(() => {
    function isEditableTarget(target: EventTarget | null) {
      if (!(target instanceof HTMLElement)) return false
      const tagName = target.tagName.toLowerCase()
      return tagName === 'input' || tagName === 'textarea' || tagName === 'select' || target.isContentEditable
    }

    function onKeyDown(event: KeyboardEvent) {
      if (isEditableTarget(event.target)) return

      if (event.key === ' ' || event.code === 'Space') {
        event.preventDefault()
        flushSync(() => setIsSpacePressed(true))
        return
      }

      if (event.defaultPrevented) return
      if (!reactFlowRef.current) return

      if (event.key === '0') {
        event.preventDefault()
        reactFlowRef.current.fitView({ padding: 0.2 })
        return
      }

      const isZoomIn = event.key === '+' || (event.code === 'Equal' && event.shiftKey)
      const isZoomOut = event.key === '-' || event.code === 'Minus'

      if (isZoomIn) {
        event.preventDefault()
        reactFlowRef.current.zoomIn()
      } else if (isZoomOut) {
        event.preventDefault()
        reactFlowRef.current.zoomOut()
      }
    }

    function onKeyUp(event: KeyboardEvent) {
      if (event.key === ' ') {
        flushSync(() => setIsSpacePressed(false))
      }
    }

    function onWindowBlur() {
      setIsSpacePressed(false)
      setIsPointerDown(false)
    }

    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('keyup', onKeyUp)
    window.addEventListener('blur', onWindowBlur)

    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('keyup', onKeyUp)
      window.removeEventListener('blur', onWindowBlur)
    }
  }, [])

  const nodes = useMemo((): Node<PlanDagStepNodeData>[] => {
    return steps.map((step, idx) => {
      const order = step.order || idx + 1
      return {
        id: `step-${order}`,
        type: 'step',
        draggable: false,
        // Increased horizontal spacing for better readability
        position: { x: idx * 280, y: 0 },
        data: {
          order,
          tool: step.tool,
          description: step.description,
          status: statusByOrder?.[order],
          onSelect:
            onStepSelect && !isSpacePressed ? () => onStepSelect(order) : undefined,
        },
      }
    })
  }, [steps, onStepSelect, statusByOrder, isSpacePressed])

  const edges = useMemo((): Edge[] => {
    if (steps.length < 2) return []
    const orders = steps.map((step, idx) => step.order || idx + 1)
    return orders.slice(1).map((targetOrder, idx) => {
      const sourceOrder = orders[idx]
      const source = `step-${sourceOrder}`
      const target = `step-${targetOrder}`
      const sourceStatus = statusByOrder?.[sourceOrder] ?? 'pending'
      const targetStatus = statusByOrder?.[targetOrder] ?? 'pending'
      const isFailed = sourceStatus === 'failed' || targetStatus === 'failed'
      const isRunning = sourceStatus === 'running' || targetStatus === 'running'
      const isDone = sourceStatus === 'succeeded' && targetStatus === 'succeeded'
      const isCancelled = sourceStatus === 'cancelled' || targetStatus === 'cancelled'
      const isSkipped = sourceStatus === 'skipped' || targetStatus === 'skipped'
      const edgeStatus: DagNodeStatus = isFailed
        ? 'failed'
        : isCancelled
          ? 'cancelled'
          : isRunning
            ? 'running'
            : isDone
              ? 'succeeded'
              : isSkipped
                ? 'skipped'
                : 'pending'
      const stroke = isFailed
        ? 'hsl(var(--destructive))'
        : isRunning
          ? 'hsl(var(--primary))'
          : isDone
            ? 'hsl(var(--primary))'
            : 'hsl(var(--muted-foreground))'

      return {
        id: `edge-step-${sourceOrder}-step-${targetOrder}`,
        source,
        target,
        animated: isRunning,
        style: { stroke },
        data: {
          status: edgeStatus,
          stroke,
        },
      }
    })
  }, [steps, statusByOrder])

  return (
    <div
      ref={containerRef}
      data-testid="plan-dag-view"
      data-space-pressed={isSpacePressed ? 'true' : 'false'}
      tabIndex={0}
      onPointerDownCapture={() => {
        containerRef.current?.focus()
        setIsPointerDown(true)
      }}
      onPointerUpCapture={() => setIsPointerDown(false)}
      onPointerCancel={() => setIsPointerDown(false)}
      className={cn(
        'relative h-[200px] w-full overflow-hidden rounded-2xl border bg-gradient-to-br from-slate-50 to-slate-100/50 dark:from-slate-900 dark:to-slate-800/50',
        isSpacePressed ? null : 'dag-nopan',
        isSpacePressed ? (isPointerDown ? 'cursor-grabbing' : 'cursor-grab') : null,
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2',
        className,
      )}
    >
      <div
        data-testid="dag-viewport"
        data-x={viewport.x}
        data-y={viewport.y}
        data-zoom={viewport.zoom}
        className="sr-only"
      />
      <div className="absolute bottom-2 left-2 z-10 flex items-center gap-1 rounded-lg bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm p-1 shadow-sm border border-slate-200/50 dark:border-slate-700/50">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          data-testid="dag-zoom-in"
          aria-label="Zoom in"
          disabled={!isReady}
          onClick={() => reactFlowRef.current?.zoomIn()}
          className="h-7 w-7 hover:bg-slate-100 dark:hover:bg-slate-800"
        >
          <Plus className="h-3.5 w-3.5" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          data-testid="dag-zoom-out"
          aria-label="Zoom out"
          disabled={!isReady}
          onClick={() => reactFlowRef.current?.zoomOut()}
          className="h-7 w-7 hover:bg-slate-100 dark:hover:bg-slate-800"
        >
          <Minus className="h-3.5 w-3.5" />
        </Button>
        <div className="w-px h-4 bg-slate-200 dark:bg-slate-700" />
        <Button
          type="button"
          variant="ghost"
          size="icon"
          data-testid="dag-fitview"
          aria-label="Fit view"
          disabled={!isReady}
          onClick={() => reactFlowRef.current?.fitView({ padding: 0.3 })}
          className="h-7 w-7 hover:bg-slate-100 dark:hover:bg-slate-800"
        >
          <Maximize2 className="h-3.5 w-3.5" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          data-testid="dag-reset"
          aria-label="Reset view"
          disabled={!isReady}
          onClick={() => reactFlowRef.current?.setViewport({ x: 0, y: 0, zoom: 1 })}
          className="h-7 w-7 hover:bg-slate-100 dark:hover:bg-slate-800"
        >
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onInit={(instance) => {
          reactFlowRef.current = instance
          setIsReady(true)
          // Auto fit with better padding after init
          setTimeout(() => instance.fitView({ padding: 0.3 }), 50)
        }}
        fitView
        fitViewOptions={{ padding: 0.3, maxZoom: 1.2 }}
        minZoom={0.3}
        maxZoom={2}
        panOnDrag
        selectionOnDrag={false}
        zoomOnScroll={true}
        zoomOnPinch={true}
        onMove={(_, nextViewport) => setViewport(nextViewport)}
        noPanClassName={isSpacePressed ? undefined : 'dag-nopan'}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={true}
        defaultEdgeOptions={defaultEdgeOptions}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="hsl(var(--muted-foreground) / 0.2)" />
      </ReactFlow>
    </div>
  )
}
