'use client'

import Link from 'next/link'
import * as React from 'react'
import { useSearchParams } from 'next/navigation'

import { ProtectedRoute } from '@/components/auth/protected-route'
import { NavigationWrapper } from '@/components/navigation/navigation-wrapper'
import { RunsSidebar } from '@/components/workspace/RunsSidebar'
import {
  buildHubWorkspaceHandoff,
  createOrAttachHubSession,
  getHubSession,
  isRetryableHubGatewayError,
  type HubSessionEnvelope,
  type HubWorkspaceHandoff,
} from '@/lib/api/hub-sessions'
import { useAuth } from '@/hooks/use-auth'

import {
  buildHubRuntimeTargetUrl,
  handoffAllowsDirectRuntimeOpen,
  handoffNeedsRuntimePolling,
  parseHubLaunchRequest,
} from './hub-workspace-state'

const HUB_POLL_INTERVAL_MS = 2000

// Auto-retry budget for the INITIAL hub launch only. The Recreate-strategy
// orchestrator redeploy window is 30-60s, so the backoff schedule below must
// sum to comfortably more than the worst case: initial attempt + 6 retries with
// delays [2,4,8,10,10,10]s == ~44s of waiting (plus request time), so total
// elapsed reliably exceeds ~60s before we surface the terminal error.
const HUB_LAUNCH_MAX_RETRIES = 6
const HUB_LAUNCH_BACKOFF_MS = [2000, 4000, 8000, 10000, 10000, 10000]

function getHubLaunchBackoffMs(attempt: number): number {
  const idx = Math.min(attempt, HUB_LAUNCH_BACKOFF_MS.length - 1)
  return HUB_LAUNCH_BACKOFF_MS[idx]
}

function getErrorMessage(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback
}

function isMissingHubSessionError(err: unknown): boolean {
  return getErrorMessage(err, '').includes('Hub session not found')
}

function replaceHubWorkspaceUrl(nextUrl: string): void {
  if (typeof window === 'undefined') {
    return
  }

  try {
    const url = new URL(nextUrl, window.location.origin)
    const sameOriginPath =
      url.origin === window.location.origin
        ? `${url.pathname}${url.search}${url.hash}`
        : url.toString()
    window.history.replaceState({}, '', sameOriginPath)
  } catch {
    window.history.replaceState({}, '', nextUrl)
  }
}

