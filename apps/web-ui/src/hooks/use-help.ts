import { useState, useCallback, useEffect, useMemo } from 'react'
import { useLocalStorage } from './use-local-storage'
import { HELP_TOOLTIPS } from '@/lib/help-content'

export interface TourStep {
  target: string
  content: string
  title?: string
  placement?: 'top' | 'bottom' | 'left' | 'right' | 'center'
  disableBeacon?: boolean
  styles?: {
    options?: {
      primaryColor?: string
      backgroundColor?: string
      textColor?: string
      overlayColor?: string
    }
  }
}

export interface Tour {
  id: string
  name: string
  description: string
  steps: TourStep[]
  category: string
  estimatedTime: number
}

export interface OnboardingProgress {
  currentStep: number
  completedSteps: string[]
  isCompleted: boolean
  startedAt?: Date
  completedAt?: Date
}

export interface HelpContent {
  id: string
  title: string
  content: string
  category: string
  tags: string[]
  type: 'article' | 'video' | 'tooltip' | 'tour' | 'faq'
  relevanceScore: number
  searchTerms: string[]
  videoUrl?: string
  url?: string
  lastUpdated: Date
  readTime?: number
}

interface HelpState {
  isHelpOpen: boolean
  currentTour: string | null
  tourRunning: boolean
  showTooltips: boolean
  onboardingProgress: OnboardingProgress
  tourCompletions: Record<string, boolean>
  helpAnalytics: {
    searchQueries: string[]
    viewedContent: string[]
    completedTours: string[]
  }
}

const defaultOnboardingProgress: OnboardingProgress = {
  currentStep: 0,
  completedSteps: [],
  isCompleted: false,
}

const defaultHelpState: HelpState = {
  isHelpOpen: false,
  currentTour: null,
  tourRunning: false,
  showTooltips: true,
  onboardingProgress: defaultOnboardingProgress,
  tourCompletions: {},
  helpAnalytics: {
    searchQueries: [],
    viewedContent: [],
    completedTours: [],
  },
}

