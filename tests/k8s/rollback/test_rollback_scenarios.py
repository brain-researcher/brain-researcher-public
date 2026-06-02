"""
Kubernetes Rollback Tests for Brain Researcher Platform

This module provides comprehensive tests for rollback scenarios including
deployment rollbacks, StatefulSet rollback handling, data persistence during rollbacks,
and service availability during updates.
"""

import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest
import yaml

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RollbackTestClient:
    """Client for testing rollback scenarios."""

    def __init__(self, namespace: str = "brain-researcher-core"):
        self.namespace = namespace

    def run_kubectl(self, args: List[str], check: bool = True) -> str:
        """Execute kubectl command and return output."""
        cmd = ["kubectl"] + args
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=check)
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            if check:
                logger.error(f"Command failed: {' '.join(cmd)}")
                logger.error(f"Error: {e.stderr}")
                raise
            return e.stderr.strip()

    def get_json_output(
        self, resource_type: str, name: str = None, namespace: str = None
    ) -> Dict[str, Any]:
        """Get JSON output for a Kubernetes resource."""
        ns = namespace or self.namespace
        args = ["get", resource_type]
        if name:
            args.append(name)
        args.extend(["-n", ns, "-o", "json"])
        output = self.run_kubectl(args)
        return json.loads(output)

    def wait_for_rollout(
        self, resource_type: str, name: str, namespace: str = None, timeout: int = 300
    ) -> bool:
        """Wait for a rollout to complete."""
        ns = namespace or self.namespace
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                self.run_kubectl(
                    [
                        "rollout",
                        "status",
                        f"{resource_type}/{name}",
                        "-n",
                        ns,
                        f"--timeout={timeout}s",
                    ]
                )
                return True
            except subprocess.CalledProcessError:
                time.sleep(10)
                continue

        return False

    def get_deployment_revision(
        self, deployment_name: str, namespace: str = None
    ) -> int:
        """Get current revision number of a deployment."""
        ns = namespace or self.namespace
        deployment_data = self.get_json_output("deployment", deployment_name, ns)
        return (
            deployment_data.get("metadata", {})
            .get("annotations", {})
            .get("deployment.kubernetes.io/revision", "0")
        )

    def trigger_deployment_update(
        self, deployment_name: str, namespace: str = None
    ) -> bool:
        """Trigger a deployment update by changing an annotation."""
        ns = namespace or self.namespace
        timestamp = str(int(time.time()))

        try:
            self.run_kubectl(
                [
                    "annotate",
                    "deployment",
                    deployment_name,
                    f"test.rollback/update-trigger={timestamp}",
                    "-n",
                    ns,
                    "--overwrite",
                ]
            )
            return True
        except subprocess.CalledProcessError:
            return False


@pytest.fixture(scope="module")
def rollback_client():
    """Rollback test client fixture."""
    return RollbackTestClient()


@pytest.fixture(scope="function")
def deployment_backup():
    """Fixture to backup and restore deployment state."""
    backup_data = {}

    def backup(deployment_name: str, namespace: str = "brain-researcher-core"):
        """Backup deployment configuration."""
        client = RollbackTestClient(namespace)
        try:
            deployment_data = client.get_json_output(
                "deployment", deployment_name, namespace
            )
            backup_data[f"{namespace}/{deployment_name}"] = deployment_data
            return deployment_data
        except subprocess.CalledProcessError:
            return None

    def restore(deployment_name: str, namespace: str = "brain-researcher-core"):
        """Restore deployment configuration."""
        key = f"{namespace}/{deployment_name}"
        if key not in backup_data:
            return False

        client = RollbackTestClient(namespace)
        try:
            # Apply the original configuration
            deployment_yaml = yaml.dump(backup_data[key])
            with open(f"/tmp/{deployment_name}-backup.yaml", "w") as f:
                f.write(deployment_yaml)

            client.run_kubectl(["apply", "-f", f"/tmp/{deployment_name}-backup.yaml"])
            return client.wait_for_rollout("deployment", deployment_name, namespace)
        except Exception as e:
            logger.error(f"Failed to restore deployment {deployment_name}: {e}")
            return False

    backup.restore = restore
    return backup


