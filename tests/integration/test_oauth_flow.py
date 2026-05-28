"""Integration tests for OAuth authentication flow"""

import pytest
import httpx
from unittest.mock import patch, MagicMock
import json
import secrets
from datetime import datetime

# Test configuration
TEST_BASE_URL = "http://localhost:3001"
TEST_FRONTEND_URL = "http://localhost:3000"

@pytest.fixture
def test_client():
    """Create a test client for the FastAPI app"""
    return httpx.Client(base_url=TEST_BASE_URL)

@pytest.fixture
def mock_oauth_config():
    """Mock OAuth configuration"""
    return {
        'google': {
            'client_id': 'test-google-client-id',
            'client_secret': 'test-google-secret',
            'authorize_url': 'https://accounts.google.com/o/oauth2/v2/auth',
            'token_url': 'https://oauth2.googleapis.com/token',
            'userinfo_url': 'https://www.googleapis.com/oauth2/v2/userinfo',
            'scopes': ['openid', 'email', 'profile']
        },
        'microsoft': {
            'client_id': 'test-azure-client-id',
            'client_secret': 'test-azure-secret',
            'tenant': 'organizations',
            'authorize_url': 'https://login.microsoftonline.com/organizations/oauth2/v2.0/authorize',
            'token_url': 'https://login.microsoftonline.com/organizations/oauth2/v2.0/token',
            'userinfo_url': 'https://graph.microsoft.com/v1.0/me',
            'scopes': ['openid', 'email', 'profile', 'User.Read']
        },
        'github': {
            'client_id': 'test-github-client-id',
            'client_secret': 'test-github-secret',
            'authorize_url': 'https://github.com/login/oauth/authorize',
            'token_url': 'https://github.com/login/oauth/access_token',
            'userinfo_url': 'https://api.github.com/user',
            'scopes': ['read:user', 'user:email']
        }
    }

class TestOAuthAuthorization:
    """Test OAuth authorization flow initiation"""
    
    def test_google_authorize_redirect(self, test_client):
        """Test Google OAuth authorization redirect"""
        response = test_client.get(
            "/auth/oauth/google/authorize",
            follow_redirects=False
        )
        
        assert response.status_code == 307  # Redirect
        location = response.headers.get('location')
        assert location
        assert 'accounts.google.com' in location
        assert 'client_id=' in location
        assert 'state=' in location
        assert 'scope=openid+email+profile' in location
    
    def test_microsoft_authorize_redirect(self, test_client):
        """Test Microsoft OAuth authorization redirect"""
        response = test_client.get(
            "/auth/oauth/microsoft/authorize",
            follow_redirects=False
        )
        
        assert response.status_code == 307  # Redirect
        location = response.headers.get('location')
        assert location
        assert 'login.microsoftonline.com' in location
        assert 'organizations' in location  # Default tenant
        assert 'client_id=' in location
        assert 'state=' in location
    
    def test_github_authorize_redirect(self, test_client):
        """Test GitHub OAuth authorization redirect"""
        response = test_client.get(
            "/auth/oauth/github/authorize",
            follow_redirects=False
        )
        
        assert response.status_code == 307  # Redirect
        location = response.headers.get('location')
        assert location
        assert 'github.com/login/oauth/authorize' in location
        assert 'client_id=' in location
        assert 'state=' in location
    
    def test_invalid_provider(self, test_client):
        """Test invalid OAuth provider"""
        response = test_client.get("/auth/oauth/invalid/authorize")
        assert response.status_code == 400
        assert 'Unsupported provider' in response.text

