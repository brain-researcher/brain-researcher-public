'use client'

import { useMemo } from 'react'
import { useSearchParams } from 'next/navigation'

import { useHypothesisSession } from '@/hooks/use-hypothesis-session'
import { HypothesisArtifactPanel } from '@/components/hypothesis/HypothesisArtifactPanel'
import { HypothesisChatBox } from '@/components/hypothesis/HypothesisChatBox'
import { SearchProgressFeed } from '@/components/hypothesis/SearchProgressFeed'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { useToast } from '@/hooks/use-toast'

export function HypothesisExplorerPage() {
  const searchParams = useSearchParams()
  const { toast } = useToast()

  const sessionId = searchParams.get('sessionId') || searchParams.get('session') || undefined
  const runId = searchParams.get('runId') || searchParams.get('run') || undefined
  const datasetId = searchParams.get('datasetId') || searchParams.get('dataset') || undefined
  const conceptId = searchParams.get('conceptId') || searchParams.get('concept') || undefined
  const taskId = searchParams.get('taskId') || searchParams.get('task') || undefined
  const threadId = searchParams.get('threadId') || searchParams.get('thread') || undefined

  const {
    session,
    messages,
    error,
    lastBatchRun,
    activeRunId,
    artifacts,
    progressFeed,
    currentStage,
    isLoadingSession,
    isSendingChat,
    isRunningBatch,
    isExploring,
    refreshSession,
    sendChat,
    runBatch,
  } = useHypothesisSession({
    sessionId,
    runId,
    datasetId,
    conceptId,
    taskId,
    threadId,
  })

  const runBatchCandidateIds = useMemo(() => {
    const sessionIds = (session?.candidates || []).map((candidate) => candidate.id)
    if (sessionIds.length) return sessionIds
    return artifacts.candidates.map((candidate) => candidate.id)
  }, [artifacts.candidates, session?.candidates])

  const artifactCandidates = useMemo(() => {
    const sessionCandidates = session?.candidates || []
    if (activeRunId && artifacts.candidates.length) {
      return artifacts.candidates
    }
    if (sessionCandidates.length) {
      return sessionCandidates.map((candidate) => ({
        id: candidate.id,
        title: candidate.title,
        summary: candidate.statement,
        source: 'session' as const,
      }))
    }
    if (artifacts.candidates.length) return artifacts.candidates
    return sessionCandidates.map((candidate) => ({
      id: candidate.id,
      title: candidate.title,
      summary: candidate.statement,
      source: 'session' as const,
    }))
  }, [activeRunId, artifacts.candidates, session?.candidates])

  const selectedEvidence = useMemo(() => {
    if (artifacts.evidence.length) return artifacts.evidence
    const selectedId = session?.selected_hypothesis_id
    const selected =
      (selectedId && session?.candidates.find((candidate) => candidate.id === selectedId)) ||
      session?.candidates?.[0] ||
      null
    return selected?.evidence || []
  }, [artifacts.evidence, session?.candidates, session?.selected_hypothesis_id])

  const defaultSelectedHypothesisId = useMemo(
    () => session?.candidates?.[0]?.id || artifactCandidates[0]?.id || null,
    [artifactCandidates, session?.candidates],
  )
  const evidenceStatus = artifacts.evidenceMeta?.deep_research_status || null
  const analysisReady = currentStage === 'completed'
  const evidencePending = evidenceStatus === 'pending'
  const evidenceReady = evidenceStatus === 'ready'
  const evidenceFailed = evidenceStatus === 'failed'
  const currentSessionId = session?.session_id || sessionId || null
  const currentRunId = activeRunId || runId || null
  const hasDeepResearchReport =
    Boolean(artifacts.evidenceMeta?.deep_research_report_available) ||
    Boolean(artifacts.deepResearchReport)
  const deepResearchReportHref =
    hasDeepResearchReport && currentSessionId && currentRunId
      ? `/hypothesis/report?sessionId=${encodeURIComponent(currentSessionId)}&runId=${encodeURIComponent(
          currentRunId,
        )}`
      : null

  const handleRunBatch = async () => {
    if (!runBatchCandidateIds.length) {
      toast({
        title: 'No hypotheses available',
        description: 'Start from chat and let the run generate candidate hypotheses first.',
      })
      return
    }

    try {
      const run = await runBatch({ hypothesisIds: runBatchCandidateIds })
      toast({
        title: 'Batch started',
        description: run.run_id ? `Run ${run.run_id} started.` : 'Batch submitted.',
      })
    } catch (err) {
      toast({
        title: 'Run Batch failed',
        description: err instanceof Error ? err.message : 'Unable to start batch run.',
        variant: 'destructive',
      })
    }
  }

  const handleSendChat = async (message: string) => {
    const trimmed = message.trim()
    if (!trimmed) return

    try {
      await sendChat({
        message: trimmed,
        selectedHypothesisId: defaultSelectedHypothesisId,
      })
    } catch (err) {
      toast({
        title: 'Chat failed',
        description: err instanceof Error ? err.message : 'Unable to send message.',
        variant: 'destructive',
      })
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">Hypothesis Explorer</h1>
            <p className="text-sm text-muted-foreground">
              Chat first. We clarify intent, run deep research, and stream progress plus artifacts.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {deepResearchReportHref ? (
              <Button type="button" variant="outline" asChild>
                <a href={deepResearchReportHref} target="_blank" rel="noreferrer">
                  Deep Research Report
                </a>
              </Button>
            ) : null}
            <Button
              type="button"
              variant="outline"
              onClick={() => void refreshSession()}
              disabled={isLoadingSession}
            >
              Refresh
            </Button>
            <Button
              type="button"
              onClick={() => void handleRunBatch()}
              disabled={isRunningBatch || !runBatchCandidateIds.length}
            >
              {isRunningBatch ? 'Running...' : 'Run Batch'}
            </Button>
          </div>
        </div>

        <div className="flex flex-wrap gap-2 text-xs">
          <Badge variant="outline">session: {session?.session_id || sessionId || 'n/a'}</Badge>
          {activeRunId ? <Badge variant="outline">run: {activeRunId}</Badge> : null}
          <Badge variant="outline">stage: {currentStage}</Badge>
          {analysisReady ? <Badge>Analysis ready</Badge> : null}
          {analysisReady && evidencePending ? <Badge variant="secondary">Evidence updating...</Badge> : null}
          {analysisReady && evidenceReady ? <Badge variant="outline">Evidence ready</Badge> : null}
          {analysisReady && evidenceFailed ? <Badge variant="destructive">Evidence failed</Badge> : null}
          <Badge variant="outline">hypotheses: {runBatchCandidateIds.length}</Badge>
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <SearchProgressFeed currentStage={currentStage} events={progressFeed} />
          <HypothesisArtifactPanel
            analysisReady={analysisReady}
            canvas={artifacts.canvas}
            preview={artifacts.preview}
            candidates={artifactCandidates}
            candidateSummary={artifacts.candidateSummary}
            candidateDiagnostics={artifacts.candidateDiagnostics}
            candidateTrace={artifacts.candidateTrace}
            evidence={selectedEvidence}
            evidenceMeta={artifacts.evidenceMeta}
            hotLoadTrajectory={artifacts.hotLoadTrajectory}
            sessionId={currentSessionId}
            runId={currentRunId}
            plan={artifacts.plan}
            validation={artifacts.validation}
            kgCompare={artifacts.kgCompare}
          />
        </div>

        {lastBatchRun ? (
          <Card className="border-border/70">
            <CardContent className="p-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div className="text-sm">
                Batch run <span className="font-medium">{lastBatchRun.run_id}</span> is{' '}
                <span className="font-medium">{lastBatchRun.status}</span>
              </div>
              {lastBatchRun.leaderboard_url ? (
                <a
                  href={lastBatchRun.leaderboard_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-xs text-blue-600 hover:underline"
                >
                  Open leaderboard
                </a>
              ) : null}
            </CardContent>
          </Card>
        ) : null}

        {error ? (
          <Card className="border-red-300 bg-red-50">
            <CardContent className="p-3 text-sm text-red-700">{error}</CardContent>
          </Card>
        ) : null}

        <HypothesisChatBox
          messages={messages}
          submitting={isSendingChat}
          disabled={!session?.session_id || isExploring}
          onSend={handleSendChat}
        />
      </div>
    </div>
  )
}
