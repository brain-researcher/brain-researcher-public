/**
 * Insights Summary Component
 * Displays AI-generated insights in an organized, actionable format
 */

'use client';

import React from 'react';
import { 
  Brain, 
  TrendingUp, 
  AlertTriangle, 
  CheckCircle, 
  Users, 
  Clock,
  Star,
  Eye,
  ChevronRight
} from 'lucide-react';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';

import { SurveyInsight, InsightType } from '@/types/survey';

interface InsightsSummaryProps {
  insights: SurveyInsight[];
  selectedType: InsightType | 'all';
  onTypeFilter: (type: InsightType | 'all') => void;
}

const INSIGHT_ICONS: Record<InsightType, React.ReactNode> = {
  sentiment_analysis: <Users className="h-5 w-5" />,
  response_patterns: <TrendingUp className="h-5 w-5" />,
  completion_trends: <Clock className="h-5 w-5" />,
  demographic_analysis: <Users className="h-5 w-5" />,
  neuroimaging_correlations: <Brain className="h-5 w-5" />,
  quality_assessment: <CheckCircle className="h-5 w-5" />,
  comparative_analysis: <TrendingUp className="h-5 w-5" />,
  predictive_insights: <Star className="h-5 w-5" />,
  anomaly_detection: <AlertTriangle className="h-5 w-5" />
};

const INSIGHT_COLORS: Record<InsightType, string> = {
  sentiment_analysis: 'text-blue-600',
  response_patterns: 'text-green-600',
  completion_trends: 'text-orange-600',
  demographic_analysis: 'text-purple-600',
  neuroimaging_correlations: 'text-indigo-600',
  quality_assessment: 'text-emerald-600',
  comparative_analysis: 'text-cyan-600',
  predictive_insights: 'text-yellow-600',
  anomaly_detection: 'text-red-600'
};

