/**
 * Advanced caching utilities for Brain Researcher UI
 * Provides multi-layered caching with TTL, LRU, and storage persistence
 */

// Cache entry interface
interface CacheEntry<T> {
  data: T;
  timestamp: number;
  ttl: number;
  accessCount: number;
  lastAccessed: number;
  tags: string[];
}

// Cache configuration
interface CacheConfig {
  maxSize: number;
  defaultTTL: number;
  persistent: boolean;
  compression: boolean;
  encryption?: boolean;
}

// Storage adapter interface
interface StorageAdapter {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
  clear(): void;
  key(index: number): string | null;
  get length(): number;
}

// Browser storage adapters
class LocalStorageAdapter implements StorageAdapter {
  getItem(key: string): string | null {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  }

  setItem(key: string, value: string): void {
    try {
      localStorage.setItem(key, value);
    } catch (e) {
      console.warn('LocalStorage setItem failed:', e);
    }
  }

  removeItem(key: string): void {
    try {
      localStorage.removeItem(key);
    } catch (e) {
      console.warn('LocalStorage removeItem failed:', e);
    }
  }

  clear(): void {
    try {
      localStorage.clear();
    } catch (e) {
      console.warn('LocalStorage clear failed:', e);
    }
  }

  key(index: number): string | null {
    try {
      return localStorage.key(index);
    } catch {
      return null;
    }
  }

  get length(): number {
    try {
      return localStorage.length;
    } catch {
      return 0;
    }
  }
}

class SessionStorageAdapter implements StorageAdapter {
  getItem(key: string): string | null {
    try {
      return sessionStorage.getItem(key);
    } catch {
      return null;
    }
  }

  setItem(key: string, value: string): void {
    try {
      sessionStorage.setItem(key, value);
    } catch (e) {
      console.warn('SessionStorage setItem failed:', e);
    }
  }

  removeItem(key: string): void {
    try {
      sessionStorage.removeItem(key);
    } catch (e) {
      console.warn('SessionStorage removeItem failed:', e);
    }
  }

  clear(): void {
    try {
      sessionStorage.clear();
    } catch (e) {
      console.warn('SessionStorage clear failed:', e);
    }
  }

  key(index: number): string | null {
    try {
      return sessionStorage.key(index);
    } catch {
      return null;
    }
  }

  get length(): number {
    try {
      return sessionStorage.length;
    } catch {
      return 0;
    }
  }
}

// IndexedDB adapter for larger data (unused stub)
class IndexedDBAdapter {
  private dbName: string;
  private storeName: string;
  private version: number;

  constructor(dbName = 'BrainResearcherCache', storeName = 'cache', version = 1) {
    this.dbName = dbName;
    this.storeName = storeName;
    this.version = version;
  }

  private async getDB(): Promise<IDBDatabase> {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(this.dbName, this.version);
      
      request.onerror = () => reject(request.error);
      request.onsuccess = () => resolve(request.result);
      
      request.onupgradeneeded = (event) => {
        const db = (event.target as IDBOpenDBRequest).result;
        if (!db.objectStoreNames.contains(this.storeName)) {
          db.createObjectStore(this.storeName);
        }
      };
    });
  }

  async getItemAsync(key: string): Promise<string | null> {
    try {
      const db = await this.getDB();
      const transaction = db.transaction(this.storeName, 'readonly');
      const store = transaction.objectStore(this.storeName);
      
      return new Promise((resolve, reject) => {
        const request = store.get(key);
        request.onerror = () => reject(request.error);
        request.onsuccess = () => resolve(request.result || null);
      });
    } catch {
      return null;
    }
  }

  async getItem(key: string): Promise<string | null> {
    return this.getItemAsync(key);
  }

  async setItem(key: string, value: string): Promise<void> {
    try {
      const db = await this.getDB();
      const transaction = db.transaction(this.storeName, 'readwrite');
      const store = transaction.objectStore(this.storeName);
      
      return new Promise((resolve, reject) => {
        const request = store.put(value, key);
        request.onerror = () => reject(request.error);
        request.onsuccess = () => resolve();
      });
    } catch (e) {
      console.warn('IndexedDB setItem failed:', e);
    }
  }

  async removeItem(key: string): Promise<void> {
    try {
      const db = await this.getDB();
      const transaction = db.transaction(this.storeName, 'readwrite');
      const store = transaction.objectStore(this.storeName);
      
      return new Promise((resolve, reject) => {
        const request = store.delete(key);
        request.onerror = () => reject(request.error);
        request.onsuccess = () => resolve();
      });
    } catch (e) {
      console.warn('IndexedDB removeItem failed:', e);
    }
  }

  async clear(): Promise<void> {
    try {
      const db = await this.getDB();
      const transaction = db.transaction(this.storeName, 'readwrite');
      const store = transaction.objectStore(this.storeName);
      
      return new Promise((resolve, reject) => {
        const request = store.clear();
        request.onerror = () => reject(request.error);
        request.onsuccess = () => resolve();
      });
    } catch (e) {
      console.warn('IndexedDB clear failed:', e);
    }
  }

}

