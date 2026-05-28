/**
 * Image Optimization Utilities for Brain Researcher
 * Handles image processing, compression, and format conversion
 */

const sharp = require('sharp');
const fs = require('fs').promises;
const path = require('path');
const crypto = require('crypto');

class ImageOptimizer {
    constructor(options = {}) {
        this.options = {
            quality: 85,
            progressive: true,
            stripMetadata: true,
            formats: ['webp', 'avif', 'jpeg', 'png'],
            sizes: [400, 800, 1200, 1920],
            cacheDir: options.cacheDir || './cache/images',
            outputDir: options.outputDir || './public/optimized',
            ...options
        };
        
        this.initializeDirectories();
    }
    
    /**
     * Initialize required directories
     */
    async initializeDirectories() {
        try {
            await fs.mkdir(this.options.cacheDir, { recursive: true });
            await fs.mkdir(this.options.outputDir, { recursive: true });
        } catch (error) {
            console.error('Failed to create directories:', error);
        }
    }
    
    /**
     * Generate image hash for caching
     */
    generateImageHash(imagePath, options) {
        const content = `${imagePath}:${JSON.stringify(options)}`;
        return crypto.createHash('md5').update(content).digest('hex');
    }
    
    /**
     * Check if optimized image exists in cache
     */
    async getCachedImage(hash, format, size) {
        const filename = `${hash}_${size}.${format}`;
        const cachePath = path.join(this.options.cacheDir, filename);
        
        try {
            await fs.access(cachePath);
            return cachePath;
        } catch {
            return null;
        }
    }
    
    /**
     * Optimize single image with multiple formats and sizes
     */
    async optimizeImage(inputPath, outputOptions = {}) {
        const options = { ...this.options, ...outputOptions };
        const hash = this.generateImageHash(inputPath, options);
        
        try {
            const image = sharp(inputPath);
            const metadata = await image.metadata();
            const results = {};
            
            console.log(`Optimizing image: ${inputPath}`);
            console.log(`Original: ${metadata.width}x${metadata.height}, ${metadata.format}`);
            
            // Process each format
            for (const format of options.formats) {
                results[format] = {};
                
                // Process each size
                for (const size of options.sizes) {
                    // Skip if original is smaller than target size
                    if (metadata.width < size && format !== 'webp' && format !== 'avif') {
                        continue;
                    }
                    
                    const cachedPath = await this.getCachedImage(hash, format, size);
                    
                    if (cachedPath) {
                        results[format][size] = cachedPath;
                        continue;
                    }
                    
                    const filename = `${hash}_${size}.${format}`;
                    const outputPath = path.join(this.options.cacheDir, filename);
                    
                    let pipeline = image.clone()
                        .resize(size, null, {
                            withoutEnlargement: true,
                            fit: 'inside'
                        });
                    
                    // Apply format-specific optimizations
                    switch (format) {
                        case 'webp':
                            pipeline = pipeline.webp({
                                quality: options.quality,
                                effort: 6,
                                smartSubsample: true
                            });
                            break;
                            
                        case 'avif':
                            pipeline = pipeline.avif({
                                quality: options.quality - 10, // AVIF can achieve same quality at lower setting
                                effort: 6,
                                chromaSubsampling: '4:2:0'
                            });
                            break;
                            
                        case 'jpeg':
                            pipeline = pipeline.jpeg({
                                quality: options.quality,
                                progressive: options.progressive,
                                mozjpeg: true,
                                trellisQuantisation: true,
                                overshootDeringing: true,
                                optimizeScans: true
                            });
                            break;
                            
                        case 'png':
                            pipeline = pipeline.png({
                                compressionLevel: 9,
                                adaptiveFiltering: true,
                                progressive: options.progressive
                            });
                            break;
                    }
                    
                    // Remove metadata if requested
                    if (options.stripMetadata) {
                        pipeline = pipeline.withMetadata({});
                    }
                    
                    await pipeline.toFile(outputPath);
                    results[format][size] = outputPath;
                    
                    const optimizedStats = await fs.stat(outputPath);
                    console.log(`  ${format} ${size}w: ${(optimizedStats.size / 1024).toFixed(1)}KB`);
                }
            }
            
            return results;
            
        } catch (error) {
            console.error(`Failed to optimize image ${inputPath}:`, error);
            throw error;
        }
    }
    
