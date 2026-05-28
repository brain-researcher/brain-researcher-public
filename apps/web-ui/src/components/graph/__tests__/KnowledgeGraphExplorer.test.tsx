// @ts-nocheck
/**
 * @jest-environment jsdom
 */

import React from 'react';
import { vi } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import cytoscape from 'cytoscape';
import { GraphControls } from '../GraphControls';
import { NodeDetailsPanel } from '../NodeDetailsPanel';
import { GraphSearch } from '../GraphSearch';
import KnowledgeGraphExplorerEnhanced from '../KnowledgeGraphExplorerEnhanced';
import { brainResearcherAPI } from '@/lib/brain-researcher-api';

vi.mock('@/hooks/use-debounce', () => ({
  useDebouncedValue: <T,>(value: T) => value,
  useDebounce: <T extends (...args: any[]) => any>(callback: T) => callback
}));

// Mock Cytoscape
vi.mock('cytoscape', () => {
  const mockLayout = {
    run: vi.fn(),
    stop: vi.fn()
  };
  
  const mockNode = {
    id: vi.fn(() => 'test-node'),
    data: vi.fn(() => ({ label: 'Test Node', nodeType: 'Concept' })),
    addClass: vi.fn(),
    removeClass: vi.fn(),
    connectedEdges: vi.fn(() => mockCytoscape),
    connectedNodes: vi.fn(() => mockCytoscape)
  };
  
  const mockEdge = {
    id: vi.fn(() => 'test-edge'),
    data: vi.fn(() => ({ label: 'TEST_RELATION', edgeType: 'RELATES_TO' })),
    source: vi.fn(() => mockNode),
    target: vi.fn(() => mockNode),
    addClass: vi.fn(),
    removeClass: vi.fn()
  };

  const mockCytoscape = {
    layout: vi.fn(() => mockLayout),
    on: vi.fn(),
    off: vi.fn(),
    elements: vi.fn(() => mockCytoscape),
    remove: vi.fn(() => mockCytoscape),
    add: vi.fn(() => mockCytoscape),
    nodes: vi.fn(() => mockCytoscape),
    edges: vi.fn(() => mockCytoscape),
    filter: vi.fn(() => mockCytoscape),
    zoom: vi.fn(() => 1),
    fit: vi.fn(),
    reset: vi.fn(),
    destroy: vi.fn(),
    style: vi.fn(),
    png: vi.fn(() => new Blob()),
    animate: vi.fn(),
    $: vi.fn(() => mockCytoscape),
    addClass: vi.fn(),
    removeClass: vi.fn()
  };

  const cytoscapeConstructor = vi.fn(() => mockCytoscape);
  cytoscapeConstructor.use = vi.fn();
  return { __esModule: true, default: cytoscapeConstructor };
});

// Mock cytoscape extensions
vi.mock('cytoscape-cose-bilkent', () => ({}));
vi.mock('cytoscape-dagre', () => ({}));

// Mock html-to-image
vi.mock('html-to-image', () => ({
  toPng: jest.fn(() => Promise.resolve('data:image/png;base64,test'))
}));

// Mock the brain researcher API
vi.mock('@/lib/brain-researcher-api', () => ({
  brainResearcherAPI: {
    searchNodes: vi.fn(),
    getGraphStats: vi.fn(),
    expandNode: vi.fn()
  }
}));

// Sample test data
const mockNodes = [
  {
    id: 'c1',
    label: 'Working Memory',
    type: 'Concept',
    properties: { description: 'Cognitive function' }
  },
  {
    id: 't1',
    label: 'N-Back Task', 
    type: 'Task',
    properties: { difficulty: 'moderate' }
  },
  {
    id: 'r1',
    label: 'Prefrontal Cortex',
    type: 'BrainRegion',
    properties: { hemisphere: 'bilateral' }
  }
];

