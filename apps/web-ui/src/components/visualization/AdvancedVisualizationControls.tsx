'use client';

import React, { useRef, useEffect, useState, useCallback } from 'react';
import { Niivue, SHOW_RENDER } from '@niivue/niivue';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card';
import { Button } from '../ui/button';
import { Separator } from '../ui/separator';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../ui/tabs';
import { ClippingPlaneControls } from './ClippingPlaneControls';
import { LayerManager } from './LayerManager';
import { AnimationTimeline } from './AnimationTimeline';
import { useNiivue } from '../../hooks/use-niivue';
import { createNiivueManager } from '../../lib/niivue-manager';
import { Eye, EyeOff, RotateCcw, Download, Settings } from 'lucide-react';

export interface VolumeLayer {
  id: string;
  name: string;
  url: string;
  visible: boolean;
  opacity: number;
  colormap: string;
  cal_min: number;
  cal_max: number;
  volumeId?: number; // Niivue internal volume ID
}

export interface VisualizationState {
  layers: VolumeLayer[];
  clipPlane: {
    enabled: boolean;
    depth: number;
    azimuth: number;
    elevation: number;
  };
  sliceType: 'axial' | 'coronal' | 'sagittal' | 'multiplanar';
  crosshair: boolean;
  colorbar: boolean;
  worldSpace: boolean;
  frame: number;
  maxFrames: number;
  isAnimating: boolean;
}

interface AdvancedVisualizationControlsProps {
  volumes?: string[]; // URLs of NIfTI files to load
  onStateChange?: (state: VisualizationState) => void;
  className?: string;
  enableCollaboration?: boolean;
}

