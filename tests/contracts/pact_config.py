"""
Pact configuration for Brain Researcher contract testing.
"""

import os
from pathlib import Path
from typing import Dict, Any, List
from pydantic import BaseModel, Field


LEGACY_GATEWAY_CONTRACT_ENV = "BR_ENABLE_LEGACY_GATEWAY_TESTS"


def legacy_gateway_contracts_enabled() -> bool:
    """Return whether legacy API gateway contract coverage is explicitly enabled."""
    return os.getenv(LEGACY_GATEWAY_CONTRACT_ENV, "0").lower() in {"1", "true", "yes", "on"}


class PactBrokerConfig(BaseModel):
    """Configuration for Pact Broker."""
    broker_base_url: str = Field(default="http://localhost:9292")
    broker_username: str = Field(default="pact_workshop")
    broker_password: str = Field(default="pact_workshop")
    publish_verification_results: bool = True
    
    @classmethod
    def from_env(cls) -> "PactBrokerConfig":
        """Create config from environment variables."""
        return cls(
            broker_base_url=os.getenv("PACT_BROKER_BASE_URL", "http://localhost:9292"),
            broker_username=os.getenv("PACT_BROKER_USERNAME", "pact_workshop"),
            broker_password=os.getenv("PACT_BROKER_PASSWORD", "pact_workshop"),
            publish_verification_results=os.getenv("PACT_PUBLISH_VERIFICATION_RESULTS", "true").lower() == "true"
        )


class ServiceConfig(BaseModel):
    """Configuration for a service."""
    name: str
    version: str
    base_url: str
    health_endpoint: str = "/health"
    
    
class PactConfig(BaseModel):
    """Main Pact configuration."""
    pact_dir: Path = Field(default=Path(__file__).parent / "pacts")
    log_level: str = "INFO"
    pact_specification_version: str = "4.0"
    
    # Service configurations
    services: Dict[str, ServiceConfig] = Field(default_factory=lambda: {
        "orchestrator": ServiceConfig(
            name="orchestrator",
            version="1.0.0",
            base_url="http://localhost:3001",
            health_endpoint="/health"
        ),
        "agent": ServiceConfig(
            name="agent-service",
            version="1.0.0", 
            base_url="http://localhost:8000",
            health_endpoint="/health"
        ),
        "neurokg": ServiceConfig(
            name="neurokg-service",
            version="1.0.0",
            base_url="http://localhost:5000",
            health_endpoint="/health"
        ),
        "web_ui": ServiceConfig(
            name="web-ui",
            version="1.0.0",
            base_url="http://localhost:3000",
            health_endpoint="/api/health"
        ),
        "api_gateway": ServiceConfig(
            name="api-gateway",
            version="1.0.0",
            base_url="http://localhost:8080",
            health_endpoint="/health"
        )
    })
    
    # Consumer-Provider relationships
    consumer_provider_pairs: List[Dict[str, str]] = Field(default_factory=lambda: [
        {"consumer": "web_ui", "provider": "orchestrator"},
        {"consumer": "orchestrator", "provider": "agent"},
        {"consumer": "orchestrator", "provider": "neurokg"},
        {"consumer": "agent", "provider": "neurokg"},
        # Legacy standalone gateway compatibility pairs. These are opt-in only.
        {"consumer": "api_gateway", "provider": "orchestrator"},
        {"consumer": "api_gateway", "provider": "agent"},
        {"consumer": "api_gateway", "provider": "neurokg"}
    ])
    
    # Broker configuration
    broker: PactBrokerConfig = Field(default_factory=PactBrokerConfig.from_env)
    
    def __init__(self, **data):
        super().__init__(**data)
        # Ensure pact directory exists
        self.pact_dir.mkdir(parents=True, exist_ok=True)


# Global configuration instance
pact_config = PactConfig()


def get_consumer_provider_pairs() -> List[tuple]:
    """Get all consumer-provider pairs for testing."""
    pairs = []
    for pair in pact_config.consumer_provider_pairs:
        consumer_config = pact_config.services[pair["consumer"]]
        provider_config = pact_config.services[pair["provider"]]
        pairs.append((consumer_config, provider_config))
    return pairs


def get_pact_file_path(consumer: str, provider: str) -> Path:
    """Get the path for a pact file."""
    return pact_config.pact_dir / f"{consumer}-{provider}.json"


def get_service_config(service_name: str) -> ServiceConfig:
    """Get configuration for a service."""
    if service_name not in pact_config.services:
        raise ValueError(f"Unknown service: {service_name}")
    return pact_config.services[service_name]
