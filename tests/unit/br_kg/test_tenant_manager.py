"""
Unit tests for Tenant Management System

Tests tenant lifecycle, authentication, configuration management,
and multi-tenant isolation for BR-KG.
"""

from dataclasses import asdict
from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from brain_researcher.services.br_kg.tenants.manager import (
    TenantConfiguration,
    TenantManager,
    TenantStatus,
    TenantTier,
    TenantUser,
)


class TestTenantConfiguration:
    """Test TenantConfiguration dataclass"""

    def test_tenant_configuration_creation(self):
        """Test creation of tenant configuration"""
        config = TenantConfiguration(
            tenant_id="test_tenant_123",
            name="Test Tenant",
            description="A test tenant",
            tier=TenantTier.BASIC,
            status=TenantStatus.ACTIVE,
            max_nodes=100000,
            max_relationships=500000,
            max_queries_per_day=10000,
            max_concurrent_queries=5,
            max_storage_mb=1000,
            max_users=5,
            sparql_enabled=True,
            federation_enabled=True,
            analytics_enabled=True,
            api_access_enabled=True,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            expires_at=None,
            admin_email="admin@example.com",
            billing_contact=None,
            custom_settings={},
        )

        assert config.tenant_id == "test_tenant_123"
        assert config.name == "Test Tenant"
        assert config.tier == TenantTier.BASIC
        assert config.status == TenantStatus.ACTIVE
        assert config.max_nodes == 100000
        assert config.sparql_enabled is True

    def test_tenant_configuration_to_dict(self):
        """Test conversion to dictionary"""
        config = TenantConfiguration(
            tenant_id="test_tenant",
            name="Test",
            description="Test",
            tier=TenantTier.FREE,
            status=TenantStatus.ACTIVE,
            max_nodes=1000,
            max_relationships=5000,
            max_queries_per_day=100,
            max_concurrent_queries=2,
            max_storage_mb=50,
            max_users=1,
            sparql_enabled=True,
            federation_enabled=False,
            analytics_enabled=False,
            api_access_enabled=True,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            expires_at=None,
            admin_email="admin@test.com",
            billing_contact=None,
            custom_settings={"key": "value"},
        )

        config_dict = asdict(config)
        assert config_dict["tenant_id"] == "test_tenant"
        assert config_dict["tier"] == TenantTier.FREE
        assert config_dict["custom_settings"] == {"key": "value"}


class TestTenantUser:
    """Test TenantUser dataclass"""

    def test_tenant_user_creation(self):
        """Test creation of tenant user"""
        user = TenantUser(
            user_id="user_123",
            tenant_id="tenant_123",
            username="testuser",
            email="test@example.com",
            role="admin",
            permissions={"read", "write", "admin"},
            api_key="test_api_key",
            created_at=datetime.now(),
            last_active=None,
            is_active=True,
        )

        assert user.user_id == "user_123"
        assert user.tenant_id == "tenant_123"
        assert user.username == "testuser"
        assert user.role == "admin"
        assert "read" in user.permissions
        assert "write" in user.permissions
        assert "admin" in user.permissions
        assert user.is_active is True