// Advanced cache manager with multiple strategies
export class CacheManager<T = any> {
  private cache = new Map<string, CacheEntry<T>>();
  private config: CacheConfig;
  private storageAdapter: StorageAdapter;
  private cacheKey: string;

  constructor(
    cacheKey: string,
    config: Partial<CacheConfig> = {}
  ) {
    this.cacheKey = `br_cache_${cacheKey}`;
    this.config = {
      maxSize: 100,
      defaultTTL: 300000, // 5 minutes
      persistent: true,
      compression: false,
      ...config
    };

    // Choose storage adapter
    if (typeof window === 'undefined') {
      // Server-side: use in-memory only
      this.storageAdapter = new (class implements StorageAdapter {
        private data = new Map<string, string>();
        getItem(key: string) { return this.data.get(key) || null; }
        setItem(key: string, value: string) { this.data.set(key, value); }
        removeItem(key: string) { this.data.delete(key); }
        clear() { this.data.clear(); }
        key(index: number) { return Array.from(this.data.keys())[index] || null; }
        get length() { return this.data.size; }
      })();
    } else {
      // Client-side: use appropriate storage
      if (this.config.persistent) {
        this.storageAdapter = new LocalStorageAdapter();
      } else {
        this.storageAdapter = new SessionStorageAdapter();
      }
    }

    this.loadFromStorage();
  }

  // Get cached data
  get(key: string): T | null {
    const entry = this.cache.get(key);
    
    if (!entry) return null;

    // Check TTL
    if (this.isExpired(entry)) {
      this.cache.delete(key);
      this.removeFromStorage(key);
      return null;
    }

    // Update access statistics
    entry.accessCount++;
    entry.lastAccessed = Date.now();

    return entry.data;
  }

  // Set cached data
  set(
    key: string, 
    data: T, 
    options: { 
      ttl?: number; 
      tags?: string[]; 
      priority?: 'high' | 'normal' | 'low' 
    } = {}
  ): void {
    const { ttl = this.config.defaultTTL, tags = [], priority = 'normal' } = options;

    // Enforce cache size limit
    if (this.cache.size >= this.config.maxSize) {
      this.evictLRU();
    }

    const entry: CacheEntry<T> = {
      data,
      timestamp: Date.now(),
      ttl,
      accessCount: 1,
      lastAccessed: Date.now(),
      tags
    };

    this.cache.set(key, entry);
    
    // Persist if configured
    if (this.config.persistent) {
      this.saveToStorage(key, entry);
    }
  }

  // Check if key exists and is valid
  has(key: string): boolean {
    const entry = this.cache.get(key);
    return entry !== undefined && !this.isExpired(entry);
  }

  // Delete specific key
  delete(key: string): boolean {
    const deleted = this.cache.delete(key);
    if (deleted) {
      this.removeFromStorage(key);
    }
    return deleted;
  }

  // Clear all cache
  clear(): void {
    this.cache.clear();
    if (this.config.persistent) {
      this.storageAdapter.clear();
    }
  }

  // Clear by tags
  clearByTag(tag: string): void {
    const keysToDelete: string[] = [];
    
    for (const [key, entry] of Array.from(this.cache.entries())) {
      if (entry.tags.includes(tag)) {
        keysToDelete.push(key);
      }
    }

    keysToDelete.forEach(key => this.delete(key));
  }

  // Get cache statistics
  getStats(): {
    size: number;
    maxSize: number;
    hitRate: number;
    totalAccess: number;
    oldestEntry: number;
    newestEntry: number;
  } {
    let totalAccess = 0;
    let oldestEntry = Date.now();
    let newestEntry = 0;

    for (const entry of Array.from(this.cache.values())) {
      totalAccess += entry.accessCount;
      oldestEntry = Math.min(oldestEntry, entry.timestamp);
      newestEntry = Math.max(newestEntry, entry.timestamp);
    }

    return {
      size: this.cache.size,
      maxSize: this.config.maxSize,
      hitRate: totalAccess > 0 ? (this.cache.size / totalAccess) * 100 : 0,
      totalAccess,
      oldestEntry: oldestEntry === Date.now() ? 0 : oldestEntry,
      newestEntry
    };
  }

  // Get or set with async function
  async getOrSet(
    key: string,
    factory: () => Promise<T>,
    options: { ttl?: number; tags?: string[] } = {}
  ): Promise<T> {
    const cached = this.get(key);
    if (cached !== null) {
      return cached;
    }

    const data = await factory();
    this.set(key, data, options);
    return data;
  }

  // Batch operations
  setMany(entries: Array<{ key: string; data: T; options?: any }>): void {
    entries.forEach(({ key, data, options }) => {
      this.set(key, data, options);
    });
  }

  getMany(keys: string[]): Map<string, T | null> {
    const result = new Map<string, T | null>();
    keys.forEach(key => {
      result.set(key, this.get(key));
    });
    return result;
  }

  // Private methods
  private isExpired(entry: CacheEntry<T>): boolean {
    return Date.now() - entry.timestamp > entry.ttl;
  }

