/**
 * CDN Cache Warming System for Brain Researcher
 * Proactively loads critical resources into edge caches for optimal performance
 */

const fetch = require('node-fetch');
const fs = require('fs').promises;
const path = require('path');
const pLimit = require('p-limit');
const cliProgress = require('cli-progress');

class CacheWarmer {
    constructor(options = {}) {
        this.baseUrl = options.baseUrl || process.env.CDN_BASE_URL || 'https://brain-researcher.com';
        this.concurrency = options.concurrency || 10;
        this.timeout = options.timeout || 30000;
        this.retryCount = options.retryCount || 3;
        this.retryDelay = options.retryDelay || 1000;
        this.userAgent = options.userAgent || 'BrainResearcher-CacheWarmer/1.0';
        
        this.limiter = pLimit(this.concurrency);
        this.results = {
            total: 0,
            success: 0,
            failed: 0,
            cached: 0,
            errors: []
        };
        
        // Progress tracking
        this.progressBar = new cliProgress.SingleBar({
            format: 'Cache Warming |{bar}| {percentage}% | {value}/{total} | {duration_formatted} | {status}',
            barCompleteChar: '\u2588',
            barIncompleteChar: '\u2591',
            hideCursor: true
        });
    }
    
    /**
     * Load URLs from various sources
     */
    async loadUrlsFromSitemap(sitemapUrl) {
        console.log(`Loading URLs from sitemap: ${sitemapUrl}`);
        
        try {
            const response = await fetch(sitemapUrl, { timeout: this.timeout });
            const sitemapText = await response.text();
            
            // Parse XML sitemap
            const urlMatches = sitemapText.match(/<loc>(.*?)<\/loc>/g);
            if (!urlMatches) {
                throw new Error('No URLs found in sitemap');
            }
            
            const urls = urlMatches.map(match => 
                match.replace('<loc>', '').replace('</loc>', '').trim()
            );
            
            console.log(`Found ${urls.length} URLs in sitemap`);
            return urls;
            
        } catch (error) {
            console.error('Failed to load sitemap:', error.message);
            return [];
        }
    }
    
    /**
     * Load URLs from configuration file
     */
    async loadUrlsFromConfig(configPath) {
        try {
            const configContent = await fs.readFile(configPath, 'utf8');
            const config = JSON.parse(configContent);
            
            let allUrls = [];
            
            // Critical pages (highest priority)
            if (config.critical) {
                allUrls = allUrls.concat(config.critical.map(url => ({ url, priority: 'critical' })));
            }
            
            // Important pages (medium priority)
            if (config.important) {
                allUrls = allUrls.concat(config.important.map(url => ({ url, priority: 'important' })));
            }
            
            // Standard pages (normal priority)
            if (config.standard) {
                allUrls = allUrls.concat(config.standard.map(url => ({ url, priority: 'standard' })));
            }
            
            // Static assets
            if (config.assets) {
                allUrls = allUrls.concat(config.assets.map(url => ({ url, priority: 'asset' })));
            }
            
            return allUrls;
            
        } catch (error) {
            console.error('Failed to load config:', error.message);
            return [];
        }
    }
    
    /**
     * Generate default critical URLs
     */
    getDefaultCriticalUrls() {
        return [
            { url: '/', priority: 'critical' },
            { url: '/knowledge-graph', priority: 'critical' },
            { url: '/datasets', priority: 'important' },
            { url: '/api/health', priority: 'important' },
            { url: '/static/css/main.css', priority: 'asset' },
            { url: '/static/js/main.js', priority: 'asset' },
            { url: '/static/images/logo.svg', priority: 'asset' },
            { url: '/_next/static/css/app.css', priority: 'asset' },
            { url: '/_next/static/js/app.js', priority: 'asset' },
            { url: '/manifest.json', priority: 'asset' }
        ];
    }
    
