'use client'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { MethodRecommendation } from '@/types/copilot'
import { Brain, Lightbulb, Play, Star } from 'lucide-react'

interface MethodRecommendationsProps {
  recommendations: MethodRecommendation[]
  onInsert: (recommendation: MethodRecommendation) => void
  className?: string
}

export function MethodRecommendations({ recommendations, onInsert, className }: MethodRecommendationsProps) {
  const getCategoryColor = (category: string) => {
    switch (category) {
      case 'preprocessing': return 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300'
      case 'first_level': return 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300'
      case 'group_level': return 'bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300'
      case 'connectivity': return 'bg-orange-100 text-orange-700 dark:bg-orange-900 dark:text-orange-300'
      case 'machine_learning': return 'bg-pink-100 text-pink-700 dark:bg-pink-900 dark:text-pink-300'
      default: return 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300'
    }
  }

  const renderSuitabilityStars = (suitability: number) => {
    const stars = Math.round(suitability * 5)
    return Array.from({ length: 5 }, (_, i) => (
      <Star
        key={i}
        className={`h-3 w-3 ${
          i < stars 
            ? 'fill-yellow-400 text-yellow-400' 
            : 'text-gray-300 dark:text-gray-600'
        }`}
      />
    ))
  }

  if (recommendations.length === 0) {
    return (
      <div className={`text-center py-8 text-muted-foreground ${className}`}>
        <Brain className="h-8 w-8 mx-auto mb-2 opacity-50" />
        <p className="text-sm">No method recommendations available</p>
        <p className="text-xs">Describe your analysis goals to get suggestions</p>
      </div>
    )
  }

  return (
    <div className={`space-y-4 ${className}`}>
      <h3 className="font-semibold text-sm flex items-center gap-2">
        <Lightbulb className="h-4 w-4" />
        Method Recommendations
      </h3>
      
      {recommendations.map((recommendation) => (
        <Card key={recommendation.id} className="group hover:shadow-lg transition-all duration-200">
          <CardHeader className="pb-3">
            <div className="flex items-start justify-between">
              <div className="flex-1">
                <CardTitle className="text-base font-semibold flex items-center gap-2">
                  <Brain className="h-4 w-4" />
                  {recommendation.name}
                </CardTitle>
                <CardDescription className="mt-1">
                  {recommendation.description}
                </CardDescription>
              </div>
              
              <div className="flex items-center gap-2 ml-4">
                <Badge 
                  variant="secondary" 
                  className={`text-xs ${getCategoryColor(recommendation.category)}`}
                >
                  {recommendation.category.replace('_', ' ')}
                </Badge>
                
                <Button
                  variant="default"
                  size="sm"
                  onClick={() => onInsert(recommendation)}
                  className="opacity-0 group-hover:opacity-100 transition-opacity"
                >
                  <Play className="h-3 w-3 mr-1" />
                  Try It
                </Button>
              </div>
            </div>
          </CardHeader>
          
          <CardContent className="space-y-3">
            {/* Suitability rating */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium">Suitability:</span>
                <div className="flex items-center gap-0.5">
                  {renderSuitabilityStars(recommendation.suitability)}
                </div>
              </div>
              <div className="text-xs text-muted-foreground">
                {Math.round(recommendation.suitability * 100)}% match
              </div>
            </div>
            
            {/* Reasoning */}
            <div className="text-xs text-muted-foreground bg-muted/50 p-2 rounded">
              <strong>Why this method:</strong> {recommendation.reasoning}
            </div>
            
            {/* Key parameters */}
            {recommendation.parameters.length > 0 && (
              <div>
                <div className="text-xs font-medium mb-1">Key Parameters:</div>
                <div className="flex flex-wrap gap-1">
                  {recommendation.parameters.slice(0, 3).map((param) => (
                    <Badge key={param.id} variant="outline" className="text-xs">
                      {param.name}: {String(param.value)}
                    </Badge>
                  ))}
                  {recommendation.parameters.length > 3 && (
                    <Badge variant="outline" className="text-xs">
                      +{recommendation.parameters.length - 3} more
                    </Badge>
                  )}
                </div>
              </div>
            )}
            
            {/* Prerequisites */}
            {recommendation.prerequisites && recommendation.prerequisites.length > 0 && (
              <div>
                <div className="text-xs font-medium mb-1">Prerequisites:</div>
                <ul className="text-xs text-muted-foreground list-disc list-inside">
                  {recommendation.prerequisites.map((prereq, index) => (
                    <li key={index}>{prereq}</li>
                  ))}
                </ul>
              </div>
            )}
            
            {recommendation.example_prompt?.trim() ? (
              <div className="bg-muted/30 p-2 rounded">
                <div className="text-xs font-medium mb-1">Suggested prompt:</div>
                <div className="text-xs font-mono text-muted-foreground">
                  "{recommendation.example_prompt}"
                </div>
              </div>
            ) : null}
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
