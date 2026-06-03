/**
 * Image optimization utilities for Brain Researcher UI
 * Handles Next.js Image component optimization, lazy loading, and progressive enhancement
 */

import Image, { ImageProps } from 'next/image';
import { ComponentProps, useState, useEffect, CSSProperties } from 'react';

// Types
export interface OptimizedImageProps extends Omit<ImageProps, 'src'> {
  src: string;
  alt: string;
  fallbackSrc?: string;
  placeholderColor?: string;
  progressive?: boolean;
  lazy?: boolean;
  quality?: number;
  formats?: ('webp' | 'avif' | 'jpg' | 'png')[];
  responsive?: boolean;
  blur?: boolean;
  onLoadComplete?: () => void;
  onError?: () => void;
}

export interface ImageOptimizerConfig {
  domains: string[];
  deviceSizes: number[];
  imageSizes: number[];
  formats: string[];
  minimumCacheTTL: number;
  dangerouslyAllowSVG: boolean;
}

// Image format priorities (best to worst)
const FORMAT_PRIORITY: Record<string, number> = {
  avif: 1,
  webp: 2,
  jpg: 3,
  jpeg: 3,
  png: 4,
  gif: 5,
  svg: 6
};

// Device size breakpoints for responsive images
export const DEVICE_SIZES = [640, 750, 828, 1080, 1200, 1920, 2048, 3840];

// Standard image sizes for different use cases
export const IMAGE_SIZES = {
  thumbnail: 150,
  small: 320,
  medium: 640,
  large: 1024,
  xlarge: 1920,
  icon: 64,
  avatar: 128,
  hero: 1920
};

// Generate blur placeholder data URL
function generateBlurPlaceholder(
  width: number,
  height: number,
  color: string = '#e5e7eb'
): string {
  const svg = `
    <svg width="${width}" height="${height}" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="g">
          <stop stop-color="${color}" offset="0%"/>
          <stop stop-color="${adjustBrightness(color, -10)}" offset="100%"/>
        </linearGradient>
      </defs>
      <rect width="100%" height="100%" fill="url(#g)"/>
    </svg>
  `;
  
  const base64 = Buffer.from(svg).toString('base64');
  return `data:image/svg+xml;base64,${base64}`;
}

// Adjust color brightness
function adjustBrightness(color: string, percent: number): string {
  const num = parseInt(color.replace('#', ''), 16);
  const amt = Math.round(2.55 * percent);
  const R = (num >> 16) + amt;
  const G = (num >> 8 & 0x00FF) + amt;
  const B = (num & 0x0000FF) + amt;
  
  return '#' + (0x1000000 + (R < 255 ? R < 1 ? 0 : R : 255) * 0x10000 +
    (G < 255 ? G < 1 ? 0 : G : 255) * 0x100 +
    (B < 255 ? B < 1 ? 0 : B : 255))
    .toString(16)
    .slice(1);
}

// Generate responsive sizes string based on container width
export function generateResponsiveSizes(
  breakpoints: Record<string, number> = {}
): string {
  const defaultBreakpoints = {
    sm: 100,  // Small screens: full width
    md: 50,   // Medium screens: half width
    lg: 33,   // Large screens: third width
    xl: 25,   // Extra large: quarter width
    ...breakpoints
  };

  return Object.entries(defaultBreakpoints)
    .map(([breakpoint, width]) => {
      if (breakpoint === 'sm') {
        return `${width}vw`;
      }
      return `(min-width: ${DEVICE_SIZES.find(size => size >= width * 10) || 640}px) ${width}vw`;
    })
    .join(', ');
}

