/**
 * FeatureAdoptionChart - Interactive chart for feature adoption visualization
 * Part of TELEMETRY-003 Usage Metrics Tracking System
 */

'use client';

import React, { useState, useEffect, useMemo } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Progress } from '@/components/ui/progress';
import { 
  BarChart, 
  Bar, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ResponsiveContainer,
  LineChart,
  Line,
  ScatterChart,
  Scatter,
  Area,
  AreaChart,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  Treemap,
  Cell
} from 'recharts';
import { 
  TrendingUp, 
  TrendingDown, 
  Minus,
  Users, 
  Calendar,
  Target,
  Lightbulb,
  ArrowUp,
  ArrowDown,
  Clock,
  Activity
} from 'lucide-react';
import { useTelemetry, type FeatureUsage } from './telemetry-provider';
import { useInteractionTracking } from './telemetry-provider';

interface AdoptionDataPoint {
  featureName: string;
  adoptionRate: number;
  totalUsers: number;
  totalUses: number;
  successRate: number;
  trend: 'increasing' | 'decreasing' | 'stable';
  periodChange: number;
  category: string;
  maturityStage: 'early' | 'growth' | 'mature' | 'declining';
  riskLevel: 'low' | 'medium' | 'high';
}

interface AdoptionTrendPoint {
  period: string;
  [featureName: string]: any;
}

interface MaturityAnalysis {
  stage: string;
  features: string[];
  averageAdoption: number;
  totalUsers: number;
  recommendations: string[];
}

const CHART_COLORS = [
  '#8884d8', '#82ca9d', '#ffc658', '#ff7300', '#00ff00',
  '#ff00ff', '#00ffff', '#ff0000', '#0000ff', '#ffff00',
  '#8dd1e1', '#d084d0', '#87d068', '#ffa940', '#722ed1'
];

const FEATURE_CATEGORIES = {
  'analysis': 'Analysis Tools',
  'visualization': 'Visualization',
  'data': 'Data Management', 
  'collaboration': 'Collaboration',
  'workflow': 'Workflow',
  'ui': 'User Interface',
  'search': 'Search & Discovery',
  'export': 'Export & Sharing'
};

const getMaturityStage = (adoptionRate: number, totalUsers: number, trend: string): 'early' | 'growth' | 'mature' | 'declining' => {
  if (adoptionRate < 0.1) return 'early';
  if (adoptionRate < 0.3 && trend === 'increasing') return 'growth';
  if (adoptionRate >= 0.3 && trend !== 'decreasing') return 'mature';
  return 'declining';
};

const getRiskLevel = (successRate: number, adoptionRate: number, trend: string): 'low' | 'medium' | 'high' => {
  if (successRate < 0.8 || (adoptionRate < 0.1 && trend === 'decreasing')) return 'high';
  if (successRate < 0.9 || trend === 'decreasing') return 'medium';
  return 'low';
};

const categorizeFeature = (featureName: string): string => {
  const name = featureName.toLowerCase();
  if (name.includes('analysis') || name.includes('glm') || name.includes('statistical')) return 'analysis';
  if (name.includes('plot') || name.includes('chart') || name.includes('visual')) return 'visualization';
  if (name.includes('data') || name.includes('load') || name.includes('import')) return 'data';
  if (name.includes('share') || name.includes('collaborate')) return 'collaboration';
  if (name.includes('workflow') || name.includes('pipeline')) return 'workflow';
  if (name.includes('search') || name.includes('find') || name.includes('discover')) return 'search';
  if (name.includes('export') || name.includes('download') || name.includes('save')) return 'export';
  return 'ui';
};

const formatNumber = (num: number): string => {
  if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
  if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
  return num.toString();
};

const TrendIcon: React.FC<{ trend: string; value: number }> = ({ trend, value }) => {
  const color = trend === 'increasing' ? 'text-green-500' : 
                trend === 'decreasing' ? 'text-red-500' : 'text-gray-500';
  const Icon = trend === 'increasing' ? ArrowUp : 
               trend === 'decreasing' ? ArrowDown : Minus;
  
  return (
    <div className={`flex items-center ${color}`}>
      <Icon className="w-3 h-3 mr-1" />
      <span className="text-xs font-medium">
        {value > 0 ? '+' : ''}{value.toFixed(1)}%
      </span>
    </div>
  );
};

