-- Patent + Innovation Radar: Core Schema
-- PostgreSQL 14+
-- Run with: psql -U postgres -d patent_radar -f schemas/patent_schema.sql

-- ============================================================================
-- PATENTS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS patents (
    patent_id TEXT PRIMARY KEY,
    publication_number TEXT UNIQUE NOT NULL,
    publication_date DATE NOT NULL,
    filing_date DATE NOT NULL,
    title TEXT NOT NULL,
    abstract TEXT,
    claims TEXT,
    num_claims INT,
    num_citations INT DEFAULT 0,
    
    -- CPC Classification
    primary_cpc_code TEXT,
    cpc_codes TEXT[],
    
    -- Patent Type
    is_utility BOOLEAN DEFAULT TRUE,
    patent_type TEXT DEFAULT 'utility',
    
    -- Enriched Fields
    num_co_inventors INT DEFAULT 0,
    num_assignees INT DEFAULT 0,
    first_assignee_id TEXT,
    
    -- Scoring Fields (populated by batch jobs)
    novelty_score REAL,
    novelty_score_version TEXT,
    novelty_scored_at TIMESTAMP,
    trend_acceleration REAL,
    
    -- Raw Data
    raw_data JSONB,
    
    -- Metadata
    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source TEXT DEFAULT 'patentsview',
    version INT DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_patents_filing_date ON patents(filing_date DESC);
CREATE INDEX IF NOT EXISTS idx_patents_publication_date ON patents(publication_date DESC);
CREATE INDEX IF NOT EXISTS idx_patents_primary_cpc ON patents(primary_cpc_code);
CREATE INDEX IF NOT EXISTS idx_patents_cpc_codes ON patents USING GIN (cpc_codes);
CREATE INDEX IF NOT EXISTS idx_patents_first_assignee ON patents(first_assignee_id);
CREATE INDEX IF NOT EXISTS idx_patents_ingested ON patents(ingested_at DESC);
CREATE INDEX IF NOT EXISTS idx_patents_title_gin ON patents USING GIN (to_tsvector('english', title));
CREATE INDEX IF NOT EXISTS idx_patents_abstract_gin ON patents USING GIN (to_tsvector('english', abstract));

-- ============================================================================
-- ASSIGNEES TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS assignees (
    assignee_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT,  -- 'company', 'individual', 'government'
    country TEXT,
    state TEXT,
    city TEXT,
    
    -- Patent Statistics
    num_patents INT DEFAULT 0,
    num_inventors INT DEFAULT 0,
    first_patent_date DATE,
    last_patent_date DATE,
    
    -- Topic Distribution (JSON for flexibility)
    topic_distribution JSONB,  -- {"topic_id": count, ...}
    cpc_distribution JSONB,    -- {"cpc_code": count, ...}
    recent_new_topics TEXT[],  -- Topics entered in last 90 days
    recent_new_cpcs TEXT[],
    
    -- Metadata
    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_updated_at TIMESTAMP,
    raw_data JSONB
);

CREATE INDEX IF NOT EXISTS idx_assignees_name ON assignees(name);
CREATE INDEX IF NOT EXISTS idx_assignees_country ON assignees(country);
CREATE INDEX IF NOT EXISTS idx_assignees_type ON assignees(type);
CREATE INDEX IF NOT EXISTS idx_assignees_last_patent ON assignees(last_patent_date DESC);

-- ============================================================================
-- INVENTORS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS inventors (
    inventor_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    num_patents INT DEFAULT 0,
    num_assignees INT DEFAULT 0,
    num_co_inventors INT DEFAULT 0,
    first_patent_date DATE,
    last_patent_date DATE,
    
    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_updated_at TIMESTAMP,
    raw_data JSONB
);

CREATE INDEX IF NOT EXISTS idx_inventors_name ON inventors(name);
CREATE INDEX IF NOT EXISTS idx_inventors_last_patent ON inventors(last_patent_date DESC);

-- ============================================================================
-- PATENT-ASSIGNEE JOIN (many-to-many)
-- ============================================================================
CREATE TABLE IF NOT EXISTS patent_assignees (
    patent_id TEXT NOT NULL,
    assignee_id TEXT NOT NULL,
    position INT,  -- Order in assignee list (0 = primary)
    PRIMARY KEY (patent_id, assignee_id),
    FOREIGN KEY (patent_id) REFERENCES patents(patent_id) ON DELETE CASCADE,
    FOREIGN KEY (assignee_id) REFERENCES assignees(assignee_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_patent_assignees_assignee ON patent_assignees(assignee_id);

-- ============================================================================
-- PATENT-INVENTOR JOIN (many-to-many)
-- ============================================================================
CREATE TABLE IF NOT EXISTS patent_inventors (
    patent_id TEXT NOT NULL,
    inventor_id TEXT NOT NULL,
    position INT,  -- Order in inventor list
    PRIMARY KEY (patent_id, inventor_id),
    FOREIGN KEY (patent_id) REFERENCES patents(patent_id) ON DELETE CASCADE,
    FOREIGN KEY (inventor_id) REFERENCES inventors(inventor_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_patent_inventors_inventor ON patent_inventors(inventor_id);

-- ============================================================================
-- CPC CODES TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS cpc_codes (
    cpc_code TEXT PRIMARY KEY,
    title TEXT,
    description TEXT,
    parent_code TEXT,
    
    -- Statistics
    num_patents INT DEFAULT 0,
    num_recent_patents INT DEFAULT 0,  -- Last 90 days
    trend_velocity REAL,  -- Weekly growth rate
    trend_acceleration REAL,  -- Z-score
    
    -- Topic Co-occurrence
    dominant_topics TEXT[],
    
    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_updated_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_cpc_codes_trend ON cpc_codes(trend_acceleration DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_cpc_codes_parent ON cpc_codes(parent_code);

-- ============================================================================
-- CITATIONS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS citations (
    citation_id BIGSERIAL PRIMARY KEY,
    citing_patent_id TEXT NOT NULL,
    cited_patent_id TEXT NOT NULL,
    citation_date DATE,
    FOREIGN KEY (citing_patent_id) REFERENCES patents(patent_id) ON DELETE CASCADE,
    FOREIGN KEY (cited_patent_id) REFERENCES patents(patent_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_citations_citing ON citations(citing_patent_id);
CREATE INDEX IF NOT EXISTS idx_citations_cited ON citations(cited_patent_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_citations_pair ON citations(citing_patent_id, cited_patent_id);

-- ============================================================================
-- EMBEDDINGS METADATA TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS embeddings (
    patent_id TEXT PRIMARY KEY,
    embedding_model_id TEXT NOT NULL,
    embedding_model_version TEXT,
    embedding_dim INT,
    qdrant_id TEXT UNIQUE,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    FOREIGN KEY (patent_id) REFERENCES patents(patent_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_embeddings_model ON embeddings(embedding_model_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_qdrant ON embeddings(qdrant_id);

-- ============================================================================
-- TOPICS TABLE (BERTopic)
-- ============================================================================
CREATE TABLE IF NOT EXISTS topics (
    topic_id INT PRIMARY KEY,
    name TEXT,
    description TEXT,
    label TEXT,
    
    -- Statistics
    num_patents INT DEFAULT 0,
    representative_patents TEXT[],  -- Top 5 patent IDs
    top_keywords TEXT[],  -- Top 15 keywords
    
    -- Quality Metrics
    coherence_score REAL,
    topic_stability REAL,
    
    -- Versioning
    model_version TEXT NOT NULL,
    model_trained_at TIMESTAMP,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_topics_model ON topics(model_version);
CREATE INDEX IF NOT EXISTS idx_topics_num_patents ON topics(num_patents DESC);

-- ============================================================================
-- TOPIC ASSIGNMENTS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS topic_assignments (
    patent_id TEXT NOT NULL,
    topic_id INT NOT NULL,
    probability REAL NOT NULL,  -- 0-1
    PRIMARY KEY (patent_id, topic_id),
    FOREIGN KEY (patent_id) REFERENCES patents(patent_id) ON DELETE CASCADE,
    FOREIGN KEY (topic_id) REFERENCES topics(topic_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_topic_assignments_topic ON topic_assignments(topic_id);
CREATE INDEX IF NOT EXISTS idx_topic_assignments_patent ON topic_assignments(patent_id);
CREATE INDEX IF NOT EXISTS idx_topic_assignments_prob ON topic_assignments(probability DESC);

-- ============================================================================
-- WATCHLISTS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS watchlists (
    watchlist_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    
    -- Criteria
    assignee_ids TEXT[],
    cpc_codes TEXT[],
    topic_ids INT[],
    keywords TEXT[],
    
    -- Alert Settings
    alert_threshold_z_score REAL DEFAULT 2.0,
    alert_threshold_confidence REAL DEFAULT 0.75,
    digest_frequency TEXT DEFAULT 'weekly',  -- 'daily', 'weekly'
    email_addresses TEXT[],
    
    -- Metadata
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    last_alert_sent_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_watchlists_user ON watchlists(user_id);
CREATE INDEX IF NOT EXISTS idx_watchlists_active ON watchlists(is_active) WHERE is_active = TRUE;

-- ============================================================================
-- ALERTS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS alerts (
    alert_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    watchlist_id UUID NOT NULL,
    
    alert_type TEXT NOT NULL,  -- 'material_change', 'new_trend', 'competitor_move', 'novelty_spike'
    triggered_on TEXT,  -- 'assignee_id', 'cpc_code', 'topic_id', 'keyword'
    triggered_value TEXT,  -- The actual value (assignee ID, CPC code, etc.)
    
    -- Metrics
    metric_value REAL,  -- Z-score, count, etc.
    confidence REAL,  -- 0-1
    description TEXT,
    
    -- Evidence
    evidence_patents TEXT[],  -- patent IDs
    evidence_details JSONB,  -- Rich metadata
    
    -- Status
    status TEXT DEFAULT 'active',  -- 'active', 'acknowledged', 'dismissed'
    is_delivered BOOLEAN DEFAULT FALSE,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    delivered_at TIMESTAMP,
    acknowledged_at TIMESTAMP,
    
    FOREIGN KEY (watchlist_id) REFERENCES watchlists(watchlist_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_alerts_watchlist ON alerts(watchlist_id);
CREATE INDEX IF NOT EXISTS idx_alerts_created ON alerts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);
CREATE INDEX IF NOT EXISTS idx_alerts_type ON alerts(alert_type);

-- ============================================================================
-- REPORTS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS reports (
    report_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT,
    watchlist_id UUID,
    
    report_type TEXT NOT NULL,  -- 'weekly_brief', 'deep_dive', 'incident'
    title TEXT NOT NULL,
    executive_summary TEXT,
    
    -- Structured Content
    emerging_topics JSONB,  -- [{topic_id, name, growth_rate, novel_patents}, ...]
    key_patents JSONB,      -- [{patent_id, title, novelty, reason}, ...]
    competitor_moves JSONB, -- [{assignee, new_topic, new_cpc, confidence}, ...]
    watchlist_changes JSONB,
    
    -- Evidence & Methodology
    evidence_patents TEXT[],
    evidence_queries TEXT[],
    methodology_notes TEXT,
    
    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    delivered_at TIMESTAMP,
    version INT DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_reports_user ON reports(user_id);
CREATE INDEX IF NOT EXISTS idx_reports_created ON reports(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_reports_type ON reports(report_type);

-- ============================================================================
-- INGESTION TRACKING TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS ingestion_log (
    ingestion_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT NOT NULL,  -- 'patentsview_api', 'bulk_load', 'manual'
    status TEXT,  -- 'started', 'success', 'failed'
    
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    
    num_patents_processed INT,
    num_patents_inserted INT,
    num_patents_updated INT,
    num_errors INT,
    
    error_details TEXT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ingestion_log_source ON ingestion_log(source);
CREATE INDEX IF NOT EXISTS idx_ingestion_log_created ON ingestion_log(created_at DESC);

-- ============================================================================
-- MODEL VERSIONING TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS model_versions (
    model_version_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_type TEXT NOT NULL,  -- 'embedding', 'topic', 'novelty'
    model_name TEXT,
    version_string TEXT,
    
    -- Metadata
    trained_at TIMESTAMP,
    promoted_to_prod_at TIMESTAMP,
    metrics JSONB,  -- {accuracy, f1, coherence, etc.}
    
    hyperparameters JSONB,
    training_config JSONB,
    
    artifact_path TEXT,  -- Path in MLflow or object store
    
    is_active BOOLEAN DEFAULT FALSE,
    notes TEXT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_model_versions_type ON model_versions(model_type);
CREATE INDEX IF NOT EXISTS idx_model_versions_active ON model_versions(is_active);