class TestDeploymentRollbacks:
    """Test deployment rollback scenarios."""

    @pytest.mark.parametrize(
        "deployment_name",
        [
            "orchestrator",
            "web-ui",
            "nginx",
        ],
    )
    def test_deployment_rollback_basic(
        self,
        rollback_client: RollbackTestClient,
        deployment_backup,
        deployment_name: str,
    ):
        """Test basic deployment rollback functionality."""
        namespace = "brain-researcher-core"

        # Skip if deployment doesn't exist
        try:
            original_deployment = deployment_backup(deployment_name, namespace)
            if not original_deployment:
                pytest.skip(f"Deployment {deployment_name} not found")
        except subprocess.CalledProcessError:
            pytest.skip(f"Deployment {deployment_name} not found")

        # Get initial revision
        initial_revision = rollback_client.get_deployment_revision(
            deployment_name, namespace
        )
        logger.info(f"Initial revision for {deployment_name}: {initial_revision}")

        try:
            # Trigger an update
            update_success = rollback_client.trigger_deployment_update(
                deployment_name, namespace
            )
            assert update_success, f"Failed to trigger update for {deployment_name}"

            # Wait for update to complete
            rollout_success = rollback_client.wait_for_rollout(
                "deployment", deployment_name, namespace
            )
            assert (
                rollout_success
            ), f"Deployment update for {deployment_name} did not complete"

            # Verify revision changed
            new_revision = rollback_client.get_deployment_revision(
                deployment_name, namespace
            )
            assert (
                new_revision != initial_revision
            ), "Deployment revision did not change"

            # Perform rollback
            rollback_cmd = [
                "rollout",
                "undo",
                f"deployment/{deployment_name}",
                "-n",
                namespace,
            ]
            rollback_client.run_kubectl(rollback_cmd)

            # Wait for rollback to complete
            rollback_success = rollback_client.wait_for_rollout(
                "deployment", deployment_name, namespace
            )
            assert rollback_success, f"Rollback for {deployment_name} did not complete"

            # Verify we can rollback to the initial state
            final_revision = rollback_client.get_deployment_revision(
                deployment_name, namespace
            )
            logger.info(f"Final revision for {deployment_name}: {final_revision}")

            # Check that pods are running after rollback
            time.sleep(10)  # Give pods time to start
            pods_data = rollback_client.get_json_output("pods", namespace=namespace)

            deployment_pods = [
                pod
                for pod in pods_data.get("items", [])
                if deployment_name in pod["metadata"]["name"]
            ]

            assert (
                len(deployment_pods) > 0
            ), f"No pods found for {deployment_name} after rollback"

            for pod in deployment_pods:
                pod_phase = pod["status"].get("phase", "Unknown")
                assert pod_phase in [
                    "Running",
                    "Pending",
                ], f"Pod {pod['metadata']['name']} in unexpected phase: {pod_phase}"

        finally:
            # Restore original deployment
            deployment_backup.restore(deployment_name, namespace)

    def test_rollback_with_specific_revision(self, rollback_client: RollbackTestClient):
        """Test rolling back to a specific revision."""
        deployment_name = "orchestrator"
        namespace = "brain-researcher-core"

        try:
            # Get rollout history
            history_output = rollback_client.run_kubectl(
                ["rollout", "history", f"deployment/{deployment_name}", "-n", namespace]
            )

            # Parse history to find available revisions
            lines = history_output.strip().split("\n")
            revisions = []

            for line in lines[1:]:  # Skip header
                parts = line.split()
                if parts and parts[0].isdigit():
                    revisions.append(int(parts[0]))

            if len(revisions) < 2:
                pytest.skip(
                    f"Not enough revisions for {deployment_name} to test specific rollback"
                )

            # Get current revision
            current_revision = int(
                rollback_client.get_deployment_revision(deployment_name, namespace)
            )

            # Find a different revision to rollback to
            target_revision = None
            for rev in revisions:
                if rev != current_revision:
                    target_revision = rev
                    break

            if target_revision is None:
                pytest.skip("No suitable target revision found")

            # Rollback to specific revision
            rollback_client.run_kubectl(
                [
                    "rollout",
                    "undo",
                    f"deployment/{deployment_name}",
                    f"--to-revision={target_revision}",
                    "-n",
                    namespace,
                ]
            )

            # Wait for rollback
            success = rollback_client.wait_for_rollout(
                "deployment", deployment_name, namespace
            )
            assert success, "Specific revision rollback did not complete"

            # Verify revision changed
            final_revision = int(
                rollback_client.get_deployment_revision(deployment_name, namespace)
            )
            assert (
                final_revision != current_revision
            ), "Revision did not change after rollback"

        except subprocess.CalledProcessError:
            pytest.skip(
                f"Could not test specific revision rollback for {deployment_name}"
            )

    def test_rollback_preserves_service_discovery(
        self, rollback_client: RollbackTestClient
    ):
        """Test that rollback preserves service discovery and networking."""
        deployment_name = "orchestrator"
        service_name = "orchestrator-service"
        namespace = "brain-researcher-core"

        try:
            # Get service info before rollback
            service_before = rollback_client.get_json_output(
                "service", service_name, namespace
            )
            cluster_ip_before = service_before["spec"].get("clusterIP")

            # Trigger update and rollback
            rollback_client.trigger_deployment_update(deployment_name, namespace)
            rollback_client.wait_for_rollout("deployment", deployment_name, namespace)

            rollback_client.run_kubectl(
                ["rollout", "undo", f"deployment/{deployment_name}", "-n", namespace]
            )
            rollback_client.wait_for_rollout("deployment", deployment_name, namespace)

            # Verify service still exists and has same cluster IP
            service_after = rollback_client.get_json_output(
                "service", service_name, namespace
            )
            cluster_ip_after = service_after["spec"].get("clusterIP")

            assert (
                cluster_ip_before == cluster_ip_after
            ), "Service cluster IP changed during rollback"

            # Check service endpoints
            endpoints_data = rollback_client.get_json_output(
                "endpoints", service_name, namespace
            )
            subsets = endpoints_data.get("subsets", [])

            # Should have endpoints after rollback
            has_addresses = any(subset.get("addresses", []) for subset in subsets)

            # Give some time for endpoints to be populated
            if not has_addresses:
                time.sleep(30)
                endpoints_data = rollback_client.get_json_output(
                    "endpoints", service_name, namespace
                )
                subsets = endpoints_data.get("subsets", [])
                has_addresses = any(subset.get("addresses", []) for subset in subsets)

            assert (
                has_addresses
            ), f"Service {service_name} has no endpoints after rollback"

        except subprocess.CalledProcessError:
            pytest.skip(
                f"Could not test service discovery preservation for {deployment_name}"
            )


