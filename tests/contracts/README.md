# Brain Researcher Contract Testing

This directory contains contract tests using Pact to validate service integration across the Brain Researcher platform.

Legacy standalone `api_gateway` contract coverage is retained here as compatibility-only scaffolding. It is disabled by default and should be enabled only when intentionally validating the retired gateway surface.

## Overview

Contract testing validates the integration between services by defining contracts between consumers and providers. This ensures that:

- Frontend-backend integration remains stable
- Service communication doesn't break with changes
- API contracts are honored across service boundaries
- Deployment safety is verified before releases

## Architecture

The Brain Researcher platform has the following service relationships:

```
Web UI ──────────────┐
                     ├──► Orchestrator ──┬──► Agent Service ──┐
API Gateway (legacy) ──┘                │                  ├──► BR-KG Service
                                         └──────────────────┘
```

## Contract Relationships

### Consumer → Provider Contracts

1. **Web UI → Orchestrator**: Frontend interface contracts
2. **Orchestrator → Agent Service**: LLM execution contracts
3. **Orchestrator → BR-KG Service**: Knowledge graph contracts
4. **Agent → BR-KG Service**: Analysis context contracts
5. **API Gateway → All Services**: legacy standalone compatibility contracts

## Directory Structure

```
tests/contracts/
├── consumers/           # Consumer contract tests
│   ├── test_webui_orchestrator_contract.py
│   ├── test_orchestrator_agent_contract.py
│   ├── test_orchestrator_br_kg_contract.py
│   ├── test_agent_br_kg_contract.py
│   └── test_api_gateway_contracts.py
├── providers/           # Provider verification tests
│   ├── test_orchestrator_provider.py
│   ├── test_agent_provider.py
│   └── test_br_kg_provider.py
├── pact_helpers/        # Shared utilities
│   ├── pact_client.py
│   ├── mock_data.py
│   ├── state_setup.py
│   └── verification_utils.py
├── pact_broker/         # Pact Broker setup
│   ├── docker-compose.yml
│   └── setup.sh
├── pacts/              # Generated pact files (auto-created)
├── pact_config.py      # Configuration
├── compatibility_checker.py  # Breaking change detection
└── requirements.txt    # Dependencies
```

## Quick Start

### 1. Install Dependencies

```bash
pip install -r tests/contracts/requirements.txt
```

### 2. Start Pact Broker (Optional but recommended)

```bash
cd tests/contracts/pact_broker
./setup.sh
```

This starts a Pact Broker at http://localhost:9292 for managing contracts.

### 3. Run Contract Tests

Use the provided script:

```bash
./run_contract_tests.sh
```

Or run manually:

```bash
# Run consumer tests (generates pact files)
pytest tests/contracts/consumers/ -v

# Start test services
docker-compose -f docker-compose.test.yml up -d

# Run provider verification tests
pytest tests/contracts/providers/ -v

# Check compatibility
python tests/contracts/compatibility_checker.py --verbose
```

Legacy gateway contract coverage is opt-in:

```bash
BR_ENABLE_LEGACY_GATEWAY_TESTS=1 pytest tests/contracts/consumers/test_api_gateway_contracts.py -v
```

## Consumer Tests

Consumer tests run from the consumer's perspective and generate pact files that define expected interactions.

### Example Consumer Test

```python
@pytest.mark.asyncio
async def test_create_job_contract(self, pact_client):
    async with pact_client as pact:
        request_data = MockDataGenerator.run_request()

        (pact
         .given("orchestrator can accept jobs")
         .upon_receiving("a request to create a new job")
         .with_request(
             method="POST",
             path="/run",
             body=request_data
         )
         .will_respond_with(
             status=200,
             body=PactMatchers.job_response()
         ))

        response = await pact.execute_request("POST", "/run", json_data=request_data)
        assert response.status_code == 200
```

## Provider Tests

Provider tests verify that the actual service implementation can fulfill the contracts defined by consumers.

### Provider States

Provider tests use states to set up the required conditions:

- `"orchestrator can accept jobs"` - Sets up job creation capability
- `"a job exists"` - Creates a test job for retrieval
- `"datasets are available"` - Populates test datasets
- `"knowledge graph has data"` - Seeds knowledge graph

## Matchers and Mock Data

### Pact Matchers

The framework provides matchers for flexible contract validation:

```python
# Pattern matching
job_id = Term(r"job_[a-zA-Z0-9_]+", "job_abc123")

# Type matching
duration = Like(90)  # Matches any integer

# Array matching
artifacts = EachLike({
    "id": Term(r"artifact_[a-zA-Z0-9_]+", "artifact_stat_map"),
    "type": "brain_map"
})
```

