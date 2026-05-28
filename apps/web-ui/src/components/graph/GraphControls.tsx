'use client';

import React from 'react';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Slider } from '@/components/ui/slider';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { 
  ZoomIn, 
  ZoomOut, 
  Maximize2, 
  Minimize2, 
  RefreshCw, 
  Download, 
  Move, 
  Pause, 
  Play,
  RotateCcw,
  Settings,
  Eye,
  EyeOff
} from 'lucide-react';
import { layoutDefinitions } from '@/lib/graph-layouts';
import { cn } from '@/lib/utils';

interface GraphControlsProps {
  // Layout controls
  currentLayout: string;
  onLayoutChange: (layout: string) => void;
  layouts?: typeof layoutDefinitions;
  isLayoutRunning?: boolean;
  onStopLayout?: () => void;

  // View controls
  onZoomIn: () => void;
  onZoomOut: () => void;
  onFitView: () => void;
  onResetView: () => void;
  onToggleFullscreen?: () => void;
  isFullscreen?: boolean;

  // Data controls
  onRefresh: () => void;
  onExport?: () => void;
  isLoading?: boolean;

  // Display options
  nodeCount: number;
  edgeCount: number;
  nodeLimit?: number[];
  onNodeLimitChange?: (limit: number[]) => void;
  maxNodeLimit?: number;

  // Filter controls
  showFilters?: boolean;
  onToggleFilters?: () => void;
  activeFilters?: number;

  // Animation controls
  animationEnabled?: boolean;
  onToggleAnimation?: () => void;
  animationSpeed?: number[];
  onAnimationSpeedChange?: (speed: number[]) => void;

  className?: string;
}

