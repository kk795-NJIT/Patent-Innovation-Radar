# Patent + Innovation Radar: Complete Build & Deployment Guide

## Quick Start (5 minutes)

```bash
# Clone and setup
git clone <repo>
cd patent-innovation-radar

# Copy environment
cp .env.sample .env

# Start all services (Docker Compose)
docker-compose up -d

# Wait for services to be healthy (30-60 seconds)
docker-compose ps

# Initialize database schema
docker exec patent-innovation-radar-postgres-1 psql -U postgres -d patent_radar -f /docker-entrypoint-initdb.d/patent_schema.sql

# Test API
curl http://localhost:8000/health

# Open UI
open http://localhost:8501  # Streamlit UI
open http://localhost:3000  # Grafana dashboards
open http://localhost:8000/docs  # API docs (Swagger)
```

---

## 4-Week Execution Plan

### Week 1: Data Pipeline & Basic Search (MVP Foundation)

**Goal**: Prove data ingestion, storage, and basic search work end-to-end.

#### Day 1-2: Setup Infrastructure
- [x] Docker Compose: Postgres + Redis + MinIO + Qdrant + monitoring
- [x] Database schema (patent_schema.sql)
- [x] Seed sample data (1000 patents for local dev)
- **Task**: `docker-compose up -d` should deploy all services
- **Validation**: `curl http://localhost:5432` returns health check

#### Day 3-4: Ingestion Pipeline
- [x] PatentsView API client (`services/api/ingest.py`)
  - Rate limiting, retries, incremental fetching
  - Great Expectations validation (schema, nullability, duplicates)
- [x] Automated daily ingestion script
- **Task**: Run `python ingest.py --since-days 7`
  - Should fetch ~1000 patents from PatentsView API
  - Log: "Inserted 950 patents, updated 40, errors 10"
  - Validate in Postgres: `SELECT COUNT(*) FROM patents`

#### Day 5-7: FastAPI Backend & UI
- [x] FastAPI endpoints: `/patents/search`, `/topics`, `/trends`, `/watchlists`
- [x] Streamlit UI: basic search interface
- **Task**: 
  - POST http://localhost:8000/patents/search?q=quantum
  - View results in Streamlit
- **Success Criteria**:
  - Full-text search returns results in <500ms
  - UI loads in <2s

#### Deliverables (Week 1):
- `services/api/main.py` - 4 endpoints working
- `services/ui/app.py` - Search & browse UI
- Sample data in Postgres (1K patents)
- Docker Compose stack running
- Runbook: `docs/WEEK1_RUNBOOK.md`

#### Testing:
```bash
# Unit tests
pytest tests/unit/test_ingest.py
pytest tests/unit/test_api.py

# Integration test
pytest tests/integration/test_search.py
```

---

### Week 2: Embeddings & Semantic Search (V1 Analytics)

**Goal**: Add vector search and topic modeling foundation.

#### Day 1-2: Embeddings Service
- [x] Sentence-Transformers integration (`ml/models/ml_services.py`)
- [x] Batch embedding of patents (abstract + title)
- [x] Store vectors in Qdrant
- **Task**: 
  - Embed all 50K patents: `python ml/models/embed_batch.py --batch-size 100`
  - Monitor: `curl http://localhost:6333/collections/patents` (check point count)
  - Estimate time: ~5 mins on CPU, <1 min on GPU

#### Day 3-4: Semantic Search API
- [x] FastAPI endpoint: `POST /patents/semantic-search`
- [x] Query embedding + Qdrant similarity search
- **Task**: 
  - POST http://localhost:8000/patents/semantic-search
    ```json
    {"query": "quantum error correction", "limit": 10}
    ```
  - Should return top 10 similar patents in <200ms

#### Day 5-7: Topic Modeling
- [x] BERTopic model fitting (`ml/models/topic_model.py`)
- [x] Fit on 50K patent abstracts → 50 topics
- [x] Topic API: `GET /topics`, `GET /topics/{topic_id}`
- **Task**:
  - Run `python ml/models/train_topics.py`
  - Log: "Fitted 50 topics from 50K documents"
  - API: GET http://localhost:8000/topics
  - Result: 50 topics with keywords

#### Deliverables (Week 2):
- Embeddings for 50K patents in Qdrant
- BERTopic model v1 in MLflow
- Semantic search API + UI
- Topic pages with top patents
- `ml/models/ml_services.py` - Full ML layer

#### Testing:
```bash
pytest tests/unit/test_embeddings.py
pytest tests/unit/test_topic_model.py
pytest tests/integration/test_semantic_search.py

# Performance test
pytest tests/performance/test_embedding_latency.py --benchmark
```

---

### Week 3: Novelty Scoring & Alerts (Competitive Intelligence)

**Goal**: Add novelty detection and watchlist alerting.

#### Day 1-2: Novelty Scoring Model
- [x] Feature engineering: embedding distance, recency, CPC diversity
- [x] Train LightGBM novelty ranker (offline)
- [x] Score all patents
- **Task**:
  - Run `python ml/models/train_novelty.py`
  - Log: "Trained model. F1=0.82, saved to MLflow"
  - Check DB: `SELECT COUNT(*) FROM patents WHERE novelty_score IS NOT NULL`