// Define available tours. These are real, anchored tours and always render.
export const TOURS: Record<string, Tour> = {
  'get-started': {
    id: 'get-started',
    name: 'Get started with Brain Researcher',
    description:
      'A quick orientation to the navigation, global search, and the help system. Run this from any page after signing in.',
    category: 'onboarding',
    estimatedTime: 3,
    steps: [
      {
        target: 'body',
        title: 'Welcome to Brain Researcher',
        content:
          "Brain Researcher is plan-once, run-anywhere: you design a workflow here, then hand it off to the coding agent you already use (Claude Code, Codex, Cursor) over MCP. This 60-second tour shows you where everything lives. Use the arrow keys or the buttons to move through it.",
        placement: 'center',
      },
      {
        target: '[data-tour="navigation"]',
        title: 'Main navigation',
        content:
          'Everything starts here: MCP setup, Datasets, Workflows, Demos, the Knowledge Graph, and Studio. A typical first session is: connect MCP, browse Workflows or the Knowledge Graph, then hand a workflow off to your agent.',
        placement: 'bottom',
      },
      {
        target: '[data-testid="nav-mcp"]',
        title: 'Connect your agent first',
        content:
          "The MCP tab is step one. It generates a personal token and gives you a config to paste into Cursor, Codex, or Claude Code so your agent can call Brain Researcher tools. The 'Connect your coding agent via MCP' tour walks through it.",
        placement: 'bottom',
      },
      {
        target: '[data-tour="search"]',
        title: 'Global search',
        content:
          'Search across datasets, workflows, and knowledge-graph nodes from anywhere. Press Ctrl+K to jump straight to it.',
        placement: 'bottom',
      },
      {
        target: '[data-tour="help-button"]',
        title: 'Help is always one click away',
        content:
          'Open this panel any time for tours, guides, and support. Press F1 to toggle it from anywhere in the app.',
        placement: 'bottom',
      },
    ],
  },
  'connect-mcp': {
    id: 'connect-mcp',
    name: 'Connect your coding agent via MCP',
    description:
      'Generate a token and wire Cursor, Codex, or Claude Code to Brain Researcher. Start this tour on the MCP page (/mcp/setup).',
    category: 'mcp',
    estimatedTime: 5,
    steps: [
      {
        target: '[data-testid="nav-mcp"]',
        title: 'Open the MCP setup page',
        content:
          'If you are not already on it, click MCP in the nav to open /mcp/setup. The rest of this tour highlights the four-step setup flow on that page.',
        placement: 'bottom',
      },
      {
        target: '[data-tour="mcp-token-panel"]',
        title: '1. Generate a personal token',
        content:
          "Click Generate token to mint your personal token (format brk_<kid>.<secret>). It is shown only once, so copy it now. Generating a new token rotates the old one immediately. Use the raw token value as BR_MCP_TOKEN — never put 'Bearer ' inside it.",
        placement: 'top',
      },
      {
        target: '[data-tour="mcp-config-snippet"]',
        title: '2. Paste the config into your client',
        content:
          "Pick Cursor, Codex, or Claude Code, then copy the snippet into your IDE's MCP configuration. Cursor and Windsurf take the full token in the JSON; Codex and Claude Code read BR_MCP_TOKEN from your shell. Prefer a local or air-gapped run? Use the Local (Advanced) tab: npx -y @brain-researcher/mcp-server start.",
        placement: 'top',
      },
      {
        target: '[data-tour="mcp-verify-guide"]',
        title: '3. Verify the connection',
        content:
          "In your agent, ask it to call server_info and system_self_test. Expect server_info ok=true and system_self_test overall=pass. If the client can't see those tools, have it inspect the exposed MCP tool names first.",
        placement: 'top',
      },
      {
        target: '[data-tour="mcp-handoff-guide"]',
        title: '4. Hand off a workflow',
        content:
          'Use the example prompt to have your agent prepare a runnable recipe. Remember the execution boundary: get_execution_recipe returns a recipe, not a completed analysis — success means real artifacts, logs, and a run manifest were produced and checked.',
        placement: 'top',
      },
    ],
  },
  'run-workflow-studio': {
    id: 'run-workflow-studio',
    name: 'Run a workflow in Studio',
    description:
      'Open a hosted Marimo notebook, run cells, and attach a run live. Start this tour on Studio (/hub).',
    category: 'studio',
    estimatedTime: 5,
    steps: [
      {
        target: '[data-tour="chat"]',
        title: 'Open Studio',
        content:
          'Click Studio in the nav to open /hub. Studio is a hosted Marimo notebook environment where you can run analysis cells against your data.',
        placement: 'bottom',
      },
      {
        target: '[data-tour="studio-runtime"]',
        title: 'Your hosted notebook',
        content:
          'This panel embeds a live Marimo runtime. On a fresh runtime it can take ~10–35 seconds to provision; cells auto-run when the notebook opens. If it ever looks blank, give it a moment — the iframe self-recovers.',
        placement: 'center',
      },
      {
        target: '[data-tour="studio-open-runtime"]',
        title: 'Open in a new tab',
        content:
          "Use 'Open runtime ↗' to pop the notebook out full-screen. The kernel serves one tab at a time, so the new tab may ask you to 'Take over session' from the embedded view — that's expected.",
        placement: 'bottom',
      },
      {
        target: '[data-testid="runs-sidebar-trigger"]',
        title: 'The Runs drawer',
        content:
          'Every run — whether launched in Studio or by your external agent over MCP — shows up here, auto-refreshing. This same drawer is where your results live (Runs replaced the old Vault page).',
        placement: 'left',
      },
      {
        target: '[data-testid="runs-sidebar-trigger"]',
        title: 'Attach a run into the notebook',
        content:
          "Open the Runs drawer and pick a run, then 'Attach in notebook' injects a live br.attach_run(...) cell so you can explore its artifacts inline. 'Hand off' instead sends the run to your coding agent over MCP.",
        placement: 'left',
      },
    ],
  },
  'explore-kg': {
    id: 'explore-kg',
    name: 'Explore the Knowledge Graph',
    description:
      'Search graph-backed evidence across Task, Disease, and ONVOC lenses before committing to a run. Start this tour on the Knowledge Graph page (/kg).',
    category: 'exploration',
    estimatedTime: 4,
    steps: [
      {
        target: '[data-testid="nav-knowledge graph"]',
        title: 'Open the Knowledge Graph',
        content:
          'Click Knowledge Graph in the nav to open /kg. The KG lets you explore datasets, tasks, diseases, and the evidence linking them — useful for grounding a hypothesis before you run anything.',
        placement: 'bottom',
      },
      {
        target: '[data-tour="kg-lens-tabs"]',
        title: 'Switch lenses',
        content:
          'Toggle between the Task, Disease, and ONVOC lenses. Each lens reorganizes the same graph around a different entry point so you can approach the evidence from the angle that fits your question.',
        placement: 'bottom',
      },
      {
        target: '[data-tour="kg-search"]',
        title: 'Search the graph',
        content:
          'Search for a brain region, task, disease, or concept to focus the graph. Selecting a node reveals its neighbors and the datasets and evidence connected to it.',
        placement: 'right',
      },
      {
        target: '[data-tour="kg-explorer"]',
        title: 'Read the evidence, then act',
        content:
          'The explorer surfaces connected nodes and the evidence behind each link. When something looks worth running, jump to Workflows or hand the context off to your agent — a graph view is evidence, not a claim on its own.',
        placement: 'top',
      },
    ],
  },
  'find-results': {
    id: 'find-results',
    name: 'Find your results (Runs)',
    description:
      'Where runs and their artifacts live now that Vault has moved into Studio. Start this tour on Studio (/hub).',
    category: 'results',
    estimatedTime: 3,
    steps: [
      {
        target: '[data-tour="chat"]',
        title: 'Results live in Studio',
        content:
          'The old Vault and Analyses pages have been retired. Your runs and their artifacts now live in the Runs drawer inside Studio, so open Studio (/hub) to find them.',
        placement: 'bottom',
      },
      {
        target: '[data-testid="runs-sidebar-trigger"]',
        title: 'Open the Runs drawer',
        content:
          'Click Runs to open the drawer. The count badge shows how many runs you have, and a blue dot marks active runs. The list auto-refreshes, so you can watch a run progress without reloading.',
        placement: 'left',
      },
      {
        target: '[data-testid="runs-sidebar-trigger"]',
        title: 'Filter and inspect a run',
        content:
          'Inside the drawer, the All / Active / Recent / Failed tabs filter your runs. Each row shows status, dataset, task, duration, and artifact count — and whether it came from Studio or an external agent.',
        placement: 'left',
      },
      {
        target: '[data-testid="runs-sidebar-trigger"]',
        title: 'Attach or hand off',
        content:
          "From any run, 'Attach in notebook' drops a br.attach_run(...) cell into the open notebook to explore its artifacts, while 'Hand off' sends the run to your coding agent over MCP. Every result stays tied to the evidence and run manifest behind it.",
        placement: 'left',
      },
    ],
  },
}

