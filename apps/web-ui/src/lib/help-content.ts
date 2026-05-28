export type HelpTooltip = {
  id: string
  title: string
  description: string
  category: 'feature' | 'concept' | 'shortcut' | 'workflow'
  learnMoreUrl?: string
  videoUrl?: string
  relatedTourId?: string
}

const HELP_SEED_ENABLED = process.env.NEXT_PUBLIC_ENABLE_HELP_SEED === '1'

// Contextual help content database (shared across help surfaces).
export const HELP_TOOLTIPS: Record<string, HelpTooltip> = HELP_SEED_ENABLED ? {
  navigation: {
    id: 'navigation',
    title: 'Main Navigation',
    description:
      'Access all main features of Brain Researcher from this navigation bar. Each section provides specialized tools for different aspects of neuroimaging analysis.',
    category: 'feature',
    learnMoreUrl: '/docs/navigation',
    relatedTourId: 'welcome',
  },
  search: {
    id: 'search',
    title: 'Global Search',
    description:
      'Search across datasets, research papers, brain regions, and analysis results. Use natural language queries or specific terms.',
    category: 'feature',
    relatedTourId: 'welcome',
  },
  chat: {
    id: 'chat',
    title: 'AI Chat Interface',
    description:
      'Interact with your neuroimaging data using natural language. Ask questions, request analyses, or get explanations of results.',
    category: 'feature',
    relatedTourId: 'welcome',
  },
  'upload-data': {
    id: 'upload-data',
    title: 'Data Upload',
    description:
      'Upload your neuroimaging data in BIDS format, NIfTI files, or other supported formats. Drag and drop or click to browse files.',
    category: 'workflow',
    learnMoreUrl: '/docs/data-upload',
    relatedTourId: 'data-analysis',
  },
  'analysis-tools': {
    id: 'analysis-tools',
    title: 'Analysis Tools',
    description:
      'Select from various neuroimaging analysis methods including GLM, connectivity analysis, machine learning, and more.',
    category: 'feature',
    relatedTourId: 'data-analysis',
  },
  pipeline: {
    id: 'pipeline',
    title: 'Analysis Pipeline',
    description:
      'Build custom analysis workflows by connecting different processing steps. Monitor progress and modify parameters as needed.',
    category: 'workflow',
    relatedTourId: 'data-analysis',
  },
  results: {
    id: 'results',
    title: 'Analysis Results',
    description:
      'View and interpret your analysis results with interactive visualizations, statistical maps, and detailed reports.',
    category: 'feature',
    relatedTourId: 'data-analysis',
  },
  'kg-viewer': {
    id: 'kg-viewer',
    title: 'Knowledge Graph',
    description:
      'Explore connections between research findings, brain regions, cognitive functions, and studies in an interactive graph visualization.',
    category: 'concept',
    learnMoreUrl: '/docs/knowledge-graph',
    relatedTourId: 'knowledge-graph',
  },
  'kg-search': {
    id: 'kg-search',
    title: 'Graph Search',
    description:
      'Search for specific nodes in the knowledge graph by brain region, study, author, or concept. Results will be highlighted in the graph.',
    category: 'feature',
    relatedTourId: 'knowledge-graph',
  },
  'kg-filters': {
    id: 'kg-filters',
    title: 'Graph Filters',
    description:
      'Filter the knowledge graph by study type, publication year, brain region, or other metadata to focus on relevant connections.',
    category: 'feature',
    relatedTourId: 'knowledge-graph',
  },
  dashboard: {
    id: 'dashboard',
    title: 'Dashboard',
    description:
      'Your personalized overview of recent analyses, datasets, and research progress. Customize widgets to suit your workflow.',
    category: 'feature',
    learnMoreUrl: '/docs/dashboard',
  },
  settings: {
    id: 'settings',
    title: 'Settings',
    description:
      'Configure your preferences, manage data sources, set up integrations, and customize the interface.',
    category: 'feature',
  },
} : {}
