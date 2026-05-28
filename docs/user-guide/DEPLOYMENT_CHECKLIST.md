# Brain Researcher Agent - Deployment Checklist

## 📋 Pre-Deployment Requirements

### 1. Environment Configuration ✅

#### Required API Keys
- [ ] **OPENAI_API_KEY** - For GPT-4 agent operations
- [ ] **ANTHROPIC_API_KEY** - Optional, for Claude models
- [ ] **DEEPSEEK_API_KEY** - Optional, for DeepSeek models
- [ ] **BR_PLAN_TRACKER_PROVIDER** - Optional external tracker backend (`auto|none|linear`)
- [ ] **BR_PLAN_TRACKER_LINEAR_API_KEY** - Optional, when `linear` tracker backend is enabled
- [ ] **BR_PLAN_TRACKER_LINEAR_TEAM_ID** - Optional, when `linear` tracker backend is enabled

#### Database & Cache
- [ ] **Neo4j** (Required)
  - Port: 7687 (bolt)
  - Used for: Knowledge graph storage (Neo4j-only; SQLite mock removed)
  - Credentials: `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`

- [ ] **Redis** (Recommended for production; FakeRedis acceptable in dev)
  - Port: 6379 (default)
  - Used for: Agent state persistence, execution tracking

### 2. Service Dependencies 🔧

#### Core Services (current topology)
```yaml
Services to Deploy:
1. Agent Service (Port 8000)
   - Flask-based API with LangGraph planner

2. BR-KG Service (Port 5000)
   - Requires Neo4j backend
   - Graph + dataset APIs

3. Orchestrator Service (Port 3001)
   - Analysis jobs, share links, credits, notifications, job inspection

4. Web UI (Next.js) (Port 3000 via CLI; 3000 in Docker)
   - Fans out to Agent + BR-KG + Orchestrator via Next.js API routes

5. Redis Cache (Port 6379)
   - Optional in dev (FakeRedis); recommended in prod
```

#### Python Dependencies
```bash
# Core requirements
python >= 3.10
langgraph >= 0.0.20
langchain >= 0.1.0
fastapi >= 0.100.0
redis >= 5.0.0
fakeredis >= 2.20.0 (for testing)
```

### 3. Infrastructure Requirements 🖥️

#### Minimum Hardware
- **CPU**: 4 cores
- **RAM**: 8GB (16GB recommended)
- **Storage**: 50GB available
- **Network**: Stable internet for API calls

#### Docker Requirements
- Docker Engine >= 20.10
- Docker Compose >= 2.0
- Available ports: 5000, 6379, 8000, 3000

### 4. Data & Models 📊

#### Required Data
- [ ] BIDS datasets in `./data/bids/`
- [ ] BR-KG database initialized
- [ ] Agent parameter database available at `src/data/parameter_db.json` (auto-created if missing)

#### Optional Data
- [ ] NICLIP models in `./models/niclip/`
- [ ] Cached neuroimaging data
- [ ] Pre-computed embeddings

---

## 🚀 Deployment Steps

### Step 1: Environment Setup
```bash
# 1. Clone repository
git clone <repository-url>
cd brain_researcher

# 2. Copy environment file
cp .env.example .env

# 3. Edit .env with your credentials
nano .env  # Add API keys, configure ports
```

### Step 2: Docker Deployment
```bash
# 1. Build all services
docker-compose build

# 2. Start services in order
docker-compose up -d redis     # Start Redis first
docker-compose up -d neurokg   # Start BR-KG (requires Neo4j env)
docker-compose up -d agent     # Start Agent service
docker-compose up -d orchestrator  # Start Orchestrator service
docker-compose up -d web-ui    # Start Next.js Web UI

# 3. Verify health
docker-compose ps
curl http://localhost:8000/health
curl http://localhost:5000/health
curl http://localhost:3001/health
curl http://localhost:3000/api/health
```

### Step 3: Native Deployment (Alternative)
```bash
# 1. Install dependencies
pip install -e ".[all]"

# 2. Start Redis
redis-server &

# 3. Start services individually
br serve kg &      # BR-KG on port 5000
br serve agent &   # Agent on port 8000
br serve orchestrator &  # Orchestrator on port 3001
br serve web &     # Next.js Web UI on port 3000
```

### Step 4: Database Initialization
```bash
# Initialize BR-KG database
br db init

# Load sample data (optional)
br data load-pubmed --input data/sample_pubmed.json
br ingest openneuro ds000001

# Verify database
br db status
```

### Step 5: Service Verification
```bash
# Test agent endpoint
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "Test query"}'

# Test BR-KG
curl "http://localhost:5000/api/kg/concepts?limit=1"

# Check orchestrator execution tracking
curl http://localhost:3001/api/jobs

# Access Web UI
open http://localhost:3000
```