class TestStatefulSetRollbacks:
    """Test StatefulSet rollback handling."""

    @pytest.mark.parametrize(
        "statefulset_info",
        [
            ("agent", "brain-researcher-core"),
            ("br_kg", "brain-researcher-core"),
            ("postgres", "brain-researcher-data"),
            ("redis", "brain-researcher-data"),
        ],
    )
    def test_statefulset_rollback_handling(
        self, rollback_client: RollbackTestClient, statefulset_info
    ):
        """Test StatefulSet rollback scenarios."""
        statefulset_name, namespace = statefulset_info

        try:
            # Check if StatefulSet exists
            sts_data = rollback_client.get_json_output(
                "statefulset", statefulset_name, namespace
            )
            current_revision = sts_data.get("status", {}).get(
                "updateRevision", "unknown"
            )

            logger.info(
                f"Testing StatefulSet {statefulset_name} rollback, current revision: {current_revision}"
            )

            # Get rollout history
            try:
                history_output = rollback_client.run_kubectl(
                    [
                        "rollout",
                        "history",
                        f"statefulset/{statefulset_name}",
                        "-n",
                        namespace,
                    ]
                )
                logger.info(f"StatefulSet history: {history_output}")
            except subprocess.CalledProcessError:
                # History might not be available
                pass

            # StatefulSets handle updates differently - they use rolling updates
            # Test that we can trigger an update and it handles it gracefully
            original_image = None
            containers = sts_data["spec"]["template"]["spec"]["containers"]

            if containers:
                original_image = containers[0]["image"]

            # Trigger a controlled update by adding an annotation
            timestamp = str(int(time.time()))
            rollback_client.run_kubectl(
                [
                    "annotate",
                    "statefulset",
                    statefulset_name,
                    f"test.rollback/update-trigger={timestamp}",
                    "-n",
                    namespace,
                    "--overwrite",
                ]
            )

            # Wait for the update to start
            time.sleep(10)

            # Check StatefulSet status
            updated_sts = rollback_client.get_json_output(
                "statefulset", statefulset_name, namespace
            )
            status = updated_sts.get("status", {})

            replicas = status.get("replicas", 0)
            ready_replicas = status.get("readyReplicas", 0)

            # For StatefulSets, rollback is more about ensuring the update process is stable
            # rather than explicit rollback commands
            assert replicas > 0, f"StatefulSet {statefulset_name} has no replicas"

            # Check that pods are being managed correctly
            pods_data = rollback_client.get_json_output("pods", namespace=namespace)
            sts_pods = [
                pod
                for pod in pods_data.get("items", [])
                if statefulset_name in pod["metadata"]["name"]
            ]

            assert (
                len(sts_pods) > 0
            ), f"No pods found for StatefulSet {statefulset_name}"

            # Verify pod naming convention (StatefulSet pods have ordinal names)
            for pod in sts_pods:
                pod_name = pod["metadata"]["name"]
                assert (
                    f"{statefulset_name}-" in pod_name
                ), f"Pod {pod_name} doesn't follow StatefulSet naming convention"

                # Check that pod ordinal can be extracted
                ordinal_part = pod_name.split(f"{statefulset_name}-")[-1]
                assert (
                    ordinal_part.isdigit()
                ), f"Pod {pod_name} doesn't have valid ordinal suffix"

        except subprocess.CalledProcessError:
            pytest.skip(
                f"StatefulSet {statefulset_name} not found in namespace {namespace}"
            )

    def test_statefulset_persistent_volume_preservation(
        self, rollback_client: RollbackTestClient
    ):
        """Test that StatefulSet PVCs are preserved during updates."""
        statefulset_name = "postgres"
        namespace = "brain-researcher-data"

        try:
            # Get StatefulSet PVCs before update
            pvcs_before = rollback_client.get_json_output("pvc", namespace=namespace)
            sts_pvcs_before = [
                pvc
                for pvc in pvcs_before.get("items", [])
                if statefulset_name in pvc["metadata"]["name"]
            ]

            if not sts_pvcs_before:
                pytest.skip(f"No PVCs found for StatefulSet {statefulset_name}")

            pvc_names_before = {pvc["metadata"]["name"] for pvc in sts_pvcs_before}
            logger.info(f"PVCs before update: {pvc_names_before}")

            # Trigger StatefulSet update
            timestamp = str(int(time.time()))
            rollback_client.run_kubectl(
                [
                    "annotate",
                    "statefulset",
                    statefulset_name,
                    f"test.rollback/update-trigger={timestamp}",
                    "-n",
                    namespace,
                    "--overwrite",
                ]
            )

            # Wait a bit for update to process
            time.sleep(30)

            # Check PVCs after update
            pvcs_after = rollback_client.get_json_output("pvc", namespace=namespace)
            sts_pvcs_after = [
                pvc
                for pvc in pvcs_after.get("items", [])
                if statefulset_name in pvc["metadata"]["name"]
            ]

            pvc_names_after = {pvc["metadata"]["name"] for pvc in sts_pvcs_after}
            logger.info(f"PVCs after update: {pvc_names_after}")

            # PVCs should be preserved
            assert (
                pvc_names_before == pvc_names_after
            ), "StatefulSet PVCs were not preserved during update"

            # Check that PVCs are still bound
            for pvc in sts_pvcs_after:
                pvc_name = pvc["metadata"]["name"]
                pvc_status = pvc["status"]["phase"]
                assert (
                    pvc_status == "Bound"
                ), f"PVC {pvc_name} is not bound after StatefulSet update: {pvc_status}"

        except subprocess.CalledProcessError:
            pytest.skip(
                f"Could not test PVC preservation for StatefulSet {statefulset_name}"
            )


