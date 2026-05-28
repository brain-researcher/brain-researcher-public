'use client';

import React, { useState, useMemo, useCallback, useRef, useEffect } from 'react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { Separator } from '@/components/ui/separator';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Checkbox } from '@/components/ui/checkbox';
import { 
  Search, 
  X, 
  Filter, 
  ChevronDown, 
  ChevronUp,
  Settings,
  Eye,
  EyeOff,
  RefreshCw
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useDebouncedValue } from '@/hooks/use-debounce';

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

interface SearchResult {
  nodes: GraphNode[];
  edges: GraphEdge[];
  total: number;
}

interface GraphSearchProps {
  // Search functionality
  onSearch: (query: string) => void;
  onClearSearch: () => void;
  searchQuery: string;
  isSearching?: boolean;
  searchResults?: SearchResult;

  // Filter functionality
  nodeTypes: string[];
  edgeTypes: string[];
  filteredTypes: Set<string>;
  onToggleFilter: (type: string) => void;
  onResetFilters: () => void;

  // Highlighting
  onHighlightNodes?: (nodeIds: string[]) => void;
  onHighlightEdges?: (edgeIds: string[]) => void;
  onClearHighlight?: () => void;

  // Display options
  showFilters?: boolean;
  onToggleFilters?: () => void;
  placeholder?: string;
  className?: string;
}

const nodeTypeColors: Record<string, string> = {
  'Concept': '#8B5CF6',
  'Task': '#10B981',
  'Dataset': '#06B6D4',
  'BrainRegion': '#F59E0B',
  'Publication': '#3B82F6',
  'Contrast': '#EF4444'
};

function SearchResultItem({ 
  node, 
  query, 
  onClick 
}: { 
  node: GraphNode; 
  query: string;
  onClick: () => void;
}) {
  const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

  const highlightText = (text: string, query: string) => {
    if (!query.trim()) return text;
    
    const regex = new RegExp(`(${escapeRegExp(query)})`, 'gi');
    const parts = text.split(regex);
    
    return parts.map((part, index) => 
      regex.test(part) ? (
        <mark key={index} className="bg-yellow-200 dark:bg-yellow-800 px-1 rounded">
          {part}
        </mark>
      ) : part
    );
  };

  return (
    <div 
      className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 cursor-pointer rounded border-l-4 border-transparent hover:border-blue-500 transition-all"
      onClick={onClick}
    >
      <div className="flex items-center justify-between">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <div
              className="w-3 h-3 rounded-full"
              style={{ backgroundColor: nodeTypeColors[node.type] || '#6B7280' }}
            />
            <span className="text-xs text-gray-500">{node.type}</span>
          </div>
          <div className="font-medium text-sm truncate">
            <span className="sr-only">{node.label}</span>
            <span aria-hidden="true">{highlightText(node.label, query)}</span>
          </div>
          <div className="text-xs text-gray-500 truncate">
            ID: {node.id}
          </div>
        </div>
      </div>
    </div>
  );
}

