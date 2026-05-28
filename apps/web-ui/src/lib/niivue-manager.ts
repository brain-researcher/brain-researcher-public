import { Niivue } from '@niivue/niivue';

export interface FrameController {
  setFrame: (frame: number) => void;
  getCurrentFrame: () => number;
  getMaxFrames: () => number;
  startAnimation: () => void;
  stopAnimation: () => void;
  isAnimating: () => boolean;
}

export interface NiivueManager extends FrameController {
  nv: Niivue;
  detectFrameControlMethod: () => 'setFrame4D' | 'setFrame' | 'none';
  exportScreenshot: (format?: 'png' | 'jpeg') => string;
  exportAnimation: (format?: 'webm' | 'gif') => Promise<Blob>;
  alignVolumesToRAS: () => Promise<void>;
  getVisualizationState: () => any;
  setVisualizationState: (state: any) => void;
}

/**
 * Creates a Niivue manager with runtime API detection and enhanced functionality
 */
export function createNiivueManager(nv: Niivue): NiivueManager {
  let animationTimer: NodeJS.Timeout | null = null;
  let isCurrentlyAnimating = false;
  let frameControlMethod: 'setFrame4D' | 'setFrame' | 'none' | null = null;

  // Detect which frame control method is available at runtime
  const detectFrameControlMethod = (): 'setFrame4D' | 'setFrame' | 'none' => {
    if (frameControlMethod) return frameControlMethod;

    // Check for setFrame4D method (newer versions)
    if (typeof (nv as any).setFrame4D === 'function') {
      frameControlMethod = 'setFrame4D';
      console.log('Detected setFrame4D method for 4D navigation');
      return frameControlMethod;
    }

    // Check for setFrame method (older versions)
    if (typeof (nv as any).setFrame === 'function') {
      frameControlMethod = 'setFrame';
      console.log('Detected setFrame method for 4D navigation');
      return frameControlMethod;
    }

    // Check for volumes with frame properties
    if (nv.volumes && nv.volumes.length > 0) {
      const volume = nv.volumes[0];
      if (volume.nFrame4D && volume.nFrame4D > 1) {
        // Try to use volume.frame4D property directly
        frameControlMethod = 'setFrame';
        console.log('Detected 4D volume properties for navigation');
        return frameControlMethod;
      }
    }

    frameControlMethod = 'none';
    console.warn('No 4D frame control method detected');
    return frameControlMethod;
  };

  // Set current frame with runtime detection
  const setFrame = (frame: number): void => {
    const method = detectFrameControlMethod();
    
    if (method === 'none') {
      console.warn('No frame control method available');
      return;
    }

    try {
      if (method === 'setFrame4D' && typeof (nv as any).setFrame4D === 'function') {
        (nv as any).setFrame4D(frame);
      } else if (method === 'setFrame' && typeof (nv as any).setFrame === 'function') {
        (nv as any).setFrame(frame);
      } else if (nv.volumes && nv.volumes.length > 0) {
        // Fallback: set frame property directly and redraw
        const volume = nv.volumes[0];
        if (volume.frame4D !== undefined) {
          volume.frame4D = frame;
          nv.updateGLVolume();
          nv.drawScene();
        }
      }
    } catch (error) {
      console.error('Error setting frame:', error);
    }
  };

  // Get current frame
  const getCurrentFrame = (): number => {
    if (nv.volumes && nv.volumes.length > 0) {
      const volume = nv.volumes[0];
      return volume.frame4D || 0;
    }
    return 0;
  };

  // Get maximum frames
  const getMaxFrames = (): number => {
    if (nv.volumes && nv.volumes.length > 0) {
      const volume = nv.volumes[0];
      return volume.nFrame4D || 1;
    }
    return 1;
  };

  // Start animation
  const startAnimation = (): void => {
    if (isCurrentlyAnimating || getMaxFrames() <= 1) return;

    isCurrentlyAnimating = true;
    let currentFrame = getCurrentFrame();

    const animate = () => {
      if (!isCurrentlyAnimating) return;

      currentFrame = (currentFrame + 1) % getMaxFrames();
      setFrame(currentFrame);

      animationTimer = setTimeout(animate, 100); // 10 FPS
    };

    animate();
  };

  // Stop animation
  const stopAnimation = (): void => {
    isCurrentlyAnimating = false;
    if (animationTimer) {
      clearTimeout(animationTimer);
      animationTimer = null;
    }
  };

  // Check if animating
  const isAnimating = (): boolean => {
    return isCurrentlyAnimating;
  };

  // Export screenshot
  const exportScreenshot = (format: 'png' | 'jpeg' = 'png'): string => {
    const canvas = nv.canvas;
    return canvas.toDataURL(`image/${format}`);
  };

  // Export animation (WebM format for web compatibility)
  const exportAnimation = async (format: 'webm' | 'gif' = 'webm'): Promise<Blob> => {
    const maxFrames = getMaxFrames();
    if (maxFrames <= 1) {
      throw new Error('No 4D data available for animation export');
    }

    // For WebM export using MediaRecorder API
    if (format === 'webm' && 'MediaRecorder' in window) {
      return new Promise((resolve, reject) => {
        const canvas = nv.canvas;
        const stream = canvas.captureStream(10); // 10 FPS
        const mediaRecorder = new MediaRecorder(stream, {
          mimeType: 'video/webm;codecs=vp9'
        });

        const chunks: Blob[] = [];
        
        mediaRecorder.ondataavailable = (event) => {
          chunks.push(event.data);
        };

        mediaRecorder.onstop = () => {
          const blob = new Blob(chunks, { type: 'video/webm' });
          resolve(blob);
        };

        mediaRecorder.onerror = (event) => {
          reject(new Error('MediaRecorder error'));
        };

        mediaRecorder.start();

        // Animate through all frames
        let currentFrame = 0;
        const animateForExport = () => {
          setFrame(currentFrame);
          currentFrame++;
          
          if (currentFrame >= maxFrames) {
            setTimeout(() => mediaRecorder.stop(), 100);
          } else {
            setTimeout(animateForExport, 100);
          }
        };

        animateForExport();
      });
    }

    // Fallback: collect frames as data URLs (for GIF or if WebM not supported)
    const frames: string[] = [];
    const originalFrame = getCurrentFrame();

    for (let i = 0; i < maxFrames; i++) {
      setFrame(i);
      await new Promise(resolve => setTimeout(resolve, 50)); // Wait for render
      frames.push(exportScreenshot());
    }

    // Restore original frame
    setFrame(originalFrame);

    // For now, return a simple blob with frame data
    // In a real implementation, you'd use a GIF encoder library
    const frameData = JSON.stringify(frames);
    return new Blob([frameData], { type: 'application/json' });
  };

  // Align all volumes to RAS+ coordinate system
  const alignVolumesToRAS = async (): Promise<void> => {
    if (!nv.volumes || nv.volumes.length === 0) return;

    try {
      // Niivue automatically handles coordinate system alignment
      // This method ensures all volumes use the same space
      await nv.loadVolumes(nv.volumes.map(vol => ({ url: vol.url })));
      console.log('Volumes aligned to RAS+ coordinate system');
    } catch (error) {
      console.error('Error aligning volumes to RAS:', error);
    }
  };

  // Get current visualization state for serialization
  const getVisualizationState = () => {
    const state = {
      volumes: nv.volumes.map(vol => ({
        url: vol.url,
        opacity: vol.opacity,
        colormap: vol.colormap,
        cal_min: vol.cal_min,
        cal_max: vol.cal_max,
        frame4D: vol.frame4D
      })),
      sliceType: (nv as any).sliceType,
      crosshair: nv.opts.show3Dcrosshair,
      // Niivue >=0.62 uses ; fall back if older props exist
      colorbar: (nv as any).opts?.isColorbar ?? (nv as any).opts?.showLegend ?? (nv as any).opts?.show3DColorbar,
      clipPlane: nv.scene.clipPlane || [0, 0, 0],
      camera: {
        azimuth: nv.scene.renderAzimuth,
        elevation: nv.scene.renderElevation,
        distance: nv.volScaleMultiplier
      }
    };

    return state;
  };

  // Set visualization state from serialized data
  const setVisualizationState = (state: any): void => {
    try {
      // Set slice type
      if (state.sliceType !== undefined) {
        nv.setSliceType(state.sliceType);
      }

      // Set clip plane
      if (state.clipPlane && Array.isArray(state.clipPlane)) {
        nv.setClipPlane(state.clipPlane);
      }

      // Set volume properties
      if (state.volumes && Array.isArray(state.volumes)) {
        state.volumes.forEach((volState: any, index: number) => {
          if (nv.volumes[index]) {
            if (volState.opacity !== undefined) {
              nv.setOpacity(index, volState.opacity);
            }
            if (volState.colormap !== undefined) {
              (nv as any).setColormap(index, volState.colormap as any);
            }
            if (volState.frame4D !== undefined) {
              setFrame(volState.frame4D);
            }
          }
        });
      }

      // Set camera position
      if (state.camera) {
        if (state.camera.azimuth !== undefined) {
          nv.scene.renderAzimuth = state.camera.azimuth;
        }
        if (state.camera.elevation !== undefined) {
          nv.scene.renderElevation = state.camera.elevation;
        }
        if (state.camera.distance !== undefined) {
          nv.volScaleMultiplier = state.camera.distance;
        }
      }

      // Redraw scene
      nv.drawScene();
    } catch (error) {
      console.error('Error setting visualization state:', error);
    }
  };

  return {
    nv,
    detectFrameControlMethod,
    setFrame,
    getCurrentFrame,
    getMaxFrames,
    startAnimation,
    stopAnimation,
    isAnimating,
    exportScreenshot,
    exportAnimation,
    alignVolumesToRAS,
    getVisualizationState,
    setVisualizationState
  };
}

export default createNiivueManager;