export interface HelpFaq {
  id: string
  question: string
  answer: string
  category: string
  tags: string[]
  relatedRoute?: string
}

export const HELP_FAQS: HelpFaq[] = [
  {
    id: 'studio-vs-mcp',
    question: "What's the difference between Studio and MCP?",
    answer:
      "Two ways to use BR. Studio (/hub, /studio) is a hosted Marimo notebook in the browser where you open a notebook, run cells, and attach runs. MCP connects BR to a coding agent you already run (Claude Code, Codex, Cursor) so it can search workflows, pull KG evidence, and generate runnable recipes from your own terminal. The motto is 'plan once, run anywhere' - same BR tools either place. Use Studio for an in-browser session; use MCP to drive BR from your IDE/agent.",
    category: 'getting-started',
    tags: ['studio', 'mcp', 'overview'],
    relatedRoute: '/mcp/setup',
  },
  {
    id: 'get-mcp-token',
    question: 'How do I get an MCP token?',
    answer:
      "Go to /mcp/setup and sign in, then under 'Personal MCP token' click Generate token (or Rotate token if you already have one). The secret is shown once - copy it immediately. There is one active token per user, so generating a new one rotates and immediately revokes the previous one. The token format is brk_<kid>.<secret>. Paste it into your IDE's MCP config or export it as BR_MCP_TOKEN.",
    category: 'mcp',
    tags: ['token', 'setup', 'auth'],
    relatedRoute: '/mcp/setup',
  },
  {
    id: 'agent-cant-see-mcp-tools',
    question: "My agent can't see the MCP tools. How do I fix it?",
    answer:
      "Most often the token is wrong. Use the RAW brk_<kid>.<secret> value in BR_MCP_TOKEN - never put 'Bearer ' inside the token; the config adds Authorization: Bearer ${BR_MCP_TOKEN} for you. Confirm the server URL is https://${PUBLIC_HOSTNAME}/mcp and the Accept header is 'application/json, text/event-stream'. Reload your shell so BR_MCP_TOKEN is set, restart the client, then ask it to call server_info (expect ok=true) and system_self_test (expect overall=pass). If it still can't see tools, have it inspect the exposed MCP tool names before trying anything else.",
    category: 'troubleshooting',
    tags: ['mcp', 'tools', 'token', 'bearer'],
    relatedRoute: '/mcp/setup',
  },
  {
    id: 'verify-mcp-connection',
    question: 'How do I verify my MCP connection is working?',
    answer:
      'Ask your agent to run the two health-check tools: server_info should return ok=true, and system_self_test should return overall=pass. The /mcp/setup page has ready-made smoke prompts for Codex and Claude Code. Always run these before claiming the server is connected or before requesting a workflow recipe.',
    category: 'mcp',
    tags: ['server_info', 'system_self_test', 'health-check'],
    relatedRoute: '/mcp/setup',
  },
  {
    id: 'notebook-blank-not-loading',
    question: "My Studio notebook is blank or won't load. What do I do?",
    answer:
      "Give it a moment - on a fresh runtime the notebook iframe self-recovers, usually within about 10-35 seconds, and cells auto-run on open. If it's still blank after that, refresh/reopen the notebook to reconnect the session (a Studio session can expire). 'Open in new tab' opens the runtime full-screen, which also helps. To attach runs you must wait until the runtime is ready.",
    category: 'studio',
    tags: ['notebook', 'blank', 'loading', 'marimo'],
    relatedRoute: '/hub',
  },
  {
    id: 'where-are-my-results',
    question: 'Where do my run results go?',
    answer:
      "Live and recent runs appear in the Runs drawer in Studio (the 'Runs' button), with tabs for All / Active / Recent / Failed and a badge for each run's status and source (Studio vs External agent). Persisted results, analyses, and output files live in the Vault (/vault and the analyses pages). From a run you can click 'Attach in notebook' to inject a br.attach_run(...) cell, or 'Hand off' to continue it in your agent. With MCP, use run_list / run_get / run_logs / artifact_list to inspect the same runs.",
    category: 'results',
    tags: ['runs', 'vault', 'results', 'artifacts'],
    relatedRoute: '/vault',
  },
  {
    id: 'does-recipe-run-analysis',
    question: 'Does get_execution_recipe actually run the analysis?',
    answer:
      "No. get_execution_recipe returns a RECIPE - the exact command, required inputs, expected artifacts, and any blockers - not a completed analysis. This is BR's 'execution boundary': preparing a plan is not proof it ran. Execution only counts as successful when the expected artifacts, logs, and run manifest are actually produced and inspected. The recipe is what you (or your agent) then run locally, in a container, on Neurodesk, or on a cluster.",
    category: 'mcp',
    tags: ['execution-boundary', 'recipe', 'get_execution_recipe'],
    relatedRoute: '/mcp/setup',
  },
  {
    id: 'local-airgapped-mcp',
    question: 'Can I run BR\'s MCP server locally or air-gapped?',
    answer:
      "Yes. Instead of the hosted cloud URL, run the server locally with: npx -y @brain-researcher/mcp-server start. For local-only data processing or air-gapped use, set ALLOW_NETWORK=false and ALLOWED_ROOTS=/data so the server only touches the paths you allow. This is the 'Local (Advanced)' tab on /mcp/setup.",
    category: 'mcp',
    tags: ['local', 'air-gapped', 'npx', 'offline'],
    relatedRoute: '/mcp/setup',
  },
  {
    id: 'data-handling-privacy',
    question: 'How does BR handle my data?',
    answer:
      'With the hosted cloud MCP and Studio, requests go to ${PUBLIC_HOSTNAME} over an authenticated connection tied to your personal token. If you need data to stay on your own machine, use the local MCP server (npx -y @brain-researcher/mcp-server start) with ALLOW_NETWORK=false and ALLOWED_ROOTS scoped to the directories you permit, so the server never reaches the network and only reads the roots you list. Tokens are personal, one active per user, and can be rotated or revoked at any time on /mcp/setup.',
    category: 'mcp',
    tags: ['data', 'privacy', 'security', 'local'],
    relatedRoute: '/mcp/setup',
  },
  {
    id: 'what-is-a-claim-record',
    question: "What does 'claim record' or 'grounding' mean in BR?",
    answer:
      "BR's core philosophy: a generated output is NOT a scientific claim by default. A claim record turns researcher judgment into executable commitments - the allowed alternatives, validation rules, provenance, and the boundaries beyond which a result shouldn't be read. 'Grounding' means tying a statement to real BR evidence (a dataset, workflow, KG node, or run) rather than asserting it. Every result stays linked to the evidence behind it and to its stated limits.",
    category: 'results',
    tags: ['claim', 'grounding', 'provenance', 'philosophy'],
    relatedRoute: '/kg',
  },
  {
    id: 'how-to-cite',
    question: 'How do I cite a BR result or claim?',
    answer:
      'Cite the result through its provenance, not as a bare statement. Each run and analysis keeps its evidence trail (dataset + version, workflow, parameters, run manifest, and KG evidence), so reference the specific run/analysis in Vault and the datasets/workflows it grounds in. Because outputs aren\'t claims by default, report the verified claim together with its boundaries and validation rules rather than the raw output alone.',
    category: 'results',
    tags: ['citation', 'provenance', 'reproducibility', 'vault'],
    relatedRoute: '/vault',
  },
  {
    id: 'attach-run-in-notebook',
    question: 'How do I bring a run into my Studio notebook?',
    answer:
      "Open the Runs drawer in Studio, find the run, and click 'Attach in notebook'. BR injects a live cell at the end of the notebook: import brain_researcher.sdk as br; br.attach_run('<run_id>'). The runtime must be ready first - if it isn't, open the notebook and wait for it to load, then retry. You can also 'Hand off' a run to continue it in your connected coding agent over MCP.",
    category: 'studio',
    tags: ['attach', 'runs', 'notebook', 'sdk'],
    relatedRoute: '/hub',
  },
]