#### Day 3-4: Trend Acceleration Detection
- [x] Compute z-scores of weekly filing counts per topic/CPC
- [x] Flag accelerating trends (z > 2.0)
- [x] API: `GET /trends?period_days=90&min_z_score=2.0`
- **Task**:
  - GET http://localhost:8000/trends
  - Result: list of accelerating topics with z-scores

#### Day 5-7: Watchlists & Alerts
- [x] CRUD endpoints: POST/GET/PUT /watchlists
- [x] Alert generation: material changes trigger immediately
- [x] Email task (Celery): send daily/weekly digests
- **Task**:
  - POST /watchlists (create watchlist for Nvidia)
  - GET /watchlists/{watchlist_id}/alerts
  - Manually trigger: `celery -A tasks call send_watchlist_digest --args='[watchlist_id]'`

#### Deliverables (Week 3):
- Novelty scores for 50K patents
- LightGBM model in MLflow
- Watchlist management API
- Alert system with Celery background tasks
- Email integration (sample SMTP)

#### Testing:
```bash
pytest tests/unit/test_novelty_scorer.py
pytest tests/unit/test_watchlist.py
pytest tests/integration/test_alerts.py

# Load test
locust -f tests/load/locustfile.py
```

---

### Week 4: MLOps, Monitoring & Agent (Production Ready)

**Goal**: Complete MLOps pipeline, observability, and agentic AI report generation.

#### Day 1-2: Kubeflow Pipelines
- [x] Define pipeline DAG: ingest → validate → embed → topic → novelty → register → publish
- [x] Component definitions for each step
- [x] Cron job: daily ingestion + weekly model retraining
- **Task**:
  - Compile: `kfp.compiler.Compiler().compile(patent_pipeline, 'patent_pipeline.yaml')`
  - Deploy to Kubeflow: `kubectl apply -f patent_pipeline.yaml`
  - Monitor: Check Kubeflow UI for successful runs

#### Day 3-4: Observability (Prometheus + Grafana + Loki + Tempo)
- [x] Prometheus metrics: patent counts, ingestion lag, API latency, model scores
- [x] Grafana dashboards: Pipeline Health, Model Health, Trend Radar, Alert Quality
- [x] Loki: aggregate logs from all services
- [x] Tempo: distributed traces (OpenTelemetry)
- **Task**:
  - View Grafana: http://localhost:3000 (admin/admin)
  - Check "Pipeline Health" dashboard
  - Verify metrics are flowing

#### Day 5-7: LangGraph Agent & Weekly Reports
- [x] Report agent (`services/agent/report_agent.py`): fetch evidence, analyze, generate
- [x] Weekly digest generation with Claude LLM
- [x] Cron job: Mondays 8 AM send digest to all users
- [x] Incident detection: auto-generate incident summaries on drift/freshness drops
- **Task**:
  - Run manually: `python services/agent/report_agent.py --user-id analyst_001`
  - Output: Markdown report with citations + evidence links
  - Email: Check SMTP output

#### Deliverables (Week 4):
- Kubeflow pipeline running daily
- Grafana dashboards + Prometheus metrics
- LangGraph report agent
- Weekly digest automation
- Helm charts for k8s deployment
- Full documentation + runbooks

#### Testing:
```bash
# E2E pipeline test
pytest tests/e2e/test_full_pipeline.py

# Agent test
pytest tests/unit/test_report_agent.py

# Observability test
pytest tests/integration/test_prometheus_metrics.py
```

---

## Local Development Checklist

### Prerequisites
```bash
# macOS
brew install docker docker-compose python@3.10 postgresql

# Linux (Ubuntu)
sudo apt update
sudo apt install docker.io docker-compose python3.10 postgresql

# Windows (WSL2 recommended)
# Use Docker Desktop for Windows
```

### First Run
```bash
# 1. Clone and cd
git clone <repo> && cd patent-innovation-radar

# 2. Create .env
cp .env.sample .env

# 3. Create Python virtual env
python3.10 -m venv venv
source venv/bin/activate  # macOS/Linux
# or: venv\Scripts\activate  # Windows

# 4. Install dependencies
pip install -r requirements-dev.txt

# 5. Start Docker Compose
docker-compose up -d

# 6. Initialize database
docker-compose exec postgres psql -U postgres -d patent_radar -f /docker-entrypoint-initdb.d/patent_schema.sql

# 7. Seed sample data (optional)
python scripts/seed_sample_data.py --count 1000

# 8. Test API
curl http://localhost:8000/health

# 9. View UIs
# Streamlit: http://localhost:8501
# Swagger: http://localhost:8000/docs
# Grafana: http://localhost:3000 (admin/admin)
# Neo4j: http://localhost:7474 (neo4j/password123)
```

### Daily Development
```bash
# Watch API logs
docker-compose logs -f api

# Run tests
pytest tests/ -v

# Ingest fresh patents
docker-compose exec api python ingest.py --since-days 1

# View Prometheus metrics
curl http://localhost:9090/api/v1/query?query=patent_count_total

# Trigger manual pipeline job
docker-compose exec api python -m services.agent.report_agent
```

