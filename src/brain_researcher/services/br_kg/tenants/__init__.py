"""
Multi-tenant support for BR-KG

Provides tenant-based data isolation, resource quotas, and usage tracking.
"""

from .isolation import DataIsolationManager
from .manager import TenantManager
from .quotas import ResourceQuotaManager

__all__ = ["TenantManager", "DataIsolationManager", "ResourceQuotaManager"]
