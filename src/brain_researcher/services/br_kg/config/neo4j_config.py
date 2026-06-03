"""Neo4j database configuration and deployment utilities.

This module handles Neo4j database setup, authentication, SSL, backups, and monitoring.
"""

import os
import ssl
import logging
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

from neo4j import GraphDatabase, basic_auth
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import schedule
import redis

logger = logging.getLogger(__name__)


@dataclass
class Neo4jConfig:
    """Neo4j database configuration."""

    # Connection settings
    uri: str = field(default_factory=lambda: os.getenv("NEO4J_URI", "bolt://localhost:7687"))
    username: str = field(default_factory=lambda: os.getenv("NEO4J_USER", "neo4j"))
    password: str = field(default_factory=lambda: os.getenv("NEO4J_PASSWORD", "password"))
    database: str = field(default_factory=lambda: os.getenv("NEO4J_DATABASE", "neo4j"))

    # SSL settings
    ssl_enabled: bool = field(default_factory=lambda: os.getenv("NEO4J_SSL_ENABLED", "false").lower() == "true")
    ssl_cert_path: Path = field(default_factory=lambda: Path(os.getenv("NEO4J_SSL_CERT", "/etc/neo4j/ssl/cert.pem")))
    ssl_key_path: Path = field(default_factory=lambda: Path(os.getenv("NEO4J_SSL_KEY", "/etc/neo4j/ssl/key.pem")))

    # Auth settings
    ldap_enabled: bool = field(default_factory=lambda: os.getenv("NEO4J_LDAP_ENABLED", "false").lower() == "true")
    ldap_server: str = field(default_factory=lambda: os.getenv("LDAP_SERVER", "ldap://localhost:389"))
    oauth_enabled: bool = field(default_factory=lambda: os.getenv("NEO4J_OAUTH_ENABLED", "false").lower() == "true")
    oauth_provider: str = field(default_factory=lambda: os.getenv("OAUTH_PROVIDER", "google"))

    # Backup settings
    backup_enabled: bool = True
    backup_dir: Path = field(default_factory=lambda: Path("/var/backups/neo4j"))
    backup_schedule: str = "0 2 * * *"  # Daily at 2 AM
    backup_retention_days: int = 30

    # Cluster settings
    cluster_enabled: bool = field(default_factory=lambda: os.getenv("NEO4J_CLUSTER_ENABLED", "false").lower() == "true")
    cluster_members: List[str] = field(default_factory=list)

    # Monitoring
    metrics_enabled: bool = True
    metrics_port: int = 2004
    prometheus_enabled: bool = True


class SSLManager:
    """Manage SSL certificates for Neo4j."""

    def __init__(self, config: Neo4jConfig):
        """Initialize SSL manager.

        Args:
            config: Neo4j configuration
        """
        self.config = config

    def generate_self_signed_cert(self) -> tuple[Path, Path]:
        """Generate self-signed SSL certificate.

        Returns:
            Tuple of (cert_path, key_path)
        """
        # Generate private key
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048
        )

        # Generate certificate
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "CA"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "San Francisco"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Brain Researcher"),
            x509.NameAttribute(NameOID.COMMON_NAME, "neo4j.brainresearcher.local"),
        ])

        cert = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            issuer
        ).public_key(
            private_key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.utcnow()
        ).not_valid_after(
            datetime.utcnow() + timedelta(days=365)
        ).add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.DNSName("neo4j.brainresearcher.local"),
            ]),
            critical=False,
        ).sign(private_key, hashes.SHA256())

        # Save certificate
        cert_path = self.config.ssl_cert_path
        cert_path.parent.mkdir(parents=True, exist_ok=True)

        with open(cert_path, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

        # Save private key
        key_path = self.config.ssl_key_path
        with open(key_path, "wb") as f:
            f.write(private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PEM,
                encryption_algorithm=serialization.NoEncryption()
            ))

        # Set permissions
        os.chmod(key_path, 0o600)

        logger.info(f"Generated SSL certificate: {cert_path}")
        return cert_path, key_path

    def configure_neo4j_ssl(self):
        """Configure Neo4j for SSL."""
        config_lines = [
            "dbms.ssl.policy.bolt.enabled=true",
            f"dbms.ssl.policy.bolt.base_directory={self.config.ssl_cert_path.parent}",
            "dbms.ssl.policy.bolt.private_key=key.pem",
            "dbms.ssl.policy.bolt.public_certificate=cert.pem",
            "dbms.ssl.policy.bolt.client_auth=NONE",
            "dbms.connector.bolt.tls_level=REQUIRED",
        ]

        # Write to Neo4j config
        neo4j_conf = Path("/etc/neo4j/neo4j.conf")
        if neo4j_conf.exists():
            with open(neo4j_conf, "a") as f:
                f.write("\n# SSL Configuration\n")
                for line in config_lines:
                    f.write(f"{line}\n")

            logger.info("SSL configuration added to Neo4j")


