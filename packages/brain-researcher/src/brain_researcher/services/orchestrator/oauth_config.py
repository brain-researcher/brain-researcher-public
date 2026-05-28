"""OAuth Provider Configuration for Brain Researcher"""

from typing import Optional, List, Dict, Any
import os
from enum import Enum

class OAuthProvider(str, Enum):
    GOOGLE = "google"
    MICROSOFT = "microsoft"
    GITHUB = "github"
    EMAIL = "email"

class OAuthConfig:
    """OAuth provider configurations for Google, Microsoft, and GitHub"""
    
    # Provider configurations - using @classmethod to read env vars at runtime
    @classmethod
    def _get_providers(cls) -> Dict[str, Dict[str, Any]]:
        """Get provider configurations (reads env vars at runtime)"""
        return {
            'google': {
                'client_id': os.getenv('GOOGLE_CLIENT_ID'),
                'client_secret': os.getenv('GOOGLE_CLIENT_SECRET'),
                'authorize_url': 'https://accounts.google.com/o/oauth2/v2/auth',
                'token_url': 'https://oauth2.googleapis.com/token',
                'userinfo_url': 'https://www.googleapis.com/oauth2/v2/userinfo',
                'scopes': ['openid', 'email', 'profile'],
                'response_type': 'code',
                'access_type': 'offline',
                'prompt': 'consent'
            },
            'microsoft': {
                'client_id': os.getenv('AZURE_AD_CLIENT_ID'),
                'client_secret': os.getenv('AZURE_AD_CLIENT_SECRET'),
                'tenant': os.getenv('AZURE_AD_TENANT_ID', 'organizations'),  # default to organizations
                'authorize_url': 'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize',
                'token_url': 'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token',
                'userinfo_url': 'https://graph.microsoft.com/v1.0/me',
                'scopes': ['openid', 'email', 'profile', 'User.Read'],
                'response_type': 'code',
                'prompt': 'select_account'
            },
            'github': {
                'client_id': os.getenv('GITHUB_CLIENT_ID'),
                'client_secret': os.getenv('GITHUB_CLIENT_SECRET'),
                'authorize_url': 'https://github.com/login/oauth/authorize',
                'token_url': 'https://github.com/login/oauth/access_token',
                'userinfo_url': 'https://api.github.com/user',
                'userinfo_email_url': 'https://api.github.com/user/emails',  # GitHub requires separate call for email
                'scopes': ['read:user', 'user:email'],
            }
        }
    
    # Domain allowlist for Microsoft (universities)
    ALLOWED_DOMAINS: List[str] = []
    
    def __init__(self):
        """Initialize OAuth configuration"""
        # Load allowed domains from environment
        domains = os.getenv('ALLOWED_DOMAINS', '')
        if domains:
            self.ALLOWED_DOMAINS = [d.strip() for d in domains.split(',')]
    
    @classmethod
    def get_provider_config(cls, provider: str) -> Optional[Dict[str, Any]]:
        """Get configuration for a specific provider"""
        config = cls._get_providers().get(provider)
        if not config:
            return None

        # Handle Microsoft tenant in URLs
        if provider == 'microsoft':
            tenant = config['tenant']
            config = config.copy()
            config['authorize_url'] = config['authorize_url'].format(tenant=tenant)
            config['token_url'] = config['token_url'].format(tenant=tenant)

        return config
    
    @classmethod
    def validate_email_domain(cls, email: str, provider: str) -> bool:
        """
        Validate email domain against allowlist.
        Only applies to Microsoft provider when ALLOWED_DOMAINS is configured.
        """
        if provider != 'microsoft' or not cls.ALLOWED_DOMAINS:
            return True
        
        if '@' not in email:
            return False
        
        domain = email.split('@')[1].lower()
        return domain in [d.lower() for d in cls.ALLOWED_DOMAINS]
    
    @classmethod
    def get_redirect_uri(cls, provider: str) -> str:
        """Get the redirect URI for a provider (reads env var at runtime)"""
        # Read environment variable at runtime to ensure load_dotenv() has been called
        base_url = os.getenv('OAUTH_REDIRECT_BASE_URL', 'http://localhost:3001')
        return f"{base_url}/auth/oauth/{provider}/callback"
    
    @classmethod
    def is_provider_configured(cls, provider: str) -> bool:
        """Check if a provider is properly configured with credentials"""
        config = cls._get_providers().get(provider)
        if not config:
            return False

        # Check required credentials
        if provider == 'google':
            return bool(config['client_id'] and config['client_secret'])
        elif provider == 'microsoft':
            return bool(config['client_id'] and config['client_secret'])
        elif provider == 'github':
            return bool(config['client_id'] and config['client_secret'])

        return False
    
    @classmethod
    def get_configured_providers(cls) -> List[str]:
        """Get list of all properly configured providers"""
        return [
            provider for provider in cls._get_providers().keys()
            if cls.is_provider_configured(provider)
        ]
    
    @classmethod
    def parse_user_info(cls, provider: str, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse user info from provider response into standard format"""
        
        if provider == 'google':
            return {
                'provider_id': user_data.get('id'),
                'email': user_data.get('email'),
                'name': user_data.get('name'),
                'picture': user_data.get('picture'),
                'verified_email': user_data.get('verified_email', False)
            }
        
        elif provider == 'microsoft':
            return {
                'provider_id': user_data.get('id'),
                'email': user_data.get('mail') or user_data.get('userPrincipalName'),
                'name': user_data.get('displayName'),
                'picture': None,  # Microsoft Graph requires separate call for photo
                'organization': user_data.get('companyName'),
                'department': user_data.get('department'),
                'job_title': user_data.get('jobTitle')
            }
        
        elif provider == 'github':
            return {
                'provider_id': str(user_data.get('id')),
                'email': user_data.get('email'),  # May be null if private
                'name': user_data.get('name') or user_data.get('login'),
                'picture': user_data.get('avatar_url'),
                'github_username': user_data.get('login'),
                'company': user_data.get('company'),
                'bio': user_data.get('bio')
            }
        
        return {}