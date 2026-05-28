'use client'

import { useState, useEffect } from 'react'
import { Shield, Database, Users, Award, TrendingUp, Zap, Globe, Check } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'

interface TrustMetric {
  id: string
  label: string
  value: string | number
  icon: React.ComponentType<{ className?: string }>
  description: string
  trend?: {
    direction: 'up' | 'down' | 'stable'
    value: string
  }
  color: string
  animate?: boolean
}

interface ToolLogo {
  name: string
  logo: string
  description: string
  category: 'analysis' | 'preprocessing' | 'visualization' | 'data'
  url?: string
}

interface Institution {
  name: string
  logo?: string
  type: 'university' | 'research' | 'medical' | 'government'
  country: string
}

export interface TrustStripProps {
  className?: string
  showTools?: boolean
  showInstitutions?: boolean
  showMetrics?: boolean
  animate?: boolean
}

const TRUST_METRICS: TrustMetric[] = [
  {
    id: 'datasets',
    label: 'Datasets',
    value: '2,847',
    icon: Database,
    description: 'Curated neuroimaging datasets',
    trend: { direction: 'up', value: '+127 this month' },
    color: 'text-blue-600',
    animate: true
  },
  {
    id: 'studies',
    label: 'Studies',
    value: '45,239',
    icon: Award,
    description: 'Peer-reviewed research studies',
    trend: { direction: 'up', value: '+2.3K this month' },
    color: 'text-green-600',
    animate: true
  },
  {
    id: 'users',
    label: 'Researchers',
    value: '12,450+',
    icon: Users,
    description: 'Active research users',
    trend: { direction: 'up', value: '+15% growth' },
    color: 'text-purple-600',
    animate: true
  },
  {
    id: 'uptime',
    label: 'Uptime',
    value: '99.9%',
    icon: Shield,
    description: 'System reliability',
    trend: { direction: 'stable', value: 'Last 30 days' },
    color: 'text-emerald-600'
  }
]

const TOOL_LOGOS: ToolLogo[] = [
  {
    name: 'FSL',
    logo: '🧠',
    description: 'FMRIB Software Library',
    category: 'analysis',
    url: 'https://fsl.fmrib.ox.ac.uk'
  },
  {
    name: 'Nilearn',
    logo: '🐍',
    description: 'Machine learning for neuroimaging',
    category: 'analysis',
    url: 'https://nilearn.github.io'
  },
  {
    name: 'fMRIPrep',
    logo: '⚙️',
    description: 'Robust preprocessing pipeline',
    category: 'preprocessing',
    url: 'https://fmriprep.org'
  },
  {
    name: 'BIDS',
    logo: '📁',
    description: 'Brain Imaging Data Structure',
    category: 'data',
    url: 'https://bids.neuroimaging.io'
  },
  {
    name: 'OpenNeuro',
    logo: '🌐',
    description: 'Open neuroimaging datasets',
    category: 'data',
    url: 'https://openneuro.org'
  },
  {
    name: 'Plotly',
    logo: '📊',
    description: 'Interactive visualizations',
    category: 'visualization',
    url: 'https://plotly.com'
  }
]

const INSTITUTIONS: Institution[] = [
  { name: 'Stanford University', type: 'university', country: 'US' },
  { name: 'Harvard Medical School', type: 'medical', country: 'US' },
  { name: 'Oxford University', type: 'university', country: 'UK' },
  { name: 'MIT', type: 'university', country: 'US' },
  { name: 'Max Planck Institute', type: 'research', country: 'DE' },
  { name: 'NIH', type: 'government', country: 'US' },
  { name: 'University of Toronto', type: 'university', country: 'CA' },
  { name: 'ETH Zurich', type: 'university', country: 'CH' }
]

