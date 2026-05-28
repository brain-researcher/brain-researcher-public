'use client';

import { useRef, useEffect, useState, useCallback, useMemo } from 'react';
import { Niivue } from '@niivue/niivue';
import { createNiivueManager, type NiivueManager } from '../lib/niivue-manager';

export interface NiivueConfig {
  show3Dcrosshair?: boolean;
  backColor?: number[];
  crosshairColor?: number[];
  // Niivue 0.62.x uses ; keep legacy  for callers.
  isColorbar?: boolean;
  show3DColorbar?: boolean;
  multiplanarPadPixels?: number;
  multiplanarShowRender?: 'always' | 'never' | 'auto';
}

export interface UseNiivueReturn {
  canvasRef: React.RefObject<HTMLCanvasElement>;
  niivue: Niivue | null;
  manager: NiivueManager | null;
  isInitialized: boolean;
  error: string | null;
  loadVolume: (url: string) => Promise<void>;
  loadVolumes: (urls: string[]) => Promise<void>;
  reset: () => Promise<void>;
}

/**
 * React hook for managing Niivue 3D brain visualization
 */
export const useNiivue = (config: NiivueConfig = {}): UseNiivueReturn => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const niivueRef = useRef<Niivue | null>(null);
  const managerRef = useRef<NiivueManager | null>(null);

  const [isInitialized, setIsInitialized] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const defaultConfig = useMemo<NiivueConfig>(() => ({
    show3Dcrosshair: true,
    backColor: [0.2, 0.2, 0.2, 1],
    crosshairColor: [1, 0, 0, 1],
    isColorbar: true,
    multiplanarPadPixels: 4,
    multiplanarShowRender: 'always',
    ...config
  }), [config]);

  // Initialize Niivue instance
  const initialize = useCallback(async () => {
    if (!canvasRef.current || niivueRef.current) return;

    try {
      setError(null);
      
      // Map legacy colorbar config to the current Niivue option
      const nvOpts = {
        ...defaultConfig,
        isColorbar: (defaultConfig as any).isColorbar ?? (defaultConfig as any).show3DColorbar ?? true,
      } as any;
      const nv = new Niivue(nvOpts);
      await nv.attachTo(canvasRef.current as unknown as string);
      
      niivueRef.current = nv;
      managerRef.current = createNiivueManager(nv);
      
      setIsInitialized(true);
      console.log('Niivue initialized successfully');
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to initialize Niivue';
      setError(errorMessage);
      console.error('Niivue initialization error:', err);
    }
  }, [defaultConfig]);

  // Load a single volume
  const loadVolume = useCallback(async (url: string): Promise<void> => {
    if (!niivueRef.current) {
      throw new Error('Niivue not initialized');
    }

    try {
      await niivueRef.current.loadVolumes([{ url }]);
      console.log('Volume loaded:', url);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to load volume';
      setError(errorMessage);
      throw new Error(errorMessage);
    }
  }, []);

  // Load multiple volumes
  const loadVolumes = useCallback(async (urls: string[]): Promise<void> => {
    if (!niivueRef.current) {
      throw new Error('Niivue not initialized');
    }

    try {
      const volumeConfigs = urls.map(url => ({ url }));
      await niivueRef.current.loadVolumes(volumeConfigs);
      console.log('Volumes loaded:', urls);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to load volumes';
      setError(errorMessage);
      throw new Error(errorMessage);
    }
  }, []);

  // Reset the viewer
  const reset = useCallback(async (): Promise<void> => {
    if (!niivueRef.current) return;

    try {
      // Clear all volumes
      niivueRef.current.volumes = [];

      // Redraw scene
      niivueRef.current.drawScene();
      
      setError(null);
      console.log('Niivue viewer reset');
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to reset viewer';
      setError(errorMessage);
      console.error('Reset error:', err);
    }
  }, []);

  // Initialize when canvas is available
  useEffect(() => {
    if (canvasRef.current && !isInitialized) {
      initialize();
    }
  }, [initialize, isInitialized]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (managerRef.current) {
        managerRef.current.stopAnimation();
      }
      if (niivueRef.current) {
        niivueRef.current = null;
      }
      managerRef.current = null;
      setIsInitialized(false);
    };
  }, []);

  return {
    canvasRef,
    niivue: niivueRef.current,
    manager: managerRef.current,
    isInitialized,
    error,
    loadVolume,
    loadVolumes,
    reset
  };
};

/**
 * Hook for managing visualization state persistence
 */
export const useVisualizationState = (manager: NiivueManager | null) => {
  const [savedState, setSavedState] = useState<any>(null);

  const saveState = useCallback(() => {
    if (!manager) return null;
    
    const state = manager.getVisualizationState();
    setSavedState(state);
    
    // Store in localStorage for persistence
    try {
      localStorage.setItem('niivue-visualization-state', JSON.stringify(state));
    } catch (err) {
      console.warn('Failed to save state to localStorage:', err);
    }
    
    return state;
  }, [manager]);

  const loadState = useCallback((state?: any) => {
    if (!manager) return;

    const stateToLoad = state || savedState;
    if (!stateToLoad) {
      // Try to load from localStorage
      try {
        const stored = localStorage.getItem('niivue-visualization-state');
        if (stored) {
          const parsedState = JSON.parse(stored);
          manager.setVisualizationState(parsedState);
          setSavedState(parsedState);
        }
      } catch (err) {
        console.warn('Failed to load state from localStorage:', err);
      }
      return;
    }

    manager.setVisualizationState(stateToLoad);
  }, [manager, savedState]);

  const clearState = useCallback(() => {
    setSavedState(null);
    try {
      localStorage.removeItem('niivue-visualization-state');
    } catch (err) {
      console.warn('Failed to clear state from localStorage:', err);
    }
  }, []);

  return {
    savedState,
    saveState,
    loadState,
    clearState
  };
};

/**
 * Hook for keyboard shortcuts in Niivue
 */
export const useNiivueKeyboardShortcuts = (manager: NiivueManager | null) => {
  useEffect(() => {
    if (!manager) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      // Prevent default for our shortcuts
      const shortcuts = ['Space', 'ArrowLeft', 'ArrowRight', 'Home', 'End', 'Equal', 'Minus'];
      if (shortcuts.includes(event.code)) {
        event.preventDefault();
      }

      switch (event.code) {
        case 'Space':
          // Play/Pause animation
          if (manager.isAnimating()) {
            manager.stopAnimation();
          } else {
            manager.startAnimation();
          }
          break;

        case 'ArrowLeft':
          // Previous frame
          const currentFrame = manager.getCurrentFrame();
          const prevFrame = Math.max(0, currentFrame - 1);
          manager.setFrame(prevFrame);
          break;

        case 'ArrowRight':
          // Next frame
          const nextFrame = Math.min(manager.getMaxFrames() - 1, manager.getCurrentFrame() + 1);
          manager.setFrame(nextFrame);
          break;

        case 'Home':
          // First frame
          manager.setFrame(0);
          break;

        case 'End':
          // Last frame
          manager.setFrame(manager.getMaxFrames() - 1);
          break;

        case 'KeyR':
          if (event.ctrlKey || event.metaKey) {
            // Reset view - redraw scene
            manager.nv.drawScene();
          }
          break;

        case 'KeyS':
          if (event.ctrlKey || event.metaKey) {
            // Save screenshot
            const dataUrl = manager.exportScreenshot();
            const link = document.createElement('a');
            link.download = 'niivue-screenshot.png';
            link.href = dataUrl;
            link.click();
          }
          break;
      }
    };

    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [manager]);
};

export default useNiivue;