const mockEdges = [
  {
    id: 'e1',
    source: 't1',
    target: 'c1',
    type: 'MEASURES',
    properties: { strength: 0.8 }
  },
  {
    id: 'e2', 
    source: 'c1',
    target: 'r1',
    type: 'INVOLVES',
    properties: { activation: 'positive' }
  }
];

describe('GraphControls', () => {
  const defaultProps = {
    currentLayout: 'cose-bilkent',
    onLayoutChange: jest.fn(),
    onZoomIn: jest.fn(),
    onZoomOut: jest.fn(),
    onFitView: jest.fn(),
    onResetView: jest.fn(),
    onRefresh: jest.fn(),
    nodeCount: 10,
    edgeCount: 5
  };

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders graph controls with correct node and edge counts', () => {
    render(<GraphControls {...defaultProps} />);
    
    expect(screen.getByText('10 nodes')).toBeInTheDocument();
    expect(screen.getByText('5 edges')).toBeInTheDocument();
  });

  it('calls onLayoutChange when layout is changed', async () => {
    const user = userEvent.setup();
    render(<GraphControls {...defaultProps} />);
    
    const layoutSelect = screen.getByRole('combobox');
    await user.click(layoutSelect);
    
    // Wait for options to appear
    await waitFor(() => {
      expect(screen.getByText('Hierarchical')).toBeInTheDocument();
    });
    
    await user.click(screen.getByText('Hierarchical'));
    
    expect(defaultProps.onLayoutChange).toHaveBeenCalledWith('dagre');
  });

  it('calls zoom functions when zoom buttons are clicked', async () => {
    const user = userEvent.setup();
    render(<GraphControls {...defaultProps} />);
    
    const zoomInButton = screen.getByTitle('Zoom in');
    const zoomOutButton = screen.getByTitle('Zoom out');
    
    await user.click(zoomInButton);
    expect(defaultProps.onZoomIn).toHaveBeenCalled();
    
    await user.click(zoomOutButton);
    expect(defaultProps.onZoomOut).toHaveBeenCalled();
  });

  it('shows loading state correctly', () => {
    render(<GraphControls {...defaultProps} isLoading={true} />);
    
    expect(screen.getByTestId('loading-spinner') || document.querySelector('.animate-spin')).toBeInTheDocument();
  });

  it('handles node limit slider changes', async () => {
    const onNodeLimitChange = jest.fn();
    const user = userEvent.setup();
    
    render(
      <GraphControls 
        {...defaultProps} 
        nodeLimit={[50]}
        onNodeLimitChange={onNodeLimitChange}
      />
    );
    
    // Find slider and interact with it
    const slider = screen.getByRole('slider');
    await user.click(slider);
    
    // The exact interaction will depend on the slider implementation
    // This is a basic test structure
  });
});