export function TrustStrip({
  className = '',
  showTools = true,
  showInstitutions = true,
  showMetrics = true,
  animate = true
}: TrustStripProps) {
  const [isVisible, setIsVisible] = useState(false)
  const [currentMetricIndex, setCurrentMetricIndex] = useState(0)

  useEffect(() => {
    setIsVisible(true)
    
    if (animate) {
      const interval = setInterval(() => {
        setCurrentMetricIndex(prev => (prev + 1) % TRUST_METRICS.length)
      }, 3000)
      
      return () => clearInterval(interval)
    }
  }, [animate])

  const getCategoryIcon = (category: string) => {
    switch (category) {
      case 'analysis': return '🔬'
      case 'preprocessing': return '⚙️'
      case 'visualization': return '📊'
      case 'data': return '📁'
      default: return '🔧'
    }
  }

  const getInstitutionIcon = (type: string) => {
    switch (type) {
      case 'university': return '🎓'
      case 'medical': return '🏥'
      case 'research': return '🔬'
      case 'government': return '🏛️'
      default: return '🏢'
    }
  }

  const getCountryFlag = (country: string) => {
    const flags: Record<string, string> = {
      'US': '🇺🇸', 'UK': '🇬🇧', 'DE': '🇩🇪', 'CA': '🇨🇦', 'CH': '🇨🇭'
    }
    return flags[country] || '🌍'
  }

  return (
    <section className={`bg-gradient-to-r from-gray-50 via-blue-50 to-purple-50 py-12 border-y ${className}`}>
      <div className="container mx-auto px-4">
        {/* Trust Metrics */}
        {showMetrics && (
          <div className="mb-12">
            <div className="text-center mb-8">
              <h3 className="text-2xl font-bold text-gray-900 mb-2">
                Trusted by the Research Community
              </h3>
              <p className="text-gray-600">
                Real-time metrics from our growing platform
              </p>
            </div>
            
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-6">
              {TRUST_METRICS.map((metric, index) => {
                const Icon = metric.icon
                const isHighlighted = animate && index === currentMetricIndex
                
                return (
                  <Card
                    key={metric.id}
                    className={`text-center transition-all duration-500 hover:shadow-lg ${
                      isHighlighted ? 'ring-2 ring-primary shadow-lg scale-105' : ''
                    } ${
                      isVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'
                    }`}
                    style={{ transitionDelay: `${index * 100}ms` }}
                  >
                    <CardContent className="p-6">
                      <div className={`w-12 h-12 rounded-full bg-gradient-to-br from-white to-gray-100 flex items-center justify-center mx-auto mb-4 ${
                        isHighlighted ? 'animate-pulse' : ''
                      }`}>
                        <Icon className={`h-6 w-6 ${metric.color}`} />
                      </div>
                      
                      <div className={`text-3xl font-bold mb-1 ${
                        metric.animate && isHighlighted ? 'animate-bounce' : ''
                      }`}>
                        {metric.value}
                      </div>
                      
                      <div className="text-sm font-medium text-gray-900 mb-2">
                        {metric.label}
                      </div>
                      
                      <div className="text-xs text-gray-600 mb-3">
                        {metric.description}
                      </div>
                      
                      {metric.trend && (
                        <div className="flex items-center justify-center">
                          <TrendingUp className={`h-3 w-3 mr-1 ${
                            metric.trend.direction === 'up' ? 'text-green-500' : 
                            metric.trend.direction === 'down' ? 'text-red-500 rotate-180' : 
                            'text-gray-500'
                          }`} />
                          <span className="text-xs text-gray-500">
                            {metric.trend.value}
                          </span>
                        </div>
                      )}
                    </CardContent>
                  </Card>
                )
              })}
            </div>
          </div>
        )}

        {/* Supported Tools */}
        {showTools && (
          <div className="mb-12">
            <div className="text-center mb-8">
              <h3 className="text-xl font-semibold text-gray-900 mb-2">
                Built on Industry-Standard Tools
              </h3>
              <p className="text-gray-600">
                Integrating the best neuroimaging software and standards
              </p>
            </div>
            
            <div className="grid grid-cols-3 md:grid-cols-6 gap-4">
              {TOOL_LOGOS.map((tool, index) => (
                <div
                  key={tool.name}
                  className={`group cursor-pointer transition-all duration-300 hover:scale-110 ${
                    isVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'
                  }`}
                  style={{ transitionDelay: `${index * 50}ms` }}
                  onClick={() => tool.url && window.open(tool.url, '_blank')}
                >
                  <div className="bg-white rounded-lg p-4 shadow-sm hover:shadow-md transition-shadow border border-gray-200 hover:border-primary/30">
                    <div className="text-center">
                      <div className="text-3xl mb-2">
                        {tool.logo}
                      </div>
                      <div className="text-sm font-medium text-gray-900 mb-1">
                        {tool.name}
                      </div>
                      <div className="text-xs text-gray-500 mb-2">
                        {tool.description}
                      </div>
                      <Badge 
                        variant="outline" 
                        className="text-xs"
                      >
                        {getCategoryIcon(tool.category)} {tool.category}
                      </Badge>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Institutional Partners */}
        {showInstitutions && (
          <div>
            <div className="text-center mb-8">
              <h3 className="text-xl font-semibold text-gray-900 mb-2">
                Trusted by Leading Institutions
              </h3>
              <p className="text-gray-600">
                Used by researchers at top universities and research centers worldwide
              </p>
            </div>
            
            <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-4">
              {INSTITUTIONS.map((institution, index) => (
                <div
                  key={institution.name}
                  className={`group text-center transition-all duration-300 hover:scale-105 ${
                    isVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'
                  }`}
                  style={{ transitionDelay: `${index * 30}ms` }}
                >
                  <div className="bg-white/80 rounded-lg p-3 hover:bg-white hover:shadow-md transition-all border border-gray-100">
                    <div className="text-2xl mb-1">
                      {getInstitutionIcon(institution.type)}
                    </div>
                    <div className="text-xs font-medium text-gray-800 mb-1 line-clamp-2">
                      {institution.name}
                    </div>
                    <div className="text-xs text-gray-500 flex items-center justify-center">
                      <span className="mr-1">{getCountryFlag(institution.country)}</span>
                      <Badge variant="outline" className="text-xs px-1">
                        {institution.type}
                      </Badge>
                    </div>
                  </div>
                </div>
              ))}
            </div>
            
            <div className="text-center mt-8">
              <Button variant="outline" className="group">
                <Globe className="h-4 w-4 mr-2 group-hover:rotate-12 transition-transform" />
                View All Partners
              </Button>
            </div>
          </div>
        )}

        {/* Performance Indicators */}
        <div className="mt-12 pt-8 border-t border-gray-200">
          <div className="flex flex-wrap justify-center items-center gap-6 text-sm text-gray-600">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 bg-green-400 rounded-full animate-pulse" />
              <span>All systems operational</span>
            </div>
            <div className="flex items-center gap-2">
              <Check className="h-4 w-4 text-green-600" />
              <span>SOC 2 Type II Compliant</span>
            </div>
            <div className="flex items-center gap-2">
              <Shield className="h-4 w-4 text-blue-600" />
              <span>GDPR & HIPAA Ready</span>
            </div>
            <div className="flex items-center gap-2">
              <Zap className="h-4 w-4 text-yellow-500" />
              <span>99.9% API Uptime</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}