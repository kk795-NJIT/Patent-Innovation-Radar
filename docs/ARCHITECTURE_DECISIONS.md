# Patent + Innovation Radar: Architecture Decision Records (ADRs)

## ADR-001: PostgreSQL + Qdrant + Neo4j for Data Storage

**Status**: Accepted

**Context**:
Need to store 50M+ patents with full-text search, semantic similarity, and graph relationships (assignees, inventors, topics).

**Decision**:
- **PostgreSQL**: Primary OLTP database for structured data (patents, assignees, inventors, CPC codes)
  - ACID guarantees
  - JSONB for flexible metadata (raw_data field)
  - Full-text search capabilities
  - Proven at scale (50M+ records)
  
- **Qdrant**: Vector database for semantic embeddings
  - Pure Rust, production-ready
  - Payload filtering (metadata filtering alongside similarity search)
  - Open-source alternative to Pinecone
  
- **Neo4j**: Graph database for relationships
  - Assignee → Patent → Inventor → CPC relationships
  - Quick traversals: "who invents for which companies in which topics"
  - Community detection for competitive clustering

**Alternatives Rejected**:
- Elasticsearch (not OLTP; overkill for structured data)
- Snowflake (proprietary; cost)
- Single Postgres with pg_vector (slower for high-dim vectors; not production-proven for our scale)

**Consequences**:
- Operational complexity: manage 3 databases
- Data consistency: must keep data in sync across systems
- Benefit: best-of-breed for each use case; no compromises

---

## ADR-002: Sentence-Transformers + BERTopic for NLP

**Status**: Accepted

**Context**:
Need embeddings and topic modeling on patent abstracts.

**Decision**:
- **Sentence-Transformers**: all-mpnet-base-v2 model
  - 768-dimensional embeddings
  - Pre-trained on semantic similarity
  - Fast inference (10K patents/min on CPU)
  
- **BERTopic**: Unsupervised topic modeling
  - Fast on-the-fly clustering
  - Stable topics (tested coherence)
  - Interpretable keywords per topic

**Alternatives Rejected**:
- OpenAI embeddings (API cost; latency; vendor lock-in)
- LDA (slower; lower quality embeddings)
- FastText (lower semantic quality)

---

## ADR-003: LangGraph for Agentic Report Generation

**Status**: Accepted

**Context**:
Need to orchestrate multi-step report generation with Claude LLM, human-in-the-loop gates, and reusable tools.

**Decision**:
- **LangGraph**: Structured workflow for agents
  - DAG execution (fetch evidence → analyze → generate → finalize)
  - Tool calling with typed inputs/outputs
  - State management for context persistence
  - Easy to add approval gates (block on APPROVE_REQUIRED state)
  
- **Claude 3.5 Sonnet**: LLM backbone
  - Cost-effective
  - Instruction-following (structured JSON output)
  - Fast inference

**Alternatives Rejected**:
- Simple prompt chaining (fragile; no reuse)
- AutoGPT (overkill; less control)
- Custom orchestration (maintenance burden)

---

## ADR-004: Kubeflow Pipelines for ML Orchestration

**Status**: Accepted

**Context**:
Need to run daily ingestion, weekly topic retraining, continuous embedding and novelty scoring at scale.

**Decision**:
- **Kubeflow Pipelines v2**: Kubernetes-native ML workflows
  - Component-based: reusable steps (ingest, validate, embed, topic, score)
  - Built-in caching (skip unchanged steps)
  - Native integration with Prometheus/Grafana
  - ArgoCD GitOps ready
  
- **Daily schedule**: Ingest → Validate → Embed → Score
- **Weekly schedule**: Topic model retraining
- **On-demand**: Manual novelty model retraining

**Alternatives Rejected**:
- Apache Airflow (not Kubernetes-native; more overhead)
- Prefect (less proven for k8s; API complexity)
- Jenkins (not designed for ML)

---

## ADR-005: Prometheus + Grafana + Loki + Tempo for Observability

**Status**: Accepted

**Context**:
Need to monitor data pipeline health, ML model performance, API latency, and debug production issues.

**Decision**:
- **Prometheus**: Metrics (ingestion lag, embedding coverage, API latency, model scores)
- **Grafana**: Dashboards and alerting
- **Loki**: Log aggregation (structured logging from all services)
- **Tempo**: Distributed tracing (OpenTelemetry)