### Cleanup
```bash
# Stop services
docker-compose down

# Reset data
docker-compose down -v  # Remove volumes

# Full rebuild
docker-compose up -d --force-recreate
```

---

## Production Deployment (Kubernetes)

### Prerequisites
```bash
# Install tools
brew install kubectl helm kustomize argocd

# Connect to cluster
kubectl config use-context your-cluster

# Create namespace
kubectl create namespace patent-radar
```

### Deploy with Helm
```bash
# Install chart
helm install patent-radar ./infra/helm/patent-radar \
  --namespace patent-radar \
  -f ./infra/helm/values-prod.yaml

# Verify
kubectl get pods -n patent-radar

# Port forward to test
kubectl port-forward -n patent-radar svc/patent-radar-api 8000:8000
curl http://localhost:8000/health
```

### Deploy with Kustomize
```bash
# Build manifests
kustomize build ./infra/kustomize/overlays/prod > manifest.yaml

# Apply
kubectl apply -f manifest.yaml

# Monitor rollout
kubectl rollout status deployment/api -n patent-radar
```

### GitOps with ArgoCD
```bash
# Create ArgoCD Application
kubectl apply -f ./infra/argocd/application.yaml

# Monitor
argocd app get patent-radar
```

---

## Important Files Summary

| Path | Purpose |
|------|---------|
| `PRODUCT_SPEC.md` | Product requirements, user personas, journeys |
| `ARCHITECTURE.md` | System design, data model, API surface |
| `data/schemas/patent_schema.sql` | Complete PostgreSQL schema |
| `services/api/main.py` | FastAPI backend |
| `services/api/ingest.py` | PatentsView ingestion |
| `ml/models/ml_services.py` | Embeddings, topics, novelty |
| `services/agent/report_agent.py` | LangGraph report generator |
| `pipelines/kubeflow/patent_pipeline.py` | ML orchestration |
| `docker-compose.yml` | Local dev stack |
| `infra/helm/` | Kubernetes charts |
| `infra/monitoring/` | Prometheus, Grafana, Loki configs |

---

## Troubleshooting

### Services Not Starting
```bash
# Check logs
docker-compose logs postgres
docker-compose logs api

# Common issues:
# - Port already in use: docker-compose ps, netstat -an
# - Postgres not initialized: docker-compose down -v && docker-compose up -d
```

### High API Latency
```bash
# Check database indexes
docker-compose exec postgres psql -U postgres -d patent_radar -c "SELECT * FROM pg_stat_user_indexes WHERE idx_scan = 0;"

# Rebuild indexes
docker-compose exec postgres psql -U postgres -d patent_radar -c "REINDEX TABLE patents;"
```

### Embeddings Not Computing
```bash
# Check GPU availability
docker-compose exec api nvidia-smi

# Fall back to CPU
docker-compose exec api CUDA_VISIBLE_DEVICES="" python ml/models/embed_batch.py
```

### Celery Tasks Failing
```bash
# Check Celery worker
docker-compose logs -f celery

# Re-queue failed tasks
docker-compose exec celery celery -A tasks purge  # WARNING: clears ALL tasks
```

---

## Success Criteria

### MVP (Week 1)
- ✅ Daily ingestion of 1K+ patents from PatentsView
- ✅ Keyword search API (<500ms latency)
- ✅ Basic UI with search + browse

### V1 (Week 2-3)
- ✅ 50K patents with embeddings
- ✅ 50 topics (BERTopic)
- ✅ Semantic search API
- ✅ Novelty scores for all patents
- ✅ Watchlists + alerts
- ✅ Weekly email digest

### V1+ (Week 4)
- ✅ Kubeflow pipeline running daily
- ✅ MLflow model registry with versioning
- ✅ Prometheus + Grafana + Loki + Tempo
- ✅ LangGraph agent generating reports
- ✅ Helm/Kustomize k8s deployment
- ✅ 99.0% uptime SLA

---

## Next Steps (Post-MVP)

1. **Advanced Analytics**
   - SHAP explainability for novelty scores
   - Seasonal trend adjustment (LOESS)
   - Graph analytics (PageRank, community detection) on Neo4j

2. **KServe Integration**
   - Deploy embedding model as inference service
   - Deploy novelty model as inference service
   - Real-time scoring at scale

3. **Advanced Auth**
   - Keycloak integration
   - RBAC (admin/analyst/viewer)
   - API rate limiting per user

4. **Data Quality**
   - Evidently AI drift monitoring
   - Custom Great Expectations suites
   - Alert on data quality degradation

5. **UI Enhancements**
   - React frontend (from Streamlit MVP)
   - Real-time trend visualization
   - Graph exploration interface

---

## Support & Contributions

- **Issues**: GitHub Issues
- **PRs**: Follow CONTRIBUTING.md
- **Docs**: See `docs/` folder
- **ADRs**: Architecture Decision Records in `docs/adr/`

