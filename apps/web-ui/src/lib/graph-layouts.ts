'use client';

// Layout configurations for Cytoscape.js
export interface LayoutConfig {
  name: string;
  animate: boolean;
  animationDuration: number;
  [key: string]: any;
}

export interface LayoutDefinition {
  name: string;
  displayName: string;
  description: string;
  config: LayoutConfig;
  bestFor: string[];
}

// Core layout configurations
export const layoutConfigs: Record<string, LayoutConfig> = {
  // Force-directed layouts
  'cose': {
    name: 'cose',
    animate: true,
    animationDuration: 1000,
    nodeDimensionsIncludeLabels: true,
    nodeRepulsion: 8000,
    idealEdgeLength: 100,
    edgeElasticity: 100,
    nestingFactor: 5,
    gravity: 80,
    numIter: 1000,
    initialTemp: 200,
    coolingFactor: 0.95,
    minTemp: 1.0
  },

  'cose-bilkent': {
    name: 'cose-bilkent',
    animate: true,
    animationDuration: 1500,
    nodeDimensionsIncludeLabels: true,
    nodeRepulsion: 4500,
    idealEdgeLength: 80,
    edgeElasticity: 0.45,
    nestingFactor: 0.1,
    numIter: 2500,
    tile: true,
    tilingPaddingVertical: 10,
    tilingPaddingHorizontal: 10,
    gravityRange: 3.8,
    gravityCompound: 1.0,
    gravityRangeCompound: 1.5
  },

  // Hierarchical layouts
  'dagre': {
    name: 'dagre',
    animate: true,
    animationDuration: 1000,
    rankDir: 'TB', // TB, BT, LR, RL
    align: undefined, // UL, UR, DL, DR
    nodeSep: 50,
    edgeSep: 10,
    rankSep: 100,
    marginX: 20,
    marginY: 20
  },

  'breadthfirst': {
    name: 'breadthfirst',
    animate: true,
    animationDuration: 1000,
    directed: true,
    roots: undefined, // Use nodes with no indegree
    padding: 10,
    spacingFactor: 1.75,
    boundingBox: undefined,
    avoidOverlap: true,
    maximal: false
  },

  // Geometric layouts  
  'circle': {
    name: 'circle',
    animate: true,
    animationDuration: 1000,
    radius: undefined, // Auto-calculated
    spacingFactor: 1.0,
    boundingBox: undefined,
    transform: (node: any, position: any) => position,
    clockwise: true,
    startAngle: 3/2 * Math.PI // Start at top
  },

  'concentric': {
    name: 'concentric',
    animate: true,
    animationDuration: 1000,
    concentric: (node: any) => node.degree(),
    levelWidth: (nodes: any) => nodes.maxDegree() / 4,
    spacingFactor: 1.0,
    boundingBox: undefined,
    avoidOverlap: true,
    clockwise: true,
    startAngle: 3/2 * Math.PI,
    minNodeSpacing: 10
  },

  'grid': {
    name: 'grid',
    animate: true,
    animationDuration: 1000,
    rows: undefined, // Auto-calculated
    cols: undefined, // Auto-calculated
    spacingFactor: 1.0,
    boundingBox: undefined,
    transform: (node: any, position: any) => position,
    nodeDimensionsIncludeLabels: false,
    avoidOverlap: true,
    avoidOverlapPadding: 10
  },

  // Random layout
  'random': {
    name: 'random',
    animate: true,
    animationDuration: 500,
    boundingBox: undefined,
    transform: (node: any, position: any) => position
  }
};

// Layout definitions with metadata
export const layoutDefinitions: LayoutDefinition[] = [
  {
    name: 'cose-bilkent',
    displayName: 'Force Directed (Advanced)',
    description: 'Advanced force-directed layout with better node separation',
    config: layoutConfigs['cose-bilkent'],
    bestFor: ['large graphs', 'complex relationships', 'general purpose']
  },
  {
    name: 'cose',
    displayName: 'Force Directed',
    description: 'Standard physics-based layout that groups related nodes',
    config: layoutConfigs['cose'],
    bestFor: ['medium graphs', 'clustering', 'organic layouts']
  },
  {
    name: 'dagre',
    displayName: 'Hierarchical',
    description: 'Tree-like layout showing clear hierarchical relationships',
    config: layoutConfigs['dagre'],
    bestFor: ['hierarchies', 'workflows', 'directed graphs']
  },
  {
    name: 'breadthfirst',
    displayName: 'Breadth First',
    description: 'Hierarchical layout starting from root nodes',
    config: layoutConfigs['breadthfirst'],
    bestFor: ['trees', 'taxonomies', 'dependency graphs']
  },
  {
    name: 'concentric',
    displayName: 'Concentric',
    description: 'Circular layers based on node importance/degree',
    config: layoutConfigs['concentric'],
    bestFor: ['centrality visualization', 'hub identification', 'small to medium graphs']
  },
  {
    name: 'circle',
    displayName: 'Circle',
    description: 'Simple circular arrangement of all nodes',
    config: layoutConfigs['circle'],
    bestFor: ['equal importance nodes', 'simple visualization', 'small graphs']
  },
  {
    name: 'grid',
    displayName: 'Grid',
    description: 'Regular grid arrangement for systematic viewing',
    config: layoutConfigs['grid'],
    bestFor: ['systematic comparison', 'dense graphs', 'matrix-like data']
  },
  {
    name: 'random',
    displayName: 'Random',
    description: 'Random positioning for initial exploration',
    config: layoutConfigs['random'],
    bestFor: ['initial positioning', 'before applying other layouts']
  }
];

// Layout utilities
export class GraphLayoutManager {
  private cy: any;
  private currentLayout: string = 'cose-bilkent';
  private layoutHistory: string[] = [];