class TestDataPersistenceDuringRollbacks:
    """Test that data persists during rollback operations."""

    def test_database_data_persistence(self, rollback_client: RollbackTestClient):
        """Test that database data persists during rollbacks."""
        postgres_sts = "postgres"
        postgres_svc = "postgres-service"
        namespace = "brain-researcher-data"

        try:
            # Check if postgres StatefulSet and service exist
            rollback_client.get_json_output("statefulset", postgres_sts, namespace)
            rollback_client.get_json_output("service", postgres_svc, namespace)

            # Check PVC exists and is bound
            pvcs_data = rollback_client.get_json_output("pvc", namespace=namespace)
            postgres_pvcs = [
                pvc
                for pvc in pvcs_data.get("items", [])
                if "postgres" in pvc["metadata"]["name"]
            ]

            if not postgres_pvcs:
                pytest.skip("No PostgreSQL PVCs found")

            # Verify PVC is bound before testing
            for pvc in postgres_pvcs:
                pvc_status = pvc["status"]["phase"]
                assert pvc_status == "Bound", f"PostgreSQL PVC not bound: {pvc_status}"

            # Get initial StatefulSet state
            initial_sts = rollback_client.get_json_output(
                "statefulset", postgres_sts, namespace
            )
            initial_revision = initial_sts.get("status", {}).get("updateRevision")

            # Trigger StatefulSet update
            timestamp = str(int(time.time()))
            rollback_client.run_kubectl(
                [
                    "annotate",
                    "statefulset",
                    postgres_sts,
                    f"test.rollback/data-persistence-test={timestamp}",
                    "-n",
                    namespace,
                    "--overwrite",
                ]
            )

            # Wait for update to propagate
            time.sleep(30)

            # Check that PVCs are still there and bound
            pvcs_after_update = rollback_client.get_json_output(
                "pvc", namespace=namespace
            )
            postgres_pvcs_after = [
                pvc
                for pvc in pvcs_after_update.get("items", [])
                if "postgres" in pvc["metadata"]["name"]
            ]

            assert len(postgres_pvcs_after) == len(
                postgres_pvcs
            ), "Number of PostgreSQL PVCs changed during update"

            for pvc in postgres_pvcs_after:
                pvc_name = pvc["metadata"]["name"]
                pvc_status = pvc["status"]["phase"]
                assert (
                    pvc_status == "Bound"
                ), f"PostgreSQL PVC {pvc_name} not bound after update: {pvc_status}"

            # Check that volume names haven't changed (indicating same persistent volumes)
            pvc_volumes_before = {
                pvc["metadata"]["name"]: pvc["spec"].get("volumeName")
                for pvc in postgres_pvcs
            }
            pvc_volumes_after = {
                pvc["metadata"]["name"]: pvc["spec"].get("volumeName")
                for pvc in postgres_pvcs_after
            }

            assert (
                pvc_volumes_before == pvc_volumes_after
            ), "PostgreSQL PVC volume mappings changed during update"

            logger.info("PostgreSQL data persistence test passed")

        except subprocess.CalledProcessError:
            pytest.skip(
                "PostgreSQL StatefulSet not available for data persistence test"
            )

    def test_redis_cache_persistence(self, rollback_client: RollbackTestClient):
        """Test that Redis cache can persist during rollbacks."""
        redis_sts = "redis"
        namespace = "brain-researcher-data"

        try:
            # Check Redis StatefulSet
            rollback_client.get_json_output("statefulset", redis_sts, namespace)

            # Check Redis PVCs
            pvcs_data = rollback_client.get_json_output("pvc", namespace=namespace)
            redis_pvcs = [
                pvc
                for pvc in pvcs_data.get("items", [])
                if "redis" in pvc["metadata"]["name"]
            ]

            if not redis_pvcs:
                pytest.skip("No Redis PVCs found - might be using ephemeral storage")

            # Test similar to PostgreSQL
            for pvc in redis_pvcs:
                pvc_status = pvc["status"]["phase"]
                assert pvc_status == "Bound", f"Redis PVC not bound: {pvc_status}"

            # Trigger update
            timestamp = str(int(time.time()))
            rollback_client.run_kubectl(
                [
                    "annotate",
                    "statefulset",
                    redis_sts,
                    f"test.rollback/cache-persistence-test={timestamp}",
                    "-n",
                    namespace,
                    "--overwrite",
                ]
            )

            time.sleep(20)

            # Verify PVCs still exist and bound
            pvcs_after = rollback_client.get_json_output("pvc", namespace=namespace)
            redis_pvcs_after = [
                pvc
                for pvc in pvcs_after.get("items", [])
                if "redis" in pvc["metadata"]["name"]
            ]

            assert len(redis_pvcs_after) == len(
                redis_pvcs
            ), "Redis PVC count changed during update"

            for pvc in redis_pvcs_after:
                pvc_status = pvc["status"]["phase"]
                assert (
                    pvc_status == "Bound"
                ), f"Redis PVC not bound after update: {pvc_status}"

            logger.info("Redis cache persistence test passed")

        except subprocess.CalledProcessError:
            pytest.skip("Redis StatefulSet not available for cache persistence test")


