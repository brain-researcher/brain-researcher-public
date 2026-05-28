import type { Meta, StoryObj } from '@storybook/react';
import { fn } from '@storybook/test';
import React from 'react';
import { BarChart3, Brain, Users, Activity, Download, Clock, Target, TrendingUp } from 'lucide-react';

// Mock dashboard components for comprehensive documentation
const MockAnalyticsDashboard = ({ 
  widgets = [], 
  layout = 'grid',
  onExportDashboard,
  onCustomizeLayout,
  className = ''
}: {
  widgets?: Array<{ id: string; title: string; type: string; data: any }>;
  layout?: 'grid' | 'masonry' | 'flexible';
  onExportDashboard?: () => void;
  onCustomizeLayout?: () => void;
  className?: string;
}) => {
  const renderWidget = (widget: any) => {
    switch (widget.type) {
      case 'kpi':
        return (
          <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">{widget.title}</h3>
              <div className="p-2 bg-blue-50 dark:bg-blue-900/20 rounded-lg">
                <BarChart3 className="h-5 w-5 text-blue-600 dark:text-blue-400" />
              </div>
            </div>
            <div className="text-3xl font-bold text-gray-900 dark:text-white mb-2">
              {widget.data.value}
            </div>
            <div className="text-sm text-gray-600 dark:text-gray-400">
              {widget.data.subtitle}
            </div>
            {widget.data.trend && (
              <div className="mt-4 flex items-center gap-2">
                <TrendingUp className="h-4 w-4 text-green-500" />
                <span className="text-sm text-green-600">+{widget.data.trend}% vs last month</span>
              </div>
            )}
          </div>
        );
        
      case 'chart':
        return (
          <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-6">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">{widget.title}</h3>
            <div className="h-48 bg-gray-50 dark:bg-gray-900 rounded-lg flex items-center justify-center">
              <div className="text-center text-gray-500 dark:text-gray-400">
                <BarChart3 className="h-8 w-8 mx-auto mb-2" />
                <div className="text-sm">Interactive Chart Placeholder</div>
              </div>
            </div>
          </div>
        );
        
      case 'activity':
        return (
          <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-6">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">{widget.title}</h3>
            <div className="space-y-3">
              {widget.data.activities.map((activity: any, i: number) => (
                <div key={i} className="flex items-center gap-3">
                  <div className="w-2 h-2 bg-blue-500 rounded-full"></div>
                  <div className="flex-1">
                    <div className="text-sm font-medium text-gray-900 dark:text-white">
                      {activity.title}
                    </div>
                    <div className="text-xs text-gray-500 dark:text-gray-400">
                      {activity.timestamp}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        );
        
      default:
        return (
          <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-6">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">{widget.title}</h3>
            <div className="mt-4 text-gray-600 dark:text-gray-400">
              Widget type: {widget.type}
            </div>
          </div>
        );
    }
  };
  
  return (
    <div className={`min-h-screen bg-gray-50 dark:bg-gray-900 ${className}`}>
      {/* Dashboard Header */}
      <div className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 p-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
              Research Analytics Dashboard
            </h1>
            <p className="text-gray-600 dark:text-gray-400 mt-1">
              Real-time insights into your neuroimaging research workflow
            </p>
          </div>
          
          <div className="flex items-center gap-3">
            <button 
              onClick={onCustomizeLayout}
              className="px-4 py-2 text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600"
            >
              Customize Layout
            </button>
            <button 
              onClick={onExportDashboard}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 flex items-center gap-2"
            >
              <Download className="h-4 w-4" />
              Export
            </button>
          </div>
        </div>
      </div>
      
      {/* Dashboard Content */}
      <div className="p-6">
        <div className={`grid gap-6 ${
          layout === 'grid' ? 'grid-cols-1 md:grid-cols-2 lg:grid-cols-3' :
          layout === 'masonry' ? 'columns-1 md:columns-2 lg:columns-3' :
          'flex flex-wrap'
        }`}>
          {widgets.map((widget) => (
            <div key={widget.id} className="break-inside-avoid">
              {renderWidget(widget)}
            </div>
          ))}
        </div>
        
        {widgets.length === 0 && (
          <div className="text-center py-12">
            <Brain className="h-12 w-12 text-gray-400 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">
              No widgets configured
            </h3>
            <p className="text-gray-600 dark:text-gray-400 mb-4">
              Add widgets to start monitoring your research metrics
            </p>
            <button 
              onClick={onCustomizeLayout}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
            >
              Add Widgets
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

const mockWidgets = [
  {
    id: '1',
    title: 'Studies Processed',
    type: 'kpi',
    data: {
      value: '2,847',
      subtitle: 'Total fMRI analyses this month',
      trend: 23
    }
  },
  {
    id: '2',
    title: 'Active Researchers',
    type: 'kpi',
    data: {
      value: '127',
      subtitle: 'Currently using the platform',
      trend: 8
    }
  },
  {
    id: '3',
    title: 'Processing Queue',
    type: 'chart',
    data: {}
  },
  {
    id: '4',
    title: 'Recent Activity',
    type: 'activity',
    data: {
      activities: [
        { title: 'fMRI GLM Analysis completed', timestamp: '2 minutes ago' },
        { title: 'Dataset uploaded: Visual Working Memory', timestamp: '15 minutes ago' },
        { title: 'ROI Analysis exported', timestamp: '1 hour ago' },
        { title: 'New collaboration started', timestamp: '2 hours ago' },
      ]
    }
  },
  {
    id: '5',
    title: 'System Performance',
    type: 'kpi',
    data: {
      value: '99.2%',
      subtitle: 'Uptime this month',
      trend: 0.1
    }
  },
  {
    id: '6',
    title: 'Analysis Accuracy',
    type: 'kpi',
    data: {
      value: '94.7%',
      subtitle: 'Quality control pass rate',
      trend: 2.3
    }
  }
];

const meta = {
  title: 'Components/Dashboard',
  component: MockAnalyticsDashboard,
  parameters: {
    layout: 'fullscreen',
    docs: {
      description: {
        component:
          'A comprehensive analytics dashboard for monitoring research workflows, system performance, and user activity. Supports customizable layouts, real-time updates, and data export functionality.',
      },
    },
  },
  tags: ['autodocs'],
  argTypes: {
    widgets: {
      description: 'Array of dashboard widgets to display',
    },
    layout: {
      control: { type: 'select' },
      options: ['grid', 'masonry', 'flexible'],
      description: 'Dashboard layout style',
    },
    onExportDashboard: {
      action: 'exportDashboard',
      description: 'Callback when export button is clicked',
    },
    onCustomizeLayout: {
      action: 'customizeLayout',
      description: 'Callback when customize layout is clicked',
    },
  },
  args: {
    onExportDashboard: fn(),
    onCustomizeLayout: fn(),
  },
} satisfies Meta<typeof MockAnalyticsDashboard>;

export default meta;
type Story = StoryObj<typeof meta>;

// Full dashboard
export const DefaultDashboard: Story = {
  args: {
    widgets: mockWidgets,
    layout: 'grid',
  },
  parameters: {
    docs: {
      description: {
        story: 'Complete research analytics dashboard with KPIs, charts, and activity feeds.',
      },
    },
  },
};

// Empty state
export const EmptyDashboard: Story = {
  args: {
    widgets: [],
  },
  parameters: {
    docs: {
      description: {
        story: 'Empty dashboard state encouraging users to add widgets.',
      },
    },
  },
};

// Minimal dashboard
export const MinimalDashboard: Story = {
  args: {
    widgets: mockWidgets.slice(0, 3),
    layout: 'grid',
  },
  parameters: {
    docs: {
      description: {
        story: 'Minimal dashboard setup with essential monitoring widgets.',
      },
    },
  },
};

// Masonry layout
export const MasonryLayout: Story = {
  args: {
    widgets: [
      ...mockWidgets,
      {
        id: '7',
        title: 'Brain Region Analysis',
        type: 'chart',
        data: {}
      }
    ],
    layout: 'masonry',
  },
  parameters: {
    docs: {
      description: {
        story: 'Dashboard using masonry layout for dynamic widget sizing.',
      },
    },
  },
};

// Research-specific dashboard
export const ResearchDashboard: Story = {
  args: {
    widgets: [
      {
        id: '1',
        title: 'Active Studies',
        type: 'kpi',
        data: {
          value: '12',
          subtitle: 'Ongoing research projects',
          trend: 20
        }
      },
      {
        id: '2',
        title: 'Significant Results',
        type: 'kpi',
        data: {
          value: '847',
          subtitle: 'Brain regions with p < 0.05',
          trend: 15
        }
      },
      {
        id: '3',
        title: 'Collaboration Network',
        type: 'chart',
        data: {}
      },
      {
        id: '4',
        title: 'Publication Pipeline',
        type: 'activity',
        data: {
          activities: [
            { title: 'Manuscript draft completed', timestamp: '1 day ago' },
            { title: 'Statistical analysis validated', timestamp: '3 days ago' },
            { title: 'Peer review submitted', timestamp: '1 week ago' },
            { title: 'Supplementary materials prepared', timestamp: '2 weeks ago' },
          ]
        }
      }
    ],
  },
  parameters: {
    docs: {
      description: {
        story: 'Dashboard focused on research progress and scientific collaboration.',
      },
    },
  },
};

// Performance monitoring
export const PerformanceDashboard: Story = {
  args: {
    widgets: [
      {
        id: '1',
        title: 'Processing Speed',
        type: 'kpi',
        data: {
          value: '2.3s',
          subtitle: 'Average analysis time per scan',
          trend: -12
        }
      },
      {
        id: '2',
        title: 'Memory Usage',
        type: 'kpi',
        data: {
          value: '78%',
          subtitle: 'Peak system memory utilization',
          trend: 5
        }
      },
      {
        id: '3',
        title: 'Queue Status',
        type: 'activity',
        data: {
          activities: [
            { title: 'GLM Analysis #1247 - Running', timestamp: 'Now' },
            { title: 'Preprocessing #1248 - Queued', timestamp: 'Now' },
            { title: 'ROI Analysis #1246 - Completed', timestamp: '5 min ago' },
            { title: 'Quality Check #1245 - Completed', timestamp: '12 min ago' },
          ]
        }
      }
    ],
  },
  parameters: {
    docs: {
      description: {
        story: 'System performance monitoring dashboard for administrators.',
      },
    },
  },
};

// Mobile responsive
export const MobileDashboard: Story = {
  args: {
    widgets: mockWidgets.slice(0, 4),
    layout: 'grid',
  },
  parameters: {
    viewport: {
      defaultViewport: 'mobile',
    },
    docs: {
      description: {
        story: 'Dashboard optimized for mobile devices with touch-friendly interactions.',
      },
    },
  },
};

// Dark theme
export const DarkThemeDashboard: Story = {
  args: {
    widgets: mockWidgets,
    layout: 'grid',
  },
  parameters: {
    backgrounds: { default: 'dark' },
    docs: {
      description: {
        story: 'Dashboard in dark theme showing proper contrast and readability.',
      },
    },
  },
  decorators: [
    (Story) => (
      <div className="dark">
        <Story />
      </div>
    ),
  ],
};

// Customization workflow
export const CustomizationWorkflow: Story = {
  render: () => (
    <div className="space-y-6">
      <div className="bg-blue-50 dark:bg-blue-900/20 p-4 rounded-lg">
        <h3 className="font-semibold text-blue-900 dark:text-blue-100 mb-2">
          Dashboard Customization Features
        </h3>
        <ul className="text-sm text-blue-700 dark:text-blue-300 space-y-1">
          <li>• Drag and drop widget repositioning</li>
          <li>• Resize widgets for different data densities</li>
          <li>• Add/remove widgets based on research focus</li>
          <li>• Save custom layouts for different project contexts</li>
          <li>• Export dashboards as images or reports</li>
        </ul>
      </div>
      
      <MockAnalyticsDashboard widgets={mockWidgets.slice(0, 4)} />
      
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
        <div className="bg-gray-50 dark:bg-gray-800 p-4 rounded-lg">
          <h4 className="font-medium mb-2">Research Focused</h4>
          <p className="text-gray-600 dark:text-gray-400">
            Widgets for tracking study progress, publications, and scientific metrics
          </p>
        </div>
        
        <div className="bg-gray-50 dark:bg-gray-800 p-4 rounded-lg">
          <h4 className="font-medium mb-2">System Monitoring</h4>
          <p className="text-gray-600 dark:text-gray-400">
            Performance metrics, resource usage, and system health indicators
          </p>
        </div>
        
        <div className="bg-gray-50 dark:bg-gray-800 p-4 rounded-lg">
          <h4 className="font-medium mb-2">Collaborative</h4>
          <p className="text-gray-600 dark:text-gray-400">
            Team activity, shared resources, and collaboration metrics
          </p>
        </div>
      </div>
    </div>
  ),
  parameters: {
    docs: {
      description: {
        story: 'Comprehensive workflow showing dashboard customization capabilities and use cases.',
      },
    },
  },
};