function HubWorkspaceInner() {
  const searchParams = useSearchParams()
  const { accessToken, isLoading: authLoading } = useAuth()
  const [envelope, setEnvelope] = React.useState<HubSessionEnvelope | null>(null)
  const [handoff, setHandoff] = React.useState<HubWorkspaceHandoff | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  // Auto-retry attempt counter for the initial launch (0 = first attempt / not
  // retrying). Drives the transient reassuring copy on the loading card.
  const [retryAttempt, setRetryAttempt] = React.useState(0)

  const launchState = React.useMemo(
    () => parseHubLaunchRequest(new URLSearchParams(searchParams.toString())),
    [searchParams],
  )

  React.useEffect(() => {
    if (authLoading) {
      return
    }

    let cancelled = false

    // One launch attempt. Resolves on success (incl. the existing missing-session
    // recovery), or throws on failure so the loop can decide whether to retry.
    async function attemptLaunch(): Promise<void> {
      if (launchState.sessionId) {
        let sessionEnvelope: HubSessionEnvelope
        let nextHandoff: HubWorkspaceHandoff
        try {
          ;[sessionEnvelope, nextHandoff] = await Promise.all([
            getHubSession(launchState.sessionId, { accessToken }),
            buildHubWorkspaceHandoff(launchState.sessionId, launchState.handoffPayload, {
              accessToken,
            }),
          ])
        } catch (err) {
          if (!isMissingHubSessionError(err)) {
            throw err
          }

          const recovered = await createOrAttachHubSession(launchState.createPayload, {
            accessToken,
          })
          if (cancelled) {
            return
          }
          replaceHubWorkspaceUrl(recovered.handoff.workspace_url)
          setEnvelope(recovered)
          setHandoff(recovered.handoff)
          return
        }
        if (cancelled) {
          return
        }
        setEnvelope(sessionEnvelope)
        setHandoff(nextHandoff)
        return
      }

      const created = await createOrAttachHubSession(launchState.createPayload, { accessToken })
      if (cancelled) {
        return
      }
      setEnvelope(created)
      setHandoff(created.handoff)
    }

    async function loadWorkspace() {
      setLoading(true)
      setError(null)
      setRetryAttempt(0)
      try {
        for (let attempt = 0; ; attempt += 1) {
          try {
            await attemptLaunch()
            if (!cancelled) {
              setRetryAttempt(0)
            }
            return
          } catch (err) {
            // Only network blips (status 0) and 5xx are transient; a 4xx (auth,
            // validation, genuinely-missing) goes straight to the terminal card.
            // The 'Hub session not found' case is recovered inside attemptLaunch,
            // not here. Exhausting the retry budget also falls through to terminal.
            if (
              cancelled ||
              !isRetryableHubGatewayError(err) ||
              attempt >= HUB_LAUNCH_MAX_RETRIES
            ) {
              if (!cancelled) {
                setError(getErrorMessage(err, 'Failed to open hosted workspace'))
              }
              return
            }

            setRetryAttempt(attempt + 1)
            await new Promise((resolve) => setTimeout(resolve, getHubLaunchBackoffMs(attempt)))
            if (cancelled) {
              return
            }
            // continue the loop for the next attempt
          }
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    void loadWorkspace()
    return () => {
      cancelled = true
    }
  }, [accessToken, authLoading, launchState])

  React.useEffect(() => {
    const sessionId = envelope?.session.id
    if (!sessionId || !handoffNeedsRuntimePolling(handoff)) {
      return
    }

    let cancelled = false
    const intervalId = window.setInterval(() => {
      void getHubSession(sessionId, { accessToken })
        .then((nextEnvelope) => {
          if (cancelled) {
            return
          }
          setEnvelope(nextEnvelope)
          setHandoff(nextEnvelope.handoff)
        })
        .catch(() => {
          // Best-effort polling while the runtime target is still provisioning.
        })
    }, HUB_POLL_INTERVAL_MS)

    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [accessToken, envelope?.session.id, handoff?.runtime_target_ready])

  const activeHandoff = handoff || envelope?.handoff || null
  const targetUrl = activeHandoff?.runtime_target_url || null
  const targetUrlWithSession = buildHubRuntimeTargetUrl(targetUrl, envelope?.session.id)
  const canOpenRuntimeDirectly = handoffAllowsDirectRuntimeOpen(activeHandoff)
  const runtimeReady = activeHandoff?.runtime_target_ready || false
  const runtimeReason = activeHandoff?.runtime_target_reason || 'runtime_target_unavailable'
  const runtimeMode = activeHandoff?.runtime_connection_mode || 'pending'

  React.useEffect(() => {
    if (runtimeMode === 'redirect' && targetUrlWithSession) {
      window.location.replace(targetUrlWithSession)
    }
  }, [runtimeMode, targetUrlWithSession])

  // Client-side cell injection: the runtime iframe is same-origin with the hub,
  // so reach its live marimo session directly via window.__brAppendCell (exposed
  // by the marimo frontend patch). This appends through the browser's live
  // kernel, which the detached server-side POST cannot reliably target. Retries
  // briefly because the bridge appears shortly after the iframe loads. Throws on
  // give-up so RunsSidebar falls back to the server path.
  const iframeRef = React.useRef<HTMLIFrameElement | null>(null)
  const appendCellClient = React.useCallback(async (code: string) => {
    const delaysMs = [0, 250, 500, 1000, 1500, 2500]
    let lastError: unknown = new Error('runtime bridge unavailable')
    for (const delay of delaysMs) {
      if (delay) await new Promise((resolve) => setTimeout(resolve, delay))
      try {
        const win = iframeRef.current?.contentWindow as
          | (Window & { __brAppendCell?: (code: string) => unknown })
          | null
          | undefined
        const fn = win?.__brAppendCell
        if (typeof fn === 'function') {
          await fn(code)
          return
        }
        lastError = new Error('runtime bridge not ready')
      } catch (err) {
        // Cross-origin access or marimo throw — stop retrying, let caller fall back.
        throw err instanceof Error ? err : new Error(String(err))
      }
    }
    throw lastError instanceof Error ? lastError : new Error(String(lastError))
  }, [])

  // Iframe blank-frame watchdog. The pod readiness probe gates on marimo's
  // /health, but the editor SPA + kernel websocket can still be a beat behind,
  // and an embedded iframe that attaches in that window can render a permanently
  // blank frame (body empty, sessions: 0) with no built-in retry — while opening
  // the same runtime URL in a top-level tab a moment later works. Poll the
  // same-origin frame for signs of life and, if it stays blank past a grace
  // window, remount it (bounded), mirroring a manual reopen.
  const [iframeReloadKey, setIframeReloadKey] = React.useState(0)
  const iframeShown = Boolean(
    targetUrlWithSession && runtimeReady && runtimeMode === 'iframe',
  )
  React.useEffect(() => {
    if (!iframeShown) return
    const MAX_RELOADS = 3
    const GRACE_MS = 12000
    const POLL_MS = 1500
    let settled = false
    const frameAlive = (): boolean => {
      try {
        const win = iframeRef.current?.contentWindow as
          | (Window & { __brAppendCell?: unknown })
          | null
          | undefined
        if (win && typeof win.__brAppendCell === 'function') return true
        const doc = iframeRef.current?.contentDocument
        if (doc && doc.querySelector('[data-cell-id], .cm-editor')) return true
        return false
      } catch {
        // transient cross-origin/redirect state — treat as not-yet-alive
        return false
      }
    }
    const start = Date.now()
    const intervalId = window.setInterval(() => {
      if (settled) return
      if (frameAlive()) {
        settled = true
        window.clearInterval(intervalId)
        return
      }
      if (Date.now() - start >= GRACE_MS) {
        settled = true
        window.clearInterval(intervalId)
        if (iframeReloadKey < MAX_RELOADS) {
          setIframeReloadKey((key) => key + 1)
        }
      }
    }, POLL_MS)
    return () => {
      settled = true
      window.clearInterval(intervalId)
    }
  }, [iframeShown, iframeReloadKey, targetUrlWithSession])

  const handleRetry = React.useCallback(async () => {
    if (!envelope?.session.id) {
      return
    }
    setLoading(true)
    setError(null)
    try {
      const refreshedEnvelope = await getHubSession(envelope.session.id, { accessToken })
      setEnvelope(refreshedEnvelope)
      setHandoff(refreshedEnvelope.handoff)
      setRetryAttempt(0)
    } catch (err) {
      setError(getErrorMessage(err, 'Failed to refresh hosted workspace'))
    } finally {
      setLoading(false)
    }
  }, [accessToken, envelope?.session.id])

  return (
    <NavigationWrapper>
      <main className="min-h-[calc(100dvh-4rem)] bg-slate-950 text-slate-100">
        <div className="flex min-h-[calc(100dvh-4rem)] flex-col" data-tour="studio-runtime">
          <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
            <div className="space-y-1">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
                Hosted Marimo Workspace
              </div>
              <div className="text-sm text-slate-300">
                Session {envelope?.session.id ?? launchState.sessionId ?? 'provisioning'}
              </div>
            </div>
            <div className="flex items-center gap-3 text-sm">
              <RunsSidebar
                brSessionId={envelope?.session.id ?? null}
                runtimeReady={Boolean(runtimeReady)}
                appendCellClient={appendCellClient}
              />
              {targetUrlWithSession && canOpenRuntimeDirectly ? (
                <a
                  data-tour="studio-open-runtime"
                  className="rounded-full border border-slate-600 px-4 py-2 text-slate-100 transition hover:border-slate-300"
                  href={targetUrlWithSession}
                  rel="noreferrer"
                  target="_blank"
                  title="Open this runtime in a full browser tab."
                >
                  Open in new tab ↗
                </a>
              ) : targetUrlWithSession ? (
                <span
                  data-tour="studio-open-runtime"
                  className="rounded-full border border-slate-800 px-4 py-2 text-slate-500"
                >
                  Runtime starting…
                </span>
              ) : null}
              <Link
                className="rounded-full border border-slate-700 px-4 py-2 text-slate-300 transition hover:border-slate-400 hover:text-slate-100"
                href="/workspace"
              >
                Back to launcher
              </Link>
            </div>
          </div>

          {loading ? (
            <div className="flex flex-1 items-center justify-center px-6">
              <div className="max-w-xl rounded-3xl border border-slate-800 bg-slate-900/80 p-8 text-center shadow-2xl">
                {retryAttempt > 0 ? (
                  <>
                    <div className="text-lg font-semibold text-white">Starting your workspace</div>
                    <p className="mt-3 text-sm leading-6 text-slate-300">
                      Studio is starting up — reconnecting to the workspace gateway. This can take a
                      moment after a deploy… (attempt {retryAttempt} of {HUB_LAUNCH_MAX_RETRIES})
                    </p>
                  </>
                ) : (
                  <>
                    <div className="text-lg font-semibold text-white">Provisioning workspace</div>
                    <p className="mt-3 text-sm leading-6 text-slate-300">
                      Brain Researcher is creating or reattaching your hosted Marimo runtime and
                      waiting for the runtime target to become reachable.
                    </p>
                  </>
                )}
              </div>
            </div>
          ) : error ? (
            <div className="flex flex-1 items-center justify-center px-6">
              <div className="max-w-xl rounded-3xl border border-rose-800 bg-rose-950/40 p-8 text-center shadow-2xl">
                <div className="text-lg font-semibold text-rose-100">Workspace launch failed</div>
                <p className="mt-3 text-sm leading-6 text-rose-200">{error}</p>
                <button
                  className="mt-6 rounded-full border border-rose-500 px-4 py-2 text-sm font-medium text-rose-100 transition hover:border-rose-300"
                  onClick={() => void handleRetry()}
                  type="button"
                >
                  Retry
                </button>
              </div>
            </div>
          ) : targetUrlWithSession && runtimeReady && runtimeMode === 'iframe' ? (
            <iframe
              key={`hub-runtime-${iframeReloadKey}`}
              ref={iframeRef}
              className="h-[calc(100dvh-4rem-57px)] w-full flex-1 border-0 bg-white"
              src={targetUrlWithSession}
              title="Hosted Marimo workspace"
            />
          ) : (
            <div className="flex flex-1 items-center justify-center px-6">
              <div className="max-w-2xl rounded-3xl border border-slate-800 bg-slate-900/80 p-8 shadow-2xl">
                <div className="text-lg font-semibold text-white">Runtime target is not ready yet</div>
                <p className="mt-3 text-sm leading-6 text-slate-300">
                  The hosted /hub control plane is up, but the Marimo runtime target is still
                  provisioning or requires an external gateway URL. Current status: {runtimeReason}.
                </p>
                <dl className="mt-6 grid gap-3 text-sm text-slate-300 md:grid-cols-2">
                  <div>
                    <dt className="text-slate-500">Launch mode</dt>
                    <dd>{activeHandoff?.launch_mode ?? 'unknown'}</dd>
                  </div>
                  <div>
                    <dt className="text-slate-500">Connection mode</dt>
                    <dd>{runtimeMode}</dd>
                  </div>
                  <div>
                    <dt className="text-slate-500">Session ID</dt>
                    <dd>{envelope?.session.id ?? 'n/a'}</dd>
                  </div>
                  <div>
                    <dt className="text-slate-500">Runtime session</dt>
                    <dd>{envelope?.runtime.id ?? 'n/a'}</dd>
                  </div>
                </dl>
                <div className="mt-6 flex flex-wrap gap-3">
                  <button
                    className="rounded-full border border-slate-600 px-4 py-2 text-sm font-medium text-slate-100 transition hover:border-slate-300"
                    onClick={() => void handleRetry()}
                    type="button"
                  >
                    Refresh runtime target
                  </button>
                  {canOpenRuntimeDirectly && targetUrlWithSession ? (
                    <a
                      className="rounded-full border border-slate-700 px-4 py-2 text-sm font-medium text-slate-300 transition hover:border-slate-400 hover:text-slate-100"
                      href={targetUrlWithSession}
                      rel="noreferrer"
                      target="_blank"
                    >
                      Open target directly
                    </a>
                  ) : null}
                </div>
              </div>
            </div>
          )}
        </div>
      </main>
    </NavigationWrapper>
  )
}

export function HubWorkspacePage() {
  return (
    <ProtectedRoute>
      <HubWorkspaceInner />
    </ProtectedRoute>
  )
}