    /**
     * Warm single URL with retry logic
     */
    async warmUrl(urlInfo, attempt = 1) {
        const url = typeof urlInfo === 'string' ? urlInfo : urlInfo.url;
        const priority = typeof urlInfo === 'object' ? urlInfo.priority : 'standard';
        
        const fullUrl = url.startsWith('http') ? url : `${this.baseUrl}${url}`;
        
        try {
            const startTime = Date.now();
            
            const response = await fetch(fullUrl, {
                method: 'GET',
                headers: {
                    'User-Agent': this.userAgent,
                    'Accept': '*/*',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Cache-Control': 'no-cache', // Force cache refresh
                    'Pragma': 'no-cache'
                },
                timeout: this.timeout,
                redirect: 'follow'
            });
            
            const duration = Date.now() - startTime;
            const cacheStatus = response.headers.get('x-cache') || 
                              response.headers.get('cf-cache-status') || 
                              'unknown';
            
            if (response.ok) {
                this.results.success++;
                
                if (cacheStatus.toLowerCase().includes('hit')) {
                    this.results.cached++;
                }
                
                return {
                    url: fullUrl,
                    status: response.status,
                    duration,
                    cacheStatus,
                    priority,
                    contentLength: parseInt(response.headers.get('content-length') || '0'),
                    contentType: response.headers.get('content-type'),
                    success: true
                };
            } else {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
        } catch (error) {
            if (attempt < this.retryCount) {
                console.log(`Retrying ${url} (attempt ${attempt + 1}/${this.retryCount})`);
                await new Promise(resolve => setTimeout(resolve, this.retryDelay * attempt));
                return this.warmUrl(urlInfo, attempt + 1);
            }
            
            this.results.failed++;
            this.results.errors.push({
                url: fullUrl,
                error: error.message,
                priority,
                attempts: attempt
            });
            
            return {
                url: fullUrl,
                error: error.message,
                priority,
                attempts: attempt,
                success: false
            };
        }
    }
    
    /**
     * Warm multiple URLs with concurrency control and prioritization
     */
    async warmUrls(urls, options = {}) {
        const { showProgress = true, sortByPriority = true } = options;
        
        // Sort by priority if requested
        if (sortByPriority) {
            const priorityOrder = { critical: 0, important: 1, standard: 2, asset: 3 };
            urls.sort((a, b) => {
                const aPriority = typeof a === 'object' ? a.priority : 'standard';
                const bPriority = typeof b === 'object' ? b.priority : 'standard';
                return priorityOrder[aPriority] - priorityOrder[bPriority];
            });
        }
        
        this.results.total = urls.length;
        
        if (showProgress) {
            this.progressBar.start(this.results.total, 0, { status: 'Starting...' });
        }
        
        const tasks = urls.map((url, index) => 
            this.limiter(async () => {
                const result = await this.warmUrl(url);
                
                if (showProgress) {
                    const completed = this.results.success + this.results.failed;
                    this.progressBar.update(completed, { 
                        status: result.success ? 'Success' : 'Failed'
                    });
                }
                
                return result;
            })
        );
        
        const results = await Promise.all(tasks);
        
        if (showProgress) {
            this.progressBar.stop();
        }
        
        return results;
    }
    
    /**
     * Warm cache from sitemap
     */
    async warmFromSitemap(sitemapUrl, options = {}) {
        console.log('🔥 Starting cache warming from sitemap...');
        
        const urls = await this.loadUrlsFromSitemap(sitemapUrl);
        if (urls.length === 0) {
            console.log('No URLs to warm');
            return { results: [] };
        }
        
        const urlsWithPriority = urls.map(url => ({ url, priority: 'standard' }));
        const results = await this.warmUrls(urlsWithPriority, options);
        
        return { results };
    }
    
    /**
     * Warm cache from configuration
     */
    async warmFromConfig(configPath, options = {}) {
        console.log('🔥 Starting cache warming from configuration...');
        
        let urls = await this.loadUrlsFromConfig(configPath);
        
        if (urls.length === 0) {
            console.log('No configuration found, using default URLs');
            urls = this.getDefaultCriticalUrls();
        }
        
        const results = await this.warmUrls(urls, options);
        
        return { results };
    }
    
    /**
     * Generate warming report
     */
    generateReport(results, outputPath = null) {
        const report = {
            timestamp: new Date().toISOString(),
            summary: {
                total: this.results.total,
                successful: this.results.success,
                failed: this.results.failed,
                cached: this.results.cached,
                successRate: ((this.results.success / this.results.total) * 100).toFixed(2) + '%',
                cacheHitRate: ((this.results.cached / this.results.success) * 100).toFixed(2) + '%'
            },
            performance: {
                averageResponseTime: this.calculateAverageResponseTime(results),
                slowestUrls: this.getSlowestUrls(results, 5),
                fastestUrls: this.getFastestUrls(results, 5)
            },
            failures: this.results.errors,
            byPriority: this.groupResultsByPriority(results)
        };
        
        if (outputPath) {
            fs.writeFile(outputPath, JSON.stringify(report, null, 2));
            console.log(`📊 Report saved to: ${outputPath}`);
        }
        
        return report;
    }
    
    /**
     * Calculate average response time
     */
    calculateAverageResponseTime(results) {
        const successfulResults = results.filter(r => r.success && r.duration);
        if (successfulResults.length === 0) return 0;
        
        const totalTime = successfulResults.reduce((sum, r) => sum + r.duration, 0);
        return Math.round(totalTime / successfulResults.length);
    }
    
    /**
     * Get slowest URLs
     */
    getSlowestUrls(results, count = 5) {
        return results
            .filter(r => r.success && r.duration)
            .sort((a, b) => b.duration - a.duration)
            .slice(0, count)
            .map(r => ({
                url: r.url,
                duration: r.duration,
                priority: r.priority
            }));
    }
    
    /**
     * Get fastest URLs
     */
    getFastestUrls(results, count = 5) {
        return results
            .filter(r => r.success && r.duration)
            .sort((a, b) => a.duration - b.duration)
            .slice(0, count)
            .map(r => ({
                url: r.url,
                duration: r.duration,
                priority: r.priority
            }));
    }
    
    /**
     * Group results by priority
     */
    groupResultsByPriority(results) {
        const groups = {};
        
        results.forEach(result => {
            const priority = result.priority || 'standard';
            if (!groups[priority]) {
                groups[priority] = { total: 0, success: 0, failed: 0 };
            }
            
            groups[priority].total++;
            if (result.success) {
                groups[priority].success++;
            } else {
                groups[priority].failed++;
            }
        });
        
        return groups;
    }
    
    /**
     * Scheduled cache warming
     */
    async startScheduledWarming(configPath, interval = 3600000) { // Default: 1 hour
        console.log(`🕒 Starting scheduled cache warming every ${interval/1000/60} minutes`);
        
        const runWarming = async () => {
            try {
                console.log(`\n🔥 Running scheduled cache warming at ${new Date().toISOString()}`);
                const { results } = await this.warmFromConfig(configPath, { showProgress: true });
                const report = this.generateReport(results);
                
                console.log(`✅ Completed: ${report.summary.successful}/${report.summary.total} URLs`);
                console.log(`📊 Cache hit rate: ${report.summary.cacheHitRate}`);
                
                // Reset results for next run
                this.results = {
                    total: 0,
                    success: 0,
                    failed: 0,
                    cached: 0,
                    errors: []
                };
                
            } catch (error) {
                console.error('Scheduled warming failed:', error);
            }
        };
        
        // Run immediately, then on schedule
        await runWarming();
        
        return setInterval(runWarming, interval);
    }
    
    /**
     * Health check for cached resources
     */
    async healthCheck(urls) {
        console.log('🏥 Running cache health check...');
        
        const results = await this.warmUrls(urls, { showProgress: true });
        const unhealthyUrls = results.filter(r => !r.success || r.duration > 5000);
        
        if (unhealthyUrls.length > 0) {
            console.warn(`⚠️  Found ${unhealthyUrls.length} unhealthy URLs:`);
            unhealthyUrls.forEach(url => {
                console.warn(`   - ${url.url}: ${url.error || 'Slow response'}`);
            });
        } else {
            console.log('✅ All URLs are healthy');
        }
        
        return {
            healthy: results.filter(r => r.success && r.duration <= 5000).length,
            unhealthy: unhealthyUrls.length,
            unhealthyUrls
        };
    }
}

// Configuration file template
const defaultConfig = {
    critical: [
        '/',
        '/knowledge-graph',
        '/api/health'
    ],
    important: [
        '/datasets',
        '/about',
        '/docs',
        '/api/datasets',
        '/api/concepts'
    ],
    standard: [
        '/contact',
        '/privacy',
        '/terms',
        '/api/search',
        '/api/studies'
    ],
    assets: [
        '/static/css/main.css',
        '/static/js/main.js',
        '/static/images/logo.svg',
        '/static/images/brain-icon.png',
        '/_next/static/css/app.css',
        '/_next/static/js/app.js',
        '/manifest.json',
        '/favicon.ico'
    ]
};

module.exports = { CacheWarmer, defaultConfig };

// CLI usage
if (require.main === module) {
    const command = process.argv[2];
    const configPath = process.argv[3] || './cache-warming-config.json';
    
    const warmer = new CacheWarmer({
        baseUrl: process.env.CDN_BASE_URL || 'https://brain-researcher.com',
        concurrency: parseInt(process.env.CACHE_WARM_CONCURRENCY) || 10
    });
    
    switch (command) {
        case 'warm':
            warmer.warmFromConfig(configPath)
                .then(({ results }) => {
                    const report = warmer.generateReport(results, './cache-warming-report.json');
                    console.log('\n📊 Cache Warming Summary:');
                    console.log(`   Total URLs: ${report.summary.total}`);
                    console.log(`   Successful: ${report.summary.successful}`);
                    console.log(`   Failed: ${report.summary.failed}`);
                    console.log(`   Success Rate: ${report.summary.successRate}`);
                    console.log(`   Cache Hit Rate: ${report.summary.cacheHitRate}`);
                    
                    if (report.summary.failed > 0) {
                        console.log('\n❌ Failed URLs:');
                        report.failures.forEach(failure => {
                            console.log(`   - ${failure.url}: ${failure.error}`);
                        });
                    }
                })
                .catch(error => {
                    console.error('Cache warming failed:', error);
                    process.exit(1);
                });
            break;
            
        case 'sitemap':
            const sitemapUrl = process.argv[3];
            if (!sitemapUrl) {
                console.error('Please provide sitemap URL');
                process.exit(1);
            }
            
            warmer.warmFromSitemap(sitemapUrl)
                .then(({ results }) => {
                    const report = warmer.generateReport(results);
                    console.log('Sitemap warming completed:', report.summary);
                })
                .catch(error => {
                    console.error('Sitemap warming failed:', error);
                    process.exit(1);
                });
            break;
            
        case 'schedule':
            const interval = parseInt(process.argv[4]) || 3600000; // 1 hour
            warmer.startScheduledWarming(configPath, interval)
                .then(intervalId => {
                    console.log('Scheduled warming started. Press Ctrl+C to stop.');
                    
                    process.on('SIGINT', () => {
                        clearInterval(intervalId);
                        console.log('\nScheduled warming stopped.');
                        process.exit(0);
                    });
                })
                .catch(error => {
                    console.error('Scheduled warming failed:', error);
                    process.exit(1);
                });
            break;
            
        case 'health':
            const healthUrls = [
                { url: '/', priority: 'critical' },
                { url: '/api/health', priority: 'critical' },
                { url: '/knowledge-graph', priority: 'important' }
            ];
            
            warmer.healthCheck(healthUrls)
                .then(result => {
                    console.log(`Health check completed: ${result.healthy} healthy, ${result.unhealthy} unhealthy`);
                })
                .catch(error => {
                    console.error('Health check failed:', error);
                    process.exit(1);
                });
            break;
            
        case 'init':
            const configOutput = process.argv[3] || './cache-warming-config.json';
            fs.writeFile(configOutput, JSON.stringify(defaultConfig, null, 2))
                .then(() => {
                    console.log(`✅ Created default configuration: ${configOutput}`);
                })
                .catch(error => {
                    console.error('Failed to create config:', error);
                    process.exit(1);
                });
            break;
            
        default:
            console.log(`
🔥 Brain Researcher Cache Warmer

Usage: node cache-warmer.js <command> [options]

Commands:
  warm [config]              Warm cache from configuration file
  sitemap <url>             Warm cache from sitemap URL  
  schedule [config] [interval]  Start scheduled warming (interval in ms)
  health                    Run health check on critical URLs
  init [config]             Create default configuration file

Examples:
  node cache-warmer.js warm ./cache-config.json
  node cache-warmer.js sitemap https://brain-researcher.com/sitemap.xml
  node cache-warmer.js schedule ./cache-config.json 1800000
  node cache-warmer.js health
  node cache-warmer.js init ./my-cache-config.json
            `);
    }
}