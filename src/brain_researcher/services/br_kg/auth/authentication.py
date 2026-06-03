"""Authentication system for BR-KG API.

This module provides JWT authentication, API key management, role-based access control,
and audit logging for the BR-KG system.
"""

import hashlib
import secrets
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

import jwt
import bcrypt
import redis
from fastapi import HTTPException, Security, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
from pydantic import BaseModel, EmailStr, Field

logger = logging.getLogger(__name__)


class Role(str, Enum):
    """User roles for RBAC."""

    ADMIN = "admin"
    RESEARCHER = "researcher"
    COLLABORATOR = "collaborator"
    VIEWER = "viewer"
    API_USER = "api_user"


class Permission(str, Enum):
    """System permissions."""

    # Read permissions
    READ_CONCEPTS = "read:concepts"
    READ_TASKS = "read:tasks"
    READ_REGIONS = "read:regions"
    READ_PUBLICATIONS = "read:publications"
    READ_DATASETS = "read:datasets"

    # Write permissions
    WRITE_CONCEPTS = "write:concepts"
    WRITE_TASKS = "write:tasks"
    WRITE_REGIONS = "write:regions"
    WRITE_PUBLICATIONS = "write:publications"
    WRITE_DATASETS = "write:datasets"

    # Admin permissions
    MANAGE_USERS = "manage:users"
    MANAGE_ROLES = "manage:roles"
    MANAGE_API_KEYS = "manage:api_keys"
    VIEW_AUDIT_LOGS = "view:audit_logs"
    MANAGE_SYSTEM = "manage:system"


# Role-Permission mapping
ROLE_PERMISSIONS = {
    Role.ADMIN: [p.value for p in Permission],  # All permissions
    Role.RESEARCHER: [
        Permission.READ_CONCEPTS.value,
        Permission.READ_TASKS.value,
        Permission.READ_REGIONS.value,
        Permission.READ_PUBLICATIONS.value,
        Permission.READ_DATASETS.value,
        Permission.WRITE_CONCEPTS.value,
        Permission.WRITE_TASKS.value,
        Permission.WRITE_REGIONS.value,
        Permission.WRITE_PUBLICATIONS.value,
        Permission.WRITE_DATASETS.value,
    ],
    Role.COLLABORATOR: [
        Permission.READ_CONCEPTS.value,
        Permission.READ_TASKS.value,
        Permission.READ_REGIONS.value,
        Permission.READ_PUBLICATIONS.value,
        Permission.READ_DATASETS.value,
        Permission.WRITE_CONCEPTS.value,
        Permission.WRITE_TASKS.value,
    ],
    Role.VIEWER: [
        Permission.READ_CONCEPTS.value,
        Permission.READ_TASKS.value,
        Permission.READ_REGIONS.value,
        Permission.READ_PUBLICATIONS.value,
        Permission.READ_DATASETS.value,
    ],
    Role.API_USER: [
        Permission.READ_CONCEPTS.value,
        Permission.READ_TASKS.value,
        Permission.READ_REGIONS.value,
        Permission.READ_PUBLICATIONS.value,
    ],
}


@dataclass
class User:
    """User model."""

    user_id: str
    email: str
    username: str
    role: Role
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    is_active: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class APIKey:
    """API Key model."""

    key_id: str
    key_hash: str
    user_id: str
    name: str
    scopes: List[str]
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    last_used: Optional[datetime] = None
    is_active: bool = True


@dataclass
class AuditLog:
    """Audit log entry."""

    log_id: str
    user_id: str
    action: str
    resource: str
    resource_id: Optional[str]
    ip_address: str
    user_agent: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    success: bool = True
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class TokenData(BaseModel):
    """JWT token payload."""

    sub: str  # Subject (user_id)
    email: EmailStr
    role: Role
    permissions: List[str]
    exp: datetime
    iat: datetime = Field(default_factory=datetime.utcnow)
    jti: Optional[str] = Field(default_factory=lambda: secrets.token_urlsafe(16))


