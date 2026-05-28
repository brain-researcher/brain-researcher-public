import { NextRequest, NextResponse } from 'next/server'

import { dump as dumpYaml } from 'js-yaml'

import { forwardAuthHeaders, resolveOrchestratorBaseUrl } from '@/lib/server/downstream'
import { requireAuth } from '@/lib/server/orchestrator-proxy'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const shouldInclude = (value: string | null) => value !== 'false'

export async function GET(
  req: NextRequest,
  { params }: { params: { analysisId: string } },
) {
  const analysisId = typeof params.analysisId === 'string' ? params.analysisId.trim() : ''
  if (!analysisId) {
    return NextResponse.json({ detail: 'analysisId is required.' }, { status: 400 })
  }

  const authResponse = await requireAuth(req)
  if (authResponse) return authResponse

  const format = (req.nextUrl.searchParams.get('format') || 'json').toLowerCase()
  if (format !== 'json' && format !== 'yaml') {
    return NextResponse.json(
      { detail: "Only 'json' and 'yaml' are supported for observation export." },
      { status: 400 },
    )
  }

  const includeArtifacts = shouldInclude(req.nextUrl.searchParams.get('includeArtifacts'))
  const includeProvenance = shouldInclude(req.nextUrl.searchParams.get('includeProvenance'))
  const includeCitations = shouldInclude(req.nextUrl.searchParams.get('includeCitations'))
  const includeEnvironment = shouldInclude(req.nextUrl.searchParams.get('includeEnvironment'))

  const orchBase = resolveOrchestratorBaseUrl()
  const url = `${orchBase}/api/jobs/${encodeURIComponent(analysisId)}/observation`
  const headers = forwardAuthHeaders(req)

  try {
    const res = await fetch(url, { cache: 'no-store', headers })
    if (!res.ok) {
      let payload: any = null
      try {
        payload = await res.json()
      } catch {
        payload = { detail: await res.text() }
      }
      return NextResponse.json(payload, { status: res.status })
    }

    const observation = await res.json()
    const filtered = typeof structuredClone === 'function'
      ? structuredClone(observation)
      : JSON.parse(JSON.stringify(observation))

    if (!includeArtifacts) {
      delete filtered.artifacts
    }

    if (!includeProvenance) {
      delete filtered.provenance
      delete filtered.steps
    }

    if (!includeCitations) {
      if (filtered.run_card && Array.isArray(filtered.run_card.citations)) {
        filtered.run_card.citations = []
      }
      if (filtered.runCard && Array.isArray(filtered.runCard.citations)) {
        filtered.runCard.citations = []
      }
    }

    if (!includeEnvironment) {
      if (filtered.provenance && filtered.provenance.environment) {
        delete filtered.provenance.environment
      }
    }

    if (format === 'yaml') {
      const body = dumpYaml(filtered, { noRefs: true })
      return new NextResponse(body, {
        status: 200,
        headers: {
          'content-type': 'text/yaml; charset=utf-8',
          'content-disposition': `attachment; filename="observation_${analysisId}.yaml"`,
        },
      })
    }

    const body = JSON.stringify(filtered, null, 2)
    return new NextResponse(body, {
      status: 200,
      headers: {
        'content-type': 'application/json; charset=utf-8',
        'content-disposition': `attachment; filename="observation_${analysisId}.json"`,
      },
    })
  } catch (err) {
    return NextResponse.json(
      { error: 'orchestrator_unreachable', detail: String(err) },
      { status: 502 },
    )
  }
}