export const AdvancedVisualizationControls: React.FC<AdvancedVisualizationControlsProps> = ({
  volumes = [],
  onStateChange,
  className = '',
  enableCollaboration = false
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const niivueRef = useRef<Niivue | null>(null);
  const managerRef = useRef<any>(null);
  
  const [state, setState] = useState<VisualizationState>({
    layers: [],
    clipPlane: {
      enabled: false,
      depth: 0,
      azimuth: 0,
      elevation: 0
    },
    sliceType: 'multiplanar',
    crosshair: true,
    colorbar: true,
    worldSpace: false,
    frame: 0,
    maxFrames: 0,
    isAnimating: false
  });

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Initialize Niivue and manager
  useEffect(() => {
    if (!canvasRef.current) return;

    const initializeViewer = async () => {
      try {
        setLoading(true);
        
        // Initialize Niivue
        const nv = new Niivue({
          show3Dcrosshair: state.crosshair,
          backColor: [0.2, 0.2, 0.2, 1],
          crosshairColor: [1, 0, 0, 1],
          isColorbar: state.colorbar,
          multiplanarPadPixels: 4,
          multiplanarShowRender: SHOW_RENDER.ALWAYS
        });

        await nv.attachToCanvas(canvasRef.current);
        niivueRef.current = nv;

        // Initialize manager with runtime detection
        managerRef.current = createNiivueManager(nv);

        // Load initial volumes
        if (volumes.length > 0) {
          await loadVolumes(volumes);
        }

        setError(null);
      } catch (err) {
        console.error('Failed to initialize Niivue:', err);
        setError('Failed to initialize 3D viewer');
      } finally {
        setLoading(false);
      }
    };

    initializeViewer();

    return () => {
      if (niivueRef.current) {
        niivueRef.current = null;
      }
    };
  }, []);

  // Load volumes into viewer
  const loadVolumes = useCallback(async (urls: string[]) => {
    if (!niivueRef.current) return;

    try {
      setLoading(true);
      const nv = niivueRef.current;
      
      // Load volumes and get their internal IDs
      await nv.loadVolumes(urls.map(url => ({ url })));
      
      // Create layer objects with volume IDs
      const newLayers: VolumeLayer[] = urls.map((url, index) => {
        const volumeId = nv.volumes.length > index ? index : -1;
        return {
          id: `layer_${index}`,
          name: url.split('/').pop()?.split('.')[0] || `Volume ${index + 1}`,
          url,
          visible: true,
          opacity: index === 0 ? 1.0 : 0.7,
          colormap: index === 0 ? 'gray' : 'red',
          cal_min: 0,
          cal_max: 100,
          volumeId
        };
      });

      // Apply initial layer settings
      newLayers.forEach((layer, index) => {
        if (layer.volumeId !== undefined && layer.volumeId >= 0 && nv.volumes[layer.volumeId]) {
          nv.setOpacity(layer.volumeId, layer.opacity);
          nv.setColormap(nv.volumes[layer.volumeId].id, layer.colormap);
        }
      });

      // Detect 4D volumes and update max frames
      let maxFrames = 0;
      if (nv.volumes.length > 0) {
        const volume = nv.volumes[0];
        if (volume.nFrame4D && volume.nFrame4D > 1) {
          maxFrames = volume.nFrame4D;
        }
      }

      const newState = {
        ...state,
        layers: newLayers,
        maxFrames
      };

      setState(newState);
      onStateChange?.(newState);
      
    } catch (err) {
      console.error('Failed to load volumes:', err);
      setError('Failed to load brain volumes');
    } finally {
      setLoading(false);
    }
  }, [state, onStateChange]);

  // Handle state updates
  const updateState = useCallback((updates: Partial<VisualizationState>) => {
    const newState = { ...state, ...updates };
    setState(newState);
    onStateChange?.(newState);
  }, [state, onStateChange]);

  // Handle clipping plane changes
  const handleClippingChange = useCallback((clipPlane: VisualizationState['clipPlane']) => {
    if (!niivueRef.current) return;

    const nv = niivueRef.current;
    
    if (clipPlane.enabled) {
      // Use correct API: setClipPlane([depth, azimuth, elevation])
      nv.setClipPlane([clipPlane.depth, clipPlane.azimuth, clipPlane.elevation]);
    } else {
      // Disable clipping by setting all planes to 0
      nv.setClipPlane([0, 0, 0]);
    }

    updateState({ clipPlane });
  }, [updateState]);

  // Handle layer changes
  const handleLayerChange = useCallback((layers: VolumeLayer[]) => {
    if (!niivueRef.current) return;

    const nv = niivueRef.current;
    
    layers.forEach(layer => {
      if (layer.volumeId !== undefined && layer.volumeId >= 0 && nv.volumes[layer.volumeId]) {
        // Update opacity and colormap using correct API
        nv.setOpacity(layer.volumeId, layer.visible ? layer.opacity : 0);
        nv.setColormap(nv.volumes[layer.volumeId].id, layer.colormap);
      }
    });

    updateState({ layers });
  }, [updateState]);

  // Handle frame changes for 4D volumes
  const handleFrameChange = useCallback((frame: number) => {
    if (!managerRef.current || !niivueRef.current) return;

    managerRef.current.setFrame(frame);
    updateState({ frame });
  }, [updateState]);

  // Handle animation control
  const handleAnimationToggle = useCallback(() => {
    if (!managerRef.current) return;

    const newAnimating = !state.isAnimating;
    
    if (newAnimating) {
      managerRef.current.startAnimation();
    } else {
      managerRef.current.stopAnimation();
    }

    updateState({ isAnimating: newAnimating });
  }, [state.isAnimating, updateState]);

  // Handle slice type changes
  const handleSliceTypeChange = useCallback((sliceType: VisualizationState['sliceType']) => {
    if (!niivueRef.current) return;

    const nv = niivueRef.current;
    
    switch (sliceType) {
      case 'axial':
        nv.setSliceType(nv.sliceTypeAxial);
        break;
      case 'coronal':
        nv.setSliceType(nv.sliceTypeCoronal);
        break;
      case 'sagittal':
        nv.setSliceType(nv.sliceTypeSagittal);
        break;
      case 'multiplanar':
        nv.setSliceType(nv.sliceTypeMultiplanar);
        break;
    }

    updateState({ sliceType });
  }, [updateState]);

  // Reset view
  const handleResetView = useCallback(() => {
    if (!niivueRef.current) return;
    niivueRef.current.resetBriCon();
  }, []);

  // Export screenshot
  const handleExportScreenshot = useCallback(() => {
    if (!niivueRef.current) return;
    
    const canvas = niivueRef.current.canvas;
    const link = document.createElement('a');
    link.download = 'brain-visualization.png';
    link.href = canvas.toDataURL();
    link.click();
  }, []);

  if (error) {
    return (
      <Card className={`border-red-200 ${className}`}>
        <CardHeader>
          <CardTitle className="text-red-600">Visualization Error</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-red-600">{error}</p>
          <Button 
            onClick={() => window.location.reload()} 
            className="mt-2"
            variant="outline"
          >
            Reload Page
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className={`flex flex-col h-full ${className}`}>
      {/* Main viewer */}
      <Card className="flex-1 mb-4">
        <CardHeader className="pb-2">
          <div className="flex justify-between items-center">
            <CardTitle>Brain Visualization</CardTitle>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => updateState({ crosshair: !state.crosshair })}
              >
                {state.crosshair ? <Eye className="w-4 h-4" /> : <EyeOff className="w-4 h-4" />}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={handleResetView}
              >
                <RotateCcw className="w-4 h-4" />
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={handleExportScreenshot}
              >
                <Download className="w-4 h-4" />
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-2">
          <div className="relative w-full" style={{ height: '60vh' }}>
            <canvas
              ref={canvasRef}
              className="w-full h-full border rounded"
              style={{ background: '#333' }}
            />
            {loading && (
              <div className="absolute inset-0 bg-black bg-opacity-50 flex items-center justify-center rounded">
                <div className="text-white">Loading brain data...</div>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Controls */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2">
            <Settings className="w-4 h-4" />
            Advanced Controls
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="layers" className="w-full">
            <TabsList className="grid w-full grid-cols-4">
              <TabsTrigger value="layers">Layers</TabsTrigger>
              <TabsTrigger value="clipping">Clipping</TabsTrigger>
              <TabsTrigger value="animation">Animation</TabsTrigger>
              <TabsTrigger value="settings">Settings</TabsTrigger>
            </TabsList>

            <TabsContent value="layers" className="space-y-4">
              <LayerManager
                layers={state.layers}
                onChange={handleLayerChange}
                onAddLayer={async (url) => {
                  await loadVolumes([...volumes, url]);
                }}
              />
            </TabsContent>

            <TabsContent value="clipping" className="space-y-4">
              <ClippingPlaneControls
                clipPlane={state.clipPlane}
                onChange={handleClippingChange}
              />
            </TabsContent>

            <TabsContent value="animation" className="space-y-4">
              <AnimationTimeline
                currentFrame={state.frame}
                maxFrames={state.maxFrames}
                isAnimating={state.isAnimating}
                onFrameChange={handleFrameChange}
                onAnimationToggle={handleAnimationToggle}
              />
            </TabsContent>

            <TabsContent value="settings" className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-sm font-medium">Slice Type</label>
                  <select
                    value={state.sliceType}
                    onChange={(e) => handleSliceTypeChange(e.target.value as VisualizationState['sliceType'])}
                    className="w-full mt-1 px-3 py-2 border rounded-md"
                  >
                    <option value="multiplanar">Multiplanar</option>
                    <option value="axial">Axial</option>
                    <option value="coronal">Coronal</option>
                    <option value="sagittal">Sagittal</option>
                  </select>
                </div>
                <div className="space-y-2">
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={state.colorbar}
                      onChange={(e) => updateState({ colorbar: e.target.checked })}
                    />
                    <span className="text-sm">Show Colorbar</span>
                  </label>
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={state.worldSpace}
                      onChange={(e) => updateState({ worldSpace: e.target.checked })}
                    />
                    <span className="text-sm">World Space</span>
                  </label>
                </div>
              </div>
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </div>
  );
};

export default AdvancedVisualizationControls;
