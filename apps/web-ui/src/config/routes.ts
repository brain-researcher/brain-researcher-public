export const routes = {
  // Primary IA (Explore / Studio / Vault / Settings)
  home: '/',
  explore: '/explore',
  studio: '/hub',
  hypothesis: '/hypothesis',
  vault: '/vault',
  analyses: '/analyses',
  datasets: '/datasets',
  files: '/vault/files',
  settings: '/settings',
  library: '/library',

  // Advanced (hidden by default)
  dashboard: '/dashboard',
  knowledgeGraph: '/kg',
  pipeline: '/pipeline',
  pipelineBuilder: '/pipeline-builder',
  tools: '/library/tools',
  status: '/status',

  // Legacy / secondary
  chat: '/hub',
  finder: '/datasets',
  analytics: '/dashboard?view=analytics',
  resources: '/dashboard?view=resources',
  workflow: '/workflow',
  profile: '/profile',
  help: '/help',
  docs: '/docs',
}

export type RouteKey = keyof typeof routes