export interface HelpGuide {
  title: string
  description: string
  href: string
  kind: string
}

export const HELP_GUIDES: HelpGuide[] = [
  {
    title: 'Connect Brain Researcher to your coding agent (MCP setup)',
    description:
      '4-step flow: generate a brk_ token, paste the config into Claude Code/Codex/Cursor, verify with server_info + system_self_test, then hand off a workflow.',
    href: '/mcp/setup',
    kind: 'walkthrough',
  },
  {
    title: 'Open a hosted notebook in Studio',
    description:
      'Launch a Marimo notebook, run cells, and attach runs in the hosted Studio workspace.',
    href: '/studio',
    kind: 'walkthrough',
  },
  {
    title: 'Explore graph-backed evidence in the Knowledge Graph',
    description:
      'Search datasets and nodes and inspect KG evidence across task, disease, and ONVOC views before committing to a run.',
    href: '/kg',
    kind: 'reference',
  },
  {
    title: 'Browse the worked case reports',
    description:
      'Open the demo catalog of public use-case reports with replay evidence, artifact packages, and MCP handoff context.',
    href: '/demos',
    kind: 'demo',
  },
  {
    title: 'Case 1: NeuroMark schizophrenia multiverse',
    description:
      'Replay a leading case report on multiverse analysis using NeuroMark functional network connectivity.',
    href: '/demos/case1-neuromark-schizophrenia-multiverse',
    kind: 'demo',
  },
  {
    title: 'Case 2: Cocaine network segregation robustness',
    description:
      'Walk through multiverse robustness of resting-state network segregation in cocaine use disorder.',
    href: '/demos/case2-cocaine-network-segregation',
    kind: 'demo',
  },
  {
    title: 'Case 3: Connectome hubness and decoding',
    description:
      'Inspect a case report on high-dimensional connectome matrices, hubness, decoding, and generative fidelity.',
    href: '/demos/case3-connectome-hubness-decoding',
    kind: 'demo',
  },
  {
    title: 'Case 4: Ingroup-outgroup cultural boundaries',
    description:
      'Review the cross-cultural ingroup-outgroup case report and its unified neural architecture argument.',
    href: '/demos/case4-ingroup-outgroup-cultural-boundaries',
    kind: 'demo',
  },
  {
    title: 'Bounded self-evolving research: Discovery',
    description:
      'See a bounded autoresearch discovery case report using TRIBE stimulus discovery as the worked example.',
    href: '/demos/bounded-self-evolving-discovery',
    kind: 'demo',
  },
  {
    title: 'Bounded self-evolving research: Predictive',
    description:
      'See a bounded autoresearch predictive case report on calibrated resting-state functional connectivity.',
    href: '/demos/bounded-self-evolving-predictive',
    kind: 'demo',
  },
  {
    title: 'Read the documentation',
    description:
      'Start from the docs landing page for the Help Center, resources, and platform overview.',
    href: '/docs',
    kind: 'reference',
  },
  {
    title: 'Browse the workflow library',
    description:
      'Discover reusable workflows and pipelines you can plan once and run anywhere via your coding agent.',
    href: '/library',
    kind: 'reference',
  },
]

