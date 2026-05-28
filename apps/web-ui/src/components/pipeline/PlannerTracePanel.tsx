"use client"

import React, { useMemo } from 'react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { Copy, Download, AlertTriangle } from 'lucide-react'
import type { AgentPlanResponse } from '@/types/kg-responses'

type PlannerTracePanelProps = {
  plan?: AgentPlanResponse | null
}

const formatPercent = (value?: number) => {
  if (typeof value !== 'number') return 'N/A'
  return `${Math.round(value * 100)}%`
}

export function PlannerTracePanel({ plan }: PlannerTracePanelProps) {
  const tracePayload = useMemo(() => {
    if (!plan) return null
    return {
      planner_events: (plan as any).planner_events ?? [],
      planner_state: (plan as any).planner_state ?? null,
      run_summary: (plan as any).run_summary ?? null,
      mask_reasons: (plan as any).mask_reasons ?? null,
    }
  }, [plan])

  const copyTrace = async () => {
    if (!tracePayload) return
    try {
      await navigator.clipboard.writeText(JSON.stringify(tracePayload, null, 2))
    } catch {
      // ignore clipboard failures
    }
  }

  const downloadTrace = () => {
    if (!tracePayload) return
    const blob = new Blob([JSON.stringify(tracePayload, null, 2)], {
      type: 'application/json',
    })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `planner-trace-${Date.now()}.json`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  }

  const events: any[] = Array.isArray((plan as any)?.planner_events)
    ? (plan as any).planner_events
    : []

  const recoveryEvents = events.filter((e: any) => e?.event_type === 'recovery_triggered')

  const hasUncertainty =
    typeof plan?.run_summary?.uncertainty_penalty === 'number' &&
    (plan?.run_summary?.uncertainty_penalty ?? 0) >= 0.05

  const behaviorPolicyInfo = useMemo(() => {
    const reasons = (plan as any)?.selection_reasons
    if (!Array.isArray(reasons)) return null
    const entry = reasons.find(
      (r) => r && typeof r === 'object' && r.code === 'behavior_policy_options'
    )
    if (!entry) return null
    const policies = Array.isArray(entry.policies) ? entry.policies : []
    const table = entry.table as string | undefined
    return { policies, table }
  }, [plan])

  const maskReasons = Array.isArray((plan as any)?.mask_reasons)
    ? ((plan as any).mask_reasons as any[])
    : []

  if (!plan) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-gray-500 text-sm">
          No planner trace available. Generate a plan to view trace details.
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center justify-between">
            Planner Summary
            <div className="flex gap-2">
              <Button size="sm" variant="outline" onClick={copyTrace} disabled={!tracePayload}>
                <Copy className="h-3 w-3 mr-1" />
                Copy JSON
              </Button>
              <Button size="sm" variant="outline" onClick={downloadTrace} disabled={!tracePayload}>
                <Download className="h-3 w-3 mr-1" />
                Download
              </Button>
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline">
              Plan confidence: {formatPercent(plan.run_summary?.plan_conf ?? (plan as any).plan_conf ?? plan.confidence_score)}
            </Badge>
            <Badge variant="secondary">
              Chosen tool: {plan.chosen_tool_name || plan.chosen_tool}
            </Badge>
            {recoveryEvents.length > 0 && (
              <Badge variant="destructive">Recovery used</Badge>
            )}
            {hasUncertainty && (
              <Badge variant="outline" className="text-yellow-700 border-yellow-300">
                High uncertainty
              </Badge>
            )}
          </div>

          {typeof plan.run_summary?.uncertainty_penalty === 'number' && (
            <div className="text-xs text-gray-500">
              Uncertainty penalty: {formatPercent(plan.run_summary.uncertainty_penalty)}
            </div>
          )}
        </CardContent>
      </Card>

      {recoveryEvents.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-500" />
              Recovery Actions
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2 text-sm text-gray-700">
              {recoveryEvents.map((e: any, idx: number) => (
                <li key={e.event_id || idx}>
                  <span className="font-mono text-xs">
                    {e.payload?.from_tool} → {e.payload?.to_tool}
                  </span>
                  {e.payload?.reason ? (
                    <span className="ml-2 text-gray-500">{e.payload.reason}</span>
                  ) : null}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {maskReasons.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-500" />
              Constraint / Mask Reasons
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2 text-sm text-gray-700">
              {maskReasons.slice(0, 12).map((v: any, idx: number) => (
                <li key={`${v?.code || 'v'}-${idx}`} className="flex items-start justify-between gap-2">
                  <div className="flex items-start gap-2">
                    <span className="font-mono text-xs text-gray-900">{v?.code || 'violation'}</span>
                    <span className="text-gray-600">{v?.message || ''}</span>
                  </div>
                  {v?.blocking ? (
                    <Badge variant="destructive" className="text-[10px]">blocking</Badge>
                  ) : (
                    <Badge variant="outline" className="text-[10px]">{v?.severity || 'warn'}</Badge>
                  )}
                </li>
              ))}
            </ul>
            {maskReasons.length > 12 && (
              <div className="text-xs text-gray-500 mt-2">+{maskReasons.length - 12} more…</div>
            )}
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-4">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Branch Confidence</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {Array.isArray(plan.run_summary?.branch_conf) && plan.run_summary!.branch_conf!.length > 0 ? (
              plan.run_summary!.branch_conf!.map((b: any, idx: number) => (
                <div key={b.branch_id || idx} className="flex items-center justify-between text-sm">
                  <span className="font-mono text-xs">{b.branch_id || 'branch'}</span>
                  <span className="text-gray-700">{formatPercent(b.branch_conf)}</span>
                </div>
              ))
            ) : (
              <p className="text-xs text-gray-500">No branch confidence available.</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Step Confidence</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {Array.isArray(plan.run_summary?.step_conf) && plan.run_summary!.step_conf!.length > 0 ? (
              plan.run_summary!.step_conf!.map((s: any, idx: number) => (
                <div key={`${s.branch_id || 'br'}:${s.step_id || idx}`} className="flex items-center justify-between text-sm">
                  <span className="font-mono text-xs">
                    {(s.step_id || 'step')}{s.tool_id ? ` • ${s.tool_id}` : ''}
                  </span>
                  <span className="text-gray-700">{formatPercent(s.step_conf)}</span>
                </div>
              ))
            ) : (
              <p className="text-xs text-gray-500">No step confidence available.</p>
            )}
          </CardContent>
        </Card>
      </div>

      {behaviorPolicyInfo && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Behavior Policies</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-xs">
            {behaviorPolicyInfo.policies.length > 0 && (
              <div className="overflow-auto">
                <table className="w-full text-[11px] border border-border rounded">
                  <thead className="bg-muted/40">
                    <tr>
                      <th className="px-2 py-1 text-left">policy_id</th>
                      <th className="px-2 py-1 text-left">rt_min</th>
                      <th className="px-2 py-1 text-left">rt_max</th>
                      <th className="px-2 py-1 text-left">acc_min</th>
                      <th className="px-2 py-1 text-left">miss_max</th>
                      <th className="px-2 py-1 text-left">notes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {behaviorPolicyInfo.policies.map((p: any) => (
                      <tr key={p.policy_id}>
                        <td className="px-2 py-1 font-mono">{p.policy_id}</td>
                        <td className="px-2 py-1">{p.rt_min_sec ?? '-'}</td>
                        <td className="px-2 py-1">{p.rt_max_sec ?? '-'}</td>
                        <td className="px-2 py-1">{p.accuracy_min ?? '-'}</td>
                        <td className="px-2 py-1">{p.miss_rate_max ?? '-'}</td>
                        <td className="px-2 py-1 max-w-[240px] truncate">
                          {Array.isArray(p.notes) ? p.notes.join(' | ') : p.notes ?? '-'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {behaviorPolicyInfo.table && (
              <pre className="bg-muted/60 text-[11px] font-mono p-2 rounded whitespace-pre-wrap max-h-40 overflow-auto">
                {behaviorPolicyInfo.table}
              </pre>
            )}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Planner Timeline</CardTitle>
        </CardHeader>
        <CardContent>
          {events.length > 0 ? (
            <ScrollArea className="h-56">
              <ul className="space-y-2 text-xs text-gray-600">
                {events.map((e: any) => (
                  <li key={e.event_id || `${e.ts}:${e.event_type}`} className="flex items-start justify-between gap-3">
                    <span className="font-mono">{e.event_type}</span>
                    <span className="text-gray-400">
                      {typeof e.ts === 'number' ? new Date(e.ts * 1000).toLocaleTimeString() : ''}
                    </span>
                  </li>
                ))}
              </ul>
            </ScrollArea>
          ) : (
            <p className="text-xs text-gray-500">No planner trace events available.</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Hypotheses & Branches</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-xs text-gray-600">
          <div>
            <div className="text-xs text-gray-500 mb-1">Hypotheses</div>
            <ScrollArea className="h-24">
              <pre className="whitespace-pre-wrap">
                {JSON.stringify((plan as any).planner_state?.hypotheses ?? [], null, 2)}
              </pre>
            </ScrollArea>
          </div>
          <Separator />
          <div>
            <div className="text-xs text-gray-500 mb-1">Branches</div>
            <ScrollArea className="h-24">
              <pre className="whitespace-pre-wrap">
                {JSON.stringify((plan as any).planner_state?.branches ?? [], null, 2)}
              </pre>
            </ScrollArea>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

export default PlannerTracePanel
