import { NextRequest, NextResponse } from 'next/server'

import { forwardAuthHeaders, resolveOrchestratorBaseUrl } from '@/lib/server/downstream'
import { isRequestAuthenticated } from '@/lib/server/request-auth'
export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

type OrchestratorStep = { id?: string; name?: string; status?: string; progress?: number }

type MilestoneEvent = {
  analysis_id: string
  stage:
    | 'data_check'
    | 'preprocess'
    | 'model'
    | 'stats'
    | 'report'
    | 'complete'
    | 'error'
    | 'unknown'
  status: string
  percent?: number
  step?: { index?: number; id?: string; name?: string }
}

const formatSse = (event: string, data: unknown) =>
  `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`

function normalizeStatus(value: unknown): string {
  if (typeof value !== 'string') return 'unknown'
  const normalized = value.trim().toLowerCase()
  if (normalized === 'claimed') return 'running'
  if (normalized === 'succeeded') return 'completed'
  if (normalized === 'skipped') return 'cancelled'
  return normalized
}

function clampPercent(value: unknown): number | undefined {
  if (typeof value !== 'number' || !Number.isFinite(value)) return undefined
  return Math.max(0, Math.min(100, value))
}

function classifyStage(stepNameRaw: unknown, status: unknown): MilestoneEvent['stage'] {
  const normalizedStatus = normalizeStatus(status)
  if (normalizedStatus === 'completed') return 'complete'
  if (
    normalizedStatus === 'failed' ||
    normalizedStatus === 'cancelled' ||
    normalizedStatus === 'timeout'
  ) {
    return 'error'
  }

  const name = typeof stepNameRaw === 'string' ? stepNameRaw.toLowerCase() : ''
  if (!name) return 'unknown'

  if (
    name.includes('validate') ||
    name.includes('check') ||
    name.includes('qc') ||
    name.includes('sanity') ||
    name.includes('ingest') ||
    name.includes('load') ||
    name.includes('download')
  ) {
    return 'data_check'
  }

  if (
    name.includes('preprocess') ||
    name.includes('fmriprep') ||
    name.includes('qsiprep') ||
    name.includes('normalize') ||
    name.includes('registration') ||
    name.includes('recon') ||
    name.includes('skull') ||
    name.includes('motion')
  ) {
    return 'preprocess'
  }

  if (
    name.includes('glm') ||
    name.includes('model') ||
    name.includes('fit') ||
    name.includes('regress') ||
    name.includes('train') ||
    name.includes('decode') ||
    name.includes('classif') ||
    name.includes('encoding')
  ) {
    return 'model'
  }

  if (
    name.includes('stats') ||
    name.includes('threshold') ||
    name.includes('cluster') ||
    name.includes('fdr') ||
    name.includes('fwe') ||
    name.includes('permutation')
  ) {
    return 'stats'
  }

  if (
    name.includes('report') ||
    name.includes('export') ||
    name.includes('render') ||
    name.includes('figure') ||
    name.includes('runcard') ||
    name.includes('package') ||
    name.includes('artifact')
  ) {
    return 'report'
  }

  return 'unknown'
}

function coerceSteps(raw: unknown): OrchestratorStep[] {
  if (!raw) return []
  if (Array.isArray(raw)) return raw as OrchestratorStep[]
  if (typeof raw === 'object') {
    const obj = raw as any
    if (Array.isArray(obj.steps)) return obj.steps as OrchestratorStep[]
  }
  return []
}

function coerceArtifacts(raw: unknown): any[] {
  if (!raw) return []
  if (Array.isArray(raw)) return raw
  if (typeof raw === 'object') {
    const obj = raw as any
    if (Array.isArray(obj.artifacts)) return obj.artifacts
  }
  return []
}

function parseSseChunk(chunk: string): { event: string; data: string } | null {
  const lines = chunk.split('\n')
  let event = 'message'
  const dataParts: string[] = []
  for (const line of lines) {
    if (!line) continue
    if (line.startsWith(':')) continue
    if (line.startsWith('event:')) {
      event = line.slice('event:'.length).trim() || 'message'
      continue
    }
    if (line.startsWith('data:')) {
      dataParts.push(line.slice('data:'.length).trimStart())
    }
  }
  if (!dataParts.length) return null
  return { event, data: dataParts.join('\n') }
}

export async function GET(
  req: NextRequest,
  { params }: { params: { analysisId: string } },
) {
  const analysisId = params.analysisId
  if (!analysisId) {
    return NextResponse.json({ detail: 'analysisId is required.' }, { status: 400 })
  }

  const authed = await isRequestAuthenticated(req)
  if (!authed) {
    return NextResponse.json({ error: 'E-UNAUTHORIZED', detail: 'Authentication required.' }, { status: 401 })
  }

  return streamAnalysisProgress(req, analysisId)
}