const slugify = (value: string): string =>
  value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')

const buildHelpIndex = (): HelpContent[] => {
  const tooltipEntries: HelpContent[] = Object.values(HELP_TOOLTIPS).map((tooltip) => ({
    id: `tooltip-${tooltip.id}`,
    title: tooltip.title,
    content: tooltip.description,
    category: tooltip.category,
    tags: [tooltip.category],
    type: 'tooltip',
    relevanceScore: 0,
    searchTerms: [
      tooltip.title,
      tooltip.description,
      tooltip.category,
      tooltip.relatedTourId ?? '',
    ]
      .join(' ')
      .toLowerCase()
      .split(/\s+/)
      .filter(Boolean),
    videoUrl: tooltip.videoUrl,
    url: tooltip.learnMoreUrl,
    lastUpdated: new Date(),
  }))

  const tourEntries: HelpContent[] = Object.values(TOURS).map((tour) => {
    const stepText = tour.steps.map((step) => `${step.title ?? ''} ${step.content}`).join(' ')
    const searchTerms = `${tour.name} ${tour.description} ${tour.category} ${stepText}`
      .toLowerCase()
      .split(/\s+/)
      .filter(Boolean)

    return {
      id: `tour-${tour.id}`,
      title: tour.name,
      content: tour.description,
      category: tour.category,
      tags: [tour.category],
      type: 'tour',
      relevanceScore: 0,
      searchTerms,
      lastUpdated: new Date(),
      readTime: tour.estimatedTime,
    }
  })

  const faqEntries: HelpContent[] = HELP_FAQS.map((f) => ({
    id: `faq-${f.id}`,
    title: f.question,
    content: f.answer,
    category: f.category,
    tags: f.tags,
    type: 'faq',
    relevanceScore: 0,
    searchTerms: `${f.question} ${f.answer} ${f.tags.join(' ')}`
      .toLowerCase()
      .split(/\s+/)
      .filter(Boolean),
    url: f.relatedRoute || undefined,
    lastUpdated: new Date(),
  }))

  const guideEntries: HelpContent[] = HELP_GUIDES.map((g) => ({
    id: `guide-${slugify(g.title)}`,
    title: g.title,
    content: g.description,
    category: 'guides',
    tags: [g.kind],
    type: 'article',
    relevanceScore: 0,
    searchTerms: `${g.title} ${g.description}`
      .toLowerCase()
      .split(/\s+/)
      .filter(Boolean),
    url: g.href,
    lastUpdated: new Date(),
  }))

  return [...tooltipEntries, ...tourEntries, ...faqEntries, ...guideEntries]
}