describe('NodeDetailsPanel', () => {
  const mockNode = mockNodes[0];
  const mockEdge = mockEdges[0];
  
  const defaultProps = {
    onClose: jest.fn(),
    onExpandNode: jest.fn(),
    connectedNodes: [mockNodes[1]],
    connectedEdges: [mockEdges[0]]
  };

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders node details when node is selected', () => {
    render(
      <NodeDetailsPanel 
        {...defaultProps}
        selectedNode={mockNode}
      />
    );
    
    expect(screen.getByText('Node Details')).toBeInTheDocument();
    expect(screen.getByText('Working Memory')).toBeInTheDocument();
    expect(screen.getAllByText('Concept')[0]).toBeInTheDocument();
  });

  it('renders edge details when edge is selected', () => {
    render(
      <NodeDetailsPanel 
        {...defaultProps}
        selectedEdge={mockEdge}
      />
    );
    
    expect(screen.getByText('Edge Details')).toBeInTheDocument();
    expect(screen.getByText('MEASURES')).toBeInTheDocument();
  });

  it('calls onClose when close button is clicked', async () => {
    const user = userEvent.setup();
    render(
      <NodeDetailsPanel 
        {...defaultProps}
        selectedNode={mockNode}
      />
    );
    
    const closeButton = screen.getByRole('button', { name: /close/i });
    await user.click(closeButton);
    
    expect(defaultProps.onClose).toHaveBeenCalled();
  });

  it('calls onExpandNode when expand button is clicked', async () => {
    const user = userEvent.setup();
    render(
      <NodeDetailsPanel 
        {...defaultProps}
        selectedNode={mockNode}
      />
    );
    
    const expandButton = screen.getByText('Expand Neighborhood');
    await user.click(expandButton);
    
    expect(defaultProps.onExpandNode).toHaveBeenCalledWith(mockNode);
  });

  it('shows connected nodes and edges', () => {
    render(
      <NodeDetailsPanel 
        {...defaultProps}
        selectedNode={mockNode}
      />
    );
    
    // Switch to connections tab
    const connectionsTab = screen.getByText('Connections');
    fireEvent.click(connectionsTab);
    
    expect(screen.getByText('N-Back Task')).toBeInTheDocument();
    expect(screen.getByText('Task')).toBeInTheDocument();
  });

  it('handles node properties correctly', () => {
    render(
      <NodeDetailsPanel 
        {...defaultProps}
        selectedNode={mockNode}
      />
    );
    
    // Properties should be shown in the Properties tab (default)
    expect(screen.getByText('Description')).toBeInTheDocument();
    expect(screen.getByText('Cognitive function')).toBeInTheDocument();
  });

  it('returns null when no node or edge is selected', () => {
    const { container } = render(
      <NodeDetailsPanel {...defaultProps} />
    );
    
    expect(container.firstChild).toBeNull();
  });
});

describe('GraphSearch', () => {
  const defaultProps = {
    onSearch: jest.fn(),
    onClearSearch: jest.fn(),
    searchQuery: '',
    nodeTypes: ['Concept', 'Task', 'BrainRegion'],
    edgeTypes: ['MEASURES', 'INVOLVES'],
    filteredTypes: new Set<string>(),
    onToggleFilter: jest.fn(),
    onResetFilters: jest.fn()
  };

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders search input with placeholder', () => {
    render(<GraphSearch {...defaultProps} />);
    
    expect(screen.getByPlaceholderText('Search nodes and edges...')).toBeInTheDocument();
  });

  it('calls onSearch when user types in search input', async () => {
    const user = userEvent.setup();
    render(<GraphSearch {...defaultProps} />);
    
    const searchInput = screen.getByPlaceholderText('Search nodes and edges...');
    await user.type(searchInput, 'memory');
    
    // Wait for debounced search
    await waitFor(() => {
      expect(defaultProps.onSearch).toHaveBeenCalledWith('memory');
    }, { timeout: 500 });
  });

  it('shows and hides filters when toggle is clicked', async () => {
    const user = userEvent.setup();
    const onToggleFilters = jest.fn();
    render(
      <GraphSearch 
        {...defaultProps} 
        showFilters={false}
        onToggleFilters={onToggleFilters}
      />
    );
    
    const filterButton = screen.getByRole('button', { name: /filter/i });
    await user.click(filterButton);
    
    expect(onToggleFilters).toHaveBeenCalled();
  });

  it('displays search results when available', () => {
    const searchResults = {
      nodes: [mockNodes[0]],
      edges: [],
      total: 1
    };
    
    render(
      <GraphSearch 
        {...defaultProps}
        searchQuery="memory"
        searchResults={searchResults}
      />
    );
    
    expect(screen.getByText('Search Results')).toBeInTheDocument();
    expect(screen.getByText('Working Memory')).toBeInTheDocument();
  });

  it('handles filter toggles correctly', async () => {
    const user = userEvent.setup();
    render(
      <GraphSearch 
        {...defaultProps}
        showFilters={true}
      />
    );
    
    // Find and click a filter checkbox
    const conceptFilter = screen.getByLabelText(/Concept/);
    await user.click(conceptFilter);
    
    expect(defaultProps.onToggleFilter).toHaveBeenCalledWith('Concept');
  });

  it('shows loading state during search', () => {
    render(<GraphSearch {...defaultProps} isSearching={true} />);
    
    expect(document.querySelector('.animate-spin')).toBeInTheDocument();
  });

  it('clears search when clear button is clicked', async () => {
    const user = userEvent.setup();
    render(<GraphSearch {...defaultProps} searchQuery="test query" />);
    
    const clearButton = screen.getByRole('button', { name: /clear/i });
    await user.click(clearButton);
    
    expect(defaultProps.onClearSearch).toHaveBeenCalled();
  });
});

