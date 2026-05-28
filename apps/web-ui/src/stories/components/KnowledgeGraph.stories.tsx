import type { Meta, StoryObj } from '@storybook/react';
import { fn } from '@storybook/test';
import React from 'react';

// Mock the KnowledgeGraph component since it uses dynamic imports
const MockKnowledgeGraphExplorer = ({ 
  initialQuery, 
  onNodeSelect, 
  onExportGraph,
  className 
}: {
  initialQuery?: string;
  onNodeSelect?: (nodeId: string, nodeData: any) => void;
  onExportGraph?: () => void;
  className?: string;
}) => {
  return (
    <div className={`bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 ${className}`}>
      <div className="p-4 border-b border-gray-200 dark:border-gray-700">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            Knowledge Graph Explorer
          </h2>
          <div className="flex items-center gap-2">
            <button 
              onClick={onExportGraph}
              className="p-2 text-gray-500 hover:bg-gray-100 rounded-lg"
            >
              Export
            </button>
          </div>
        </div>
        
        <div className="relative">
          <input
            type="text"
            placeholder="Search for papers, authors, brain regions..."
            defaultValue={initialQuery}
            className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          />
        </div>
      </div>
      
      <div className="relative h-96 bg-gray-50 dark:bg-gray-900">
        {/* Mock graph visualization */}
        <svg width="100%" height="100%" className="absolute inset-0">
          {/* Mock nodes */}
          <circle cx="200" cy="150" r="20" fill="#3b82f6" className="cursor-pointer" />
          <text x="200" y="155" textAnchor="middle" className="text-xs fill-white pointer-events-none">
            fMRI
          </text>
          
          <circle cx="350" cy="100" r="15" fill="#10b981" className="cursor-pointer" />
          <text x="350" y="105" textAnchor="middle" className="text-xs fill-white pointer-events-none">
            V1
          </text>
          
          <circle cx="350" cy="200" r="18" fill="#f59e0b" className="cursor-pointer" />
          <text x="350" y="205" textAnchor="middle" className="text-xs fill-white pointer-events-none">
            Author
          </text>
          
          <circle cx="500" cy="150" r="12" fill="#ef4444" className="cursor-pointer" />
          <text x="500" y="155" textAnchor="middle" className="text-xs fill-white pointer-events-none">
            Study
          </text>
          
          {/* Mock edges */}
          <line x1="220" y1="150" x2="330" y2="100" stroke="#6b7280" strokeWidth="2" />
          <line x1="220" y1="150" x2="330" y2="200" stroke="#6b7280" strokeWidth="2" />
          <line x1="368" y1="110" x2="485" y2="145" stroke="#6b7280" strokeWidth="2" />
          <line x1="368" y1="190" x2="485" y2="155" stroke="#6b7280" strokeWidth="2" />
        </svg>
        
        {/* Mock stats overlay */}
        <div className="absolute bottom-4 left-4 bg-white dark:bg-gray-800 rounded-lg p-3 shadow-sm border">
          <div className="text-sm text-gray-600 dark:text-gray-400">
            <div>Nodes: 847</div>
            <div>Edges: 1,234</div>
            <div>Studies: 23</div>
          </div>
        </div>
        
        {/* Mock controls overlay */}
        <div className="absolute top-4 right-4 flex flex-col gap-2">
          <button className="p-2 bg-white dark:bg-gray-800 rounded-lg shadow-sm border">
            +
          </button>
          <button className="p-2 bg-white dark:bg-gray-800 rounded-lg shadow-sm border">
            −
          </button>
          <button className="p-2 bg-white dark:bg-gray-800 rounded-lg shadow-sm border">
            ⟲
          </button>
        </div>
      </div>
      
      {/* Mock node details panel */}
      <div className="p-4 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900">
        <div className="text-sm">
          <h3 className="font-medium text-gray-900 dark:text-white mb-2">
            Selected: Primary Visual Cortex (V1)
          </h3>
          <div className="space-y-1 text-gray-600 dark:text-gray-400">
            <div><strong>Type:</strong> Brain Region</div>
            <div><strong>Studies:</strong> 156 papers</div>
            <div><strong>Citations:</strong> 4,523</div>
            <div><strong>Related:</strong> V2, V3, MT+</div>
          </div>
        </div>
      </div>
    </div>
  );
};

const meta = {
  title: 'Components/Knowledge Graph',
  component: MockKnowledgeGraphExplorer,
  parameters: {
    layout: 'padded',
    docs: {
      description: {
        component:
          'An interactive knowledge graph explorer for visualizing relationships between brain regions, studies, authors, and research concepts. Features dynamic node layouts, filtering, and detailed information panels.',
      },
    },
  },
  tags: ['autodocs'],
  argTypes: {
    initialQuery: {
      control: { type: 'text' },
      description: 'Initial search query to populate the graph',
    },
    onNodeSelect: {
      action: 'nodeSelect',
      description: 'Callback when a node is selected',
    },
    onExportGraph: {
      action: 'exportGraph',
      description: 'Callback when export button is clicked',
    },
    className: {
      control: { type: 'text' },
      description: 'Additional CSS classes',
    },
  },
  args: {
    onNodeSelect: fn(),
    onExportGraph: fn(),
  },
} satisfies Meta<typeof MockKnowledgeGraphExplorer>;