// Determine optimal image format based on browser support
export function getOptimalFormat(
  originalSrc: string,
  supportedFormats: string[] = []
): string {
  if (typeof window === 'undefined') return originalSrc;

  const canvas = document.createElement('canvas');
  canvas.width = 1;
  canvas.height = 1;

  // Check AVIF support
  const supportsAVIF = canvas.toDataURL('image/avif').indexOf('data:image/avif') === 0;
  
  // Check WebP support
  const supportsWebP = canvas.toDataURL('image/webp').indexOf('data:image/webp') === 0;

  const url = new URL(originalSrc, window.location.origin);
  const extension = url.pathname.split('.').pop()?.toLowerCase() || '';

  // Priority order: AVIF > WebP > Original
  if (supportsAVIF && !['gif', 'svg'].includes(extension)) {
    url.searchParams.set('format', 'avif');
    return url.toString();
  }
  
  if (supportsWebP && !['gif', 'svg'].includes(extension)) {
    url.searchParams.set('format', 'webp');
    return url.toString();
  }

  return originalSrc;
}

// Add image optimization query parameters
export function addImageOptimizations(
  src: string,
  options: {
    width?: number;
    height?: number;
    quality?: number;
    format?: string;
    fit?: 'cover' | 'contain' | 'fill' | 'inside' | 'outside';
    blur?: number;
  } = {}
): string {
  if (typeof window === 'undefined') {
    return src;
  }

  const {
    width,
    height,
    quality = 85,
    format,
    fit = 'cover',
    blur
  } = options;

  try {
    const url = new URL(src, window.location.origin);
    
    if (width) url.searchParams.set('w', width.toString());
    if (height) url.searchParams.set('h', height.toString());
    if (quality < 100) url.searchParams.set('q', quality.toString());
    if (format) url.searchParams.set('format', format);
    if (fit !== 'cover') url.searchParams.set('fit', fit);
    if (blur) url.searchParams.set('blur', blur.toString());
    
    return url.toString();
  } catch {
    return src;
  }
}

// Enhanced OptimizedImage component
export function OptimizedImage({
  src,
  alt,
  fallbackSrc,
  placeholderColor = '#e5e7eb',
  progressive = true,
  lazy = true,
  quality = 85,
  formats = ['avif', 'webp'],
  responsive = true,
  blur = true,
  onLoadComplete,
  onError,
  className,
  style,
  width,
  height,
  sizes,
  priority = false,
  ...props
}: OptimizedImageProps) {
  const [imageError, setImageError] = useState(false);
  const [isLoaded, setIsLoaded] = useState(false);

  // Generate optimized src
  const optimizedSrc = getOptimalFormat(src, formats);
  const finalSrc = imageError && fallbackSrc ? fallbackSrc : optimizedSrc;

  // Generate blur placeholder if needed
  const blurDataURL = blur && width && height
    ? generateBlurPlaceholder(
        typeof width === 'number' ? width : 400,
        typeof height === 'number' ? height : 300,
        placeholderColor
      )
    : undefined;

  // Generate responsive sizes if not provided
  const responsiveSizes = responsive && !sizes
    ? generateResponsiveSizes()
    : sizes;

  const handleLoad = () => {
    setIsLoaded(true);
    onLoadComplete?.();
  };

  const handleError = () => {
    setImageError(true);
    onError?.();
  };

  const imageStyle: CSSProperties = {
    ...style,
    transition: progressive ? 'opacity 0.3s ease-in-out' : undefined,
    opacity: isLoaded ? 1 : 0.8
  };

  return (
    <Image
      src={finalSrc}
      alt={alt}
      width={width}
      height={height}
      quality={quality}
      sizes={responsiveSizes}
      priority={priority}
      placeholder={blurDataURL ? 'blur' : 'empty'}
      blurDataURL={blurDataURL}
      className={className}
      style={imageStyle}
      onLoad={handleLoad}
      onError={handleError}
      {...props}
    />
  );
}

// Brain image specific optimizations
export function BrainImage({
  src,
  alt,
  className,
  ...props
}: OptimizedImageProps) {
  return (
    <OptimizedImage
      src={src}
      alt={alt}
      className={`brain-image ${className || ''}`}
      quality={90} // Higher quality for scientific images
      formats={['webp', 'png']} // PNG fallback for precision
      blur={false} // No blur for scientific accuracy
      {...props}
    />
  );
}

