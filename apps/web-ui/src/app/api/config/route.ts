import { NextResponse } from 'next/server'

export const dynamic = 'force-dynamic'

const resolveSupabaseProviderList = (raw?: string | null) => {
  const defaultProviders = ['google', 'github']
  const providers = (raw || '')
    .split(',')
    .map((value) => value.trim().toLowerCase())
    .filter(Boolean)
  return providers.length ? providers : defaultProviders
}

const resolveAuthProvider = () => {
  const supabaseEnabled = Boolean(
    process.env.SUPABASE_URL ||
      process.env.NEXT_PUBLIC_SUPABASE_URL ||
      process.env.SUPABASE_ANON_KEY ||
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
  )

  const raw = (process.env.BR_AUTH_PROVIDER || process.env.NEXT_PUBLIC_AUTH_MODE || '')
    .trim()
    .toLowerCase()

  if (raw === 'supabase') return supabaseEnabled ? 'supabase' : 'nextauth'
  if (raw === 'nextauth') return 'nextauth'
  if (raw === 'both') return supabaseEnabled ? 'both' : 'nextauth'

  return supabaseEnabled ? 'supabase' : 'nextauth'
}

export async function GET() {
  const useProxy = (process.env.NEXT_PUBLIC_USE_API_PROXY || 'true').toLowerCase() !== 'false'
  const explicitPublicOrchestratorBase = process.env.NEXT_PUBLIC_ORCHESTRATOR_URL || ''
  const explicitPublicAgentBase =
    process.env.NEXT_PUBLIC_AGENT_API || ''
  const orchestratorBase = useProxy ? '' : explicitPublicOrchestratorBase
  const agentBase = useProxy ? '/internal/agent' : explicitPublicAgentBase || '/internal/agent'
  const websocketBase = process.env.NEXT_PUBLIC_WS_URL || '/ws'

  const niclipApi = (process.env.NEXT_PUBLIC_NICLIP_API || '').trim()

  const supabaseProviders = resolveSupabaseProviderList(
    process.env.SUPABASE_OAUTH_PROVIDERS || process.env.NEXT_PUBLIC_SUPABASE_OAUTH_PROVIDERS
  )

  const services: Record<string, string> = {
    agent: agentBase,
    kg: '/api/kg',
    brKg: '/api/br-kg',
    orchestrator: orchestratorBase,
    websocket: websocketBase,
  }

  if (niclipApi) {
    services.niclip = niclipApi
  }

  const health: Record<string, string> = {
    agent: '/api/health',
    kg: '/api/kg/health',
    brKg: '/api/br-kg/health',
    orchestrator: orchestratorBase
      ? `${orchestratorBase.replace(/\/$/, '')}/health`
      : '/health',
  }

  if (niclipApi) {
    health.niclip = `${niclipApi.replace(/\/$/, '')}/health`
  }

  const config = {
    services,
    pathMappings: {
      '/api/pipelines': '/jobs',
      '/api/executions': '/jobs',
      '/api/search_and_expand': '/api/search_and_expand',
      '/api/openneuro': '/api/openneuro',
    },
    health,
    auth: {
      provider: resolveAuthProvider(),
      supabase: {
        providers: supabaseProviders,
      },
    },
  }

  return NextResponse.json(config)
}
