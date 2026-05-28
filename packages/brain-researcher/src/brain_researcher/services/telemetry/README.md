# TELEMETRY-003 Usage Metrics Tracking System

A comprehensive telemetry and usage metrics tracking system for the Brain Researcher platform with advanced privacy controls, real-time analytics, and feature adoption monitoring.

## 🏗️ Architecture Overview

The telemetry system consists of four main components working together to provide comprehensive usage analytics:

```
┌─────────────────┐    ┌──────────────────┐    ┌────────────────┐    ┌─────────────┐
│  Data Sources   │───▶│  TelemetryAPI    │───▶│  Web Dashboard │───▶│   Insights  │
│                 │    │                  │    │                │    │             │
│ • Agent Service │    │ • REST Endpoints │    │ • Metrics Panel│    │ • Adoption  │
│ • BR-KG API   │    │ • Privacy Rules  │    │ • Heatmaps     │    │ • Patterns  │
│ • Web UI        │    │ • Aggregation    │    │ • Charts       │    │ • Trends    │
│ • Orchestrator  │    │ • Real-time      │    │ • Reports      │    │ • Alerts    │
└─────────────────┘    └──────────────────┘    └────────────────┘    └─────────────┘
```

### Core Components

1. **TelemetryCollector** - Real-time event collection with privacy controls
2. **UsageMetricsAggregator** - Advanced data aggregation and analysis
3. **PrivacyController** - GDPR/CCPA compliant data anonymization
4. **TelemetryAPI** - RESTful endpoints for data access
5. **Service Integrations** - Hooks for Agent, BR-KG, and UI services
6. **React Components** - Interactive dashboards and visualizations

## 🚀 Quick Start

### Backend Setup

```python
from brain_researcher.services.telemetry import TelemetryCollector, TelemetryConfiguration

# Initialize telemetry
config = TelemetryConfiguration(
    collection_enabled=True,
    anonymization_enabled=True,
    gdpr_compliance_mode=True
)

collector = TelemetryCollector(config)
await collector.start()

# Track an event
event_id = collector.collect(
    event_type='tool_invocation',
    service='agent',
    feature_name='fmri_analysis',
    user_id='user_123',
    duration_ms=5000,
    success=True
)
```

### Service Integration

```python
from brain_researcher.services.telemetry.integrations import create_agent_telemetry

# Agent service integration
telemetry = create_agent_telemetry()
telemetry.set_user_context('user_123', 'session_456')

# Track tool usage
telemetry.track_tool_execution(
    tool_name='glm_analysis',
    input_params={'smoothing': 6, 'threshold': 0.001},
    output_artifacts=['statistical_map.nii.gz'],
    execution_time_ms=15000,
    success=True
)
```

### Frontend Integration

```tsx
import { TelemetryProvider, useTelemetry, UsageMetricsPanel } from '@/components/telemetry';

function App() {
  return (
    <TelemetryProvider config={{ enabled: true, apiBaseUrl: '/api/telemetry' }}>
      <Dashboard />
    </TelemetryProvider>
  );
}

function Dashboard() {
  const { trackFeatureUsage } = useTelemetry();
  
  const handleAnalysisClick = () => {
    trackFeatureUsage('analysis_dashboard', 'start_analysis', {
      analysis_type: 'glm',
      dataset_size: 'large'
    });
  };

  return (
    <div>
      <button onClick={handleAnalysisClick}>Start Analysis</button>
      <UsageMetricsPanel />
    </div>
  );
}
```

## 📊 Features

### Data Collection
- **Real-time event tracking** with configurable sampling rates
- **Automatic privacy controls** with PII detection and anonymization
- **Batch processing** for performance optimization
- **Rate limiting** and queue management
- **Session and user journey tracking**

### Privacy & Compliance
- **GDPR/CCPA compliant** data handling
- **Automatic PII detection** and anonymization
- **Configurable retention policies** by privacy level
- **Audit logging** for compliance reporting
- **User consent management**

### Analytics & Visualization
- **Usage metrics** with trend analysis
- **Feature adoption** tracking and maturity analysis
- **Tool usage heatmaps** showing temporal patterns
- **Real-time dashboards** with health monitoring
- **User journey analysis** and funnel optimization

### Service Integration
- **Agent service** - Tool execution and workflow tracking
- **BR-KG service** - Graph query and data ingestion metrics
- **Web UI service** - Component interactions and page views
- **Orchestrator service** - Job management and resource usage