export default meta;
type Story = StoryObj<typeof meta>;

// Default state
export const Default: Story = {
  args: {
    initialQuery: '',
  },
  parameters: {
    docs: {
      description: {
        story: 'Default knowledge graph explorer showing brain region relationships.',
      },
    },
  },
};

// With initial search
export const WithSearch: Story = {
  args: {
    initialQuery: 'visual cortex',
  },
  parameters: {
    docs: {
      description: {
        story: 'Knowledge graph populated with search results for visual cortex.',
      },
    },
  },
};

// fMRI-focused view
export const FMRIFocused: Story = {
  args: {
    initialQuery: 'fMRI activation',
  },
  parameters: {
    docs: {
      description: {
        story: 'Knowledge graph focused on fMRI activation studies and related brain regions.',
      },
    },
  },
};

// Author network view
export const AuthorNetwork: Story = {
  args: {
    initialQuery: 'neuroimaging authors',
  },
  parameters: {
    docs: {
      description: {
        story: 'Knowledge graph showing author collaboration networks in neuroimaging research.',
      },
    },
  },
};

// Large network simulation
const LargeNetworkGraph = (props: any) => {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
      <div className="p-4 border-b border-gray-200 dark:border-gray-700">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            Large Network Visualization
          </h2>
        </div>
      </div>
      
      <div className="relative h-96 bg-gray-50 dark:bg-gray-900">
        <svg width="100%" height="100%" className="absolute inset-0">
          {/* Generate many mock nodes and edges for large network */}
          {Array.from({ length: 50 }, (_, i) => (
            <g key={i}>
              <circle 
                cx={100 + (i % 10) * 60} 
                cy={50 + Math.floor(i / 10) * 60} 
                r="8" 
                fill={`hsl(${i * 7}, 70%, 50%)`}
                className="cursor-pointer opacity-70"
              />
            </g>
          ))}
          
          {/* Mock connection lines */}
          {Array.from({ length: 30 }, (_, i) => (
            <line 
              key={i}
              x1={100 + (i % 10) * 60} 
              y1={50 + Math.floor(i / 10) * 60}
              x2={100 + ((i + 1) % 10) * 60} 
              y2={50 + Math.floor((i + 1) / 10) * 60}
              stroke="#6b7280" 
              strokeWidth="1"
              opacity="0.5"
            />
          ))}
        </svg>
        
        <div className="absolute bottom-4 left-4 bg-white dark:bg-gray-800 rounded-lg p-3 shadow-sm border">
          <div className="text-sm text-gray-600 dark:text-gray-400">
            <div>Nodes: 2,847</div>
            <div>Edges: 5,234</div>
            <div>Clusters: 12</div>
          </div>
        </div>
      </div>
    </div>
  );
};

export const LargeNetwork: Story = {
  render: () => <LargeNetworkGraph />,
  parameters: {
    docs: {
      description: {
        story: 'Large network visualization showing performance with many nodes and edges.',
      },
    },
  },
};

// Mobile responsive view
export const Mobile: Story = {
  args: {
    initialQuery: 'brain regions',
    className: 'h-screen',
  },
  parameters: {
    viewport: {
      defaultViewport: 'mobile',
    },
    docs: {
      description: {
        story: 'Knowledge graph optimized for mobile viewing with touch interactions.',
      },
    },
  },
};

// Dark theme
export const DarkTheme: Story = {
  args: {
    initialQuery: 'prefrontal cortex',
  },
  parameters: {
    backgrounds: { default: 'dark' },
    docs: {
      description: {
        story: 'Knowledge graph in dark theme showing contrast and readability.',
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

// Scientific workflow example
export const ScientificWorkflow: Story = {
  render: () => (
    <div className="space-y-6">
      <div className="text-center">
        <h3 className="text-lg font-semibold mb-2">Research Discovery Workflow</h3>
        <p className="text-gray-600 dark:text-gray-400">
          Explore relationships between brain regions, studies, and findings
        </p>
      </div>
      
      <MockKnowledgeGraphExplorer 
        initialQuery="working memory fMRI"
        className="h-80"
      />
      
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
        <div className="bg-blue-50 dark:bg-blue-900/20 p-4 rounded-lg">
          <h4 className="font-medium text-blue-900 dark:text-blue-100 mb-2">
            1. Search & Discover
          </h4>
          <p className="text-blue-700 dark:text-blue-300">
            Start with a research question and explore related concepts
          </p>
        </div>
        
        <div className="bg-green-50 dark:bg-green-900/20 p-4 rounded-lg">
          <h4 className="font-medium text-green-900 dark:text-green-100 mb-2">
            2. Analyze Connections
          </h4>
          <p className="text-green-700 dark:text-green-300">
            Identify patterns and relationships between studies and regions
          </p>
        </div>
        
        <div className="bg-orange-50 dark:bg-orange-900/20 p-4 rounded-lg">
          <h4 className="font-medium text-orange-900 dark:text-orange-100 mb-2">
            3. Generate Insights
          </h4>
          <p className="text-orange-700 dark:text-orange-300">
            Export findings and create new research hypotheses
          </p>
        </div>
      </div>
    </div>
  ),
  parameters: {
    layout: 'padded',
    docs: {
      description: {
        story: 'Complete scientific workflow showing how researchers use the knowledge graph.',
      },
    },
  },
};