export function InsightsSummary({ 
  insights, 
  selectedType, 
  onTypeFilter 
}: InsightsSummaryProps) {
  const filteredInsights = selectedType === 'all' 
    ? insights 
    : insights.filter(insight => insight.insight_type === selectedType);

  const getInsightPriority = (insight: SurveyInsight): 'high' | 'medium' | 'low' => {
    if (insight.insight_type === 'anomaly_detection' || insight.confidence_score >= 0.8) {
      return 'high';
    }
    if (insight.confidence_score >= 0.6) {
      return 'medium';
    }
    return 'low';
  };

  const getPriorityBadge = (priority: 'high' | 'medium' | 'low') => {
    const variants = {
      high: 'destructive',
      medium: 'default',
      low: 'secondary'
    } as const;

    return (
      <Badge variant={variants[priority]} className="text-xs">
        {priority.toUpperCase()}
      </Badge>
    );
  };

  const renderInsightCard = (insight: SurveyInsight) => {
    const priority = getInsightPriority(insight);
    const iconColor = INSIGHT_COLORS[insight.insight_type as InsightType];
    
    return (
      <Card key={insight.id} className="hover:shadow-lg transition-shadow">
        <CardHeader className="pb-3">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-3">
              <div className={`${iconColor}`}>
                {INSIGHT_ICONS[insight.insight_type as InsightType] || <Brain className="h-5 w-5" />}
              </div>
              <div>
                <CardTitle className="text-lg">{insight.title}</CardTitle>
                <div className="flex items-center gap-2 mt-1">
                  <Badge variant="outline" className="text-xs">
                    {insight.insight_type.replace('_', ' ')}
                  </Badge>
                  {getPriorityBadge(priority)}
                  <div className="flex items-center text-yellow-500">
                    <Star className="h-3 w-3 mr-1" />
                    <span className="text-xs font-medium">
                      {(insight.confidence_score * 5).toFixed(1)}/5.0
                    </span>
                  </div>
                </div>
              </div>
            </div>
            <Button variant="ghost" size="sm">
              <Eye className="h-4 w-4" />
            </Button>
          </div>
        </CardHeader>
        
        <CardContent className="space-y-4">
          <p className="text-gray-700 leading-relaxed">
            {insight.description}
          </p>
          
          {/* Supporting Data Preview */}
          {insight.supporting_data && Object.keys(insight.supporting_data).length > 0 && (
            <div className="bg-gray-50 rounded-lg p-3">
              <div className="text-sm font-medium text-gray-700 mb-2">Key Data Points:</div>
              <div className="grid grid-cols-2 gap-3 text-sm">
                {Object.entries(insight.supporting_data).slice(0, 4).map(([key, value]) => (
                  <div key={key} className="flex justify-between">
                    <span className="text-gray-600 capitalize">
                      {key.replace('_', ' ')}:
                    </span>
                    <span className="font-medium">
                      {typeof value === 'number' ? value.toFixed(1) : String(value)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
          
          {/* Methodology */}
          <div className="flex items-center justify-between text-xs text-gray-500">
            <span>Generated by: {insight.generated_by}</span>
            <span>{new Date(insight.generated_at).toLocaleDateString()}</span>
          </div>
          
          {/* Action Items for High Priority */}
          {priority === 'high' && insight.insight_type === 'anomaly_detection' && (
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>
                <strong>Action Required:</strong> Review flagged responses for data quality issues.
              </AlertDescription>
            </Alert>
          )}
          
          {priority === 'high' && insight.insight_type === 'quality_assessment' && (
            <Alert>
              <CheckCircle className="h-4 w-4" />
              <AlertDescription>
                <strong>Recommendation:</strong> Consider implementing suggested data quality improvements.
              </AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>
    );
  };

  const renderInsightCategories = () => {
    const categories = insights.reduce((acc, insight) => {
      const type = insight.insight_type as InsightType;
      if (!acc[type]) acc[type] = [];
      acc[type].push(insight);
      return acc;
    }, {} as Record<InsightType, SurveyInsight[]>);

    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
        {Object.entries(categories).map(([type, typeInsights]) => (
          <Card 
            key={type}
            className={`cursor-pointer transition-colors ${
              selectedType === type ? 'ring-2 ring-blue-500 bg-blue-50' : 'hover:bg-gray-50'
            }`}
            onClick={() => onTypeFilter(type as InsightType)}
          >
            <CardContent className="p-4 text-center">
              <div className={`${INSIGHT_COLORS[type as InsightType]} mb-2`}>
                {INSIGHT_ICONS[type as InsightType]}
              </div>
              <div className="text-sm font-medium capitalize mb-1">
                {type.replace('_', ' ')}
              </div>
              <div className="text-2xl font-bold text-gray-900">
                {typeInsights.length}
              </div>
              <div className="text-xs text-gray-500">
                Avg confidence: {(typeInsights.reduce((sum, i) => sum + i.confidence_score, 0) / typeInsights.length).toFixed(2)}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    );
  };

  if (insights.length === 0) {
    return (
      <Card>
        <CardContent className="pt-6 text-center">
          <Brain className="h-12 w-12 mx-auto mb-4 text-gray-400" />
          <h3 className="text-lg font-semibold mb-2">No Insights Available</h3>
          <p className="text-gray-600 mb-4">
            Insights will be generated automatically as survey responses are collected. 
            You need at least 5 responses to generate meaningful insights.
          </p>
          <Alert>
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>
              <strong>Tip:</strong> Insights improve in quality and accuracy as more responses are collected. 
              Check back after reaching 20+ responses for comprehensive analysis.
            </AlertDescription>
          </Alert>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      {/* Categories Overview */}
      <div>
        <h3 className="text-lg font-semibold mb-4">Insights by Category</h3>
        {renderInsightCategories()}
      </div>

      {/* Filter Info */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-600">
            Showing {filteredInsights.length} of {insights.length} insights
          </span>
          {selectedType !== 'all' && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onTypeFilter('all')}
            >
              Clear filter
            </Button>
          )}
        </div>
        
        <div className="text-xs text-gray-500">
          Last updated: {new Date().toLocaleString()}
        </div>
      </div>

      {/* Insights List */}
      <div className="space-y-4">
        {filteredInsights
          .sort((a, b) => {
            // Sort by priority (high confidence and anomalies first)
            const aPriority = getInsightPriority(a);
            const bPriority = getInsightPriority(b);
            
            const priorityOrder = { high: 3, medium: 2, low: 1 };
            if (priorityOrder[aPriority] !== priorityOrder[bPriority]) {
              return priorityOrder[bPriority] - priorityOrder[aPriority];
            }
            
            // Then by confidence score
            return b.confidence_score - a.confidence_score;
          })
          .map(renderInsightCard)}
      </div>

      {/* Insights Summary */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Insights Summary</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="text-center">
              <div className="text-2xl font-bold text-red-600">
                {filteredInsights.filter(i => getInsightPriority(i) === 'high').length}
              </div>
              <div className="text-sm text-gray-600">High Priority</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-blue-600">
                {(filteredInsights.reduce((sum, i) => sum + i.confidence_score, 0) / filteredInsights.length).toFixed(2)}
              </div>
              <div className="text-sm text-gray-600">Avg Confidence</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-green-600">
                {filteredInsights.filter(i => i.insight_type.includes('neuroimaging')).length}
              </div>
              <div className="text-sm text-gray-600">Neuroimaging Specific</div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}