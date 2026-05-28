# Brain Researcher Monitoring Runbooks

## Service Health Alerts

### ServiceDown
**Alert:** Service {{ $labels.job }} is down
**Severity:** Critical
**Troubleshooting:**
1. Check service status: `docker ps | grep {{ $labels.job }}`
2. Check service logs: `docker logs brain-researcher-{{ $labels.job }}`
3. Restart service: `docker-compose restart {{ $labels.job }}`
4. If persistent, check resource constraints and dependencies
5. Escalate to on-call engineer if restart fails

### HighErrorRate
**Alert:** High error rate on {{ $labels.job }}
**Severity:** Warning
**Troubleshooting:**
1. Check application logs for error patterns
2. Review recent deployments or configuration changes
3. Check dependent services availability
4. Monitor user reports and application metrics
5. Consider rolling back if errors correlate with recent changes

### HighLatency
**Alert:** High response time on {{ $labels.job }}
**Severity:** Warning
**Troubleshooting:**
1. Check CPU and memory usage
2. Review database query performance
3. Check for resource contention
4. Analyze slow request patterns
5. Consider scaling resources or optimizing queries

## System Resource Alerts

### HighCPUUsage
**Alert:** High CPU usage on {{ $labels.instance }}
**Severity:** Warning
**Troubleshooting:**
1. Identify top CPU consumers: `top` or `htop`
2. Check for runaway processes
3. Review recent application changes
4. Consider vertical or horizontal scaling
5. Optimize resource-intensive operations

### HighMemoryUsage
**Alert:** High memory usage on {{ $labels.instance }}
**Severity:** Warning
**Troubleshooting:**
1. Check memory usage by process: `ps aux --sort=-%mem | head`
2. Look for memory leaks in applications
3. Check for large caches that can be cleared
4. Consider increasing memory limits
5. Monitor garbage collection in applications

### DiskSpaceLow/DiskSpaceCritical
**Alert:** Low/Critical disk space on {{ $labels.instance }}
**Severity:** Warning/Critical
**Troubleshooting:**
1. Check disk usage: `df -h`
2. Find large files/directories: `du -sh /* | sort -h`
3. Clean up old logs: `journalctl --vacuum-time=7d`
4. Clear Docker unused resources: `docker system prune -f`
5. Rotate or compress log files
6. Consider expanding disk space if cleanup insufficient

## Application-Specific Alerts

### AgentQueryBacklog
**Alert:** Agent query backlog building up
**Severity:** Warning
**Troubleshooting:**
1. Check agent service health and performance
2. Review LLM API rate limits and quotas
3. Monitor tool execution times
4. Consider scaling agent workers
5. Check for slow or failing tool integrations

### LLMTokenLimitApproaching
**Alert:** High LLM token usage
**Severity:** Warning
**Troubleshooting:**
1. Monitor token costs and budget
2. Review query patterns for optimization opportunities
3. Implement response caching where appropriate
4. Consider using smaller models for simple tasks
5. Set up cost alerts and limits

### ToolExecutionFailureRate
**Alert:** High tool execution failure rate
**Severity:** Warning
**Troubleshooting:**
1. Check tool integration logs
2. Verify external service dependencies
3. Review API credentials and permissions
4. Check network connectivity to external services
5. Implement retry logic and circuit breakers

### Neo4jConnectionPoolExhausted
**Alert:** Neo4j connection pool nearly exhausted
**Severity:** Critical
**Troubleshooting:**
1. Check for connection leaks in application code
2. Monitor long-running queries
3. Increase connection pool size if needed
4. Optimize database queries
5. Consider read replicas for load distribution

### SlowSemanticSearch
**Alert:** Slow semantic search queries
**Severity:** Warning
**Troubleshooting:**
1. Check vector index performance
2. Review query complexity and patterns
3. Consider index optimization or rebuilding
4. Monitor database resource usage
5. Implement query result caching

## Infrastructure Alerts

### RedisConnectionFailure
**Alert:** Redis cache is unavailable
**Severity:** Critical
**Troubleshooting:**
1. Check Redis service status: `docker ps | grep redis`
2. Review Redis logs: `docker logs brain-researcher-redis`
3. Check Redis configuration and memory usage
4. Restart Redis service: `docker-compose restart redis`
5. Verify network connectivity and firewall rules

### PrometheusTargetDown
**Alert:** Prometheus monitoring is down
**Severity:** Critical
**Troubleshooting:**
1. Check Prometheus service status immediately
2. Review Prometheus configuration for errors
3. Check storage space for Prometheus data
4. Restart Prometheus: `docker-compose restart prometheus`
5. Verify all monitored targets are accessible

## General Response Procedures

### Alert Response Workflow
1. **Acknowledge** the alert in AlertManager
2. **Assess** the severity and impact
3. **Investigate** using the specific runbook
4. **Mitigate** the immediate issue
5. **Monitor** for resolution
6. **Document** actions taken and lessons learned
7. **Follow up** with preventive measures

### Escalation Paths
- **Critical alerts**: Immediate escalation to on-call engineer
- **Warning alerts**: Handle within 30 minutes, escalate if unresolved in 2 hours
- **Infrastructure issues**: Escalate to platform team
- **Application issues**: Escalate to relevant development team

### Communication Channels
- **Slack**: Use appropriate team channels for real-time updates
- **Email**: For formal notifications and documentation
- **PagerDuty**: For critical alerts requiring immediate attention
- **Status Page**: Update external status page for user-facing issues

### Post-Incident Actions
1. Conduct post-mortem for critical incidents
2. Update runbooks based on new insights
3. Implement monitoring improvements
4. Review and adjust alert thresholds
5. Schedule preventive maintenance if needed