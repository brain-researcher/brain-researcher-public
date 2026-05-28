import { NextRequest, NextResponse } from 'next/server'
import { resolveKgBaseUrl } from '@/lib/server/kg-proxy'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

/**
 * GET /api/kg/pipelines
 *
 * Fetches all pipeline templates from BR-KG with their associated
 * operations, tool families, and recommended datasets.
 *
 * Returns: {
 *   pipelines: Array<{
 *     id: string
 *     name: string
 *     ops: string[]
 *     preferred_families: string[]
 *     datasets: string[]
 *   }>
 * }
 */
export async function GET(request: NextRequest) {
  try {
    const baseUrl = resolveKgBaseUrl()

    // Cypher query to fetch pipeline templates with relationships
    const cypherQuery = `
      MATCH (p:PipelineTemplate)
      OPTIONAL MATCH (p)-[:HAS_STEP]->(o:Operation)
      OPTIONAL MATCH (p)-[:USES_FAMILY]->(f:ToolFamily)
      OPTIONAL MATCH (p)-[:RECOMMENDED_FOR]->(d:DatasetFamily)
      RETURN
        p.id AS id,
        p.name AS name,
        collect(DISTINCT o.id) AS ops,
        collect(DISTINCT f.id) AS preferred_families,
        collect(DISTINCT d.id) AS datasets
      ORDER BY p.name
    `

    const queryUrl = `${baseUrl}/api/cypher`

    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 5000)

    const response = await fetch(queryUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: cypherQuery }),
      signal: controller.signal,
      cache: 'no-store',
    })

    clearTimeout(timeout)

    if (!response.ok) {
      console.error(
        `BR-KG cypher query failed: ${response.status} ${response.statusText}`
      )
      return NextResponse.json(
        { error: 'Failed to fetch pipelines from knowledge graph' },
        { status: response.status }
      )
    }

    const data = await response.json()

    // Transform Cypher result format to our API format (Neo4j HTTP)
    const pipelines = (data.results || data.data || []).map((row: any) => ({
      id: row.id || row[0],
      name: row.name || row[1],
      ops: (row.ops || row[2] || []).filter(Boolean),
      preferred_families: (row.preferred_families || row[3] || []).filter(Boolean),
      datasets: (row.datasets || row[4] || []).filter(Boolean),
    }))

    // If Neo4j returns rows, return them
    if (pipelines.length) {
      return NextResponse.json({ pipelines })
    }

    // Fallback: return empty list to avoid hard failure
    return NextResponse.json({ pipelines: [] })
  } catch (error: any) {
    // Fallback: read static mapping YAML if Neo4j HTTP isn't available
    try {
      const { readFile } = await import('node:fs/promises')
      const { join } = await import('node:path')
      const { existsSync } = await import('node:fs')
      const YAML = (await import('yaml')).default

      const root = process.cwd()
      const rootCandidates = [root, join(root, '..'), join(root, '..', '..'), join(root, '..', '..', '..')]
      const mappingPath =
        rootCandidates
          .map((candidate) => join(candidate, 'tools', 'etl', 'kg_mapping_pipeline_templates.yaml'))
          .find((candidate) => existsSync(candidate)) ??
        join(root, 'tools', 'etl', 'kg_mapping_pipeline_templates.yaml')
      const datasetPath =
        rootCandidates
          .map((candidate) => join(candidate, 'tools', 'etl', 'kg_mapping_pipeline_datasets.yaml'))
          .find((candidate) => existsSync(candidate)) ??
        join(root, 'tools', 'etl', 'kg_mapping_pipeline_datasets.yaml')

      const rawPipelines = YAML.parse(await readFile(mappingPath, 'utf-8'))?.pipelines
      const rawDatasetRecs = YAML.parse(await readFile(datasetPath, 'utf-8')) || []

      const datasetMap = new Map<string, string[]>()
      for (const rec of rawDatasetRecs || []) {
        if (rec?.pipeline_id && rec?.dataset_family) {
          const arr = datasetMap.get(rec.pipeline_id) || []
          arr.push(rec.dataset_family)
          datasetMap.set(rec.pipeline_id, arr)
        }
      }

      const pipelines = (Array.isArray(rawPipelines)
        ? rawPipelines
        : Object.values(rawPipelines || {})
      ).map((p: any) => ({
        id: p.id,
        name: p.name,
        ops: p.operations || [],
        preferred_families: p.prefer_families || [],
        datasets: datasetMap.get(p.id) || [],
      }))

      return NextResponse.json({ pipelines, source: 'file_fallback' })
    } catch (fallbackError) {
      if (error?.name === 'AbortError') {
        console.error('BR-KG pipelines request timed out')
        return NextResponse.json(
          { error: 'Request timed out', pipelines: [] },
          { status: 504 }
        )
      }

      console.error('Error fetching pipelines:', error, 'fallbackError:', fallbackError)
      return NextResponse.json(
        { error: 'Internal server error', pipelines: [] },
        { status: 500 }
      )
    }
  }
}
