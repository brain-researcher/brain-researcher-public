'use client'

import { useState } from 'react'
import { 
  X, 
  ExternalLink, 
  Download, 
  Play, 
  ChevronRight, 
  ChevronDown,
  File,
  Folder,
  Users,
  Calendar,
  Database,
  Zap,
  Brain,
  Star
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { Dataset, BidsNode } from '@/types/dataset'
import { formatBytes } from '@/lib/utils'

interface DatasetDrawerProps {
  dataset: Dataset | null
  isOpen: boolean
  onClose: () => void
  onRunDemo: (dataset: Dataset) => void
}

function BidsTreeNode({ node, depth = 0 }: { node: BidsNode, depth?: number }) {
  const [isExpanded, setIsExpanded] = useState(depth < 2)

  return (
    <div className="select-none">
      <div 
        className="flex items-center gap-2 py-1 px-2 hover:bg-muted/50 rounded cursor-pointer"
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        onClick={() => node.type === 'folder' && setIsExpanded(!isExpanded)}
      >
        {node.type === 'folder' ? (
          <>
            {isExpanded ? (
              <ChevronDown className="h-3 w-3 text-muted-foreground" />
            ) : (
              <ChevronRight className="h-3 w-3 text-muted-foreground" />
            )}
            <Folder className="h-4 w-4 text-blue-500" />
          </>
        ) : (
          <>
            <div className="w-3" />
            <File className="h-4 w-4 text-muted-foreground" />
          </>
        )}
        
        <span className="text-sm font-mono">{node.name}</span>
        
        {node.size && (
          <span className="text-xs text-muted-foreground ml-auto">
            {formatBytes(node.size)}
          </span>
        )}
      </div>
      
      {node.type === 'folder' && isExpanded && node.children && (
        <div>
          {node.children.map((child, index) => (
            <BidsTreeNode key={index} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  )
}

export function DatasetDrawer({ dataset, isOpen, onClose, onRunDemo }: DatasetDrawerProps) {
  const [activeTab, setActiveTab] = useState<'overview' | 'structure' | 'contrasts'>('overview')

  if (!dataset || !isOpen) return null

  const renderStars = (rating: number) => {
    return Array.from({ length: 5 }, (_, i) => (
      <Star
        key={i}
        className={`h-4 w-4 ${
          i < rating 
            ? 'fill-yellow-400 text-yellow-400' 
            : 'text-gray-300 dark:text-gray-600'
        }`}
      />
    ))
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
      <div className="bg-background rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b">
          <div className="flex-1">
            <div className="flex items-center gap-3 mb-2">
              <h2 className="text-2xl font-bold">{dataset.name}</h2>
              <div className="flex items-center gap-1">
                {renderStars(dataset.popularity)}
              </div>
            </div>
            <p className="text-muted-foreground">{dataset.description}</p>
          </div>
          
          <div className="flex items-center gap-2 ml-4">
            <Button onClick={() => onRunDemo(dataset)}>
              <Play className="h-4 w-4 mr-2" />
              Run Demo
            </Button>
            <Button
              variant="outline"
              size="icon"
              onClick={onClose}
              aria-label="Close dataset details"
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex border-b">
          {[
            { id: 'overview', label: 'Overview' },
            { id: 'structure', label: 'BIDS Structure' },
            { id: 'contrasts', label: 'Contrasts' }
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              className={`px-6 py-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.id
                  ? 'border-primary text-primary'
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="p-6 overflow-y-auto max-h-[60vh]">
          {activeTab === 'overview' && (
            <div className="space-y-6">
              {/* Key metrics */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <Card>
                  <CardContent className="p-4 text-center">
                    <Users className="h-8 w-8 mx-auto mb-2 text-primary" />
                    <div className="text-2xl font-bold">{dataset.nSubjects.toLocaleString()}</div>
                    <div className="text-sm text-muted-foreground">Subjects</div>
                  </CardContent>
                </Card>

                <Card>
                  <CardContent className="p-4 text-center">
                    <Database className="h-8 w-8 mx-auto mb-2 text-primary" />
                    <div className="text-2xl font-bold">{dataset.size}</div>
                    <div className="text-sm text-muted-foreground">Total Size</div>
                  </CardContent>
                </Card>

                {dataset.tr && (
                  <Card>
                    <CardContent className="p-4 text-center">
                      <Zap className="h-8 w-8 mx-auto mb-2 text-primary" />
                      <div className="text-2xl font-bold">{dataset.tr}s</div>
                      <div className="text-sm text-muted-foreground">TR</div>
                    </CardContent>
                  </Card>
                )}

                <Card>
                  <CardContent className="p-4 text-center">
                    <Calendar className="h-8 w-8 mx-auto mb-2 text-primary" />
                    <div className="text-2xl font-bold">{dataset.lastUpdated.getFullYear()}</div>
                    <div className="text-sm text-muted-foreground">Updated</div>
                  </CardContent>
                </Card>
              </div>

              {/* Details */}
              <div className="grid md:grid-cols-2 gap-6">
                <Card>
                  <CardHeader>
                    <CardTitle className="text-lg">Dataset Details</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <div>
                      <div className="font-medium text-sm">Source</div>
                      <div className="text-sm text-muted-foreground">{dataset.source}</div>
                    </div>
                    {dataset.category && (
                      <div>
                        <div className="font-medium text-sm">Category</div>
                        <div className="text-sm text-muted-foreground">{dataset.category}</div>
                      </div>
                    )}

                    <div>
                      <div className="font-medium text-sm">Modalities</div>
                      <div className="flex flex-wrap gap-1 mt-1">
                        {dataset.modality.map((mod) => (
                          <span
                            key={mod}
                            className="px-2 py-1 bg-secondary text-secondary-foreground rounded text-xs"
                          >
                            {mod}
                          </span>
                        ))}
                      </div>
                    </div>

                    {dataset.fieldStrength && (
                      <div>
                        <div className="font-medium text-sm">Field Strength</div>
                        <div className="text-sm text-muted-foreground">{dataset.fieldStrength}</div>
                      </div>
                    )}

                    {dataset.spatialResolution && (
                      <div>
                        <div className="font-medium text-sm">Spatial Resolution</div>
                        <div className="text-sm text-muted-foreground">{dataset.spatialResolution}</div>
                      </div>
                    )}
                  </CardContent>
                </Card>

                {dataset.demographics && (
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-lg">Demographics</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      <div>
                        <div className="font-medium text-sm">Age Range</div>
                        <div className="text-sm text-muted-foreground">
                          {dataset.demographics.ageRange[0]} - {dataset.demographics.ageRange[1]} years
                          {dataset.demographics.meanAge && ` (mean: ${dataset.demographics.meanAge})`}
                        </div>
                      </div>

                      {dataset.demographics.genderDistribution && (
                        <div>
                          <div className="font-medium text-sm">Gender Distribution</div>
                          <div className="text-sm text-muted-foreground">
                            {dataset.demographics.genderDistribution.male} male, {dataset.demographics.genderDistribution.female} female
                            {dataset.demographics.genderDistribution.other && `, ${dataset.demographics.genderDistribution.other} other`}
                          </div>
                        </div>
                      )}

                      {dataset.demographics.handedness && (
                        <div>
                          <div className="font-medium text-sm">Handedness</div>
                          <div className="text-sm text-muted-foreground">
                            {dataset.demographics.handedness.right} right, {dataset.demographics.handedness.left} left
                            {dataset.demographics.handedness.ambidextrous && `, ${dataset.demographics.handedness.ambidextrous} ambidextrous`}
                          </div>
                        </div>
                      )}
                    </CardContent>
                  </Card>
                )}
              </div>

              {/* Tasks and Constructs */}
              {(dataset.tasks || dataset.constructs) && (
                <div className="grid md:grid-cols-2 gap-6">
                  {dataset.tasks && (
                    <Card>
                      <CardHeader>
                        <CardTitle className="text-lg">Tasks</CardTitle>
                      </CardHeader>
                      <CardContent>
                        <div className="flex flex-wrap gap-2">
                          {dataset.tasks.map((task) => (
                            <span
                              key={task}
                              className="px-3 py-1 bg-primary/10 text-primary rounded-full text-sm"
                            >
                              {task}
                            </span>
                          ))}
                        </div>
                      </CardContent>
                    </Card>
                  )}

                  {dataset.constructs && (
                    <Card>
                      <CardHeader>
                        <CardTitle className="text-lg">Cognitive Constructs</CardTitle>
                      </CardHeader>
                      <CardContent>
                        <div className="flex flex-wrap gap-2">
                          {dataset.constructs.map((construct) => (
                            <span
                              key={construct}
                              className="px-3 py-1 bg-secondary text-secondary-foreground rounded-full text-sm"
                            >
                              {construct}
                            </span>
                          ))}
                        </div>
                      </CardContent>
                    </Card>
                  )}
                </div>
              )}

              {/* README */}
              {dataset.readme && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-lg">README</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <pre className="whitespace-pre-wrap text-sm text-muted-foreground font-sans">
                      {dataset.readme}
                    </pre>
                  </CardContent>
                </Card>
              )}

              {/* External links */}
              <div className="flex gap-3">
                {dataset.url && (
                  <Button variant="outline" asChild>
                    <a href={dataset.url} target="_blank" rel="noopener noreferrer">
                      <ExternalLink className="h-4 w-4 mr-2" />
                      View on {dataset.source}
                    </a>
                  </Button>
                )}
                
                {dataset.doi && (
                  <Button variant="outline" asChild>
                    <a href={`https://doi.org/${dataset.doi}`} target="_blank" rel="noopener noreferrer">
                      <ExternalLink className="h-4 w-4 mr-2" />
                      DOI
                    </a>
                  </Button>
                )}
              </div>
            </div>
          )}

          {activeTab === 'structure' && (
            <div>
              {dataset.bidsTree ? (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-lg">BIDS File Structure</CardTitle>
                    <CardDescription>
                      Explore the Brain Imaging Data Structure (BIDS) organization of this dataset
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="bg-muted/30 rounded-lg p-4 max-h-96 overflow-y-auto">
                      {dataset.bidsTree.map((node, index) => (
                        <BidsTreeNode key={index} node={node} />
                      ))}
                    </div>
                  </CardContent>
                </Card>
              ) : (
                <div className="text-center py-8 text-muted-foreground">
                  <Folder className="h-12 w-12 mx-auto mb-4" />
                  <p>BIDS structure not available for this dataset</p>
                </div>
              )}
            </div>
          )}

          {activeTab === 'contrasts' && (
            <div>
              {dataset.contrasts && dataset.contrasts.length > 0 ? (
                <div className="space-y-4">
                  {dataset.contrasts.map((contrast, index) => (
                    <Card key={index}>
                      <CardHeader>
                        <CardTitle className="text-lg flex items-center gap-2">
                          <Brain className="h-5 w-5" />
                          {contrast.name}
                          <span className="text-sm font-normal bg-muted px-2 py-1 rounded">
                            {contrast.type}-contrast
                          </span>
                        </CardTitle>
                        <CardDescription>{contrast.description}</CardDescription>
                      </CardHeader>
                      <CardContent>
                        <div>
                          <div className="font-medium text-sm mb-2">Conditions:</div>
                          <div className="flex flex-wrap gap-2">
                            {contrast.conditions.map((condition) => (
                              <span
                                key={condition}
                                className="px-2 py-1 bg-primary/10 text-primary rounded text-sm"
                              >
                                {condition}
                              </span>
                            ))}
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              ) : (
                <div className="text-center py-8 text-muted-foreground">
                  <Brain className="h-12 w-12 mx-auto mb-4" />
                  <p>No contrasts defined for this dataset</p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
