'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { Copy } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useAuth } from '@/hooks/use-auth'
import { useToast } from '@/hooks/use-toast'
import {
  buildHostedMcpSnippet,
  buildMcpTokenExportCommand,
  DEFAULT_MCP_CLOUD_URL,
  MCP_TOKEN_PLACEHOLDER,
  type HostedMcpClient,
} from '@/lib/mcp-config-snippets'
import { buildLatestPlanContinuationPrompt } from '@/lib/mcp-plan-handoff'

const DEFAULT_MCP_LOCAL_COMMAND = 'npx -y @brain-researcher/mcp-server start'

type McpTokenMetadata = {
  kid: string
  user_id?: string
  enabled?: boolean
  created_at?: string | null
  last_used_at?: string | null
  revoked_at?: string | null
  expires_at?: string | null
  pepper_version?: string | null
  token_preview?: string | null
}

type TokenListResponse = {
  tokens?: McpTokenMetadata[]
  count?: number
  detail?: string
}

type TokenCreateResponse = {
  token?: string
  metadata?: McpTokenMetadata
  detail?: string
}

type TokenVerifyResponse = {
  backend?: string
  redis_available?: boolean
  pepper_configured?: boolean
  has_active_token?: boolean
  detail?: string
}

export type McpConfigurationPanelProps = {
  showManageInSettings?: boolean
  onManageInSettings?: () => void
  /** When true (setup page), label the token + config sections as numbered steps. */
  numbered?: boolean
  planId?: string | null
  threadId?: string | null
  workflowId?: string | null
  workflowLabel?: string | null
  datasetId?: string | null
  datasetVersion?: string | null
  continuationPrompt?: string | null
}

function StepHeader({
  step,
  numbered,
  title,
  subtitle,
}: {
  step: number
  numbered: boolean
  title: string
  subtitle?: string
}) {
  return (
    <div className="flex items-start gap-3">
      {numbered ? (
        <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gray-900 text-xs font-semibold text-white">
          {step}
        </span>
      ) : null}
      <div className="space-y-0.5">
        <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
        {subtitle ? <p className="text-xs text-muted-foreground">{subtitle}</p> : null}
      </div>
    </div>
  )
}

