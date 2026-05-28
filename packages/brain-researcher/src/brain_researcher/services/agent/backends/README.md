# Multi-Backend Runtime Support

This module provides support for executing neuroimaging jobs across multiple backend platforms including Kubernetes, SLURM, and AWS Batch with intelligent selection and transparent failover.

## Features

- **Multiple Backend Support**: Kubernetes, SLURM, AWS Batch
- **Intelligent Selection**: Choose optimal backend based on resources, cost, and availability
- **Transparent Failover**: Automatic failover to alternative backends
- **Unified Job Monitoring**: Track jobs across all backends with consistent interface
- **Resource Management**: Automatic resource matching and capacity planning
- **Cost Optimization**: Consider cost estimates in backend selection

## Architecture

```
BackendSelector
├── KubernetesBackend
├── SLURMBackend
└── AWSBatchBackend
```

All backends implement the `BaseBackend` interface providing:
- Job submission (`submit_job`)
- Status monitoring (`get_job_status`)
- Job cancellation (`cancel_job`)
- Log retrieval (`get_logs`)
- Health checking (`check_health`)
- Capacity reporting (`get_capacity`)

## Quick Start

### 1. Configure Backends

Create a configuration file (see `config/backends_example.yaml`):

```yaml
backends:
  kubernetes:
    enabled: true
    namespace: "brain-researcher"
  slurm:
    enabled: true
    host: "hpc-cluster.example.com"
    username: "user"
    key_file: "/path/to/ssh/key"
  aws_batch:
    enabled: true
    job_queue: "brain-researcher-queue"
    job_definition: "brain-researcher-base"
    role_arn: "arn:aws:iam::account:role/BatchRole"
```

### 2. Initialize Backend Selector

```python
from brain_researcher.services.agent.backends import BackendSelector, SelectionStrategy
from brain_researcher.services.agent.backends import KubernetesBackend, SLURMBackend, AWSBatchBackend

# Initialize backends
backends = []
backends.append(KubernetesBackend('k8s', k8s_config))
backends.append(SLURMBackend('slurm', slurm_config))
backends.append(AWSBatchBackend('aws', aws_config))

# Create selector
selector = BackendSelector(backends, SelectionStrategy.MOST_AVAILABLE)
```

### 3. Submit Jobs

```python
from brain_researcher.services.agent.backends import JobSpecification, ResourceRequirements

# Define job
job_spec = JobSpecification(
    name="fsl-analysis",
    command="fsl_anat -i T1.nii.gz -o output",
    image="neurodesk/fsl:latest",
    environment={"FSLDIR": "/usr/local/fsl"},
    resources=ResourceRequirements(
        cpu=4.0,
        memory_gb=16.0,
        walltime_minutes=120
    )
)

# Submit job with automatic backend selection
backend = await selector.select_with_failover(job_spec.resources)
job_id = await backend.submit_job(job_spec)

# Monitor job
status = await backend.get_job_status(job_id)
print(f"Job {job_id} status: {status.state}")
```

## Backend Implementations

### Kubernetes Backend

- Submits jobs as Kubernetes Jobs
- Supports GPU scheduling
- Automatic pod cleanup
- Resource limits enforcement
- Log aggregation from pods

**Requirements**: `kubernetes` Python library

### SLURM Backend

- SSH-based job submission
- Supports Singularity/Podman containers
- SBATCH script generation
- Queue monitoring via squeue/sacct
- Automatic cleanup

**Requirements**: `paramiko` Python library, SSH access to SLURM head node

### AWS Batch Backend

- AWS Batch job submission
- Dynamic job definition creation
- CloudWatch logs integration
- Spot instance support
- Cost estimation

**Requirements**: `boto3` Python library, AWS credentials

## Selection Strategies

### FASTEST
Selects backend with shortest estimated queue time.

### CHEAPEST
Selects backend with lowest estimated cost.