  private evictLRU(): void {
    let oldestKey: string | null = null;
    let oldestTime = Date.now();

    for (const [key, entry] of Array.from(this.cache.entries())) {
      if (entry.lastAccessed < oldestTime) {
        oldestTime = entry.lastAccessed;
        oldestKey = key;
      }
    }

    if (oldestKey) {
      this.delete(oldestKey);
    }
  }

  private loadFromStorage(): void {
    if (!this.config.persistent) return;

    try {
      const stored = this.storageAdapter.getItem(this.cacheKey);
      if (stored) {
        const data = JSON.parse(stored);
        for (const [key, entry] of Object.entries(data)) {
          if (!this.isExpired(entry as CacheEntry<T>)) {
            this.cache.set(key, entry as CacheEntry<T>);
          }
        }
      }
    } catch (e) {
      console.warn('Failed to load cache from storage:', e);
    }
  }

  private saveToStorage(key: string, entry: CacheEntry<T>): void {
    if (!this.config.persistent) return;

    try {
      // Load existing data
      const stored = this.storageAdapter.getItem(this.cacheKey);
      const data = stored ? JSON.parse(stored) : {};
      
      // Update with new entry
      data[key] = entry;
      
      // Save back
      this.storageAdapter.setItem(this.cacheKey, JSON.stringify(data));
    } catch (e) {
      console.warn('Failed to save cache to storage:', e);
    }
  }

  private removeFromStorage(key: string): void {
    if (!this.config.persistent) return;

    try {
      const stored = this.storageAdapter.getItem(this.cacheKey);
      if (stored) {
        const data = JSON.parse(stored);
        delete data[key];
        this.storageAdapter.setItem(this.cacheKey, JSON.stringify(data));
      }
    } catch (e) {
      console.warn('Failed to remove cache from storage:', e);
    }
  }
}

// Specialized cache managers for different data types
export class APICache extends CacheManager<any> {
  constructor() {
    super('api', {
      maxSize: 200,
      defaultTTL: 300000, // 5 minutes
      persistent: true
    });
  }

  // Cache API responses with automatic key generation
  cacheResponse(
    url: string, 
    method: string = 'GET', 
    data?: any,
    response?: any,
    ttl?: number
  ): void {
    const key = this.generateAPIKey(url, method, data);
    this.set(key, response, { 
      ttl, 
      tags: ['api', method.toLowerCase(), this.extractDomain(url)] 
    });
  }

  getCachedResponse(url: string, method: string = 'GET', data?: any): any {
    const key = this.generateAPIKey(url, method, data);
    return this.get(key);
  }

  private generateAPIKey(url: string, method: string, data?: any): string {
    const dataHash = data ? JSON.stringify(data) : '';
    return `${method}:${url}:${dataHash}`;
  }

  private extractDomain(url: string): string {
    try {
      return new URL(url).hostname;
    } catch {
      return 'unknown';
    }
  }
}

export class ImageCache extends CacheManager<string> {
  constructor() {
    super('images', {
      maxSize: 50,
      defaultTTL: 3600000, // 1 hour
      persistent: true
    });
  }
}

export class ChartCache extends CacheManager<any> {
  constructor() {
    super('charts', {
      maxSize: 30,
      defaultTTL: 600000, // 10 minutes
      persistent: false // Charts change frequently
    });
  }
}

// Global cache instances
export const apiCache = new APICache();
export const imageCache = new ImageCache();
export const chartCache = new ChartCache();

// Cache-aware fetch wrapper
export async function cachedFetch(
  url: string,
  options: RequestInit & { cache?: 'force-cache' | 'no-cache' | 'reload'; ttl?: number } = {}
): Promise<Response> {
  const { cache = 'default', ttl = 300000, ...fetchOptions } = options;
  const method = fetchOptions.method || 'GET';

  // Check cache first
  if (cache !== 'no-cache' && cache !== 'reload') {
    const cached = apiCache.getCachedResponse(url, method, fetchOptions.body);
    if (cached) {
      // Return cached response
      return new Response(JSON.stringify(cached), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
    }
  }

  // Fetch from network
  const response = await fetch(url, fetchOptions);
  
  // Cache successful responses
  if (response.ok && method === 'GET') {
    const data = await response.clone().json().catch(() => null);
    if (data) {
      apiCache.cacheResponse(url, method, fetchOptions.body, data, ttl);
    }
  }

  return response;
}

// Service Worker cache management (if available)
export class ServiceWorkerCache {
  static async isAvailable(): Promise<boolean> {
    return 'serviceWorker' in navigator && 'caches' in window;
  }

  static async cache(request: RequestInfo, response: Response, cacheName = 'br-cache-v1'): Promise<void> {
    if (await this.isAvailable()) {
      const cache = await caches.open(cacheName);
      await cache.put(request, response.clone());
    }
  }

  static async getCached(request: RequestInfo, cacheName = 'br-cache-v1'): Promise<Response | undefined> {
    if (await this.isAvailable()) {
      const cache = await caches.open(cacheName);
      return cache.match(request);
    }
  }

  static async clearCache(cacheName = 'br-cache-v1'): Promise<void> {
    if (await this.isAvailable()) {
      await caches.delete(cacheName);
    }
  }
}
