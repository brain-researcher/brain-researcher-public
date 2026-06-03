"""
Orchestrator Service Configuration
"""

import os
from enum import Enum


class DemoMode(str, Enum):
    """Demo mode for controlling legacy demo endpoints"""
    PRODUCTION = "production"
    DEVELOPMENT = "development"


class OrchestratorConfig:
    """Configuration for orchestrator service"""

    # Demo mode - controls whether legacy fake demo endpoints are accessible
    DEMO_MODE: DemoMode = DemoMode(
        os.getenv("BR_DEMO_MODE", "production").lower()
    )

    # BR-KG service URL
    BR_KG_URL: str = os.getenv("BR_KG_URL", "http://localhost:5000")

    # Redis URL for caching; fall back to local Redis if unset
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    @classmethod
    def is_development_mode(cls) -> bool:
        """Check if running in development mode"""
        return cls.DEMO_MODE == DemoMode.DEVELOPMENT

    @classmethod
    def is_production_mode(cls) -> bool:
        """Check if running in production mode"""
        return cls.DEMO_MODE == DemoMode.PRODUCTION


# Singleton instance
config = OrchestratorConfig()
