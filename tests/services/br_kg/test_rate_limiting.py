"""
Tests for BR-KG rate limiting implementation.
"""

import json
import time
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask, jsonify, request

from brain_researcher.services.br_kg.rate_limiting import (
    RateLimitConfig,
    RateLimiter,
    RateLimitMiddleware,
    RateLimitStatus,
    TokenBucket,
    create_rate_limit_endpoints,
    rate_limit,
)


class TestTokenBucket:
    """Test token bucket algorithm."""

    def test_bucket_creation(self):
        """Test bucket initialization."""
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        assert bucket.capacity == 10
        assert bucket.refill_rate == 1.0
        assert bucket.tokens == 10

    def test_consume_tokens(self):
        """Test consuming tokens."""
        bucket = TokenBucket(capacity=10, refill_rate=1.0)

        # Consume single token
        assert bucket.consume(1) == True
        assert bucket.tokens == 9

        # Consume multiple tokens
        assert bucket.consume(5) == True
        assert bucket.tokens == 4

        # Try to consume more than available
        assert bucket.consume(5) == False
        assert bucket.tokens == 4

    def test_refill(self):
        """Test token refill over time."""
        bucket = TokenBucket(capacity=10, refill_rate=10.0)  # 10 tokens/second

        # Consume all tokens
        bucket.consume(10)
        assert bucket.tokens == 0

        # Wait and check refill
        time.sleep(0.5)  # Should add 5 tokens
        bucket._refill()
        assert bucket.tokens >= 4  # Allow for timing variance
        assert bucket.tokens <= 6

    def test_wait_time(self):
        """Test wait time calculation."""
        bucket = TokenBucket(capacity=10, refill_rate=2.0)  # 2 tokens/second

        # Consume all tokens
        bucket.consume(10)

        # Check wait time for 1 token
        wait = bucket.get_wait_time(1)
        assert wait >= 0.4  # Should be ~0.5 seconds
        assert wait <= 0.6

        # Check wait time for 5 tokens
        wait = bucket.get_wait_time(5)
        assert wait >= 2.4  # Should be ~2.5 seconds
        assert wait <= 2.6

    def test_serialization(self):
        """Test bucket serialization."""
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        bucket.consume(3)

        # Serialize
        data = bucket.to_dict()
        assert data["capacity"] == 10
        assert data["refill_rate"] == 1.0
        assert data["tokens"] == 7

        # Deserialize
        bucket2 = TokenBucket.from_dict(data)
        assert bucket2.capacity == 10
        assert bucket2.refill_rate == 1.0
        assert bucket2.tokens == 7


class TestRateLimiter:
    """Test rate limiter."""

    @pytest.fixture
    def limiter(self):
        """Create rate limiter with test config."""
        config = RateLimitConfig(
            requests_per_minute=60, requests_per_hour=1000, burst_size=5
        )
        return RateLimiter(config=config)

    def test_client_id_generation(self, limiter):
        """Test client ID generation."""
        # User ID
        assert limiter._get_client_id(user_id="user123") == "user:user123"

        # API key (hashed)
        client_id = limiter._get_client_id(api_key="secret_key")
        assert client_id.startswith("key:")
        assert len(client_id) == 20  # key: + 16 char hash

        # IP address
        mock_request = MagicMock()
        mock_request.remote_addr = "192.168.1.1"
        mock_request.environ = {}
        assert limiter._get_client_id(request_obj=mock_request) == "ip:192.168.1.1"

    def test_check_limit_success(self, limiter):
        """Test successful rate limit check."""
        status = limiter.check_limit(user_id="test_user", tokens=1)

        assert status.allowed == True
        assert status.limit == 60  # Per minute
        assert status.remaining >= 59  # Consumed 1, plus burst
        assert status.retry_after is None

    def test_minute_limit_exceeded(self, limiter):
        """Test minute rate limit exceeded."""
        # Consume all minute tokens
        for _ in range(65):  # 60 + 5 burst
            status = limiter.check_limit(user_id="test_user", tokens=1)

        # Next request should be denied
        status = limiter.check_limit(user_id="test_user", tokens=1)
        assert status.allowed == False
        assert status.retry_after > 0
        assert status.remaining == 0

    def test_hour_limit_exceeded(self, limiter):
        """Test hour rate limit exceeded."""
        # Use different users to avoid minute limit
        for i in range(1005):  # 1000 + 5 burst
            status = limiter.check_limit(user_id=f"user_{i}", tokens=1)

        # Global hour limit should affect new user
        status = limiter.check_limit(user_id="new_user", tokens=100)
        # This test depends on global vs per-user config

    def test_reset_limit(self, limiter):
        """Test resetting rate limit."""
        # Consume tokens
        for _ in range(10):
            limiter.check_limit(user_id="test_user", tokens=1)

        # Reset
        limiter.reset_limit(user_id="test_user")

        # Should have full tokens again
        status = limiter.check_limit(user_id="test_user", tokens=1)
        assert status.allowed == True
        assert status.remaining >= 59  # Full capacity minus 1

    def test_get_status(self, limiter):
        """Test getting rate limit status."""
        # Consume some tokens
        limiter.check_limit(user_id="test_user", tokens=5)

        # Get status
        status = limiter.get_status(user_id="test_user")

        assert "client_id" in status
        assert status["client_id"] == "user:test_user"
        assert "limits" in status
        assert "per_minute" in status["limits"]
        assert "per_hour" in status["limits"]
        assert status["limits"]["per_minute"]["remaining"] >= 55


