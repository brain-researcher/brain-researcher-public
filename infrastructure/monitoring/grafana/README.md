Grafana dashboard provisioning
-----------------------------

- Datasource: `Prometheus` at `http://prometheus:9090` (see `provisioning/datasources/prometheus.yml`).
- Dashboards: all JSON files under `infrastructure/monitoring/grafana/dashboards` are loaded by the default provider (`provisioning/dashboards/dashboard.yml` → `/var/lib/grafana/dashboards`).

Agent metrics scrape (planner/catalog)
--------------------------------------

- The agent exposes Prometheus metrics at `/metrics` (Flask app).
- Kubernetes annotations already enable scraping (`prometheus.io/scrape: "true"`, `prometheus.io/port: "8000"`, `prometheus.io/path: "/metrics"` in `k8s/manifests/03-services.yaml` and `05-statefulsets.yaml`).
- Prometheus job `agent` in `infrastructure/monitoring/prometheus.yml` picks up pods with those annotations.

New dashboard
-------------

- `planner_catalog_monitoring.json` visualizes:
  - `planner_requests_total`, `planner_errors_total`, `planner_request_duration_ms`
  - `catalog_load_failures_total`
  - `tool_executions_total`, `agent_errors_total`
  - Error rate: `rate(planner_errors_total[5m])`
- Import or mount this JSON into the Grafana dashboards directory; it will appear under the “Brain Researcher” folder.
