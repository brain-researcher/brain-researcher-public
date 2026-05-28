import { NextRequest, NextResponse } from 'next/server'

import {
  getRunEventsSincePersisted,
  getRunSnapshotPersisted,
  getStoredRunStatePersisted,
} from '@/lib/server/hypothesis-run-store'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

function toSseChunk(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
}

function parseCursor(value: string | null): number {
  if (!value) return 0
  const parsed = Number(value)
  if (!Number.isFinite(parsed) || parsed < 0) return 0
  return Math.trunc(parsed)
}

export async function GET(
  req: NextRequest,
  context: { params: { runId: string } },
) {
  const runId = context.params.runId?.trim()
  if (!runId) {
    return NextResponse.json(
      { error: 'missing_run_id', message: 'runId is required.' },
      { status: 400 },
    )
  }

  const snapshot = await getRunSnapshotPersisted(runId)
  if (!snapshot) {
    return NextResponse.json(
      { error: 'run_not_found', message: `Run ${runId} was not found.` },
      { status: 404 },
    )
  }

  const from = parseCursor(req.nextUrl.searchParams.get('from'))
  const encoder = new TextEncoder()
  let closed = false
  let intervalId: ReturnType<typeof setInterval> | null = null
  let pingId: ReturnType<typeof setInterval> | null = null
  let controllerRef: ReadableStreamDefaultController<Uint8Array> | null = null

  const cleanup = () => {
    if (closed) return
    closed = true
    if (intervalId) clearInterval(intervalId)
    if (pingId) clearInterval(pingId)
    intervalId = null
    pingId = null

    if (controllerRef) {
      try {
        controllerRef.close()
      } catch {
        // Stream may already be closed by the runtime.
      }
    }
  }

  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controllerRef = controller
      let cursor = from

      const emit = (event: string, data: unknown) => {
        if (closed) return
        controller.enqueue(encoder.encode(toSseChunk(event, data)))
      }

      emit('snapshot', {
        run_id: snapshot.run_id,
        state: snapshot.state,
        seq: cursor,
        ts: snapshot.updated_at,
      })

      let ticking = false
      const tick = async () => {
        if (closed || ticking) return
        ticking = true
        try {
          const state = await getStoredRunStatePersisted(runId)
          if (!state) {
            emit('error', {
              type: 'error',
              run_id: runId,
              seq: cursor,
              ts: new Date().toISOString(),
              payload: { message: 'Run state is no longer available.' },
            })
            cleanup()
            return
          }

          const events = await getRunEventsSincePersisted(runId, cursor)
          if (events.length) {
            for (const event of events) {
              emit(event.type, event)
              cursor = Math.max(cursor, event.seq)
            }
          }

          if (state.done && events.length === 0) {
            cleanup()
          }
        } finally {
          ticking = false
        }
      }

      intervalId = setInterval(() => {
        void tick()
      }, 250)
      pingId = setInterval(() => {
        emit('ping', { ts: new Date().toISOString(), run_id: runId })
      }, 10_000)

      void tick()
    },
    cancel() {
      cleanup()
    },
  })

  return new NextResponse(stream, {
    headers: {
      'content-type': 'text/event-stream',
      'cache-control': 'no-cache, no-transform',
      connection: 'keep-alive',
      'x-accel-buffering': 'no',
    },
  })
}