export async function streamAnalysisProgress(req: NextRequest, analysisId: string) {
  const headers = forwardAuthHeaders(req)
  const orchBase = resolveOrchestratorBaseUrl()
  const upstreamUrl = `${orchBase}/api/jobs/${encodeURIComponent(analysisId)}/stream`
  const jobUrl = `${orchBase}/api/jobs/${encodeURIComponent(analysisId)}`
  const progressUrl = `${orchBase}/api/jobs/${encodeURIComponent(analysisId)}/progress`
  const artifactsUrl = `${orchBase}/api/jobs/${encodeURIComponent(analysisId)}/artifacts`

  const encoder = new TextEncoder()
  const decoder = new TextDecoder()

  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      const abortController = new AbortController()
      const abort = () => abortController.abort()
      req.signal.addEventListener('abort', abort)

      const emit = (event: string, data: unknown) => {
        controller.enqueue(encoder.encode(formatSse(event, data)))
      }

      try {
        const runPollingFallback = async () => {
          const terminalStatuses = new Set([
            'completed',
            'failed',
            'cancelled',
            'timeout',
            'skipped',
            'review_blocked',
          ])

          const seenArtifacts = new Set<string>()
          let lastArtifactsCheck = 0
          let steps: OrchestratorStep[] = []
          let lastStage: MilestoneEvent['stage'] | null = null

          const seedArtifacts = async () => {
            try {
              const res = await fetch(artifactsUrl, {
                method: 'GET',
                headers,
                cache: 'no-store',
                signal: abortController.signal,
              })
              if (!res.ok) return
              const parsed = (await res.json().catch(() => null)) as unknown
              const artifacts = coerceArtifacts(parsed)
              for (const artifact of artifacts) {
                const id =
                  artifact && typeof artifact === 'object'
                    ? artifact.id || artifact.artifact_id || artifact.name || artifact.file_name
                    : null
                const key = id != null ? String(id) : ''
                if (!key) continue
                seenArtifacts.add(key)
              }
            } catch {
              // ignore
            }
          }

          const maybeEmitNewArtifacts = async () => {
            const now = Date.now()
            if (now - lastArtifactsCheck < 10_000) return
            lastArtifactsCheck = now

            try {
              const res = await fetch(artifactsUrl, {
                method: 'GET',
                headers,
                cache: 'no-store',
                signal: abortController.signal,
              })
              if (!res.ok) return
              const parsed = (await res.json().catch(() => null)) as unknown
              const artifacts = coerceArtifacts(parsed)
              for (const artifact of artifacts) {
                const id =
                  artifact && typeof artifact === 'object'
                    ? artifact.id || artifact.artifact_id || artifact.name || artifact.file_name
                    : null
                const key = id != null ? String(id) : ''
                if (!key) continue
                if (seenArtifacts.has(key)) continue
                seenArtifacts.add(key)
                emit('artifact_created', { analysis_id: analysisId, artifact })
              }
            } catch {
              // ignore
            }
          }

          // Best-effort initial_state (so clients can render step list)
          try {
            const jobRes = await fetch(jobUrl, {
              method: 'GET',
              headers,
              cache: 'no-store',
              signal: abortController.signal,
            })
            if (jobRes.ok) {
              const job = await jobRes.json().catch(() => null)
              steps = coerceSteps(job?.steps)
              emit('initial_state', job)
            }
          } catch {
            // ignore
          }

          await seedArtifacts()

          while (!abortController.signal.aborted) {
            const res = await fetch(progressUrl, {
              method: 'GET',
              headers,
              cache: 'no-store',
              signal: abortController.signal,
            })
            if (!res.ok) {
              const text = await res.text().catch(() => '')
              emit('error', {
                error: 'upstream_error',
                status: res.status,
                detail: text || res.statusText,
              })
              return
            }

            const progress = await res.json().catch(() => null)
            emit('progress_update', progress)

            const status = normalizeStatus((progress as any)?.status)
            const percent = clampPercent((progress as any)?.overall_progress ?? (progress as any)?.progress)
            const currentStepIdx =
              typeof (progress as any)?.current_step === 'number' ? (progress as any).current_step : undefined

            const currentStep = typeof currentStepIdx === 'number' ? steps[currentStepIdx] : undefined
            const stepName =
              currentStep?.name ||
              (Array.isArray((progress as any)?.step_progress)
                ? (progress as any).step_progress.find((s: any) => normalizeStatus(s?.status) === 'running')?.name
                : undefined)

            const stage = classifyStage(stepName, status)
            const milestone: MilestoneEvent = {
              analysis_id: analysisId,
              stage,
              status,
              percent,
              step: {
                index: currentStepIdx,
                id: currentStep?.id,
                name: stepName,
              },
            }

            if (stage !== lastStage) {
              lastStage = stage
              emit('milestone', milestone)
            }

            void maybeEmitNewArtifacts()

            if (terminalStatuses.has(status)) {
              emit('job_complete', progress)
              await maybeEmitNewArtifacts()
              return
            }

            await new Promise((resolve) => setTimeout(resolve, 2000))
          }
        }

        const upstreamHeaders = new Headers(headers)
        upstreamHeaders.set('accept', 'text/event-stream')

        const upstream = await fetch(upstreamUrl, {
          method: 'GET',
          headers: upstreamHeaders,
          cache: 'no-store',
          signal: abortController.signal,
        })

        if (!upstream.ok || !upstream.body) {
          // Fall back to polling when streaming isn't available (older deployments).
          await runPollingFallback()
          return
        }

        let steps: OrchestratorStep[] = []
        let lastStage: MilestoneEvent['stage'] | null = null
        const seenArtifacts = new Set<string>()
        let lastArtifactsCheck = 0

        const seedArtifacts = async () => {
          try {
            const res = await fetch(artifactsUrl, {
              method: 'GET',
              headers,
              cache: 'no-store',
              signal: abortController.signal,
            })
            if (!res.ok) return
            const parsed = (await res.json().catch(() => null)) as unknown
            const artifacts = coerceArtifacts(parsed)
            for (const artifact of artifacts) {
              const id =
                artifact && typeof artifact === 'object'
                  ? artifact.id || artifact.artifact_id || artifact.name || artifact.file_name
                  : null
              const key = id != null ? String(id) : ''
              if (!key) continue
              seenArtifacts.add(key)
            }
          } catch {
            // ignore
          }
        }

        const maybeEmitNewArtifacts = async () => {
          const now = Date.now()
          if (now - lastArtifactsCheck < 10_000) return
          lastArtifactsCheck = now

          try {
            const res = await fetch(artifactsUrl, {
              method: 'GET',
              headers,
              cache: 'no-store',
              signal: abortController.signal,
            })
            if (!res.ok) return
            const parsed = (await res.json().catch(() => null)) as unknown
            const artifacts = coerceArtifacts(parsed)
            for (const artifact of artifacts) {
              const id =
                artifact && typeof artifact === 'object'
                  ? artifact.id || artifact.artifact_id || artifact.name || artifact.file_name
                  : null
              const key = id != null ? String(id) : ''
              if (!key) continue
              if (seenArtifacts.has(key)) continue
              seenArtifacts.add(key)
              emit('artifact_created', { analysis_id: analysisId, artifact })
            }
          } catch {
            // ignore
          }
        }

        const reader = upstream.body.getReader()
        let buffer = ''

        while (!abortController.signal.aborted) {
          const { value, done } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          buffer = buffer.replace(/\r\n/g, '\n')

          let idx: number
          while ((idx = buffer.indexOf('\n\n')) !== -1) {
            const raw = buffer.slice(0, idx).trim()
            buffer = buffer.slice(idx + 2)
            if (!raw) continue

            const parsed = parseSseChunk(raw)
            if (!parsed) continue

            if (parsed.event === 'initial_state') {
              let job: any = null
              try {
                job = parsed.data ? JSON.parse(parsed.data) : null
              } catch {
                emit('error', { error: 'upstream_parse_error', detail: 'Failed to parse initial_state.' })
                return
              }
              steps = coerceSteps(job?.steps)
              emit('initial_state', job)
              await seedArtifacts()
              continue
            }

            if (parsed.event === 'progress_update' || parsed.event === 'job_complete') {
              let progress: any = null
              try {
                progress = parsed.data ? JSON.parse(parsed.data) : null
              } catch {
                emit('error', { error: 'upstream_parse_error', detail: `Failed to parse ${parsed.event}.` })
                return
              }

              emit(parsed.event, progress)

              const status = normalizeStatus(progress?.status)
              const percent = clampPercent(progress?.overall_progress ?? progress?.progress)
              const currentStepIdx =
                typeof progress?.current_step === 'number' ? progress.current_step : undefined

              const currentStep = typeof currentStepIdx === 'number' ? steps[currentStepIdx] : undefined
              const stepName =
                currentStep?.name ||
                (Array.isArray(progress?.step_progress)
                  ? progress.step_progress.find((s: any) => normalizeStatus(s?.status) === 'running')?.name
                  : undefined)

              const stage = classifyStage(stepName, status)
              const milestone: MilestoneEvent = {
                analysis_id: analysisId,
                stage,
                status,
                percent,
                step: {
                  index: currentStepIdx,
                  id: currentStep?.id,
                  name: stepName,
                },
              }

              if (parsed.event === 'job_complete' || stage !== lastStage) {
                lastStage = stage
                emit('milestone', milestone)
              }

              void maybeEmitNewArtifacts()

              if (parsed.event === 'job_complete') {
                await maybeEmitNewArtifacts()
                return
              }

              continue
            }

            if (parsed.event === 'error') {
              emit('error', { error: 'upstream_stream_error', detail: parsed.data })
              return
            }
          }
        }
      } catch (err) {
        if (!req.signal.aborted) {
          emit('error', { error: 'stream_failed', detail: String(err) })
        }
      } finally {
        req.signal.removeEventListener('abort', abort)
        controller.close()
      }
    },
    cancel() {
      // Client disconnected.
    },
  })

  return new Response(stream, {
    status: 200,
    headers: {
      'content-type': 'text/event-stream; charset=utf-8',
      'cache-control': 'no-cache, no-transform',
      connection: 'keep-alive',
      'x-accel-buffering': 'no',
    },
  })
}
