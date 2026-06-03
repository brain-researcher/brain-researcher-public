"""
Resource Quota Manager for Multi-tenant BR-KG

Manages resource quotas, usage tracking, and enforcement for tenants.
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum
from dataclasses import dataclass
from collections import defaultdict, deque
import json

logger = logging.getLogger(__name__)


class QuotaType(Enum):
    QUERIES_PER_DAY = "queries_per_day"
    QUERIES_PER_HOUR = "queries_per_hour"
    CONCURRENT_QUERIES = "concurrent_queries"
    STORAGE_MB = "storage_mb"
    NODES = "nodes"
    RELATIONSHIPS = "relationships"
    API_CALLS_PER_MINUTE = "api_calls_per_minute"
    FEDERATION_QUERIES = "federation_queries"
    EXPORT_OPERATIONS = "export_operations"


class QuotaStatus(Enum):
    OK = "ok"
    WARNING = "warning"  # Close to limit
    EXCEEDED = "exceeded"
    SUSPENDED = "suspended"


@dataclass
class QuotaLimit:
    """Represents a quota limit for a tenant"""
    quota_type: QuotaType
    limit: int  # -1 for unlimited
    current_usage: int
    reset_period: str  # daily, hourly, monthly, etc.
    last_reset: datetime
    warning_threshold: float = 0.8  # Warn at 80%

    def is_exceeded(self) -> bool:
        return self.limit > 0 and self.current_usage >= self.limit

    def is_warning(self) -> bool:
        return (
            self.limit > 0 and
            self.current_usage >= (self.limit * self.warning_threshold)
        )

    def get_status(self) -> QuotaStatus:
        if self.is_exceeded():
            return QuotaStatus.EXCEEDED
        elif self.is_warning():
            return QuotaStatus.WARNING
        else:
            return QuotaStatus.OK

    def get_usage_percentage(self) -> float:
        if self.limit <= 0:
            return 0.0
        return (self.current_usage / self.limit) * 100.0


@dataclass
class UsageEvent:
    """Represents a usage event"""
    tenant_id: str
    quota_type: QuotaType
    amount: int
    timestamp: datetime
    metadata: Dict[str, Any]


class ResourceQuotaManager:
    """
    Manages resource quotas and usage tracking for tenants

    Features:
    - Real-time usage tracking
    - Quota enforcement
    - Usage analytics and reporting
    - Automated quota resets
    - Alert generation
    """

    def __init__(self, neo4j_db):
        self.neo4j_db = neo4j_db

        # In-memory usage tracking for real-time limits
        self.current_usage: Dict[str, Dict[QuotaType, QuotaLimit]] = {}
        self.usage_events: Dict[str, deque] = defaultdict(lambda: deque(maxlen=10000))

        # Concurrent query tracking
        self.active_queries: Dict[str, Set[str]] = defaultdict(set)

        # Rate limiting windows
        self.rate_limit_windows: Dict[str, Dict[str, deque]] = defaultdict(lambda: defaultdict(lambda: deque()))

        # Alert thresholds
        self.alert_callbacks: List[callable] = []

        # Initialize schema
        self._initialize_quota_schema()

        logger.info("Resource quota manager initialized")

    def _initialize_quota_schema(self):
        """Initialize Neo4j schema for quota tracking"""

        schema_queries = [
            # Quota limits
            "CREATE CONSTRAINT quota_unique IF NOT EXISTS FOR (q:TenantQuota) REQUIRE (q.tenant_id, q.quota_type) IS UNIQUE",
            "CREATE INDEX quota_tenant_idx IF NOT EXISTS FOR (q:TenantQuota) ON (q.tenant_id)",
            "CREATE INDEX quota_type_idx IF NOT EXISTS FOR (q:TenantQuota) ON (q.quota_type)",

            # Usage events
            "CREATE INDEX usage_tenant_idx IF NOT EXISTS FOR (u:UsageEvent) ON (u.tenant_id)",
            "CREATE INDEX usage_timestamp_idx IF NOT EXISTS FOR (u:UsageEvent) ON (u.timestamp)",
            "CREATE INDEX usage_type_idx IF NOT EXISTS FOR (u:UsageEvent) ON (u.quota_type)",
        ]

        for query in schema_queries:
            try:
                self.neo4j_db._run(query)
            except Exception as e:
                logger.warning("Quota schema creation warning: %s", str(e))

    def set_tenant_quotas(
        self,
        tenant_id: str,
        quotas: Dict[QuotaType, int],
        reset_existing: bool = False
    ):
        """Set quotas for a tenant"""

        if reset_existing:
            # Clear existing quotas
            query = "MATCH (q:TenantQuota {tenant_id: $tenant_id}) DELETE q"
            self.neo4j_db._run(query, {'tenant_id': tenant_id})

        # Create quota limits
        tenant_quotas = {}
        now = datetime.now(timezone.utc)

        for quota_type, limit in quotas.items():
            quota_limit = QuotaLimit(
                quota_type=quota_type,
                limit=limit,
                current_usage=0,
                reset_period=self._get_reset_period(quota_type),
                last_reset=now
            )

            # Store in Neo4j
            self._store_quota_limit(tenant_id, quota_limit)

            tenant_quotas[quota_type] = quota_limit

        # Cache quotas
        self.current_usage[tenant_id] = tenant_quotas

        logger.info("Set quotas for tenant %s: %s", tenant_id, quotas)

    def check_quota(
        self,
        tenant_id: str,
        quota_type: QuotaType,
        requested_amount: int = 1
    ) -> Tuple[bool, QuotaLimit]:
        """
        Check if quota allows the requested usage

        Returns:
            (allowed, quota_limit)
        """

        quota_limit = self.get_quota_limit(tenant_id, quota_type)

        if not quota_limit:
            # No quota set - allow unlimited
            return True, None

        # Check if request would exceed quota
        if quota_limit.limit > 0:
            projected_usage = quota_limit.current_usage + requested_amount
            if projected_usage > quota_limit.limit:
                return False, quota_limit

        return True, quota_limit

    def consume_quota(
        self,
        tenant_id: str,
        quota_type: QuotaType,
        amount: int = 1,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Consume quota and track usage

        Returns:
            True if quota was successfully consumed
        """

        # Check quota first
        allowed, quota_limit = self.check_quota(tenant_id, quota_type, amount)

        if not allowed:
            self._trigger_quota_exceeded_alert(tenant_id, quota_type, quota_limit)
            return False

        # Update usage
        if quota_limit:
            quota_limit.current_usage += amount

            # Update in database
            self._update_quota_usage(tenant_id, quota_limit)

            # Check for warnings
            if quota_limit.is_warning() and not quota_limit.was_warning:
                self._trigger_quota_warning_alert(tenant_id, quota_type, quota_limit)
                quota_limit.was_warning = True

        # Record usage event
        usage_event = UsageEvent(
            tenant_id=tenant_id,
            quota_type=quota_type,
            amount=amount,
            timestamp=datetime.now(timezone.utc),
            metadata=metadata or {}
        )

        self._record_usage_event(usage_event)

        return True

    def start_concurrent_operation(
        self,
        tenant_id: str,
        operation_id: str,
        operation_type: str = "query"
    ) -> bool:
        """Start a concurrent operation (e.g., query)"""

        quota_type = QuotaType.CONCURRENT_QUERIES

        # Check concurrent limit
        current_count = len(self.active_queries[tenant_id])
        allowed, quota_limit = self.check_quota(tenant_id, quota_type, 1)

        if not allowed:
            return False

        # Track active operation
        self.active_queries[tenant_id].add(operation_id)

        # Update concurrent usage
        if quota_limit:
            quota_limit.current_usage = len(self.active_queries[tenant_id])
            self._update_quota_usage(tenant_id, quota_limit)

        return True

    def end_concurrent_operation(
        self,
        tenant_id: str,
        operation_id: str
    ):
        """End a concurrent operation"""

        # Remove from active operations
        if operation_id in self.active_queries[tenant_id]:
            self.active_queries[tenant_id].remove(operation_id)

        # Update concurrent usage
        quota_type = QuotaType.CONCURRENT_QUERIES
        quota_limit = self.get_quota_limit(tenant_id, quota_type)

        if quota_limit:
            quota_limit.current_usage = len(self.active_queries[tenant_id])
            self._update_quota_usage(tenant_id, quota_limit)

    def check_rate_limit(
        self,
        tenant_id: str,
        operation_type: str,
        window_seconds: int = 60,
        max_operations: int = 100
    ) -> bool:
        """Check rate limit for operations"""

        now = time.time()
        window_key = f"{operation_type}_{window_seconds}"

        # Clean old entries
        window = self.rate_limit_windows[tenant_id][window_key]
        while window and now - window[0] > window_seconds:
            window.popleft()

        # Check limit
        if len(window) >= max_operations:
            return False

        # Record operation
        window.append(now)
        return True

    def get_quota_limit(
        self,
        tenant_id: str,
        quota_type: QuotaType
    ) -> Optional[QuotaLimit]:
        """Get quota limit for tenant and type"""

        # Check cache first
        if tenant_id in self.current_usage and quota_type in self.current_usage[tenant_id]:
            return self.current_usage[tenant_id][quota_type]

        # Load from database
        quota_limit = self._load_quota_limit(tenant_id, quota_type)

        if quota_limit:
            # Cache it
            if tenant_id not in self.current_usage:
                self.current_usage[tenant_id] = {}
            self.current_usage[tenant_id][quota_type] = quota_limit

        return quota_limit

    def get_tenant_usage_summary(self, tenant_id: str) -> Dict[str, Any]:
        """Get usage summary for tenant"""

        summary = {
            'tenant_id': tenant_id,
            'quotas': {},
            'current_usage': {},
            'usage_percentages': {},
            'quota_status': {},
            'active_queries': len(self.active_queries.get(tenant_id, set())),
            'recent_events_count': len(self.usage_events.get(tenant_id, deque()))
        }

        # Load all quotas for tenant
        tenant_quotas = self._load_all_tenant_quotas(tenant_id)

        for quota_type, quota_limit in tenant_quotas.items():
            summary['quotas'][quota_type.value] = quota_limit.limit
            summary['current_usage'][quota_type.value] = quota_limit.current_usage
            summary['usage_percentages'][quota_type.value] = quota_limit.get_usage_percentage()
            summary['quota_status'][quota_type.value] = quota_limit.get_status().value

        return summary

    def get_usage_analytics(
        self,
        tenant_id: str,
        days: int = 7
    ) -> Dict[str, Any]:
        """Get usage analytics for tenant"""

        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(days=days)

        analytics = {
            'tenant_id': tenant_id,
            'period_days': days,
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat(),
            'daily_usage': {},
            'quota_violations': [],
            'peak_usage_times': {},
            'total_events': 0
        }

        # Get usage events from database
        usage_events = self._get_usage_events(tenant_id, start_time, end_time)
        analytics['total_events'] = len(usage_events)

        # Analyze daily usage
        daily_usage = defaultdict(lambda: defaultdict(int))

        for event in usage_events:
            day = event.timestamp.date().isoformat()
            quota_type = event.quota_type.value
            daily_usage[day][quota_type] += event.amount

        analytics['daily_usage'] = dict(daily_usage)

        # Find quota violations
        violations = self._get_quota_violations(tenant_id, start_time, end_time)
        analytics['quota_violations'] = violations

        return analytics

    def reset_quotas(self, tenant_id: str, quota_types: Optional[List[QuotaType]] = None):
        """Reset quotas for tenant"""

        if not quota_types:
            # Reset all quotas
            if tenant_id in self.current_usage:
                quota_types = list(self.current_usage[tenant_id].keys())
            else:
                return

        now = datetime.now(timezone.utc)

        for quota_type in quota_types:
            quota_limit = self.get_quota_limit(tenant_id, quota_type)
            if quota_limit:
                quota_limit.current_usage = 0
                quota_limit.last_reset = now
                quota_limit.was_warning = False

                # Update in database
                self._update_quota_usage(tenant_id, quota_limit)

        logger.info("Reset quotas for tenant %s: %s", tenant_id, quota_types)

    def schedule_automatic_resets(self):
        """Schedule automatic quota resets (would be called by scheduler)"""

        now = datetime.now(timezone.utc)

        # Get all quotas that need reset
        query = """
        MATCH (q:TenantQuota)
        WHERE q.reset_period = 'daily' AND q.last_reset < $yesterday
           OR q.reset_period = 'hourly' AND q.last_reset < $hour_ago
           OR q.reset_period = 'monthly' AND q.last_reset < $month_ago
        RETURN q.tenant_id as tenant_id, q.quota_type as quota_type
        """

        params = {
            'yesterday': (now - timedelta(days=1)).isoformat(),
            'hour_ago': (now - timedelta(hours=1)).isoformat(),
            'month_ago': (now - timedelta(days=30)).isoformat()
        }

        result = self.neo4j_db._run(query, params)

        resets_by_tenant = defaultdict(list)
        for record in result:
            tenant_id = record['tenant_id']
            quota_type = QuotaType(record['quota_type'])
            resets_by_tenant[tenant_id].append(quota_type)

        # Reset quotas
        for tenant_id, quota_types in resets_by_tenant.items():
            self.reset_quotas(tenant_id, quota_types)

    def add_alert_callback(self, callback: callable):
        """Add callback for quota alerts"""
        self.alert_callbacks.append(callback)

    # Helper methods
    def _get_reset_period(self, quota_type: QuotaType) -> str:
        """Get reset period for quota type"""

        period_mapping = {
            QuotaType.QUERIES_PER_DAY: 'daily',
            QuotaType.QUERIES_PER_HOUR: 'hourly',
            QuotaType.API_CALLS_PER_MINUTE: 'minutely',
            QuotaType.CONCURRENT_QUERIES: 'none',
            QuotaType.STORAGE_MB: 'none',
            QuotaType.NODES: 'none',
            QuotaType.RELATIONSHIPS: 'none'
        }

        return period_mapping.get(quota_type, 'daily')

    def _store_quota_limit(self, tenant_id: str, quota_limit: QuotaLimit):
        """Store quota limit in Neo4j"""

        query = """
        MERGE (q:TenantQuota {tenant_id: $tenant_id, quota_type: $quota_type})
        SET q.limit = $limit,
            q.current_usage = $current_usage,
            q.reset_period = $reset_period,
            q.last_reset = $last_reset,
            q.warning_threshold = $warning_threshold
        """

        params = {
            'tenant_id': tenant_id,
            'quota_type': quota_limit.quota_type.value,
            'limit': quota_limit.limit,
            'current_usage': quota_limit.current_usage,
            'reset_period': quota_limit.reset_period,
            'last_reset': quota_limit.last_reset.isoformat(),
            'warning_threshold': quota_limit.warning_threshold
        }

        self.neo4j_db._run(query, params)

    def _load_quota_limit(self, tenant_id: str, quota_type: QuotaType) -> Optional[QuotaLimit]:
        """Load quota limit from Neo4j"""

        query = """
        MATCH (q:TenantQuota {tenant_id: $tenant_id, quota_type: $quota_type})
        RETURN q
        """

        result = self.neo4j_db._run(query, {
            'tenant_id': tenant_id,
            'quota_type': quota_type.value
        }).single()

        if result:
            data = dict(result['q'])
            return QuotaLimit(
                quota_type=QuotaType(data['quota_type']),
                limit=data['limit'],
                current_usage=data['current_usage'],
                reset_period=data['reset_period'],
                last_reset=datetime.fromisoformat(data['last_reset']),
                warning_threshold=data.get('warning_threshold', 0.8)
            )

        return None

    def _load_all_tenant_quotas(self, tenant_id: str) -> Dict[QuotaType, QuotaLimit]:
        """Load all quotas for a tenant"""

        query = "MATCH (q:TenantQuota {tenant_id: $tenant_id}) RETURN q"
        result = self.neo4j_db._run(query, {'tenant_id': tenant_id})

        quotas = {}

        for record in result:
            data = dict(record['q'])
            quota_limit = QuotaLimit(
                quota_type=QuotaType(data['quota_type']),
                limit=data['limit'],
                current_usage=data['current_usage'],
                reset_period=data['reset_period'],
                last_reset=datetime.fromisoformat(data['last_reset']),
                warning_threshold=data.get('warning_threshold', 0.8)
            )
            quotas[quota_limit.quota_type] = quota_limit

        return quotas

    def _update_quota_usage(self, tenant_id: str, quota_limit: QuotaLimit):
        """Update quota usage in Neo4j"""

        query = """
        MATCH (q:TenantQuota {tenant_id: $tenant_id, quota_type: $quota_type})
        SET q.current_usage = $current_usage
        """

        self.neo4j_db._run(query, {
            'tenant_id': tenant_id,
            'quota_type': quota_limit.quota_type.value,
            'current_usage': quota_limit.current_usage
        })

    def _record_usage_event(self, usage_event: UsageEvent):
        """Record usage event"""

        # Add to in-memory cache
        self.usage_events[usage_event.tenant_id].append(usage_event)

        # Store in database (async in production)
        query = """
        CREATE (u:UsageEvent {
            tenant_id: $tenant_id,
            quota_type: $quota_type,
            amount: $amount,
            timestamp: $timestamp,
            metadata: $metadata
        })
        """

        try:
            self.neo4j_db._run(query, {
                'tenant_id': usage_event.tenant_id,
                'quota_type': usage_event.quota_type.value,
                'amount': usage_event.amount,
                'timestamp': usage_event.timestamp.isoformat(),
                'metadata': json.dumps(usage_event.metadata)
            })
        except Exception as e:
            logger.error("Failed to record usage event: %s", str(e))

    def _get_usage_events(
        self,
        tenant_id: str,
        start_time: datetime,
        end_time: datetime
    ) -> List[UsageEvent]:
        """Get usage events from database"""

        query = """
        MATCH (u:UsageEvent {tenant_id: $tenant_id})
        WHERE u.timestamp >= $start_time AND u.timestamp <= $end_time
        RETURN u
        ORDER BY u.timestamp DESC
        """

        result = self.neo4j_db._run(query, {
            'tenant_id': tenant_id,
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat()
        })

        events = []
        for record in result:
            data = dict(record['u'])
            event = UsageEvent(
                tenant_id=data['tenant_id'],
                quota_type=QuotaType(data['quota_type']),
                amount=data['amount'],
                timestamp=datetime.fromisoformat(data['timestamp']),
                metadata=json.loads(data.get('metadata', '{}'))
            )
            events.append(event)

        return events

    def _get_quota_violations(
        self,
        tenant_id: str,
        start_time: datetime,
        end_time: datetime
    ) -> List[Dict[str, Any]]:
        """Get quota violations in time period"""

        # This would query violation logs
        # For now, return empty list
        return []

    def _trigger_quota_exceeded_alert(
        self,
        tenant_id: str,
        quota_type: QuotaType,
        quota_limit: QuotaLimit
    ):
        """Trigger alert for quota exceeded"""

        alert_data = {
            'alert_type': 'quota_exceeded',
            'tenant_id': tenant_id,
            'quota_type': quota_type.value,
            'limit': quota_limit.limit,
            'current_usage': quota_limit.current_usage,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }

        for callback in self.alert_callbacks:
            try:
                callback(alert_data)
            except Exception as e:
                logger.error("Alert callback failed: %s", str(e))

        logger.warning("Quota exceeded for tenant %s: %s (%d/%d)",
                      tenant_id, quota_type.value, quota_limit.current_usage, quota_limit.limit)

    def _trigger_quota_warning_alert(
        self,
        tenant_id: str,
        quota_type: QuotaType,
        quota_limit: QuotaLimit
    ):
        """Trigger warning alert for quota approaching limit"""

        alert_data = {
            'alert_type': 'quota_warning',
            'tenant_id': tenant_id,
            'quota_type': quota_type.value,
            'limit': quota_limit.limit,
            'current_usage': quota_limit.current_usage,
            'usage_percentage': quota_limit.get_usage_percentage(),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }

        for callback in self.alert_callbacks:
            try:
                callback(alert_data)
            except Exception as e:
                logger.error("Alert callback failed: %s", str(e))

        logger.info("Quota warning for tenant %s: %s (%.1f%% used)",
                   tenant_id, quota_type.value, quota_limit.get_usage_percentage())