import { NextRequest } from 'next/server'
import fs from 'fs'
import path from 'path'
import yaml from 'js-yaml'

export const dynamic = 'force-dynamic'

// Paths to config files (relative to project root)
const PROJECT_ROOT =
  process.env.PROJECT_ROOT ||
  process.env.NEXT_PUBLIC_PROJECT_ROOT ||
  process.cwd()
const TOOLSET_YAML_PATH = path.join(PROJECT_ROOT, 'configs/grandmaster/toolset_vfinal.yaml')
const TOOLS_JSON_PATH = path.join(PROJECT_ROOT, 'configs/tools_catalog_merged.json')
const CAPABILITIES_YAML_PATH = path.join(PROJECT_ROOT, 'configs/catalog/capabilities.yaml')
// Note: boutiques_index.json tools are already included in tools_catalog_merged.json

type ToolRow = {
  name: string
  display_name?: string
  description?: string
  runtime?: string
  runtime_kind?: string
  domain?: string
  modality?: string[]
  path?: string
  module?: string
  container_image?: string
  entrypoint?: string
  package?: string
  category?: string
  stage?: string
  layer?: string
  cost_tier?: string
  origin?: string
  impl?: string
  tags?: string[]
  function?: string
  risk?: string
  exposure?: string
  consumes?: Record<string, string> | string[]
  produces?: Record<string, string> | string[]
  confidence?: string
  source: string
}

type Category = { key: string; name: string; description?: string; examples?: string[] }

type GrandmasterTool = {
  id: string
  layer?: string
  stage?: string
  cost_tier?: string
  origin?: string
  impl?: string
  runtime?: {
    kind?: string
    target?: string
    entrypoint?: string
  }
}

type GrandmasterYaml = {
  version?: string
  stages?: Array<{ id: string; description: string }>
  cost_tiers?: Record<string, string>
  atomic_tools?: GrandmasterTool[]
}

type CatalogTool = {
  name: string
  description?: string
  runtime_kind?: string
  domain?: string
  function?: string
  risk?: string
  exposure?: string
  tags?: string[]
  python_module?: string
}

type CatalogJson = {
  tools?: CatalogTool[]
}

type CapabilityTool = {
  id?: string
  name?: string
  description?: string
  package?: string
  domain?: string
  runtime_kind?: string
  modality?: string[]
  intents?: string[]
  capabilities?: string[]
  consumes?: string[]
  produces?: string[]
  tags?: string[]
  python?: {
    module?: string
    function?: string
  }
}

type CapabilitiesYaml = {
  tools?: CapabilityTool[]
}

// Cache for loaded tools
let cachedTools: ToolRow[] | null = null
let cachedCategories: Category[] | null = null
let cacheTime = 0
const CACHE_TTL = 60000 // 1 minute