class TestOAuthCallback:
    """Test OAuth callback handling"""
    
    @patch('httpx.AsyncClient.post')
    @patch('httpx.AsyncClient.get')
    async def test_google_callback_success(self, mock_get, mock_post, test_client):
        """Test successful Google OAuth callback"""
        # Mock token exchange
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                'access_token': 'test-access-token',
                'refresh_token': 'test-refresh-token',
                'expires_in': 3600
            }
        )
        
        # Mock user info
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                'id': '12345',
                'email': 'test@gmail.com',
                'name': 'Test User',
                'picture': 'https://example.com/photo.jpg',
                'verified_email': True
            }
        )
        
        # Create a valid state
        state = secrets.token_urlsafe(32)
        # Would need to inject state into the app's state storage
        
        response = test_client.get(
            f"/auth/oauth/google/callback?code=test-code&state={state}",
            follow_redirects=False
        )
        
        # Should redirect to frontend with tokens
        assert response.status_code == 307
        location = response.headers.get('location')
        assert location
        assert TEST_FRONTEND_URL in location
        assert 'access_token=' in location
    
    def test_callback_with_error(self, test_client):
        """Test OAuth callback with error"""
        response = test_client.get(
            "/auth/oauth/google/callback?error=access_denied&error_description=User+denied+access",
            follow_redirects=False
        )
        
        assert response.status_code == 307
        location = response.headers.get('location')
        assert '/auth/error' in location
    
    def test_callback_invalid_state(self, test_client):
        """Test OAuth callback with invalid state"""
        response = test_client.get(
            "/auth/oauth/google/callback?code=test-code&state=invalid-state"
        )
        
        assert response.status_code == 400
        assert 'Invalid state' in response.text

class TestMagicLink:
    """Test Magic Link authentication"""
    
    def test_send_magic_link(self, test_client):
        """Test sending a magic link"""
        response = test_client.post(
            "/auth/oauth/magic-link/send",
            json={"email": "test@example.com"}
        )
        
        # In test mode without email config, should still return success
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert 'Magic link sent' in data['message']
    
    def test_magic_link_rate_limit(self, test_client):
        """Test magic link rate limiting"""
        email = "ratelimit@example.com"
        
        # Send multiple requests
        for i in range(3):
            response = test_client.post(
                "/auth/oauth/magic-link/send",
                json={"email": email}
            )
            assert response.status_code == 200
        
        # Fourth request should be rate limited
        # Note: This requires Redis to be running
        # response = test_client.post(
        #     "/auth/oauth/magic-link/send",
        #     json={"email": email}
        # )
        # assert response.status_code == 429
    
    @patch('brain_researcher.services.orchestrator.magic_link.MagicLinkService.verify_magic_link')
    async def test_verify_magic_link_success(self, mock_verify, test_client):
        """Test successful magic link verification"""
        mock_verify.return_value = "test@example.com"
        
        response = test_client.post(
            "/auth/oauth/magic-link/verify",
            params={"token": "test-token"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert 'access_token' in data
        assert 'refresh_token' in data
        assert data['user']['email'] == "test@example.com"
    
    def test_verify_invalid_magic_link(self, test_client):
        """Test invalid magic link verification"""
        response = test_client.post(
            "/auth/oauth/magic-link/verify",
            params={"token": "invalid-token"}
        )
        
        assert response.status_code == 400
        assert 'Invalid or expired' in response.text

class TestDomainValidation:
    """Test domain validation for Microsoft OAuth"""
    
    def test_allowed_domain_validation(self):
        """Test email domain validation"""
        from brain_researcher.services.orchestrator.oauth_config import OAuthConfig
        
        # Mock allowed domains
        OAuthConfig.ALLOWED_DOMAINS = ['stanford.edu', 'mit.edu']
        
        # Test valid domains
        assert OAuthConfig.validate_email_domain('user@stanford.edu', 'microsoft') is True
        assert OAuthConfig.validate_email_domain('user@mit.edu', 'microsoft') is True
        
        # Test invalid domain
        assert OAuthConfig.validate_email_domain('user@gmail.com', 'microsoft') is False
        
        # Test non-Microsoft provider (should always pass)
        assert OAuthConfig.validate_email_domain('user@gmail.com', 'google') is True
        
        # Reset
        OAuthConfig.ALLOWED_DOMAINS = []

if __name__ == "__main__":
    pytest.main([__file__, "-v"])