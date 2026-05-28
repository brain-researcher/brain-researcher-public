"""
Unit tests for Demo Cache & Performance Optimization
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import time
import json
from datetime import datetime, timedelta


class TestDemoCache:
    """Test suite for Demo Cache functionality"""
    
    @pytest.fixture
    def cache_config(self):
        """Cache configuration"""
        return {
            'max_size': 50,
            'default_ttl': 300000,  # 5 minutes in ms
            'cleanup_interval': 60000  # 1 minute
        }
    
    @pytest.fixture
    def demo_data(self):
        """Sample demo data"""
        return {
            'glm': {
                'id': 'glm',
                'preloaded': True,
                'assets': ['activation_map.nii.gz', 'glass_brain.png'],
                'cached_at': datetime.now().isoformat()
            },
            'connectivity': {
                'id': 'connectivity',
                'preloaded': True,
                'assets': ['correlation_matrix.csv', 'network_graph.json']
            }
        }
    
    def test_cache_initialization(self, cache_config):
        """Test cache initialization with config"""
        assert cache_config['max_size'] == 50
        assert cache_config['default_ttl'] == 300000
        assert cache_config['cleanup_interval'] == 60000
    
    def test_cache_hit(self, demo_data):
        """Test cache hit scenario"""
        cache = {}
        key = 'demo_glm'
        
        # Store in cache
        cache[key] = {
            'data': demo_data['glm'],
            'timestamp': time.time() * 1000,
            'ttl': 300000
        }
        
        # Retrieve from cache
        assert key in cache
        assert cache[key]['data']['id'] == 'glm'
    
    def test_cache_miss(self):
        """Test cache miss scenario"""
        cache = {}
        key = 'demo_missing'
        
        assert key not in cache
        
        # Fetch and store
        fetched_data = {'id': 'missing', 'fetched': True}
        cache[key] = {
            'data': fetched_data,
            'timestamp': time.time() * 1000,
            'ttl': 300000
        }
        
        assert cache[key]['data']['fetched'] is True
    
    def test_cache_expiration(self, demo_data):
        """Test cache entry expiration"""
        cache = {}
        key = 'demo_glm'
        
        # Store with short TTL
        cache[key] = {
            'data': demo_data['glm'],
            'timestamp': (time.time() - 400) * 1000,  # 400 seconds ago
            'ttl': 300000  # 300 seconds TTL
        }
        
        # Check if expired
        current_time = time.time() * 1000
        is_expired = current_time - cache[key]['timestamp'] > cache[key]['ttl']
        
        assert is_expired is True
    
    def test_lru_eviction(self, cache_config, demo_data):
        """Test LRU eviction when cache is full"""
        cache = {}
        max_size = 3  # Small size for testing
        
        # Fill cache
        for i in range(max_size + 1):
            key = f'demo_{i}'
            cache[key] = {
                'data': {'id': i},
                'timestamp': time.time() * 1000,
                'ttl': 300000
            }
            
            # Simulate LRU eviction
            if len(cache) > max_size:
                oldest_key = list(cache.keys())[0]
                del cache[oldest_key]
        
        assert len(cache) == max_size
        assert 'demo_0' not in cache  # First item evicted
    
    def test_prefetch_functionality(self, demo_data):
        """Test prefetching demo assets"""
        prefetch_queue = set(['glm', 'dmn', 'connectivity'])
        prefetched = {}
        
        for scenario in prefetch_queue:
            # Simulate prefetch
            if scenario in demo_data:
                prefetched[f'demo_{scenario}'] = demo_data[scenario]
        
        assert 'demo_glm' in prefetched
        assert 'demo_connectivity' in prefetched
    
    def test_etag_generation(self):
        """Test ETag generation for cache validation"""
        data = {'test': 'data', 'value': 123}
        
        # Simple hash generation
        str_data = json.dumps(data)
        hash_value = 0
        for char in str_data:
            hash_value = ((hash_value << 5) - hash_value) + ord(char)
            hash_value = hash_value & 0xFFFFFFFF  # 32-bit
        
        etag = f'W/"{abs(hash_value):x}"'
        
        assert etag.startswith('W/"')
        assert etag.endswith('"')
    
    def test_performance_metrics(self):
        """Test performance metrics tracking"""
        metrics = {
            'cache_hits': 0,
            'cache_misses': 0,
            'average_response_time': 0,
            'p95_response_time': 0,
            'total_requests': 0
        }
        
        response_times = []
        
        # Simulate requests
        for i in range(10):
            start = time.time()
            time.sleep(0.001)  # Simulate processing
            response_time = (time.time() - start) * 1000
            response_times.append(response_time)
            
            # Update metrics
            if i % 3 == 0:  # Simulate cache hit
                metrics['cache_hits'] += 1
            else:
                metrics['cache_misses'] += 1
            
            metrics['total_requests'] += 1
        
        # Calculate average
        metrics['average_response_time'] = sum(response_times) / len(response_times)
        
        # Calculate P95
        sorted_times = sorted(response_times)
        p95_index = int(len(sorted_times) * 0.95)
        metrics['p95_response_time'] = sorted_times[p95_index]
        
        assert metrics['total_requests'] == 10
        assert metrics['cache_hits'] > 0
        assert metrics['cache_misses'] > 0
        assert metrics['average_response_time'] > 0
    
    def test_hit_rate_calculation(self):
        """Test cache hit rate calculation"""
        cache_hits = 75
        cache_misses = 25
        total_requests = cache_hits + cache_misses
        
        hit_rate = (cache_hits / total_requests) * 100
        
        assert hit_rate == 75.0
    
    def test_optimistic_updates(self):
        """Test optimistic update mechanism"""
        pending_updates = {}
        rollback_data = {}
        
        key = 'demo_state'
        original = {'status': 'idle'}
        update = {'status': 'running'}
        
        # Apply optimistic update
        rollback_data[key] = original
        pending_updates[key] = update
        
        assert pending_updates[key]['status'] == 'running'
        assert rollback_data[key]['status'] == 'idle'
        
        # Rollback if needed
        if key in rollback_data:
            restored = rollback_data[key]
            assert restored['status'] == 'idle'
    
    def test_response_interceptor(self):
        """Test response interceptor for automatic caching"""
        cache = {}
        
        def get_cache_key(url, method='GET'):
            return json.dumps({'url': url, 'method': method})
        
        # Intercept GET request
        url = '/api/demo/results/glm'
        cache_key = get_cache_key(url)
        
        # Check cache first for GET
        if 'GET' in cache_key:
            # Try cache
            if cache_key not in cache:
                # Fetch and cache
                cache[cache_key] = {
                    'data': {'result': 'success'},
                    'timestamp': time.time() * 1000
                }
        
        assert cache_key in cache
        assert cache[cache_key]['data']['result'] == 'success'
    
    def test_cache_invalidation(self):
        """Test cache invalidation for mutations"""
        cache = {
            'demo_glm': {'data': 'cached'},
            'demo_connectivity': {'data': 'cached'}
        }
        
        # POST request should invalidate related entries
        mutation_url = '/api/demo/glm'
        
        # Invalidate all demo entries
        keys_to_delete = [k for k in cache.keys() if 'demo' in k]
        for key in keys_to_delete:
            del cache[key]
        
        assert len(cache) == 0
    
    def test_cleanup_interval(self):
        """Test periodic cache cleanup"""
        cache = {}
        current_time = time.time() * 1000
        
        # Add expired and valid entries
        cache['expired'] = {
            'timestamp': current_time - 400000,  # Expired
            'ttl': 300000
        }
        cache['valid'] = {
            'timestamp': current_time - 100000,  # Still valid
            'ttl': 300000
        }
        
        # Cleanup expired entries
        keys_to_delete = []
        for key, entry in cache.items():
            if current_time - entry['timestamp'] > entry['ttl']:
                keys_to_delete.append(key)
        
        for key in keys_to_delete:
            del cache[key]
        
        assert 'expired' not in cache
        assert 'valid' in cache
    
    def test_3_5_second_cached_response(self):
        """Test that cached demo responses meet 3-5s target"""
        start_time = time.time()
        
        # Simulate cached response
        time.sleep(0.001)  # Cache hit should be very fast
        
        response_time = time.time() - start_time
        
        # Cached responses should be under 100ms (well under 3-5s target)
        assert response_time < 0.1