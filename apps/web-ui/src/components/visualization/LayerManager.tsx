'use client';

import React, { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card';
import { Button } from '../ui/button';
import { Slider } from '../ui/slider';
import { Switch } from '../ui/switch';
import { Label } from '../ui/label';
import { Separator } from '../ui/separator';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '../ui/dialog';
import { Eye, EyeOff, Plus, Trash2, Settings, Palette, Upload } from 'lucide-react';

export interface VolumeLayer {
  id: string;
  name: string;
  url: string;
  visible: boolean;
  opacity: number;
  colormap: string;
  cal_min: number;
  cal_max: number;
  volumeId?: number;
}

interface LayerManagerProps {
  layers: VolumeLayer[];
  onChange: (layers: VolumeLayer[]) => void;
  onAddLayer?: (url: string) => Promise<void>;
  className?: string;
}

const COLORMAPS = [
  'gray', 'red', 'green', 'blue', 'yellow', 'purple', 'cyan',
  'hot', 'cool', 'spring', 'summer', 'autumn', 'winter',
  'bone', 'copper', 'pink', 'lines', 'colorcube', 'prism',
  'flag', 'white'
];

export const LayerManager: React.FC<LayerManagerProps> = ({
  layers,
  onChange,
  onAddLayer,
  className = ''
}) => {
  const [selectedLayer, setSelectedLayer] = useState<string | null>(null);
  const [isAddDialogOpen, setIsAddDialogOpen] = useState(false);
  const [newLayerUrl, setNewLayerUrl] = useState('');

  const updateLayer = (layerId: string, updates: Partial<VolumeLayer>) => {
    const updatedLayers = layers.map(layer =>
      layer.id === layerId ? { ...layer, ...updates } : layer
    );
    onChange(updatedLayers);
  };

  const removeLayer = (layerId: string) => {
    const filteredLayers = layers.filter(layer => layer.id !== layerId);
    onChange(filteredLayers);
  };

  const handleAddLayer = async () => {
    if (!newLayerUrl.trim() || !onAddLayer) return;
    
    try {
      await onAddLayer(newLayerUrl.trim());
      setNewLayerUrl('');
      setIsAddDialogOpen(false);
    } catch (error) {
      console.error('Failed to add layer:', error);
      // Could add toast notification here
    }
  };

  const moveLayer = (layerId: string, direction: 'up' | 'down') => {
    const currentIndex = layers.findIndex(layer => layer.id === layerId);
    if (currentIndex === -1) return;

    const newIndex = direction === 'up' ? currentIndex - 1 : currentIndex + 1;
    if (newIndex < 0 || newIndex >= layers.length) return;

    const reorderedLayers = [...layers];
    [reorderedLayers[currentIndex], reorderedLayers[newIndex]] = 
    [reorderedLayers[newIndex], reorderedLayers[currentIndex]];
    
    onChange(reorderedLayers);
  };

  return (
    <Card className={className}>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Palette className="w-4 h-4" />
            Layer Management
          </CardTitle>
          {onAddLayer && (
            <Dialog open={isAddDialogOpen} onOpenChange={setIsAddDialogOpen}>
              <DialogTrigger asChild>
                <Button size="sm" variant="outline">
                  <Plus className="w-4 h-4 mr-1" />
                  Add Layer
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Add New Layer</DialogTitle>
                  <DialogDescription>
                    Load a NIfTI volume to overlay in the viewer.
                  </DialogDescription>
                </DialogHeader>
                <div className="space-y-4">
                  <div>
                    <Label htmlFor="layer-url">NIfTI File URL</Label>
                    <input
                      id="layer-url"
                      type="text"
                      value={newLayerUrl}
                      onChange={(e) => setNewLayerUrl(e.target.value)}
                      placeholder="Enter NIfTI URL"
                      className="w-full mt-1 px-3 py-2 border rounded-md"
                    />
                  </div>
                  <div className="flex gap-2">
                    <Button onClick={handleAddLayer} className="flex-1">
                      <Upload className="w-4 h-4 mr-2" />
                      Load Layer
                    </Button>
                    <Button variant="outline" onClick={() => setIsAddDialogOpen(false)}>
                      Cancel
                    </Button>
                  </div>
                </div>
              </DialogContent>
            </Dialog>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {layers.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground">
            No layers loaded. Add a brain volume to get started.
          </div>
        ) : (
          layers.map((layer, index) => (
            <Card key={layer.id} className="border-2 hover:border-blue-200 transition-colors">
              <CardContent className="p-4">
                {/* Layer Header */}
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => updateLayer(layer.id, { visible: !layer.visible })}
                      className="p-1"
                    >
                      {layer.visible ? 
                        <Eye className="w-4 h-4" /> : 
                        <EyeOff className="w-4 h-4 opacity-50" />
                      }
                    </Button>
                    <div>
                      <h4 className="font-medium text-sm">{layer.name}</h4>
                      <p className="text-xs text-muted-foreground">Volume ID: {layer.volumeId ?? 'N/A'}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-1">
                    {/* Layer ordering */}
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => moveLayer(layer.id, 'up')}
                      disabled={index === 0}
                      className="p-1 text-xs"
                    >
                      ↑
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => moveLayer(layer.id, 'down')}
                      disabled={index === layers.length - 1}
                      className="p-1 text-xs"
                    >
                      ↓
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setSelectedLayer(selectedLayer === layer.id ? null : layer.id)}
                      className="p-1"
                    >
                      <Settings className="w-4 h-4" />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => removeLayer(layer.id)}
                      className="p-1 text-red-600 hover:text-red-700"
                      disabled={layers.length === 1}
                    >
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  </div>
                </div>

                {/* Opacity Control */}
                <div className="space-y-2">
                  <div className="flex justify-between items-center">
                    <Label className="text-sm">Opacity</Label>
                    <span className="text-sm text-muted-foreground">
                      {(layer.opacity * 100).toFixed(0)}%
                    </span>
                  </div>
                  <Slider
                    value={[layer.opacity]}
                    onValueChange={(values) => updateLayer(layer.id, { opacity: values[0] })}
                    max={1}
                    min={0}
                    step={0.01}
                    className="w-full"
                    disabled={!layer.visible}
                  />
                </div>

                {/* Colormap Selection */}
                <div className="space-y-2">
                  <Label className="text-sm">Colormap</Label>
                  <select
                    value={layer.colormap}
                    onChange={(e) => updateLayer(layer.id, { colormap: e.target.value })}
                    className="w-full px-2 py-1 border rounded text-sm"
                    disabled={!layer.visible}
                  >
                    {COLORMAPS.map(colormap => (
                      <option key={colormap} value={colormap}>
                        {colormap.charAt(0).toUpperCase() + colormap.slice(1)}
                      </option>
                    ))}
                  </select>
                </div>

                {/* Advanced Settings */}
                {selectedLayer === layer.id && (
                  <>
                    <Separator className="my-3" />
                    <div className="space-y-3">
                      <h5 className="text-sm font-medium">Advanced Settings</h5>
                      
                      {/* Intensity Range */}
                      <div className="space-y-2">
                        <Label className="text-sm">Min Intensity</Label>
                        <Slider
                          value={[layer.cal_min]}
                          onValueChange={(values) => updateLayer(layer.id, { cal_min: values[0] })}
                          max={1000}
                          min={0}
                          step={1}
                          className="w-full"
                        />
                        <div className="flex justify-between text-xs text-muted-foreground">
                          <span>0</span>
                          <span>{layer.cal_min}</span>
                          <span>1000</span>
                        </div>
                      </div>

                      <div className="space-y-2">
                        <Label className="text-sm">Max Intensity</Label>
                        <Slider
                          value={[layer.cal_max]}
                          onValueChange={(values) => updateLayer(layer.id, { cal_max: values[0] })}
                          max={1000}
                          min={0}
                          step={1}
                          className="w-full"
                        />
                        <div className="flex justify-between text-xs text-muted-foreground">
                          <span>0</span>
                          <span>{layer.cal_max}</span>
                          <span>1000</span>
                        </div>
                      </div>

                      {/* Layer Info */}
                      <div className="bg-muted/50 p-2 rounded text-xs">
                        <div><strong>URL:</strong> {layer.url}</div>
                        <div><strong>Range:</strong> {layer.cal_min} - {layer.cal_max}</div>
                      </div>
                    </div>
                  </>
                )}
              </CardContent>
            </Card>
          ))
        )}

        {/* Layer Stack Order Info */}
        {layers.length > 1 && (
          <div className="bg-blue-50 dark:bg-blue-950/20 p-3 rounded-lg">
            <h4 className="text-sm font-medium mb-2">Layer Stack</h4>
            <div className="text-xs text-muted-foreground">
              Layers are rendered from bottom to top. Use ↑↓ buttons to reorder.
              Higher layers will be blended over lower layers based on opacity.
            </div>
            <div className="mt-2 space-y-1">
              {layers.map((layer, index) => (
                <div key={layer.id} className="flex items-center gap-2">
                  <span className="w-4 text-center">{layers.length - index}</span>
                  <div className={`w-2 h-2 rounded ${layer.visible ? 'bg-green-500' : 'bg-gray-300'}`} />
                  <span className="text-xs">{layer.name}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Quick Actions */}
        {layers.length > 0 && (
          <>
            <Separator />
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  const updatedLayers = layers.map(layer => ({ ...layer, visible: true }));
                  onChange(updatedLayers);
                }}
                className="flex-1"
              >
                Show All
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  const updatedLayers = layers.map(layer => ({ ...layer, visible: false }));
                  onChange(updatedLayers);
                }}
                className="flex-1"
              >
                Hide All
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  const updatedLayers = layers.map(layer => ({ ...layer, opacity: 0.5 }));
                  onChange(updatedLayers);
                }}
                className="flex-1"
              >
                50% All
              </Button>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
};

export default LayerManager;