## 🔧 Configuration

### TelemetryConfiguration

```python
config = TelemetryConfiguration(
    # Collection settings
    collection_enabled=True,
    sampling_rate=1.0,  # 100% sampling
    batch_size=100,
    flush_interval_seconds=30,
    
    # Privacy settings
    anonymization_enabled=True,
    ip_anonymization=True,
    user_id_hashing=True,
    gdpr_compliance_mode=True,
    
    # Performance settings
    max_events_per_second=1000,
    async_processing=True,
    queue_max_size=10000,
    
    # Retention policies
    retention_policy_days=90,
    archive_after_days=30
)
```

### Frontend Configuration

```tsx
const telemetryConfig = {
  enabled: process.env.NODE_ENV === 'production',
  apiBaseUrl: '/api/telemetry',
  batchSize: 50,
  flushIntervalMs: 30000,
  samplingRate: 1.0,
  debugMode: process.env.NODE_ENV === 'development'
};

<TelemetryProvider config={telemetryConfig}>
  <App />
</TelemetryProvider>
```

## 🔍 API Endpoints

### Event Collection

```http
POST /telemetry/events/collect
Content-Type: application/json

{
  "event_type": "tool_invocation",
  "service": "agent",
  "feature_name": "fmri_analysis",
  "action": "execute",
  "user_id": "hashed_user_id",
  "duration_ms": 5000,
  "success": true,
  "context": {"analysis_type": "glm"},
  "privacy_level": "aggregate_only"
}
```

### Metrics Retrieval

```http
POST /telemetry/metrics
Content-Type: application/json

{
  "start_time": "2024-01-01T00:00:00Z",
  "end_time": "2024-01-02T00:00:00Z",
  "granularity": "hour",
  "services": ["agent", "web_ui"],
  "metric_types": ["usage_count", "adoption_rate"]
}
```

### Feature Analysis

```http
POST /telemetry/features/analyze
Content-Type: application/json

{
  "start_time": "2024-01-01T00:00:00Z",
  "end_time": "2024-01-07T00:00:00Z",
  "service": "agent",
  "min_usage_count": 5
}
```

### Real-time Metrics

```http
GET /telemetry/realtime
```

## 📱 Frontend Components

### UsageMetricsPanel

Interactive dashboard showing comprehensive usage analytics:

- **Summary cards** with key metrics and trends
- **Time series charts** showing usage patterns over time
- **Feature ranking** with adoption and success rates
- **Performance metrics** including response times and error rates
- **Real-time updates** with health monitoring

### FeatureAdoptionChart

Advanced feature adoption analysis with multiple visualization modes:

- **Adoption matrix** scatter plot showing adoption vs success rates
- **Usage ranking** bar charts with trend indicators
- **Trend analysis** showing feature lifecycle stages
- **Maturity matrix** with strategic recommendations

### ToolUsageHeatmap

Interactive heatmap showing tool usage patterns:

- **24x7 heatmap** showing usage intensity by hour and day
- **Pattern analysis** identifying peak usage times
- **Tool ranking** with performance metrics
- **Category filtering** and trend analysis

## 🛡️ Privacy Features

### Automatic Anonymization

The system automatically detects and anonymizes PII:

```python
# Before anonymization
event = {
    'user_id': 'john.doe@university.edu',
    'context': {
        'researcher_name': 'John Doe',
        'ip_address': '192.168.1.100'
    }
}

# After anonymization  
anonymized_event = {
    'user_id': 'hash_a1b2c3d4e5f6',
    'ip_hash': 'hash_x1y2z3',
    'country_code': 'US',
    'context': {
        'researcher_name_hash': 'hash_n1a2m3e4'
    }
}
```

### Compliance Validation

```python
is_compliant, violations = privacy_controller.validate_data_compliance(event)
if not is_compliant:
    logger.warning(f"Privacy violations detected: {violations}")
```

### Audit Logging

All privacy operations are automatically logged:

```python
audit_logs = privacy_controller.export_audit_log(
    start_time=datetime.now() - timedelta(days=30)
)
```

## 📈 Metrics and KPIs

### Usage Metrics
- **Event volume** - Total events per time period
- **Unique users** - Active user count  
- **Session duration** - Average time spent
- **Success rates** - Operation completion rates
- **Error rates** - Failure analysis by service