class TestTenantManager:
    """Test suite for TenantManager class"""

    @pytest.fixture
    def mock_neo4j_db(self):
        """Mock Neo4j database connection"""
        mock_db = Mock()
        mock_db._run = Mock(return_value=[])
        return mock_db

    @pytest.fixture
    def tenant_manager(self, mock_neo4j_db):
        """Create TenantManager instance with mocked dependencies"""
        return TenantManager(neo4j_db=mock_neo4j_db)

    def test_tenant_manager_initialization(self, mock_neo4j_db):
        """Test proper initialization of tenant manager"""
        manager = TenantManager(neo4j_db=mock_neo4j_db)

        assert manager.neo4j_db == mock_neo4j_db
        assert isinstance(manager.tenant_cache, dict)
        assert isinstance(manager.user_cache, dict)
        assert isinstance(manager.api_key_to_user, dict)
        assert isinstance(manager.tier_configurations, dict)

        # Check tier configurations are set up
        assert TenantTier.FREE in manager.tier_configurations
        assert TenantTier.BASIC in manager.tier_configurations
        assert TenantTier.PROFESSIONAL in manager.tier_configurations
        assert TenantTier.ENTERPRISE in manager.tier_configurations

    def test_tier_configurations(self, tenant_manager):
        """Test default tier configurations"""
        free_config = tenant_manager.tier_configurations[TenantTier.FREE]
        assert free_config["max_nodes"] == 10000
        assert free_config["max_users"] == 1
        assert free_config["federation_enabled"] is False

        enterprise_config = tenant_manager.tier_configurations[TenantTier.ENTERPRISE]
        assert enterprise_config["max_nodes"] == -1  # Unlimited
        assert enterprise_config["max_users"] == -1  # Unlimited
        assert enterprise_config["federation_enabled"] is True

    def test_generate_tenant_id(self, tenant_manager):
        """Test tenant ID generation"""
        name = "Test Tenant Name"

        # Mock time.time() to ensure consistent testing
        with patch("time.time", return_value=1234567890):
            tenant_id = tenant_manager._generate_tenant_id(name)

        assert tenant_id.startswith("tenant_")
        assert "testtenant" in tenant_id  # Cleaned name
        assert "1234567890" in tenant_id  # Timestamp

    def test_generate_user_id(self, tenant_manager):
        """Test user ID generation"""
        tenant_id = "tenant_123"
        username = "Test User"

        with patch("time.time", return_value=9876543210):
            user_id = tenant_manager._generate_user_id(tenant_id, username)

        assert user_id.startswith(tenant_id)
        assert "testuser" in user_id  # Cleaned username
        assert "9876543210" in user_id  # Timestamp

    def test_generate_api_key(self, tenant_manager):
        """Test API key generation"""
        api_key = tenant_manager._generate_api_key()

        assert api_key.startswith("nkg_")
        assert len(api_key) > 20  # Should be reasonably long

        # Should generate unique keys
        api_key2 = tenant_manager._generate_api_key()
        assert api_key != api_key2

    def test_create_tenant_success(self, tenant_manager):
        """Test successful tenant creation"""
        # Mock database operations
        tenant_manager._create_tenant_in_database = Mock()
        tenant_manager._create_admin_user = Mock(
            return_value=Mock(
                user_id="admin_123", api_key="test_key", spec=["user_id", "api_key"]
            )
        )
        tenant_manager._initialize_tenant_workspace = Mock()
        tenant_manager._update_tenant_in_database = Mock()

        tenant_config = tenant_manager.create_tenant(
            name="Test Tenant",
            admin_email="admin@test.com",
            tier=TenantTier.BASIC,
            description="Test tenant description",
        )

        assert isinstance(tenant_config, TenantConfiguration)
        assert tenant_config.name == "Test Tenant"
        assert tenant_config.admin_email == "admin@test.com"
        assert tenant_config.tier == TenantTier.BASIC
        assert tenant_config.status == TenantStatus.ACTIVE
        assert tenant_config.description == "Test tenant description"

        # Verify database operations were called
        tenant_manager._create_tenant_in_database.assert_called_once()
        tenant_manager._create_admin_user.assert_called_once()
        tenant_manager._initialize_tenant_workspace.assert_called_once()
        tenant_manager._update_tenant_in_database.assert_called_once()

        # Verify tenant is cached
        assert tenant_config.tenant_id in tenant_manager.tenant_cache

    def test_create_tenant_already_exists(self, tenant_manager):
        """Test creating tenant that already exists"""
        # Mock existing tenant
        existing_config = Mock()
        tenant_manager.get_tenant = Mock(return_value=existing_config)

        with pytest.raises(ValueError, match="already exists"):
            tenant_manager.create_tenant(
                name="Existing Tenant", admin_email="admin@test.com"
            )

    def test_create_tenant_database_failure(self, tenant_manager):
        """Test tenant creation with database failure"""
        # Mock database operation to fail
        tenant_manager._create_tenant_in_database = Mock(
            side_effect=Exception("DB Error")
        )
        tenant_manager._cleanup_failed_tenant_creation = Mock()
        tenant_manager.get_tenant = Mock(return_value=None)  # Tenant doesn't exist

        with pytest.raises(ValueError, match="Failed to create tenant"):
            tenant_manager.create_tenant(
                name="Test Tenant", admin_email="admin@test.com"
            )

        # Cleanup should be called
        tenant_manager._cleanup_failed_tenant_creation.assert_called_once()

    def test_get_tenant_from_cache(self, tenant_manager):
        """Test getting tenant from cache"""
        # Setup cache
        tenant_id = "test_tenant_123"
        cached_config = Mock()
        cached_config.tenant_id = tenant_id
        tenant_manager.tenant_cache[tenant_id] = cached_config

        result = tenant_manager.get_tenant(tenant_id)

        assert result == cached_config

    def test_get_tenant_from_database(self, tenant_manager):
        """Test getting tenant from database when not in cache"""
        tenant_id = "test_tenant_123"

        # Mock database query
        config_from_db = Mock()
        tenant_manager._load_tenant_from_database = Mock(return_value=config_from_db)

        result = tenant_manager.get_tenant(tenant_id)

        assert result == config_from_db
        # Should be cached after loading
        assert tenant_manager.tenant_cache[tenant_id] == config_from_db

    def test_get_tenant_not_found(self, tenant_manager):
        """Test getting non-existent tenant"""
        tenant_id = "nonexistent_tenant"

        # Mock database query returning None
        tenant_manager._load_tenant_from_database = Mock(return_value=None)

        result = tenant_manager.get_tenant(tenant_id)

        assert result is None

    def test_update_tenant_success(self, tenant_manager):
        """Test successful tenant update"""
        tenant_id = "test_tenant_123"
        existing_config = Mock()
        existing_config.name = "Old Name"
        existing_config.description = "Old Description"

        tenant_manager.get_tenant = Mock(return_value=existing_config)
        tenant_manager._update_tenant_in_database = Mock()

        updates = {"name": "New Name", "description": "New Description"}

        result = tenant_manager.update_tenant(tenant_id, updates)

        assert result == existing_config
        assert existing_config.name == "New Name"
        assert existing_config.description == "New Description"
        assert hasattr(existing_config, "updated_at")

        tenant_manager._update_tenant_in_database.assert_called_once()
        assert tenant_manager.tenant_cache[tenant_id] == existing_config

    def test_update_tenant_not_found(self, tenant_manager):
        """Test updating non-existent tenant"""
        tenant_id = "nonexistent_tenant"
        tenant_manager.get_tenant = Mock(return_value=None)

        result = tenant_manager.update_tenant(tenant_id, {"name": "New Name"})

        assert result is None

    def test_delete_tenant_soft_delete(self, tenant_manager):
        """Test soft delete of tenant"""
        tenant_id = "test_tenant_123"
        tenant_config = Mock()
        tenant_config.status = TenantStatus.ACTIVE

        tenant_manager.get_tenant = Mock(return_value=tenant_config)
        tenant_manager._update_tenant_in_database = Mock()
        tenant_manager.tenant_cache[tenant_id] = tenant_config

        result = tenant_manager.delete_tenant(tenant_id, force=False)

        assert result is True
        assert tenant_config.status == TenantStatus.DELETED
        assert hasattr(tenant_config, "updated_at")

        # Should be removed from cache
        assert tenant_id not in tenant_manager.tenant_cache
        tenant_manager._update_tenant_in_database.assert_called_once()

    def test_delete_tenant_hard_delete(self, tenant_manager):
        """Test hard delete of tenant"""
        tenant_id = "test_tenant_123"
        tenant_config = Mock()
        tenant_config.status = TenantStatus.SUSPENDED

        tenant_manager.get_tenant = Mock(return_value=tenant_config)
        tenant_manager._delete_tenant_data = Mock()
        tenant_manager._delete_tenant_from_database = Mock()
        tenant_manager.tenant_cache[tenant_id] = tenant_config

        # Add some users to cache for cleanup
        user1 = Mock()
        user1.tenant_id = tenant_id
        user1.api_key = "key1"
        user2 = Mock()
        user2.tenant_id = tenant_id
        user2.api_key = "key2"

        tenant_manager.user_cache["user1"] = user1
        tenant_manager.user_cache["user2"] = user2
        tenant_manager.api_key_to_user["key1"] = "user1"
        tenant_manager.api_key_to_user["key2"] = "user2"

        result = tenant_manager.delete_tenant(tenant_id, force=True)

        assert result is True
        tenant_manager._delete_tenant_data.assert_called_once_with(tenant_id)
        tenant_manager._delete_tenant_from_database.assert_called_once_with(tenant_id)

        # Should be removed from all caches
        assert tenant_id not in tenant_manager.tenant_cache
        assert "user1" not in tenant_manager.user_cache
        assert "user2" not in tenant_manager.user_cache
        assert "key1" not in tenant_manager.api_key_to_user
        assert "key2" not in tenant_manager.api_key_to_user

    def test_delete_tenant_not_found(self, tenant_manager):
        """Test deleting non-existent tenant"""
        tenant_id = "nonexistent_tenant"
        tenant_manager.get_tenant = Mock(return_value=None)

        result = tenant_manager.delete_tenant(tenant_id)

        assert result is False

    def test_delete_tenant_database_error(self, tenant_manager):
        """Test hard delete with database error"""
        tenant_id = "test_tenant_123"
        tenant_config = Mock()
        tenant_config.status = TenantStatus.SUSPENDED

        tenant_manager.get_tenant = Mock(return_value=tenant_config)
        tenant_manager._delete_tenant_data = Mock(side_effect=Exception("DB Error"))

        result = tenant_manager.delete_tenant(tenant_id, force=True)

        assert result is False

    def test_list_tenants_no_filters(self, tenant_manager):
        """Test listing tenants without filters"""
        # Mock database result
        mock_records = [
            {
                "t": {
                    "tenant_id": "tenant1",
                    "name": "Tenant 1",
                    "status": "active",
                    "tier": "basic",
                }
            },
            {
                "t": {
                    "tenant_id": "tenant2",
                    "name": "Tenant 2",
                    "status": "active",
                    "tier": "free",
                }
            },
        ]
        tenant_manager.neo4j_db._run.return_value = mock_records
        tenant_manager._dict_to_tenant_config = Mock(
            side_effect=lambda x: Mock(tenant_id=x["tenant_id"])
        )

        result = tenant_manager.list_tenants()

        assert len(result) == 2

        # Verify query parameters
        call_args = tenant_manager.neo4j_db._run.call_args
        query, params = call_args[0], call_args[1]
        assert "MATCH (t:Tenant)" in query
        assert params["limit"] == 100
        assert params["offset"] == 0

    def test_list_tenants_with_filters(self, tenant_manager):
        """Test listing tenants with status and tier filters"""
        tenant_manager.neo4j_db._run.return_value = []
        tenant_manager._dict_to_tenant_config = Mock(return_value=Mock())

        tenant_manager.list_tenants(
            status=TenantStatus.ACTIVE,
            tier=TenantTier.PROFESSIONAL,
            limit=50,
            offset=10,
        )

        call_args = tenant_manager.neo4j_db._run.call_args
        query, params = call_args[0], call_args[1]

        assert "AND t.status = $status" in query
        assert "AND t.tier = $tier" in query
        assert params["status"] == "active"
        assert params["tier"] == "professional"
        assert params["limit"] == 50
        assert params["offset"] == 10

    def test_authenticate_user_from_cache(self, tenant_manager):
        """Test user authentication from cache"""
        api_key = "test_api_key"
        user_id = "user_123"
        cached_user = Mock()
        cached_user.is_active = True

        tenant_manager.api_key_to_user[api_key] = user_id
        tenant_manager.user_cache[user_id] = cached_user

        result = tenant_manager.authenticate_user(api_key)

        assert result == cached_user

    def test_authenticate_user_from_database(self, tenant_manager):
        """Test user authentication from database"""
        api_key = "test_api_key"
        user_from_db = Mock()
        user_from_db.is_active = True
        user_from_db.user_id = "user_123"
        user_from_db.last_active = None

        tenant_manager._load_user_by_api_key = Mock(return_value=user_from_db)
        tenant_manager._update_user_in_database = Mock()

        result = tenant_manager.authenticate_user(api_key)

        assert result == user_from_db
        assert hasattr(user_from_db, "last_active")

        # Should be cached
        assert tenant_manager.user_cache[user_from_db.user_id] == user_from_db
        assert tenant_manager.api_key_to_user[api_key] == user_from_db.user_id

        tenant_manager._update_user_in_database.assert_called_once()

    def test_authenticate_user_inactive(self, tenant_manager):
        """Test authentication of inactive user"""
        api_key = "test_api_key"
        inactive_user = Mock()
        inactive_user.is_active = False

        tenant_manager._load_user_by_api_key = Mock(return_value=inactive_user)

        result = tenant_manager.authenticate_user(api_key)

        assert result is None

    def test_authenticate_user_not_found(self, tenant_manager):
        """Test authentication with invalid API key"""
        api_key = "invalid_api_key"

        tenant_manager._load_user_by_api_key = Mock(return_value=None)

        result = tenant_manager.authenticate_user(api_key)

        assert result is None

    def test_create_user_success(self, tenant_manager):
        """Test successful user creation"""
        tenant_id = "test_tenant_123"
        tenant_config = Mock()
        tenant_config.status = TenantStatus.ACTIVE
        tenant_config.max_users = 5

        tenant_manager.get_tenant = Mock(return_value=tenant_config)
        tenant_manager._count_tenant_users = Mock(return_value=2)  # Current count
        tenant_manager._create_user_in_database = Mock()

        user = tenant_manager.create_user(
            tenant_id=tenant_id,
            username="testuser",
            email="test@example.com",
            role="editor",
            permissions={"read", "write"},
        )

        assert isinstance(user, TenantUser)
        assert user.tenant_id == tenant_id
        assert user.username == "testuser"
        assert user.email == "test@example.com"
        assert user.role == "editor"
        assert user.permissions == {"read", "write"}
        assert user.is_active is True
        assert user.api_key is not None

        # Should be cached
        assert user.user_id in tenant_manager.user_cache
        assert user.api_key in tenant_manager.api_key_to_user

        tenant_manager._create_user_in_database.assert_called_once()

    def test_create_user_tenant_not_active(self, tenant_manager):
        """Test creating user for inactive tenant"""
        tenant_id = "test_tenant_123"
        tenant_config = Mock()
        tenant_config.status = TenantStatus.SUSPENDED

        tenant_manager.get_tenant = Mock(return_value=tenant_config)

        result = tenant_manager.create_user(
            tenant_id=tenant_id, username="testuser", email="test@example.com"
        )

        assert result is None

    def test_create_user_limit_exceeded(self, tenant_manager):
        """Test creating user when limit is exceeded"""
        tenant_id = "test_tenant_123"
        tenant_config = Mock()
        tenant_config.status = TenantStatus.ACTIVE
        tenant_config.max_users = 1

        tenant_manager.get_tenant = Mock(return_value=tenant_config)
        tenant_manager._count_tenant_users = Mock(return_value=1)  # At limit

        with pytest.raises(ValueError, match="user limit exceeded"):
            tenant_manager.create_user(
                tenant_id=tenant_id, username="testuser", email="test@example.com"
            )

    def test_create_user_database_error(self, tenant_manager):
        """Test user creation with database error"""
        tenant_id = "test_tenant_123"
        tenant_config = Mock()
        tenant_config.status = TenantStatus.ACTIVE
        tenant_config.max_users = 5

        tenant_manager.get_tenant = Mock(return_value=tenant_config)
        tenant_manager._count_tenant_users = Mock(return_value=1)
        tenant_manager._create_user_in_database = Mock(
            side_effect=Exception("DB Error")
        )

        result = tenant_manager.create_user(
            tenant_id=tenant_id, username="testuser", email="test@example.com"
        )

        assert result is None

    def test_get_tenant_users(self, tenant_manager):
        """Test getting all users for a tenant"""
        tenant_id = "test_tenant_123"

        # Mock database result
        mock_records = [
            {"u": {"user_id": "user1", "username": "user1", "tenant_id": tenant_id}},
            {"u": {"user_id": "user2", "username": "user2", "tenant_id": tenant_id}},
        ]
        tenant_manager.neo4j_db._run.return_value = mock_records
        tenant_manager._dict_to_tenant_user = Mock(
            side_effect=lambda x: Mock(user_id=x["user_id"])
        )

        users = tenant_manager.get_tenant_users(tenant_id)

        assert len(users) == 2

        # Verify query
        call_args = tenant_manager.neo4j_db._run.call_args
        query, params = call_args[0], call_args[1]
        assert "MATCH (u:TenantUser {tenant_id: $tenant_id})" in query
        assert params["tenant_id"] == tenant_id

    def test_get_tenant_stats(self, tenant_manager):
        """Test getting tenant statistics"""
        tenant_id = "test_tenant_123"

        # Mock database queries
        tenant_manager.neo4j_db._run.side_effect = [
            [{"count": 1000}],  # Node count
            [{"count": 5000}],  # Relationship count
        ]
        tenant_manager._count_tenant_users = Mock(return_value=3)

        stats = tenant_manager.get_tenant_stats(tenant_id)

        assert stats["tenant_id"] == tenant_id
        assert stats["nodes"] == 1000
        assert stats["relationships"] == 5000
        assert stats["users"] == 3
        assert "storage_mb" in stats
        assert "queries_today" in stats
        assert "last_activity" in stats


