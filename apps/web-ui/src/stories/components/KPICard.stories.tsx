import type { Meta, StoryObj } from '@storybook/react';
import { KPICard } from '@/components/analytics/KPICard';
import { KPICardData } from '@/types/analytics';

// Mock type definition for KPICardData if not available
interface MockKPICardData {
  title: string;
  value: number | string;
  subtitle?: string;
  format?: 'number' | 'percentage' | 'currency' | 'time';
  unit?: string;
  trend?: 'up' | 'down' | 'stable';
  trendValue?: number;
  target?: number;
  icon?: React.ReactNode;
  color?: string;
}

// Mock KPICard component for demonstration
const MockKPICard = ({ 
  data, 
  className, 
  showTarget = false 
}: { 
  data: MockKPICardData; 
  className?: string; 
  showTarget?: boolean;
}) => {
  const formatValue = (value: number | string, format?: string, unit?: string) => {
    if (typeof value === 'string') return value;
    
    let formatted = value.toString();
    
    switch (format) {
      case 'percentage':
        formatted = `${value.toFixed(1)}%`;
        break;
      case 'time':
        const hours = Math.floor(value / 60);
        const minutes = Math.round(value % 60);
        formatted = hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`;
        break;
      default:
        if (value >= 1000000) {
          formatted = `${(value / 1000000).toFixed(1)}M`;
        } else if (value >= 1000) {
          formatted = `${(value / 1000).toFixed(1)}K`;
        } else {
          formatted = value.toLocaleString();
        }
    }
    
    return unit ? `${formatted} ${unit}` : formatted;
  };

  const getTrendIcon = (trend?: 'up' | 'down' | 'stable') => {
    switch (trend) {
      case 'up': return '↗️';
      case 'down': return '↘️';
      default: return '➡️';
    }
  };

  const getTrendColor = (trend?: 'up' | 'down' | 'stable') => {
    switch (trend) {
      case 'up': return 'text-green-600';
      case 'down': return 'text-red-600';
      default: return 'text-gray-600';
    }
  };

  return (
    <div className={`bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-6 ${className}`}>
      <div className="flex items-start justify-between mb-4">
        <div className="space-y-1">
          <h3 className="text-sm font-medium text-gray-600 dark:text-gray-400">
            {data.title}
          </h3>
          <div className="text-2xl font-bold text-gray-900 dark:text-white">
            {formatValue(data.value, data.format, data.unit)}
          </div>
          {data.subtitle && (
            <p className="text-xs text-gray-500 dark:text-gray-400">
              {data.subtitle}
            </p>
          )}
        </div>
        
        {data.icon && (
          <div className={`p-2 rounded-lg ${data.color || 'bg-blue-50 text-blue-600 dark:bg-blue-900/20 dark:text-blue-400'}`}>
            {data.icon}
          </div>
        )}
      </div>
      
      {data.trend && data.trendValue !== undefined && (
        <div className="flex items-center gap-2">
          <div className={`flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium ${getTrendColor(data.trend)}`}>
            <span>{getTrendIcon(data.trend)}</span>
            <span>{Math.abs(data.trendValue)}%</span>
          </div>
          <span className="text-xs text-gray-500">vs last period</span>
        </div>
      )}
      
      {showTarget && data.target && typeof data.value === 'number' && (
        <div className="mt-4">
          <div className="flex items-center justify-between text-xs text-gray-600 dark:text-gray-400 mb-1">
            <span>Target: {formatValue(data.target, data.format, data.unit)}</span>
            <span>{Math.round((data.value / data.target) * 100)}%</span>
          </div>
          <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2">
            <div 
              className={`h-2 rounded-full transition-all ${
                data.value >= data.target ? 'bg-green-500' : 'bg-blue-500'
              }`}
              style={{ width: `${Math.min((data.value / data.target) * 100, 100)}%` }}
            />
          </div>
        </div>
      )}
    </div>
  );
};

const meta = {
  title: 'Components/KPI Card',
  component: MockKPICard,
  parameters: {
    layout: 'padded',
    docs: {
      description: {
        component:
          'A key performance indicator card component for displaying metrics, analytics, and scientific measurements with trend indicators and target tracking.',
      },
    },
  },
  tags: ['autodocs'],
  argTypes: {
    data: {
      description: 'KPI data including value, title, and metadata',
    },
    showTarget: {
      control: { type: 'boolean' },
      description: 'Whether to show target progress bar',
    },
    className: {
      control: { type: 'text' },
      description: 'Additional CSS classes',
    },
  },
} satisfies Meta<typeof MockKPICard>;

export default meta;
type Story = StoryObj<typeof meta>;

// Basic metrics
export const StudiesAnalyzed: Story = {
  args: {
    data: {
      title: 'Studies Analyzed',
      value: 1247,
      subtitle: 'Total fMRI studies in database',
      trend: 'up',
      trendValue: 12.5,
      icon: '📊',
      color: 'bg-blue-50 text-blue-600 dark:bg-blue-900/20 dark:text-blue-400'
    },
  },
  parameters: {
    docs: {
      description: {
        story: 'Basic KPI showing the number of studies analyzed with positive trend.',
      },
    },
  },
};

export const ActiveUsers: Story = {
  args: {
    data: {
      title: 'Active Researchers',
      value: 89,
      subtitle: 'Currently using the platform',
      trend: 'stable',
      trendValue: 2.1,
      icon: '👥',
      color: 'bg-green-50 text-green-600 dark:bg-green-900/20 dark:text-green-400'
    },
  },
};

export const AnalysisTime: Story = {
  args: {
    data: {
      title: 'Avg Analysis Time',
      value: 147,
      format: 'time',
      subtitle: 'Per fMRI dataset',
      trend: 'down',
      trendValue: 8.3,
      icon: '⏱️',
      color: 'bg-orange-50 text-orange-600 dark:bg-orange-900/20 dark:text-orange-400'
    },
  },
  parameters: {
    docs: {
      description: {
        story: 'Analysis time metric showing improved performance (downward trend is good).',
      },
    },
  },
};

// Scientific metrics
export const ActivationThreshold: Story = {
  args: {
    data: {
      title: 'Activation Threshold',
      value: 3.45,
      unit: 't-statistic',
      subtitle: 'Statistical significance cutoff',
      target: 3.0,
      icon: '🧠',
      color: 'bg-purple-50 text-purple-600 dark:bg-purple-900/20 dark:text-purple-400'
    },
    showTarget: true,
  },
  parameters: {
    docs: {
      description: {
        story: 'Scientific metric with statistical threshold and target visualization.',
      },
    },
  },
};

export const SignificantVoxels: Story = {
  args: {
    data: {
      title: 'Significant Voxels',
      value: 15678,
      subtitle: 'p < 0.05 (FWE corrected)',
      format: 'number',
      trend: 'up',
      trendValue: 23.4,
      icon: '🎯',
      color: 'bg-red-50 text-red-600 dark:bg-red-900/20 dark:text-red-400'
    },
  },
};

export const ROICoverage: Story = {
  args: {
    data: {
      title: 'ROI Coverage',
      value: 87.3,
      format: 'percentage',
      subtitle: 'Brain regions analyzed',
      target: 90.0,
      trend: 'up',
      trendValue: 5.7,
      icon: '🗺️',
    },
    showTarget: true,
  },
  parameters: {
    docs: {
      description: {
        story: 'Percentage metric with target progress showing brain region coverage.',
      },
    },
  },
};

// Large numbers
export const DataPoints: Story = {
  args: {
    data: {
      title: 'Data Points Processed',
      value: 2847293,
      subtitle: 'Across all analyses this month',
      trend: 'up',
      trendValue: 45.2,
      icon: '📈',
    },
  },
  parameters: {
    docs: {
      description: {
        story: 'Large number formatting showing data points in millions.',
      },
    },
  },
};

// Text-based metric
export const CurrentStatus: Story = {
  args: {
    data: {
      title: 'System Status',
      value: 'Operational',
      subtitle: 'All services running normally',
      icon: '✅',
      color: 'bg-green-50 text-green-600 dark:bg-green-900/20 dark:text-green-400'
    },
  },
  parameters: {
    docs: {
      description: {
        story: 'Text-based status metric for system health monitoring.',
      },
    },
  },
};

// Target not met
export const AccuracyTarget: Story = {
  args: {
    data: {
      title: 'Model Accuracy',
      value: 82.4,
      format: 'percentage',
      target: 90.0,
      subtitle: 'Classification performance',
      trend: 'down',
      trendValue: 3.1,
      icon: '🎯',
    },
    showTarget: true,
  },
  parameters: {
    docs: {
      description: {
        story: 'Metric below target showing accuracy that needs improvement.',
      },
    },
  },
};

// Scientific precision
export const PValue: Story = {
  args: {
    data: {
      title: 'Primary Contrast',
      value: 'p < 0.001',
      subtitle: 'Task vs Rest activation',
      icon: '📊',
      color: 'bg-green-50 text-green-600 dark:bg-green-900/20 dark:text-green-400'
    },
  },
  parameters: {
    docs: {
      description: {
        story: 'Statistical significance display for scientific results.',
      },
    },
  },
};

// Grid showcase
export const MetricsDashboard: Story = {
  render: () => (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
      <MockKPICard 
        data={{
          title: 'Total Studies',
          value: 1247,
          trend: 'up',
          trendValue: 12.5,
          icon: '📚'
        }}
      />
      <MockKPICard 
        data={{
          title: 'Active Users',
          value: 89,
          trend: 'stable',
          trendValue: 2.1,
          icon: '👥'
        }}
      />
      <MockKPICard 
        data={{
          title: 'Avg Processing',
          value: 147,
          format: 'time',
          trend: 'down',
          trendValue: 8.3,
          icon: '⏱️'
        }}
      />
      <MockKPICard 
        data={{
          title: 'Success Rate',
          value: 94.7,
          format: 'percentage',
          trend: 'up',
          trendValue: 1.2,
          icon: '✅'
        }}
      />
    </div>
  ),
  args: {
    data: {
      title: 'Total Studies',
      value: 1247,
    },
  },
  parameters: {
    docs: {
      description: {
        story: 'Complete metrics dashboard showing multiple KPI cards in a grid layout.',
      },
    },
  },
};

// Dark theme
export const DarkTheme: Story = {
  args: {
    data: {
      title: 'Brain Activation',
      value: 4.23,
      unit: 't-statistic',
      subtitle: 'Peak activation in motor cortex',
      trend: 'up',
      trendValue: 15.7,
      target: 3.0,
      icon: '🧠',
    },
    showTarget: true,
  },
  parameters: {
    backgrounds: { default: 'dark' },
    docs: {
      description: {
        story: 'KPI card in dark theme showing proper contrast and readability.',
      },
    },
  },
  decorators: [
    (Story) => (
      <div className="dark">
        <div className="bg-gray-900 p-4">
          <Story />
        </div>
      </div>
    ),
  ],
};