  constructor(cytoscapeInstance: any) {
    this.cy = cytoscapeInstance;
  }

  // Apply a layout with custom options
  applyLayout(layoutName: string, customOptions?: Partial<LayoutConfig>) {
    if (!this.cy) return;

    const baseConfig = layoutConfigs[layoutName];
    if (!baseConfig) {
      console.warn(`Unknown layout: ${layoutName}`);
      return;
    }

    const layoutOptions = { ...baseConfig, ...customOptions };

    // Add to history
    if (this.currentLayout !== layoutName) {
      this.layoutHistory.push(this.currentLayout);
      this.currentLayout = layoutName;
    }

    return this.cy.layout(layoutOptions).run();
  }

  // Get layout recommendation based on graph properties
  recommendLayout(nodeCount: number, edgeCount: number, hasDirectedEdges: boolean = false): string {
    const density = nodeCount > 0 ? edgeCount / (nodeCount * (nodeCount - 1)) : 0;

    // Small graphs (< 20 nodes)
    if (nodeCount < 20) {
      return hasDirectedEdges ? 'dagre' : 'cose-bilkent';
    }
    
    // Medium graphs (20-100 nodes)
    if (nodeCount < 100) {
      if (density > 0.1) { // Dense
        return 'concentric';
      } else if (hasDirectedEdges) {
        return 'breadthfirst';
      } else {
        return 'cose-bilkent';
      }
    }

    // Large graphs (100+ nodes)
    if (density > 0.05) { // Very dense
      return 'grid';
    } else if (hasDirectedEdges) {
      return 'dagre';
    } else {
      return 'cose'; // Faster than cose-bilkent for large graphs
    }
  }

  // Animate transition between layouts
  async animateLayoutTransition(fromLayout: string, toLayout: string, steps: number = 5) {
    if (!this.cy || fromLayout === toLayout) return;

    const fromConfig = layoutConfigs[fromLayout];
    const toConfig = layoutConfigs[toLayout];
    
    if (!fromConfig || !toConfig) return;

    // Create intermediate layouts by interpolating parameters
    for (let i = 1; i <= steps; i++) {
      const progress = i / steps;
      
      // For now, just apply the target layout
      // In a more sophisticated version, we could interpolate specific parameters
      if (i === steps) {
        this.applyLayout(toLayout);
      }
      
      // Wait for each step
      await new Promise(resolve => setTimeout(resolve, 200));
    }
  }

  // Apply layout with performance optimization
  applyLayoutOptimized(layoutName: string, nodeCount: number) {
    const config = { ...layoutConfigs[layoutName] };

    // Optimize for large graphs
    if (nodeCount > 200) {
      config.animate = false; // Disable animation for performance
      
      if (layoutName === 'cose' || layoutName === 'cose-bilkent') {
        config.numIter = Math.min(500, config.numIter); // Reduce iterations
        config.nodeRepulsion = config.nodeRepulsion * 0.7; // Reduce repulsion for faster convergence
      }
    } else if (nodeCount > 100) {
      config.animationDuration = 500; // Faster animation
      
      if (layoutName === 'cose' || layoutName === 'cose-bilkent') {
        config.numIter = Math.min(1000, config.numIter);
      }
    }

    return this.applyLayout(layoutName, config);
  }

  // Get current layout info
  getCurrentLayout(): string {
    return this.currentLayout;
  }

  // Get layout history
  getLayoutHistory(): string[] {
    return [...this.layoutHistory];
  }

  // Revert to previous layout
  revertLayout(): boolean {
    if (this.layoutHistory.length === 0) return false;
    
    const previousLayout = this.layoutHistory.pop()!;
    this.currentLayout = previousLayout;
    this.applyLayout(previousLayout);
    return true;
  }

  // Stop current layout
  stopLayout() {
    if (this.cy) {
      this.cy.layout().stop();
    }
  }

  // Get layout-specific node positioning functions
  getLayoutSpecificOptions(layoutName: string, graphProperties: {
    nodeTypes: string[];
    hasHierarchy: boolean;
    centralNodes: string[];
  }) {
    const options: Partial<LayoutConfig> = {};

    switch (layoutName) {
      case 'dagre':
        // For hierarchical layouts, set root nodes
        if (graphProperties.centralNodes.length > 0) {
          options.roots = `#${graphProperties.centralNodes.join(', #')}`;
        }
        break;

      case 'breadthfirst':
        // Use central nodes as roots
        if (graphProperties.centralNodes.length > 0) {
          options.roots = `#${graphProperties.centralNodes.join(', #')}`;
        }
        break;

      case 'concentric':
        // Use degree or node type for concentric levels
        options.concentric = (node: any) => {
          const nodeType = node.data('nodeType') || node.data('type');
          const typeIndex = graphProperties.nodeTypes.indexOf(nodeType);
          return typeIndex !== -1 ? graphProperties.nodeTypes.length - typeIndex : 1;
        };
        break;

      default:
        break;
    }

    return options;
  }
}

// Export utility functions
export function getLayoutByName(name: string): LayoutDefinition | undefined {
  return layoutDefinitions.find(layout => layout.name === name);
}

export function getLayoutsForGraph(nodeCount: number, edgeCount: number): LayoutDefinition[] {
  return layoutDefinitions.filter(layout => {
    if (nodeCount < 20) return true; // All layouts work for small graphs
    if (nodeCount < 100) return !['random'].includes(layout.name);
    return ['cose', 'dagre', 'grid', 'concentric'].includes(layout.name);
  });
}

export function createLayoutManager(cytoscapeInstance: any): GraphLayoutManager {
  return new GraphLayoutManager(cytoscapeInstance);
}