class AuthenticationManager:
    """Main authentication manager."""

    def __init__(
        self,
        secret_key: str,
        algorithm: str = "HS256",
        access_token_expire_minutes: int = 30,
        refresh_token_expire_days: int = 7,
        redis_client: Optional[redis.Redis] = None
    ):
        """Initialize authentication manager.

        Args:
            secret_key: JWT secret key
            algorithm: JWT algorithm
            access_token_expire_minutes: Access token expiration
            refresh_token_expire_days: Refresh token expiration
            redis_client: Redis client for token blacklist
        """
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.access_token_expire = timedelta(minutes=access_token_expire_minutes)
        self.refresh_token_expire = timedelta(days=refresh_token_expire_days)

        self.redis = redis_client or self._create_redis_client()
        self.users: Dict[str, User] = {}
        self.api_keys: Dict[str, APIKey] = {}
        self.audit_logs: List[AuditLog] = []

    def _create_redis_client(self) -> redis.Redis:
        """Create Redis client with fallback."""
        try:
            client = redis.Redis(
                host='localhost',
                port=6379,
                decode_responses=True
            )
            client.ping()
            return client
        except:
            import fakeredis
            return fakeredis.FakeRedis(decode_responses=True)

    def hash_password(self, password: str) -> str:
        """Hash password using bcrypt.

        Args:
            password: Plain password

        Returns:
            Hashed password
        """
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify password against hash.

        Args:
            plain_password: Plain password
            hashed_password: Hashed password

        Returns:
            True if password matches
        """
        return bcrypt.checkpw(
            plain_password.encode('utf-8'),
            hashed_password.encode('utf-8')
        )

    def create_access_token(self, user: User) -> str:
        """Create JWT access token.

        Args:
            user: User object

        Returns:
            JWT token
        """
        expire = datetime.utcnow() + self.access_token_expire

        token_data = TokenData(
            sub=user.user_id,
            email=user.email,
            role=user.role,
            permissions=ROLE_PERMISSIONS[user.role],
            exp=expire
        )

        encoded_jwt = jwt.encode(
            token_data.dict(),
            self.secret_key,
            algorithm=self.algorithm
        )

        # Store token in Redis for tracking
        self.redis.setex(
            f"token:access:{token_data.jti}",
            int(self.access_token_expire.total_seconds()),
            user.user_id
        )

        return encoded_jwt

    def create_refresh_token(self, user: User) -> str:
        """Create JWT refresh token.

        Args:
            user: User object

        Returns:
            JWT refresh token
        """
        expire = datetime.utcnow() + self.refresh_token_expire

        token_data = {
            "sub": user.user_id,
            "type": "refresh",
            "exp": expire,
            "iat": datetime.utcnow(),
            "jti": secrets.token_urlsafe(16)
        }

        encoded_jwt = jwt.encode(
            token_data,
            self.secret_key,
            algorithm=self.algorithm
        )

        # Store refresh token
        self.redis.setex(
            f"token:refresh:{token_data['jti']}",
            int(self.refresh_token_expire.total_seconds()),
            user.user_id
        )

        return encoded_jwt

    def verify_token(self, token: str) -> Optional[TokenData]:
        """Verify JWT token.

        Args:
            token: JWT token

        Returns:
            Token data if valid
        """
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm]
            )

            # Check if token is blacklisted
            jti = payload.get('jti')
            if jti and self.redis.exists(f"token:blacklist:{jti}"):
                return None

            return TokenData(**payload)

        except jwt.ExpiredSignatureError:
            logger.warning("Token expired")
            return None
        except jwt.JWTError as e:
            logger.warning(f"Token verification failed: {e}")
            return None

    def revoke_token(self, token: str):
        """Revoke/blacklist a token.

        Args:
            token: JWT token to revoke
        """
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
                options={"verify_exp": False}
            )

            jti = payload.get('jti')
            if jti:
                # Add to blacklist
                exp = payload.get('exp')
                ttl = exp - datetime.utcnow().timestamp() if exp else 86400

                self.redis.setex(
                    f"token:blacklist:{jti}",
                    int(ttl),
                    "revoked"
                )

                logger.info(f"Token revoked: {jti}")

        except jwt.JWTError as e:
            logger.error(f"Failed to revoke token: {e}")

    def create_api_key(self, user: User, name: str, scopes: List[str]) -> str:
        """Create API key for user.

        Args:
            user: User object
            name: API key name
            scopes: Permission scopes

        Returns:
            API key
        """
        # Generate secure random key
        api_key = f"nkg_{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()

        # Create API key object
        api_key_obj = APIKey(
            key_id=secrets.token_urlsafe(16),
            key_hash=key_hash,
            user_id=user.user_id,
            name=name,
            scopes=scopes
        )

        # Store API key
        self.api_keys[key_hash] = api_key_obj
        self.redis.hset(
            "api_keys",
            key_hash,
            json.dumps({
                "user_id": user.user_id,
                "scopes": scopes,
                "created_at": api_key_obj.created_at.isoformat()
            })
        )

        logger.info(f"Created API key for user {user.user_id}: {name}")

        return api_key

    def verify_api_key(self, api_key: str) -> Optional[Tuple[User, List[str]]]:
        """Verify API key.

        Args:
            api_key: API key

        Returns:
            Tuple of (User, scopes) if valid
        """
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()

        # Check in cache
        api_key_obj = self.api_keys.get(key_hash)

        if not api_key_obj:
            # Check in Redis
            key_data = self.redis.hget("api_keys", key_hash)
            if not key_data:
                return None

            key_info = json.loads(key_data)
            user = self.get_user(key_info["user_id"])

            if user and user.is_active:
                # Update last used
                self.redis.hset(
                    "api_keys:last_used",
                    key_hash,
                    datetime.utcnow().isoformat()
                )

                return user, key_info["scopes"]

        elif api_key_obj.is_active:
            user = self.get_user(api_key_obj.user_id)

            if user and user.is_active:
                api_key_obj.last_used = datetime.utcnow()
                return user, api_key_obj.scopes

        return None

    def create_user(
        self,
        email: str,
        username: str,
        password: str,
        role: Role = Role.VIEWER
    ) -> User:
        """Create new user.

        Args:
            email: User email
            username: Username
            password: Plain password
            role: User role

        Returns:
            Created user
        """
        user_id = secrets.token_urlsafe(16)
        hashed_password = self.hash_password(password)

        user = User(
            user_id=user_id,
            email=email,
            username=username,
            role=role
        )

        # Store user
        self.users[user_id] = user

        # Store in Redis
        self.redis.hset(
            "users",
            user_id,
            json.dumps({
                "email": email,
                "username": username,
                "password": hashed_password,
                "role": role.value,
                "created_at": user.created_at.isoformat()
            })
        )

        logger.info(f"Created user: {username} ({email})")

        return user

    def get_user(self, user_id: str) -> Optional[User]:
        """Get user by ID.

        Args:
            user_id: User ID

        Returns:
            User object if found
        """
        # Check cache
        if user_id in self.users:
            return self.users[user_id]

        # Check Redis
        user_data = self.redis.hget("users", user_id)
        if user_data:
            user_info = json.loads(user_data)
            user = User(
                user_id=user_id,
                email=user_info["email"],
                username=user_info["username"],
                role=Role(user_info["role"]),
                created_at=datetime.fromisoformat(user_info["created_at"])
            )

            self.users[user_id] = user
            return user

        return None

    def authenticate_user(self, username: str, password: str) -> Optional[User]:
        """Authenticate user with username/password.

        Args:
            username: Username or email
            password: Plain password

        Returns:
            User object if authenticated
        """
        # Find user by username or email
        user_data = None
        for uid, udata in self.redis.hgetall("users").items():
            uinfo = json.loads(udata)
            if uinfo["username"] == username or uinfo["email"] == username:
                user_data = uinfo
                user_data["user_id"] = uid
                break

        if not user_data:
            return None

        # Verify password
        if not self.verify_password(password, user_data["password"]):
            return None

        # Create user object
        user = User(
            user_id=user_data["user_id"],
            email=user_data["email"],
            username=user_data["username"],
            role=Role(user_data["role"]),
            created_at=datetime.fromisoformat(user_data["created_at"])
        )

        self.users[user.user_id] = user
        return user

    def check_permission(self, user: User, permission: Permission) -> bool:
        """Check if user has permission.

        Args:
            user: User object
            permission: Required permission

        Returns:
            True if user has permission
        """
        user_permissions = ROLE_PERMISSIONS.get(user.role, [])
        return permission.value in user_permissions

    def log_audit(
        self,
        user_id: str,
        action: str,
        resource: str,
        resource_id: Optional[str] = None,
        ip_address: str = "unknown",
        user_agent: str = "unknown",
        success: bool = True,
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Log audit event.

        Args:
            user_id: User ID
            action: Action performed
            resource: Resource type
            resource_id: Resource ID
            ip_address: Client IP
            user_agent: User agent string
            success: Whether action succeeded
            error_message: Error message if failed
            metadata: Additional metadata
        """
        audit_log = AuditLog(
            log_id=secrets.token_urlsafe(16),
            user_id=user_id,
            action=action,
            resource=resource,
            resource_id=resource_id,
            ip_address=ip_address,
            user_agent=user_agent,
            success=success,
            error_message=error_message,
            metadata=metadata or {}
        )

        self.audit_logs.append(audit_log)

        # Store in Redis
        self.redis.lpush(
            "audit_logs",
            json.dumps({
                "log_id": audit_log.log_id,
                "user_id": audit_log.user_id,
                "action": audit_log.action,
                "resource": audit_log.resource,
                "resource_id": audit_log.resource_id,
                "ip_address": audit_log.ip_address,
                "user_agent": audit_log.user_agent,
                "timestamp": audit_log.timestamp.isoformat(),
                "success": audit_log.success,
                "error_message": audit_log.error_message,
                "metadata": audit_log.metadata
            })
        )

        # Trim to keep only last 10000 entries
        self.redis.ltrim("audit_logs", 0, 9999)

        if not success:
            logger.warning(f"Audit: {action} on {resource} failed for user {user_id}: {error_message}")
        else:
            logger.info(f"Audit: {action} on {resource} by user {user_id}")


