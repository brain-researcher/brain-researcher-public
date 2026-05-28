'use client';

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Niivue } from '@niivue/niivue';
import { mat4 } from 'gl-matrix';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Slider } from '@/components/ui/slider';
import { 
  Download, 
  Maximize2, 
  Minimize2, 
  RotateCw,
  Grid3X3,
  Brain,
  Layers
} from 'lucide-react';

import { resolveKgVizUrl } from '@/lib/service-endpoints';
import { resolveVolumeName } from '@/lib/niivue/resolveVolumeName';

type Overlay = { 
  url: string; 
  name?: string;
  colormap?: string; 
  min?: number; 
  max?: number; 
  threshold?: number;
  opacity?: number;
};

type VizConfig = {
  baseVolume: string;
  baseVolumeFallback?: string;
  overlays?: Overlay[];
  surfaces?: {
    left?: { mesh: string; scalar?: string };
    right?: { mesh: string; scalar?: string };
  };
  export?: { enableSnapshot?: boolean };
  interaction?: { 
    allowPick?: boolean; 
    allowSlice?: boolean;
    allowDrag?: boolean;
  };
  metadata?: {
    subject?: string;
    session?: string;
    task?: string;
    dataset?: string;
  };
};

type ViewOption = 'axial' | 'coronal' | 'sagittal' | '3d' | 'mosaic';

export type BrainViewerPoint = { x: number; y: number; z: number };

interface Brain3DProps {
  jobId?: string;
  config?: VizConfig;
  preferredOverlayName?: string;
  preferredOverlayUrl?: string;
  height?: string;
  mode?: 'full' | 'compact';
  initialView?: ViewOption;
  focusPoint?: BrainViewerPoint;
  peaks?: BrainViewerPoint[];
}

