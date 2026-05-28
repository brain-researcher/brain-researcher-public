# Brain Researcher Testing Guide

## Quick Start Testing

### 1. Prerequisites
```bash
# Install dependencies
pip install -r requirements.txt
pip install pytest pytest-cov pytest-asyncio hypothesis

# Start Redis (required for caching and state management)
docker run -d -p 6379:6379 redis:latest

# Optional: Start other services
docker-compose up -d  # For full stack
```

### 2. Run All Tests
```bash
# Run all tests with coverage
pytest tests/ --cov=brain_researcher --cov-report=html

# View coverage report
open htmlcov/index.html
```

### 3. Test Specific Modules
```bash
# Core Agent tests
pytest tests/unit/test_cot_reasoning.py -v
pytest tests/unit/test_parallel_executor.py -v
pytest tests/unit/test_adaptive_scheduler.py -v

# RL and Learning tests
pytest tests/unit/test_rl/ -v
pytest tests/unit/test_bandits/ -v
pytest tests/unit/test_continuous_learning/ -v

# Integration tests
pytest tests/integration/ -v -m "not slow"
```

## Interactive Testing

### 1. Start the Development Server
```bash
# Start the Brain Researcher agent (includes LangGraph planner)
br serve agent --debug

# Start the standalone orchestrator service
br serve orchestrator --port 3001

# Optional: Start the Web UI (Next.js)
br serve web --port 3000
```

### 2. Test via CLI
```bash
# Simple GLM analysis
br run "Perform GLM analysis on dataset ds000114"

# Complex workflow with caching
br run "Compare activation patterns between young and old subjects in ds000030 using FSL FEAT"

# Test parallel execution
br run "Process all subjects in ds000114 with fMRIPrep and then run group analysis"

# Test multi-language support
br run "Explique-moi les résultats de l'analyse GLM" --lang fr
```

### 3. Test via REST API
```bash
# Submit a job through the orchestrator execution surface
curl -X POST http://localhost:3001/run \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Analyze resting state connectivity in ds000102",
    "parameters": {
      "parallel": true,
      "cache": true
    }
  }'

# Check orchestrator job status
curl http://localhost:3001/api/jobs/{job_id}

# Direct agent action surface
curl -X POST http://localhost:8000/act \
  -H "Content-Type: application/json" \
  -d '{"query": "Explain the latest run status"}'

# Get execution metrics
curl http://localhost:3001/api/adaptive/metrics

# Test A/B experiments
curl -X POST http://localhost:3001/api/experiments \
  -H "Content-Type: application/json" \
  -d '{
    "name": "tool_selection_test",
    "variants": ["baseline", "rl_optimized"],
    "metrics": ["execution_time", "success_rate"]
  }'
```

## Testing Specific Features

### 1. Test Chain-of-Thought Reasoning
```python
# tests/manual/test_cot.py
from brain_researcher.services.agent.cot_reasoning import ChainOfThoughtReasoner

reasoner = ChainOfThoughtReasoner()
result = reasoner.reason(
    "What brain regions show increased activation during working memory tasks?"
)
print(f"Reasoning steps: {result.steps}")
print(f"Confidence: {result.confidence}")
```

### 2. Test Parallel Execution
```python
# tests/manual/test_parallel.py
from brain_researcher.services.agent.parallel_executor import ParallelExecutionOrchestrator
from brain_researcher.services.agent.dag_language import DAGDefinition

dag = DAGDefinition.from_yaml("""
name: parallel_test
nodes:
  - id: preprocess_1
    tool: fmriprep
    parallel: true
  - id: preprocess_2
    tool: fmriprep
    parallel: true
  - id: preprocess_3
    tool: fmriprep
    parallel: true
  - id: group_analysis
    tool: fsl_glm
    depends_on: [preprocess_1, preprocess_2, preprocess_3]
""")

executor = ParallelExecutionOrchestrator()
result = await executor.execute_parallel(dag.to_execution_graph())
print(f"Speedup: {result.speedup}x")
```

### 3. Test RL Optimization
```python
# tests/manual/test_rl.py
from brain_researcher.services.agent.rl.iql_optimizer import IQLOptimizer
from brain_researcher.services.feedback.reward_tracker import RewardTracker

# Collect some training data
tracker = RewardTracker()
tracker.track_reward(
    state={"task": "glm", "dataset_size": 50},
    action="use_fsl",
    reward=0.8,
    next_state={"task": "glm", "completed": True}
)

# Train RL model
optimizer = IQLOptimizer(state_dim=10, action_dim=5)
optimizer.train(tracker.get_offline_dataset())

# Test optimized decisions
action = optimizer.select_action({"task": "glm", "dataset_size": 100})
print(f"RL recommended action: {action}")
```

### 4. Test Distributed Architecture
```python
# tests/manual/test_distributed.py
from brain_researcher.services.agent.distributed.coordinator import DistributedCoordinator

# Start coordinator
coordinator = DistributedCoordinator("node-1", redis_client)
await coordinator.start()

# Register worker nodes
await coordinator.register_node({
    "node_id": "worker-1",
    "hostname": "localhost",
    "capacity": {"cpu": 8, "memory_gb": 32}
})

# Submit distributed task
result = await coordinator.submit_task(task, strategy="least_loaded")
```

### 5. Test Workflow Debugging
```python
# tests/manual/test_debugger.py
from brain_researcher.services.agent.debugger.workflow_debugger import WorkflowDebugger

debugger = WorkflowDebugger(dag_executor)

# Set breakpoint
debugger.add_breakpoint("node_3", condition="output.error_rate > 0.1")

# Debug execution
await debugger.debug_execute(dag, step_mode=True)

# Inspect variables
value = debugger.inspect_variable("activation_map")
print(f"Current value: {value}")

# Step through
await debugger.step_over()
```

