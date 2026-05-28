# Prometheus Alert Rules for Brain Researcher Orchestrator

This document defines recommended Prometheus alert rules for monitoring the Brain Researcher orchestrator service (P5.11).

## Alert Rule Configuration

These rules should be added to your Prometheus `alerting_rules.yml` configuration file.

```yaml
groups:
  - name: brain_researcher_orchestrator
    interval: 30s
    rules:
      # ===== Job Failure Rate Alerts =====

      - alert: OrchestratorHighJobFailureRate
        expr: |
          (
            rate(brain_researcher_orchestrator_jobs_completed_total{state="failed"}[5m])
            /
            rate(brain_researcher_orchestrator_jobs_completed_total[5m])
          ) > 0.20
        for: 10m
        labels:
          severity: warning
          service: brain_researcher_orchestrator
        annotations:
          summary: "High job failure rate detected"
          description: "Orchestrator has {{ $value | humanizePercentage }} job failure rate over the last 5 minutes (threshold: 20%)."
          runbook_url: "https://brain-researcher.readthedocs.io/ops/runbooks/high-failure-rate/"

      - alert: OrchestratorCriticalJobFailureRate
        expr: |
          (
            rate(brain_researcher_orchestrator_jobs_completed_total{state="failed"}[5m])
            /
            rate(brain_researcher_orchestrator_jobs_completed_total[5m])
          ) > 0.50
        for: 5m
        labels:
          severity: critical
          service: brain_researcher_orchestrator
        annotations:
          summary: "Critical job failure rate detected"
          description: "Orchestrator has {{ $value | humanizePercentage }} job failure rate over the last 5 minutes (threshold: 50%)."
          runbook_url: "https://brain-researcher.readthedocs.io/ops/runbooks/critical-failure-rate/"

      # ===== Job Duration Alerts =====

      - alert: OrchestratorSlowJobProcessing
        expr: |
          histogram_quantile(0.95,
            rate(brain_researcher_orchestrator_jobs_duration_seconds_bucket[10m])
          ) > 1800
        for: 15m
        labels:
          severity: warning
          service: brain_researcher_orchestrator
        annotations:
          summary: "Job processing is slow"
          description: "95th percentile job duration is {{ $value | humanizeDuration }} (threshold: 30m)."
          runbook_url: "https://brain-researcher.readthedocs.io/ops/runbooks/slow-jobs/"

      # ===== Queue Depth Alerts =====

      - alert: OrchestratorQueueBacklog
        expr: |
          brain_researcher_orchestrator_queue_depth{state="pending"} > 100
        for: 10m
        labels:
          severity: warning
          service: brain_researcher_orchestrator
        annotations:
          summary: "Large job queue backlog"
          description: "{{ $value }} jobs pending in queue (threshold: 100)."
          runbook_url: "https://brain-researcher.readthedocs.io/ops/runbooks/queue-backlog/"

      - alert: OrchestratorQueueStalled
        expr: |
          brain_researcher_orchestrator_queue_depth{state="pending"} > 50
          and
          rate(brain_researcher_orchestrator_jobs_completed_total[5m]) == 0
        for: 10m
        labels:
          severity: critical
          service: brain_researcher_orchestrator
        annotations:
          summary: "Job queue is stalled"
          description: "{{ $value }} jobs pending but no jobs completing in the last 5 minutes."
          runbook_url: "https://brain-researcher.readthedocs.io/ops/runbooks/queue-stalled/"

      # ===== Cache Performance Alerts =====

      - alert: OrchestratorLowCacheHitRate
        expr: |
          (
            rate(brain_researcher_orchestrator_cache_operations_total{operation="lookup",result="hit"}[10m])
            /
            rate(brain_researcher_orchestrator_cache_operations_total{operation="lookup"}[10m])
          ) < 0.30
        for: 15m
        labels:
          severity: info
          service: brain_researcher_orchestrator
        annotations:
          summary: "Low cache hit rate"
          description: "Cache hit rate is {{ $value | humanizePercentage }} (threshold: 30%)."
          runbook_url: "https://brain-researcher.readthedocs.io/ops/runbooks/low-cache-hit-rate/"

      # ===== Timeout Alerts =====

      - alert: OrchestratorHighTimeoutRate
        expr: |
          (
            rate(brain_researcher_orchestrator_jobs_completed_total{state="timeout"}[10m])
            /
            rate(brain_researcher_orchestrator_jobs_completed_total[10m])
          ) > 0.10
        for: 10m
        labels:
          severity: warning
          service: brain_researcher_orchestrator
        annotations:
          summary: "High job timeout rate"
          description: "{{ $value | humanizePercentage }} of jobs are timing out (threshold: 10%)."
          runbook_url: "https://brain-researcher.readthedocs.io/ops/runbooks/high-timeout-rate/"

      # ===== Service Health Alerts =====

      - alert: OrchestratorDown
        expr: |
          up{job="brain_researcher_orchestrator"} == 0
        for: 2m
        labels:
          severity: critical
          service: brain_researcher_orchestrator
        annotations:
          summary: "Orchestrator service is down"
          description: "Orchestrator has been down for more than 2 minutes."
          runbook_url: "https://brain-researcher.readthedocs.io/ops/runbooks/service-down/"

      - alert: OrchestratorNoJobActivity
        expr: |
          rate(brain_researcher_orchestrator_jobs_enqueued_total[15m]) == 0
          and
          brain_researcher_orchestrator_queue_depth{state="pending"} == 0
        for: 30m
        labels:
          severity: info
          service: brain_researcher_orchestrator
        annotations:
          summary: "No job activity detected"
          description: "No jobs enqueued or pending for 30 minutes. Service may be idle or experiencing issues."
          runbook_url: "https://brain-researcher.readthedocs.io/ops/runbooks/no-activity/"
```

