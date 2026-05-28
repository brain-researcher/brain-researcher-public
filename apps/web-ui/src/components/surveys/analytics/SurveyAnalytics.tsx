/**
 * Survey Analytics Component
 * Comprehensive analytics dashboard for survey performance and insights
 */

'use client';

import React, { useState, useEffect } from 'react';
import { 
  BarChart3, 
  TrendingUp, 
  Users, 
  Clock, 
  CheckCircle, 
  AlertCircle,
  Brain,
  Download,
  RefreshCw,
  Calendar,
  Filter,
  Eye,
  Star
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { 
  Select, 
  SelectContent, 
  SelectItem, 
  SelectTrigger, 
  SelectValue 
} from '@/components/ui/select';
import { DatePickerWithRange } from '@/components/ui/date-picker';
import { Alert, AlertDescription } from '@/components/ui/alert';

import { useSurveyAnalytics } from '@/hooks/useSurvey';
import { SurveyInsight, InsightType } from '@/types/survey';
import { ResponseRateChart } from './ResponseRateChart';
import { InsightsSummary } from './InsightsSummary';

interface SurveyAnalyticsProps {
  surveyIds: string[];
  dateRange?: { start: string; end: string };
  refreshInterval?: number;
}

export function SurveyAnalytics({ 
  surveyIds, 
  dateRange, 
  refreshInterval = 30000 
}: SurveyAnalyticsProps) {
  const [selectedDateRange, setSelectedDateRange] = useState(dateRange);
  const [activeTab, setActiveTab] = useState('overview');
  const [selectedInsightType, setSelectedInsightType] = useState<InsightType | 'all'>('all');

  const { 
    analytics, 
    insights, 
    loading, 
    error, 
    fetchInsights, 
    refetch 
  } = useSurveyAnalytics(surveyIds, selectedDateRange);

  // Auto-refresh
  useEffect(() => {
    if (refreshInterval > 0) {
      const interval = setInterval(refetch, refreshInterval);
      return () => clearInterval(interval);
    }
  }, [refetch, refreshInterval]);

  const renderKPICards = () => {
    const normalizeRate = (value?: number | null) => {
      if (typeof value !== 'number' || !Number.isFinite(value)) return undefined;
      if (value > 0 && value <= 1) return Math.round(value * 1000) / 10;
      return value;
    };

    const responseRates = analytics.response_rates ?? analytics.response_rate ?? {};
    const completionRates = analytics.completion_rates ?? analytics.completion_rate ?? {};

    const responseRateEntries = Object.values(responseRates).map((entry: any) => {
      if (typeof entry === 'number') return { rate: normalizeRate(entry), responses: undefined };
      if (!entry || typeof entry !== 'object') return { rate: undefined, responses: undefined };
      return {
        rate: normalizeRate(entry.rate ?? entry.response_rate),
        responses: entry.responses ?? entry.count ?? entry.total_responses,
      };
    });

    const completionRateEntries = Object.values(completionRates).map((entry: any) => {
      if (typeof entry === 'number') return normalizeRate(entry);
      if (!entry || typeof entry !== 'object') return undefined;
      return normalizeRate(entry.rate ?? entry.completion_rate);
    });

    const totalResponses =
      responseRateEntries.reduce((sum, entry) => sum + (entry.responses ?? 0), 0) ||
      analytics.total_responses ||
      0;

    const avgResponseRate = responseRateEntries.length
      ? responseRateEntries.reduce((sum, entry) => sum + (entry.rate ?? 0), 0) /
        responseRateEntries.filter((entry) => entry.rate != null).length
      : normalizeRate(analytics.response_rate);

    const avgCompletionRate = completionRateEntries.length
      ? completionRateEntries.reduce((sum, rate) => sum + (rate ?? 0), 0) /
        completionRateEntries.filter((rate) => rate != null).length
      : normalizeRate(analytics.completion_rate);

    const avgCompletionSeconds =
      analytics.average_completion_time ??
      analytics.avg_completion_time ??
      analytics.quality_metrics?.completion_time_analysis?.average_seconds;

    const avgCompletionDisplay =
      typeof avgCompletionSeconds === 'number' && Number.isFinite(avgCompletionSeconds)
        ? `${Math.round((avgCompletionSeconds / 60) * 10) / 10} min`
        : '—';

    const kpis: Array<{ title: string; value: string | number; icon: any; color: string; bgColor: string; subtitle?: string }> = [
      {
        title: 'Total Responses',
        value: totalResponses || '—',
        icon: Users,
        color: 'text-blue-600',
        bgColor: 'bg-blue-100',
      },
      {
        title: 'Avg Response Rate',
        value: typeof avgResponseRate === 'number' ? `${avgResponseRate.toFixed(1)}%` : '—',
        icon: TrendingUp,
        color: 'text-green-600',
        bgColor: 'bg-green-100',
      },
      {
        title: 'Completion Rate',
        value: typeof avgCompletionRate === 'number' ? `${avgCompletionRate.toFixed(1)}%` : '—',
        icon: CheckCircle,
        color: 'text-purple-600',
        bgColor: 'bg-purple-100',
      },
      {
        title: 'Avg Time',
        value: avgCompletionDisplay,
        icon: Clock,
        color: 'text-orange-600',
        bgColor: 'bg-orange-100',
      }
    ];

    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-6">
        {kpis.map((kpi, index) => (
          <Card key={index}>
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-600">{kpi.title}</p>
                  <p className="text-2xl font-bold text-gray-900">{kpi.value}</p>
                </div>
                <div className={`p-3 rounded-full ${kpi.bgColor}`}>
                  <kpi.icon className={`h-6 w-6 ${kpi.color}`} />
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    );
  };

  const renderOverview = () => (
    <div className="space-y-6">
      {renderKPICards()}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Response Rate Chart */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <BarChart3 className="h-5 w-5" />
              Response Rates Over Time
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ResponseRateChart 
              data={analytics.response_rates}
              dateRange={selectedDateRange}
            />
          </CardContent>
        </Card>

        {/* Top Insights */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Brain className="h-5 w-5" />
              Key Insights
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {insights.slice(0, 3).map((insight, index) => (
                <div key={insight.id} className="border-l-4 border-blue-500 pl-4">
                  <div className="flex items-center gap-2 mb-1">
                    <Badge variant="outline" className="text-xs">
                      {insight.insight_type.replace('_', ' ')}
                    </Badge>
                    <div className="flex items-center text-yellow-500">
                      <Star className="h-3 w-3 mr-1" />
                      <span className="text-xs">{(insight.confidence_score * 5).toFixed(1)}</span>
                    </div>
                  </div>
                  <h4 className="font-medium text-sm">{insight.title}</h4>
                  <p className="text-xs text-gray-600 mt-1 line-clamp-2">
                    {insight.description}
                  </p>
                </div>
              ))}
              {insights.length === 0 && (
                <div className="text-center py-4 text-gray-500">
                  <AlertCircle className="h-8 w-8 mx-auto mb-2" />
                  <p>No insights available yet</p>
                  <p className="text-xs">Insights will appear as responses are collected</p>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Demographics Overview */}
      {analytics.demographics && (
        <Card>
          <CardHeader>
            <CardTitle>Demographics Overview</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              {Object.entries(analytics.demographics).map(([surveyId, demo]: [string, any]) => (
                <div key={surveyId} className="space-y-4">
                  <h4 className="font-medium">Survey {surveyId.substring(0, 8)}...</h4>
                  
                  {demo.age_distribution && (
                    <div>
                      <div className="text-sm font-medium text-gray-700 mb-2">Age Distribution</div>
                      <div className="text-2xl font-bold text-blue-600">
                        {demo.age_distribution.mean?.toFixed(1)} years
                      </div>
                      <div className="text-xs text-gray-600">
                        Range: {demo.age_distribution.ranges ? Object.keys(demo.age_distribution.ranges).join(', ') : 'N/A'}
                      </div>
                    </div>
                  )}
                  
                  {demo.gender_distribution && (
                    <div>
                      <div className="text-sm font-medium text-gray-700 mb-2">Gender</div>
                      <div className="space-y-1">
                        {Object.entries(demo.gender_distribution).map(([gender, count]: [string, any]) => (
                          <div key={gender} className="flex justify-between text-sm">
                            <span className="capitalize">{gender}</span>
                            <span className="font-medium">{count}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );

  const renderInsights = () => (
    <div className="space-y-6">
      {/* Insights Filter */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h3 className="text-lg font-semibold">AI-Generated Insights</h3>
          <Select value={selectedInsightType} onValueChange={(value: any) => setSelectedInsightType(value)}>
            <SelectTrigger className="w-48">
              <SelectValue placeholder="All insight types" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Types</SelectItem>
              <SelectItem value="sentiment_analysis">Sentiment Analysis</SelectItem>
              <SelectItem value="response_patterns">Response Patterns</SelectItem>
              <SelectItem value="completion_trends">Completion Trends</SelectItem>
              <SelectItem value="neuroimaging_correlations">Neuroimaging Correlations</SelectItem>
              <SelectItem value="quality_assessment">Quality Assessment</SelectItem>
              <SelectItem value="anomaly_detection">Anomaly Detection</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <Button onClick={() => fetchInsights(surveyIds[0])} size="sm">
          <RefreshCw className="h-4 w-4 mr-2" />
          Refresh Insights
        </Button>
      </div>

      <InsightsSummary 
        insights={insights}
        selectedType={selectedInsightType}
        onTypeFilter={setSelectedInsightType}
      />
    </div>
  );

  const renderResponses = () => (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">Response Analysis</h3>
        <Button size="sm">
          <Download className="h-4 w-4 mr-2" />
          Export Data
        </Button>
      </div>

      {/* Response Quality Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Response Quality</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              <div className="flex justify-between">
                <span className="text-sm text-gray-600">High Quality</span>
                <span className="font-medium text-green-600">78%</span>
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-gray-600">Medium Quality</span>
                <span className="font-medium text-yellow-600">18%</span>
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-gray-600">Low Quality</span>
                <span className="font-medium text-red-600">4%</span>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Completion Times</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              <div className="flex justify-between">
                <span className="text-sm text-gray-600">Average</span>
                <span className="font-medium">12.5 min</span>
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-gray-600">Median</span>
                <span className="font-medium">10.2 min</span>
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-gray-600">Fast (&lt;5&nbsp;min)</span>
                <span className="font-medium text-orange-600">15%</span>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Neuroimaging Responses</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              <div className="flex justify-between">
                <span className="text-sm text-gray-600">Scanner Params</span>
                <span className="font-medium">95%</span>
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-gray-600">Brain Regions</span>
                <span className="font-medium">87%</span>
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-gray-600">Cognitive Tests</span>
                <span className="font-medium">72%</span>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Response Patterns Alert */}
      <Alert>
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>
          <strong>Pattern Detected:</strong> 23% of responses show unusually fast completion times 
          for neuroimaging protocol questions. Consider reviewing data quality.
        </AlertDescription>
      </Alert>
    </div>
  );

  if (error) {
    return (
      <Card>
        <CardContent className="pt-6">
          <div className="text-center">
            <AlertCircle className="h-12 w-12 mx-auto mb-4 text-red-500" />
            <h3 className="text-lg font-semibold mb-2">Error Loading Analytics</h3>
            <p className="text-gray-600 mb-4">{error}</p>
            <Button onClick={refetch}>Try Again</Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Survey Analytics</h1>
          <p className="text-gray-600">
            Analysis for {surveyIds.length} survey{surveyIds.length > 1 ? 's' : ''}
          </p>
        </div>
        
        <div className="flex items-center gap-3">
          <DatePickerWithRange
            dateRange={selectedDateRange}
            onRangeChange={setSelectedDateRange}
          />
          <Button onClick={refetch} disabled={loading} size="sm">
            <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Loading State */}
      {loading && (
        <div className="flex items-center justify-center py-12">
          <div className="text-center">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
            <p className="text-gray-600">Loading analytics...</p>
          </div>
        </div>
      )}

      {/* Content */}
      {!loading && (
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList className="grid grid-cols-4 w-full max-w-2xl">
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="insights">AI Insights</TabsTrigger>
            <TabsTrigger value="responses">Responses</TabsTrigger>
            <TabsTrigger value="export">Export</TabsTrigger>
          </TabsList>

          <TabsContent value="overview" className="mt-6">
            {renderOverview()}
          </TabsContent>

          <TabsContent value="insights" className="mt-6">
            {renderInsights()}
          </TabsContent>

          <TabsContent value="responses" className="mt-6">
            {renderResponses()}
          </TabsContent>

          <TabsContent value="export" className="mt-6">
            <Card>
              <CardHeader>
                <CardTitle>Export Analytics Data</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  <p className="text-gray-600">
                    Export your survey analytics data in various formats for further analysis.
                  </p>
                  <div className="flex gap-3">
                    <Button>
                      <Download className="h-4 w-4 mr-2" />
                      Export CSV
                    </Button>
                    <Button variant="outline">
                      <Download className="h-4 w-4 mr-2" />
                      Export JSON
                    </Button>
                    <Button variant="outline">
                      <Download className="h-4 w-4 mr-2" />
                      Export Report (PDF)
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
