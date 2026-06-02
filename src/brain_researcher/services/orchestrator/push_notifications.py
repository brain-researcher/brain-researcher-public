"""
Push Notification Service for Brain Researcher
Handles push notification subscriptions and delivery for PWA users
"""

import asyncio
import base64
import json
import logging
import os
import sqlite3
import struct
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import redis.asyncio as redis
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from fastapi import HTTPException
from pywebpush import WebPushException, webpush

logger = logging.getLogger(__name__)


@dataclass
class PushSubscription:
    """Represents a push notification subscription"""

    endpoint: str
    p256dh: str  # Public key for encryption
    auth: str  # Authentication secret
    user_id: Optional[str] = None
    user_agent: Optional[str] = None
    subscribed_at: Optional[datetime] = None
    last_notification: Optional[datetime] = None
    notification_count: int = 0
    is_active: bool = True


@dataclass
class NotificationPayload:
    """Represents a notification to be sent"""

    title: str
    body: str
    type: str = "default"
    data: Optional[Dict[str, Any]] = None
    actions: Optional[List[Dict[str, str]]] = None
    icon: str = "/icons/icon-192x192.png"
    badge: str = "/icons/icon-192x192.png"
    tag: Optional[str] = None
    require_interaction: bool = False
    ttl: int = 86400  # 24 hours
    urgency: str = "normal"  # low, normal, high