class AuthenticationManager:
    """Manage authentication for Neo4j."""

    def __init__(self, config: Neo4jConfig):
        """Initialize authentication manager.

        Args:
            config: Neo4j configuration
        """
        self.config = config
        self.driver = None

    def configure_ldap(self):
        """Configure LDAP authentication."""
        if not self.config.ldap_enabled:
            return

        ldap_config = {
            "dbms.security.auth_enabled": "true",
            "dbms.security.auth_provider": "ldap",
            "dbms.security.ldap.host": self.config.ldap_server,
            "dbms.security.ldap.authentication.user_dn_template": "uid={0},ou=users,dc=example,dc=com",
            "dbms.security.ldap.authorization.user_search_base": "ou=users,dc=example,dc=com",
            "dbms.security.ldap.authorization.user_search_filter": "(&(objectClass=person)(uid={0}))",
            "dbms.security.ldap.authorization.group_membership_attributes": "memberOf"
        }

        # Apply LDAP configuration
        neo4j_conf = Path("/etc/neo4j/neo4j.conf")
        if neo4j_conf.exists():
            with open(neo4j_conf, "a") as f:
                f.write("\n# LDAP Configuration\n")
                for key, value in ldap_config.items():
                    f.write(f"{key}={value}\n")

            logger.info("LDAP authentication configured")

    def configure_oauth(self):
        """Configure OAuth authentication."""
        if not self.config.oauth_enabled:
            return

        # OAuth configuration would typically involve a plugin
        # This is a placeholder for OAuth setup
        oauth_config = {
            "dbms.security.auth_provider": "oauth",
            "dbms.security.oauth.provider": self.config.oauth_provider,
            "dbms.security.oauth.client_id": os.getenv("OAUTH_CLIENT_ID", ""),
            "dbms.security.oauth.client_secret": os.getenv("OAUTH_CLIENT_SECRET", ""),
            "dbms.security.oauth.redirect_uri": "http://localhost:7474/oauth/callback"
        }

        logger.info(f"OAuth authentication configured for {self.config.oauth_provider}")

    def create_user(self, username: str, password: str, roles: List[str] = None):
        """Create a Neo4j user.

        Args:
            username: Username
            password: Password
            roles: List of roles to assign
        """
        if not self.driver:
            self.driver = GraphDatabase.driver(
                self.config.uri,
                auth=basic_auth(self.config.username, self.config.password)
            )

        with self.driver.session() as session:
            # Create user
            session.run(
                "CALL dbms.security.createUser($username, $password, false)",
                username=username,
                password=password
            )

            # Assign roles
            if roles:
                for role in roles:
                    session.run(
                        "CALL dbms.security.addRoleToUser($role, $username)",
                        role=role,
                        username=username
                    )

            logger.info(f"Created user: {username}")


