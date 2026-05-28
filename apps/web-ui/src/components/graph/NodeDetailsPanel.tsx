'use client';

import React, { useState, useMemo } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ScrollArea } from '@/components/ui/scroll-area';
import { 
  X, 
  Info, 
  ExternalLink, 
  Copy, 
  ChevronDown, 
  ChevronRight,
  Maximize2,
  Network,
  BookOpen,
  Brain,
  Database
} from 'lucide-react';
import { cn } from '@/lib/utils';

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

interface NodeDetailsPanelProps {
  selectedNode?: GraphNode | null;
  selectedEdge?: GraphEdge | null;
  onClose: () => void;
  onExpandNode?: (node: GraphNode) => void;
  onNavigateToNode?: (nodeId: string) => void;
  connectedNodes?: GraphNode[];
  connectedEdges?: GraphEdge[];
  isExpanded?: boolean;
  onToggleExpanded?: () => void;
  className?: string;
}

const nodeTypeIcons: Record<string, React.ReactNode> = {
  'Concept': <Brain className="h-4 w-4" />,
  'Task': <BookOpen className="h-4 w-4" />,
  'Dataset': <Database className="h-4 w-4" />,
  'BrainRegion': <Brain className="h-4 w-4" />,
  'Publication': <BookOpen className="h-4 w-4" />,
  'Contrast': <Network className="h-4 w-4" />
};

const nodeTypeColors: Record<string, string> = {
  'Concept': 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200',
  'Task': 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  'Dataset': 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
  'BrainRegion': 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200',
  'Publication': 'bg-indigo-100 text-indigo-800 dark:bg-indigo-900 dark:text-indigo-200',
  'Contrast': 'bg-pink-100 text-pink-800 dark:bg-pink-900 dark:text-pink-200'
};

function PropertyValue({ value }: { value: any }) {
  const [isExpanded, setIsExpanded] = useState(false);

  if (value === null || value === undefined) {
    return <span className="text-gray-400 italic">null</span>;
  }

  if (typeof value === 'boolean') {
    return <Badge variant={value ? 'default' : 'secondary'}>{String(value)}</Badge>;
  }

  if (typeof value === 'number') {
    return <span className="font-mono text-blue-600 dark:text-blue-400">{value}</span>;
  }

  if (typeof value === 'object') {
    const jsonString = JSON.stringify(value, null, 2);
    const isLong = jsonString.length > 100;

    return (
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setIsExpanded(!isExpanded)}
            className="h-6 p-1"
          >
            {isExpanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            <span className="text-xs">{Array.isArray(value) ? 'Array' : 'Object'}</span>
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigator.clipboard.writeText(jsonString)}
            className="h-6 p-1"
          >
            <Copy className="h-3 w-3" />
          </Button>
        </div>
        {isExpanded && (
          <pre className="text-xs bg-gray-100 dark:bg-gray-800 p-2 rounded overflow-x-auto">
            {isLong ? jsonString.slice(0, 500) + '...' : jsonString}
          </pre>
        )}
      </div>
    );
  }

  const stringValue = String(value);
  const isUrl = stringValue.startsWith('http://') || stringValue.startsWith('https://');
  const isLong = stringValue.length > 100;

  if (isUrl) {
    return (
      <a
        href={stringValue}
        target="_blank"
        rel="noopener noreferrer"
        className="text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-1"
      >
        {isLong ? stringValue.slice(0, 50) + '...' : stringValue}
        <ExternalLink className="h-3 w-3" />
      </a>
    );
  }

  if (isLong) {
    const [isExpanded, setIsExpanded] = useState(false);
    return (
      <div>
        <p className="break-words">
          {isExpanded ? stringValue : stringValue.slice(0, 100) + '...'}
        </p>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setIsExpanded(!isExpanded)}
          className="h-6 p-1 text-xs mt-1"
        >
          {isExpanded ? 'Show less' : 'Show more'}
        </Button>
      </div>
    );
  }

  return <span className="break-words">{stringValue}</span>;
}