function FilterSection({ 
  title, 
  items, 
  filteredItems, 
  onToggle, 
  colors = {} 
}: {
  title: string;
  items: string[];
  filteredItems: Set<string>;
  onToggle: (item: string) => void;
  colors?: Record<string, string>;
}) {
  const [isExpanded, setIsExpanded] = useState(true);

  if (items.length === 0) return null;

  return (
    <div className="space-y-2">
      <Button
        variant="ghost"
        size="sm"
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full justify-between h-8 px-2"
      >
        <span className="text-sm font-medium">{title}</span>
        {isExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
      </Button>
      
      {isExpanded && (
        <div className="space-y-1 pl-2">
          {items.map(item => (
            <div key={item} className="flex items-center space-x-2">
              <Checkbox
                id={`filter-${item}`}
                checked={!filteredItems.has(item)}
                onCheckedChange={() => onToggle(item)}
                className="h-4 w-4"
              />
              <label
                htmlFor={`filter-${item}`}
                className="text-sm cursor-pointer flex items-center gap-2 flex-1"
              >
                {colors[item] && (
                  <div
                    className="w-3 h-3 rounded-full"
                    style={{ backgroundColor: colors[item] }}
                  />
                )}
                <span>{item}</span>
                <Badge variant="secondary" className="text-xs ml-auto">
                  {filteredItems.has(item) ? 0 : '?'}
                </Badge>
              </label>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function GraphSearch({
  onSearch,
  onClearSearch,
  searchQuery,
  isSearching = false,
  searchResults,
  nodeTypes,
  edgeTypes,
  filteredTypes,
  onToggleFilter,
  onResetFilters,
  onHighlightNodes,
  onHighlightEdges,
  onClearHighlight,
  showFilters = false,
  onToggleFilters,
  placeholder = "Search nodes and edges...",
  className
}: GraphSearchProps) {
  const [localQuery, setLocalQuery] = useState(searchQuery);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  
  // Debounce search to avoid excessive API calls
  const debouncedQuery = useDebouncedValue(localQuery, 300);

  useEffect(() => {
    if (debouncedQuery !== searchQuery) {
      onSearch(debouncedQuery);
    }
  }, [debouncedQuery, searchQuery, onSearch]);

  const handleClear = useCallback(() => {
    setLocalQuery('');
    onClearSearch();
    onClearHighlight?.();
    inputRef.current?.focus();
  }, [onClearSearch, onClearHighlight]);

  const handleResultClick = useCallback((node: GraphNode) => {
    onHighlightNodes?.([node.id]);
    // You might also want to fit the view to this node
  }, [onHighlightNodes]);

  const activeFilterCount = filteredTypes.size;
  const hasResults = searchResults && (searchResults.nodes.length > 0 || searchResults.edges.length > 0);

  return (
    <div className={cn("space-y-2", className)}>
      {/* Search input */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 h-4 w-4" />
        <Input
          ref={inputRef}
          type="text"
          value={localQuery}
          onChange={(e) => setLocalQuery(e.target.value)}
          placeholder={placeholder}
          className="pl-10 pr-20"
        />
        <div className="absolute right-2 top-1/2 transform -translate-y-1/2 flex items-center gap-1">
          {isSearching && (
            <RefreshCw className="h-4 w-4 text-gray-400 animate-spin" />
          )}
          {localQuery && (
            <Button
              variant="ghost"
              size="sm"
              onClick={handleClear}
              className="h-6 w-6 p-0"
              aria-label="Clear search"
              title="Clear search"
            >
              <X className="h-3 w-3" />
            </Button>
          )}
          {onToggleFilters && (
            <Button
              variant="ghost"
              size="sm"
              onClick={onToggleFilters}
              className={cn(
                "h-6 w-6 p-0",
                showFilters && "bg-blue-100 dark:bg-blue-900"
              )}
              aria-label="Filter"
              title="Filter"
            >
              <Filter className="h-3 w-3" />
              {activeFilterCount > 0 && (
                <Badge
                  variant="destructive"
                  className="absolute -top-1 -right-1 h-4 w-4 p-0 text-xs"
                >
                  {activeFilterCount}
                </Badge>
              )}
            </Button>
          )}
        </div>
      </div>

      {/* Advanced search options */}
      <div className="flex items-center justify-between text-xs text-gray-500">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="h-6 p-1"
        >
          <Settings className="h-3 w-3 mr-1" />
          Advanced
          {showAdvanced ? <ChevronUp className="h-3 w-3 ml-1" /> : <ChevronDown className="h-3 w-3 ml-1" />}
        </Button>
        
        {hasResults && (
          <span>
            Found {searchResults!.nodes.length} nodes, {searchResults!.edges.length} edges
          </span>
        )}
      </div>

      {/* Advanced search options */}
      {showAdvanced && (
        <Card className="p-3 space-y-3">
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-medium">Search Options</h4>
            <Button variant="ghost" size="sm" onClick={onResetFilters} className="text-xs h-6">
              Reset All
            </Button>
          </div>
          
          <div className="space-y-2 text-xs">
            <div className="flex items-center gap-2">
              <Checkbox id="exact-match" />
              <label htmlFor="exact-match">Exact match</label>
            </div>
            <div className="flex items-center gap-2">
              <Checkbox id="case-sensitive" />
              <label htmlFor="case-sensitive">Case sensitive</label>
            </div>
            <div className="flex items-center gap-2">
              <Checkbox id="search-properties" defaultChecked />
              <label htmlFor="search-properties">Search properties</label>
            </div>
          </div>
        </Card>
      )}

      {/* Filters panel */}
      {showFilters && (
        <Card className="p-3">
          <div className="flex items-center justify-between mb-3">
            <h4 className="text-sm font-medium flex items-center gap-2">
              <Filter className="h-4 w-4" />
              Filters
            </h4>
            <div className="flex items-center gap-2">
              {activeFilterCount > 0 && (
                <Badge variant="secondary" className="text-xs">
                  {activeFilterCount} hidden
                </Badge>
              )}
              <Button variant="ghost" size="sm" onClick={onResetFilters} className="text-xs h-6">
                Clear All
              </Button>
            </div>
          </div>

          <div className="space-y-3">
            <FilterSection
              title="Node Types"
              items={nodeTypes}
              filteredItems={filteredTypes}
              onToggle={onToggleFilter}
              colors={nodeTypeColors}
            />
            
            {edgeTypes.length > 0 && (
              <>
                <Separator />
                <FilterSection
                  title="Edge Types"
                  items={edgeTypes}
                  filteredItems={filteredTypes}
                  onToggle={onToggleFilter}
                />
              </>
            )}
          </div>
        </Card>
      )}

      {/* Search results */}
      {hasResults && localQuery.trim() && (
        <Card className="p-3">
          <div className="flex items-center justify-between mb-2">
            <h4 className="text-sm font-medium">Search Results</h4>
            <Button
              variant="ghost"
              size="sm"
              onClick={onClearHighlight}
              className="text-xs h-6"
            >
              <Eye className="h-3 w-3 mr-1" />
              Clear Highlight
            </Button>
          </div>

          {searchResults!.nodes.length > 0 && (
            <div className="space-y-2">
              <div className="text-xs text-gray-500 font-medium">
                Nodes ({searchResults!.nodes.length})
              </div>
              <ScrollArea className="max-h-64">
                <div className="space-y-1">
                  {searchResults!.nodes.slice(0, 20).map(node => (
                    <SearchResultItem
                      key={node.id}
                      node={node}
                      query={localQuery}
                      onClick={() => handleResultClick(node)}
                    />
                  ))}
                  {searchResults!.nodes.length > 20 && (
                    <div className="p-2 text-xs text-gray-500 text-center">
                      And {searchResults!.nodes.length - 20} more nodes...
                    </div>
                  )}
                </div>
              </ScrollArea>
            </div>
          )}

          {searchResults!.edges.length > 0 && (
            <div className="space-y-2 mt-4">
              <div className="text-xs text-gray-500 font-medium">
                Edges ({searchResults!.edges.length})
              </div>
              <ScrollArea className="max-h-32">
                <div className="space-y-1">
                  {searchResults!.edges.slice(0, 10).map(edge => (
                    <div
                      key={edge.id}
                      className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 cursor-pointer rounded text-xs"
                      onClick={() => onHighlightEdges?.([edge.id])}
                    >
                      <div className="font-medium">{edge.type}</div>
                      <div className="text-gray-500">
                        {edge.source} → {edge.target}
                      </div>
                    </div>
                  ))}
                  {searchResults!.edges.length > 10 && (
                    <div className="p-2 text-xs text-gray-500 text-center">
                      And {searchResults!.edges.length - 10} more edges...
                    </div>
                  )}
                </div>
              </ScrollArea>
            </div>
          )}

          {searchResults!.nodes.length === 0 && searchResults!.edges.length === 0 && (
            <div className="text-center py-4 text-gray-500">
              <Search className="h-8 w-8 mx-auto mb-2 opacity-50" />
              <p className="text-sm">No results found for "{localQuery}"</p>
              <p className="text-xs mt-1">Try different keywords or adjust filters</p>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}

// Compact version for smaller displays
export function GraphSearchCompact({
  onSearch,
  searchQuery,
  isSearching,
  onToggleFilters,
  filteredTypes,
  placeholder = "Search...",
  className
}: Pick<GraphSearchProps, 'onSearch' | 'searchQuery' | 'isSearching' | 'onToggleFilters' | 'filteredTypes' | 'placeholder' | 'className'>) {
  const [localQuery, setLocalQuery] = useState(searchQuery);
  const debouncedQuery = useDebouncedValue(localQuery, 300);

  useEffect(() => {
    if (debouncedQuery !== searchQuery) {
      onSearch(debouncedQuery);
    }
  }, [debouncedQuery, searchQuery, onSearch]);

  return (
    <div className={cn("relative", className)}>
      <Search className="absolute left-2 top-1/2 transform -translate-y-1/2 text-gray-400 h-3 w-3" />
      <Input
        type="text"
        value={localQuery}
        onChange={(e) => setLocalQuery(e.target.value)}
        placeholder={placeholder}
        className="pl-8 pr-8 h-8 text-sm"
      />
      <div className="absolute right-2 top-1/2 transform -translate-y-1/2 flex items-center gap-1">
        {isSearching && (
          <RefreshCw className="h-3 w-3 text-gray-400 animate-spin" />
        )}
          {onToggleFilters && (
          <Button
            variant="ghost"
            size="sm"
            onClick={onToggleFilters}
            className="h-5 w-5 p-0"
            aria-label="Filter"
            title="Filter"
          >
            <Filter className="h-3 w-3" />
            {filteredTypes.size > 0 && (
              <Badge
                variant="destructive"
                className="absolute -top-1 -right-1 h-3 w-3 p-0 text-xs"
              >
                {filteredTypes.size}
              </Badge>
            )}
          </Button>
        )}
      </div>
    </div>
  );
}