### Mock Data Generator

Consistent test data generation:

```python
job_response = MockDataGenerator.job_response()
dataset_list = MockDataGenerator.dataset_list(count=5)
error_response = MockDataGenerator.error_response("NOT_FOUND")
```

## CI/CD Integration

### GitHub Actions Workflow

The contract tests run in GitHub Actions with the following stages:

1. **Consumer Tests**: Run consumer tests and generate pact files
2. **Provider Tests**: Start test services and verify contracts
3. **Compatibility Check**: Detect breaking changes
4. **Can I Deploy**: Verify deployment readiness

### Pipeline Configuration

```yaml
# .github/workflows/contract_tests.yml
on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]
```

## Pact Broker Integration

### Publishing Contracts

Consumer tests automatically publish contracts to the Pact Broker:

```bash
pact-broker publish \
  --pact-dir tests/contracts/pacts \
  --consumer-app-version $VERSION \
  --broker-base-url http://localhost:9292
```

### Verification Results

Provider tests publish verification results:

```bash
pact-broker publish-verification \
  --provider-app-version $VERSION \
  --broker-base-url http://localhost:9292
```

### Can I Deploy?

Check if it's safe to deploy:

```bash
pact-broker can-i-deploy \
  --pacticipant orchestrator \
  --version $VERSION \
  --to-environment production
```

## Breaking Change Detection

The compatibility checker analyzes contracts for breaking changes:

```bash
python tests/contracts/compatibility_checker.py \
  --pact-dir tests/contracts/pacts \
  --output compatibility-report.json \
  --fail-on-breaking
```

### Breaking Change Types

- **Removed endpoints**: Endpoints that consumers expect but provider no longer supports
- **Changed response structure**: Response fields that are modified or removed
- **Modified status codes**: HTTP status code changes
- **Request validation changes**: Stricter request validation

### Warnings

- **Strict matching**: Using exact values instead of flexible matchers
- **Missing descriptions**: Interactions without clear descriptions
- **Large response bodies**: Responses that may impact performance

## Configuration

### Service URLs

Configure service endpoints in `pact_config.py`:

```python
services = {
    "orchestrator": ServiceConfig(
        name="orchestrator",
        base_url="http://localhost:3001"
    ),
    "agent": ServiceConfig(
        name="agent-service",
        base_url="http://localhost:8000"
    )
}
```

### Pact Broker

Configure broker connection:

```python
broker = PactBrokerConfig(
    broker_base_url="http://localhost:9292",
    broker_username="pact_workshop",
    broker_password="pact_workshop"
)
```

## Troubleshooting

### Common Issues

1. **Pact files not generated**: Check consumer test execution and pact directory permissions
2. **Provider verification fails**: Ensure test services are running and provider states are set up
3. **Contract compatibility issues**: Review breaking changes in compatibility report
4. **Service startup timeouts**: Increase health check timeouts in docker-compose.test.yml

### Debugging

Enable verbose logging:

```bash
pytest tests/contracts/ -v -s --log-cli-level=DEBUG
```

View service logs:

```bash
docker-compose -f docker-compose.test.yml logs orchestrator-test
```

### Mock vs Real Services

Consumer tests use Pact mock servers, while provider tests use real service instances. This ensures contracts are validated against actual implementations.

## Best Practices

1. **Use flexible matchers** instead of exact values where appropriate
2. **Set up meaningful provider states** that represent real scenarios
3. **Test both success and error cases** in contracts
4. **Keep contracts focused** on essential API behavior
5. **Version contracts** and check compatibility before deployment
6. **Monitor contract drift** with regular compatibility checks
7. **Document provider states** and their setup requirements

## Extending Contract Tests

### Adding New Service

1. Add service config to `pact_config.py`
2. Create consumer contract tests
3. Create provider verification tests
4. Set up provider states
5. Update CI/CD pipeline
6. Document new contracts

### Adding New Interaction

1. Identify consumer-provider relationship
2. Define expected request/response structure
3. Create appropriate provider state
4. Add mock data generation
5. Test both consumer and provider sides

## Monitoring and Maintenance

### Regular Tasks

- Review contract compatibility reports
- Update provider states as service logic changes
- Refresh mock data to match production scenarios
- Monitor Pact Broker for contract evolution
- Validate "can-i-deploy" results before releases

### Contract Evolution

Contracts should evolve safely:
- **Additive changes**: New optional fields (non-breaking)
- **Removal changes**: Deprecated fields with migration period
- **Modification changes**: Coordinated with consumer updates

This contract testing framework ensures reliable service integration across the Brain Researcher platform while maintaining development velocity.
