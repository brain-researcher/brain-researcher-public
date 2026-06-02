"""
Backup Monitoring Tests

Tests for alert triggering validation, metric collection verification,
and health check validation for the backup system.
"""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
import requests


class TestAlertTriggering:
    """Test backup monitoring alert triggering"""

    def test_backup_failure_alert_triggering(self, backup_config):
        """Test alert triggering when backup fails"""
        failure_scenarios = [
            {
                "component": "postgres",
                "error_type": "connection_error",
                "severity": "high",
                "expected_alert_level": "warning",
            },
            {
                "component": "postgres",
                "error_type": "disk_full",
                "severity": "critical",
                "expected_alert_level": "critical",
            },
            {
                "component": "redis",
                "error_type": "timeout",
                "severity": "medium",
                "expected_alert_level": "info",
            },
        ]

        for scenario in failure_scenarios:
            failure_event = {
                "timestamp": datetime.now().isoformat(),
                "component": scenario["component"],
                "error_type": scenario["error_type"],
                "severity": scenario["severity"],
                "message": f"Backup failed for {scenario['component']}",
            }

            alert_result = self._trigger_backup_failure_alert(
                failure_event, backup_config
            )

            assert alert_result["alert_triggered"] is True
            assert alert_result["alert_level"] == scenario["expected_alert_level"]
            assert alert_result["component"] == scenario["component"]
            assert "notification_channels" in alert_result
            assert len(alert_result["notification_channels"]) > 0

    def test_backup_success_after_failure_alert(self, backup_config):
        """Test alert triggering when backup succeeds after previous failures"""
        # Simulate failure history
        failure_history = [
            {"timestamp": datetime.now() - timedelta(minutes=30), "status": "failed"},
            {"timestamp": datetime.now() - timedelta(minutes=15), "status": "failed"},
        ]

        success_event = {
            "timestamp": datetime.now().isoformat(),
            "component": "postgres",
            "status": "success",
            "message": "Backup completed successfully after previous failures",
        }

        recovery_alert = self._trigger_backup_recovery_alert(
            success_event, failure_history, backup_config
        )

        assert recovery_alert["recovery_alert_triggered"] is True
        assert recovery_alert["alert_level"] == "info"
        assert recovery_alert["previous_failures"] == 2
        assert "recovery_time" in recovery_alert

    def test_backup_duration_threshold_alert(self, backup_config):
        """Test alert triggering when backup takes too long"""
        duration_scenarios = [
            {
                "component": "postgres",
                "duration_minutes": 45,
                "threshold_minutes": 30,
                "expected_alert": True,
            },
            {
                "component": "br_kg",
                "duration_minutes": 25,
                "threshold_minutes": 30,
                "expected_alert": False,
            },
            {
                "component": "redis",
                "duration_minutes": 65,
                "threshold_minutes": 15,
                "expected_alert": True,
            },
        ]

        for scenario in duration_scenarios:
            duration_event = {
                "timestamp": datetime.now().isoformat(),
                "component": scenario["component"],
                "duration_minutes": scenario["duration_minutes"],
                "status": "completed",
            }

            duration_alert = self._trigger_backup_duration_alert(
                duration_event, scenario["threshold_minutes"], backup_config
            )

            if scenario["expected_alert"]:
                assert duration_alert["alert_triggered"] is True
                assert duration_alert["alert_level"] == "warning"
                assert duration_alert["threshold_exceeded"] is True
            else:
                assert duration_alert["alert_triggered"] is False

    def test_backup_size_anomaly_alert(self, backup_config):
        """Test alert triggering for backup size anomalies"""
        size_scenarios = [
            {
                "component": "postgres",
                "current_size_mb": 50,
                "historical_avg_mb": 500,
                "expected_alert": True,
                "anomaly_type": "too_small",
            },
            {
                "component": "br_kg",
                "current_size_mb": 2000,
                "historical_avg_mb": 200,
                "expected_alert": True,
                "anomaly_type": "too_large",
            },
            {
                "component": "redis",
                "current_size_mb": 95,
                "historical_avg_mb": 100,
                "expected_alert": False,
                "anomaly_type": "normal",
            },
        ]

        for scenario in size_scenarios:
            size_event = {
                "timestamp": datetime.now().isoformat(),
                "component": scenario["component"],
                "backup_size_mb": scenario["current_size_mb"],
                "status": "completed",
            }

            size_alert = self._trigger_backup_size_alert(
                size_event, scenario["historical_avg_mb"], backup_config
            )

            if scenario["expected_alert"]:
                assert size_alert["alert_triggered"] is True
                assert size_alert["anomaly_type"] == scenario["anomaly_type"]
                assert (
                    size_alert["size_deviation_percent"] > 50
                )  # Significant deviation
            else:
                assert size_alert["alert_triggered"] is False

    def test_backup_schedule_miss_alert(self, backup_config):
        """Test alert triggering when scheduled backup is missed"""
        scheduled_time = datetime.now() - timedelta(
            hours=2
        )  # Should have run 2 hours ago
        current_time = datetime.now()

        schedule_miss_event = {
            "component": "postgres",
            "scheduled_time": scheduled_time.isoformat(),
            "current_time": current_time.isoformat(),
            "status": "missed",
        }

        schedule_alert = self._trigger_schedule_miss_alert(
            schedule_miss_event, backup_config
        )

        assert schedule_alert["alert_triggered"] is True
        assert schedule_alert["alert_level"] == "warning"
        assert schedule_alert["delay_hours"] == 2
        assert "schedule_compliance" in schedule_alert

    def test_storage_space_threshold_alert(self, backup_config):
        """Test alert triggering for storage space thresholds"""
        storage_scenarios = [
            {"available_space_percent": 5, "expected_alert_level": "critical"},
            {"available_space_percent": 15, "expected_alert_level": "warning"},
            {"available_space_percent": 50, "expected_alert_level": None},  # No alert
        ]

        for scenario in storage_scenarios:
            storage_event = {
                "timestamp": datetime.now().isoformat(),
                "backup_location": "/backups",
                "available_space_percent": scenario["available_space_percent"],
                "total_space_gb": 1000,
                "used_space_gb": 1000
                * (100 - scenario["available_space_percent"])
                / 100,
            }

            storage_alert = self._trigger_storage_space_alert(
                storage_event, backup_config
            )

            if scenario["expected_alert_level"]:
                assert storage_alert["alert_triggered"] is True
                assert storage_alert["alert_level"] == scenario["expected_alert_level"]
                assert storage_alert["space_critical"] is True
            else:
                assert storage_alert["alert_triggered"] is False

    def _trigger_backup_failure_alert(self, failure_event, config):
        """Mock backup failure alert triggering"""
        severity_to_level = {
            "low": "info",
            "medium": "info",
            "high": "warning",
            "critical": "critical",
        }

        alert_level = severity_to_level.get(failure_event["severity"], "warning")

        # Determine notification channels based on alert level
        notification_channels = []
        if alert_level == "info":
            notification_channels = ["log"]
        elif alert_level == "warning":
            notification_channels = ["log", "email"]
        elif alert_level == "critical":
            notification_channels = ["log", "email", "slack", "pager"]

        return {
            "alert_triggered": True,
            "alert_level": alert_level,
            "component": failure_event["component"],
            "error_type": failure_event["error_type"],
            "notification_channels": notification_channels,
            "alert_id": f"backup_failure_{failure_event['component']}_{int(time.time())}",
            "timestamp": failure_event["timestamp"],
        }

    def _trigger_backup_recovery_alert(self, success_event, failure_history, config):
        """Mock backup recovery alert triggering"""
        previous_failures = len(failure_history)

        if previous_failures > 0:
            # Calculate recovery time (time since last failure)
            last_failure_time = max(f["timestamp"] for f in failure_history)
            success_time = datetime.fromisoformat(success_event["timestamp"])
            recovery_time_minutes = (
                success_time - last_failure_time
            ).total_seconds() / 60

            return {
                "recovery_alert_triggered": True,
                "alert_level": "info",
                "component": success_event["component"],
                "previous_failures": previous_failures,
                "recovery_time": f"{recovery_time_minutes:.1f} minutes",
                "alert_id": f"backup_recovery_{success_event['component']}_{int(time.time())}",
                "notification_channels": ["log", "email"],
            }
        else:
            return {"recovery_alert_triggered": False, "reason": "no_previous_failures"}

    def _trigger_backup_duration_alert(self, duration_event, threshold_minutes, config):
        """Mock backup duration alert triggering"""
        duration_minutes = duration_event["duration_minutes"]
        threshold_exceeded = duration_minutes > threshold_minutes

        if threshold_exceeded:
            return {
                "alert_triggered": True,
                "alert_level": "warning",
                "component": duration_event["component"],
                "duration_minutes": duration_minutes,
                "threshold_minutes": threshold_minutes,
                "threshold_exceeded": True,
                "alert_id": f"backup_duration_{duration_event['component']}_{int(time.time())}",
                "notification_channels": ["log", "email"],
            }
        else:
            return {"alert_triggered": False, "duration_within_threshold": True}

    def _trigger_backup_size_alert(self, size_event, historical_avg_mb, config):
        """Mock backup size anomaly alert triggering"""
        current_size = size_event["backup_size_mb"]

        # Calculate deviation percentage
        if historical_avg_mb > 0:
            size_deviation_percent = (
                abs((current_size - historical_avg_mb) / historical_avg_mb) * 100
            )
        else:
            size_deviation_percent = 100

        # Trigger alert if deviation is more than 50%
        alert_triggered = size_deviation_percent > 50

        if alert_triggered:
            if current_size < historical_avg_mb * 0.5:
                anomaly_type = "too_small"
            elif current_size > historical_avg_mb * 1.5:
                anomaly_type = "too_large"
            else:
                anomaly_type = "deviation"

            return {
                "alert_triggered": True,
                "alert_level": "warning",
                "component": size_event["component"],
                "current_size_mb": current_size,
                "historical_avg_mb": historical_avg_mb,
                "size_deviation_percent": size_deviation_percent,
                "anomaly_type": anomaly_type,
                "alert_id": f"backup_size_{size_event['component']}_{int(time.time())}",
                "notification_channels": ["log", "email"],
            }
        else:
            return {"alert_triggered": False, "size_normal": True}

    def _trigger_schedule_miss_alert(self, schedule_event, config):
        """Mock schedule miss alert triggering"""
        scheduled_time = datetime.fromisoformat(schedule_event["scheduled_time"])
        current_time = datetime.fromisoformat(schedule_event["current_time"])

        delay_hours = (current_time - scheduled_time).total_seconds() / 3600

        return {
            "alert_triggered": True,
            "alert_level": "warning",
            "component": schedule_event["component"],
            "scheduled_time": schedule_event["scheduled_time"],
            "current_time": schedule_event["current_time"],
            "delay_hours": delay_hours,
            "schedule_compliance": "violated",
            "alert_id": f"schedule_miss_{schedule_event['component']}_{int(time.time())}",
            "notification_channels": ["log", "email"],
        }

    def _trigger_storage_space_alert(self, storage_event, config):
        """Mock storage space threshold alert triggering"""
        available_percent = storage_event["available_space_percent"]

        if available_percent <= 10:
            alert_level = "critical"
            space_critical = True
        elif available_percent <= 20:
            alert_level = "warning"
            space_critical = True
        else:
            return {"alert_triggered": False, "space_sufficient": True}

        return {
            "alert_triggered": True,
            "alert_level": alert_level,
            "available_space_percent": available_percent,
            "backup_location": storage_event["backup_location"],
            "space_critical": space_critical,
            "alert_id": f"storage_space_{int(time.time())}",
            "notification_channels": (
                ["log", "email", "slack"]
                if alert_level == "critical"
                else ["log", "email"]
            ),
        }