export function useHelp() {
  const [helpState, setHelpState] = useLocalStorage<HelpState>('help-state', defaultHelpState)
  const [searchResults, setSearchResults] = useState<HelpContent[]>([])
  const [isSearching, setIsSearching] = useState(false)
  const helpIndex = useMemo(() => buildHelpIndex(), [])

  // Toggle help panel
  const toggleHelp = useCallback(() => {
    setHelpState(prev => ({ ...prev, isHelpOpen: !prev.isHelpOpen }))
  }, [setHelpState])

  // Start a tour
  const startTour = useCallback((tourId: string) => {
    const tour = TOURS[tourId]
    if (!tour) return

    setHelpState(prev => ({
      ...prev,
      currentTour: tourId,
      tourRunning: true,
    }))

    // Track tour start
    trackHelpEvent('tour_started', { tourId, tourName: tour.name })
  }, [setHelpState])

  // Complete a tour
  const completeTour = useCallback((tourId: string) => {
    setHelpState(prev => ({
      ...prev,
      currentTour: null,
      tourRunning: false,
      tourCompletions: { ...prev.tourCompletions, [tourId]: true },
      helpAnalytics: {
        ...prev.helpAnalytics,
        completedTours: [...prev.helpAnalytics.completedTours, tourId],
      },
    }))

    // Track tour completion
    trackHelpEvent('tour_completed', { tourId })
  }, [setHelpState])

  // Skip/stop tour
  const stopTour = useCallback(() => {
    setHelpState(prev => ({
      ...prev,
      currentTour: null,
      tourRunning: false,
    }))
  }, [setHelpState])

  // Toggle tooltips
  const toggleTooltips = useCallback(() => {
    setHelpState(prev => ({ ...prev, showTooltips: !prev.showTooltips }))
  }, [setHelpState])

  // Update onboarding progress
  const updateOnboardingProgress = useCallback((step: number, stepId?: string) => {
    setHelpState(prev => ({
      ...prev,
      onboardingProgress: {
        ...prev.onboardingProgress,
        currentStep: step,
        completedSteps: stepId
          ? Array.from(new Set([...prev.onboardingProgress.completedSteps, stepId]))
          : prev.onboardingProgress.completedSteps,
        isCompleted: step >= 5, // Assume 5 steps in onboarding
        completedAt: step >= 5 ? new Date() : prev.onboardingProgress.completedAt,
      },
    }))
  }, [setHelpState])

  // Search help content
  const searchHelp = useCallback(async (query: string) => {
    if (!query.trim()) {
      setSearchResults([])
      return
    }

    setIsSearching(true)

    // Track search query
    setHelpState(prev => ({
      ...prev,
      helpAnalytics: {
        ...prev.helpAnalytics,
        searchQueries: [...prev.helpAnalytics.searchQueries.slice(-20), query], // Keep last 20 searches
      },
    }))

    try {
      const terms = query
        .toLowerCase()
        .split(/\s+/)
        .map((term) => term.trim())
        .filter(Boolean)

      const scored = helpIndex
        .map((item) => {
          const haystack = `${item.title} ${item.content} ${item.tags.join(' ')} ${item.category}`.toLowerCase()
          let score = 0
          for (const term of terms) {
            if (item.title.toLowerCase().includes(term)) score += 3
            if (item.tags.some((tag) => tag.toLowerCase().includes(term))) score += 2
            if (haystack.includes(term)) score += 1
          }
          return { ...item, relevanceScore: score }
        })
        .filter((item) => item.relevanceScore > 0)
        .sort((a, b) => b.relevanceScore - a.relevanceScore)
        .slice(0, 20)

      setSearchResults(scored)
      trackHelpEvent('search_performed', { query, resultsCount: scored.length })
    } catch (error) {
      console.error('Help search error:', error)
      setSearchResults([])
    } finally {
      setIsSearching(false)
    }
  }, [setHelpState, helpIndex])

  // Track help content view
  const trackContentView = useCallback((contentId: string) => {
    setHelpState(prev => ({
      ...prev,
      helpAnalytics: {
        ...prev.helpAnalytics,
        viewedContent: Array.from(new Set([...prev.helpAnalytics.viewedContent, contentId])),
      },
    }))

    trackHelpEvent('content_viewed', { contentId })
  }, [setHelpState])

  // Reset onboarding
  const resetOnboarding = useCallback(() => {
    setHelpState(prev => ({
      ...prev,
      onboardingProgress: { ...defaultOnboardingProgress, startedAt: new Date() },
    }))
  }, [setHelpState])

  // Keyboard shortcut handling
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      // F1 key or Ctrl+?
      if (event.key === 'F1' || (event.ctrlKey && event.key === '?')) {
        event.preventDefault()
        toggleHelp()
      }
      // Escape to close help
      if (event.key === 'Escape' && helpState.isHelpOpen) {
        setHelpState(prev => ({ ...prev, isHelpOpen: false }))
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [toggleHelp, helpState.isHelpOpen, setHelpState])

  return {
    // State
    isHelpOpen: helpState.isHelpOpen,
    currentTour: helpState.currentTour,
    tourRunning: helpState.tourRunning,
    showTooltips: helpState.showTooltips,
    onboardingProgress: helpState.onboardingProgress,
    tourCompletions: helpState.tourCompletions,
    helpAnalytics: helpState.helpAnalytics,
    searchResults,
    isSearching,
    helpContent: helpIndex,
    tours: TOURS,
    faqs: HELP_FAQS,
    guides: HELP_GUIDES,

    // Actions
    toggleHelp,
    startTour,
    completeTour,
    stopTour,
    toggleTooltips,
    updateOnboardingProgress,
    searchHelp,
    trackContentView,
    resetOnboarding,
  }
}

// Analytics helper
function trackHelpEvent(event: string, properties?: Record<string, any>) {
  // In a real implementation, this would send to analytics service
  console.log('Help analytics:', { event, properties, timestamp: new Date() })
}
