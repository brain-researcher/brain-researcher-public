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

  const launchState = React.useMemo(
    () => parseHubLaunchRequest(new URLSearchParams(searchParams.toString())),
    [searchParams],
  )

  React.useEffect(() => {
    if (authLoading) {
      return
    }

    let cancelled = false

    async function loadWorkspace() {
      setLoading(true)
      setError(null)
      try {
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
      } catch (err) {
        if (!cancelled) {
          setError(getErrorMessage(err, 'Failed to open hosted workspace'))
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
    } catch (err) {
      setError(getErrorMessage(err, 'Failed to refresh hosted workspace'))
    } finally {
      setLoading(false)
    }
  }, [accessToken, envelope?.session.id])

  return (
    <NavigationWrapper>
      <main className="min-h-[calc(100dvh-4rem)] bg-slate-950 text-slate-100">
        <div className="flex min-h-[calc(100dvh-4rem)] flex-col">
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
              />
              {targetUrlWithSession && canOpenRuntimeDirectly ? (
                <a
                  className="rounded-full border border-slate-600 px-4 py-2 text-slate-100 transition hover:border-slate-300"
                  href={targetUrlWithSession}
                  rel="noreferrer"
                  target="_blank"
                >
                  Open runtime
                </a>
              ) : targetUrlWithSession ? (
                <span className="rounded-full border border-slate-800 px-4 py-2 text-slate-500">
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
                <div className="text-lg font-semibold text-white">Provisioning workspace</div>
                <p className="mt-3 text-sm leading-6 text-slate-300">
                  Brain Researcher is creating or reattaching your hosted Marimo runtime and
                  waiting for the runtime target to become reachable.
                </p>
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
