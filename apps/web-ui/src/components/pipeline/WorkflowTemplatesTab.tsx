'use client'

import { useEffect, useMemo, useState } from 'react'
import yaml from 'js-yaml'
import { brainResearcherAPI } from '@/lib/brain-researcher-api'
import type {
  WorkflowTemplateDetail,
  WorkflowTemplateListItem
} from '@/types/workflow-templates'
import type {
  WorkflowCatalogResponse,
  WorkflowDetail,
  WorkflowSummary
} from '@/lib/api/workflows'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { AlertCircle, RefreshCw, Search, Plus, FileText } from 'lucide-react'

const statusVariant = (status: string) => {
  switch (status) {
    case 'active':
      return 'default'
    case 'experimental':
      return 'secondary'
    case 'deprecated':
      return 'destructive'
    default:
      return 'outline'
  }
}

export function WorkflowTemplatesTab() {
  const [templates, setTemplates] = useState<WorkflowTemplateListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [catalogVersion, setCatalogVersion] = useState<string>('v1')
  const [searchQuery, setSearchQuery] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [createYaml, setCreateYaml] = useState('')
  const [createError, setCreateError] = useState<string | null>(null)
  const [createPending, setCreatePending] = useState(false)
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [selectedTemplate, setSelectedTemplate] = useState<WorkflowTemplateDetail | null>(null)

  const humanizeId = (value: string) =>
    value
      .replace(/[_-]+/g, ' ')
      .replace(/\b\w/g, (c) => c.toUpperCase())

  const toTemplateListItem = (
    workflow: WorkflowSummary,
    version: string
  ): WorkflowTemplateListItem => ({
    id: workflow.id,
    name: humanizeId(workflow.id),
    description: workflow.description || 'Workflow from library',
    version,
    category: workflow.stage || 'unknown',
    author: workflow.origin || 'workflow-catalog',
    status: 'active',
    tags: workflow.modalities || [],
    parameter_count: 0,
    step_count: 0,
    created_at: new Date().toISOString(),
  })

  const toTemplateDetail = (
    workflow: WorkflowDetail,
    version: string
  ): WorkflowTemplateDetail => ({
    id: workflow.id,
    name: humanizeId(workflow.id),
    description: workflow.description || workflow.impl || 'Workflow from library',
    version,
    category: workflow.stage || 'unknown',
    author: workflow.origin || 'workflow-catalog',
    status: 'active',
    tags: workflow.modalities || [],
    parameters: [],
    steps:
      workflow.runtime?.steps?.map((step) => ({
        name: step.id || step.tool,
        tool: step.tool,
        description: '',
        parameters: step.params || {},
      })) ?? [],
    outputs: {},
    metadata: {
      stage: workflow.stage,
      cost_tier: workflow.cost_tier,
      origin: workflow.origin,
      impl: workflow.impl,
    },
    inherits_from: null,
    created_at: new Date().toISOString(),
  })

  const fetchTemplates = async () => {
    setLoading(true)
    setError(null)
    try {
      const catalog: WorkflowCatalogResponse = await brainResearcherAPI.fetchWorkflowCatalog({
        limit: 200,
      })
      const version = catalog.version || 'v1'
      setCatalogVersion(version)
      setTemplates((catalog.workflows || []).map((wf) => toTemplateListItem(wf, version)))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch templates')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchTemplates()
  }, [])

  const filteredTemplates = useMemo(() => {
    const query = searchQuery.trim().toLowerCase()
    if (!query) return templates
    return templates.filter(template => {
      const tagMatch = template.tags?.some(tag => tag.toLowerCase().includes(query))
      return (
        template.name.toLowerCase().includes(query) ||
        template.description?.toLowerCase().includes(query) ||
        template.category.toLowerCase().includes(query) ||
        template.author.toLowerCase().includes(query) ||
        tagMatch
      )
    })
  }, [templates, searchQuery])

  const openTemplateDetail = async (templateId: string) => {
    setDetailOpen(true)
    setDetailLoading(true)
    setDetailError(null)
    setSelectedTemplate(null)
    try {
      const detail = await brainResearcherAPI.fetchWorkflowById(templateId)
      setSelectedTemplate(toTemplateDetail(detail, catalogVersion))
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : 'Failed to load template')
    } finally {
      setDetailLoading(false)
    }
  }

  const parseTemplateYaml = (): Record<string, unknown> => {
    const parsed = yaml.load(createYaml)
    if (!parsed || typeof parsed !== 'object') {
      throw new Error('Template YAML must parse to an object')
    }

    if (Object.prototype.hasOwnProperty.call(parsed, 'templates')) {
      const templatesObj = (parsed as any).templates
      let normalizedTemplates: Record<string, unknown> | unknown[] | null = null

      if (templatesObj instanceof Map) {
        normalizedTemplates = Object.fromEntries(templatesObj)
      } else if (Array.isArray(templatesObj)) {
        normalizedTemplates = templatesObj
      } else if (typeof templatesObj === 'string') {
        try {
          const parsedTemplates = yaml.load(templatesObj)
          if (parsedTemplates && typeof parsedTemplates === 'object') {
            normalizedTemplates = parsedTemplates as Record<string, unknown>
          }
        } catch {
          normalizedTemplates = null
        }
      } else if (templatesObj && typeof templatesObj === 'object') {
        normalizedTemplates = templatesObj as Record<string, unknown>
      }

      if (!normalizedTemplates) {
        throw new Error('templates must be a mapping of template ids')
      }

      const entries = Array.isArray(normalizedTemplates)
        ? normalizedTemplates.map((entry, index) => [String(index), entry] as const)
        : Object.entries(normalizedTemplates as Record<string, unknown>)

      if (entries.length !== 1) {
        throw new Error('Please provide exactly one template inside templates:')
      }
      const [templateId, data] = entries[0]
      let normalizedEntry: Record<string, unknown> | null = null

      if (data && typeof data === 'object') {
        normalizedEntry = data as Record<string, unknown>
      } else if (typeof data === 'string') {
        try {
          const parsedEntry = yaml.load(data)
          if (parsedEntry && typeof parsedEntry === 'object') {
            normalizedEntry = parsedEntry as Record<string, unknown>
          }
        } catch {
          normalizedEntry = null
        }
      }

      if (!normalizedEntry) {
        throw new Error('Template entry must be an object')
      }

      const payload = { ...normalizedEntry }
      if (!payload.id) {
        payload.id = templateId
      }
      return payload
    }

    return parsed as Record<string, unknown>
  }

  const handleCreateTemplate = async () => {
    setCreateError(null)
    setCreatePending(true)
    try {
      const payload = parseTemplateYaml()
      await brainResearcherAPI.createWorkflowTemplate(payload, true)
      setCreateOpen(false)
      setCreateYaml('')
      await fetchTemplates()
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : 'Failed to create template')
    } finally {
      setCreatePending(false)
    }
  }

  if (loading) {
    return (
      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        {[1, 2, 3, 4, 5, 6].map(i => (
          <Card key={i} className="animate-pulse">
            <CardHeader>
              <div className="h-6 bg-gray-200 rounded w-3/4 mb-2" />
              <div className="h-4 bg-gray-100 rounded w-full" />
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                <div className="h-4 bg-gray-100 rounded w-full" />
                <div className="h-4 bg-gray-100 rounded w-2/3" />
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    )
  }

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription className="flex items-center justify-between">
          <span>{error}</span>
          <Button onClick={fetchTemplates} variant="outline" size="sm" className="ml-4">
            <RefreshCw className="h-4 w-4 mr-1" />
            Retry
          </Button>
        </AlertDescription>
      </Alert>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[220px] max-w-md">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-400" />
          <Input
            type="text"
            placeholder="Search templates, tags, categories..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-10"
          />
        </div>
        <Button
          onClick={() => {
            setCreateYaml('')
            setCreateError(null)
            setCreateOpen(true)
          }}
        >
          <Plus className="h-4 w-4 mr-2" />
          New Template
        </Button>
        <Button onClick={fetchTemplates} variant="outline" size="sm">
          <RefreshCw className="h-4 w-4 mr-1" />
          Refresh
        </Button>
      </div>

      <div className="text-sm text-gray-600">
        Showing {filteredTemplates.length} template{filteredTemplates.length !== 1 ? 's' : ''}
      </div>

      {filteredTemplates.length === 0 ? (
        <Card className="p-10 text-center">
          <FileText className="h-14 w-14 mx-auto text-gray-400 mb-4" />
          <h3 className="text-lg font-semibold mb-2">No Templates Found</h3>
          <p className="text-gray-600 mb-4">
            No workflow templates match your search. Try a different keyword or create a new template.
          </p>
          <Button
            onClick={() => {
              setCreateYaml('')
              setCreateError(null)
              setCreateOpen(true)
            }}
          >
            <Plus className="h-4 w-4 mr-2" />
            Create Template
          </Button>
        </Card>
      ) : (
        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          {filteredTemplates.map(template => (
            <Card key={template.id} className="hover:shadow-lg transition-shadow">
              <CardHeader>
                <CardTitle className="flex items-start justify-between gap-2">
                  <span className="truncate">{template.name}</span>
                  <Badge variant={statusVariant(template.status)} className="shrink-0">
                    {template.status}
                  </Badge>
                </CardTitle>
                {template.description && (
                  <CardDescription className="line-clamp-3">
                    {template.description}
                  </CardDescription>
                )}
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex flex-wrap gap-2 text-xs">
                  <Badge variant="outline">{template.category}</Badge>
                  <Badge variant="outline">{template.step_count} steps</Badge>
                  <Badge variant="outline">{template.parameter_count} params</Badge>
                </div>

                {template.tags?.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {template.tags.slice(0, 4).map(tag => (
                      <Badge key={tag} variant="secondary">
                        {tag}
                      </Badge>
                    ))}
                    {template.tags.length > 4 && (
                      <Badge variant="outline">+{template.tags.length - 4} more</Badge>
                    )}
                  </div>
                )}

                <div className="flex items-center justify-between text-xs text-gray-500">
                  <span>by {template.author || 'unknown'}</span>
                  <span>v{template.version}</span>
                </div>

                <div className="flex items-center gap-2">
                  <Button size="sm" variant="outline" onClick={() => openTemplateDetail(template.id)}>
                    View Details
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Create Custom Workflow Template</DialogTitle>
            <DialogDescription>
              Paste a single template definition in YAML format. The template will be saved and
              appear in the list once created.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                <div>
                  Provide exactly one template under <span className="font-mono">templates:</span> or a single template object.
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                    setCreateYaml('')
                    setCreateError(null)
                  }}
                  disabled={!createYaml}
                >
                  Clear
                </Button>
              </div>
            </div>
            <Textarea
              value={createYaml}
              onChange={(e) => setCreateYaml(e.target.value)}
              rows={16}
              className="font-mono text-xs"
            />
            {createError && (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>{createError}</AlertDescription>
              </Alert>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleCreateTemplate} disabled={createPending}>
              {createPending ? 'Saving...' : 'Save Template'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={detailOpen} onOpenChange={setDetailOpen}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>{selectedTemplate?.name || 'Template Details'}</DialogTitle>
            {selectedTemplate?.description && (
              <DialogDescription>{selectedTemplate.description}</DialogDescription>
            )}
          </DialogHeader>
          {detailLoading ? (
            <div className="text-sm text-gray-500">Loading...</div>
          ) : detailError ? (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{detailError}</AlertDescription>
            </Alert>
          ) : selectedTemplate ? (
            <div className="space-y-4 text-sm">
              <div className="flex flex-wrap gap-2">
                <Badge variant={statusVariant(selectedTemplate.status)}>{selectedTemplate.status}</Badge>
                <Badge variant="outline">{selectedTemplate.category}</Badge>
                <Badge variant="outline">{selectedTemplate.steps.length} steps</Badge>
                <Badge variant="outline">{selectedTemplate.parameters.length} params</Badge>
              </div>

              {selectedTemplate.parameters.length > 0 && (
                <div>
                  <h4 className="font-medium mb-2">Parameters</h4>
                  <div className="grid gap-2">
                    {selectedTemplate.parameters.map(param => (
                      <div key={param.name} className="border rounded-md p-3">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold">{param.name}</span>
                          <Badge variant="secondary">{param.type}</Badge>
                          {param.required && <Badge variant="outline">required</Badge>}
                        </div>
                        {param.description && (
                          <p className="text-gray-600 mt-1">{param.description}</p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {selectedTemplate.steps.length > 0 && (
                <div>
                  <h4 className="font-medium mb-2">Steps</h4>
                  <ol className="space-y-2 list-decimal list-inside">
                    {selectedTemplate.steps.map(step => (
                      <li key={step.name} className="border rounded-md p-3">
                        <div className="font-semibold">{step.name}</div>
                        <div className="text-xs text-gray-500">Tool: {step.tool}</div>
                        {step.description && <p className="text-gray-600 mt-1">{step.description}</p>}
                      </li>
                    ))}
                  </ol>
                </div>
              )}
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  )
}