class TestMetricCollection:
    """Test backup monitoring metric collection"""

    def test_backup_performance_metrics_collection(
        self, temp_backup_dir, backup_config
    ):
        """Test collection of backup performance metrics"""
        backup_execution = {
            "component": "postgres",
            "start_time": datetime.now() - timedelta(minutes=30),
            "end_time": datetime.now(),
            "backup_size_bytes": 500 * 1024 * 1024,  # 500MB
            "compression_ratio": 0.3,
            "cpu_usage_percent": 45.2,
            "memory_usage_mb": 1024,
            "disk_io_mbps": 125.5,
            "network_throughput_mbps": 85.3,
        }

        performance_metrics = self._collect_backup_performance_metrics(backup_execution)

        assert performance_metrics["component"] == "postgres"
        assert performance_metrics["duration_minutes"] == 30
        assert performance_metrics["throughput_mbps"] > 0
        assert performance_metrics["compression_effectiveness"] > 0
        assert performance_metrics["resource_utilization"]["cpu_percent"] == 45.2
        assert performance_metrics["resource_utilization"]["memory_mb"] == 1024
        assert "efficiency_score" in performance_metrics

    def test_backup_reliability_metrics_collection(self, backup_config):
        """Test collection of backup reliability metrics"""
        backup_history = [
            {"timestamp": datetime.now() - timedelta(days=7), "status": "success"},
            {"timestamp": datetime.now() - timedelta(days=6), "status": "success"},
            {"timestamp": datetime.now() - timedelta(days=5), "status": "failed"},
            {"timestamp": datetime.now() - timedelta(days=4), "status": "success"},
            {"timestamp": datetime.now() - timedelta(days=3), "status": "success"},
            {"timestamp": datetime.now() - timedelta(days=2), "status": "failed"},
            {"timestamp": datetime.now() - timedelta(days=1), "status": "success"},
        ]

        reliability_metrics = self._collect_backup_reliability_metrics(
            "postgres", backup_history
        )

        assert reliability_metrics["component"] == "postgres"
        assert reliability_metrics["success_rate_percent"] == 71.4  # 5/7 * 100
        assert reliability_metrics["total_attempts"] == 7
        assert reliability_metrics["successful_attempts"] == 5
        assert reliability_metrics["failed_attempts"] == 2
        assert reliability_metrics["mean_time_between_failures_days"] > 0
        assert reliability_metrics["availability_score"] <= 1.0

    def test_storage_utilization_metrics_collection(
        self, temp_backup_dir, backup_config
    ):
        """Test collection of storage utilization metrics"""
        storage_info = {
            "backup_location": str(temp_backup_dir),
            "total_space_gb": 1000,
            "used_space_gb": 650,
            "available_space_gb": 350,
            "backup_files_count": 45,
            "oldest_backup_age_days": 30,
            "retention_policy_days": 30,
        }

        storage_metrics = self._collect_storage_utilization_metrics(storage_info)

        assert storage_metrics["utilization_percent"] == 65.0
        assert storage_metrics["available_percent"] == 35.0
        assert storage_metrics["backup_density"] == 45  # files per location
        assert storage_metrics["retention_compliance"] is True
        assert storage_metrics["storage_efficiency"]["space_per_backup_gb"] > 0
        assert "growth_trend" in storage_metrics

    def test_backup_schedule_compliance_metrics(self, backup_config):
        """Test collection of backup schedule compliance metrics"""
        schedule_events = [
            {
                "component": "postgres",
                "scheduled_time": datetime.now()
                - timedelta(days=1, minutes=5),  # 5 min late
                "actual_time": datetime.now() - timedelta(days=1),
                "status": "completed",
            },
            {
                "component": "postgres",
                "scheduled_time": datetime.now() - timedelta(days=2),
                "actual_time": datetime.now()
                - timedelta(days=2, minutes=-2),  # 2 min early
                "status": "completed",
            },
            {
                "component": "postgres",
                "scheduled_time": datetime.now() - timedelta(days=3),
                "actual_time": None,  # Missed backup
                "status": "missed",
            },
        ]

        compliance_metrics = self._collect_schedule_compliance_metrics(
            "postgres", schedule_events
        )

        assert compliance_metrics["component"] == "postgres"
        assert compliance_metrics["total_scheduled"] == 3
        assert compliance_metrics["completed_on_time"] == 2
        assert compliance_metrics["missed_backups"] == 1
        assert compliance_metrics["compliance_rate_percent"] == 66.7  # 2/3 * 100
        assert compliance_metrics["average_delay_minutes"] > 0
        assert "schedule_reliability_score" in compliance_metrics

    def test_backup_quality_metrics_collection(self, temp_backup_dir, backup_config):
        """Test collection of backup quality and integrity metrics"""
        backup_validations = [
            {
                "component": "postgres",
                "timestamp": datetime.now() - timedelta(days=1),
                "validation_passed": True,
                "integrity_score": 0.98,
                "completeness_score": 1.0,
                "corruption_detected": False,
            },
            {
                "component": "br_kg",
                "timestamp": datetime.now() - timedelta(days=1),
                "validation_passed": True,
                "integrity_score": 0.95,
                "completeness_score": 0.92,
                "corruption_detected": False,
            },
            {
                "component": "redis",
                "timestamp": datetime.now() - timedelta(days=1),
                "validation_passed": False,
                "integrity_score": 0.65,
                "completeness_score": 0.80,
                "corruption_detected": True,
            },
        ]

        quality_metrics = self._collect_backup_quality_metrics(backup_validations)

        assert quality_metrics["total_validations"] == 3
        assert quality_metrics["validations_passed"] == 2
        assert quality_metrics["validation_success_rate"] == 66.7  # 2/3 * 100
        assert quality_metrics["average_integrity_score"] == 0.86  # (0.98+0.95+0.65)/3
        assert (
            quality_metrics["average_completeness_score"] == 0.91
        )  # (1.0+0.92+0.80)/3
        assert quality_metrics["corruption_incidents"] == 1
        assert "overall_quality_score" in quality_metrics

    def test_backup_cost_metrics_collection(self, backup_config):
        """Test collection of backup cost and efficiency metrics"""
        cost_data = [
            {
                "component": "postgres",
                "storage_cost_usd": 12.50,
                "compute_cost_usd": 3.25,
                "network_cost_usd": 1.80,
                "backup_size_gb": 50,
                "processing_time_hours": 0.5,
            },
            {
                "component": "br_kg",
                "storage_cost_usd": 8.30,
                "compute_cost_usd": 2.10,
                "network_cost_usd": 1.20,
                "backup_size_gb": 25,
                "processing_time_hours": 0.3,
            },
        ]

        cost_metrics = self._collect_backup_cost_metrics(cost_data)

        assert cost_metrics["total_monthly_cost_usd"] == 29.15  # Sum of all costs
        assert (
            cost_metrics["storage_cost_percent"] > 50
        )  # Storage should be largest component
        assert cost_metrics["cost_per_gb_usd"] > 0
        assert cost_metrics["cost_efficiency_score"] > 0
        assert len(cost_metrics["cost_breakdown_by_component"]) == 2
        assert "optimization_opportunities" in cost_metrics

    def _collect_backup_performance_metrics(self, execution_data):
        """Mock backup performance metrics collection"""
        duration_minutes = (
            execution_data["end_time"] - execution_data["start_time"]
        ).total_seconds() / 60
        backup_size_mb = execution_data["backup_size_bytes"] / (1024 * 1024)
        throughput_mbps = (
            backup_size_mb / duration_minutes if duration_minutes > 0 else 0
        )

        # Calculate efficiency score based on various factors
        compression_score = (
            1 - execution_data["compression_ratio"]
        ) * 100  # Lower ratio = better
        resource_score = 100 - max(
            execution_data["cpu_usage_percent"],
            execution_data["memory_usage_mb"] / 20.48,
        )  # Normalize memory to %
        throughput_score = min(throughput_mbps / 10 * 100, 100)  # 10 MB/min = 100%

        efficiency_score = (compression_score + resource_score + throughput_score) / 3

        return {
            "component": execution_data["component"],
            "timestamp": execution_data["end_time"].isoformat(),
            "duration_minutes": duration_minutes,
            "backup_size_mb": backup_size_mb,
            "throughput_mbps": throughput_mbps,
            "compression_effectiveness": (1 - execution_data["compression_ratio"])
            * 100,
            "resource_utilization": {
                "cpu_percent": execution_data["cpu_usage_percent"],
                "memory_mb": execution_data["memory_usage_mb"],
                "disk_io_mbps": execution_data["disk_io_mbps"],
                "network_mbps": execution_data["network_throughput_mbps"],
            },
            "efficiency_score": round(efficiency_score, 2),
        }

    def _collect_backup_reliability_metrics(self, component, history):
        """Mock backup reliability metrics collection"""
        total_attempts = len(history)
        successful_attempts = len([h for h in history if h["status"] == "success"])
        failed_attempts = total_attempts - successful_attempts

        success_rate = (
            (successful_attempts / total_attempts) * 100 if total_attempts > 0 else 0
        )

        # Calculate MTBF (Mean Time Between Failures)
        failure_timestamps = [
            h["timestamp"] for h in history if h["status"] == "failed"
        ]
        if len(failure_timestamps) > 1:
            time_between_failures = []
            for i in range(1, len(failure_timestamps)):
                diff = (failure_timestamps[i] - failure_timestamps[i - 1]).days
                time_between_failures.append(diff)
            mtbf_days = sum(time_between_failures) / len(time_between_failures)
        else:
            mtbf_days = 0

        # Availability score (considering recent history more heavily)
        recent_history = history[-7:]  # Last 7 backups
        recent_success_rate = len(
            [h for h in recent_history if h["status"] == "success"]
        ) / len(recent_history)
        availability_score = (
            success_rate * 0.3 + recent_success_rate * 100 * 0.7
        ) / 100

        return {
            "component": component,
            "timestamp": datetime.now().isoformat(),
            "total_attempts": total_attempts,
            "successful_attempts": successful_attempts,
            "failed_attempts": failed_attempts,
            "success_rate_percent": round(success_rate, 1),
            "mean_time_between_failures_days": round(mtbf_days, 1),
            "availability_score": round(availability_score, 3),
        }

    def _collect_storage_utilization_metrics(self, storage_info):
        """Mock storage utilization metrics collection"""
        utilization_percent = (
            storage_info["used_space_gb"] / storage_info["total_space_gb"]
        ) * 100
        available_percent = 100 - utilization_percent

        space_per_backup_gb = (
            storage_info["used_space_gb"] / storage_info["backup_files_count"]
        )
        retention_compliance = (
            storage_info["oldest_backup_age_days"]
            <= storage_info["retention_policy_days"]
        )

        # Estimate growth trend (mock calculation)
        daily_growth_gb = storage_info["used_space_gb"] / max(
            storage_info["oldest_backup_age_days"], 1
        )
        projected_full_days = (
            storage_info["available_space_gb"] / daily_growth_gb
            if daily_growth_gb > 0
            else float("inf")
        )

        return {
            "backup_location": storage_info["backup_location"],
            "timestamp": datetime.now().isoformat(),
            "total_space_gb": storage_info["total_space_gb"],
            "used_space_gb": storage_info["used_space_gb"],
            "available_space_gb": storage_info["available_space_gb"],
            "utilization_percent": round(utilization_percent, 1),
            "available_percent": round(available_percent, 1),
            "backup_density": storage_info["backup_files_count"],
            "retention_compliance": retention_compliance,
            "storage_efficiency": {
                "space_per_backup_gb": round(space_per_backup_gb, 2),
                "compression_savings_gb": storage_info["used_space_gb"]
                * 0.7,  # Estimated
            },
            "growth_trend": {
                "daily_growth_gb": round(daily_growth_gb, 2),
                "projected_full_days": (
                    round(projected_full_days, 1)
                    if projected_full_days != float("inf")
                    else None
                ),
            },
        }

    def _collect_schedule_compliance_metrics(self, component, schedule_events):
        """Mock schedule compliance metrics collection"""
        total_scheduled = len(schedule_events)
        completed_events = [e for e in schedule_events if e["status"] == "completed"]
        missed_backups = len([e for e in schedule_events if e["status"] == "missed"])

        # Calculate delays for completed backups
        delays_minutes = []
        for event in completed_events:
            if event["actual_time"]:
                scheduled = event["scheduled_time"]
                actual = event["actual_time"]
                delay_minutes = (actual - scheduled).total_seconds() / 60
                delays_minutes.append(delay_minutes)

        average_delay = (
            sum(delays_minutes) / len(delays_minutes) if delays_minutes else 0
        )
        on_time_count = len(
            [d for d in delays_minutes if abs(d) <= 5]
        )  # Within 5 minutes

        compliance_rate = (
            (on_time_count / total_scheduled) * 100 if total_scheduled > 0 else 0
        )
        reliability_score = (
            ((total_scheduled - missed_backups) / total_scheduled)
            if total_scheduled > 0
            else 0
        )

        return {
            "component": component,
            "timestamp": datetime.now().isoformat(),
            "total_scheduled": total_scheduled,
            "completed_on_time": on_time_count,
            "completed_late": len(completed_events) - on_time_count,
            "missed_backups": missed_backups,
            "compliance_rate_percent": round(compliance_rate, 1),
            "average_delay_minutes": round(average_delay, 1),
            "schedule_reliability_score": round(reliability_score, 3),
        }

    def _collect_backup_quality_metrics(self, validations):
        """Mock backup quality metrics collection"""
        total_validations = len(validations)
        passed_validations = len([v for v in validations if v["validation_passed"]])
        corruption_incidents = len([v for v in validations if v["corruption_detected"]])

        validation_success_rate = (
            (passed_validations / total_validations) * 100
            if total_validations > 0
            else 0
        )

        # Calculate average scores
        avg_integrity = (
            sum(v["integrity_score"] for v in validations) / total_validations
        )
        avg_completeness = (
            sum(v["completeness_score"] for v in validations) / total_validations
        )

        # Overall quality score combines multiple factors
        corruption_penalty = (corruption_incidents / total_validations) * 100
        overall_quality = (
            validation_success_rate * 0.4
            + avg_integrity * 100 * 0.3
            + avg_completeness * 100 * 0.3
            - corruption_penalty * 0.1
        )

        return {
            "timestamp": datetime.now().isoformat(),
            "total_validations": total_validations,
            "validations_passed": passed_validations,
            "validations_failed": total_validations - passed_validations,
            "validation_success_rate": round(validation_success_rate, 1),
            "average_integrity_score": round(avg_integrity, 2),
            "average_completeness_score": round(avg_completeness, 2),
            "corruption_incidents": corruption_incidents,
            "overall_quality_score": round(
                max(overall_quality, 0), 2
            ),  # Don't go below 0
        }

    def _collect_backup_cost_metrics(self, cost_data):
        """Mock backup cost metrics collection"""
        total_cost = sum(
            c["storage_cost_usd"] + c["compute_cost_usd"] + c["network_cost_usd"]
            for c in cost_data
        )

        total_storage_cost = sum(c["storage_cost_usd"] for c in cost_data)
        total_size_gb = sum(c["backup_size_gb"] for c in cost_data)

        storage_cost_percent = (
            (total_storage_cost / total_cost) * 100 if total_cost > 0 else 0
        )
        cost_per_gb = total_cost / total_size_gb if total_size_gb > 0 else 0

        # Cost efficiency score (lower cost per GB = higher score)
        baseline_cost_per_gb = 0.50  # $0.50 per GB baseline
        efficiency_score = max(
            0, (baseline_cost_per_gb - cost_per_gb) / baseline_cost_per_gb * 100
        )

        component_breakdown = {}
        for c in cost_data:
            component_cost = (
                c["storage_cost_usd"] + c["compute_cost_usd"] + c["network_cost_usd"]
            )
            component_breakdown[c["component"]] = {
                "total_cost_usd": component_cost,
                "cost_per_gb_usd": (
                    component_cost / c["backup_size_gb"]
                    if c["backup_size_gb"] > 0
                    else 0
                ),
                "size_gb": c["backup_size_gb"],
            }

        return {
            "timestamp": datetime.now().isoformat(),
            "total_monthly_cost_usd": round(total_cost, 2),
            "storage_cost_percent": round(storage_cost_percent, 1),
            "compute_cost_percent": round(
                (sum(c["compute_cost_usd"] for c in cost_data) / total_cost) * 100, 1
            ),
            "network_cost_percent": round(
                (sum(c["network_cost_usd"] for c in cost_data) / total_cost) * 100, 1
            ),
            "cost_per_gb_usd": round(cost_per_gb, 3),
            "cost_efficiency_score": round(efficiency_score, 1),
            "cost_breakdown_by_component": component_breakdown,
            "optimization_opportunities": (
                [
                    "Implement data deduplication",
                    "Optimize backup schedules",
                    "Use cheaper storage tiers for older backups",
                ]
                if efficiency_score < 70
                else []
            ),
        }


