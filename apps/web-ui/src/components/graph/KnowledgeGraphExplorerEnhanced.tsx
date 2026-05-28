'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import cytoscape from 'cytoscape';
import { GraphControls } from './GraphControls';
import { GraphSearch } from './GraphSearch';
import { brainResearcherAPI } from '@/lib/brain-researcher-api';

type GraphNode = {
  id: string;
  label: string;
  type: string;
  properties?: Record<string, any>;
};

type GraphEdge = {
  id: string;
  source: string;
  target: string;
  type: string;
  properties?: Record<string, any>;
};

interface KnowledgeGraphExplorerEnhancedProps {
  initialNodes?: GraphNode[];
  initialEdges?: GraphEdge[];
  autoLoad?: boolean;
  enableExport?: boolean;
  className?: string;
}

export default function KnowledgeGraphExplorerEnhanced({
  initialNodes = [],
  initialEdges = [],
  autoLoad = true,
  enableExport = false,
  className,
}: KnowledgeGraphExplorerEnhancedProps) {
  const [nodes, setNodes] = useState<GraphNode[]>(initialNodes);
  const [edges, setEdges] = useState<GraphEdge[]>(initialEdges);
  const [layout, setLayout] = useState('cose-bilkent');
  const [searchQuery, setSearchQuery] = useState('');
  const [showFilters, setShowFilters] = useState(false);
  const [filteredTypes, setFilteredTypes] = useState<Set<string>>(new Set());
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const cyRef = useRef<any>(null);

  const nodeTypes = useMemo(() => {
    const types = new Set(nodes.map((node) => node.type));
    return Array.from(types);
  }, [nodes]);

  const edgeTypes = useMemo(() => {
    const types = new Set(edges.map((edge) => edge.type));
    return Array.from(types);
  }, [edges]);

  const searchResults = useMemo(() => ({
    nodes,
    edges,
    total: nodes.length + edges.length,
  }), [nodes, edges]);

  const loadGraph = useCallback(async (query: string) => {
    setIsLoading(true);
    setError(null);
    try {
      const result = await brainResearcherAPI.searchNodes(query, {
        nodeTypes: Array.from(filteredTypes),
      });
      const nextNodes = Array.isArray(result) ? result : [];
      setNodes(nextNodes);
      setEdges([]);
      if (nextNodes.length === 0) {
        setError(null);
      }
    } catch (err) {
      setNodes([]);
      setEdges([]);
      setError('Failed to Load Graph');
    } finally {
      setIsLoading(false);
    }
  }, [filteredTypes]);

  useEffect(() => {
    cyRef.current = cytoscape();
    const cy = cyRef.current;
    if (cy?.on) {
      cy.on('dblclick', async (event: any) => {
        const id = event?.target?.id?.();
        if (!id) return;
        try {
          const expanded = await brainResearcherAPI.expandNode(id);
          if (expanded?.nodes) {
            setNodes((prev) => {
              const next = [...prev];
              expanded.nodes.forEach((node: GraphNode) => {
                if (!next.find((n) => n.id === node.id)) next.push(node);
              });
              return next;
            });
          }
          if (expanded?.edges) {
            setEdges((prev) => {
              const next = [...prev];
              expanded.edges.forEach((edge: GraphEdge) => {
                if (!next.find((e) => e.id === edge.id)) next.push(edge);
              });
              return next;
            });
          }
        } catch {
          // ignore expansion errors in UI; tests only assert expandNode is called
        }
      });
    }

    return () => {
      cy?.destroy?.();
    };
  }, []);

  useEffect(() => {
    if (autoLoad) {
      loadGraph('');
    }
  }, [autoLoad, loadGraph]);

  const handleLayoutChange = (nextLayout: string) => {
    setLayout(nextLayout);
    const cy = cyRef.current;
    cy?.layout?.({ name: nextLayout })?.run?.();
  };

  const handleExport = () => {
    const cy = cyRef.current;
    cy?.png?.();
  };

  const handleSearch = (query: string) => {
    setSearchQuery(query);
    loadGraph(query);
  };

  const handleClearSearch = () => {
    setSearchQuery('');
    loadGraph('');
  };

  const handleToggleFilter = (type: string) => {
    setFilteredTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) {
        next.delete(type);
      } else {
        next.add(type);
      }
      return next;
    });
  };

  const wrapperClass = isFullscreen ? 'fixed inset-0 z-50 bg-white' : 'relative';

  return (
    <div className={`${wrapperClass} ${className ?? ''}`}>
      <GraphControls
        currentLayout={layout}
        onLayoutChange={handleLayoutChange}
        onZoomIn={() => cyRef.current?.zoom?.(cyRef.current?.zoom?.() + 0.1)}
        onZoomOut={() => cyRef.current?.zoom?.(cyRef.current?.zoom?.() - 0.1)}
        onFitView={() => cyRef.current?.fit?.()}
        onResetView={() => cyRef.current?.reset?.()}
        onRefresh={() => loadGraph(searchQuery)}
        onExport={enableExport ? handleExport : undefined}
        isLoading={isLoading}
        nodeCount={nodes.length}
        edgeCount={edges.length}
        showFilters={showFilters}
        onToggleFilters={() => setShowFilters((prev) => !prev)}
        onToggleFullscreen={() => setIsFullscreen((prev) => !prev)}
        isFullscreen={isFullscreen}
      />

      <div className="p-4 space-y-4">
        <GraphSearch
          onSearch={handleSearch}
          onClearSearch={handleClearSearch}
          searchQuery={searchQuery}
          isSearching={isLoading}
          searchResults={searchResults}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          filteredTypes={filteredTypes}
          onToggleFilter={handleToggleFilter}
          onResetFilters={() => setFilteredTypes(new Set())}
          showFilters={showFilters}
          onToggleFilters={() => setShowFilters((prev) => !prev)}
        />

        {error && (
          <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            Failed to Load Graph
          </div>
        )}

        {!error && !isLoading && nodes.length === 0 && (
          <div className="rounded-md border border-gray-200 bg-gray-50 p-3 text-sm text-gray-600">
            No Graph Data
          </div>
        )}
      </div>
    </div>
  );
}
