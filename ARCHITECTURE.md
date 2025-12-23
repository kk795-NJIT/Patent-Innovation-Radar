# Patent + Innovation Radar: System Architecture & Data Model

## 1. High-Level Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          EXTERNAL SOURCES                                   │
│  PatentsView API (daily delta)  |  PatentsView Bulk (backfill)             │
└──────────────────────┬──────────────────────┬─────────────────────────────┘
                       │                      │
                       v                      v
┌─────────────────────────────────────────────────────────────────────────────┐
│  DATA INGESTION LAYER                                                       │
│  ├─ PatentsView API Client (rate-limited, incremental)                     │
│  ├─ Bulk Loader (validate, transform, load to raw zone)                    │
│  └─ Great Expectations (schema, nullability, duplicate checks)             │
└──────────────────┬──────────────────────────────────────────────────────────┘
                   │
                   v
┌─────────────────────────────────────────────────────────────────────────────┐
│  DATA LAKE (Postgres + MinIO)                                              │
│  ├─ Raw Zone: patents_raw, assignees_raw, inventors_raw, cpc_raw, ...      │
│  └─ Curated Zone: patents, assignees, inventors, cpc, citations, ...       │
│                   (cleaned, deduplicated, enriched)                         │
│                   (MinIO: PDF docs, metadata blobs)                         │
└──────────────────┬──────────────────────────────────────────────────────────┘
                   │
        ┌──────────┼──────────┐
        v          v          v
    PIPELINE 1 PIPELINE 2 PIPELINE 3
        │          │          │
    ┌───────────┬──────────┬──────────┐
    │ Feature  │Embeddings│ Topics  │
    │ Store    │ Service  │ Service │
    │ (Feast)  │ (Qdrant) │(BERTopic)
    └───────┬──────┬──────┬──────────┘
            │      │      │
        ┌───v──────v──────v─────┐
        │   ML MODELS LAYER     │
        ├─ Novelty Ranking      │
        ├─ Trend Acceleration   │
        └─ Competitive Moves    │
            (MLflow registry)
            │
            v
    ┌──────────────────────┐
    │ Batch Scoring Job    │
    │ (weekly/daily)       │
    └──────────┬───────────┘
              │
    ┌─────────v──────────┐
    │ SERVING LAYER      │
    ├─ KServe inference  │
    ├─ FastAPI endpoints │
    └────────┬───────────┘
             │
    ┌────────v──────────┐
    │ APPLICATIONS       │
    ├─ Search API       │
    ├─ Semantic Search  │
    ├─ Watchlists/Alerts
    ├─ Weekly Report    │
    │  (LangGraph Agent) │
    └─ Streamlit UI     │
```

---

## 2. Data Model & Schema

### Core Entity Diagram

```
            ┌─────────────────┐
            │   Patents       │
            └────────┬────────┘
                     │ cites
                     ├─> Citations
                     │
                     ├─ assigned_to ──> ┌──────────────┐
                     │                  │  Assignees   │
                     ├─ co-inventors ──>│  (Companies) │
                     │                  └──────────────┘
                     │
                     ├─ invented_by ──> ┌──────────────┐
                     │                  │  Inventors   │
                     │                  │  (People)    │
                     │                  └──────────────┘
                     │
                     ├─ classified_by──>┌──────────────┐
                     │                  │ CPC Codes    │
                     │                  │ (Taxonomy)   │
                     │                  └──────────────┘
                     │
                     ├─ embedded_in ──> ┌──────────────┐
                     │                  │  Embeddings  │
                     │                  │  (Qdrant)    │
                     │                  └──────────────┘
                     │
                     └─ belongs_to ───> ┌──────────────┐
                                        │   Topics     │
                                        │  (BERTopic)  │
                                        └──────────────┘
```

### Detailed Schema

#### Table: patents
```sql
CREATE TABLE patents (
    patent_id TEXT PRIMARY KEY,              -- USPTO ID (e.g., 10000000)
    publication_date DATE NOT NULL,
    filing_date DATE NOT NULL,
    title TEXT NOT NULL,
    abstract TEXT,
    claims TEXT,
    num_claims INT,
    num_citations INT,
    primary_cpc_code TEXT,
    publication_number TEXT UNIQUE,
    
    -- Enriched fields
    num_co_inventors INT,
    num_assignees INT,
    is_utility BOOLEAN,
    
    -- Novelty & Scoring (populated by batch jobs)
    novelty_score FLOAT,                    -- 0-100
    novelty_score_version TEXT,             -- model version
    trend_acceleration FLOAT,                -- z-score of topic filing rate
    
    -- Metadata
    raw_data JSONB,                         -- full original data
    ingested_at TIMESTAMP DEFAULT NOW(),
    last_scored_at TIMESTAMP,
    version INT DEFAULT 1
);

