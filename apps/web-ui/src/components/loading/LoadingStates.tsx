/**
 * Enhanced loading states with skeleton loaders, progress indicators,
 * timeout warnings, and cancel operations functionality.
 */

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { 
  Loader2, 
  Clock, 
  X, 
  AlertTriangle, 
  CheckCircle, 
  RefreshCw,
  Pause,
  Play,
  Square
} from 'lucide-react';

interface LoadingState {
  isLoading: boolean;
  progress?: number;
  message?: string;
  stage?: string;
  timeoutWarning?: boolean;
  error?: string;
  canCancel?: boolean;
  estimatedTimeRemaining?: number;
}

interface LoadingStatesProps {
  state: LoadingState;
  onCancel?: () => void;
  onRetry?: () => void;
  onPause?: () => void;
  onResume?: () => void;
  timeoutThreshold?: number;
  showSkeletonLoader?: boolean;
  skeletonType?: 'cards' | 'table' | 'chart' | 'text' | 'custom';
  customSkeleton?: React.ReactNode;
  className?: string;
}

// Skeleton components
function SkeletonCard({ count = 3 }: { count?: number }) {
  return (
    <div className="space-y-4">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="bg-white rounded-lg shadow p-6">
          <div className="animate-pulse">
            <div className="h-4 bg-gray-300 rounded w-3/4 mb-3"></div>
            <div className="h-3 bg-gray-300 rounded w-1/2 mb-4"></div>
            <div className="space-y-2">
              <div className="h-3 bg-gray-300 rounded w-full"></div>
              <div className="h-3 bg-gray-300 rounded w-5/6"></div>
              <div className="h-3 bg-gray-300 rounded w-4/6"></div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function SkeletonTable({ rows = 5, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div className="bg-white rounded-lg shadow overflow-hidden">
      <div className="animate-pulse">
        {/* Header */}
        <div className="bg-gray-50 px-6 py-3 border-b border-gray-200">
          <div className="flex space-x-4">
            {Array.from({ length: cols }).map((_, i) => (
              <div key={i} className="h-4 bg-gray-300 rounded flex-1"></div>
            ))}
          </div>
        </div>
        
        {/* Rows */}
        <div className="divide-y divide-gray-200">
          {Array.from({ length: rows }).map((_, i) => (
            <div key={i} className="px-6 py-4">
              <div className="flex space-x-4">
                {Array.from({ length: cols }).map((_, j) => (
                  <div key={j} className="h-4 bg-gray-300 rounded flex-1"></div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function SkeletonChart() {
  return (
    <div className="bg-white rounded-lg shadow p-6">
      <div className="animate-pulse">
        <div className="h-6 bg-gray-300 rounded w-1/3 mb-4"></div>
        <div className="h-64 bg-gray-300 rounded mb-4"></div>
        <div className="flex justify-center space-x-4">
          <div className="h-4 bg-gray-300 rounded w-20"></div>
          <div className="h-4 bg-gray-300 rounded w-20"></div>
          <div className="h-4 bg-gray-300 rounded w-20"></div>
        </div>
      </div>
    </div>
  );
}

function SkeletonText({ lines = 5 }: { lines?: number }) {
  return (
    <div className="bg-white rounded-lg shadow p-6">
      <div className="animate-pulse space-y-3">
        {Array.from({ length: lines }).map((_, i) => (
          <div
            key={i}
            className={`h-4 bg-gray-300 rounded ${
              i === lines - 1 ? 'w-3/4' : 'w-full'
            }`}
          ></div>
        ))}
      </div>
    </div>
  );
}

// Progress indicator component
function ProgressIndicator({ 
  progress, 
  message, 
  stage, 
  estimatedTimeRemaining 
}: { 
  progress?: number; 
  message?: string; 
  stage?: string;
  estimatedTimeRemaining?: number;
}) {
  const formatTime = (seconds: number) => {
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = Math.round(seconds % 60);
    return `${minutes}m ${remainingSeconds}s`;
  };

  return (
    <div className="w-full">
      {/* Progress bar */}
      {progress !== undefined && (
        <div className="mb-3">
          <div className="flex justify-between text-sm text-gray-600 mb-1">
            <span>{stage || 'Processing'}</span>
            <span>{Math.round(progress)}%</span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-2">
            <div
              className="bg-blue-600 h-2 rounded-full transition-all duration-300 ease-out"
              style={{ width: `${Math.min(progress, 100)}%` }}
            ></div>
          </div>
        </div>
      )}

      {/* Message */}
      {message && (
        <p className="text-sm text-gray-600 mb-2">{message}</p>
      )}

      {/* Estimated time remaining */}
      {estimatedTimeRemaining && (
        <div className="flex items-center text-xs text-gray-500">
          <Clock className="h-3 w-3 mr-1" />
          <span>About {formatTime(estimatedTimeRemaining)} remaining</span>
        </div>
      )}
    </div>
  );
}

// Main loading component
export function LoadingStates({
  state,
  onCancel,
  onRetry,
  onPause,
  onResume,
  timeoutThreshold = 30000,
  showSkeletonLoader = true,
  skeletonType = 'cards',
  customSkeleton,
  className = ''
}: LoadingStatesProps) {
  const [startTime] = useState(Date.now());
  const [elapsedTime, setElapsedTime] = useState(0);
  const [isPaused, setIsPaused] = useState(false);

  // Update elapsed time
  useEffect(() => {
    if (!state.isLoading) return;

    const interval = setInterval(() => {
      setElapsedTime(Date.now() - startTime);
    }, 1000);

    return () => clearInterval(interval);
  }, [state.isLoading, startTime]);

  const handlePause = useCallback(() => {
    setIsPaused(true);
    onPause?.();
  }, [onPause]);

  const handleResume = useCallback(() => {
    setIsPaused(false);
    onResume?.();
  }, [onResume]);

  const handleCancel = useCallback(() => {
    onCancel?.();
  }, [onCancel]);

  const shouldShowTimeout = useMemo(() => {
    return state.timeoutWarning || (elapsedTime > timeoutThreshold);
  }, [state.timeoutWarning, elapsedTime, timeoutThreshold]);

  // Render skeleton loader
  const renderSkeleton = () => {
    if (customSkeleton) return customSkeleton;

    switch (skeletonType) {
      case 'table':
        return <SkeletonTable />;
      case 'chart':
        return <SkeletonChart />;
      case 'text':
        return <SkeletonText />;
      case 'cards':
      default:
        return <SkeletonCard />;
    }
  };

  if (state.error) {
    return (
      <div className={`flex flex-col items-center justify-center p-8 ${className}`}>
        <div className="bg-red-50 border border-red-200 rounded-lg p-6 max-w-md w-full">
          <div className="flex items-center mb-4">
            <AlertTriangle className="h-6 w-6 text-red-600 mr-3" />
            <h3 className="text-lg font-semibold text-red-900">Error</h3>
          </div>
          
          <p className="text-red-700 mb-4">{state.error}</p>
          
          <div className="flex gap-3">
            {onRetry && (
              <button
                onClick={onRetry}
                className="inline-flex items-center px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2"
              >
                <RefreshCw className="h-4 w-4 mr-2" />
                Try Again
              </button>
            )}
            
            {onCancel && (
              <button
                onClick={onCancel}
                className="px-4 py-2 bg-gray-300 text-gray-700 rounded-md hover:bg-gray-400 focus:outline-none focus:ring-2 focus:ring-gray-500 focus:ring-offset-2"
              >
                Cancel
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }

  if (!state.isLoading) {
    return null;
  }

  return (
    <div className={`relative ${className}`}>
      {/* Loading overlay with controls */}
      <div className="bg-white rounded-lg shadow-lg p-6 mb-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center">
            <Loader2 className={`h-6 w-6 text-blue-600 mr-3 ${isPaused ? '' : 'animate-spin'}`} />
            <h3 className="text-lg font-semibold text-gray-900">
              {isPaused ? 'Paused' : 'Processing'}
            </h3>
          </div>
          
          {/* Control buttons */}
          <div className="flex items-center space-x-2">
            {onPause && onResume && (
              <button
                onClick={isPaused ? handleResume : handlePause}
                className="p-2 text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded-md"
                title={isPaused ? 'Resume' : 'Pause'}
              >
                {isPaused ? (
                  <Play className="h-4 w-4" />
                ) : (
                  <Pause className="h-4 w-4" />
                )}
              </button>
            )}
            
            {state.canCancel && onCancel && (
              <button
                onClick={handleCancel}
                className="p-2 text-red-600 hover:text-red-800 hover:bg-red-100 rounded-md"
                title="Cancel"
              >
                <Square className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>

        {/* Progress indicator */}
        <ProgressIndicator
          progress={state.progress}
          message={state.message}
          stage={state.stage}
          estimatedTimeRemaining={state.estimatedTimeRemaining}
        />

        {/* Timeout warning */}
        {shouldShowTimeout && (
          <div className="mt-4 p-3 bg-yellow-50 border border-yellow-200 rounded-md">
            <div className="flex items-start">
              <AlertTriangle className="h-5 w-5 text-yellow-600 mr-2 mt-0.5" />
              <div className="flex-1">
                <h4 className="text-sm font-medium text-yellow-800">
                  Taking longer than expected
                </h4>
                <p className="text-sm text-yellow-700 mt-1">
                  This operation has been running for {Math.round(elapsedTime / 1000)} seconds. 
                  You can continue waiting or cancel the operation.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Elapsed time */}
        <div className="mt-3 flex items-center text-xs text-gray-500">
          <Clock className="h-3 w-3 mr-1" />
          <span>Elapsed: {Math.round(elapsedTime / 1000)}s</span>
        </div>
      </div>

      {/* Skeleton loader */}
      {showSkeletonLoader && (
        <div className="opacity-50 pointer-events-none">
          {renderSkeleton()}
        </div>
      )}
    </div>
  );
}

// Individual skeleton components for export
export { SkeletonCard, SkeletonTable, SkeletonChart, SkeletonText };

// Loading spinner component
export function LoadingSpinner({ 
  size = 'md', 
  color = 'blue',
  className = '' 
}: { 
  size?: 'sm' | 'md' | 'lg';
  color?: 'blue' | 'gray' | 'green' | 'red';
  className?: string;
}) {
  const sizeClasses = {
    sm: 'h-4 w-4',
    md: 'h-6 w-6',
    lg: 'h-8 w-8'
  };

  const colorClasses = {
    blue: 'text-blue-600',
    gray: 'text-gray-600',
    green: 'text-green-600',
    red: 'text-red-600'
  };

  return (
    <Loader2 className={`animate-spin ${sizeClasses[size]} ${colorClasses[color]} ${className}`} />
  );
}

// Simple loading overlay
export function LoadingOverlay({ 
  message = 'Loading...', 
  show = true,
  className = ''
}: { 
  message?: string;
  show?: boolean;
  className?: string;
}) {
  if (!show) return null;

  return (
    <div className={`fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 ${className}`}>
      <div className="bg-white rounded-lg p-6 flex items-center space-x-3">
        <LoadingSpinner />
        <span className="text-gray-900">{message}</span>
      </div>
    </div>
  );
}

// Button with loading state
export function LoadingButton({
  children,
  loading = false,
  disabled = false,
  onClick,
  className = '',
  ...props
}: {
  children: React.ReactNode;
  loading?: boolean;
  disabled?: boolean;
  onClick?: () => void;
  className?: string;
  [key: string]: any;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      className={`inline-flex items-center px-4 py-2 rounded-md font-medium focus:outline-none focus:ring-2 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed ${className}`}
      {...props}
    >
      {loading && <LoadingSpinner size="sm" className="mr-2" />}
      {children}
    </button>
  );
}

// Hook for managing loading states
export function useLoadingState(initialState: Partial<LoadingState> = {}) {
  const [state, setState] = useState<LoadingState>({
    isLoading: false,
    ...initialState
  });

  const setLoading = useCallback((loading: boolean) => {
    setState(prev => ({ ...prev, isLoading: loading }));
  }, []);

  const setProgress = useCallback((progress: number) => {
    setState(prev => ({ ...prev, progress }));
  }, []);

  const setMessage = useCallback((message: string) => {
    setState(prev => ({ ...prev, message }));
  }, []);

  const setStage = useCallback((stage: string) => {
    setState(prev => ({ ...prev, stage }));
  }, []);

  const setError = useCallback((error: string | null) => {
    setState(prev => ({ 
      ...prev, 
      error: error || undefined,
      isLoading: error ? false : prev.isLoading
    }));
  }, []);

  const reset = useCallback(() => {
    setState({ isLoading: false });
  }, []);

  return {
    state,
    setState,
    setLoading,
    setProgress,
    setMessage,
    setStage,
    setError,
    reset
  };
}

export default LoadingStates;