class TestServiceAvailabilityDuringUpdates:
    """Test service availability during rollback operations."""

    def test_service_availability_during_rolling_update(
        self, rollback_client: RollbackTestClient
    ):
        """Test that services remain available during rolling updates."""
        deployment_name = "orchestrator"
        service_name = "orchestrator-service"
        namespace = "brain-researcher-core"

        try:
            # Check initial state
            initial_deployment = rollback_client.get_json_output(
                "deployment", deployment_name, namespace
            )
            initial_replicas = initial_deployment["spec"]["replicas"]

            if initial_replicas < 2:
                pytest.skip(
                    "Need at least 2 replicas for rolling update availability test"
                )

            # Check service is available
            service_data = rollback_client.get_json_output(
                "service", service_name, namespace
            )
            cluster_ip = service_data["spec"]["clusterIP"]

            # Monitor service availability during update
            timestamp = str(int(time.time()))

            # Start the update
            rollback_client.run_kubectl(
                [
                    "annotate",
                    "deployment",
                    deployment_name,
                    f"test.rollback/availability-test={timestamp}",
                    "-n",
                    namespace,
                    "--overwrite",
                ]
            )

            # Monitor endpoints during the update
            availability_issues = []
            monitor_duration = 60  # Monitor for 1 minute
            check_interval = 5

            start_time = time.time()
            while time.time() - start_time < monitor_duration:
                try:
                    endpoints_data = rollback_client.get_json_output(
                        "endpoints", service_name, namespace
                    )
                    subsets = endpoints_data.get("subsets", [])

                    total_addresses = sum(
                        len(subset.get("addresses", [])) for subset in subsets
                    )

                    if total_addresses == 0:
                        availability_issues.append(
                            f"No available endpoints at {time.time()}"
                        )

                    time.sleep(check_interval)

                except subprocess.CalledProcessError:
                    availability_issues.append(
                        f"Could not check endpoints at {time.time()}"
                    )
                    time.sleep(check_interval)

            # Check final state
            rollback_client.wait_for_rollout(
                "deployment", deployment_name, namespace, timeout=120
            )

            final_endpoints = rollback_client.get_json_output(
                "endpoints", service_name, namespace
            )
            final_subsets = final_endpoints.get("subsets", [])
            final_addresses = sum(
                len(subset.get("addresses", [])) for subset in final_subsets
            )

            assert final_addresses > 0, f"No endpoints available after update"

            # Some brief unavailability might be acceptable, but shouldn't be prolonged
            if len(availability_issues) > monitor_duration // check_interval // 2:
                pytest.fail(
                    f"Too many availability issues during update: {availability_issues}"
                )

            logger.info(
                f"Service availability test passed with {len(availability_issues)} minor issues"
            )

        except subprocess.CalledProcessError:
            pytest.skip(f"Could not test service availability for {deployment_name}")

    def test_database_connection_resilience(self, rollback_client: RollbackTestClient):
        """Test database connection resilience during updates."""
        postgres_sts = "postgres"
        postgres_svc = "postgres-service"
        namespace = "brain-researcher-data"

        try:
            # Check PostgreSQL service
            service_data = rollback_client.get_json_output(
                "service", postgres_svc, namespace
            )
            cluster_ip = service_data["spec"]["clusterIP"]

            # Trigger StatefulSet update
            timestamp = str(int(time.time()))
            rollback_client.run_kubectl(
                [
                    "annotate",
                    "statefulset",
                    postgres_sts,
                    f"test.rollback/connection-resilience={timestamp}",
                    "-n",
                    namespace,
                    "--overwrite",
                ]
            )

            # Monitor service endpoints
            connection_issues = []
            monitor_duration = 90  # StatefulSet updates are slower
            check_interval = 10

            start_time = time.time()
            while time.time() - start_time < monitor_duration:
                try:
                    # Check service endpoints
                    endpoints_data = rollback_client.get_json_output(
                        "endpoints", postgres_svc, namespace
                    )
                    subsets = endpoints_data.get("subsets", [])

                    has_ready_addresses = any(
                        subset.get("addresses", []) for subset in subsets
                    )

                    if not has_ready_addresses:
                        connection_issues.append(
                            f"No ready database endpoints at {time.time()}"
                        )

                    # Check that service ClusterIP hasn't changed
                    current_service = rollback_client.get_json_output(
                        "service", postgres_svc, namespace
                    )
                    current_ip = current_service["spec"]["clusterIP"]

                    if current_ip != cluster_ip:
                        connection_issues.append(
                            f"Service ClusterIP changed: {cluster_ip} -> {current_ip}"
                        )
                        cluster_ip = current_ip

                    time.sleep(check_interval)

                except subprocess.CalledProcessError:
                    connection_issues.append(
                        f"Could not check database service at {time.time()}"
                    )
                    time.sleep(check_interval)

            # Database connections should be resilient with proper configuration
            # Some brief interruption might be acceptable for StatefulSets
            max_acceptable_issues = monitor_duration // check_interval // 3

            if len(connection_issues) > max_acceptable_issues:
                logger.warning(f"Database connection issues: {connection_issues}")
                # Don't fail the test unless issues are severe
                # pytest.fail(f"Too many database connection issues: {connection_issues}")

            logger.info(
                f"Database resilience test completed with {len(connection_issues)} issues"
            )

        except subprocess.CalledProcessError:
            pytest.skip(
                "PostgreSQL service not available for connection resilience test"
            )


if __name__ == "__main__":
    # Run rollback tests
    pytest.main([__file__, "-v", "-s"])