### Adoption Metrics
- **Feature adoption rate** - % of users using each feature
- **Retention rate** - Users returning to features
- **Time to adoption** - Speed of feature uptake  
- **Churn analysis** - Feature abandonment patterns
- **Maturity stages** - Feature lifecycle analysis

### Performance Metrics
- **Response times** - P50, P95, P99 percentiles
- **Throughput** - Operations per second
- **Resource utilization** - Memory and CPU usage
- **Queue depths** - Processing backlogs
- **Health scores** - Overall system health

## 🚦 Monitoring and Alerting

### Real-time Monitoring

The system provides real-time monitoring with:

- **Health checks** for all components
- **Performance dashboards** with key metrics
- **Alert thresholds** for anomaly detection
- **Auto-scaling** based on load

### Alert Conditions

```python
# Configure alerts
config.alert_on_errors = True
config.alert_threshold_error_rate = 0.05  # Alert if >5% error rate
config.alert_threshold_response_time_ms = 5000  # Alert if >5s response time
```

## 🧪 Testing and Validation

### Running the Demo

```bash
python -m brain_researcher.services.telemetry.example_usage
```

The demo demonstrates:
- Event collection across all services
- Privacy controls and anonymization
- Metrics aggregation and analysis
- User journey tracking
- Real-time monitoring

### Unit Tests

```bash
pytest tests/unit/telemetry/ tests/integration/telemetry/ -v
```

### Integration Tests

```bash
pytest tests/integration/test_telemetry_system.py -v
```

## 🔄 Data Flow

```
1. Event Generation
   ├── Agent Service (tool execution, workflows)
   ├── BR-KG Service (queries, ingestion)
   ├── Web UI (user interactions, page views)
   └── Orchestrator (job management)
   
2. Collection & Privacy
   ├── Rate limiting and sampling
   ├── PII detection and anonymization
   ├── Privacy level assignment
   └── Batch processing
   
3. Storage & Processing
   ├── Event buffering and queuing
   ├── Real-time aggregation
   ├── Background analytics
   └── Archive management
   
4. API & Visualization
   ├── RESTful API endpoints
   ├── Real-time dashboards
   ├── Interactive charts
   └── Export capabilities
```

## 🔧 Deployment

### Docker Setup

```dockerfile
# Telemetry service container
FROM python:3.9-slim

COPY requirements.txt /app/
RUN pip install -r /app/requirements.txt

COPY . /app/
WORKDIR /app

EXPOSE 8003
CMD ["uvicorn", "brain_researcher.services.telemetry.api:app", "--host", "0.0.0.0", "--port", "8003"]
```

### Environment Variables

```bash
# Collection settings
TELEMETRY_ENABLED=true
TELEMETRY_SAMPLING_RATE=1.0
TELEMETRY_BATCH_SIZE=100

# Privacy settings
TELEMETRY_ANONYMIZATION_ENABLED=true
TELEMETRY_GDPR_MODE=true
TELEMETRY_RETENTION_DAYS=90

# Performance settings  
TELEMETRY_MAX_EVENTS_PER_SEC=1000
TELEMETRY_QUEUE_SIZE=10000
TELEMETRY_FLUSH_INTERVAL_SEC=30

# API settings
TELEMETRY_API_PORT=8003
TELEMETRY_API_HOST=0.0.0.0
```

### Production Considerations

- **Database**: Use PostgreSQL or ClickHouse for production scale
- **Caching**: Redis for real-time metrics and session management
- **Monitoring**: Integrate with Prometheus and Grafana
- **Load balancing**: Multiple telemetry service instances
- **Data retention**: Automated archival and purging policies

## 📚 Additional Resources

- [Privacy Controls Documentation](./privacy.py)
- [API Reference](./api.py) 
- [Frontend Integration Guide](../../../../apps/web-ui/src/components/telemetry/)
- [Service Integration Examples](./integrations.py)
- [Configuration Options](./models.py)

## 🤝 Contributing

1. Follow the existing code structure and patterns
2. Add comprehensive tests for new features
3. Update documentation for API changes
4. Ensure privacy compliance for any new data collection
5. Test with the provided demo scenarios

## 📄 License

This telemetry system is part of the Brain Researcher project and follows the same licensing terms.

---

The TELEMETRY-003 Usage Metrics Tracking System provides comprehensive, privacy-compliant analytics for the Brain Researcher platform, enabling data-driven decisions while respecting user privacy and regulatory requirements.