function NodeDetails({ 
  node, 
  onExpandNode, 
  connectedNodes, 
  connectedEdges 
}: { 
  node: GraphNode;
  onExpandNode?: (node: GraphNode) => void;
  connectedNodes?: GraphNode[];
  connectedEdges?: GraphEdge[];
}) {
  const filteredProperties = useMemo(() => {
    if (!node.properties) return {};
    const { id, label, type, ...rest } = node.properties;
    return rest;
  }, [node.properties]);

  const propertyEntries = Object.entries(filteredProperties);

  return (
    <div className="space-y-4">
      {/* Node header */}
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          {nodeTypeIcons[node.type] || <Network className="h-4 w-4" />}
          <Badge className={cn("text-xs", nodeTypeColors[node.type] || "bg-gray-100 text-gray-800")}>
            {node.type}
          </Badge>
        </div>
        <h4 className="font-semibold text-lg break-words">{node.label}</h4>
        <p className="text-sm text-gray-500 font-mono break-all">ID: {node.id}</p>
      </div>

      {/* Actions */}
      <div className="flex gap-2">
        {onExpandNode && (
          <Button size="sm" onClick={() => onExpandNode(node)}>
            <Network className="h-4 w-4 mr-2" />
            Expand Neighborhood
          </Button>
        )}
        <Button
          variant="outline"
          size="sm"
          onClick={() => navigator.clipboard.writeText(node.id)}
        >
          <Copy className="h-4 w-4 mr-2" />
          Copy ID
        </Button>
      </div>

      {/* Tabs for different types of information */}
      <Tabs defaultValue="properties" className="w-full">
        <TabsList className="grid w-full grid-cols-3">
          <TabsTrigger value="properties">Properties</TabsTrigger>
          <TabsTrigger value="connections">Connections</TabsTrigger>
          <TabsTrigger value="metadata">Metadata</TabsTrigger>
        </TabsList>

        <TabsContent value="properties" className="space-y-3" forceMount>
          {propertyEntries.length > 0 ? (
            <ScrollArea className="h-[300px]">
              <div className="space-y-3">
                {propertyEntries.map(([key, value]) => (
                  <div key={key} className="space-y-1">
                    <div className="flex items-center justify-between">
                      <label className="text-sm font-medium text-gray-700 dark:text-gray-300 capitalize">
                        {key.replace(/_/g, ' ').replace(/^./, (char) => char.toUpperCase())}
                      </label>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => navigator.clipboard.writeText(String(value))}
                        className="h-6 p-1"
                      >
                        <Copy className="h-3 w-3" />
                      </Button>
                    </div>
                    <div className="text-sm text-gray-900 dark:text-gray-100">
                      <PropertyValue value={value} />
                    </div>
                  </div>
                ))}
              </div>
            </ScrollArea>
          ) : (
            <p className="text-gray-500 italic">No additional properties</p>
          )}
        </TabsContent>

        <TabsContent value="connections" className="space-y-3" forceMount>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <h5 className="font-medium text-sm mb-2">Connected Nodes</h5>
              {connectedNodes && connectedNodes.length > 0 ? (
                <ScrollArea className="h-[250px]">
                  <div className="space-y-2">
                    {connectedNodes.map(connectedNode => (
                      <div
                        key={connectedNode.id}
                        className="p-2 bg-gray-50 dark:bg-gray-800 rounded text-sm"
                      >
                        <div className="font-medium">{connectedNode.label}</div>
                        <div className="text-xs text-gray-500">{connectedNode.type}</div>
                      </div>
                    ))}
                  </div>
                </ScrollArea>
              ) : (
                <p className="text-gray-500 italic text-sm">No connections</p>
              )}
            </div>

            <div>
              <h5 className="font-medium text-sm mb-2">Relationships</h5>
              {connectedEdges && connectedEdges.length > 0 ? (
                <ScrollArea className="h-[250px]">
                  <div className="space-y-2">
                    {connectedEdges.map(edge => (
                      <div
                        key={edge.id}
                        className="p-2 bg-gray-50 dark:bg-gray-800 rounded text-sm"
                      >
                        <div className="font-medium text-xs">{edge.type}</div>
                        <div className="text-xs text-gray-500">
                          {edge.source === node.id ? '→ ' + edge.target : edge.source + ' →'}
                        </div>
                      </div>
                    ))}
                  </div>
                </ScrollArea>
              ) : (
                <p className="text-gray-500 italic text-sm">No relationships</p>
              )}
            </div>
          </div>
        </TabsContent>

        <TabsContent value="metadata" className="space-y-3" forceMount>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="font-medium text-gray-700 dark:text-gray-300">Node Type:</span>
              <span className="ml-2">{node.type}</span>
            </div>
            <div>
              <span className="font-medium text-gray-700 dark:text-gray-300">Properties:</span>
              <span className="ml-2">{propertyEntries.length}</span>
            </div>
            <div>
              <span className="font-medium text-gray-700 dark:text-gray-300">Connections:</span>
              <span className="ml-2">{connectedNodes?.length || 0}</span>
            </div>
            <div>
              <span className="font-medium text-gray-700 dark:text-gray-300">Relationships:</span>
              <span className="ml-2">{connectedEdges?.length || 0}</span>
            </div>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}