function loadToolsFromFiles(): { tools: ToolRow[]; categories: Category[] } {
  const now = Date.now()
  if (cachedTools && cachedCategories && now - cacheTime < CACHE_TTL) {
    return { tools: cachedTools, categories: cachedCategories }
  }

  const tools: ToolRow[] = []
  const stageSet = new Set<string>()
  const stageDescriptions: Record<string, string> = {}

  // Load from toolset_vfinal.yaml (Grandmaster tools)
  try {
    if (fs.existsSync(TOOLSET_YAML_PATH)) {
      const yamlContent = fs.readFileSync(TOOLSET_YAML_PATH, 'utf-8')
      const data = yaml.load(yamlContent) as GrandmasterYaml

      // Extract stage descriptions
      if (data.stages) {
        for (const stage of data.stages) {
          stageDescriptions[stage.id] = stage.description
        }
      }

      // Extract atomic tools
      if (data.atomic_tools) {
        for (const tool of data.atomic_tools) {
          stageSet.add(tool.stage || 'unknown')
          tools.push({
            name: tool.id,
            display_name: tool.id.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
            description: tool.impl,
            runtime: tool.runtime?.kind || 'unknown',
            runtime_kind: tool.runtime?.kind,
            stage: tool.stage,
            layer: tool.layer,
            cost_tier: tool.cost_tier,
            origin: tool.origin,
            impl: tool.impl,
            entrypoint: tool.runtime?.entrypoint,
            category: tool.stage,
            source: 'grandmaster',
          })
        }
      }
    }
  } catch (err) {
    console.error('Failed to load toolset_vfinal.yaml:', err)
  }

  // Load from tools_catalog_merged.json (includes NiWrap/Boutiques tools)
  try {
    if (fs.existsSync(TOOLS_JSON_PATH)) {
      const jsonContent = fs.readFileSync(TOOLS_JSON_PATH, 'utf-8')
      const data = JSON.parse(jsonContent) as CatalogJson

      if (data.tools) {
        for (const tool of data.tools) {
          // Skip if already exists from grandmaster
          if (tools.some((t) => t.name === tool.name)) continue

          // Check if this is a NiWrap tool (e.g., "afni.24.2.06.3dDeconvolve.run")
          const isNiwrapTool = /^(afni|fsl|ants|freesurfer|mrtrix|workbench|c3d|greedy|niftyreg|minc)\.\d/.test(tool.name)
          
          let stage = tool.domain?.split('.')[0] || tool.function || 'unknown'
          let displayName = tool.name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
          let pkg: string | undefined
          let toolSource = 'catalog'

          if (isNiwrapTool) {
            // Parse NiWrap tool ID: package.version.toolname.run
            const parts = tool.name.split('.')
            pkg = parts[0]
            const version = parts.slice(1, -2).join('.')
            const toolName = parts[parts.length - 2]
            displayName = `${toolName} (${pkg})`
            toolSource = 'niwrap'
            
            // Determine stage based on package
            const packageStageMap: Record<string, string> = {
              afni: 'preprocessing',
              fsl: 'preprocessing',
              ants: 'registration',
              freesurfer: 'segmentation',
              mrtrix: 'dmri',
              workbench: 'surface',
              c3d: 'conversion',
              greedy: 'registration',
              niftyreg: 'registration',
              minc: 'preprocessing',
            }
            stage = packageStageMap[pkg] || 'niwrap'
            pkg = `${pkg}@${version}`
          }

          stageSet.add(stage)

          tools.push({
            name: tool.name,
            display_name: displayName,
            description: tool.description,
            runtime: tool.runtime_kind || 'python',
            runtime_kind: tool.runtime_kind,
            domain: tool.domain,
            function: tool.function,
            risk: tool.risk,
            exposure: tool.exposure,
            tags: tool.tags,
            module: tool.python_module,
            package: pkg,
            category: stage,
            source: toolSource,
          })
        }
      }
    }
  } catch (err) {
    console.error('Failed to load tools_catalog_merged.json:', err)
  }

  // Load repo-owned capabilities surface (includes IBL/Neuropixels tools)
  try {
    if (fs.existsSync(CAPABILITIES_YAML_PATH)) {
      const yamlContent = fs.readFileSync(CAPABILITIES_YAML_PATH, 'utf-8')
      const data = yaml.load(yamlContent) as CapabilitiesYaml

      if (data.tools) {
        for (const tool of data.tools) {
          const toolId = tool.id || tool.name
          if (!toolId) continue
          if (tools.some((t) => t.name === toolId)) continue

          const category =
            tool.intents?.[0] || tool.capabilities?.[0] || tool.domain || tool.package || 'capability'
          stageSet.add(category)

          const mergedTags = Array.from(
            new Set([...(tool.tags || []), ...(tool.intents || []), ...(tool.capabilities || [])]),
          )

          tools.push({
            name: toolId,
            display_name: tool.name || toolId.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
            description: tool.description,
            runtime: tool.runtime_kind || 'python',
            runtime_kind: tool.runtime_kind,
            domain: tool.domain,
            modality: tool.modality,
            module: tool.python?.module,
            function: tool.python?.function,
            package: tool.package,
            category,
            tags: mergedTags,
            consumes: tool.consumes,
            produces: tool.produces,
            source: 'capabilities',
          })
        }
      }
    }
  } catch (err) {
    console.error('Failed to load capabilities.yaml:', err)
  }

  // Build categories from stages
  const categories: Category[] = Array.from(stageSet)
    .sort()
    .map((stage) => ({
      key: stage,
      name: stage.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
      description: stageDescriptions[stage],
      examples: tools
        .filter((t) => t.category === stage)
        .slice(0, 3)
        .map((t) => t.name),
    }))

  // Update cache
  cachedTools = tools
  cachedCategories = categories
  cacheTime = now

  return { tools, categories }
}

function toSearchText(tool: ToolRow): string {
  const parts: string[] = []
  const add = (value?: string) => {
    if (value) parts.push(value)
  }
  const addResourceValues = (value?: Record<string, string> | string[]) => {
    if (!value) return
    if (Array.isArray(value)) {
      parts.push(...value)
      return
    }
    parts.push(...Object.keys(value), ...Object.values(value))
  }
  add(tool.name)
  add(tool.display_name)
  add(tool.description)
  add(tool.runtime)
  add(tool.domain)
  add(tool.path)
  add(tool.module)
  add(tool.container_image)
  add(tool.entrypoint)
  add(tool.package)
  add(tool.category)
  add(tool.stage)
  add(tool.layer)
  add(tool.cost_tier)
  add(tool.origin)
  add(tool.impl)
  add(tool.function)
  add(tool.confidence)
  add(tool.source)

  if (tool.modality?.length) {
    parts.push(...tool.modality)
  }
  if (tool.tags?.length) {
    parts.push(...tool.tags)
  }
  addResourceValues(tool.consumes)
  addResourceValues(tool.produces)

  return parts.join(' ').toLowerCase()
}

function matchesQuery(tool: ToolRow, tokens: string[]): boolean {
  if (!tokens.length) return true
  const haystack = toSearchText(tool)
  return tokens.every((token) => haystack.includes(token))
}

export async function GET(req: NextRequest) {
  try {
    const data = loadToolsFromFiles()

    const query = req.nextUrl.searchParams.get('q')?.trim().toLowerCase() || ''
    const tokens = query.split(/\s+/).filter(Boolean)

    if (!tokens.length) {
      return Response.json(data)
    }

    const filteredTools = data.tools.filter((tool) => matchesQuery(tool, tokens))
    let filteredCategories = data.categories
    if (filteredCategories?.length) {
      const categoryKeys = new Set(filteredTools.map((tool) => tool.category).filter(Boolean))
      filteredCategories = filteredCategories.filter((category) => categoryKeys.has(category.key))
    }

    return Response.json({
      tools: filteredTools,
      categories: filteredCategories,
    })
  } catch (error) {
    console.error('Error loading tools:', error)
    return Response.json(
      { error: 'Failed to load tools', tools: [], categories: [] },
      { status: 500 }
    )
  }
}