### MOST_AVAILABLE
Selects backend with highest resource availability ratio.

### PREFERRED
Uses predefined backend preference order with fallback.

### LOAD_BALANCED
Distributes jobs across backends to balance load.

## API Endpoints

The REST API provides endpoints for job management:

- `GET /api/backends/available` - List available backends
- `POST /api/backends/submit` - Submit job for execution
- `GET /api/backends/job/{job_id}` - Get job status
- `DELETE /api/backends/job/{job_id}` - Cancel job
- `GET /api/backends/job/{job_id}/logs` - Get job logs
- `POST /api/backends/health-check` - Check backend health

## Error Handling

### Common Exceptions

- `BackendSubmissionError`: Job submission failed
- `JobNotFoundError`: Job not found in backend
- `BackendUnavailableError`: Backend is unavailable
- `BackendConfigError`: Invalid backend configuration

### Failover Behavior

1. Select primary backend based on strategy
2. Attempt job submission
3. If failure, exclude failed backend
4. Retry with next best backend
5. Continue until success or all backends exhausted

## Monitoring and Observability

### Health Checks
- Periodic backend health monitoring
- Capacity tracking with caching
- Automatic unhealthy backend exclusion

### Metrics
- Job submission success/failure rates
- Backend utilization statistics
- Queue depth monitoring
- Cost tracking per backend

### Logging
- Structured logging for all operations
- Job lifecycle event tracking
- Backend selection reasoning
- Error context preservation

## Configuration Options

### Backend-Specific Settings

**Kubernetes**:
- `namespace`: Target namespace
- `image_pull_policy`: Image pull policy
- `node_selector`: Node selection labels
- `tolerations`: Pod tolerations

**SLURM**:
- `host`: SLURM head node hostname
- `username`: SSH username
- `key_file`/`password`: Authentication
- `partition`: Target partition
- `modules`: Environment modules to load

**AWS Batch**:
- `region`: AWS region
- `job_queue`: Batch job queue
- `job_definition`: Base job definition
- `role_arn`: IAM role for jobs

### Global Settings

- `default_strategy`: Default selection strategy
- `preferred_order`: Backend preference order
- `resource_limits`: Maximum resource limits
- `cost_optimization`: Cost control settings

## Security Considerations

### Kubernetes
- Use service accounts with minimal required permissions
- Network policies for pod isolation
- Resource quotas and limits

### SLURM
- SSH key-based authentication
- Restricted user permissions
- Secure container runtime configuration

### AWS Batch
- IAM roles with least privilege
- VPC security groups
- Encryption at rest and in transit

## Performance Optimization

### Caching
- Backend health status (1 minute TTL)
- Capacity information (5 minute TTL)
- Job status queries (configurable)

### Batch Operations
- Parallel backend health checks
- Concurrent capacity queries
- Bulk job status updates

### Resource Efficiency
- Lazy backend initialization
- Connection pooling where applicable
- Efficient job polling intervals

## Troubleshooting

### Common Issues

1. **Backend not available**
   - Check network connectivity
   - Verify authentication credentials
   - Review backend-specific logs

2. **Job submission failures**
   - Validate resource requirements
   - Check backend capacity
   - Review job specification

3. **Slow job execution**
   - Monitor backend queue depth
   - Consider alternative backends
   - Optimize resource requests

### Debug Mode

Enable debug logging for detailed troubleshooting:

```python
import logging
logging.getLogger('brain_researcher.services.agent.backends').setLevel(logging.DEBUG)
```

## Contributing

When adding new backend implementations:

1. Inherit from `BaseBackend`
2. Implement all abstract methods
3. Add comprehensive error handling
4. Include unit and integration tests
5. Update documentation

## Future Enhancements

- Additional backend support (Azure Batch, Google Cloud)
- Advanced scheduling algorithms
- Machine learning-based backend selection
- Real-time cost optimization
- Integration with workflow engines