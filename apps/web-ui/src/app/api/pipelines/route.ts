/**
 * Pipeline Browser API
 *
 * Serves pipeline metadata from configs/catalog/pipelines.yaml as JSON
 * for dynamic UI rendering. Filters to only expose safe fields.
 */

import { NextResponse } from "next/server"
import fs from "fs"
import path from "path"
import yaml from "js-yaml"
export const dynamic = 'force-dynamic'

interface PipelineStep {
  order: number
  tool: string
  description?: string
  params?: Record<string, unknown>
}

interface Pipeline {
  id: string
  name: string
  description: string
  modalities: string[]
  steps: PipelineStep[]
}

interface PipelineResponse {
  id: string
  name: string
  description: string
  modalities: string[]
  steps: {
    order: number
    tool: string
    description: string
    paramNames: string[]
  }[]
}

export async function GET() {
  try {
    // Resolve path to pipelines.yaml from the repo root.
    const webUiRoot = process.cwd()
    const yamlCandidates = [
      path.join(webUiRoot, "configs/catalog/pipelines.yaml"),
      path.join(webUiRoot, "..", "configs/catalog/pipelines.yaml"),
      path.join(webUiRoot, "..", "..", "configs/catalog/pipelines.yaml"),
      path.join(webUiRoot, "..", "..", "..", "configs/catalog/pipelines.yaml"),
    ]
    const yamlPath = yamlCandidates.find((candidate) => fs.existsSync(candidate))

    if (!yamlPath) {
      console.error(`pipelines.yaml not found; tried: ${yamlCandidates.join(", ")}`)
      return NextResponse.json(
        { error: "Pipeline configuration not found" },
        { status: 500 }
      )
    }

    const content = fs.readFileSync(yamlPath, "utf8")
    const rawData = yaml.load(content) as { pipelines?: Pipeline[] } | Pipeline[]

    // Handle both formats: { pipelines: [...] } and [...]
    const data: Pipeline[] = Array.isArray(rawData)
      ? rawData
      : rawData?.pipelines ?? []

    if (!Array.isArray(data)) {
      return NextResponse.json(
        { error: "Invalid pipeline configuration format" },
        { status: 500 }
      )
    }

    // Filter to only expose safe fields (no secrets, no internal paths)
    const pipelines: PipelineResponse[] = data
      .filter((p) => p.id && p.name) // Skip malformed entries
      .map((p) => ({
        id: p.id,
        name: p.name,
        description: p.description || "",
        modalities: p.modalities || [],
        steps: (p.steps || []).map((s) => ({
          order: s.order || 0,
          tool: s.tool || "",
          description: s.description || "",
          // Only expose param names, not values (which may contain placeholders or defaults)
          paramNames: s.params ? Object.keys(s.params) : [],
        })),
      }))

    return NextResponse.json({
      pipelines,
      count: pipelines.length,
    })
  } catch (error) {
    console.error("Failed to load pipelines:", error)
    return NextResponse.json(
      { error: "Failed to load pipeline configuration" },
      { status: 500 }
    )
  }
}