    /**
     * Batch optimize images in directory
     */
    async optimizeDirectory(inputDir, outputDir = null) {
        const targetDir = outputDir || this.options.outputDir;
        const imageExtensions = ['.jpg', '.jpeg', '.png', '.webp', '.tiff', '.bmp'];
        
        try {
            const files = await fs.readdir(inputDir);
            const imageFiles = files.filter(file => 
                imageExtensions.includes(path.extname(file).toLowerCase())
            );
            
            console.log(`Found ${imageFiles.length} images to optimize`);
            
            const results = {};
            
            for (const file of imageFiles) {
                const inputPath = path.join(inputDir, file);
                const baseName = path.parse(file).name;
                
                try {
                    const optimized = await this.optimizeImage(inputPath);
                    results[baseName] = optimized;
                } catch (error) {
                    console.error(`Failed to optimize ${file}:`, error);
                    results[baseName] = { error: error.message };
                }
            }
            
            // Generate manifest file
            const manifestPath = path.join(targetDir, 'image-manifest.json');
            await fs.writeFile(manifestPath, JSON.stringify(results, null, 2));
            
            return results;
            
        } catch (error) {
            console.error('Failed to optimize directory:', error);
            throw error;
        }
    }
    
    /**
     * Generate responsive image HTML
     */
    generateResponsiveHTML(imageName, optimizedResults, options = {}) {
        const { alt = '', className = '', loading = 'lazy' } = options;
        
        if (!optimizedResults || Object.keys(optimizedResults).length === 0) {
            return `<img src="${imageName}" alt="${alt}" class="${className}" loading="${loading}">`;
        }
        
        // Generate source elements for different formats
        const sources = [];
        const formatPriority = ['avif', 'webp', 'jpeg', 'png'];
        
        formatPriority.forEach(format => {
            if (optimizedResults[format]) {
                const sizes = Object.keys(optimizedResults[format])
                    .map(size => parseInt(size))
                    .sort((a, b) => a - b);
                
                if (sizes.length > 0) {
                    const srcset = sizes
                        .map(size => {
                            const path = optimizedResults[format][size].replace(this.options.cacheDir, '/optimized');
                            return `${path} ${size}w`;
                        })
                        .join(', ');
                    
                    sources.push(`<source srcset="${srcset}" type="image/${format}" sizes="(max-width: 768px) 100vw, (max-width: 1200px) 50vw, 33vw">`);
                }
            }
        });
        
        // Fallback image (largest JPEG or PNG)
        const fallbackFormat = optimizedResults.jpeg || optimizedResults.png;
        let fallbackSrc = imageName;
        
        if (fallbackFormat) {
            const sizes = Object.keys(fallbackFormat).map(size => parseInt(size)).sort((a, b) => b - a);
            if (sizes.length > 0) {
                fallbackSrc = fallbackFormat[sizes[0]].replace(this.options.cacheDir, '/optimized');
            }
        }
        
        return `
            <picture>
                ${sources.join('\n                ')}
                <img src="${fallbackSrc}" alt="${alt}" class="${className}" loading="${loading}">
            </picture>
        `.trim();
    }
    
    /**
     * Generate Next.js Image component props
     */
    generateNextImageProps(imageName, optimizedResults, options = {}) {
        if (!optimizedResults || Object.keys(optimizedResults).length === 0) {
            return { src: imageName, ...options };
        }
        
        // Find the largest size for the default src
        let src = imageName;
        let width, height;
        
        const formats = Object.keys(optimizedResults);
        if (formats.length > 0) {
            const firstFormat = optimizedResults[formats[0]];
            const sizes = Object.keys(firstFormat).map(size => parseInt(size)).sort((a, b) => b - a);
            
            if (sizes.length > 0) {
                src = firstFormat[sizes[0]].replace(this.options.cacheDir, '/optimized');
                
                // Get dimensions from the optimized image
                try {
                    const metadata = require('sharp')(firstFormat[sizes[0]]).metadata();
                    width = metadata.width;
                    height = metadata.height;
                } catch (error) {
                    console.warn('Could not get image dimensions:', error);
                }
            }
        }
        
        return {
            src,
            width,
            height,
            sizes: "(max-width: 768px) 100vw, (max-width: 1200px) 50vw, 33vw",
            ...options
        };
    }
    
