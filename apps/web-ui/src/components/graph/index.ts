// Knowledge Graph Explorer Components
export { GraphControls, GraphControlsCompact } from './GraphControls';
export { NodeDetailsPanel } from './NodeDetailsPanel';
export { GraphSearch, GraphSearchCompact } from './GraphSearch';

// Hooks
export { useGraphData } from '@/hooks/use-graph-data';

// Utilities
export { 
  createLayoutManager,
  layoutDefinitions,
  layoutConfigs,
  getLayoutByName,
  getLayoutsForGraph,
  GraphLayoutManager
} from '@/lib/graph-layouts';

// Types
export interface GraphNode {
  id: string;
  label: string;
  type: string;
  properties?: Record<string, any>;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  properties?: Record<string, any>;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  stats?: {
    total_nodes: number;
    total_edges: number;
    node_types: Record<string, number>;
    edge_types: Record<string, number>;
  };
}

export interface KnowledgeGraphExplorerProps {
  initialNodes?: GraphNode[];
  initialEdges?: GraphEdge[];
  apiEndpoint?: string;
  height?: string;
  className?: string;
  onNodeClick?: (node: GraphNode) => void;
  onEdgeClick?: (edge: GraphEdge) => void;
  onNodeDoubleClick?: (node: GraphNode) => void;
  enableSearch?: boolean;
  enableFilters?: boolean;
  enableExport?: boolean;
  autoLoad?: boolean;
}