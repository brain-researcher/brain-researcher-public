import React, { useEffect, useMemo, useState } from 'react'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import {
  Search,
  ChevronRight,
  Brain,
  Activity,
  BarChart3,
  Database,
  Cpu,
  FileText,
  Layers,
  Zap,
  GitBranch,
} from 'lucide-react'

type ApiTool = {
  name: string
  display_name?: string
  description?: string
  category?: string
  stage?: string
  consumes?: Record<string, string>
  produces?: Record<string, string>
}

type ApiCategory = {
  key: string
  name: string
  description?: string
}

type UiTool = {
  id: string
  name: string
  description?: string
  inputs: string[]
  outputs: string[]
  category?: string
  raw?: ApiTool
}

type UiCategory = {
  icon: React.ComponentType<{ className?: string }>
  tools: UiTool[]
}

// Tool categories with their tools (fallback when API is unavailable)
const fallbackToolCategories = {
  'fMRI Analysis': {
    icon: Brain,
    tools: [
      { id: 'fmriprep', name: 'fMRIPrep', description: 'Preprocessing pipeline', inputs: ['raw_data'], outputs: ['preprocessed'] },
      { id: 'fsl_feat', name: 'FSL FEAT', description: 'GLM analysis', inputs: ['preprocessed'], outputs: ['stats'] },
      { id: 'spm_glm', name: 'SPM GLM', description: 'Statistical parametric mapping', inputs: ['preprocessed'], outputs: ['stats'] },
      { id: 'nilearn_glm', name: 'Nilearn GLM', description: 'Python-based GLM', inputs: ['preprocessed'], outputs: ['stats'] },
      { id: 'fitlins', name: 'FitLins', description: 'BIDS model fitting', inputs: ['preprocessed'], outputs: ['stats'] },
    ]
  },
  'Connectivity': {
    icon: Activity,
    tools: [
      { id: 'conn', name: 'CONN Toolbox', description: 'Functional connectivity', inputs: ['preprocessed'], outputs: ['connectivity'] },
      { id: 'nilearn_connectivity', name: 'Nilearn Connectivity', description: 'Connectivity matrices', inputs: ['timeseries'], outputs: ['matrix'] },
      { id: 'graph_theory', name: 'Graph Theory', description: 'Network analysis', inputs: ['matrix'], outputs: ['metrics'] },
      { id: 'dynamic_connectivity', name: 'Dynamic Connectivity', description: 'Time-varying connectivity', inputs: ['timeseries'], outputs: ['dynamic'] },
      { id: 'gnn_connectivity', name: 'GNN Analysis', description: 'Graph neural networks', inputs: ['matrix'], outputs: ['predictions'] },
    ]
  },
  'Preprocessing': {
    icon: Database,
    tools: [
      { id: 'fsl_bet', name: 'FSL BET', description: 'Brain extraction', inputs: ['anatomical'], outputs: ['brain_mask'] },
      { id: 'fsl_flirt', name: 'FSL FLIRT', description: 'Linear registration', inputs: ['image'], outputs: ['registered'] },
      { id: 'ants', name: 'ANTs', description: 'Advanced normalization', inputs: ['image'], outputs: ['normalized'] },
      { id: 'freesurfer', name: 'FreeSurfer', description: 'Surface reconstruction', inputs: ['anatomical'], outputs: ['surfaces'] },
      { id: 'xcpd', name: 'XCP-D', description: 'Post-processing', inputs: ['preprocessed'], outputs: ['cleaned'] },
    ]
  },
  'MEG/EEG': {
    icon: Zap,
    tools: [
      { id: 'mne_preprocessing', name: 'MNE Preprocessing', description: 'MEG/EEG preprocessing', inputs: ['raw_meg'], outputs: ['preprocessed_meg'] },
      { id: 'mne_ica', name: 'MNE ICA', description: 'Independent components', inputs: ['preprocessed_meg'], outputs: ['components'] },
      { id: 'mne_source', name: 'MNE Source', description: 'Source localization', inputs: ['preprocessed_meg'], outputs: ['source_estimates'] },
      { id: 'mne_timefreq', name: 'MNE Time-Frequency', description: 'Spectral analysis', inputs: ['preprocessed_meg'], outputs: ['tfr'] },
      { id: 'fooof', name: 'FOOOF', description: 'Spectral parameterization', inputs: ['power_spectrum'], outputs: ['parameters'] },
    ]
  },
  'Statistics': {
    icon: BarChart3,
    tools: [
      { id: 'fsl_palm', name: 'FSL PALM', description: 'Permutation testing', inputs: ['stats'], outputs: ['corrected'] },
      { id: 'multiple_comparison', name: 'Multiple Comparison', description: 'FDR/FWE correction', inputs: ['stats'], outputs: ['corrected'] },
      { id: 'mixed_effects', name: 'Mixed Effects', description: 'Group analysis', inputs: ['first_level'], outputs: ['group_stats'] },
      { id: 'bayesian', name: 'Bayesian Analysis', description: 'Bayesian inference', inputs: ['data'], outputs: ['posterior'] },
      { id: 'permutation_testing', name: 'Permutation Tests', description: 'Non-parametric tests', inputs: ['data'], outputs: ['p_values'] },
    ]
  },
  'Deep Learning': {
    icon: Cpu,
    tools: [
      { id: 'dl_pytorch', name: 'PyTorch Models', description: '3D CNNs, VAEs, RNNs', inputs: ['data'], outputs: ['predictions'] },
      { id: 'nilearn_decoding', name: 'Nilearn Decoding', description: 'ML classification', inputs: ['features'], outputs: ['predictions'] },
      { id: 'mvpa', name: 'MVPA', description: 'Pattern analysis', inputs: ['data'], outputs: ['patterns'] },
      { id: 'searchlight', name: 'Searchlight', description: 'Local pattern analysis', inputs: ['data'], outputs: ['maps'] },
      { id: 'encoding_models', name: 'Encoding Models', description: 'Predictive models', inputs: ['stimuli', 'responses'], outputs: ['model'] },
    ]
  },
  'Diffusion': {
    icon: GitBranch,
    tools: [
      { id: 'qsiprep', name: 'QSIPrep', description: 'Diffusion preprocessing', inputs: ['dwi'], outputs: ['preprocessed_dwi'] },
      { id: 'fsl_bedpostx', name: 'FSL BEDPOSTX', description: 'Fiber orientation', inputs: ['dwi'], outputs: ['fibers'] },
      { id: 'mrtrix', name: 'MRtrix3', description: 'Tractography', inputs: ['dwi'], outputs: ['tracks'] },
      { id: 'dipy', name: 'DIPY', description: 'Diffusion imaging', inputs: ['dwi'], outputs: ['tensors'] },
    ]
  },
  'Visualization': {
    icon: FileText,
    tools: [
      { id: 'nilearn_plotting', name: 'Nilearn Plotting', description: 'Brain visualization', inputs: ['stats'], outputs: ['figures'] },
      { id: 'surface_plotting', name: 'Surface Plotting', description: 'Cortical surface maps', inputs: ['surface_data'], outputs: ['figures'] },
      { id: 'glass_brain', name: 'Glass Brain', description: '3D visualization', inputs: ['coords'], outputs: ['figure'] },
      { id: 'reports', name: 'Report Generator', description: 'HTML reports', inputs: ['results'], outputs: ['report'] },
    ]
  },
}