class TestHealthCheckValidation:
    """Test backup system health check validation"""

    def test_backup_service_health_check(self, backup_config):
        """Test health check validation for backup services"""
        service_components = [
            {
                "name": "postgres_backup_service",
                "status": "running",
                "last_execution": datetime.now() - timedelta(hours=2),
                "next_scheduled": datetime.now() + timedelta(hours=22),
            },
            {
                "name": "br_kg_backup_service",
                "status": "stopped",
                "last_execution": datetime.now() - timedelta(days=2),
                "next_scheduled": None,
            },
            {
                "name": "redis_backup_service",
                "status": "running",
                "last_execution": datetime.now() - timedelta(minutes=30),
                "next_scheduled": datetime.now() + timedelta(hours=23, minutes=30),
            },
        ]

        health_check = self._perform_service_health_check(service_components)

        assert health_check["overall_health"] == "degraded"  # One service stopped
        assert health_check["healthy_services"] == 2
        assert health_check["unhealthy_services"] == 1
        assert "br_kg_backup_service" in health_check["failed_services"]
        assert len(health_check["recommendations"]) > 0

    def test_backup_storage_health_check(self, temp_backup_dir, backup_config):
        """Test health check validation for backup storage"""
        storage_locations = [
            {
                "path": str(temp_backup_dir),
                "type": "local",
                "accessible": True,
                "free_space_gb": 500,
                "total_space_gb": 1000,
                "read_write_test": True,
            },
            {
                "path": "s3://backup-bucket/brain-researcher/",
                "type": "s3",
                "accessible": False,  # Simulating S3 access issue
                "free_space_gb": None,
                "total_space_gb": None,
                "read_write_test": False,
            },
        ]

        storage_health = self._perform_storage_health_check(storage_locations)

        assert storage_health["overall_health"] == "warning"
        assert storage_health["accessible_locations"] == 1
        assert storage_health["inaccessible_locations"] == 1
        assert storage_health["local_storage_healthy"] is True
        assert storage_health["remote_storage_healthy"] is False
        assert "s3_connectivity_issue" in [
            issue["type"] for issue in storage_health["issues"]
        ]

    def test_backup_encryption_health_check(self, temp_backup_dir, mock_encryption_key):
        """Test health check validation for backup encryption"""
        encryption_components = [
            {
                "component": "encryption_key",
                "status": "valid",
                "key_file": str(mock_encryption_key),
                "key_accessible": True,
                "key_permissions": "600",
            },
            {
                "component": "openssl_binary",
                "status": "available",
                "version": "1.1.1f",
                "algorithms_supported": ["aes-256-cbc", "aes-128-cbc"],
            },
            {
                "component": "test_encryption",
                "status": "passed",
                "encrypt_test_successful": True,
                "decrypt_test_successful": True,
            },
        ]

        encryption_health = self._perform_encryption_health_check(encryption_components)

        assert encryption_health["overall_health"] == "healthy"
        assert encryption_health["encryption_available"] is True
        assert encryption_health["key_management_healthy"] is True
        assert encryption_health["algorithm_support_adequate"] is True
        assert len(encryption_health["security_issues"]) == 0

    def test_backup_network_connectivity_health_check(self, backup_config):
        """Test health check validation for network connectivity"""
        network_targets = [
            {
                "name": "database_server",
                "host": "localhost",
                "port": 5432,
                "protocol": "postgresql",
                "reachable": True,
                "response_time_ms": 25,
            },
            {
                "name": "s3_endpoint",
                "host": "s3.amazonaws.com",
                "port": 443,
                "protocol": "https",
                "reachable": False,
                "response_time_ms": None,
            },
            {
                "name": "webhook_endpoint",
                "host": "notifications.example.com",
                "port": 443,
                "protocol": "https",
                "reachable": True,
                "response_time_ms": 150,
            },
        ]

        network_health = self._perform_network_health_check(network_targets)

        assert network_health["overall_health"] == "degraded"
        assert network_health["reachable_targets"] == 2
        assert network_health["unreachable_targets"] == 1
        assert (
            network_health["critical_services_reachable"] is True
        )  # Database is critical
        assert network_health["average_response_time_ms"] == 87.5  # (25+150)/2

    def test_backup_integrity_health_check(self, temp_backup_dir, backup_config):
        """Test health check validation for backup integrity"""
        recent_backups = [
            {
                "component": "postgres",
                "file": temp_backup_dir / "postgres_20240101_120000.sql.gz.enc",
                "timestamp": datetime.now() - timedelta(hours=2),
                "integrity_verified": True,
                "corruption_detected": False,
                "size_normal": True,
            },
            {
                "component": "br_kg",
                "file": temp_backup_dir / "br_kg_20240101_120000.tar.gz.enc",
                "timestamp": datetime.now() - timedelta(hours=3),
                "integrity_verified": False,  # Failed verification
                "corruption_detected": True,
                "size_normal": False,
            },
            {
                "component": "redis",
                "file": temp_backup_dir / "redis_20240101_120000.tar.gz.enc",
                "timestamp": datetime.now() - timedelta(hours=1),
                "integrity_verified": True,
                "corruption_detected": False,
                "size_normal": True,
            },
        ]

        # Create the backup files for testing
        for backup in recent_backups:
            backup["file"].write_text("mock backup content")

        integrity_health = self._perform_integrity_health_check(recent_backups)

        assert integrity_health["overall_health"] == "warning"
        assert integrity_health["verified_backups"] == 2
        assert integrity_health["failed_verifications"] == 1
        assert integrity_health["corruption_detected"] == 1
        assert integrity_health["integrity_success_rate"] == 66.7  # 2/3 * 100
        assert "br_kg" in [
            issue["component"] for issue in integrity_health["integrity_issues"]
        ]

    def test_comprehensive_system_health_check(self, temp_backup_dir, backup_config):
        """Test comprehensive system health check combining all components"""
        system_components = {
            "services": "healthy",
            "storage": "warning",
            "encryption": "healthy",
            "network": "degraded",
            "integrity": "warning",
        }

        comprehensive_health = self._perform_comprehensive_health_check(
            system_components
        )

        assert comprehensive_health["overall_system_health"] == "degraded"
        assert comprehensive_health["healthy_components"] == 2
        assert comprehensive_health["warning_components"] == 2
        assert comprehensive_health["critical_components"] == 0
        assert comprehensive_health["degraded_components"] == 1
        assert comprehensive_health["system_operational"] is True
        assert comprehensive_health["immediate_attention_required"] is True
        assert len(comprehensive_health["priority_actions"]) > 0

    def _perform_service_health_check(self, service_components):
        """Mock service health check"""
        healthy_services = 0
        unhealthy_services = 0
        failed_services = []
        recommendations = []

        for service in service_components:
            if service["status"] == "running":
                # Check if last execution was recent enough
                hours_since_last = (
                    datetime.now() - service["last_execution"]
                ).total_seconds() / 3600
                if hours_since_last > 25:  # More than 25 hours (daily + buffer)
                    unhealthy_services += 1
                    failed_services.append(service["name"])
                    recommendations.append(f"Check {service['name']} schedule")
                else:
                    healthy_services += 1
            else:
                unhealthy_services += 1
                failed_services.append(service["name"])
                recommendations.append(f"Restart {service['name']} service")

        if unhealthy_services == 0:
            overall_health = "healthy"
        elif unhealthy_services < len(service_components) / 2:
            overall_health = "degraded"
        else:
            overall_health = "critical"

        return {
            "overall_health": overall_health,
            "total_services": len(service_components),
            "healthy_services": healthy_services,
            "unhealthy_services": unhealthy_services,
            "failed_services": failed_services,
            "recommendations": recommendations,
        }

    def _perform_storage_health_check(self, storage_locations):
        """Mock storage health check"""
        accessible_locations = 0
        inaccessible_locations = 0
        local_healthy = False
        remote_healthy = True
        issues = []

        for location in storage_locations:
            if location["accessible"]:
                accessible_locations += 1
                if location["type"] == "local":
                    local_healthy = True
                    # Check disk space
                    if location["free_space_gb"] and location["total_space_gb"]:
                        usage_percent = (
                            1 - location["free_space_gb"] / location["total_space_gb"]
                        ) * 100
                        if usage_percent > 90:
                            issues.append(
                                {
                                    "type": "disk_space_critical",
                                    "location": location["path"],
                                    "usage_percent": usage_percent,
                                }
                            )
            else:
                inaccessible_locations += 1
                if location["type"] == "s3":
                    remote_healthy = False
                    issues.append(
                        {"type": "s3_connectivity_issue", "location": location["path"]}
                    )

        if inaccessible_locations == 0:
            overall_health = "healthy"
        elif local_healthy:
            overall_health = "warning"
        else:
            overall_health = "critical"

        return {
            "overall_health": overall_health,
            "total_locations": len(storage_locations),
            "accessible_locations": accessible_locations,
            "inaccessible_locations": inaccessible_locations,
            "local_storage_healthy": local_healthy,
            "remote_storage_healthy": remote_healthy,
            "issues": issues,
        }

    def _perform_encryption_health_check(self, encryption_components):
        """Mock encryption health check"""
        all_components_healthy = True
        security_issues = []

        for component in encryption_components:
            if component["status"] not in ["valid", "available", "passed"]:
                all_components_healthy = False
                security_issues.append(
                    {
                        "component": component["component"],
                        "issue": f"Component status is {component['status']}",
                    }
                )

        # Check key file permissions
        key_component = next(
            (c for c in encryption_components if c["component"] == "encryption_key"),
            None,
        )
        if key_component and key_component.get("key_permissions") != "600":
            security_issues.append(
                {
                    "component": "encryption_key",
                    "issue": "Key file permissions too permissive",
                }
            )

        return {
            "overall_health": "healthy" if all_components_healthy else "warning",
            "encryption_available": all_components_healthy,
            "key_management_healthy": (
                key_component["status"] == "valid" if key_component else False
            ),
            "algorithm_support_adequate": any(
                c["component"] == "openssl_binary"
                and "aes-256-cbc" in c.get("algorithms_supported", [])
                for c in encryption_components
            ),
            "security_issues": security_issues,
        }

    def _perform_network_health_check(self, network_targets):
        """Mock network health check"""
        reachable_targets = len([t for t in network_targets if t["reachable"]])
        unreachable_targets = len(network_targets) - reachable_targets

        # Database is critical for backups
        critical_services = ["database_server"]
        critical_reachable = all(
            t["reachable"] for t in network_targets if t["name"] in critical_services
        )

        # Calculate average response time for reachable targets
        response_times = [
            t["response_time_ms"]
            for t in network_targets
            if t["reachable"] and t["response_time_ms"] is not None
        ]
        avg_response_time = (
            sum(response_times) / len(response_times) if response_times else 0
        )

        if unreachable_targets == 0:
            overall_health = "healthy"
        elif critical_reachable:
            overall_health = "degraded"
        else:
            overall_health = "critical"

        return {
            "overall_health": overall_health,
            "total_targets": len(network_targets),
            "reachable_targets": reachable_targets,
            "unreachable_targets": unreachable_targets,
            "critical_services_reachable": critical_reachable,
            "average_response_time_ms": round(avg_response_time, 1),
        }

    def _perform_integrity_health_check(self, recent_backups):
        """Mock integrity health check"""
        verified_backups = len([b for b in recent_backups if b["integrity_verified"]])
        failed_verifications = len(recent_backups) - verified_backups
        corruption_detected = len(
            [b for b in recent_backups if b["corruption_detected"]]
        )

        success_rate = (
            (verified_backups / len(recent_backups)) * 100 if recent_backups else 0
        )

        integrity_issues = []
        for backup in recent_backups:
            if not backup["integrity_verified"] or backup["corruption_detected"]:
                integrity_issues.append(
                    {
                        "component": backup["component"],
                        "file": str(backup["file"]),
                        "issue": (
                            "corruption_detected"
                            if backup["corruption_detected"]
                            else "verification_failed"
                        ),
                    }
                )

        if corruption_detected > 0 or failed_verifications > 0:
            overall_health = "warning" if corruption_detected == 1 else "critical"
        else:
            overall_health = "healthy"

        return {
            "overall_health": overall_health,
            "total_backups_checked": len(recent_backups),
            "verified_backups": verified_backups,
            "failed_verifications": failed_verifications,
            "corruption_detected": corruption_detected,
            "integrity_success_rate": round(success_rate, 1),
            "integrity_issues": integrity_issues,
        }

    def _perform_comprehensive_health_check(self, system_components):
        """Mock comprehensive system health check"""
        health_scores = {"healthy": 100, "warning": 75, "degraded": 50, "critical": 25}

        component_counts = {}
        total_score = 0

        for component, health in system_components.items():
            component_counts[health] = component_counts.get(health, 0) + 1
            total_score += health_scores[health]

        average_score = total_score / len(system_components)

        # Determine overall health
        if average_score >= 90:
            overall_health = "healthy"
        elif average_score >= 70:
            overall_health = "warning"
        elif average_score >= 50:
            overall_health = "degraded"
        else:
            overall_health = "critical"

        # System is operational if no critical components
        system_operational = component_counts.get("critical", 0) == 0

        # Immediate attention needed if any critical or multiple degraded
        immediate_attention = (
            component_counts.get("critical", 0) > 0
            or component_counts.get("degraded", 0) > 1
        )

        priority_actions = []
        if component_counts.get("critical", 0) > 0:
            priority_actions.append("Address critical component failures immediately")
        if component_counts.get("degraded", 0) > 0:
            priority_actions.append("Investigate degraded components")
        if component_counts.get("warning", 0) > 1:
            priority_actions.append("Review warning components to prevent degradation")

        return {
            "overall_system_health": overall_health,
            "system_score": round(average_score, 1),
            "total_components": len(system_components),
            "healthy_components": component_counts.get("healthy", 0),
            "warning_components": component_counts.get("warning", 0),
            "degraded_components": component_counts.get("degraded", 0),
            "critical_components": component_counts.get("critical", 0),
            "system_operational": system_operational,
            "immediate_attention_required": immediate_attention,
            "priority_actions": priority_actions,
        }
