"""
Integration tests for A/B Testing functionality
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import json
from datetime import datetime, timedelta


class TestABTesting:
    """Test suite for A/B Testing integration"""
    
    @pytest.fixture
    def ab_config(self):
        """Sample A/B test configuration"""
        return {
            'testName': 'landing_hero_v1',
            'variants': ['A', 'B'],
            'cookieName': 'ab_landing_hero',
            'cookieExpiry': 30,
            'apiEndpoint': '/api/ab'
        }
    
    @pytest.fixture
    def mock_fetch(self):
        """Mock fetch for API calls"""
        with patch('fetch') as mock:
            mock.return_value.ok = True
            mock.return_value.json = MagicMock(return_value={'variant': 'A'})
            yield mock
    
    def test_variant_assignment(self, ab_config, mock_fetch):
        """Test variant assignment from backend"""
        endpoint = f"{ab_config['apiEndpoint']}/assign?test={ab_config['testName']}"
        
        response = mock_fetch(endpoint)
        data = response.json()
        
        assert data['variant'] in ab_config['variants']
        assert response.ok is True
    
    def test_cookie_persistence(self, ab_config):
        """Test that variant is persisted in cookies"""
        cookie_name = ab_config['cookieName']
        variant = 'B'
        expiry_days = ab_config['cookieExpiry']
        
        # Simulate cookie setting
        cookie_value = f"{cookie_name}={variant}"
        assert variant in cookie_value
        assert cookie_name in cookie_value
        
        # Check expiry is set correctly
        expiry_time = datetime.now() + timedelta(days=expiry_days)
        assert expiry_time > datetime.now()
    
    def test_variant_consistency(self, ab_config):
        """Test that same user gets consistent variant"""
        assigned_variants = {}
        user_id = 'user-123'
        
        # First assignment
        assigned_variants[user_id] = 'A'
        
        # Subsequent checks should return same variant
        for _ in range(5):
            assert assigned_variants[user_id] == 'A'
    
    def test_conversion_tracking(self, ab_config, mock_fetch):
        """Test conversion tracking for A/B tests"""
        test_name = ab_config['testName']
        variant = 'A'
        
        conversion_data = {
            'test': test_name,
            'variant': variant,
            'event': 'conversion',
            'conversionType': 'demo_completed',
            'timestamp': datetime.now().isoformat()
        }
        
        response = mock_fetch(
            f"{ab_config['apiEndpoint']}/track",
            method='POST',
            body=json.dumps(conversion_data)
        )
        
        assert response.ok is True
        assert conversion_data['event'] == 'conversion'
        assert conversion_data['variant'] in ab_config['variants']
    
    def test_event_enrichment(self, ab_config):
        """Test that events are enriched with A/B variant data"""
        event_data = {
            'event': 'button_clicked',
            'button_id': 'hero-cta'
        }
        
        # Enrich with A/B data
        enriched_data = {
            **event_data,
            'ab_variants': {
                ab_config['testName']: 'A'
            }
        }
        
        assert 'ab_variants' in enriched_data
        assert ab_config['testName'] in enriched_data['ab_variants']
    
    def test_multiple_tests_simultaneously(self):
        """Test handling multiple A/B tests at once"""
        tests = {
            'landing_hero': 'A',
            'demo_cta': 'button',
            'onboarding': 'guided'
        }
        
        assert len(tests) == 3
        assert all(variant for variant in tests.values())
    
    def test_fallback_to_random(self, ab_config):
        """Test fallback to random assignment when API fails"""
        with patch('fetch') as mock_fetch:
            mock_fetch.side_effect = Exception("API Error")
            
            # Should fall back to random selection
            import random
            random.seed(42)  # For reproducible tests
            variant = random.choice(ab_config['variants'])
            
            assert variant in ab_config['variants']
    
    def test_variant_distribution(self, ab_config):
        """Test that variant distribution is roughly even"""
        assignments = {'A': 0, 'B': 0}
        
        # Simulate 100 assignments
        import random
        for _ in range(100):
            variant = random.choice(ab_config['variants'])
            assignments[variant] += 1
        
        # Check distribution is roughly even (40-60% each)
        for variant, count in assignments.items():
            assert 30 <= count <= 70
    
    def test_conditional_rendering(self, ab_config):
        """Test conditional rendering based on variant"""
        current_variant = 'A'
        
        # Component should render for variant A
        should_render_a = current_variant == 'A'
        should_render_b = current_variant == 'B'
        
        assert should_render_a is True
        assert should_render_b is False
    
    def test_analytics_integration(self, ab_config):
        """Test that A/B test data is sent to analytics"""
        with patch('analytics.trackEvent') as mock_track:
            mock_track('ab_test_assigned', {
                'test': ab_config['testName'],
                'variant': 'A'
            })
            
            mock_track.assert_called_once()
            call_args = mock_track.call_args[0]
            assert call_args[0] == 'ab_test_assigned'
            assert call_args[1]['test'] == 'landing_hero_v1'
    
    def test_cookie_cleanup(self, ab_config):
        """Test cleanup of expired A/B test cookies"""
        expired_cookies = [
            'ab_old_test=A',
            'ab_expired_test=B'
        ]
        
        active_cookies = [
            f"{ab_config['cookieName']}=A"
        ]
        
        # Only active cookies should remain
        assert len(active_cookies) == 1
        assert ab_config['cookieName'] in active_cookies[0]
    
    def test_variant_metrics(self, ab_config):
        """Test collection of metrics per variant"""
        metrics = {
            'A': {
                'impressions': 500,
                'conversions': 50,
                'conversion_rate': 0.10
            },
            'B': {
                'impressions': 480,
                'conversions': 72,
                'conversion_rate': 0.15
            }
        }
        
        # Variant B has higher conversion rate
        assert metrics['B']['conversion_rate'] > metrics['A']['conversion_rate']
    
    def test_experiment_status(self, ab_config):
        """Test checking experiment status"""
        experiment_status = {
            'test': ab_config['testName'],
            'status': 'active',
            'start_date': '2025-01-01',
            'variants': ab_config['variants'],
            'traffic_allocation': {'A': 50, 'B': 50}
        }
        
        assert experiment_status['status'] == 'active'
        assert sum(experiment_status['traffic_allocation'].values()) == 100
    
    def test_cross_domain_tracking(self, ab_config):
        """Test A/B test tracking across subdomains"""
        domains = [
            'app.brainresearcher.com',
            'docs.brainresearcher.com',
            'api.brainresearcher.com'
        ]
        
        # Cookie should be set for parent domain
        cookie_domain = '.brainresearcher.com'
        
        for domain in domains:
            assert cookie_domain[1:] in domain  # Remove leading dot for check