**Metrics to track**:
- Data freshness: hours since last ingestion
- Embedding coverage: % patents with vectors
- Novelty score distribution: mean, stddev per week
- API latency: p50, p95, p99 per endpoint
- Alert precision: % alerts leading to decisions
- Model drift: KS statistic vs baseline

---

## ADR-006: Helm + Kustomize for Kubernetes Deployment

**Status**: Accepted

**Context**:
Need to deploy to dev, staging, prod with environment-specific configs.

**Decision**:
- **Helm**: Package management for core services
  - One Chart per service (api, agent, ui, monitoring)
  - Shared values-{env}.yaml for config per environment
  
- **Kustomize**: Overlays for environment-specific patches
  - Base manifests from Helm
  - Overlays for dev/staging/prod
  - Easy to sync with ArgoCD

**Alternatives Rejected**:
- Helm only (less flexible for overlays)
- Kustomize only (more verbose)

---

## ADR-007: Great Expectations for Data Validation

**Status**: Accepted

**Context**:
Need to catch data quality issues (schema, nullability, duplicates, value ranges) early in pipeline.

**Decision**:
- **Great Expectations**: Declarative suite definitions
  - Checkpoints: run on ingestion, before model training
  - Connectors to Postgres
  - Integration with Prometheus metrics
  - Human-readable reports

**Expectations**:
- Patents table: no nulls in patent_id, title, publication_date
- Assignees table: at least 1 assignee per patent
- Abstracts: max 5000 chars, no HTML tags
- Duplicates: 0 duplicate patent IDs

---

## ADR-008: Neo4j Community Edition (Not Enterprise)

**Status**: Accepted

**Context**:
Need relationship queries but budget-constrained.

**Decision**:
- **Community Edition**: Sufficient for single-node deployment
  - No clustering (acceptable for MVP/V1)
  - Full CYPHER query support
  - Free license
  
- **Upgrade path**: Switch to Enterprise if scaling beyond 1M nodes + 10M edges

---

## ADR-009: MinIO for S3-Compatible Object Storage

**Status**: Accepted

**Context**:
Need to store PDFs, embeddings blobs, model artifacts.

**Decision**:
- **MinIO**: Open-source, self-hosted S3 API
  - Drop-in replacement for AWS S3
  - Can scale to distributed setup later
  - Zero cost

**Alternatives Rejected**:
- AWS S3 (cost; vendor lock-in)
- Local filesystem (not scalable; no replication)

---

## ADR-010: Celery + Redis for Async Tasks

**Status**: Accepted

**Context**:
Email delivery, scheduled reports, long-running jobs should not block API.

**Decision**:
- **Celery**: Task queue with Redis backend
  - Distributed workers
  - Retries + dead-letter queue
  - Scheduled tasks (Celery Beat)
  
- **Redis**: In-memory message broker
  - Fast, simple
  - Optional persistence for dev

**Tasks**:
- send_watchlist_digest (daily, weekly per user)
- ingest_patents (daily)
- compute_embeddings (nightly)

---

## ADR-011: Anthropic Claude for LLM (Not OpenAI)

**Status**: Accepted

**Context**:
LangGraph agent needs to generate structured reports with accurate citations.

**Decision**:
- **Claude 3.5 Sonnet**: Better instruction following for structured output
  - Cheaper than GPT-4
  - Native JSON mode
  - Longer context (200K tokens)

**Alternatives Rejected**:
- GPT-4 (cost; slower)
- Local LLM (accuracy risk; latency)
- Gemini (less proven for instruction-following)

---

## ADR-012: Docker Compose for Local Dev, Helm for Prod

**Status**: Accepted

**Context**:
Developers need fast local setup; production needs robust orchestration.

**Decision**:
- **Docker Compose**: Single `docker-compose up` for all services locally
  - Zero configuration beyond .env
  - Mirrors prod services (Postgres, Qdrant, Neo4j, monitoring)
  
- **Helm**: Production k8s deployment
  - Version controlled
  - GitOps ready (ArgoCD)
  - Environment overrides via values files

**Upgrade path**: `docker-compose.yml` → Helm charts (one-time conversion)