export function McpConfigurationPanel({
  showManageInSettings = false,
  onManageInSettings,
  numbered = false,
  planId,
  threadId,
  workflowId,
  workflowLabel,
  datasetId,
  datasetVersion,
  continuationPrompt,
}: McpConfigurationPanelProps) {
  const { isAuthenticated, isLoading: authLoading } = useAuth()
  const { toast } = useToast()
  const [isLoadingTokens, setIsLoadingTokens] = useState(false)
  const [isCreatingToken, setIsCreatingToken] = useState(false)
  const [isRevokingToken, setIsRevokingToken] = useState(false)
  const [tokens, setTokens] = useState<McpTokenMetadata[]>([])
  const [verifyStatus, setVerifyStatus] = useState<TokenVerifyResponse | null>(null)
  const [newToken, setNewToken] = useState<string | null>(null)
  const [cloudConfigTab, setCloudConfigTab] = useState<HostedMcpClient>('cursor')

  const mcpUrl = (process.env.NEXT_PUBLIC_MCP_CLOUD_URL || DEFAULT_MCP_CLOUD_URL).trim()
  const activeToken = tokens.find((token) => token.enabled && !token.revoked_at) ?? null

  const exportTokenCommand = useMemo(() => {
    return buildMcpTokenExportCommand(newToken || MCP_TOKEN_PLACEHOLDER)
  }, [newToken])

  const cloudSnippet = useMemo(
    () =>
      buildHostedMcpSnippet(cloudConfigTab, {
        directToken: newToken || MCP_TOKEN_PLACEHOLDER,
        url: mcpUrl,
      }),
    [cloudConfigTab, mcpUrl, newToken],
  )
  const normalizedPlanId = typeof planId === 'string' && planId.trim() ? planId.trim() : null
  const normalizedThreadId =
    typeof threadId === 'string' && threadId.trim() ? threadId.trim() : null
  const normalizedWorkflowId =
    typeof workflowId === 'string' && workflowId.trim() ? workflowId.trim() : null
  const normalizedWorkflowLabel =
    typeof workflowLabel === 'string' && workflowLabel.trim() ? workflowLabel.trim() : null
  const normalizedDatasetId =
    typeof datasetId === 'string' && datasetId.trim() ? datasetId.trim() : null
  const normalizedDatasetVersion =
    typeof datasetVersion === 'string' && datasetVersion.trim() ? datasetVersion.trim() : null
  const explicitContinuationPrompt =
    typeof continuationPrompt === 'string' && continuationPrompt.trim()
      ? continuationPrompt.trim()
      : null
  const continuationPromptText = useMemo(() => {
    if (explicitContinuationPrompt) return explicitContinuationPrompt
    return buildLatestPlanContinuationPrompt({
      planId: normalizedPlanId,
      threadId: normalizedThreadId,
      workflowId: normalizedWorkflowId,
      workflowLabel: normalizedWorkflowLabel,
      datasetId: normalizedDatasetId,
      datasetVersion: normalizedDatasetVersion,
    })
  }, [
    explicitContinuationPrompt,
    normalizedDatasetId,
    normalizedDatasetVersion,
    normalizedPlanId,
    normalizedThreadId,
    normalizedWorkflowId,
    normalizedWorkflowLabel,
  ])
  const hasPlanContext = Boolean(
    normalizedPlanId ||
      normalizedThreadId ||
      normalizedWorkflowId ||
      normalizedWorkflowLabel ||
      normalizedDatasetId,
  )
  const showContinuationPrompt = hasPlanContext || Boolean(explicitContinuationPrompt)
  const tokenManagementEnabled = isAuthenticated

  const copyToClipboard = async (label: string, value: string) => {
    try {
      await navigator.clipboard.writeText(value)
      toast({ title: `Copied ${label}` })
    } catch {
      toast({ title: `Failed to copy ${label}`, variant: 'destructive' })
    }
  }

  const formatTimestamp = (value?: string | null) => {
    if (!value) return '—'
    const parsed = new Date(value)
    if (Number.isNaN(parsed.getTime())) return value
    return parsed.toLocaleString()
  }

  const loadTokenState = useCallback(async () => {
    if (authLoading) {
      return
    }
    if (!tokenManagementEnabled) {
      setTokens([])
      setVerifyStatus(null)
      setNewToken(null)
      setIsLoadingTokens(false)
      return
    }
    setIsLoadingTokens(true)
    try {
      const [tokensRes, verifyRes] = await Promise.all([
        fetch('/api/mcp/tokens', { cache: 'no-store' }),
        fetch('/api/mcp/tokens/verify', { cache: 'no-store' }),
      ])

      const tokensPayload = (await tokensRes.json().catch(() => ({}))) as TokenListResponse
      if (tokensRes.status === 401 || tokensRes.status === 403) {
        setTokens([])
        setVerifyStatus(null)
        return
      }
      if (!tokensRes.ok) {
        throw new Error(tokensPayload.detail || `Failed to load tokens (${tokensRes.status})`)
      }

      const verifyPayload = (await verifyRes.json().catch(() => ({}))) as TokenVerifyResponse
      setTokens(Array.isArray(tokensPayload.tokens) ? tokensPayload.tokens : [])
      setVerifyStatus(verifyRes.ok ? verifyPayload : null)
    } catch (error) {
      setTokens([])
      setVerifyStatus(null)
      toast({
        title: 'Failed to load MCP tokens',
        description: error instanceof Error ? error.message : 'Please try again.',
        variant: 'destructive',
      })
    } finally {
      setIsLoadingTokens(false)
    }
  }, [authLoading, toast, tokenManagementEnabled])

  useEffect(() => {
    void loadTokenState()
  }, [loadTokenState])

  const handleCreateOrRotate = async () => {
    if (!tokenManagementEnabled) {
      toast({
        title: 'Sign in required',
        description: 'Sign in to generate or rotate MCP tokens.',
        variant: 'destructive',
      })
      return
    }
    setIsCreatingToken(true)
    try {
      const res = await fetch('/api/mcp/tokens', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({}),
      })
      const payload = (await res.json().catch(() => ({}))) as TokenCreateResponse
      if (!res.ok || !payload.token) {
        throw new Error(payload.detail || `Failed to create token (${res.status})`)
      }

      setNewToken(payload.token)
      toast({ title: activeToken ? 'MCP token rotated' : 'MCP token created' })
      await loadTokenState()
    } catch (error) {
      toast({
        title: 'Failed to create MCP token',
        description: error instanceof Error ? error.message : 'Please try again.',
        variant: 'destructive',
      })
    } finally {
      setIsCreatingToken(false)
    }
  }

  const handleRevoke = async () => {
    if (!tokenManagementEnabled) {
      toast({
        title: 'Sign in required',
        description: 'Sign in to revoke MCP tokens.',
        variant: 'destructive',
      })
      return
    }
    if (!activeToken?.kid) return
    const ok = window.confirm(`Revoke MCP token ${activeToken.kid}?`)
    if (!ok) return

    setIsRevokingToken(true)
    try {
      const res = await fetch(`/api/mcp/tokens/${encodeURIComponent(activeToken.kid)}`, {
        method: 'DELETE',
      })
      const payload = (await res.json().catch(() => ({}))) as { detail?: string }
      if (!res.ok) {
        throw new Error(payload.detail || `Failed to revoke token (${res.status})`)
      }
      setNewToken(null)
      toast({ title: 'MCP token revoked' })
      await loadTokenState()
    } catch (error) {
      toast({
        title: 'Failed to revoke MCP token',
        description: error instanceof Error ? error.message : 'Please try again.',
        variant: 'destructive',
      })
    } finally {
      setIsRevokingToken(false)
    }
  }

  return (
    <div className="space-y-4">
      {showContinuationPrompt ? (
        <div className="rounded-lg border p-4 space-y-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="space-y-1">
              <div className="text-xs font-medium text-muted-foreground">
                {hasPlanContext ? 'Continue from current Studio plan' : 'Continue in MCP'}
              </div>
              <div className="text-xs text-muted-foreground">
                Use this prompt in Codex, Cursor, or Claude Code after MCP is connected.
              </div>
            </div>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              className="shrink-0"
              onClick={() => void copyToClipboard('continuation prompt', continuationPromptText)}
            >
              <Copy className="mr-2 h-3 w-3" />
              Copy prompt
            </Button>
          </div>
          {hasPlanContext ? (
            <div className="grid gap-2 text-xs md:grid-cols-2">
              <div>
                <span className="text-muted-foreground">Plan ID:</span>{' '}
                <code className="font-mono">
                  {normalizedPlanId || 'resolve via get_latest_plan(thread_id)'}
                </code>
              </div>
              <div>
                <span className="text-muted-foreground">Thread:</span>{' '}
                <code className="font-mono">{normalizedThreadId || 'current thread'}</code>
              </div>
              {normalizedWorkflowLabel ? (
                <div>
                  <span className="text-muted-foreground">Workflow:</span>{' '}
                  <span>{normalizedWorkflowLabel}</span>
                </div>
              ) : null}
              {normalizedDatasetId ? (
                <div>
                  <span className="text-muted-foreground">Dataset:</span>{' '}
                  <code className="font-mono">
                    {normalizedDatasetId}
                    {normalizedDatasetVersion ? `:${normalizedDatasetVersion}` : ''}
                  </code>
                </div>
              ) : null}
            </div>
          ) : null}
          <div className="rounded border bg-muted/20 p-3 font-mono text-xs whitespace-pre-wrap break-words">
            {continuationPromptText}
          </div>
        </div>
      ) : null}

      <Tabs defaultValue="cloud">
        <TabsList className="w-full justify-start">
          <TabsTrigger value="cloud">Cloud (Recommended)</TabsTrigger>
          <TabsTrigger value="local">Local (Advanced)</TabsTrigger>
        </TabsList>

        <TabsContent value="cloud" className="mt-4 space-y-4">
          {/* Step 1 — generate the token (must come before the config that uses it) */}
          <div className="space-y-3">
            <StepHeader
              step={1}
              numbered={numbered}
              title="Generate your personal token"
              subtitle="One active token per user. Generating a new one rotates the previous immediately — the full secret is shown only once, so copy it now."
            />
            <div className="rounded-lg border p-3 space-y-3" data-tour="mcp-token-panel">
              <div className="flex flex-wrap items-center justify-end gap-2 sm:justify-start">
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  onClick={() => void loadTokenState()}
                  disabled={isLoadingTokens || !tokenManagementEnabled}
                >
                  Refresh
                </Button>
                <Button
                  type="button"
                  size="sm"
                  onClick={() => void handleCreateOrRotate()}
                  disabled={isCreatingToken || !tokenManagementEnabled}
                >
                  {activeToken ? 'Rotate token' : 'Generate token'}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => void handleRevoke()}
                  disabled={!activeToken || isRevokingToken || !tokenManagementEnabled}
                >
                  Revoke
                </Button>
              </div>

              {newToken ? (
                <div className="rounded border bg-muted/20 p-3 space-y-2">
                  <div className="text-xs font-medium text-muted-foreground">
                    New token (shown once)
                  </div>
                  <div className="font-mono text-xs break-all">{newToken}</div>
                  <div className="flex justify-end">
                    <Button
                      type="button"
                      size="sm"
                      variant="secondary"
                      onClick={() => void copyToClipboard('MCP token', newToken)}
                    >
                      <Copy className="mr-2 h-3 w-3" />
                      Copy token
                    </Button>
                  </div>
                </div>
              ) : null}

              {!newToken ? (
                <div className="rounded border bg-muted/20 p-2 text-xs text-muted-foreground">
                  {authLoading
                    ? 'Checking sign-in status for MCP token management…'
                    : tokenManagementEnabled
                      ? 'Click Generate to mint a token — it is filled into the config and shell export in step 2. The full secret is only shown once.'
                      : 'Sign in to manage personal MCP tokens. The step 2 instructions still work with an existing token.'}
                </div>
              ) : null}

              {activeToken ? (
                <div className="grid gap-2 text-xs md:grid-cols-2">
                  <div>
                    <span className="text-muted-foreground">Active key id:</span>{' '}
                    <code className="font-mono">{activeToken.kid}</code>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Created:</span>{' '}
                    <span>{formatTimestamp(activeToken.created_at)}</span>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Last used:</span>{' '}
                    <span>{formatTimestamp(activeToken.last_used_at)}</span>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Expires:</span>{' '}
                    <span>{formatTimestamp(activeToken.expires_at)}</span>
                  </div>
                </div>
              ) : (
                <div className="text-xs text-muted-foreground">
                  {tokenManagementEnabled
                    ? 'No active token yet. Generate one to connect IDE MCP clients.'
                    : 'Sign in to view or manage MCP tokens.'}
                </div>
              )}

              {verifyStatus ? (
                <div className="rounded border bg-muted/20 p-2 text-xs text-muted-foreground">
                  Backend: {verifyStatus.backend || 'unknown'} · Redis:{' '}
                  {verifyStatus.redis_available ? 'connected' : 'unavailable'} · Pepper:{' '}
                  {verifyStatus.pepper_configured ? 'configured' : 'missing'}
                </div>
              ) : null}
            </div>
          </div>

          {/* Step 2 — drop the config (with the step-1 token) into your agent */}
          <div className="space-y-3">
            <StepHeader
              step={2}
              numbered={numbered}
              title="Add Brain Researcher to your coding agent"
              subtitle="Pick your client, then paste this into its MCP configuration. Your step-1 token is already filled in."
            />

            <div className="rounded-lg border bg-muted/20 p-4" data-tour="mcp-config-snippet">
              <div className="mb-3 flex flex-wrap gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant={cloudConfigTab === 'cursor' ? 'default' : 'secondary'}
                  aria-pressed={cloudConfigTab === 'cursor'}
                  onClick={() => setCloudConfigTab('cursor')}
                >
                  Cursor
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant={cloudConfigTab === 'codex' ? 'default' : 'secondary'}
                  aria-pressed={cloudConfigTab === 'codex'}
                  onClick={() => setCloudConfigTab('codex')}
                >
                  Codex
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant={cloudConfigTab === 'claude' ? 'default' : 'secondary'}
                  aria-pressed={cloudConfigTab === 'claude'}
                  onClick={() => setCloudConfigTab('claude')}
                >
                  Claude Code
                </Button>
              </div>
              <div className="flex items-center justify-between gap-3">
                <div className="text-xs text-muted-foreground">{cloudSnippet.fileName}</div>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  className="shrink-0"
                  onClick={() => void copyToClipboard(cloudSnippet.copyLabel, cloudSnippet.snippet)}
                >
                  <Copy className="mr-2 h-3 w-3" />
                  {cloudSnippet.copyButtonLabel}
                </Button>
              </div>
              <pre className="mt-3 text-xs overflow-x-auto whitespace-pre-wrap">{cloudSnippet.snippet}</pre>
            </div>

            <div className="rounded-lg border p-3 text-sm space-y-2">
              <div className="text-xs font-medium text-muted-foreground">
                Shell environment (Codex &amp; Claude Code)
              </div>
              <div className="rounded border bg-muted/20 p-2 font-mono text-xs break-all">
                {exportTokenCommand}
              </div>
              <div className="text-xs text-muted-foreground">
                Keep <code className="font-mono">BR_MCP_TOKEN</code> as the raw{' '}
                <code className="font-mono">brk_&lt;kid&gt;.&lt;secret&gt;</code> token — no{' '}
                <code className="font-mono">Bearer </code> prefix. Cursor and Windsurf paste the
                full token directly into the JSON instead.
              </div>
            </div>

            <details className="rounded-lg border p-3 text-xs text-muted-foreground">
              <summary className="cursor-pointer font-medium text-gray-900">
                Client-specific notes
              </summary>
              <div className="mt-2 space-y-1">
                <div>
                  Cursor and Windsurf work best with the full token pasted directly into the JSON
                  config.
                </div>
                <div>
                  Codex uses <code className="font-mono">~/.codex/config.toml</code> with{' '}
                  <code className="font-mono">BR_MCP_TOKEN</code> in the shell and the{' '}
                  <code className="font-mono">Accept</code> header under{' '}
                  <code className="font-mono">[http_headers]</code>.
                </div>
                <div>
                  Claude Code keeps{' '}
                  <code className="font-mono">Authorization: Bearer ${'{'}BR_MCP_TOKEN{'}'}</code> in
                  the hosted HTTP JSON config.
                </div>
              </div>
            </details>
          </div>

          {showManageInSettings && onManageInSettings ? (
            <div className="flex justify-end">
              <Button type="button" size="sm" variant="ghost" onClick={onManageInSettings}>
                Manage in Settings
              </Button>
            </div>
          ) : null}

          <div className="text-xs text-muted-foreground">
            <Link href="/docs" className="underline">
              View docs →
            </Link>
          </div>
        </TabsContent>

        <TabsContent value="local" className="mt-4 space-y-4">
          <div className="text-sm text-muted-foreground">
            For local data processing or air-gapped environments:
          </div>

          <div className="rounded-lg border bg-muted/20 p-4">
            <div className="flex items-start justify-between gap-3">
              <pre className="text-xs overflow-x-auto whitespace-pre-wrap">{DEFAULT_MCP_LOCAL_COMMAND}</pre>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                className="shrink-0"
                onClick={() => void copyToClipboard('command', DEFAULT_MCP_LOCAL_COMMAND)}
              >
                <Copy className="mr-2 h-3 w-3" />
                Copy command
              </Button>
            </div>
          </div>

          <div className="space-y-2 text-sm">
            <div className="text-xs font-medium text-muted-foreground">Environment variables</div>
            <div className="rounded-lg border bg-muted/20 p-3 font-mono text-xs">
              <div>ALLOW_NETWORK=false</div>
              <div>ALLOWED_ROOTS=/data</div>
            </div>
          </div>

          <div className="text-xs text-muted-foreground">
            <Link href="/docs" className="underline">
              View docs →
            </Link>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  )
}
