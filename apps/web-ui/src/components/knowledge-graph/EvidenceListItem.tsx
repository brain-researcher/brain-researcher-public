'use client'

import { ExternalLink, Database, FileText, TestTube, Wrench, Brain } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

export interface EvidenceItem {
  id?: string
  name?: string
  title?: string
  label?: string
  description?: string
  url?: string
  pmid?: string
  year?: number
  authors?: string
  map_id?: string
  space?: string
  atlas?: string
  contrast?: string
  roi?: string
  task?: string
  x?: number
  y?: number
  z?: number
  statistic?: string
  statmap_count?: number
  dataset_count?: number
  source_channel?: string
  path_type?: string
  support_count?: number
  freshness_ts?: string
  doi?: string
}

export type EvidenceType =
  | 'dataset'
  | 'paper'
  | 'statmap'
  | 'coordinate'
  | 'tool'
  | 'study'
  | 'timeseries'
  | 'task'
  | 'contrast'

interface EvidenceListItemProps {
  item: EvidenceItem
  type: EvidenceType
}

const typeConfig = {
  dataset: {
    icon: Database,
    iconColor: 'text-blue-500',
    bgColor: 'bg-blue-50 dark:bg-blue-950/20'
  },
  paper: {
    icon: FileText,
    iconColor: 'text-green-500',
    bgColor: 'bg-green-50 dark:bg-green-950/20'
  },
  statmap: {
    icon: Brain,
    iconColor: 'text-purple-500',
    bgColor: 'bg-purple-50 dark:bg-purple-950/20'
  },
  coordinate: {
    icon: Brain,
    iconColor: 'text-pink-500',
    bgColor: 'bg-pink-50 dark:bg-pink-950/20'
  },
  tool: {
    icon: Wrench,
    iconColor: 'text-orange-500',
    bgColor: 'bg-orange-50 dark:bg-orange-950/20'
  },
  study: {
    icon: TestTube,
    iconColor: 'text-teal-500',
    bgColor: 'bg-teal-50 dark:bg-teal-950/20'
  },
  timeseries: {
    icon: Brain,
    iconColor: 'text-indigo-500',
    bgColor: 'bg-indigo-50 dark:bg-indigo-950/20'
  },
  task: {
    icon: TestTube,
    iconColor: 'text-cyan-500',
    bgColor: 'bg-cyan-50 dark:bg-cyan-950/20'
  },
  contrast: {
    icon: TestTube,
    iconColor: 'text-amber-500',
    bgColor: 'bg-amber-50 dark:bg-amber-950/20'
  }
}