---

## 🔒 Security Checklist

### API Security
- [ ] API keys stored in environment variables
- [ ] Never commit `.env` file
- [ ] Use secrets management in production
- [ ] Enable CORS only for trusted origins

### Network Security
- [ ] Services bound to localhost in development
- [ ] Use reverse proxy (nginx) in production
- [ ] Enable HTTPS for external access
- [ ] Firewall rules configured

### Data Security
- [ ] Sensitive data encrypted at rest
- [ ] Database credentials secured
- [ ] Regular backups configured
- [ ] Access logs enabled

---

## 📊 Monitoring & Health Checks

### Health Endpoints
```bash
# Agent health
GET http://localhost:8000/health

# BR-KG health
GET http://localhost:5000/health

# Redis health
redis-cli ping

# Orchestrator job status
GET http://localhost:3001/api/jobs/{job_id}
```

### Logging Configuration
```yaml
Log Locations:
- Agent: ./logs/agent.log
- BR-KG: ./logs/neurokg.log
- UI: ./logs/ui.log
- System: docker-compose logs
```

### Performance Monitoring
- [ ] CPU usage < 80%
- [ ] Memory usage < 80%
- [ ] Response time < 2s
- [ ] Redis memory < 1GB
- [ ] Database connections < 20

---

## 🛠️ Troubleshooting

### Common Issues

#### Port Conflicts
```bash
# Check port usage
lsof -i :8000
lsof -i :5000
lsof -i :6379

# Kill conflicting process
kill -9 <PID>

# Or use auto port selection
export AGENT_PORT=auto
export KG_PORT=auto
```

#### Redis Connection Issues
```bash
# Test Redis connection
redis-cli ping

# Check Redis status
systemctl status redis

# Use FakeRedis for testing
export REDIS_URL=""  # Will fallback to FakeRedis
```

#### API Key Issues
```bash
# Verify API keys
python -c "import os; print(os.getenv('OPENAI_API_KEY')[:10] + '...')"

# Test API connection
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY"
```

#### Memory Issues
```bash
# Check memory usage
docker stats

# Increase Docker memory
# Docker Desktop > Preferences > Resources > Memory

# Or limit service memory in docker-compose.yml
services:
  agent:
    mem_limit: 2g
```

---

## ✅ Post-Deployment Verification

### Functional Tests
- [ ] Agent responds to queries
- [ ] Parameter validation working
- [ ] Execution tracking active
- [ ] Error handling functional
- [ ] BR-KG queries return data
- [ ] UI dashboard accessible
- [ ] WebSocket connections stable

### Integration Tests
- [ ] Agent → BR-KG communication
- [ ] Redis state persistence
- [ ] Execution status updates
- [ ] Error recovery mechanisms
- [ ] Multi-step workflows complete

### Performance Tests
- [ ] Response time acceptable
- [ ] Concurrent request handling
- [ ] Memory usage stable
- [ ] No memory leaks detected

---

## 📝 Maintenance

### Regular Tasks
- **Daily**: Check logs for errors
- **Weekly**: Review resource usage
- **Monthly**: Update dependencies
- **Quarterly**: Security audit

### Backup Strategy
```bash
# Backup Redis
redis-cli BGSAVE

# Backup Neo4j (requires APOC or cypher-shell)
NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=... \\
  scripts/tools/dev/neo4j_export.sh backups/neo4j_dump_$(date +%Y%m%d).cypher

# Backup configurations
tar -czf config_backup.tar.gz .env docker-compose.yml
```

### Update Procedure
```bash
# 1. Backup current state
./scripts/backup.sh

# 2. Pull updates
git pull origin main

# 3. Rebuild services
docker-compose build

# 4. Restart services
docker-compose down
docker-compose up -d

# 5. Verify functionality
./scripts/health_check.sh
```

---

## 🚨 Emergency Procedures

### Service Recovery
```bash
# Full restart
docker-compose down
docker-compose up -d

# Individual service restart
docker-compose restart agent
docker-compose restart neurokg
docker-compose restart web-ui

# Clear Redis cache
redis-cli FLUSHDB

# Reset to clean state
docker-compose down -v
docker-compose up -d
```

### Rollback Procedure
```bash
# Tag current version
git tag -a v1.0-backup -m "Pre-update backup"

# Rollback if needed
git checkout v1.0-backup
docker-compose build
docker-compose up -d
```

---

## 📞 Support Contacts

- **Technical Issues**: Create issue on GitHub
- **Security Concerns**: security@example.com
- **Documentation**: docs/README.md
- **Community**: Discord/Slack channel

---

*Last Updated: 2025-08-18*
*Version: 1.0.0*
