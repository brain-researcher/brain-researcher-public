'use client'

import Link from 'next/link'
import { useEffect, useRef, useState } from 'react'
import { useSession } from 'next-auth/react'
import {
  ArrowRight,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Copy,
  Download,
  FileText,
  Github,
  KeyRound,
  LogIn,
  Terminal,
} from 'lucide-react'

import { useAuth } from '@/hooks/use-auth'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useToast } from '@/hooks/use-toast'
import { AgentComparisonDemo } from '@/components/landing/agent-comparison-demo'
import { AuthenticatedNavigation } from '@/components/authenticated-navigation'
import { NavigationHeader } from '@/components/navigation/navigation-header'
import {
  buildHostedMcpSnippet,
  buildMcpTokenExportCommand,
  DEFAULT_MCP_CLOUD_URL,
  type HostedMcpClient,
} from '@/lib/mcp-config-snippets'

const TOKEN_PATH = '/mcp/setup'
const PAPER_TITLE =
  'Brain Researcher: AI-assisted research infrastructure workspace for neuroimaging analyses'
const PAPER_AUTHORS = 'Brain Researcher contributors'
// Condensed for the landing; the full abstract lives in the paper (docs/overleaf/.../abstract.tex).
const PAPER_ABSTRACT = `AI agents can write code, run analyses, and propose hypotheses, but a generated output is not a scientific claim by default. Brain Researcher turns researcher judgment into executable commitments: allowed alternatives, validation rules, provenance, and claim boundaries. Every result stays tied to the evidence behind it and the limits beyond which it shouldn't be read. Tested on neuroimaging across seven foundation models, it raised tool-selection accuracy from a 51% to 63% baseline to about 93%, and returned bounded claim records (accepted, qualified, or rejected) instead of unqualified findings.`
const HERO_STATS = [
  { value: '1,600+', label: 'datasets' },
  { value: '2,000+', label: 'tool specs' },
  { value: '87', label: 'MCP tools' },
  { value: '60+', label: 'workflows' },
]
const HERO_MODEL_LINE = 'Tested across Claude, Codex, Gemini, GLM, DeepSeek, Kimi, and Qwen.'

const BIBTEX = `@misc{brain_researcher_2026,
  author       = {{Brain Researcher contributors}},
  title        = {Brain Researcher: AI-assisted research infrastructure workspace for neuroimaging analyses},
  year         = {2026},
  howpublished = {\\url{https://\${PUBLIC_HOSTNAME}}},
  note         = {arXiv:XXXX.XXXXX (preprint pending); Zenodo DOI pending}
}`

type Client = {
  id: HostedMcpClient
  name: string
  downloadUrl: string
  install: string
}

// Order: Claude Code, Codex, Cursor
const CLIENTS: Client[] = [
  {
    id: 'claude',
    name: 'Claude Code',
    downloadUrl: 'https://www.anthropic.com/claude-code',
    install: 'npm install -g @anthropic-ai/claude-code',
  },
  {
    id: 'codex',
    name: 'Codex',
    downloadUrl: 'https://developers.openai.com/codex',
    install: 'npm install -g @openai/codex',
  },
  { id: 'cursor', name: 'Cursor', downloadUrl: 'https://cursor.com', install: 'Download the Cursor desktop app from cursor.com.' },
]

function sanitizeCallbackUrl(value: string): string {
  const trimmed = value.trim()
  if (!trimmed.startsWith('/')) return '/studio'
  if (trimmed.startsWith('/auth')) return '/studio'
  return trimmed
}

function buildSignupHref(callbackUrl: string): string {
  const safe = sanitizeCallbackUrl(callbackUrl)
  return `/auth/signup?callbackUrl=${encodeURIComponent(safe)}`
}

function buildLoginHref(callbackUrl: string): string {
  const safe = sanitizeCallbackUrl(callbackUrl)
  return `/auth/login?callbackUrl=${encodeURIComponent(safe)}`
}

function useCopy() {
  const { toast } = useToast()
  const [copiedKey, setCopiedKey] = useState<string | null>(null)

  const copy = async (key: string, value: string, label: string) => {
    try {
      await navigator.clipboard.writeText(value)
      setCopiedKey(key)
      window.setTimeout(() => setCopiedKey((current) => (current === key ? null : current)), 1500)
    } catch {
      toast({ title: `Failed to copy ${label}`, variant: 'destructive' })
    }
  }

  return { copiedKey, copy }
}