export function Brain3D({
  jobId,
  config: externalConfig,
  preferredOverlayName,
  preferredOverlayUrl,
  height = '600px',
  mode = 'full',
  initialView = '3d',
    focusPoint,
    peaks: _peaks, // currently unused: future marker rendering
  }: Brain3DProps) {
  const resolvedJobId = jobId || 'analysis';
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const niivueRef = useRef<any>(null);
  const [cfg, setCfg] = useState<VizConfig | null>(null);
  const [isLoading, setIsLoading] = useState(Boolean(jobId) && !externalConfig);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [retryNonce, setRetryNonce] = useState(0);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [threshold, setThreshold] = useState<number[]>([0]);
  const [opacity, setOpacity] = useState<number[]>([1]);
  const [currentView, setCurrentView] = useState<ViewOption>(initialView);
  const currentViewRef = useRef<ViewOption>(initialView);
  const [coordinates, setCoordinates] = useState({ x: 0, y: 0, z: 0 });
  const [niivueReady, setNiivueReady] = useState(false);

  const normalizeOverlayKey = useCallback((value?: string | null) => {
    if (!value) return '';
    const stripped = value.split('#', 1)[0]?.split('?', 1)[0] ?? value;
    const decoded = decodeURIComponent(stripped);
    const segments = decoded.split('/').filter(Boolean);
    return (segments.at(-1) ?? decoded).toLowerCase();
  }, []);

  const applyOverlayPreference = useCallback(
    (config: VizConfig | null): VizConfig | null => {
      if (!config?.overlays?.length) {
        return config;
      }

      const preferredKeys = new Set(
        [preferredOverlayName, preferredOverlayUrl]
          .map((value) => normalizeOverlayKey(value))
          .filter(Boolean),
      );

      if (!preferredKeys.size) {
        return config;
      }

      const overlays = [...config.overlays];
      const preferredIndex = overlays.findIndex((overlay) => {
        const overlayKeys = [
          normalizeOverlayKey(overlay.name),
          normalizeOverlayKey(overlay.url),
        ];
        return overlayKeys.some((key) => key && preferredKeys.has(key));
      });

      if (preferredIndex <= 0) {
        return config;
      }

      const preferredOverlay = overlays.splice(preferredIndex, 1)[0];
      overlays.unshift(preferredOverlay);
      return { ...config, overlays };
    },
    [normalizeOverlayKey, preferredOverlayName, preferredOverlayUrl],
  );

  const ensureCanvasSize = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const parent = canvas.parentElement;
    if (!parent) return;
    const rect = parent.getBoundingClientRect();
    const dpr =
      typeof window !== 'undefined'
        ? Math.min(2, Math.max(1, window.devicePixelRatio || 1))
        : 1;
    const width = Math.max(2, Math.floor(rect.width * dpr));
    const height = Math.max(2, Math.floor(rect.height * dpr));
    canvas.style.width = '100%';
    canvas.style.height = '100%';
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    var nvInstance = niivueRef.current as any;
    var glCanvas = nvInstance && nvInstance.gl && nvInstance.gl.canvas ? nvInstance.gl.canvas : null;
    if (glCanvas) {
      if (glCanvas.width !== width || glCanvas.height !== height) {
        glCanvas.width = width;
        glCanvas.height = height;
      }
    }
    if (nvInstance && nvInstance.canvas && nvInstance.canvas !== canvas) {
      if (nvInstance.canvas.width !== width || nvInstance.canvas.height !== height) {
        nvInstance.canvas.width = width;
        nvInstance.canvas.height = height;
      }
    }
    nvInstance?.resizeListener?.();
    if (nvInstance && nvInstance.gl && nvInstance.gl.viewport) {
      nvInstance.gl.viewport(0, 0, width, height);
    }
    nvInstance?.drawScene?.();
  }, []);

  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    ensureCanvasSize();
    const resizeObserver =
      typeof window !== 'undefined' && 'ResizeObserver' in window
        ? new ResizeObserver(() => ensureCanvasSize())
        : null;
    const parent = canvas.parentElement;
    if (resizeObserver && parent) {
      resizeObserver.observe(parent);
    }
    const handleContextLost = (event: Event) => {
      event.preventDefault();
    };
    const handleContextRestored = () => {
      requestAnimationFrame(() => ensureCanvasSize());
    };
    canvas.addEventListener('webglcontextlost', handleContextLost);
    canvas.addEventListener('webglcontextrestored', handleContextRestored);
    return () => {
      resizeObserver?.disconnect();
      canvas.removeEventListener('webglcontextlost', handleContextLost);
      canvas.removeEventListener('webglcontextrestored', handleContextRestored);
    };
  }, [ensureCanvasSize]);

  const overlayDefaults = useMemo(() => cfg?.overlays?.[0], [cfg]);
  const thresholdMin = overlayDefaults?.min ?? 0;
  const thresholdMax =
    overlayDefaults?.max ??
    (overlayDefaults?.threshold
      ? Math.max(overlayDefaults.threshold * 2, thresholdMin + 4)
      : thresholdMin + 8);

  useEffect(() => {
    if (externalConfig) {
      setCfg(applyOverlayPreference(externalConfig));
      setIsLoading(false);
      setLoadError(null);
      return;
    }

    if (!jobId) {
      setCfg(null);
      setIsLoading(false);
      return;
    }

    let cancelled = false;
    setIsLoading(true);
    setLoadError(null);
    const params = new URLSearchParams({ job_id: jobId });
    fetch(resolveKgVizUrl('/config', params))
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`Failed to load viewer config (${response.status})`);
        }
        return response.json();
      })
      .then((data) => {
        if (cancelled) return;
        setCfg(applyOverlayPreference(data as VizConfig));
      })
      .catch((err) => {
        if (cancelled) return;
        console.error('Failed to load viz config:', err);
        setCfg(null);
        setLoadError(err instanceof Error ? err.message : 'Failed to load viewer configuration.');
      })
      .finally(() => {
        if (cancelled) return;
        setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [applyOverlayPreference, externalConfig, jobId, retryNonce]);

  useEffect(() => {
    if (!cfg) {
      setThreshold([0]);
      setOpacity([1]);
      return;
    }
    const overlay = cfg.overlays?.[0];
    setThreshold([overlay?.threshold ?? 0]);
    setOpacity([overlay?.opacity ?? 1]);
  }, [cfg]);

  useEffect(() => {
    currentViewRef.current = currentView;
  }, [currentView]);

  const applyView = (nvInstance: any, view: ViewOption) => {
    switch (view) {
      case 'axial':
        nvInstance.setSliceType(nvInstance.sliceTypeAxial);
        break;
      case 'coronal':
        nvInstance.setSliceType(nvInstance.sliceTypeCoronal);
        break;
      case 'sagittal':
        nvInstance.setSliceType(nvInstance.sliceTypeSagittal);
        break;
      case 'mosaic':
        nvInstance.setSliceType(nvInstance.sliceTypeMultiplanar);
        break;
      case '3d':
      default:
        nvInstance.setSliceType(nvInstance.sliceTypeRender);
        break;
    }
  };

  const getOverlayIndex = () => {
    const nv = niivueRef.current;
    if (!nv || !cfg?.overlays?.length) return -1;
    // By construction base volume is first volume
    return nv.volumes.length > 1 ? 1 : -1;
  };

  // Initialize Niivue
  useEffect(() => {
    if (!cfg || !canvasRef.current) return;

    setNiivueReady(false);
    setIsLoading(true);
    setLoadError(null);

    const nv = new Niivue({
      dragAndDropEnabled: false,
      isResizeCanvas: false,
      trustCalMinMax: true,
      show3Dcrosshair: true,
      // Niivue 0.62.x uses  (not )
      isColorbar: true,
      backColor: [0, 0, 0, 1],
      crosshairColor: [1, 0, 0, 1],
    });

    niivueRef.current = nv;
    nv.attachToCanvas(canvasRef.current);
    if (typeof window !== 'undefined') {
      (window as any).__NIIVUE_LAST_INSTANCE = nv;
    }

    ensureCanvasSize();

    // Observe the canvas container to keep GL viewport in sync
    let ro: ResizeObserver | null = null;
    try {
      const target = canvasRef.current?.parentElement ?? canvasRef.current ?? undefined;
      if (typeof window !== 'undefined' && 'ResizeObserver' in window && target) {
        ro = new ResizeObserver(() => ensureCanvasSize());
        ro.observe(target);
      }
    } catch {}

    // Load base volume
    const attemptLoad = async (baseUrl?: string) => {
      if (process.env.NODE_ENV !== 'production') {
        console.debug('Brain3D: attemptLoad called', { baseUrl });
      }

      // Clear existing volumes
      if (nv.removeVolume && Array.isArray(nv.volumes) && nv.volumes.length) {
        for (let i = nv.volumes.length - 1; i >= 0; i--) {
          nv.removeVolume(nv.volumes[i]);
        }
      } else if (Array.isArray(nv.volumes)) {
        nv.volumes.length = 0;
      }
      // If we have a base volume URL, fetch and load it first using ArrayBuffer
      if (baseUrl) {
        if (process.env.NODE_ENV !== 'production') {
          console.debug('Brain3D: fetching base volume', { baseUrl });
        }
        const response = await fetch(baseUrl);
        if (!response.ok) {
          throw new Error(`Failed to fetch base volume: ${response.status} ${response.statusText}`);
        }
        const arrayBuffer = await response.arrayBuffer();
        const baseName = resolveVolumeName(baseUrl, response);

        if (process.env.NODE_ENV !== 'production') {
          console.debug('Brain3D: loading base from ArrayBuffer', {
            baseName,
            byteLength: arrayBuffer.byteLength
          });
        }
       await nv.loadFromArrayBuffer(arrayBuffer, baseName);
       ensureCanvasSize();

        if (process.env.NODE_ENV !== 'production') {
          console.debug('Brain3D: base load complete', {
            volumes: nv.volumes?.length ?? 0,
          });
        }

        const baseVolume = nv.volumes?.[0];
        if (baseVolume && !baseVolume.toRAS) {
          baseVolume.toRAS = mat4.create();
        }
      }

      // Now load overlays if any
      const overlays = cfg.overlays || [];
      if (overlays.length > 0) {
        if (process.env.NODE_ENV !== 'production') {
          console.debug('Brain3D: loading overlays', { count: overlays.length });
        }
        for (const overlay of overlays) {
          if (!overlay?.url) {
            continue;
          }

          let overlayName = overlay.name || resolveVolumeName(overlay.url);

          if (typeof (nv as any).addVolumeFromUrl === 'function') {
            await (nv as any).addVolumeFromUrl({
              url: overlay.url,
              name: overlayName,
            });
          } else {
            const overlayResponse = await fetch(overlay.url);
            if (!overlayResponse.ok) {
              throw new Error(`Failed to fetch overlay ${overlay.url}: ${overlayResponse.status} ${overlayResponse.statusText}`);
            }
            const overlayBuffer = await overlayResponse.arrayBuffer();
            await nv.loadFromArrayBuffer(overlayBuffer, overlayName);
          }

          const overlayIndex = nv.volumes?.length ? nv.volumes.length - 1 : -1;
          if (overlayIndex >= 0) {
            const volume = nv.volumes[overlayIndex];
            if (volume && !volume.toRAS) {
              volume.toRAS = mat4.create();
            }

            const calMin = overlay.min ?? 0;
            const calMax = overlay.max ?? Math.max((overlay.threshold ?? 0) * 2, calMin + 4);
            const opacityValue = overlay.opacity ?? 1.0;

            if (volume) {
              if (overlay.colormap) {
                volume.colormap = overlay.colormap;
              }
              volume.opacity = opacityValue;
              volume.cal_min = calMin;
              volume.cal_max = calMax;
              if (overlay.threshold != null) {
                (volume as any).cal_min_threshold = overlay.threshold;
              }
            }

            if (typeof nv.updateGLVolume === 'function') {
              nv.updateGLVolume();
            }

            ensureCanvasSize();

            if (process.env.NODE_ENV !== 'production') {
              console.debug('Brain3D: overlay appended', {
                index: overlayIndex,
                totalVolumes: nv.volumes?.length ?? 0,
              });
            }
          }
        }
      }

      if (typeof window !== 'undefined') {
        (window as any).__BRAIN3D_LAST_LOAD = {
          baseUrl,
          overlayCount: overlays.length,
          overlays: nv.volumes?.slice(1).map((v: any) => v?.name) ?? [],
          background: nv.volumes?.[0]?.name ?? null,
        };
      }
    };

    const loadWithFallbacks = async () => {
      const attemptedBases = new Set<string | undefined>();
      const queue: Array<string | undefined> = [];

      if (cfg.baseVolume) queue.push(cfg.baseVolume);
      const fallbackCandidate =
        cfg.baseVolumeFallback ??
        resolveKgVizUrl('/base', new URLSearchParams({ template: 'mni152' }));
      if (fallbackCandidate && fallbackCandidate !== cfg.baseVolume) {
        queue.push(fallbackCandidate);
      }
      // Final attempt: overlays only (no base volume)
      queue.push(undefined);

      for (const baseUrl of queue) {
        if (attemptedBases.has(baseUrl)) continue;
        attemptedBases.add(baseUrl);
        try {
          await attemptLoad(baseUrl);
          const layersToGuard = nv.volumes ?? [];
          layersToGuard.forEach(layer => {
            if (layer && !layer.toRAS) {
              layer.toRAS = mat4.create();
            }
          });

          applyView(nv, currentViewRef.current);
          if (typeof nv.drawScene === 'function') {
            nv.drawScene();
          }
          return;
        } catch (error) {
          console.warn(
            `Failed to load brain visualization${baseUrl ? ` from ${baseUrl}` : ''
            }:`,
            error,
            error instanceof Error ? error.stack : undefined,
          );
          if (typeof window !== 'undefined') {
            const errorHistory = (window as any).__BRAIN3D_ERROR_HISTORY ?? [];
            const errorPayload = {
              baseUrl,
              message: error instanceof Error ? error.message : String(error),
              stack: error instanceof Error ? error.stack : undefined,
            };
            errorHistory.push(errorPayload);
            (window as any).__BRAIN3D_LAST_ERROR = errorPayload;
            (window as any).__BRAIN3D_ERROR_HISTORY = errorHistory;
          }
        }
      }
      console.error('Unable to load brain visualization volumes after retries.');
      throw new Error('Failed to load any brain volumes');
    };

    loadWithFallbacks()
      .then(() => {
        setNiivueReady(true);
      })
      .catch((error) => {
        const message =
          error instanceof Error ? error.message : 'Failed to load any brain volumes.';
        setLoadError(message);
      })
      .finally(() => {
        setIsLoading(false);
      });

    // Set up interaction callbacks
    if (cfg.interaction?.allowPick) {
      nv.onLocationChange = (location: any) => {
        setCoordinates({
          x: Math.round(location.mm[0]),
          y: Math.round(location.mm[1]),
          z: Math.round(location.mm[2])
        });
      };
    }

    return () => {
      // Cleanup Niivue instance
      try {
        // Disconnect observer first
        try { ro?.disconnect(); } catch {}
        if (niivueRef.current) {
          // Dispose method if it exists, otherwise just clear the reference
          if (typeof niivueRef.current.dispose === 'function') {
            niivueRef.current.dispose();
          }
          niivueRef.current = null;
        }
      } catch (error) {
        console.error('Error cleaning up Niivue instance:', error);
      }
      setNiivueReady(false);
    };
  }, [cfg, ensureCanvasSize, retryNonce]);

  // Handle focusPoint changes - jump crosshair to coordinate
  useEffect(() => {
    if (!focusPoint || !niivueReady || !niivueRef.current) return;

    const nv = niivueRef.current;
    try {
      // Set crosshair to MNI coordinates [x, y, z]
      if (typeof nv.setSliceMM === 'function') {
        nv.setSliceMM([focusPoint.x, focusPoint.y, focusPoint.z]);
      }
    } catch (error) {
      console.warn('Failed to set focus point:', error);
    }
  }, [focusPoint, niivueReady]);

  // NOTE: Peak markers are currently visualized via crosshair jumps handled
  // by the parent visualization controller (focusPoint). Niivue does not expose a stable public API
  // for custom point sprites, and monkey‑patching drawScene proved brittle.
  // When Niivue adds native marker support, we can render peaks here by
  // adding a mesh layer instead of patching the render loop.

  const applyThresholdToNiivue = useCallback(
    (thresholdValue: number) => {
      const nv = niivueRef.current;
      if (!nv) return;
      const overlayIndex = getOverlayIndex();
      if (overlayIndex < 0) return;

      const overlayVolume = nv.volumes[overlayIndex];
      if (!overlayVolume) return;

      const min = overlayVolume.cal_min ?? thresholdMin;
      const max =
        overlayVolume.cal_max ??
        thresholdMax ??
        Math.max(thresholdValue * 2 || 4, thresholdMin + 4);

      if (typeof nv.setCalMinMax === 'function') {
        nv.setCalMinMax(overlayIndex, min, max, thresholdValue);
      } else {
        overlayVolume.cal_min = min;
        overlayVolume.cal_max = max;
        (overlayVolume as any).cal_min_threshold = thresholdValue;
        nv.updateGLVolume();
      }
      if (typeof nv.drawScene === 'function') {
        nv.drawScene();
      }
    },
    [cfg],
  );

  const updateThreshold = (value: number[]) => {
    const [raw] = value;
    const minAllowed = thresholdMin;
    const maxAllowed = thresholdMax;
    const clamped = Math.min(Math.max(raw, minAllowed), maxAllowed);
    setThreshold([clamped]);
    applyThresholdToNiivue(clamped);
  };

  const applyOpacityToNiivue = useCallback((value: number) => {
    const nv = niivueRef.current;
    if (!nv) return;
    const overlayIndex = getOverlayIndex();
    if (overlayIndex < 0) return;

    if (typeof nv.setOpacity === 'function') {
      nv.setOpacity(overlayIndex, value);
    } else if (nv.volumes?.[overlayIndex]) {
      nv.volumes[overlayIndex].opacity = value;
    }
    if (typeof nv.updateGLVolume === 'function') {
      nv.updateGLVolume();
    }
    if (typeof nv.drawScene === 'function') {
      nv.drawScene();
    }
  }, []);

  const updateOpacity = (value: number[]) => {
    const [raw] = value;
    const clamped = Math.min(Math.max(raw, 0), 1);
    setOpacity([clamped]);
    applyOpacityToNiivue(clamped);
  };

  useEffect(() => {
    if (!niivueReady) return;
    applyThresholdToNiivue(threshold[0]);
  }, [niivueReady, threshold, applyThresholdToNiivue]);

  useEffect(() => {
    if (!niivueReady) return;
    applyOpacityToNiivue(opacity[0]);
  }, [niivueReady, opacity, applyOpacityToNiivue]);

  // View controls
  const setView = (view: ViewOption) => {
    setCurrentView(view);
    if (niivueRef.current) {
      applyView(niivueRef.current, view);
    }
  };

  // Reset view
  const resetView = () => {
    if (niivueRef.current) {
      applyView(niivueRef.current, '3d');
      niivueRef.current.scene.pan2Dxyzmm = [0, 0, 0, 1];
      niivueRef.current.updateGLVolume();
    }
    setCurrentView('3d');
  };

  // Download snapshot
  const downloadSnapshot = () => {
    if (!canvasRef.current) return;
    
    const link = document.createElement('a');
    link.href = canvasRef.current.toDataURL('image/png');
    link.download = `brain-${resolvedJobId}-${Date.now()}.png`;
    link.click();
  };

  const retryLoad = () => {
    setLoadError(null);
    setRetryNonce((value) => value + 1);
  };

  if (isLoading) {
    return (
      <Card className="p-6">
        <div className="animate-pulse">
          <div className="h-96 bg-gray-200 rounded-lg"></div>
          <div className="mt-4 space-y-2">
            <div className="h-4 bg-gray-200 rounded w-1/4"></div>
            <div className="h-4 bg-gray-200 rounded w-1/2"></div>
          </div>
        </div>
      </Card>
    );
  }

  if (!cfg) {
    return (
      <Card className="p-6" data-testid="brain3d-error">
        <div className="space-y-4 text-center">
          <div className="text-gray-900 font-medium">Failed to load the brain map viewer</div>
          <div className="text-sm text-gray-500">
            {loadError || 'Failed to load visualization configuration.'}
          </div>
          <div className="flex items-center justify-center gap-2">
            <Button variant="outline" size="sm" onClick={retryLoad} data-testid="brain3d-retry">
              Retry viewer
            </Button>
          </div>
        </div>
      </Card>
    );
  }

  if (loadError) {
    return (
      <Card className="p-6" data-testid="brain3d-error">
        <div className="space-y-4 text-center">
          <div className="text-gray-900 font-medium">Unable to render this brain map</div>
          <div className="text-sm text-gray-500">{loadError}</div>
          <div className="flex items-center justify-center gap-2">
            <Button variant="outline" size="sm" onClick={retryLoad} data-testid="brain3d-retry">
              Retry viewer
            </Button>
          </div>
        </div>
      </Card>
    );
  }

  const showFullscreenToggle = mode === 'full';

  const headerTitle =
    mode === 'compact' ? '3D Brain View' : '3D Brain Visualization';

  const headerContent = (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Brain className={mode === 'compact' ? 'h-4 w-4' : 'h-5 w-5'} />
          <h3 className={mode === 'compact' ? 'text-sm font-semibold' : 'text-lg font-semibold'}>
            {headerTitle}
          </h3>
          {cfg.metadata && mode !== 'compact' && (
            <div className="flex gap-2 text-sm text-gray-500">
              {cfg.metadata.subject && <span>Subject: {cfg.metadata.subject}</span>}
              {cfg.metadata.task && <span>Task: {cfg.metadata.task}</span>}
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" variant={currentView === 'axial' ? 'default' : 'outline'} onClick={() => setView('axial')}>
            Axial
          </Button>
          <Button size="sm" variant={currentView === 'coronal' ? 'default' : 'outline'} onClick={() => setView('coronal')}>
            Coronal
          </Button>
          <Button size="sm" variant={currentView === 'sagittal' ? 'default' : 'outline'} onClick={() => setView('sagittal')}>
            Sagittal
          </Button>
          <Button size="sm" variant={currentView === '3d' ? 'default' : 'outline'} onClick={() => setView('3d')}>
            3D
          </Button>
          <Button size="sm" variant={currentView === 'mosaic' ? 'default' : 'outline'} onClick={() => setView('mosaic')}>
            <Grid3X3 className="h-4 w-4" />
          </Button>

          <div className="h-6 w-px bg-gray-300" />

          <Button size="sm" variant="outline" onClick={resetView}>
            <RotateCw className="h-4 w-4" />
          </Button>
          <Button size="sm" variant="outline" onClick={downloadSnapshot}>
            <Download className="h-4 w-4" />
          </Button>
          {showFullscreenToggle && (
            <Button size="sm" variant="outline" onClick={() => setIsFullscreen(!isFullscreen)}>
              {isFullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
            </Button>
          )}
        </div>
      </div>

      {cfg.overlays && cfg.overlays.length > 0 && (
        <div className={`mt-4 flex flex-wrap items-center gap-4 ${mode === 'compact' ? 'text-xs' : ''}`}>
          <div className="flex items-center gap-2">
            <Layers className="h-4 w-4" />
            <span>Threshold:</span>
            <Slider
              value={threshold}
              onValueChange={updateThreshold}
              min={thresholdMin}
              max={thresholdMax}
              step={Math.max((thresholdMax - thresholdMin) / 100, 0.05)}
              className={mode === 'compact' ? 'w-24' : 'w-32'}
            />
            <span className="font-mono">{threshold[0].toFixed(2)}</span>
          </div>

          <div className="flex items-center gap-2">
            <span>Opacity:</span>
            <Slider
              value={opacity}
              onValueChange={updateOpacity}
              min={0}
              max={1}
              step={0.05}
              className={mode === 'compact' ? 'w-24' : 'w-32'}
            />
            <span className="font-mono">{(opacity[0] * 100).toFixed(0)}%</span>
          </div>
        </div>
      )}
    </>
  );

  const canvasSection = (
    <div className="relative bg-black">
      <canvas
        ref={canvasRef}
        className="w-full h-full"
        style={{
          height:
            showFullscreenToggle && isFullscreen
              ? 'calc(100vh - 140px)'
              : height,
        }}
      />

      {cfg.interaction?.allowPick && (
        <div className="absolute bottom-4 left-4 rounded bg-black/80 p-2 font-mono text-sm text-white">
          MNI: [{coordinates.x}, {coordinates.y}, {coordinates.z}]
        </div>
      )}
    </div>
  );

  return (
    mode === 'compact' ? (
      <div className="rounded-xl border bg-background shadow-sm">
        <div className="border-b p-3 text-sm">
          {headerContent}
        </div>
        {canvasSection}
      </div>
    ) : (
      <Card className={`${isFullscreen ? 'fixed inset-0 z-50' : ''}`}>
        <div className="border-b p-4">
          {headerContent}
        </div>
        {canvasSection}
      </Card>
    )
  );
}

// Export type aliases for external components
export type Brain3DConfig = VizConfig;