class PushNotificationService:
    """Service for managing push notifications"""

    def __init__(
        self,
        vapid_private_key: Optional[str] = None,
        vapid_public_key: Optional[str] = None,
        vapid_email: str = "admin@brainresearcher.com",
        redis_url: str = "redis://localhost:6379",
        db_path: str = "push_subscriptions.db",
    ):
        self.vapid_private_key = vapid_private_key or os.getenv("VAPID_PRIVATE_KEY")
        self.vapid_public_key = vapid_public_key or os.getenv("VAPID_PUBLIC_KEY")
        self.vapid_email = vapid_email
        self.redis_url = redis_url
        self.db_path = db_path
        self.redis_client = None

        # Generate VAPID keys if not provided
        if not self.vapid_private_key or not self.vapid_public_key:
            self._generate_vapid_keys()

        # Initialize database
        self._init_db()

    async def __aenter__(self):
        """Async context manager entry"""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()

    async def initialize(self):
        """Initialize async resources"""
        try:
            self.redis_client = redis.from_url(
                self.redis_url, encoding="utf-8", decode_responses=True
            )
            await self.redis_client.ping()
            logger.info("Push notification service initialized")
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}. Using fallback storage.")
            self.redis_client = None

    async def close(self):
        """Close async resources"""
        if self.redis_client:
            await self.redis_client.close()

    def _generate_vapid_keys(self):
        """Generate VAPID key pair for push notifications"""
        private_key = ec.generate_private_key(ec.SECP256R1())

        # Export private key
        private_pem = private_key.private_bytes(
            encoding=Encoding.PEM,
            format=PrivateFormat.PKCS8,
            encryption_algorithm=NoEncryption(),
        )
        self.vapid_private_key = private_pem.decode("utf-8")

        # Export public key
        public_key = private_key.public_key()
        public_pem = public_key.public_bytes(
            encoding=Encoding.PEM, format=PublicFormat.SubjectPublicKeyInfo
        )
        self.vapid_public_key = public_pem.decode("utf-8")

        logger.info("Generated new VAPID keys")

        # Save to environment or config
        print(f"VAPID_PRIVATE_KEY={self.vapid_private_key}")
        print(f"VAPID_PUBLIC_KEY={self.vapid_public_key}")

    def _init_db(self):
        """Initialize SQLite database for subscriptions"""
        with self._get_db() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    endpoint TEXT UNIQUE NOT NULL,
                    p256dh TEXT NOT NULL,
                    auth TEXT NOT NULL,
                    user_id TEXT,
                    user_agent TEXT,
                    subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_notification TIMESTAMP,
                    notification_count INTEGER DEFAULT 0,
                    is_active BOOLEAN DEFAULT 1
                )
            """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notification_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subscription_id INTEGER,
                    notification_type TEXT,
                    title TEXT,
                    body TEXT,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT,
                    error_message TEXT,
                    FOREIGN KEY (subscription_id) REFERENCES subscriptions (id)
                )
            """
            )

            conn.commit()

    @contextmanager
    def _get_db(self):
        """Get database connection context manager"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    async def subscribe(
        self,
        endpoint: str,
        p256dh: str,
        auth: str,
        user_id: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> bool:
        """Subscribe to push notifications"""
        try:
            subscription = PushSubscription(
                endpoint=endpoint,
                p256dh=p256dh,
                auth=auth,
                user_id=user_id,
                user_agent=user_agent,
                subscribed_at=datetime.utcnow(),
            )

            # Store in database
            with self._get_db() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO subscriptions
                    (endpoint, p256dh, auth, user_id, user_agent, subscribed_at, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        subscription.endpoint,
                        subscription.p256dh,
                        subscription.auth,
                        subscription.user_id,
                        subscription.user_agent,
                        subscription.subscribed_at,
                        subscription.is_active,
                    ),
                )
                conn.commit()

            # Cache in Redis if available
            if self.redis_client:
                await self.redis_client.set(
                    f"push_sub:{endpoint}",
                    json.dumps(asdict(subscription), default=str),
                    ex=86400 * 30,  # 30 days
                )

            logger.info(f"New push subscription: {endpoint}")
            return True

        except Exception as e:
            logger.error(f"Failed to subscribe: {e}")
            return False

    async def unsubscribe(self, endpoint: str) -> bool:
        """Unsubscribe from push notifications"""
        try:
            # Remove from database
            with self._get_db() as conn:
                conn.execute(
                    "UPDATE subscriptions SET is_active = 0 WHERE endpoint = ?",
                    (endpoint,),
                )
                conn.commit()

            # Remove from Redis if available
            if self.redis_client:
                await self.redis_client.delete(f"push_sub:{endpoint}")

            logger.info(f"Unsubscribed: {endpoint}")
            return True

        except Exception as e:
            logger.error(f"Failed to unsubscribe: {e}")
            return False

    async def send_notification(
        self,
        payload: NotificationPayload,
        user_id: Optional[str] = None,
        endpoints: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Send push notification to subscribers"""
        results = {"sent": 0, "failed": 0, "errors": []}

        try:
            # Get target subscriptions
            subscriptions = await self._get_subscriptions(user_id, endpoints)

            if not subscriptions:
                logger.warning("No active subscriptions found")
                return results

            # Prepare notification data
            notification_data = {
                "title": payload.title,
                "body": payload.body,
                "type": payload.type,
                "icon": payload.icon,
                "badge": payload.badge,
                "data": payload.data or {},
                "actions": payload.actions or [],
                "tag": payload.tag,
                "requireInteraction": payload.require_interaction,
            }

            # Send to each subscription
            tasks = []
            for subscription in subscriptions:
                task = self._send_to_subscription(
                    subscription, notification_data, payload
                )
                tasks.append(task)

            # Execute sends concurrently
            send_results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process results
            for i, result in enumerate(send_results):
                if isinstance(result, Exception):
                    results["failed"] += 1
                    results["errors"].append(str(result))
                    logger.error(
                        f"Failed to send to {subscriptions[i].endpoint}: {result}"
                    )
                elif result:
                    results["sent"] += 1
                else:
                    results["failed"] += 1

            logger.info(
                f"Notification sent: {results['sent']} successful, {results['failed']} failed"
            )

        except Exception as e:
            logger.error(f"Failed to send notifications: {e}")
            results["errors"].append(str(e))

        return results

    async def _get_subscriptions(
        self, user_id: Optional[str] = None, endpoints: Optional[List[str]] = None
    ) -> List[PushSubscription]:
        """Get active subscriptions from database"""
        subscriptions = []

        try:
            with self._get_db() as conn:
                if endpoints:
                    # Get specific endpoints
                    placeholders = ",".join(["?"] * len(endpoints))
                    query = f"""
                        SELECT * FROM subscriptions
                        WHERE endpoint IN ({placeholders}) AND is_active = 1
                    """
                    rows = conn.execute(query, endpoints).fetchall()
                elif user_id:
                    # Get subscriptions for specific user
                    rows = conn.execute(
                        "SELECT * FROM subscriptions WHERE user_id = ? AND is_active = 1",
                        (user_id,),
                    ).fetchall()
                else:
                    # Get all active subscriptions
                    rows = conn.execute(
                        "SELECT * FROM subscriptions WHERE is_active = 1"
                    ).fetchall()

                for row in rows:
                    subscription = PushSubscription(
                        endpoint=row["endpoint"],
                        p256dh=row["p256dh"],
                        auth=row["auth"],
                        user_id=row["user_id"],
                        user_agent=row["user_agent"],
                        subscribed_at=(
                            datetime.fromisoformat(row["subscribed_at"])
                            if row["subscribed_at"]
                            else None
                        ),
                        last_notification=(
                            datetime.fromisoformat(row["last_notification"])
                            if row["last_notification"]
                            else None
                        ),
                        notification_count=row["notification_count"],
                        is_active=bool(row["is_active"]),
                    )
                    subscriptions.append(subscription)

        except Exception as e:
            logger.error(f"Failed to get subscriptions: {e}")

        return subscriptions

    async def _send_to_subscription(
        self,
        subscription: PushSubscription,
        notification_data: Dict[str, Any],
        payload: NotificationPayload,
    ) -> bool:
        """Send notification to a specific subscription"""
        try:
            # Prepare webpush data
            webpush_data = {
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            }

            # Send push notification
            response = webpush(
                subscription_info=webpush_data,
                data=json.dumps(notification_data),
                vapid_private_key=self.vapid_private_key,
                vapid_claims={"sub": f"mailto:{self.vapid_email}"},
                ttl=payload.ttl,
                headers={"Urgency": payload.urgency},
            )

            # Update subscription stats
            await self._update_subscription_stats(subscription.endpoint, True)

            # Log notification
            await self._log_notification(
                subscription.endpoint, payload.type, payload.title, payload.body, "sent"
            )

            return True

        except WebPushException as e:
            if e.response and e.response.status_code in [410, 413, 429]:
                # Subscription is no longer valid
                await self.unsubscribe(subscription.endpoint)
                logger.warning(f"Invalid subscription removed: {subscription.endpoint}")

            await self._log_notification(
                subscription.endpoint,
                payload.type,
                payload.title,
                payload.body,
                "failed",
                str(e),
            )

            return False

        except Exception as e:
            await self._log_notification(
                subscription.endpoint,
                payload.type,
                payload.title,
                payload.body,
                "failed",
                str(e),
            )

            logger.error(f"Failed to send push notification: {e}")
            return False

    async def _update_subscription_stats(self, endpoint: str, success: bool):
        """Update subscription statistics"""
        try:
            with self._get_db() as conn:
                if success:
                    conn.execute(
                        """
                        UPDATE subscriptions
                        SET last_notification = ?, notification_count = notification_count + 1
                        WHERE endpoint = ?
                    """,
                        (datetime.utcnow(), endpoint),
                    )
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to update subscription stats: {e}")

    async def _log_notification(
        self,
        endpoint: str,
        notification_type: str,
        title: str,
        body: str,
        status: str,
        error_message: Optional[str] = None,
    ):
        """Log notification send attempt"""
        try:
            with self._get_db() as conn:
                # Get subscription ID
                row = conn.execute(
                    "SELECT id FROM subscriptions WHERE endpoint = ?", (endpoint,)
                ).fetchone()
                subscription_id = row["id"] if row else None

                conn.execute(
                    """
                    INSERT INTO notification_log
                    (subscription_id, notification_type, title, body, status, error_message)
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                    (
                        subscription_id,
                        notification_type,
                        title,
                        body,
                        status,
                        error_message,
                    ),
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to log notification: {e}")

    async def send_brain_analysis_complete(
        self,
        analysis_name: str,
        analysis_id: str,
        user_id: Optional[str] = None,
        has_significant_findings: bool = False,
    ):
        """Send notification when brain analysis is complete"""
        payload = NotificationPayload(
            title="Brain Analysis Complete",
            body=f"Analysis '{analysis_name}' has finished processing."
            + (" Significant findings detected!" if has_significant_findings else ""),
            type="analysis-complete",
            data={
                "analysisId": analysis_id,
                "analysisName": analysis_name,
                "significantFindings": has_significant_findings,
            },
            actions=[
                {"action": "view", "title": "View Results"},
                {"action": "dismiss", "title": "Dismiss"},
            ],
            tag=f"analysis-{analysis_id}",
            require_interaction=has_significant_findings,
        )

        return await self.send_notification(payload, user_id)

    async def send_dataset_update(
        self,
        dataset_name: str,
        update_type: str = "update",
        user_id: Optional[str] = None,
    ):
        """Send notification when dataset is updated"""
        payload = NotificationPayload(
            title="Dataset Update Available",
            body=f"New brain data available: {dataset_name}",
            type="data-update",
            data={"datasetName": dataset_name, "updateType": update_type},
            actions=[
                {"action": "sync", "title": "Sync Now"},
                {"action": "later", "title": "Later"},
            ],
            tag=f"dataset-{dataset_name}",
            urgency="low",
        )

        return await self.send_notification(payload, user_id)

    async def send_system_alert(
        self, message: str, severity: str = "medium", user_id: Optional[str] = None
    ):
        """Send system alert notification"""
        payload = NotificationPayload(
            title="Brain Researcher Alert",
            body=message,
            type="system-alert",
            data={"message": message, "severity": severity},
            require_interaction=severity == "high",
            urgency="high" if severity == "high" else "normal",
            tag="system-alert",
        )

        return await self.send_notification(payload, user_id)

    async def send_offline_sync_complete(
        self, synced_items: int, user_id: Optional[str] = None
    ):
        """Send notification when offline sync is complete"""
        payload = NotificationPayload(
            title="Offline Sync Complete",
            body=f"{synced_items} items synchronized while offline",
            type="sync-complete",
            data={"syncedItems": synced_items},
            tag="offline-sync",
            urgency="low",
        )

        return await self.send_notification(payload, user_id)

    async def get_subscription_stats(self) -> Dict[str, Any]:
        """Get subscription statistics"""
        stats = {
            "total_subscriptions": 0,
            "active_subscriptions": 0,
            "notifications_sent_today": 0,
            "notifications_sent_total": 0,
        }

        try:
            with self._get_db() as conn:
                # Total subscriptions
                stats["total_subscriptions"] = conn.execute(
                    "SELECT COUNT(*) FROM subscriptions"
                ).fetchone()[0]

                # Active subscriptions
                stats["active_subscriptions"] = conn.execute(
                    "SELECT COUNT(*) FROM subscriptions WHERE is_active = 1"
                ).fetchone()[0]

                # Notifications sent today
                today = datetime.utcnow().date()
                stats["notifications_sent_today"] = conn.execute(
                    'SELECT COUNT(*) FROM notification_log WHERE date(sent_at) = ? AND status = "sent"',
                    (today,),
                ).fetchone()[0]

                # Total notifications sent
                stats["notifications_sent_total"] = conn.execute(
                    'SELECT COUNT(*) FROM notification_log WHERE status = "sent"'
                ).fetchone()[0]

        except Exception as e:
            logger.error(f"Failed to get subscription stats: {e}")

        return stats

    async def cleanup_old_subscriptions(self, days: int = 30):
        """Clean up old inactive subscriptions"""
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)

            with self._get_db() as conn:
                # Delete old inactive subscriptions
                result = conn.execute(
                    """
                    DELETE FROM subscriptions
                    WHERE is_active = 0 AND subscribed_at < ?
                """,
                    (cutoff_date,),
                )

                deleted_count = result.rowcount
                conn.commit()

                logger.info(f"Cleaned up {deleted_count} old subscriptions")
                return deleted_count

        except Exception as e:
            logger.error(f"Failed to cleanup subscriptions: {e}")
            return 0


# Global service instance
push_service = PushNotificationService()


# Convenience functions
async def send_analysis_complete_notification(
    analysis_name: str,
    analysis_id: str,
    user_id: Optional[str] = None,
    has_significant_findings: bool = False,
):
    """Send analysis complete notification"""
    return await push_service.send_brain_analysis_complete(
        analysis_name, analysis_id, user_id, has_significant_findings
    )


async def send_dataset_update_notification(
    dataset_name: str, update_type: str = "update", user_id: Optional[str] = None
):
    """Send dataset update notification"""
    return await push_service.send_dataset_update(dataset_name, update_type, user_id)


async def send_system_alert_notification(
    message: str, severity: str = "medium", user_id: Optional[str] = None
):
    """Send system alert notification"""
    return await push_service.send_system_alert(message, severity, user_id)
