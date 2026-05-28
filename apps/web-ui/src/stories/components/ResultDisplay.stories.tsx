import type { Meta, StoryObj } from '@storybook/react';
import { fn } from '@storybook/test';
import { ResultCard, ResultData } from '@/components/results/ResultCard';

// Mock data for different result types
const mockImageResult: ResultData = {
  id: '1',
  name: 'Statistical Map - T1 vs T2',
  type: 'image',
  content: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg==',
  metadata: {
    created_at: '2024-01-15T10:30:00Z',
    author: 'Dr. Sarah Chen',
    description: 'Statistical parametric map showing activation differences between task conditions',
    size: 2048576,
    format: 'NIfTI',
    dimensions: '182x218x182',
    tags: ['fMRI', 'activation', 'statistics']
  }
};

const mockTableResult: ResultData = {
  id: '2',
  name: 'ROI Analysis Results',
  type: 'table',
  content: [
    { roi: 'V1', hemisphere: 'Left', activation: 3.45, p_value: 0.001, cluster_size: 234 },
    { roi: 'V1', hemisphere: 'Right', activation: 3.12, p_value: 0.003, cluster_size: 198 },
    { roi: 'MT+', hemisphere: 'Left', activation: 4.67, p_value: 0.0001, cluster_size: 345 },
    { roi: 'MT+', hemisphere: 'Right', activation: 4.23, p_value: 0.0002, cluster_size: 298 },
    { roi: 'FFA', hemisphere: 'Left', activation: 2.89, p_value: 0.008, cluster_size: 156 },
  ],
  metadata: {
    created_at: '2024-01-15T11:15:00Z',
    author: 'Analysis Pipeline',
    description: 'Region of Interest analysis showing activation strength and statistical significance',
    size: 1024,
    format: 'CSV',
    tags: ['ROI', 'statistics', 'activation']
  }
};

const mockJsonResult: ResultData = {
  id: '3',
  name: 'Analysis Configuration',
  type: 'json',
  content: {
    analysis_type: 'GLM',
    design_matrix: {
      conditions: ['task_a', 'task_b', 'rest'],
      duration: 6.0,
      tr: 2.0,
      high_pass_filter: 0.01
    },
    contrasts: [
      { name: 'Task A vs Rest', weights: [1, 0, -1] },
      { name: 'Task B vs Rest', weights: [0, 1, -1] },
      { name: 'Task A vs Task B', weights: [1, -1, 0] }
    ],
    preprocessing: {
      motion_correction: true,
      slice_timing: true,
      spatial_smoothing: 6.0,
      temporal_filtering: true
    }
  },
  metadata: {
    created_at: '2024-01-15T09:45:00Z',
    author: 'Dr. Michael Torres',
    description: 'General Linear Model configuration for first-level analysis',
    version: '1.2.0',
    tags: ['config', 'GLM', 'preprocessing']
  }
};

const mockReportResult: ResultData = {
  id: '4',
  name: 'Analysis Summary Report',
  type: 'report',
  content: `# fMRI Analysis Report

## Study Overview
- **Participants**: 24 healthy adults
- **Task**: Visual motion detection
- **Acquisition**: 3T Siemens Prisma
- **TR**: 2.0s, **TE**: 30ms

## Results Summary
Statistical analysis revealed significant activation in:
- Primary visual cortex (p < 0.001, corrected)
- Middle temporal area (p < 0.001, corrected)
- Superior parietal lobule (p < 0.005, corrected)

## Conclusions
The results confirm expected activation patterns for visual motion processing.`,
  metadata: {
    created_at: '2024-01-15T16:20:00Z',
    author: 'Analysis Pipeline',
    description: 'Comprehensive analysis report with findings and interpretations',
    format: 'Markdown',
    tags: ['report', 'summary', 'results']
  }
};

const meta = {
  title: 'Components/Result Display',
  component: ResultCard,
  parameters: {
    layout: 'padded',
    docs: {
      description: {
        component:
          'A comprehensive result display component for showing analysis outputs in various formats including images, tables, JSON data, and reports. Supports expansion, downloading, and sharing functionality.',
      },
    },
  },
  tags: ['autodocs'],
  argTypes: {
    result: {
      description: 'Result data object containing content and metadata',
    },
    expanded: {
      control: { type: 'boolean' },
      description: 'Whether the result content is expanded and visible',
    },
    onDownload: {
      action: 'download',
      description: 'Callback when download button is clicked',
    },
    onShare: {
      action: 'share',
      description: 'Callback when share button is clicked',
    },
    onToggleExpand: {
      action: 'toggleExpand',
      description: 'Callback when expand/collapse button is clicked',
    },
  },
  args: {
    onDownload: fn(),
    onShare: fn(),
    onToggleExpand: fn(),
  },
} satisfies Meta<typeof ResultCard>;

export default meta;
type Story = StoryObj<typeof meta>;