// Chart/visualization image optimizations
export function ChartImage({
  src,
  alt,
  className,
  ...props
}: OptimizedImageProps) {
  return (
    <OptimizedImage
      src={src}
      alt={alt}
      className={`chart-image ${className || ''}`}
      quality={95} // High quality for charts
      formats={['webp', 'png']} // PNG fallback for text clarity
      blur={true}
      {...props}
    />
  );
}

// Avatar/profile image optimizations
export function AvatarImage({
  src,
  alt,
  size = IMAGE_SIZES.avatar,
  className,
  ...props
}: OptimizedImageProps & { size?: number }) {
  return (
    <OptimizedImage
      src={src}
      alt={alt}
      width={size}
      height={size}
      className={`avatar-image rounded-full ${className || ''}`}
      quality={80}
      formats={['avif', 'webp', 'jpg']}
      blur={true}
      {...props}
    />
  );
}

// Hero/banner image optimizations
export function HeroImage({
  src,
  alt,
  className,
  ...props
}: OptimizedImageProps) {
  return (
    <OptimizedImage
      src={src}
      alt={alt}
      className={`hero-image w-full h-full object-cover ${className || ''}`}
      quality={85}
      formats={['avif', 'webp', 'jpg']}
      blur={true}
      priority={true} // Heroes are usually above the fold
      sizes="100vw"
      {...props}
    />
  );
}

// Image preloader utility
export class ImagePreloader {
  private static cache = new Set<string>();

  static preload(src: string | string[], options: { quality?: number } = {}): Promise<void[]> {
    const sources = Array.isArray(src) ? src : [src];
    const { quality = 85 } = options;

    return Promise.all(
      sources.map(source => {
        if (this.cache.has(source)) {
          return Promise.resolve();
        }

        return new Promise<void>((resolve, reject) => {
          const link = document.createElement('link');
          link.rel = 'preload';
          link.as = 'image';
          link.href = addImageOptimizations(source, { quality });
          
          link.onload = () => {
            this.cache.add(source);
            document.head.removeChild(link);
            resolve();
          };
          
          link.onerror = () => {
            document.head.removeChild(link);
            reject(new Error(`Failed to preload image: ${source}`));
          };

          document.head.appendChild(link);
        });
      })
    );
  }

  static prefetch(src: string | string[]): void {
    const sources = Array.isArray(src) ? src : [src];
    
    sources.forEach(source => {
      if (!this.cache.has(source)) {
        const link = document.createElement('link');
        link.rel = 'prefetch';
        link.as = 'image';
        link.href = source;
        document.head.appendChild(link);
        this.cache.add(source);
      }
    });
  }
}

// Image optimization configuration for Next.js
export const imageConfig: ImageOptimizerConfig = {
  domains: [
    'localhost',
    '${PUBLIC_HOSTNAME}',
    'neurosynth.org',
    'neurovault.org',
    'openneuro.org',
    'brainmap.org'
  ],
  deviceSizes: DEVICE_SIZES,
  imageSizes: Object.values(IMAGE_SIZES),
  formats: ['image/avif', 'image/webp'],
  minimumCacheTTL: 60 * 60 * 24 * 7, // 1 week
  dangerouslyAllowSVG: true
};

// Utility to extract image dimensions from src
export async function getImageDimensions(src: string): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const img = new (globalThis as any).Image();
    img.onload = () => resolve({ width: img.naturalWidth, height: img.naturalHeight });
    img.onerror = reject;
    img.src = src;
  });
}

// Generate srcset for responsive images
export function generateSrcSet(
  src: string,
  sizes: number[] = [480, 768, 1024, 1280, 1920]
): string {
  return sizes
    .map(size => {
      const optimizedSrc = addImageOptimizations(src, { width: size });
      return `${optimizedSrc} ${size}w`;
    })
    .join(', ');
}
