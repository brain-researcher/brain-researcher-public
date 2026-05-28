'use client'

import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { Network, ArrowUp, ArrowDown, Tag } from 'lucide-react'

interface ConceptSummary {
  id: string
  label: string
  definition?: string
  uri?: string
  synonyms?: string[]
  scheme?: string
}

interface ConceptHierarchy {
  parents?: Array<{ id: string; label: string }>
  children?: Array<{ id: string; label: string }>
}

interface ConceptOverviewTabProps {
  concept: ConceptSummary | null
  hierarchy?: ConceptHierarchy
  isLoading?: boolean
}

export function ConceptOverviewTab({ concept, hierarchy, isLoading }: ConceptOverviewTabProps) {
  if (isLoading) {
    return (
      <div className="space-y-4 animate-pulse">
        <div className="h-20 bg-muted rounded-lg" />
        <div className="h-40 bg-muted rounded-lg" />
        <div className="h-32 bg-muted rounded-lg" />
      </div>
    )
  }

  if (!concept) {
    return (
      <div className="flex items-center justify-center h-64 text-center">
        <div>
          <Network className="h-12 w-12 text-muted-foreground mx-auto mb-3" />
          <p className="text-sm text-muted-foreground">
            No concept selected
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Concept Basic Info */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <Network className="h-5 w-5 text-primary" />
            {concept.label}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {concept.definition && (
            <div>
              <h4 className="text-sm font-medium text-muted-foreground mb-1">Definition</h4>
              <p className="text-sm text-foreground">{concept.definition}</p>
            </div>
          )}

          {!concept.definition && (
            <p className="text-sm text-muted-foreground italic">
              No definition available for this concept
            </p>
          )}

          <Separator />

          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <span className="text-muted-foreground">ID:</span>
              <p className="font-mono text-xs mt-0.5">{concept.id}</p>
            </div>
            {concept.scheme && (
              <div>
                <span className="text-muted-foreground">Scheme:</span>
                <p className="font-mono text-xs mt-0.5">{concept.scheme}</p>
              </div>
            )}
          </div>

          {concept.uri && (
            <div className="text-sm">
              <span className="text-muted-foreground">URI:</span>
              <a
                href={concept.uri}
                target="_blank"
                rel="noopener noreferrer"
                className="font-mono text-xs block mt-0.5 text-primary hover:underline truncate"
              >
                {concept.uri}
              </a>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Synonyms */}
      {concept.synonyms && concept.synonyms.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm flex items-center gap-2">
              <Tag className="h-4 w-4" />
              Synonyms
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {concept.synonyms.map((synonym, idx) => (
                <Badge key={idx} variant="secondary" className="text-xs">
                  {synonym}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Hierarchy */}
      {hierarchy && (hierarchy.parents || hierarchy.children) && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Hierarchy</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {hierarchy.parents && hierarchy.parents.length > 0 && (
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <ArrowUp className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm font-medium text-muted-foreground">
                    Parent Concepts ({hierarchy.parents.length})
                  </span>
                </div>
                <div className="space-y-1.5 pl-6">
                  {hierarchy.parents.map((parent) => (
                    <div
                      key={parent.id}
                      className="text-sm p-2 rounded bg-muted/50 hover:bg-muted transition-colors"
                    >
                      <span className="font-medium">{parent.label}</span>
                      <span className="text-xs text-muted-foreground ml-2">
                        ({parent.id})
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {hierarchy.children && hierarchy.children.length > 0 && (
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <ArrowDown className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm font-medium text-muted-foreground">
                    Child Concepts ({hierarchy.children.length})
                  </span>
                </div>
                <div className="space-y-1.5 pl-6">
                  {hierarchy.children.slice(0, 10).map((child) => (
                    <div
                      key={child.id}
                      className="text-sm p-2 rounded bg-muted/50 hover:bg-muted transition-colors"
                    >
                      <span className="font-medium">{child.label}</span>
                      <span className="text-xs text-muted-foreground ml-2">
                        ({child.id})
                      </span>
                    </div>
                  ))}
                  {hierarchy.children.length > 10 && (
                    <p className="text-xs text-muted-foreground pl-2">
                      ... and {hierarchy.children.length - 10} more
                    </p>
                  )}
                </div>
              </div>
            )}

            {(!hierarchy.parents || hierarchy.parents.length === 0) &&
             (!hierarchy.children || hierarchy.children.length === 0) && (
              <p className="text-sm text-muted-foreground italic">
                No hierarchy information available
              </p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