const AdoptionTooltip: React.FC<{ active?: boolean; payload?: any[]; label?: string }> = ({ 
  active, payload, label 
}) => {
  if (!active || !payload || !payload.length) return null;

  const data = payload[0].payload;
  return (
    <div className="bg-white p-3 border rounded-lg shadow-lg">
      <h4 className="font-medium mb-2">{data.featureName}</h4>
      <div className="space-y-1 text-sm">
        <div>Adoption Rate: <strong>{(data.adoptionRate * 100).toFixed(1)}%</strong></div>
        <div>Total Users: <strong>{formatNumber(data.totalUsers)}</strong></div>
        <div>Success Rate: <strong>{(data.successRate * 100).toFixed(1)}%</strong></div>
        <div>Category: <strong>{FEATURE_CATEGORIES[data.category as keyof typeof FEATURE_CATEGORIES] || data.category}</strong></div>
        <div className="flex items-center">
          <span>Trend: </span>
          <TrendIcon trend={data.trend} value={data.periodChange} />
        </div>
      </div>
    </div>
  );
};

export const FeatureAdoptionChart: React.FC = () => {
  const { getFeatureAnalysis } = useTelemetry();
  const trackInteraction = useInteractionTracking('feature_adoption_chart');

  const [features, setFeatures] = useState<FeatureUsage[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedService, setSelectedService] = useState<string>('all');
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [viewType, setViewType] = useState<'scatter' | 'bar' | 'trend' | 'matrix'>('scatter');
  const [timeRange, setTimeRange] = useState<'7d' | '30d' | '90d'>('30d');

  const adoptionData: AdoptionDataPoint[] = useMemo(() => {
    return features.map(feature => ({
      featureName: feature.featureName,
      adoptionRate: feature.adoptionRate,
      totalUsers: feature.uniqueUsers,
      totalUses: feature.totalUses,
      successRate: feature.successRate,
      trend: feature.trend,
      periodChange: feature.periodOverPeriodChange,
      category: categorizeFeature(feature.featureName),
      maturityStage: getMaturityStage(feature.adoptionRate, feature.uniqueUsers, feature.trend),
      riskLevel: getRiskLevel(feature.successRate, feature.adoptionRate, feature.trend)
    }));
  }, [features]);

  const filteredData = useMemo(() => {
    let filtered = adoptionData;
    
    if (selectedService !== 'all') {
      const serviceFeatures = features.filter(f => f.service === selectedService);
      filtered = filtered.filter(d => serviceFeatures.some(f => f.featureName === d.featureName));
    }
    
    if (selectedCategory !== 'all') {
      filtered = filtered.filter(d => d.category === selectedCategory);
    }
    
    return filtered;
  }, [adoptionData, selectedService, selectedCategory, features]);

  const maturityAnalysis = useMemo(() => {
    const analysis: { [key: string]: MaturityAnalysis } = {};
    
    ['early', 'growth', 'mature', 'declining'].forEach(stage => {
      const stageFeatures = filteredData.filter(d => d.maturityStage === stage);
      analysis[stage] = {
        stage,
        features: stageFeatures.map(f => f.featureName),
        averageAdoption: stageFeatures.reduce((sum, f) => sum + f.adoptionRate, 0) / (stageFeatures.length || 1),
        totalUsers: stageFeatures.reduce((sum, f) => sum + f.totalUsers, 0),
        recommendations: generateRecommendations(stage, stageFeatures)
      };
    });
    
    return analysis;
  }, [filteredData]);

  const generateRecommendations = (stage: string, stageFeatures: AdoptionDataPoint[]): string[] => {
    const recommendations: string[] = [];
    
    switch (stage) {
      case 'early':
        recommendations.push('Consider improving onboarding and documentation');
        recommendations.push('Analyze user feedback to identify adoption barriers');
        if (stageFeatures.some(f => f.successRate < 0.8)) {
          recommendations.push('Fix reliability issues to build user trust');
        }
        break;
      case 'growth':
        recommendations.push('Focus on scaling infrastructure and performance');
        recommendations.push('Create advanced tutorials and use cases');
        recommendations.push('Monitor for quality issues as usage increases');
        break;
      case 'mature':
        recommendations.push('Optimize for efficiency and advanced use cases');
        recommendations.push('Consider feature extensions and integrations');
        break;
      case 'declining':
        recommendations.push('Investigate reasons for declining adoption');
        recommendations.push('Consider feature redesign or sunset planning');
        break;
    }
    
    return recommendations;
  };

  const loadData = async () => {
    setLoading(true);
    setError(null);

    try {
      const endTime = new Date();
      const daysMap = { '7d': 7, '30d': 30, '90d': 90 };
      const startTime = new Date(endTime.getTime() - daysMap[timeRange] * 24 * 60 * 60 * 1000);

      const featuresData = await getFeatureAnalysis({
        start_time: startTime.toISOString(),
        end_time: endTime.toISOString(),
        min_usage_count: 5
      });

      setFeatures(featuresData);
      trackInteraction('data_loaded', { 
        timeRange, 
        featuresCount: featuresData.length,
        selectedService,
        selectedCategory 
      });
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to load feature data';
      setError(errorMessage);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [timeRange]);

  const handleViewChange = (newView: string) => {
    setViewType(newView as any);
    trackInteraction('view_changed', { view: newView });
  };

  const handleFilterChange = (filterType: string, value: string) => {
    if (filterType === 'service') {
      setSelectedService(value);
    } else if (filterType === 'category') {
      setSelectedCategory(value);
    }
    trackInteraction('filter_changed', { filterType, value });
  };

  if (loading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center p-8">
          <Activity className="w-6 h-6 animate-pulse mr-2" />
          <span>Loading adoption data...</span>
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center p-8">
          <span className="text-red-500">Error: {error}</span>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <div className="flex justify-between items-start">
            <div>
              <CardTitle>Feature Adoption Analysis</CardTitle>
              <CardDescription>
                Track feature adoption rates, usage patterns, and maturity lifecycle
              </CardDescription>
            </div>
            <div className="flex space-x-2">
              <Select value={timeRange} onValueChange={(value: any) => setTimeRange(value)}>
                <SelectTrigger className="w-32">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="7d">Last 7 days</SelectItem>
                  <SelectItem value="30d">Last 30 days</SelectItem>
                  <SelectItem value="90d">Last 90 days</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {/* Filters */}
          <div className="flex space-x-4 mb-6">
            <div>
              <label className="text-xs font-medium text-muted-foreground">Service</label>
              <Select value={selectedService} onValueChange={(value) => handleFilterChange('service', value)}>
                <SelectTrigger className="w-40">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Services</SelectItem>
                  <SelectItem value="web_ui">Web UI</SelectItem>
                  <SelectItem value="agent">Agent</SelectItem>
                  <SelectItem value="kg">Knowledge Graph</SelectItem>
                </SelectContent>
              </Select>
            </div>
            
            <div>
              <label className="text-xs font-medium text-muted-foreground">Category</label>
              <Select value={selectedCategory} onValueChange={(value) => handleFilterChange('category', value)}>
                <SelectTrigger className="w-40">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Categories</SelectItem>
                  {Object.entries(FEATURE_CATEGORIES).map(([key, label]) => (
                    <SelectItem key={key} value={key}>{label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* Chart Tabs */}
          <Tabs value={viewType} onValueChange={handleViewChange} className="space-y-4">
            <TabsList>
              <TabsTrigger value="scatter">Adoption Matrix</TabsTrigger>
              <TabsTrigger value="bar">Usage Ranking</TabsTrigger>
              <TabsTrigger value="trend">Trend Analysis</TabsTrigger>
              <TabsTrigger value="matrix">Maturity Matrix</TabsTrigger>
            </TabsList>

            <TabsContent value="scatter">
              <div className="h-96">
                <ResponsiveContainer width="100%" height="100%">
                  <ScatterChart data={filteredData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis 
                      type="number" 
                      dataKey="adoptionRate" 
                      name="Adoption Rate"
                      domain={[0, 1]}
                      tickFormatter={(value) => `${(value * 100).toFixed(0)}%`}
                    />
                    <YAxis 
                      type="number" 
                      dataKey="successRate" 
                      name="Success Rate"
                      domain={[0, 1]}
                      tickFormatter={(value) => `${(value * 100).toFixed(0)}%`}
                    />
                    <Tooltip content={<AdoptionTooltip />} />
                    <Scatter 
                      data={filteredData} 
                      fill="#8884d8"
                    >
                      {filteredData.map((entry, index) => (
                        <Cell 
                          key={`cell-${index}`} 
                          fill={
                            entry.riskLevel === 'high' ? '#ff4444' :
                            entry.riskLevel === 'medium' ? '#ffaa44' : '#44aa44'
                          }
                        />
                      ))}
                    </Scatter>
                  </ScatterChart>
                </ResponsiveContainer>
              </div>
              <div className="mt-4 flex justify-center space-x-6">
                <div className="flex items-center">
                  <div className="w-3 h-3 bg-green-500 rounded mr-2"></div>
                  <span className="text-sm">Low Risk</span>
                </div>
                <div className="flex items-center">
                  <div className="w-3 h-3 bg-yellow-500 rounded mr-2"></div>
                  <span className="text-sm">Medium Risk</span>
                </div>
                <div className="flex items-center">
                  <div className="w-3 h-3 bg-red-500 rounded mr-2"></div>
                  <span className="text-sm">High Risk</span>
                </div>
              </div>
            </TabsContent>

            <TabsContent value="bar">
              <div className="h-96">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={filteredData.slice(0, 15)} layout="horizontal">
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis type="number" tickFormatter={(value) => `${(value * 100).toFixed(0)}%`} />
                    <YAxis type="category" dataKey="featureName" width={120} />
                    <Tooltip 
                      formatter={(value: any) => [`${(value * 100).toFixed(1)}%`, 'Adoption Rate']}
                    />
                    <Bar dataKey="adoptionRate" fill="#8884d8" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </TabsContent>

            <TabsContent value="trend">
              <div className="space-y-4">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  {['increasing', 'stable', 'decreasing'].map(trend => {
                    const trendFeatures = filteredData.filter(f => f.trend === trend);
                    const avgChange = trendFeatures.reduce((sum, f) => sum + f.periodChange, 0) / 
                      (trendFeatures.length || 1);
                    
                    return (
                      <Card key={trend}>
                        <CardContent className="p-4">
                          <div className="flex items-center justify-between">
                            <div>
                              <h4 className="font-medium capitalize">{trend}</h4>
                              <p className="text-sm text-muted-foreground">
                                {trendFeatures.length} features
                              </p>
                            </div>
                            <TrendIcon trend={trend} value={avgChange} />
                          </div>
                        </CardContent>
                      </Card>
                    );
                  })}
                </div>

                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={Object.entries(
                      filteredData.reduce((acc, feature) => {
                        acc[feature.trend] = (acc[feature.trend] || 0) + 1;
                        return acc;
                      }, {} as Record<string, number>)
                    ).map(([trend, count]) => ({ trend, count }))}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="trend" />
                      <YAxis />
                      <Tooltip />
                      <Bar dataKey="count" fill="#82ca9d" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </TabsContent>

            <TabsContent value="matrix">
              <div className="space-y-6">
                {/* Maturity Overview */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  {Object.entries(maturityAnalysis).map(([stage, analysis]) => (
                    <Card key={stage}>
                      <CardContent className="p-4">
                        <div className="flex items-center justify-between mb-2">
                          <h4 className="font-medium capitalize">{stage}</h4>
                          <Badge variant="secondary">{analysis.features.length}</Badge>
                        </div>
                        <div className="space-y-1 text-sm">
                          <div>
                            Avg Adoption: {(analysis.averageAdoption * 100).toFixed(1)}%
                          </div>
                          <div>
                            Total Users: {formatNumber(analysis.totalUsers)}
                          </div>
                        </div>
                        <Progress 
                          value={analysis.averageAdoption * 100} 
                          className="mt-2" 
                        />
                      </CardContent>
                    </Card>
                  ))}
                </div>

                {/* Feature Matrix */}
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <Treemap
                      data={filteredData.map(f => ({
                        name: f.featureName,
                        size: f.totalUsers,
                        adoption: f.adoptionRate
                      }))}
                      dataKey="size"
                      aspectRatio={4/3}
                      stroke="#fff"
                      fill="#8884d8"
                    />
                  </ResponsiveContainer>
                </div>

                {/* Recommendations */}
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center">
                      <Lightbulb className="w-4 h-4 mr-2" />
                      Recommendations
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-4">
                      {Object.entries(maturityAnalysis).map(([stage, analysis]) => (
                        analysis.features.length > 0 && (
                          <div key={stage}>
                            <h4 className="font-medium capitalize mb-2">{stage} Stage Features</h4>
                            <ul className="space-y-1 text-sm text-muted-foreground ml-4">
                              {analysis.recommendations.map((rec, index) => (
                                <li key={index} className="flex items-start">
                                  <span className="w-1 h-1 bg-gray-400 rounded-full mt-2 mr-2 flex-shrink-0"></span>
                                  {rec}
                                </li>
                              ))}
                            </ul>
                          </div>
                        )
                      ))}
                    </div>
                  </CardContent>
                </Card>
              </div>
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </div>
  );
};

export default FeatureAdoptionChart;