## Alert Severity Levels

- **critical**: Immediate action required. Service degradation or outage.
- **warning**: Action required soon. Potential service degradation.
- **info**: Informational. May indicate suboptimal performance but not urgent.

## Grafana Alert Manager Integration

To send alerts to Slack, PagerDuty, or email, configure Alertmanager with these routes:

```yaml
route:
  receiver: 'default-receiver'
  group_by: ['alertname', 'service']
  group_wait: 10s
  group_interval: 5m
  repeat_interval: 3h

  routes:
    - match:
        service: brain_researcher_orchestrator
        severity: critical
      receiver: pagerduty-critical
      continue: true

    - match:
        service: brain_researcher_orchestrator
        severity: warning
      receiver: slack-warnings

    - match:
        service: brain_researcher_orchestrator
        severity: info
      receiver: slack-info

receivers:
  - name: 'default-receiver'
    email_configs:
      - to: 'ops@yourcompany.com'

  - name: 'pagerduty-critical'
    pagerduty_configs:
      - service_key: '<your-pagerduty-key>'

  - name: 'slack-warnings'
    slack_configs:
      - api_url: '<your-slack-webhook>'
        channel: '#brain-researcher-alerts'
        title: 'Orchestrator Warning'

  - name: 'slack-info'
    slack_configs:
      - api_url: '<your-slack-webhook>'
        channel: '#brain-researcher-monitoring'
        title: 'Orchestrator Info'
```

## Testing Alerts

To test alert rules before deploying:

```bash
# Validate alert rules syntax
promtool check rules alerting_rules.yml

# Test expression evaluation
promtool query instant http://localhost:9090 \
  'rate(brain_researcher_orchestrator_jobs_completed_total{state="failed"}[5m])'
```

## Tuning Thresholds

Alert thresholds should be adjusted based on your workload characteristics:

| Alert | Default Threshold | Tuning Guidance |
|-------|------------------|-----------------|
| HighJobFailureRate | 20% | Lower for critical pipelines, raise for experimental workloads |
| QueueBacklog | 100 jobs | Adjust based on worker capacity and typical queue size |
| SlowJobProcessing | 30 minutes | Set based on 95th percentile of typical job duration |
| LowCacheHitRate | 30% | Depends on workload diversity - repetitive tasks should have higher hit rates |
| HighTimeoutRate | 10% | Lower if jobs have generous timeout settings |

## Related Documentation

- [Metrics Guide](./metrics.md) - Complete metric reference and PromQL examples
- [Runbooks](../runbooks/) - Step-by-step troubleshooting guides for each alert
- [Grafana Dashboards](../../infra/grafana/) - Pre-built dashboard configurations

## Revision History

- **2025-01-08**: Initial P5.11 alert rules (MVP)
