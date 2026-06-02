'use client'

import { useEffect, useMemo, useState } from 'react'
import { useSession } from 'next-auth/react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Bell, Coins, PlugZap, Settings2, User } from 'lucide-react'
import { McpConfigurationPanel } from '@/components/mcp/mcp-configuration-panel'
import {
  CreditsLedgerEntry,
  fetchCreditsLedger,
  readApiUsdCreditsBalance,
  readApiUsdCreditsUpdatedAt,
  readCreditsBalance,
  readCreditsUpdatedAt,
  subscribeCreditsUpdates,
  syncApiUsdCreditsBalanceFromServer,
  syncCreditsBalanceFromServer,
} from '@/lib/credits'

type ThemePreference = 'system' | 'light' | 'dark'

type LocalPreferences = {
  theme: ThemePreference
  compactMode: boolean
  soundEnabled: boolean
  advancedMode: boolean
}

const PREFS_STORAGE_KEY = 'br:settings:preferences'

const policyDisablesAdvancedMode = (): boolean => {
  const raw = process.env.NEXT_PUBLIC_DISABLE_ADVANCED_MODE
  if (!raw) return false
  const normalized = raw.trim().toLowerCase()
  return normalized === '1' || normalized === 'true' || normalized === 'yes'
}

const loadPrefs = (): LocalPreferences => {
  if (typeof window === 'undefined') {
    return { theme: 'system', compactMode: false, soundEnabled: true, advancedMode: true }
  }
  try {
    const raw = window.localStorage.getItem(PREFS_STORAGE_KEY)
    if (!raw) return { theme: 'system', compactMode: false, soundEnabled: true, advancedMode: true }
    const parsed = JSON.parse(raw) as Partial<LocalPreferences>
    const theme = parsed.theme === 'light' || parsed.theme === 'dark' || parsed.theme === 'system' ? parsed.theme : 'system'
    return {
      theme,
      compactMode: Boolean(parsed.compactMode),
      soundEnabled: parsed.soundEnabled === false ? false : true,
      advancedMode: typeof parsed.advancedMode === 'undefined' ? true : Boolean(parsed.advancedMode),
    }
  } catch {
    return { theme: 'system', compactMode: false, soundEnabled: true, advancedMode: true }
  }
}

const cleanQueryValue = (value: string | null): string | null => {
  const trimmed = typeof value === 'string' ? value.trim() : ''
  return trimmed || null
}

