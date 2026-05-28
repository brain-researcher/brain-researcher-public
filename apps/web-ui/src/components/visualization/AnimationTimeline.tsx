'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card';
import { Button } from '../ui/button';
import { Slider } from '../ui/slider';
import { Label } from '../ui/label';
import { Separator } from '../ui/separator';
import { Play, Pause, SkipBack, SkipForward, Square, RotateCcw } from 'lucide-react';

interface AnimationTimelineProps {
  currentFrame: number;
  maxFrames: number;
  isAnimating: boolean;
  onFrameChange: (frame: number) => void;
  onAnimationToggle: () => void;
  className?: string;
}

export const AnimationTimeline: React.FC<AnimationTimelineProps> = ({
  currentFrame,
  maxFrames,
  isAnimating,
  onFrameChange,
  onAnimationToggle,
  className = ''
}) => {
  const [playbackSpeed, setPlaybackSpeed] = useState(1);
  const [loopMode, setLoopMode] = useState<'once' | 'loop' | 'pingpong'>('loop');
  const [direction, setDirection] = useState<'forward' | 'backward'>('forward');
  const [frameRate, setFrameRate] = useState(10); // frames per second

  // Animation step handler
  const stepFrame = useCallback((delta: number) => {
    const newFrame = currentFrame + delta;
    
    if (loopMode === 'once') {
      const clampedFrame = Math.max(0, Math.min(maxFrames - 1, newFrame));
      if (clampedFrame !== newFrame && isAnimating) {
        onAnimationToggle(); // Stop animation at boundaries
      }
      onFrameChange(clampedFrame);
    } else if (loopMode === 'loop') {
      const wrappedFrame = ((newFrame % maxFrames) + maxFrames) % maxFrames;
      onFrameChange(wrappedFrame);
    } else if (loopMode === 'pingpong') {
      // Ping-pong: reverse direction at boundaries
      if (newFrame >= maxFrames - 1 || newFrame <= 0) {
        setDirection(prev => prev === 'forward' ? 'backward' : 'forward');
      }
      const clampedFrame = Math.max(0, Math.min(maxFrames - 1, newFrame));
      onFrameChange(clampedFrame);
    }
  }, [currentFrame, maxFrames, loopMode, isAnimating, onFrameChange, onAnimationToggle]);

  // Animation loop effect
  useEffect(() => {
    if (!isAnimating || maxFrames <= 1) return;

    const interval = setInterval(() => {
      const delta = direction === 'forward' ? playbackSpeed : -playbackSpeed;
      stepFrame(delta);
    }, 1000 / frameRate);

    return () => clearInterval(interval);
  }, [isAnimating, maxFrames, playbackSpeed, direction, frameRate, stepFrame]);

  const handleFrameChange = (values: number[]) => {
    onFrameChange(values[0]);
  };

  const handlePreviousFrame = () => {
    stepFrame(-1);
  };

  const handleNextFrame = () => {
    stepFrame(1);
  };

  const handleResetToStart = () => {
    onFrameChange(0);
    setDirection('forward');
  };

  const formatTime = (frame: number) => {
    const seconds = frame / frameRate;
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = (seconds % 60).toFixed(1);
    return `${minutes}:${remainingSeconds.padStart(4, '0')}`;
  };

  const isDisabled = maxFrames <= 1;

  return (
    <Card className={className}>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2">
          4D Animation Timeline
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {isDisabled ? (
          <div className="text-center py-8 text-muted-foreground">
            <p>No 4D data available for animation</p>
            <p className="text-sm">Load a 4D NIfTI volume to enable timeline controls</p>
          </div>
        ) : (
          <>
            {/* Frame Counter */}
            <div className="flex justify-between items-center">
              <div className="text-sm">
                <span className="font-medium">Frame:</span> {currentFrame + 1} of {maxFrames}
              </div>
              <div className="text-sm text-muted-foreground">
                Time: {formatTime(currentFrame)}
              </div>
            </div>

            {/* Timeline Slider */}
            <div className="space-y-2">
              <Slider
                value={[currentFrame]}
                onValueChange={handleFrameChange}
                max={maxFrames - 1}
                min={0}
                step={1}
                className="w-full"
              />
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>0</span>
                <span>{Math.floor((maxFrames - 1) / 2)}</span>
                <span>{maxFrames - 1}</span>
              </div>
            </div>

            {/* Playback Controls */}
            <div className="flex justify-center items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={handleResetToStart}
              >
                <SkipBack className="w-4 h-4" />
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={handlePreviousFrame}
              >
                <RotateCcw className="w-4 h-4" />
              </Button>
              <Button
                size="default"
                onClick={onAnimationToggle}
                className="px-6"
              >
                {isAnimating ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={handleNextFrame}
              >
                <SkipForward className="w-4 h-4" />
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => onFrameChange(maxFrames - 1)}
              >
                <Square className="w-4 h-4" />
              </Button>
            </div>

            <Separator />

            {/* Animation Settings */}
            <div className="grid grid-cols-2 gap-4">
              {/* Playback Speed */}
              <div className="space-y-2">
                <div className="flex justify-between items-center">
                  <Label className="text-sm">Speed</Label>
                  <span className="text-sm text-muted-foreground">
                    {playbackSpeed}x
                  </span>
                </div>
                <Slider
                  value={[playbackSpeed]}
                  onValueChange={(values) => setPlaybackSpeed(values[0])}
                  max={5}
                  min={0.1}
                  step={0.1}
                  className="w-full"
                />
              </div>

              {/* Frame Rate */}
              <div className="space-y-2">
                <div className="flex justify-between items-center">
                  <Label className="text-sm">FPS</Label>
                  <span className="text-sm text-muted-foreground">
                    {frameRate}
                  </span>
                </div>
                <Slider
                  value={[frameRate]}
                  onValueChange={(values) => setFrameRate(Math.round(values[0]))}
                  max={30}
                  min={1}
                  step={1}
                  className="w-full"
                />
              </div>
            </div>

            {/* Loop Mode */}
            <div className="space-y-2">
              <Label className="text-sm">Loop Mode</Label>
              <div className="grid grid-cols-3 gap-2">
                <Button
                  size="sm"
                  variant={loopMode === 'once' ? 'default' : 'outline'}
                  onClick={() => setLoopMode('once')}
                >
                  Once
                </Button>
                <Button
                  size="sm"
                  variant={loopMode === 'loop' ? 'default' : 'outline'}
                  onClick={() => setLoopMode('loop')}
                >
                  Loop
                </Button>
                <Button
                  size="sm"
                  variant={loopMode === 'pingpong' ? 'default' : 'outline'}
                  onClick={() => setLoopMode('pingpong')}
                >
                  Ping-Pong
                </Button>
              </div>
            </div>

            {/* Direction Control */}
            <div className="space-y-2">
              <Label className="text-sm">Direction</Label>
              <div className="grid grid-cols-2 gap-2">
                <Button
                  size="sm"
                  variant={direction === 'forward' ? 'default' : 'outline'}
                  onClick={() => setDirection('forward')}
                >
                  Forward
                </Button>
                <Button
                  size="sm"
                  variant={direction === 'backward' ? 'default' : 'outline'}
                  onClick={() => setDirection('backward')}
                >
                  Backward
                </Button>
              </div>
            </div>

            {/* Timeline Stats */}
            <div className="bg-muted/50 p-3 rounded-lg">
              <h4 className="text-sm font-medium mb-2">Timeline Information</h4>
              <div className="grid grid-cols-2 gap-4 text-xs">
                <div>
                  <div className="font-medium">Total Duration</div>
                  <div className="text-muted-foreground">{formatTime(maxFrames - 1)}</div>
                </div>
                <div>
                  <div className="font-medium">Current Time</div>
                  <div className="text-muted-foreground">{formatTime(currentFrame)}</div>
                </div>
                <div>
                  <div className="font-medium">Progress</div>
                  <div className="text-muted-foreground">
                    {((currentFrame / (maxFrames - 1)) * 100).toFixed(1)}%
                  </div>
                </div>
                <div>
                  <div className="font-medium">Remaining</div>
                  <div className="text-muted-foreground">
                    {formatTime(maxFrames - 1 - currentFrame)}
                  </div>
                </div>
              </div>
            </div>

            {/* Keyboard Shortcuts */}
            <div className="bg-blue-50 dark:bg-blue-950/20 p-3 rounded-lg">
              <h4 className="text-sm font-medium mb-2">Keyboard Shortcuts</h4>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div><kbd className="px-1 bg-muted rounded">Space</kbd> Play/Pause</div>
                <div><kbd className="px-1 bg-muted rounded">←/→</kbd> Frame Step</div>
                <div><kbd className="px-1 bg-muted rounded">Home/End</kbd> First/Last</div>
                <div><kbd className="px-1 bg-muted rounded">+/-</kbd> Speed</div>
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
};

export default AnimationTimeline;