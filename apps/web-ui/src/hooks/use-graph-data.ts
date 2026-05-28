'use client';

import { useState, useCallback, useRef, useEffect } from 'react';
import { brainResearcherAPI } from '@/lib/brain-researcher-api';

interface GraphNode {
  id: string;
  label: string;
  type: string;
  properties?: Record<string, any>;
}

interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  properties?: Record<string, any>;
}

interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  stats?: {
    total_nodes: number;
    total_edges: number;
    node_types: Record<string, number>;
    edge_types: Record<string, number>;
  };
}

interface GraphState {
  data: GraphData | null;
  loading: boolean;
  error: string | null;
  selectedNode: GraphNode | null;
  selectedEdge: GraphEdge | null;
  searchQuery: string;
  filteredTypes: Set<string>;
  expandedNodes: Set<string>;
}

interface UseGraphDataOptions {
  initialData?: GraphData;
  apiEndpoint?: string;
  autoLoad?: boolean;
  cacheResults?: boolean;
}

export function useGraphData({
  initialData,
  apiEndpoint = '/api',
  autoLoad = true,
  cacheResults = true
}: UseGraphDataOptions = {}) {
  const [state, setState] = useState<GraphState>({
    data: initialData || null,
    loading: false,
    error: null,
    selectedNode: null,
    selectedEdge: null,
    searchQuery: '',
    filteredTypes: new Set(),
    expandedNodes: new Set()
  });

  const cache = useRef<Map<string, GraphData>>(new Map());
  const abortController = useRef<AbortController | null>(null);

  // Load graph data from API
  const loadData = useCallback(async (query?: string, options?: { limit?: number; types?: string[] }) => {
    // Cancel previous request
    if (abortController.current) {
      abortController.current.abort();
    }

    abortController.current = new AbortController();
    
    setState(prev => ({ ...prev, loading: true, error: null }));

    try {
      const cacheKey = `${query || 'default'}_${JSON.stringify(options || {})}`;
      
      // Check cache first
      if (cacheResults && cache.current.has(cacheKey)) {
        const cachedData = cache.current.get(cacheKey)!;
        setState(prev => ({ ...prev, data: cachedData, loading: false }));
        return cachedData;
      }

      let data: GraphData;

      if (query) {
        // Search for specific nodes
        const searchResult = await brainResearcherAPI.searchNodes(query, { 
          limit: options?.limit || 100,
          signal: abortController.current.signal 
        });

        const nodes = Array.isArray(searchResult) ? searchResult.map((item: any, index: number) => ({
          id: item.node_id || `node_${index}`,
          label: item.properties?.title || item.properties?.name || item.label || `Node ${index}`,
          type: item.node_type || 'Unknown',
          properties: item.properties || {}
        })) : [];

        // Edges should come from the API - don't generate synthetic edges
        // If the API doesn't return edges, show nodes only
        data = { nodes, edges: [] };
      } else {
        // Load sample/default data
        const stats = await brainResearcherAPI.getGraphStats();
        const searchResult = await brainResearcherAPI.searchNodes('brain', { 
          limit: options?.limit || 50,
          signal: abortController.current.signal 
        });

        const nodes = Array.isArray(searchResult) ? searchResult.map((item: any, index: number) => ({
          id: item.node_id || `node_${index}`,
          label: item.properties?.title || item.properties?.name || item.label || `Node ${index}`,
          type: item.node_type || 'Unknown',
          properties: item.properties || {}
        })) : [];

        // Edges should come from the API - don't use sample data
        const edges: GraphEdge[] = [];

        data = {
          nodes,
          edges,
          stats: {
            total_nodes: stats?.total_nodes || nodes.length,
            total_edges: stats?.total_edges || edges.length,
            node_types: stats?.node_types || getNodeTypeCounts(nodes),
            edge_types: stats?.edge_types || getEdgeTypeCounts(edges)
          }
        };
      }

      // Cache the result
      if (cacheResults) {
        cache.current.set(cacheKey, data);
      }

      setState(prev => ({ ...prev, data, loading: false }));
      return data;
    } catch (err: any) {
      if (err.name === 'AbortError') return;
      
      console.error('Failed to load graph data:', err);
      const errorMessage = err.message || 'Failed to load graph data';
      setState(prev => ({ ...prev, error: errorMessage, loading: false }));
      throw err;
    }
  }, [cacheResults]);

  // Expand node neighborhood
  const expandNode = useCallback(async (nodeId: string, depth: number = 1) => {
    if (state.expandedNodes.has(nodeId)) return;

    setState(prev => ({ ...prev, loading: true }));

    try {
      const nodeData = state.data?.nodes.find(n => n.id === nodeId);
      if (!nodeData) return;

      const expandedData = await brainResearcherAPI.expandNode(nodeId, nodeData.type, depth);
      
      if (expandedData?.nodes) {
        const newNodes = expandedData.nodes.filter((newNode: GraphNode) => 
          !state.data?.nodes.find(existingNode => existingNode.id === newNode.id)
        );

        const newEdges = (expandedData.edges || []).filter((newEdge: GraphEdge) => 
          !state.data?.edges.find(existingEdge => existingEdge.id === newEdge.id)
        );

        if (newNodes.length > 0 || newEdges.length > 0) {
          setState(prev => ({
            ...prev,
            data: prev.data ? {
              ...prev.data,
              nodes: [...prev.data.nodes, ...newNodes],
              edges: [...prev.data.edges, ...newEdges]
            } : null,
            expandedNodes: new Set([...Array.from(prev.expandedNodes), nodeId]),
            loading: false
          }));
        } else {
          setState(prev => ({
            ...prev,
            expandedNodes: new Set([...Array.from(prev.expandedNodes), nodeId]),
            loading: false
          }));
        }
      }
    } catch (err) {
      console.error('Failed to expand node:', err);
      setState(prev => ({ ...prev, loading: false }));
    }
  }, [state.data, state.expandedNodes]);

  // Search functionality
  const search = useCallback((query: string) => {
    setState(prev => ({ ...prev, searchQuery: query }));
    
    if (query.trim()) {
      loadData(query);
    }
  }, [loadData]);

  // Filter functionality
  const toggleFilter = useCallback((type: string) => {
    setState(prev => {
      const newFilters = new Set(prev.filteredTypes);
      if (newFilters.has(type)) {
        newFilters.delete(type);
      } else {
        newFilters.add(type);
      }
      return { ...prev, filteredTypes: newFilters };
    });
  }, []);

  // Selection handlers
  const selectNode = useCallback((node: GraphNode | null) => {
    setState(prev => ({ ...prev, selectedNode: node, selectedEdge: null }));
  }, []);

  const selectEdge = useCallback((edge: GraphEdge | null) => {
    setState(prev => ({ ...prev, selectedEdge: edge, selectedNode: null }));
  }, []);

  // Clear selection
  const clearSelection = useCallback(() => {
    setState(prev => ({ ...prev, selectedNode: null, selectedEdge: null }));
  }, []);

  // Refresh data
  const refresh = useCallback(() => {
    cache.current.clear();
    loadData(state.searchQuery);
  }, [loadData, state.searchQuery]);

  // Reset filters
  const resetFilters = useCallback(() => {
    setState(prev => ({ ...prev, filteredTypes: new Set() }));
  }, []);

  // Get filtered data
  const getFilteredData = useCallback((): GraphData | null => {
    if (!state.data || state.filteredTypes.size === 0) {
      return state.data;
    }

    const filteredNodes = state.data.nodes.filter(node => !state.filteredTypes.has(node.type));
    const nodeIds = new Set(filteredNodes.map(node => node.id));
    const filteredEdges = state.data.edges.filter(edge => 
      nodeIds.has(edge.source) && nodeIds.has(edge.target)
    );

    return {
      ...state.data,
      nodes: filteredNodes,
      edges: filteredEdges
    };
  }, [state.data, state.filteredTypes]);

  // Auto-load data on mount
  useEffect(() => {
    if (autoLoad && !state.data && !initialData) {
      loadData();
    }
  }, [autoLoad, loadData, state.data, initialData]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (abortController.current) {
        abortController.current.abort();
      }
    };
  }, []);

  return {
    // State
    data: getFilteredData(),
    loading: state.loading,
    error: state.error,
    selectedNode: state.selectedNode,
    selectedEdge: state.selectedEdge,
    searchQuery: state.searchQuery,
    filteredTypes: state.filteredTypes,
    expandedNodes: state.expandedNodes,

    // Actions
    loadData,
    expandNode,
    search,
    toggleFilter,
    selectNode,
    selectEdge,
    clearSelection,
    refresh,
    resetFilters,

    // Computed values
    nodeTypes: state.data ? Array.from(new Set(state.data.nodes.map(n => n.type))).sort() : [],
    edgeTypes: state.data ? Array.from(new Set(state.data.edges.map(e => e.type))).sort() : [],
    nodeCount: getFilteredData()?.nodes.length || 0,
    edgeCount: getFilteredData()?.edges.length || 0,
    isExpanded: (nodeId: string) => state.expandedNodes.has(nodeId)
  };
}

// Helper functions for type counts
function getNodeTypeCounts(nodes: GraphNode[]): Record<string, number> {
  return nodes.reduce((acc, node) => {
    acc[node.type] = (acc[node.type] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);
}

function getEdgeTypeCounts(edges: GraphEdge[]): Record<string, number> {
  return edges.reduce((acc, edge) => {
    acc[edge.type] = (acc[edge.type] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);
}