# FastAPI dependencies
security = HTTPBearer()
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
    auth_manager: AuthenticationManager = Depends()
) -> User:
    """Get current user from JWT token.

    Args:
        credentials: Authorization credentials
        auth_manager: Authentication manager

    Returns:
        Current user

    Raises:
        HTTPException: If authentication fails
    """
    token = credentials.credentials
    token_data = auth_manager.verify_token(token)

    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"}
        )

    user = auth_manager.get_user(token_data.sub)

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive"
        )

    return user


async def get_api_user(
    api_key: Optional[str] = Security(api_key_header),
    auth_manager: AuthenticationManager = Depends()
) -> Optional[User]:
    """Get user from API key.

    Args:
        api_key: API key from header
        auth_manager: Authentication manager

    Returns:
        User if API key is valid
    """
    if not api_key:
        return None

    result = auth_manager.verify_api_key(api_key)

    if result:
        user, scopes = result
        return user

    return None


def require_permission(permission: Permission):
    """Require specific permission.

    Args:
        permission: Required permission

    Returns:
        Dependency function
    """
    async def permission_checker(
        current_user: User = Depends(get_current_user),
        auth_manager: AuthenticationManager = Depends()
    ):
        if not auth_manager.check_permission(current_user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {permission.value}"
            )
        return current_user

    return permission_checker