    /**
     * Clean up old cached images
     */
    async cleanupCache(maxAgeHours = 168) { // 7 days default
        const maxAge = maxAgeHours * 60 * 60 * 1000;
        const now = Date.now();
        
        try {
            const files = await fs.readdir(this.options.cacheDir);
            let cleanedCount = 0;
            
            for (const file of files) {
                const filePath = path.join(this.options.cacheDir, file);
                const stats = await fs.stat(filePath);
                
                if (now - stats.mtime.getTime() > maxAge) {
                    await fs.unlink(filePath);
                    cleanedCount++;
                }
            }
            
            console.log(`Cleaned up ${cleanedCount} cached images`);
            return cleanedCount;
            
        } catch (error) {
            console.error('Failed to cleanup cache:', error);
            throw error;
        }
    }
    
    /**
     * Get cache statistics
     */
    async getCacheStats() {
        try {
            const files = await fs.readdir(this.options.cacheDir);
            let totalSize = 0;
            const formats = {};
            
            for (const file of files) {
                const filePath = path.join(this.options.cacheDir, file);
                const stats = await fs.stat(filePath);
                
                totalSize += stats.size;
                
                const ext = path.extname(file).substring(1);
                formats[ext] = (formats[ext] || 0) + 1;
            }
            
            return {
                fileCount: files.length,
                totalSize,
                totalSizeMB: (totalSize / 1024 / 1024).toFixed(2),
                formats
            };
            
        } catch (error) {
            console.error('Failed to get cache stats:', error);
            return null;
        }
    }
}

module.exports = { ImageOptimizer };

// CLI usage
if (require.main === module) {
    const args = process.argv.slice(2);
    const command = args[0];
    
    const optimizer = new ImageOptimizer();
    
    switch (command) {
        case 'optimize':
            const inputPath = args[1];
            if (!inputPath) {
                console.error('Please provide input path');
                process.exit(1);
            }
            
            optimizer.optimizeImage(inputPath)
                .then(results => {
                    console.log('Optimization complete:', results);
                })
                .catch(error => {
                    console.error('Optimization failed:', error);
                    process.exit(1);
                });
            break;
            
        case 'optimize-dir':
            const inputDir = args[1];
            const outputDir = args[2];
            
            if (!inputDir) {
                console.error('Please provide input directory');
                process.exit(1);
            }
            
            optimizer.optimizeDirectory(inputDir, outputDir)
                .then(results => {
                    console.log('Directory optimization complete');
                    console.log(`Processed ${Object.keys(results).length} images`);
                })
                .catch(error => {
                    console.error('Directory optimization failed:', error);
                    process.exit(1);
                });
            break;
            
        case 'cleanup':
            const maxAge = parseInt(args[1]) || 168;
            
            optimizer.cleanupCache(maxAge)
                .then(count => {
                    console.log(`Cleaned up ${count} files`);
                })
                .catch(error => {
                    console.error('Cleanup failed:', error);
                    process.exit(1);
                });
            break;
            
        case 'stats':
            optimizer.getCacheStats()
                .then(stats => {
                    console.log('Cache Statistics:', stats);
                })
                .catch(error => {
                    console.error('Failed to get stats:', error);
                    process.exit(1);
                });
            break;
            
        default:
            console.log(`
Usage: node image-optimizer.js <command> [options]

Commands:
  optimize <input>           Optimize single image
  optimize-dir <input> [output]  Optimize directory of images
  cleanup [maxAge]          Clean up cache (maxAge in hours, default: 168)
  stats                     Show cache statistics

Examples:
  node image-optimizer.js optimize ./src/images/hero.jpg
  node image-optimizer.js optimize-dir ./src/images ./public/optimized
  node image-optimizer.js cleanup 72
  node image-optimizer.js stats
            `);
    }
}