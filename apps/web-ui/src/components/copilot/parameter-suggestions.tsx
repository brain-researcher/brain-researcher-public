'use client'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ParameterSuggestion } from '@/types/copilot'
import { Zap, Info, Plus, ExternalLink } from 'lucide-react'

interface ParameterSuggestionsProps {
  suggestions: ParameterSuggestion[]
  onInsert: (suggestion: ParameterSuggestion) => void
  className?: string
}

export function ParameterSuggestions({ suggestions, onInsert, className }: ParameterSuggestionsProps) {
  const fromBackend = suggestions.some(s => s.source === 'backend')

  const getCategoryColor = (category: string) => {
    switch (category) {
      case 'preprocessing': return 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300'
      case 'analysis': return 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300'
      case 'statistics': return 'bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300'
      case 'visualization': return 'bg-orange-100 text-orange-700 dark:bg-orange-900 dark:text-orange-300'
      case 'backend': return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300'
      default: return 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300'
    }
  }

  const getConfidenceColor = (confidence: number) => {
    if (confidence >= 0.8) return 'text-green-600 dark:text-green-400'
    if (confidence >= 0.6) return 'text-yellow-600 dark:text-yellow-400'
    return 'text-red-600 dark:text-red-400'
  }

  if (suggestions.length === 0) {
    return (
      <div className={`text-center py-8 text-muted-foreground ${className}`}>
        <Zap className="h-8 w-8 mx-auto mb-2 opacity-50" />
        <p className="text-sm">No parameter suggestions available</p>
        <p className="text-xs">Select a dataset to get recommendations</p>
      </div>
    )
  }

  return (
    <div className={`space-y-3 ${className}`}>
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-semibold text-sm flex items-center gap-2">
          <Zap className="h-4 w-4" />
          Parameter Suggestions
        </h3>
        <span className="text-[10px] text-muted-foreground uppercase tracking-wide">
          {fromBackend ? 'From assistant' : 'Default'}
        </span>
      </div>
      
      {suggestions.map((suggestion) => (
        <Card key={suggestion.id} className="group hover:shadow-md transition-shadow">
          <CardHeader className="pb-2">
            <div className="flex items-start justify-between">
              <div className="flex-1">
                <CardTitle className="text-sm font-medium">{suggestion.name}</CardTitle>
                <CardDescription className="text-xs">
                  {suggestion.description}
                </CardDescription>
              </div>
              
              <div className="flex items-center gap-1 ml-2">
                <Badge 
                  variant="secondary" 
                  className={`text-xs ${getCategoryColor(suggestion.category)}`}
                >
                  {suggestion.category}
                </Badge>
                
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onInsert(suggestion)}
                  className="h-6 w-6 p-0 opacity-0 group-hover:opacity-100 transition-opacity"
                >
                  <Plus className="h-3 w-3" />
                </Button>
              </div>
            </div>
          </CardHeader>
          
          <CardContent className="pt-0 space-y-2">
            <div className="flex items-center justify-between">
              <div className="font-mono text-sm bg-muted px-2 py-1 rounded">
                {String(suggestion.value)}
              </div>
              
              <div className={`text-xs font-medium ${getConfidenceColor(suggestion.confidence)}`}>
                {Math.round(suggestion.confidence * 100)}% confidence
              </div>
            </div>
            
            <div className="text-xs text-muted-foreground">
              <div className="flex items-start gap-1">
                <Info className="h-3 w-3 mt-0.5 flex-shrink-0" />
                <span>{suggestion.reasoning}</span>
              </div>
            </div>
            
            {suggestion.citation && (
              <div className="text-xs text-muted-foreground flex items-center gap-1">
                <ExternalLink className="h-3 w-3" />
                <span>{suggestion.citation}</span>
              </div>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  )
}