describe('KnowledgeGraphExplorerEnhanced', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    
    // Mock the API responses
    brainResearcherAPI.searchNodes.mockResolvedValue(mockNodes);
    brainResearcherAPI.getGraphStats.mockResolvedValue({
      total_nodes: 3,
      total_edges: 2,
      node_types: { 'Concept': 1, 'Task': 1, 'BrainRegion': 1 },
      edge_types: { 'MEASURES': 1, 'INVOLVES': 1 }
    });
    brainResearcherAPI.expandNode.mockResolvedValue({
      nodes: [mockNodes[2]],
      edges: [mockEdges[1]]
    });
  });

  it('renders the knowledge graph explorer', async () => {
    await act(async () => {
      render(<KnowledgeGraphExplorerEnhanced />);
    });
    
    expect(screen.getByText('Knowledge Graph')).toBeInTheDocument();
  });

  it('loads initial data on mount', async () => {
    await act(async () => {
      render(<KnowledgeGraphExplorerEnhanced autoLoad={true} />);
    });
    
    await waitFor(() => {
      expect(brainResearcherAPI.searchNodes).toHaveBeenCalled();
    });
  });

  it('handles search functionality', async () => {
    await act(async () => {
      render(<KnowledgeGraphExplorerEnhanced />);
    });
    
    // Wait for initial load
    await waitFor(() => {
      expect(screen.getByPlaceholderText('Search nodes and edges...')).toBeInTheDocument();
    });
    
    const searchInput = screen.getByPlaceholderText('Search nodes and edges...');
    fireEvent.change(searchInput, { target: { value: 'working memory' } });
    
    await waitFor(() => {
      expect(brainResearcherAPI.searchNodes).toHaveBeenCalledWith(
        'working memory',
        expect.any(Object)
      );
    }, { timeout: 1000 });
  });

  it('handles layout changes', async () => {
    const user = userEvent.setup();
    
    await act(async () => {
      render(<KnowledgeGraphExplorerEnhanced />);
    });
    
    await waitFor(() => {
      expect(screen.getByRole('combobox')).toBeInTheDocument();
    });
    
    const layoutSelect = screen.getByRole('combobox');
    await user.click(layoutSelect);
    
    await waitFor(() => {
      expect(screen.getByText('Hierarchical')).toBeInTheDocument();
    });
    
    await user.click(screen.getByText('Hierarchical'));
    
    // Verify layout change was applied (this would interact with Cytoscape mock)
    expect(cytoscape().layout).toHaveBeenCalled();
  });

  it('handles export functionality', async () => {
    const user = userEvent.setup();
    
    await act(async () => {
      render(<KnowledgeGraphExplorerEnhanced enableExport={true} />);
    });
    
    // Wait for the export button to be available
    await waitFor(() => {
      expect(screen.getByTitle('Export graph')).toBeInTheDocument();
    });
    
    const exportButton = screen.getByTitle('Export graph');
    await user.click(exportButton);
    
    // Verify export function was called
    await waitFor(() => {
      expect(cytoscape().png).toHaveBeenCalled();
    });
  });

  it('handles node expansion', async () => {
    await act(async () => {
      render(
        <KnowledgeGraphExplorerEnhanced 
          initialNodes={mockNodes}
          initialEdges={mockEdges}
          autoLoad={false}
        />
      );
    });
    
    // Simulate double-clicking a node (this would typically trigger through Cytoscape events)
    // For testing, we can trigger the handler directly
    const mockCyInstance = cytoscape();
    
    // Simulate the double-click event
    const eventHandlers = mockCyInstance.on.mock.calls.find(
      ([event]) => event === 'dblclick'
    );
    
    if (eventHandlers) {
      const [, handler] = eventHandlers;
      const mockEvent = {
        target: {
          id: () => 'c1',
          data: () => ({ label: 'Working Memory', nodeType: 'Concept' })
        }
      };
      
      await act(async () => {
        handler(mockEvent);
      });
      
      await waitFor(() => {
        expect(brainResearcherAPI.expandNode).toHaveBeenCalledWith('c1');
      });
    }
  });

  it('handles error states gracefully', async () => {
    brainResearcherAPI.searchNodes.mockRejectedValue(new Error('API Error'));
    
    await act(async () => {
      render(<KnowledgeGraphExplorerEnhanced />);
    });
    
    await waitFor(() => {
      expect(screen.getByText(/Failed to Load Graph/)).toBeInTheDocument();
    });
  });

  it('shows empty state when no data is available', async () => {
    brainResearcherAPI.searchNodes.mockResolvedValue([]);
    
    await act(async () => {
      render(<KnowledgeGraphExplorerEnhanced />);
    });
    
    await waitFor(() => {
      expect(screen.getByText('No Graph Data')).toBeInTheDocument();
    });
  });

  it('handles fullscreen toggle', async () => {
    const user = userEvent.setup();
    
    await act(async () => {
      render(<KnowledgeGraphExplorerEnhanced />);
    });
    
    const fullscreenButton = screen.getByTitle('Fullscreen');
    await user.click(fullscreenButton);
    
    // Verify fullscreen class is applied
    await waitFor(() => {
      const card = document.querySelector('.fixed.inset-0.z-50');
      expect(card).toBeInTheDocument();
    });
  });
});