interface ToolPaletteProps {
  searchQuery: string
  onSearchChange: (query: string) => void
}

export default function ToolPalette({
  searchQuery,
  onSearchChange,
}: ToolPaletteProps) {
  const [apiTools, setApiTools] = useState<ApiTool[]>([])
  const [apiCategories, setApiCategories] = useState<ApiCategory[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState<boolean>(false)

  useEffect(() => {
    let active = true
    const controller = new AbortController()

    const fetchTools = async () => {
      setIsLoading(true)
      setLoadError(null)
      try {
        const qs = searchQuery ? `?q=${encodeURIComponent(searchQuery)}` : ''
        const res = await fetch(`/api/tools/search${qs}`, { signal: controller.signal })
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`)
        }
        const data = await res.json()
        if (!active) return
        setApiTools(Array.isArray(data.tools) ? data.tools : [])
        setApiCategories(Array.isArray(data.categories) ? data.categories : [])
      } catch (err) {
        if (!active) return
        setLoadError(err instanceof Error ? err.message : 'Failed to load tools')
      } finally {
        if (active) setIsLoading(false)
      }
    }

    const timer = setTimeout(fetchTools, 200)
    return () => {
      active = false
      clearTimeout(timer)
      controller.abort()
    }
  }, [searchQuery])

  const [openCategories, setOpenCategories] = useState<Set<string>>(
    new Set(Object.keys(fallbackToolCategories))
  )

  const normalizedToolCategories: Record<string, UiCategory> = useMemo(() => {
    if (loadError || !apiTools.length) {
      return fallbackToolCategories
    }

    const categoryMap = new Map<string, UiCategory>()
    apiCategories.forEach((category) => {
      categoryMap.set(category.key, {
        icon: category.key.includes('connect') ? Activity : Brain,
        tools: [],
      })
    })

    apiTools.forEach((tool) => {
      const categoryKey = tool.category || tool.stage || 'uncategorized'
      if (!categoryMap.has(categoryKey)) {
        categoryMap.set(categoryKey, {
          icon: categoryKey.includes('connect') ? Activity : Brain,
          tools: [],
        })
      }
      const inputs = tool.consumes ? Object.keys(tool.consumes) : []
      const outputs = tool.produces ? Object.keys(tool.produces) : []
      categoryMap.get(categoryKey)?.tools.push({
        id: tool.name,
        name: tool.display_name || tool.name,
        description: tool.description,
        inputs,
        outputs,
        category: categoryKey,
        raw: tool,
      })
    })

    return Object.fromEntries(categoryMap.entries())
  }, [apiTools, apiCategories, loadError])

  useEffect(() => {
    setOpenCategories(new Set(Object.keys(normalizedToolCategories)))
  }, [normalizedToolCategories])

  // Filter tools based on search
  const filteredCategories = useMemo(() => {
    if (!searchQuery) return normalizedToolCategories

    const filtered: Record<string, UiCategory> = {}
    
    Object.entries(normalizedToolCategories).forEach(([category, data]) => {
      const filteredTools = data.tools.filter(
        tool =>
          tool.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
          tool.description.toLowerCase().includes(searchQuery.toLowerCase())
      )
      
      if (filteredTools.length > 0) {
        filtered[category] = {
          ...data,
          tools: filteredTools,
        }
      }
    })
    
    return filtered
  }, [searchQuery])

  const toggleCategory = (category: string) => {
    const newOpen = new Set(openCategories)
    if (newOpen.has(category)) {
      newOpen.delete(category)
    } else {
      newOpen.add(category)
    }
    setOpenCategories(newOpen)
  }

  const onDragStart = (event: React.DragEvent, tool: any, category: string) => {
    event.dataTransfer.setData('application/reactflow', 'tool')
    // Include both a structured payload and a plain category for consumers
    const normalizedCategory = category.toLowerCase().replace(/[^a-z]/g, '-')
    event.dataTransfer.setData('tool', JSON.stringify({ ...tool, category: normalizedCategory }))
    event.dataTransfer.setData('category', normalizedCategory)
    event.dataTransfer.effectAllowed = 'move'
  }

  return (
    <div className="w-80 border-r bg-background flex flex-col">
      <div className="p-4 border-b">
        <h2 className="text-lg font-semibold mb-3">Neuroimaging Tools</h2>
        <div className="relative">
          <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search tools..."
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            className="pl-8"
          />
        </div>
        {isLoading && (
          <div className="text-xs text-muted-foreground mt-2">Loading tools…</div>
        )}
        {loadError && (
          <div className="text-xs text-destructive mt-2">Tool catalog unavailable; showing fallback.</div>
        )}
      </div>

      <ScrollArea className="flex-1">
        <div className="p-2">
          {Object.entries(filteredCategories).map(([category, data]) => {
            const Icon = data.icon
            const isOpen = openCategories.has(category)
            
            return (
              <Collapsible
                key={category}
                open={isOpen}
                onOpenChange={() => toggleCategory(category)}
                className="mb-2"
              >
                <CollapsibleTrigger className="flex items-center gap-2 w-full p-2 hover:bg-accent rounded-lg transition-colors">
                  <ChevronRight
                    className={`h-4 w-4 transition-transform ${
                      isOpen ? 'rotate-90' : ''
                    }`}
                  />
                  <Icon className="h-4 w-4" />
                  <span className="font-medium text-sm flex-1 text-left">
                    {category}
                  </span>
                  <Badge variant="secondary" className="text-xs">
                    {data.tools.length}
                  </Badge>
                </CollapsibleTrigger>
                <CollapsibleContent className="pl-6 pr-2 pt-1">
                  {data.tools.map((tool) => (
                    <div
                      key={tool.id}
                      draggable
                      onDragStart={(e) => onDragStart(e, tool, category)}
                      onDoubleClick={() => {
                        const normalizedCategory = category.toLowerCase().replace(/[^a-z]/g, '-')
                        const evt = new CustomEvent('pipeline:add-tool', {
                          detail: { tool: { ...tool, category: normalizedCategory } },
                        })
                        window.dispatchEvent(evt)
                      }}
                      className="p-2 mb-1 rounded-lg border bg-card hover:bg-accent cursor-move transition-colors"
                    >
                      <div className="font-medium text-sm">{tool.name}</div>
                      <div className="text-xs text-muted-foreground mt-1">
                        {tool.description}
                      </div>
                      <div className="flex gap-2 mt-2">
                        <Badge variant="outline" className="text-xs">
                          {tool.inputs.length} in
                        </Badge>
                        <Badge variant="outline" className="text-xs">
                          {tool.outputs.length} out
                        </Badge>
                      </div>
                    </div>
                  ))}
                </CollapsibleContent>
              </Collapsible>
            )
          })}
        </div>
      </ScrollArea>

      <div className="p-4 border-t">
        <div className="text-sm text-muted-foreground">
          <p className="mb-2">📍 Drag tools to canvas</p>
          <p className="mb-2">🔗 Connect outputs to inputs</p>
          <p>⚙️ Click nodes to configure</p>
        </div>
      </div>
    </div>
  )
}