## Performance Testing

### 1. Load Testing
```bash
# Install locust for load testing
pip install locust

# Create locustfile.py
cat > locustfile.py << 'EOF'
from locust import HttpUser, task, between

class BrainResearcherUser(HttpUser):
    wait_time = between(1, 3)
    
    @task
    def submit_analysis(self):
        self.client.post("/run", json={
            "prompt": "Run GLM analysis on test dataset"
        })
    
    @task
    def check_status(self):
        self.client.get("/api/jobs/test-job-id")
EOF

# Run load test
locust -f locustfile.py --host=http://localhost:3001 --users 100 --spawn-rate 10
```

### 2. Benchmark Specific Features
```bash
# Benchmark parallel execution
python tests/benchmarks/bench_parallel.py

# Benchmark caching
python tests/benchmarks/bench_cache.py

# Benchmark RL optimization
python tests/benchmarks/bench_rl.py
```

## Integration Testing

### 1. End-to-End Workflow Test
```bash
# Run complete neuroimaging pipeline
python tests/e2e/test_complete_pipeline.py

# This tests:
# - Query parsing and planning
# - Tool execution (fMRIPrep, FSL, etc.)
# - Parallel processing
# - Result aggregation
# - Report generation
```

### 2. Multi-Module Integration
```bash
# Test Agent + BR-KG integration
pytest tests/integration/test_agent_neurokg.py

# Test Agent + UI integration
pytest tests/integration/test_agent_ui.py

# Test complete system
pytest tests/integration/test_full_system.py
```

## Testing with Real Data

### 1. Download Test Dataset
```bash
# Download a small OpenNeuro dataset
br data download --dataset ds000114 --output ./test_data/

# Or use sample data
br data use-sample --type fmri
```

### 2. Run Real Analysis
```bash
# Preprocessing
br run "Preprocess ds000114 with fMRIPrep" --real-data ./test_data/ds000114

# GLM Analysis
br run "Perform first-level GLM on preprocessed data" --input ./test_data/preprocessed/

# Group Analysis
br run "Run group-level analysis comparing conditions" --input ./test_data/glm_results/
```

## Monitoring and Debugging

### 1. View Logs
```bash
# Agent logs
tail -f ~/.brain_researcher/logs/agent.log

# Execution logs
tail -f ~/.brain_researcher/logs/execution.log

# Error logs
tail -f ~/.brain_researcher/logs/error.log
```

### 2. Monitor Performance
```bash
# Real-time metrics
br monitor metrics --live

# System health
br monitor health

# Resource usage
br monitor resources
```

### 3. Debug Issues
```bash
# Enable debug mode
export BR_DEBUG=true

# Run with verbose output
br run "test query" -vvv

# Trace execution
br debug trace --execution-id {id}

# Inspect state
br debug state --job-id {id}
```

## Testing Checklist

### Core Features
- [ ] Query parsing and understanding
- [ ] Chain-of-thought reasoning
- [ ] Workflow planning
- [ ] Tool execution
- [ ] Parallel processing
- [ ] Caching and memoization
- [ ] Error handling and recovery

### Advanced Features
- [ ] Distributed execution
- [ ] Multi-backend support (K8s, SLURM, AWS)
- [ ] Complex DAG workflows
- [ ] Workflow debugging
- [ ] Cost optimization
- [ ] Multi-language support

### Learning Features
- [ ] A/B testing
- [ ] RL optimization
- [ ] Contextual bandits
- [ ] Continuous learning
- [ ] Drift detection

### Integration
- [ ] REST API endpoints
- [ ] WebSocket real-time updates
- [ ] Database persistence
- [ ] File handling
- [ ] Authentication (if enabled)

## Troubleshooting

### Common Issues

1. **Redis Connection Error**
```bash
# Check Redis is running
redis-cli ping

# Start Redis if needed
docker run -d -p 6379:6379 redis:latest
```

2. **Import Errors**
```bash
# Ensure you're in the project root
cd <repo>

# Install in development mode
pip install -e .
```

3. **Test Failures**
```bash
# Run specific failing test with verbose output
pytest tests/unit/test_file.py::test_name -vvs

# Check test fixtures
ls tests/fixtures/
```

4. **Performance Issues**
```bash
# Profile the code
python -m cProfile -o profile.out br run "test query"
python -m pstats profile.out
```

## Continuous Integration

### GitHub Actions Workflow
```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    services:
      redis:
        image: redis
        ports:
          - 6379:6379
    
    steps:
    - uses: actions/checkout@v2
    
    - name: Set up Python
      uses: actions/setup-python@v2
      with:
        python-version: '3.9'
    
    - name: Install dependencies
      run: |
        pip install -r requirements.txt
        pip install -e .
    
    - name: Run tests
      run: |
        pytest tests/ --cov=brain_researcher --cov-report=xml
    
    - name: Upload coverage
      uses: codecov/codecov-action@v2
```

## Next Steps

1. **Run the test suite** to verify everything works
2. **Try the interactive examples** to see features in action
3. **Test with real neuroimaging data** if available
4. **Set up CI/CD** for automated testing
5. **Deploy to staging** for user testing

For more information, see:
- API Documentation: `/docs/api/`
- User Guide: `/docs/user_guide.md`
- Developer Guide: `/docs/developer_guide.md`