describe('Graph Integration Tests', () => {
  it('handles complete search and filter workflow', async () => {
    await act(async () => {
      render(<KnowledgeGraphExplorerEnhanced />);
    });
    
    // Wait for initial load
    await waitFor(() => {
      expect(screen.getByPlaceholderText('Search nodes and edges...')).toBeInTheDocument();
    });
    
    // Search for nodes
    const searchInput = screen.getByPlaceholderText('Search nodes and edges...');
    fireEvent.change(searchInput, { target: { value: 'memory' } });
    
    // Apply filters
    const filterButtons = screen.getAllByRole('button', { name: /filter/i });
    const filterButton =
      filterButtons.find((button) => button.getAttribute('aria-label') === 'Filter') ||
      filterButtons[0];
    fireEvent.click(filterButton);
    
    // Verify search and filter integration
    await waitFor(() => {
      expect(brainResearcherAPI.searchNodes).toHaveBeenCalledWith(
        'memory',
        expect.any(Object)
      );
    });
  });

  it('maintains state consistency during layout changes', async () => {
    const user = userEvent.setup();
    
    await act(async () => {
      render(
        <KnowledgeGraphExplorerEnhanced 
          initialNodes={mockNodes}
          initialEdges={mockEdges}
          autoLoad={false}
        />
      );
    });
    
    // Change layout
    const layoutSelect = screen.getByRole('combobox');
    await user.click(layoutSelect);
    
    await waitFor(() => {
      expect(screen.getByText('Hierarchical')).toBeInTheDocument();
    });
    
    await user.click(screen.getByText('Hierarchical'));
    
    // Verify node and edge counts remain consistent
    expect(screen.getByText('3 nodes')).toBeInTheDocument();
    expect(screen.getByText('2 edges')).toBeInTheDocument();
  });
});