export function SettingsInterface() {
  const { data: session } = useSession()
  const searchParams = useSearchParams()
  const [activeTab, setActiveTab] = useState('profile')
  const [prefs, setPrefs] = useState<LocalPreferences>(() => loadPrefs())
  const advancedAllowed = !policyDisablesAdvancedMode()
  const requestedTab = (searchParams.get('tab') || '').trim().toLowerCase()
  const handoffPlanId = cleanQueryValue(searchParams.get('planId') || searchParams.get('plan_id'))
  const handoffThreadId = cleanQueryValue(
    searchParams.get('threadId') || searchParams.get('thread_id') || searchParams.get('thread'),
  )
  const handoffWorkflowId = cleanQueryValue(
    searchParams.get('workflowId') ||
      searchParams.get('workflow_id') ||
      searchParams.get('pipeline'),
  )
  const handoffWorkflowLabel =
    cleanQueryValue(searchParams.get('workflowLabel') || searchParams.get('workflow_label')) ||
    handoffWorkflowId
  const handoffDatasetId = cleanQueryValue(
    searchParams.get('datasetId') || searchParams.get('dataset_id') || searchParams.get('dataset'),
  )
  const handoffDatasetVersion = cleanQueryValue(
    searchParams.get('datasetVersion') || searchParams.get('dataset_version'),
  )
  const handoffKgConceptId = cleanQueryValue(
    searchParams.get('kgConceptId') || searchParams.get('kg_concept_id'),
  )
  const handoffKgConceptLabel =
    cleanQueryValue(searchParams.get('kgConceptLabel') || searchParams.get('kg_concept_label')) ||
    handoffKgConceptId
  const handoffKgQuery = cleanQueryValue(searchParams.get('kgQuery') || searchParams.get('kg_query'))
  const kgContinuationPrompt =
    handoffKgQuery
      ? [
          'Continue from this Brain Researcher KG search handoff.',
          `Use BR MCP KG tools first for query "${handoffKgQuery}".`,
          'Start with kg_search_nodes and then use kg_get_node, kg_neighbors, and kg_multihop_qa when seeds are found.',
          'Find related datasets, official workflows, and provenance before selecting an execution recipe.',
        ].join(' ')
      : null
  const kgNodeContinuationPrompt =
    handoffKgConceptId || handoffKgConceptLabel
      ? [
          'Continue from this Brain Researcher KG handoff.',
          `Use BR MCP KG tools first for concept "${handoffKgConceptLabel || handoffKgConceptId}" (${handoffKgConceptId || 'unresolved id'}).`,
          'Find related datasets, official workflows, and provenance before selecting an execution recipe.',
        ].join(' ')
      : null

  useEffect(() => {
    if (!requestedTab) return
    if (
      !['profile', 'preferences', 'credits', 'integrations', 'api-keys', 'notifications'].includes(
        requestedTab,
      )
    ) {
      return
    }
    setActiveTab(requestedTab === 'api-keys' ? 'integrations' : requestedTab)
  }, [requestedTab])

  useEffect(() => {
    if (typeof window === 'undefined') return
    try {
      const nextPrefs = {
        ...prefs,
        advancedMode: advancedAllowed ? prefs.advancedMode : false,
      }
      window.localStorage.setItem(PREFS_STORAGE_KEY, JSON.stringify(nextPrefs))
    } catch {
      // ignore
    }
  }, [prefs, advancedAllowed])

  const userInfo = useMemo(() => {
    const name = session?.user?.name || session?.user?.email || 'Unknown user'
    const email = session?.user?.email || 'No data yet.'
    const role = session?.user?.role || null
    const tenant = (session?.user as any)?.tenant_id || null
    return { name, email, role, tenant }
  }, [session?.user])

  const [creditsBalance, setCreditsBalance] = useState<number | null>(null)
  const [creditsUpdatedAt, setCreditsUpdatedAt] = useState<number | null>(null)
  const [creditsLoading, setCreditsLoading] = useState(false)
  const [apiUsdCreditsBalance, setApiUsdCreditsBalance] = useState<number | null>(null)
  const [apiUsdCreditsUpdatedAt, setApiUsdCreditsUpdatedAt] = useState<number | null>(null)
  const [apiUsdCreditsLoading, setApiUsdCreditsLoading] = useState(false)
  const [ledger, setLedger] = useState<CreditsLedgerEntry[]>([])
  const [ledgerLoading, setLedgerLoading] = useState(false)

  useEffect(() => {
    if (typeof window === 'undefined') return

    let cancelled = false

    const refreshLocal = () => {
      const balance = readCreditsBalance()
      setCreditsBalance(balance)
      setCreditsUpdatedAt(readCreditsUpdatedAt())
      setApiUsdCreditsBalance(readApiUsdCreditsBalance())
      setApiUsdCreditsUpdatedAt(readApiUsdCreditsUpdatedAt())
    }

    const refreshRemote = async () => {
      setCreditsLoading(true)
      setApiUsdCreditsLoading(true)
      await Promise.all([syncCreditsBalanceFromServer(), syncApiUsdCreditsBalanceFromServer()])
      if (!cancelled) {
        refreshLocal()
        setCreditsLoading(false)
        setApiUsdCreditsLoading(false)
      }
      if (cancelled) return

      setLedgerLoading(true)
      try {
        const payload = await fetchCreditsLedger(10)
        if (!cancelled) {
          setLedger(Array.isArray(payload.items) ? payload.items : [])
        }
      } catch {
        if (!cancelled) {
          setLedger([])
        }
      } finally {
        if (!cancelled) setLedgerLoading(false)
      }
    }

    refreshLocal()
    void refreshRemote()

    const unsubscribe = subscribeCreditsUpdates(refreshLocal)
    const onVisible = () => {
      if (!document.hidden) {
        void refreshRemote()
      }
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      cancelled = true
      unsubscribe()
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [])

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Settings</h1>
        <p className="text-sm text-muted-foreground">Account details and local UI preferences.</p>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="grid w-full grid-cols-2 gap-1 sm:grid-cols-5">
          <TabsTrigger value="profile" className="flex items-center gap-2">
            <User className="h-4 w-4" />
            Profile
          </TabsTrigger>
          <TabsTrigger value="preferences" className="flex items-center gap-2">
            <Settings2 className="h-4 w-4" />
            Preferences
          </TabsTrigger>
          <TabsTrigger value="credits" className="flex items-center gap-2">
            <Coins className="h-4 w-4" />
            Credits
          </TabsTrigger>
          <TabsTrigger value="integrations" className="flex items-center gap-2">
            <PlugZap className="h-4 w-4" />
            Integrations
          </TabsTrigger>
          <TabsTrigger value="notifications" className="flex items-center gap-2">
            <Bell className="h-4 w-4" />
            Notifications
          </TabsTrigger>
        </TabsList>

        <TabsContent value="profile" className="mt-6">
          <Card>
            <CardHeader>
              <CardTitle>Profile</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{userInfo.name}</span>
                {userInfo.role && <Badge variant="secondary">{userInfo.role}</Badge>}
                {userInfo.tenant && <Badge variant="outline">Tenant: {String(userInfo.tenant)}</Badge>}
              </div>
              <div className="text-muted-foreground">{userInfo.email}</div>

              {!session && (
                <div className="pt-2 text-muted-foreground">
                  No session loaded. Sign in to see your account details.
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="preferences" className="mt-6">
          <Card>
            <CardHeader>
              <CardTitle>Preferences</CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="text-sm text-muted-foreground">
                These preferences are stored locally in your browser for now.
              </div>

              <div className="flex items-center justify-between gap-4">
                <div className="space-y-1">
                  <Label className="text-sm">Theme</Label>
                  <div className="text-xs text-muted-foreground">System / Light / Dark</div>
                </div>
                <div className="flex items-center gap-2">
                  {(['system', 'light', 'dark'] as ThemePreference[]).map((value) => (
                    <Button
                      key={value}
                      type="button"
                      size="sm"
                      variant={prefs.theme === value ? 'default' : 'outline'}
                      onClick={() => setPrefs((prev) => ({ ...prev, theme: value }))}
                      className="capitalize"
                    >
                      {value}
                    </Button>
                  ))}
                </div>
              </div>

              <div className="flex items-center justify-between gap-4">
                <div className="space-y-1">
                  <Label className="text-sm">Compact mode</Label>
                  <div className="text-xs text-muted-foreground">Reduce padding and density.</div>
                </div>
                <Switch
                  checked={prefs.compactMode}
                  onCheckedChange={(checked) => setPrefs((prev) => ({ ...prev, compactMode: checked }))}
                />
              </div>

              <div className="flex items-center justify-between gap-4">
                <div className="space-y-1">
                  <Label className="text-sm">Sound</Label>
                  <div className="text-xs text-muted-foreground">Enable UI sounds.</div>
                </div>
                <Switch
                  checked={prefs.soundEnabled}
                  onCheckedChange={(checked) => setPrefs((prev) => ({ ...prev, soundEnabled: checked }))}
                />
              </div>

            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="credits" className="mt-6">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between gap-2">
                <CardTitle>Credits</CardTitle>
                <Badge variant="secondary">Beta</Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              {!session ? (
                <div className="text-muted-foreground">
                  Sign in to view your credit balance.
                </div>
              ) : (
                <>
                  <div className="space-y-2">
                    <div className="grid gap-3 md:grid-cols-2">
                      <div className="rounded-lg border bg-background p-3">
                        <div className="text-xs text-muted-foreground">Workflow runtime credits</div>
                        <div className="mt-1 text-2xl font-semibold">
                          {creditsBalance == null ? '0' : creditsBalance.toLocaleString()} credits
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          {creditsLoading
                            ? 'Refreshing…'
                            : creditsUpdatedAt
                            ? `Last updated: ${new Date(creditsUpdatedAt).toLocaleString()}`
                            : 'No balance snapshot yet.'}
                        </div>
                      </div>
                      <div className="rounded-lg border bg-background p-3">
                        <div className="text-xs text-muted-foreground">API-fee USD credits</div>
                        <div className="mt-1 text-2xl font-semibold">
                          {apiUsdCreditsBalance == null
                            ? '$0.00'
                            : apiUsdCreditsBalance.toLocaleString(undefined, {
                                style: 'currency',
                                currency: 'USD',
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 3,
                              })}
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          {apiUsdCreditsLoading
                            ? 'Refreshing…'
                            : apiUsdCreditsUpdatedAt
                            ? `Last updated: ${new Date(apiUsdCreditsUpdatedAt).toLocaleString()}`
                            : 'No API-fee balance snapshot yet.'}
                        </div>
                      </div>
                    </div>

                    <div className="flex justify-end">
                      <Button type="button" variant="outline" size="sm" asChild>
                        <Link href="/analyses">View workflow usage</Link>
                      </Button>
                    </div>

                    <div className="rounded-lg border bg-muted/20 p-3">
                      <div className="text-sm text-muted-foreground">
                        Workflow runtime credits are consumed when analyses are created. API-fee USD credits are tracked separately for platform-managed provider API usage.
                      </div>
                    </div>
                  </div>
                  <div className="rounded-lg border bg-muted/20 p-3 text-xs text-muted-foreground">
                    API-fee USD credits are not workflow runtime credits. BYOK and local OAuth provider calls are not debited from the API-fee USD bucket.
                  </div>

                  <div className="rounded-lg border bg-muted/20 p-3 text-xs text-muted-foreground space-y-2">
                    <div className="font-medium">Recent workflow credit ledger entries</div>
                    {ledgerLoading ? (
                      <div>Loading ledger…</div>
                    ) : ledger.length ? (
                      <div className="space-y-1">
                        {ledger.map((entry) => (
                          <div key={entry.entry_id} className="flex items-center justify-between gap-3">
                            <span className="truncate">{entry.event_type}</span>
                            <span className="tabular-nums">
                              {entry.amount >= 0 ? '+' : ''}
                              {Math.trunc(entry.amount)}
                            </span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div>No ledger entries yet.</div>
                    )}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    MCP access tokens are managed separately under <strong>Integrations</strong>; credits do not affect MCP
                    authentication.
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="integrations" className="mt-6">
          <Card>
            <CardHeader>
              <CardTitle>Integrations</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              <div className="text-muted-foreground">
                Connect Brain Researcher to tools that support the Model Context Protocol (MCP).
              </div>
              <McpConfigurationPanel
                planId={handoffPlanId}
                threadId={handoffThreadId}
                workflowId={handoffWorkflowId}
                workflowLabel={handoffWorkflowLabel}
                datasetId={handoffDatasetId}
                datasetVersion={handoffDatasetVersion}
                continuationPrompt={kgContinuationPrompt || kgNodeContinuationPrompt}
              />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="notifications" className="mt-6">
          <Card>
            <CardHeader>
              <CardTitle>Notifications</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div className="text-muted-foreground">No data yet.</div>
              <div className="text-muted-foreground">
                Notification preferences aren’t wired in this UI yet.
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}
