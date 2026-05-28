type FeatureCounts = {
  statmaps: number
  coords: number
  timeseries: number
  datasets: number
  papers: number
  tasks: number
  contrasts: number
  tools: number
  studies: number
}

type OntologyCounts = {
  parents: number
  children: number
  classified_neighbors: number
}

type FilterableFeature = 'statmaps' | 'coords' | 'timeseries' | 'datasets' | 'papers'

const DEFAULT_FEATURE_COUNTS: FeatureCounts = {
  statmaps: 0,
  coords: 0,
  timeseries: 0,
  datasets: 0,
  papers: 0,
  tasks: 0,
  contrasts: 0,
  tools: 0,
  studies: 0,
}

const DEFAULT_ONTOLOGY_COUNTS: OntologyCounts = {
  parents: 0,
  children: 0,
  classified_neighbors: 0,
}

export type ConceptSummary = {
  id: string
  label: string
  status?: 'online' | 'download-only' | 'degraded' | 'unknown' | 'loading'
  features?: Partial<FeatureCounts>
  features_verified?: Partial<FeatureCounts>
  features_unverified?: Partial<FeatureCounts>
  ontology?: Partial<OntologyCounts>
  spaces?: string[]
  atlases?: string[]
  origin?: string
  updated_at?: string | number
  breadcrumb?: string[]
}

type ToggleFilters = {
  feature?: FilterableFeature
  space?: string
  atlas?: string
}

type Props = {
  summary?: ConceptSummary
  backendSource?: string
  lens?: 'onvoc' | 'task' | 'disease' | 'population'
  onToggle: (filters: ToggleFilters) => void
  onPrimary?: { onSearchData?: () => void; onMaps?: () => void; onAsk?: () => void }
}

export function CatalogHeader({ summary, backendSource, lens = 'onvoc', onToggle, onPrimary }: Props) {
  if (!summary) return null
  const { id, label, breadcrumb } = summary
  const status = summary.status ?? 'unknown'
  const features = { ...DEFAULT_FEATURE_COUNTS, ...(summary.features ?? {}) }
  const ontology = { ...DEFAULT_ONTOLOGY_COUNTS, ...(summary.ontology ?? {}) }
  const spaces = summary.spaces ?? []
  const atlases = summary.atlases ?? []
  const origin = summary.origin ?? 'unknown'

  const Chip = ({ name, count }: { name: FilterableFeature; count: number }) => (
    <button
      disabled={!count}
      onClick={() => onToggle({ feature: name })}
      className={`px-2.5 py-1 rounded-full text-xs border ${count ? 'hover:bg-gray-50' : 'opacity-50 cursor-not-allowed'}`}
    >
      {name} {count ? `(${count})` : ''}
    </button>
  )

  const lensLabel = { onvoc: 'Concepts', task: 'Tasks', disease: 'Disorders', population: 'Cohorts' }[lens] ?? 'Entities'
  const anchorLabel = lens === 'onvoc' ? `Anchored on ONVOC: ${id}` : id

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <div className="text-xs text-gray-500">
            {breadcrumb && breadcrumb.length ? breadcrumb.join(' › ') : lensLabel}
          </div>
          <h1 className="text-2xl font-bold">{label}</h1>
          <div className="text-sm text-gray-500 mt-1">{anchorLabel}</div>
        </div>
        <div className="flex items-center gap-2">
          {backendSource && (
            <span className="px-2 py-1 text-xs rounded bg-emerald-50 text-emerald-700 border">Backend: {backendSource}</span>
          )}
          <span className="px-2 py-1 text-xs rounded-full bg-gray-100 border">{status}</span>
        </div>
      </div>

      <div className="flex items-center flex-wrap gap-2 mb-3">
        <Chip name="statmaps" count={features.statmaps} />
        <Chip name="coords" count={features.coords} />
        <Chip name="timeseries" count={features.timeseries} />
        <Chip name="datasets" count={features.datasets} />
        <Chip name="papers" count={features.papers} />
      </div>

      {(ontology.parents > 0 || ontology.children > 0 || ontology.classified_neighbors > 0) && (
        <div className="flex items-center flex-wrap gap-2 mb-3 text-xs">
          <span className="text-gray-600">Ontology</span>
          <span className="px-2.5 py-1 rounded-full border bg-gray-50 text-gray-700">
            parents ({ontology.parents})
          </span>
          <span className="px-2.5 py-1 rounded-full border bg-gray-50 text-gray-700">
            children ({ontology.children})
          </span>
          <span className="px-2.5 py-1 rounded-full border bg-gray-50 text-gray-700">
            neighbors ({ontology.classified_neighbors})
          </span>
        </div>
      )}

      <div className="flex items-center flex-wrap gap-2 mb-4">
        {spaces?.map((s) => (
          <button key={s} onClick={() => onToggle({ space: s })} className="px-2 py-1 text-xs border rounded">{s}</button>
        ))}
        {atlases?.map((a) => (
          <button key={a} onClick={() => onToggle({ atlas: a })} className="px-2 py-1 text-xs border rounded">{a}</button>
        ))}
      </div>

      <div className="flex items-center justify-between">
        <div className="text-xs text-gray-600">
          Origin: <code className="px-1.5 py-0.5 bg-gray-50 border rounded">{origin}</code>
        </div>
        <div className="flex gap-2 text-xs">
          <button onClick={onPrimary?.onSearchData} className="border rounded px-2 py-1">Search KG</button>
          <button onClick={onPrimary?.onMaps} className="border rounded px-2 py-1">Maps/Coords</button>
          <button onClick={onPrimary?.onAsk} className="bg-black text-white rounded px-2 py-1">Ask the KG</button>
        </div>
      </div>
    </div>
  )
}