export function EvidenceListItem({ item, type }: EvidenceListItemProps) {
  const config = typeConfig[type]
  const Icon = config.icon

  const normalizeId = (value?: string) =>
    typeof value === 'string' && value.trim().length > 0 ? value.trim() : ''

  const normalizeLink = (value?: string): string | null => {
    if (!value) return null
    const trimmed = value.trim()
    if (!trimmed) return null
    if (/^(https?:\/\/|\/)/i.test(trimmed)) return trimmed
    return `https://doi.org/${trimmed}`
  }

  const doi = normalizeId(item.doi)
  const pmid = normalizeId(item.pmid)

  const actionLinks = (() => {
    const links: { label: string; href: string }[] = []

    if (item.url) {
      links.push({
        label: 'Open source',
        href: item.url,
      })
    }

    if (type === 'paper' && pmid) {
      links.push({
        label: 'PubMed',
        href: `https://pubmed.ncbi.nlm.nih.gov/${pmid}/`,
      })
    }

    if (type === 'paper' && doi) {
      links.push({
        label: 'DOI',
        href: normalizeLink(doi) || `https://doi.org/${doi}`,
      })
    }

    if (type === 'dataset' && item.id && /^ds[\w-]+$/i.test(item.id)) {
      links.push({
        label: 'Open dataset',
        href: `/datasets/${encodeURIComponent(item.id)}`,
      })
    }

    return links
  })()

  const openLink = (href: string) => {
    const target = href.startsWith('http') ? '_blank' : '_self'
    window.open(href, target, 'noopener,noreferrer')
  }

  const openLabel = () => {
    if (!actionLinks.length) return null

    return (
      <div className="mt-2 flex flex-wrap gap-2">
        {actionLinks.map((action) => (
          <Button
            key={action.label}
            type="button"
            variant="outline"
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={() => openLink(action.href)}
          >
            {action.label}
          </Button>
        ))}
      </div>
    )
  }

  const getTitle = () => {
    if (type === 'dataset') return item.name || item.id || 'Unnamed Dataset'
    if (type === 'paper') return item.title || `PMID: ${item.pmid}`
    if (type === 'statmap') return item.contrast || item.map_id || 'Statistical Map'
    if (type === 'coordinate') return item.label || `Coordinate (${item.x}, ${item.y}, ${item.z})`
    if (type === 'tool') return item.name || item.id || 'Tool'
    if (type === 'study') return item.name || item.id || 'Study'
    if (type === 'timeseries') return item.roi || item.id || 'Time Series'
    if (type === 'task') return item.label || item.name || item.id || 'Task'
    if (type === 'contrast') return item.label || item.name || item.id || 'Contrast'
    return 'Unknown'
  }

  const getSubtitle = () => {
    if (type === 'dataset') return item.description || item.id
    if (type === 'paper') return `${item.authors || 'Unknown'} (${item.year || 'N/A'})`
    if (type === 'statmap') return `${item.space || 'Unknown space'} | ${item.atlas || 'Unknown atlas'}`
    if (type === 'coordinate') return `${item.statistic || 'Unknown statistic'}`
    if (type === 'tool') return item.description
    if (type === 'study') return item.description
    if (type === 'timeseries') return `Task: ${item.task || 'Unknown'}`
    if (type === 'task') return item.description || `Datasets: ${item.dataset_count || 0}`
    if (type === 'contrast') return `Stat maps: ${item.statmap_count || 0}`
    return null
  }

  const title = getTitle()
  const subtitle = getSubtitle()

  return (
    <Card className={`${config.bgColor} border-0 shadow-none`}>
      <CardContent className="p-3">
        <div className="flex items-start gap-3">
          <div className="mt-0.5">
            <Icon className={`h-5 w-5 ${config.iconColor}`} />
          </div>

          <div className="flex-1 min-w-0">
            <div className="flex items-start justify-between gap-2">
              <div className="flex-1 min-w-0">
                <h4 className="text-sm font-medium text-foreground truncate">
                  {title}
                </h4>
                {subtitle && (
                  <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">
                    {subtitle}
                  </p>
                )}
              </div>

              {item.url && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 w-7 p-0 shrink-0"
                  onClick={() => window.open(item.url, '_blank')}
                >
                  <ExternalLink className="h-3.5 w-3.5" />
                  <span className="sr-only">Open link</span>
                </Button>
              )}
            </div>

            {/* Additional metadata badges */}
            <div className="flex gap-1.5 mt-2 flex-wrap">
              {type === 'paper' && item.pmid && (
                <Badge variant="outline" className="text-xs">
                  PMID: {item.pmid}
                </Badge>
              )}
              {type === 'statmap' && item.contrast && (
                <Badge variant="outline" className="text-xs">
                  {item.contrast}
                </Badge>
              )}
              {type === 'dataset' && item.id && (
                <Badge variant="outline" className="text-xs">
                  {item.id}
                </Badge>
              )}
              {item.source_channel && (
                <Badge variant="outline" className="text-xs">
                  {item.source_channel}
                </Badge>
              )}
              {item.path_type && (
                <Badge variant="outline" className="text-xs">
                  {item.path_type}
                </Badge>
              )}
              {typeof item.support_count === 'number' && item.support_count > 1 && (
                <Badge variant="outline" className="text-xs">
                  support x{item.support_count}
                </Badge>
              )}
            </div>
            {openLabel()}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

export function EmptyState({ type, message }: { type: EvidenceType, message?: string }) {
  const config = typeConfig[type]
  const Icon = config.icon

  const defaultMessages = {
    dataset: 'No datasets found for this concept',
    paper: 'No papers found for this concept',
    statmap: 'No brain maps found for this concept',
    coordinate: 'No coordinates found for this concept',
    tool: 'No tools found for this concept',
    study: 'No studies found for this concept',
    timeseries: 'No time series data found for this concept',
    task: 'No tasks found for this concept',
    contrast: 'No contrasts found for this concept'
  }

  return (
    <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
      <div className={`rounded-full p-3 ${config.bgColor} mb-3`}>
        <Icon className={`h-6 w-6 ${config.iconColor}`} />
      </div>
      <p className="text-sm text-muted-foreground">
        {message || defaultMessages[type]}
      </p>
      <p className="text-xs text-muted-foreground mt-1">
        Try selecting a different concept or check back later
      </p>
    </div>
  )
}