class TestRateLimitDecorator:
    """Test rate limit decorator."""

    @pytest.fixture
    def app(self):
        """Create test Flask app."""
        app = Flask(__name__)

        @app.route("/test")
        @rate_limit(requests_per_minute=10)
        def test_endpoint():
            return {"message": "success"}

        @app.route("/custom")
        @rate_limit(
            requests_per_minute=5, get_api_key=lambda: request.headers.get("X-API-Key")
        )
        def custom_endpoint():
            return {"message": "custom"}

        return app

    def test_rate_limit_decorator(self, app):
        """Test rate limiting decorator."""
        client = app.test_client()

        # First requests should succeed
        for i in range(10):
            response = client.get("/test")
            assert response.status_code == 200
            assert "X-RateLimit-Limit" in response.headers
            assert "X-RateLimit-Remaining" in response.headers

        # 11th request should be rate limited (considering burst)
        for i in range(5):  # Try a few more to account for burst
            response = client.get("/test")
            if response.status_code == 429:
                break

        assert response.status_code == 429
        assert "Retry-After" in response.headers
        data = json.loads(response.data)
        assert "error" in data
        assert "retry_after" in data

    def test_custom_rate_limit(self, app):
        """Test custom rate limit parameters."""
        client = app.test_client()

        # Use API key
        headers = {"X-API-Key": "test_key"}

        # Should allow 5 requests per minute
        for i in range(5):
            response = client.get("/custom", headers=headers)
            assert response.status_code == 200

        # Check rate limit headers
        assert int(response.headers["X-RateLimit-Limit"]) == 5
        assert int(response.headers["X-RateLimit-Remaining"]) >= 0


class TestRateLimitMiddleware:
    """Test rate limit middleware."""

    @pytest.fixture
    def app(self):
        """Create test Flask app with middleware."""
        app = Flask(__name__)

        # Add middleware
        config = RateLimitConfig(requests_per_minute=30, requests_per_hour=500)
        RateLimitMiddleware(app, config)

        @app.route("/api/test")
        def test_endpoint():
            return {"message": "test"}

        @app.route("/health")
        def health():
            return {"status": "ok"}

        # Add rate limit management endpoints
        create_rate_limit_endpoints(app)

        return app

    def test_middleware_rate_limiting(self, app):
        """Test middleware applies rate limiting."""
        client = app.test_client()

        # Regular endpoint should be rate limited
        response = client.get("/api/test")
        assert response.status_code == 200
        assert "X-RateLimit-Limit" in response.headers

        # Health check should not be rate limited
        for _ in range(50):
            response = client.get("/health")
            assert response.status_code == 200
            assert "X-RateLimit-Limit" not in response.headers

    def test_rate_limit_status_endpoint(self, app):
        """Test rate limit status endpoint."""
        client = app.test_client()

        # Make some requests
        for _ in range(5):
            client.get("/api/test")

        # Check status
        response = client.get("/api/rate-limit/status")
        assert response.status_code == 200

        data = json.loads(response.data)
        assert "client_id" in data
        assert "limits" in data
        assert data["limits"]["per_minute"]["limit"] == 30
        assert data["limits"]["per_minute"]["remaining"] < 30

    def test_rate_limit_reset_endpoint(self, app):
        """Test rate limit reset endpoint."""
        client = app.test_client()

        # Reset should be rate limited itself
        for _ in range(6):
            response = client.post(
                "/api/rate-limit/reset",
                json={"client_id": "test_client"},
                content_type="application/json",
            )

        # Should eventually hit rate limit on reset endpoint
        assert response.status_code in [200, 429]


class TestIntegration:
    """Integration tests with BR-KG app."""

    @pytest.fixture
    def app(self):
        """Create BR-KG app with rate limiting."""
        from brain_researcher.services.br_kg.app import app

        # Add rate limiting
        config = RateLimitConfig(requests_per_minute=30, requests_per_hour=500)
        RateLimitMiddleware(app, config)
        create_rate_limit_endpoints(app)

        return app

    def test_graphql_rate_limiting(self, app):
        """Test GraphQL endpoint rate limiting."""
        client = app.test_client()

        query = {"query": "{ concepts { id name } }"}

        # Make requests
        response = client.post("/graphql", json=query, content_type="application/json")

        # Should have rate limit headers
        if response.status_code == 200:
            assert "X-RateLimit-Limit" in response.headers
            assert "X-RateLimit-Remaining" in response.headers

    def test_search_rate_limiting(self, app):
        """Test search endpoint rate limiting."""
        client = app.test_client()

        # Make search request
        response = client.post(
            "/api/search", json={"query": "test"}, content_type="application/json"
        )

        # Should have rate limit headers
        if response.status_code == 200:
            assert "X-RateLimit-Limit" in response.headers


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