export function GraphControls({
  currentLayout,
  onLayoutChange,
  layouts = layoutDefinitions,
  isLayoutRunning = false,
  onStopLayout,

  onZoomIn,
  onZoomOut,
  onFitView,
  onResetView,
  onToggleFullscreen,
  isFullscreen = false,

  onRefresh,
  onExport,
  isLoading = false,

  nodeCount,
  edgeCount,
  nodeLimit,
  onNodeLimitChange,
  maxNodeLimit = 500,

  showFilters = false,
  onToggleFilters,
  activeFilters = 0,

  animationEnabled = true,
  onToggleAnimation,
  animationSpeed,
  onAnimationSpeedChange,

  className
}: GraphControlsProps) {
  const currentLayoutDef = layouts.find(l => l.name === currentLayout);

  return (
    <div className={cn("flex items-center justify-between gap-4 p-4 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700", className)}>
      {/* Left side - Info and layout */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
            Knowledge Graph
          </h3>
        {isLoading && (
          <div
            className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"
            data-testid="loading-spinner"
          />
        )}
        </div>

        <div className="flex gap-2">
          <Badge variant="secondary" className="text-xs">
            {nodeCount} nodes
          </Badge>
          <Badge variant="secondary" className="text-xs">
            {edgeCount} edges
          </Badge>
          {activeFilters > 0 && (
            <Badge variant="outline" className="text-xs">
              {activeFilters} filters
            </Badge>
          )}
        </div>

        <Separator orientation="vertical" className="h-6" />

        {/* Layout selector */}
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-600 dark:text-gray-400">Layout:</span>
          <Select value={currentLayout} onValueChange={onLayoutChange} disabled={isLayoutRunning}>
            <SelectTrigger className="w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {layouts.map(layout => (
                <SelectItem key={layout.name} value={layout.name}>
                  <div className="flex flex-col">
                    <span>{layout.displayName}</span>
                    <span className="text-xs text-gray-500">{layout.description}</span>
                  </div>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {isLayoutRunning && onStopLayout && (
            <Button size="sm" variant="outline" onClick={onStopLayout}>
              <Pause className="h-4 w-4" />
            </Button>
          )}
        </div>

        {/* Layout info tooltip */}
        {currentLayoutDef && (
          <div className="hidden lg:block text-xs text-gray-500 max-w-xs">
            Best for: {currentLayoutDef.bestFor.join(', ')}
          </div>
        )}
      </div>

      {/* Right side - Controls */}
      <div className="flex items-center gap-2">
        {/* Node limit slider (if provided) */}
        {nodeLimit && onNodeLimitChange && (
          <>
            <div className="flex items-center gap-2">
              <span className="text-sm text-gray-600 dark:text-gray-400">Limit:</span>
              <Slider
                value={nodeLimit}
                onValueChange={onNodeLimitChange}
                min={10}
                max={maxNodeLimit}
                step={10}
                className="w-24"
              />
              <span className="text-sm font-medium w-8 text-right">{nodeLimit[0]}</span>
            </div>
            <Separator orientation="vertical" className="h-6" />
          </>
        )}

        {/* Animation controls */}
        {onToggleAnimation && (
          <>
            <Button
              size="sm"
              variant="outline"
              onClick={onToggleAnimation}
              title={animationEnabled ? 'Disable animations' : 'Enable animations'}
            >
              {animationEnabled ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
            </Button>

            {animationSpeed && onAnimationSpeedChange && animationEnabled && (
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-500">Speed:</span>
                <Slider
                  value={animationSpeed}
                  onValueChange={onAnimationSpeedChange}
                  min={1}
                  max={10}
                  step={1}
                  className="w-16"
                />
              </div>
            )}
            <Separator orientation="vertical" className="h-6" />
          </>
        )}

        {/* View controls */}
        <Button size="sm" variant="outline" onClick={onZoomIn} title="Zoom in">
          <ZoomIn className="h-4 w-4" />
        </Button>
        
        <Button size="sm" variant="outline" onClick={onZoomOut} title="Zoom out">
          <ZoomOut className="h-4 w-4" />
        </Button>
        
        <Button size="sm" variant="outline" onClick={onFitView} title="Fit to view">
          <Move className="h-4 w-4" />
        </Button>
        
        <Button size="sm" variant="outline" onClick={onResetView} title="Reset view">
          <RotateCcw className="h-4 w-4" />
        </Button>

        <Separator orientation="vertical" className="h-6" />

        {/* Filter toggle */}
        {onToggleFilters && (
          <Button
            size="sm"
            variant="outline"
            onClick={onToggleFilters}
            title={showFilters ? 'Hide filters' : 'Show filters'}
          >
            {showFilters ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </Button>
        )}

        {/* Data controls */}
        <Button
          size="sm"
          variant="outline"
          onClick={onRefresh}
          disabled={isLoading}
          title="Refresh data"
        >
          <RefreshCw className={cn("h-4 w-4", isLoading && "animate-spin")} />
        </Button>

        {onExport && (
          <Button size="sm" variant="outline" onClick={onExport} title="Export graph">
            <Download className="h-4 w-4" />
          </Button>
        )}

        {/* Fullscreen toggle */}
        {onToggleFullscreen && (
          <Button
            size="sm"
            variant="outline"
            onClick={onToggleFullscreen}
            title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
          >
            {isFullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
          </Button>
        )}
      </div>
    </div>
  );
}

// Compact version for mobile or smaller displays
export function GraphControlsCompact({
  currentLayout,
  onLayoutChange,
  onZoomIn,
  onZoomOut,
  onFitView,
  onRefresh,
  onToggleFullscreen,
  isFullscreen = false,
  isLoading = false,
  nodeCount,
  edgeCount,
  className
}: Pick<GraphControlsProps, 
  'currentLayout' | 'onLayoutChange' | 'onZoomIn' | 'onZoomOut' | 
  'onFitView' | 'onRefresh' | 'onToggleFullscreen' | 'isFullscreen' | 
  'isLoading' | 'nodeCount' | 'edgeCount' | 'className'
>) {
  return (
    <div className={cn("flex items-center justify-between gap-2 p-2 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700", className)}>
      <div className="flex items-center gap-2">
        <Badge variant="secondary" className="text-xs">
          {nodeCount}n {edgeCount}e
        </Badge>
        
        <Select value={currentLayout} onValueChange={onLayoutChange}>
          <SelectTrigger className="w-24 h-8">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {layoutDefinitions.map(layout => (
              <SelectItem key={layout.name} value={layout.name}>
                {layout.displayName}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex items-center gap-1">
        <Button size="sm" variant="outline" onClick={onZoomIn} className="h-8 w-8 p-0">
          <ZoomIn className="h-3 w-3" />
        </Button>
        <Button size="sm" variant="outline" onClick={onZoomOut} className="h-8 w-8 p-0">
          <ZoomOut className="h-3 w-3" />
        </Button>
        <Button size="sm" variant="outline" onClick={onFitView} className="h-8 w-8 p-0">
          <Move className="h-3 w-3" />
        </Button>
        <Button size="sm" variant="outline" onClick={onRefresh} disabled={isLoading} className="h-8 w-8 p-0">
          <RefreshCw className={cn("h-3 w-3", isLoading && "animate-spin")} />
        </Button>
        {onToggleFullscreen && (
          <Button size="sm" variant="outline" onClick={onToggleFullscreen} className="h-8 w-8 p-0">
            {isFullscreen ? <Minimize2 className="h-3 w-3" /> : <Maximize2 className="h-3 w-3" />}
          </Button>
        )}
      </div>
    </div>
  );
}