// Basic collapsed state
export const ImageResultCollapsed: Story = {
  args: {
    result: mockImageResult,
    expanded: false,
  },
  parameters: {
    docs: {
      description: {
        story: 'Brain imaging result in collapsed state showing metadata and type indicator.',
      },
    },
  },
};

// Basic expanded state
export const ImageResultExpanded: Story = {
  args: {
    result: mockImageResult,
    expanded: true,
  },
  parameters: {
    docs: {
      description: {
        story: 'Brain imaging result expanded to show the statistical map image.',
      },
    },
  },
};

// Table result
export const TableResult: Story = {
  args: {
    result: mockTableResult,
    expanded: true,
  },
  parameters: {
    docs: {
      description: {
        story: 'ROI analysis results displayed as an interactive sortable table.',
      },
    },
  },
};

// JSON result
export const JsonResult: Story = {
  args: {
    result: mockJsonResult,
    expanded: true,
  },
  parameters: {
    docs: {
      description: {
        story: 'Analysis configuration displayed as formatted JSON with syntax highlighting.',
      },
    },
  },
};

// Report result
export const ReportResult: Story = {
  args: {
    result: mockReportResult,
    expanded: true,
  },
  parameters: {
    docs: {
      description: {
        story: 'Analysis report displayed as formatted text content.',
      },
    },
  },
};

// Minimal result without metadata
const minimalResult: ResultData = {
  id: '5',
  name: 'Simple Result',
  type: 'file',
  content: 'Basic text content without additional metadata'
};

export const MinimalResult: Story = {
  args: {
    result: minimalResult,
    expanded: true,
  },
  parameters: {
    docs: {
      description: {
        story: 'Minimal result without metadata, showing fallback display.',
      },
    },
  },
};

// Large dataset example
const largeTableResult: ResultData = {
  id: '6',
  name: 'Voxel-wise Analysis Results',
  type: 'table',
  content: Array.from({ length: 100 }, (_, i) => ({
    voxel_id: `voxel_${i + 1}`,
    x: Math.floor(Math.random() * 182),
    y: Math.floor(Math.random() * 218),
    z: Math.floor(Math.random() * 182),
    t_stat: (Math.random() * 8 - 4).toFixed(3),
    p_value: Math.random() < 0.1 ? (Math.random() * 0.05).toFixed(6) : (Math.random() * 0.5 + 0.05).toFixed(6),
    cluster_id: Math.floor(Math.random() * 20) + 1
  })),
  metadata: {
    created_at: '2024-01-15T14:30:00Z',
    author: 'Voxel Analysis Pipeline',
    description: 'Comprehensive voxel-wise statistical analysis across the entire brain volume',
    size: 51200,
    format: 'CSV',
    tags: ['voxel-wise', 'whole-brain', 'statistics']
  }
};

export const LargeDataset: Story = {
  args: {
    result: largeTableResult,
    expanded: true,
  },
  parameters: {
    docs: {
      description: {
        story: 'Large dataset example showing table pagination and performance handling.',
      },
    },
  },
};

// Error state simulation
const errorResult: ResultData = {
  id: '7',
  name: 'Corrupted Analysis',
  type: 'image',
  content: null,
  metadata: {
    created_at: '2024-01-15T12:00:00Z',
    author: 'Failed Pipeline',
    description: 'This result failed to generate properly',
    tags: ['error', 'failed']
  }
};

export const ErrorState: Story = {
  args: {
    result: errorResult,
    expanded: true,
  },
  parameters: {
    docs: {
      description: {
        story: 'Error state when result content cannot be displayed properly.',
      },
    },
  },
};

// Multiple results showcase
export const AllResultTypes: Story = {
  render: () => (
    <div className="space-y-4">
      <ResultCard result={mockImageResult} expanded={false} />
      <ResultCard result={mockTableResult} expanded={false} />
      <ResultCard result={mockJsonResult} expanded={false} />
      <ResultCard result={mockReportResult} expanded={false} />
    </div>
  ),
  args: {
    result: mockImageResult,
  },
  parameters: {
    layout: 'padded',
    docs: {
      description: {
        story: 'Showcase of all result types in their collapsed states for comparison.',
      },
    },
  },
};

// Responsive behavior
export const ResponsiveExample: Story = {
  args: {
    result: mockTableResult,
    expanded: true,
  },
  parameters: {
    viewport: {
      defaultViewport: 'mobile',
    },
    docs: {
      description: {
        story: 'Result display on mobile devices showing responsive layout adaptations.',
      },
    },
  },
};

// Dark theme example
export const DarkTheme: Story = {
  args: {
    result: mockImageResult,
    expanded: true,
  },
  parameters: {
    backgrounds: { default: 'dark' },
    docs: {
      description: {
        story: 'Result display in dark theme showing proper contrast and readability.',
      },
    },
  },
  decorators: [
    (Story) => (
      <div className="dark">
        <div className="bg-gray-900 p-4 min-h-screen">
          <Story />
        </div>
      </div>
    ),
  ],
};
