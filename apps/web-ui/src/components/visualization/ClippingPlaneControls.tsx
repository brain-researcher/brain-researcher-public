'use client';

import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card';
import { Button } from '../ui/button';
import { Slider } from '../ui/slider';
import { Switch } from '../ui/switch';
import { Label } from '../ui/label';
import { Separator } from '../ui/separator';
import { RotateCcw, Scissors } from 'lucide-react';

interface ClipPlaneSettings {
  enabled: boolean;
  depth: number;
  azimuth: number;
  elevation: number;
}

interface ClippingPlaneControlsProps {
  clipPlane: ClipPlaneSettings;
  onChange: (clipPlane: ClipPlaneSettings) => void;
  className?: string;
}

export const ClippingPlaneControls: React.FC<ClippingPlaneControlsProps> = ({
  clipPlane,
  onChange,
  className = ''
}) => {
  const handleToggle = (enabled: boolean) => {
    onChange({ ...clipPlane, enabled });
  };

  const handleDepthChange = (values: number[]) => {
    onChange({ ...clipPlane, depth: values[0] });
  };

  const handleAzimuthChange = (values: number[]) => {
    onChange({ ...clipPlane, azimuth: values[0] });
  };

  const handleElevationChange = (values: number[]) => {
    onChange({ ...clipPlane, elevation: values[0] });
  };

  const handleReset = () => {
    onChange({
      enabled: false,
      depth: 0,
      azimuth: 0,
      elevation: 0
    });
  };

  const presets = [
    { name: 'Anterior', depth: 0.5, azimuth: 90, elevation: 0 },
    { name: 'Posterior', depth: 0.5, azimuth: 270, elevation: 0 },
    { name: 'Superior', depth: 0.5, azimuth: 0, elevation: 90 },
    { name: 'Inferior', depth: 0.5, azimuth: 0, elevation: 270 },
    { name: 'Left', depth: 0.5, azimuth: 0, elevation: 0 },
    { name: 'Right', depth: 0.5, azimuth: 180, elevation: 0 }
  ];

  const applyPreset = (preset: typeof presets[0]) => {
    onChange({
      enabled: true,
      depth: preset.depth,
      azimuth: preset.azimuth,
      elevation: preset.elevation
    });
  };

  return (
    <Card className={className}>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Scissors className="w-4 h-4" />
            Clipping Plane Controls
          </CardTitle>
          <Button
            size="sm"
            variant="outline"
            onClick={handleReset}
            disabled={!clipPlane.enabled && clipPlane.depth === 0 && clipPlane.azimuth === 0 && clipPlane.elevation === 0}
          >
            <RotateCcw className="w-4 h-4" />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Enable/Disable Toggle */}
        <div className="flex items-center justify-between">
          <Label htmlFor="clip-enabled" className="text-sm font-medium">
            Enable Clipping
          </Label>
          <Switch
            id="clip-enabled"
            checked={clipPlane.enabled}
            onCheckedChange={handleToggle}
          />
        </div>

        <Separator />

        {/* Depth Control */}
        <div className="space-y-2">
          <div className="flex justify-between items-center">
            <Label className="text-sm font-medium">Depth</Label>
            <span className="text-sm text-muted-foreground">
              {clipPlane.depth.toFixed(2)}
            </span>
          </div>
          <Slider
            value={[clipPlane.depth]}
            onValueChange={handleDepthChange}
            max={1}
            min={0}
            step={0.01}
            className="w-full"
            disabled={!clipPlane.enabled}
          />
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>Front</span>
            <span>Back</span>
          </div>
        </div>

        {/* Azimuth Control */}
        <div className="space-y-2">
          <div className="flex justify-between items-center">
            <Label className="text-sm font-medium">Azimuth</Label>
            <span className="text-sm text-muted-foreground">
              {clipPlane.azimuth.toFixed(0)}°
            </span>
          </div>
          <Slider
            value={[clipPlane.azimuth]}
            onValueChange={handleAzimuthChange}
            max={360}
            min={0}
            step={1}
            className="w-full"
            disabled={!clipPlane.enabled}
          />
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>0° (Anterior)</span>
            <span>360°</span>
          </div>
        </div>

        {/* Elevation Control */}
        <div className="space-y-2">
          <div className="flex justify-between items-center">
            <Label className="text-sm font-medium">Elevation</Label>
            <span className="text-sm text-muted-foreground">
              {clipPlane.elevation.toFixed(0)}°
            </span>
          </div>
          <Slider
            value={[clipPlane.elevation]}
            onValueChange={handleElevationChange}
            max={360}
            min={0}
            step={1}
            className="w-full"
            disabled={!clipPlane.enabled}
          />
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>0° (Horizontal)</span>
            <span>360°</span>
          </div>
        </div>

        <Separator />

        {/* Preset Positions */}
        <div className="space-y-3">
          <Label className="text-sm font-medium">Quick Presets</Label>
          <div className="grid grid-cols-3 gap-2">
            {presets.map((preset) => (
              <Button
                key={preset.name}
                size="sm"
                variant="outline"
                onClick={() => applyPreset(preset)}
                className="text-xs"
              >
                {preset.name}
              </Button>
            ))}
          </div>
        </div>

        {/* Advanced Info */}
        <div className="bg-muted/50 p-3 rounded-lg">
          <h4 className="text-sm font-medium mb-2">Clipping Parameters</h4>
          <div className="space-y-1 text-xs text-muted-foreground">
            <div>
              <strong>Depth:</strong> Distance from center (0 = front, 1 = back)
            </div>
            <div>
              <strong>Azimuth:</strong> Rotation around vertical axis (0° = anterior)
            </div>
            <div>
              <strong>Elevation:</strong> Rotation around horizontal axis (0° = horizontal)
            </div>
          </div>
        </div>

        {/* Real-time Preview Values */}
        {clipPlane.enabled && (
          <div className="bg-blue-50 dark:bg-blue-950/20 p-3 rounded-lg">
            <h4 className="text-sm font-medium mb-2">Current Settings</h4>
            <div className="grid grid-cols-3 gap-2 text-xs">
              <div className="text-center">
                <div className="font-medium">Depth</div>
                <div className="text-muted-foreground">{clipPlane.depth.toFixed(3)}</div>
              </div>
              <div className="text-center">
                <div className="font-medium">Azimuth</div>
                <div className="text-muted-foreground">{clipPlane.azimuth.toFixed(1)}°</div>
              </div>
              <div className="text-center">
                <div className="font-medium">Elevation</div>
                <div className="text-muted-foreground">{clipPlane.elevation.toFixed(1)}°</div>
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
};

export default ClippingPlaneControls;