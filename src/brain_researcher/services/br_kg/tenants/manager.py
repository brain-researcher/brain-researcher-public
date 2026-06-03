"""
Tenant Management System for BR-KG

Handles tenant lifecycle, authentication, and configuration.
"""

import logging
import hashlib
import secrets
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Set
from enum import Enum
from dataclasses import dataclass, asdict
import json

logger = logging.getLogger(__name__)


class TenantStatus(Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"
    PROVISIONING = "provisioning"


class TenantTier(Enum):
    FREE = "free"
    BASIC = "basic"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


@dataclass
class TenantConfiguration:
    """Configuration for a tenant"""
    tenant_id: str
    name: str
    description: str
    tier: TenantTier
    status: TenantStatus

    # Resource limits
    max_nodes: int
    max_relationships: int
    max_queries_per_day: int
    max_concurrent_queries: int
    max_storage_mb: int
    max_users: int

    # Features
    sparql_enabled: bool
    federation_enabled: bool
    analytics_enabled: bool
    api_access_enabled: bool

    # Metadata
    created_at: datetime
    updated_at: datetime
    expires_at: Optional[datetime]

    # Contact information
    admin_email: str
    billing_contact: Optional[str]

    # Custom settings
    custom_settings: Dict[str, Any]


@dataclass
class TenantUser:
    """User within a tenant"""
    user_id: str
    tenant_id: str
    username: str
    email: str
    role: str  # admin, editor, viewer
    permissions: Set[str]
    api_key: Optional[str]
    created_at: datetime
    last_active: Optional[datetime]
    is_active: bool


class TenantManager:
    """
    Manages tenant lifecycle, configuration, and authentication
    """

    def __init__(self, neo4j_db, storage_backend=None):
        self.neo4j_db = neo4j_db
        self.storage_backend = storage_backend  # For persistent storage

        # In-memory cache for active tenants
        self.tenant_cache: Dict[str, TenantConfiguration] = {}
        self.user_cache: Dict[str, TenantUser] = {}
        self.api_key_to_user: Dict[str, str] = {}

        # Default tier configurations
        self.tier_configurations = {
            TenantTier.FREE: {
                'max_nodes': 10000,
                'max_relationships': 50000,
                'max_queries_per_day': 1000,
                'max_concurrent_queries': 2,
                'max_storage_mb': 100,
                'max_users': 1,
                'sparql_enabled': True,
                'federation_enabled': False,
                'analytics_enabled': False,
                'api_access_enabled': True
            },
            TenantTier.BASIC: {
                'max_nodes': 100000,
                'max_relationships': 500000,
                'max_queries_per_day': 10000,
                'max_concurrent_queries': 5,
                'max_storage_mb': 1000,
                'max_users': 5,
                'sparql_enabled': True,
                'federation_enabled': True,
                'analytics_enabled': True,
                'api_access_enabled': True
            },
            TenantTier.PROFESSIONAL: {
                'max_nodes': 1000000,
                'max_relationships': 5000000,
                'max_queries_per_day': 100000,
                'max_concurrent_queries': 10,
                'max_storage_mb': 10000,
                'max_users': 20,
                'sparql_enabled': True,
                'federation_enabled': True,
                'analytics_enabled': True,
                'api_access_enabled': True
            },
            TenantTier.ENTERPRISE: {
                'max_nodes': -1,  # Unlimited
                'max_relationships': -1,
                'max_queries_per_day': -1,
                'max_concurrent_queries': 50,
                'max_storage_mb': -1,
                'max_users': -1,
                'sparql_enabled': True,
                'federation_enabled': True,
                'analytics_enabled': True,
                'api_access_enabled': True
            }
        }

        # Initialize schema
        self._initialize_tenant_schema()

        logger.info("Tenant manager initialized")

    def _initialize_tenant_schema(self):
        """Initialize Neo4j schema for tenant management"""

        schema_queries = [
            # Tenant nodes
            "CREATE CONSTRAINT tenant_id_unique IF NOT EXISTS FOR (t:Tenant) REQUIRE t.tenant_id IS UNIQUE",
            "CREATE INDEX tenant_name_idx IF NOT EXISTS FOR (t:Tenant) ON (t.name)",
            "CREATE INDEX tenant_status_idx IF NOT EXISTS FOR (t:Tenant) ON (t.status)",
            "CREATE INDEX tenant_tier_idx IF NOT EXISTS FOR (t:Tenant) ON (t.tier)",

            # User nodes
            "CREATE CONSTRAINT user_id_unique IF NOT EXISTS FOR (u:TenantUser) REQUIRE u.user_id IS UNIQUE",
            "CREATE INDEX user_email_idx IF NOT EXISTS FOR (u:TenantUser) ON (u.email)",
            "CREATE INDEX user_tenant_idx IF NOT EXISTS FOR (u:TenantUser) ON (u.tenant_id)",
            "CREATE INDEX api_key_idx IF NOT EXISTS FOR (u:TenantUser) ON (u.api_key)",

            # Isolation labels for tenant data (per-label indexes are created during tenant operations)
        ]

        for query in schema_queries:
            try:
                self.neo4j_db._run(query)
            except Exception as e:
                logger.warning("Schema creation warning: %s", str(e))

    def create_tenant(
        self,
        name: str,
        admin_email: str,
        tier: TenantTier = TenantTier.FREE,
        description: str = "",
        custom_settings: Optional[Dict[str, Any]] = None
    ) -> TenantConfiguration:
        """Create a new tenant"""

        tenant_id = self._generate_tenant_id(name)

        # Check if tenant already exists
        if self.get_tenant(tenant_id):
            raise ValueError(f"Tenant {tenant_id} already exists")

        # Get tier configuration
        tier_config = self.tier_configurations[tier]

        # Create tenant configuration
        tenant_config = TenantConfiguration(
            tenant_id=tenant_id,
            name=name,
            description=description,
            tier=tier,
            status=TenantStatus.PROVISIONING,
            admin_email=admin_email,
            billing_contact=None,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            expires_at=None,
            custom_settings=custom_settings or {},
            **tier_config
        )

        try:
            # Create tenant in Neo4j
            self._create_tenant_in_database(tenant_config)

            # Create admin user
            admin_user = self._create_admin_user(tenant_config)

            # Initialize tenant workspace
            self._initialize_tenant_workspace(tenant_id)

            # Update status to active
            tenant_config.status = TenantStatus.ACTIVE
            tenant_config.updated_at = datetime.now()
            self._update_tenant_in_database(tenant_config)

            # Cache tenant
            self.tenant_cache[tenant_id] = tenant_config
            self.user_cache[admin_user.user_id] = admin_user
            if admin_user.api_key:
                self.api_key_to_user[admin_user.api_key] = admin_user.user_id

            logger.info("Created tenant %s with admin user %s", tenant_id, admin_user.user_id)
            return tenant_config

        except Exception as e:
            # Cleanup on failure
            try:
                self._cleanup_failed_tenant_creation(tenant_id)
            except:
                pass
            raise ValueError(f"Failed to create tenant: {str(e)}")

    def get_tenant(self, tenant_id: str) -> Optional[TenantConfiguration]:
        """Get tenant configuration"""

        # Check cache first
        if tenant_id in self.tenant_cache:
            return self.tenant_cache[tenant_id]

        # Load from database
        tenant_config = self._load_tenant_from_database(tenant_id)
        if tenant_config:
            self.tenant_cache[tenant_id] = tenant_config

        return tenant_config

    def update_tenant(
        self,
        tenant_id: str,
        updates: Dict[str, Any]
    ) -> Optional[TenantConfiguration]:
        """Update tenant configuration"""

        tenant_config = self.get_tenant(tenant_id)
        if not tenant_config:
            return None

        # Apply updates
        for field, value in updates.items():
            if hasattr(tenant_config, field):
                setattr(tenant_config, field, value)

        tenant_config.updated_at = datetime.now()

        # Update in database
        self._update_tenant_in_database(tenant_config)

        # Update cache
        self.tenant_cache[tenant_id] = tenant_config

        logger.info("Updated tenant %s", tenant_id)
        return tenant_config

    def delete_tenant(self, tenant_id: str, force: bool = False) -> bool:
        """Delete tenant and all associated data"""

        tenant_config = self.get_tenant(tenant_id)
        if not tenant_config:
            return False

        if not force and tenant_config.status != TenantStatus.SUSPENDED:
            # Soft delete - mark as deleted but keep data for recovery
            tenant_config.status = TenantStatus.DELETED
            tenant_config.updated_at = datetime.now()
            self._update_tenant_in_database(tenant_config)

            # Remove from cache
            if tenant_id in self.tenant_cache:
                del self.tenant_cache[tenant_id]

            logger.info("Soft deleted tenant %s", tenant_id)
            return True
        else:
            # Hard delete - remove all data
            try:
                self._delete_tenant_data(tenant_id)
                self._delete_tenant_from_database(tenant_id)

                # Remove from cache
                if tenant_id in self.tenant_cache:
                    del self.tenant_cache[tenant_id]

                # Remove users from cache
                users_to_remove = [
                    user_id for user_id, user in self.user_cache.items()
                    if user.tenant_id == tenant_id
                ]
                for user_id in users_to_remove:
                    user = self.user_cache[user_id]
                    if user.api_key and user.api_key in self.api_key_to_user:
                        del self.api_key_to_user[user.api_key]
                    del self.user_cache[user_id]

                logger.info("Hard deleted tenant %s", tenant_id)
                return True

            except Exception as e:
                logger.error("Failed to delete tenant %s: %s", tenant_id, str(e))
                return False

    def list_tenants(
        self,
        status: Optional[TenantStatus] = None,
        tier: Optional[TenantTier] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[TenantConfiguration]:
        """List tenants with optional filtering"""

        query = "MATCH (t:Tenant) WHERE 1=1"
        params = {}

        if status:
            query += " AND t.status = $status"
            params['status'] = status.value

        if tier:
            query += " AND t.tier = $tier"
            params['tier'] = tier.value

        query += " RETURN t ORDER BY t.created_at DESC SKIP $offset LIMIT $limit"
        params['offset'] = offset
        params['limit'] = limit

        result = self.neo4j_db._run(query, params)

        tenants = []
        for record in result:
            tenant_data = dict(record['t'])
            tenant_config = self._dict_to_tenant_config(tenant_data)
            tenants.append(tenant_config)

        return tenants

    def authenticate_user(self, api_key: str) -> Optional[TenantUser]:
        """Authenticate user by API key"""

        # Check cache first
        if api_key in self.api_key_to_user:
            user_id = self.api_key_to_user[api_key]
            if user_id in self.user_cache:
                return self.user_cache[user_id]

        # Load from database
        user = self._load_user_by_api_key(api_key)
        if user and user.is_active:
            # Update last active
            user.last_active = datetime.now()
            self._update_user_in_database(user)

            # Cache user
            self.user_cache[user.user_id] = user
            self.api_key_to_user[api_key] = user.user_id

            return user

        return None

    def create_user(
        self,
        tenant_id: str,
        username: str,
        email: str,
        role: str = "viewer",
        permissions: Optional[Set[str]] = None
    ) -> Optional[TenantUser]:
        """Create a new user in tenant"""

        tenant_config = self.get_tenant(tenant_id)
        if not tenant_config or tenant_config.status != TenantStatus.ACTIVE:
            return None

        # Check user limit
        current_users = self._count_tenant_users(tenant_id)
        if tenant_config.max_users > 0 and current_users >= tenant_config.max_users:
            raise ValueError(f"Tenant user limit exceeded ({tenant_config.max_users})")

        user_id = self._generate_user_id(tenant_id, username)
        api_key = self._generate_api_key()

        user = TenantUser(
            user_id=user_id,
            tenant_id=tenant_id,
            username=username,
            email=email,
            role=role,
            permissions=permissions or set(),
            api_key=api_key,
            created_at=datetime.now(),
            last_active=None,
            is_active=True
        )

        try:
            self._create_user_in_database(user)

            # Cache user
            self.user_cache[user_id] = user
            self.api_key_to_user[api_key] = user_id

            logger.info("Created user %s in tenant %s", user_id, tenant_id)
            return user

        except Exception as e:
            logger.error("Failed to create user: %s", str(e))
            return None

    def get_tenant_users(self, tenant_id: str) -> List[TenantUser]:
        """Get all users for a tenant"""

        query = """
        MATCH (u:TenantUser {tenant_id: $tenant_id})
        RETURN u
        ORDER BY u.created_at
        """

        result = self.neo4j_db._run(query, {'tenant_id': tenant_id})

        users = []
        for record in result:
            user_data = dict(record['u'])
            user = self._dict_to_tenant_user(user_data)
            users.append(user)

        return users

    def get_tenant_stats(self, tenant_id: str) -> Dict[str, Any]:
        """Get statistics for a tenant"""

        stats = {
            'tenant_id': tenant_id,
            'nodes': 0,
            'relationships': 0,
            'storage_mb': 0,
            'users': 0,
            'queries_today': 0,
            'last_activity': None
        }

        # Count nodes and relationships with tenant isolation
        node_query = "MATCH (n) WHERE n._tenant_id = $tenant_id RETURN count(n) as count"
        rel_query = "MATCH ()-[r]->() WHERE r._tenant_id = $tenant_id RETURN count(r) as count"

        node_result = self.neo4j_db._run(node_query, {'tenant_id': tenant_id}).single()
        rel_result = self.neo4j_db._run(rel_query, {'tenant_id': tenant_id}).single()

        stats['nodes'] = node_result['count'] if node_result else 0
        stats['relationships'] = rel_result['count'] if rel_result else 0

        # Count users
        stats['users'] = self._count_tenant_users(tenant_id)

        # Get query count for today (would need query log)
        # stats['queries_today'] = self._get_daily_query_count(tenant_id)

        return stats

    # Helper methods
    def _generate_tenant_id(self, name: str) -> str:
        """Generate unique tenant ID"""
        # Create ID from name + timestamp
        clean_name = ''.join(c.lower() for c in name if c.isalnum())[:20]
        timestamp = int(time.time())
        return f"tenant_{clean_name}_{timestamp}"

    def _generate_user_id(self, tenant_id: str, username: str) -> str:
        """Generate unique user ID"""
        clean_username = ''.join(c.lower() for c in username if c.isalnum())[:20]
        return f"{tenant_id}_user_{clean_username}_{int(time.time())}"

    def _generate_api_key(self) -> str:
        """Generate secure API key"""
        return f"nkg_{secrets.token_urlsafe(32)}"

    def _create_tenant_in_database(self, tenant_config: TenantConfiguration):
        """Create tenant record in Neo4j"""
        query = """
        CREATE (t:Tenant {
            tenant_id: $tenant_id,
            name: $name,
            description: $description,
            tier: $tier,
            status: $status,
            max_nodes: $max_nodes,
            max_relationships: $max_relationships,
            max_queries_per_day: $max_queries_per_day,
            max_concurrent_queries: $max_concurrent_queries,
            max_storage_mb: $max_storage_mb,
            max_users: $max_users,
            sparql_enabled: $sparql_enabled,
            federation_enabled: $federation_enabled,
            analytics_enabled: $analytics_enabled,
            api_access_enabled: $api_access_enabled,
            created_at: $created_at,
            updated_at: $updated_at,
            admin_email: $admin_email,
            custom_settings: $custom_settings
        })
        """

        params = asdict(tenant_config)
        params['tier'] = tenant_config.tier.value
        params['status'] = tenant_config.status.value
        params['created_at'] = tenant_config.created_at.isoformat()
        params['updated_at'] = tenant_config.updated_at.isoformat()
        params['custom_settings'] = json.dumps(tenant_config.custom_settings)

        self.neo4j_db._run(query, params)

    def _create_admin_user(self, tenant_config: TenantConfiguration) -> TenantUser:
        """Create admin user for tenant"""
        admin_permissions = {
            'read', 'write', 'admin', 'manage_users',
            'manage_settings', 'view_analytics'
        }

        admin_user = TenantUser(
            user_id=f"{tenant_config.tenant_id}_admin",
            tenant_id=tenant_config.tenant_id,
            username="admin",
            email=tenant_config.admin_email,
            role="admin",
            permissions=admin_permissions,
            api_key=self._generate_api_key(),
            created_at=datetime.now(),
            last_active=None,
            is_active=True
        )

        self._create_user_in_database(admin_user)
        return admin_user

    def _create_user_in_database(self, user: TenantUser):
        """Create user record in Neo4j"""
        query = """
        CREATE (u:TenantUser {
            user_id: $user_id,
            tenant_id: $tenant_id,
            username: $username,
            email: $email,
            role: $role,
            permissions: $permissions,
            api_key: $api_key,
            created_at: $created_at,
            is_active: $is_active
        })
        """

        params = {
            'user_id': user.user_id,
            'tenant_id': user.tenant_id,
            'username': user.username,
            'email': user.email,
            'role': user.role,
            'permissions': json.dumps(list(user.permissions)),
            'api_key': user.api_key,
            'created_at': user.created_at.isoformat(),
            'is_active': user.is_active
        }

        self.neo4j_db._run(query, params)

    def _initialize_tenant_workspace(self, tenant_id: str):
        """Initialize workspace for tenant"""
        # Create tenant-specific indexes and constraints
        # This would set up tenant-specific data structures
        logger.info("Initialized workspace for tenant %s", tenant_id)

    def _cleanup_failed_tenant_creation(self, tenant_id: str):
        """Cleanup after failed tenant creation"""
        try:
            self.neo4j_db._run("MATCH (t:Tenant {tenant_id: $tenant_id}) DELETE t", {'tenant_id': tenant_id})
            self.neo4j_db._run("MATCH (u:TenantUser {tenant_id: $tenant_id}) DELETE u", {'tenant_id': tenant_id})
        except:
            pass

    def _load_tenant_from_database(self, tenant_id: str) -> Optional[TenantConfiguration]:
        """Load tenant from Neo4j"""
        query = "MATCH (t:Tenant {tenant_id: $tenant_id}) RETURN t"
        result = self.neo4j_db._run(query, {'tenant_id': tenant_id}).single()

        if result:
            tenant_data = dict(result['t'])
            return self._dict_to_tenant_config(tenant_data)

        return None

    def _load_user_by_api_key(self, api_key: str) -> Optional[TenantUser]:
        """Load user by API key"""
        query = "MATCH (u:TenantUser {api_key: $api_key}) RETURN u"
        result = self.neo4j_db._run(query, {'api_key': api_key}).single()

        if result:
            user_data = dict(result['u'])
            return self._dict_to_tenant_user(user_data)

        return None

    def _dict_to_tenant_config(self, data: Dict[str, Any]) -> TenantConfiguration:
        """Convert dict to TenantConfiguration"""
        return TenantConfiguration(
            tenant_id=data['tenant_id'],
            name=data['name'],
            description=data.get('description', ''),
            tier=TenantTier(data['tier']),
            status=TenantStatus(data['status']),
            max_nodes=data['max_nodes'],
            max_relationships=data['max_relationships'],
            max_queries_per_day=data['max_queries_per_day'],
            max_concurrent_queries=data['max_concurrent_queries'],
            max_storage_mb=data['max_storage_mb'],
            max_users=data['max_users'],
            sparql_enabled=data['sparql_enabled'],
            federation_enabled=data['federation_enabled'],
            analytics_enabled=data['analytics_enabled'],
            api_access_enabled=data['api_access_enabled'],
            created_at=datetime.fromisoformat(data['created_at']),
            updated_at=datetime.fromisoformat(data['updated_at']),
            expires_at=datetime.fromisoformat(data['expires_at']) if data.get('expires_at') else None,
            admin_email=data['admin_email'],
            billing_contact=data.get('billing_contact'),
            custom_settings=json.loads(data.get('custom_settings', '{}'))
        )

    def _dict_to_tenant_user(self, data: Dict[str, Any]) -> TenantUser:
        """Convert dict to TenantUser"""
        return TenantUser(
            user_id=data['user_id'],
            tenant_id=data['tenant_id'],
            username=data['username'],
            email=data['email'],
            role=data['role'],
            permissions=set(json.loads(data.get('permissions', '[]'))),
            api_key=data.get('api_key'),
            created_at=datetime.fromisoformat(data['created_at']),
            last_active=datetime.fromisoformat(data['last_active']) if data.get('last_active') else None,
            is_active=data.get('is_active', True)
        )

    def _update_tenant_in_database(self, tenant_config: TenantConfiguration):
        """Update tenant in database"""
        query = """
        MATCH (t:Tenant {tenant_id: $tenant_id})
        SET t += $updates
        """

        updates = asdict(tenant_config)
        updates['tier'] = tenant_config.tier.value
        updates['status'] = tenant_config.status.value
        updates['created_at'] = tenant_config.created_at.isoformat()
        updates['updated_at'] = tenant_config.updated_at.isoformat()
        updates['custom_settings'] = json.dumps(tenant_config.custom_settings)

        self.neo4j_db._run(query, {'tenant_id': tenant_config.tenant_id, 'updates': updates})

    def _update_user_in_database(self, user: TenantUser):
        """Update user in database"""
        query = """
        MATCH (u:TenantUser {user_id: $user_id})
        SET u.last_active = $last_active
        """

        params = {
            'user_id': user.user_id,
            'last_active': user.last_active.isoformat() if user.last_active else None
        }

        self.neo4j_db._run(query, params)

    def _count_tenant_users(self, tenant_id: str) -> int:
        """Count users in tenant"""
        query = "MATCH (u:TenantUser {tenant_id: $tenant_id}) RETURN count(u) as count"
        result = self.neo4j_db._run(query, {'tenant_id': tenant_id}).single()
        return result['count'] if result else 0

    def _delete_tenant_data(self, tenant_id: str):
        """Delete all tenant data"""
        # Delete tenant-specific nodes and relationships
        queries = [
            "MATCH (n) WHERE n._tenant_id = $tenant_id DETACH DELETE n",
            "MATCH ()-[r]->() WHERE r._tenant_id = $tenant_id DELETE r"
        ]

        for query in queries:
            self.neo4j_db._run(query, {'tenant_id': tenant_id})

    def _delete_tenant_from_database(self, tenant_id: str):
        """Delete tenant record from database"""
        queries = [
            "MATCH (u:TenantUser {tenant_id: $tenant_id}) DELETE u",
            "MATCH (t:Tenant {tenant_id: $tenant_id}) DELETE t"
        ]

        for query in queries:
            self.neo4j_db._run(query, {'tenant_id': tenant_id})