CREATE INDEX idx_patents_filing_date ON patents(filing_date DESC);
CREATE INDEX idx_patents_publication_date ON patents(publication_date DESC);
CREATE INDEX idx_patents_primary_cpc ON patents(primary_cpc_code);
```

#### Table: assignees
```sql
CREATE TABLE assignees (
    assignee_id TEXT PRIMARY KEY,           -- PatentsView assignee_id
    name TEXT NOT NULL,
    type TEXT,                              -- e.g., 'Company', 'Individual'
    country TEXT,
    state TEXT,
    city TEXT,
    
    -- Graph fields
    num_patents INT DEFAULT 0,
    num_inventors INT DEFAULT 0,
    first_patent_date DATE,
    last_patent_date DATE,
    
    -- Competitive intelligence
    topic_distribution JSONB,               -- {topic_id: count, ...}
    cpc_distribution JSONB,                 -- {cpc_code: count, ...}
    recent_new_topics TEXT[],               -- Topics entered in last 90 days
    recent_new_cpcs TEXT[],
    
    ingested_at TIMESTAMP DEFAULT NOW(),
    last_updated TIMESTAMP
);

CREATE INDEX idx_assignees_name ON assignees(name);
CREATE INDEX idx_assignees_country ON assignees(country);
```

#### Table: inventors
```sql
CREATE TABLE inventors (
    inventor_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    num_patents INT,
    num_assignees INT,
    first_patent_date DATE,
    last_patent_date DATE,
    raw_data JSONB,
    ingested_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_inventors_name ON inventors(name);
```

#### Table: cpc_codes
```sql
CREATE TABLE cpc_codes (
    cpc_code TEXT PRIMARY KEY,              -- e.g., 'H01L'
    title TEXT,
    num_patents INT,
    num_recent_patents INT,                 -- last 90 days
    trend_velocity FLOAT,                   -- weekly growth rate
    trend_acceleration FLOAT,                -- z-score
    parent_code TEXT,                       -- hierarchy
    
    -- Topic co-occurrence
    dominant_topics TEXT[],                 -- top 3 topics
    
    ingested_at TIMESTAMP DEFAULT NOW(),
    last_updated TIMESTAMP
);

CREATE INDEX idx_cpc_codes_trend ON cpc_codes(trend_acceleration DESC);
```

#### Table: citations
```sql
CREATE TABLE citations (
    citation_id SERIAL PRIMARY KEY,
    citing_patent_id TEXT NOT NULL,
    cited_patent_id TEXT NOT NULL,
    citation_date DATE,
    FOREIGN KEY (citing_patent_id) REFERENCES patents(patent_id),
    FOREIGN KEY (cited_patent_id) REFERENCES patents(patent_id)
);

CREATE INDEX idx_citations_citing ON citations(citing_patent_id);
CREATE INDEX idx_citations_cited ON citations(cited_patent_id);
```

#### Table: embeddings
```sql
-- Metadata only; vectors stored in Qdrant
CREATE TABLE embeddings (
    patent_id TEXT PRIMARY KEY,
    embedding_model_id TEXT NOT NULL,       -- e.g., 'sentence-transformers/all-mpnet-base-v2'
    embedding_dim INT,
    qdrant_id TEXT UNIQUE,                  -- Qdrant point ID
    created_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (patent_id) REFERENCES patents(patent_id)
);

CREATE INDEX idx_embeddings_model ON embeddings(embedding_model_id);
```

#### Table: topics
```sql
CREATE TABLE topics (
    topic_id INT PRIMARY KEY,               -- BERTopic ID
    name TEXT,                              -- topic label
    description TEXT,
    num_patents INT,
    representative_patents TEXT[],          -- top 5 patent IDs
    top_keywords TEXT[],                    -- top 10 keywords
    coherence_score FLOAT,                  -- BERTopic coherence
    model_version TEXT,                     -- topic model version
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

#### Table: topic_assignments
```sql
CREATE TABLE topic_assignments (
    patent_id TEXT NOT NULL,
    topic_id INT NOT NULL,
    probability FLOAT,                      -- 0-1, confidence
    PRIMARY KEY (patent_id, topic_id),
    FOREIGN KEY (patent_id) REFERENCES patents(patent_id),
    FOREIGN KEY (topic_id) REFERENCES topics(topic_id)
);

CREATE INDEX idx_topic_assignments_topic ON topic_assignments(topic_id);
CREATE INDEX idx_topic_assignments_patent ON topic_assignments(patent_id);
```

#### Table: watchlists
```sql
CREATE TABLE watchlists (
    watchlist_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    name TEXT,
    
    -- Watchlist criteria
    assignee_ids TEXT[],
    cpc_codes TEXT[],
    topics INT[],
    keywords TEXT[],
    
    -- Alert settings
    alert_threshold_z_score FLOAT DEFAULT 2.0,
    alert_threshold_confidence FLOAT DEFAULT 0.75,
    digest_frequency TEXT DEFAULT 'WEEKLY',  -- DAILY, WEEKLY
    
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);
```

#### Table: alerts
```sql
CREATE TABLE alerts (
    alert_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    watchlist_id UUID NOT NULL,
    alert_type TEXT,                        -- 'MATERIAL_CHANGE', 'NEW_TREND', 'COMPETITOR_MOVE'
    
    triggered_on TEXT,                      -- 'assignee_id' | 'cpc_code' | 'topic_id'
    triggered_value TEXT,
    
    metric_value FLOAT,                     -- e.g., z-score
    confidence FLOAT,                       -- 0-1
    
    description TEXT,
    evidence_patents TEXT[],                -- patent IDs
    
    status TEXT DEFAULT 'ACTIVE',           -- ACTIVE, ACKNOWLEDGED, DISMISSED
    created_at TIMESTAMP DEFAULT NOW(),
    delivered_at TIMESTAMP,
    FOREIGN KEY (watchlist_id) REFERENCES watchlists(watchlist_id)
);

CREATE INDEX idx_alerts_watchlist ON alerts(watchlist_id);
CREATE INDEX idx_alerts_created ON alerts(created_at DESC);
```

#### Table: reports
```sql
CREATE TABLE reports (
    report_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT,
    watchlist_id UUID,
    report_type TEXT,                       -- 'WEEKLY_BRIEF', 'DEEP_DIVE', 'INCIDENT'
    
    title TEXT,
    executive_summary TEXT,
    
    -- Structured content
    emerging_topics JSONB,                  -- [{topic_id, name, growth_rate, novel_patents}, ...]
    key_patents JSONB,                      -- [{patent_id, title, novelty, reason}, ...]
    competitor_moves JSONB,                 -- [{assignee, new_topic, new_cpc, confidence}, ...]
    watchlist_changes JSONB,
    
    -- Evidence & links
    evidence_patents TEXT[],
    evidence_queries TEXT[],                -- queries used to generate report
    
    created_at TIMESTAMP DEFAULT NOW(),
    delivered_at TIMESTAMP,
    version INT DEFAULT 1
);

CREATE INDEX idx_reports_user ON reports(user_id);
CREATE INDEX idx_reports_created ON reports(created_at DESC);
```

---

## 3. Storage Technology Decisions

| Component | Technology | Justification |
|-----------|-----------|-------------------|
| **Primary OLTP** | PostgreSQL 14+ | ACID guarantees, JSON support (JSONB), strong indexing, open-source. Handles 50M patents + metadata efficiently. |
| **Vector Store** | Qdrant (self-hosted) | Open-source, pure Rust, excellent filtering (payload filtering on metadata), production-grade. Alternative: Milvus. |
| **Graph Database** | Neo4j (Community Edition) | Powerful graph queries (assignee networks, co-inventor graphs), visual exploration, schema-flexible property graphs. Handles millions of nodes/edges. |
| **Object Storage** | MinIO (self-hosted S3 API) | Open-source, fully compatible with S3 ecosystem, single-node or distributed. Store PDFs, embeddings blobs. |
| **Feature Store** | Feast (lightweight) | Open-source, integrates with Postgres + Qdrant, online + offline feature serving, supports versioning. |
| **Metrics/Time-Series** | Postgres + Prometheus | Postgres for historical rollups; Prometheus for real-time system metrics (ingestion lag, model latency, etc.). |
| **OLAP (V2 upgrade)** | ClickHouse (optional) | Ultra-fast aggregations on large patent tables. Useful for dashboards querying billions of rows. Skip for MVP. |

### Why NOT these:

- **Snowflake**: Paid. Not required for this workload; Postgres + Clickhouse handle it.
- **Elasticsearch**: Overkill for structured patent data; Postgres full-text search + Qdrant covers needs.
- **Cassandra**: Not needed; no write-heavy time-series at extreme scale.

---

## 4. Deployment Topology

### Local Development (Docker Compose)
```
docker-compose up -d

Services:
  postgres (port 5432)
  redis (port 6379)
  minio (port 9000)
  qdrant (port 6333)
  neo4j (port 7474, 7687)
  
  api (FastAPI, port 8000)
  agent (LangGraph worker, runs on schedule)
  ui (Streamlit, port 8501)
  
  prometheus (port 9090)
  grafana (port 3000)
  loki (port 3100)
  tempo (port 3200)
```

### Kubernetes (Helm/Kustomize)
```
Namespaces:
  - prod (core services)
  - staging (pre-release)
  - monitoring (Prometheus, Grafana, Loki, Tempo)
  - kubeflow (ML pipelines)

StatefulSets:
  - postgres-primary + postgres-replica
  - qdrant
  - neo4j-primary
  - minio

Deployments:
  - api (HPA: 2-20 replicas based on CPU)
  - agent-scheduler (single pod + Kubeflow jobs)
  - ui

ConfigMaps:
  - pipeline-config
  - model-config
  - alert-rules

Secrets:
  - patentsview-api-key
  - mlflow-creds
  - database-creds
```

---

## 5. Data Flow: Example Ingestion → Serving

**Timeline: Monday 2 AM – Tuesday 2 AM**

1. **02:00 – Trigger Ingestion**
   - Cron job: `GET /patents?since=2024-12-16`
   - Batch: ~7000 patents from PatentsView API
   
2. **02:30 – Validate + Load to Raw**
   - Great Expectations: schema, nullability, duplicates
   - Insert to `patents_raw`, `assignees_raw`, etc.
   
3. **03:00 – Curate**
   - Deduplicate on patent_id
   - Enrich with CPC hierarchy
   - Update `patents`, `assignees`, `cpc_codes` tables
   - Mark raw records as processed
   
4. **03:30 – Feature Engineering (Feast)**
   - Compute rolling statistics: 7d, 30d, 90d patent counts per assignee/CPC
   - Compute topic prevalence: # patents per topic per assignee
   - Feast `materialize` online + offline stores
   
5. **04:00 – Embeddings**
   - Fetch new patents from `patents` where `embedding_id IS NULL`
   - Batch inference via embedding service (8 GPUs, throughput ~10k patents/min)
   - Store vectors in Qdrant + metadata in `embeddings` table
   
6. **05:00 – Topic Modeling** (Nightly, skip if no new patents)
   - Fetch all patents from `patents`
   - Re-fit BERTopic on 50k most recent + random 50k historical
   - Evaluate coherence; if improved, promote model in MLflow
   - Update `topic_assignments` table
   
7. **06:00 – Novelty Scoring**
   - Fetch new patents + recent re-topics
   - For each: compute embedding distance to 50 nearest neighbors (Qdrant)
   - Fetch LightGBM novelty model from KServe
   - Score; write to `patents.novelty_score`
   
8. **07:00 – Trend Acceleration**
   - For each CPC code: compute z-score of weekly filing count
   - For each topic: compute z-score of weekly filing count
   - Flag if z > 2.0 (configurable)
   - Insert accelerating topics to `alerts` table if > threshold
   
9. **08:00 – Publish Metrics**
   - Write to Prometheus:
     - `patent_ingestion_lag_hours`
     - `embeddings_produced_count`
     - `novelty_score_mean`
     - `trend_accelerations_detected`
     - `api_request_latency_p95`
   
10. **18:00 – Weekly Report (Every Monday)**
    - Agent: fetch data for each user watchlist
    - Identify top 5 emerging topics, top 10 novel patents, competitor moves
    - Generate markdown report
    - Email + store in `reports` table

---

## 6. API Surface Preview

```python
# Search
GET /patents/search?q=quantum&offset=0&limit=10
  Returns: [PatentSchema]

# Semantic Search
POST /patents/semantic-search
  Body: { "query": "quantum error correction", "limit": 10 }
  Returns: [PatentSchema with similarity_score]

# Topics
GET /topics/{topic_id}
  Returns: Topic + top patents + trend chart
GET /topics?search=quantum
  Returns: [TopicSchema]

# Trends
GET /trends?period_days=90
  Returns: [TopicTrendSchema] sorted by acceleration DESC

# Watchlists
POST /watchlists
GET /watchlists/{watchlist_id}
PUT /watchlists/{watchlist_id}
DELETE /watchlists/{watchlist_id}

# Alerts
GET /watchlists/{watchlist_id}/alerts
PATCH /alerts/{alert_id} (acknowledge/dismiss)

# Reports
GET /reports/{report_id}
GET /reports?user_id=...&from_date=...&to_date=...

# KServe (inference)
POST /v1/models/embedding-model:predict
  Body: { "instances": [{"text": "..."}, ...] }
  Returns: [embedding_vectors]

POST /v1/models/novelty-model:predict
  Body: { "instances": [{"embedding": [...], "cpc_code": "H01L", ...}, ...] }
  Returns: [novelty_scores]
```

