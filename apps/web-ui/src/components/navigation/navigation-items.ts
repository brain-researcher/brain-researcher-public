import {
  Activity,
  Award,
  BarChart3,
  BookOpen,
  FolderOpen,
  GitBranch,
  MessageSquare,
  Network,
  PlayCircle,
  Plug,
  Wrench,
} from 'lucide-react'
import type React from 'react'

export interface NavItem {
  label: string
  href: string
  icon?: React.ElementType
  badge?: number
}

export const primaryNavItems: NavItem[] = [
  { label: 'MCP', href: '/mcp/setup', icon: Plug },
  { label: 'Datasets', href: '/datasets', icon: FolderOpen },
  { label: 'Workflows', href: '/library', icon: BookOpen },
  { label: 'Demos', href: '/demos', icon: PlayCircle },
  { label: 'Knowledge Graph', href: '/kg', icon: Network },
  { label: 'Studio', href: '/hub', icon: MessageSquare },
]

export const advancedNavItems: NavItem[] = [
  { label: 'Dashboard', href: '/dashboard', icon: BarChart3 },
  { label: 'Execution', href: '/pipeline', icon: Activity },
  { label: 'Pipeline Builder', href: '/pipeline-builder', icon: GitBranch },
  { label: 'Tool Catalog', href: '/library/tools', icon: Wrench },
  { label: 'Status', href: '/status', icon: BarChart3 },
  { label: 'Benchmark', href: '/benchmark', icon: Award },
]