class TestTenantManagerDatabaseOperations:
    """Test database operation methods"""

    @pytest.fixture
    def tenant_manager(self):
        mock_db = Mock()
        mock_db._run = Mock()
        return TenantManager(neo4j_db=mock_db)

    def test_create_tenant_in_database(self, tenant_manager):
        """Test creating tenant record in Neo4j"""
        tenant_config = TenantConfiguration(
            tenant_id="test_tenant",
            name="Test Tenant",
            description="Test",
            tier=TenantTier.BASIC,
            status=TenantStatus.ACTIVE,
            max_nodes=100000,
            max_relationships=500000,
            max_queries_per_day=10000,
            max_concurrent_queries=5,
            max_storage_mb=1000,
            max_users=5,
            sparql_enabled=True,
            federation_enabled=True,
            analytics_enabled=True,
            api_access_enabled=True,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            expires_at=None,
            admin_email="admin@test.com",
            billing_contact=None,
            custom_settings={"key": "value"},
        )

        tenant_manager._create_tenant_in_database(tenant_config)

        # Verify query was called
        tenant_manager.neo4j_db._run.assert_called_once()

        call_args = tenant_manager.neo4j_db._run.call_args
        query, params = call_args[0], call_args[1]

        assert "CREATE (t:Tenant {" in query
        assert params["tenant_id"] == "test_tenant"
        assert params["name"] == "Test Tenant"
        assert params["tier"] == "basic"
        assert params["status"] == "active"
        assert params["custom_settings"] == '{"key": "value"}'

    def test_create_user_in_database(self, tenant_manager):
        """Test creating user record in Neo4j"""
        user = TenantUser(
            user_id="user_123",
            tenant_id="tenant_123",
            username="testuser",
            email="test@example.com",
            role="editor",
            permissions={"read", "write"},
            api_key="test_api_key",
            created_at=datetime.now(),
            last_active=None,
            is_active=True,
        )

        tenant_manager._create_user_in_database(user)

        tenant_manager.neo4j_db._run.assert_called_once()

        call_args = tenant_manager.neo4j_db._run.call_args
        query, params = call_args[0], call_args[1]

        assert "CREATE (u:TenantUser {" in query
        assert params["user_id"] == "user_123"
        assert params["tenant_id"] == "tenant_123"
        assert params["username"] == "testuser"
        assert params["email"] == "test@example.com"
        assert params["role"] == "editor"
        assert (
            '["read", "write"]' in params["permissions"]
            or '["write", "read"]' in params["permissions"]
        )
        assert params["api_key"] == "test_api_key"
        assert params["is_active"] is True

    def test_load_tenant_from_database(self, tenant_manager):
        """Test loading tenant from database"""
        tenant_id = "test_tenant_123"

        # Mock database result
        mock_result = Mock()
        mock_result.single.return_value = {
            "t": {
                "tenant_id": tenant_id,
                "name": "Test Tenant",
                "tier": "basic",
                "status": "active",
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "admin_email": "admin@test.com",
                "custom_settings": "{}",
            }
        }
        tenant_manager.neo4j_db._run.return_value = mock_result
        tenant_manager._dict_to_tenant_config = Mock(
            return_value=Mock(tenant_id=tenant_id)
        )

        result = tenant_manager._load_tenant_from_database(tenant_id)

        assert result is not None

        call_args = tenant_manager.neo4j_db._run.call_args
        query, params = call_args[0], call_args[1]

        assert "MATCH (t:Tenant {tenant_id: $tenant_id})" in query
        assert params["tenant_id"] == tenant_id

    def test_load_tenant_from_database_not_found(self, tenant_manager):
        """Test loading non-existent tenant from database"""
        tenant_id = "nonexistent_tenant"

        # Mock empty result
        mock_result = Mock()
        mock_result.single.return_value = None
        tenant_manager.neo4j_db._run.return_value = mock_result

        result = tenant_manager._load_tenant_from_database(tenant_id)

        assert result is None

    def test_dict_to_tenant_config(self, tenant_manager):
        """Test conversion of dict to TenantConfiguration"""
        data = {
            "tenant_id": "test_tenant",
            "name": "Test Tenant",
            "description": "Test Description",
            "tier": "basic",
            "status": "active",
            "max_nodes": 100000,
            "max_relationships": 500000,
            "max_queries_per_day": 10000,
            "max_concurrent_queries": 5,
            "max_storage_mb": 1000,
            "max_users": 5,
            "sparql_enabled": True,
            "federation_enabled": True,
            "analytics_enabled": True,
            "api_access_enabled": True,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "expires_at": None,
            "admin_email": "admin@test.com",
            "billing_contact": None,
            "custom_settings": '{"key": "value"}',
        }

        config = tenant_manager._dict_to_tenant_config(data)

        assert isinstance(config, TenantConfiguration)
        assert config.tenant_id == "test_tenant"
        assert config.name == "Test Tenant"
        assert config.tier == TenantTier.BASIC
        assert config.status == TenantStatus.ACTIVE
        assert config.custom_settings == {"key": "value"}
        assert isinstance(config.created_at, datetime)
        assert isinstance(config.updated_at, datetime)

    def test_dict_to_tenant_user(self, tenant_manager):
        """Test conversion of dict to TenantUser"""
        data = {
            "user_id": "user_123",
            "tenant_id": "tenant_123",
            "username": "testuser",
            "email": "test@example.com",
            "role": "editor",
            "permissions": '["read", "write"]',
            "api_key": "test_api_key",
            "created_at": datetime.now().isoformat(),
            "last_active": None,
            "is_active": True,
        }

        user = tenant_manager._dict_to_tenant_user(data)

        assert isinstance(user, TenantUser)
        assert user.user_id == "user_123"
        assert user.tenant_id == "tenant_123"
        assert user.username == "testuser"
        assert user.email == "test@example.com"
        assert user.role == "editor"
        assert user.permissions == {"read", "write"}
        assert user.api_key == "test_api_key"
        assert user.is_active is True
        assert isinstance(user.created_at, datetime)
        assert user.last_active is None

    def test_cleanup_failed_tenant_creation(self, tenant_manager):
        """Test cleanup after failed tenant creation"""
        tenant_id = "failed_tenant"

        tenant_manager._cleanup_failed_tenant_creation(tenant_id)

        # Should call delete queries
        assert tenant_manager.neo4j_db._run.call_count == 2

        calls = tenant_manager.neo4j_db._run.call_args_list

        # Check tenant deletion query
        tenant_query, tenant_params = calls[0][0], calls[0][1]
        assert "DELETE t" in tenant_query
        assert tenant_params["tenant_id"] == tenant_id

        # Check user deletion query
        user_query, user_params = calls[1][0], calls[1][1]
        assert "DELETE u" in user_query
        assert user_params["tenant_id"] == tenant_id

    def test_delete_tenant_data(self, tenant_manager):
        """Test deletion of tenant-specific data"""
        tenant_id = "tenant_to_delete"

        tenant_manager._delete_tenant_data(tenant_id)

        # Should call queries to delete tenant data
        assert tenant_manager.neo4j_db._run.call_count == 2

        calls = tenant_manager.neo4j_db._run.call_args_list

        for call_args, _call_kwargs in calls:
            query, params = call_args
            assert "_tenant_id = $tenant_id" in query
            assert params["tenant_id"] == tenant_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