function CodeBlock({
  value,
  label,
  copyKey,
  copiedKey,
  onCopy,
  className = '',
}: {
  value: string
  label: string
  copyKey: string
  copiedKey: string | null
  onCopy: (key: string, value: string, label: string) => void
  className?: string
}) {
  const copied = copiedKey === copyKey
  return (
    <div className={`group relative min-w-0 rounded-lg border border-slate-800 bg-slate-950 ${className}`}>
      <button
        type="button"
        onClick={() => onCopy(copyKey, value, label)}
        className="absolute right-2 top-2 z-10 inline-flex items-center gap-1 rounded-md bg-slate-800/80 px-2 py-1 text-[11px] font-medium text-slate-200 hover:bg-slate-700"
        aria-label={`Copy ${label}`}
      >
        {copied ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
        {copied ? 'Copied' : 'Copy'}
      </button>
      <pre className="max-h-40 overflow-auto p-3 pr-16 text-[11px] leading-relaxed text-slate-100">
        <code className="font-mono whitespace-pre">{value}</code>
      </pre>
    </div>
  )
}

function StepCard({
  step,
  title,
  children,
}: {
  step: number
  title: string
  children: React.ReactNode
}) {
  return (
    <div className="flex min-w-0 flex-col rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-3 flex items-center gap-3">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-900 text-sm font-semibold text-white">
          {step}
        </span>
        <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
      </div>
      <div className="flex flex-1 flex-col gap-3 text-sm text-slate-600">{children}</div>
    </div>
  )
}

type DemoIndexEntry = {
  slug: string
  title: string
  description?: string
  is_template?: boolean
  evidence_mode?: 'real' | 'hybrid' | 'template'
  demo_type?: string
  tags?: string[]
  created_at?: string
  bundle_available?: boolean
  bundle_artifact_count?: number
  primary_prompt?: string
}

function humanizeType(value?: string): string {
  if (!value) return ''
  return value.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
}

function evidenceLabel(mode?: DemoIndexEntry['evidence_mode']): string {
  return mode === 'real' ? 'Real evidence' : mode === 'hybrid' ? 'Hybrid evidence' : 'Template'
}

export default function LandingPageStatic() {
  const { isAuthenticated, isLoading } = useAuth()
  const { data: session, status } = useSession()
  const [hydrated, setHydrated] = useState(false)
  const [client, setClient] = useState<HostedMcpClient>('claude')
  const [demos, setDemos] = useState<DemoIndexEntry[]>([])
  const [demosLoading, setDemosLoading] = useState(true)
  const { copiedKey, copy } = useCopy()

  useEffect(() => setHydrated(true), [])

  useEffect(() => {
    const controller = new AbortController()
    fetch('/api/demo/index', { cache: 'no-store', signal: controller.signal })
      .then((res) => (res.ok ? res.json() : { demos: [] }))
      .then((data) => setDemos((data.demos || []).slice(0, 6)))
      .catch(() => setDemos([]))
      .finally(() => setDemosLoading(false))
    return () => controller.abort()
  }, [])

  const showAuthenticatedActions =
    !isLoading && (isAuthenticated || status === 'authenticated' || Boolean(session))

  const buildEntryHref = (callbackUrl: string) => {
    const safe = sanitizeCallbackUrl(callbackUrl)
    return showAuthenticatedActions ? safe : buildSignupHref(safe)
  }

  const demoTrackRef = useRef<HTMLDivElement | null>(null)
  const [activeDemo, setActiveDemo] = useState(0)
  const goToDemo = (i: number) => {
    const el = demoTrackRef.current
    if (!el) return
    const idx = Math.max(0, Math.min(i, el.children.length - 1))
    const card = el.children[idx] as HTMLElement | undefined
    if (card) el.scrollTo({ left: card.offsetLeft, behavior: 'smooth' })
  }
  const onDemoScroll = () => {
    const el = demoTrackRef.current
    if (el) setActiveDemo(Math.round(el.scrollLeft / el.clientWidth))
  }

  const activeClient = CLIENTS.find((c) => c.id === client) ?? CLIENTS[0]
  const tokenExport = buildMcpTokenExportCommand()
  const snippet = buildHostedMcpSnippet(client, { url: DEFAULT_MCP_CLOUD_URL })

  return (
    <div
      data-testid="landing-page"
      data-hydrated={hydrated ? '1' : '0'}
      className="h-screen w-full snap-y snap-mandatory overflow-y-auto scroll-smooth bg-white text-slate-900"
    >
      {/* Site navigation — same header as the rest of the app (fixed, floats over the snap container) */}
      {isAuthenticated ? (
        <AuthenticatedNavigation />
      ) : (
        <NavigationHeader user={null} />
      )}

      {/* Screen 1 — Product banner + MCP setup steps */}
      <section
        id="mcp-setup"
        className="relative flex min-h-screen w-full snap-start flex-col justify-center px-6 pb-16 pt-24"
      >
        <div className="mx-auto w-full max-w-6xl">
          <div className="mx-auto max-w-4xl text-center">
            <h1 className="text-balance text-4xl font-semibold tracking-tight sm:text-6xl">
              Brain Researcher
            </h1>
            <p className="mx-auto mt-3 max-w-3xl text-balance text-xl font-semibold sm:text-3xl">
              <span className="text-slate-500">AI-assisted research infrastructure for neuroimaging</span>
            </p>
            <p className="mx-auto mt-4 max-w-2xl text-base text-slate-500 sm:text-lg">
              Turn neuroimaging questions into evidence-linked plans, runnable workflows, and
              reviewable scientific claims.
            </p>
            <dl className="mx-auto mt-7 grid max-w-3xl grid-cols-2 gap-3 sm:grid-cols-4">
              {HERO_STATS.map((stat) => (
                <div key={stat.label} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-3">
                  <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{stat.label}</dt>
                  <dd className="mt-1 text-2xl font-semibold text-slate-950">{stat.value}</dd>
                </div>
              ))}
            </dl>
            <p className="mx-auto mt-4 max-w-2xl text-sm text-slate-500">{HERO_MODEL_LINE}</p>
          </div>

          {/* Client selector */}
          <div className="mt-10 flex justify-center">
            <div
              className="inline-flex rounded-xl border border-slate-200 bg-slate-50 p-1"
              role="tablist"
              aria-label="Choose a coding agent"
            >
              {CLIENTS.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  role="tab"
                  aria-selected={client === c.id}
                  onClick={() => setClient(c.id)}
                  className={`rounded-lg px-4 py-1.5 text-sm font-medium transition-colors ${
                    client === c.id
                      ? 'bg-white text-slate-900 shadow-sm'
                      : 'text-slate-500 hover:text-slate-900'
                  }`}
                >
                  {c.name}
                </button>
              ))}
            </div>
          </div>

          {/* 3 steps */}
          <div className="mt-6 grid gap-4 md:grid-cols-3">
            <StepCard step={1} title={`Install ${activeClient.name}`}>
              <p>{activeClient.install}</p>
              {activeClient.install.startsWith('npm ') ? (
                <CodeBlock
                  value={activeClient.install}
                  label="install command"
                  copyKey="install"
                  copiedKey={copiedKey}
                  onCopy={copy}
                />
              ) : null}
              <Button asChild variant="outline" size="sm" className="mt-auto w-full">
                <Link href={activeClient.downloadUrl} target="_blank" rel="noreferrer">
                  <Download className="mr-2 h-4 w-4" />
                  Get {activeClient.name}
                </Link>
              </Button>
            </StepCard>

            <StepCard step={2} title="Get your token">
              {showAuthenticatedActions ? (
                <>
                  <p>You&apos;re signed in. Mint your personal MCP token and copy it once.</p>
                  <Button asChild size="sm" className="mt-auto w-full">
                    <Link href={TOKEN_PATH}>
                      <KeyRound className="mr-2 h-4 w-4" />
                      Get my token
                    </Link>
                  </Button>
                </>
              ) : (
                <>
                  <p>Sign in to mint your personal MCP token (a one-time secret).</p>
                  <div className="mt-auto flex flex-col gap-2">
                    <Button asChild size="sm" className="w-full">
                      <Link href={buildLoginHref(TOKEN_PATH)}>
                        <LogIn className="mr-2 h-4 w-4" />
                        Log in
                      </Link>
                    </Button>
                    <Button asChild size="sm" variant="outline" className="w-full">
                      <Link href={buildSignupHref(TOKEN_PATH)}>Create account</Link>
                    </Button>
                  </div>
                </>
              )}
            </StepCard>

            <StepCard step={3} title="Configure MCP">
              <p>
                Export your token, then drop this config into{' '}
                <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-xs">
                  {snippet.fileName}
                </code>
                .
              </p>
              <CodeBlock
                value={tokenExport}
                label="token export"
                copyKey="token"
                copiedKey={copiedKey}
                onCopy={copy}
              />
              <CodeBlock
                value={snippet.snippet}
                label={snippet.copyLabel}
                copyKey="snippet"
                copiedKey={copiedKey}
                onCopy={copy}
              />
            </StepCard>
          </div>
        </div>

        {/* Scroll hint */}
        <a
          href="#try-it"
          className="absolute bottom-6 left-1/2 flex -translate-x-1/2 flex-col items-center gap-1 text-xs font-medium text-slate-400 transition-colors hover:text-slate-700"
          aria-label="Scroll to try it"
        >
          Try it
          <ChevronDown className="h-5 w-5 animate-bounce" />
        </a>
      </section>

      {/* Screen 2 — Try it: prompt + demo output */}
      <section
        id="try-it"
        className="relative flex min-h-screen w-full snap-start flex-col justify-center bg-slate-50 px-6 py-24"
      >
        <div className="mx-auto w-full max-w-5xl">
          <div className="text-center">
            <div className="text-xs font-medium uppercase tracking-wider text-slate-400">
              Claude alone vs. with Brain Researcher
            </div>
            <h2 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">
              Now, just ask.
            </h2>
            <p className="mx-auto mt-3 max-w-xl text-slate-500">
              Same question, same agent. Only one of them can find the dataset and hand you a
              runnable recipe.
            </p>
          </div>

          <div className="mt-8">
            <AgentComparisonDemo />
          </div>

          <div className="mt-8 flex justify-center">
            <Button asChild size="lg">
              <Link href={buildEntryHref('/studio')}>
                <Terminal className="mr-2 h-4 w-4" />
                Open Studio
              </Link>
            </Button>
          </div>
        </div>

        {/* Scroll hint */}
        <a
          href="#paper-code"
          className="absolute bottom-6 left-1/2 flex -translate-x-1/2 flex-col items-center gap-1 text-xs font-medium text-slate-400 transition-colors hover:text-slate-700"
          aria-label="Scroll to paper and code"
        >
          Paper &amp; code
          <ChevronDown className="h-5 w-5 animate-bounce" />
        </a>
      </section>

      {/* Screen 3 — Paper + Code */}
      <section
        id="paper-code"
        className="relative flex min-h-screen w-full snap-start flex-col justify-center px-6 py-24"
      >
        <div className="mx-auto w-full max-w-6xl">
          <div className="mb-10 text-center">
            <div className="text-xs font-medium uppercase tracking-wider text-slate-400">
              Open &amp; reproducible
            </div>
            <h2 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">
              Read the paper, run the code
            </h2>
          </div>

          <div className="grid gap-6 lg:grid-cols-2 lg:items-stretch">
            {/* Paper */}
            <div className="flex flex-col rounded-2xl border border-slate-200 bg-white p-7 shadow-sm">
              <div className="flex items-center gap-2 text-slate-900">
                <FileText className="h-5 w-5" />
                <span className="text-xs font-semibold uppercase tracking-wider">Paper</span>
              </div>
              <h3 className="mt-3 text-xl font-semibold leading-snug">{PAPER_TITLE}</h3>
              <p className="mt-1 text-sm text-slate-500">{PAPER_AUTHORS}</p>
              <div className="mt-2">
                <Badge variant="outline" className="text-[11px]">
                  Preprint pending · arXiv soon
                </Badge>
              </div>
              <p className="mt-4 flex-1 text-sm leading-relaxed text-slate-600">{PAPER_ABSTRACT}</p>

              <div className="mt-5 flex flex-wrap gap-2">
                <Button disabled variant="default" size="sm">
                  <FileText className="mr-2 h-4 w-4" />
                  Read paper (soon)
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => copy('bibtex', BIBTEX, 'BibTeX')}
                >
                  {copiedKey === 'bibtex' ? (
                    <Check className="mr-2 h-4 w-4 text-emerald-600" />
                  ) : (
                    <Copy className="mr-2 h-4 w-4" />
                  )}
                  {copiedKey === 'bibtex' ? 'Copied BibTeX' : 'Copy BibTeX'}
                </Button>
              </div>
            </div>

            {/* Code */}
            <div className="flex flex-col rounded-2xl border border-slate-200 bg-white p-7 shadow-sm">
              <div className="flex items-center gap-2 text-slate-900">
                <Github className="h-5 w-5" />
                <span className="text-xs font-semibold uppercase tracking-wider">Code</span>
              </div>
              <h3 className="mt-3 text-xl font-semibold leading-snug text-slate-900">
                Brain Researcher
              </h3>
              <div className="mt-2">
                <Badge variant="outline" className="text-[11px]">
                  Open-source release coming soon
                </Badge>
              </div>
              <p className="mt-4 flex-1 text-sm leading-relaxed text-slate-600">
                The full platform: Next.js web UI, FastAPI orchestrator + agent, 87 public MCP
                tools, 2,000+ registry tool specs, and the Neo4j knowledge graph. We&apos;re
                open-sourcing it so you can wire up your MCP token and reproduce every workflow end
                to end.
              </p>

              <div className="mt-4 flex flex-wrap gap-1.5">
                {['Python', 'TypeScript', 'Next.js', 'FastAPI', 'Neo4j', 'MCP'].map((tag) => (
                  <span
                    key={tag}
                    className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-0.5 text-[11px] text-slate-600"
                  >
                    {tag}
                  </span>
                ))}
              </div>

              <div className="mt-5 flex flex-wrap gap-2">
                <Button disabled size="sm">
                  <Github className="mr-2 h-4 w-4" />
                  On GitHub (soon)
                </Button>
                <Button asChild variant="outline" size="sm">
                  <Link href={buildEntryHref('/studio')}>
                    Open in Studio
                    <ArrowRight className="ml-2 h-4 w-4" />
                  </Link>
                </Button>
              </div>
            </div>
          </div>
        </div>

        {/* Scroll hint */}
        <a
          href="#demos"
          className="absolute bottom-6 left-1/2 flex -translate-x-1/2 flex-col items-center gap-1 text-xs font-medium text-slate-400 transition-colors hover:text-slate-700"
          aria-label="Scroll to demos"
        >
          Demos
          <ChevronDown className="h-5 w-5 animate-bounce" />
        </a>
      </section>

      {/* Screen 4 — Demos */}
      <section
        id="demos"
        className="relative flex min-h-screen w-full snap-start flex-col justify-center bg-slate-50 px-6 py-24"
      >
        <div className="mx-auto w-full max-w-6xl">
          <div className="mb-10 text-center">
            <div className="text-xs font-medium uppercase tracking-wider text-slate-400">
              See it in action
            </div>
            <h2 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">
              Explore worked demos
            </h2>
            <p className="mx-auto mt-3 max-w-xl text-slate-500">
              Curated use cases with real evidence bundles, reports, and handoff context. Open one to
              walk the full research episode.
            </p>
          </div>

          {/* pager controls */}
          <div className="mb-4 flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={() => goToDemo(activeDemo - 1)}
              disabled={activeDemo <= 0}
              aria-label="Previous demo"
              className="rounded-full border border-slate-200 bg-white p-2 text-slate-600 shadow-sm transition-colors hover:bg-slate-50 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ChevronLeft className="h-5 w-5" />
            </button>
            <button
              type="button"
              onClick={() => goToDemo(activeDemo + 1)}
              disabled={demos.length > 0 && activeDemo >= demos.length - 1}
              aria-label="Next demo"
              className="rounded-full border border-slate-200 bg-white p-2 text-slate-600 shadow-sm transition-colors hover:bg-slate-50 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ChevronRight className="h-5 w-5" />
            </button>
          </div>

          {/* one-card-per-page track */}
          <div
            ref={demoTrackRef}
            onScroll={onDemoScroll}
            className="flex snap-x snap-mandatory gap-4 overflow-x-auto scroll-smooth pb-2 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
          >
            {demosLoading ? (
              <div className="w-full shrink-0 animate-pulse snap-start rounded-2xl border border-slate-200 bg-white p-8">
                <div className="h-4 w-32 rounded bg-slate-100" />
                <div className="mt-4 h-7 w-2/3 rounded bg-slate-100" />
                <div className="mt-4 h-4 w-full rounded bg-slate-100" />
                <div className="mt-2 h-4 w-5/6 rounded bg-slate-100" />
              </div>
            ) : demos.length === 0 ? (
              <div className="w-full rounded-2xl border border-dashed border-slate-200 py-12 text-center text-sm text-slate-400">
                No demos available yet.
              </div>
            ) : (
              demos.map((demo) => (
                <Link
                  key={demo.slug}
                  href={`/demos/${demo.slug}`}
                  className="group grid w-full shrink-0 snap-start gap-6 rounded-2xl border border-slate-200 bg-white p-7 shadow-sm transition-colors hover:border-slate-300 md:grid-cols-[1.4fr_1fr] md:p-9"
                >
                  {/* left: title + description + CTA */}
                  <div className="flex flex-col">
                    <div className="flex flex-wrap items-center gap-2">
                      {demo.demo_type ? (
                        <span className="text-xs font-medium uppercase tracking-wider text-slate-400">
                          {humanizeType(demo.demo_type)}
                        </span>
                      ) : null}
                      <span className="rounded-full border border-slate-200 px-2 py-0.5 text-[10px] font-medium text-slate-500">
                        {evidenceLabel(demo.evidence_mode)}
                      </span>
                      {demo.is_template ? (
                        <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-700">
                          Template
                        </span>
                      ) : null}
                    </div>
                    <h3 className="mt-3 text-xl font-semibold leading-snug text-slate-900 sm:text-2xl">
                      {demo.title}
                    </h3>
                    {demo.description ? (
                      <p className="mt-3 flex-1 text-sm leading-relaxed text-slate-600">
                        {demo.description}
                      </p>
                    ) : (
                      <div className="flex-1" />
                    )}
                    <span className="mt-6 inline-flex items-center gap-1 text-sm font-medium text-slate-900">
                      Open use case
                      <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                    </span>
                  </div>

                  {/* right: prompt + tags + meta */}
                  <div className="flex flex-col gap-4 md:border-l md:border-slate-100 md:pl-6">
                    {demo.primary_prompt ? (
                      <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                        <div className="text-[10px] font-medium uppercase tracking-wider text-slate-400">
                          Example prompt
                        </div>
                        <p className="mt-1 text-xs leading-relaxed text-slate-600 line-clamp-4">
                          {demo.primary_prompt}
                        </p>
                      </div>
                    ) : null}
                    {demo.tags && demo.tags.length > 0 ? (
                      <div className="flex flex-wrap gap-1.5">
                        {demo.tags.slice(0, 5).map((tag) => (
                          <span
                            key={tag}
                            className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] text-slate-600"
                          >
                            {tag}
                          </span>
                        ))}
                      </div>
                    ) : null}
                    <div className="mt-auto flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-slate-400">
                      {demo.bundle_available ? (
                        <span>
                          Evidence bundle · {demo.bundle_artifact_count ?? 0} artifact
                          {(demo.bundle_artifact_count ?? 0) === 1 ? '' : 's'}
                        </span>
                      ) : null}
                      {demo.created_at ? <span>{demo.created_at}</span> : null}
                    </div>
                  </div>
                </Link>
              ))
            )}
          </div>

          {/* dots */}
          {!demosLoading && demos.length > 1 ? (
            <div className="mt-5 flex items-center justify-center gap-2">
              {demos.map((demo, i) => (
                <button
                  key={demo.slug}
                  type="button"
                  onClick={() => goToDemo(i)}
                  aria-label={`Go to demo ${i + 1}`}
                  className={`h-2 rounded-full transition-all ${
                    i === activeDemo ? 'w-6 bg-slate-900' : 'w-2 bg-slate-300 hover:bg-slate-400'
                  }`}
                />
              ))}
            </div>
          ) : null}

          <div className="mt-8 flex justify-center">
            <Button asChild variant="outline">
              <Link href="/demos">Browse all demos</Link>
            </Button>
          </div>
        </div>

        {/* Back to top */}
        <a
          href="#mcp-setup"
          className="absolute bottom-6 left-1/2 -translate-x-1/2 text-xs font-medium text-slate-400 transition-colors hover:text-slate-700"
        >
          Back to top
        </a>
      </section>
    </div>
  )
}