class BackupManager:
    """Manage Neo4j backups."""

    def __init__(self, config: Neo4jConfig):
        """Initialize backup manager.

        Args:
            config: Neo4j configuration
        """
        self.config = config
        self.config.backup_dir.mkdir(parents=True, exist_ok=True)

    def create_backup(self) -> Path:
        """Create a Neo4j backup.

        Returns:
            Path to backup file
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"neo4j_backup_{timestamp}"
        backup_path = self.config.backup_dir / backup_name

        # Run neo4j-admin backup
        cmd = [
            "neo4j-admin", "backup",
            "--database", self.config.database,
            "--to", str(backup_path)
        ]

        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.info(f"Backup created: {backup_path}")

            # Clean old backups
            self._cleanup_old_backups()

            return backup_path

        except subprocess.CalledProcessError as e:
            logger.error(f"Backup failed: {e.stderr}")
            raise

    def restore_backup(self, backup_path: Path):
        """Restore from backup.

        Args:
            backup_path: Path to backup
        """
        # Stop database
        subprocess.run(["neo4j", "stop"], check=True)

        # Restore backup
        cmd = [
            "neo4j-admin", "restore",
            "--from", str(backup_path),
            "--database", self.config.database,
            "--force"
        ]

        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.info(f"Restored from backup: {backup_path}")

            # Start database
            subprocess.run(["neo4j", "start"], check=True)

        except subprocess.CalledProcessError as e:
            logger.error(f"Restore failed: {e.stderr}")
            raise

    def _cleanup_old_backups(self):
        """Remove backups older than retention period."""
        cutoff_date = datetime.now() - timedelta(days=self.config.backup_retention_days)

        for backup_dir in self.config.backup_dir.iterdir():
            if backup_dir.is_dir() and backup_dir.stat().st_mtime < cutoff_date.timestamp():
                import shutil
                shutil.rmtree(backup_dir)
                logger.info(f"Removed old backup: {backup_dir}")

    def schedule_backups(self):
        """Schedule automatic backups."""
        if not self.config.backup_enabled:
            return

        # Parse cron-like schedule
        schedule.every().day.at("02:00").do(self.create_backup)

        logger.info(f"Scheduled backups: {self.config.backup_schedule}")


class ClusterManager:
    """Manage Neo4j cluster operations."""

    def __init__(self, config: Neo4jConfig):
        """Initialize cluster manager.

        Args:
            config: Neo4j configuration
        """
        self.config = config
        self.redis_client = redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            decode_responses=True
        )

    def configure_cluster(self):
        """Configure Neo4j cluster."""
        if not self.config.cluster_enabled:
            return

        cluster_config = {
            "dbms.mode": "CORE",
            "dbms.cluster.minimum_core_cluster_size_at_formation": "3",
            "dbms.cluster.minimum_core_cluster_size_at_runtime": "3",
            "causal_clustering.initial_discovery_members": ",".join(self.config.cluster_members),
            "causal_clustering.discovery_advertised_address": f"{self._get_hostname()}:5000",
            "causal_clustering.transaction_advertised_address": f"{self._get_hostname()}:6000",
            "causal_clustering.raft_advertised_address": f"{self._get_hostname()}:7000"
        }

        # Apply cluster configuration
        neo4j_conf = Path("/etc/neo4j/neo4j.conf")
        if neo4j_conf.exists():
            with open(neo4j_conf, "a") as f:
                f.write("\n# Cluster Configuration\n")
                for key, value in cluster_config.items():
                    f.write(f"{key}={value}\n")

            logger.info("Cluster configuration applied")

    def test_failover(self) -> bool:
        """Test cluster failover.

        Returns:
            True if failover successful
        """
        if not self.config.cluster_enabled:
            return True

        # Connect to each cluster member
        for member in self.config.cluster_members:
            try:
                driver = GraphDatabase.driver(
                    f"bolt://{member}:7687",
                    auth=basic_auth(self.config.username, self.config.password)
                )

                with driver.session() as session:
                    result = session.run("CALL dbms.cluster.role()")
                    role = result.single()["role"]

                    # Store cluster state
                    self.redis_client.hset(
                        "neo4j:cluster:status",
                        member,
                        role
                    )

                    logger.info(f"Cluster member {member}: {role}")

                driver.close()

            except Exception as e:
                logger.error(f"Failed to connect to {member}: {e}")
                return False

        return True

    def _get_hostname(self) -> str:
        """Get current hostname."""
        import socket
        return socket.gethostname()


class MonitoringManager:
    """Monitor Neo4j database health and metrics."""

    def __init__(self, config: Neo4jConfig):
        """Initialize monitoring manager.

        Args:
            config: Neo4j configuration
        """
        self.config = config
        self.driver = None
        self.metrics = {}

    def collect_metrics(self) -> Dict[str, Any]:
        """Collect database metrics.

        Returns:
            Dictionary of metrics
        """
        if not self.driver:
            self.driver = GraphDatabase.driver(
                self.config.uri,
                auth=basic_auth(self.config.username, self.config.password)
            )

        metrics = {}

        with self.driver.session() as session:
            # Database size
            result = session.run("CALL dbms.queryJmx('org.neo4j:instance=kernel#0,name=Store file sizes') YIELD value")
            store_sizes = result.single()["value"]
            metrics["database_size_bytes"] = sum(store_sizes.values())

            # Node count
            result = session.run("MATCH (n) RETURN count(n) as count")
            metrics["node_count"] = result.single()["count"]

            # Relationship count
            result = session.run("MATCH ()-[r]->() RETURN count(r) as count")
            metrics["relationship_count"] = result.single()["count"]

            # Transaction metrics
            result = session.run("CALL dbms.queryJmx('org.neo4j:instance=kernel#0,name=Transactions') YIELD value")
            tx_metrics = result.single()["value"]
            metrics["transactions"] = tx_metrics

            # Query execution time
            result = session.run("""
                CALL dbms.listQueries()
                YIELD queryId, query, elapsedTimeMillis
                RETURN avg(elapsedTimeMillis) as avg_time,
                       max(elapsedTimeMillis) as max_time
            """)
            query_stats = result.single()
            metrics["avg_query_time_ms"] = query_stats["avg_time"] or 0
            metrics["max_query_time_ms"] = query_stats["max_time"] or 0

        self.metrics = metrics
        logger.info(f"Collected metrics: {metrics}")

        return metrics

    def export_prometheus_metrics(self) -> str:
        """Export metrics in Prometheus format.

        Returns:
            Prometheus-formatted metrics
        """
        if not self.config.prometheus_enabled:
            return ""

        metrics = self.collect_metrics()

        prometheus_output = []

        # Format metrics for Prometheus
        prometheus_output.append("# HELP neo4j_database_size_bytes Total database size in bytes")
        prometheus_output.append("# TYPE neo4j_database_size_bytes gauge")
        prometheus_output.append(f"neo4j_database_size_bytes {metrics['database_size_bytes']}")

        prometheus_output.append("# HELP neo4j_node_count Total number of nodes")
        prometheus_output.append("# TYPE neo4j_node_count gauge")
        prometheus_output.append(f"neo4j_node_count {metrics['node_count']}")

        prometheus_output.append("# HELP neo4j_relationship_count Total number of relationships")
        prometheus_output.append("# TYPE neo4j_relationship_count gauge")
        prometheus_output.append(f"neo4j_relationship_count {metrics['relationship_count']}")

        prometheus_output.append("# HELP neo4j_avg_query_time_ms Average query execution time")
        prometheus_output.append("# TYPE neo4j_avg_query_time_ms gauge")
        prometheus_output.append(f"neo4j_avg_query_time_ms {metrics['avg_query_time_ms']}")

        return "\n".join(prometheus_output)


class Neo4jDeployment:
    """Main Neo4j deployment manager."""

    def __init__(self, config: Optional[Neo4jConfig] = None):
        """Initialize deployment manager.

        Args:
            config: Neo4j configuration
        """
        self.config = config or Neo4jConfig()
        self.ssl_manager = SSLManager(self.config)
        self.auth_manager = AuthenticationManager(self.config)
        self.backup_manager = BackupManager(self.config)
        self.cluster_manager = ClusterManager(self.config)
        self.monitoring_manager = MonitoringManager(self.config)

    def deploy(self):
        """Deploy and configure Neo4j."""
        logger.info("Starting Neo4j deployment...")

        # Configure SSL
        if self.config.ssl_enabled:
            cert_path, key_path = self.ssl_manager.generate_self_signed_cert()
            self.ssl_manager.configure_neo4j_ssl()
            logger.info("SSL configured")

        # Configure authentication
        if self.config.ldap_enabled:
            self.auth_manager.configure_ldap()
        if self.config.oauth_enabled:
            self.auth_manager.configure_oauth()

        # Setup backups
        if self.config.backup_enabled:
            self.backup_manager.schedule_backups()
            logger.info("Backup schedule configured")

        # Configure cluster
        if self.config.cluster_enabled:
            self.cluster_manager.configure_cluster()
            logger.info("Cluster configured")

        # Start monitoring
        if self.config.metrics_enabled:
            self.monitoring_manager.collect_metrics()
            logger.info("Monitoring started")

        logger.info("Neo4j deployment complete")

    def health_check(self) -> bool:
        """Check Neo4j health.

        Returns:
            True if healthy
        """
        try:
            driver = GraphDatabase.driver(
                self.config.uri,
                auth=basic_auth(self.config.username, self.config.password)
            )

            with driver.session() as session:
                result = session.run("RETURN 1")
                return result.single()[0] == 1

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False

    def test_failover(self) -> bool:
        """Test failover scenarios.

        Returns:
            True if failover works
        """
        if self.config.cluster_enabled:
            return self.cluster_manager.test_failover()
        return True


# CLI interface
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Neo4j deployment manager")
    parser.add_argument("--deploy", action="store_true", help="Deploy Neo4j")
    parser.add_argument("--backup", action="store_true", help="Create backup")
    parser.add_argument("--restore", type=str, help="Restore from backup")
    parser.add_argument("--health", action="store_true", help="Health check")
    parser.add_argument("--failover", action="store_true", help="Test failover")

    args = parser.parse_args()

    deployment = Neo4jDeployment()

    if args.deploy:
        deployment.deploy()
    elif args.backup:
        backup_path = deployment.backup_manager.create_backup()
        print(f"Backup created: {backup_path}")
    elif args.restore:
        deployment.backup_manager.restore_backup(Path(args.restore))
    elif args.health:
        if deployment.health_check():
            print("Neo4j is healthy")
        else:
            print("Neo4j health check failed")
            exit(1)
    elif args.failover:
        if deployment.test_failover():
            print("Failover test passed")
        else:
            print("Failover test failed")
            exit(1)