function EdgeDetails({ edge }: { edge: GraphEdge }) {
  const filteredProperties = useMemo(() => {
    if (!edge.properties) return {};
    const { id, source, target, type, ...rest } = edge.properties;
    return rest;
  }, [edge.properties]);

  const propertyEntries = Object.entries(filteredProperties);

  return (
    <div className="space-y-4">
      {/* Edge header */}
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Network className="h-4 w-4" />
          <Badge variant="secondary" className="text-xs">
            {edge.type}
          </Badge>
        </div>
        <h4 className="font-semibold text-lg">Relationship</h4>
        <div className="text-sm space-y-1">
          <p><span className="font-medium">From:</span> {edge.source}</p>
          <p><span className="font-medium">To:</span> {edge.target}</p>
          <p className="text-gray-500 font-mono text-xs">ID: {edge.id}</p>
        </div>
      </div>

      {/* Properties */}
      <div>
        <h5 className="font-medium text-sm mb-2">Properties</h5>
        {propertyEntries.length > 0 ? (
          <ScrollArea className="h-[300px]">
            <div className="space-y-3">
              {propertyEntries.map(([key, value]) => (
                <div key={key} className="space-y-1">
                  <label className="text-sm font-medium text-gray-700 dark:text-gray-300 capitalize">
                    {key.replace(/_/g, ' ')}
                  </label>
                  <div className="text-sm text-gray-900 dark:text-gray-100">
                    <PropertyValue value={value} />
                  </div>
                </div>
              ))}
            </div>
          </ScrollArea>
        ) : (
          <p className="text-gray-500 italic">No additional properties</p>
        )}
      </div>
    </div>
  );
}

export function NodeDetailsPanel({
  selectedNode,
  selectedEdge,
  onClose,
  onExpandNode,
  onNavigateToNode,
  connectedNodes,
  connectedEdges,
  isExpanded = false,
  onToggleExpanded,
  className
}: NodeDetailsPanelProps) {
  if (!selectedNode && !selectedEdge) return null;

  return (
    <Card className={cn(
      "absolute top-4 right-4 shadow-lg border-gray-200 dark:border-gray-700",
      isExpanded ? "w-96 max-h-[80vh]" : "w-80 max-h-96",
      className
    )}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base flex items-center gap-2">
            <Info className="h-4 w-4" />
            {selectedNode ? 'Node Details' : 'Edge Details'}
          </CardTitle>
          <div className="flex items-center gap-1">
            {onToggleExpanded && (
              <Button variant="ghost" size="sm" onClick={onToggleExpanded}>
                <Maximize2 className="h-4 w-4" />
              </Button>
            )}
            <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close">
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </CardHeader>
      
      <CardContent className="pt-0">
        {selectedNode && (
          <NodeDetails
            node={selectedNode}
            onExpandNode={onExpandNode}
            connectedNodes={connectedNodes}
            connectedEdges={connectedEdges}
          />
        )}
        
        {selectedEdge && (
          <EdgeDetails edge={selectedEdge} />
        )}
      </CardContent>
    </Card>
  );
}
